"""Class to represent dali lamps"""
import json

import dali.gear.general as gear

from .config import Config
from .consts import *

from .devicesnamesconfig import DevicesNamesConfig
from .functions import normalize

logging.basicConfig(format=LOG_FORMAT)
logger = logging.getLogger(__name__)


class Lamp:
    def __init__(self, driver, mqtt, dali_lamp):
        self.config = Config()
        logger.setLevel(ALL_SUPPORTED_LOG_LEVELS[self.config[CONF_LOG_LEVEL]])

        self.driver = driver
        self.mqtt = mqtt
        self.dali_lamp = dali_lamp
        self.address = dali_lamp.address

        self.friendly_name = DevicesNamesConfig().get_friendly_name(f"DALI Lamp {self.address}")
        self.device_name = f"lamp_{self.address}"

        self.current_scene = None
        _scenes = []
        for i in range(0, 16):
            v = driver.send(gear.QuerySceneLevel(self.dali_lamp, i)).value
            _scenes.append(v)
        self.scenes = _scenes
        logger.debug(f"Scenes: {json.dumps(self.scenes)}")

        self.groups = []

        self.min_physical_level = self.driver.send(gear.QueryPhysicalMinimum(self.dali_lamp)).value
        self.min_level = self.driver.send(gear.QueryMinLevel(self.dali_lamp)).value
        self.min_levels = max(self.min_physical_level, self.min_level)
        self.max_level = self.driver.send(gear.QueryMaxLevel(self.dali_lamp)).value

        self._getLevelDALI()
        self._register_discovery()
        self._setSceneToNoneMQTT()

        self.mqtt.publish(
            MQTT_BRIGHTNESS_STATE_TOPIC.format(self.config[CONF_MQTT_BASE_TOPIC], self.device_name),
            self.level,
            retain=True,
        )
        self.mqtt.publish(
            MQTT_STATE_TOPIC.format(self.config[CONF_MQTT_BASE_TOPIC], self.device_name),
            MQTT_PAYLOAD_ON if self.level > 0 else MQTT_PAYLOAD_OFF,
            retain=True,
        )
        logger.info(
            "   - short address: %d, actual brightness level: %d (minimum: %d, max: %d, physical minimum: %d)",
            self.address,
            self.level,
            self.min_level,
            self.max_level,
            self.min_physical_level,
        )

    def __repr__(self):
        return f"LAMP A{self.address}"

    __str__ = __repr__

    def addGroup(self, group):
        self.groups.append(group)

    def _register_discovery(self):
        json_config = {
            "name": self.friendly_name,
            "unique_id": f"{self.config[CONF_MQTT_BASE_TOPIC]}_{self.device_name}",
            "state_topic": MQTT_STATE_TOPIC.format(self.config[CONF_MQTT_BASE_TOPIC], self.device_name),
            "command_topic": MQTT_COMMAND_TOPIC.format(
                self.config[CONF_MQTT_BASE_TOPIC], self.device_name
            ),
            "payload_off": MQTT_PAYLOAD_OFF.decode("utf-8"),
            "brightness_state_topic": MQTT_BRIGHTNESS_STATE_TOPIC.format(
                self.config[CONF_MQTT_BASE_TOPIC], self.device_name
            ),
            "brightness_command_topic": MQTT_BRIGHTNESS_COMMAND_TOPIC.format(
                self.config[CONF_MQTT_BASE_TOPIC], self.device_name
            ),
            "brightness_scale": 255,
            "on_command_type": "brightness",
            "availability_topic": MQTT_DALI2MQTT_STATUS.format(self.config[CONF_MQTT_BASE_TOPIC]),
            "payload_available": MQTT_AVAILABLE,
            "payload_not_available": MQTT_NOT_AVAILABLE,
            "device": {
                "identifiers": f"{self.config[CONF_MQTT_BASE_TOPIC]}_A{self.address}",
                "via_device": self.config[CONF_MQTT_BASE_TOPIC],
                "name": f"DALI Lamp {self.address}",
                "sw_version": f"dali2mqtt {VERSION}",
                "manufacturer": AUTHOR,
                "connections": [("DALI", f"A{self.address}")]
            },
        }
        self.mqtt.publish(
            HA_DISCOVERY_PREFIX_LIGHT.format(self.config[CONF_HA_DISCOVERY_PREFIX], self.config[CONF_MQTT_BASE_TOPIC], self.device_name),
            json.dumps(json_config),
            retain=True,
        )

        json_config = {
            "name": self.friendly_name + " Scene",
            "unique_id": f"{self.config[CONF_MQTT_BASE_TOPIC]}_{self.device_name}_scene",
            "state_topic": MQTT_SCENE_STATE_TOPIC.format(self.config[CONF_MQTT_BASE_TOPIC], self.device_name),
            "command_topic": MQTT_SCENE_COMMAND_TOPIC.format(
                self.config[CONF_MQTT_BASE_TOPIC], self.device_name
            ),
            "options": [],
            "availability_topic": MQTT_DALI2MQTT_STATUS.format(self.config[CONF_MQTT_BASE_TOPIC]),
            "payload_available": MQTT_AVAILABLE,
            "payload_not_available": MQTT_NOT_AVAILABLE,
            "device": {
                "identifiers": f"{self.config[CONF_MQTT_BASE_TOPIC]}_A{self.address}",
                "via_device": self.config[CONF_MQTT_BASE_TOPIC],
                "name": f"DALI Lamp {self.address}",
                "sw_version": f"dali2mqtt {VERSION}",
                "manufacturer": AUTHOR,
                "connections": [("DALI", f"A{self.address}")]
            },
        }
        json_config["options"].append("-")
        for index, scene in enumerate(self.scenes):
            if str(scene).upper() != "MASK":
                json_config["options"].append(f"Scene {index}")

        self.mqtt.publish(
            HA_DISCOVERY_PREFIX_SELECT.format(self.config[CONF_HA_DISCOVERY_PREFIX], self.config[CONF_MQTT_BASE_TOPIC], self.device_name),
            json.dumps(json_config),
            retain=True,
        )

    def setLevel(self, level, dali=True):
        if self.level == level:
            return
        old = self.level
        self.level = level

        if dali:
            for _x in self.groups:
                _x.recalc_level()
            self._sendLevelDALI(level)

        self._sendLevelMQTT(level, old)

    def setScene(self, scene):
        self._setSceneToNoneMQTT()
        if 0 <= scene <= 15 and self.scenes[scene] != "MASK":
            level = self.scenes[scene]

            self.mqtt.publish(
                MQTT_SCENE_STATE_TOPIC.format(self.config[CONF_MQTT_BASE_TOPIC], self.device_name), f"Scene {scene}",
                retain=True)
            self.current_scene = scene

            if self.level != level:
                old = self.level
                self.level = level

                for _x in self.groups:
                    _x.recalc_level()
                self._sendSceneDALI(scene)

                self._sendLevelMQTT(level, old)


    def _sendLevelMQTT(self, level, old_level):
        self.mqtt.publish(
            MQTT_BRIGHTNESS_STATE_TOPIC.format(self.config[CONF_MQTT_BASE_TOPIC], self.device_name),
            level,
            retain=True,
        )
        if old_level == 0 or level == 0:
            self.mqtt.publish(
                MQTT_STATE_TOPIC.format(self.config[CONF_MQTT_BASE_TOPIC], self.device_name),
                MQTT_PAYLOAD_ON if level > 0 else MQTT_PAYLOAD_OFF,
                retain=True,
            )

    def _setSceneToNoneMQTT(self):
        self.mqtt.publish(
            MQTT_SCENE_STATE_TOPIC.format(self.config[CONF_MQTT_BASE_TOPIC], self.device_name), "-", retain=True)

    def pollLevel(self):
        old = self.level
        self._getLevelDALI()
        if old != self.level:
            self.mqtt.publish(
                MQTT_BRIGHTNESS_STATE_TOPIC.format(self.config[CONF_MQTT_BASE_TOPIC], self.device_name),
                self.level,
                retain=True,
            )
            self.mqtt.publish(
                MQTT_STATE_TOPIC.format(self.config[CONF_MQTT_BASE_TOPIC], self.device_name),
                MQTT_PAYLOAD_ON if self.level > 0 else MQTT_PAYLOAD_OFF,
                retain=True,
            )

    def _sendLevelDALI(self, level):
        level = normalize(level, 0, 255, self.min_levels, self.max_level)
        self.driver.send(gear.DAPC(self.dali_lamp, level))
        logger.info(f"Set {self.friendly_name} brightness level to {self.level} ({level})")

    def _sendSceneDALI(self, scene):
        self.driver.send(gear.GoToScene(self.dali_lamp, scene))
        logger.info(f"Call scene {scene} on {self.friendly_name}")

    def _getLevelDALI(self):
        level = self.driver.send(gear.QueryActualLevel(self.dali_lamp)).value
        if level == 0:
            self.level = 0
        else:
            self.level = normalize(level, self.min_levels, self.max_level, 0, 255)
        logger.debug(f"Get {self.friendly_name} brightness level {self.level} ({level})")
