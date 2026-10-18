"""Извлечение текста: HTML без скриптов и стилей, PDF с проверкой текстового слоя."""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from html.parser import HTMLParser
from pathlib import Path

_SKIP_TAGS = {"script", "style", "noscript", "template", "svg", "head"}
_BLOCK_TAGS = {
    "p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6",
    "section", "article", "header", "footer", "blockquote", "pre", "table", "ul", "ol",
}


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []
        self._skip_depth = 0
        self._title_parts: list[str] = []
        self._in_title = False

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in _SKIP_TAGS:
            self._skip_depth += 1
        elif tag == "title":
            self._in_title = True
        if tag in _BLOCK_TAGS:
            self._parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP_TAGS:
            self._skip_depth = max(0, self._skip_depth - 1)
        elif tag == "title":
            self._in_title = False
        if tag in _BLOCK_TAGS:
            self._parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self._title_parts.append(data)
        if self._skip_depth:
            return
        if data.strip():
            self._parts.append(data)

    @property
    def text(self) -> str:
        raw = "".join(self._parts)
        raw = raw.replace("\xa0", " ")
        lines = [re.sub(r"[ \t]+", " ", line).strip() for line in raw.splitlines()]
        return "\n".join(line for line in lines if line)

    @property
    def title(self) -> str:
        return " ".join("".join(self._title_parts).split())


def html_to_text(html: str) -> str:
    parser = _TextExtractor()
    parser.feed(html)
    parser.close()
    return parser.text


def html_title(html: str) -> str:
    parser = _TextExtractor()
    parser.feed(html)
    parser.close()
    return parser.title


def pdf_to_text(path: str | Path) -> tuple[str, dict[str, int]]:
    """Текст PDF и статистика покрытия: сколько страниц реально содержат текст.

    Скан без текстового слоя даёт пустые страницы — это фиксируется как отсутствие
    текста, а не как успешно прочитанный документ.
    """
    path = Path(path)
    if shutil.which("pdftotext") is None:
        raise RuntimeError("нет pdftotext (poppler-utils): PDF не читается")
    proc = subprocess.run(
        ["pdftotext", "-layout", str(path), "-"],
        capture_output=True,
        timeout=120,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"pdftotext вернул {proc.returncode}: {proc.stderr.decode('utf-8', 'replace')[:200]}")
    raw = proc.stdout.decode("utf-8", "replace")
    pages = raw.split("\f")
    if pages and not pages[-1].strip():
        pages = pages[:-1]
    with_text = sum(1 for p in pages if len(p.strip()) >= 40)
    text = "\n".join(
        line.rstrip() for page in pages for line in page.splitlines()
    ).strip()
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text, {"pages": len(pages), "pages_with_text": with_text}


def pdf_bytes_to_text(data: bytes) -> tuple[str, dict[str, int]]:
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as fh:
        fh.write(data)
        tmp = Path(fh.name)
    try:
        return pdf_to_text(tmp)
    finally:
        tmp.unlink(missing_ok=True)


def looks_like_captcha(text: str, headers: dict[str, str] | None = None) -> bool:
    """Грубая эвристика: страница-заглушка вместо содержимого."""
    low = text.lower()[:2000]
    markers = (
        "captcha",
        "are you a robot",
        "verify you are human",
        "access denied",
        "request blocked",
        "enable javascript",
        "проверка на робота",
        "доступ ограничен",
    )
    if any(m in low for m in markers):
        return True
    if headers:
        for key in ("cf-mitigated", "x-captcha", "x-ratelimit-remaining"):
            if key in {k.lower() for k in headers}:
                return True
    return False
