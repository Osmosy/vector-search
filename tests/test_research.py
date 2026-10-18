"""Оркестратор исследования: бюджет, отказы, пробелы."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import pytest

from vsearch.fetch import FetchResult
from vsearch.ledger import Ledger
from vsearch.research import Assessment, Budget, ResearchSession, heuristic_assess, summarize
from vsearch.search import Hit, StaticSearch

GOOD_TEXT = (
    "Средний результат 42,7 из 105 при семи прогонах. Стоимость прогона $1.84. "
    "Модель отвечала в DeepSeek Harness. " + ("Подробности на странице. " * 20)
)


def fake_fetcher(url: str, **kwargs) -> FetchResult:
    if "dead" in url:
        return FetchResult(url=url, final_url=url, status=404, error="HTTP 404")
    return FetchResult(url=url, final_url=url, status=200, content_type="text/html", text=GOOD_TEXT)


@pytest.fixture
def ledger(tmp_path: Path) -> Ledger:
    return Ledger(tmp_path / "ledger.jsonl")


def test_single_round_when_question_covered(ledger: Ledger) -> None:
    provider = StaticSearch(default=[Hit("Результат", "https://a.example/x", "42,7 из 105")])
    session = ResearchSession(ledger, provider, fetcher=fake_fetcher)
    result = session.run(["результат 42,7 прогонах"])
    assert result.answered
    assert len(result.rounds) == 1
    assert len(result.sources) == 1
    assert not result.exhausted


def test_no_sources_means_gap(ledger: Ledger) -> None:
    provider = StaticSearch(default=[])
    result = ResearchSession(ledger, provider, fetcher=fake_fetcher).run(["чего-то очень специфичного"])
    assert not result.answered
    assert result.exhausted
    assert result.gaps


def test_round_budget_is_hard(ledger: Ledger) -> None:
    class Endless:
        name = "endless"

        def __init__(self) -> None:
            self.n = 0

        def search(self, query: str, limit: int = 8) -> list[Hit]:
            self.n += 1
            return [Hit("t", f"https://a.example/{self.n}", "s")]

    def never_satisfied(questions: Sequence[str], led: Ledger, sources: Sequence[int]) -> Assessment:
        return Assessment(answered=False, gaps=["всё ещё нет"], next_queries=["ещё запрос"])

    session = ResearchSession(ledger, Endless(), budget=Budget(max_rounds=3), fetcher=fake_fetcher)
    result = session.run(["вопрос"], assess=never_satisfied)
    assert not result.answered
    assert len(result.rounds) == 3
    assert "бюджет раундов" in result.reason


def test_fetch_budget_is_hard(ledger: Ledger) -> None:
    hits = [Hit("t", f"https://a.example/{i}", "s") for i in range(10)]
    session = ResearchSession(
        ledger,
        StaticSearch(default=hits),
        budget=Budget(max_rounds=1, max_fetches=2, per_round=10),
        fetcher=fake_fetcher,
    )
    result = session.run(["вопрос"])
    assert len(result.rounds[0].fetched) == 2
    assert "бюджет чтений" in result.reason
    assert result.exhausted


def test_refused_page_is_recorded_not_counted(ledger: Ledger) -> None:
    provider = StaticSearch(default=[Hit("t", "https://dead.example/x", "s")])
    result = ResearchSession(ledger, provider, fetcher=fake_fetcher).run(["вопрос"])
    assert result.sources == []
    assert "HTTP 404" in result.rounds[0].refused[0]
    # отказ тоже в журнале: доказательство отсутствия материала
    assert len(ledger) == 1
    src = ledger.get(1)
    assert src is not None and not src.ok


def test_duplicate_urls_are_skipped(ledger: Ledger) -> None:
    provider = StaticSearch(default=[
        Hit("t1", "https://a.example/x", "s"),
        Hit("t2", "https://a.example/x", "s"),
    ])
    result = ResearchSession(ledger, provider, budget=Budget(max_rounds=1), fetcher=fake_fetcher).run(["вопрос"])
    assert result.rounds[0].duplicates == 1
    assert len(result.sources) == 1


def test_summary_names_the_exhaustion(ledger: Ledger) -> None:
    result = ResearchSession(ledger, StaticSearch(default=[]), fetcher=fake_fetcher).run(["вопрос"])
    text = summarize(result)
    assert "данных недостаточно" in text
    assert "пробел:" in text


def test_heuristic_assess_uses_source_text(ledger: Ledger) -> None:
    src = ledger.add(url="https://a.example/x", status=200, content_type="text/html", text=GOOD_TEXT)
    verdict = heuristic_assess(["стоимость прогона"], ledger, [src.id])
    assert verdict.answered
    verdict = heuristic_assess(["совершенно другой вопрос"], ledger, [src.id])
    assert not verdict.answered
