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
