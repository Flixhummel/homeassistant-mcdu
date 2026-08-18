"""WebSocket API backing the MCDU configuration panel.

Commands:
  mcdu/devices        list configured MCDU devices
  mcdu/pages/get      load the page configuration of one device
  mcdu/pages/save     save + apply the page configuration (strict format check)
  mcdu/preview        render one page through the real engine → 14 lines

The preview uses the same PageEngine as the hardware, so the panel shows
exactly what the display will show — there is no second rendering path.
"""

from __future__ import annotations

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .page_engine import PageEngine


def async_register_commands(hass: HomeAssistant) -> None:
    websocket_api.async_register_command(hass, ws_devices)
    websocket_api.async_register_command(hass, ws_pages_get)
    websocket_api.async_register_command(hass, ws_pages_save)
    websocket_api.async_register_command(hass, ws_preview)


def _controller(hass: HomeAssistant, entry_id: str):
    entry = hass.config_entries.async_get_entry(entry_id)
    if entry is None or entry.domain != DOMAIN or not hasattr(entry, "runtime_data"):
        return None
    hub = entry.runtime_data
    return getattr(hub, "controller", None)


@websocket_api.websocket_command({vol.Required("type"): "mcdu/devices"})
@websocket_api.async_response
async def ws_devices(hass, connection, msg):
    result = [
        {
            "entry_id": entry.entry_id,
            "device_id": entry.data.get("device_id"),
            "title": entry.title,
            "online": getattr(entry.runtime_data, "online", False)
            if hasattr(entry, "runtime_data")
            else False,
        }
        for entry in hass.config_entries.async_entries(DOMAIN)
    ]
    connection.send_result(msg["id"], result)


@websocket_api.websocket_command(
    {vol.Required("type"): "mcdu/pages/get", vol.Required("entry_id"): str}
)
@websocket_api.async_response
async def ws_pages_get(hass, connection, msg):
    controller = _controller(hass, msg["entry_id"])
    if controller is None:
        connection.send_error(msg["id"], "not_found", "Device not found")
        return
    connection.send_result(
        msg["id"],
        {
            "pages": controller.engine.pages,
            "function_keys": controller.function_keys,
            "led_bindings": controller.led_bindings,
            "current_page": controller.current_page_id,
        },
    )


@websocket_api.websocket_command(
    {
        vol.Required("type"): "mcdu/pages/save",
        vol.Required("entry_id"): str,
        vol.Required("pages"): list,
        vol.Optional("function_keys"): dict,
        vol.Optional("led_bindings"): dict,
    }
)
@websocket_api.async_response
async def ws_pages_save(hass, connection, msg):
    from .controller import (  # avoids cycle
        _valid_function_keys,
        _valid_led_bindings,
        _valid_pages,
    )

    controller = _controller(hass, msg["entry_id"])
    if controller is None:
        connection.send_error(msg["id"], "not_found", "Device not found")
        return

    pages = msg["pages"]
    if not _valid_pages(pages):
        connection.send_error(
            msg["id"], "invalid_format", "Pages do not match the current format"
        )
        return

    function_keys = _valid_function_keys(
        msg.get("function_keys", controller.function_keys)
    )
    led_bindings = _valid_led_bindings(
        msg.get("led_bindings", controller.led_bindings)
    )
    await controller.store.async_save(
        {"pages": pages, "functionKeys": function_keys, "ledBindings": led_bindings}
    )
    await controller.async_apply_config(pages, function_keys, led_bindings)
    connection.send_result(msg["id"], {"saved": True})


@websocket_api.websocket_command(
    {
        vol.Required("type"): "mcdu/preview",
        vol.Required("entry_id"): str,
        vol.Required("page_id"): str,
        vol.Optional("pages"): list,
        vol.Optional("page_offset"): int,
    }
)
@websocket_api.async_response
async def ws_preview(hass, connection, msg):
    """Render a page (optionally from unsaved draft pages) to 14 lines."""
    controller = _controller(hass, msg["entry_id"])
    if controller is None:
        connection.send_error(msg["id"], "not_found", "Device not found")
        return

    pages = msg.get("pages") or controller.engine.pages
    engine = PageEngine(
        pages,
        value_resolver=controller._resolve_entity,  # noqa: SLF001 — same integration
        scratchpad_provider=lambda: ("", "white"),
        clock=dt_util.now,
    )
    engine.current_page_offset = msg.get("page_offset", 0)
    engine.breadcrumb = engine.build_breadcrumb(msg["page_id"])
    lines = engine.render_page(msg["page_id"])
    connection.send_result(
        msg["id"],
        {
            "lines": lines,
            "total_pages": engine.total_pages,
            "page_offset": engine.current_page_offset,
        },
    )
