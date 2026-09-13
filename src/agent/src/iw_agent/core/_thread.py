from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, TypeVar

T = TypeVar("T")

_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="iw-collector")


async def read(fn: Callable[..., T], *args) -> T:
    """Run a blocking host reading off the event loop, always on the same thread."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_executor, fn, *args)
