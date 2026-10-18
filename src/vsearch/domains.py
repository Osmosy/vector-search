"""Домены: независимость источников для правила двух подтверждений.

Два URL на одном сайте — не два независимых подтверждения: это одна редакция,
один автор и одна ошибка. Независимость считается по registrable domain (eTLD+1),
без внешних зависимостей — с коротким списком двухуровневых суффиксов.
"""

from __future__ import annotations

from urllib.parse import urlsplit

# Наиболее частые двухуровневые публичные суффиксы; списка PSL достаточно для
# практики, а полный PSL тянул бы зависимость ради одной функции.
_TWO_LEVEL_SUFFIXES = {
    "co.uk", "org.uk", "ac.uk", "gov.uk", "co.jp", "ne.jp", "or.jp", "co.kr",
    "com.au", "net.au", "org.au", "co.nz", "com.br", "com.cn", "com.tr", "com.ua",
    "co.in", "co.za", "com.mx", "com.ar", "com.sg", "com.hk", "com.tw",
}


def host_of(url: str) -> str:
    return (urlsplit(url).hostname or "").lower().strip(".")


def registrable_domain(url: str) -> str:
    """eTLD+1: «news.example.co.uk» → «example.co.uk», «a.example.com» → «example.com»."""
    host = host_of(url)
    if not host:
        return ""
    parts = host.split(".")
    if len(parts) <= 2:
        return host
    suffix = ".".join(parts[-2:])
    if suffix in _TWO_LEVEL_SUFFIXES and len(parts) >= 3:
        return ".".join(parts[-3:])
    return suffix


def independent_domains(urls: list[str]) -> set[str]:
    return {d for d in (registrable_domain(u) for u in urls) if d}
