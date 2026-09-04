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
    def __init__(self, mapped=()):
        self.enabled = True
        self.set_all_calls = []
        self.set_address_calls = []
        self._mapped = set(mapped)

    def is_mapped(self, a):
        return a in self._mapped

    def set_all(self, action):
        self.set_all_calls.append(action)

    def set_address(self, address, action, brightness_pct=None):
        self.set_address_calls.append((address, action, brightness_pct))


def _make_data(mirror, lamps=()):
    return {"all_lamps": {a: None for a in lamps}, "queue": asyncio.Queue(), "mirror": mirror}


async def _run_cmd(monkeypatch, command, mapped=(), lamps=()):
    bridge.config_busy.clear()
    monkeypatch.setattr(bridge, "Config", lambda: {"mqtt_base_topic": "dali2mqtt"})
    monkeypatch.setitem(bridge._runtime, "client",
                        type("C", (), {"publish": lambda s, t, p: None})())
    mirror = _AllMirror(mapped=mapped)
    bridge.print_command_and_response(_make_data(mirror, lamps=lamps), None, command, None, False)
    await asyncio.sleep(0.05)   # let run_in_executor complete
    return mirror


async def test_broadcast_off_sets_all_off(monkeypatch):
    m = await _run_cmd(monkeypatch, gear.Off(address.Broadcast()))
    assert m.set_all_calls == ["off"]


async def test_broadcast_dapc_ignored(monkeypatch):
    # DAPC is the bridge's own control command; it must NOT drive the mirror.
    m = await _run_cmd(monkeypatch, gear.DAPC(address.Broadcast(), 0))
    assert m.set_all_calls == []


async def test_broadcast_recall_max_sets_all_on(monkeypatch):
    m = await _run_cmd(monkeypatch, gear.RecallMaxLevel(address.Broadcast()))
    assert m.set_all_calls == ["on"]


async def test_broadcast_query_does_nothing(monkeypatch):
    m = await _run_cmd(monkeypatch, gear.QueryActualLevel(address.Broadcast()))
    assert m.set_all_calls == []


def test_simulate_broadcast_off(monkeypatch):
    class M:
        enabled = True
        def __init__(self): self.calls = []
        def set_all(self, a): self.calls.append(a)
        def all_entities(self): return ["dining", "sport room"]
    m = M()
    monkeypatch.setitem(bridge._runtime, "data", {"mirror": m})
    res = bridge.simulate_broadcast("off")
    assert res["ok"] is True and res["action"] == "off"
    assert m.calls == ["off"]


def test_simulate_broadcast_bad_action(monkeypatch):
    assert bridge.simulate_broadcast("dim")["ok"] is False


async def test_ha_online_triggers_reinit(monkeypatch):
    called = []
    async def fake_init(data, client):
        called.append(True)
    monkeypatch.setattr(bridge, "initialize_lamps", fake_init)
    msg = type("M", (), {"payload": b"online"})()
    await bridge.on_message_ha_online(None, {}, msg)
    assert called == [True]


async def test_ha_offline_is_ignored(monkeypatch):
    called = []
    async def fake_init(data, client):
        called.append(True)
    monkeypatch.setattr(bridge, "initialize_lamps", fake_init)
    msg = type("M", (), {"payload": b"offline"})()
    await bridge.on_message_ha_online(None, {}, msg)
    assert called == []


def test_mirror_action_classifier():
    assert bridge.mirror_action(gear.Off(address.Short(20))) == ("off", None)
    assert bridge.mirror_action(gear.RecallMaxLevel(address.Short(20))) == ("on", 100)
    # DAPC on a LAMP address is ignored (bridge's own control -> no feedback loop)
    assert bridge.mirror_action(gear.DAPC(address.Short(20), 254), is_lamp_addr=True) == (None, None)
    # DAPC on a non-lamp (phantom switch) address -> brightness percent
    assert bridge.mirror_action(gear.DAPC(address.Short(20), 127), is_lamp_addr=False)[0] == "on"
    assert bridge.mirror_action(gear.DAPC(address.Short(20), 0), is_lamp_addr=False) == ("off", None)


async def test_switch_recallmax_turns_on(monkeypatch):
    m = await _run_cmd(monkeypatch, gear.RecallMaxLevel(address.Short(20)), mapped={20})
    assert m.set_address_calls == [(20, "on", 100)]


async def test_switch_off_turns_off(monkeypatch):
    m = await _run_cmd(monkeypatch, gear.Off(address.Short(20)), mapped={20})
    assert m.set_address_calls == [(20, "off", None)]


async def test_switch_dapc_ignored_on_lamp(monkeypatch):
    # DAPC to a mapped address that IS a DALI lamp must not loop back
    m = await _run_cmd(monkeypatch, gear.DAPC(address.Short(20), 200), mapped={20}, lamps={20})
    assert m.set_address_calls == []


async def test_switch_dapc_dims_nonlamp(monkeypatch):
    # DAPC to a mapped phantom (non-lamp) address -> brightness percent
    m = await _run_cmd(monkeypatch, gear.DAPC(address.Short(20), 127), mapped={20})
    assert len(m.set_address_calls) == 1
    addr, act, pct = m.set_address_calls[0]
    assert (addr, act) == (20, "on") and pct == 50


async def test_switch_unmapped_address_ignored(monkeypatch):
    m = await _run_cmd(monkeypatch, gear.Off(address.Short(5)), mapped={20})
    assert m.set_address_calls == []


def test_get_switch_map(monkeypatch):
    mirror = type("M", (), {"_switch_map": {20: ["dining"], 10: ["sport room"]}})()
    monkeypatch.setitem(bridge._runtime, "data", {"mirror": mirror})
    sm = bridge.get_switch_map()
    assert sm == [
        {"address": 10, "entities": ["sport room"]},
        {"address": 20, "entities": ["dining"]},
    ]


def test_save_switch_map(monkeypatch):
    calls = {}
    def fake_api(method, path, payload=None):
        calls.setdefault(path, []).append((method, payload))
        if path == "/addons/self/info":
            return {"data": {"options": {"dali_lamps": 64}}}
        return {"result": "ok"}
    monkeypatch.setattr(bridge, "_supervisor_api", fake_api)
    mirror = type("M", (), {"_switch_map": {}})()
    monkeypatch.setitem(bridge._runtime, "data", {"mirror": mirror})
    res = bridge.save_switch_map([
        {"address": 20, "entities": ["dining"]},
        {"address": 99, "entities": ["x"]},        # out of range -> dropped
        {"address": 10, "entities": []},           # no entities -> dropped
    ])
    assert res["ok"] and res["count"] == 1
    # persisted options kept dali_lamps and set switch_map
    posted = calls["/addons/self/options"][0][1]["options"]
    assert posted["dali_lamps"] == 64
    assert posted["switch_map"] == [{"address": 20, "entities": ["dining"]}]
    # live mirror updated
    assert mirror._switch_map == {20: ["dining"]}
