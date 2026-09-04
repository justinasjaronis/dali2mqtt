#!/usr/bin/env python3
"""Bridge between a DALI controller and an MQTT bus."""
import asyncio
import functools
import json
import logging
import selectors
import signal
import traceback
from pprint import pformat

import dali.address as address
import dali.gear.general as gear
from dali.command import YesNoResponse
from dali.exceptions import DALIError
from dali.gear.general import Off, SetFadeTime
from asyncio_paho import AsyncioPahoClient
from slugify import slugify

from .config import Config
from .consts import *
from .devicesnamesconfig import DevicesNamesConfig
from .group import Group
from .ha_mirror import HAEntityMirror
from .lamp import Lamp

logging.basicConfig(format=LOG_FORMAT)
logger = logging.getLogger(__name__)

# Shared runtime references so the config web UI can refresh MQTT discovery.
_runtime = {}

# Set while the config web UI performs bus operations (scan/commission/etc.).
# While set, the bridge ignores bus traffic and pauses its read-back queue so
# config operations don't trigger a feedback storm of re-reads on the bus.
config_busy = asyncio.Event()


async def reinit_discovery():
    """Re-scan the DALI bus and refresh Home Assistant MQTT discovery."""
    data_object = _runtime.get("data")
    client = _runtime.get("client")
    if data_object is None or client is None:
        logger.warning("Cannot reinit: bridge not connected yet")
        return
    await initialize_lamps(data_object, client)


def simulate_button(addr):
    """Simulate a physical DALI button press, for testing the HA mirror remotely.

    Directly invokes the same mirror -> Home Assistant toggle that a real
    Off/SetFadeTime command to a mapped address would trigger. Returns a dict
    describing the outcome. (Blocking HTTP inside; call from an executor.)
    """
    data_object = _runtime.get("data")
    if data_object is None:
        return {"ok": False, "error": "bridge not connected yet"}
    mirror = data_object.get("mirror")
    if mirror is None or not getattr(mirror, "enabled", False):
        return {"ok": False, "error": "HA mirror not enabled (check switch_map)"}
    if not mirror.is_mapped(int(addr)):
        return {"ok": False, "error": f"address {addr} not in switch_map"}
    mirror.toggle_address(int(addr))
    return {"ok": True, "address": int(addr)}


def simulate_broadcast(action):
    """Simulate a DALI broadcast all-off / all-on, for remote testing.

    Runs the same mirror.set_all a real broadcast Off/RecallMaxLevel would.
    (Blocking HTTP inside; call from an executor.)
    """
    if action not in ("on", "off"):
        return {"ok": False, "error": "action must be 'on' or 'off'"}
    data_object = _runtime.get("data")
    if data_object is None:
        return {"ok": False, "error": "bridge not connected yet"}
    mirror = data_object.get("mirror")
    if mirror is None or not getattr(mirror, "enabled", False):
        return {"ok": False, "error": "HA mirror not enabled (check switch_map)"}
    mirror.set_all(action)
    return {"ok": True, "action": action, "entities": mirror.all_entities()}


def mirror_action(command, is_lamp_addr=False):
    """Classify a DALI bus command for HA mirroring.

    Returns a ``(action, brightness_pct)`` tuple where action is 'on', 'off' or
    None. RecallMaxLevel -> on 100%, Off -> off. For addresses that are NOT a
    DALI lamp (e.g. a phantom switch address), an arc-power level (DAPC) is
    mirrored as a brightness percentage. DAPC to real lamp addresses is ignored,
    because the bridge itself controls lamps with DAPC (avoids a feedback loop).
    """
    if isinstance(command, Off):
        return ("off", None)
    if isinstance(command, gear.RecallMaxLevel):
        return ("on", 100)
    if not is_lamp_addr and isinstance(command, gear.DAPC):
        level = command.power or 0
        if level == 0:
            return ("off", None)
        return ("on", max(1, round(level / 254 * 100)))
    return (None, None)


