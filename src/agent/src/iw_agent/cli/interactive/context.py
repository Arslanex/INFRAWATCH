"""Shared state bag passed through an interactive command session."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class PageContext:
    args: Any
    data: dict[str, Any]
