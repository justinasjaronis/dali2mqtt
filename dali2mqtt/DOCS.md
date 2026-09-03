# DALI2MQTT — Home Assistant add-on

A DALI &harr; MQTT bridge with Home Assistant MQTT discovery, plus a built-in
web **DALI Config** tool (a small "DALI cockpit") served in the Home Assistant
sidebar via Ingress.

It lets Home Assistant control DALI control gear (lamps/ballasts) and DALI
groups as normal `light` entities, and it can turn physical DALI switch presses
into actions on **any** Home Assistant entity (including non-DALI devices such
as eWeLink/Sonoff, Zigbee, etc.).

Supported DALI interfaces: **Tridonic DALI USB**, **hasseb DALI USB**, and
**daliserver** (TCP). This build ships with python-dali 0.11, which adds
DALI-2 control-device / push-button support.

---

## 1. Installation

1. In Home Assistant go to **Settings → Add-ons → Add-on Store**.
2. Add this repository (**⋮ → Repositories**) if it is not already installed,
   then install **DALI2MQTT**.
3. Make sure you have an **MQTT broker** (e.g. the *Mosquitto broker* add-on)
   and the **MQTT integration** configured in Home Assistant. This add-on
   auto-discovers the broker through the Supervisor MQTT service; you only need
   to set `mqtt_host`/`mqtt_username`/… manually if you use an external broker.
4. Plug the DALI USB interface into the Home Assistant host.
5. Start the add-on, then open **Web UI** (or the **DALI Config** sidebar panel).

The add-on needs `usb`/`udev` access (already declared) and Home Assistant API
access (used for the physical-switch mirror; see §6).

---

## 2. Configuration options

All options are set on the add-on **Configuration** tab.

| Option | Default | Description |
|---|---|---|
| `dali_driver` | `tridonic` | DALI interface driver: `tridonic`, `hasseb`, or `dali_server`. |
| `dali_device` | `/dev/dali/daliusb-*` | Device path (or glob) for the USB interface. For a single fixed adapter you can also use `/dev/hidraw0`. |
| `dali_lamps` | `64` | Upper bound on the number of control gear to scan for (scan stops early once this many are found). |
| `dali_server_host` | `localhost` | Host for the `dali_server` driver. |
| `dali_server_port` | `55825` | Port for the `dali_server` driver. |
| `mqtt_base_topic` | `dali2mqtt` | Root MQTT topic. |
| `ha_discovery_prefix` | `homeassistant` | Home Assistant MQTT discovery prefix. |
| `group_mode` | `mean` | How a group reports its brightness from its members: `mean`, `max`, `min`, or `off`. |
| `log_level` | `info` | `critical`, `error`, `warning`, `info`, or `debug`. |
| `log_color` | `false` | Colorize log output. |
| `mqtt_host` / `mqtt_port` / `mqtt_username` / `mqtt_password` | *(auto)* | Only needed for an external broker; otherwise the Supervisor MQTT service is used. |
| `switch_map` | `[]` | Map physical DALI switches to Home Assistant entities. See §6. |

Example (Configuration tab, YAML view):

```yaml
dali_driver: tridonic
dali_device: "/dev/dali/daliusb-*"
dali_lamps: 64
mqtt_base_topic: dali2mqtt
group_mode: mean
log_level: info
switch_map:
  - address: 10
    entities: ["sport room"]
  - address: 20
    entities: ["dining"]
  - address: 21
    entities: ["facade1", "facade2", "facade3"]
```

---

## 3. Entities created in Home Assistant

On start the add-on scans the DALI bus and publishes MQTT discovery for:

* **`light.dali_lamp_<address>`** — one per control gear found (0–63).
* **`light.dali_group_<group>`** — one per DALI group in use.
* A **scene select** per lamp/group (recall stored DALI scenes).
* Helper **buttons** (e.g. *Poll lamps*, *Reinitialize lamps*).

Friendly names come from `addon_config/devicesnames.yaml` (auto-created on first
run); edit it to rename entities.

Brightness uses the raw DALI range internally; Home Assistant sees a normal
0–255 light. Turning a light off sends `DAPC 0`.

---

## 4. The DALI Config web UI (Ingress)

Open it from the add-on **Web UI** button or the **DALI Config** sidebar panel.
It shares the running bridge's DALI driver, so it never conflicts with normal
operation. While a config operation runs, the bridge pauses its bus-traffic
read-back queue to avoid a feedback storm.

### Control gear (top toolbar → **Scan bus**)

Selecting a gear from the list shows:

* **Actual level** slider + **Max / Off / Identify** buttons. *Identify* blinks
  the fixture so you can locate it.
* **Parameters** — read/write **MIN**, **MAX**, **Power-on** and
  **System-failure** levels, and **Fade time (0–15)** / **Fade rate (1–15)**.
* **Groups** — tick boxes 0–15 to add/remove the fixture from DALI groups.
* **Scenes** — view and set the stored level for scenes 0–15 (leave blank to
  clear a scene).
* **Change short address** — reassign the fixture's DALI short address (0–63).

### Commissioning (top toolbar)

* **Commission (new)** — assign short addresses to currently **unaddressed**
  control gear (safe; existing addresses are kept).
* **Re-address all…** — clears **all** short addresses and reassigns them
  (disruptive: entity names that reference addresses will change).

After addressing changes the UI refreshes Home Assistant discovery. You can
also force this with **Refresh HA entities**.

### Control devices — DALI-2 (top toolbar → **Scan devices**)

