"""Tests for app.ha_client (Supervisor-proxy fallback + fuzzy entity match)."""
from app.ha_client import HomeAssistantClient, _similarity


def test_similarity():
    assert _similarity("dining", "dining") == 100
    assert _similarity("abc", "xyz") < 50


def test_from_config_explicit():
    c = HomeAssistantClient.from_config("http://h:8123", "tok", False)
    assert c is not None and c.url == "http://h:8123"


def test_from_config_supervisor_proxy(monkeypatch):
    monkeypatch.setenv("SUPERVISOR_TOKEN", "xyz")
    c = HomeAssistantClient.from_config("", "")
    assert c is not None and c.url == "http://supervisor/core"


def test_from_config_none(monkeypatch):
    monkeypatch.delenv("SUPERVISOR_TOKEN", raising=False)
    assert HomeAssistantClient.from_config("", "") is None


def test_find_entity_matches_best():
    c = HomeAssistantClient("http://h", "t")
    states = [
        {"entity_id": "switch.sonoff_x", "state": "off",
         "attributes": {"friendly_name": "dining"}},
        {"entity_id": "light.kitchen", "state": "on",
         "attributes": {"friendly_name": "kitchen"}},
    ]
    c._get_state = lambda: states
    e = c.find_entity("dining", ["switch", "light"])
    assert e["id"] == "switch.sonoff_x"


def test_find_entity_respects_domain_filter():
    c = HomeAssistantClient("http://h", "t")
    states = [{"entity_id": "sensor.dining", "state": "1",
               "attributes": {"friendly_name": "dining"}}]
    c._get_state = lambda: states
    assert c.find_entity("dining", ["switch", "light"]) is None


def test_find_entity_no_match():
    c = HomeAssistantClient("http://h", "t")
    c._get_state = lambda: [{"entity_id": "light.kitchen", "state": "on",
                             "attributes": {"friendly_name": "kitchen"}}]
    assert c.find_entity("zzzzzz", ["light"]) is None
