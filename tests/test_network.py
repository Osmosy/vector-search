"""Живая сеть и живой браузер: по умолчанию выключены.

Запуск: ``VSEARCH_NETWORK=1 uv run pytest -m network`` и
``VSEARCH_NETWORK=1 uv run pytest -m browser``.
"""

from __future__ import annotations

import os
import shutil
import uuid

import pytest

from vsearch.browser import BrowserError, BskRenderer
from vsearch.fetch import check_url, fetch

network = pytest.mark.skipif(
    os.getenv("VSEARCH_NETWORK") != "1",
    reason="живая сеть выключена; включить VSEARCH_NETWORK=1",
)
browser = pytest.mark.skipif(
    os.getenv("VSEARCH_NETWORK") != "1" or shutil.which("bsk") is None,
    reason="нужны VSEARCH_NETWORK=1 и bsk",
)

pytestmark = pytest.mark.network


@network
def test_real_page_read(tmp_path) -> None:
    from vsearch.ledger import Ledger

    ledger = Ledger(tmp_path / "ledger.jsonl")
    result = fetch("https://www.python.org/about/", timeout=45, min_chars=400)
    assert result.ok, result.error
    assert result.status == 200
    assert len(result.text) > 400
    src = ledger.add(
        url=result.url,
        final_url=result.final_url,
        status=result.status,
        content_type=result.content_type,
        text=result.text,
        provider=result.provider,
    )
    assert ledger.text(src.id) == result.text


@network
def test_real_404_is_error() -> None:
    url = f"https://www.python.org/definitely-missing-{uuid.uuid4().hex}"
    result = fetch(url, timeout=45)
    assert not result.ok
    assert "HTTP 404" in (result.error or "")


@network
def test_private_address_blocked_without_network() -> None:
    ok, reason = check_url("http://169.254.169.254/latest/meta-data/")
    assert not ok and "публичный" in reason


@browser
@pytest.mark.browser
def test_js_page_rendered_by_browser() -> None:
    result = fetch("https://quotes.toscrape.com/js/", timeout=90, allow_browser=True,
                   renderer=BskRenderer())
    assert result.ok, result.error
    assert result.provider.startswith("browser:")
    assert "Einstein" in result.text or "quote" in result.text.lower()


@network
def test_browser_renderer_reports_missing_binary() -> None:
    renderer = BskRenderer(binary="bsk-does-not-exist")
    assert renderer.available() is False
    with pytest.raises(BrowserError):
        renderer.render("https://example.com")
