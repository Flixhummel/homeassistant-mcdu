# WinWing MCDU for Home Assistant

Control your smart home through a WinWing MCDU-32-CAPTAIN aviation cockpit display —
natively integrated into Home Assistant.

```
Home Assistant (this integration)  <-- MQTT -->  mcdu-client (Raspberry Pi)  <-- USB HID -->  WinWing MCDU
```

The Raspberry Pi client is a dumb terminal that bridges MQTT to USB HID. All business
logic (page rendering, navigation, scratchpad input, validation) lives in this
integration. The client and the MQTT protocol are shared with the sibling
[ioBroker adapter](https://github.com/Flixhummel/ioBroker.mcdu) — see its
[`docs/PROTOCOL.md`](https://github.com/Flixhummel/ioBroker.mcdu/blob/main/docs/PROTOCOL.md)
for the canonical protocol specification (v1.0) and `mcdu-client/` for the Pi client.

> **Important:** Only ONE brain may drive a given MCDU at a time. If you previously
> used the ioBroker adapter, stop its instance before enabling this integration.

## Status

Early development. Roadmap (see the concept document in the ioBroker repo,
`docs/HOME-ASSISTANT-CONCEPT.md`):

| Phase | Scope | Status |
|---|---|---|
| 0 | Protocol spec, repo scaffold, config flow with MQTT device discovery, online sensor, button events | ✅ |
| 1 | Page engine port (rendering, colors/segments, pagination), LSK navigation | ✅ |
| 2 | Live entity values on pages, LSK actions, LED + brightness entities | ✅ |
| 3 | Scratchpad input, validation from entity metadata | ✅ (confirmation dialogs pending) |
| 4 | Configuration panel (sidebar): live display preview, page tree, entity pickers | ✅ MVP |
| 5 | Page generators (from areas), function key config | ✅ (profiles + ioBroker import pending) |
| 6 | HACS release | – |

## Requirements

- Home Assistant 2024.11+ with the **MQTT integration** configured
- A running [`mcdu-client`](https://github.com/Flixhummel/ioBroker.mcdu/tree/main/mcdu-client)
  connected to the same broker

## Installation

**Via HACS (recommended):** HACS → Custom repositories → add
`https://github.com/Flixhummel/homeassistant-mcdu` (type: Integration) → download
"WinWing MCDU" → restart Home Assistant.

**Manual:** Copy `custom_components/mcdu/` into your HA `config/custom_components/`
directory and restart Home Assistant.

Then add the integration via *Settings → Devices & Services → Add Integration →
WinWing MCDU*. Devices announcing themselves on `mcdu/+/status/online` are
discovered automatically.

## What you get today

- **Config flow** with automatic device discovery over MQTT
- **Device** with an `Online` connectivity sensor (from the client's retained status topic)
- **Pages on the MCDU display**: configured pages render with sub-labels, left/right
  columns, per-side colors, pagination and a breadcrumb status bar; **live entity
  values** re-render automatically when the underlying entity changes
- **Navigation on the hardware**: LSK keys follow `navigation` buttons,
  `datapoint` buttons toggle/increment/decrement entities, CLR goes to the parent
  page, SLEW left/right cycles sibling pages, SLEW up/down scrolls paginated pages,
  BRT/DIM adjusts both backlights
- **Scratchpad input**: type values on the keypad (line 14), press an LSK next to a
  writable entity to set it — validated against the entity's metadata (numbers:
  min/max, selects: options; read-only entities show SCHREIBGESCHUETZT). Errors
  follow the Airbus pattern: the message replaces the scratchpad, CLR restores your
  input for editing. Double-CLR jumps home; PLUSMINUS toggles the sign
- **Entities**: switches for the 9 indicator LEDs (FAIL, FM, MCDU, ...), brightness
  sliders (0–255) for keyboard and screen backlight
- **MCDU sidebar panel** (admin only) built around an **interactive image of the
  MCDU**: the display (live preview rendered by the same engine that drives the
  hardware), the 12 LSK bars, all function keys and the LED strips are
  clickable. Click an LSK or a display row half to edit that line side (each
  side is simply *nothing, text, an entity, or a page link* — only relevant
  fields appear), click a function key to assign it a page, click an LED to
  bind it to an entity. Save applies instantly to the device
- **"+ Import…" from a dashboard view**: generate a page from any Lovelace
  dashboard view — its entities and names are already curated, so no junk
  comes along. Importing from an HA area is still available as fallback.
  Pages longer than 6 lines paginate automatically
- **Function keys**: DIR, PROG, PERF, INIT, DATA, FPLN, RAD, FUEL, SEC, ATC,
  MENU, AIRPORT each jump to their assigned page from anywhere
- **LED bindings**: each of the 9 indicator LEDs can follow an entity — lit
  while the entity is on / greater than zero (e.g. RDY ← washing machine done)
- **`mcdu_button` events** on the HA event bus for every hardware button
  (`{device_id, button, action}`) — usable in automations right now:

```yaml
triggers:
  - trigger: event
    event_type: mcdu_button
    event_data:
      device_id: mcdu-client-pi
      button: DIR
      action: press
```

## License

MIT — Copyright (c) 2026 Flixhummel
