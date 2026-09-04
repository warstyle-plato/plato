"""В книге нет чисел там, где в шаблоне стояла формула, — кроме названных.

«Эксель должен работать почти как движок… но если что-то меняешь где-то, всё
должно меняться так же, как в движке» (решение владельца, 03.09.2026), и до
этого — его же опасение: «как провести ревизию, что у нас не появились харды
какие-нибудь вместо формул».

Ревизии не существовало вовсе, и настоящий хард выглядел бы точно как
намеренный. Первая ревизия нашла 482 клетки: помесячная соцстройка (480),
расчётный лимит ПФ и дата соцплатежа. Цена харда не в том, что число
устареет: соседние статьи — формулы, они поедут за новым календарём очереди, а
записанная числом строка останется в прежних колонках. Внутри книги это
выглядит исправно — итоги считаются, цифры на месте, — и стройка уезжает на
год, пока садик стоит на месте.

Сторож сверяет собранную книгу с шаблоном клетка в клетку и валится на каждой
замене «формула → число», которой нет в `V4_ENGINE_WRITTEN_CELLS` с причиной.

Запуск: python3 -m pytest tests/test_the_workbook_has_no_unnamed_hard_values.py -q
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import main_legacy as core  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))

import v4_inputs  # noqa: E402

openpyxl = pytest.importorskip("openpyxl")

TEMPLATE = ROOT / "templates" / "DevelopAid_model_v4.xlsx"


def read(source) -> dict[str, dict[str, tuple[str, str]]]:
    """{лист: {клетка: ('f'|'v', содержимое)}} — формула или значение.

    Ввод переехал на свой лист, и на прежней координате стоит ссылка на него.
    Ссылка — тоже формула, поэтому «число на месте формулы шаблона» на листе
    вводных стало бы невидимым: сравнение показывало бы формулу против
    формулы. Ровно на этом листе харды и вероятнее всего — движок пишет туда
    все вводные. Поэтому ссылка раскрывается, лист сравнивается под прежним
    именем, а сам лист ввода отдельной записью не идёт: он не копия
    шаблонного, а его продолжение.
    """
    book = openpyxl.load_workbook(source, data_only=False)
    out: dict[str, dict[str, tuple[str, str]]] = {}
    for sheet in book.worksheets:
        if sheet.title == v4_inputs.ENTRY and v4_inputs.PARAMS in book.sheetnames:
            continue
        cells: dict[str, tuple[str, str]] = {}
        view = (v4_inputs.inputs(book)
                if sheet.title == v4_inputs.PARAMS and v4_inputs.ENTRY in book.sheetnames
                else None)
        for row in sheet.iter_rows():
            for cell in row:
                value = view[cell.coordinate].value if view is not None else cell.value
                if value is None:
                    continue
                if isinstance(value, str) and value.startswith("="):
                    cells[cell.coordinate] = ("f", value[:90])
                else:
                    cells[cell.coordinate] = ("v", str(value)[:40])
        out["Вводные" if view is not None else sheet.title] = cells
    book.close()
    return out


@pytest.fixture(scope="module")
def revision():
    content, _, meta = core.build_project_workbook(
        dict(core.DEFAULT_INPUTS), core.TEP_DEFAULT, [], {}, project_name="ревизия")
    return read(TEMPLATE), read(io.BytesIO(content)), meta


def test_the_revision_actually_read_the_book(revision):
    """Ноль найденного значит что-то только вместе с числом прочитанного.

    Первый заход разбирал XML своими руками, нашёл ноль листов — и напечатал
    «замен нет». Пустой разбор и чистая книга выглядят одинаково.
    """
    was, now, _ = revision
    formulas = sum(1 for cells in was.values() for kind, _ in cells.values() if kind == "f")
    assert len(was) >= 15, was.keys()
    assert formulas > 50_000, formulas
    assert set(now) == set(was), "в собранной книге не те листы"


def _replacements(was, now):
    found = []
    for sheet, before in was.items():
        after = now.get(sheet, {})
        for coord, (kind, text) in before.items():
            if kind != "f":
                continue
            if after.get(coord, ("f", ""))[0] == "v":
                found.append((sheet, coord, text, after[coord][1]))
    return found


def test_every_hard_value_is_named_with_its_reason(revision):
    """Хард без причины — это хард, о котором никто не знает."""
    was, now, _ = revision
    unnamed = [(s, c, was_text, now_text)
               for s, c, was_text, now_text in _replacements(was, now)
               if not core.v4_hard_value_reason(s, c)]
    if unnamed:
        lines = [f"{s}!{c}: было {w} · стало {n}" for s, c, w, n in unnamed[:12]]
        pytest.fail(
            f"в книге {len(unnamed)} чисел на месте формул шаблона, и они не названы:\n  "
            + "\n  ".join(lines)
            + (f"\n  …ещё {len(unnamed) - 12}" if len(unnamed) > 12 else "")
            + "\n\nЛибо запиши формулу, либо назови причину в V4_ENGINE_WRITTEN_CELLS.")


def test_the_named_list_has_no_stale_rows(revision):
    """Названная причина без харда — след правки, которая уже сделана.

    Оставленная строка обещает ограничение, которого нет: читатель списка
    решит, что клетка по-прежнему не пересчитывается.
    """
    was, now, _ = revision
    live = set()
    for sheet, coord, _, _ in _replacements(was, now):
        live.add((sheet, coord))
        row = "".join(ch for ch in coord if ch.isdigit())
        live.add((sheet, f"строка {row}"))
    stale = [key for key in core.V4_ENGINE_WRITTEN_CELLS if key not in live]
    assert stale == [], f"причина стоит там, где харда уже нет: {stale}"


def test_the_guard_catches_a_planted_hard(revision):
    """Проверка, которая не падает на поломке, — не проверка."""
    was, now, _ = revision
    sheet = "КРЕДИТЫ"
    coord = next(c for c, (kind, _) in was[sheet].items() if kind == "f")
    broken = {**now, sheet: {**now[sheet], coord: ("v", "1234")}}
    planted = [(s, c) for s, c, _, _ in _replacements(was, broken)
               if not core.v4_hard_value_reason(s, c)]
    assert (sheet, coord) in planted, "подсунутый хард сторож не увидел"


def test_the_book_reports_nothing_missing(revision):
    """Клетка без соответствия уходит в meta['missing'], а не молчит."""
    _, _, meta = revision
    assert list(meta.get("missing") or []) == [], meta.get("missing")
