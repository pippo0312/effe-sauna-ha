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
        SaunaTemperatureSensor(coordinator, entry),
        SaunaHeaterTempSensor(coordinator, entry),
        SaunaSetpointSensor(coordinator, entry),
    ])


class SaunaTemperatureSensor(CoordinatorEntity[SaunaCoordinator], SensorEntity):
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_has_entity_name = True
    _attr_name = "Temperatura Sauna"
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
        self._last_value: float | None = None

    @property
    def native_value(self) -> float | None:
        v = self.coordinator.data.temperature
        if v is not None:
            self._last_value = v
        return self._last_value

    @property
    def available(self) -> bool:
        return self._last_value is not None and self.coordinator.no_data_streak < NO_DATA_THRESHOLD


class SaunaHeaterTempSensor(CoordinatorEntity[SaunaCoordinator], SensorEntity):
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_has_entity_name = True
    _attr_name = "Temperatura Resistenza Sauna"
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
        self._last_value: float | None = None

    @property
    def native_value(self) -> float | None:
        v = self.coordinator.data.heater_temp
        if v is not None:
            self._last_value = v
        return self._last_value

    @property
    def available(self) -> bool:
        return self._last_value is not None and self.coordinator.no_data_streak < NO_DATA_THRESHOLD


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
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": "Effe ECC Sauna",
            "manufacturer": "Effe Perfect Wellness",
            "model": "ECC",
        }
        self._last_value: float | None = None

    @property
    def native_value(self) -> float | None:
        v = self.coordinator.data.setpoint
        if v is not None:
            self._last_value = v
        return self._last_value

    @property
    def available(self) -> bool:
        return self._last_value is not None and self.coordinator.no_data_streak < NO_DATA_THRESHOLD
