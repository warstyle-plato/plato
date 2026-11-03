"""Район участка и его положение относительно ТТК — один владелец.

Прежде на этот вопрос отвечали двое. Норма приобъектной парковки читала
`_glavapu_import.territory`, которую страница не сохраняет. Поэтому ступень
«К2 по району из разбора кадастра», обещанная подписью поля, в живом проекте
не срабатывала. Льготы ВРИ (`vri_benefits`) читали разбор кадастра, но
вписанное человеком ставили ниже документа, а паркинг — выше. При ручном
«за ТТК» и разборе «внутри» парковка и льгота за МПТ считали бы разные
участки.

Правило одно (решение владельца, 10.10.2026): вписанное человеком главнее, и
расчёт идёт по нему. Но ручное «наоборот» чаще всего ошибка, а ошибочное «за
ТТК» даёт льготу за МПТ, которой нет. Поэтому противоречие с документом не
молчит: оно уходит в `conflicts` с обоими значениями и источником, и каждая
поверхность, где положение меняет число, показывает его красным. Истинный
случай тоже бывает: территория из участков по обе стороны ТТК, а разбор даёт
один признак на всю территорию.

Отсутствие — не «за ТТК». Если ГлавАПУ на вопрос о кольце не ответил
(`inside_ttc_known` = False), признака нет, и читатель называет это прямо.
"""
from __future__ import annotations

from typing import Any

MANUAL_TTK_KEY = "parking_inside_ttk"
MANUAL_DISTRICT_KEY = "parking_district"
MANUAL_SOURCE = "вписано в проекте"
ANALYSIS_SOURCE = "разбор кадастра (ГлавАПУ, insideTTC)"
ANALYSIS_DISTRICT_SOURCE = "разбор кадастра"
IMPORT_SOURCE = "выгрузка ГлавАПУ"

_INSIDE = {"inside", "true", "1", "да", "внутри"}
_OUTSIDE = {"outside", "false", "0", "нет", "вне", "за"}


def manual_ttk(value: Any) -> bool | None:
    """Ручной признак: «inside» / «outside» из поля или bool из API.

    Пустое поле — «считать по документу», а не «за ТТК».
    """
    if isinstance(value, bool):
        return value
    text = str(value if value is not None else "").strip().lower()
    if text in _INSIDE:
        return True
    if text in _OUTSIDE:
        return False
    return None


def _document_ttk(territory: dict[str, Any]) -> bool | None:
    if "inside_ttc" not in territory:
        return None
    # Ключ стоит всегда, а ответ ГлавАПУ — не всегда: без `inside_ttc_known`
    # bool(None) читался бы как «за кольцом».
    if territory.get("inside_ttc_known") is False:
        return None
    value = territory.get("inside_ttc")
    return None if value is None else bool(value)


def _same_district(a: str, b: str) -> bool:
    def key(name: str) -> str:
        text = name.lower().replace("ё", "е")
        for word in ("район", "муниципальный округ", "поселение"):
            text = text.replace(word, " ")
        return " ".join(text.replace("-", " ").split())
    return key(a) == key(b)


def _ttk_label(value: bool) -> str:
    return "внутри ТТК" if value else "за ТТК"


def site_position(inputs: dict[str, Any] | None) -> dict[str, Any]:
    """Район, ТТК, кадастровый номер и квартал участка — с происхождением.

    Ответ: `district` / `district_source`, `inside_ttc` (True / False / None)
    / `ttk_source`, `cadastral`, `quarter`, `conflicts` — список
    {field, manual, document, document_source, text}.
    """
    inputs = inputs or {}
    analysis = inputs.get("_cadastral_analysis") or {}
    analysed = analysis.get("territory") or {}
    imported = inputs.get("_glavapu_import") or {}
    imported_territory = imported.get("territory") or {}
    normalized = imported.get("normalized") or {}

    doc_ttk, doc_ttk_source = _document_ttk(analysed), ANALYSIS_SOURCE
    if doc_ttk is None:
        doc_ttk, doc_ttk_source = _document_ttk(imported_territory), IMPORT_SOURCE
    if doc_ttk is None:
        doc_ttk_source = ""

    doc_district, doc_district_source = "", ""
    for value, source in ((analysed.get("district"), ANALYSIS_DISTRICT_SOURCE),
                          (imported_territory.get("district"), IMPORT_SOURCE),
                          (normalized.get("district"), IMPORT_SOURCE)):
        text = str(value or "").strip()
        if text:
            doc_district, doc_district_source = text, source
            break

    hand_ttk = manual_ttk(inputs.get(MANUAL_TTK_KEY))
    hand_district = str(inputs.get(MANUAL_DISTRICT_KEY) or "").strip()

    conflicts: list[dict[str, Any]] = []
    if hand_ttk is not None and doc_ttk is not None and hand_ttk != doc_ttk:
        conflicts.append({
            "field": MANUAL_TTK_KEY, "manual": _ttk_label(hand_ttk),
            "document": _ttk_label(doc_ttk), "document_source": doc_ttk_source,
            "text": (f"Положение относительно ТТК вписано вручную — «{_ttk_label(hand_ttk)}», "
                     f"а {doc_ttk_source} даёт «{_ttk_label(doc_ttk)}». Расчёт идёт по "
                     "вписанному. Проверьте: если территория не лежит по обе стороны "
                     "кольца, это ошибка ввода."),
        })
    if hand_district and doc_district and not _same_district(hand_district, doc_district):
        conflicts.append({
            "field": MANUAL_DISTRICT_KEY, "manual": hand_district,
            "document": doc_district, "document_source": doc_district_source,
            "text": (f"Район вписан вручную — «{hand_district}», а {doc_district_source} "
                     f"даёт «{doc_district}». Расчёт идёт по вписанному."),
        })

    numbers = analysis.get("recognized") or analysis.get("requested") or []
    quarter = str(analysed.get("cadastral_quarter") or normalized.get("cadastral_quarter")
                  or "").strip()
    return {
        "district": hand_district or doc_district,
        "district_source": MANUAL_SOURCE if hand_district else doc_district_source,
        "inside_ttc": hand_ttk if hand_ttk is not None else doc_ttk,
        "ttk_source": MANUAL_SOURCE if hand_ttk is not None else doc_ttk_source,
        "cadastral": str(numbers[0]).strip() if numbers else quarter,
        "quarter": quarter,
        "conflicts": conflicts,
    }
