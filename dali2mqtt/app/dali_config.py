"""DALI bus configuration helpers (a small "cockpit" backend).

All operations share the running bridge's python-dali driver. The driver
serialises access through its ``transaction_lock`` (and repeats config commands
twice as required by DALI), so config actions and the normal bridge traffic can
safely interleave. Long, disruptive operations (commissioning) run through
``driver.run_sequence`` which holds the transaction lock for their whole
duration.
"""
import asyncio
import contextlib
import logging
import time
from collections import deque

import dali.address as address
import dali.gear.general as gear
from dali.command import YesNoResponse
from dali.exceptions import DALIError
from dali.sequences import Commissioning

try:
    import dali.gear.colour as _colour
except Exception:  # noqa: BLE001
    _colour = None
try:
    import dali.gear.emergency as _emergency
except Exception:  # noqa: BLE001
    _emergency = None

try:
    from dali.memory import diagnostics as _mem_diag
    from dali.memory import energy as _mem_energy
    from dali.memory import info as _mem_info
    from dali.memory import maintenance as _mem_maint
    from dali.memory import oem as _mem_oem
    from dali.memory.location import MemoryType as _MemoryType
    from dali.memory.location import MemoryValue as _MemoryValue

    _MEM_RW_TYPES = {
        _MemoryType.RAM_RW,
        _MemoryType.NVM_RW,
        _MemoryType.NVM_RW_L,
        _MemoryType.NVM_RW_P,
    }

    # Typed memory-bank groups (spec-accurate, from python-dali) — the data
    # behind a Cockpit-style typed "device page".
    _MEMORY_GROUPS = [
        ("Device info", _mem_info),
        ("OEM / luminaire", _mem_oem),
        ("Energy", _mem_energy),
        ("Diagnostics", _mem_diag),
        ("Maintenance", _mem_maint),
    ]
    _HAVE_MEMORY = True
except Exception:  # noqa: BLE001
    _MEMORY_GROUPS = []
    _MemoryValue = None
    _HAVE_MEMORY = False

try:
    import dali.device.general as device
    import dali.device.sequences as devseq
    from dali.device import pushbutton as pb
    from dali.device.general import EventScheme
    from dali.address import InstanceNumber

    _HAVE_DEVICE = True
except ImportError:  # python-dali < 0.11
    device = None
    devseq = None
    pb = None
    EventScheme = None
    InstanceNumber = None
    _HAVE_DEVICE = False

# Push-button instance event names (Part 301 Table 3), low bit first.
PB_EVENTS = [
    "button_released",
    "button_pressed",
    "short_press",
    "double_press",
    "long_press_start",
    "long_press_repeat",
    "long_press_stop",
    "button_stuck_free",
]

logger = logging.getLogger(__name__)

BROADCAST = address.Broadcast()


def _val(resp):
    """Extract an integer value from a query response, or None."""
    try:
        v = resp.value
    except Exception:
        return None
    if v is None:
        return None
    # Some responses expose the raw frame; prefer its integer form.
    if hasattr(v, "as_integer"):
        try:
            return int(v.as_integer)
        except Exception:
            return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


