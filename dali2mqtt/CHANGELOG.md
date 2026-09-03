# Changelog

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
