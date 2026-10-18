"""Гейт перед выдачей: либо все утверждения раскрыты, либо отказ.

Гейт отвечает на один вопрос — можно ли на этом основании принимать решение.
Он не оценивает красоту текста и не спорит с формулировками: он проверяет, что
каждое утверждение имеет источник, дословную цитату и числа, найденные в тексте.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .claims import Claim, validate_claim
from .ledger import Ledger, Source
from .numbers import critical_reason


@dataclass
class Report:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    per_claim: dict[int, list[str]] = field(default_factory=dict)
    coverage: float = 0.0

    @property
    def ok(self) -> bool:
        return not self.errors


def verify(
    claims: list[Claim],
    ledger: Ledger,
    *,
    min_coverage: float = 1.0,
    require_evidence: bool = True,
) -> Report:
    report = Report()
    if not claims:
        report.errors.append("нет ни одного утверждения — проверять нечего")
        return report

    proven = 0
    for claim in claims:
        errs = validate_claim(claim, ledger, require_evidence=require_evidence)
        report.per_claim[claim.id] = errs
        if claim.critical_source == "declared" and not claim.critical:
            reason = critical_reason(claim.text, *claim.numbers)
            if reason:
                report.warnings.append(
                    f"утверждение [{claim.id}] «{_short(claim.text)}»: число «{reason}» "
                    "объявлено необязательным (critical: false) — проверьте, что это осознанно"
                )
        if errs:
            for err in errs:
                report.errors.append(f"утверждение [{claim.id}] «{_short(claim.text)}»: {err}")
        else:
            proven += 1

    report.coverage = proven / len(claims)
    if report.coverage < min_coverage:
        report.errors.append(
            f"покрытие доказательствами {report.coverage:.0%} ниже требуемого {min_coverage:.0%} "
            f"({proven} из {len(claims)})"
        )

    unused = [s.id for s in ledger if s.ok and not any(s.id in c.source_ids for c in claims)]
    if unused:
        report.warnings.append(
            "в журнале есть прочитанные источники, не использованные ни в одном утверждении: "
            + ", ".join(f"[{i}]" for i in unused)
        )
    return report


def _short(text: str, limit: int = 60) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _md_cell(text: str, limit: int = 80) -> str:
    text = " ".join(str(text).split()).replace("|", "\\|")
    return text if len(text) <= limit else text[: limit - 1] + "…"


def receipt(claims: list[Claim], ledger: Ledger) -> str:
    """Квитанция: по каждому утверждению — источник, цитата, хеш и время."""
    lines = [
        "| Утверждение | Источник | Цитата | sha256 | Получено |",
        "|---|---|---|---|---|",
    ]
    for claim in claims:
        sources: list[Source] = [s for s in (ledger.get(i) for i in claim.source_ids) if s is not None]
        if not sources:
            lines.append(f"| {_md_cell(claim.text)} | — | — | — | — |")
            continue
        for src in sources:
            lines.append(
                "| {claim} | [{sid}] {url} | {quote} | {sha} | {at} |".format(
                    claim=_md_cell(claim.text),
                    sid=src.id,
                    url=_md_cell(src.final_url, 60),
                    quote=_md_cell(claim.quote or "—", 60),
                    sha=(src.sha256 or "—")[:12],
                    at=src.fetched_at,
                )
            )
    return "\n".join(lines)


def summary(report: Report) -> str:
    status = "OK: все утверждения раскрыты до источников" if report.ok else "ОТКАЗ: есть непроверенные утверждения"
    return f"{status} (покрытие {report.coverage:.0%})"
