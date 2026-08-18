"""Switch entities for the MCDU indicator LEDs."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import LED_NAMES
from .hub import McduConfigEntry, McduHub

INDICATOR_LEDS = [name for name in LED_NAMES if name not in ("BACKLIGHT", "SCREEN_BACKLIGHT")]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: McduConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up one switch per indicator LED."""
    hub = entry.runtime_data
    async_add_entities(McduLedSwitch(hub, led) for led in INDICATOR_LEDS)


class McduLedSwitch(SwitchEntity):
    """One indicator LED on the MCDU front panel.

    Optimistic: the client does not report LED state back, so the hub's local
    cache is the source of truth.
    """

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_entity_category = EntityCategory.CONFIG
    _attr_assumed_state = True

    def __init__(self, hub: McduHub, led: str) -> None:
        self._hub = hub
        self._led = led
        self._attr_unique_id = f"{hub.device_id}_led_{led.lower()}"
        self._attr_name = f"LED {led}"
        self._attr_device_info = hub.device_info

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            async_dispatcher_connect(self.hass, self._hub.signal_leds, self._handle_update)
        )

    @callback
    def _handle_update(self) -> None:
        self.async_write_ha_state()

    @property
    def is_on(self) -> bool:
        return bool(self._hub.leds.get(self._led))

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._hub.async_set_led(self._led, True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._hub.async_set_led(self._led, False)
