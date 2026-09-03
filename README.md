# DALI2MQTT — Home Assistant add-on

DALI ↔ MQTT bridge with Home Assistant MQTT discovery, packaged as an
installable Home Assistant add-on. Fork of
[dali2mqtt](https://github.com/dgomes/dali2mqtt) by
[dgomes](https://github.com/dgomes).

## Install

1. Home Assistant → **Settings → Add-ons → Add-on Store**.
2. **⋮ → Repositories** → add this repository URL:
   `https://github.com/justinasjaronis/dali2mqtt`
3. Install **DALI2MQTT**, set the options, start it.

Full documentation and every option is in [dali2mqtt/DOCS.md](dali2mqtt/DOCS.md).

## What this fork changed

The original was a single-host script with credentials and site-specific data
hard-coded in source. This version is a clean, installable add-on:

- **No secrets in the tree.** MQTT broker is auto-discovered from the Home
  Assistant MQTT service (manual override available); the Home Assistant REST
  API uses the Supervisor proxy + token.
- **Everything is configurable** via add-on options: driver, device path, lamp
  count, group mode, discovery prefix, logging, and the physical-switch map.
- **`switch_map`** replaces the hard-coded `DEVICE_TO_ENTITY_MAP`: mirror
  physical DALI switch presses onto Home Assistant entities from configuration.
- Assorted bug fixes (async flash, group `asyncio` import, `Config.__contains__`,
  broadcast handling) and the removal of the `fuzzywuzzy` dependency.

## Repository layout

```
repository.yaml          # Home Assistant add-on repository descriptor
dali2mqtt/               # the add-on
  config.yaml            # add-on manifest (options + schema)
  build.yaml             # base images per architecture
  Dockerfile
  run.sh                 # bashio entrypoint (MQTT auto-discovery, config build)
  requirements.txt
  DOCS.md
  app/                   # the Python application (run standalone with `python -m app`)
example/                 # udev rule + systemd unit for standalone (non-add-on) use
```

## Running standalone (without the add-on)

```bash
cd dali2mqtt
python3 -m venv venv && . venv/bin/activate
pip install -r requirements.txt
# Use a config path that does not clash with the add-on manifest (config.yaml):
python3 -m app --config ~/dali2mqtt.yaml    # creates an example config on first run
```

## Credits & License

This project is a fork of **[dali2mqtt](https://github.com/dgomes/dali2mqtt)**,
originally created by **Diogo Gomes ([@dgomes](https://github.com/dgomes))**, with
later contributions by **Tobias Albert**. Huge thanks to the original authors —
the DALI &harr; MQTT core builds on their work.

It also builds on **[python-dali](https://github.com/sde1000/python-dali)** by
Simon de Sio and contributors.

Licensed under the **MIT License** — the same license as the upstream project,
so there is no license conflict. All original copyright notices are retained in
[LICENSE](LICENSE); see that file for the full text.

## Development & tests

```bash
cd dali2mqtt
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
pytest                      # 58 unit/module tests, no hardware required
```

Tests use a fake DALI driver (see `tests/conftest.py`); CI runs them on every
push via `.github/workflows/tests.yml`.
