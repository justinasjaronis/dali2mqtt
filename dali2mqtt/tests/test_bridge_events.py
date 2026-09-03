"""Tests for bus-event publishing and button simulation in app.bridge."""
import json

import dali.address as address
import dali.gear.general as gear

import app.bridge as bridge


class _Client:
    def __init__(self):
        self.published = []

    def publish(self, topic, payload):
        self.published.append((topic, payload))


def test_publish_bus_event_publishes_action(monkeypatch):
    client = _Client()
    monkeypatch.setitem(bridge._runtime, "client", client)
    monkeypatch.setattr(bridge, "Config", lambda: {"mqtt_base_topic": "dali2mqtt"})
    bridge.publish_bus_event(gear.Off(address.Short(6)), None)
    assert len(client.published) == 1
    topic, payload = client.published[0]
    assert topic == "dali2mqtt/bus_event"
    d = json.loads(payload)
    assert d["type"] == "Off"
    assert d["address"] == 6
    assert d["destination_kind"] == "short"


def test_publish_bus_event_group_address(monkeypatch):
    client = _Client()
    monkeypatch.setitem(bridge._runtime, "client", client)
    monkeypatch.setattr(bridge, "Config", lambda: {"mqtt_base_topic": "dali2mqtt"})
    bridge.publish_bus_event(gear.GoToScene(address.Group(8), 4), None)
    d = json.loads(client.published[0][1])
    assert d["type"] == "GoToScene"
    assert d["address"] == 8
    assert d["destination_kind"] == "group"


def test_publish_bus_event_skips_queries(monkeypatch):
    client = _Client()
    monkeypatch.setitem(bridge._runtime, "client", client)
    monkeypatch.setattr(bridge, "Config", lambda: {"mqtt_base_topic": "dali2mqtt"})
    bridge.publish_bus_event(gear.QueryActualLevel(address.Short(6)), None)
    assert client.published == []


class _Mirror:
    def __init__(self, mapped):
        self.enabled = True
        self._mapped = mapped
        self.toggled = []

    def is_mapped(self, a):
        return a in self._mapped

    def toggle_address(self, a):
        self.toggled.append(a)


def test_simulate_button_ok(monkeypatch):
    mirror = _Mirror({20})
    monkeypatch.setitem(bridge._runtime, "data", {"mirror": mirror})
    assert bridge.simulate_button(20) == {"ok": True, "address": 20}
    assert mirror.toggled == [20]


def test_simulate_button_unmapped(monkeypatch):
    mirror = _Mirror({20})
    monkeypatch.setitem(bridge._runtime, "data", {"mirror": mirror})
    assert bridge.simulate_button(21)["ok"] is False


def test_simulate_button_no_mirror(monkeypatch):
    monkeypatch.setitem(bridge._runtime, "data", {"mirror": None})
    assert bridge.simulate_button(20)["ok"] is False


import asyncio  # noqa: E402


class _AllMirror:
    def __init__(self):
        self.enabled = True
        self.set_all_calls = []

    def is_mapped(self, a):
        return False

    def set_all(self, action):
        self.set_all_calls.append(action)


def _make_data(mirror):
    return {"all_lamps": {}, "queue": asyncio.Queue(), "mirror": mirror}


async def _run_cmd(monkeypatch, command):
    bridge.config_busy.clear()
    monkeypatch.setattr(bridge, "Config", lambda: {"mqtt_base_topic": "dali2mqtt"})
    monkeypatch.setitem(bridge._runtime, "client",
                        type("C", (), {"publish": lambda s, t, p: None})())
    mirror = _AllMirror()
    bridge.print_command_and_response(_make_data(mirror), None, command, None, False)
    await asyncio.sleep(0.05)   # let run_in_executor complete
    return mirror


async def test_broadcast_off_sets_all_off(monkeypatch):
    m = await _run_cmd(monkeypatch, gear.Off(address.Broadcast()))
    assert m.set_all_calls == ["off"]


async def test_broadcast_dapc_zero_sets_all_off(monkeypatch):
    m = await _run_cmd(monkeypatch, gear.DAPC(address.Broadcast(), 0))
    assert m.set_all_calls == ["off"]


async def test_broadcast_recall_max_sets_all_on(monkeypatch):
    m = await _run_cmd(monkeypatch, gear.RecallMaxLevel(address.Broadcast()))
    assert m.set_all_calls == ["on"]


async def test_broadcast_query_does_nothing(monkeypatch):
    m = await _run_cmd(monkeypatch, gear.QueryActualLevel(address.Broadcast()))
    assert m.set_all_calls == []
