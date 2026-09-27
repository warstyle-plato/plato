"""Контур площадки-решения: её слаг — тоже слаг.

Площадка без карточки в реестре приезжает ключом `decision:<номер документа>`:
своего слага у неё нет вовсе. Сбор контура по перечню проекта решения сторожил
вход образцом `[a-zA-Z0-9_-]`, двоеточия не знавшим, — и 240 строк каталога из
522 получали «слаг площадки не задан» при заданном слаге. Ровно у них контур
собирается ТОЛЬКО по решению: в файле карты города их нет по построению
(владелец, 21.09.2026: «А почему на карте нет участков конкретных контуром раз
уж тут в PDF решения они указаны конкретно»).

Вторая половина того же пробела — дверь чтения: перечень брался `requirements`,
которая ищет площадку в каталоге по слагу, а площадки-решения там нет.

Запуск: python3 -m pytest tests/test_the_decision_site_gets_its_outline.py -q
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from market_search import krt_registry as registry_mod  # noqa: E402

SLUG = "decision:349135220"
DOCUMENT = "349135220"
# Четыре номера — из настоящего перечня проекта решения по ул. Архитектора
# Власова, влд. 59 (замер 21.09.2026: приложение PDF отдало ровно их).
NUMBERS = ["77:06:0003016:13", "77:06:0003016:32",
           "77:06:0003016:1000", "77:06:0003016:1023"]

SQUARE = [[[4179000, 7492000], [4179400, 7492000], [4179400, 7492400], [4179000, 7492400]]]
TRIANGLE = [[[4179400, 7492000], [4179800, 7492000], [4179800, 7492400]]]


def _egrn(asked: list[str]) -> list[dict]:
    answers = {
        "77:06:0003016:13": {"found": True, "kind": "land", "contour_merc": SQUARE,
                             "area_sqm": 20000.0},
        "77:06:0003016:32": {"found": True, "kind": "land", "contour_merc": TRIANGLE,
                             "area_sqm": 16600.0},
        "77:06:0003016:1000": {"found": True, "kind": "building", "contour_merc": SQUARE},
    }
    return [dict(answers.get(one, {"found": False}), cadastral_number=one) for one in asked]


def _registry(tmp_path, *, available=True, numbers=None):
    """Реестр, у которого решение ПРОЧИТАНО, а карточки в каталоге нет вовсе."""
    reg = registry_mod.KrtRegistry(tmp_path, fetch=lambda url: b"[]")

    def decision_requirements(document_id, refresh=False):
        assert document_id == DOCUMENT, "спрошен номер документа, а не слаг целиком"
        if not available:
            return {"available": False, "decision_available": False,
                    "reason": "mos_document_attachments: PDF не опубликован"}
        return {"available": True, "decision_available": True,
                "pdf_url": "https://www.mos.ru/upload/vlasov.pdf",
                "cadastral_numbers": list(NUMBERS if numbers is None else numbers),
                "cadastral_numbers_source": "appendix"}

    def find_decision(document_id):
        return {"slug": SLUG, "name": "ул. Архитектора Власова, влд. 59",
                "url": "https://www.mos.ru/dgp/documents/view/349135220/"}

    def catalogue_only(slug, refresh=False):
        raise AssertionError("площадку-решение искали в каталоге — её там нет")

    reg.decision_requirements = decision_requirements  # type: ignore[method-assign]
    reg.find_decision = find_decision  # type: ignore[method-assign]
    reg.requirements = catalogue_only  # type: ignore[method-assign]
    return reg


def test_the_decision_slug_is_a_slug(tmp_path) -> None:
    """Контур собирается, и подпись называет документ, из которого он собран."""
    reg = _registry(tmp_path)
    outline = reg.decision_outline(SLUG, lookup=_egrn)
    assert outline["problem"] == "", outline["problem"]
    assert outline["counts"] == {"numbers": 4, "asked": 4, "land": 2, "buildings": 1,
                                 "missing": 1}
    assert len(outline["rings_merc"]) == 2
    assert outline["area_ha"] == 3.66
    assert outline["decision"]["title"] == "ул. Архитектора Власова, влд. 59"
    assert outline["decision"]["page_url"].endswith("/349135220/")
    assert outline["decision"]["pdf_url"].endswith("vlasov.pdf")
    # Прочитанный контур виден и читателю карты, и фоновому дочитывателю: без
    # этого обзорная карта каждый раз считала бы площадку непрочитанной.
    assert (reg.outline_cached(SLUG) or {})["counts"]["land"] == 2
    assert reg.fill_outlines_in_background([SLUG], lookup=_egrn) is False


def test_an_empty_slug_is_still_refused_and_says_which_way_it_is(tmp_path) -> None:
    """Сторож не снят: пустое и непохожее отказываются, и отказы разные."""
    reg = _registry(tmp_path)
    assert reg.decision_outline("", lookup=_egrn)["problem"] == "слаг площадки не задан"
    dirty = reg.decision_outline("../../etc/passwd", lookup=_egrn)
    assert dirty["rings_merc"] == [] and "не похож на слаг" in dirty["problem"]
    assert reg.outline_cached("../../etc/passwd") is None
    assert reg.fill_outlines_in_background(["../../etc/passwd"], lookup=_egrn) is False
    # Ключ решения с чужим номером — тоже не слаг: двоеточие само по себе не пропуск.
    assert "не похож на слаг" in reg.decision_outline("decision:нет", lookup=_egrn)["problem"]


def test_an_unread_decision_names_its_own_reason(tmp_path) -> None:
    """Документ не прочитан — сказано, ЧЕМ он не прочитан, а не «не читаются»."""
    reg = _registry(tmp_path, available=False)
    outline = reg.decision_outline(SLUG, lookup=_egrn)
    assert outline["rings_merc"] == []
    assert "PDF не опубликован" in outline["problem"]
    # Подпись документа при непрочитанном решении не выдумывается.
    assert outline["decision"] == {"title": None, "page_url": None, "pdf_url": None}


def test_the_reading_door_is_chosen_in_one_place(tmp_path) -> None:
    """Дверь выбирает реестр, и маршруты торгов читают его, а не выбирают сами."""
    reg = _registry(tmp_path)
    assert reg.requirements_for(SLUG)["cadastral_numbers"] == NUMBERS
    # Каталожный слаг уходит каталожной дверью — стенд на ней падает нарочно.
    try:
        reg.requirements_for("varshavskoe-37")
    except AssertionError as exc:
        assert "в каталоге" in str(exc)
    else:  # pragma: no cover — дверь перепутана
        raise AssertionError("каталожный слаг ушёл дверью решения")
    source = (ROOT / "auction_search" / "api.py").read_text(encoding="utf-8")
    door = source[source.index("def _requirements_for("):]
    door = door[: door.index("def _asking_price_mln(")]
    assert 'getattr(krt_registry, "requirements_for"' in door
    route = source[source.index("async def auction_krt_requirements("):]
    route = route[: route.index("def _decision_outline_now(")]
    assert "_requirements_for" in route, "маршрут требований читает общую дверь"


def test_the_outline_does_not_ask_egrn_twice(tmp_path) -> None:
    """Второе открытие карточки ЕГРН не трогает: контур лежит на диске."""
    reg = _registry(tmp_path)
    calls: list[list[str]] = []

    def lookup(numbers):
        calls.append(list(numbers))
        return _egrn(numbers)

    first = reg.decision_outline(SLUG, lookup=lookup)
    again = reg.decision_outline(SLUG, lookup=lookup)
    assert again["rings_merc"] == first["rings_merc"] and len(calls) == 1
    stale = time.time() - reg.outline_ttl_seconds - 1
    import os

    os.utime(reg.outline_dir / f"{SLUG}.json", (stale, stale))
    reg.decision_outline(SLUG, lookup=lookup)
    assert len(calls) == 2
