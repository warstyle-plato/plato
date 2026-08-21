from auction_search.classifier import classify_lot
from auction_search.developaid_mapper import build_developaid_seed
from auction_search.krt import extract_krt_obligations
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


def test_krt_mapper_does_not_replace_terms_with_glavapu():
    lot = AuctionLot(source=source(), lot_kind=LotKind.KRT, title="КРТ Тест")
    seed = build_developaid_seed(lot)
    assert seed["krt"]["tep_source_policy"] == "official_krt_documents"
    assert seed["krt"]["glavapu_role"] == "validation_only"


def test_ordinary_land_does_not_autoinsert_vri_payment():
    lot = AuctionLot(source=source(), lot_kind=LotKind.LAND_SALE, title="Обычная продажа")
    seed = build_developaid_seed(lot)
    assert seed["ordinary_land"]["vri_change_payment_rub"] is None
