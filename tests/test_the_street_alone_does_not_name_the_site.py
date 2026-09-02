"""Улица опознаёт площадку только там, где площадка на ней одна.

«Мы анализировали Нагатинскую, там нет ни реновации, ни ФСК» (владелец,
02.09.2026, снимок экрана): у «Варшавское шоссе, вл. 37, Нагатинская ул., влд.
3А/6» якорями выходили основы «варша» и «нагат». Под них подходит любая статья
про Нагатино и про пятнадцать километров Варшавского шоссе — в карточку и
приехали чужая реновация и чужой застройщик.

Правило то же, что у геокодера, починенного в тот же день: якорь обязан быть не
менее точным, чем то, что он опознаёт. Улица, на которой стоит ещё одна
площадка каталога, площадку не опознаёт. Улица, где она одна, — опознаёт, и
требовать там номер значило бы терять настоящие находки: «на Фестивальной»
пишут и без номера.
"""

import json
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from market_search.krt_open_sources import read_findings  # noqa: E402

SITE = "Варшавское шоссе, вл. 37, Нагатинская ул., влд. 3А/6"
SOLO = "Никулинская ул., вл. 2"


def catalogue() -> list[str]:
    data = json.loads((ROOT / "data" / "market" / "krt" / "catalogue.json").read_text("utf-8"))
    return [str(row.get("name") or "") for row in data["projects"]]


def doc(title: str, snippet: str) -> SimpleNamespace:
    return SimpleNamespace(title=title, snippet=snippet,
                           url="https://example.ru/a", domain="example.ru")


ALIEN = [
    doc("ФСК построит жильё в Нагатинском затоне",
        "ГК ФСК получила площадку в Нагатинском затоне; проект идёт по программе реновации."),
    doc("Дом по реновации на Варшавском шоссе",
        "На Варшавском шоссе завершено строительство дома по программе реновации."),
]
OURS = [
    doc("КРТ на Варшавском шоссе, вл. 37",
        "Оператором КРТ по адресу Варшавское шоссе, вл. 37 выступит компания «Пример»."),
]


def test_a_neighbours_article_no_longer_names_our_operator():
    siblings = [name for name in catalogue() if name != SITE]
    found = read_findings(ALIEN, SITE, siblings)
    assert found["strict_house"] is True
    assert found["shared_anchors"] == ["варша", "нагат"]
    assert found["operator_named"] == []
    assert found["city_needs"] == [], "чужая реновация не должна становиться нашей"
    # Прочитанное не выбрасывается: документы видны, просто не привязаны.
    assert found["documents"] and not any(item["anchored"] for item in found["documents"])


def test_our_own_article_still_counts():
    siblings = [name for name in catalogue() if name != SITE]
    found = read_findings(ALIEN + OURS, SITE, siblings)
    assert [item["name"] for item in found["operator_named"]] == ["Пример"]


def test_a_single_site_street_is_not_strict_but_a_heavy_claim_still_needs_proof():
    """Улица одиночная — строгого режима нет; тяжёлый признак всё равно по номеру.

    Строгость по соседям и строгость по тяжести признака — разные правила.
    Первое отвечает «опознаёт ли улица площадку», второе — «чем доказано, что
    вход закрыт». «Шипиловского 39 в реестре нет вовсе» (владелец, 02.09.2026),
    и первое правило его бы не поймало.
    """
    siblings = [name for name in catalogue() if name != SOLO]
    without = read_findings(
        [doc("Реновация на Никулинской",
             "На Никулинской улице квартал застраивается по программе реновации.")],
        SOLO, siblings)
    assert without["strict_house"] is False
    assert without["city_needs"] == [], "тяжёлый признак поставлен по одной улице"
    assert without["documents"][0]["anchored"] is True, "документ потерян вместе с признаком"
    # Тот же текст с нашим номером — находка на месте.
    with_number = read_findings(
        [doc("Реновация на Никулинской, вл. 2",
             "На Никулинской улице, вл. 2 квартал застраивается по программе реновации.")],
        SOLO, siblings)
    assert with_number["city_needs"], "находка с номером потеряна"


def test_without_siblings_nothing_changes():
    """Соседей не передали — правило не включается: это «не знаем», а не «строго»."""
    found = read_findings(ALIEN, SITE)
    assert found["strict_house"] is False
