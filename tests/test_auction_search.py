from auction_search.adapters.lot_online import LotOnlineAdapter
from auction_search.classifier import classify_lot
from auction_search.developaid_mapper import build_developaid_seed
from auction_search.krt import extract_krt_obligations, extract_krt_program
from auction_search.models import AuctionLot, AuctionSource, LotKind, SourceKind
from auction_search.service import AuctionSearchService


def source():
    return AuctionSource(
        platform=SourceKind.LOT_ONLINE,
        lot_url="https://catalog.lot-online.ru/example",
        external_lot_id="RAD-TEST",
        fetched_at="2026-08-21T18:00:00Z",
    )


def test_classifier_krt_overrides_generic_land_wording():
    assert classify_lot("Земельные участки. Право на заключение договора о комплексном развитии территории") == LotKind.KRT


def test_generic_right_to_lease_is_not_krt():
    assert classify_lot("Право на заключение договора аренды земельного участка") == LotKind.LAND_LEASE


def test_small_ijs_is_filtered_out():
    lot = AuctionLot(
        source=source(),
        lot_kind=LotKind.LAND_SALE,
        title="Участок",
        land_area_sqm=900,
        permitted_use="ИЖС",
    )
    assert AuctionSearchService.is_development_relevant(lot) is False


def test_legacy_50_cadastral_prefix_is_not_excluded_for_moscow():
    lot = AuctionLot(
        source=source(),
        lot_kind=LotKind.LAND_SALE,
        title="Коммунарка",
        land_area_sqm=173_494,
        cadastral_numbers=["50:21:0120316:1221"],
        permitted_use="Многофункциональные общественные центры",
        address="Москва, Коммунарка",
    )
    assert AuctionSearchService.is_development_relevant(lot) is True


def test_rad_public_offer_schedule_is_structured():
    # Same official table shape as the Kommunarka RAD lot; no network in unit test.
    text = (
        "Время начала периода, начала приема заявок Время окончания приема заявок "
        "Время окончания периода Величина изменения Предложение Сумма задатка Время внесения задатка "
        "22.07.2026 00:00 27.08.2026 14:00 31.08.2026 00:00 "
        "0.00 1 100 250 000.00 165 037 500.00 27.08.2026 14:00 "
        "31.08.2026 00:00 01.09.2026 14:00 05.09.2026 00:00 "
        "79 438 050.00 1 020 811 950.00 153 121 792.50 01.09.2026 14:00"
    )
    periods = LotOnlineAdapter._price_schedule(
        text,
        lot_url="https://catalog.lot-online.ru/test",
        fetched_at="2026-08-21T18:00:00Z",
    )
    assert len(periods) == 2
    assert periods[0].price_rub == 1_100_250_000
    assert periods[0].deposit_rub == 165_037_500
    assert periods[0].application_deadline.startswith("2026-08-27T14:00")
    assert periods[1].price_rub == 1_020_811_950


def test_krt_program_is_separate_from_investor_obligation():
    text = ["Предельная площадь жилой застройки составляет 180 000 кв. м."]
    program = extract_krt_program(
        text,
        source_url="https://official-etp.example/lot/1",
        source_document="Решение КРТ.pdf",
        fetched_at="2026-08-21T18:00:00Z",
    )
    obligations = extract_krt_obligations(
        text,
        source_url="https://official-etp.example/lot/1",
        source_document="Решение КРТ.pdf",
        fetched_at="2026-08-21T18:00:00Z",
    )
    assert program
    assert program[0].category == "housing"
    assert program[0].area_sqm == 180_000
    assert obligations == []


def test_krt_obligation_keeps_source_provenance():
    text = ["Инвестор обязан построить общеобразовательную школу на 775 мест и передать объект городу Москве безвозмездно."]
    items = extract_krt_obligations(
        text,
        source_url="https://official-etp.example/lot/1",
        source_document="Проект договора КРТ.pdf",
        fetched_at="2026-08-21T18:00:00Z",
    )
    assert items
    assert items[0].quantity == 775
    assert items[0].provenance.source_document == "Проект договора КРТ.pdf"
    assert items[0].estimated_cost_rub is None
    assert items[0].transfer_free_of_charge is True
    assert items[0].recipient == "город Москва"


def test_krt_mapper_does_not_replace_terms_with_glavapu():
    lot = AuctionLot(source=source(), lot_kind=LotKind.KRT, title="КРТ Тест")
    seed = build_developaid_seed(lot)
    assert seed["krt"]["tep_source_policy"] == "official_krt_documents"
    assert seed["krt"]["glavapu_role"] == "validation_only"


def test_ordinary_land_does_not_autoinsert_vri_payment():
    lot = AuctionLot(source=source(), lot_kind=LotKind.LAND_SALE, title="Обычная продажа")
    seed = build_developaid_seed(lot)
    assert seed["ordinary_land"]["vri_change_payment_rub"] is None
