"""ТЭП тизера перечисляет только продукты, которые есть в проекте.

Владелец (04.10.2026, прод 0.24.90): в тизере, блок «ТЭП» второй страницы,
стояли все продукты движка — «Кладовые» с единицами 0, «Офисы / МФОЦ»,
«Офисы 2…5», «Коммерция ОСЗ», «ОСЗ 2…5», «Наземный паркинг», «ФОК /
медцентр» — при проекте из квартир, коммерции 1 этажа и подземного паркинга.
Состав отчёта страницы и полного PDF починен признаком `excluded` (#582), а
модель представления тизера признак не переносила.

Есть ли продукт в проекте — решает движок одной функцией (`row_listed`):
её читают тизер (через модель представления) и ТЭП полного PDF. Отсутствие —
не ноль: кладовых без метров и штук нет, и «0» им не печатается.

Проверяется отрисованный тизер: настоящий расчёт, настоящая сборка PDF;
строки снимаются с той сетки, которую тизер действительно рисует.

Запуск: python3 -m pytest tests/test_the_teaser_lists_only_project_products.py -q
"""

from __future__ import annotations

import copy
import io
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import main as _wrapper  # noqa: E402
import teaser_pdf  # noqa: E402

core = _wrapper.core

TEP_HEADER = ["Продукт", "ГНС, м²", "Продаваемая, м²", "Единиц"]
ABSENT = ("Кладовые", "Офисы / МФОЦ", "Офисы 2", "Офисы 5", "Коммерция ОСЗ",
          "Наземный паркинг", "ФОК / медцентр")


def _owner_project() -> tuple[dict, dict]:
    """Проект владельца: квартиры, коммерция 1 этажа, подземный паркинг."""
    x = copy.deepcopy(core.DEFAULT_INPUTS)
    x.update(project_name="Тизер владельца", kindergarten_places=0, social_dou_gba_sqm=0)
    t = copy.deepcopy(core.TEP_DEFAULT)
    t["apartments"].update(gns=13193, total_area=12000, useful=8575, saleable=8575, units=180)
    t["ground_commercial"].update(gns=842, total_area=800, useful=758, saleable=758)
    t["underground_parking"].update(gns=3815, total_area=3815, units=32, guest_units=0)
    t["kindergarten"].update(gns=0, total_area=0, transfer=0, units=0, transfer_units=0)
    return x, t


def _objects_project() -> tuple[dict, dict]:
    """Тот же дом плюс офисы, ОСЗ и второй наземный паркинг."""
    x, t = _owner_project()
    x.update(offices_enabled=True, offices_gba_sqm=6000, offices_saleable_sqm=4000,
             retail_enabled=True, above_parking_enabled=False,
             above_parking2_enabled=True, object_instances=["above_parking2"])
    t["offices"].update(gns=6000, total_area=5600, saleable=4000)
    t["standalone_retail"].update(gns=3000, total_area=2800, saleable=2000)
    t["above_parking2"].update(gns=2500, total_area=2500, units=100)
    return x, t


def _drawn_tep(shape, monkeypatch) -> tuple[list[list[str]], str]:
    """Строки сетки ТЭП, которую рисует тизер, и текст его PDF."""
    drawn: list[list[list[str]]] = []
    real_grid = teaser_pdf._grid

    def spy(header, rows, *args, **kwargs):
        if list(header) == TEP_HEADER:
            drawn.append([list(row) for row in rows])
        return real_grid(header, rows, *args, **kwargs)

    monkeypatch.setattr(teaser_pdf, "_grid", spy)
    x, t = shape()
    bundle = core._run_authoritative_model(x, t, [], None)
    content = core.build_teaser_pdf(bundle, x, t, None)
    assert len(drawn) == 1, f"сетка ТЭП нарисована {len(drawn)} раз"
    from pypdf import PdfReader
    text = "\n".join(page.extract_text() or "" for page in PdfReader(io.BytesIO(content)).pages)
    return drawn[0], text


def _check_owner_project(rows: list[list[str]], text: str) -> None:
    labels = [row[0] for row in rows]
    assert labels == ["Квартиры", "Коммерция 1 этажа", "Подземный паркинг", "Итого"], labels
    for label in ABSENT:
        assert label not in text, f"«{label}» в тизере, а в проекте его нет"


def test_the_owner_project_lists_three_products(monkeypatch) -> None:
    rows, text = _drawn_tep(_owner_project, monkeypatch)
    _check_owner_project(rows, text)
    by_label = {row[0]: row for row in rows}
    # Подземный паркинг — штучный: его места стоят в колонке единиц.
    assert by_label["Подземный паркинг"][3] not in ("", "—", "0"), by_label["Подземный паркинг"]


def test_the_counterfeit_that_lists_everything_is_caught(monkeypatch) -> None:
    """Подделка «вернуть все строки» обязана ронять проверку."""
    monkeypatch.setattr(core, "row_listed", lambda row: True)
    rows, text = _drawn_tep(_owner_project, monkeypatch)
    assert "Кладовые" in [row[0] for row in rows]
    with pytest.raises(AssertionError):
        _check_owner_project(rows, text)


def test_project_objects_keep_their_rows(monkeypatch) -> None:
    rows, _text = _drawn_tep(_objects_project, monkeypatch)
    labels = [row[0] for row in rows]
    for label in ("Квартиры", "Офисы / МФОЦ", "Коммерция ОСЗ", "Наземный паркинг 2", "Итого"):
        assert label in labels, (label, labels)
    for label in ("Кладовые", "Офисы 2", "Наземный паркинг", "ФОК / медцентр"):
        assert label not in labels, (label, labels)


def test_the_full_pdf_reads_the_same_rule() -> None:
    """Полный PDF печатает ТЭП той же функцией — второго фильтра нет."""
    source = Path(core.__file__).read_text(encoding="utf-8")
    start = source.index("def _build_developaid_pdf(")
    body = source[start:source.index("\ndef ", start + 1)]
    assert "if row_listed(row)" in body
