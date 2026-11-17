"""Effe ECC Sauna — switch entities."""
from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import DOMAIN, NO_DATA_THRESHOLD, SaunaCoordinator, device_info
from . import protocol as ccp


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: SaunaCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([
        SaunaPowerSwitch(coordinator, entry),
        SaunaLightSwitch(coordinator, entry),
    ])


class _SaunaSwitch(CoordinatorEntity[SaunaCoordinator], SwitchEntity):
    _attr_has_entity_name = True
    _function: int
    _key: str

    def __init__(self, coordinator: SaunaCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_{self._key}"
        self._attr_device_info = device_info(coordinator)

    @property
    def available(self) -> bool:
        return self.coordinator.no_data_streak < NO_DATA_THRESHOLD

    async def async_turn_on(self, **kwargs) -> None:
        await self.coordinator.async_switch(self._function, True)

    async def async_turn_off(self, **kwargs) -> None:
        await self.coordinator.async_switch(self._function, False)


class SaunaPowerSwitch(_SaunaSwitch):
    _attr_icon = "mdi:sauna"
    _attr_name = "Sauna"
    _function = ccp.FUNC_SAUNA
    _key = "power"

    @property
    def is_on(self) -> bool:
        return self.coordinator.data is not None and self.coordinator.data.master_on


class SaunaLightSwitch(_SaunaSwitch):
    _attr_icon = "mdi:lightbulb"
    _attr_name = "Luce Sauna"
    _function = ccp.FUNC_LIGHT
    _key = "light"

    @property
    def is_on(self) -> bool:
        return self.coordinator.data is not None and self.coordinator.data.light_on
