"""Досье: утверждения, оценка достаточности и покрытие вопросов."""

from __future__ import annotations

from pathlib import Path

import pytest

from vsearch.dossier import SufficiencyError, check_dossier, parse_sufficiency, summarize_dossier
from vsearch.ledger import Ledger

TEXT = "Средний результат 42,7 из 105 при семи прогонах. Стоимость $1.84."


@pytest.fixture
def ledger(tmp_path: Path) -> Ledger:
    led = Ledger(tmp_path / "ledger.jsonl")
    led.add(url="https://a.example/x", status=200, content_type="text/html", text=TEXT)
    return led


def dossier_payload(**overrides):
    base = {
        "questions": ["средний результат"],
        "claims": [
            {
                "id": 1,
                "text": "средний результат 42,7 из 105",
                "source_ids": [1],
                "quote": "42,7 из 105 при семи прогонах",
                "numbers": ["42.7", "105"],
            }
        ],
        "sufficiency": {"answered": True, "gaps": [], "next_queries": []},
    }
    base.update(overrides)
    return base


def test_complete_dossier_passes(ledger: Ledger) -> None:
    result = check_dossier(dossier_payload(), ledger)
    assert result.ok, result.report.errors
    assert summarize_dossier(result).startswith("OK")


def test_answered_with_gaps_is_contradiction(ledger: Ledger) -> None:
    payload = dossier_payload(sufficiency={"answered": True, "gaps": ["нет цены"]})
    result = check_dossier(payload, ledger)
    assert not result.ok
    assert any("противоречие" in e for e in result.report.errors)


def test_answered_without_claims_is_contradiction(ledger: Ledger) -> None:
    payload = dossier_payload(claims=[], sufficiency={"answered": True})
    result = check_dossier(payload, ledger)
    assert not result.ok


def test_not_answered_without_gaps_is_contradiction(ledger: Ledger) -> None:
    payload = dossier_payload(sufficiency={"answered": False, "gaps": []})
    result = check_dossier(payload, ledger)
    assert not result.ok
    assert any("пробелы не названы" in e for e in result.report.errors)


def test_question_without_claim_is_uncovered(ledger: Ledger) -> None:
    payload = dossier_payload(questions=["средний результат", "стоимость подписки навсегда"])
    result = check_dossier(payload, ledger)
    assert not result.ok
    assert result.uncovered == ["стоимость подписки навсегда"]


def test_answered_must_be_bool() -> None:
    with pytest.raises(SufficiencyError):
        parse_sufficiency({"answered": "true"})


def test_gaps_must_be_strings() -> None:
    with pytest.raises(SufficiencyError):
        parse_sufficiency({"answered": False, "gaps": [1]})


def test_claim_without_evidence_blocks(ledger: Ledger) -> None:
    payload = dossier_payload(claims=[{"id": 1, "text": "средний результат", "source_ids": [1]}])
    result = check_dossier(payload, ledger)
    assert not result.ok


def test_next_queries_parsed_aliases() -> None:
    s = parse_sufficiency({"answered": False, "gaps": ["x"], "next_search_queries": ["y"]})
    assert s.next_queries == ["y"]
