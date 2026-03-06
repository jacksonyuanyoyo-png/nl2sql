from __future__ import annotations

import asyncio

from mine_agent.capabilities.data_source.router import DataSourceRouter
from mine_agent.core.tool.registry import ToolRegistry
from mine_agent.engine.orchestrator import Orchestrator
from mine_agent.integrations.local.storage import InMemoryConversationStore
from mine_agent.integrations.mock.llm import MockLlmService
from mine_agent.integrations.oracle.client import OracleDataSource
from mine_agent.integrations.snowflake.client import SnowflakeDataSource
from mine_agent.tools.query_data import QueryDataTool


async def main() -> None:
    router = DataSourceRouter()
    router.register(
        OracleDataSource(
            source_id="oracle_demo",
            connection_options={"dsn": "oracle-host:1521/ORCL"},
        )
    )
    router.register(
        SnowflakeDataSource(
            source_id="snowflake_demo",
            connection_options={"account": "demo_account"},
        )
    )

    tool_registry = ToolRegistry()
    tool_registry.register(QueryDataTool(router=router))

    orchestrator = Orchestrator(
        llm_service=MockLlmService(),
        tool_registry=tool_registry,
        conversation_store=InMemoryConversationStore(),
    )

    result = await orchestrator.chat(
        conversation_id="conv-1",
        user_id="u-1",
        user_message="SELECT * FROM dual",
    )
    print(result)


if __name__ == "__main__":
    asyncio.run(main())
