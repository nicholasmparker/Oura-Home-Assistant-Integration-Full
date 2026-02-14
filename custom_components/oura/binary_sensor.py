"""Binary sensor platform for Oura Ring integration."""
from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import ATTRIBUTION, DOMAIN
from .coordinator import OuraDataUpdateCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Oura Ring binary sensors."""
    coordinator: OuraDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]

    entities = [
        OuraRestModeBinarySensor(coordinator),
    ]

    async_add_entities(entities)


class OuraRestModeBinarySensor(CoordinatorEntity[OuraDataUpdateCoordinator], BinarySensorEntity):
    """Representation of Oura Ring Rest Mode binary sensor."""

    _attr_attribution = ATTRIBUTION
    _attr_has_entity_name = True
    _attr_icon = "mdi:bed"
    _attr_name = "Rest Mode"
    _attr_translation_key = "rest_mode"

    def __init__(
        self,
        coordinator: OuraDataUpdateCoordinator,
    ) -> None:
        """Initialize the binary sensor."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_rest_mode_active"

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information about this Oura Ring."""
        return DeviceInfo(
            identifiers={(DOMAIN, self.coordinator.entry.entry_id)},
            name="Oura Ring",
            manufacturer="Oura",
            model="Oura Ring",
            entry_type=DeviceEntryType.SERVICE,
        )

    @property
    def is_on(self) -> bool | None:
        """Return true if rest mode is active."""
        return self.coordinator.data.get("rest_mode_active")

    @property
    def extra_state_attributes(self) -> dict[str, str] | None:
        """Return extra state attributes."""
        attrs = {}

        if self.coordinator.data and "_active_rest_mode_raw" in self.coordinator.data:
            rest_mode_raw = self.coordinator.data["_active_rest_mode_raw"]

            # Add useful rest mode metadata
            if rest_mode_id := rest_mode_raw.get("id"):
                attrs["id"] = rest_mode_id
            if start_day := rest_mode_raw.get("start_day"):
                attrs["start_day"] = start_day
            if end_day := rest_mode_raw.get("end_day"):
                attrs["end_day"] = end_day

        return attrs if attrs else None

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return (
            self.coordinator.data is not None
            and "rest_mode_active" in self.coordinator.data
            and self.coordinator.data["rest_mode_active"] is not None
        )
