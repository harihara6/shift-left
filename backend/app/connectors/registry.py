from typing import Any

from app.connectors.base import Connector
from app.connectors.mock import MockConnector

# Real adapters register here as each is built; until then every key resolves to the mock,
# which answers the same contract.
_REAL: dict[str, type[Connector]] = {}


def get_connector(key: str, name: str, config: dict[str, Any], secrets: dict[str, str]) -> Connector:
    cls = _REAL.get(key)
    if cls is not None:
        return cls(config, secrets)
    return MockConnector(key, name, config, secrets)
