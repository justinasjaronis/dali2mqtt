# Changelog

## 1.5.0

- Config UI: added a **Memory Bank Tool** (like DALI Cockpit) — read any memory
  bank of a control gear or control device as a hex/ASCII dump, and write a
  single byte to a location. Writes are targeted to one device via the addressed
  ENABLE WRITE MEMORY command and unlock/relock the bank automatically.

## 1.4.0

- Config UI: added a **Bus Monitor** — a live view of DALI bus traffic. DALI-1
  switches/sensors have no address and cannot be scanned, but pressing one
  broadcasts a command that now shows up here (scene/level/off + target group),
  so you can identify and document what each physical button does.

## 1.3.0

- Config UI: added DALI-2 **control device** (button/sensor) support — scan,
  identify, read instances, and change short address. Requires python-dali
  0.11. (Lunatone button-to-action mapping lives in proprietary device config
  and is not exposed by the generic DALI-2 protocol.)

## 1.2.1

- Config UI: pause the bridge's bus-traffic read-back queue during config
  operations (scan/commission/etc.) to avoid a DALI re-read storm that made
  scanning extremely slow.

## 1.2.0

- New: built-in **DALI Config** web UI (a small DALI-cockpit), served in the
  Home Assistant sidebar via Ingress. Scan the bus, identify/blink gear, set
  level, MIN/MAX/power-on/system-failure levels and fade time/rate, edit group
  membership and scene levels, change a gear's short address, and run DALI
  commissioning (assign new addresses or re-address all). Shares the bridge's
  DALI driver (no bus contention).

## 1.1.0

- Upgraded python-dali 0.9 -> 0.11 (adds DALI-2 control device / push-button
  support, and asyncio compatibility with Python 3.10+).
- build_driver adapted to the 0.11 driver API (tridonic/hasseb no longer take
  glob/loop kwargs).

## 1.0.0

- Repackaged as an installable Home Assistant add-on.
- Removed all hard-coded configuration (MQTT credentials, Home Assistant IP and
  long-lived token, DALI address→entity map, device paths).
- MQTT broker auto-discovered from the Home Assistant MQTT service, with manual
  override.
- Physical DALI switch → Home Assistant entity mirroring is now configuration
  driven (`switch_map`) and uses the Supervisor proxy + token.
- Bug fixes: blocking `time.sleep` in async lamp flash, missing `asyncio`
  import in groups, inverted `Config.__contains__`, broadcast handler iterating
  dict items instead of addresses.
- Dropped the `fuzzywuzzy` dependency (uses the standard library instead).
