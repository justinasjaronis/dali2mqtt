"""Tests for memory-bank read/write and DALI-2 control-device operations."""
import pytest

from app.dali_config import DaliConfig
from conftest import RawResp, cname, dtr_value, numeric


# ------------------------------------------------------------ memory read
async def test_read_memory_sequence_and_data(driver):
    data_bytes = [0xAA, 0xBB, 0xCC, 0xDD]
    pending = list(data_bytes)

    def responder(cmd):
        if cname(cmd) == "ReadMemoryLocation":
            return RawResp(raw_int=pending.pop(0))
        return None

    driver._responder = responder
    cfg = DaliConfig(driver)
    res = await cfg.read_memory(6, bank=0, start=0, count=4)
    assert driver.sent_types() == [
        "DTR1", "DTR0", "ReadMemoryLocation", "ReadMemoryLocation",
        "ReadMemoryLocation", "ReadMemoryLocation",
    ]
    assert dtr_value(driver.sent[0]) == 0   # bank
    assert dtr_value(driver.sent[1]) == 0   # start
    assert res["data"] == data_bytes


async def test_read_memory_missing_byte_is_none(driver):
    driver._responder = lambda cmd: RawResp(raw_int=None) if cname(cmd) == "ReadMemoryLocation" else None
    cfg = DaliConfig(driver)
    res = await cfg.read_memory(6, bank=0, start=0, count=2)
    assert res["data"] == [None, None]


# ------------------------------------------------------------ memory write
async def test_write_memory_with_unlock(driver):
    driver._responder = lambda cmd: RawResp(raw_int=0x42) if cname(cmd) == "WriteMemoryLocation" else None
    cfg = DaliConfig(driver)
    res = await cfg.write_memory(6, bank=1, offset=5, value=0x42, unlock=True)
    assert driver.sent_types() == [
        "DTR1", "EnableWriteMemory",
        "DTR0", "WriteMemoryLocationNoReply",   # unlock lock byte = 0x55
        "DTR0", "WriteMemoryLocation",          # the actual byte
        "DTR0", "WriteMemoryLocationNoReply",   # relock = 0xFF
    ]
    assert dtr_value(driver.sent[0]) == 1       # bank
    assert dtr_value(driver.sent[2]) == 2       # lock byte offset
    assert dtr_value(driver.sent[3]) == 0x55    # unlock value
    assert dtr_value(driver.sent[4]) == 5       # target offset
    assert dtr_value(driver.sent[7]) == 0xFF    # relock value
    assert res["written"] == 0x42
    assert res["expected"] == 0x42


async def test_write_memory_without_unlock(driver):
    driver._responder = lambda cmd: RawResp(raw_int=7) if cname(cmd) == "WriteMemoryLocation" else None
    cfg = DaliConfig(driver)
    await cfg.write_memory(6, bank=1, offset=5, value=7, unlock=False)
    assert driver.sent_types() == [
        "DTR1", "EnableWriteMemory", "DTR0", "WriteMemoryLocation",
    ]


# ------------------------------------------------------------ control devices
def _device_responder(present, instances=2, op_mode=0):
    def responder(cmd):
        n = cname(cmd)
        if n == "QueryDeviceStatus":
            a = getattr(getattr(cmd, "destination", None), "address", None)
            return RawResp(value=32, raw_int=32) if a in present else RawResp(raw_int=None)
        if n == "QueryNumberOfInstances":
            return numeric(instances)
        if n == "QueryOperatingMode":
            return numeric(op_mode)
        if n == "QueryInstanceType":
            return numeric(1)
        return None

    return responder


async def test_scan_devices(driver):
    driver._responder = _device_responder(present={62}, instances=3)
    cfg = DaliConfig(driver)
    res = await cfg.scan_devices(range(60, 64))
    assert [d["address"] for d in res] == [62]
    assert res[0]["instances"] == 3
    assert res[0]["status"] == 32


async def test_scan_devices_none(driver):
    driver._responder = _device_responder(present=set())
    cfg = DaliConfig(driver)
    assert await cfg.scan_devices(range(60, 64)) == []


async def test_identify_device(driver):
    cfg = DaliConfig(driver)
    await cfg.identify_device(62)
    assert cname(driver.sent[0]) == "IdentifyDevice"


async def test_change_device_address(driver):
    cfg = DaliConfig(driver)
    await cfg.change_device_address(62, 5)
    assert cname(driver.sent[0]) == "DTR0"
    assert dtr_value(driver.sent[0]) == 5
    assert cname(driver.sent[1]) == "SetShortAddress"


async def test_read_pushbutton(driver):
    def responder(cmd):
        n = cname(cmd)
        if n == "QueryInstanceType":
            return numeric(1)
        if n.startswith("Query") and "Timer" in n:
            return numeric(20)
        return None

    driver._responder = responder
    cfg = DaliConfig(driver)
    res = await cfg.read_pushbutton(62, 0)
    assert res["instance_type"] == 1
    assert res["timers"]["short"] == 20
    assert res["timers"]["stuck"] == 20


async def test_scan_lunatone(driver):
    pending = list(range(1, 33))
    def responder(cmd):
        n = cname(cmd)
        a = getattr(getattr(cmd, "destination", None), "address", None)
        if n == "QueryControlGearPresent":
            from conftest import yes, no
            return yes() if a == 6 else no()
        if n == "QueryDeviceType":
            return numeric(8)
        if n == "ReadMemoryLocation":
            return RawResp(raw_int=(pending.pop(0) if pending else 0))
        return None
    driver._responder = responder
    cfg = DaliConfig(driver)
    res = await cfg.scan_lunatone(bank=3, count=32, addresses=range(0, 8))
    assert [g["address"] for g in res] == [6]
    assert res[0]["bank"] == 3
    assert len(res[0]["data"]) == 32
    assert res[0]["data"][0] == 1
