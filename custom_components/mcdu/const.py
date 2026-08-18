"""Constants for the WinWing MCDU integration."""

from __future__ import annotations

DOMAIN = "mcdu"

CONF_DEVICE_ID = "device_id"
CONF_TOPIC_PREFIX = "topic_prefix"

DEFAULT_TOPIC_PREFIX = "mcdu"

# Seconds to wait for retained status messages during discovery
DISCOVERY_TIMEOUT = 1.5

# Event fired on the HA bus for every hardware button press/release
EVENT_BUTTON = "mcdu_button"

# Display geometry (see docs/PROTOCOL.md in the ioBroker.mcdu repository)
DISPLAY_LINES = 14
DISPLAY_COLS = 24

COLORS = [
    "white",
    "amber",
    "cyan",
    "green",
    "magenta",
    "red",
    "yellow",
    "grey",
    "blue",
]

# Configurable function keys (physical layout order on the WinWing MCDU)
FUNCTION_KEYS = [
    "DIR",
    "PROG",
    "PERF",
    "INIT",
    "DATA",
    "FPLN",
    "RAD",
    "FUEL",
    "SEC",
    "ATC",
    "MENU",
    "AIRPORT",
]

LED_NAMES = [
    "FAIL",
    "FM",
    "MCDU",
    "MENU",
    "FM1",
    "IND",
    "RDY",
    "STATUS",
    "FM2",
    "BACKLIGHT",
    "SCREEN_BACKLIGHT",
]
