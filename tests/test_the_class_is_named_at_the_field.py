"""Поле, значение которого ставит класс, говорит об этом само.

Три жалобы одного экрана (владелец, 15.09.2026):

    я не вижу ничего про площадь машиноместа установлена по классу
    не вижу изменений в благоустройстве где во вводных оставались стоимость
    на гнс, а не расчет, который мы оставили в настройках классов

Обе про одно: профиль класса задаёт одиннадцать вводных — цены, ставки
себестоимости, метры на машино-место, метры двора на человека, площадь
кладовой, — и на экране они неотличимы от набранных руками. А у
благоустройства методика переехала в «Настройки класса» ОБЕИМИ половинами
(норматив 11/15/20 м²/чел. и ставка 15/35/50 тыс ₽/м² двора), и во «Вводных»
должен стоять счётный показатель ₽ на метр дома — «посчитанный из данных
настроек, с пометкой, что можно ввести вручную или поменять в настройках»
(владелец, 14.09.2026).

Проверять это можно только браузером: в исходнике сломанная и починенная
страница выглядят одинаково — пометка собирается при отрисовке, а значение
поля пишет `renderLandscapingRateNote`.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import main_legacy as core  # noqa: E402

PORT = 18921


@pytest.fixture(scope="module")
def page_state():
    """Один подъём страницы на весь файл: браузер дорог, а вопросы к одной форме."""
    import browser as browser_helper

    chrome = browser_helper.chromium_or_skip()
    from playwright.sync_api import sync_playwright

    import main as _wrapper

    read_units = r"""() => [...document.querySelectorAll('#inputs .field')].map(one => ({
      id: (one.querySelector('input,select') || {}).id || '',
      unit: (one.querySelector('.unit') || {}).textContent || '',
    })).filter(one => one.id.startsWith('f_'))"""

    with browser_helper.serve(_wrapper.app, PORT) as root:
        with sync_playwright() as pw:
            chromium = pw.chromium.launch(executable_path=str(chrome))
            page = chromium.new_page()
            errors: list[str] = []
            page.on("pageerror", lambda exc: errors.append(str(exc)))
            page.goto(root, wait_until="networkidle")
            # Расчёт нужен: счётный показатель считает движок, а не страница.
            page.evaluate("calculate()")
            page.wait_for_function(
                "() => lastResult && lastResult.summary "
                "&& lastResult.summary.landscaping_per_gns_th > 0",
                timeout=60000)
            state = {
                "errors": errors,
                "units": page.evaluate(read_units),
                # Имена нарисованных групп: складка без единого своего поля
                # видна только здесь — в исходнике она объявлена как все.
                "groups": page.evaluate(
                    "[...document.querySelectorAll('details[data-group]')]"
                    ".map(one => one.dataset.group)"),
                "rate_note": page.evaluate(
                    "(document.getElementById('landscapingRateNote')||{}).textContent||''"),
                "house_note": page.evaluate(
                    "(document.getElementById('landscapingHouseRateNote')||{}).textContent||''"),
                "shown": page.evaluate(
                    "(document.getElementById('f_landscaping_gns_th_per_sqm')||{}).value"),
                "kept": page.evaluate("Number(inputs.landscaping_gns_th_per_sqm||0)"),
                "computed": page.evaluate("lastResult.summary.landscaping_per_gns_th"),
            }
            # Вписанное руками методику перебивает и в поле остаётся своим.
            page.evaluate("window.__prev=lastResult")
            page.evaluate(
                "()=>{const el=document.getElementById('f_landscaping_gns_th_per_sqm');"
                "el.value='4';el.onchange();}")
            # Ждём НОВЫЙ результат — то единственное, что не зависит от
            # проверяемого. Ожидание самого значения или подписи превратило бы
            # находку в таймаут фикстуры: падение вышло бы про неё, а не про то,
            # что сломалось.
            page.wait_for_function(
                "() => lastResult && lastResult !== window.__prev", timeout=60000)
            state["by_hand"] = page.evaluate(
                "document.getElementById('f_landscaping_gns_th_per_sqm').value")
            state["by_hand_note"] = page.evaluate(
                "(document.getElementById('landscapingHouseRateNote')||{}).textContent||''")
            # Очищенное поле возвращает методику — и её показатель.
            page.evaluate("window.__prev=lastResult")
            page.evaluate(
                "()=>{const el=document.getElementById('f_landscaping_gns_th_per_sqm');"
                "el.value='';el.onchange();}")
            page.wait_for_function(
                "() => lastResult && lastResult !== window.__prev", timeout=60000)
            state["cleared"] = page.evaluate(
                "document.getElementById('f_landscaping_gns_th_per_sqm').value")
            # Смена класса двигает обе половины методики — а с ними показатель.
            page.evaluate("window.__prev=lastResult")
            page.evaluate("()=>{applyProjectClassPreset('elite');renderInputs();calculate();}")
            # В ожидании стоит только свежесть результата: добавь сюда «а ставка
            # стала больше» — и замершее поле давало бы таймаут фикстуры вместо
            # названной разницы. Мерят утверждения, а не ожидание.
            page.wait_for_function(
                "() => lastResult && lastResult !== window.__prev", timeout=60000)
            state["elite"] = page.evaluate(
                "document.getElementById('f_landscaping_gns_th_per_sqm').value")
            state["elite_kept"] = page.evaluate(
                "Number(inputs.landscaping_gns_th_per_sqm||0)")
            state["elite_computed"] = page.evaluate(
                "lastResult.summary.landscaping_per_gns_th")
            chromium.close()
    return state


def test_the_page_draws_without_errors(page_state):
    assert not page_state["errors"], page_state["errors"]


def test_every_class_field_says_so_and_only_it(page_state):
    """Пометка — у полей профиля класса, и ни у одного чужого.

    Список берётся из САМОГО профиля: перечисленный рядом, он отстал бы на
    следующем поле — так «Площадь одной кладовой» и «Норматив площади на
    машино-место» и въехали в профиль, ничего о том не сказав.
    """
    profile = {key for key in core.PROJECT_CLASS_PRESETS["comfort"] if key != "label"}
    drawn = {one["id"][2:]: one["unit"] for one in page_state["units"]}
    assert drawn, "форма не отрисовалась"
    marked = {key for key, unit in drawn.items() if "ставит класс проекта" in unit}
    # Поля профиля, которые форма вообще рисует: `CLASS_ONLY_INPUTS` скрыты, и
    # спрашивать с них пометку не с чего.
    expected = {key for key in profile
                if key in drawn and key not in core.CLASS_ONLY_INPUTS}
    assert expected, "ни одного поля профиля на форме — мерить нечего"
    assert marked == expected, {"без пометки": sorted(expected - marked),
                                "лишняя пометка": sorted(marked - expected)}
    # Та самая жалоба: площадь машино-места.
    assert "underground_area_per_space_sqm" in marked
    # И контроль в другую сторону: цена входа классу не принадлежит.
    assert "ставит класс проекта" not in drawn.get("purchase_price_mln", "")


def test_the_mark_says_where_the_value_is_changed(page_state):
    """Пометка отвечает и на «а где тогда»: гашение без этого — половина ответа."""
    drawn = {one["id"][2:]: one["unit"] for one in page_state["units"]}
    assert "Настройках класса" in drawn["underground_area_per_space_sqm"]


def test_both_halves_of_the_yard_method_live_in_the_class(page_state):
    """Ставка метра двора ушла к своему нормативу, и во «Вводных» её нет."""
    assert "landscaping_th_per_sqm" in core.CLASS_ONLY_INPUTS
    assert "landscaping_area_per_person_sqm" in core.CLASS_ONLY_INPUTS
    drawn = {one["id"][2:] for one in page_state["units"]}
    assert "landscaping_th_per_sqm" not in drawn
    assert "landscaping_area_per_person_sqm" not in drawn
    # Скрытое поле обязано иметь второй дом: подпись и единицу окно классов
    # берёт из `FIELD_GROUPS`, а значение — из профиля.
    for key in core.CLASS_ONLY_INPUTS:
        assert key in core.PROJECT_CLASS_PRESETS["comfort"], key
        assert core.class_field_unit(key), key


def test_the_yard_line_moved_with_its_field(page_state):
    """Подпись, привязанная к полю, переезжает вместе с ним.

    Строка про двор висела на ставке метра двора. Ставка ушла в «Настройки
    класса» — и подпись не нарисовалась бы ВОВСЕ, молча: в исходнике она на
    месте. Новый дом — площадь двора, единственное поле двора во «Вводных».
    """
    assert "Двор" in page_state["rate_note"], page_state["rate_note"]
    assert "м²" in page_state["rate_note"]


def test_the_field_shows_the_figure_the_settings_produce(page_state):
    """Во «Вводных» стоит счётный показатель, а не ноль.

    Ноль читается как «ноль рублей» там, где стоит статья на 400 млн.
    """
    shown = float(str(page_state["shown"]).replace(",", "."))
    assert shown > 0, page_state["shown"]
    assert abs(shown - round(page_state["computed"], 2)) < 0.005, page_state
    # Вводная при этом остаётся нулём: ноль здесь значит «считает методика».
    # Записанное в состояние число заменило бы методику снимком — смена класса
    # его больше не двигала бы, и поле замерло бы, как замирал паркинг.
    assert page_state["kept"] == 0, page_state["kept"]
    assert "методика класса" in page_state["house_note"], page_state["house_note"]
    # Само число подпись не повторяет: оно стоит в поле строкой выше.
    shown_text = str(page_state["shown"]).replace(".", ",")
    assert shown_text not in page_state["house_note"], page_state["house_note"]


def test_a_hand_written_rate_wins_and_an_empty_field_gives_it_back(page_state):
    """«Можно ввести вручную или поменять в настройках» — обе половины."""
    assert page_state["by_hand"] == "4", page_state["by_hand"]
    assert "руками" in page_state["by_hand_note"], page_state["by_hand_note"]
    back = float(str(page_state["cleared"]).replace(",", "."))
    assert abs(back - round(page_state["computed"], 2)) < 0.005, page_state


def test_the_hint_names_the_base_and_the_note_names_the_state(page_state):
    """Подсказка говорит БАЗУ, подпись — чьё это число: каждое сказано один раз.

    Прежде обе говорили и то и другое — 333 знака подсказки и 218 подписи, — и
    одно и то же дважды подряд перестают читать оба раза («текста
    пояснительного слишком много», владелец, 16.09.2026).
    """
    hints = {field[0]: field[2] for group in core.FIELD_GROUPS for field in group[1]}
    hint = hints["landscaping_gns_th_per_sqm"]
    assert "ГНС" in hint, hint
    # Инструкции в подсказке больше нет — она у подписи, у которой есть состояние.
    assert "перебьёт" not in hint, hint
    assert "очистите" not in hint.lower(), hint
    # Прежняя подсказка обещала пустое поле — а в поле теперь стоит число.
    assert "Пусто — считается методикой" not in hint, hint
    note = page_state["house_note"]
    assert "перебьёт" in note and "Настройках класса" in note, note
    assert "наземной части дома" not in note, note


def test_the_figure_follows_the_class_and_does_not_freeze(page_state):
    """«Поменять в настройках» — и показатель идёт за настройками.

    Это и есть цена того, что вводная остаётся нулём. Запиши страница
    посчитанное число в состояние — оно уехало бы в сбор формы (`calculate`
    забирает её целиком), класс сменили бы, а ставка осталась бы прежней:
    ровно так замирал паркинг, пока норма не начала помечать своё.
    """
    comfort = float(str(page_state["shown"]).replace(",", "."))
    elite = float(str(page_state["elite"]).replace(",", "."))
    assert elite > comfort * 2, {"комфорт": comfort, "элит": elite}
    assert abs(elite - round(page_state["elite_computed"], 2)) < 0.005, page_state
    assert page_state["elite_kept"] == 0, page_state["elite_kept"]


def test_the_storage_area_lives_only_in_the_class(page_state):
    """Площадь кладовой правится в «Настройках класса», и во «Вводных» её нет.

    Владелец, 16.09.2026: «этот блок тут не нужен, если он есть в настройках
    класса». Поле было единственным в группе «Кладовые» и повторяло строку
    окна классов слово в слово.
    """
    assert "storage_area_per_unit_sqm" in core.CLASS_ONLY_INPUTS
    drawn = {one["id"][2:] for one in page_state["units"]}
    assert drawn, "форма не отрисовалась"
    assert "storage_area_per_unit_sqm" not in drawn
    # Второй дом у поля есть — иначе это вводная, которую негде править.
    assert "storage_area_per_unit_sqm" in core.PROJECT_CLASS_PRESETS["comfort"]
    assert core.class_field_unit("storage_area_per_unit_sqm")


def test_a_group_without_its_own_fields_is_not_drawn(page_state):
    """Складка, у которой все поля уехали в класс, не рисуется вовсе.

    Пустая «Кладовые» читается как продукт, у которого вводных нет, а не как
    поле, переехавшее в соседнее окно. Утверждение мерится составом: на экране
    ровно те группы, у которых осталось хоть одно своё поле, — перечисление
    имён отстало бы на следующей такой группе.
    """
    drawn = set(page_state["groups"])
    assert drawn, "групп на экране нет — мерить нечего"
    expected = {title for title, fields in core.FIELD_GROUPS
                if any(one[0] not in core.CLASS_ONLY_INPUTS for one in fields)}
    hidden = {title for title, fields in core.FIELD_GROUPS
              if fields and not any(one[0] not in core.CLASS_ONLY_INPUTS
                                    for one in fields)}
    # Предохранитель: без такой группы проверка не значит ничего.
    assert hidden, "ни одной группы, целиком уехавшей в класс"
    assert drawn == expected, {"не нарисованы": sorted(expected - drawn),
                               "лишние": sorted(drawn - expected)}
    assert not (drawn & hidden), sorted(drawn & hidden)