def publish_bus_event(command, response):
    """Publish an observed DALI bus command to MQTT as a trigger source.

    This lets Home Assistant automations react to physical DALI buttons/switches
    (including DALI-1, which broadcast scene/level commands) and to DALI-2 input
    events. Queries are skipped. The payload carries the decoded command so an
    automation can match a specific button (identify it with the Bus Monitor).
    """
    client = _runtime.get("client")
    if client is None or command is None:
        return
    name = type(command).__name__
    if name.startswith("Query") or name in (
        "DTR0", "DTR1", "DTR2", "Terminate", "Initialise",
        "Randomise", "Compare", "Withdraw",
        "ReadMemoryLocation", "WriteMemoryLocation", "WriteMemoryLocationNoReply",
    ):
        return
    try:
        base = Config()[CONF_MQTT_BASE_TOPIC]
        dest = getattr(command, "destination", None)
        addr_num = None
        dest_kind = None
        if isinstance(dest, address.Short):
            addr_num, dest_kind = dest.address, "short"
        elif isinstance(dest, address.Group):
            addr_num, dest_kind = dest.group, "group"
        elif isinstance(dest, address.Broadcast):
            dest_kind = "broadcast"
        payload = json.dumps(
            {
                "command": str(command),
                "type": name,
                "address": addr_num,
                "destination_kind": dest_kind,
                "destination": str(dest) if dest is not None else "",
                "response": str(response) if response is not None else None,
            }
        )
        client.publish(f"{base}/bus_event", payload)
    except Exception as err:  # noqa: BLE001
        logger.debug("bus_event publish failed: %s", err)


class _SelectorEventLoopPolicy(asyncio.DefaultEventLoopPolicy):
    """Force a SelectSelector loop (required by some DALI HID drivers)."""

    def new_event_loop(self):
        return asyncio.SelectorEventLoop(selectors.SelectSelector())


asyncio.set_event_loop_policy(_SelectorEventLoopPolicy())


async def scan_lamps(driver):
    """Scan a maximum number of DALI devices."""
    lamps = []
    logger.info("Searching for lamps...")
    config = Config()
    for lamp in range(0, 64):
        try:
            logger.debug("Search for lamp %s", lamp)
            present = await driver.send(
                gear.QueryControlGearPresent(address.Short(lamp))
            )
            if isinstance(present, YesNoResponse) and present.value:
                lamps.append(lamp)
                logger.debug("Found lamp at address %d", lamp)
                if len(lamps) >= config[CONF_DALI_LAMPS]:
                    logger.warning(
                        "All %s configured lamps have been found, stopping scan",
                        config[CONF_DALI_LAMPS],
                    )
                    logger.info("Found %d lamps", len(lamps))
                    return lamps
        except DALIError as err:
            logger.warning("%s not present: %s", lamp, err)

    logger.info("Found %d lamps", len(lamps))
    return lamps


async def scan_groups(dali_driver, lamps):
    logger.info("Scanning for groups...")
    groups = {}
    for lamp in lamps:
        try:
            logger.debug("Search for groups for lamp %s", lamp)
            group1 = (
                await dali_driver.send(gear.QueryGroupsZeroToSeven(address.Short(lamp)))
            ).value.as_integer
            group2 = (
                await dali_driver.send(
                    gear.QueryGroupsEightToFifteen(address.Short(lamp))
                )
            ).value.as_integer

            lamp_groups = []
            for i in range(8):
                checkgroup = 1 << i
                if (group1 & checkgroup) == checkgroup:
                    groups.setdefault(i, []).append(lamp)
                    lamp_groups.append(i)
                if (group2 & checkgroup) != 0:
                    groups.setdefault(i + 8, []).append(lamp)
                    lamp_groups.append(i + 8)

            logger.debug("Lamp %d is in groups %s", lamp, lamp_groups)
        except Exception as err:
            logger.warning("Can't get groups for lamp %s: %s", lamp, err)
    logger.info("Finished scanning for groups")
    return groups


