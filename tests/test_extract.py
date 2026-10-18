"""Извлечение текста: HTML без скриптов и стилей, PDF с проверкой покрытия."""

from __future__ import annotations

from pathlib import Path

from vsearch.extract import html_title, html_to_text, looks_like_captcha, pdf_to_text

from tests.conftest import HTML_ARTICLE, HTML_CAPTCHA


def test_html_text_skips_scripts_and_styles() -> None:
    text = html_to_text(HTML_ARTICLE)
    assert "Цена: 1 999 ₽" in text
    assert "window.track" not in text
    assert "color:red" not in text


def test_html_title() -> None:
    assert html_title(HTML_ARTICLE) == "Цена и характеристики"


def test_block_elements_become_lines() -> None:
    text = html_to_text(HTML_ARTICLE)
    assert "\n" in text
    assert "В наличии 14 шт." in text


def test_captcha_detected() -> None:
    text = html_to_text(HTML_CAPTCHA)
    assert looks_like_captcha(text)


def test_captcha_not_detected_in_article() -> None:
    assert not looks_like_captcha(html_to_text(HTML_ARTICLE))


def test_pdf_with_text_layer(pdf_with_text: Path) -> None:
    text, stats = pdf_to_text(pdf_with_text)
    assert "Vector search verifies every claim" in text
    assert stats["pages"] == 1
    assert stats["pages_with_text"] == 1


def test_pdf_scan_has_no_text(pdf_scan: Path) -> None:
    text, stats = pdf_to_text(pdf_scan)
    assert text.strip() == ""
    assert stats["pages_with_text"] == 0
