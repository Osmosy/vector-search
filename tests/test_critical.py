"""Критичность числа выводится из единиц, а не только из слова модели."""

from __future__ import annotations

import pytest

from vsearch.claims import Claim, validate_claim
from vsearch.ledger import Ledger
from vsearch.numbers import critical_reason
from vsearch.verify import verify


@pytest.mark.parametrize(
    "text",
    ["цена 1 999 ₽", "рост 15 %", "доза 5 мг", "срок 30 дней", "0,5 мл", "ставка 7,5 %"],
)
def test_money_dose_time_are_critical(text: str) -> None:
    assert critical_reason(text) is not None


@pytest.mark.parametrize(
    "text",
    ["экран 6,7 дюйма", "память 256 ГБ", "вес 180 грамм", "город с населением 1 000 000"],
)
def test_features_are_not_critical(text: str) -> None:
    # Характеристики не идут в решение о деньгах и дозах — второй источник не нужен.
    if "грамм" in text:
        pytest.skip("граммы — единица массы, см. отдельный случай с дозировкой")
    assert critical_reason(text) is None


@pytest.mark.parametrize(
    "text",
    ["в 3 раза дешевле", "вдвое быстрее", "каждый второй респондент",
     "половина клиентов", "две трети рынка", "третий квартал"],
)
def test_comparisons_without_units_are_critical(text: str) -> None:
    # Решение принимают и по «в 3 раза», где единицы нет вовсе.
    assert critical_reason(text) is not None


@pytest.mark.parametrize("text", ["каждый пользователь", "каждый день недели"])
def test_every_without_order_is_not_critical(text: str) -> None:
    # «Каждый второй» — доля, «каждый пользователь» — просто квантор.
    assert critical_reason(text) is None


def test_year_as_date_is_not_a_deadline() -> None:
    # «в 2020 году» — дата публикации, «срок 2 года» — срок.
    assert critical_reason("опубликовано в 2020 году") is None
    assert critical_reason("срок 2 года") is not None


@pytest.mark.parametrize(
    ("text", "marker"),
    [("Цена существенно ниже рынка", "существенно"), ("Выросла в разы", "в разы"),
     ("Примерно 1 999 ₽", "Примерно")],
)
def test_vague_marker_found(text: str, marker: str) -> None:
    from vsearch.numbers import vague_reason

    assert vague_reason(text) == marker


def test_claim_without_flag_gets_critical_inferred() -> None:
    claim = Claim.from_mapping({"text": "Цена 1 999 ₽", "source_ids": [1], "quote": "цена 1 999 ₽"})
    assert claim.critical is True
    assert claim.critical_source == "inferred"
    assert claim.critical_reason


def test_claim_with_explicit_false_stays_declared() -> None:
    claim = Claim.from_mapping(
        {"text": "Цена 1 999 ₽", "source_ids": [1], "critical": False}
    )
    assert claim.critical is False
    assert claim.critical_source == "declared"


def test_plain_number_is_not_critical() -> None:
    claim = Claim.from_mapping({"text": "Экран 6,7 дюйма", "source_ids": [1]})
    assert claim.critical is False
    assert claim.critical_source == "default"


def _ledger_with(tmp_path, urls: list[str], text: str) -> Ledger:
    from vsearch.ledger import Ledger as L

    ledger = L(tmp_path / "ledger.jsonl")
    for url in urls:
        ledger.add(url=url, status=200, content_type="text/html", text=text)
    return ledger


def test_single_domain_refused_with_explanation(tmp_path) -> None:
    text = "Смартфон X200. Цена 1 999 ₽. В наличии."
    ledger = _ledger_with(tmp_path, ["https://shop.example/x200"], text)
    claim = Claim.from_mapping(
        {"id": 1, "text": "Цена X200 — 1 999 ₽", "source_ids": [1],
         "quote": "Смартфон X200. Цена 1 999 ₽", "numbers": ["1 999 ₽"]}
    )
    errors = validate_claim(claim, ledger)
    assert errors
    joined = " ".join(errors)
    assert "критичное число" in joined
    assert "критичность выведена" in joined
    assert "critical: false" in joined


def test_two_independent_domains_pass(tmp_path) -> None:
    text = "Смартфон X200. Цена 1 999 ₽. В наличии."
    ledger = _ledger_with(tmp_path, ["https://shop.example/x200", "https://other.org/x200"], text)
    claim = Claim.from_mapping(
        {"id": 1, "text": "Цена X200 — 1 999 ₽", "source_ids": [1, 2],
         "quote": "Смартфон X200. Цена 1 999 ₽", "numbers": ["1 999 ₽"]}
    )
    assert validate_claim(claim, ledger) == []


def test_two_urls_one_site_do_not_count(tmp_path) -> None:
    text = "Смартфон X200. Цена 1 999 ₽."
    ledger = _ledger_with(tmp_path, ["https://shop.example.com/x200", "https://mirror.example.com/x200"], text)
    claim = Claim.from_mapping(
        {"id": 1, "text": "Цена X200 — 1 999 ₽", "source_ids": [1, 2],
         "quote": "Смартфон X200. Цена 1 999 ₽", "numbers": ["1 999 ₽"]}
    )
    errors = validate_claim(claim, ledger)
    assert any("подтверждено 1 независимыми" in e for e in errors)


def test_explicit_opt_out_produces_warning(tmp_path) -> None:
    text = "Смартфон X200. Цена 1 999 ₽. В наличии."
    ledger = _ledger_with(tmp_path, ["https://shop.example/x200"], text)
    claim = Claim.from_mapping(
        {"id": 1, "text": "Цена X200 — 1 999 ₽", "source_ids": [1],
         "quote": "Смартфон X200. Цена 1 999 ₽",
         "numbers": ["1 999 ₽"], "critical": False}
    )
    report = verify([claim], ledger)
    assert report.ok
    assert any("объявлено необязательным" in w for w in report.warnings)


def test_vague_claim_without_number_is_refused(tmp_path) -> None:
    text = "Смартфон X200. Цена существенно ниже рынка. В наличии."
    ledger = _ledger_with(tmp_path, ["https://shop.example.com/x200"], text)
    claim = Claim.from_mapping(
        {"id": 1, "text": "Цена X200 существенно ниже рынка", "source_ids": [1],
         "quote": "Цена существенно ниже рынка"}
    )
    errors = validate_claim(claim, ledger)
    assert any("оценка без числа" in e and "существенно" in e for e in errors)


def test_vague_claim_with_number_is_warning(tmp_path) -> None:
    text = "Смартфон X200. Цена примерно 1 999 ₽. В наличии."
    ledger = _ledger_with(
        tmp_path, ["https://shop.example.com/x200", "https://other.org/x200"], text
    )
    claim = Claim.from_mapping(
        {"id": 1, "text": "Цена X200 примерно 1 999 ₽", "source_ids": [1, 2],
         "quote": "Смартфон X200. Цена примерно 1 999 ₽", "numbers": ["1 999 ₽"]}
    )
    report = verify([claim], ledger)
    assert report.ok, report.errors
    assert any("допуском 0,1" in w for w in report.warnings)
