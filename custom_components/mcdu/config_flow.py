"""Config flow for the WinWing MCDU integration.

Devices are discovered via the retained ``{prefix}/+/status/online`` topics
published by every mcdu-client (protocol v1.0). Retained messages arrive
immediately on subscribe, so a short collection window is enough.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import voluptuous as vol

from homeassistant.components import mqtt
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
)

from .const import (
    CONF_DEVICE_ID,
    CONF_TOPIC_PREFIX,
    DEFAULT_TOPIC_PREFIX,
    DISCOVERY_TIMEOUT,
    DOMAIN,
)


class McduConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the MCDU config flow."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step."""
        if not await mqtt.async_wait_for_mqtt_client(self.hass):
            return self.async_abort(reason="mqtt_unavailable")

        if user_input is not None:
            device_id = user_input[CONF_DEVICE_ID].strip()
            prefix = user_input.get(CONF_TOPIC_PREFIX, DEFAULT_TOPIC_PREFIX).strip("/ ")

            await self.async_set_unique_id(device_id)
            self._abort_if_unique_id_configured()

            return self.async_create_entry(
                title=f"MCDU {device_id}",
                data={CONF_DEVICE_ID: device_id, CONF_TOPIC_PREFIX: prefix},
            )

        discovered = await self._async_discover_devices()

        if discovered:
            device_selector = SelectSelector(
                SelectSelectorConfig(
                    options=[
                        SelectOptionDict(
                            value=device_id,
                            label=f"{device_id} ({hostname})" if hostname else device_id,
                        )
                        for device_id, hostname in sorted(discovered.items())
                    ],
                    custom_value=True,
                    mode=SelectSelectorMode.DROPDOWN,
                )
            )
        else:
            device_selector = TextSelector()

        schema = vol.Schema(
            {
                vol.Required(CONF_DEVICE_ID): device_selector,
                vol.Required(CONF_TOPIC_PREFIX, default=DEFAULT_TOPIC_PREFIX): TextSelector(),
            }
        )

        return self.async_show_form(
            step_id="user",
            data_schema=schema,
            description_placeholders={"count": str(len(discovered))},
        )

    async def _async_discover_devices(self) -> dict[str, str]:
        """Collect device ids from retained status topics (default prefix)."""
        devices: dict[str, str] = {}

        @callback
        def message_received(msg: mqtt.ReceiveMessage) -> None:
            parts = msg.topic.split("/")
            if len(parts) < 4:
                return
            try:
                payload = json.loads(msg.payload)
            except ValueError:
                return
            if payload.get("status") == "online":
                devices[parts[1]] = payload.get("hostname", "")

        unsubscribe = await mqtt.async_subscribe(
            self.hass,
            f"{DEFAULT_TOPIC_PREFIX}/+/status/online",
            message_received,
            qos=1,
        )
        try:
            await asyncio.sleep(DISCOVERY_TIMEOUT)
        finally:
            unsubscribe()

        return devices
