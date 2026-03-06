from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List, Tuple

from mine_agent.capabilities.data_source.models import QueryRequest, QueryResult


class DataSource(ABC):
    @property
    @abstractmethod
    def source_id(self) -> str:
        raise NotImplementedError

    @abstractmethod
    async def test_connection(self) -> bool:
        raise NotImplementedError

    @abstractmethod
    async def execute_query(self, request: QueryRequest) -> QueryResult:
        raise NotImplementedError

    @abstractmethod
    async def list_tables(self, schema: str | None = None) -> List[str]:
        raise NotImplementedError

    @abstractmethod
    async def get_columns(
        self, schema: str | None, table: str
    ) -> List[Tuple[str, str]]:
        """
        Return columns for a table as (column_name, data_type) list.
        """
        raise NotImplementedError
