"""Effe ECC Sauna — sensor entities.

Temperature sensors in this integration reflect values from the device's internal
probes, which are NOT suitable for measuring actual cabin temperature:

- Probe Temperature (byte[9]): near the heating element. Reads ~32°C (ambient
  electronics) for the first 20–30 min, then jumps abruptly to ~97°C. Useful to
  detect whether the element has reached operating temperature.

- Heater Temperature (byte[11]): heating element / stones probe. Stable around
  96–99°C when the sauna is active.

- Setpoint (byte[20]): the target temperature set via the physical dial on the device.
  Reliable but not independently calibrated.

For actual cabin air temperature, use an external sensor placed inside the cabin
(e.g. a Ruuvi Tag or similar Bluetooth thermometer).
"""
from __future__ import annotations

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import DOMAIN, SaunaCoordinator


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: SaunaCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([
        SaunaTemperatureSensor(coordinator, entry),
        SaunaHeaterTempSensor(coordinator, entry),
        SaunaSetpointSensor(coordinator, entry),
    ])


class SaunaTemperatureSensor(CoordinatorEntity[SaunaCoordinator], SensorEntity):
    """Device internal probe near the heating element.

    Reads ambient electronics temperature (~32°C) for the first 20–30 min after
    power-on, then jumps to ~97°C once the element heats the probe physically.
    This is NOT cabin air temperature.
    """

    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_has_entity_name = True
    _attr_name = "Probe Temperature"
    _attr_icon = "mdi:thermometer"

    def __init__(self, coordinator: SaunaCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_temperature"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": "Effe ECC Sauna",
            "manufacturer": "Effe Perfect Wellness",
            "model": "ECC",
        }

    @property
    def native_value(self) -> float | None:
        return self.coordinator.data.temperature

    @property
    def available(self) -> bool:
        return self.coordinator.data.available and self.coordinator.data.temperature is not None


class SaunaHeaterTempSensor(CoordinatorEntity[SaunaCoordinator], SensorEntity):
    """Heating element / stones temperature probe.

    Slow-changing sensor, typically 96–99°C when the sauna is active.
    Not calibrated; intended as a relative indicator only.
    """

    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_has_entity_name = True
    _attr_name = "Heater Temperature"
    _attr_icon = "mdi:thermometer-high"

    def __init__(self, coordinator: SaunaCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_heater_temp"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": "Effe ECC Sauna",
            "manufacturer": "Effe Perfect Wellness",
            "model": "ECC",
        }

    @property
    def native_value(self) -> float | None:
        return self.coordinator.data.heater_temp

    @property
    def available(self) -> bool:
        return self.coordinator.data.available and self.coordinator.data.heater_temp is not None


class SaunaSetpointSensor(CoordinatorEntity[SaunaCoordinator], SensorEntity):
    """Target temperature set via the physical dial on the device.

    This value is stable and reflects the dial position. It is not independently
    calibrated but is reliably read from the protocol (byte[20] ÷ 2°C).
    """

    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_has_entity_name = True
    _attr_name = "Setpoint"
    _attr_icon = "mdi:thermometer-chevron-up"

    def __init__(self, coordinator: SaunaCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_setpoint"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": "Effe ECC Sauna",
            "manufacturer": "Effe Perfect Wellness",
            "model": "ECC",
        }

    @property
    def native_value(self) -> float | None:
        return self.coordinator.data.setpoint

    @property
    def available(self) -> bool:
        return self.coordinator.data.available and self.coordinator.data.setpoint is not None
