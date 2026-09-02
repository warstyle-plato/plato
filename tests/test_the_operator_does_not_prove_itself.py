"""Тяжёлый признак ставится только по номеру владения, и оператор не якорь.

«Ты на Шипиловском 55 одновременно пишешь про торги и что там ГК Орехово, а
это Шипиловский 39» (владелец, 02.09.2026). Тридцать девятого в реестре нет
вовсе — значит правило «улица общая с соседом по каталогу» его бы не поймало:
улица нашлась, а номер никто не спрашивал.

Отсюда две правки.

**Чем тяжелее утверждение, тем строже доказательство.** «Оператор назван»,
«договор заключён» и «городские нужды» закрывают вход на площадку — они
ставятся только при названном НАШЕМ номере владения либо имени проекта, всегда,
а не только при соседе в каталоге. «Право ещё выставят на торги» говорит, что
площадка свободна, и строгость там была бы потерей.

**Компания в кавычках — не имя проекта.** Из «оператором стала ГК „Орехово“»
бралось «Орехово» как бренд площадки, бренд работал вторым якорем — и якорь
подтверждал ту самую находку, из которой вышел. Оператор доказывал сам себя.

Запуск: python3 -m pytest tests/test_the_operator_does_not_prove_itself.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from market_search import krt_open_sources as sources  # noqa: E402

SITE = "Шипиловский пр-д, вл. 55"


def doc(title: str, snippet: str) -> SimpleNamespace:
    return SimpleNamespace(title=title, snippet=snippet,
                           url="https://example.ru/a", domain="example.ru")


NEIGHBOUR = doc("КРТ на Шипиловском проезде",
                "Оператором КРТ на Шипиловском проезде, вл. 39 стала ГК «Орехово».")
NO_NUMBER = doc("КРТ на Шипиловском проезде",
                "Оператором КРТ на Шипиловском проезде стала ГК «Орехово».")
OURS = doc("КРТ на Шипиловском проезде, вл. 55",
           "Оператором КРТ по адресу Шипиловский проезд, вл. 55 стало ООО «Пример».")


def test_a_neighbour_absent_from_the_catalogue_is_still_a_neighbour() -> None:
    got = sources.read_findings([NEIGHBOUR], SITE)
    assert got["operator_named"] == []
    assert got["taken"] is False


def test_a_heavy_claim_without_a_number_is_not_a_fact() -> None:
    got = sources.read_findings([NO_NUMBER], SITE)
    assert got["operator_named"] == [], "оператор приписан по одной улице"
    assert got["taken"] is False
    # Прочитанное не выброшено: документ виден, признака по нему нет.
    assert got["documents"], "документ пропал вместе с признаком"


def test_our_own_number_still_names_the_operator() -> None:
    got = sources.read_findings([OURS], SITE)
    assert [item["name"] for item in got["operator_named"]] == ["ООО «Пример»"]
    assert got["taken"] is True


def test_a_company_in_quotes_is_not_the_sites_brand() -> None:
    assert sources.brand_names([NO_NUMBER], SITE) == []
    assert sources.brand_names([NEIGHBOUR], SITE) == []


def test_a_real_project_name_is_still_an_anchor() -> None:
    """Правка не имеет права убить второй якорь, ради которого он заведён."""
    article = doc("ЖК «Строгино 360» на Маршала Воробьева, вл. 12",
                  "Проект «Строгино 360» строится на улице Маршала Воробьева, вл. 12.")
    assert sources.brand_names([article], "Маршала Воробьева ул., вл. 12") == ["Строгино 360"]


def test_a_free_site_is_still_reported_without_a_number() -> None:
    """«Право ещё выставят» вход не закрывает — строгость там была бы потерей."""
    article = doc("Торги по КРТ на Шипиловском проезде",
                  "Право на заключение договора о КРТ на Шипиловском проезде выставят на торги.")
    got = sources.read_findings([article], SITE)
    assert got["operator_pending"], "находка о будущих торгах потеряна"
    assert got["taken"] is False


def test_the_rules_version_grew_with_the_rule() -> None:
    assert sources.ANCHOR_RULES_VERSION >= 3, (
        "правило изменилось, а версия нет — хранимые ответы прежнего правила "
        "останутся признаками")
