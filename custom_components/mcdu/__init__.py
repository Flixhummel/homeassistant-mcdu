"""The WinWing MCDU integration."""

from __future__ import annotations

from pathlib import Path

from homeassistant.components import panel_custom
from homeassistant.components.http import StaticPathConfig
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.typing import ConfigType

from .const import DOMAIN
from .controller import McduController
from .hub import McduConfigEntry, McduHub
from .websocket import async_register_commands

PLATFORMS: list[Platform] = [Platform.BINARY_SENSOR, Platform.NUMBER, Platform.SWITCH]

PANEL_URL_PATH = "mcdu"
PANEL_STATIC_PATH = "/mcdu_panel"


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register WebSocket API and the configuration panel (once)."""
    async_register_commands(hass)

    await hass.http.async_register_static_paths(
        [
            StaticPathConfig(
                PANEL_STATIC_PATH,
                str(Path(__file__).parent / "frontend"),
                cache_headers=False,
            )
        ]
    )
    await panel_custom.async_register_panel(
        hass,
        frontend_url_path=PANEL_URL_PATH,
        webcomponent_name="mcdu-panel",
        module_url=f"{PANEL_STATIC_PATH}/panel.js",
        sidebar_title="MCDU",
        sidebar_icon="mdi:airplane",
        require_admin=True,
        config={"domain": DOMAIN},
    )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: McduConfigEntry) -> bool:
    """Set up an MCDU device from a config entry."""
    hub = McduHub(hass, entry)
    await hub.async_start()
    entry.runtime_data = hub

    controller = await McduController.async_create(hass, hub)
    hub.button_handler = controller.async_handle_button
    hub.controller = controller
    # Publish the current page as retained frame; a (re)connecting client
    # renders it immediately without further interaction.
    await controller.async_render()

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: McduConfigEntry) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        hub = entry.runtime_data
        if hub.controller:
            await hub.controller.async_stop()
        await hub.async_stop()
    return unload_ok
