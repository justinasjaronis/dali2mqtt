"""Entry point for dali2mqtt.

Two modes are supported:

* Add-on / container mode - ``--options-json PATH`` loads a fully resolved
  configuration document (produced by ``run.sh`` from the Home Assistant add-on
  options and the auto-discovered MQTT service). No secrets live in the image.
* Standalone mode - the classic ``--config config.yaml`` plus command-line
  overrides and ``D2M_*`` environment variables.
"""
import argparse
import json
import logging
import os

import voluptuous as vol
import yaml

from .bridge import main as run_bridge
from .consts import (
    ALL_SUPPORTED_GROUP_MODES,
    ALL_SUPPORTED_LOG_LEVELS,
    CONF_CONFIG,
    CONF_CONFIG_EXAMPLE,
    CONF_DALI_DRIVER,
    CONF_DALI_LAMPS,
    CONF_DEVICES_NAMES_FILE,
    CONF_GROUP_MODE,
    CONF_HA_DISCOVERY_PREFIX,
    CONF_LOG_COLOR,
    CONF_LOG_LEVEL,
    CONF_MQTT_BASE_TOPIC,
    CONF_MQTT_PASSWORD,
    CONF_MQTT_PORT,
    CONF_MQTT_SERVER,
    CONF_MQTT_USERNAME,
    CONF_SCHEMA,
    DALI_DRIVERS,
    DEFAULT_CONFIG_FILE,
    LOG_FORMAT,
)

logging.basicConfig(format=LOG_FORMAT)
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Keys that must be coerced when they arrive as strings from the environment.
_INT_KEYS = {CONF_MQTT_PORT, CONF_DALI_LAMPS}
_BOOL_KEYS = {CONF_LOG_COLOR}


def load_json_options(path):
    """Load a fully resolved configuration document (add-on mode)."""
    with open(path, "r", encoding="utf8") as infile:
        logger.info("Loading configuration from %s", path)
        raw = json.load(infile) or {}
    try:
        return CONF_SCHEMA(raw)
    except vol.MultipleInvalid as error:
        logger.error("Invalid configuration in %s: %s", path, error)
        raise SystemExit(1)


def load_config_file(path, create):
    """Load configuration from a YAML file (standalone mode)."""
    try:
        with open(path, "r", encoding="utf8") as infile:
            logger.info("Loading configuration from %s", path)
            configuration = yaml.safe_load(infile)
            if not configuration:
                logger.error("Error loading configuration file %s", path)
                raise SystemExit(1)
            return CONF_SCHEMA(configuration)
    except vol.MultipleInvalid as error:
        logger.error("In configuration file %s: %s", path, error)
        raise SystemExit(1)
    except FileNotFoundError:
        if create:
            logger.info("No configuration file found, creating a new one")
            try:
                with open(path, "w", encoding="utf8") as outfile:
                    yaml.dump(
                        CONF_SCHEMA({}),
                        outfile,
                        default_flow_style=False,
                        allow_unicode=True,
                    )
                logger.info("Example configuration created. Please edit it now!")
            except Exception as err:
                logger.error("Could not save configuration: %s", err)
            raise SystemExit(0)
        logger.info("No configuration file found, using defaults.")
        return CONF_SCHEMA({})


def _coerce_env_value(key, value):
    if key in _INT_KEYS:
        return int(value)
    if key in _BOOL_KEYS:
        return value.strip().lower() in ("1", "true", "yes", "on")
    return value


def apply_env_overrides(config):
    """Overlay ``D2M_<KEY>`` environment variables onto the config."""
    for env_key, env_value in os.environ.items():
        if not env_key.startswith("D2M_"):
            continue
        key = env_key[4:].lower()
        if key not in config:
            logger.warning("Ignoring unknown env override %s", env_key)
            continue
        config[key] = _coerce_env_value(key, env_value)
    return config


def build_arg_parser():
    parser = argparse.ArgumentParser(argument_default=argparse.SUPPRESS)
    parser.add_argument(
        "--options-json",
        help="fully resolved JSON configuration (add-on mode)",
        default=None,
    )
    parser.add_argument(
        f"--{CONF_CONFIG}", help="configuration file", default=DEFAULT_CONFIG_FILE
    )
    parser.add_argument(
        f"--{CONF_CONFIG_EXAMPLE.replace('_', '-')}",
        help="create configuration file example",
        action="store_true",
        default=False,
    )
    parser.add_argument(
        f"--{CONF_DEVICES_NAMES_FILE.replace('_', '-')}", help="devices names file"
    )
    parser.add_argument(f"--{CONF_MQTT_SERVER.replace('_', '-')}", help="MQTT server")
    parser.add_argument(
        f"--{CONF_MQTT_PORT.replace('_', '-')}", help="MQTT port", type=int
    )
    parser.add_argument(
        f"--{CONF_MQTT_USERNAME.replace('_', '-')}", help="MQTT username"
    )
    parser.add_argument(
        f"--{CONF_MQTT_PASSWORD.replace('_', '-')}", help="MQTT password"
    )
    parser.add_argument(
        f"--{CONF_MQTT_BASE_TOPIC.replace('_', '-')}", help="MQTT base topic"
    )
    parser.add_argument(
        f"--{CONF_DALI_DRIVER.replace('_', '-')}",
        help="DALI device driver",
        choices=DALI_DRIVERS,
    )
    parser.add_argument(
        f"--{CONF_DALI_LAMPS.replace('_', '-')}",
        help="Number of lamps to scan",
        type=int,
    )
    parser.add_argument(
        f"--{CONF_HA_DISCOVERY_PREFIX.replace('_', '-')}",
        help="HA discovery mqtt prefix",
    )
    parser.add_argument(
        f"--{CONF_LOG_LEVEL.replace('_', '-')}",
        help="Log level",
        choices=list(ALL_SUPPORTED_LOG_LEVELS),
    )
    parser.add_argument(
        f"--{CONF_LOG_COLOR.replace('_', '-')}",
        help="Coloring output",
        action="store_true",
    )
    parser.add_argument(
        f"--{CONF_GROUP_MODE.replace('_', '-')}",
        help="Group mode",
        choices=ALL_SUPPORTED_GROUP_MODES,
    )
    return parser


def main():
    args = vars(build_arg_parser().parse_args())

    options_json = args.pop("options_json", None)
    if options_json:
        config = load_json_options(options_json)
        run_bridge(config)
        return

    config = load_config_file(args.pop(CONF_CONFIG), args.pop(CONF_CONFIG_EXAMPLE))
    config = apply_env_overrides(config)
    for key, value in args.items():
        config[key] = value

    run_bridge(config)


if __name__ == "__main__":
    main()
