from __future__ import annotations

from typing import List, Tuple

import pytest

from mine_agent.capabilities.data_source.base import DataSource
from mine_agent.capabilities.data_source.errors import UnknownDataSourceError
from mine_agent.capabilities.data_source.models import QueryRequest, QueryResult
from mine_agent.capabilities.data_source.router import DataSourceRouter


class FakeDataSource(DataSource):
    def __init__(
        self,
        source_id: str,
        *,
        health_ok: bool = True,
        health_raises: bool = False,
    ) -> None:
        self._source_id = source_id
        self._health_ok = health_ok
        self._health_raises = health_raises

    @property
    def source_id(self) -> str:
        return self._source_id

    async def test_connection(self) -> bool:
        if self._health_raises:
            raise RuntimeError("connection failed")
        return self._health_ok

    async def execute_query(self, request: QueryRequest) -> QueryResult:
        return QueryResult(
            columns=["col1"],
            rows=[{"col1": 1}],
            row_count=1,
        )

    async def list_tables(self, schema: str | None = None) -> List[str]:
        return []

    async def get_columns(self, schema: str | None, table: str) -> List[Tuple[str, str]]:
        return []


@pytest.mark.asyncio
async def test_register_and_get_source() -> None:
    router = DataSourceRouter()
    source = FakeDataSource("s1")
    router.register(source)
    assert router.get_source("s1") is source
    assert router.list_source_ids() == ["s1"]


@pytest.mark.asyncio
async def test_register_duplicate_raises() -> None:
    router = DataSourceRouter()
    router.register(FakeDataSource("s1"))
    with pytest.raises(ValueError, match="already registered: s1"):
        router.register(FakeDataSource("s1"))


@pytest.mark.asyncio
async def test_get_source_unknown_raises() -> None:
    router = DataSourceRouter()
    router.register(FakeDataSource("s1"))
    with pytest.raises(UnknownDataSourceError, match="Unknown data source: s2"):
        router.get_source("s2")


@pytest.mark.asyncio
async def test_execute_query_unknown_source_raises() -> None:
    router = DataSourceRouter()
    router.register(FakeDataSource("s1"))
    request = QueryRequest(source_id="s2", sql="SELECT 1")
    with pytest.raises(UnknownDataSourceError, match="Unknown data source: s2"):
        await router.execute_query(request)


@pytest.mark.asyncio
async def test_list_source_ids() -> None:
    router = DataSourceRouter()
    assert router.list_source_ids() == []
    router.register(FakeDataSource("a"))
    router.register(FakeDataSource("b"))
    ids = router.list_source_ids()
    assert set(ids) == {"a", "b"}
    assert len(ids) == 2


@pytest.mark.asyncio
async def test_health_check_all() -> None:
    router = DataSourceRouter()
    router.register(FakeDataSource("ok", health_ok=True))
    router.register(FakeDataSource("fail", health_ok=False))
    router.register(FakeDataSource("raises", health_raises=True))
    result = await router.health_check_all()
    assert result == {"ok": True, "fail": False, "raises": False}
