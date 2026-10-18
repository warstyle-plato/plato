"""Инвентаризация видимых текстов страницы для правки простым языком.

Достаёт из исходников страницы строковые литералы с русским текстом и
помечает те, где есть внутренний жаргон или телеграф (цепочки через «·»,
точки с запятой). Правила — `docs/plain_language.md`, очередь —
`docs/plain_language_inventory.md`.

Это опись, а не проверка: литерал в исходнике ещё не значит, что его видно,
и решает отрисованная страница. Список нужен, чтобы ничего не забыть.

Запуск: python3 scripts/plain_language_inventory.py [--all] > /tmp/inventory.md
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Порядок — по заметности: главный экран и шаги, затем «Экономика»,
# «Результат», остальное.
SURFACES = [
    ("Участок и шаги (слой /ia)", "ia_preview/assets/overlay.js"),
    ("Разметка страницы", "engine/page_markup.py"),
    ("Карточка участка", "engine/page_js_land.py"),
    ("Расчёт по Москве и области", "engine/page_js_mo_glavapu.py"),
    ("Личный кабинет и выгрузки", "engine/page_js_export_projects.py"),
    ("Экономика: поля", "engine/page_js_inputs.py"),
    ("Экономика: подписи полей", "engine/inputs.py"),
    ("Результат и отчёт", "engine/page_js_results.py"),
    ("Расчёт и состояние", "engine/page_js_calc.py"),
    ("Очередность", "engine/page_js_phasing.py"),
    ("ТЭП (кроме блока «Действия с ТЭП», PR #747)", "engine/page_js_tep.py"),
    ("Платон (кроме разбора документов, PR #745)", "engine/page_js_plato.py"),
    ("Общее", "engine/page_js_core.py"),
    ("Telegram в странице", "engine/page_js_telegram.py"),
]

JARGON = re.compile(
    r"производн|вводн|РНГП|соцнагруз|УПКС|Кср\b|КБО|LLCR|DSCR|ГНС|СПП|ННП|"
    r"п\.п\.|overhead|Goal Seek|РВЭ|РнС|ИРД|ОСЗ|МФОЦ|МПТ|НСПД|НКЛ|ГПЗУ|ППТ|"
    r"ГЗК|ДОО|СОШ|м/м|БРИДЖ|\bПФ\b|пресет|движ(?:ок|ка|ке)\b|штатн")
TELEGRAPH = re.compile(r" · |;\s")
LITERAL = re.compile(
    r"'((?:[^'\\\n]|\\.)*[А-Яа-яЁё](?:[^'\\\n]|\\.)*)'"
    r"|\"((?:[^\"\\\n]|\\.)*[А-Яа-яЁё](?:[^\"\\\n]|\\.)*)\""
    r"|>([^<>{}\n]*[А-Яа-яЁё][^<>{}\n]*)<")
COMMENT_START = ("//", "#", "*", "/*", "<!--", '"""')


def literals(path: Path):
    """(номер строки, текст) для русских литералов вне комментариев."""
    in_comment = False
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        stripped = line.strip()
        if in_comment:
            if "*/" in stripped or "-->" in stripped:
                in_comment = False
            continue
        if stripped.startswith(("/*", "<!--")) and "*/" not in stripped and "-->" not in stripped:
            in_comment = True
            continue
        if stripped.startswith(COMMENT_START):
            continue
        for match in LITERAL.finditer(line):
            text = re.sub(r"<[^>]+>", "", next(g for g in match.groups() if g)).strip()
            if len(re.findall("[А-Яа-яЁё]", text)) >= 4:
                yield number, text


def flags(text: str) -> str:
    found = []
    words = sorted({m.group(0) for m in JARGON.finditer(text)})
    if words:
        found.append("жаргон: " + ", ".join(words))
    if TELEGRAPH.search(text):
        found.append("телеграф")
    return "; ".join(found)


def main(argv: list[str]) -> int:
    show_all = "--all" in argv
    for title, rel in SURFACES:
        rows = [(n, t, flags(t)) for n, t in literals(ROOT / rel)]
        marked = [r for r in rows if r[2]]
        print(f"\n### {title} — `{rel}`\n")
        print(f"Литералов: {len(rows)}, с пометкой: {len(marked)}.\n")
        print("| Строка | Текст | Пометка |\n|---|---|---|")
        for number, text, why in (rows if show_all else marked):
            cell = text.replace("|", "\\|")
            cell = cell if len(cell) <= 160 else cell[:157] + "…"
            print(f"| {number} | {cell} | {why} |")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
