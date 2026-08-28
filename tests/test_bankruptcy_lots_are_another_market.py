"""Банкротные торги — другой источник и другой рынок, а не другой фильтр.

Наши три площадки продают ГОРОДСКОЕ имущество. Реестры, которые смотрит
девелопер, наполовину состоят из другого: имущественные комплексы, нежилые
здания и незавершёнка от арбитражных управляющих и залоговых кредиторов. Из
двух присланных владельцем реестров (96 лотов от 200 млн ₽ и 242 от 20 000 м²)
наш инструмент не нашёл бы НИ ОДНОГО — и дело не в настройке фильтра.

Механика тоже разная: у города цена не снижается, у банкротного лота публичное
предложение идёт по графику от начальной к минимальной. «Дешевле» там часто
значит «дошло до последнего шага», а не «выгодно», и показывать это надо
картинкой, а не строкой.

Запуск: python3 -m pytest tests/test_bankruptcy_lots_are_another_market.py -q
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from auction_search.adapters.torgi_gov import (  # noqa: E402
    FLAG, REGION_PARAM_CANDIDATES, TorgiGovAdapter, classify, to_lot,
)
from auction_search.models import LotKind, LotOrigin, lot_subject  # noqa: E402


def _card(**over):
    card = {
        "id": "21000123",
        "lotName": "Имущественный комплекс",
        "lotDescription": "Конкурсное производство, продажа имущества должника",
        "biddType": {"code": "178FZ", "name": "Продажа имущества должников"},
        "estimatedPrice": 3643151220,
        "priceMin": 182157561,
        "priceFin": 1800000000,
        "estateAddress": "г. Москва, Перовское ш., вл. 2",
        "estateArea": 79664.9,
        "biddEndTime": "2026-09-01T10:00:00Z",
    }
    card.update(over)
    return card


def _lot(**over):
    return to_lot(_card(**over), datetime.now(timezone.utc).isoformat())


# --- происхождение ----------------------------------------------------------

def test_a_bankruptcy_lot_is_marked_as_one() -> None:
    assert _lot().origin is LotOrigin.BANKRUPTCY


def test_privatization_is_the_city_market_not_bankruptcy() -> None:
    """178-ФЗ — приватизация государственного и муниципального имущества.

    Продавец там город, и цена по публичному предложению у него тоже ползёт,
    но рынок это городской. Отнести такой лот к банкротным значит поставить
    его в сравнение не с теми соседями — там «дешевле» читается как «дошло до
    последнего шага», а не как выгода.
    """
    lot = _lot(lotName="Нежилое здание", lotDescription="Приватизация",
               biddType={"code": "178FZ", "name": "Приватизация имущества"})
    assert lot.origin is LotOrigin.CITY


def test_a_named_procedure_outweighs_a_guessed_code() -> None:
    """Коды справочника не сверены живым ответом, слова процедуры — сверены.

    Догадка не отменяет доказательства: карточка, называющая конкурсное
    производство, банкротная при любом коде.
    """
    lot = _lot(biddType={"code": "178FZ", "name": "Приватизация"},
               lotDescription="Конкурсное производство в отношении должника")
    assert lot.origin is LotOrigin.BANKRUPTCY


def test_a_tender_word_is_not_a_bankruptcy_word() -> None:
    """«Конкурсная документация» — обычные городские торги, а не банкротство.

    Голое «конкурсн» ловило и её, и «конкурсную комиссию»: слово, которое
    означает две разные вещи, признаком быть не может.
    """
    lot = _lot(lotName="Земельный участок",
               lotDescription="Конкурсная документация размещена на площадке",
               biddType={"code": "AUCTION", "name": "Открытый конкурс"})
    assert lot.origin is not LotOrigin.BANKRUPTCY


def test_a_debtor_alone_is_not_proof_of_bankruptcy() -> None:
    """Имущество должника продают и приставы вне дела о банкротстве.

    Прежде такой лот оставался «прочим»: третьей метки у нас не было, и
    неопознанное лучше было оставить «другим», чем уверенно подписать неверно.
    Метка появилась — арест и исполнительное производство, — и она заведена не
    ради полноты перечня: в реестре владельца из пятнадцати таких лотов с
    прошедшими торгами до сделки дошёл один. Банкротством лот при этом
    по-прежнему не становится.
    """
    lot = _lot(lotName="Нежилое помещение",
               lotDescription="Реализация имущества должника по решению суда",
               biddType={"code": "FSSP", "name": "Реализация арестованного имущества"})
    assert lot.origin is not LotOrigin.BANKRUPTCY
    assert lot.origin is LotOrigin.SEIZED


def test_an_unset_origin_is_not_city() -> None:
    """Умолчание, которое утверждает, — не умолчание.

    Прежде здесь стояли городские торги: три наших источника заводились под
    городское имущество. Лот РАД по Коммунарке эту посылку опроверг — продавец
    банк, а в списке он стоял городским. На экране опознанное и неопознанное
    выглядели одинаково, и сравнить их было не с чем.
    """
    from auction_search.models import AuctionLot, AuctionSource, SourceKind
    lot = AuctionLot(
        source=AuctionSource(platform=SourceKind.ROSELTORG, lot_url="x",
                             external_lot_id="1", fetched_at="now"),
        lot_kind=LotKind.KRT, title="Площадка КРТ")
    assert lot.origin is LotOrigin.OTHER
    assert lot.to_dict()["origin"] == "other"


def test_an_unrecognised_notice_is_not_forced_into_bankruptcy() -> None:
    """Не опознали — «прочее», а не подогнано под ближайшую рубрику."""
    kind, origin = classify({"lotName": "Аренда киоска", "biddType": {"code": "X", "name": "Аренда"}})
    assert origin is LotOrigin.OTHER


# --- предмет ----------------------------------------------------------------

def test_subject_is_derived_not_stored_twice() -> None:
    """Второе поле о том же самом однажды разошлось бы с lot_kind."""
    assert lot_subject(LotKind.KRT) == "land"
    assert lot_subject(LotKind.LAND_LEASE) == "land"
    assert lot_subject(LotKind.PROPERTY_COMPLEX) == "building"
    assert lot_subject(LotKind.UNFINISHED) == "building"
    assert lot_subject(LotKind.OTHER) == "other"


def test_the_subject_reaches_the_page() -> None:
    assert _lot().to_dict()["subject"] == "building"


def test_unfinished_construction_is_recognised() -> None:
    kind, _ = classify({"lotName": "Объект незавершенного строительства"})
    assert kind is LotKind.UNFINISHED


def test_a_land_lot_is_recognised() -> None:
    kind, _ = classify({"lotName": "Земельный участок под застройку"})
    assert kind is LotKind.LAND_SALE


# --- цена, которая ползёт ---------------------------------------------------

def test_one_price_field_does_not_become_three() -> None:
    """У сервиса ценовое поле ОДНО — `priceMin`. Живой ответ 24.08.2026.

    Полей `estimatedPrice` и `priceFin`, на которые мы рассчитывали, в ответе
    нет вовсе. Разложить одно число по трём нашим полям значит выдумать два
    из них, а выдуманная начальная цена делает батарейку хода правдоподобной
    и неверной. Начальная и минимальная остаются пустыми.
    """
    lot = _lot(priceMin=460599.0, estimatedPrice=None, priceFin=None)
    assert lot.current_price_rub == 460599.0
    assert lot.start_price_rub is None
    assert lot.min_price_rub is None


def test_the_unknown_meaning_of_the_price_is_said_out_loud() -> None:
    """Число без правового смысла — не «цена», а «какое-то число».

    По ответу нельзя определить, начальная это цена, текущая или отсечка.
    Молча подписать её «ценой сейчас» и не сказать больше ничего значит
    выдать догадку за факт.
    """
    lot = _lot(priceMin=460599.0)
    assert any("priceMin" in flag for flag in lot.relevance_flags)


def test_a_public_offer_says_its_ladder_is_not_in_the_answer() -> None:
    """Форма торгов лежит в `biddForm`, а не в `biddType`.

    «PP» — публичное предложение: цена снижается по графику. Графика в ответе
    поиска нет, и молчание об этом читалось бы как «снижения не будет».
    """
    lot = _lot(biddForm={"code": "PP", "name": "Публичное предложение"})
    assert any("публичное предложение" in flag for flag in lot.relevance_flags)


# --- осторожность -----------------------------------------------------------

def test_the_source_is_on_once_it_has_been_checked(monkeypatch) -> None:
    """Источник ждал не флага, а проверки — и дождался.

    Разбор сверен живым ответом на десяти карточках, имя параметра региона
    измерено пробой с ядра. Держать после этого выключенным значит держать
    выключенным проверенное.
    """
    monkeypatch.delenv(FLAG, raising=False)
    assert TorgiGovAdapter.enabled() is True


def test_the_source_can_still_be_switched_off(monkeypatch) -> None:
    """Выключатель остаётся: источник чужой, и он может испортиться."""
    monkeypatch.setenv(FLAG, "0")
    assert TorgiGovAdapter.enabled() is False
    assert list(TorgiGovAdapter().discover_moscow()) == []


def test_the_switch_off_says_why(monkeypatch) -> None:
    monkeypatch.setenv(FLAG, "0")
    adapter = TorgiGovAdapter()
    list(adapter.discover_moscow())
    assert FLAG in adapter.last_report["reason"]


def test_the_report_says_who_filtered_the_region(monkeypatch) -> None:
    """Серверного фильтра у этого API нет — молчание об этом читалось бы
    как «сервис прислал только наше».

    Проба 25.08.2026 перебрала шесть имён параметра, включая контрольный
    запрос без него: ни одно не отфильтровало, выдача одна и та же с чужими
    регионами (47, 69, 76, 77).
    """
    monkeypatch.setenv(FLAG, "0")
    adapter = TorgiGovAdapter()
    list(adapter.discover_moscow())
    assert "region_filter" in adapter.last_report
    monkeypatch.setattr(TorgiGovAdapter, "_fetch_page",
                        lambda self, page, **_: {"content": []})
    monkeypatch.setenv(FLAG, "1")
    adapter = TorgiGovAdapter()
    list(adapter.discover_moscow())
    assert "subjectRFCode" in adapter.last_report["region_filter"]


def test_a_card_without_a_name_is_skipped_not_invented() -> None:
    assert to_lot({"id": "1"}, "now") is None
    assert to_lot({"lotName": "Без номера"}, "now") is None


def test_the_probe_exists_for_checking_from_the_core() -> None:
    """Из песочницы torgi.gov.ru закрыт, как НСПД: сверять поля можно с ядра."""
    import main_registry
    paths = [getattr(route, "path", "") for route in main_registry.app.routes]
    assert "/auctions/torgi/probe" in paths


def test_the_source_list_names_the_new_source() -> None:
    from fastapi.testclient import TestClient
    import main_registry
    got = TestClient(main_registry.app).get("/auctions/sources").json()
    ids = {row["id"] for row in got["sources"]}
    assert "torgi_gov" in ids


# --- страница ---------------------------------------------------------------

def test_the_page_can_filter_by_origin_and_subject() -> None:
    from auction_search.ui import auctions_page
    page = auctions_page()
    assert 'id="origin"' in page
    assert 'value="bankruptcy"' in page
    assert 'value="land"' in page and 'value="building"' in page
    assert "lotMatchesKind" in page


def test_the_page_draws_the_price_ladder_as_a_battery() -> None:
    from auction_search.ui import auctions_page
    page = auctions_page()
    assert "priceBattery" in page and "priceCharge" in page
    # Полная — торги только объявлены, пустая — снижать больше некуда.
    assert "Публичное предложение" in page


def test_a_lot_without_a_ladder_gets_no_battery() -> None:
    """У городского лота цена не снижается — мерить нечего, и рисовать нечего."""
    from auction_search.ui import auctions_page
    assert "if(!(start>0)||!(min>0)||min>=start)return null" in auctions_page()


def test_the_battery_keeps_the_square_corners_of_this_page() -> None:
    """Механика из Монитора, углы — этой страницы: скруглённое читалось бы чужим."""
    from auction_search.ui import auctions_page
    page = auctions_page()
    style = page[page.index("<style>"):page.index("</style>")]
    assert ".pbatt{" in style
    assert "border-radius:5px" not in style


# --- проба с ядра -----------------------------------------------------------
#
# Проба — единственный оставшийся путь сверки: ни из песочницы, ни из чужого
# облачного браузера torgi.gov.ru не отвечает (24.08.2026, 502 от прокси).
# Значит она обязана ответить с первого раза и не прятать ничего.

class _Response:
    def __init__(self, body, status=200, ctype="application/json"):
        self._body = body.encode("utf-8")
        self.status = status
        self.headers = {"Content-Type": ctype}

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _probe_with(body, monkeypatch, status=200, ctype="application/json"):
    import auction_search.adapters.torgi_gov as mod
    monkeypatch.setattr(mod.urllib.request, "urlopen",
                        lambda *a, **k: _Response(body, status, ctype))
    return TorgiGovAdapter().probe()


def test_the_probe_shows_every_field_name(monkeypatch) -> None:
    """Обрезанный список ключей выглядит полным — и поле теряется молча.

    Ровно так уже терялись глифы в отчёте о продажах: неизвестное
    выбрасывалось, а выгрузка при этом казалась исправной.
    """
    card = {f"field{n}": n for n in range(60)}
    card["lotName"] = "Лот"
    result = _probe_with(json.dumps({"content": [card]}), monkeypatch)
    assert result["ok"] is True
    assert set(result["raw_first"]) == set(card)
    assert set(result["field_counts"]) == set(card)


def test_the_probe_says_which_key_held_the_array(monkeypatch) -> None:
    """Догадка об оболочке не должна читаться как «лотов нет»."""
    result = _probe_with(json.dumps({"lots": [{"lotName": "Лот"}]}), monkeypatch)
    assert result["array_key"] == "lots"
    assert "content" in (result["envelope_note"] or "")
    assert result["on_page"] == 1


def test_the_probe_confirms_the_guessed_envelope_without_a_note(monkeypatch) -> None:
    result = _probe_with(json.dumps({"content": [{"lotName": "Лот"}],
                                     "totalElements": 7}), monkeypatch)
    assert result["array_key"] == "content"
    assert result["envelope_note"] is None
    assert "totalElements" in result["envelope_keys"]


def test_a_page_of_html_is_shown_not_swallowed(monkeypatch) -> None:
    """502 от прокси приходил и нам, и стороннему браузеру.

    Невнятная ошибка разбора JSON на это не отвечает: видно должно быть, что
    пришла страница ошибки, а не лоты.
    """
    result = _probe_with("<html><h1>502 Bad Gateway</h1></html>", monkeypatch,
                         status=502, ctype="text/html")
    assert result["ok"] is False
    assert result["http_status"] == 502
    assert "502" in result["body_head"]


def test_the_probe_prints_the_address_it_asked(monkeypatch) -> None:
    """Проба печатает тот адрес, по которому пойдёт рабочий сбор.

    Раньше здесь требовался `dynSubjRF`: параметр стоял в рабочем запросе.
    Проба показала, что он ухудшает выдачу, и из сбора он убран — значит и
    печатать проба должна запрос без него, иначе она проверяет не то.
    """
    result = _probe_with(json.dumps({"content": []}), monkeypatch)
    assert result["url"].startswith("https://torgi.gov.ru/new/api/public/")
    assert "dynSubjRF" not in result["url"]
    assert "size=" in result["url"] and "page=" in result["url"]


def test_the_probe_and_the_real_collector_ask_the_same_address() -> None:
    """Сверенное пробой относится к тому запросу, который пойдёт в дело."""
    import inspect
    source = inspect.getsource(TorgiGovAdapter._fetch_page)
    assert "_search_url" in source


def test_an_optional_field_is_visible_as_optional(monkeypatch) -> None:
    """По одной карточке необязательное поле неотличимо от отсутствующего."""
    body = json.dumps({"content": [
        {"lotName": "А", "priceMin": 1}, {"lotName": "Б"}, {"lotName": "В"}]})
    result = _probe_with(body, monkeypatch)
    assert result["field_counts"]["lotName"] == 3
    assert result["field_counts"]["priceMin"] == 1


def test_a_card_that_did_not_parse_says_so(monkeypatch) -> None:
    """Пустой разбор рядом с сырым лотом читался бы как «лотов нет»."""
    result = _probe_with(json.dumps({"content": [{"nothing": "useful"}]}), monkeypatch)
    assert result["parsed_first"] is None
    assert result["parsed_note"]


# --- живой ответ ------------------------------------------------------------
#
# Всё выше проверяет наши предположения на наших же выдумках. Здесь — карточка
# из настоящего ответа сервиса (24.08.2026), и она единственная доказывает, что
# разбор относится к тому, что действительно приходит.

def _real_card():
    path = Path(__file__).resolve().parent / "fixtures" / "torgi_gov_lotcard.json"
    return json.loads(path.read_text(encoding="utf-8"))


def test_the_real_card_parses() -> None:
    from auction_search.adapters.torgi_gov import to_lot as parse
    lot = parse(_real_card(), "now")
    assert lot is not None
    assert lot.title.startswith("Здание дома кордона")
    assert lot.status == "PUBLISHED"
    assert lot.application_deadline.startswith("2026-09-25")


def test_the_cadastral_number_comes_out_of_characteristics() -> None:
    """Кадастра отдельным полем в ответе нет — он строка `characteristics`."""
    from auction_search.adapters.torgi_gov import to_lot as parse
    assert parse(_real_card(), "now").cadastral_numbers == ["76:14:020110:400"]


def test_building_area_is_not_land_area() -> None:
    """«Общая площадь» карточки — метры здания. Участок стоит только в тексте.

    Сложить их в одно поле значит подписать два разных числа одним именем.
    """
    from auction_search.adapters.torgi_gov import to_lot as parse
    lot = parse(_real_card(), "now")
    assert lot.building_area_sqm == 86.3
    assert lot.land_area_sqm is None


def test_the_service_rubric_decides_the_kind_not_word_order() -> None:
    """«Здание … С ЗЕМЕЛЬНЫМ УЧАСТКОМ» — это здание.

    Гонку слов выигрывал тот, кто выше в нашем списке: «земельн» стоял перед
    «здание», и лот уходил в продажу земли. У сервиса есть своя рубрика.
    """
    from auction_search.adapters.torgi_gov import to_lot as parse
    assert parse(_real_card(), "now").lot_kind is LotKind.PROPERTY_COMPLEX


def test_privatization_in_the_real_card_is_the_city() -> None:
    from auction_search.adapters.torgi_gov import to_lot as parse
    assert parse(_real_card(), "now").origin is LotOrigin.CITY


def test_both_the_type_and_the_form_reach_the_lot() -> None:
    """Вид торгов и форма — разные поля, и человеку нужны оба."""
    from auction_search.adapters.torgi_gov import to_lot as parse
    procedure = parse(_real_card(), "now").procedure_type
    assert "приватизация" in procedure
    assert "Публичное предложение" in procedure


def test_a_foreign_region_is_not_ours() -> None:
    """Ответ на запросе с dynSubjRF=77,50 принёс Ярославскую область (76).

    Серверный фильтр под этим именем не работает. Пока рабочее имя не
    выяснено, лот из Рыбинска в московском списке был бы не шумом, а ложью.
    """
    from auction_search.adapters.torgi_gov import in_target_region
    assert in_target_region(_real_card()) is False
    assert in_target_region(dict(_real_card(), subjectRFCode="77")) is True
    # subjectRFCode=50 — Московская область, а страница называется Москвой.
    # Это не то же самое, что старый кадастровый префикс 50 у Новой Москвы.
    assert in_target_region(dict(_real_card(), subjectRFCode="50")) is False


def test_the_collector_drops_foreign_regions(monkeypatch) -> None:
    import auction_search.adapters.torgi_gov as mod
    ours = dict(_real_card(), subjectRFCode="77", id="ours_1")
    body = json.dumps({"content": [_real_card(), ours]})
    monkeypatch.setenv(FLAG, "1")
    monkeypatch.setattr(mod.urllib.request, "urlopen",
                        lambda *a, **k: _Response(body))
    adapter = TorgiGovAdapter()
    lots = list(adapter.discover_moscow())
    assert [lot.source.external_lot_id for lot in lots] == ["ours_1"]


def test_a_page_of_foreign_regions_says_why_it_is_empty(monkeypatch) -> None:
    """Пустой список после полной страницы читался бы как «лотов нет»."""
    import auction_search.adapters.torgi_gov as mod
    monkeypatch.setenv(FLAG, "1")
    monkeypatch.setattr(mod.urllib.request, "urlopen",
                        lambda *a, **k: _Response(json.dumps({"content": [_real_card()]})))
    adapter = TorgiGovAdapter()
    assert list(adapter.discover_moscow()) == []
    assert "subjectRFCode" in adapter.last_report["reason"]


def test_the_probe_counts_how_many_lots_were_actually_ours(monkeypatch) -> None:
    """«Фильтр работает» и «не работает» не должны выглядеть одинаково."""
    body = json.dumps({"content": [_real_card(),
                                   dict(_real_card(), subjectRFCode="77")]})
    result = _probe_with(body, monkeypatch)
    assert result["on_page"] == 2
    assert result["in_target_region"] == 1
    assert result["subject_codes_seen"] == ["76", "77"]


def test_an_attribute_is_found_despite_the_services_own_typos() -> None:
    """В живом ответе встречаются `minpiced` без «r» и `minpriced((178)`.

    Сверять код целиком значит терять поле на каждой чужой описке.
    """
    from auction_search.adapters.torgi_gov import attribute, ATTR_LIMITATIONS
    for code in ("DA_limitations_PP(178)", "DA_limitations_minpiced(178)",
                 "DA_limitations_minpriced((178)"):
        card = {"attributes": [{"code": code, "value": "есть ограничения"}]}
        assert attribute(card, ATTR_LIMITATIONS) == "есть ограничения"


def test_a_street_named_moscow_is_not_moscow() -> None:
    """«улица Московская» есть в половине городов страны.

    Запасной путь по словам прошёл бы ярославский лот за наш — та же ошибка,
    на которой в модуле рынка кандидат забрал себе адрес объекта оценки.
    """
    from auction_search.adapters.torgi_gov import in_target_region
    card = dict(_real_card(), lotDescription="Ярославская область, ул. Московская, д. 4")
    card.pop("subjectRFCode")
    assert in_target_region(card) is False


def test_cards_without_a_region_are_counted_not_swallowed(monkeypatch) -> None:
    """Пропущенное молча читается как отсутствующее."""
    import auction_search.adapters.torgi_gov as mod
    blind = dict(_real_card(), id="blind_1")
    blind.pop("subjectRFCode")
    ours = dict(_real_card(), subjectRFCode="77", id="ours_1")
    monkeypatch.setenv(FLAG, "1")
    monkeypatch.setattr(mod.urllib.request, "urlopen",
                        lambda *a, **k: _Response(json.dumps({"content": [blind, ours]})))
    adapter = TorgiGovAdapter()
    lots = list(adapter.discover_moscow())
    assert [lot.source.external_lot_id for lot in lots] == ["ours_1"]
    assert "без кода региона: 1" in adapter.last_report["reason"]


# --- доверие к сертификатам -------------------------------------------------
#
# Проба с ядра 24.08.2026 упёрлась не в сеть, а в TLS: соединение с
# torgi.gov.ru устанавливается, а цепочка не проверяется. Соблазн «отключить
# проверку на один источник» здесь и ловится.

def test_verification_is_never_switched_off() -> None:
    """Выключенная проверка принимает любой сертификат.

    Тогда «мы читаем ГИС Торги» перестаёт что-либо значить: читать могли и не
    их. Недоступный источник, честно сказавший, что он недоступен, лучше.
    """
    from auction_search.adapters.torgi_gov import trust_context
    import ssl as ssl_module
    context = trust_context()
    assert context.verify_mode is ssl_module.CERT_REQUIRED
    assert context.check_hostname is True


def test_the_module_has_no_way_to_disable_verification() -> None:
    """Переключателя нет в исходнике — не только в умолчании."""
    from pathlib import Path as _Path
    source = (_Path(__file__).resolve().parent.parent
              / "auction_search" / "adapters" / "torgi_gov.py").read_text(encoding="utf-8")
    for forbidden in ("CERT_NONE", "check_hostname = False", "_create_unverified"):
        assert forbidden not in source, forbidden


def test_extra_roots_are_added_not_substituted(tmp_path) -> None:
    """Наш корень добавляется к системным, а не заменяет их."""
    from auction_search.adapters.torgi_gov import extra_ca_files
    (tmp_path / "root.cer").write_text("x")
    (tmp_path / "chain.pem").write_text("x")
    (tmp_path / "notes.txt").write_text("x")
    found = [one.rsplit("/", 1)[-1] for one in extra_ca_files(str(tmp_path))]
    assert found == ["chain.pem", "root.cer"]


def test_a_page_pretending_to_be_a_root_is_named(tmp_path) -> None:
    """«Файл лежит» и «корень принят» — разные вещи, и путать их нельзя.

    По неверному адресу скачалась HTML-страница портала и легла в каталог с
    расширением .cer. Отчёт «корень добавлен» на таком файле — враньё того же
    рода, что «ограничений не обнаружено» там, где не спрашивали.
    """
    from auction_search.adapters.torgi_gov import trust_report
    (tmp_path / "root.cer").write_text("<!doctype html><html>портал</html>")
    report = trust_report(str(tmp_path))
    assert report["accepted"] == []
    assert report["rejected"] and report["rejected"][0].endswith("root.cer")


def test_a_broken_root_does_not_open_the_door(tmp_path) -> None:
    """Битый файл — не повод доверять всему подряд."""
    from auction_search.adapters.torgi_gov import trust_context
    import ssl as ssl_module
    (tmp_path / "broken.pem").write_text("это не сертификат")
    context = trust_context(str(tmp_path))
    assert context.verify_mode is ssl_module.CERT_REQUIRED


def test_a_certificate_failure_says_what_to_do(monkeypatch) -> None:
    """Причина без выхода читается как тупик, а выход здесь есть."""
    import auction_search.adapters.torgi_gov as mod

    def boom(*a, **k):
        raise mod.urllib.error.URLError(
            "[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: "
            "unable to get local issuer certificate")

    monkeypatch.setattr(mod.urllib.request, "urlopen", boom)
    result = TorgiGovAdapter().probe()
    assert result["ok"] is False
    assert mod.EXTRA_CA_DIR in result["hint"]
    assert "openssl" in result["hint"]
    assert result["extra_ca"] == mod.trust_report()


def test_a_binary_certificate_is_accepted_too(tmp_path) -> None:
    """Издатель по ссылке из сертификата приезжает в DER, а не в PEM.

    `cafile` понимает только текстовый вид: годный корень отвергался бы как
    битый, и причина была бы невнятной — «файл не сертификат» про настоящий
    сертификат. Вид решает содержимое, а не расширение.
    """
    import ssl as ssl_module
    from auction_search.adapters.torgi_gov import trust_report
    pem = ssl_module.get_default_verify_paths().cafile
    if not pem:
        pytest.skip("в системе нет связки корней")
    with open(pem, "r", encoding="ascii", errors="ignore") as handle:
        text = handle.read()
    one = text[text.index("-----BEGIN CERTIFICATE-----"):
               text.index("-----END CERTIFICATE-----") + len("-----END CERTIFICATE-----")] + "\n"
    (tmp_path / "pem_root.pem").write_text(one)
    (tmp_path / "der_root.crt").write_bytes(ssl_module.PEM_cert_to_DER_cert(one))
    report = trust_report(str(tmp_path))
    assert report["rejected"] == []
    assert len(report["accepted"]) == 2


# --- имя параметра региона измеряется, а не угадывается ---------------------

def test_the_region_parameter_is_measured_not_guessed(monkeypatch) -> None:
    """Сервис молча игнорирует неизвестный параметр.

    Значит перебирать имена вслепую можно вечно, а измерить — один раз:
    «сколько из присланного наше». Запрос без параметра идёт первым: без него
    сработавший фильтр не с чем сравнить.
    """
    import auction_search.adapters.torgi_gov as mod
    ours = dict(_real_card(), subjectRFCode="77")
    alien = _real_card()

    def answer(request, *a, **k):
        url = getattr(request, "full_url", request)
        cards = [ours] if "subjectRFCode=77" in str(url) else [ours, alien]
        return _Response(json.dumps({"content": cards}))

    monkeypatch.setattr(mod.urllib.request, "urlopen", answer)
    result = TorgiGovAdapter().probe_regions()
    assert result["working"] == ["subjectRFCode"]
    control = result["trials"][0]
    assert control["param"] == "(без параметра)"
    assert control["filters"] is False


def test_half_a_page_is_not_a_working_filter(monkeypatch) -> None:
    """Фильтр либо отбирает всё, либо не фильтр.

    «Больше половины наших» — совпадение выдачи, а не работающий параметр.
    """
    import auction_search.adapters.torgi_gov as mod
    body = json.dumps({"content": [dict(_real_card(), subjectRFCode="77"), _real_card()]})
    monkeypatch.setattr(mod.urllib.request, "urlopen", lambda *a, **k: _Response(body))
    result = TorgiGovAdapter().probe_regions()
    assert result["working"] == []
    assert "subjectRFCode" in result["note"]


def test_the_probe_lists_the_service_dictionaries(monkeypatch) -> None:
    """Код банкротства мы не видели ни разу — пусть находится сам.

    Одно значение справочника выглядит как единственное: пока в выдаче одна
    приватизация, кажется, что других видов торгов не бывает.
    """
    body = json.dumps({"content": [
        _real_card(),
        dict(_real_card(), biddType={"code": "127FZ", "name": "Банкротство"}),
    ]})
    result = _probe_with(body, monkeypatch)
    assert result["codes_seen"]["biddType"] == {"127FZ": 1, "178FZ": 1}
    assert result["codes_seen"]["biddForm"] == {"PP": 2}


# --- происхождение у трёх старых источников ---------------------------------
#
# Умолчание `CITY` жило на посылке «наши площадки продают городское имущество».
# Лот РАД по Коммунарке (`50:21:0120316:1221`, экран владельца 24.08.2026) её
# опроверг: продавец — банк, процедура — публичное предложение, а в списке лот
# стоял городским. Форма процедуры при этом не улика: публичное предложение
# бывает и у приватизации по 178-ФЗ. Улика — продавец.

class _FakeResponse:
    def __init__(self, html: str) -> None:
        self._html = html

    def read(self) -> bytes:
        return self._html.encode("utf-8")

    @property
    def headers(self):
        class _H:
            @staticmethod
            def get_content_charset():
                return "utf-8"
        return _H()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _rad_html(*, seller: str, direction: str, procedure: str = "Продажа посредством публичного предложения") -> str:
    return (
        "<html><body>"
        "<p>Опубликовано: На lot-online.ru: 20.08.2026 10:00</p>"
        "<h1>Земельный участок в г. Москва, поселение Сосенское</h1>"
        "<p>Начальная цена</p><p>1 000 000 000 руб.</p>"
        "<p>Минимальная цена</p><p>500 000 000 руб.</p>"
        "<p>Регион</p><p>Москва</p>"
        "<p>Адрес</p><p>г. Москва, поселение Сосенское</p>"
        "<p>Категория земель</p><p>земли населенных пунктов</p>"
        "<p>Кадастровый номер</p><p>50:21:0120316:1221</p>"
        "<p>Доступность</p><p>Доступен</p>"
        f"<p>Направление продаж</p><p>{direction}</p>"
        f"<p>Вид процедуры</p><p>{procedure}</p>"
        "<p>Код лота</p><p>123456</p>"
        f"<p>Наименование ФО</p><p>{seller}</p>"
        "<p>Является залогом</p><p>Нет</p>"
        "</body></html>"
    )


def _rad_lot(monkeypatch, **kw):
    from auction_search.adapters import lot_online as module
    monkeypatch.setattr(module, "urlopen", lambda *a, **k: _FakeResponse(_rad_html(**kw)))
    adapter = module.LotOnlineAdapter()
    return adapter.fetch_lot("https://catalog.lot-online.ru/index.php?dispatch=products.view&product_id=123456")


def test_a_bank_seller_on_rad_is_not_the_city_market(monkeypatch) -> None:
    """Продавец — банк, площадка — РАД. Городским это не делает ничто.

    Так выглядел лот по Коммунарке: в списке он стоял «городскими торгами»
    только потому, что приехал с площадки, заведённой под городское имущество.
    Сравнивать его цену с городскими соседями — сравнивать несравнимое, и на
    экране об этом не было ни слова.
    """
    lot = _rad_lot(monkeypatch, seller="ПАО «Банк Икс»",
                   direction="Имущество финансовых организаций")
    assert lot.origin is not LotOrigin.CITY
    assert lot.origin is LotOrigin.OTHER
    assert lot.to_dict()["origin"] == "other"


def test_the_city_seller_on_rad_is_recognised(monkeypatch) -> None:
    """Городской лот опознаётся продавцом, а не площадкой."""
    lot = _rad_lot(monkeypatch, seller="Департамент городского имущества города Москвы",
                   direction="Приватизация государственного и муниципального имущества")
    assert lot.origin is LotOrigin.CITY


def test_the_platform_rubric_can_prove_bankruptcy(monkeypatch) -> None:
    """«Направление продаж» — рубрика самой площадки, а не наша догадка."""
    lot = _rad_lot(monkeypatch, seller="ООО «Ромашка»",
                   direction="Имущество банкротов")
    assert lot.origin is LotOrigin.BANKRUPTCY


def test_the_public_offer_form_alone_decides_nothing() -> None:
    """Публичное предложение бывает и у приватизации, и у банкротства.

    Соблазн был: форма процедуры лежит в карточке и выглядит признаком рынка.
    Она признак МЕХАНИКИ цены, а не продавца.
    """
    from auction_search.classifier import origin_from_evidence
    assert origin_from_evidence(
        procedure_type="Продажа посредством публичного предложения",
    ) is LotOrigin.OTHER


def test_the_organizer_never_decides_the_market() -> None:
    """РАД проводит и городские торги, и продажу имущества финансовых
    организаций. Организатор доказывает только, кто вёл процедуру."""
    from auction_search.classifier import origin_from_evidence
    assert origin_from_evidence(
        organizer="Российский аукционный дом", seller="ООО «Ромашка»",
    ) is LotOrigin.OTHER


def test_roseltorg_reads_its_own_trading_section() -> None:
    """У Росэлторга рынок называет торговая секция."""
    from auction_search.classifier import origin_from_evidence
    assert origin_from_evidence(
        seller="ООО «Ромашка»", organizer="Росэлторг",
        text="Продажа имущества банкротов",
    ) is LotOrigin.BANKRUPTCY


def test_one_dictionary_of_bankruptcy_words_for_every_source() -> None:
    """Правило «это банкротный лот» одно на модуль.

    Разойдись копии — один и тот же лот с ГИС Торгов и с РАД попал бы в разные
    рынки, и оба списка выглядели бы верными.
    """
    from auction_search import classifier
    from auction_search.adapters import torgi_gov
    assert torgi_gov.BANKRUPTCY_WORDS is classifier.BANKRUPTCY_WORDS


def test_the_page_shows_unrecognised_origin_as_its_own_group() -> None:
    """Неопознанное обязано выглядеть неопознанным и на экране."""
    from auction_search.ui import AUCTIONS_PAGE
    page = AUCTIONS_PAGE if isinstance(AUCTIONS_PAGE, str) else str(AUCTIONS_PAGE)
    assert 'value="other">Прочие' in page
    assert "l.origin||'city'" not in page


def test_a_short_page_is_not_the_last_page(monkeypatch) -> None:
    """Размер страницы мы просим, а не назначаем.

    На прод приехал сбор из ОДНОЙ страницы: сервис прислал десять карточек на
    запрос с `size=50`, и сработала остановка «пришло меньше запрошенного —
    значит последняя». Она верна только там, где размер соблюдают.
    """
    import auction_search.adapters.torgi_gov as mod
    monkeypatch.setenv(FLAG, "1")
    pages: list[list[dict]] = [
        [dict(_real_card(), subjectRFCode="77", id=f"p{page}_{n}") for n in range(10)]
        for page in range(3)
    ] + [[]]
    seen_pages: list[int] = []

    def fake(self, page: int, **_):
        seen_pages.append(page)
        return {"content": pages[page] if page < len(pages) else []}

    monkeypatch.setattr(TorgiGovAdapter, "_fetch_page", fake)
    adapter = TorgiGovAdapter()
    lots = list(adapter.discover_moscow())
    assert len(lots) == 30, adapter.last_report
    assert seen_pages[:4] == [0, 1, 2, 3]
    # Просили пятьдесят, приходит десять — это видно числом, а не по логу.
    assert adapter.last_report["cards_per_page"] == 10


def test_the_envelope_says_where_the_pages_end(monkeypatch) -> None:
    """Конец выборки объявляет ответ, а не наша догадка о размере."""
    import auction_search.adapters.torgi_gov as mod
    monkeypatch.setenv(FLAG, "1")
    asked: list[int] = []

    def fake(self, page: int, **_):
        asked.append(page)
        return {"content": [dict(_real_card(), subjectRFCode="77", id=f"x{page}")],
                "totalPages": 2, "totalElements": 2}

    monkeypatch.setattr(TorgiGovAdapter, "_fetch_page", fake)
    adapter = TorgiGovAdapter()
    lots = list(adapter.discover_moscow())
    assert asked == [0, 1], asked
    assert len(lots) == 2
    assert adapter.last_report["total_elements"] == 2


def test_a_standing_page_number_is_caught(monkeypatch) -> None:
    """Сервис, игнорирующий `page`, вернул бы свои карточки сорок раз.

    Список выглядел бы полным, а счётчики карточек выросли бы в сорок раз.
    Повтор ловится до разбора, поэтому и числа остаются честными.
    """
    import auction_search.adapters.torgi_gov as mod
    monkeypatch.setenv(FLAG, "1")
    monkeypatch.setattr(TorgiGovAdapter, "_fetch_page",
                        lambda self, page, **_: {"content": [dict(_real_card(), subjectRFCode="77", id="same")]})
    adapter = TorgiGovAdapter()
    lots = list(adapter.discover_moscow())
    assert [lot.source.external_lot_id for lot in lots] == ["same"]
    assert adapter.last_report["pages"] == 1
    assert "нумерация страниц не двигается" in adapter.last_report["reason"]


def test_the_working_request_carries_no_region_parameter() -> None:
    """Параметр, ухудшающий выдачу, — не безобидный.

    Проба с ядра 25.08.2026: контрольный запрос БЕЗ параметра дал одну
    московскую карточку из десяти (регионы 50 и 69), а `dynSubjRF=77,50` — ни
    одной, зато регионы 47 и 76. Сервис его не игнорирует: он понимает его как
    что-то своё и отдаёт другой срез.

    Я прочитал ту пробу как «ни один не фильтрует» и оставил параметр в сборе
    «вдруг заработает». Итог на проде: сорок страниц, четыреста карточек, наших
    ноль — прочитали честно, спросили не то.
    """
    adapter = TorgiGovAdapter()
    working = adapter._search_url(0)
    assert "dynSubjRF" not in working, working
    for name in ("subjectRFCode", "subjectRF", "subjectRFList", "dynSubjRFCode"):
        assert name not in working, name
    # Контрольный запрос пробы и рабочий — один и тот же адрес: проба обязана
    # проверять то, что потом пойдёт в дело.
    assert adapter._search_url(0, None) == working


def test_the_probe_still_tries_the_candidates() -> None:
    """Убрать параметр из сбора — не то же самое, что перестать искать имя."""
    adapter = TorgiGovAdapter()
    assert "dynSubjRF=" in adapter._search_url(0, "dynSubjRF")
    assert len(REGION_PARAM_CANDIDATES) >= 5
