"""Командная строка: fetch, verify, numbers."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .browser import BskRenderer
from .claims import ClaimError, claims_from_json
from .dossier import SufficiencyError, check_dossier, summarize_dossier
from .extract import html_to_text
from .fetch import fetch
from .ledger import Ledger
from .numbers import extract_numbers
from .products import build_answer, parse_offers
from .research import Budget, ResearchSession, summarize
from .search import DuckDuckGoSearch, StaticSearch, hits_from_json
from .verify import receipt, summary, verify


def _cmd_fetch(args: argparse.Namespace) -> int:
    ledger = Ledger(args.ledger)
    renderer = BskRenderer() if args.browser else None
    result = fetch(
        args.url,
        timeout=args.timeout,
        min_chars=args.min_chars,
        max_bytes=args.max_bytes,
        allow_browser=args.browser,
        renderer=renderer,
    )
    src = ledger.add(
        url=result.url,
        final_url=result.final_url,
        status=result.status,
        content_type=result.content_type,
        text=result.text,
        redirects=result.redirects,
        error=result.error,
        title=result.title,
        provider=result.provider,
    )
    if src.ok:
        print(
            f"[{src.id}] {src.status} {src.chars} симв. {src.sha256[:12]} "
            f"{src.content_type or '—'} {src.provider} {src.final_url}"
        )
        return 0
    print(f"[{src.id}] ОТКАЗ: {src.error}", file=sys.stderr)
    return 1


def _cmd_verify(args: argparse.Namespace) -> int:
    ledger = Ledger(args.ledger)
    try:
        payload = json.loads(Path(args.claims).read_text(encoding="utf-8"))
        claims = claims_from_json(payload)
    except (OSError, json.JSONDecodeError, ClaimError) as exc:
        print(f"ОТКАЗ: утверждения не разобраны: {exc}", file=sys.stderr)
        return 1

    report = verify(
        claims,
        ledger,
        min_coverage=args.min_coverage,
        require_evidence=not args.no_evidence,
    )
    print(summary(report))
    for err in report.errors:
        print(f"  ошибка: {err}", file=sys.stderr)
    for warn in report.warnings:
        print(f"  предупреждение: {warn}")
    if args.receipt:
        Path(args.receipt).write_text(receipt(claims, ledger) + "\n", encoding="utf-8")
        print(f"квитанция: {args.receipt}")
    else:
        print()
        print(receipt(claims, ledger))
    return 0 if report.ok else 1


def _cmd_check(args: argparse.Namespace) -> int:
    ledger = Ledger(args.ledger)
    try:
        payload = json.loads(Path(args.dossier).read_text(encoding="utf-8"))
        dossier = check_dossier(
            payload,
            ledger,
            min_coverage=args.min_coverage,
            require_evidence=not args.no_evidence,
        )
    except (OSError, json.JSONDecodeError, SufficiencyError) as exc:
        print(f"ОТКАЗ: досье не разобрано: {exc}", file=sys.stderr)
        return 1
    print(summarize_dossier(dossier))
    if args.receipt:
        Path(args.receipt).write_text(receipt(dossier.claims, ledger) + "\n", encoding="utf-8")
        print(f"квитанция: {args.receipt}")
    return 0 if dossier.ok else 1


def _cmd_research(args: argparse.Namespace) -> int:
    ledger = Ledger(args.ledger)
    if args.hits:
        provider = StaticSearch(hits_from_json(json.loads(Path(args.hits).read_text(encoding="utf-8"))))
    else:
        provider = DuckDuckGoSearch()
    budget = Budget(
        max_rounds=args.rounds,
        max_fetches=args.fetches,
        per_round=args.per_round,
        min_chars=args.min_chars,
        page_timeout=args.timeout,
    )
    fetcher = fetch
    if args.browser:
        from functools import partial

        fetcher = partial(fetch, allow_browser=True, renderer=BskRenderer())
    session = ResearchSession(ledger, provider, budget=budget, fetcher=fetcher)
    result = session.run(args.questions)
    print(summarize(result))
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"журнал исследования: {out}")
    return 0 if result.answered else 1


def _cmd_products(args: argparse.Namespace) -> int:
    if args.file:
        text = Path(args.file).read_text(encoding="utf-8")
        if args.file.lower().endswith((".html", ".htm")):
            text = html_to_text(text)
        ledger: Ledger = _SelfLedger(text)
        source_id = 1
    elif args.source is not None:
        ledger = Ledger(args.ledger)
        try:
            text = ledger.text(args.source)
        except Exception as exc:  # noqa: BLE001 — причина отказа важнее типа
            print(f"ОТКАЗ: {exc}", file=sys.stderr)
            return 1
        source_id = args.source
    else:
        print("нужен --source ID или --file путь", file=sys.stderr)
        return 1

    offers = parse_offers(text, source_id)
    accepted, rejected = build_answer(offers, ledger)
    for line in accepted:
        print(f"ОК: {line}")
    for offer, errors in rejected:
        print(f"ОТКЛОНЕНО: {offer.name} — {'; '.join(errors)}", file=sys.stderr)
    if not offers:
        print("ОТКАЗ: в тексте не найдено ни одного предложения с ценой", file=sys.stderr)
        return 1
    if args.strict and rejected:
        return 1
    return 0 if accepted else 1


class _SelfLedger(Ledger):
    """Журнал из одного текста без файла: только для --file."""

    def __init__(self, text: str) -> None:  # noqa: D107 — простой контейнер
        import tempfile

        super().__init__(Path(tempfile.mkdtemp()) / "ledger.jsonl")
        self.add(url="file://local", status=200, content_type="text/plain", text=text)


def _cmd_numbers(args: argparse.Namespace) -> int:
    text = Path(args.file).read_text(encoding="utf-8") if args.file else sys.stdin.read()
    for num in extract_numbers(text):
        print(f"{num.raw!r:>18} → {num.value}{(' ' + num.unit) if num.unit else ''}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="vsearch", description="Проверяемый поиск: утверждение → источник → цитата")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_fetch = sub.add_parser("fetch", help="прочитать страницу в журнал источников")
    p_fetch.add_argument("url")
    p_fetch.add_argument("--ledger", default="data/ledger.jsonl")
    p_fetch.add_argument("--timeout", type=float, default=60.0)
    p_fetch.add_argument("--min-chars", type=int, default=400)
    p_fetch.add_argument("--max-bytes", type=int, default=5 * 1024 * 1024)
    p_fetch.add_argument("--browser", action="store_true", help="рендерить JS-страницы через bsk")
    p_fetch.set_defaults(func=_cmd_fetch)

    p_verify = sub.add_parser("verify", help="проверить утверждения против журнала")
    p_verify.add_argument("claims")
    p_verify.add_argument("--ledger", default="data/ledger.jsonl")
    p_verify.add_argument("--min-coverage", type=float, default=1.0)
    p_verify.add_argument("--no-evidence", action="store_true", help="не требовать дословную цитату")
    p_verify.add_argument("--receipt", help="куда записать квитанцию (markdown)")
    p_verify.set_defaults(func=_cmd_verify)

    p_check = sub.add_parser("check", help="проверить досье: утверждения, достаточность, покрытие вопросов")
    p_check.add_argument("dossier")
    p_check.add_argument("--ledger", default="data/ledger.jsonl")
    p_check.add_argument("--min-coverage", type=float, default=1.0)
    p_check.add_argument("--no-evidence", action="store_true")
    p_check.add_argument("--receipt")
    p_check.set_defaults(func=_cmd_check)

    p_research = sub.add_parser("research", help="раунды поиска и чтения с бюджетом")
    p_research.add_argument("questions", nargs="+")
    p_research.add_argument("--ledger", default="data/ledger.jsonl")
    p_research.add_argument("--hits", help="файл выдачи для офлайна: {запрос: [{title,url}]}")
    p_research.add_argument("--rounds", type=int, default=4)
    p_research.add_argument("--fetches", type=int, default=16)
    p_research.add_argument("--per-round", type=int, default=5)
    p_research.add_argument("--min-chars", type=int, default=400)
    p_research.add_argument("--timeout", type=float, default=60.0)
    p_research.add_argument("--out", default="data/research.json")
    p_research.add_argument("--browser", action="store_true", help="рендерить JS-страницы через bsk")
    p_research.set_defaults(func=_cmd_research)

    p_products = sub.add_parser("products", help="сверить товарные предложения с текстом источника")
    p_products.add_argument("--ledger", default="data/ledger.jsonl")
    p_products.add_argument("--source", type=int, help="номер источника в журнале")
    p_products.add_argument("--file", help="текст страницы из файла")
    p_products.add_argument("--strict", action="store_true", help="ненулевой код при любом отклонении")
    p_products.set_defaults(func=_cmd_products)

    p_numbers = sub.add_parser("numbers", help="показать числа, как их видит сверка")
    p_numbers.add_argument("file", nargs="?")
    p_numbers.set_defaults(func=_cmd_numbers)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
