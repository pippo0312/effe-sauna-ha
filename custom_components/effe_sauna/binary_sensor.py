"""Effe ECC Sauna — binary sensors."""
from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import DOMAIN, NO_DATA_THRESHOLD, SaunaCoordinator, device_info


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: SaunaCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([
        SaunaReadySensor(coordinator, entry),
        SaunaDomoticSensor(coordinator, entry),
    ])


class _SaunaBinary(CoordinatorEntity[SaunaCoordinator], BinarySensorEntity):
    _attr_has_entity_name = True
    _key: str
    _field: str

    def __init__(self, coordinator: SaunaCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_{self._key}"
        self._attr_device_info = device_info(coordinator)

    @property
    def available(self) -> bool:
        d = self.coordinator.data
        return (
            d is not None
            and getattr(d, self._field) is not None
            and self.coordinator.no_data_streak < NO_DATA_THRESHOLD
        )

    @property
    def is_on(self) -> bool | None:
        d = self.coordinator.data
        return getattr(d, self._field) if d else None


class SaunaReadySensor(_SaunaBinary):
    """STATE DATA[5] bit 7: the controller says the sauna reached temperature."""
    _attr_name = "Sauna pronta"
    _attr_icon = "mdi:sauna"
    _key = "ready"
    _field = "ready"


class SaunaDomoticSensor(_SaunaBinary):
    """STATE DATA[24] bit 1: remote control (domotica) enabled on the panel.
    When off the controller answers NACK to every command."""
    _attr_name = "Domotica abilitata"
    _attr_icon = "mdi:remote"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _key = "domotic"
    _field = "domotic"

    @property
    def extra_state_attributes(self) -> dict:
        d = self.coordinator.data
        if not d or d.sauna_flags is None:
            return {}
        return {"flag_sauna": f"0x{d.sauna_flags:02X}", "pannello": d.panel}
