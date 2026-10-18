"""Нормализация чисел: то, что ломается при сверке «глазами»."""

from __future__ import annotations

from decimal import Decimal

import pytest

from vsearch.numbers import extract_numbers, normalize_number, numbers_in_text, parse_body


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("1 999", "1999"),
        ("1\u00a0999", "1999"),
        ("1999", "1999"),
        ("1,5", "1.5"),
        ("1.5", "1.5"),
        ("1.234,56", "1234.56"),
        ("1,234.56", "1234.56"),
        ("47.4", "47.4"),
        ("0,0012", "0.0012"),
    ],
)
def test_parse_body(raw: str, expected: str) -> None:
    assert parse_body(raw) == Decimal(expected)


def test_thousands_with_comma_are_not_decimal() -> None:
    # 1,999 — это тысяча девятьсот девяносто девять, а не 1.999
    assert parse_body("1,999") == Decimal("1999")


def test_units_and_scale() -> None:
    nums = extract_numbers("выручка 2,5 млрд ₽ и скидка 12 %")
    assert nums[0].value == Decimal("2500000000")
    assert any(n.unit.strip() == "%" for n in nums)


@pytest.mark.parametrize(
    "claim,text",
    [
        ("1999", "цена 1 999 руб"),
        ("1 999", "цена 1999"),
        ("1,5", "вес 1.5 кг"),
        ("47.4", "среднее 47,4 из 105"),
        ("$1.84", "стоимость $1.84"),
    ],
)
def test_numbers_found_across_formatting(claim: str, text: str) -> None:
    assert numbers_in_text([claim], text) == []


def test_wrong_number_is_reported() -> None:
    assert numbers_in_text(["1899"], "цена 1 999 руб") == ["1899"]


def test_approximate_claim_is_not_a_match() -> None:
    # «в 50 раз» против фактических 47.4 — это расхождение, а не подтверждение
    assert numbers_in_text(["50"], "дешевле в 47,4 раза") == ["50"]


def test_normalize_number_rejects_text() -> None:
    assert normalize_number("нет чисел") is None
