"""Effe ECC Sauna — sensor entities."""
from __future__ import annotations

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTemperature
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
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


class _SaunaTempBase(CoordinatorEntity[SaunaCoordinator], SensorEntity, RestoreEntity):
    """Common base. Caches the last good reading in `_handle_coordinator_update`
    so that `available` and `native_value` stay consistent (avoiding the
    chicken-and-egg where `available` reads `_last_value` but only `native_value`
    populated it, and HA skips `native_value` when `available=False`).
    Also restores the last value across HA restarts via RestoreEntity, so the
    sensor stays available immediately after a restart while the first poll
    is in flight."""

    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_has_entity_name = True

    _field: str = ""  # overridden by subclass

    def __init__(self, coordinator: SaunaCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": "Effe ECC Sauna",
            "manufacturer": "Effe Perfect Wellness",
            "model": "ECC",
        }
        self._last_value: float | None = None

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state is not None and last_state.state not in ("unavailable", "unknown"):
            try:
                self._last_value = float(last_state.state)
            except (ValueError, TypeError):
                pass

    @callback
    def _handle_coordinator_update(self) -> None:
        v = getattr(self.coordinator.data, self._field, None)
        if v is not None:
            self._last_value = v
        super()._handle_coordinator_update()

    @property
    def native_value(self) -> float | None:
        return self._last_value

    @property
    def available(self) -> bool:
        return self._last_value is not None and self.coordinator.no_data_streak < NO_DATA_THRESHOLD


class SaunaTemperatureSensor(_SaunaTempBase):
    _attr_name = "Temperatura Sauna"
    _attr_icon = "mdi:thermometer"
    _field = "temperature"

    def __init__(self, coordinator: SaunaCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_temperature"


class SaunaHeaterTempSensor(_SaunaTempBase):
    _attr_name = "Temperatura Resistenza Sauna"
    _attr_icon = "mdi:thermometer-high"
    _field = "heater_temp"

    def __init__(self, coordinator: SaunaCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_heater_temp"


class SaunaSetpointSensor(_SaunaTempBase):
    _attr_name = "Temperatura Impostata Sauna"
    _attr_icon = "mdi:thermometer-chevron-up"
    _field = "setpoint"

    def __init__(self, coordinator: SaunaCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_setpoint"
