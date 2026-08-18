"""Glue between the pure page engine and Home Assistant.

Loads page configuration from HA storage, resolves datapoint sources against
HA entities, handles hardware buttons (LSK navigation, SLEW, CLR) and publishes
rendered frames to the device via the hub (protocol v1.0, display/set retained).
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .page_engine import PageEngine

if TYPE_CHECKING:
    from .hub import McduHub

_LOGGER = logging.getLogger(__name__)

STORAGE_VERSION = 1

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
        self.engine.breadcrumb = self.engine.build_breadcrumb(self.current_page_id)
        lines = self.engine.render_page(self.current_page_id)
        await self.hub.async_publish(
            "display/set",
            {"lines": lines, "timestamp": int(time.time() * 1000)},
            retain=True,
        )

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
        elif btn_type not in (None, "empty"):
            _LOGGER.debug(
                "Button type %s not implemented yet (row %s, %s)", btn_type, row, side
            )

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
