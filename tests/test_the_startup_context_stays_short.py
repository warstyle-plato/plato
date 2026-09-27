"""Корневой CLAUDE.md читается каждым туром — и потому у его длины есть сторож.

Файл вырос до 9982 строк не за раз: каждая сессия дописывала разбор своей
поломки, и каждая была права по отдельности. Читается он при этом НА КАЖДОМ
пробуждении — не на каждой правке, а на каждом «посмотрю, как там прогон», — и
20.09.2026 владелец сказал, чем это кончилось: недельный предел съедается за
три дня, пятичасовой за час.

Разделение (короткий корень + архив + индекс) лечит это ровно один раз. Дальше
файл отрастёт обратно, если мешать этому нечем: сам корень просит «не
превращать его снова в журнал разработки», а просьба — не правило. Правило без
сторожа — это память.

Границы названы НАШИМ суждением, а не измерением: корню есть куда расти, но не
в разы. Уперлись — это не повод поднять число, а повод унести разбор в архив,
ради чего разделение и сделано.

Запуск: python3 -m pytest tests/test_the_startup_context_stays_short.py -q
"""

from __future__ import annotations

import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
STARTUP = ROOT / "CLAUDE.md"
ARCHIVE = ROOT / "docs" / "CLAUDE_HISTORY_2026-09-20.md"
INDEX = ROOT / "docs" / "CLAUDE_RULE_INDEX.md"

MAX_LINES = 150
MAX_BYTES = 24_000


def test_the_startup_file_stays_short() -> None:
    text = STARTUP.read_text(encoding="utf-8")
    lines, size = text.count("\n"), len(text.encode("utf-8"))
    assert lines <= MAX_LINES and size <= MAX_BYTES, (
        f"CLAUDE.md разросся: {lines} строк и {size} байт при потолке "
        f"{MAX_LINES} и {MAX_BYTES}. Разбор поломки уносят в "
        f"{ARCHIVE.relative_to(ROOT)}, а сюда пишут короткое правило — "
        "потолок поднимать нельзя, он и есть смысл разделения")


def test_the_startup_file_points_at_files_that_exist() -> None:
    """Указатель на несуществующий файл хуже отсутствующего."""
    text = STARTUP.read_text(encoding="utf-8")
    named = set(re.findall(r"`(docs/[\w./-]+\.md)`", text))
    assert named, "корень не называет ни архива, ни индекса — искать правило негде"
    missing = sorted(n for n in named if not (ROOT / n).exists())
    assert not missing, f"корень ссылается на несуществующее: {missing}"


def test_the_archive_holds_the_history_the_startup_file_gave_up() -> None:
    """Короткий корень честен, только если длинное лежит целиком в архиве."""
    archive = ARCHIVE.read_text(encoding="utf-8")
    assert archive.count("\n") > 5000, (
        "архив короче, чем история проекта: разделение потеряло разборы, "
        "а не перенесло их")


def test_the_index_is_built_from_the_archive_not_by_hand() -> None:
    """Индекс — производная архива, и расходится он молча.

    Рукотворный индекс уже разошёлся: main дописал семь правил, и ссылки
    поехали на прежние строки. Поэтому сверку делает тот же генератор,
    который индекс и собирает, — второй ответ на «где лежит правило»
    однажды разойдётся с первым, и оба будут выглядеть верными.
    """
    done = subprocess.run(
        [sys.executable, "scripts/claude_rule_index.py", "--check"],
        cwd=ROOT, capture_output=True, text=True)
    assert done.returncode == 0, (
        f"{done.stdout}{done.stderr}".strip() or "индекс разошёлся с архивом")


def test_every_index_line_lands_on_its_rule() -> None:
    """Ссылка, ведущая не туда, читается как отсутствие правила."""
    archive = ARCHIVE.read_text(encoding="utf-8").split("\n")
    misses = []
    total = 0
    for line in INDEX.read_text(encoding="utf-8").split("\n"):
        found = re.match(r"- L(\d+) (?:\[[^\]]+\] )?(.+)", line)
        if not found:
            continue
        total += 1
        number, name = int(found.group(1)), found.group(2)
        target = archive[number - 1] if 0 < number <= len(archive) else ""
        if name[:35] not in target:
            misses.append(f"L{number}: индекс «{name[:50]}» / архив «{target[:50]}»")
    assert total > 500, f"индекс почти пуст: {total} ссылок"
    assert not misses, "ссылки индекса ведут не на свои правила:\n  " + \
        "\n  ".join(misses[:5])