async def initialize_lamps(data_object, client):
    logger.info("Initializing lamps...")
    driver_object = data_object["driver"]
    lamps = await scan_lamps(driver_object)
    logger.info("Getting lamp parameters:")
    for lamp in lamps:
        try:
            _address = address.Short(lamp)
            lamp = Lamp(driver_object, client, _address)
            await lamp.read_current_state()
            data_object["all_lamps"][lamp.address] = lamp
        except Exception as err:
            logger.error("While initializing lamp <%s>: %s", lamp, err)
            logger.debug(traceback.format_exc())
            raise err

    groups = await scan_groups(driver_object, lamps)
    for group, group_lamps in groups.items():
        try:
            _address = address.Group(group)
            _lamps = [data_object["all_lamps"][_x] for _x in group_lamps]
            group = Group(driver_object, client, _address, _lamps)
            for _x in group_lamps:
                data_object["all_lamps"][_x].addGroup(group)
            data_object["all_groups"][group.address] = group
        except Exception as err:
            logger.error("While initializing group <%s>: %s", group, err)
            logger.debug(traceback.format_exc())
            raise err

    devices_names_config = DevicesNamesConfig()
    if devices_names_config.is_devices_file_empty():
        devices_names_config.save_devices_names_file(
            list(data_object["all_lamps"].values())
            + list(data_object["all_groups"].values())
        )

    config = Config()
    client.publish(
        MQTT_DALI2MQTT_STATUS.format(config[CONF_MQTT_BASE_TOPIC]),
        MQTT_AVAILABLE,
        retain=True,
    )
    logger.info("Lamp initialization finished")


def get_light_object(data_object, light):
    try:
        _x = light.split("_")
        light_type = _x[0]
        light = int(_x[1])
    except (KeyError, ValueError):
        logger.error("Invalid topic %s", light)
        return None

    try:
        if light_type == "lamp":
            return data_object["all_lamps"][light]
        if light_type == "group":
            return data_object["all_groups"][light]
        logger.error("%s %s invalid type", light_type, light)
    except KeyError:
        logger.error("Light %s %s doesn't exist", light_type, light)
    return None


async def on_message_cmd(mqtt_client, data_object, msg):
    """Callback on MQTT command message."""
    logger.debug("Command on %s: %s", msg.topic, msg.payload)
    light = get_light_object(data_object, msg.topic.split("/")[1])
    if light is None:
        return
    if msg.payload == MQTT_PAYLOAD_OFF:
        try:
            await light.setLevel(0)
            logger.debug("Set %s to OFF", light.device_name)
        except DALIError as err:
            logger.error("Failed to set %s to OFF: %s", light.device_name, err)


async def on_message_flash(mqtt_client, data_object, msg):
    """Callback on MQTT flash message."""
    logger.debug("Flash on %s: %s", msg.topic, msg.payload)
    light = get_light_object(data_object, msg.topic.split("/")[1])
    if light is None:
        return
    try:
        data = json.loads(msg.payload)
    except ValueError:
        logger.warning("Failed to parse flash payload for %s", light.device_name)
        return

    try:
        await light.flash(data["count"], data["speed"])
    except KeyError:
        logger.warning(
            "Missing parameters in flash payload %s for %s", data, light.device_name
        )


async def on_message_brightness_cmd(mqtt_client, data_object, msg):
    """Callback on MQTT brightness command message."""
    logger.debug("Brightness command on %s: %s", msg.topic, msg.payload)
    light = get_light_object(data_object, msg.topic.split("/")[1])
    if light is None:
        return
    level = msg.payload.decode("utf-8")
    if level.isdigit() and 0 <= int(level) < 256:
        level = int(level)
        try:
            await light.setLevel(level)
            logger.debug("Set %s to %s", light.device_name, level)
        except DALIError as err:
            logger.error("Failed to set %s to %s: %s", light.device_name, level, err)
    else:
        logger.error("Invalid brightness payload for %s: %s", light, level)


