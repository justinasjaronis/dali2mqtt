"""Singleton configuration object."""
import logging

from .consts import (
    CONF_HA_BASE_URL,
    CONF_HA_TOKEN,
    CONF_HA_VERIFY_SSL,
    CONF_MQTT_BASE_TOPIC,
    CONF_MQTT_PASSWORD,
    CONF_MQTT_PORT,
    CONF_MQTT_SERVER,
    CONF_MQTT_USERNAME,
    CONF_SCHEMA,
    CONF_SWITCH_MAP,
    CONF_SWITCH_MAP_ADDRESS,
    CONF_SWITCH_MAP_ENTITIES,
    DEFAULT_MQTT_PASSWORD,
    DEFAULT_MQTT_USERNAME,
    LOG_FORMAT,
    SetupError,
)

logging.basicConfig(format=LOG_FORMAT)
logger = logging.getLogger(__name__)


class Config:
    _instance = None
    _done_setup = False
    _config = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(Config, cls).__new__(cls)
        return cls._instance

    def setup(self, config):
        self._done_setup = True
        self._config = CONF_SCHEMA(config)

    def _did_setup(self):
        if not self._done_setup:
            raise SetupError("Class was not setup properly.")

    def __repr__(self):
        self._did_setup()
        return repr(self._config)

    def __getitem__(self, item):
        self._did_setup()
        if item not in self._config:
            raise IndexError(f"Value {item} not in config")
        return self._config[item]

    def get(self, item, default=None):
        self._did_setup()
        return self._config.get(item, default)

    def __contains__(self, item):
        self._did_setup()
        return item in self._config

    @property
    def mqtt_conf(self):
        self._did_setup()
        return (
            self._config[CONF_MQTT_SERVER],
            self._config[CONF_MQTT_PORT],
            self._config.get(CONF_MQTT_USERNAME, DEFAULT_MQTT_USERNAME),
            self._config.get(CONF_MQTT_PASSWORD, DEFAULT_MQTT_PASSWORD),
            self._config[CONF_MQTT_BASE_TOPIC],
        )

    @property
    def switch_map(self):
        """Return {dali_address: [ha_entity, ...]} for physical-switch mirroring."""
        self._did_setup()
        result = {}
        for entry in self._config.get(CONF_SWITCH_MAP, []):
            result[entry[CONF_SWITCH_MAP_ADDRESS]] = list(
                entry[CONF_SWITCH_MAP_ENTITIES]
            )
        return result

    @property
    def ha_conf(self):
        """Return (base_url, token, verify_ssl) for the Home Assistant REST client."""
        self._did_setup()
        return (
            self._config.get(CONF_HA_BASE_URL, ""),
            self._config.get(CONF_HA_TOKEN, ""),
            self._config.get(CONF_HA_VERIFY_SSL, False),
        )
