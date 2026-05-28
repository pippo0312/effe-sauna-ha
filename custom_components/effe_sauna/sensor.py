"""Effe ECC Sauna — sensor entities."""
from __future__ import annotations

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import DOMAIN, NO_DATA_THRESHOLD, SaunaCoordinator


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: SaunaCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([
        SaunaHeaterRawSensor(coordinator, entry),
        SaunaSetpointSensor(coordinator, entry),
    ])


def _device_info(entry_id: str) -> dict:
    return {
        "identifiers": {(DOMAIN, entry_id)},
        "name": "Effe ECC Sauna",
        "manufacturer": "Effe Perfect Wellness",
        "model": "ECC",
    }


class SaunaHeaterRawSensor(CoordinatorEntity[SaunaCoordinator], SensorEntity):
    """Raw value of the controller's internal probe (byte[11]).

    NOT a linear Celsius reading — the firmware exposes the raw NTC sensor
    value, not a calibrated temperature. Use an external thermometer (e.g.
    Ruuvi Tag) for accurate cabin temperature.
    """
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_has_entity_name = True
    _attr_name = "Sonda Sauna (raw)"
    _attr_icon = "mdi:thermometer-alert"
    _attr_entity_registry_enabled_default = True

    def __init__(self, coordinator: SaunaCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_heater_raw"
        self._attr_device_info = _device_info(entry.entry_id)

    @property
    def native_value(self) -> int | None:
        return self.coordinator.data.heater_raw if self.coordinator.data else None

    @property
    def available(self) -> bool:
        return (
            self.coordinator.data is not None
            and self.coordinator.data.heater_raw is not None
            and self.coordinator.no_data_streak < NO_DATA_THRESHOLD
        )


class SaunaSetpointSensor(CoordinatorEntity[SaunaCoordinator], SensorEntity):
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_has_entity_name = True
    _attr_name = "Temperatura Impostata Sauna"
    _attr_icon = "mdi:thermometer-chevron-up"

    def __init__(self, coordinator: SaunaCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_setpoint"
        self._attr_device_info = _device_info(entry.entry_id)

    @property
    def native_value(self) -> float | None:
        return self.coordinator.data.setpoint if self.coordinator.data else None

    @property
    def available(self) -> bool:
        return (
            self.coordinator.data is not None
            and self.coordinator.data.setpoint is not None
            and self.coordinator.no_data_streak < NO_DATA_THRESHOLD
        )
