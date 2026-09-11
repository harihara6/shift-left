from typing import Any

from app.connectors.base import Connector
from app.connectors.live import REGISTRY as _REAL
from app.connectors.mock import MockConnector

# Which connector's config/secrets are merged in ahead of its own before it is built, since it
# has no credential of its own - see connectors.json's auth method for each ("Shares the Jira /
# GitHub connection") and live.py's JsmConnector / CiConnector docstrings.
SHARED_CREDENTIALS: dict[str, str] = {"jsm": "jira", "ci": "github"}


def get_connector(key: str, name: str, config: dict[str, Any], secrets: dict[str, str]) -> Connector:
    cls = _REAL.get(key)
    if cls is not None:
        return cls(key, name, config, secrets)
    return MockConnector(key, name, config, secrets)
