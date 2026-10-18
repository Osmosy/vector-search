"""Независимость источников: два URL одного сайта — не два подтверждения."""

from __future__ import annotations

from pathlib import Path

import pytest

from vsearch.claims import Claim, validate_claim
from vsearch.domains import host_of, independent_domains, registrable_domain
from vsearch.ledger import Ledger

TEXT = "Средний результат 42,7 из 105 при семи прогонах."


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://example.com/a", "example.com"),
        ("https://news.example.com/a", "example.com"),
        ("https://a.b.example.co.uk/x", "example.co.uk"),
        ("https://example.org", "example.org"),
        ("https://sub.example.org:8443/x", "example.org"),
        ("http://localhost:8000/x", "localhost"),
    ],
)
def test_registrable_domain(url: str, expected: str) -> None:
    assert registrable_domain(url) == expected


def test_host_of_strips_port() -> None:
    assert host_of("https://Example.COM:443/x") == "example.com"


def test_independent_domains() -> None:
    assert independent_domains(["https://a.example.com/1", "https://b.example.com/2", "https://other.org/"]) == {
        "example.com",
        "other.org",
    }


@pytest.fixture
def ledger(tmp_path: Path) -> Ledger:
    led = Ledger(tmp_path / "ledger.jsonl")
    led.add(url="https://a.example.com/x", status=200, content_type="text/html", text=TEXT)
    led.add(url="https://b.example.com/y", status=200, content_type="text/html", text=TEXT)
    led.add(url="https://other.org/z", status=200, content_type="text/html", text=TEXT)
    return led


def critical_claim(sources: list[int]) -> Claim:
    return Claim(
        id=1,
        text="средний результат 42,7 из 105",
        source_ids=sources,
        quote="42,7 из 105 при семи прогонах",
        numbers=["42.7", "105"],
        critical=True,
    )


def test_critical_number_needs_two_domains(ledger: Ledger) -> None:
    assert validate_claim(critical_claim([1, 3]), ledger) == []


def test_two_urls_same_domain_are_one_source(ledger: Ledger) -> None:
    errors = validate_claim(critical_claim([1, 2]), ledger)
    assert any("независимыми" in e for e in errors)


def test_single_source_is_not_enough(ledger: Ledger) -> None:
    errors = validate_claim(critical_claim([1]), ledger)
    assert any("из 2" in e for e in errors)


def test_non_critical_claim_needs_one_source(ledger: Ledger) -> None:
    claim = critical_claim([1])
    claim.critical = False
    assert validate_claim(claim, ledger) == []


def test_critical_flag_parsed_from_json() -> None:
    claim = Claim.from_mapping(
        {"id": 1, "text": "x", "source_ids": [1], "quote": "a b c", "critical": True}
    )
    assert claim.critical is True
