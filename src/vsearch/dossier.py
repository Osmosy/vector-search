"""Достаточность и досье: ответ модели как структура, а не как проза.

Модель возвращает не текст ответа, а досье: вопросы, утверждения с доказательствами
и оценку достаточности. Программа проверяет три вещи, которые модель проверять не
может: утверждения раскрыты до источников, оценка не противоречит сама себе, и на
каждый вопрос есть хотя бы одно утверждение.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from .claims import Claim, ClaimError, claims_from_json
from .ledger import Ledger
from .verify import Report, verify

_STOPWORDS = {
    "и", "в", "во", "на", "с", "со", "по", "для", "что", "как", "это", "the", "a", "an",
    "of", "to", "in", "for", "is", "are", "and", "or", "with", "on", "by", "ли", "же",
}


class SufficiencyError(Exception):
    """Оценка достаточности не соответствует схеме."""


@dataclass
class Sufficiency:
    answered: bool
    gaps: list[str] = field(default_factory=list)
    next_queries: list[str] = field(default_factory=list)


def parse_sufficiency(payload: Any) -> Sufficiency:
    if not isinstance(payload, Mapping):
        raise SufficiencyError("sufficiency должен быть объектом")
    if "answered" not in payload:
        raise SufficiencyError("в sufficiency нет поля answered")
    answered = payload["answered"]
    if not isinstance(answered, bool):
        raise SufficiencyError("answered должен быть true/false, а не строка или число")
    gaps = _string_list(payload.get("gaps", []), "gaps")
    next_queries = _string_list(
        payload.get("next_queries", payload.get("next_search_queries", [])),
        "next_queries",
    )
    return Sufficiency(answered=answered, gaps=gaps, next_queries=next_queries)


def _string_list(value: Any, name: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, (list, tuple)):
        raise SufficiencyError(f"{name} должен быть списком строк")
    out: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise SufficiencyError(f"{name}: элемент не строка: {item!r}")
        if item.strip():
            out.append(item.strip())
    return out


def _tokens(text: str) -> set[str]:
    words = re.findall(r"[\w\-]{3,}", text.lower())
    return {w for w in words if w not in _STOPWORDS}


@dataclass
class Dossier:
    questions: list[str]
    claims: list[Claim]
    sufficiency: Sufficiency
    report: Report
    uncovered: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.report.ok and not self.uncovered


def check_dossier(
    payload: Any,
    ledger: Ledger,
    *,
    min_coverage: float = 1.0,
    require_evidence: bool = True,
) -> Dossier:
    """Проверить досье целиком: утверждения, оценку и покрытие вопросов."""
    if not isinstance(payload, Mapping):
        raise SufficiencyError("досье должно быть объектом")
    questions = _string_list(payload.get("questions", []), "questions")
    sufficiency = parse_sufficiency(payload.get("sufficiency", {}))
    try:
        claims = claims_from_json(payload)
    except ClaimError as exc:
        raise SufficiencyError(f"утверждения не разобраны: {exc}") from exc

    report = verify(claims, ledger, min_coverage=min_coverage, require_evidence=require_evidence)

    if sufficiency.answered and sufficiency.gaps:
        report.errors.append(
            "противоречие: answered=true, но перечислены пробелы: " + "; ".join(sufficiency.gaps)
        )
    if sufficiency.answered and not claims:
        report.errors.append("противоречие: answered=true без единого утверждения")
    if not sufficiency.answered and not sufficiency.gaps:
        report.errors.append("противоречие: answered=false, но пробелы не названы")

    uncovered: list[str] = []
    for question in questions:
        tokens = _tokens(question)
        covered = any(tokens and tokens <= _tokens(claim.text) for claim in claims)
        if not covered:
            uncovered.append(question)

    return Dossier(
        questions=questions,
        claims=claims,
        sufficiency=sufficiency,
        report=report,
        uncovered=uncovered,
    )


def summarize_dossier(dossier: Dossier) -> str:
    lines: list[str] = []
    if dossier.ok:
        lines.append(f"OK: досье проверено, утверждений {len(dossier.claims)}, вопросов {len(dossier.questions)}")
    else:
        lines.append("ОТКАЗ: досье не прошло проверку")
        lines.append(f"  покрытие утверждений доказательствами: {dossier.report.coverage:.0%}")
        for err in dossier.report.errors:
            lines.append(f"  ошибка: {err}")
        for question in dossier.uncovered:
            lines.append(f"  вопрос без утверждения: {question}")
    if dossier.sufficiency.gaps:
        lines.append("  пробелы, названные моделью: " + "; ".join(dossier.sufficiency.gaps))
    return "\n".join(lines)


def questions_from_ledger(ledger: Ledger) -> Sequence[str]:
    """Заголовки прочитанных источников — черновой список вопросов для отчёта."""
    return [s.title for s in ledger if s.ok and s.title]
