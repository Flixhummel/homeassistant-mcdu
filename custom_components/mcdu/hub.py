"""MQTT hub for one MCDU device.

Speaks protocol v1.0 as specified in docs/PROTOCOL.md of the ioBroker.mcdu
repository. The Pi client is a dumb terminal; this hub is the HA side of the
"brain". Phase 0 scope: connection status + button events. The page engine
(rendering, navigation, input) is added on top of this in later phases.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from homeassistant.components import mqtt
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_send

from homeassistant.helpers.device_registry import DeviceInfo

from .const import (
    CONF_DEVICE_ID,
    CONF_TOPIC_PREFIX,
    DEFAULT_TOPIC_PREFIX,
    DOMAIN,
    EVENT_BUTTON,
    LED_NAMES,
)

_LOGGER = logging.getLogger(__name__)


class McduHub:
    """Owns the MQTT subscriptions for one MCDU device."""

    def __init__(self, hass: HomeAssistant, entry: "McduConfigEntry") -> None:
        self.hass = hass
        self.entry = entry
        self.device_id: str = entry.data[CONF_DEVICE_ID]
        self.prefix: str = entry.data.get(CONF_TOPIC_PREFIX, DEFAULT_TOPIC_PREFIX)
        self.online: bool = False
        self.status: dict[str, Any] = {}
        self._unsubscribers: list = []
        # Set during setup: async callable(button, action) and the controller
        self.button_handler = None
        self.controller = None
        # Local LED state cache (the client does not report LED state back).
        # Backlights carry brightness 0-255, indicator LEDs are boolean.
        self.leds: dict[str, Any] = {name: False for name in LED_NAMES}
        self.leds["BACKLIGHT"] = 128
        self.leds["SCREEN_BACKLIGHT"] = 128

    @property
    def signal_status(self) -> str:
        """Dispatcher signal fired when the device status changes."""
        return f"{DOMAIN}_{self.device_id}_status"

    @property
    def signal_leds(self) -> str:
        """Dispatcher signal fired when an LED value changes."""
        return f"{DOMAIN}_{self.device_id}_leds"

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self.device_id)},
            name=f"MCDU {self.device_id}",
            manufacturer="WinWing",
            model="MCDU-32-CAPTAIN",
        )

    def topic(self, suffix: str) -> str:
        return f"{self.prefix}/{self.device_id}/{suffix}"

    async def async_start(self) -> None:
        self._unsubscribers.append(
            await mqtt.async_subscribe(
                self.hass, self.topic("status/online"), self._status_received, qos=1
            )
        )
        self._unsubscribers.append(
            await mqtt.async_subscribe(
                self.hass, self.topic("buttons/event"), self._button_received, qos=1
            )
        )

    async def async_stop(self) -> None:
        for unsubscribe in self._unsubscribers:
            unsubscribe()
        self._unsubscribers.clear()

    async def async_publish(self, suffix: str, payload: dict, retain: bool = False) -> None:
        """Publish a JSON payload to a device topic."""
        await mqtt.async_publish(
            self.hass, self.topic(suffix), json.dumps(payload), qos=1, retain=retain
        )

    async def async_set_led(self, name: str, value: bool | int) -> None:
        """Set a single LED (bool for indicators, 0-255 for backlights).

        Protocol note: LEDs are published AFTER any display update on the wire;
        callers changing both must render the display first.
        """
        if name not in self.leds:
            _LOGGER.warning("Unknown LED: %s", name)
            return
        self.leds[name] = value
        payload: dict[str, Any] = {"name": name}
        if isinstance(value, bool):
            payload["state"] = value
        else:
            payload["brightness"] = max(0, min(255, int(value)))
        await self.async_publish("leds/single", payload)
        async_dispatcher_send(self.hass, self.signal_leds)

    @callback
    def _status_received(self, msg: mqtt.ReceiveMessage) -> None:
        try:
            payload = json.loads(msg.payload)
        except ValueError:
            _LOGGER.warning("Invalid JSON on %s: %s", msg.topic, msg.payload)
            return
        self.status = payload
        online = payload.get("status") == "online"
        if online != self.online:
            _LOGGER.info("MCDU %s is now %s", self.device_id, payload.get("status"))
        self.online = online
        async_dispatcher_send(self.hass, self.signal_status)

    @callback
    def _button_received(self, msg: mqtt.ReceiveMessage) -> None:
        try:
            payload = json.loads(msg.payload)
        except ValueError:
            _LOGGER.warning("Invalid JSON on %s: %s", msg.topic, msg.payload)
            return
        button = payload.get("button")
        action = payload.get("action")
        if not button or action not in ("press", "release"):
            return
        self.hass.bus.async_fire(
            EVENT_BUTTON,
            {
                "device_id": self.device_id,
                "button": button,
                "action": action,
            },
        )
        if self.button_handler:
            self.hass.async_create_task(self.button_handler(button, action))


McduConfigEntry = ConfigEntry[McduHub]