async def on_message_scene_cmd(mqtt_client, data_object, msg):
    """Callback on MQTT scene command message."""
    logger.debug("Scene command on %s: %s", msg.topic, msg.payload)
    light = get_light_object(data_object, msg.topic.split("/")[1])
    if light is None:
        return
    scene = msg.payload.decode("utf-8")
    if scene == "-":
        light.setSceneToNoneMQTT()
        return
    parts = scene.split(" ")
    if scene.startswith("Scene ") and len(parts) == 2 and parts[1].isdigit():
        scene = int(parts[1])
        if 0 <= scene <= 15:
            try:
                await light.setScene(scene)
                logger.debug("Set %s to Scene %s", light.device_name, scene)
            except DALIError as err:
                logger.error(
                    "Failed to set %s to Scene %s: %s", light.device_name, scene, err
                )
            return
    logger.error("Invalid scene payload for %s: %s", light, scene)


async def on_message_reinitialize_lamps_cmd(mqtt_client, data_object, msg):
    """Callback on MQTT scan lamps command message."""
    logger.info("Reinitializing lamps")
    config = Config()
    mqtt_client.publish(
        MQTT_DALI2MQTT_STATUS.format(config[CONF_MQTT_BASE_TOPIC]),
        MQTT_NOT_AVAILABLE,
        retain=True,
    )
    await initialize_lamps(data_object, mqtt_client)


async def on_message_ha_online(mqtt_client, data_object, msg):
    """Republish discovery/state when Home Assistant restarts (birth message)."""
    payload = msg.payload.decode() if isinstance(msg.payload, bytes) else msg.payload
    if str(payload).lower() != "online":
        return
    logger.info("Home Assistant came online; republishing lamps")
    await initialize_lamps(data_object, mqtt_client)


async def on_message_poll_lamps_cmd(mqtt_client, data_object, msg):
    """Callback on MQTT poll lamps command message."""
    logger.info("Polling lamps")
    for _x in data_object["all_lamps"].values():
        await _x.pollLevel()
    for _x in data_object["all_groups"].values():
        _x.recalc_level()
    logger.info("Polling lamps finished")


async def on_message(mqtt_client, data_object, msg):  # pylint: disable=W0613
    """Default callback on MQTT message."""
    logger.debug("Unhandled message on %s", msg.topic)


async def on_connect(client, data_object, flags, result):  # pylint: disable=W0613,R0913
    """Callback on connection to MQTT server."""
    config = Config()
    result = client.subscribe(
        [
            (MQTT_COMMAND_TOPIC.format(config[CONF_MQTT_BASE_TOPIC], "+"), 0),
            (MQTT_FLASH_TOPIC.format(config[CONF_MQTT_BASE_TOPIC], "+"), 0),
            (MQTT_BRIGHTNESS_COMMAND_TOPIC.format(config[CONF_MQTT_BASE_TOPIC], "+"), 0),
            (MQTT_SCENE_COMMAND_TOPIC.format(config[CONF_MQTT_BASE_TOPIC], "+"), 0),
            (MQTT_SCAN_LAMPS_COMMAND_TOPIC.format(config[CONF_MQTT_BASE_TOPIC]), 0),
            (MQTT_POLL_LAMPS_COMMAND_TOPIC.format(config[CONF_MQTT_BASE_TOPIC]), 0),
            # Home Assistant birth/will topic: republish on HA restart.
            ("{}/status".format(config[CONF_HA_DISCOVERY_PREFIX]), 0),
        ]
    )
    logger.debug("Subscribe result: %s", result)
    client.publish(
        MQTT_DALI2MQTT_STATUS.format(config[CONF_MQTT_BASE_TOPIC]),
        MQTT_AVAILABLE,
        retain=True,
    )
    # Queue processes state updates triggered by physical DALI bus traffic.
    data_object["queue"] = asyncio.Queue()

    await start_listening_on_dali(data_object)
    await initialize_lamps(data_object, client)
    await register_bridge(client)
    # Expose runtime refs to the config web UI (for discovery refresh).
    _runtime["data"] = data_object
    _runtime["client"] = client
    await asyncio.create_task(process_queue(client, data_object))


