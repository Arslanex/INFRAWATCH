from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum, auto
from typing import Any

from iw_agent.cli.output import clear_screen, print_nav_hint, print_page_header


class PageResult(Enum):
    STAY = auto()
    BACK = auto()
    EXIT = auto()


@dataclass
class PageContext:
    args: Any
    data: dict[str, Any]


class Page(ABC):
    @property
    @abstractmethod
    def title(self) -> str:
        raise NotImplementedError

    @property
    def subtitle(self) -> str:
        return ""

    async def on_enter(self, context: PageContext) -> None:
        return None

    @abstractmethod
    def render(self, context: PageContext) -> None:
        raise NotImplementedError

    @abstractmethod
    async def handle(self, context: PageContext) -> PageResult | Page:
        raise NotImplementedError


class Navigator:
    def __init__(self, context: PageContext) -> None:
        self._context = context
        self._stack: list[Page] = []

    async def run(self, root: Page) -> None:
        self._stack = [root]
        await root.on_enter(self._context)

        while self._stack:
            page = self._stack[-1]
            clear_screen()
            print_page_header(page.title, page.subtitle)
            page.render(self._context)
            print_nav_hint(allow_back=len(self._stack) > 1)
            result = await page.handle(self._context)

            if result is PageResult.STAY:
                continue
            if result is PageResult.BACK:
                self._stack.pop()
                continue
            if result is PageResult.EXIT:
                return
            if isinstance(result, Page):
                self._stack.append(result)
                await result.on_enter(self._context)
                continue
            raise TypeError(f"unexpected page result: {result!r}")

    def push(self, page: Page) -> None:
        self._stack.append(page)

    def pop(self) -> None:
        if self._stack:
            self._stack.pop()
