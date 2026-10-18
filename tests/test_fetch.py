"""Строгое чтение: сеть подменяется транспортом httpx, реальных запросов нет."""

from __future__ import annotations

import httpx
import pytest

from vsearch.fetch import check_url, fetch

PUBLIC = lambda host: ["93.184.216.34"]  # noqa: E731 — резолвер-заглушка


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False)


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "ftp://example.com/x",
        "http://localhost/x",
        "http://127.0.0.1/x",
        "http://169.254.169.254/latest/meta-data/",
        "http://metadata.google.internal/x",
        "http://10.0.0.5/x",
    ],
)
def test_private_and_bad_schemes_blocked(url: str) -> None:
    ok, reason = check_url(url, PUBLIC)
    assert not ok, reason


def test_public_host_allowed() -> None:
    ok, reason = check_url("https://example.com/a", PUBLIC)
    assert ok, reason


def test_host_resolving_to_private_blocked() -> None:
    ok, reason = check_url("https://evil.example/a", lambda host: ["10.0.0.5"])
    assert not ok and "непубличный" in reason


def test_200_html_read() -> None:
    html = "<html><head><title>T</title></head><body>" + ("текст страницы " * 60) + "</body></html>"
    client = _client(lambda request: httpx.Response(200, headers={"content-type": "text/html; charset=utf-8"}, text=html))
    result = fetch("https://example.com/a", client=client, resolver=PUBLIC, min_chars=100)
    assert result.ok, result.error
    assert result.status == 200
    assert "текст страницы" in result.text
    assert result.title == "T"


def test_404_is_error_not_text() -> None:
    client = _client(lambda request: httpx.Response(404, headers={"content-type": "text/html"}, text="not found"))
    result = fetch("https://example.com/a", client=client, resolver=PUBLIC)
    assert not result.ok
    assert "HTTP 404" in (result.error or "")


def test_redirect_to_private_host_is_blocked() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "example.com":
            return httpx.Response(302, headers={"location": "http://127.0.0.1/secret"})
        return httpx.Response(200, text="ok")

    client = _client(handler)
    result = fetch("https://example.com/a", client=client, resolver=PUBLIC)
    assert not result.ok
    assert "127.0.0.1" in (result.error or "")


def test_short_page_is_refused() -> None:
    client = _client(lambda request: httpx.Response(200, headers={"content-type": "text/html"}, text="<p>мало</p>"))
    result = fetch("https://example.com/a", client=client, resolver=PUBLIC, min_chars=400)
    assert not result.ok
    assert "меньше порога" in (result.error or "")


def test_captcha_page_is_refused() -> None:
    html = "<html><body><h1>Are you a robot?</h1>" + ("verify you are human " * 40) + "</body></html>"
    client = _client(lambda request: httpx.Response(200, headers={"content-type": "text/html"}, text=html))
    result = fetch("https://example.com/a", client=client, resolver=PUBLIC, min_chars=100)
    assert not result.ok
    assert "капчу" in (result.error or "")


def test_unsupported_type_refused() -> None:
    client = _client(lambda request: httpx.Response(200, headers={"content-type": "image/png"}, content=b"\x89PNG"))
    result = fetch("https://example.com/a", client=client, resolver=PUBLIC)
    assert not result.ok
    assert "не поддерживается" in (result.error or "")


def test_too_many_redirects() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": "https://example.com/next"})

    client = _client(handler)
    result = fetch("https://example.com/a", client=client, resolver=PUBLIC, max_redirects=2)
    assert not result.ok
    assert "редиректов" in (result.error or "")
