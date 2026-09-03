"""Minimal Home Assistant REST API client.

Used to mirror physical DALI switch presses onto Home Assistant entities.
Authentication and endpoint are fully configuration driven: when running as a
Home Assistant add-on the Supervisor proxy (``http://supervisor/core`` with the
``SUPERVISOR_TOKEN``) is used, so no host/IP or long-lived token is ever stored
in the source tree.
"""
import json
import logging
from difflib import SequenceMatcher

from requests import get, post
from requests.exceptions import RequestException, Timeout

logger = logging.getLogger(__name__)

# Timeout (seconds) for HA requests
TIMEOUT = 10


def _similarity(a, b):
    """Return a 0-100 fuzzy match score between two strings."""
    return SequenceMatcher(None, a, b).ratio() * 100


class HomeAssistantClient:
    def __init__(self, base_url, token, verify_ssl=True):
        self.url = base_url.rstrip("/")
        self.verify = verify_ssl
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

    @classmethod
    def from_config(cls, base_url, token, verify_ssl=False):
        """Build a client, returning None when not configured."""
        if not base_url or not token:
            return None
        return cls(base_url, token, verify_ssl)

    def _get_state(self):
        req = get(
            f"{self.url}/api/states",
            headers=self.headers,
            verify=self.verify,
            timeout=TIMEOUT,
        )
        req.raise_for_status()
        return req.json()

    def connected(self):
        try:
            self._get_state()
            return True
        except (Timeout, ConnectionError, RequestException) as err:
            logger.warning("Home Assistant not reachable: %s", err)
            return False

    def find_entity(self, entity, types):
        """Find an entity by fuzzy-matching friendly name or entity id."""
        json_data = self._get_state()
        best_score = 50  # require a score above 50%
        best_entity = None
        if not json_data:
            return None
        for state in json_data:
            try:
                if state["entity_id"].split(".")[0] not in types:
                    continue
                for candidate in (
                    state["attributes"]["friendly_name"].lower(),
                    state["entity_id"].lower(),
                ):
                    score = _similarity(entity, candidate)
                    if score > best_score:
                        best_score = score
                        best_entity = {
                            "id": state["entity_id"],
                            "dev_name": state["attributes"]["friendly_name"],
                            "state": state["state"],
                            "best_score": best_score,
                        }
            except KeyError:
                pass
        return best_entity

    def execute_service(self, domain, service, data):
        r = post(
            f"{self.url}/api/services/{domain}/{service}",
            headers=self.headers,
            data=json.dumps(data),
            verify=self.verify,
            timeout=TIMEOUT,
        )
        r.raise_for_status()
        return r
