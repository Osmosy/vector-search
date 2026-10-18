"""Общие фикстуры: HTML-страницы и минимальный PDF с текстовым слоем."""

from __future__ import annotations

from pathlib import Path

import pytest

HTML_ARTICLE = """<!doctype html>
<html><head><title>Цена и характеристики</title>
<style>body{color:red}</style>
<script>window.track=1;</script>
</head>
<body>
<h1>Модель X200</h1>
<p>Цена: 1 999 ₽. Вес: 1,5 кг.</p>
<p>Скидка 12 % при оплате картой. В наличии 14 шт.</p>
</body></html>
"""

HTML_CAPTCHA = """<html><head><title>Access denied</title></head>
<body><h1>Are you a robot?</h1><p>Verify you are human to continue.</p></body></html>
"""

HTML_THIN = """<html><body><p>Короткая заглушка.</p></body></html>"""


def _make_pdf(text: str, *, empty: bool = False) -> bytes:
    """Минимальный валидный PDF: одна страница, шрифт Helvetica."""
    if empty:
        content = b""
    else:
        lines = [
            "Vector search verifies every claim against fetched bytes.",
            text,
            "The receipt carries the source url, the quote and the sha256.",
        ]
        ops = " ".join(
            f"72 {720 - i * 16} Td ({line}) Tj" for i, line in enumerate(lines)
        )
        content = f"BT /F1 12 Tf {ops} ET".encode("latin-1")
    objects: list[bytes] = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length " + str(len(content)).encode() + b" >>\nstream\n" + content + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets: list[int] = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n".encode() + body + b"\nendobj\n"
    xref_at = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode()
    out += b"0000000000 65535 f \n"
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode()
    out += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_at}\n%%EOF\n"
    ).encode()
    return bytes(out)


@pytest.fixture
def pdf_with_text(tmp_path: Path) -> Path:
    path = tmp_path / "article.pdf"
    path.write_bytes(_make_pdf("Vector search verifies claims"))
    return path


@pytest.fixture
def pdf_scan(tmp_path: Path) -> Path:
    path = tmp_path / "scan.pdf"
    path.write_bytes(_make_pdf("", empty=True))
    return path


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "network: тест требует выхода в сеть (нужен VSEARCH_NETWORK=1)")
    config.addinivalue_line("markers", "browser: тест требует запущенного браузера и bsk")
