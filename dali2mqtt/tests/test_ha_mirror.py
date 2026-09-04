"""Tests for app.ha_mirror.HAEntityMirror."""
from app.ha_mirror import HAEntityMirror


class FakeClient:
    def __init__(self):
        self.calls = []

    def connected(self):
        return True

    def find_entity(self, name, types):
        return {"id": "switch.mapped_" + name.replace(" ", "_"),
                "dev_name": name, "state": "off"}

    def execute_service(self, domain, service, data):
        self.calls.append((domain, service, data))


def make_mirror(switch_map):
    m = HAEntityMirror(switch_map, "http://h", "tok", False)
    m._client = FakeClient()   # avoid real HTTP
    return m


def test_enabled_and_mapped():
    m = make_mirror({20: ["dining"]})
    assert m.enabled
    assert m.is_mapped(20)
    assert not m.is_mapped(21)


def test_toggle_address_calls_toggle():
    m = make_mirror({20: ["dining"]})
    m.toggle_address(20)
    assert m._client.calls == [
        ("homeassistant", "toggle", {"entity_id": "switch.mapped_dining"})
    ]


def test_toggle_multiple_entities():
    m = make_mirror({21: ["facade1", "facade2", "facade3"]})
    m.toggle_address(21)
    assert len(m._client.calls) == 3


def test_disabled_when_no_map():
    m = HAEntityMirror({}, "http://h", "tok")
    m._client = FakeClient()
    assert not m.enabled
    m.toggle_address(20)          # must be a no-op
    assert m._client.calls == []


def test_set_all_off_calls_turn_off():
    m = make_mirror({10: ["sport room"], 20: ["dining"]})
    m.set_all("off")
    services = [c[1] for c in m._client.calls]
    assert services == ["turn_off", "turn_off"]


def test_set_all_on_calls_turn_on():
    m = make_mirror({20: ["dining"]})
    m.set_all("on")
    assert m._client.calls[0][1] == "turn_on"


def test_all_entities_dedup():
    m = make_mirror({8: ["radviles"], 13: ["radviles"], 20: ["dining"]})
    assert m.all_entities() == ["radviles", "dining"]


def test_set_all_ignores_bad_action():
    m = make_mirror({20: ["dining"]})
    m.set_all("dim")
    assert m._client.calls == []


def test_set_address_on():
    m = make_mirror({20: ["dining"]})
    m.set_address(20, "on")
    assert m._client.calls == [("homeassistant", "turn_on", {"entity_id": "switch.mapped_dining"})]


def test_set_address_off():
    m = make_mirror({20: ["dining"]})
    m.set_address(20, "off")
    assert m._client.calls[0][1] == "turn_off"


def test_set_address_unmapped_noop():
    m = make_mirror({20: ["dining"]})
    m.set_address(21, "on")
    assert m._client.calls == []


class FakeClientLight:
    def __init__(self):
        self.calls = []
    def connected(self):
        return True
    def find_entity(self, name, types):
        return {"id": "light." + name.replace(" ", "_"), "dev_name": name, "state": "off"}
    def execute_service(self, domain, service, data):
        self.calls.append((domain, service, data))


def test_set_address_brightness_on_light():
    m = HAEntityMirror({15: ["living"]}, "http://h", "tok")
    m._client = FakeClientLight()
    m.set_address(15, "on", 50)
    assert m._client.calls == [
        ("light", "turn_on", {"entity_id": "light.living", "brightness_pct": 50})
    ]


def test_set_address_brightness_ignored_on_switch():
    m = make_mirror({20: ["dining"]})   # FakeClient -> switch.* domain
    m.set_address(20, "on", 50)
    # switch has no brightness -> plain turn_on
    assert m._client.calls == [("homeassistant", "turn_on", {"entity_id": "switch.mapped_dining"})]
