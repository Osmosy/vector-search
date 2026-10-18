"""Товарная сверка: цена, наличие, сборка ответа из проверенных строк."""

from __future__ import annotations

from pathlib import Path

import pytest

from vsearch.ledger import Ledger
from vsearch.numbers import Number
from vsearch.products import Offer, build_answer, parse_offers, verify_offer

TEXT = """Каталог магазина
Модель X200 — 1 999 ₽ — в наличии
Модель X300 — 2 499 ₽ — нет в наличии
Модель X400 — $1.84 — in stock
"""


@pytest.fixture
def ledger(tmp_path: Path) -> Ledger:
    led = Ledger(tmp_path / "ledger.jsonl")
    led.add(url="https://shop.example/catalog", status=200, content_type="text/html", text=TEXT)
    return led


def test_parse_three_offers() -> None:
    offers = parse_offers(TEXT, 1)
    assert [o.name for o in offers] == ["Модель X200", "Модель X300", "Модель X400"]
    assert offers[0].price is not None and str(offers[0].price.value) == "1999"
    assert offers[0].currency == "RUB"
    assert offers[1].availability == "нет в наличии"
    assert offers[2].currency == "USD"


def test_verified_offer_passes(ledger: Ledger) -> None:
    offer = parse_offers(TEXT, 1)[0]
    assert verify_offer(offer, ledger) == []


def test_substituted_price_is_rejected(ledger: Ledger) -> None:
    offer = parse_offers(TEXT, 1)[0]
    price = offer.price
    assert price is not None
    offer.price = Number(raw="1 899 ₽", value=price.value - 100, unit="₽")
    errors = verify_offer(offer, ledger)
    assert any("цены" in e and "нет в тексте" in e for e in errors)


def test_availability_must_be_in_line(ledger: Ledger) -> None:
    offer = parse_offers(TEXT, 1)[0]
    offer.availability = "под заказ"
    errors = verify_offer(offer, ledger)
    # «под заказ» в источнике нет — предложение не проходит
    assert any("нет в тексте" in e for e in errors)


def test_build_answer_splits_accepted_and_rejected(ledger: Ledger) -> None:
    offers = parse_offers(TEXT, 1)
    bad = Offer(source_id=1, name="Модель X500", price=offers[0].price, currency="RUB",
                availability="в наличии", line="Модель X500 — 1 999 ₽ — в наличии")
    accepted, rejected = build_answer([*offers, bad], ledger)
    assert len(accepted) == 3
    assert len(rejected) == 1
    assert rejected[0][0].name == "Модель X500"
    assert "нет в тексте" in " ".join(rejected[0][1])


def test_answer_never_invents_price(ledger: Ledger) -> None:
    offers = parse_offers(TEXT, 1)
    accepted, _ = build_answer(offers, ledger)
    assert all("1999" in line or "2499" in line or "1.84" in line for line in accepted)
