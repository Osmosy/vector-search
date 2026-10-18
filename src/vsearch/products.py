"""Товарная сверка: цена, наличие и характеристики должны быть в тексте страницы.

Текст страницы — единственный источник истины. Ответ собирается из предложений,
которые прошли сверку; всё остальное отбрасывается с причиной, а не «поправляется».
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field

from .ledger import Ledger, LedgerError
from .numbers import Number, extract_numbers

_CURRENCY_RE = re.compile(r"(₽|руб\.?|рублей|р\.|\$|€|usd|eur|rub)", re.IGNORECASE)
_AVAILABILITY_WORDS = (
    "в наличии",
    "нет в наличии",
    "под заказ",
    "ожидается",
    "закончился",
    "распродано",
    "in stock",
    "out of stock",
    "pre-order",
)
_SPLIT_RE = re.compile(r"\s*[—–|;:]\s*|\s{3,}")


@dataclass
class Offer:
    source_id: int
    name: str
    price: Number | None
    currency: str = ""
    availability: str = ""
    features: dict[str, str] = field(default_factory=dict)
    line: str = ""

    @property
    def price_text(self) -> str:
        return self.price.raw if self.price else ""


def _detect_currency(text: str) -> str:
    match = _CURRENCY_RE.search(text)
    if not match:
        return ""
    raw = match.group(1).lower()
    if raw in {"₽", "руб", "руб.", "рублей", "р.", "rub"}:
        return "RUB"
    if raw in {"$", "usd"}:
        return "USD"
    if raw in {"€", "eur"}:
        return "EUR"
    return raw.upper()


def _money_in(text: str) -> Number | None:
    for num in extract_numbers(text):
        if _CURRENCY_RE.search(text):
            return num
        if num.unit and num.unit in {"₽", "$", "€", "руб", "руб."}:
            return num
    return None


def parse_offers(text: str, source_id: int) -> list[Offer]:
    """Разбор строк вида «Модель — 1 999 ₽ — в наличии»."""
    offers: list[Offer] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        parts = [p for p in _SPLIT_RE.split(line) if p.strip()]
        if len(parts) < 2:
            continue
        price_part = next((p for p in parts if _money_in(p)), None)
        if price_part is None:
            continue
        name = next((p for p in parts if p is not price_part and not _has_availability(p)), "")
        if not name:
            continue
        availability = next((p for p in parts if _has_availability(p)), "")
        offers.append(
            Offer(
                source_id=source_id,
                name=name.strip(),
                price=_money_in(price_part),
                currency=_detect_currency(price_part),
                availability=availability.strip().lower(),
                line=line,
            )
        )
    return offers


def _has_availability(part: str) -> bool:
    low = part.lower()
    return any(word in low for word in _AVAILABILITY_WORDS)


def verify_offer(offer: Offer, ledger: Ledger) -> list[str]:
    """Что в предложении не подтверждается текстом источника."""
    errors: list[str] = []
    try:
        text = ledger.text(offer.source_id)
    except LedgerError as exc:
        return [f"нет текста источника: {exc}"]

    if not offer.line.strip():
        errors.append("нет строки-основания")
        return errors
    if " ".join(offer.line.split()).lower() not in " ".join(text.split()).lower():
        errors.append("строки предложения нет в тексте источника")

    if offer.name and offer.name.strip().lower() not in text.lower():
        errors.append(f"названия «{offer.name}» нет в тексте")

    if offer.price is not None:
        numbers = extract_numbers(text)
        same = [n for n in numbers if _same_value(n, offer.price)]
        if not same:
            errors.append(f"цены {offer.price_text} нет в тексте")
        elif offer.currency:
            window = text
            if offer.currency == "RUB" and not re.search(r"₽|руб|р\.", window, re.IGNORECASE):
                errors.append("валюта RUB не подтверждена текстом")
            if offer.currency == "USD" and not re.search(r"\$|usd", window, re.IGNORECASE):
                errors.append("валюта USD не подтверждена текстом")
            if offer.currency == "EUR" and not re.search(r"€|eur", window, re.IGNORECASE):
                errors.append("валюта EUR не подтверждена текстом")

    if offer.availability:
        if not _has_availability(offer.availability):
            errors.append("наличие не распознано")
        elif offer.availability.lower() not in text.lower():
            errors.append(f"наличия «{offer.availability}» нет в тексте")
    return errors


def _same_value(a: Number, b: Number, rel_tol: float = 0.001) -> bool:
    if a.value == b.value:
        return True
    denom = max(abs(a.value), abs(b.value))
    if denom == 0:
        return True
    return abs(a.value - b.value) / denom <= rel_tol


def build_answer(offers: Iterable[Offer], ledger: Ledger) -> tuple[list[str], list[tuple[Offer, list[str]]]]:
    """Собрать ответ только из проверенных предложений.

    Возвращает строки ответа и отклонённые предложения с причинами: молчаливое
    отбрасывание скрыло бы, что данные были, но не подтвердились.
    """
    accepted: list[str] = []
    rejected: list[tuple[Offer, list[str]]] = []
    for offer in offers:
        errors = verify_offer(offer, ledger)
        if errors:
            rejected.append((offer, errors))
            continue
        price = f"{offer.price.value}" if offer.price else "—"
        currency = f" {offer.currency}" if offer.currency else ""
        availability = f" — {offer.availability}" if offer.availability else ""
        accepted.append(f"{offer.name}: {price}{currency}{availability}")
    return accepted, rejected
