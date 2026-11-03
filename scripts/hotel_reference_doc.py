"""Таблицы `docs/hotel_reference_benchmarks.md` из `hotel_reference`.

Числа в документе не набираются руками: их владелец — модуль, а он сверен
тестом с ячейками книг. Скрипт заменяет блок между маркерами; текст вокруг
блока пишет человек.

    python3 scripts/hotel_reference_doc.py           # напечатать блок
    python3 scripts/hotel_reference_doc.py --write   # обновить документ
    python3 scripts/hotel_reference_doc.py --check   # код 1, если документ отстал
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import hotel_reference as ref  # noqa: E402

DOC = ROOT / "docs" / "hotel_reference_benchmarks.md"
BEGIN = "<!-- hotel_reference:begin (собрано scripts/hotel_reference_doc.py, руками не править) -->"
END = "<!-- hotel_reference:end -->"


def _number(value: float, digits: int) -> str:
    text = f"{value:,.{digits}f}".replace(",", " ").replace(".", ",")
    if "," in text:
        text = text.rstrip("0").rstrip(",")
    return text


def fmt(value: float, unit: str) -> tuple[str, str]:
    """Значение и подпись единицы для таблицы; доли — в процентах."""
    if unit.startswith("доля"):
        return _number(value * 100, 2), unit.replace("доля", "%", 1)
    if isinstance(value, int) or float(value).is_integer():
        return _number(value, 0), unit
    digits = 2 if abs(value) >= 1 else 4
    return _number(value, digits), unit


def _row(*cells: str) -> str:
    return "| " + " | ".join(cell.replace("|", "\\|") for cell in cells) + " |"


def render() -> str:
    out: list[str] = [BEGIN, ""]
    for group, title in ref.GROUPS.items():
        rows = [b for b in ref.BENCHMARKS if b.group == group]
        derived = [d for d in ref.DERIVED if d.group == group]
        if not rows and not derived:
            continue
        out += [f"### {title}", "",
                _row("Модель", "Показатель", "Значение", "Ед.", "Источник (файл · лист · ячейка)"),
                _row("---", "---", "---:", "---", "---")]
        for b in rows:
            shown, unit = fmt(b.value, b.unit)
            label = b.label + (f" ({b.note})" if b.note else "")
            out.append(_row(b.model, label, shown, unit, b.source))
        for d in derived:
            shown, unit = fmt(d.value, d.unit)
            num, den = ref.BY_KEY[d.numerator], ref.BY_KEY[d.denominator]
            scale = "" if d.scale == 1.0 else f" × {_number(d.scale, 0)}"
            label = d.label + (f" ({d.note})" if d.note else "")
            how = f"{num.sheet.strip()}!{num.cell}{scale} ÷ {den.sheet.strip()}!{den.cell}"
            out.append(_row(d.model, label, shown, unit, f"расчёт: {how}"))
        out.append("")
    out += ["### Расхождения внутри книг", "",
            _row("Что", "Ячейки и значения", "Комментарий"),
            _row("---", "---", "---")]
    for title, keys, comment in ref.DISCREPANCIES:
        cells = "; ".join(
            f"{ref.BY_KEY[k].sheet.strip()}!{ref.BY_KEY[k].cell} = "
            + " ".join(fmt(ref.BY_KEY[k].value, ref.BY_KEY[k].unit))
            for k in keys)
        out.append(_row(title, cells, comment))
    out += ["", END]
    return "\n".join(out)


def current_block(text: str) -> str:
    start, end = text.index(BEGIN), text.index(END) + len(END)
    return text[start:end]


def main(argv: list[str]) -> int:
    block = render()
    if "--write" in argv or "--check" in argv:
        text = DOC.read_text(encoding="utf-8")
        if "--check" in argv:
            if current_block(text) != block:
                print(f"{DOC.relative_to(ROOT)} отстал от hotel_reference: "
                      "python3 scripts/hotel_reference_doc.py --write")
                return 1
            return 0
        DOC.write_text(text.replace(current_block(text), block), encoding="utf-8")
        return 0
    print(block)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
