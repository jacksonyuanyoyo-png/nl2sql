"""
Integration test configuration for Oracle.

Provides fixtures and skip logic when oracledb or env vars are missing.
Environment variables (example):
  - MINE_ORACLE_HOST, MINE_ORACLE_PORT, MINE_ORACLE_SERVICE
  - MINE_ORACLE_USER, MINE_ORACLE_PASSWORD
  - Optional MINE_ORACLE_DSN (overrides host/port/service when set)
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, Dict

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
SRC_PATH = PROJECT_ROOT / "src"

if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))


def _oracledb_available() -> bool:
    """Check if oracledb is installed."""
    try:
        import oracledb  # noqa: F401
        return True
    except ImportError:
        return False


def _oracle_env_available() -> bool:
    """Check if required Oracle connection env vars are set."""
    dsn = os.environ.get("MINE_ORACLE_DSN")
    if dsn:
        user = os.environ.get("MINE_ORACLE_USER")
        password = os.environ.get("MINE_ORACLE_PASSWORD")
        return bool(user and password)
    host = os.environ.get("MINE_ORACLE_HOST")
    port = os.environ.get("MINE_ORACLE_PORT")
    service = os.environ.get("MINE_ORACLE_SERVICE")
    user = os.environ.get("MINE_ORACLE_USER")
    password = os.environ.get("MINE_ORACLE_PASSWORD")
    return bool(host and port and service and user and password)


def _build_connection_options() -> Dict[str, Any]:
    """Build connection_options from env vars."""
    opts: Dict[str, Any] = {
        "user": os.environ["MINE_ORACLE_USER"],
        "password": os.environ["MINE_ORACLE_PASSWORD"],
    }
    dsn = os.environ.get("MINE_ORACLE_DSN")
    if dsn:
        opts["dsn"] = dsn
    else:
        opts["host"] = os.environ["MINE_ORACLE_HOST"]
        opts["port"] = int(os.environ.get("MINE_ORACLE_PORT", "1521"))
        opts["service_name"] = os.environ["MINE_ORACLE_SERVICE"]
    return opts


@pytest.fixture(scope="module")
def oracle_integration_available() -> None:
    """
    Skip integration tests when oracledb is not installed or env vars are missing.
    CI typically has no Oracle; tests are skipped automatically.
    """
    if not _oracledb_available():
        pytest.skip(
            "oracledb not installed. Install with: pip install mine-agent[oracle]",
        )
    if not _oracle_env_available():
        pytest.skip(
            "Oracle env vars missing. Set MINE_ORACLE_USER, MINE_ORACLE_PASSWORD, "
            "and either MINE_ORACLE_DSN or (MINE_ORACLE_HOST, MINE_ORACLE_PORT, MINE_ORACLE_SERVICE)",
        )


@pytest.fixture
def oracle_connection_options(oracle_integration_available: None) -> Dict[str, Any]:
    """Connection options built from env vars. Requires oracle_integration_available."""
    return _build_connection_options()


@pytest.fixture
def oracle_data_source(oracle_connection_options: Dict[str, Any]):
    """OracleDataSource instance with connection_options from env."""
    from mine_agent.integrations.oracle.client import OracleDataSource

    return OracleDataSource(
        source_id="integration_test",
        connection_options=oracle_connection_options,
    )
