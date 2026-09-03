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

import dali.address as address
import dali.gear.general as gear
from dali.command import YesNoResponse
from dali.exceptions import DALIError
from dali.sequences import Commissioning

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
    try:
        return int(v)
    except (TypeError, ValueError):
        return v


class DaliConfig:
    def __init__(self, driver, busy=None):
        self.driver = driver
        # Serialises multi-command config operations against each other.
        self._lock = asyncio.Lock()
        # Optional asyncio.Event the bridge watches to pause its bus traffic
        # while a config operation is running (prevents a re-read storm).
        self._busy = busy

    async def _ready(self):
        await self.driver.connected.wait()

    @contextlib.asynccontextmanager
    async def _guard(self):
        """Own the bus for one operation: pause the bridge, serialise access."""
        async with self._guard():
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
        low = await self._q(gear.QueryGroupsZeroToSeven(short))
        high = await self._q(gear.QueryGroupsEightToFifteen(short))
        low = _val(low) or 0
        high = _val(high) or 0
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
