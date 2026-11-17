"""Effe ECC Sauna — buttons."""
from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import DOMAIN, SaunaCoordinator, device_info


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: SaunaCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([SaunaSyncTimeButton(coordinator, entry)])


class SaunaSyncTimeButton(CoordinatorEntity[SaunaCoordinator], ButtonEntity):
    """SET_SYS_TIME (0x39) with the Home Assistant time, as the app does."""
    _attr_has_entity_name = True
    _attr_name = "Sincronizza orologio"
    _attr_icon = "mdi:clock-check-outline"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: SaunaCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_sync_time"
        self._attr_device_info = device_info(coordinator)

    async def async_press(self) -> None:
        await self.coordinator.async_sync_time()