async def register_bridge(client):
    logger.info("Registering bridge buttons")
    config = Config()
    for button in BUTTONS:
        json_config = {
            "name": button["name"],
            "unique_id": "{}_BUTTON_{}".format(
                config[CONF_MQTT_BASE_TOPIC], slugify(button["name"])
            ),
            "command_topic": button["command_topic"].format(
                config[CONF_MQTT_BASE_TOPIC]
            ),
            "entity_category": button["entity_category"],
            "availability_topic": MQTT_DALI2MQTT_STATUS.format(
                config[CONF_MQTT_BASE_TOPIC]
            ),
            "payload_available": MQTT_AVAILABLE,
            "payload_not_available": MQTT_NOT_AVAILABLE,
            "device": {
                "identifiers": config[CONF_MQTT_BASE_TOPIC],
                "name": "DALI2MQTT Bridge",
                "sw_version": VERSION,
                "manufacturer": AUTHOR,
            },
        }
        if button.get("device_class") is not None:
            json_config["device_class"] = button["device_class"]

        logger.debug("Register button %s", button["name"])
        client.publish(
            HA_DISCOVERY_PREFIX_BUTTON.format(
                config[CONF_HA_DISCOVERY_PREFIX],
                config[CONF_MQTT_BASE_TOPIC],
                slugify(button["name"]),
            ),
            json.dumps(json_config),
            retain=True,
        )


async def on_connect_fail(client, data, flags):
    logger.error("Failure to connect to MQTT")


def on_subscribe(client, *args):
    logger.debug("Subscribed to MQTT: %s", args)


async def process_queue(client, data_object):
    while True:
        item = await data_object["queue"].get()
        logger.debug("Got item from update queue: %s", item)
        # Give the lamp time to settle on its final state before reading it back.
        await asyncio.sleep(2)
        if config_busy.is_set():
            # A config operation owns the bus; drop this queued read-back.
            continue
        try:
            if item in data_object["all_lamps"]:
                await data_object["all_lamps"][item].read_current_state()
        except Exception as err:
            logger.error("Failure to update lamp %s: %s", item, err)


async def create_mqtt_client(driver_object, mirror):
    """Create the MQTT client, set up callbacks and connect to the server."""
    config = Config()
    logger.debug(
        "Connecting to %s:%s", config[CONF_MQTT_SERVER], config[CONF_MQTT_PORT]
    )
    data = {
        "driver": driver_object,
        "all_lamps": {},
        "all_groups": {},
        "mirror": mirror,
    }
    mqttc = AsyncioPahoClient(
        client_id=config[CONF_MQTT_CLIENT_ID], userdata=data
    )
    mqttc.enable_logger(logger)

    mqttc.will_set(
        MQTT_DALI2MQTT_STATUS.format(config[CONF_MQTT_BASE_TOPIC]),
        MQTT_NOT_AVAILABLE,
        retain=True,
    )

    mqttc.asyncio_listeners.add_on_connect(on_connect)
    mqttc.asyncio_listeners.add_on_connect_fail(on_connect_fail)

    for topic, callback in [
        (MQTT_COMMAND_TOPIC.format(config[CONF_MQTT_BASE_TOPIC], "+"), on_message_cmd),
        (MQTT_FLASH_TOPIC.format(config[CONF_MQTT_BASE_TOPIC], "+"), on_message_flash),
        (
            MQTT_BRIGHTNESS_COMMAND_TOPIC.format(config[CONF_MQTT_BASE_TOPIC], "+"),
            on_message_brightness_cmd,
        ),
        (
            MQTT_SCENE_COMMAND_TOPIC.format(config[CONF_MQTT_BASE_TOPIC], "+"),
            on_message_scene_cmd,
        ),
        (
            MQTT_SCAN_LAMPS_COMMAND_TOPIC.format(config[CONF_MQTT_BASE_TOPIC]),
            on_message_reinitialize_lamps_cmd,
        ),
        (
            MQTT_POLL_LAMPS_COMMAND_TOPIC.format(config[CONF_MQTT_BASE_TOPIC]),
            on_message_poll_lamps_cmd,
        ),
        (
            "{}/status".format(config[CONF_HA_DISCOVERY_PREFIX]),
            on_message_ha_online,
        ),
    ]:
        mqttc.asyncio_listeners.message_callback_add(topic, callback)
    mqttc.asyncio_listeners.add_on_message(on_message)

    if config[CONF_MQTT_USERNAME] != "":
        mqttc.username_pw_set(
            config[CONF_MQTT_USERNAME], config[CONF_MQTT_PASSWORD]
        )
    await mqttc.asyncio_connect(
        config[CONF_MQTT_SERVER], config[CONF_MQTT_PORT], 180
    )


