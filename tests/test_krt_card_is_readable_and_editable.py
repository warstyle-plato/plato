"""Карточка КРТ: свои пропорции, свёрнутые детали, первоисточник под картой.

Три замечания владельца (23.08.2026) об одном экране.

**Пропорции.** На обычной странице доли ТЭП правятся полем во вводных — у
человека на руках бывает ГПЗУ или АГР со своими. До площадки КРТ эта правка не
доезжала вовсе: скрининг читал `core.TEP_RATIOS` напрямую, мимо разбора
движка, а в предпосылках стояло «по действующей пропорции DevelopAid 65%», как
будто выбор сделан.

**Детали.** Карточка была одной сплошной колонкой: вердикт, причины балла,
семь строк ТЭП, оговорка, кнопки, карта, допущения, неучтённое и список
соседей подряд. Важное в такой стене не видно.

**Первоисточник.** Ссылки на НСПД в модуле торгов не было ни одной, а карта,
которая не построилась, оставляла пустое место.

Запуск: python3 -m pytest tests/test_krt_card_is_readable_and_editable.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import main as wrapper  # noqa: E402
from auction_search.krt_screening import build_krt_model_screening  # noqa: E402
from auction_search.ui import auctions_page  # noqa: E402

core = wrapper.core

PROJECT = {"slug": "t", "name": "КРТ Тест", "housing_gfa_sqm": 161680,
           "total_gfa_sqm": 184930, "status": "Планируемый"}
REPORT = {"subject": {"project_name": "КРТ Тест"},
          "analysis": {"site": {"segment": "бизнес", "price_per_sqm": 708000,
                                "sold_lot_avg": 50.0}},
          "price_hint": {"entry_per_sqm": 650000}, "peers": []}


def _screen(ratios: str = ""):
    return build_krt_model_screening(PROJECT, REPORT, core, ratios)


# --- пропорции ---------------------------------------------------------------

def test_the_default_ratios_are_the_engine_ones():
    """Без правки идут доли движка, а не зашитое здесь число."""
    ratios = _screen()["tep_ratios"]
    own = core.TEP_RATIOS["apartments"]
    assert ratios["apartments"]["saleable_of_gns"] == pytest.approx(own["saleable_of_gns"])
    assert ratios["apartments"]["total_of_gns"] == pytest.approx(own["total_of_gns"])
    assert ratios["custom"] is False


def test_own_ratios_change_the_saleable_area():
    """Правка долей обязана двигать метры, иначе поле — украшение."""
    base = _screen()
    mine = _screen("apartments: 90/75")
    assert mine["tep_ratios"]["custom"] is True
    base_saleable = base["phasing"]["saleable_sqm"]
    mine_saleable = mine["phasing"]["saleable_sqm"]
    assert mine_saleable > base_saleable, f"{mine_saleable} против {base_saleable}"


def test_an_impossible_ratio_is_refused_by_the_engine_not_by_us():
    """Разбор один — движковый. «Общая 120% ГНС» не принимается и называется."""
    result = _screen("apartments: 120/50")
    warnings = result["tep_ratios"]["warnings"]
    assert warnings and "не бывает" in warnings[0]
    # Отвергнутое не применяется: остаются наши доли, а не 120%.
    assert result["tep_ratios"]["custom"] is False
    assert result["tep_ratios"]["apartments"]["total_of_gns"] == pytest.approx(
        core.TEP_RATIOS["apartments"]["total_of_gns"])


def test_the_assumption_names_the_ratio_and_whose_it_is():
    """«По действующей пропорции 65%» не говорит, чья она и можно ли её менять."""
    own = _screen()["assumptions"][0]
    assert "% ГНС" in own and "умолчание DevelopAid" in own
    mine = _screen("apartments: 90/75")["assumptions"][0]
    assert "вручную" in mine and "67.5% ГНС" in mine


def test_the_screening_goes_through_the_engine_parser():
    """Второго разбора долей быть не должно: он разошёлся бы с первым."""
    import inspect

    from auction_search import krt_screening

    source = inspect.getsource(krt_screening.build_krt_model_screening)
    assert "tep_ratios_applied" in source
    assert 'core.TEP_RATIOS["apartments"]' not in source, "доли снова читаются мимо разбора"


def test_a_custom_ratio_does_not_reach_the_shared_ranking():
    """Балл в списке и числа в карточке — про одно.

    Сохрани мы разовое допущение аналитика в общий рейтинг, таблица показывала
    бы его всем и выглядела бы при этом посчитанной по методике.
    """
    import inspect

    from auction_search import api

    source = inspect.getsource(api.install)
    assert "custom_ratios" in source
    assert "and not custom_ratios" in source


# --- детали сворачиваются ----------------------------------------------------

def test_the_card_folds_its_details():
    page = auctions_page()
    for summary in ("Почему такой балл", "Остальные ТЭП каталога", "Пропорции ТЭП",
                    "Что поставлено в модель", "Что пока не учтено",
                    "Реализуемые проекты рядом"):
        assert summary in page, summary
    assert page.count("details class=\"fold\"") >= 6


def test_the_verdict_stays_open():
    """Балл, вердикт и ключевые метры не прячутся: за ними и приходят."""
    page = auctions_page()
    start = page.index("function selectKrt")
    card = page[start:page.index("\nfunction ", start + 10)]
    head = card[:card.index("details class=\"fold\"")]
    assert "Оценка Платона" in head, "балл уехал под кат"
    assert "Жильё" in head and "Всего построить" in head


# --- первоисточник -----------------------------------------------------------

def test_the_card_links_to_nspd():
    page = auctions_page()
    assert "krtNspdLink" in page
    assert "публичная кадастровая карта НСПД" in page


def test_the_link_is_built_by_the_engine():
    """Координаты НСПД — веб-меркатор. Второй пересчёт в браузере разошёлся бы."""
    import inspect

    from auction_search import api

    source = inspect.getsource(api.install)
    assert "_nspd_map_url" in source and "_wgs84_to_mercator" in source
    merc_x, merc_y = core._wgs84_to_mercator(55.7275, 37.5589)
    url = core._nspd_map_url({"merc_x": round(merc_x, 2), "merc_y": round(merc_y, 2)}, "")
    assert "coordinate_x=4181037" in url and "nspd.gov.ru" in url


def test_the_mercator_conversion_is_declared_once():
    """Формула жила внутри `_geometry_center`; копия рядом разошлась бы молча."""
    source = Path(core.__file__).read_text(encoding="utf-8")
    assert source.count("math.log(math.tan((90.0 + lat)") == 1


def test_a_map_that_did_not_build_says_why_and_leaves_the_source():
    """Пустое место читается как «карты тут не бывает»."""
    page = auctions_page()
    assert "Карта не построена: " in page
    assert "Геокодер не нашёл адрес территории" in page
    assert "Подложка карты не ответила" in page


# --- точка карты берётся тем же путём, что точка отчёта -----------------------

def test_the_map_point_is_resolved_like_the_report_point():
    """Четвёртый случай одной ошибки: свой путь там, где есть общий.

    `/auctions/krt/{slug}/point` звал `market.geocoder` напрямую — мимо крючка
    `geocode_address`. На ядре ключа Яндекса нет, значит на деле работал один
    Nominatim, и карта отвечала «Nominatim: место не найдено» на территорию,
    которую отчёт находил (экран владельца, 23.08.2026). Хуже того: точка карты
    и точка, на которой посчитан отчёт, могли разойтись — а карта это то, на
    что смотрят.
    """
    import inspect

    from auction_search import api

    source = inspect.getsource(api.install)
    point = source[source.index("async def auction_krt_point"):
                   source.index("async def auction_krt_ranking")]
    assert "market.resolve_subject" in point, "точка карты снова считается своим путём"
    assert "geocoder.geocode" not in point, "геокодер зовётся мимо крючка сервиса"


def test_the_service_prefers_the_engine_geocoder():
    """Крючок объявлен и используется: свой геокодер знает Яндекс и Nominatim,
    движковый — ещё и DaData, и цепочку из трёх источников подряд."""
    import inspect

    from market_search import service_v6

    source = inspect.getsource(service_v6.MarketDiscoveryService.resolve_subject)
    assert "self.geocode_address or self.geocoder.geocode" in source
    import main_registry
    assert callable(getattr(main_registry.market_search, "geocode_address", None))


def test_the_krt_ladder_falls_back_to_the_district():
    """Один запрос вместо лестницы — это пустая карта там, где хватило бы района.

    Порядок именно такой: отдельный адрес точнее запроса каталога, а район —
    последнее приближение, и оно помечается как район, а не выдаётся за адрес.
    """
    from market_search.subject import _krt_geocode_candidates

    territory = {
        "name": "Территория по адресу: Проектируемый проезд № 4062, вл. 1",
        "district": "Нагатинский Затон",
        "geocode_query": "Москва, Нагатинский Затон, Территория по адресу: "
                         "Проектируемый проезд № 4062, вл. 1",
    }
    ladder = _krt_geocode_candidates(territory, "krt:test")
    kinds = [kind for _, kind in ladder]
    assert kinds == ["address_fragment", "catalogue_query", "district"], kinds
    assert ladder[-1][0] == "Москва, район Нагатинский Затон"


def test_the_card_says_how_the_point_was_found():
    """Центр района выглядит на карте так же уверенно, как настоящий адрес."""
    page = auctions_page()
    assert "subject.notes" in page, "объяснение точки до экрана не доезжает"
    assert "precision" not in page[page.index("function krtSiteMap"):
                                   page.index("function krtRankCell")], \
        "своя оценка точности осталась рядом с движковой"
