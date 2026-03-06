from __future__ import annotations

from typing import Dict

from mine_agent.capabilities.data_source.base import DataSource
from mine_agent.capabilities.data_source.errors import UnknownDataSourceError
from mine_agent.capabilities.data_source.models import QueryRequest, QueryResult


class DataSourceRouter:
    def __init__(self) -> None:
        self._sources: Dict[str, DataSource] = {}

    def register(self, source: DataSource) -> None:
        if source.source_id in self._sources:
            raise ValueError(
                f"Data source already registered: {source.source_id}"
            )
        self._sources[source.source_id] = source

    def get_source(self, source_id: str) -> DataSource:
        source = self._sources.get(source_id)
        if source is None:
            raise UnknownDataSourceError(
                f"Unknown data source: {source_id}",
                source_id=source_id,
            )
        return source

    def list_source_ids(self) -> list[str]:
        return list(self._sources.keys())

    async def health_check_all(self) -> dict[str, bool]:
        result: dict[str, bool] = {}
        for source_id, source in self._sources.items():
            try:
                result[source_id] = await source.test_connection()
            except Exception:
                result[source_id] = False
        return result

    async def execute_query(self, request: QueryRequest) -> QueryResult:
        source = self._sources.get(request.source_id)
        if source is None:
            raise UnknownDataSourceError(
                f"Unknown data source: {request.source_id}",
                source_id=request.source_id,
            )
        return await source.execute_query(request=request)
