from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import Field

from iw_agent.core.schemas import AgentModel
from iw_agent.modules.ssl.schemas import Certificate


class VirtualHost(AgentModel):
    config_path: str
    server_names: list[str] = Field(default_factory=list)
    listen_ports: list[int] = Field(default_factory=list)
    upstream: Optional[str] = None
    ssl_enabled: bool = False
    cert_path: Optional[str] = None
    enabled: bool = True
    parse_ok: bool = True
    parse_error: Optional[str] = None
    raw_config: Optional[str] = None


class SslStatus(str, Enum):
    NO_SSL = "no_ssl"
    SSL_OK = "ssl_ok"
    SSL_EXPIRING = "ssl_expiring"
    SSL_EXPIRED = "ssl_expired"
    SSL_MISMATCH = "ssl_mismatch"
    SSL_ORPHAN = "ssl_orphan"


class SiteProfile(AgentModel):
    virtual_host: VirtualHost
    certificate: Optional[Certificate] = None
    ssl_status: SslStatus = SslStatus.NO_SSL
    recommendation: Optional[str] = None


class SecurityPreset(str, Enum):
    NONE = "none"
    BASIC = "basic"
    STRICT = "strict"


MANAGED_SECURITY_HEADER_NAMES = frozenset(
    {
        "X-Frame-Options",
        "X-Content-Type-Options",
        "Referrer-Policy",
        "Strict-Transport-Security",
        "Permissions-Policy",
    },
)


def security_headers_for_preset(preset: SecurityPreset) -> list[tuple[str, str]]:
    basic = [
        ("X-Frame-Options", "SAMEORIGIN"),
        ("X-Content-Type-Options", "nosniff"),
        ("Referrer-Policy", "strict-origin-when-cross-origin"),
    ]
    if preset is SecurityPreset.NONE:
        return []
    if preset is SecurityPreset.BASIC:
        return basic
    if preset is SecurityPreset.STRICT:
        return basic + [
            ("Strict-Transport-Security", "max-age=31536000; includeSubDomains"),
            ("Permissions-Policy", "geolocation=(), microphone=(), camera=()"),
        ]
    raise ValueError(f"unknown security preset: {preset}")


TRY_FILES_STANDARD = "$uri $uri/ =404"
TRY_FILES_SPA = "$uri $uri/ /index.html"
DEFAULT_INDEX_FILES = "index.html index.htm"


class SiteKind(str, Enum):
    STATIC = "static"
    PROXY = "proxy"


class ListenEndpoint(AgentModel):
    port: int
    ssl: bool = False
    address: Optional[str] = None

    def display(self) -> str:
        if self.address == "::":
            host = "[::]"
        elif self.address:
            host = self.address
        else:
            host = "*"
        ssl = " ssl" if self.ssl else ""
        return f"{host}:{self.port}{ssl}"

    def to_nginx_line(self, indent: str = "") -> str:
        ssl_part = " ssl" if self.ssl else ""
        if self.address == "::":
            return f"{indent}listen [::]:{self.port}{ssl_part};"
        if self.address:
            return f"{indent}listen {self.address}:{self.port}{ssl_part};"
        return f"{indent}listen {self.port}{ssl_part};"


class LocationBlock(AgentModel):
    path: str
    proxy_pass: Optional[str] = None
    root: Optional[str] = None
    alias: Optional[str] = None
    try_files: Optional[str] = None

    def summary(self) -> str:
        if self.proxy_pass:
            return f"proxy → {self.proxy_pass}"
        if self.alias:
            return f"alias {self.alias}"
        if self.root:
            return f"root {self.root}"
        if self.try_files:
            return f"try_files {self.try_files}"
        return "empty"


