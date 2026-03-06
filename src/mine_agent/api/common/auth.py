from __future__ import annotations

from typing import Optional

from mine_agent.api.common.errors import forbidden_error, unauthorized_error
from mine_agent.config.settings import AppSettings


def validate_bearer_token(
    authorization: Optional[str],
    settings: AppSettings,
) -> None:
    if not settings.api_auth_enabled:
        return

    if not authorization:
        raise unauthorized_error("Missing Authorization header")

    prefix = "Bearer "
    if not authorization.startswith(prefix):
        raise unauthorized_error("Authorization must use Bearer token")

    token = authorization[len(prefix) :].strip()
    if not token:
        raise unauthorized_error("Empty bearer token")

    if token not in settings.api_tokens:
        raise forbidden_error("Invalid API token")
