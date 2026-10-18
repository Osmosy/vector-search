"""Журнал источников: каждая запись раскрывается до байтов полученного текста.

Запись хранит не только адрес, но и то, что реально пришло: финальный URL после
редиректов, HTTP-статус, тип содержимого, размер, хеш текста и время получения.
Текст лежит рядом в ``store/<sha256>.txt``; при чтении хеш сверяется, поэтому
подмена файла в хранилище не проходит молча.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterator, Optional


class LedgerError(Exception):
    """Журнал или хранилище текстов повреждены."""


def text_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


@dataclass
class Source:
    id: int
    url: str
    final_url: str
    fetched_at: str
    status: int
    content_type: str
    chars: int
    sha256: str
    provider: str
    redirects: list[str] = field(default_factory=list)
    error: Optional[str] = None
    title: str = ""

    @property
    def ok(self) -> bool:
        """Источник годится для доказательств только если текст реально получен."""
        return self.error is None and self.status == 200 and self.chars > 0


class Ledger:
    """Журнал в JSONL плюс хранилище текстов в каталоге ``store``."""

    def __init__(
        self,
        path: str | os.PathLike[str],
        store: str | os.PathLike[str] | None = None,
    ) -> None:
        self.path = Path(path)
        self.store = Path(store) if store is not None else self.path.parent / "store"
        self.store.mkdir(parents=True, exist_ok=True)
        self._by_id: dict[int, Source] = {}
        if self.path.exists():
            self._load()

    # ── чтение ────────────────────────────────────────────────────────────────

    def _load(self) -> None:
        with self.path.open(encoding="utf-8") as fh:
            for lineno, line in enumerate(fh, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    src = Source(**obj)
                except (json.JSONDecodeError, TypeError) as exc:
                    raise LedgerError(f"{self.path}:{lineno}: битая запись журнала: {exc}") from exc
                self._by_id[src.id] = src

    def __len__(self) -> int:
        return len(self._by_id)

    def __iter__(self) -> Iterator[Source]:
        return iter(sorted(self._by_id.values(), key=lambda s: s.id))

    def get(self, source_id: int) -> Optional[Source]:
        return self._by_id.get(source_id)

    def __contains__(self, source_id: object) -> bool:
        return source_id in self._by_id

    def by_url(self, url: str) -> Optional[Source]:
        for src in self._by_id.values():
            if src.url == url or src.final_url == url:
                return src
        return None

    def text(self, source_id: int) -> str:
        """Текст источника с проверкой целостности по хешу."""
        src = self._by_id.get(source_id)
        if src is None:
            raise LedgerError(f"источника [{source_id}] нет в журнале")
        if src.error is not None:
            raise LedgerError(f"источник [{source_id}] не прочитан: {src.error}")
        path = self.store / f"{src.sha256}.txt"
        if not path.exists():
            raise LedgerError(f"текст источника [{source_id}] отсутствует: {path}")
        text = path.read_text(encoding="utf-8")
        actual = text_sha256(text)
        if actual != src.sha256:
            raise LedgerError(
                f"хеш текста источника [{source_id}] не совпадает: "
                f"{actual} != {src.sha256}"
            )
        return text

    # ── запись ────────────────────────────────────────────────────────────────

    def add(
        self,
        *,
        url: str,
        final_url: str | None = None,
        status: int = 0,
        content_type: str = "",
        text: str = "",
        provider: str = "httpx",
        redirects: list[str] | None = None,
        error: str | None = None,
        title: str = "",
        fetched_at: str | None = None,
    ) -> Source:
        """Добавить запись. Неудачное чтение тоже пишется — с текстом ошибки."""
        sha = text_sha256(text) if text else ""
        if text:
            (self.store / f"{sha}.txt").write_text(text, encoding="utf-8")
        next_id = max(self._by_id, default=0) + 1
        src = Source(
            id=next_id,
            url=url,
            final_url=final_url or url,
            fetched_at=fetched_at or utc_now(),
            status=status,
            content_type=content_type,
            chars=len(text),
            sha256=sha,
            provider=provider,
            redirects=list(redirects or []),
            error=error,
            title=title,
        )
        self._by_id[src.id] = src
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(asdict(src), ensure_ascii=False) + "\n")
        return src

    def record_failure(self, url: str, error: str, *, status: int = 0, provider: str = "httpx") -> Source:
        return self.add(url=url, status=status, provider=provider, error=error)

    # ── экспорт ───────────────────────────────────────────────────────────────

    def as_dicts(self) -> list[dict[str, Any]]:
        return [asdict(s) for s in self]
