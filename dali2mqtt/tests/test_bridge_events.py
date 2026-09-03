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
