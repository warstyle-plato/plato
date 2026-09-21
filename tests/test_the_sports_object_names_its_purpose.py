# -*- coding: utf-8 -*-
"""«ФОК / медцентр» — один объект, и назначение решает его норматив парковки.

Двух таких объектов в проекте разом не бывает (владелец, 15.09.2026), поэтому
пятый отдельно стоящий объект не заводился: у ФОКа появилось назначение. Цена
ошибки здесь не в подписи, а в числе — у Москвы спорт это код ВРИ 5.1 (200 м²
ННП на место), здравоохранение 3.4 (300 м²), то есть в полтора раза меньше
мест. Оставь медцентр на спортивной строке — и лишние места выглядели бы
посчитанными ровно так же, как настоящие.

У области строки здравоохранения в приложении № 10 нет вовсе, и `mo_required`
отвечает на неё правилом п. 5.12 «1 место на 50 м²», называя это допущением.
Проверяется именно НАЗВАННОЕ допущение: молча применённое правило неотличимо
от найденной строки таблицы.
"""
import main_legacy as core


def _demand(region: str, purpose: str, area_total: float = 9400.0) -> dict:
    inputs = dict(core.DEFAULT_INPUTS)
    inputs.update({"sports_enabled": True, "vri_region": region,
                   "sports_purpose": purpose, "parking_k1": 1.0, "parking_k2": 1.0,
                   "offices_enabled": False, "retail_enabled": False})
    tep = {key: dict(row) for key, row in core.TEP_DEFAULT.items()}
    tep["sports"] = dict(tep["sports"], gns=10000.0, total_area=area_total)
    got = core.parking_demand(inputs, tep)
    row = next((r for r in got.get("rows") or [] if r.get("tep_key") == "sports"), None)
    assert row is not None, "строки объекта в расчёте нет вовсе"
    return row


def test_moscow_counts_a_medical_centre_by_its_own_norm():
    sport = _demand("msk", "sport")
    clinic = _demand("msk", "healthcare")
    assert sport["function"] == "sport" and clinic["function"] == "healthcare"
    # 200 м² против 300 м² на место: на 9 400 м² это 47 мест против 32.
    assert sport["required_spaces"] == 47
    assert clinic["required_spaces"] == 32
    assert clinic["required_spaces"] < sport["required_spaces"], (
        "медцентр считается спортивной строкой — норматив взят чужой")


def test_the_oblast_says_the_rule_it_had_to_fall_back_to():
    clinic = _demand("mo", "healthcare")
    said = " ".join(clinic.get("assumptions") or [])
    assert "1 место на 50" in said, (
        "правило п. 5.12 применено молча — на экране это неотличимо от "
        f"найденной строки таблицы: {said!r}")
    # А у спорта своя строка есть, и никакого отката быть не должно.
    assert "не найдена" not in " ".join(_demand("mo", "sport").get("assumptions") or [])


def test_an_unknown_purpose_falls_back_to_sport_rather_than_guessing():
    assert core.sports_parking_functions({"sports_purpose": "выдумка"}) == ("sport", "fitness")
    assert core.sports_parking_functions({}) == ("sport", "fitness")
    assert core.sports_parking_functions(None) == ("sport", "fitness")


def test_the_object_is_named_once_and_the_same_everywhere():
    """Подпись объекта — одна. Четыре имени у одного продукта здесь уже были."""
    assert core.TEP_DEFAULT["sports"]["label"] == "ФОК / медцентр"
    stale = core.PAGE.count("ФОК / спортивный объект")
    # Одно вхождение законно: объяснение в комментарии, почему имя объявлено
    # один раз, называет прежние имена.
    assert stale <= 1, f"прежняя подпись осталась на странице {stale} раз"
    assert "'sports_purpose'" in core.PAGE or "sports_purpose" in core.PAGE, (
        "поле назначения до страницы не доехало")


def test_the_purpose_is_a_declared_input():
    assert core.DEFAULT_INPUTS["sports_purpose"] == "sport"
    keys = [f[0] for _, fields in core.FIELD_GROUPS for f in fields]
    assert "sports_purpose" in keys, "поля нет в FIELD_GROUPS — править его негде"
