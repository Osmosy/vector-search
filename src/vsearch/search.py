"""Поиск: только выдача, без текста страниц.

Провайдер отдаёт ссылки и сниппеты — этого достаточно, чтобы выбрать страницы.
Текст приходит отдельным строгим чтением, иначе нельзя отличить 200 от заглушки.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Protocol
from urllib.parse import parse_qs, unquote, urlparse

import httpx


@dataclass(frozen=True)
class Hit:
    title: str
    url: str
    snippet: str = ""
    position: int = 0


class SearchProvider(Protocol):
    name: str

    def search(self, query: str, limit: int = 8) -> list[Hit]: ...


@dataclass
class StaticSearch:
    """Выдача из файла или теста: провайдер без сети."""

    results: dict[str, list[Hit]] = field(default_factory=dict)
    default: list[Hit] = field(default_factory=list)
    name: str = "static"

    def search(self, query: str, limit: int = 8) -> list[Hit]:
        hits = self.results.get(query, self.default)
        return list(hits[:limit])


class _DdgParser(HTMLParser):
    """Разбор html.duckduckgo.com: ссылки result__a и сниппеты result__snippet."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.hits: list[Hit] = []
        self._current: dict[str, str] | None = None
        self._capture: str | None = None
        self._buffer: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        attrs = dict(attrs)
        classes = (attrs.get("class") or "").split()
        if tag == "a" and "result__a" in classes:
            href = attrs.get("href") or ""
            self._current = {"url": _clean_ddg_url(href), "title": "", "snippet": ""}
            self._capture = "title"
            self._buffer = []
        elif "result__snippet" in classes and self._current is not None:
            self._capture = "snippet"
            self._buffer = []

    def handle_data(self, data: str) -> None:
        if self._capture:
            self._buffer.append(data)

    def handle_endtag(self, tag: str) -> None:
        if not self._capture or self._current is None:
            return
        if tag in {"a", "div", "span"}:
            text = " ".join("".join(self._buffer).split())
            if self._capture == "title":
                self._current["title"] = text
            elif self._capture == "snippet":
                self._current["snippet"] = text
                self.hits.append(
                    Hit(
                        title=self._current["title"],
                        url=self._current["url"],
                        snippet=text,
                        position=len(self.hits) + 1,
                    )
                )
                self._current = None
            self._capture = None
            self._buffer = []


def _clean_ddg_url(href: str) -> str:
    """DuckDuckGo заворачивает ссылки в /l/?uddg=<target>."""
    if href.startswith("//"):
        href = "https:" + href
    parsed = urlparse(href)
    if parsed.path.startswith("/l/"):
        target = parse_qs(parsed.query).get("uddg")
        if target:
            return unquote(target[0])
    return href


class DuckDuckGoSearch:
    """HTML-выдача DuckDuckGo: без ключа, но и без гарантий доступности."""

    name = "duckduckgo"

    def __init__(self, timeout: float = 20.0, client: httpx.Client | None = None) -> None:
        self.timeout = timeout
        self._client = client

    def search(self, query: str, limit: int = 8) -> list[Hit]:
        own = self._client is None
        client = self._client or httpx.Client(
            timeout=self.timeout,
            follow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 (compatible; vector-search/0.1)"},
        )
        try:
            response = client.post(
                "https://html.duckduckgo.com/html/",
                data={"q": query},
            )
            response.raise_for_status()
        finally:
            if own:
                client.close()
        parser = _DdgParser()
        parser.feed(response.text)
        parser.close()
        return parser.hits[:limit]


def hits_from_json(payload: Iterable[dict] | dict[str, list[dict]]) -> dict[str, list[Hit]]:
    """Файл выдачи: {"запрос": [{title, url, snippet}]} или [{query, title, url}]."""
    grouped: dict[str, list[Hit]] = {}
    if isinstance(payload, dict):
        for query, items in payload.items():
            grouped[str(query)] = [
                Hit(
                    title=str(item.get("title", "")),
                    url=str(item["url"]),
                    snippet=str(item.get("snippet", "")),
                    position=i + 1,
                )
                for i, item in enumerate(items)
            ]
        return grouped
    for i, item in enumerate(payload):
        key = str(item.get("query", ""))
        grouped.setdefault(key, []).append(
            Hit(
                title=str(item.get("title", "")),
                url=str(item["url"]),
                snippet=str(item.get("snippet", "")),
                position=i + 1,
            )
        )
    return grouped
