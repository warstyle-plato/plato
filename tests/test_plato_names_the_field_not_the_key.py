"""Платон говорит человеку вкладку и подпись поля, а не ключ.

Повод — экран владельца 14.09.2026. На вопрос «благоустройство считается
некорректно, как исправить настройки? я знаю площадь двора и цену её метра»
Платон ответил так: «ставку ставьте в landscaping_th_per_sqm, площадь приведите
к landscaping_area_per_person_sqm = ваша площадь / расчётное население,
править — в Экономика → Вводные». Неверно здесь всё три раза:

- ключ поля — не его имя: на экране это «Благоустройство» и «Благоустройство —
  норматив площади на человека»;
- норматив во «Вводных» не живёт вовсе (`CLASS_ONLY_INPUTS`), он правится в
  окне «Настройки классов» — то есть человека послали туда, где поля нет;
- у него на руках была ПЛОЩАДЬ двора, под которую поле есть
  («Благоустройство — площадь территории»), и делить её на население руками не
  надо: движок приводит заданную площадь к своей мере сам, и заданная сильнее
  норматива класса.

Здесь закреплено: ответ «где это править» считается движком из `FIELD_GROUPS`
(того же списка, что рисует форму), инструмент отдаёт его Платону, а инструкция
запрещает называть ключи человеку.

Запуск: python3 -m pytest tests/test_plato_names_the_field_not_the_key.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import main as wrapper  # noqa: E402

core = wrapper.core


def test_a_field_place_names_the_tab_the_group_and_the_label():
    place = core.input_field_place("landscaping_th_per_sqm")
    assert place is not None
    assert place["label"] == "Благоустройство"
    assert place["where"] == "Вводные"
    assert place["group"] == "Строительство"
    # Путь — то, что человек читает: вкладка, группа, подпись. Ключа в нём нет.
    assert "landscaping" not in place["path"]
    assert place["unit"].startswith("тыс. ₽/м²")


def test_the_class_only_field_is_not_sent_to_the_inputs_tab():
    """Норматив правится в «Настройках классов», и место обязано это сказать."""
    field = core.CLASS_ONLY_INPUTS[0]
    place = core.input_field_place(field)
    assert place["where"] == core.CLASS_DIALOG_NAME
    assert "Вводные" not in place["path"]
    # Предохранитель: поле действительно скрыто из формы, иначе проверка
    # утверждала бы про экран то, чего на нём нет.
    assert field in core.CLASS_ONLY_INPUTS


def test_the_vri_group_goes_to_its_own_tab():
    place = core.input_field_place("vri_relief_pct")
    assert place["where"] == "ВРИ"
    assert place["group"] == core.VRI_GROUP_NAME


def test_the_vri_group_name_is_declared_once():
    """Имя группы ВРИ подставляется на страницу, а не написано на ней второй раз.

    Разойдись копии — поле ВРИ ушло бы рисоваться во «Вводные», а Платон
    продолжал бы звать на вкладку ВРИ, и обе поверхности выглядели бы верными.
    """
    page = core.PAGE
    assert core.VRI_GROUP_NAME_PLACEHOLDER not in page
    assert page.count(f'const VRI_GROUP_NAME="{core.VRI_GROUP_NAME}"') == 1


def test_the_tool_finds_the_field_by_russian_words():
    """Человек называет величину словами — «благоустройство», а не ключом."""
    answer = core._tool_where_to_edit("благоустройство")
    assert answer["available"] is True
    fields = {item["field"]: item for item in answer["fields"]}
    assert "landscaping_area_sqm" in fields, "поле площади двора должно находиться"
    assert "landscaping_th_per_sqm" in fields
    # Норматив тоже находится — но с другим местом правки.
    assert fields["landscaping_area_per_person_sqm"]["where"] == core.CLASS_DIALOG_NAME


def test_an_unknown_field_is_refused_by_name():
    """Ненайденное — отказ с причиной, а не выдуманная подпись."""
    answer = core._tool_where_to_edit("квантовый резерв")
    assert answer["available"] is False
    assert "квантовый резерв" in answer["reason"]


def test_the_instructions_forbid_raw_keys_in_the_answer():
    text = core._AGENT_INSTRUCTIONS
    assert "where_to_edit" in text
    assert "а не ключ" in text
    # И запрещают перекладывать перевод в чужую меру на человека, и называют
    # окно, где человек вводит свои данные по классу.
    assert "перевод в чужую меру — работа модели, а не человека" in text
    assert core.CLASS_DIALOG_NAME in text


def test_the_patch_takes_the_landscaping_a_person_actually_has():
    """Площадь двора и цена её метра — то, с чем человек приходит.

    Пока их не было среди переменных патча, Платон не мог подготовить кнопку
    «Применить в модель» и посылал считать руками.
    """
    assert "landscaping_area_sqm" in core._PATCH_VARIABLES
    assert "landscaping_th_per_sqm" in core._PATCH_VARIABLES
    # Подпись патча — та же, что на экране, иначе человек ищет несуществующее.
    assert core._PATCH_VARIABLES["landscaping_area_sqm"].startswith(
        core.input_field_place("landscaping_area_sqm")["label"])


def test_every_patch_variable_exists_on_the_screen():
    """Патч правит поле, которое человек видит, — иначе он правит вслепую.

    Исключение одно и названо: `main_construction_cost_th_per_sqm` —
    составная переменная подбора (наземная + подземная части), своего поля у
    неё нет по построению, и `_apply_variable` раскладывает её на два.
    """
    composite = {"main_construction_cost_th_per_sqm"}
    missing = [key for key in core._PATCH_VARIABLES
               if key not in composite and core.input_field_place(key) is None]
    assert missing == [], f"патч правит поля, которых нет на экране: {missing}"


def test_the_patch_schema_is_built_from_the_same_list():
    """Список переменных патча был третьей копией и отстал на пять полей.

    `_tool_prepare_model_patch` умеет льготу и рассрочку ВРИ, а enum схемы их
    не принимал — то есть инструкция звала к рычагу, которого инструмент не
    брал. Теперь enum считается из того же списка, что патч применяет.
    """
    schema = next(item for item in core._AGENT_TOOLS
                  if item.get("name") == "prepare_model_patch")
    enum = schema["parameters"]["properties"]["changes"]["items"]["properties"]["variable"]["enum"]
    assert set(enum) == set(core._PATCH_VARIABLES)
    assert "vri_relief_pct" in enum


def test_a_class_field_names_both_of_its_homes():
    """У ставки класса два дома, и они означают разное.

    «Надо заходить в настройки класса и там вводить свои данные, и алгоритм сам
    переведёт их в формат руб на ГНС» (владелец, 14.09.2026) — а Платон отвечал
    «отдельные поля благоустройства правятся вручную во Вводных», то есть знал
    один дом из двух. Правка в окне классов — свойство класса и применится ко
    всем проектам этого класса; правка во «Вводных» — число этого проекта.
    Назвать одно и умолчать о втором значит отправить человека менять больше
    или меньше, чем он хотел.
    """
    place = core.input_field_place("landscaping_th_per_sqm")
    assert core.CLASS_DIALOG_NAME in place["also"]
    assert "ко всем проектам этого класса" in place["also_note"]
    # Предохранитель: поле действительно в профиле класса — иначе проверка
    # утверждала бы про окно классов то, чего в нём нет.
    assert "landscaping_th_per_sqm" in core.PROJECT_CLASS_PRESETS["comfort"]
    # А поле площадки второго дома не имеет: площадь двора — свойство участка,
    # а не класса, и в окне классов её вбить некуда.
    assert "also" not in core.input_field_place("landscaping_area_sqm")


def test_the_instructions_do_not_send_a_class_field_to_the_inputs_only():
    text = core._AGENT_INSTRUCTIONS
    assert "Настройки классов" in text
    assert "Называй оба места" in text
    # Все три величины благоустройства названы своими подписями: человеку нужна
    # та, что у него на руках.
    for key in ("landscaping_th_per_sqm", "landscaping_area_per_person_sqm",
                "landscaping_area_sqm"):
        assert core.input_field_place(key)["label"] in text, key


class _Req:
    """Запрос агента в том виде, в каком его видит инструмент."""

    def __init__(self, apartments_sqm: float, region: str = "msk"):
        self.tep = {"apartments": {"saleable": apartments_sqm}}
        self.inputs = {"vri_region": region}


def test_the_reverse_count_is_done_by_the_engine_not_by_the_person():
    """«Поделите на расчётное население» — задание человеку, а не ответ.

    В «Настройках классов» поля площади нет вовсе, там только норматив на
    человека: обратный счёт там единственный путь (владелец, 14.09.2026).
    Значит население обязан дать движок, а не языковая модель на глаз.
    """
    answer = core._tool_where_to_edit("благоустройство", _Req(12_571.7))
    # 12 571,7 м² квартир ÷ 33 м² на человека = 381 (приложение 5 к 945-ПП).
    assert answer["population"] == 381
    assert "945-ПП" in answer["population_basis"]
    assert "381" in answer["per_person_conversion"]
    assert "делить его не проси" in answer["per_person_conversion"]


def test_the_dispatcher_hands_the_project_to_the_tool():
    """Платон ходит через диспетчер, и проект до инструмента обязан доезжать.

    Проверка звала инструмент напрямую и была зелёной, когда `req` из вызова
    убрали: обратный счёт молча пропадал, а Платон возвращался к «поделите
    сами». Проверять надо ту дверь, в которую ходят.
    """
    answer = core._execute_agent_tool(
        "where_to_edit", {"query": "благоустройство"}, _Req(12_571.7), {})
    assert answer["population"] == 381


def test_an_unmeasurable_population_is_named_not_guessed():
    """Квартир в ТЭП нет — пересчитать не на что, и это говорится вслух."""
    answer = core._tool_where_to_edit("благоустройство", _Req(0))
    assert "population" not in answer
    assert "пересчитать" in answer["per_person_conversion"]


def test_the_conversion_is_offered_only_where_the_measure_is_per_person():
    """Ставка за метр двора в пересчёте не нуждается — она уже в мере человека."""
    answer = core._tool_where_to_edit("резерв", _Req(12_571.7))
    assert "per_person_conversion" not in answer


def test_the_per_gns_rate_is_a_check_not_an_input():
    """«Площадь × цена ÷ ГНС» — сверка со сметой, а не число для поля.

    Статья считается от площади двора (ставка × площадь), а «на метр ГНС»
    движок отдаёт производной. Вписанная в поле ставки, она уронила бы статью
    в разы: поле умножается на площадь двора, а не на строительный объём.
    """
    text = core._AGENT_INSTRUCTIONS
    assert "landscaping_per_gns_th" in text
    assert "ПРОВЕРКА, а не ввод" in text
    # Поле само называет свою базу — подсказка и инструкция говорят одно.
    assert "а не строительного объёма" in core.input_field_place(
        "landscaping_th_per_sqm")["hint"]
