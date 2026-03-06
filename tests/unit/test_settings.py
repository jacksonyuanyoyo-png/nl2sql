from __future__ import annotations

import pytest

from mine_agent.capabilities.data_source.models import DataSourceType
from mine_agent.config.datasources import DataSourceRegistryConfig
from mine_agent.config.settings import (
    DEFAULT_ALLOWED_SQL_KEYWORDS,
    AppSettings,
)


def test_settings_from_env_defaults(monkeypatch) -> None:
    monkeypatch.delenv("MINE_ENVIRONMENT", raising=False)
    monkeypatch.delenv("MINE_API_AUTH_ENABLED", raising=False)
    monkeypatch.delenv("MINE_API_TOKENS", raising=False)

    settings = AppSettings.from_env()
    assert settings.environment == "dev"
    assert settings.api_auth_enabled is False
    assert settings.api_tokens == []


def test_settings_from_env_custom(monkeypatch) -> None:
    monkeypatch.setenv("MINE_ENVIRONMENT", "prod")
    monkeypatch.setenv("MINE_API_AUTH_ENABLED", "true")
    monkeypatch.setenv("MINE_API_TOKENS", "t1, t2 ,t3")
    monkeypatch.setenv("MINE_SERVICE_NAME", "mine-agent-internal")
    monkeypatch.setenv("MINE_SERVICE_VERSION", "1.2.3")

    settings = AppSettings.from_env()
    assert settings.environment == "prod"
    assert settings.api_auth_enabled is True
    assert settings.api_tokens == ["t1", "t2", "t3"]
    assert settings.service_name == "mine-agent-internal"
    assert settings.service_version == "1.2.3"


def test_default_query_limit_from_env(monkeypatch) -> None:
    monkeypatch.setenv("MINE_DEFAULT_QUERY_LIMIT", "4321")

    settings = AppSettings.from_env()
    assert settings.default_query_limit == 4321


def test_allowed_sql_keywords_default(monkeypatch) -> None:
    """Unset MINE_ALLOWED_SQL_KEYWORDS uses default list."""
    monkeypatch.delenv("MINE_ALLOWED_SQL_KEYWORDS", raising=False)
    settings = AppSettings.from_env()
    assert settings.allowed_sql_keywords == list(DEFAULT_ALLOWED_SQL_KEYWORDS)


def test_allowed_sql_keywords_from_env(monkeypatch) -> None:
    """MINE_ALLOWED_SQL_KEYWORDS (comma-separated) overrides default."""
    monkeypatch.setenv("MINE_ALLOWED_SQL_KEYWORDS", "SELECT, WITH, DESCRIBE")
    settings = AppSettings.from_env()
    assert settings.allowed_sql_keywords == ["SELECT", "WITH", "DESCRIBE"]


# --- Data sources from env (MINE_DATASOURCES) ---


def test_datasources_from_env_empty(monkeypatch) -> None:
    """Unset or empty MINE_DATASOURCES returns empty sources."""
    monkeypatch.delenv("MINE_DATASOURCES", raising=False)
    cfg = DataSourceRegistryConfig.from_env()
    assert cfg.sources == []

    monkeypatch.setenv("MINE_DATASOURCES", "")
    cfg = DataSourceRegistryConfig.from_env()
    assert cfg.sources == []


def test_datasources_from_env_valid_oracle_dsn(monkeypatch) -> None:
    """Valid Oracle config with dsn loads successfully."""
    monkeypatch.setenv(
        "MINE_DATASOURCES",
        '[{"source_id":"ora1","source_type":"oracle","options":{"user":"u","password":"p","dsn":"localhost:1521/XE"}}]',
    )
    cfg = DataSourceRegistryConfig.from_env()
    assert len(cfg.sources) == 1
    assert cfg.sources[0].source_id == "ora1"
    assert cfg.sources[0].source_type == DataSourceType.ORACLE
    assert cfg.sources[0].options["user"] == "u"
    assert cfg.sources[0].options["password"] == "p"
    assert cfg.sources[0].options["dsn"] == "localhost:1521/XE"


