# Changelog

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