def print_command_and_response(data_object, dev, command, response, config_command_error):
    """Sync callback to process messages coming from the DALI bus."""
    if config_busy.is_set():
        # The config web UI owns the bus; ignore its traffic to avoid a storm.
        return
    try:
        if config_command_error:
            logger.error("Failed config command: %s", command)
            return
        if not command:
            logger.info("%s -> %s", command, response)
            return
        if not hasattr(command, "destination"):
            return

        logger.debug("Received command %s", command)
        # Surface external bus activity (button/switch presses) to HA via MQTT.
        publish_bus_event(command, response)
        mirror = data_object.get("mirror")
        if isinstance(command.destination, (address.Group, address.Broadcast)):
            # Broadcast/group command: re-read every known lamp.
            for addr in data_object["all_lamps"]:
                data_object["queue"].put_nowait(addr)
            # Mirror a whole-house broadcast all-off / all-on (e.g. a bedside
            # "everything off" switch) onto the mapped Home Assistant entities.
            # is_lamp_addr=True keeps this to RecallMax/Off only (no DAPC dimming).
            action, _bpct = mirror_action(command, is_lamp_addr=True)
            if (
                action
                and isinstance(command.destination, address.Broadcast)
                and mirror is not None
                and mirror.enabled
            ):
                try:
                    asyncio.get_event_loop().run_in_executor(
                        None, mirror.set_all, action
                    )
                except RuntimeError:
                    mirror.set_all(action)
            return

        addr = command.destination.address
        if not isinstance(
            command,
            (
                gear.QuerySceneLevel,
                gear.QueryActualLevel,
                gear.QueryMaxLevel,
                gear.QueryMinLevel,
                gear.QueryPhysicalMinimum,
                gear.QueryControlGearPresent,
                gear.QueryGroupsZeroToSeven,
                gear.QueryGroupsEightToFifteen,
            ),
        ):
            data_object["queue"].put_nowait(addr)

        # A physical switch mapped to this address: RecallMaxLevel -> turn the
        # HA entity on (brightness-capable lights follow the level), Off -> off.
        is_lamp = addr in data_object["all_lamps"]
        action, bpct = mirror_action(command, is_lamp_addr=is_lamp)
        if mirror is not None and action and mirror.is_mapped(addr):
            # set_address makes blocking HTTP calls to Home Assistant; run it
            # in a thread so it never stalls the asyncio event loop.
            try:
                asyncio.get_event_loop().run_in_executor(
                    None, mirror.set_address, addr, action, bpct
                )
            except RuntimeError:
                mirror.set_address(addr, action, bpct)
    except Exception as err:
        logger.error("Error processing DALI bus command: %s", err)


