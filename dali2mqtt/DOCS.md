# DALI2MQTT add-on

Bridges a DALI lighting controller to MQTT and exposes every lamp and group to
Home Assistant through MQTT discovery. This is a Home Assistant add-on wrapper
around [dali2mqtt](https://github.com/dgomes/dali2mqtt).

## Installation

1. In Home Assistant go to **Settings → Add-ons → Add-on Store**.
2. Open the **⋮** menu → **Repositories** and add:
   `https://github.com/justinasjaronis/dali2mqtt`
3. Install **DALI2MQTT**, configure the options below, then start it.

An MQTT broker is required. If you run the **Mosquitto broker** add-on, the
connection is detected automatically — you do not need to set any MQTT option.

## Hardware access

The add-on requests USB access (`usb: true`, `udev: true`). Plug your DALI USB
controller into the Home Assistant host.

- **Tridonic DALI-USB** (default): the driver globs `dali_device`
  (`/dev/dali/daliusb-*` by default). If that symlink does not exist inside the
  container, set `dali_device` to the raw HID node, e.g. `/dev/hidraw0`.
- **hasseb**: set `dali_driver: hasseb`. `dali_device` is ignored.
- **daliserver**: set `dali_driver: dali_server` and point
  `dali_server_host` / `dali_server_port` at your daliserver instance.

## Options

| Option | Default | Description |
| --- | --- | --- |
| `dali_driver` | `tridonic` | DALI driver: `hasseb`, `tridonic`, `dali_server`. |
| `dali_device` | `/dev/dali/daliusb-*` | Device path/glob for USB drivers. |
| `dali_lamps` | `64` | Maximum number of lamps to scan (1–64). |
| `dali_server_host` | `localhost` | daliserver host (only for `dali_server`). |
| `dali_server_port` | `55825` | daliserver port. |
| `mqtt_base_topic` | `dali2mqtt` | Base MQTT topic. |
| `ha_discovery_prefix` | `homeassistant` | MQTT discovery prefix. |
| `group_mode` | `mean` | How a group level is derived: `mean`, `max`, `min`, `off`. |
| `log_level` | `info` | `critical`, `error`, `warning`, `info`, `debug`. |
| `log_color` | `false` | Colorize log output. |
| `mqtt_host` | _(unset)_ | Manual MQTT host. Leave empty to auto-detect the MQTT service. |
| `mqtt_port` | _(unset)_ | Manual MQTT port. |
| `mqtt_username` | _(unset)_ | Manual MQTT username. |
| `mqtt_password` | _(unset)_ | Manual MQTT password. |
| `switch_map` | `[]` | Mirror physical DALI switch presses onto HA entities (see below). |

## Physical switch mirroring (`switch_map`)

Some DALI installations have wall switches wired to DALI addresses. When such a
switch is pressed the address emits a `SetFadeTime`/`Off` command on the bus.
`switch_map` lets you toggle Home Assistant entities in response — for example
to fold a DALI-controlled zone into an HA scene or group.

The Home Assistant connection uses the Supervisor proxy and token
automatically; no IP address or long-lived token is required.

```yaml
switch_map:
  - address: 22
    entities:
      - gate
  - address: 25
    entities:
      - livingTerrace
      - sonas_curtain
```

Entities are matched fuzzily against their `friendly_name` or `entity_id` among
the `light`, `switch`, `group`, `fan`, `scene` and `input_boolean` domains.

## Friendly names

Lamp/group friendly names are stored in `/data/devices.yaml` (persisted across
restarts). On first run it is populated with every discovered address; edit it
and restart to rename entities.
