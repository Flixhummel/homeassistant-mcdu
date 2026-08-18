"""Number entities for the MCDU backlight brightness (0-255)."""

from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .hub import McduConfigEntry, McduHub

BACKLIGHTS = {
    "BACKLIGHT": "Keyboard backlight",
    "SCREEN_BACKLIGHT": "Screen backlight",
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: McduConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up brightness numbers for both backlights."""
    hub = entry.runtime_data
    async_add_entities(McduBacklightNumber(hub, led, name) for led, name in BACKLIGHTS.items())


class McduBacklightNumber(NumberEntity):
    """Brightness of one backlight channel (BRT/DIM buttons move it too)."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_entity_category = EntityCategory.CONFIG
    _attr_native_min_value = 0
    _attr_native_max_value = 255
    _attr_native_step = 1
    _attr_mode = NumberMode.SLIDER

    def __init__(self, hub: McduHub, led: str, name: str) -> None:
        self._hub = hub
        self._led = led
        self._attr_unique_id = f"{hub.device_id}_{led.lower()}"
        self._attr_name = name
        self._attr_device_info = hub.device_info

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            async_dispatcher_connect(self.hass, self._hub.signal_leds, self._handle_update)
        )

    @callback
    def _handle_update(self) -> None:
        self.async_write_ha_state()

    @property
    def native_value(self) -> float:
        value = self._hub.leds.get(self._led, 0)
        if isinstance(value, bool):
            return 255 if value else 0
        return float(value)

    async def async_set_native_value(self, value: float) -> None:
        await self._hub.async_set_led(self._led, int(value))
