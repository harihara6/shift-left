"""The connector contract (TDD s6).

Every source integration implements exactly this surface, so the normalization engine and the
settings UI never need to know which system they are talking to.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class SyncResult:
    ok: bool
    records: int = 0
    synced_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    message: str = ""


@dataclass
class TestResult:
    ok: bool
    message: str
    capabilities: list[str] = field(default_factory=list)
    filters: list[str] = field(default_factory=list)


class Connector(ABC):
    key: str
    name: str

    def __init__(self, config: dict[str, Any], secrets: dict[str, str]) -> None:
        self.config = config
        # Vault references, not values. A connector resolves one only at call time.
        self.secrets = secrets

    @abstractmethod
    async def test_connection(self) -> TestResult: ...

    @abstractmethod
    async def list_capabilities(self) -> list[str]: ...

    @abstractmethod
    async def list_available_filters(self) -> list[str]: ...

    @abstractmethod
    async def preview_data(self, query: str, limit: int = 10) -> list[dict[str, Any]]: ...

    @abstractmethod
    async def sync(self, query: str, mode: str = "incremental") -> SyncResult: ...

    @abstractmethod
    def map_to_canonical_model(self, raw: list[dict[str, Any]]) -> list[dict[str, Any]]: ...
