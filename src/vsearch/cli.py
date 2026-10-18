"""Командная строка: fetch, verify, numbers."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .claims import ClaimError, claims_from_json
from .fetch import fetch
from .ledger import Ledger
from .numbers import extract_numbers
from .verify import receipt, summary, verify


def _cmd_fetch(args: argparse.Namespace) -> int:
    ledger = Ledger(args.ledger)
    result = fetch(
        args.url,
        timeout=args.timeout,
        min_chars=args.min_chars,
        max_bytes=args.max_bytes,
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
    )
    if src.ok:
        print(
            f"[{src.id}] {src.status} {src.chars} симв. {src.sha256[:12]} "
            f"{src.content_type or '—'} {src.final_url}"
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
    p_fetch.set_defaults(func=_cmd_fetch)

    p_verify = sub.add_parser("verify", help="проверить утверждения против журнала")
    p_verify.add_argument("claims")
    p_verify.add_argument("--ledger", default="data/ledger.jsonl")
    p_verify.add_argument("--min-coverage", type=float, default=1.0)
    p_verify.add_argument("--no-evidence", action="store_true", help="не требовать дословную цитату")
    p_verify.add_argument("--receipt", help="куда записать квитанцию (markdown)")
    p_verify.set_defaults(func=_cmd_verify)

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
