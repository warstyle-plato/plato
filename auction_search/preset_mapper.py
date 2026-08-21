from __future__ import annotations

from dataclasses import asdict
from typing import Any

from auction_search.models import AuctionLot, KrtObligation, KrtProgramItem, LotKind


TBD = "TBD"


def _price_mln(lot: AuctionLot) -> float | None:
    value = lot.current_price_rub if lot.current_price_rub is not None else lot.start_price_rub
    return None if value is None else float(value) / 1_000_000.0


def _provenance_note(item: KrtProgramItem | KrtObligation) -> str:
    source = item.provenance.source_document if item.provenance else ""
    return f"Источник: {source}. {item.source_text or item.title}".strip()


def _social_capacity(title: str, quantity: float | None) -> dict[str, float] | None:
    if not quantity:
        return None
    low = title.lower()
    if "школ" in low or "общеобразоват" in low:
        return {"total_places": quantity, "school_places": quantity, "preschool_places": 0}
    if "доу" in low or "детск" in low or "дошколь" in low:
        return {"total_places": quantity, "school_places": 0, "preschool_places": quantity}
    return None


def _program_object(item: KrtProgramItem, index: int) -> tuple[dict[str, Any] | None, str | None]:
    """Map only unambiguous KRT program items into the existing preset products.

    Existing project_preset semantics are intentionally respected: a generic
    non-residential object becomes an office. Therefore ambiguous public-business,
    retail and industrial KRT lines are kept as open items instead of being silently
    forced into the wrong revenue product.
    """
    base = {
        "id": f"KRT_{index:03d}",
        "name": item.title[:180],
        "in_deal_perimeter": True,
        "mandatory_for_project": True,
        "source_note": _provenance_note(item),
    }
    area = float(item.area_sqm) if item.area_sqm is not None else None

    if item.category == "housing" and area:
        base.update({
            "gfa_m2": area,
            "residential_part_m2": area,
            "embedded_nonresidential_m2": 0,
            "building_type": "residential_from_krt",
        })
        return base, None

    if item.category == "office" and area:
        base.update({"gfa_m2": area, "building_type": "office_from_krt"})
        return base, None

    if item.category == "parking" and area:
        # project_preset recognises a stand-alone parking object by its name.
        base["name"] = "Гараж / паркинг · " + item.title[:150]
        base.update({"gfa_m2": area, "building_type": "parking_from_krt"})
        return base, None

    if item.category == "social":
        capacity = _social_capacity(item.title, item.quantity)
        if capacity:
            base.update({
                "gfa_m2": area or 0,
                "capacity": capacity,
                "cost_classification": "mandatory_social_construction",
                "construction_capex_in_project": True,
            })
            return base, None

    reason = (
        f"КРТ: требуется классифицировать продукт «{item.category}»: {item.title}. "
        "DevelopAid не подменяет условия КРТ предположением о типе продаваемой площади."
    )
    return None, reason


def _obligation_reference(item: KrtObligation) -> dict[str, Any]:
    return {
        "category": item.category,
        "title": item.title,
        "quantity": item.quantity,
        "unit": item.unit,
        "due_date": item.due_date,
        "executor": item.executor,
        "recipient": item.recipient,
        "transfer_free_of_charge": item.transfer_free_of_charge,
        "estimated_cost_rub": item.estimated_cost_rub,
        "source": asdict(item.provenance) if item.provenance else None,
    }


