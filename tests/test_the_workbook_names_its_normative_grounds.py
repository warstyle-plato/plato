"""Нормативные основания расчёта доезжают до листа «Источники» книги.

Владелец просил справочник нормативных актов в книге. Второго листа под него
не заводим: лист «Источники» у шаблона есть и отвечает ровно на этот вопрос —
чем посчитано. Реестр при этом НЕ копируется: строки собираются из
`normatives_registry`, и копию негде обновлять, потому что копии нет.

Отбор по юрисдикции — уже сделанная поломка: в книгу областного проекта
уезжало московское 593-ПП, и сверка честно читала это как «источники от другой
юрисдикции». Здесь это проверяется в обе стороны.

Запуск: python3 -m pytest tests/test_the_workbook_names_its_normative_grounds.py -q
"""

from __future__ import annotations

import copy
import html
import io
import re
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import main_legacy as core  # noqa: E402
import normatives_registry  # noqa: E402


def _sources_sheet(region: str) -> str:
    x = dict(core.DEFAULT_INPUTS)
    x["vri_region"] = region
    content, _, meta = core.build_project_workbook(
        x, copy.deepcopy(core.TEP_DEFAULT), [], None, project_name="Нормативы")
    assert not [item for item in (meta.get("missing") or []) if "Источники" in str(item)], \
        meta.get("missing")
    with zipfile.ZipFile(io.BytesIO(content)) as book:
        wb = book.read("xl/workbook.xml").decode("utf-8")
        rid = re.search(r'name="Источники"[^>]*?r:id="([^"]+)"', wb).group(1)
        rels = book.read("xl/_rels/workbook.xml.rels").decode("utf-8")
        target = re.search(rf'Target="([^"]+)"\s+Id="{re.escape(rid)}"', rels).group(1)
        return book.read("xl/" + target.lstrip("/").removeprefix("xl/")).decode("utf-8")


def _texts(xml: str) -> list[str]:
    """Текст ячеек: подпись лежит и `inlineStr`, и `t="str"` со значением.

    Шапка этого листа записана вторым способом — чтение только первого дало бы
    пустую шапку на исправной книге.
    """
    return [html.unescape(value) for value in
            re.findall(r"<x:t[^>]*>(.*?)</x:t>|<x:v>(.*?)</x:v>", xml, re.S)
            for value in [value[0] or value[1]] if value]


def test_the_registry_is_not_empty() -> None:
    """Предохранитель: пустой реестр позеленил бы половину файла."""
    rows = list(normatives_registry._merged_registry())
    assert len(rows) >= 10, f"в реестре {len(rows)} позиций — проверять нечего"
    scopes = {str(row.get("scope") or "") for row in rows}
    assert "Москва" in scopes and "Московская область" in scopes
    # Федеральная область у реестра зовётся своим именем, и спеллить его здесь
    # нельзя: проверка тогда держала бы не утверждение, а сегодняшнюю подпись.
    assert scopes - {"Москва", "Московская область"}, "федеральных актов в реестре нет"


def test_moscow_book_carries_the_moscow_acts() -> None:
    said = " ".join(_texts(_sources_sheet("msk")))
    assert "НОРМАТИВНЫЕ ОСНОВАНИЯ РАСЧЁТА" in said
    assert "945-ПП" in said and "593-ПП" in said
    # Ссылка на исходник — то, по чему нас проверяют.
    assert "https://" in said


def test_the_oblast_book_does_not_carry_moscow_acts() -> None:
    """Московское 593-ПП как ОСНОВАНИЕ областного расчёта — чужая юрисдикция.

    Смотрим строки оснований (SRC- и NRM-), а не весь лист: ниже стоит история
    версий модели («v2: сценарии ставки, авто-лимит ПФ, ВРИ по 593-ПП»), и это
    запись о том, что умела прошлая версия, а не утверждение о ЭТОМ проекте.
    Переписать её значило бы подделать историю ради зелёной проверки.
    """
    xml = _sources_sheet("mo")
    grounds = []
    for row in re.findall(r'<x:row r="\d+"[^>]*>.*?</x:row>', xml, re.S):
        cells = _texts(row)
        if cells and re.match(r"^(SRC|NRM)-", str(cells[0])):
            grounds.append(" ".join(cells))
    assert len(grounds) >= 10, f"строк оснований найдено {len(grounds)} — разбор не сработал"
    said = " ".join(grounds)
    assert "НОРМАТИВНЫЕ ОСНОВАНИЯ РАСЧЁТА" in " ".join(_texts(xml))
    assert "593-ПП" not in said, "московская плата за ВРИ уехала в областную книгу"
    assert "1745" in said, "областного порядка платы за ВРИ в основаниях нет"
    # Федеральный уровень идёт обоим — он не про юрисдикцию субъекта.
    assert "43-ФЗ" in said