def test_datasources_from_env_valid_oracle_host_port_service(monkeypatch) -> None:
    """Valid Oracle config with host/port/service_name loads successfully."""
    monkeypatch.setenv(
        "MINE_DATASOURCES",
        '[{"source_id":"ora2","source_type":"oracle","options":{"user":"u","password":"p","host":"localhost","port":1521,"service_name":"XE"}}]',
    )
    cfg = DataSourceRegistryConfig.from_env()
    assert len(cfg.sources) == 1
    assert cfg.sources[0].source_id == "ora2"
    assert cfg.sources[0].options["host"] == "localhost"
    assert cfg.sources[0].options["port"] == 1521
    assert cfg.sources[0].options["service_name"] == "XE"


def test_datasources_from_env_fail_fast_missing_user(monkeypatch) -> None:
    """Oracle without user raises ValueError."""
    monkeypatch.setenv(
        "MINE_DATASOURCES",
        '[{"source_id":"ora1","source_type":"oracle","options":{"password":"p","dsn":"localhost:1521/XE"}}]',
    )
    with pytest.raises(ValueError, match="missing required options.*user"):
        DataSourceRegistryConfig.from_env()


def test_datasources_from_env_fail_fast_missing_password(monkeypatch) -> None:
    """Oracle without password raises ValueError."""
    monkeypatch.setenv(
        "MINE_DATASOURCES",
        '[{"source_id":"ora1","source_type":"oracle","options":{"user":"u","dsn":"localhost:1521/XE"}}]',
    )
    with pytest.raises(ValueError, match="missing required options.*password"):
        DataSourceRegistryConfig.from_env()


def test_datasources_from_env_fail_fast_missing_connection(monkeypatch) -> None:
    """Oracle without dsn or host/port/service raises ValueError."""
    monkeypatch.setenv(
        "MINE_DATASOURCES",
        '[{"source_id":"ora1","source_type":"oracle","options":{"user":"u","password":"p"}}]',
    )
    with pytest.raises(ValueError, match="missing required options.*host"):
        DataSourceRegistryConfig.from_env()


def test_datasources_from_env_fail_fast_partial_host(monkeypatch) -> None:
    """Oracle with host but missing port/service_name raises ValueError."""
    monkeypatch.setenv(
        "MINE_DATASOURCES",
        '[{"source_id":"ora1","source_type":"oracle","options":{"user":"u","password":"p","host":"localhost"}}]',
    )
    with pytest.raises(ValueError, match="missing required options"):
        DataSourceRegistryConfig.from_env()


def test_datasources_from_env_invalid_json(monkeypatch) -> None:
    """Invalid JSON in MINE_DATASOURCES raises ValueError."""
    monkeypatch.setenv("MINE_DATASOURCES", "not json")
    with pytest.raises(ValueError, match="must be valid JSON"):
        DataSourceRegistryConfig.from_env()


def test_datasources_from_env_not_array(monkeypatch) -> None:
    """MINE_DATASOURCES that is not a JSON array raises ValueError."""
    monkeypatch.setenv("MINE_DATASOURCES", '{"key":"value"}')
    with pytest.raises(ValueError, match="must be a JSON array"):
        DataSourceRegistryConfig.from_env()


def test_app_settings_datasources_from_env(monkeypatch) -> None:
    """AppSettings.datasources_from_env delegates to DataSourceRegistryConfig.from_env."""
    monkeypatch.setenv(
        "MINE_DATASOURCES",
        '[{"source_id":"ora1","source_type":"oracle","options":{"user":"u","password":"p","dsn":"x"}}]',
    )
    cfg = AppSettings.datasources_from_env()
    assert len(cfg.sources) == 1
    assert cfg.sources[0].source_id == "ora1"
