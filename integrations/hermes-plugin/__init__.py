"""vector-search для Hermes: строгое чтение и гейт утверждений как инструменты агента.

Плагин не тянет браузер и не ходит в сеть на импорте: `vsearch` подключается из
исходников репозитория (или `VSEARCH_SRC`), журнал по умолчанию лежит в
`~/.hermes/vector-search/ledger.jsonl`.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

__version__ = "0.4.0"

_SRC = Path(os.getenv("VSEARCH_SRC", "~/projects/vector-search/src")).expanduser()
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

LEDGER_ENV = "VSEARCH_LEDGER"
DEFAULT_LEDGER = "~/.hermes/vector-search/ledger.jsonl"


def _ledger_path() -> Path:
    return Path(os.getenv(LEDGER_ENV, DEFAULT_LEDGER)).expanduser()


def _ledger():
    from vsearch.ledger import Ledger

    path = _ledger_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    return Ledger(path)


def _ok(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False)


def _fail(reason: str) -> str:
    return json.dumps({"ok": False, "error": reason}, ensure_ascii=False)


def vsearch_fetch(args: dict, **_: Any) -> str:
    """Прочитать страницу строгим загрузчиком и записать её в журнал."""
    url = str(args.get("url") or "").strip()
    if not url:
        return _fail("нужен url")
    try:
        from vsearch.browser import BskRenderer
        from vsearch.fetch import fetch
    except ImportError as exc:
        return _fail(f"vsearch не установлен: {exc} (VSEARCH_SRC={_SRC})")

    allow_browser = bool(args.get("allow_browser", False))
    try:
        result = fetch(
            url,
            timeout=float(args.get("timeout", 60.0)),
            min_chars=int(args.get("min_chars", 400)),
            allow_browser=allow_browser,
            renderer=BskRenderer() if allow_browser else None,
        )
    except Exception as exc:  # noqa: BLE001 — инструмент обязан вернуть текст, а не упасть
        return _fail(f"чтение не удалось: {exc}")

    src = _ledger().add(
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
    payload = {
        "ok": src.ok,
        "id": src.id,
        "status": src.status,
        "chars": src.chars,
        "sha256": src.sha256,
        "provider": src.provider,
        "title": src.title,
        "final_url": src.final_url,
        "fetched_at": src.fetched_at,
        "text": result.text[: int(args.get("max_chars", 6000))],
        "ledger": str(_ledger_path()),
    }
    if src.error:
        # Ключ "error" намеренно только здесь: Hermes помечает такой ответ сбоем.
        payload["error"] = src.error
    return _ok(payload)


def vsearch_check(args: dict, **_: Any) -> str:
    """Проверить досье: утверждения раскрыты, оценка достаточности не врёт."""
    payload = args.get("dossier")
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError as exc:
            return _fail(f"досье не JSON: {exc}")
    if not isinstance(payload, dict):
        return _fail("нужен объект досье с claims и sufficiency")
    try:
        from vsearch.dossier import SufficiencyError, check_dossier, summarize_dossier
        from vsearch.verify import receipt
    except ImportError as exc:
        return _fail(f"vsearch не установлен: {exc}")

    ledger = _ledger()
    try:
        dossier = check_dossier(payload, ledger, min_coverage=float(args.get("min_coverage", 1.0)))
    except SufficiencyError as exc:
        return _fail(f"досье не разобрано: {exc}")
    return _ok(
        {
            "ok": dossier.ok,
            "coverage": dossier.report.coverage,
            "problems": dossier.report.errors,
            "warnings": dossier.report.warnings,
            "uncovered": dossier.uncovered,
            "gaps": dossier.sufficiency.gaps,
            "summary": summarize_dossier(dossier),
            "receipt": receipt(dossier.claims, ledger),
        }
    )


def vsearch_status(args: dict, **_: Any) -> str:
    """Состояние журнала: сколько источников прочитано и сколько отказов."""
    try:
        from vsearch.ledger import LedgerError
    except ImportError as exc:
        return _fail(f"vsearch не установлен: {exc}")
    try:
        ledger = _ledger()
    except LedgerError as exc:
        return _fail(f"журнал повреждён: {exc}")
    sources = list(ledger)
    return _ok(
        {
            "ok": True,
            "ledger": str(_ledger_path()),
            "total": len(sources),
            "read": sum(1 for s in sources if s.ok),
            "refused": sum(1 for s in sources if not s.ok),
            "last": [
                {"id": s.id, "status": s.status, "chars": s.chars, "url": s.final_url}
                for s in sources[-5:]
            ],
        }
    )


_FETCH_SCHEMA = {
    "name": "vsearch_fetch",
    "description": (
        "Прочитать страницу строгим загрузчиком: только http/https, проверка каждого "
        "редиректа, тип и размер, порог содержательного текста, отказ на 404/капчу. "
        "Результат пишется в журнал с sha256 и временем; вернуть id источника можно "
        "использовать как source_id в досье для vsearch_check."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "Адрес страницы"},
            "allow_browser": {
                "type": "boolean",
                "description": "Рендерить JS-страницы через bsk (медленнее)",
            },
            "timeout": {"type": "number", "description": "Таймаут в секундах (по умолчанию 60)"},
            "min_chars": {
                "type": "integer",
                "description": "Минимум содержательного текста (по умолчанию 400)",
            },
            "max_chars": {
                "type": "integer",
                "description": "Сколько символов текста вернуть (по умолчанию 6000)",
            },
        },
        "required": ["url"],
    },
}

_CHECK_SCHEMA = {
    "name": "vsearch_check",
    "description": (
        "Проверить досье ответа: утверждения с source_ids, дословными цитатами и числами, "
        "оценка достаточности. Возвращает код-вердикт: ok=false, если утверждение не "
        "раскрыто, число не из текста, цитата не найдена, есть противоречие или вопрос "
        "без утверждения. На решение идёт только досье с ok=true."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "dossier": {
                "type": "object",
                "description": "Объект {questions, claims[], sufficiency} или JSON-строка",
            },
            "min_coverage": {
                "type": "number",
                "description": "Требуемая доля подтверждённых утверждений (по умолчанию 1.0)",
            },
        },
        "required": ["dossier"],
    },
}

_STATUS_SCHEMA = {
    "name": "vsearch_status",
    "description": "Показать состояние журнала источников: сколько прочитано, сколько отказов, последние записи.",
    "parameters": {"type": "object", "properties": {}},
}


def register(ctx) -> None:
    ctx.register_tool(
        name="vsearch_fetch",
        toolset="vector_search",
        schema=_FETCH_SCHEMA,
        handler=vsearch_fetch,
        description="Строгое чтение страницы в журнал источников",
        emoji="\U0001f50e",
    )
    ctx.register_tool(
        name="vsearch_check",
        toolset="vector_search",
        schema=_CHECK_SCHEMA,
        handler=vsearch_check,
        description="Гейт досье: утверждения, цитаты, числа, достаточность",
        emoji="\u2705",
    )
    ctx.register_tool(
        name="vsearch_status",
        toolset="vector_search",
        schema=_STATUS_SCHEMA,
        handler=vsearch_status,
        description="Состояние журнала источников",
        emoji="\U0001f4d2",
    )
