"""Tests for DALI command console, colour (DT8), emergency (DT1), typed writes."""
import dali.gear.general as gear
import pytest

from app.dali_config import DaliConfig
from conftest import RawResp, cname, dest_addr, numeric


# ---------------------------------------------------------- command console
async def test_command_off_short(driver):
    cfg = DaliConfig(driver)
    await cfg.send_command("short", 6, "off")
    assert isinstance(driver.sent[-1], gear.Off)
    assert dest_addr(driver.sent[-1]) == 6


async def test_command_dapc(driver):
    cfg = DaliConfig(driver)
    await cfg.send_command("short", 6, "dapc", 200)
    assert isinstance(driver.sent[-1], gear.DAPC)


async def test_command_goto_scene(driver):
    cfg = DaliConfig(driver)
    await cfg.send_command("short", 6, "goto_scene", 4)
    assert isinstance(driver.sent[-1], gear.GoToScene)


async def test_command_broadcast(driver):
    import dali.address as address
    cfg = DaliConfig(driver)
    await cfg.send_command("broadcast", None, "recall_max")
    assert isinstance(driver.sent[-1].destination, address.Broadcast)


async def test_command_unknown_rejected(driver):
    cfg = DaliConfig(driver)
    with pytest.raises(ValueError):
        await cfg.send_command("short", 6, "nope")


# ---------------------------------------------------------- colour (DT8)
async def test_set_colour_temp_sequence(driver):
    cfg = DaliConfig(driver)
    await cfg.set_colour_temp(6, 370)
    t = driver.sent_types()
    assert t == ["DTR0", "DTR1", "SetTemporaryColourTemperature", "Activate"]


async def test_set_colour_rgb_sequence(driver):
    cfg = DaliConfig(driver)
    await cfg.set_colour_rgb(6, 254, 0, 128)
    t = driver.sent_types()
    assert t == ["DTR0", "DTR1", "DTR2", "SetTemporaryRGBDimLevel", "Activate"]


# ---------------------------------------------------------- emergency (DT1)
async def test_emergency_test_function(driver):
    cfg = DaliConfig(driver)
    await cfg.emergency_test(6, "function")
    assert cname(driver.sent[-1]) == "StartFunctionTest"


async def test_emergency_test_unknown(driver):
    cfg = DaliConfig(driver)
    with pytest.raises(ValueError):
        await cfg.emergency_test(6, "bogus")


async def test_read_emergency(driver):
    def responder(cmd):
        n = cname(cmd)
        if n in ("QueryEmergencyStatus", "QueryEmergencyMode"):
            return RawResp(value=1, raw_int=1)
        if n.startswith("Query"):
            return numeric(50)
        return None
    driver._responder = responder
    cfg = DaliConfig(driver)
    res = await cfg.read_emergency(6)
    assert res["battery_charge"] == 50
    assert res["rated_duration_min"] == 100   # 50 * 2


# ---------------------------------------------------------- typed writes
async def test_write_typed_readonly_rejected(driver):
    cfg = DaliConfig(driver)
    with pytest.raises(ValueError):
        await cfg.write_typed(6, "GTIN", 123)   # bank 0 is read-only


async def test_write_typed_unknown_field(driver):
    cfg = DaliConfig(driver)
    with pytest.raises(ValueError):
        await cfg.write_typed(6, "NoSuchField", 1)
