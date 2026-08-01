"""В выгруженной книге нет ссылки на отсутствующий внешний файл.

В шаблоне живёт ссылка на лист «ОПТИМУМ» с пометкой xlPathMissing: файла, на
который она указывает, нет. Excel при открытии спрашивает про обновление
связей, часть программ такую книгу не грузит вовсе, а пользы от связи никакой —
ни одна формула наружу не смотрит.

Запуск: python3 -m pytest tests -q
"""

from __future__ import annotations

import io
import sys
import zipfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import main as wrapper  # noqa: E402

core = wrapper.core
openpyxl = pytest.importorskip("openpyxl")

TEMPLATE = Path(__file__).resolve().parent.parent / "templates" / "PLATO_template.xlsx"
pytestmark = pytest.mark.skipif(not TEMPLATE.is_file(), reason="шаблон ПЛАТО не поставляется")


def exported() -> bytes:
    data, _ = core.fill_plato_template(dict(core.DEFAULT_INPUTS), core.TEP_DEFAULT,
                                       project_name="Проверка")
    return data


def test_the_template_still_carries_the_dead_link():
    """Сторож: если связь уберут из шаблона, эта правка станет лишней."""
    with zipfile.ZipFile(TEMPLATE) as archive:
        assert any("externalLink" in name for name in archive.namelist())


def test_the_export_has_no_external_links():
    with zipfile.ZipFile(io.BytesIO(exported())) as archive:
        assert not [n for n in archive.namelist() if "externalLink" in n]
        workbook = archive.read("xl/workbook.xml").decode("utf-8")
        rels = archive.read("xl/_rels/workbook.xml.rels").decode("utf-8")
        types = archive.read("[Content_Types].xml").decode("utf-8")

    assert "externalReference" not in workbook
    assert "externalLink" not in rels
    assert "externalLink" not in types


def test_nothing_else_is_lost():
    """Убираем связь, а не листы, диаграммы и рисунки."""
    data = exported()
    with zipfile.ZipFile(TEMPLATE) as before, zipfile.ZipFile(io.BytesIO(data)) as after:
        for tag in ("xl/worksheets/sheet", "xl/charts/", "xl/drawings/", "xl/media/"):
            assert (len([n for n in after.namelist() if n.startswith(tag)])
                    == len([n for n in before.namelist() if n.startswith(tag)])), tag


def test_the_workbook_still_opens_and_recalculates():
    workbook = openpyxl.load_workbook(io.BytesIO(exported()))

    assert len(workbook.sheetnames) == 27
    assert workbook.calculation.fullCalcOnLoad is True
