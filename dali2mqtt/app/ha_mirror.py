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

    def toggle_address(self, address):
        """Toggle every Home Assistant entity mapped to a DALI address."""
        if not self.enabled:
            return
        for entity in self._switch_map.get(address, []):
            self._toggle_entity(entity)

    def _toggle_entity(self, entity):
        try:
            if not self._client.connected():
                return
            ha_entity = self._client.find_entity(entity, MIRROR_ENTITY_TYPES)
            if not ha_entity:
                logger.warning("No Home Assistant entity matched '%s'", entity)
                return
            self._client.execute_service(
                "homeassistant", "toggle", {"entity_id": ha_entity["id"]}
            )
            logger.info("Toggled Home Assistant entity %s", ha_entity["id"])
        except Exception as err:  # noqa: BLE001 - never let mirroring break the bridge
            logger.error("Failed to toggle entity '%s': %s", entity, err)
