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
    import dali.device.general as device
    from dali.device import pushbutton as pb

    _HAVE_DEVICE = True
except ImportError:  # python-dali < 0.11
    device = None
    pb = None
    _HAVE_DEVICE = False

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
            self._monitor.append(
                {
                    "seq": self._mon_seq,
                    "t": time.strftime("%H:%M:%S"),
                    "cmd": str(command) if command is not None else "",
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
            verify = await self._q(gear.QueryShortAddress(address.Short(int(new))))
        return {"ok": True, "verify": _val(verify)}

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
