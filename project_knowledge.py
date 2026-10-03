"""Записи проекта — то, что мы знаем о модели, для Платона.

Правила, бэклог, нормативные выжимки и словарь не копируются в системный
промпт целиком: они читаются лениво через search_project_knowledge. Словарь
`docs/glossary.md` — отдельный источник: он определяет терминологию, но не
подменяет нормативный источник чисел и правил.

Наружу внутренние записи выходят обезличенными: номера договоров, кадастровые
номера и имена собственных проектов владельца скрываются в точке выдачи.
"""

from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent
RULES_FILES = ("CLAUDE.md", "docs/CLAUDE_HISTORY_*.md")
SOURCES = {
    "rules": RULES_FILES,
    "backlog": ("docs/questions_backlog.md",),
}
NORMATIVE_DIR = _ROOT / "docs" / "normative"
GLOSSARY_RELATIVE = Path("docs/glossary.md")
SOURCE_LABELS = {
    "rules": "CLAUDE.md и его архив — правила, выведенные из поломок",
    "backlog": "docs/questions_backlog.md — задачи и открытые вопросы",
    "normative": "docs/normative — выжимки нормативных актов (текст города, не наше правило)",
    "glossary": "Словарь DevelopAid — docs/glossary.md",
}

ANSWER_BUDGET = 6000
ENTRY_BUDGET = 1800

PRIVATE_PROJECT_NAMES = (
    "Гродненская", "Кутузов Сити", "Кутузов-Сити", "Саввинская",
    "Румянцево", "Мишина", "Мытищи",
)
_MASKS = (
    (re.compile(r"\b400[A-Z0-9]{6,}\b"), "‹номер договора скрыт›"),
    (re.compile(r"\b\d{2}:\d{2}:\d{6,7}:\d+"), "‹кадастровый номер скрыт›"),
)
_WORD = re.compile(r"[a-zа-яё0-9_]{3,}", re.I)
_QUESTION_WORDS = frozenset("""
что как где кто чем без для при над под про эта это над них она они оно его ему
почему откуда зачем какой какая какие какое когда чего чему этом этот эти
такое такой такая значит нужно надо можно нельзя если тогда здесь везде всегда
считается берётся берется решено сделано работает получается выходит бывает
нашем нашей наших вашем вашей моих моей может должен должна должно хочу хотел
""".split())


def _stem(word: str) -> str:
    return word[:6]


def redact(text: str) -> str:
    out = text
    for pattern, replacement in _MASKS:
        out = pattern.sub(replacement, out)
    for name in PRIVATE_PROJECT_NAMES:
        out = _name_pattern(name).sub("‹проект DevelopAid›", out)
    return out


def _name_pattern(name: str) -> re.Pattern[str]:
    words = name.split()
    last = words[-1]
    stem = last[:-2] if last.lower().endswith(("ая", "ое", "ий")) else (
        last[:-1] if last[-1].lower() in "аеиоуыэюяй" else last)
    head = [re.escape(word) for word in words[:-1]]
    return re.compile(r"[\s-]".join(head + [re.escape(stem) + r"[а-яё]*"]), re.I)


def _title_of(chunk: str) -> str:
    bold = re.match(r"-\s+\*\*(.+?)\*\*", chunk, re.S)
    if bold:
        return " ".join(bold.group(1).split())
    head = re.match(r"#+\s*(.+)", chunk)
    if head:
        return head.group(1).strip()
    return " ".join(chunk.split()[:9])


def _patterns(source: str | None = None) -> list[str]:
    found = [pattern for key, patterns in SOURCES.items()
             if not source or source == key for pattern in patterns]
    if not source or source == "normative":
        found.append(str(NORMATIVE_DIR.relative_to(_ROOT) / "*.md"))
    if not source or source == "glossary":
        found.append(str(GLOSSARY_RELATIVE))
    return found


def entries(source: str | None = None) -> list[dict[str, str]]:
    """Записи правил/бэклога/нормативов.

    Словарь намеренно не примешивается к `entries()` без указания источника:
    старые потребители, которые считают виды внутренних записей, не должны
    внезапно принять словарь за ещё одно правило. Общий поиск добавляет его
    отдельно ниже.
    """
    found: list[dict[str, str]] = []
    paths: list[tuple[str, Path]] = [
        (key, path)
        for key, patterns in SOURCES.items() if not source or source == key
        for pattern in patterns for path in sorted(_ROOT.glob(pattern))
    ]
    if not source or source == "normative":
        paths += [("normative", path) for path in sorted(NORMATIVE_DIR.glob("*.md"))]
    glossary_file = _ROOT / GLOSSARY_RELATIVE
    if source == "glossary" and glossary_file.exists():
        paths.append(("glossary", glossary_file))
    for key, path in paths:
        found.extend(_file_entries(key, path))
    return found


