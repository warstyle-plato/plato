"""Проектный подземный паркинг идёт за ТЭП, пока его не тронули руками.

«Когда я поменял ТЭПы после расчёта, то машиноместа не будут двигаться? Это
неверно» (владелец, 13.09.2026). Измерено на живой странице до правки: первый
визит — пара «места ↔ площадь» пуста, строка ТЭП идёт за нормой (1199 мест);
возврат в тот же браузер — `fillUndergroundFromTep` при загрузке сохранённого
проекта заполняет пару её же числом, и дальше строка замирает: удвоение
площади квартир поднимает норму до 2397, а в строке остаётся 1199 / 41 965 м².

Замирала она не молча — `undergroundShortfallNote` печатал «не хватает 1198», —
но число выдавалось за решение человека: строка подписывалась «Задано
проектом», а вернуть поле к норме можно было только вписав норму руками, и
тогда оно запиралось снова.

Пометка — та же, что у паркинга объектов (`_parking_by_norm` / `_parking_by_hand`,
09.09.2026), и списки те же: у одного вопроса «чьё это число» один ответ.
Проектный подземный в них не попадал потому, что посев выводил имя поля из
приставки объекта, а у него имена другие.

Проверяется браузером на настоящем адресе: в исходнике замершее поле выглядит
так же, как идущее за нормой. Рядом стоит предохранитель — при снятой пометке
строка ОБЯЗАНА замереть, иначе проверка зелена на любом коде.

Запуск: python3 -m pytest tests/test_the_underground_parking_follows_the_tep.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import browser  # noqa: E402
import main_legacy as core  # noqa: E402

SAVE = "()=>{persistLocalSilently();return inputs.underground_manual_spaces}"

# Человек правит поле руками — через его собственный обработчик, а не
# присваиванием: состояние задают тем писателем, которым его задаёт страница.
TYPE = """(value)=>{
  const el=document.getElementById('f_underground_manual_spaces');
  el.value=value;
  el.dispatchEvent(new Event('change'));
}"""

READ = """()=>({
  flats: tep.apartments.saleable,
  row: tep.underground_parking.units,
  gns: Math.round(tep.underground_parking.gns),
  manual: Number(inputs.underground_manual_spaces||0),
  norm: (parkingRequirement()||{}).spaces||0,
  byHand: parkingByHand(PROJECT_PARKING_KEY),
  byNorm: parkingByNorm(PROJECT_PARKING_KEY),
})"""

DOUBLE = """()=>{
  tepCellChanged('apartments','saleable', String(tep.apartments.saleable*2));
  syncTep(false);
}"""

# Как было до правки: пометки нет, и пара замирает на своём числе.
FREEZE = """()=>{
  inputs._parking_by_norm=(inputs._parking_by_norm||[]).filter(x=>x!==PROJECT_PARKING_KEY);
  markParkingByHand(PROJECT_PARKING_KEY);
}"""


@pytest.fixture(scope="module")
def seen():
    """Сценарий возвращения: проект уже сохранён в этом браузере."""
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright

    path = browser.chromium_or_skip()
    out: dict[str, dict] = {}
    with browser.serve(core.app, 18153) as base, sync_playwright() as pw:
        with pw.chromium.launch(executable_path=str(path)) as engine:
            ctx = engine.new_context(viewport={"width": 1440, "height": 900})
            page = ctx.new_page()
            page.goto(base, wait_until="domcontentloaded")
            page.wait_for_timeout(2000)
            page.evaluate(SAVE)
            page.reload(wait_until="domcontentloaded")
            page.wait_for_timeout(2000)

            out["opened"] = page.evaluate(READ)
            page.evaluate(DOUBLE)
            out["doubled"] = page.evaluate(READ)
            page.evaluate(TYPE, "700")
            # Обработчик поля зовёт `calculate()`; он асинхронный и на лету
            # переписывает `tep` ответом сервера. Не дождавшись, стенд мерил бы
            # состояние посреди пересчёта — и правка ТЭП следом не применялась.
            page.wait_for_timeout(1500)
            out["typed"] = page.evaluate(READ)
            page.evaluate(DOUBLE)
            out["hand_holds"] = page.evaluate(READ)
            page.evaluate(TYPE, "")
            page.wait_for_timeout(1500)
            out["restored"] = page.evaluate(READ)
            # Предохранитель: снимаем пометку и повторяем правку ТЭП.
            page.evaluate(FREEZE)
            frozen_before = page.evaluate(READ)
            page.evaluate(DOUBLE)
            out["frozen_before"] = frozen_before
            out["frozen_after"] = page.evaluate(READ)
            ctx.close()
    return out


def test_the_saved_project_opens_with_the_norm_stamp(seen):
    """Пару заполнила норма — значит число ЕЁ, и пометка это говорит."""
    got = seen["opened"]
    assert got["manual"] > 0, "пара пуста — сценарий возвращения не воспроизвёлся"
    assert got["byNorm"] and not got["byHand"], (
        "число нормы приехало непомеченным — на следующей правке ТЭП оно замрёт "
        "и будет выглядеть решением человека")
    assert got["manual"] == got["norm"], \
        f"в поле {got['manual']}, норма {got['norm']} — пара не равна норме"


def test_a_tep_edit_moves_the_parking(seen):
    """То, ради чего всё: правка ТЭП двигает места и метры."""
    was, now = seen["opened"], seen["doubled"]
    assert now["norm"] > was["norm"], (
        "норма не изменилась — проверка не проверяет ничего: "
        f"{was['norm']} → {now['norm']}")
    assert now["row"] == now["norm"], (
        f"строка ТЭП {now['row']} м/м при норме {now['norm']} — паркинг замер")
    assert now["gns"] > was["gns"], "подземная площадь за местами не пошла"


def test_a_typed_number_locks_the_pair(seen):
    """Вписанное руками сильнее нормы и переживает правку ТЭП."""
    typed, held = seen["typed"], seen["hand_holds"]
    assert typed["byHand"] and not typed["byNorm"], \
        "вписанное руками не помечено — норма затрёт его на следующем пересчёте"
    assert typed["row"] == 700, f"строка ТЭП {typed['row']} — вписанное число не доехало"
    assert held["flats"] > typed["flats"], "ТЭП не менялся — замок не проверен"
    assert held["row"] == 700, \
        f"после правки ТЭП строка стала {held['row']} — руки перебиты нормой"


def test_clearing_the_field_returns_to_the_norm(seen):
    """У всякого замка спрашивают, чем его открыть."""
    got = seen["restored"]
    assert got["byNorm"] and not got["byHand"], "очистка поля замок не сняла"
    assert got["row"] == got["norm"], (
        f"строка {got['row']} при норме {got['norm']} — к нормативу не вернулись")


def test_without_the_stamp_the_parking_freezes(seen):
    """Предохранитель: без пометки строка ОБЯЗАНА замереть — как было до правки."""
    was, now = seen["frozen_before"], seen["frozen_after"]
    assert now["flats"] > was["flats"], "ТЭП не менялся — предохранитель ничего не ловит"
    assert now["row"] == was["row"], (
        "без пометки паркинг всё равно пошёл за ТЭП — значит меряем не пометку: "
        f"{was['row']} → {now['row']}")


def test_the_row_says_whose_number_it_is():
    """«Задано проектом» под числом нормы — утверждение о человеке, а не о норме."""
    page = core.PAGE
    assert "'Решение проекта':'По нормативу'" in page, \
        "подпись строки ТЭП не различает число нормы и вписанное руками"
    assert "Задано проектом:" not in page, \
        "прежняя подпись осталась — она называет решением человека число нормы"
