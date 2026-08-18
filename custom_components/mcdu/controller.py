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

from .const import DOMAIN
from .page_engine import PageEngine

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
        self, hass: HomeAssistant, hub: McduHub, store: Store, pages: list[dict]
    ) -> None:
        self.hass = hass
        self.hub = hub
        self.store = store
        self.engine = PageEngine(
            pages, value_resolver=self._resolve_entity, clock=dt_util.now
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
        return cls(hass, hub, store, pages)

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
        elif button in ("SLEW_LEFT", "SLEW_RIGHT"):
            await self._handle_sibling_slew(button)
        elif button in ("SLEW_UP", "SLEW_DOWN"):
            await self._handle_page_slew(button)
        elif button in ("BRT", "DIM"):
            await self._handle_brightness(button)

    async def _handle_lsk(self, button: str) -> None:
        # LSK1L/LSK1R → row 3 ... LSK6L/LSK6R → row 13
        try:
            row = int(button[3]) * 2 + 1
        except ValueError:
            return
        side = "left" if button.endswith("L") else "right"

        line = self.engine.line_at_row(row)
        if not line:
            return
        btn = (line.get(side) or {}).get("button") or {}
        btn_type = btn.get("type")
        target = btn.get("target")

        if btn_type in ("navigation", "goto") and target:
            await self.async_switch_page(target)
        elif btn_type == "datapoint" and target:
            await self._execute_datapoint_action(target, btn.get("action") or "toggle")
        elif btn_type not in (None, "empty"):
            _LOGGER.debug(
                "Button type %s not implemented yet (row %s, %s)", btn_type, row, side
            )

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
        if not self.current_page_id:
            return
        parent = self.engine.parent_of(self.current_page_id)
        if parent:
            await self.async_switch_page(parent)

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
