"""Браузерный рендер для страниц, которые собираются JavaScript.

HTML-оболочка без текста — это не «пустая страница», а страница, которую надо
отрендерить. Рендер подключается как отдельный движок, чтобы библиотека не тянула
браузер в зависимости: по умолчанию используется `bsk` (browser-skill), если он есть.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import time
from dataclasses import dataclass
from typing import Protocol


class BrowserError(Exception):
    """Браузер не смог открыть страницу."""


@dataclass
class RenderResult:
    text: str
    title: str = ""
    provider: str = "browser"


class Renderer(Protocol):
    name: str

    def available(self) -> bool: ...

    def render(self, url: str, timeout: float = 60.0) -> RenderResult: ...


def _json_from(output: str) -> dict:
    start = output.find("{")
    if start < 0:
        raise BrowserError(f"нет JSON в выводе: {output.strip()[:200]}")
    try:
        return json.loads(output[start:])
    except json.JSONDecodeError as exc:
        raise BrowserError(f"вывод не разобрался: {exc}") from exc


class BskRenderer:
    """Рендер через CLI browser-skill (`bsk`): session → navigate → innerText → stop."""

    name = "bsk"

    def __init__(self, binary: str = "bsk", *, settle: float = 2.0) -> None:
        self.binary = binary
        self.settle = settle

    def available(self) -> bool:
        return shutil.which(self.binary) is not None

    def _run(self, args: list[str], timeout: float) -> str:
        proc = subprocess.run(
            [self.binary, *args],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        if proc.returncode != 0:
            detail = (proc.stderr or proc.stdout).strip().splitlines()
            raise BrowserError(detail[-1][:300] if detail else f"код {proc.returncode}")
        return proc.stdout

    def render(self, url: str, timeout: float = 60.0) -> RenderResult:
        if not self.available():
            raise BrowserError(f"{self.binary} не найден в PATH")
        session = ""
        try:
            start = _json_from(self._run(["session", "start", "--json", "--name", "vsearch"], timeout))
            session = str(start.get("session_id") or "")
            if not session:
                raise BrowserError("bsk не вернул session_id")
            self._run(["navigate", "--session", session, url], timeout)
            if self.settle:
                time.sleep(self.settle)
            text = self._run(["evaluate", "--session", session, "document.body.innerText"], timeout)
            title = ""
            try:
                title = self._run(["evaluate", "--session", session, "document.title"], timeout).strip()
            except BrowserError:
                title = ""
            return RenderResult(text=text.strip(), title=title.strip(), provider=f"browser:{self.name}")
        finally:
            if session:
                try:
                    self._run(["session", "stop", session], 30)
                except (BrowserError, subprocess.TimeoutExpired):
                    pass
