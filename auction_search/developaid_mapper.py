from __future__ import annotations

from dataclasses import asdict

from auction_search.krt import obligation_cost_items
from auction_search.models import AuctionLot, LotKind


def build_developaid_seed(lot: AuctionLot) -> dict:
    """Build a conservative seed for the existing DevelopAid project flow.

    Auction facts and DevelopAid assumptions are intentionally separated.
    No ГлавАПУ-derived KRT obligations are created here.
    """
    acquisition = {
        "source_type": "official_etp",
        "source_platform": lot.source.platform.value,
        "source_url": lot.source.lot_url,
        "external_lot_id": lot.source.external_lot_id,
        "legal_structure": lot.lot_kind.value,
        "start_price_rub": lot.start_price_rub,
        "current_price_rub": lot.current_price_rub,
        "min_price_rub": lot.min_price_rub,
        "deposit_rub": lot.deposit_rub,
        "bid_step_rub": lot.bid_step_rub,
        "application_deadline": lot.application_deadline,
        "auction_date": lot.auction_date,
    }
    site = {
        "address": lot.address,
        "cadastral_numbers": list(lot.cadastral_numbers),
        "land_area_sqm": lot.land_area_sqm,
        "permitted_use_as_published": lot.permitted_use,
    }
    seed = {
        "project_name": lot.title,
        "auction": acquisition,
        "site": site,
        "source_documents": [asdict(d) for d in lot.documents],
        "provenance": {k: asdict(v) for k, v in lot.provenance.items()},
        "assumptions": {},
    }
    if lot.lot_kind == LotKind.KRT:
        seed["krt"] = {
            "development_program": [asdict(item) for item in lot.krt_program],
            "obligations": [asdict(o) for o in lot.obligations],
            "cost_candidates": obligation_cost_items(lot.obligations),
            "document_extraction_complete": bool(lot.raw.get("krt_extraction_complete")),
            "document_warnings": list(lot.raw.get("krt_document_warnings") or []),
            "tep_source_policy": "official_krt_documents",
            "glavapu_role": "validation_only",
            "revenue_policy": "derive_from_official_program_then_apply_explicit_sellability_assumptions",
            "cost_policy": "price_only_explicit_investor_obligations_with_developaid_norms",
        }
    else:
        seed["ordinary_land"] = {
            "published_vri_is_base_case": True,
            "vri_change_payment_rub": None,
            "vri_change_policy": "calculate_only_if_model_assumes_change_after_acquisition",
        }
    return seed