Lists DALI-2 control devices (buttons/sensors). Selecting one shows:

* **Identify device**, **Read instances**, **Change short address**.
* **Push-button instance (Part 301)** — read/write the instance **timers**
  (short / double / repeat in 20 ms steps, stuck in seconds) and the
  **emitted-event filter** (which events the button sends: short press, double
  press, long press start/repeat/stop, etc.).

> Note: classic **DALI-1** switches have no address and cannot be scanned. Use
> the **Bus Monitor** to see what they transmit (see §6).

### Bus Monitor (top toolbar → **🔎 Bus monitor**)

A live view of DALI bus traffic. Press a physical switch to see the command it
broadcasts (e.g. `GoToScene(<Group 8>, 4)`, `RecallMaxLevel(...)`, `Off(...)`).
Tick **Hide bridge polling** to show only button/control commands. This is how
you identify a DALI-1 switch and find the address it targets.

### Memory Bank Tool

Available on every gear and control-device detail page.

* **Read** — dump any memory bank (bank / start / count) as hex + ASCII.
  Reading is safe. Bank 0 holds device info (GTIN, firmware, serial).
* **Write byte** — write a single byte to a bank location. The write targets
  **only** the selected device (via the addressed *Enable Write Memory*
  command) and unlocks/relocks the bank automatically.
  **Writing changes device configuration — bank 0 is read-only and wrong values
  can misconfigure a device. Use with care.**

---

## 5. Bus events to MQTT (for automations)

Every observed **external** DALI command (physical button/switch presses,
DALI-2 input events) is published to:

```
<mqtt_base_topic>/bus_event
```

as JSON, for example:

```json
{
  "command": "GoToScene(<group (control gear) 8>,4)",
  "type": "GoToScene",
  "address": 8,
  "destination_kind": "group",
  "destination": "<group (control gear) 8>",
  "response": null
}
```

Queries and internal DTR/memory commands are filtered out. You can trigger a
Home Assistant automation on this topic to control **any** entity:

```yaml
alias: DALI button -> toggle a light
trigger:
  - platform: mqtt
    topic: dali2mqtt/bus_event
condition:
  - condition: template
    value_template: >
      {{ trigger.payload_json.type in ['Off', 'SetFadeTime']
         and trigger.payload_json.address == 20 }}
action:
  - service: homeassistant.toggle
    target:
      entity_id: switch.my_lamp
```

> Home-Assistant-initiated control also appears on `bus_event`, so always match
> the **specific** command your button sends (identify it with the Bus Monitor).

---

## 6. Physical DALI switch → Home Assistant entity (`switch_map`)

For the common case ("press a DALI switch, toggle an HA entity") the add-on has
a built-in mirror, so you usually do **not** need an automation.

### How it works

When the add-on sees an `Off` or `SetFadeTime` command addressed to a DALI
short address listed in `switch_map`, it toggles the mapped Home Assistant
entities. The Home Assistant connection uses the **Supervisor proxy**
automatically — no host or token needs to be configured.

Entities are matched by fuzzy name across `group`, `light`, `fan`, `switch`,
`scene`, `input_boolean` domains, so you can use a friendly name (e.g.
`"dining"`) or an exact `entity_id`.

### Configuring it

1. Open the **Bus Monitor**, press the physical switch, and note the short
   **address** it targets.
2. Add an entry to `switch_map` (see the example in §2):

   ```yaml
   switch_map:
     - address: 20
       entities: ["dining"]        # friendly name or entity_id
     - address: 21
       entities: ["facade1", "facade2", "facade3"]
   ```
3. Save and let the add-on restart. The mapping is stored in the add-on options
   and **persists across restarts**.

### Testing remotely (no physical access)

You can trigger the mirror for a mapped address without pressing the switch, via
the config API (through Ingress):

```
POST /api/simulate_button/<address>
```

This runs the exact entity-resolve + toggle the mirror would do (it does **not**
send anything on the DALI bus). Handy for verifying `switch_map` while away.

---

## 7. Optional: control Home Assistant from an MCP client

Unrelated to the add-on, Home Assistant can expose itself over the Model Context
Protocol via the built-in **Model Context Protocol Server** integration
(Settings → Devices & Services → Add integration → *MCP Server*). An MCP client
(e.g. Claude) can then read state and control entities that are **exposed to
Assist** (Settings → Voice assistants → Expose). This is a Home Assistant
feature, not part of this add-on.

---

## 8. Troubleshooting

* **Nothing happens / entities unavailable** — check the add-on log, confirm the
  DALI USB path (`dali_device`), and that MQTT is connected. All DALI entities
  share one availability topic (`<base>/status`); if a second bridge writes to
  the same topic they will fight — run only one bridge per bus.
* **Scan is slow** — scanning queries all 64 addresses; absent addresses incur a
  short timeout. This is normal.
* **Switch mirror does nothing** — verify the address in the **Bus Monitor**,
  confirm the target entity name resolves, and check the log for
  `HA mirror` / `SUPERVISOR_TOKEN` messages. Test with
  `POST /api/simulate_button/<address>`.
* **DALI-2 push-button config shows 0 instances** — the device has no input
  instances (it may be a controller/PSU, or the switch is DALI-1).

---

## 9. Security notes

* The add-on talks to Home Assistant through the **Supervisor proxy**
  (`http://supervisor/core` + the injected `SUPERVISOR_TOKEN`). No long-lived
  token is stored in the add-on config or source.
* The Memory Bank Tool and commissioning can change device configuration. They
  are intended for setup/maintenance; use deliberately.
