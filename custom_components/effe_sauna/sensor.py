"""Effe ECC Sauna — sensor entities."""
from __future__ import annotations

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import DOMAIN, NO_DATA_THRESHOLD, SaunaCoordinator, device_info


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: SaunaCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities: list[SensorEntity] = [
        SaunaHeaterRawSensor(coordinator, entry),
        SaunaProbeSensor(coordinator, entry),
        SaunaSetpointSensor(coordinator, entry),
    ]
    if coordinator.device.wifi_firmware:
        entities.append(SaunaWifiFirmwareSensor(coordinator, entry))
    async_add_entities(entities)


class _SaunaSensor(CoordinatorEntity[SaunaCoordinator], SensorEntity):
    _attr_has_entity_name = True
    _key: str
    _field: str

    def __init__(self, coordinator: SaunaCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_{self._key}"
        self._attr_device_info = device_info(coordinator)

    @property
    def available(self) -> bool:
        data = self.coordinator.data
        return (
            data is not None
            and getattr(data, self._field) is not None
            and self.coordinator.no_data_streak < NO_DATA_THRESHOLD
        )


class SaunaHeaterRawSensor(_SaunaSensor):
    """Raw byte of the controller probe (STATE DATA[7])."""
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_name = "Sonda Sauna (raw)"
    _attr_icon = "mdi:thermometer-alert"
    _key = "heater_raw"
    _field = "heater_raw"

    @property
    def native_value(self) -> int | None:
        return self.coordinator.data.heater_raw if self.coordinator.data else None


class SaunaProbeSensor(_SaunaSensor):
    """Controller probe in °C: raw / 2, the same scale as the setpoint.

    While regulating the probe settles on the setpoint (raw 183-191 with
    setpoint 186 = 93 °C), so it is the temperature the controller regulates
    on, measured at its probe (near the ceiling). Below ~40 °C it reads far
    too low (raw 5 with the cabin at 21 °C), so below MIN_VALID_C the state is
    unknown: use an external thermometer for the cabin temperature.
    """
    MIN_VALID_C = 40.0
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_name = "Temperatura sonda sauna"
    _attr_icon = "mdi:thermometer"
    _attr_suggested_display_precision = 1
    _key = "probe_c"
    _field = "heater_raw"

    @property
    def native_value(self) -> float | None:
        d = self.coordinator.data
        if not d or d.heater_raw is None:
            return None
        value = d.heater_raw / 2.0
        return value if value >= self.MIN_VALID_C else None


class SaunaSetpointSensor(_SaunaSensor):
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_name = "Temperatura Impostata Sauna"
    _attr_icon = "mdi:thermometer-chevron-up"
    _key = "setpoint"
    _field = "setpoint"

    @property
    def native_value(self) -> float | None:
        return self.coordinator.data.setpoint if self.coordinator.data else None


class SaunaWifiFirmwareSensor(CoordinatorEntity[SaunaCoordinator], SensorEntity):
    _attr_has_entity_name = True
    _attr_name = "Firmware modulo Wi-Fi"
    _attr_icon = "mdi:wifi-cog"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: SaunaCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_wifi_firmware"
        self._attr_device_info = device_info(coordinator)

    @property
    def native_value(self) -> str | None:
        return self.coordinator.device.wifi_firmware

    @property
    def extra_state_attributes(self) -> dict:
        d = self.coordinator.device
        return {
            "firmware_ecc": d.firmware,
            "seriale": d.serial,
            "codice_prodotto": d.product_code,
            "prodotto": d.product_name,
            "mac": d.mac,
        }
