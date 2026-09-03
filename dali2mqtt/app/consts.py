"""Constants common to the various modules."""
import logging

import voluptuous as vol

AUTHOR = "Diogo Gomes, TobsA & contributors"
VERSION = "1.0.0"

# --- DALI drivers ---------------------------------------------------------
HASSEB = "hasseb"
MIN_HASSEB_FIRMWARE_VERSION = 2.3
TRIDONIC = "tridonic"
DALI_SERVER = "dali_server"
DALI_DRIVERS = [HASSEB, TRIDONIC, DALI_SERVER]

# --- Configuration keys ---------------------------------------------------
CONF_CONFIG = "config"
CONF_CONFIG_EXAMPLE = "config_example"
CONF_DEVICES_NAMES_FILE = "devices_names"

CONF_MQTT_SERVER = "mqtt_server"
CONF_MQTT_PORT = "mqtt_port"
CONF_MQTT_USERNAME = "mqtt_username"
CONF_MQTT_PASSWORD = "mqtt_password"
CONF_MQTT_BASE_TOPIC = "mqtt_base_topic"
CONF_MQTT_CLIENT_ID = "mqtt_client_id"

CONF_DALI_DRIVER = "dali_driver"
CONF_DALI_DEVICE = "dali_device"
CONF_DALI_LAMPS = "dali_lamps"
CONF_DALI_SERVER_HOST = "dali_server_host"
CONF_DALI_SERVER_PORT = "dali_server_port"

CONF_HA_DISCOVERY_PREFIX = "ha_discovery_prefix"
CONF_GROUP_MODE = "group_mode"

CONF_LOG_LEVEL = "log_level"
CONF_LOG_COLOR = "log_color"

# Physical DALI switch -> Home Assistant entity mirroring
CONF_SWITCH_MAP = "switch_map"
CONF_SWITCH_MAP_ADDRESS = "address"
CONF_SWITCH_MAP_ENTITIES = "entities"
CONF_HA_BASE_URL = "ha_base_url"
CONF_HA_TOKEN = "ha_token"
CONF_HA_VERIFY_SSL = "ha_verify_ssl"

# --- Defaults -------------------------------------------------------------
DEFAULT_CONFIG_FILE = "config.yaml"
DEFAULT_DEVICES_NAMES_FILE = "devices.yaml"

DEFAULT_MQTT_SERVER = "localhost"
DEFAULT_MQTT_PORT = 1883
DEFAULT_MQTT_USERNAME = ""
DEFAULT_MQTT_PASSWORD = ""
DEFAULT_MQTT_BASE_TOPIC = "dali2mqtt"
DEFAULT_MQTT_CLIENT_ID = "dali2mqtt"

DEFAULT_DALI_DRIVER = HASSEB
DEFAULT_DALI_DEVICE = ""
DEFAULT_DALI_LAMPS = 64
DEFAULT_DALI_SERVER_HOST = "localhost"
DEFAULT_DALI_SERVER_PORT = 55825

DEFAULT_HA_DISCOVERY_PREFIX = "homeassistant"
DEFAULT_GROUP_MODE = "mean"

DEFAULT_LOG_LEVEL = "info"
DEFAULT_LOG_COLOR = False

DEFAULT_SWITCH_MAP = []
DEFAULT_HA_BASE_URL = ""
DEFAULT_HA_TOKEN = ""
DEFAULT_HA_VERIFY_SSL = False

ALL_SUPPORTED_LOG_LEVELS = {
    "critical": logging.CRITICAL,
    "error": logging.ERROR,
    "warning": logging.WARNING,
    "info": logging.INFO,
    "debug": logging.DEBUG,
}

ALL_SUPPORTED_GROUP_MODES = ["mean", "max", "min", "off"]

RESET_COLOR = "\x1b[0m"
RED_COLOR = "\x1b[31;21m"
YELLOW_COLOR = "\x1b[33;21m"
LOG_FORMAT = "%(asctime)s %(levelname)s [%(name)s]: %(message)s"

SWITCH_MAP_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_SWITCH_MAP_ADDRESS): vol.All(
            vol.Coerce(int), vol.Range(min=0, max=63)
        ),
        vol.Required(CONF_SWITCH_MAP_ENTITIES): vol.All(
            [str], vol.Length(min=1)
        ),
    }
)