def test_the_status_word_is_the_registry_word_not_a_reassurance() -> None:
    """У половины позиций статус «Требует сверки» — выдать это за
    проверенное значит подписать чужим именем."""
    said = " ".join(_texts(_sources_sheet("msk")))
    statuses = {str(row.get("status") or "")
                for row in normatives_registry._merged_registry()
                if str(row.get("scope") or "") in ("Москва", "Российская Федерация")}
    for status in statuses:
        word = core._V4_NORMATIVE_STATUS_WORDS.get(status)
        assert word, f"статус «{status}» реестра не назван словом"
        assert word in said, f"слово статуса «{word}» до листа не доехало"


def test_the_columns_are_the_sheets_own_header() -> None:
    """Вторая формулировка тех же колонок разошлась бы с первой молча."""
    xml = _sources_sheet("msk")
    header = re.search(r'<x:row r="3"[^>]*>(.*?)</x:row>', xml, re.S).group(1)
    names = _texts(header)
    assert "ID" in names and "Статус" in names
    said = _texts(xml)
    # Шапка встречается дважды: у шаблонного блока и у нашего.
    assert said.count("Статус") >= 2, "наш блок идёт без подписей колонок"


def test_our_rows_wear_the_sheets_own_style() -> None:
    """Стили берутся у шаблона: строка без стиля читается чужой вставкой."""
    xml = _sources_sheet("msk")
    rows = {int(n): body for n, body in
            re.findall(r'<x:row r="(\d+)"[^>]*>(.*?)</x:row>', xml, re.S)}
    ours = max(rows)
    template_style = re.search(r'<x:c r="A4"([^>]*)>', xml)
    assert template_style and 's="' in template_style.group(1), "у шаблона нет стиля A4"
    mine = re.search(rf'<x:c r="A{ours}"([^>]*)>', xml)
    assert mine and 's="' in mine.group(1), "наша строка идёт без стиля"


def test_the_sheet_is_not_a_second_registry() -> None:
    """Копии реестра в движке нет — строки собираются из него."""
    source = Path(core.__file__).read_text(encoding="utf-8")
    block = source[source.index("def _v4_normative_sources_rows("):]
    block = block[:block.index("\ndef ", 10)]
    assert "_merged_registry" in block, "лист собирается не из реестра"
    # Объяснение — не код: первая версия этого сторожа завалилась на
    # собственной строке, где названо, какой акт уезжал не в ту юрисдикцию.
    # Запрещают МЕСТО, а не слово, поэтому пояснение из поиска вырезается.
    body = block.split('"""', 2)
    block = body[2] if len(body) > 2 else block
    for literal in ("945-ПП", "593-ПП", "1745", "мos.ru"):
        assert literal not in block, f"в сборщике зашит акт «{literal}» — это копия реестра"


def test_the_cells_of_a_row_go_in_column_order() -> None:
    """Ячейка не на своём месте — та же поломка, что тег листа не в порядке.

    Дата дописывалась в конец строки, за колонку «Комментарий». Excel при
    таком порядке объявляет книгу повреждённой, а на экране это неотличимо
    от «книга не собралась» — то есть от нашей ошибки сборки.
    """
    xml = _sources_sheet("msk")
    broken = []
    for row in re.finditer(r'<x:row r="(\d+)"[^>]*>(.*?)</x:row>', xml, re.S):
        columns = re.findall(r'<x:c r="([A-Z]+)\d+"', row.group(2))
        if columns != sorted(columns, key=lambda name: (len(name), name)):
            broken.append(row.group(1))
    assert not broken, f"ячейки не по порядку в строках: {broken}"
