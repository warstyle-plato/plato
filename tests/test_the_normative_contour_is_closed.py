"""Контур законодательной базы замкнут с двух сторон.

Первая сторона: всякий акт, названный в коде движка, опознаётся реестром — его
номером, любым его печатным написанием или номером поправки в его ряду. Акт,
на котором стоит расчёт и которого в реестре нет, — это число без основания:
на экране оно выглядит ровно так же, как посчитанное по норме.

Вторая сторона: всякая строка реестра называет, где её число участвует в
расчёте, — и «не участвует» это тоже ответ, но названный причиной. Реестр,
который перечисляет акты и молчит о применении, отвечает на другой вопрос.

Проверять это надо СКАНОМ, а не чтением: в исходнике акт, забытый в реестре,
выглядит так же уверенно, как заведённый, — и заметить его нечем, пока никто
не сверил два списка. Предохранитель поэтому обязателен: «не опознано: 0»
зелено и на пустом скане.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import normatives_registry as registry

ROOT = Path(__file__).resolve().parents[1]
# Пропускаются каталоги, где номер акта — это цитата документа, а не основание
# расчёта: сами документы, справочные данные, чужие сборки и проверки.
_SKIP_DIRS = {
    "tests", "docs", "data", "reference_data", "genplan_assets", "presets",
    "scripts", "node_modules", "__pycache__",
}
# Номер акта в однозначном написании. Однозначность здесь важнее полноты:
# «приложение 5» или «п. 5.12» без номера акта опознать нечем, и требовать от
# них строки реестра значило бы кричать зря.
_CITATION_RE = re.compile(r"\b(\d{2,4}-ПП|\d{1,3}-ФЗ|СП \d+\.\d+(?:\.\d+)?)\b")
# Путь на диске узнаётся по расширению или по косой на конце: «parking_norms.py»
# и «docs/normative/» проверяются, а «ТЭП / Москва» и имя функции
# «_profit_tax_schedule» — прозаические имена, и файла за ними нет. Пока
# признаком была одна латиница, имя функции требовало файла и проверка кричала
# зря — а кричащая зря хуже отсутствующей.
_PATH_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_./-]*(?:/|\.[a-z]{2,4})$")


def _rows() -> list[dict]:
    data = json.loads((ROOT / "data" / "normatives" / "registry.json").read_text("utf-8"))
    return data["entries"] if isinstance(data, dict) and "entries" in data else data


def _engine_files() -> list[Path]:
    files: list[Path] = []
    for path in sorted(ROOT.rglob("*.py")):
        rel = path.relative_to(ROOT)
        if any(part in _SKIP_DIRS or part.startswith(".") for part in rel.parts[:-1]):
            continue
        files.append(path)
    return files


def code_citations() -> dict[str, set[str]]:
    """Номер акта -> файлы движка, где он назван."""
    found: dict[str, set[str]] = {}
    for path in _engine_files():
        text = path.read_text("utf-8", errors="ignore")
        for match in _CITATION_RE.finditer(text):
            found.setdefault(match.group(1), set()).add(str(path.relative_to(ROOT)))
    return found


def test_the_sweep_actually_reads_the_engine() -> None:
    """Предохранитель: сканер находит акты там, где они точно названы.

    Без него «неопознанных нет» проходит и при пустом скане — то есть
    проверка зеленеет ровно тогда, когда перестаёт работать.
    """
    files = _engine_files()
    assert len(files) > 20, f"скан обошёл {len(files)} файлов движка — это не движок"

    found = code_citations()
    assert len(found) >= 15, f"в коде движка найдено {len(found)} номеров актов — сканер молчит"
    assert "945-ПП" in found and "parking_norms.py" in found["945-ПП"]
    assert "2118-ПП" in found, "постановление о постоянных местах в коде не найдено"


def test_every_act_named_in_the_engine_is_in_the_registry() -> None:
    known = registry.cited_numbers(_rows())
    unresolved = {
        number: files
        for number, files in code_citations().items()
        if number.lower() not in known
    }
    assert not unresolved, "акты названы в коде и не опознаны реестром: " + "; ".join(
        f"{number} ({', '.join(sorted(files))})" for number, files in sorted(unresolved.items())
    )


def test_every_row_can_be_recognised_by_a_number() -> None:
    """Строка без печатного написания номера не опознаёт себя нигде."""
    nameless = [row.get("id") for row in _rows() if not (row.get("cited_as") or [])]
    assert not nameless, f"в реестре есть акты без cited_as: {nameless}"


def test_every_row_names_where_its_number_works() -> None:
    rows = _rows()
    silent = [row.get("id") for row in rows if not (row.get("engine_usage") or [])]
    assert not silent, f"акт в реестре не говорит, где он применяется: {silent}"

    empty = [
        (row.get("id"), entry)
        for row in rows
        for entry in row.get("engine_usage") or []
        if not str(entry.get("module") or "").strip() or not str(entry.get("usage") or "").strip()
    ]
    assert not empty, f"применение названо пустым: {empty}"

    # «Не участвует» — законный ответ, и он обязан назвать причину, а не
    # стоять прочерком: прочерк неотличим от забытой строки.
    unexplained = [
        row.get("id")
        for row in rows
        for entry in row.get("engine_usage") or []
        if str(entry.get("module") or "").strip() == "—"
        and len(str(entry.get("usage") or "")) < 30
    ]
    assert not unexplained, f"«не участвует» без причины: {unexplained}"


def test_a_named_module_exists_on_disk() -> None:
    """Путь, который назвал реестр, обязан существовать.

    Переименованный модуль оставляет в реестре утверждение, которое никто не
    прочитает как ложное: на экране оно выглядит как обычная ссылка.
    """
    missing = [
        (row.get("id"), module)
        for row in _rows()
        for entry in row.get("engine_usage") or []
        if _PATH_RE.match(module := str(entry.get("module") or "").strip())
        and not (ROOT / module).exists()
    ]
    assert not missing, f"реестр называет путь, которого нет: {missing}"
