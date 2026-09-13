"""Группа вводных и строка ТЭП объекта приходят из его строки реестра.

Состав объектов объявлен один раз, а форма его до сих пор была выписана
руками: четыре группы по 17–20 полей и четыре строки ТЭП. Пока объектов
четыре, копия молчит — она заговорит в тот день, ради которого реестр и
заводился: объект завели, поле забыли, и на экране «объект есть, а считать
его нечем».

Литерал при этом остаётся, и это не полумера: он держит МЕСТО — порядок строк
ТЭП и порядок групп на экране, — потому что человек ждёт группу там, где она
стояла. Содержимое приносит реестр.

Запуск: python3 -m pytest tests/test_an_object_brings_its_own_form.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import main_legacy as core  # noqa: E402


def test_the_form_on_the_screen_is_the_one_the_roster_builds() -> None:
    """Каждая группа объекта в `FIELD_GROUPS` — ответ генератора."""
    by_label = {g[0]: g for g in core.FIELD_GROUPS}
    for obj in core.STANDALONE_OBJECTS:
        assert by_label[obj.group_label] == core.standalone_object_group(obj)


def test_the_tep_row_of_an_object_is_the_one_the_roster_builds() -> None:
    """Строка ТЭП объекта — тоже ответ генератора, вместе с именем."""
    for obj in core.STANDALONE_OBJECTS:
        assert core.TEP_DEFAULT[obj.key] == core.standalone_object_tep_row(obj)
        assert core.TEP_DEFAULT[obj.key]["label"] == obj.tep_label


def test_no_placeholder_survives_to_the_page() -> None:
    """Заглушка, дожившая до страницы, — это группа без полей.

    На экране она неотличима от объекта, у которого вводных нет вовсе.
    """
    mark = core._OBJECT_PLACEHOLDER
    assert not [g for g in core.FIELD_GROUPS if str(g[0]).startswith(mark)]
    assert not [k for k, v in core.TEP_DEFAULT.items()
                if isinstance(v, str) and v.startswith(mark)]


def test_an_object_dropped_from_the_roster_has_no_form_left_behind() -> None:
    """Диверсант: без строки реестра форму объекта собрать нечем.

    Ровно этим отличается порождение от совпадения с прежним литералом:
    останься форма в литерале — она пережила бы выброшенный объект.
    """
    literal_groups = [str(g[0]) for g in core._FIELD_GROUPS_LITERAL]
    assert core._OBJECT_PLACEHOLDER + "offices" in literal_groups
    # В литерале от объекта осталось ИМЯ МЕСТА и ничего больше: ни одного поля.
    place = next(g for g in core._FIELD_GROUPS_LITERAL
                 if str(g[0]) == core._OBJECT_PLACEHOLDER + "offices")
    assert place[1] == []
    assert core._TEP_DEFAULT_LITERAL["offices"] == core._OBJECT_PLACEHOLDER + "offices"


def test_the_group_stands_where_the_literal_put_it() -> None:
    """Порядок групп на экране задаёт литерал, а не генератор.

    Дописанная в конец группа объекта уехала бы из своего раздела — а
    наземный паркинг стоит ПОСЛЕ подземного, и это не случайность.
    """
    places = [i for i, g in enumerate(core._FIELD_GROUPS_LITERAL)
              if str(g[0]).startswith(core._OBJECT_PLACEHOLDER)]
    built = [i for i, g in enumerate(core.FIELD_GROUPS)
             if g[0] in {o.group_label for o in core.STANDALONE_OBJECTS}]
    assert places == built
    # Предохранитель: места не подряд — иначе проверка не различала бы
    # «встало на место» и «дописано в конец».
    assert places != list(range(places[0], places[0] + len(places)))


def test_the_measure_decides_the_money_fields() -> None:
    """Мера отвечает, чем объект меряется и по какой ставке считается."""
    parking = core.standalone_objects(("above_parking",))[0]
    offices = core.standalone_objects(("offices",))[0]
    keys = lambda o: [f[0] for f in core.standalone_object_group(o)[1]]

    assert f"{parking.prefix}_spaces" in keys(parking)
    assert f"{parking.prefix}_price_mln_per_space" in keys(parking)
    assert f"{parking.prefix}_area_per_space_sqm" in keys(parking)
    assert f"{parking.prefix}_gba_sqm" not in keys(parking)

    assert f"{offices.prefix}_gba_sqm" in keys(offices)
    assert f"{offices.prefix}_price_th_per_sqm" in keys(offices)
    assert f"{offices.prefix}_spaces" not in keys(offices)


def test_the_hint_rides_on_the_object_not_on_the_form() -> None:
    """Приписка к подсказке — свойство объекта, а не формы.

    У ФОКа продаваемая площадь читается только при продаже; у офисов такой
    оговорки нет и быть не должно — она утверждала бы то, чего нет.
    """
    hint = lambda o, key: next(
        f[2] for f in core.standalone_object_group(o)[1]
        if f[0] == f"{o.prefix}_{key}")
    sports = core.standalone_objects(("sports",))[0]
    offices = core.standalone_objects(("offices",))[0]
    assert "при продаже" in hint(sports, "saleable_sqm")
    assert hint(offices, "saleable_sqm") == "м²"


def test_three_names_answer_three_questions() -> None:
    """У объекта три имени, и они не взаимозаменяемы.

    `label` — как его зовут в прозе, `tep_label` — продукт в строке ТЭП,
    `group_label` — раздел вводных на экране. Свести их в одно значило бы
    ответить одним именем на три вопроса.
    """
    for obj in core.STANDALONE_OBJECTS:
        assert obj.tep_label and obj.group_label
    # Предохранитель: хотя бы у одного объекта все три различаются, иначе
    # проверка «имена разные» ничего не различает.
    assert any(len({o.label, o.tep_label, o.group_label}) == 3
               for o in core.STANDALONE_OBJECTS)
