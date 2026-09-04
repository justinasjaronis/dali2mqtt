"""Mirror physical DALI switch presses onto Home Assistant entities.

Replaces the previously hard-coded ``DEVICE_TO_ENTITY_MAP`` / ``set_state``
logic. The address->entities map and the Home Assistant connection are supplied
entirely through configuration (see :class:`~app.config.Config`).
"""
import logging

from .ha_client import HomeAssistantClient

logger = logging.getLogger(__name__)

# Entity domains eligible for fuzzy matching.
MIRROR_ENTITY_TYPES = [
    "group",
    "light",
    "fan",
    "switch",
    "scene",
    "input_boolean",
]


class HAEntityMirror:
    """Toggle Home Assistant entities when mapped DALI addresses change."""

    def __init__(self, switch_map, base_url, token, verify_ssl=False):
        self._switch_map = switch_map or {}
        self._client = HomeAssistantClient.from_config(base_url, token, verify_ssl)

    @property
    def enabled(self):
        return bool(self._switch_map) and self._client is not None

    def is_mapped(self, address):
        return address in self._switch_map

    def all_entities(self):
        """Every unique Home Assistant entity across the whole switch map."""
        seen = []
        for entities in self._switch_map.values():
            for entity in entities:
                if entity not in seen:
                    seen.append(entity)
        return seen

    def toggle_address(self, address):
        """Toggle every Home Assistant entity mapped to a DALI address."""
        if not self.enabled:
            return
        for entity in self._switch_map.get(address, []):
            self._call_entity(entity, "toggle")

    def set_address(self, address, action, brightness_pct=None):
        """Turn every entity mapped to a DALI address on/off.

        Used when a physical switch sends an explicit on-command
        (RecallMaxLevel) or off-command (Off), rather than a toggle. When
        `brightness_pct` is given and the target entity is a `light`, it is set
        to that brightness percentage instead of a plain on.
        """
        if not self.enabled or action not in ("on", "off"):
            return
        for entity in self._switch_map.get(address, []):
            self._call_entity(entity, action, brightness_pct)

    def set_all(self, action):
        """Set every mapped entity to a fixed state (`on`/`off`).

        Used to mirror a DALI **broadcast** all-off / all-on (e.g. a bedside
        "everything off" switch) onto the mapped Home Assistant entities.
        """
        if not self.enabled or action not in ("on", "off"):
            return
        for entity in self.all_entities():
            self._call_entity(entity, action)

    def _call_entity(self, entity, action, brightness_pct=None):
        """Apply an action ('on'/'off'/'toggle') to one mapped HA entity.

        For a brightness-capable `light` entity with an explicit on-level, uses
        `light.turn_on` with `brightness_pct`; otherwise the domain-agnostic
        `homeassistant.turn_on/turn_off/toggle` service.
        """
        try:
            if not self._client.connected():
                return
            ha_entity = self._client.find_entity(entity, MIRROR_ENTITY_TYPES)
            if not ha_entity:
                logger.warning("No Home Assistant entity matched '%s'", entity)
                return
            entity_id = ha_entity["id"]
            domain = entity_id.split(".")[0]
            if (
                action == "on"
                and brightness_pct is not None
                and domain == "light"
            ):
                self._client.execute_service(
                    "light", "turn_on",
                    {"entity_id": entity_id, "brightness_pct": int(brightness_pct)},
                )
                logger.info("light %s -> %s%%", entity_id, int(brightness_pct))
            else:
                self._client.execute_service(
                    "homeassistant", f"turn_{action}" if action != "toggle" else "toggle",
                    {"entity_id": entity_id},
                )
                logger.info("%s Home Assistant entity %s", action, entity_id)
        except Exception as err:  # noqa: BLE001 - never let mirroring break the bridge
            logger.error("Failed to %s entity '%s': %s", action, entity, err)
