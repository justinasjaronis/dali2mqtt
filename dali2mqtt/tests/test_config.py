"""Tests for app.config.Config option parsing."""
from app.config import Config


def test_switch_map_parsing():
    Config().setup({
        "switch_map": [
            {"address": 10, "entities": ["sport room"]},
            {"address": 20, "entities": ["dining"]},
        ]
    })
    assert Config().switch_map == {10: ["sport room"], 20: ["dining"]}


def test_switch_map_empty_default():
    Config().setup({})
    assert Config().switch_map == {}


def test_ha_conf_defaults_to_empty():
    Config().setup({})
    assert Config().ha_conf == ("", "", False)
