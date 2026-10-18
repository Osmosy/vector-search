"""Исследование с бюджетом: раунды, лимиты и честный отказ при исчерпании.

Оркестратор не сочиняет утверждения — он добывает источники. Оценку достаточности
даёт вызывающая сторона (модель или эвристика); бюджет раундов и чтений жёсткий,
поэтому «продолжай, пока не найдётся» невозможно.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, field

from .fetch import FetchResult, fetch
from .ledger import Ledger
from .search import Hit, SearchProvider

_STOPWORDS = {
    "и", "в", "во", "на", "с", "со", "по", "для", "что", "как", "это", "the", "a", "an",
    "of", "to", "in", "for", "is", "are", "and", "or", "with", "on", "by",
}

Fetcher = Callable[..., FetchResult]


@dataclass
class Budget:
    max_rounds: int = 4
    max_fetches: int = 16
    page_timeout: float = 60.0
    min_chars: int = 400
    per_round: int = 5


@dataclass
class Assessment:
    answered: bool
    gaps: list[str] = field(default_factory=list)
    next_queries: list[str] = field(default_factory=list)


@dataclass
class RoundLog:
    number: int
    queries: list[str]
    hits: int
    fetched: list[int] = field(default_factory=list)
    refused: list[str] = field(default_factory=list)
    duplicates: int = 0


@dataclass
class ResearchResult:
    rounds: list[RoundLog]
    sources: list[int]
    gaps: list[str]
    answered: bool
    exhausted: bool
    reason: str

    def to_dict(self) -> dict:
        return asdict(self)


def _tokens(text: str) -> set[str]:
    words = re.findall(r"[\w\-]{3,}", text.lower())
    return {w for w in words if w not in _STOPWORDS}


def _score(hit: Hit, queries: Sequence[str]) -> int:
    haystack = f"{hit.title} {hit.snippet}".lower()
    return sum(1 for q in queries for t in _tokens(q) if t in haystack)


def heuristic_assess(questions: Sequence[str], ledger: Ledger, sources: Sequence[int]) -> Assessment:
    """Оценка без модели: вопрос покрыт, если все его значимые слова есть в прочитанном тексте."""
    if not sources:
        return Assessment(answered=False, gaps=list(questions))
    texts: list[str] = []
    for sid in sources:
        try:
            texts.append(ledger.text(sid).lower())
        except Exception:  # noqa: BLE001 — непрочитанный источник просто не участвует
            continue
    joined = "\n".join(texts)
    gaps: list[str] = []
    for question in questions:
        missing = [t for t in _tokens(question) if t not in joined]
        if missing:
            gaps.append(f"{question} (нет: {', '.join(sorted(missing)[:5])})")
    return Assessment(answered=not gaps, gaps=gaps)


class ResearchSession:
    """Раунды «поиск → выбор → чтение → чего не хватает → новые запросы»."""

    def __init__(
        self,
        ledger: Ledger,
        provider: SearchProvider,
        *,
        budget: Budget | None = None,
        fetcher: Fetcher = fetch,
    ) -> None:
        self.ledger = ledger
        self.provider = provider
        self.budget = budget or Budget()
        self.fetcher = fetcher

    def run(
        self,
        questions: Sequence[str],
        assess: Callable[[Sequence[str], Ledger, Sequence[int]], Assessment] | None = None,
    ) -> ResearchResult:
        assess = assess or heuristic_assess
        queue: list[str] = [q for q in questions if q.strip()]
        seen: set[str] = set()
        sources: list[int] = []
        rounds: list[RoundLog] = []
        fetches_used = 0
        gaps: list[str] = list(questions)
        answered = False
        reason = ""

        for number in range(1, self.budget.max_rounds + 1):
            if not queue:
                reason = "новых запросов нет"
                break
            queries = queue[: self.budget.per_round]
            queue = queue[self.budget.per_round :]

            hits: list[Hit] = []
            for query in queries:
                try:
                    hits.extend(self.provider.search(query, limit=self.budget.per_round))
                except Exception as exc:  # noqa: BLE001 — поиск упал, раунд продолжается
                    reason = f"поиск не удался: {exc}"
            log = RoundLog(number=number, queries=queries, hits=len(hits))

            chosen: list[Hit] = []
            for hit in sorted(hits, key=lambda h: -_score(h, queries)):
                if hit.url in seen:
                    log.duplicates += 1
                    continue
                seen.add(hit.url)
                chosen.append(hit)
                if len(chosen) >= self.budget.per_round:
                    break

            for hit in chosen:
                if fetches_used >= self.budget.max_fetches:
                    reason = f"исчерпан бюджет чтений ({self.budget.max_fetches})"
                    break
                fetches_used += 1
                result = self.fetcher(
                    hit.url,
                    timeout=self.budget.page_timeout,
                    min_chars=self.budget.min_chars,
                )
                src = self.ledger.add(
                    url=result.url,
                    final_url=result.final_url,
                    status=result.status,
                    content_type=result.content_type,
                    text=result.text,
                    redirects=result.redirects,
                    error=result.error,
                    title=result.title or hit.title,
                )
                if src.ok:
                    sources.append(src.id)
                    log.fetched.append(src.id)
                else:
                    log.refused.append(f"{hit.url}: {src.error}")

            rounds.append(log)
            verdict = assess(questions, self.ledger, sources)
            gaps = verdict.gaps
            if verdict.answered:
                answered = True
                reason = "достаточно подтверждений"
                break
            if fetches_used >= self.budget.max_fetches:
                # Бюджет чтений исчерпан: причина уже записана, новые запросы бесполезны.
                break
            queue.extend(q for q in verdict.next_queries if q not in queue)
            if not queue:
                reason = "пробелы остались, новых запросов нет"
                break
        else:
            reason = f"исчерпан бюджет раундов ({self.budget.max_rounds})"

        return ResearchResult(
            rounds=rounds,
            sources=sources,
            gaps=gaps,
            answered=answered,
            exhausted=not answered,
            reason=reason,
        )


def summarize(result: ResearchResult) -> str:
    lines = [f"Раундов: {len(result.rounds)}, прочитано источников: {len(result.sources)}"]
    for log in result.rounds:
        lines.append(
            f"  раунд {log.number}: запросов {len(log.queries)}, выдача {log.hits}, "
            f"прочитано {len(log.fetched)}, отказов {len(log.refused)}, дублей {log.duplicates}"
        )
        for refused in log.refused:
            lines.append(f"    отказ: {refused}")
    if result.answered:
        lines.append(f"ИТОГ: достаточно подтверждений ({result.reason})")
    else:
        lines.append(f"ИТОГ: данных недостаточно — {result.reason}")
        for gap in result.gaps:
            lines.append(f"  пробел: {gap}")
    return "\n".join(lines)
