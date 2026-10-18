"""Строгое чтение страницы.

Провайдеры поиска отдают текст без метаданных страницы: нельзя узнать, был ли это
200, не отдали ли вместо статьи заглушку и не ушёл ли редирект на другой хост.
Для решений нужен собственный загрузчик, который проверяет каждый шаг и пишет
в журнал то, что реально произошло.
"""

from __future__ import annotations

import ipaddress
import socket
from dataclasses import dataclass, field
from typing import Callable, Iterable, Optional
from urllib.parse import urljoin, urlsplit

import httpx

from .extract import html_title, html_to_text, looks_like_captcha, pdf_bytes_to_text

DEFAULT_TIMEOUT = 60.0
DEFAULT_MAX_BYTES = 5 * 1024 * 1024
DEFAULT_MIN_CHARS = 400
DEFAULT_MAX_REDIRECTS = 5

ALLOWED_TYPES = (
    "text/html",
    "application/xhtml+xml",
    "text/plain",
    "application/pdf",
)

_REDIRECT_CODES = {301, 302, 303, 307, 308}
_BLOCKED_HOSTS = {"localhost", "metadata.google.internal", "metadata"}

Resolver = Callable[[str], Iterable[str]]


@dataclass
class FetchResult:
    url: str
    final_url: str
    status: int = 0
    content_type: str = ""
    text: str = ""
    redirects: list[str] = field(default_factory=list)
    title: str = ""
    error: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.error is None and self.status == 200 and bool(self.text)


def _default_resolver(host: str) -> list[str]:
    infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    return sorted({str(info[4][0]) for info in infos})


def _is_public_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if ip.is_private or ip.is_loopback or ip.is_link_local:
        return False
    if ip.is_reserved or ip.is_multicast or ip.is_unspecified:
        return False
    if ip in ipaddress.ip_network("169.254.169.254/32"):
        return False
    return ip.is_global


def check_url(url: str, resolver: Resolver | None = None) -> tuple[bool, str]:
    """Допустим ли адрес для чтения: схема, хост и адреса, в которые он резолвится."""
    parts = urlsplit(url)
    if parts.scheme.lower() not in {"http", "https"}:
        return False, f"схема {parts.scheme or '—'} не http/https"
    host = (parts.hostname or "").strip().lower()
    if not host:
        return False, "в адресе нет хоста"
    if host in _BLOCKED_HOSTS or host.endswith(".localhost"):
        return False, f"локальный хост {host}"

    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None
    if literal is not None:
        return (_is_public_ip(literal), "" if _is_public_ip(literal) else f"адрес {host} не публичный")

    resolve = resolver or _default_resolver
    try:
        addresses = list(resolve(host))
    except OSError as exc:
        return False, f"хост {host} не резолвится: {exc}"
    if not addresses:
        return False, f"хост {host} не резолвится"
    for addr in addresses:
        try:
            ip = ipaddress.ip_address(addr)
        except ValueError:
            return False, f"непонятный адрес {addr} для {host}"
        if not _is_public_ip(ip):
            return False, f"хост {host} ведёт на непубличный адрес {addr}"
    return True, ""


def _charset(content_type: str) -> str:
    for part in content_type.split(";")[1:]:
        key, _, value = part.strip().partition("=")
        if key.lower() == "charset" and value:
            return value.strip().strip('"')
    return "utf-8"


def fetch(
    url: str,
    *,
    timeout: float = DEFAULT_TIMEOUT,
    max_bytes: int = DEFAULT_MAX_BYTES,
    min_chars: int = DEFAULT_MIN_CHARS,
    max_redirects: int = DEFAULT_MAX_REDIRECTS,
    client: httpx.Client | None = None,
    resolver: Resolver | None = None,
) -> FetchResult:
    """Прочитать страницу или вернуть причину отказа. Ошибка — не текст."""
    result = FetchResult(url=url, final_url=url)
    current = url
    own_client = client is None
    client = client or httpx.Client(
        follow_redirects=False,
        timeout=timeout,
        headers={"User-Agent": "vector-search/0.1 (+verified retrieval)"},
    )
    try:
        for _ in range(max_redirects + 1):
            ok, reason = check_url(current, resolver)
            if not ok:
                result.error = f"{current}: {reason}"
                return result
            try:
                response = client.get(current)
            except httpx.HTTPError as exc:
                result.error = f"{current}: сетевая ошибка: {exc}"
                return result

            result.status = response.status_code
            if response.status_code in _REDIRECT_CODES:
                location = response.headers.get("location")
                if not location:
                    result.error = f"{current}: редирект {response.status_code} без location"
                    return result
                current = urljoin(current, location)
                result.final_url = current
                result.redirects.append(current)
                continue

            ctype = (response.headers.get("content-type") or "").split(";")[0].strip().lower()
            result.content_type = ctype
            if response.status_code != 200:
                result.error = f"{current}: HTTP {response.status_code}"
                return result
            if not any(ctype == allowed or ctype.endswith("+" + allowed.split("/")[-1]) for allowed in ALLOWED_TYPES):
                if ctype not in ALLOWED_TYPES:
                    result.error = f"{current}: тип {ctype or '—'} не поддерживается"
                    return result

            data = response.content
            if len(data) > max_bytes:
                result.error = f"{current}: ответ больше лимита {max_bytes} байт"
                return result

            if ctype == "application/pdf":
                text, stats = pdf_bytes_to_text(data)
                if stats["pages"] and stats["pages_with_text"] == 0:
                    result.error = f"{current}: PDF без текстового слоя (скан)"
                    return result
            else:
                html = data.decode(_charset(response.headers.get("content-type", "")), "replace")
                result.title = html_title(html)
                text = html_to_text(html)

            if looks_like_captcha(text, dict(response.headers)):
                result.error = f"{current}: страница похожа на капчу или блокировку"
                return result
            if len(text) < min_chars:
                result.error = (
                    f"{current}: текста {len(text)} символов, меньше порога {min_chars}"
                )
                return result

            result.text = text
            return result

        result.error = f"{url}: больше {max_redirects} редиректов"
        return result
    finally:
        if own_client:
            client.close()
