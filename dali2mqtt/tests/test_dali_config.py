"""Unit tests for app.dali_config.DaliConfig (control gear operations)."""
from types import SimpleNamespace

import dali.address as address
import dali.gear.general as gear
import pytest

from app.dali_config import DaliConfig, _val
from conftest import RawResp, cname, dest_addr, dtr_value, groups_value, no, numeric, yes


# --------------------------------------------------------------- _val helper
@pytest.mark.parametrize(
    "resp,expected",
    [
        (RawResp(value=5), 5),
        (RawResp(value=0), 0),
        (RawResp(value=None), None),
        (None, None),
        (RawResp(value=SimpleNamespace(as_integer=9)), 9),
        (RawResp(value="MASK"), None),
    ],
)
def test_val(resp, expected):
    assert _val(resp) == expected


# --------------------------------------------------------------- scan_gear
def _scan_responder(present, level=100, groups_low=0b0000_0101):
    def responder(cmd):
        n = cname(cmd)
        a = dest_addr(cmd)
        if n == "QueryControlGearPresent":
            return yes() if a in present else no()
        if n == "QueryActualLevel":
            return numeric(level)
        if n == "QueryGroupsZeroToSeven":
            return groups_value(groups_low)
        if n == "QueryGroupsEightToFifteen":
            return groups_value(0)
        if n.startswith("Query"):
            return numeric(1)
        return None

    return responder


async def test_scan_gear_finds_present_only(driver):
    driver._responder = _scan_responder(present={6})
    cfg = DaliConfig(driver)
    result = await cfg.scan_gear(range(0, 8))
    assert [g["address"] for g in result] == [6]
    entry = result[0]
    assert entry["level"] == 100
    # groups_low 0b101 -> groups 0 and 2
    assert entry["groups"] == [0, 2]


async def test_scan_gear_empty(driver):
    driver._responder = _scan_responder(present=set())
    cfg = DaliConfig(driver)
    assert await cfg.scan_gear(range(0, 4)) == []


# --------------------------------------------------------------- set actions
async def test_set_level_sends_dapc(driver):
    cfg = DaliConfig(driver)
    await cfg.set_level(6, 120)
    assert len(driver.sent) == 1
    assert isinstance(driver.sent[0], gear.DAPC)
    assert dest_addr(driver.sent[0]) == 6


@pytest.mark.parametrize(
    "method,cls",
    [
        ("set_min_level", gear.SetMinLevel),
        ("set_max_level", gear.SetMaxLevel),
        ("set_power_on_level", gear.SetPowerOnLevel),
        ("set_system_failure_level", gear.SetSystemFailureLevel),
        ("set_fade_time", gear.SetFadeTime),
        ("set_fade_rate", gear.SetFadeRate),
    ],
)
async def test_set_via_dtr(driver, method, cls):
    cfg = DaliConfig(driver)
    await getattr(cfg, method)(6, 42)
    assert driver.sent_types() == ["DTR0", cls.__name__]
    assert dtr_value(driver.sent[0]) == 42
    assert dest_addr(driver.sent[1]) == 6


async def test_add_remove_group(driver):
    cfg = DaliConfig(driver)
    await cfg.add_to_group(6, 3)
    assert isinstance(driver.sent[0], gear.AddToGroup)
    assert dest_addr(driver.sent[0]) == 6
    driver.reset()
    await cfg.remove_from_group(6, 3)
    assert isinstance(driver.sent[0], gear.RemoveFromGroup)


async def test_scene_set_and_clear(driver):
    cfg = DaliConfig(driver)
    await cfg.set_scene(6, 4, 200)
    assert driver.sent_types() == ["DTR0", "SetScene"]
    assert dtr_value(driver.sent[0]) == 200
    assert dest_addr(driver.sent[1]) == 6
    driver.reset()
    await cfg.clear_scene(6, 4)
    assert isinstance(driver.sent[0], gear.RemoveFromScene)


async def test_change_address(driver):
    driver._responder = (
        lambda cmd: yes() if cname(cmd) == "QueryControlGearPresent" else None
    )
    cfg = DaliConfig(driver)
    res = await cfg.change_address(6, 10)
    # DTR0 = (10<<1)|1 = 21, then SetShortAddress to old addr 6
    assert cname(driver.sent[0]) == "DTR0"
    assert dtr_value(driver.sent[0]) == 21
    assert isinstance(driver.sent[1], gear.SetShortAddress)
    assert dest_addr(driver.sent[1]) == 6
    assert res["verified"] is True


async def test_change_address_rejects_out_of_range(driver):
    cfg = DaliConfig(driver)
    with pytest.raises(ValueError):
        await cfg.change_address(6, 99)


async def test_identify_restores_level(driver):
    driver._responder = lambda cmd: numeric(88) if cname(cmd) == "QueryActualLevel" else None
    cfg = DaliConfig(driver)
    await cfg.identify(6, count=2, speed=0)
    types = driver.sent_types()
    # query level, then blink pairs, then restore with DAPC
    assert types[0] == "QueryActualLevel"
    assert types.count("RecallMaxLevel") == 2
    assert types.count("RecallMinLevel") == 2
    assert isinstance(driver.sent[-1], gear.DAPC)


# --------------------------------------------------------------- busy guard
async def test_busy_guard_sets_and_clears(driver, busy):
    seen = []
    driver._responder = lambda cmd: seen.append(busy.is_set())
    cfg = DaliConfig(driver, busy=busy)
    await cfg.set_level(6, 10)
    assert seen == [True]           # busy was set while sending
    assert not busy.is_set()        # cleared afterwards


# --------------------------------------------------------------- bus monitor
async def test_monitor_records_and_filters(driver):
    cfg = DaliConfig(driver)
    # first call registers the callback and returns nothing yet
    assert cfg.monitor_events(0) == []
    cb = driver.bus_traffic._cbs[0]
    cb(driver, gear.DAPC(address.Short(6), 100), None, False)
    cb(driver, gear.Off(address.Short(6)), None, False)
    events = cfg.monitor_events(0)
    assert len(events) == 2
    assert events[0]["seq"] == 1 and events[1]["seq"] == 2
    # "since" filter
    assert len(cfg.monitor_events(1)) == 1


# --------------------------------------------------------------- commission
async def test_commission_runs_sequence(driver, busy):
    calls = {}

    async def fake_run_sequence(seq, progress=None):
        calls["ran"] = type(seq).__name__
        busy_state = busy.is_set()
        calls["busy_during"] = busy_state
        seq.close()
        return {"done": True}

    driver.run_sequence = fake_run_sequence
    cfg = DaliConfig(driver, busy=busy)
    res = await cfg.commission(readdress=False)
    assert res["ok"] is True
    assert calls["busy_during"] is True
    assert not busy.is_set()
