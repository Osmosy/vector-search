"""Проверка утверждения: цитата, источники, числа."""

from __future__ import annotations

from pathlib import Path

import pytest

from vsearch.claims import Claim, ClaimError, claims_from_json, validate_claim
from vsearch.ledger import Ledger

TEXT = "Модель X200 стоит 1 999 ₽ и весит 1,5 кг. Скидка 12 % при оплате картой."


@pytest.fixture
def ledger(tmp_path: Path) -> Ledger:
    led = Ledger(tmp_path / "ledger.jsonl")
    led.add(url="https://example.com/x200", final_url="https://example.com/x200", status=200,
            content_type="text/html", text=TEXT, title="X200")
    led.add(url="https://example.com/missing", status=404, content_type="text/html",
            error="HTTP 404")
    return led


def test_quote_found_verbatim(ledger: Ledger) -> None:
    claim = Claim(id=1, text="Цена 1 999 ₽", source_ids=[1],
                  quote="стоит 1 999 ₽ и весит 1,5 кг", numbers=["1999"])
    assert validate_claim(claim, ledger) == []


def test_quote_normalizes_whitespace(ledger: Ledger) -> None:
    claim = Claim(id=1, text="Цена", source_ids=[1], quote="стоит  1 999 ₽\nи весит")
    assert validate_claim(claim, ledger) == []


def test_quote_not_in_source(ledger: Ledger) -> None:
    claim = Claim(id=1, text="Цена", source_ids=[1], quote="стоит 1 899 ₽ и весит 1,5 кг")
    errors = validate_claim(claim, ledger)
    assert any("не найдена дословно" in e for e in errors)


def test_quote_too_short(ledger: Ledger) -> None:
    claim = Claim(id=1, text="Цена", source_ids=[1], quote="1 999 ₽")
    assert any("короче" in e for e in validate_claim(claim, ledger))


def test_missing_quote_is_error_by_default(ledger: Ledger) -> None:
    claim = Claim(id=1, text="Цена", source_ids=[1])
    assert any("нет дословной цитаты" in e for e in validate_claim(claim, ledger))


def test_no_sources(ledger: Ledger) -> None:
    assert "нет ни одного источника" in validate_claim(Claim(id=1, text="x", source_ids=[]), ledger)


def test_unknown_source(ledger: Ledger) -> None:
    claim = Claim(id=1, text="x", source_ids=[99], quote="стоит 1 999 ₽")
    assert any("отсутствует в журнале" in e for e in validate_claim(claim, ledger))


def test_failed_source_cannot_prove(ledger: Ledger) -> None:
    claim = Claim(id=1, text="x", source_ids=[2], quote="любые три слова")
    assert any("не прочитан" in e for e in validate_claim(claim, ledger))


def test_number_missing_in_source(ledger: Ledger) -> None:
    claim = Claim(id=1, text="Цена", source_ids=[1], quote="стоит 1 999 ₽ и весит 1,5 кг",
                  numbers=["1899"])
    assert any("чисел нет в тексте" in e for e in validate_claim(claim, ledger))


def test_claims_from_json_shape() -> None:
    claims = claims_from_json({"claims": [{"text": "a", "source_ids": [1], "quote": "b c d"}]})
    assert claims[0].id == 1 and claims[0].source_ids == [1]


def test_claims_from_json_rejects_empty_text() -> None:
    with pytest.raises(ClaimError):
        claims_from_json([{"text": "  ", "source_ids": [1]}])
