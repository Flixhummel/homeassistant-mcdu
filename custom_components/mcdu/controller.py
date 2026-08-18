"""Glue between the pure page engine and Home Assistant.

Loads page configuration from HA storage, resolves datapoint sources against
HA entities, handles hardware buttons (LSK navigation, SLEW, CLR) and publishes
rendered frames to the device via the hub (protocol v1.0, display/set retained).
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING

from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import DOMAIN, FUNCTION_KEYS
from .input_engine import InputModeManager, Scratchpad
from .page_engine import COLUMNS, PageEngine, pad_or_truncate, sanitize_ascii

if TYPE_CHECKING:
    from .hub import McduHub

_LOGGER = logging.getLogger(__name__)

STORAGE_VERSION = 1

# Collapse bursts of state changes into one render (reference throttles to 10/s)
RENDER_DEBOUNCE = 0.1

BRIGHTNESS_STEP = 20

# One current format, no legacy migrations: invalid stored data is reported
# and replaced by the default page, never silently converted.
DEFAULT_PAGES: list[dict] = [
    {
        "id": "home",
        "name": "Home",
        "parent": None,
        "lines": [
            {
                "row": 3,
                "left": {
                    "label": "",
                    "display": {"type": "label", "text": "WILLKOMMEN", "colData": "cyan"},
                    "button": {"type": "empty"},
                },
                "right": {"label": "", "display": {"type": "empty"}, "button": {"type": "empty"}},
            },
            {
                "row": 5,
                "left": {
                    "label": "",
                    "display": {"type": "label", "text": "HOME ASSISTANT MCDU"},
                    "button": {"type": "empty"},
                },
                "right": {"label": "", "display": {"type": "empty"}, "button": {"type": "empty"}},
            },
        ],
    }
]

UNAVAILABLE_STATES = ("unavailable", "unknown")

KEYPAD_SPECIAL = {"DOT": ".", "SLASH": "/", "SPACE": " "}

# HA domain → datapoint metadata for the input engine
BOOLEAN_DOMAINS = ("switch", "light", "input_boolean", "fan", "siren", "humidifier")
NUMBER_DOMAINS = ("number", "input_number")
TEXT_DOMAINS = ("text", "input_text")
SELECT_DOMAINS = ("select", "input_select")


def _valid_function_keys(data: object) -> dict[str, str]:
    """Keep only well-formed key→page assignments."""
    if not isinstance(data, dict):
        return {}
    return {
        key: target
        for key, target in data.items()
        if key in FUNCTION_KEYS and isinstance(target, str) and target
    }


def _valid_pages(data: object) -> bool:
    if not isinstance(data, list) or not data:
        return False
    return all(
        isinstance(page, dict)
        and isinstance(page.get("id"), str)
        and isinstance(page.get("lines", []), list)
        for page in data
    )


class McduController:
    """Drives one MCDU device: pages, navigation, rendering."""

    def __init__(
        self,
        hass: HomeAssistant,
        hub: McduHub,
        store: Store,
        pages: list[dict],
        function_keys: dict[str, str] | None = None,
    ) -> None:
        self.hass = hass
        self.hub = hub
        self.store = store
        # Function key → target page id (unassigned keys are absent)
        self.function_keys: dict[str, str] = function_keys or {}
        self.scratchpad = Scratchpad()
        self.input_manager = InputModeManager(self.scratchpad)
        self.engine = PageEngine(
            pages,
            value_resolver=self._resolve_entity,
            scratchpad_provider=lambda: (
                self.scratchpad.get_display(),
                self.scratchpad.get_color(),
            ),
            clock=dt_util.now,
        )
        self.current_page_id: str | None = pages[0]["id"] if pages else None
        self._last_lines: list[dict] | None = None
        self._tracked_page_id: str | None = None
        self._unsub_track = None
        self._render_pending = False

    @classmethod
    async def async_create(cls, hass: HomeAssistant, hub: McduHub) -> McduController:
        store: Store = Store(
            hass, STORAGE_VERSION, f"{DOMAIN}.pages_{hub.entry.entry_id}"
        )
        data = await store.async_load()
        if data is None:
            pages = DEFAULT_PAGES
        elif _valid_pages(data.get("pages")):
            pages = data["pages"]
        else:
            _LOGGER.error(
                "Stored page config for %s does not match the current format — "
                "using default page. Recreate the configuration (no automatic "
                "migration is performed).",
                hub.device_id,
            )
            pages = DEFAULT_PAGES
        function_keys = _valid_function_keys((data or {}).get("functionKeys"))
        return cls(hass, hub, store, pages, function_keys)

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------

    def _resolve_entity(self, source: str) -> dict | None:
        state = self.hass.states.get(source)
        if state is None:
            return None
        if state.state in UNAVAILABLE_STATES:
            return {"value": None, "available": False}
        return {"value": state.state, "available": True}

    async def async_render(self) -> None:
        if not self.current_page_id:
            return
        self._update_source_tracking()
        self.engine.breadcrumb = self.engine.build_breadcrumb(self.current_page_id)
        lines = self.engine.render_page(self.current_page_id)
        if lines == self._last_lines:
            return
        self._last_lines = lines
        await self.hub.async_publish(
            "display/set",
            {"lines": lines, "timestamp": int(time.time() * 1000)},
            retain=True,
        )

    # ------------------------------------------------------------------
    # Live updates: re-render when a datapoint source changes
    # ------------------------------------------------------------------

    def _page_sources(self) -> set[str]:
        page = self.engine.find_page(self.current_page_id) if self.current_page_id else None
        sources: set[str] = set()
        for line in (page or {}).get("lines") or []:
            for side in ("left", "right"):
                source = ((line.get(side) or {}).get("display") or {}).get("source")
                if source:
                    sources.add(source)
        return sources

    def _update_source_tracking(self) -> None:
        if self._tracked_page_id == self.current_page_id:
            return
        self._tracked_page_id = self.current_page_id
        if self._unsub_track:
            self._unsub_track()
            self._unsub_track = None
        sources = self._page_sources()
        if sources:
            self._unsub_track = async_track_state_change_event(
                self.hass, sorted(sources), self._source_changed
            )

    @callback
    def _source_changed(self, _event: Event) -> None:
        if self._render_pending:
            return
        self._render_pending = True

        async def _debounced_render() -> None:
            await asyncio.sleep(RENDER_DEBOUNCE)
            self._render_pending = False
            await self.async_render()

        self.hass.async_create_task(_debounced_render())

    async def async_stop(self) -> None:
        if self._unsub_track:
            self._unsub_track()
            self._unsub_track = None

    async def async_apply_config(
        self, pages: list[dict], function_keys: dict[str, str] | None = None
    ) -> None:
        """Apply a new configuration (from the panel) and re-render."""
        self.engine.pages = pages
        if function_keys is not None:
            self.function_keys = function_keys
        if not self.engine.find_page(self.current_page_id) and pages:
            self.current_page_id = pages[0]["id"]
        self.engine.current_page_offset = 0
        self._tracked_page_id = None  # force re-subscription of sources
        self._last_lines = None
        await self.async_render()

    async def async_switch_page(self, page_id: str) -> None:
        if not self.engine.find_page(page_id):
            _LOGGER.warning("Unknown page: %s", page_id)
            return
        self.current_page_id = page_id
        self.engine.current_page_offset = 0
        await self.async_render()

    # ------------------------------------------------------------------
    # Button handling
    # ------------------------------------------------------------------

    async def async_handle_button(self, button: str, action: str) -> None:
        if action != "press":
            return
        if button.startswith("LSK"):
            await self._handle_lsk(button)
        elif button == "CLR":
            await self._handle_clr()
        elif button == "PLUSMINUS":
            await self._execute_decision(self.input_manager.handle_plusminus())
        elif (char := self._keypad_char(button)) is not None:
            await self._execute_decision(self.input_manager.handle_key_input(char))
        elif button in ("SLEW_LEFT", "SLEW_RIGHT"):
            await self._handle_sibling_slew(button)
        elif button in ("SLEW_UP", "SLEW_DOWN"):
            await self._handle_page_slew(button)
        elif button in ("BRT", "DIM"):
            await self._handle_brightness(button)
        elif button in FUNCTION_KEYS:
            if target := self.function_keys.get(button):
                await self.async_switch_page(target)

    @staticmethod
    def _keypad_char(button: str) -> str | None:
        if len(button) == 1 and (button.isdigit() or button.isupper()):
            return button
        return KEYPAD_SPECIAL.get(button)

    async def _handle_lsk(self, button: str) -> None:
        # LSK1L/LSK1R → row 3 ... LSK6L/LSK6R → row 13
        try:
            row = int(button[3]) * 2 + 1
        except ValueError:
            return
        side = "left" if button.endswith("L") else "right"

        line = self.engine.line_at_row(row)
        decision = self.input_manager.handle_lsk(line, side, self._entity_meta)
        await self._execute_decision(decision)

    def _entity_meta(self, entity_id: str) -> dict | None:
        """Map an HA entity to the input engine's datapoint metadata."""
        state = self.hass.states.get(entity_id)
        if state is None:
            return None
        domain = entity_id.split(".")[0]
        attrs = state.attributes

        if domain in BOOLEAN_DOMAINS:
            return {"write": True, "type": "boolean"}
        if domain in NUMBER_DOMAINS:
            return {
                "write": True,
                "type": "number",
                "min": attrs.get("min"),
                "max": attrs.get("max"),
            }
        if domain in TEXT_DOMAINS:
            return {"write": True, "type": "string"}
        if domain in SELECT_DOMAINS:
            return {"write": True, "type": "string", "options": attrs.get("options")}
        # sensor, binary_sensor, everything else: read-only
        return {"write": False, "type": "string"}

    async def _execute_decision(self, decision: tuple) -> None:
        """Execute a decision returned by the input engine."""
        kind = decision[0]

        if kind == "none":
            return
        if kind in ("render", "cleared", "error"):
            # Scratchpad (line 14) changed
            await self.async_render()
        elif kind == "full":
            await self.async_show_message("ERR SCRATCHPAD VOLL", "red", 3)
        elif kind == "home":
            pages = self.engine.pages
            if pages:
                await self.async_switch_page(pages[0]["id"])
        elif kind == "parent":
            parent = self.engine.parent_of(self.current_page_id)
            if parent:
                await self.async_switch_page(parent)
        elif kind == "toggle":
            await self.hass.services.async_call(
                "homeassistant", "toggle", {"entity_id": decision[1]}, blocking=False
            )
        elif kind == "write":
            await self._write_entity(decision[1], decision[2])
            await self.async_render()
        elif kind == "action":
            button = decision[1]
            btn_type = button.get("type")
            target = button.get("target")
            if btn_type in ("navigation", "goto") and target:
                await self.async_switch_page(target)
            elif btn_type == "datapoint" and target:
                await self._execute_datapoint_action(
                    target, button.get("action") or "toggle"
                )

    async def _write_entity(self, entity_id: str, value: float | str) -> None:
        """Write a validated scratchpad value to an HA entity."""
        domain = entity_id.split(".")[0]
        try:
            if domain in NUMBER_DOMAINS:
                await self.hass.services.async_call(
                    domain, "set_value", {"entity_id": entity_id, "value": value},
                    blocking=True,
                )
            elif domain in TEXT_DOMAINS:
                await self.hass.services.async_call(
                    domain, "set_value", {"entity_id": entity_id, "value": str(value)},
                    blocking=True,
                )
            elif domain in SELECT_DOMAINS:
                await self.hass.services.async_call(
                    domain, "select_option",
                    {"entity_id": entity_id, "option": str(value)},
                    blocking=True,
                )
            else:
                _LOGGER.warning("Cannot write to domain of %s", entity_id)
                return
            _LOGGER.info("Written %s: %s", entity_id, value)
        except Exception:  # noqa: BLE001
            _LOGGER.exception("Failed to write %s", entity_id)
            self.scratchpad.show_error("SCHREIBFEHLER")

    async def async_show_message(self, text: str, color: str, seconds: float) -> None:
        """Show a temporary message on line 13, then restore the page."""
        await self.hub.async_publish(
            "display/line",
            {
                "lineNumber": 13,
                "text": pad_or_truncate(sanitize_ascii(text), COLUMNS),
                "color": color,
                "timestamp": int(time.time() * 1000),
            },
        )

        async def _restore() -> None:
            await asyncio.sleep(seconds)
            self._last_lines = None  # bypass dedupe — line 13 was overwritten
            await self.async_render()

        self.hass.async_create_task(_restore())

    async def _execute_datapoint_action(self, entity_id: str, action: str) -> None:
        """Execute a datapoint button action on an HA entity.

        Mirrors the reference adapter: default action is toggle; increment and
        decrement step numeric entities by 1. The resulting state change
        triggers the re-render via source tracking.
        """
        if action == "toggle":
            await self.hass.services.async_call(
                "homeassistant", "toggle", {"entity_id": entity_id}, blocking=False
            )
            return

        if action in ("increment", "decrement"):
            domain = entity_id.split(".")[0]
            if domain not in ("number", "input_number"):
                _LOGGER.warning(
                    "%s only supported for number/input_number, not %s",
                    action,
                    entity_id,
                )
                return
            state = self.hass.states.get(entity_id)
            try:
                current = float(state.state) if state else 0.0
            except ValueError:
                current = 0.0
            new_value = current + 1 if action == "increment" else current - 1
            await self.hass.services.async_call(
                domain,
                "set_value",
                {"entity_id": entity_id, "value": new_value},
                blocking=False,
            )
            return

        _LOGGER.warning("Unknown datapoint action: %s", action)

    async def _handle_clr(self) -> None:
        """CLR: double-press → home, scratchpad clear/restore, parent page."""
        if not self.current_page_id:
            return
        has_parent = self.engine.parent_of(self.current_page_id) is not None
        decision = self.input_manager.handle_clr(time.monotonic(), has_parent)
        await self._execute_decision(decision)

    async def _handle_sibling_slew(self, button: str) -> None:
        if not self.current_page_id:
            return
        if button == "SLEW_RIGHT":
            target = self.engine.navigate_next(self.current_page_id)
        else:
            target = self.engine.navigate_previous(self.current_page_id)
        if target != self.current_page_id:
            await self.async_switch_page(target)

    async def _handle_page_slew(self, button: str) -> None:
        engine = self.engine
        if button == "SLEW_DOWN" and engine.current_page_offset < engine.total_pages - 1:
            engine.current_page_offset += 1
            await self.async_render()
        elif button == "SLEW_UP" and engine.current_page_offset > 0:
            engine.current_page_offset -= 1
            await self.async_render()

    async def _handle_brightness(self, button: str) -> None:
        """BRT/DIM adjust both backlights by the configured step (clamped 0-255)."""
        delta = BRIGHTNESS_STEP if button == "BRT" else -BRIGHTNESS_STEP
        for led in ("BACKLIGHT", "SCREEN_BACKLIGHT"):
            current = self.hub.leds.get(led, 128)
            if isinstance(current, bool):
                current = 255 if current else 0
            await self.hub.async_set_led(led, max(0, min(255, current + delta)))
