"""Tests for app.webserver HTTP endpoints (aiohttp)."""
import dali.gear.general as gear
from aiohttp.test_utils import TestClient, TestServer

from app.webserver import DaliWebServer
from conftest import FakeDriver, cname, dest_addr, groups_value, no, numeric, yes


def _scan_responder(present):
    def responder(cmd):
        n = cname(cmd)
        a = dest_addr(cmd)
        if n == "QueryControlGearPresent":
            return yes() if a in present else no()
        if n == "QueryGroupsZeroToSeven" or n == "QueryGroupsEightToFifteen":
            return groups_value(0)
        if n.startswith("Query"):
            return numeric(50)
        return None
    return responder


async def _client(driver, **kw):
    web = DaliWebServer(driver, {}, **kw)
    client = TestClient(TestServer(web._app()))
    await client.start_server()
    return client


async def test_scan_endpoint():
    driver = FakeDriver(responder=_scan_responder(present={6}))
    client = await _client(driver)
    try:
        r = await client.get("/api/scan")
        assert r.status == 200
        data = await r.json()
        assert [g["address"] for g in data["gear"]] == [6]
    finally:
        await client.close()


async def test_level_endpoint_sends_dapc():
    driver = FakeDriver()
    client = await _client(driver)
    try:
        r = await client.post("/api/gear/6/level", json={"level": 120})
        assert r.status == 200
        assert isinstance(driver.sent[0], gear.DAPC)
    finally:
        await client.close()


async def test_set_field_unknown_returns_400():
    driver = FakeDriver()
    client = await _client(driver)
    try:
        r = await client.post("/api/gear/6/set", json={"field": "nope", "value": 1})
        assert r.status == 400
    finally:
        await client.close()


async def test_simulate_button_endpoint():
    driver = FakeDriver()
    client = await _client(driver, simulate=lambda a: {"ok": True, "address": a})
    try:
        r = await client.post("/api/simulate_button/20")
        assert (await r.json()) == {"ok": True, "address": 20}
    finally:
        await client.close()


async def test_simulate_button_unavailable_501():
    driver = FakeDriver()
    client = await _client(driver)   # no simulate callable
    try:
        r = await client.post("/api/simulate_button/20")
        assert r.status == 501
    finally:
        await client.close()


async def test_monitor_endpoint():
    driver = FakeDriver()
    client = await _client(driver)
    try:
        r = await client.get("/api/monitor?since=0")
        assert r.status == 200
        data = await r.json()
        assert "events" in data and "last" in data
    finally:
        await client.close()