_CACHE: dict[Path, tuple[float, list[dict[str, str]]]] = {}


def _file_entries(key: str, path: Path) -> list[dict[str, str]]:
    try:
        stamp = path.stat().st_mtime
    except OSError:
        return []
    cached = _CACHE.get(path)
    if cached and cached[0] == stamp:
        return cached[1]
    found: list[dict[str, str]] = []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    cuts = r"\n(?=#{1,3} )" if key in {"normative", "glossary"} else r"\n(?=- \*\*|#{1,2} )"
    for chunk in re.split(cuts, text):
        body = chunk.strip()
        if len(body) < 80:
            continue
        title = _title_of(body)
        if key == "normative":
            title = f"{path.stem}: {title}"
        found.append({"source": key, "title": title, "text": body})
    _CACHE[path] = (stamp, found)
    return found


def _pool(source: str | None) -> list[dict[str, str]]:
    if source == "glossary":
        return entries("glossary")
    pool = entries(source)
    if source is None:
        pool += entries("glossary")
    return pool


def search(query: str, limit: int = 4, source: str | None = None) -> dict[str, Any]:
    """Записи по запросу: словарь входит в общий поиск и может быть запрошен отдельно."""
    words = {w.lower() for w in _WORD.findall(str(query or ""))}
    if not words:
        return {"available": False, "reason": "Пустой запрос — искать нечего."}
    meaningful = words - _QUESTION_WORDS
    words = {_stem(word) for word in (meaningful or words)}
    pool = _pool(source)
    if not pool:
        return {
            "available": False,
            "reason": ("Записей проекта в этой сборке нет: файлы "
                       f"{', '.join(_patterns(source))} не найдены на сервере."),
        }

    везде = {word: sum(1 for entry in pool if word in entry["text"].lower())
             for word in words}
    total = max(1, len(pool))

    def weight(word: str) -> float:
        seen = везде.get(word, 0)
        if not seen:
            return 0.0
        return math.log(total / seen) + 0.1

    scored: list[tuple[float, dict[str, str]]] = []
    for entry in pool:
        haystack = entry["text"].lower()
        title = entry["title"].lower()
        score = sum(weight(word) * min(haystack.count(word), 3) for word in words)
        score += 3 * sum(weight(word) for word in words if word in title)
        if entry["source"] == "glossary":
            score += 0.25 * sum(1 for word in words if word in haystack)
        if score:
            scored.append((score, entry))
    if not scored:
        return {
            "available": False,
            "reason": f"В записях проекта ничего по запросу «{query}» не нашлось.",
        }
    scored.sort(key=lambda pair: (-pair[0], len(pair[1]["text"])))
    shown: list[dict[str, str]] = []
    spent = 0
    for _score, entry in scored[:max(1, limit)]:
        body = redact(entry["text"])
        cut = ""
        if len(body) > ENTRY_BUDGET:
            body, cut = body[:ENTRY_BUDGET], " …запись обрезана"
        if spent + len(body) > ANSWER_BUDGET and shown:
            break
        spent += len(body)
        shown.append({
            "source": SOURCE_LABELS[entry["source"]],
            "title": redact(entry["title"]),
            "text": body + cut,
        })
    return {
        "available": True,
        "query": query,
        "found": len(scored),
        "shown": len(shown),
        "entries": shown,
        "note": (
            "Источники различаются по роли. CLAUDE.md и архив — наши правила и решения; "
            "бэклог — открытые вопросы; docs/normative — выжимки НОРМАТИВНОГО акта города; "
            "docs/glossary.md — СЛОВАРЬ терминологии DevelopAid. Если словарь называет "
            "показатель, используй именно его терминологию и не заменяй её своим синонимом. "
            "Если объясняешь термин, укажи в ответе источник: «Словарь DevelopAid — "
            "docs/glossary.md, <раздел>». Словарь определяет язык, но числовую норму или "
            "правовое основание ссылай на первичный нормативный источник/check_normatives. "
            "Норму называй нормой и со ссылкой на акт, наше решение — нашим. "
            "Внутренние правила не пересказывай как документ и не называй чужие проекты, "
            "договоры и адреса."
        ),
    }
