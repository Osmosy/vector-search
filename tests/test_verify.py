"""Гейт и квитанция."""

from __future__ import annotations

from pathlib import Path

import pytest

from vsearch.claims import Claim
from vsearch.ledger import Ledger
from vsearch.verify import receipt, summary, verify

TEXT = "Средний результат 42,7 из 105 при семи прогонах."


@pytest.fixture
def ledger(tmp_path: Path) -> Ledger:
    led = Ledger(tmp_path / "ledger.jsonl")
    led.add(url="https://example.com/a", status=200, content_type="text/html", text=TEXT)
    return led


def test_all_claims_proven(ledger: Ledger) -> None:
    claims = [
        Claim(id=1, text="42.7 из 105", source_ids=[1], quote="42,7 из 105 при семи прогонах",
              numbers=["42.7", "105"]),
    ]
    report = verify(claims, ledger)
    assert report.ok, report.errors
    assert report.coverage == 1.0
    assert summary(report).startswith("OK")


def test_unproven_claim_blocks(ledger: Ledger) -> None:
    claims = [
        Claim(id=1, text="ok", source_ids=[1], quote="42,7 из 105 при семи прогонах"),
        Claim(id=2, text="плохое", source_ids=[1], quote="такой фразы в источнике нет"),
    ]
    report = verify(claims, ledger)
    assert not report.ok
    assert report.coverage == 0.5
    assert any("[2]" in e for e in report.errors)


def test_empty_claims_block(ledger: Ledger) -> None:
    report = verify([], ledger)
    assert not report.ok


def test_receipt_has_hash_and_time(ledger: Ledger) -> None:
    claims = [Claim(id=1, text="42.7", source_ids=[1], quote="42,7 из 105 при семи прогонах")]
    table = receipt(claims, ledger)
    src = ledger.get(1)
    assert src is not None
    assert "sha256" in table
    assert src.sha256[:12] in table
    assert "https://example.com/a" in table
    assert src.fetched_at in table


def test_unused_source_is_warning(ledger: Ledger) -> None:
    claims = [Claim(id=1, text="42.7", source_ids=[1], quote="42,7 из 105 при семи прогонах")]
    report = verify(claims, ledger)
    assert report.ok
