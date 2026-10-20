"""Shared Amap Web Service credential and boundary helpers.

One key, one rate gate.  The existing route client already reads the key from
the ``amap-maps`` MCP entry; this module adds the ``AMAP_WEB_SERVICE_KEY``
alias used by the standalone integration and is shared by POI/geocoding.
"""

from __future__ import annotations

import os

from ..config import get_settings

AMAP_RATE_GATE_KEY = "mcp:amap-maps"
AMAP_KEY_ENV_NAMES = ("AMAP_WEB_SERVICE_KEY", "AMAP_MAPS_API_KEY")


class AmapServiceError(RuntimeError):
    """Base class for bounded Amap failures."""

    code = "amap_error"

    def __init__(self, message: str, *, code: str | None = None):
        super().__init__(message)
        if code:
            self.code = code


class AmapNotConfigured(AmapServiceError):
    code = "not_configured"


class AmapTimeout(AmapServiceError):
    code = "timeout"


class AmapResponseError(AmapServiceError):
    code = "provider_refused"

    def __init__(self, message: str, *, info: str = "", infocode: str = ""):
        super().__init__(message)
        self.info = info
        self.infocode = infocode


def amap_api_key() -> str:
    """Return the configured Web Service key without ever logging it."""

    for name in AMAP_KEY_ENV_NAMES:
        value = os.getenv(name, "").strip()
        if value:
            return value
    server = get_settings().mcp_servers.get("amap-maps")
    value = str((server.env or {}).get("AMAP_MAPS_API_KEY") or "").strip() if server else ""
    if value:
        return value
    raise AmapNotConfigured(
        "高德 Web 服务 Key 未配置；请在本机 app/.env 设置 "
        "AMAP_WEB_SERVICE_KEY（或兼容的 AMAP_MAPS_API_KEY）后重启。"
    )


def amap_min_interval_seconds() -> float:
    server = get_settings().mcp_servers.get("amap-maps")
    return float(server.min_interval_seconds) if server is not None else 0.0


__all__ = [
    "AMAP_KEY_ENV_NAMES",
    "AMAP_RATE_GATE_KEY",
    "AmapNotConfigured",
    "AmapResponseError",
    "AmapServiceError",
    "AmapTimeout",
    "amap_api_key",
    "amap_min_interval_seconds",
]
