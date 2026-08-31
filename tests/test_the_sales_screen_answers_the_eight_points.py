"""Восемь пунктов владельца по своду продаж (26.08.2026).

Список пришёл целиком и по номерам, поэтому и проверка по номерам: правка,
молча снявшая один из них, иначе выглядела бы как обычная перестановка.

  1. В плашках нет процента от общего объёма метров, квартир, машиномест и
     ожидаемой выручки.
  2. Один график с переключателем — в метрах, лотах, со средней ценой.
  3. Таблицу динамики убрать или свернуть.
  4. Каналы: свернуть список брокеров, показывать «свой отдел» и «брокеры».
  5. Размерность квартир = лоты; поднять к продажам; каналы — в конец;
     добавить вымывание и идеальный пул по квартирографии.
  6. Факт против ФМ и плана банка — на одном наглядном графике.
  7. Нет выводов под блоками.
  8. Наверху нет навигации по блокам.

И поверх списка: «дублировать таблицы нет смысла, они и так у управленцев
есть, им нужна наглядность и возможность сравнивать».
"""
from __future__ import annotations

from pathlib import Path

CABINET = Path(__file__).resolve().parent.parent / "market_search" / "cabinet.py"
CONTRACTING = Path(__file__).resolve().parent.parent / "market_search" / "contracting.py"


def page() -> str:
    from market_search.cabinet import cabinet_page
    return cabinet_page()


def _render() -> str:
    """Кусок страницы, отвечающий за свод продаж."""
    text = CABINET.read_text()
    return text[text.index("const SALES_METRICS="):text.index("\nfunction tile(")]


def test_1_the_tiles_name_the_share_of_the_project() -> None:
    body = _render()
    for tile in ("'Квартиры'", "'Метры квартир'", "'Машино-места'", "'Выручка'"):
        assert tile in body, f"плашки {tile} нет"
    for ready in ("units_share", "area_share", "amount_share"):
        assert ready in body, f"доля {ready} не показана"
    # Доля считается там же, где деньги: посчитанная на экране, она была бы
    # вторым счётом той же величины.
    assert "def pool_progress(" in CONTRACTING.read_text()


def test_2_one_chart_switches_between_metres_lots_and_price() -> None:
    body = _render()
    assert "const SALES_METRICS=" in body
    for name in ("'млн ₽'", "'м²'", "'лоты'", "'₽/м²'"):
        assert name in body, f"меры {name} у переключателя нет"
    assert "salesMetricButtons(" in body
    # Четыре графика подряд читаются как четыре разных предмета.
    assert body.count("function salesChartBlock(") == 1


def test_3_the_dynamics_table_is_folded() -> None:
    body = _render()
    start = body.index("function salesChartBlock(")
    block = body[start:body.index("\n// ", start + 10)]
    assert "<details" in block and "Помесячно числами" in block


def test_4_the_broker_list_is_folded_behind_the_two_sides() -> None:
    body = _render()
    start = body.index("function salesChannelsBlock(")
    block = body[start:body.index("\n// ", start + 10)]
    # Сперва две стороны, список — под раскрытием.
    assert block.index("salesOwnVsBrokers(") < block.index("<details")
    assert "Список каналов числами" in block


def test_5_the_mix_is_lots_with_the_pool_and_the_leftover() -> None:
    body = _render()
    assert "function salesMixBlock(" in body
    for strip in ("'Пул проекта'", "'Продано'", "'Осталось показывать'"):
        assert strip in body, f"полосы {strip} нет"
    assert "b.left_share" in body, "остаток витрины не показан"
    # Без квартирографии книги пул неизвестен, но размерность известна всегда.
    assert "function salesSizesOnly(" in body
    # Каналы — в конец: после квартирографии, продуктов, оплаты и планов.
    order = [body.index(f"'{block}'") for block in ("sb-mix", "sb-prod", "sb-pay", "sb-plan", "sb-ch")]
    assert order == sorted(order), "порядок блоков не тот, что просили"


def _function(name: str) -> str:
    """Исходник функции страницы — по её объявлению, а не по соседней строке.

    Кусок резался «от `function salesPlansBlock(` до следующего комментария»,
    и разделение функции надвое (рисование меры вынесено, чтобы печатные виды
    звали тот же код) уронило проверку, ничего не сказав про поведение: оба
    плана как делили один график, так и делят. Функция — контракт, границу
    считаем скобками.
    """
    text = CABINET.read_text()
    start = text.index(f"function {name}(")
    depth, index = 0, text.index("{", start)
    while index < len(text):
        if text[index] == "{":
            depth += 1
        elif text[index] == "}":
            depth -= 1
            if depth == 0:
                return text[start:index + 1]
        index += 1
    raise AssertionError(f"функция {name} не закрыта")


def test_6_both_plans_share_one_chart() -> None:
    chart = _function("salesPlansChart")
    assert "'план ФМ'" in chart and "'план банка'" in chart
    assert chart.count("barChart(") == 1, "планов два, а график один"
    # Цена всех троих — на том же графике линиями, а не отдельной вкладкой.
    assert "'цена факт'" in chart and "'цена ФМ'" in chart and "'цена банка'" in chart

    block = _function("salesPlansBlock")
    assert "salesPlansChart(" in block, "блок рисует планы не общим кодом"
    # Сравниваются одинаковые величины: сумма договоров с валовыми продажами
    # банка, а не со строкой «с учётом рассрочки» — та про деньги на эскроу.
    assert "валовые продажи" in block


def test_7_every_block_says_what_it_means() -> None:
    body = _render()
    assert "function salesNote(" in body
    for key in ("'pool'", "'dynamics'", "'bands'", "'products'", "'payment'",
                "'channels'", "'fm'", "'bank'"):
        assert f"salesNote(d,{key})" in body, f"вывода под блоком {key} нет"
    # Фразы считает сервер, а не экран.
    assert "def conclusions(" in CONTRACTING.read_text()


def test_8_the_blocks_have_a_menu_on_top() -> None:
    body = _render()
    assert "const SALES_BLOCKS=" in body and "function salesNav(" in body
    assert ".salesnav{" in page(), "у навигации нет своего вида"
    # Пункт показывается, только если блок есть: ссылка в пустоту хуже её
    # отсутствия.
    assert "SALES_BLOCKS.filter(b=>have.includes(b.id))" in body


def test_the_tables_do_not_repeat_what_the_picture_says() -> None:
    """У управленцев таблицы и так есть — им нужна наглядность."""
    body = _render()
    # Каждая таблица свода стоит под раскрытием, кроме расторжений: там
    # таблица и есть содержание, картинки из двух строк не выйдет.
    for summary in ("Помесячно числами", "Полосы числами", "Продукты числами",
                    "Условия числами", "Список каналов числами"):
        assert f"<summary>{summary}</summary>" in body, f"«{summary}» не свёрнуто"


def test_every_block_with_a_picture_also_has_its_numbers() -> None:
    """Числа, живущие только внутри картинки, не переносятся никуда.

    У блока «Факт против планов» раскладки числами не было вовсе: в PDF её не
    выделить, а в презентации от раздела оставались одни слова — картинка
    туда не едет по решению владельца («картинка никому не уперлась»).
    У остальных блоков такая раскладка есть с самого начала.
    """
    body = page()
    for fold in ("Помесячно числами", "Полосы числами", "Продукты числами",
                 "Условия числами", "Список каналов числами", "Кварталы числами"):
        assert fold in body, f"у блока нет раскладки «{fold}»"
