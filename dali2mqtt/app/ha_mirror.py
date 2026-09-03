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

    def set_address(self, address, action):
        """Turn every entity mapped to a DALI address on/off.

        Used when a physical switch sends an explicit on-command
        (RecallMaxLevel) or off-command (Off), rather than a toggle.
        """
        if not self.enabled or action not in ("on", "off"):
            return
        service = f"turn_{action}"
        for entity in self._switch_map.get(address, []):
            self._call_entity(entity, service)

    def set_all(self, action):
        """Set every mapped entity to a fixed state (`on`/`off`).

        Used to mirror a DALI **broadcast** all-off / all-on (e.g. a bedside
        "everything off" switch) onto the mapped Home Assistant entities.
        """
        if not self.enabled or action not in ("on", "off"):
            return
        service = f"turn_{action}"
        for entity in self.all_entities():
            self._call_entity(entity, service)

    def _call_entity(self, entity, service):
        try:
            if not self._client.connected():
                return
            ha_entity = self._client.find_entity(entity, MIRROR_ENTITY_TYPES)
            if not ha_entity:
                logger.warning("No Home Assistant entity matched '%s'", entity)
                return
            self._client.execute_service(
                "homeassistant", service, {"entity_id": ha_entity["id"]}
            )
            logger.info("%s Home Assistant entity %s", service, ha_entity["id"])
        except Exception as err:  # noqa: BLE001 - never let mirroring break the bridge
            logger.error("Failed to %s entity '%s': %s", service, entity, err)
