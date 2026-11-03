"""ТЭП площадки лежит в самом проекте решения, и мы его читаем.

«Появились новые КРТ… При этом на самом mos.ru уже появилось pdf решения! А мы
его не видим и пишем в блоке КРТ что 0» (владелец, 04.09.2026). Он прав: у
площадки, карточки которой в каталоге ещё нет, единственные цифры лежат в PDF
решения — площадь территории, предельная (максимальная) суммарная поэтажная
площадь, площадь квартир, нежилая наземная площадь. Мы читали только заголовок.

Образцы — настоящие документы mos.ru, снятые 04.09.2026 (не пересказ: разбор
писан по живым ответам, а не по догадке о формулировках). Проверяются три
находки, каждая из которых стоила отдельного захода по 49 документам.

Запуск: python3 -m pytest tests/test_the_decision_carries_the_tep.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from market_search import krt_decision_tep as tep  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _decision(document_id: str) -> str:
    return (FIXTURES / f"krt_decision_{document_id}.txt").read_text(encoding="utf-8")


def test_the_document_gives_the_numbers_the_catalogue_lacks():
    """Большой Тишинский пер., влд. 8: площадка без карточки, но с цифрами."""
    out = tep.parse(_decision("347614220"))
    assert out["read"] is True
    assert out["area_ha"] == 0.28
    assert out["total_gfa_sqm"] == 9_800
    assert out["flats_sqm"] == 5_954
    assert out["nonresidential_ground_sqm"] == 662
    # «В том числе объектов жилого назначения – 9 800 кв.м»: назначение стоит
    # ПОСЛЕ величины, и без разбора этой части площадка выглядела нежилой.
    assert out["housing_gfa_sqm"] == 9_800


def test_the_purpose_inside_the_formula_decides_what_the_number_is():
    """Жилая СПП — это «Жилое назначение» каталога, а площадь квартир — нет.

    На 2-м Лихачевском жилая СПП 50 400 м² совпала с колонкой каталога до
    метра, а площадь квартир в том же документе — 30 304 м². Сложить их под
    одним именем значит завести третье число, которого нет ни у кого.
    """
    out = tep.parse(_decision("336775220"))
    assert out["housing_gfa_sqm"] == 50_400
    assert out["total_gfa_sqm"] == 50_400
    assert out["flats_sqm"] == 30_304
    assert out["flats_sqm"] != out["housing_gfa_sqm"]


def test_zones_are_parts_and_they_add_up():
    """У «Родников» две зоны: 3 020 и 126 110 м². Целое — их сумма."""
    out = tep.parse(_decision("345981220"))
    assert out["parts"]["spp_unnamed"] == 2
    assert out["total_gfa_sqm"] == 129_130
    assert out["area_ha"] == 22.69, "площадь потеряна на «подлеж ат территори и»"


def test_a_stated_zero_is_an_answer_and_not_a_silence():
    """КРТ под улично-дорожную сеть: предельная СПП – 0 кв.м.

    Отфильтровать ноль как «не нашли» значит показать «не знаем» там, где город
    сказал «строить нельзя».
    """
    out = tep.parse(_decision("346146220"))
    assert out["total_gfa_sqm"] == 0
    assert out["read"] is True
    assert out["housing_gfa_sqm"] is None, "не названное назначение — не ноль"


def test_a_silent_document_says_nothing_rather_than_zero():
    out = tep.parse("Проект решения без единого параметра.")
    assert out["read"] is False
    assert out["total_gfa_sqm"] is None
    assert out["area_ha"] is None


def test_the_hectares_are_the_self_check_of_the_pair():
    """Гектары решения против гектаров карточки: расходятся — пара неверна.

    На выборке из 26 сопоставленных площадок метры расходились ровно там, где
    расходилась площадь территории. Сверка не чинит расхождение — она не даёт
    выдать одно за другое.
    """
    out = tep.parse(_decision("337332220"))
    same = tep.catalogue_check(out, {"area_ha": out["area_ha"],
                                     "total_gfa_sqm": out["total_gfa_sqm"],
                                     "housing_gfa_sqm": out["housing_gfa_sqm"]})
    assert same["problems"] == []
    other = tep.catalogue_check(out, {"area_ha": 0.93, "total_gfa_sqm": 51_040})
    assert any("площадь территории" in one for one in other["problems"]), other
    assert any("общий объём" in one for one in other["problems"]), other
    # Нечего сверять — не «сошлось», и раньше это было написано здесь словами,
    # а утверждалось обратное: обе ветки возвращали пустой список. Различает их
    # состав сверенного, и на экране это два разных ответа.
    empty = tep.catalogue_check(out, {})
    assert empty["problems"] == [] and empty["compared"] == [], empty
    assert empty != same


def test_the_decision_housing_matches_the_catalogue_column():
    """Ул. Стромынка: «в том числе объектов жилого назначения – 179 150 кв.м».

    Это ровно колонка «Жилое назначение» каталога — на ней разбор и сверен.
    """
    out = tep.parse(_decision("337332220"))
    assert out["total_gfa_sqm"] == 197_550
    assert out["housing_gfa_sqm"] == 179_150


def test_the_registry_reads_the_pdf_once_and_keeps_the_numbers(tmp_path):
    """Документ опубликован и не меняется — перечитывать его сутками незачем.

    Отказ при этом ЗАПИСЫВАЕТСЯ со своим коротким сроком: неотвеченный документ
    иначе не становится «известным» никогда, и посчитать, что не отвечает НИ
    ОДИН, нечем — та же беда, что была с карточками города.
    """
    import json

    from market_search.krt_registry import KrtRegistry

    text = _decision("347614220")
    asked: list[str] = []

    def fetch(url: str) -> bytes:
        asked.append(url)
        if "/documents/347614220" in url and "attachments" not in url:
            return json.dumps({"id": 347614220, "institution_id": 19180090}).encode()
        if "attachments" in url or "institution" in url:
            return json.dumps({"items": [{"attachments": [
                {"url": "/upload/documents/files/x.pdf", "name": "решение"}]}]}).encode()
        return b"%PDF-1.4 fake"

    registry = KrtRegistry(tmp_path, fetch=fetch)
    # PDF разбирается штатным читателем; здесь подменяется только он, потому
    # что настоящий PDF в репозиторий не кладут — в тестах живёт его текст.
    import market_search.krt_registry as module

    original = module.pdf_text
    module.pdf_text = lambda data: text
    try:
        first = registry.decision_tep("347614220")
        rounds = len(asked)
        second = registry.decision_tep("347614220")
    finally:
        module.pdf_text = original

    assert first["available"] is True and first["total_gfa_sqm"] == 9_800
    assert second == first
    assert len(asked) == rounds, "документ перечитан, хотя он уже разобран"
    assert registry.decision_tep_coverage(["347614220", "111111111"]) == {
        "read": 1, "failed": 0, "unknown": 1, "silent": 0, "reasons": {}}


def test_a_refusal_is_remembered_and_named(tmp_path):
    from market_search.krt_registry import KrtRegistry

    def fetch(url: str) -> bytes:
        raise OSError("connection reset")

    registry = KrtRegistry(tmp_path, fetch=fetch)
    out = registry.decision_tep("347614220")
    assert out["available"] is False
    assert "не указан орган публикации" in out["reason"]
    coverage = registry.decision_tep_coverage(["347614220"])
    assert coverage["failed"] == 1 and coverage["unknown"] == 0
    assert coverage["reasons"], "отказ посчитан, но не назван"


def test_the_route_puts_the_decision_numbers_into_the_row():
    """Прочитанное решение доезжает до строки каталога, а не остаётся на диске.

    «Посчитанное на сервере, но прочитанное только из свежего нажатия,
    неотличимо от непосчитанного» — правило уже стоило нам пустой колонки
    занятости. Здесь оно проверяется на маршруте: строка без карточки несёт
    цифры своего решения, строка с карточкой — названное расхождение с ним.
    """
    from types import SimpleNamespace

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from auction_search.api import install

    catalogue = [{"slug": "site", "name": "Площадка", "status": "Планируемый",
                  "okrug": "ЦАО", "area_ha": 0.93, "total_gfa_sqm": 51_040}]
    decisions = {
        "total": 2, "matched": 1, "complete": True,
        "decisions": [{"id": "347614220", "title": "Проект решения",
                       "url": "https://www.mos.ru/dgp/documents/view/347614220/",
                       "address": "Большой Тишинский пер., влд. 8", "okrug": "ЦАО",
                       "kind": "нежилой застройки", "published_at": 1_787_605_200}],
        "matched_rows": [{"slug": "site", "id": "339017220", "published_at": 1,
                          "url": "https://www.mos.ru/dgp/documents/view/339017220/"}],
        "tep": {
            "347614220": {"available": True, "read": True, "area_ha": 0.28,
                          "total_gfa_sqm": 9_800.0, "housing_gfa_sqm": 9_800.0,
                          "flats_sqm": 5_954.0, "pdf_url": "https://www.mos.ru/x.pdf"},
            "339017220": {"available": True, "read": True, "area_ha": 1.35,
                          "total_gfa_sqm": 90_280.0},
        },
        "tep_coverage": {"read": 2, "failed": 0, "unknown": 3, "silent": 0, "reasons": {}},
        "tep_pending": ["111", "222", "333"],
    }
    filled: list[list[str]] = []
    app = FastAPI()
    app.state.market_discovery_service = SimpleNamespace(
        krt=SimpleNamespace(
            catalogue=lambda **_: list(catalogue),
            status=lambda: {"complete": True, "refreshing": False},
            decisions=lambda **_: dict(decisions),
            fill_decision_tep_in_background=lambda ids, **_: filled.append(list(ids)),
        ),
    )
    install(app)
    answer = TestClient(app).get("/auctions/krt")
    assert answer.status_code == 200
    rows = {row["slug"]: row for row in answer.json()["projects"]}

    draft = rows["decision:347614220"]
    assert draft["total_gfa_sqm"] == 9_800 and draft["housing_gfa_sqm"] == 9_800
    assert draft["area_ha"] == 0.28 and draft["flats_sqm"] == 5_954
    assert draft["tep_source"] == "decision", "источник цифр не назван"
    assert draft["status_kind"] == "draft" and not draft["status"]

    # Карточка сильнее: её числа остаются, а расхождение с решением названо.
    card = rows["site"]
    assert card["total_gfa_sqm"] == 51_040, "решение подменило собой каталог"
    check = card["decision_tep_check"]
    assert any("площадь территории" in one for one in check["problems"]), card
    # Что сверено и было ли что сверять — часть ответа: без этого «сошлось» и
    # «сверять не с чем» на экране звучали бы одинаково.
    assert "площадь территории" in check["compared"] and check["read"] is True, card
    assert card["draft_decision_at"] == 1

    assert answer.json()["decision_tep_state"]["unknown"] == 3
    assert filled == [["111", "222", "333"]], "недостающие решения не дочитываются"


def test_the_same_document_answers_whose_krt_it_is(tmp_path):
    """Скачали PDF ради ТЭП — «чьё это КРТ» берётся оттуда же, а не вторым разом.

    У площадки без карточки требований не существует, и блок «Чьё это КРТ»
    писал «проект решения ещё не прочитан» при уже прочитанном решении.
    """
    import json

    import market_search.krt_registry as module
    from market_search.krt_registry import KrtRegistry

    text = _decision("337332220")
    title = ("Проект решения о комплексном развитии территории нежилой застройки "
             "города Москвы, расположенной по адресу: г. Москва, Ул. Стромынка (ВАО)")

    def fetch(url: str) -> bytes:
        if "attachments" in url or "institution" in url:
            return json.dumps({"items": [{"attachments": [
                {"url": "/upload/x.pdf", "name": "решение"}]}]}).encode()
        if "/documents/337332220" in url:
            return json.dumps({"id": 337332220, "institution_id": 19180090,
                               "title": title}).encode()
        return b"%PDF fake"

    original = module.pdf_text
    module.pdf_text = lambda data: text
    try:
        out = KrtRegistry(tmp_path, fetch=fetch).decision_tep("337332220")
    finally:
        module.pdf_text = original

    assert out["intent"]["decision_read"] is True
    assert out["intent"]["kind"] == "нежилой застройки"
    assert out["intent"]["city_needs"], "Программа реновации в решении названа и потеряна"
    # ТЭП при этом на месте: намерение читается тем же текстом, а не вместо него.
    assert out["housing_gfa_sqm"] == 179_150