CONF_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_MQTT_SERVER, default=DEFAULT_MQTT_SERVER): str,
        vol.Optional(CONF_MQTT_PORT, default=DEFAULT_MQTT_PORT): vol.All(
            vol.Coerce(int), vol.Range(min=1, max=65535)
        ),
        vol.Optional(CONF_MQTT_USERNAME, default=DEFAULT_MQTT_USERNAME): str,
        vol.Optional(CONF_MQTT_PASSWORD, default=DEFAULT_MQTT_PASSWORD): str,
        vol.Optional(CONF_MQTT_BASE_TOPIC, default=DEFAULT_MQTT_BASE_TOPIC): str,
        vol.Optional(CONF_MQTT_CLIENT_ID, default=DEFAULT_MQTT_CLIENT_ID): str,
        vol.Required(CONF_DALI_DRIVER, default=DEFAULT_DALI_DRIVER): vol.In(
            DALI_DRIVERS
        ),
        vol.Optional(CONF_DALI_DEVICE, default=DEFAULT_DALI_DEVICE): str,
        vol.Optional(CONF_DALI_LAMPS, default=DEFAULT_DALI_LAMPS): vol.All(
            vol.Coerce(int), vol.Range(min=1, max=64)
        ),
        vol.Optional(
            CONF_DALI_SERVER_HOST, default=DEFAULT_DALI_SERVER_HOST
        ): str,
        vol.Optional(CONF_DALI_SERVER_PORT, default=DEFAULT_DALI_SERVER_PORT): vol.All(
            vol.Coerce(int), vol.Range(min=1, max=65535)
        ),
        vol.Optional(
            CONF_HA_DISCOVERY_PREFIX, default=DEFAULT_HA_DISCOVERY_PREFIX
        ): str,
        vol.Optional(CONF_DEVICES_NAMES_FILE, default=DEFAULT_DEVICES_NAMES_FILE): str,
        vol.Optional(CONF_LOG_LEVEL, default=DEFAULT_LOG_LEVEL): vol.In(
            ALL_SUPPORTED_LOG_LEVELS
        ),
        vol.Optional(CONF_LOG_COLOR, default=DEFAULT_LOG_COLOR): bool,
        vol.Optional(CONF_GROUP_MODE, default=DEFAULT_GROUP_MODE): vol.In(
            ALL_SUPPORTED_GROUP_MODES
        ),
        vol.Optional(CONF_SWITCH_MAP, default=DEFAULT_SWITCH_MAP): [SWITCH_MAP_SCHEMA],
        vol.Optional(CONF_HA_BASE_URL, default=DEFAULT_HA_BASE_URL): str,
        vol.Optional(CONF_HA_TOKEN, default=DEFAULT_HA_TOKEN): str,
        vol.Optional(CONF_HA_VERIFY_SSL, default=DEFAULT_HA_VERIFY_SSL): bool,
    },
    extra=False,
)

# --- MQTT topics ----------------------------------------------------------
MQTT_DALI2MQTT_STATUS = "{}/status"
MQTT_STATE_TOPIC = "{}/{}/status"
MQTT_COMMAND_TOPIC = "{}/{}/set"
MQTT_FLASH_TOPIC = "{}/{}/flash"
MQTT_BRIGHTNESS_STATE_TOPIC = "{}/{}/brightness/status"
MQTT_BRIGHTNESS_COMMAND_TOPIC = "{}/{}/brightness/set"
MQTT_SCENE_STATE_TOPIC = "{}/{}/scene/status"
MQTT_SCENE_COMMAND_TOPIC = "{}/{}/scene/set"
MQTT_SCAN_LAMPS_COMMAND_TOPIC = "{}/scan"
MQTT_POLL_LAMPS_COMMAND_TOPIC = "{}/poll"
MQTT_PAYLOAD_ON = b"ON"
MQTT_PAYLOAD_OFF = b"OFF"
MQTT_AVAILABLE = "online"
MQTT_NOT_AVAILABLE = "offline"

HA_DISCOVERY_PREFIX_LIGHT = "{}/light/{}/{}/config"
HA_DISCOVERY_PREFIX_SELECT = "{}/select/{}/{}/config"
HA_DISCOVERY_PREFIX_BUTTON = "{}/button/{}/{}/config"

BUTTONS = [
    {
        "name": "Poll lamps",
        "command_topic": MQTT_POLL_LAMPS_COMMAND_TOPIC,
        "device_class": None,
        "entity_category": "config",
    },
    {
        "name": "Reinitialize lamps",
        "command_topic": MQTT_SCAN_LAMPS_COMMAND_TOPIC,
        "device_class": "restart",
        "entity_category": "config",
    },
]


class SetupError(Exception):
    pass
