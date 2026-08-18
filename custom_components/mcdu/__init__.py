"""The WinWing MCDU integration."""

from __future__ import annotations

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .controller import McduController
from .hub import McduConfigEntry, McduHub

PLATFORMS: list[Platform] = [Platform.BINARY_SENSOR]


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
        await entry.runtime_data.async_stop()
    return unload_ok
