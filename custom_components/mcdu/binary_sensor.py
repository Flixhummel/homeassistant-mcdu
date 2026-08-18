"""Connectivity sensor for the MCDU client."""

from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .hub import McduConfigEntry, McduHub


async def async_setup_entry(
    hass: HomeAssistant,
    entry: McduConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the connectivity sensor."""
    async_add_entities([McduOnlineSensor(entry.runtime_data)])


class McduOnlineSensor(BinarySensorEntity):
    """Reflects the retained status/online topic of the Pi client."""

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_should_poll = False
    _attr_translation_key = "online"

    def __init__(self, hub: McduHub) -> None:
        self._hub = hub
        self._attr_unique_id = f"{hub.device_id}_online"
        self._attr_device_info = hub.device_info

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, self._hub.signal_status, self._handle_status
            )
        )

    @callback
    def _handle_status(self) -> None:
        self.async_write_ha_state()

    @property
    def is_on(self) -> bool:
        return self._hub.online

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        status = self._hub.status
        return {
            "hostname": status.get("hostname"),
            "client_version": status.get("version"),
            "mock_mode": status.get("mockMode"),
        }
