"""Утверждение — единица, которую можно проверить.

Модель не пишет прозу, которую потом нельзя проверить: она возвращает утверждения
с номерами источников, дословной цитатой и числами. Дальше всё проверяет код.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from .ledger import Ledger, LedgerError
from .numbers import numbers_in_text

MIN_QUOTE_WORDS = 3


class ClaimError(Exception):
    """Утверждение не соответствует схеме."""


def _normalize_ws(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _words(text: str) -> list[str]:
    """Слова цитаты: токены, в которых есть буква (числа и символы не считаются)."""
    return [w for w in _normalize_ws(text).split() if re.search(r"[^\W\d_]", w)]


def _match_key(text: str) -> str:
    """Нормализация для дословного сравнения: пробелы, кавычки, тире."""
    t = _normalize_ws(text).lower()
    t = t.replace("«", '"').replace("»", '"').replace("“", '"').replace("”", '"')
    t = t.replace("–", "-").replace("—", "-")
    return t


@dataclass
class Claim:
    """Одно утверждение с доказательствами."""

    id: int
    text: str
    source_ids: list[int]
    quote: str = ""
    numbers: list[str] = field(default_factory=list)

    @classmethod
    def from_mapping(cls, obj: Mapping[str, Any], *, index: int | None = None) -> Claim:
        if not isinstance(obj, Mapping):
            raise ClaimError("утверждение должно быть объектом")
        text = str(obj.get("text") or "").strip()
        if not text:
            raise ClaimError("у утверждения пустой text")
        raw_ids = obj.get("source_ids", obj.get("sources", []))
        if isinstance(raw_ids, int):
            raw_ids = [raw_ids]
        if not isinstance(raw_ids, (list, tuple)):
            raise ClaimError("source_ids должен быть списком номеров")
        try:
            source_ids = [int(i) for i in raw_ids]
        except (TypeError, ValueError) as exc:
            raise ClaimError(f"source_ids: не номер источника: {exc}") from exc
        numbers = obj.get("numbers") or []
        if not isinstance(numbers, (list, tuple)):
            raise ClaimError("numbers должен быть списком")
        return cls(
            id=int(obj.get("id", index if index is not None else 0)),
            text=text,
            source_ids=source_ids,
            quote=str(obj.get("quote") or "").strip(),
            numbers=[str(n) for n in numbers],
        )


def validate_claim(
    claim: Claim,
    ledger: Ledger,
    *,
    require_evidence: bool = True,
) -> list[str]:
    """Ошибки, из-за которых утверждение нельзя считать подтверждённым."""
    errors: list[str] = []

    if not claim.source_ids:
        errors.append("нет ни одного источника")
        return errors

    texts: dict[int, str] = {}
    for sid in claim.source_ids:
        src = ledger.get(sid)
        if src is None:
            errors.append(f"источник [{sid}] отсутствует в журнале")
            continue
        if not src.ok:
            errors.append(f"источник [{sid}] не прочитан: {src.error or 'status ' + str(src.status)}")
            continue
        try:
            texts[sid] = ledger.text(sid)
        except LedgerError as exc:
            errors.append(f"источник [{sid}]: {exc}")

    if require_evidence:
        if not claim.quote:
            errors.append("нет дословной цитаты")
        elif len(_words(claim.quote)) < MIN_QUOTE_WORDS:
            # Считаются только слова с буквами: «1 999 ₽» — не цитата.
            errors.append(f"цитата короче {MIN_QUOTE_WORDS} слов")
        else:
            key = _match_key(claim.quote)
            if texts and not any(key in _match_key(t) for t in texts.values()):
                errors.append("цитата не найдена дословно ни в одном из указанных источников")

    if claim.numbers:
        if not texts:
            errors.append("числа не с чем сверять: тексты источников недоступны")
        else:
            missing: list[str] = []
            for text in texts.values():
                missing = numbers_in_text(claim.numbers, text)
                if not missing:
                    break
            if missing:
                errors.append(
                    "чисел нет в тексте источника: " + ", ".join(missing)
                )

    return errors


def claims_from_json(payload: Any) -> list[Claim]:
    """Разбор файла: список утверждений или объект с полем ``claims``."""
    if isinstance(payload, Mapping):
        raw = payload.get("claims")
        if raw is None:
            raise ClaimError("в объекте нет поля claims")
    else:
        raw = payload
    if not isinstance(raw, list):
        raise ClaimError("claims должен быть списком")
    return [Claim.from_mapping(item, index=i + 1) for i, item in enumerate(raw)]
