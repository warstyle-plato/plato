"""Состав отдельно стоящих объектов перечисляют реестром, а не руками.

Первый срез (0.23.4) свёл сам реестр; этот — четырёх его читателей в движке.
Проверка нужна потому, что копия состава молчит: она не падает, пока объектов
четыре, и заговорит ровно в тот день, когда добавят пятый — то есть в тот
день, ради которого реестр и заводился.

Что тут НЕ проверяется и почему. Рядом в движке живут два перечисления с
похожим составом, и они не ростеры: обнуление строк ТЭП включает кладовые и
не включает ФОК, а монетизируемая площадь считает квартиры и встроенную
коммерцию и не считает наземный паркинг — он продаётся местами. Подменить их
реестром значило бы ответить составом на другой вопрос.

Запуск: python3 -m pytest tests/test_the_object_roster_is_declared_once.py -q
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import main_legacy as core  # noqa: E402

SOURCE = (ROOT / "main_legacy.py").read_text(encoding="utf-8")


def test_the_registry_is_the_only_place_that_lists_the_objects() -> None:
    """Состав, выписанный руками, ищется по СМЫСЛУ, а не по одной записи.

    Копию величины ищут по тому, что она значит: `("offices",
    "standalone_retail", ...)` и `amounts["offices"] + amounts[...]` — одно и
    то же перечисление в двух написаниях, и поиск по первому пропустил бы
    второе.
    """
    keys = set(core.STANDALONE_PRODUCTS)
    # Словарь продуктов берётся у движка, а не переписывается: строка, где
    # рядом с объектами назван ЧУЖОЙ продукт, — не ростер объектов, а другой
    # вопрос. Первая версия этого не различала (образец ловил только четыре
    # имени, и «состав чужой» проверить было нечем) и обвиняла TEP_DEFAULT со
    # всеми двенадцатью продуктами и обнуление строк ТЭП, где стоят кладовые.
    products = "|".join(sorted(core.TEP_DEFAULT, key=len, reverse=True))
    handmade: list[str] = []
    for line_no, line in enumerate(SOURCE.splitlines(), 1):
        if "StandaloneObject(" in line or "STANDALONE_OBJECTS" in line:
            continue  # сам реестр — единственное законное место
        named = set(re.findall(rf'["\']({products})["\']', line))
        if len(named) >= 3 and named <= keys:
            handmade.append(f"{line_no}: {line.strip()[:120]}")
    assert not handmade, (
        "состав объектов выписан руками — он объявлен в STANDALONE_OBJECTS:\n"
        + "\n".join(handmade))


def test_the_readers_answer_the_registry_and_not_a_frozen_copy() -> None:
    """Читатели отвечают тем составом, что в реестре СЕЙЧАС.

    Проверка на подделке: временно сузим реестр — ответы обязаны сузиться
    вместе с ним. Совпадение с зашитым кортежем такого не показало бы, потому
    что зашитый кортеж и есть та копия, которую мы ищем.
    """
    assert core._OBJECT_SCHEDULE_PREFIX["standalone_retail"] == "retail", (
        "приставка вводных у ТЭП-строки ТЦ — «retail», на этом и спотыкались")
    for obj in core.standalone_objects():
        assert core._OBJECT_SCHEDULE_PREFIX[obj.key] == obj.prefix

    full = core.STANDALONE_OBJECTS
    try:
        core.STANDALONE_OBJECTS = full[:2]
        narrowed = {obj.key for obj in core.standalone_objects()}
        assert narrowed == {full[0].key, full[1].key}
        assert len(narrowed) < len(full), "предохранитель: реестр не сузился"
    finally:
        core.STANDALONE_OBJECTS = full


def test_a_named_subset_stays_a_subset() -> None:
    """Потребитель называет СВОЙ набор — у книги v2 ФОКа нет статьёй вовсе."""
    named = core.standalone_objects(("offices", "standalone_retail"))
    assert [obj.key for obj in named] == ["standalone_retail", "offices"], (
        "порядок берётся у реестра — он экранный, а не порядок аргументов")
