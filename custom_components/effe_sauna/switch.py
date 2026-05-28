"""Effe ECC Sauna — switch entities."""
from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import (
    CMD_LIGHT_OFF,
    CMD_LIGHT_ON,
    CMD_OFF,
    CMD_ON,
    DOMAIN,
    NO_DATA_THRESHOLD,
    SaunaCoordinator,
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: SaunaCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([
        SaunaPowerSwitch(coordinator, entry),
        SaunaLightSwitch(coordinator, entry),
    ])


def _device_info(entry_id: str) -> dict:
    return {
        "identifiers": {(DOMAIN, entry_id)},
        "name": "Effe ECC Sauna",
        "manufacturer": "Effe Perfect Wellness",
        "model": "ECC",
    }


class SaunaPowerSwitch(CoordinatorEntity[SaunaCoordinator], SwitchEntity):
    _attr_icon = "mdi:sauna"
    _attr_has_entity_name = True
    _attr_name = "Sauna"

    def __init__(self, coordinator: SaunaCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_power"
        self._attr_device_info = _device_info(entry.entry_id)

    @property
    def is_on(self) -> bool:
        return self.coordinator.data is not None and self.coordinator.data.master_on

    @property
    def available(self) -> bool:
        return self.coordinator.no_data_streak < NO_DATA_THRESHOLD

    async def async_turn_on(self, **kwargs) -> None:
        await self.coordinator.async_send_command(CMD_ON)

    async def async_turn_off(self, **kwargs) -> None:
        await self.coordinator.async_send_command(CMD_OFF)


class SaunaLightSwitch(CoordinatorEntity[SaunaCoordinator], SwitchEntity):
    _attr_icon = "mdi:lightbulb"
    _attr_has_entity_name = True
    _attr_name = "Luce Sauna"

    def __init__(self, coordinator: SaunaCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_light"
        self._attr_device_info = _device_info(entry.entry_id)

    @property
    def is_on(self) -> bool:
        return self.coordinator.data is not None and self.coordinator.data.light_on

    @property
    def available(self) -> bool:
        return self.coordinator.no_data_streak < NO_DATA_THRESHOLD

    async def async_turn_on(self, **kwargs) -> None:
        await self.coordinator.async_send_command(CMD_LIGHT_ON)

    async def async_turn_off(self, **kwargs) -> None:
        await self.coordinator.async_send_command(CMD_LIGHT_OFF)
