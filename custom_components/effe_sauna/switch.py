"""Effe ECC Sauna — switch entities."""
from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import CMD_LIGHT_OFF, CMD_LIGHT_ON, CMD_OFF, CMD_ON, DOMAIN, SaunaCoordinator


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: SaunaCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([
        SaunaPowerSwitch(coordinator, entry),
        SaunaLightSwitch(coordinator, entry),
    ])


class SaunaPowerSwitch(CoordinatorEntity[SaunaCoordinator], SwitchEntity, RestoreEntity):
    _attr_icon = "mdi:sauna"
    _attr_has_entity_name = True
    _attr_name = "Sauna"

    def __init__(self, coordinator: SaunaCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_power"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": "Effe ECC Sauna",
            "manufacturer": "Effe Perfect Wellness",
            "model": "ECC",
        }
        self._is_on = False

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state is not None:
            self._is_on = last_state.state == "on"

    @callback
    def _handle_coordinator_update(self) -> None:
        data = self.coordinator.data
        if not data.available or data.temperature is None:
            # Device completely unreachable — treat as off
            self._is_on = False
            self.coordinator._sauna_commanded_on = False
        elif data.temperature > 40.0:
            # Temperature clearly above standby → sauna is definitely ON
            self._is_on = True
        # 0–40°C: standby or warming up → keep local optimistic state
        super()._handle_coordinator_update()

    @property
    def is_on(self) -> bool:
        return self._is_on

    @property
    def available(self) -> bool:
        return self.coordinator.data.available

    @property
    def extra_state_attributes(self) -> dict:
        d = self.coordinator.data
        if d.temperature is not None:
            return {"probe_temperature": f"{d.temperature:.1f}°C"}
        return {}

    async def async_turn_on(self, **kwargs) -> None:
        self._is_on = True
        self.async_write_ha_state()
        await self.coordinator.async_send_command(CMD_ON)

    async def async_turn_off(self, **kwargs) -> None:
        self._is_on = False
        self.async_write_ha_state()
        await self.coordinator.async_send_command(CMD_OFF)


class SaunaLightSwitch(CoordinatorEntity[SaunaCoordinator], SwitchEntity, RestoreEntity):
    _attr_icon = "mdi:lightbulb"
    _attr_has_entity_name = True
    _attr_name = "Sauna Light"

    def __init__(self, coordinator: SaunaCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_light"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": "Effe ECC Sauna",
            "manufacturer": "Effe Perfect Wellness",
            "model": "ECC",
        }
        self._is_on = False

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state is not None:
            self._is_on = last_state.state == "on"

    @property
    def is_on(self) -> bool:
        return self._is_on

    @property
    def available(self) -> bool:
        return self.coordinator.data.available

    @callback
    def _handle_coordinator_update(self) -> None:
        data = self.coordinator.data
        # Sync with the light state tracked in the coordinator.
        # Forced to False when sauna is turned off (hardware cuts the light).
        # Can be toggled independently at any sauna temperature.
        if not data.available:
            self._is_on = False
        else:
            self._is_on = data.light_on
        super()._handle_coordinator_update()

    async def async_turn_on(self, **kwargs) -> None:
        self._is_on = True
        self.async_write_ha_state()
        if not await self.coordinator.async_send_command(CMD_LIGHT_ON):
            self._is_on = False
            self.async_write_ha_state()

    async def async_turn_off(self, **kwargs) -> None:
        self._is_on = False
        self.async_write_ha_state()
        if not await self.coordinator.async_send_command(CMD_LIGHT_OFF):
            self._is_on = True
            self.async_write_ha_state()
