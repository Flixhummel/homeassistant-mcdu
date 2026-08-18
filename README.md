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
| 1 | Page engine port (rendering, colors/segments, pagination), LSK navigation | ⏳ |
| 2 | Live entity values on pages, LSK actions, LED + brightness entities | – |
| 3 | Scratchpad input, validation from entity metadata, confirmation dialogs | – |
| 4 | Configuration panel (sidebar): live display preview, page tree, entity pickers | – |
| 5 | Page generators (from areas/domains), profiles, ioBroker config import | – |
| 6 | HACS release | – |

## Requirements

- Home Assistant 2024.11+ with the **MQTT integration** configured
- A running [`mcdu-client`](https://github.com/Flixhummel/ioBroker.mcdu/tree/main/mcdu-client)
  connected to the same broker

## Installation (development)

Copy `custom_components/mcdu/` into your HA `config/custom_components/` directory and
restart Home Assistant. Then add the integration via *Settings → Devices & Services →
Add Integration → WinWing MCDU*. Devices announcing themselves on
`mcdu/+/status/online` are discovered automatically.

## What you get today (Phase 0)

- **Config flow** with automatic device discovery over MQTT
- **Device** with an `Online` connectivity sensor (from the client's retained status topic)
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