def build_project_preset(lot: AuctionLot) -> dict[str, Any]:
    """Convert an official auction lot into the existing DevelopAid preset v4.

    This is an import envelope, not a second model. Auction price is supplied as a
    prefilled `purchase_price_mln` for the existing `/api/project-presets/import`
    flow. Unknown TEP/product/cost fields remain explicit open items.
    """
    price_mln = _price_mln(lot)
    objects: list[dict[str, Any]] = []
    open_items: list[str] = []

    if lot.lot_kind == LotKind.KRT:
        if not lot.krt_program:
            open_items.append(
                "КРТ: программа застройки не извлечена. Нельзя запускать финансовый расчёт как полный до разбора решения/договора КРТ."
            )
        for index, item in enumerate(lot.krt_program, start=1):
            obj, problem = _program_object(item, index)
            if obj:
                objects.append(obj)
            if problem:
                open_items.append(problem)
        for obligation in lot.obligations:
            if obligation.estimated_cost_rub is None and obligation.category in {
                "social", "transport", "engineering", "demolition", "resettlement",
                "planning", "landscaping", "payment", "land",
            }:
                open_items.append(
                    f"КРТ: определить стоимость исполнения обязательства «{obligation.title}»; факт обязательства взят с ЭТП, стоимость должна дать база DevelopAid."
                )
        if lot.raw.get("krt_auth_required"):
            open_items.append(
                "КРТ: часть официальной документации требует авторизации на ЭТП; до получения документов обязательства считаются неполными."
            )
    else:
        open_items.append(
            "ТЭП не заданы условиями торгов в структурированном виде: после импорта получить/проверить их штатным кадастровым и градостроительным контуром DevelopAid."
        )

    cadastral_csv = ", ".join(lot.cadastral_numbers)
    area_ha = float(lot.land_area_sqm or 0) / 10_000.0 if lot.land_area_sqm else None
    legal = {
        LotKind.LAND_SALE: "продажа земельного участка",
        LotKind.LAND_LEASE: "право аренды земельного участка",
        LotKind.KRT: "право заключения договора КРТ",
        LotKind.PROPERTY_COMPLEX: "имущественный комплекс",
        LotKind.UNFINISHED: "объект незавершённого строительства",
    }.get(lot.lot_kind, lot.lot_kind.value)

    preset: dict[str, Any] = {
        "schema_version": "developaid.project_preset.v4",
        "project": {
            "name": f"Торги · {lot.title[:180]}",
            "region": "Москва",
            "status": "auction screening",
            "currency": "RUB",
            "address": lot.address or "",
            "site_area_ha": area_ha,
            "land_area_ha": area_ha,
            "cadastral_numbers": list(lot.cadastral_numbers),
            "cadastral_numbers_input": cadastral_csv,
            "cadastral_import": {
                "enabled": bool(lot.cadastral_numbers),
                "mode": "bulk" if len(lot.cadastral_numbers) > 1 else "single",
                "autofetch_after_import": True,
                "deduplicate": True,
                "source": lot.source.source_name,
                "note": "Кадастровые номера опубликованы официальной ЭТП; после импорта проверяются штатным контуром DevelopAid.",
            },
        },
        "land": {
            "ownership": legal,
            "area_ha": area_ha,
            "cadastral_numbers": list(lot.cadastral_numbers),
            "cadastral_numbers_csv": cadastral_csv,
            "published_permitted_use": lot.permitted_use,
            "bulk_fetch_required": bool(lot.cadastral_numbers),
        },
        "source_priority": [
            f"официальная карточка торгов: {lot.source.source_name}",
            "официальные документы, приложенные к карточке ЭТП",
            "после импорта — штатная градостроительная проверка DevelopAid",
        ],
        "sources": {
            "auction_card": lot.source.lot_url,
            "auction_platform": lot.source.source_name,
            "auction_lot_id": lot.source.external_lot_id,
            "documents": [
                {"title": doc.title, "url": doc.url, "type": doc.document_type, "access_status": doc.access_status}
                for doc in lot.documents
            ],
        },
        "planning": {
            "ppt_gfa_total_m2": sum(float(obj.get("gfa_m2") or 0) for obj in objects),
            "objects": objects,
        },
        "transaction": {
            "type": legal,
            "start_price_rub": lot.start_price_rub,
            "current_price_rub": lot.current_price_rub,
            "minimum_price_rub": lot.min_price_rub,
            "deposit_rub": lot.deposit_rub,
            "application_deadline": lot.application_deadline,
            "auction_date": lot.auction_date,
            "source": lot.source.lot_url,
        },
        # `purchase_price_mln` is also repeated in auction_import.filled_inputs:
        # existing project_preset v4 historically did not map acquisition price
        # from economics, while the import API already accepts explicit filled fields.
        "economics": {
            "purchase_price_mln": price_mln if price_mln is not None else TBD,
            "origins": {"purchase_price_mln": "source"},
        },
        "auction_import": {
            "filled_inputs": ({"purchase_price_mln": price_mln} if price_mln is not None else {}),
            "source_url": lot.source.lot_url,
            "legal_structure": lot.lot_kind.value,
            "price_basis": "current_price_rub" if lot.current_price_rub is not None else "start_price_rub",
        },
        "krt": {
            "source_of_truth": "official_etp_documents",
            "glavapu_role": "validation_only",
            "development_program": [asdict(item) for item in lot.krt_program],
            "obligations": [_obligation_reference(item) for item in lot.obligations],
        } if lot.lot_kind == LotKind.KRT else {},
        "open_items": open_items,
        "import_rules": {
            "no_silent_inference": True,
            "do_not_replace_krt_terms_with_glavapu": lot.lot_kind == LotKind.KRT,
            "ordinary_land_vri_payment": "calculate_only_if_post_acquisition_vri_change_is_explicitly_modeled",
        },
        "validation_controls": {
            "auction_source_is_official_etp": True,
            "krt_documents_complete": lot.raw.get("krt_extraction_complete") if lot.lot_kind == LotKind.KRT else None,
            "krt_auth_required": bool(lot.raw.get("krt_auth_required")) if lot.lot_kind == LotKind.KRT else None,
        },
    }
    return preset