async def start_listening_on_dali(data_object):
    """Start listening on the DALI bus."""
    dev = data_object["driver"]
    dev.bus_traffic.register(functools.partial(print_command_and_response, data_object))
    dev.connect()
    logger.debug("Waiting for device...")
    await dev.connected.wait()
    logger.info(
        "Connected, firmware=%s, serial=%s", dev.firmware_version, dev.serial
    )


def build_driver(config, event_loop):
    """Instantiate the configured DALI driver."""
    driver_name = config[CONF_DALI_DRIVER]
    logger.debug("Using <%s> driver", driver_name)

    if driver_name == HASSEB:
        # python-dali 0.11: async hasseb driver lives in dali.driver.hid
        from dali.driver.hid import hasseb

        device = config[CONF_DALI_DEVICE] or "/dev/dali/hasseb-*"
        return hasseb(device)

    if driver_name == TRIDONIC:
        from dali.driver.hid import tridonic

        # python-dali 0.11 dropped the glob/loop kwargs; pass the device path
        # (a plain path or a glob such as /dev/hidraw0 or /dev/dali/daliusb-*).
        device = config[CONF_DALI_DEVICE] or "/dev/dali/daliusb-*"
        return tridonic(device)

    if driver_name == DALI_SERVER:
        from dali.driver.daliserver import DaliServer

        return DaliServer(
            config[CONF_DALI_SERVER_HOST], config[CONF_DALI_SERVER_PORT]
        )

    raise SetupError(f"Unsupported DALI driver: {driver_name}")


def main(args):
    event_loop = asyncio.get_event_loop()
    config = Config()
    config.setup(args)

    if config[CONF_LOG_COLOR]:
        logging.addLevelName(
            logging.WARNING,
            "{}{}{}".format(
                YELLOW_COLOR, logging.getLevelName(logging.WARNING), RESET_COLOR
            ),
        )
        logging.addLevelName(
            logging.ERROR,
            "{}{}{}".format(
                RED_COLOR, logging.getLevelName(logging.ERROR), RESET_COLOR
            ),
        )

    logging.getLogger().setLevel(ALL_SUPPORTED_LOG_LEVELS[config[CONF_LOG_LEVEL]])
    logger.setLevel(ALL_SUPPORTED_LOG_LEVELS[config[CONF_LOG_LEVEL]])

    devices_names_config = DevicesNamesConfig()
    devices_names_config.setup()

    mirror = HAEntityMirror(config.switch_map, *config.ha_conf)
    if config.switch_map and not mirror.enabled:
        logger.warning(
            "switch_map is configured but the Home Assistant connection is not; "
            "physical switch mirroring is disabled"
        )

    dali_driver = build_driver(config, event_loop)

    def handle_sigint(signame, loop):
        logger.info("Received %s, disconnecting", signame)
        dali_driver.disconnect()
        loop.stop()

    event_loop.add_signal_handler(
        signal.SIGINT,
        functools.partial(handle_sigint, "SIGINT", event_loop),
    )
    event_loop.add_signal_handler(
        signal.SIGTERM,
        functools.partial(handle_sigint, "SIGTERM", event_loop),
    )

    asyncio.ensure_future(create_mqtt_client(dali_driver, mirror))

    # Start the DALI config web UI (Home Assistant Ingress). Optional: if
    # aiohttp is unavailable the bridge still runs without the UI.
    try:
        from .webserver import DaliWebServer

        web = DaliWebServer(
            dali_driver, config, reinit=reinit_discovery, busy=config_busy,
            simulate=simulate_button, simulate_broadcast=simulate_broadcast, port=8099,
        )
        asyncio.ensure_future(web.start())
    except Exception as err:  # noqa: BLE001
        logger.error("Config web UI not started: %s", err)

    event_loop.run_forever()
    logger.info("Shutting down")