class DaliConfig:
    def __init__(self, driver, busy=None):
        self.driver = driver
        # Serialises multi-command config operations against each other.
        self._lock = asyncio.Lock()
        # Optional asyncio.Event the bridge watches to pause its bus traffic
        # while a config operation is running (prevents a re-read storm).
        self._busy = busy
        # Bus monitor: a ring buffer of recent bus frames, for spotting what a
        # (DALI-1) push-button transmits when pressed.
        self._monitor = deque(maxlen=400)
        self._mon_seq = 0
        self._mon_registered = False

    async def _ready(self):
        await self.driver.connected.wait()

    # ------------------------------------------------------------- bus monitor
    def _ensure_monitor(self):
        if not self._mon_registered:
            try:
                self.driver.bus_traffic.register(self._on_traffic)
                self._mon_registered = True
            except Exception as err:  # noqa: BLE001
                logger.error("Could not register bus monitor: %s", err)

    def _on_traffic(self, dev, command, response, config_command_error):
        try:
            self._mon_seq += 1
            ctype = type(command).__name__ if command is not None else ""
            caddr = None
            dest = getattr(command, "destination", None)
            if isinstance(dest, address.Short):
                caddr = dest.address
            self._monitor.append(
                {
                    "seq": self._mon_seq,
                    "t": time.strftime("%H:%M:%S"),
                    "cmd": str(command) if command is not None else "",
                    "type": ctype,
                    "address": caddr,
                    "resp": str(response) if response is not None else "",
                    "err": bool(config_command_error),
                }
            )
        except Exception:  # noqa: BLE001
            pass

    def monitor_events(self, since=0):
        """Return buffered bus frames newer than ``since`` (registers on first use)."""
        self._ensure_monitor()
        return [e for e in self._monitor if e["seq"] > since]

    def recent_switch_addresses(self, limit=5):
        """Most-recent short addresses seen sending switch commands (for 'learn')."""
        self._ensure_monitor()
        seen = []
        for e in reversed(self._monitor):
            if e.get("type") in ("RecallMaxLevel", "Off") and e.get("address") is not None:
                a = e["address"]
                if a not in seen:
                    seen.append(a)
            if len(seen) >= limit:
                break
        return seen

    @contextlib.asynccontextmanager
    async def _guard(self):
        """Own the bus for one operation: pause the bridge, serialise access."""
        async with self._lock:
            if self._busy is not None:
                self._busy.set()
            try:
                yield
            finally:
                if self._busy is not None:
                    self._busy.clear()

    # ------------------------------------------------------------------ scan
    async def scan_gear(self, addresses=range(64)):
        """Scan control gear and return a list of dicts describing each one."""
        await self._ready()
        result = []
        async with self._guard():
            for a in addresses:
                short = address.Short(a)
                try:
                    present = await self.driver.send(gear.QueryControlGearPresent(short))
                except DALIError:
                    continue
                if not (isinstance(present, YesNoResponse) and present.value):
                    continue
                info = {"address": a}
                info["level"] = _val(await self._q(gear.QueryActualLevel(short)))
                info["min_level"] = _val(await self._q(gear.QueryMinLevel(short)))
                info["max_level"] = _val(await self._q(gear.QueryMaxLevel(short)))
                info["physical_min"] = _val(
                    await self._q(gear.QueryPhysicalMinimum(short))
                )
                info["power_on_level"] = _val(
                    await self._q(gear.QueryPowerOnLevel(short))
                )
                info["system_failure_level"] = _val(
                    await self._q(gear.QuerySystemFailureLevel(short))
                )
                info["device_type"] = _val(await self._q(gear.QueryDeviceType(short)))
                info["groups"] = await self._read_groups(short)
                result.append(info)
        logger.info("Config scan found %d control gear", len(result))
        return result

    def memory_supported(self):
        return _HAVE_MEMORY

    @staticmethod
    def _mem_value_classes(module):
        out = []
        for name, obj in vars(module).items():
            if (
                isinstance(obj, type)
                and issubclass(obj, _MemoryValue)
                and getattr(obj, "locations", None)
                and obj.__module__ == module.__name__
                and not name.endswith("_legacy")
            ):
                out.append((name, obj))
        return out

    async def read_typed_memory(self, addr):
        """Read all standard typed memory-bank values (spec-accurate).

        Produces a Cockpit-style typed device page: grouped, decoded fields
        (device info, OEM/luminaire, energy, diagnostics, maintenance). Each
        bank is read once and decoded locally.
        """
        if not _HAVE_MEMORY:
            raise RuntimeError("python-dali memory module not available")
        await self._ready()
        short = address.Short(addr)
        groups = []
        async with self._guard():
            for group_name, module in _MEMORY_GROUPS:
                # bank -> [(name, cls)]
                banks = {}
                for name, cls in self._mem_value_classes(module):
                    banks.setdefault(cls.bank.address, []).append((name, cls))
                fields = []
                for bank in sorted(banks):
                    row = await self._read_whole_bank(short, bank)
                    if not row:
                        continue
                    for name, cls in banks[bank]:
                        try:
                            val = cls.from_list(row)
                        except Exception:  # noqa: BLE001 - not implemented on device
                            continue
                        fields.append(
                            {
                                "name": name,
                                "bank": bank,
                                "value": self._mem_display(val),
                                "writeable": all(
                                    loc.type_ in _MEM_RW_TYPES for loc in cls.locations
                                ),
                            }
                        )
                if fields:
                    groups.append({"group": group_name, "fields": fields})
        return {"address": addr, "groups": groups}

    async def _read_whole_bank(self, short, bank):
        """Read locations 0..last of a memory bank; returns a list indexed by
        address, or None if the bank is not implemented."""

        def _seq():
            yield gear.DTR1(int(bank))
            yield gear.DTR0(0)
            r = yield gear.ReadMemoryLocation(short)
            last = self._resp_byte(r)
            if last is None:
                return None
            row = [last]
            for _ in range(int(last)):
                r = yield gear.ReadMemoryLocation(short)
                row.append(self._resp_byte(r))
            return row

        try:
            return await self.driver.run_sequence(_seq())
        except DALIError:
            return None

    @staticmethod
    def _mem_display(val):
        if isinstance(val, (bytes, bytearray)):
            return val.hex()
        try:
            import enum

            if isinstance(val, enum.Enum):
                return val.name
        except Exception:  # noqa: BLE001
            pass
        return str(val)

    # ----------------------------------------------------- DALI command console
    _CONSOLE_COMMANDS = {
        "off": ("Off", None),
        "recall_max": ("RecallMaxLevel", None),
        "recall_min": ("RecallMinLevel", None),
        "up": ("Up", None),
        "down": ("Down", None),
        "step_up": ("StepUp", None),
        "step_down": ("StepDown", None),
        "on_and_step_up": ("OnAndStepUp", None),
        "goto_last_active": ("GoToLastActiveLevel", None),
        "dapc": ("DAPC", "level"),          # arg 0-254
        "goto_scene": ("GoToScene", "scene"),  # arg 0-15
    }

    def _target(self, kind, addr):
        if kind == "broadcast":
            return address.Broadcast()
        if kind == "group":
            return address.Group(int(addr))
        return address.Short(int(addr))

    async def send_command(self, kind, addr, command, arg=None):
        """Send one curated DALI command to a short/group/broadcast target."""
        if command not in self._CONSOLE_COMMANDS:
            raise ValueError(f"unknown command {command}")
        await self._ready()
        cls_name, arg_kind = self._CONSOLE_COMMANDS[command]
        dest = self._target(kind, addr)
        cls = getattr(gear, cls_name)
        async with self._guard():
            if command == "dapc":
                cmd = gear.DAPC(dest, int(arg))
            elif command == "goto_scene":
                cmd = gear.GoToScene(dest, int(arg))
            else:
                cmd = cls(dest)
            resp = await self.driver.send(cmd)
        return {"ok": True, "command": str(cmd), "response": str(resp) if resp is not None else None}

    # ----------------------------------------------------- colour control (DT8)
    async def read_colour(self, addr):
        if _colour is None:
            raise RuntimeError("colour module unavailable")
        await self._ready()
        short = address.Short(addr)
        async with self._guard():
            status = await self._q(_colour.QueryColourStatus(short))
            feat = await self._q(_colour.QueryColourTypeFeatures(short))
        return {
            "address": addr,
            "colour_status": self._mem_display(status.value) if status and getattr(status, "raw_value", None) is not None else None,
            "colour_features": _val(feat),
        }

    async def set_colour_temp(self, addr, mireds):
        """Set tunable-white colour temperature (mireds) on a DT8 gear."""
        if _colour is None:
            raise RuntimeError("colour module unavailable")
        await self._ready()
        short = address.Short(addr)
        mireds = int(mireds)

        def _seq():
            yield gear.DTR0(mireds & 0xFF)
            yield gear.DTR1((mireds >> 8) & 0xFF)
            yield _colour.SetTemporaryColourTemperature(short)
            yield _colour.Activate(short)

        async with self._guard():
            await self.driver.run_sequence(_seq())
        return {"ok": True, "mireds": mireds}

    async def set_colour_rgb(self, addr, r, g, b):
        """Set RGB dim levels (0-254 each) on a DT8 RGBWAF gear."""
        if _colour is None:
            raise RuntimeError("colour module unavailable")
        await self._ready()
        short = address.Short(addr)

        def _seq():
            yield gear.DTR0(int(r) & 0xFF)
            yield gear.DTR1(int(g) & 0xFF)
            yield gear.DTR2(int(b) & 0xFF)
            yield _colour.SetTemporaryRGBDimLevel(short)
            yield _colour.Activate(short)

        async with self._guard():
            await self.driver.run_sequence(_seq())
        return {"ok": True, "rgb": [int(r), int(g), int(b)]}

    # ------------------------------------------------- emergency lighting (DT1)
    async def read_emergency(self, addr):
        if _emergency is None:
            raise RuntimeError("emergency module unavailable")
        await self._ready()
        short = address.Short(addr)
        async with self._guard():
            out = {"address": addr}
            status = await self._q(_emergency.QueryEmergencyStatus(short))
            out["status"] = self._mem_display(status.value) if status and getattr(status, "raw_value", None) is not None else None
            mode = await self._q(_emergency.QueryEmergencyMode(short))
            out["mode"] = self._mem_display(mode.value) if mode and getattr(mode, "raw_value", None) is not None else None
            out["battery_charge"] = _val(await self._q(_emergency.QueryBatteryCharge(short)))
            out["rated_duration_min"] = self._maybe_mul(_val(await self._q(_emergency.QueryRatedDuration(short))), 2)
            out["duration_test_result_min"] = self._maybe_mul(_val(await self._q(_emergency.QueryDurationTestResult(short))), 2)
            out["lamp_emergency_time_h"] = _val(await self._q(_emergency.QueryLampEmergencyTime(short)))
        return out

    @staticmethod
    def _maybe_mul(v, factor):
        return v * factor if isinstance(v, int) else v

    async def emergency_test(self, addr, kind):
        if _emergency is None:
            raise RuntimeError("emergency module unavailable")
        await self._ready()
        short = address.Short(addr)
        cmd_map = {
            "function": _emergency.StartFunctionTest,
            "duration": _emergency.StartDurationTest,
            "stop": _emergency.StopTest,
        }
        if kind not in cmd_map:
            raise ValueError(f"unknown test {kind}")
        async with self._guard():
            await self.driver.send(cmd_map[kind](short))
        return {"ok": True, "test": kind}

    # -------------------------------------------------- writable typed memory
    def _find_typed(self, name):
        for _grp, module in _MEMORY_GROUPS:
            for n, cls in self._mem_value_classes(module):
                if n == name:
                    return cls
        return None

    async def write_typed(self, addr, name, value):
        """Write a writable typed memory value (e.g. an OEM/luminaire field)."""
        if not _HAVE_MEMORY:
            raise RuntimeError("memory module unavailable")
        cls = self._find_typed(name)
        if cls is None:
            raise ValueError(f"unknown field {name}")
        if not all(loc.type_ in _MEM_RW_TYPES for loc in cls.locations):
            raise ValueError(f"{name} is read-only")
        await self._ready()
        short = address.Short(addr)
        # Coerce the value: try int, else pass through as string.
        try:
            coerced = int(value)
        except (TypeError, ValueError):
            coerced = value
        async with self._guard():
            await self.driver.run_sequence(cls.write(short, coerced))
        return {"ok": True, "field": name, "value": coerced}

    async def scan_lunatone(self, bank=3, count=32, addresses=range(64)):
        """Read a Lunatone config memory bank from every control gear.

        Lunatone DALI-1 input devices (switches) occupy a short address and
        store their button configuration (destination address, command, button
        function) in a proprietary memory bank (typically bank 3). This dumps
        that bank for each present gear so switches can be identified and their
        destination mapping inspected.
        """
        await self._ready()
        result = []
        async with self._guard():
            for a in addresses:
                short = address.Short(a)
                present = await self._q(gear.QueryControlGearPresent(short))
                if not (isinstance(present, YesNoResponse) and present.value):
                    continue
                gtin = self._resp_byte(
                    await self._q(gear.QueryDeviceType(short))
                )

                def _seq(sh=short):
                    out = []
                    yield gear.DTR1(int(bank))
                    yield gear.DTR0(0)
                    for _ in range(int(count)):
                        r = yield gear.ReadMemoryLocation(sh)
                        out.append(self._resp_byte(r))
                    return out

                try:
                    data = await self.driver.run_sequence(_seq())
                except DALIError:
                    data = None
                result.append(
                    {"address": a, "bank": int(bank), "device_type": gtin, "data": data}
                )
        logger.info("Lunatone scan read bank %s from %d gear", bank, len(result))
        return result

    async def _q(self, command):
        try:
            return await self.driver.send(command)
        except DALIError as err:
            logger.debug("Query %s failed: %s", command, err)
            return None

    async def _read_groups(self, short):
        groups = []
        low = _val(await self._q(gear.QueryGroupsZeroToSeven(short))) or 0
        high = _val(await self._q(gear.QueryGroupsEightToFifteen(short))) or 0
        for i in range(8):
            if low & (1 << i):
                groups.append(i)
            if high & (1 << i):
                groups.append(i + 8)
        return groups

    # ----------------------------------------------------------- gear actions
    async def identify(self, addr, count=3, speed=0.5):
        """Blink a control gear so it can be located physically."""
        await self._ready()
        short = address.Short(addr)
        async with self._guard():
            original = _val(await self._q(gear.QueryActualLevel(short)))
            for _ in range(count):
                await self.driver.send(gear.RecallMaxLevel(short))
                await asyncio.sleep(speed)
                await self.driver.send(gear.RecallMinLevel(short))
                await asyncio.sleep(speed)
            # restore
            await self.driver.send(gear.DAPC(short, original or 0))
        return {"ok": True}

    async def set_level(self, addr, level):
        await self._ready()
        async with self._guard():
            await self.driver.send(gear.DAPC(address.Short(addr), int(level)))
        return {"ok": True}

    async def _set_via_dtr(self, addr, value, command_cls):
        await self._ready()
        short = address.Short(addr)
        async with self._guard():
            await self.driver.send(gear.DTR0(int(value)))
            await self.driver.send(command_cls(short))
        return {"ok": True}

    async def set_min_level(self, addr, value):
        return await self._set_via_dtr(addr, value, gear.SetMinLevel)

    async def set_max_level(self, addr, value):
        return await self._set_via_dtr(addr, value, gear.SetMaxLevel)

    async def set_power_on_level(self, addr, value):
        return await self._set_via_dtr(addr, value, gear.SetPowerOnLevel)

    async def set_system_failure_level(self, addr, value):
        return await self._set_via_dtr(addr, value, gear.SetSystemFailureLevel)

    async def set_fade_time(self, addr, value):
        return await self._set_via_dtr(addr, value, gear.SetFadeTime)

    async def set_fade_rate(self, addr, value):
        return await self._set_via_dtr(addr, value, gear.SetFadeRate)

    async def add_to_group(self, addr, group):
        await self._ready()
        async with self._guard():
            await self.driver.send(gear.AddToGroup(address.Short(addr), int(group)))
        return {"ok": True}

    async def remove_from_group(self, addr, group):
        await self._ready()
        async with self._guard():
            await self.driver.send(
                gear.RemoveFromGroup(address.Short(addr), int(group))
            )
        return {"ok": True}

    async def get_scenes(self, addr):
        await self._ready()
        short = address.Short(addr)
        scenes = {}
        async with self._guard():
            for s in range(16):
                v = _val(await self._q(gear.QuerySceneLevel(short, s)))
                if v is not None and str(v).upper() != "MASK":
                    scenes[s] = v
        return scenes

    async def set_scene(self, addr, scene, level):
        await self._ready()
        short = address.Short(addr)
        async with self._guard():
            await self.driver.send(gear.DTR0(int(level)))
            await self.driver.send(gear.SetScene(short, int(scene)))
        return {"ok": True}

    async def clear_scene(self, addr, scene):
        await self._ready()
        async with self._guard():
            await self.driver.send(
                gear.RemoveFromScene(address.Short(addr), int(scene))
            )
        return {"ok": True}

    async def change_address(self, old, new):
        """Change the short address of an existing control gear."""
        await self._ready()
        if not (0 <= int(new) <= 63):
            raise ValueError("new address out of range")
        async with self._guard():
            # DTR0 = (new << 1) | 1, then SET SHORT ADDRESS (config, sent twice)
            await self.driver.send(gear.DTR0((int(new) << 1) | 1))
            await self.driver.send(gear.SetShortAddress(address.Short(int(old))))
            # Verify the gear now answers at the new short address.
            present = await self._q(
                gear.QueryControlGearPresent(address.Short(int(new)))
            )
        verified = bool(
            isinstance(present, YesNoResponse) and present.value
        )
        return {"ok": True, "verified": verified}

    async def commission(self, readdress=False, progress_cb=None):
        """Assign short addresses to control gear (DALI commissioning).

        readdress=False : only address currently-unaddressed gear (safe).
        readdress=True  : clear and re-assign ALL short addresses (disruptive).
        """
        await self._ready()

        def _prog(p):
            logger.info("Commissioning: %s", getattr(p, "message", p))
            if progress_cb:
                progress_cb(p)

        async with self._guard():
            await self.driver.run_sequence(
                Commissioning(readdress=readdress), progress=_prog
            )
        logger.info("Commissioning finished (readdress=%s)", readdress)
        return {"ok": True}

    # ----------------------------------------------- control devices (DALI-2)
    # Input devices such as push-button panels and sensors (e.g. Lunatone DALI
    # Switch). Requires python-dali >= 0.11.
    def devices_supported(self):
        return _HAVE_DEVICE

    async def scan_devices(self, addresses=range(64)):
        """Scan DALI-2 control devices (buttons/sensors)."""
        if not _HAVE_DEVICE:
            return []
        await self._ready()
        result = []
        async with self._guard():
            for a in addresses:
                short = address.DeviceShort(a)
                status = await self._q(device.QueryDeviceStatus(short))
                # No backward frame -> device absent (response.raw_value is None).
                if status is None or getattr(status, "raw_value", None) is None:
                    continue
                info = {"address": a}
                info["status"] = _val(status)
                info["instances"] = _val(
                    await self._q(device.QueryNumberOfInstances(short))
                )
                info["operating_mode"] = _val(
                    await self._q(device.QueryOperatingMode(short))
                )
                result.append(info)
        logger.info("Config scan found %d control devices", len(result))
        return result

    async def identify_device(self, addr):
        if not _HAVE_DEVICE:
            raise RuntimeError("control device support requires python-dali 0.11")
        await self._ready()
        async with self._guard():
            await self.driver.send(device.IdentifyDevice(address.DeviceShort(addr)))
        return {"ok": True}

    async def read_device(self, addr):
        """Read details of one control device (instances + pushbutton timers)."""
        if not _HAVE_DEVICE:
            raise RuntimeError("control device support requires python-dali 0.11")
        await self._ready()
        short = address.DeviceShort(addr)
        async with self._guard():
            n = _val(await self._q(device.QueryNumberOfInstances(short))) or 0
            op = _val(await self._q(device.QueryOperatingMode(short)))
            instances = []
            for i in range(n):
                inst = {"instance": i}
                inst["type"] = _val(
                    await self._q(device.QueryInstanceType(short, i))
                    if hasattr(device, "QueryInstanceType")
                    else None
                )
                instances.append(inst)
        return {"address": addr, "operating_mode": op, "instances": instances}

    async def change_device_address(self, old, new):
        """Change the short address of a control device."""
        if not _HAVE_DEVICE:
            raise RuntimeError("control device support requires python-dali 0.11")
        await self._ready()
        if not (0 <= int(new) <= 63):
            raise ValueError("new address out of range")
        async with self._guard():
            await self.driver.send(device.DTR0(int(new)))
            await self.driver.send(
                device.SetShortAddress(address.DeviceShort(int(old)))
            )
        return {"ok": True}

    # ------------------------------------------------------- memory bank tool
    def _mem_addr_mod(self, addr, is_device):
        if is_device:
            if not _HAVE_DEVICE:
                raise RuntimeError("control device support requires python-dali 0.11")
            return address.DeviceShort(addr), device
        return address.Short(addr), gear

    @staticmethod
    def _resp_byte(r):
        if r is None:
            return None
        raw = getattr(r, "raw_value", None)
        if raw is None:
            return None
        try:
            return int(raw.as_integer)
        except Exception:  # noqa: BLE001
            return None

    async def read_memory(self, addr, bank, start=0, count=16, is_device=False):
        """Read `count` bytes of a memory bank from a control gear or device."""
        await self._ready()
        short, mod = self._mem_addr_mod(addr, is_device)
        count = max(1, min(int(count), 255))

        def seq():
            out = []
            yield mod.DTR1(int(bank))
            yield mod.DTR0(int(start))
            for _ in range(count):
                r = yield mod.ReadMemoryLocation(short)
                out.append(self._resp_byte(r))
            return out

        async with self._guard():
            data = await self.driver.run_sequence(seq())
        return {"address": addr, "bank": int(bank), "start": int(start), "data": data}

    async def write_memory(self, addr, bank, offset, value, is_device=False, unlock=True):
        """Write a single byte to a memory bank location (targeted, with unlock).

        Uses the addressed ENABLE WRITE MEMORY command so only this device
        accepts the following (broadcast) WRITE MEMORY LOCATION.
        """
        await self._ready()
        short, mod = self._mem_addr_mod(addr, is_device)
        value = int(value) & 0xFF
        offset = int(offset) & 0xFF

        def seq():
            yield mod.DTR1(int(bank))
            yield mod.EnableWriteMemory(short)
            if unlock:
                yield mod.DTR0(2)
                yield mod.WriteMemoryLocationNoReply(0x55)
            yield mod.DTR0(offset)
            r = yield mod.WriteMemoryLocation(value)
            written = self._resp_byte(r)
            if unlock:
                yield mod.DTR0(2)
                yield mod.WriteMemoryLocationNoReply(0xFF)
            return written

        async with self._guard():
            written = await self.driver.run_sequence(seq())
        logger.info(
            "Memory write %s bank %s offset %s = %s (readback %s)",
            addr, bank, offset, value, written,
        )
        return {"ok": True, "written": written, "expected": value}

    # -------------------------------------- DALI-2 push-button instance config
    # Part 301. Timers are raw bytes: short/double/repeat in 20 ms steps,
    # stuck in 1 s steps. Event filter selects which events the instance emits.
    _PB_TIMER_SET = None  # set lazily to avoid touching pb when unavailable
    _PB_TIMER_QUERY = None

    def _pb_maps(self):
        return (
            {
                "short": pb.SetShortTimer,
                "double": pb.SetDoubleTimer,
                "repeat": pb.SetRepeatTimer,
                "stuck": pb.SetStuckTimer,
            },
            {
                "short": pb.QueryShortTimer,
                "double": pb.QueryDoubleTimer,
                "repeat": pb.QueryRepeatTimer,
                "stuck": pb.QueryStuckTimer,
            },
        )

    async def read_pushbutton(self, addr, instance):
        """Read a push-button instance: type, timers, and event filter."""
        if not _HAVE_DEVICE:
            raise RuntimeError("control device support requires python-dali 0.11")
        await self._ready()
        short = address.DeviceShort(addr)
        inst = InstanceNumber(int(instance))
        _, qtimers = self._pb_maps()
        async with self._guard():
            itype = _val(await self._q(device.QueryInstanceType(short, inst)))
            timers = {}
            for name, cmd in qtimers.items():
                timers[name] = _val(await self._q(cmd(short, inst)))
            try:
                flt = await self.driver.run_sequence(
                    devseq.QueryEventFilters(device=short, instance=inst, filter_type=pb)
                )
                mask = int(flt) if flt is not None else None
            except Exception as err:  # noqa: BLE001
                logger.debug("QueryEventFilters failed: %s", err)
                mask = None
        events = None
        if mask is not None:
            events = [PB_EVENTS[i] for i in range(8) if mask & (1 << i)]
        return {
            "address": addr,
            "instance": int(instance),
            "instance_type": itype,
            "timers": timers,
            "event_filter_mask": mask,
            "events": events,
        }

    async def set_pushbutton_timer(self, addr, instance, which, value):
        if not _HAVE_DEVICE:
            raise RuntimeError("control device support requires python-dali 0.11")
        await self._ready()
        setters, _ = self._pb_maps()
        if which not in setters:
            raise ValueError(f"unknown timer {which}")
        short = address.DeviceShort(addr)
        inst = InstanceNumber(int(instance))
        async with self._guard():
            await self.driver.send(device.DTR0(int(value) & 0xFF))
            await self.driver.send(setters[which](short, inst))
        return {"ok": True}

    async def set_pushbutton_events(self, addr, instance, mask):
        """Set the event filter mask (which events this button emits)."""
        if not _HAVE_DEVICE:
            raise RuntimeError("control device support requires python-dali 0.11")
        await self._ready()
        short = address.DeviceShort(addr)
        inst = InstanceNumber(int(instance))
        filt = pb.InstanceEventFilter(int(mask) & 0xFF)
        async with self._guard():
            result = await self.driver.run_sequence(
                devseq.SetEventFilters(device=short, instance=inst, filter_value=filt)
            )
        return {"ok": True, "result": int(result) if result is not None else None}

    async def set_pushbutton_scheme(self, addr, instance, scheme):
        """Set the event addressing scheme for an instance."""
        if not _HAVE_DEVICE:
            raise RuntimeError("control device support requires python-dali 0.11")
        await self._ready()
        short = address.DeviceShort(addr)
        inst = InstanceNumber(int(instance))
        async with self._guard():
            result = await self.driver.run_sequence(
                devseq.SetEventSchemes(
                    device=short, instance=inst, scheme=EventScheme(int(scheme))
                )
            )
        return {"ok": True, "result": int(result) if result is not None else None}
