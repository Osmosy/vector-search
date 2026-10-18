"""Нормализация и сверка чисел.

Русская и английская типографика смешивают разделители: ``1 999``, ``1,999``,
``1.999``, ``1.234,56``, ``1,234.56``. Для сверки утверждения с источником важно
не «похоже», а равенство значения: поэтому число разбирается в Decimal с единицей,
а сравнение идёт с допуском на округление.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

# Разряды могут отделяться пробелом (в том числе неразрывным), запятой или точкой.
_NUMBER_RE = re.compile(
    r"""
    (?P<sign>[+\-\u2212])?
    (?P<body>
        \d{1,3}(?:[ \u00a0\u202f]\d{3})+(?:[.,]\d+)?   # 1 999 или 1 999,5
      | \d{1,3}(?:[.,]\d{3})+(?:[.,]\d+)?               # 1.999 / 1,999 / 1.234,56
      | \d+(?:[.,]\d+)?                                 # 1999 / 1999,5
    )
    """,
    re.VERBOSE,
)

_UNIT_RE = re.compile(
    r"\s*(?P<unit>%|‰|₽|руб\.?|рублей|р\.|\$|€|тыс\.?|млн\.?|млрд\.?|шт\.?|мс|сек\.?|мин\.?|ч\.?|гб|мб|кб|тб|кг|г|мг|км|м)",
    re.IGNORECASE,
)

_UNIT_SCALE = {
    "тыс": Decimal(1_000),
    "млн": Decimal(1_000_000),
    "млрд": Decimal(1_000_000_000),
}


@dataclass(frozen=True)
class Number:
    raw: str
    value: Decimal
    unit: str = ""

    def key(self) -> str:
        unit = self.unit.rstrip(".")
        return f"{self.value.normalize()}|{unit.lower()}"


def _strip_spaces(s: str) -> str:
    return re.sub(r"[ \u00a0\u202f]", "", s)


def parse_body(body: str) -> Decimal | None:
    """«1 999,5» → 1999.5; «1.234,56» → 1234.56; «1,5» → 1.5."""
    b = _strip_spaces(body)
    if not b:
        return None
    has_dot, has_comma = "." in b, "," in b
    if has_dot and has_comma:
        # Последний разделитель — десятичный, предыдущий — разряды.
        last = max(b.rfind("."), b.rfind(","))
        integer = re.sub(r"[.,]", "", b[:last])
        fraction = b[last + 1 :]
        b = f"{integer}.{fraction}"
    elif has_comma or has_dot:
        sep = "," if has_comma else "."
        parts = b.split(sep)
        # Разряды: ровно 3 цифры в каждой группе после первой, групп больше одной.
        if len(parts) > 1 and all(len(p) == 3 for p in parts[1:]):
            b = "".join(parts)
        else:
            b = ".".join(parts)
    try:
        return Decimal(b)
    except InvalidOperation:
        return None


def extract_numbers(text: str) -> list[Number]:
    """Все числа текста с единицами измерения, если они примыкают."""
    out: list[Number] = []
    for m in _NUMBER_RE.finditer(text):
        value = parse_body(m.group("body"))
        if value is None:
            continue
        if m.group("sign") in {"-", "\u2212"}:
            value = -value
        unit = ""
        um = _UNIT_RE.match(text, m.end())
        if um:
            unit = um.group("unit")
            scale = _UNIT_SCALE.get(unit.rstrip(".").lower())
            if scale is not None:
                value *= scale
        out.append(Number(raw=m.group(0), value=value, unit=unit))
    return out


# Единицы, из-за которых число идёт в решение: деньги, доли, дозировки, сроки.
_CRITICAL_RE = re.compile(
    r"""(?P<num>\d[\d \u00a0\u202f.,]*)\s*
        (?P<unit>%|‰|₽|руб\w*|р\.|\$|€|usd|eur|руб/|мкг|мг|мл|кг|г(?![а-яё])|мс|сек\w*|мин\w*|ч\b|час\w*|дн\w*|сут\w*|нед\w*|мес\w*|год\w*|лет)""",
    re.VERBOSE | re.IGNORECASE,
)


# Сравнения без единиц: «в 3 раза», «вдвое», «каждый второй», «половина».
# Это тоже числа, на которых принимают решение, но записаны словами.
_MULTIPLIER_RE = re.compile(
    r"""(?:\bв\s+\d+(?:[.,]\d+)?\s*раз(?:а)?\b
        |\bвдвое\b|\bвтрое\b|\bвчетверо\b|\bвпятеро\b|\bвшестеро\b|\bвдесятеро\b
        |\bкажды[йй]\s+(?:\d+-?(?:й|го|му|м)?|втор\w*|трет\w*|четв[её]рт\w*|пят\w*|шест\w*|седьм\w*|восьм\w*|девят\w*|десят\w*)
        |\bполовин\w*|\bтрет\w*|\bчетверт\w*
        |\bдве\s+трети\b|\bтри\s+четверти\b)""",
    re.VERBOSE | re.IGNORECASE,
)


def critical_reason(*texts: str) -> str | None:
    """Почему число критично: первая критичная единица в тексте или числах.

    Возвращает фрагмент («1 999 ₽», «15 %», «5 мг»), чтобы сообщение об отказе
    объясняло, откуда взялось требование второго источника, — или None.
    """
    for text in texts:
        if not text:
            continue
        m = _CRITICAL_RE.search(str(text))
        if m:
            unit = m.group("unit")
            value = parse_body(m.group("num"))
            # Год — срок, если он короткий; «в 2020 году» — дата, а не срок.
            if unit.lower().startswith(("год", "лет")) and value is not None and abs(value) > 100:
                m = _CRITICAL_RE.search(str(text)[m.end():])
                if not m:
                    continue
                unit = m.group("unit")
            return f"{m.group('num').strip()} {unit}"
        m = _MULTIPLIER_RE.search(str(text))
        if m:
            return m.group(0).strip()
    return None


# Качественные оценки: «существенно», «в разы», «примерно». Сами по себе они
# не проверяемы — либо рядом стоит число, либо утверждение ничего не говорит.
_VAGUE_MARKERS = (
    "незначительн",
    "существенн",
    "значительн",
    "в разы",
    "многократн",
    "кардинальн",
    "почти",
    "примерно",
    "приблизительн",
    "около",
    "порядка",
    "немного",
    "слегка",
    "несколько",
)


def vague_reason(text: str) -> str | None:
    """Первая качественная оценка в тексте («существенно», «примерно») или None."""
    low = str(text).lower()
    for marker in _VAGUE_MARKERS:
        pos = low.find(marker)
        if pos < 0:
            continue
        # Маркер из нескольких слов («в разы») возвращается целиком.
        if " " in marker:
            return str(text)[pos : pos + len(marker)].strip(" .,;:()")
        # Вернуть слово целиком, а не основу: «существенно снизилась».
        start = low.rfind(" ", 0, pos) + 1
        end = low.find(" ", pos)
        return str(text)[start : end if end > 0 else len(str(text))].strip(" .,;:()")
    return None


def normalize_number(text: str) -> Number | None:
    """Первое число строки, если строка — это только число с единицей."""
    nums = extract_numbers(text)
    return nums[0] if nums else None


def _close(a: Decimal, b: Decimal, rel_tol: Decimal = Decimal("0.001")) -> bool:
    if a == b:
        return True
    denom = max(abs(a), abs(b))
    if denom == 0:
        return True
    return abs(a - b) / denom <= rel_tol


def numbers_in_text(numbers: Iterable[str | Number], text: str) -> list[str]:
    """Какие из чисел утверждения не найдены в тексте источника.

    Сравнение идёт по значению, а не подстрокой: «1 999» и «1999» — одно число,
    «47.4» и «47,4» — одно число, «в 50 раз» против 47.4 — разные.
    """
    available = extract_numbers(text)
    missing: list[str] = []
    for item in numbers:
        target = item if isinstance(item, Number) else normalize_number(str(item))
        if target is None:
            missing.append(str(item))
            continue
        if not any(_close(target.value, got.value) for got in available):
            missing.append(str(item))
    return missing
