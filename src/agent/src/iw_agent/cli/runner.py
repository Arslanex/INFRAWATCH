from __future__ import annotations

import asyncio
import sys
from collections.abc import Awaitable, Callable
from typing import TypeVar

from iw_agent.core.exceptions import AgentError

T = TypeVar("T")


def run_async(handler: Callable[[], Awaitable[T | None]]) -> int:
    try:
        asyncio.run(handler())
    except AgentError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        return 130
    return 0
