"""Tests for DALI-2 control-device commissioning (Part 103), Cockpit-style.

These exercise the randomise/compare/withdraw search that assigns short
device addresses to Lunatone push-button / input modules so they become
readable -- the step Cockpit performs before it can show a switch's config.
"""
from conftest import cname, yes, no

from app.dali_config import DaliConfig


class _DeviceBus:
    """Simulates a set of uncommissioned DALI-2 devices for the search.

    Each device has a fixed 24-bit random address. Compare answers "yes" if
    any not-yet-withdrawn device's random address is <= the current search
    address (standard DALI binary search). Withdraw removes the exact match.
    """

    def __init__(self, random_addrs):
        self.remaining = sorted(random_addrs)
        self.search = 0xFFFFFF
        self.programmed = []

    def __call__(self, cmd):
        n = cname(cmd)
        if n == "SearchAddrH":
            self.search = (self.search & 0x00FFFF) | (cmd.param << 16)
        elif n == "SearchAddrM":
            self.search = (self.search & 0xFF00FF) | (cmd.param << 8)
        elif n == "SearchAddrL":
            self.search = (self.search & 0xFFFF00) | cmd.param
        elif n == "Compare":
            return yes() if any(a <= self.search for a in self.remaining) else no()
        elif n == "Withdraw":
            # Withdraw the device whose address exactly equals the search addr.
            if self.search in self.remaining:
                self.remaining.remove(self.search)
        elif n == "ProgramShortAddress":
            self.programmed.append(cmd.param)
        elif n == "VerifyShortAddress":
            return yes()
        return None


async def test_commission_devices_programs_each(driver):
    bus = _DeviceBus([0x000010, 0x00A0B0])
    driver._responder = bus
    cfg = DaliConfig(driver)

    res = await cfg.commission_devices(readdress=False)

    assert res["found"] == 2
    assert res["programmed"] == [0, 1]      # two free addresses handed out
    assert res["dry_run"] is False
    # The device layer must be initialised for unaddressed devices (0x7F).
    init = next(c for c in driver.sent if cname(c) == "Initialise")
    assert init.param == 0x7F
    # No gear commands should leak into a device-layer commissioning run.
    assert not any(cname(c) == "SetShortAddress" for c in driver.sent)


async def test_commission_devices_dry_run_counts_only(driver):
    bus = _DeviceBus([0x000010, 0x00A0B0, 0x123456])
    driver._responder = bus
    cfg = DaliConfig(driver)

    res = await cfg.commission_devices(dry_run=True)

    assert res["found"] == 3
    assert res["programmed"] == []
    assert res["dry_run"] is True
    assert bus.programmed == []             # nothing programmed on the bus
    assert not any(cname(c) == "ProgramShortAddress" for c in driver.sent)


async def test_commission_devices_readdress_clears_first(driver):
    bus = _DeviceBus([0x000010])
    driver._responder = bus
    cfg = DaliConfig(driver)

    await cfg.commission_devices(readdress=True)

    init = next(c for c in driver.sent if cname(c) == "Initialise")
    assert init.param == 0x00               # all devices react when re-addressing
    # A broadcast clear of existing device addresses must happen.
    assert any(cname(c) == "SetShortAddress" for c in driver.sent)


async def test_commission_devices_none_present(driver):
    driver._responder = _DeviceBus([])
    cfg = DaliConfig(driver)
    res = await cfg.commission_devices()
    assert res["found"] == 0
    assert res["programmed"] == []
