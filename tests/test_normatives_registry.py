from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from starlette.requests import Request

import normatives_registry as registry

ROOT = Path(__file__).resolve().parents[1]


def _request(query: str = "") -> Request:
    return Request({
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "https",
        "path": "/normatives",
        "raw_path": b"/normatives",
        "query_string": query.encode("utf-8"),
        "headers": [],
        "client": ("test", 1),
        "server": ("developaid", 443),
    })


# Заглушка ОБЯЗАНА иметь сигнатуру настоящего гейта движка: `(session, key)`.
# Пока она принимала целиком `Request`, эти проверки были зелёными на коде,
# который не опознавал владельца НИ РАЗУ, — то есть они не «не поймали»
# поломку, а заказали её: единственный способ их позеленить был передать гейту
# то, чего он не принимает. Правило то же, что с `structuredClone`: подделка
# чужого помощника проверяет наш код только тогда, когда повторяет его форму.
def _checker(seen: list | None = None, answer: bool = True):
    def gate(session: str = "", key: str = "") -> bool:
        if seen is not None:
            seen.append((session, key))
        return answer
    return gate


def test_normatives_reuse_the_developaid_admin_checker():
    """Гейт зовётся так, как он объявлен: сессией и ключом, а не запросом."""
    seen: list = []
    core = SimpleNamespace(_is_admin_request=_checker(seen))

    assert registry._is_admin(_request("key=secret"), core) is True
    assert seen == [("", "secret")], seen


def test_the_session_reaches_the_checker_too():
    """Владельца опознают и по сессии — вход через бота, а не только ключом."""
    seen: list = []
    core = SimpleNamespace(_is_admin_request=_checker(seen))

    assert registry._is_admin(_request("session=abc"), core) is True
    assert seen == [("abc", "")], seen


def test_normatives_do_not_invent_a_second_admin_secret(monkeypatch):
    monkeypatch.setenv("NORMATIVES_ADMIN_KEY", "must-not-be-used")
    core = SimpleNamespace(_is_admin_request=_checker(answer=False))

    assert registry._is_admin(_request("key=secret"), core) is False


def _admin_bar(page: str) -> str:
    """Сама панель, а не подстрока с именем кнопки.

    `#checkBtn` стоит ещё и в стилях, то есть присутствует на странице ВСЕГДА:
    проверка по имени кнопки отвечала бы «панель есть» и там, где её нет.
    """
    start = page.find('<div class="adminbar">')
    return "" if start < 0 else page[start:start + 900]


def test_admin_button_is_not_rendered_for_public_user(monkeypatch):
    monkeypatch.setattr(registry, "_merged_registry", lambda: [])
    core = SimpleNamespace(_is_admin_request=_checker(answer=False))

    page = registry._page(_request(), core)

    assert _admin_bar(page) == ""
    assert "NORMATIVES_ADMIN_KEY" not in page


def test_admin_button_is_rendered_for_existing_admin(monkeypatch):
    monkeypatch.setattr(registry, "_merged_registry", lambda: [])
    core = SimpleNamespace(_is_admin_request=_checker())

    bar = _admin_bar(registry._page(_request("key=secret"), core))

    assert "Режим администратора DevelopAid" in bar
    # Вопроса два, и кнопка называет свой: «Проверить источники» обещала и
    # отмену акта, которую отпечаток не видит по построению.
    assert "Проверить ссылки" in bar


def test_registry_does_not_treat_a_mosru_draft_as_current_law():
    rows = {row["id"]: row for row in registry._load_registry()}
    item = rows["moscow-2152-pp"]

    assert "projects/" not in item["source_url"]
    assert "61-ПП" in item["latest_amendment"]
    assert item["status"] == "review_required"


def test_registry_tracks_the_latest_known_depr_index_document():
    rows = {row["id"]: row for row in registry._load_registry()}
    item = rows["moscow-depr-index"]

    assert "ДПР-Р-20/26" in item["title"]
    assert "ДПРР-18-26" not in item["title"]


def test_mpt_card_exposes_the_july_2026_review_gap():
    rows = {row["id"]: row for row in registry._load_registry()}
    item = rows["moscow-1874-pp"]

    assert "2072-ПП" in item["latest_amendment"]
    assert "1965-ПП" in item["latest_amendment"]
    assert item["status"] == "review_required"


def test_a_source_link_carries_no_click_id():
    """Метка перехода в ссылке источника — факт о нашем поиске, а не о документе.

    08.09.2026 ссылка на 214-ФЗ пришла из выдачи Яндекса с хвостом `ysclid`.
    Такой хвост протухает вместе с сессией поиска, а в реестре живёт вечно и
    выглядит частью адреса документа. Хуже того, он рассказывает, где мы искали,
    в публичном репозитории.

    Проверка держит утверждение, а не список: запрещены параметры перехода у
    ЛЮБОЙ карточки, включая те, что появятся позже.
    """
    import urllib.parse

    junk = {"ysclid", "utm_source", "utm_medium", "utm_campaign", "utm_term",
            "utm_content", "gclid", "fbclid", "yclid", "_openstat"}
    found = []
    for row in registry._load_registry():
        query = urllib.parse.urlsplit(row.get("source_url") or "").query
        marks = sorted(set(urllib.parse.parse_qs(query)) & junk)
        if marks:
            found.append((row.get("id"), marks))
    assert not found, f"в ссылке источника осталась метка перехода: {found}"


def test_the_click_id_guard_fails_on_a_forged_link(monkeypatch):
    """Сторож обязан падать на поломке — иначе он не сторож.

    Правило проверяется подделкой: карточка с `ysclid` должна быть найдена.
    Без этого «нарушений нет» означало бы, что не сработал сам обход.
    """
    forged = [{"id": "поддельная", "source_url": "http://example.org/doc?nd=1&ysclid=abc"}]
    monkeypatch.setattr(registry, "_load_registry", lambda: forged)
    import pytest
    with pytest.raises(AssertionError, match="метка перехода"):
        test_a_source_link_carries_no_click_id()


def test_the_card_leads_to_the_act_itself() -> None:
    """Публикация редакции и страница самого акта — разные адреса.

    «Сам 713/30 лежит вообще у нас где-то?» (владелец, 19.09.2026). Публикация
    поправки заморожена днём выхода: консолидированного текста в ней нет, и
    карточка, у которой ссылка одна, на этот вопрос ответить не могла.
    """
    entry = {"id": "mo-713-30", "scope": "Московская область",
             "short_name": "713/30", "title": "Постановление № 713/30 «Об утверждении»",
             "source_url": "http://publication.pravo.gov.ru/document/5000202609020006",
             "source_label": "Официальное опубликование — 1080-ПП",
             "act_page_url": "https://mosreg.ru/dokumenty/act",
             "act_page_label": "Страница самого акта"}
    card = registry._card(entry)
    assert "5000202609020006" in card, "ссылки на публикацию редакции нет"
    assert "https://mosreg.ru/dokumenty/act" in card, "ссылки на сам акт нет"
    assert "Страница самого акта" in card
    # Ссылка на несуществующее — такая же ложь, как подпись под чужим числом.
    assert "Страница самого акта" not in registry._card(
        dict(entry, act_page_url="", act_page_label=""))


def test_the_registry_says_the_base_act_is_not_in_the_library() -> None:
    """Чего в библиотеке НЕТ, сказано в самой карточке.

    У 713/30 лежат только поправки и приложение № 10: пробел этот стоит
    восьми открытых дыр справочника, и молча он читается как «всё есть».
    """
    import json

    rows = {row["id"]: row for row in json.loads(
        (ROOT / "data" / "normatives" / "registry.json").read_text(encoding="utf-8"))}
    row = rows["mo-713-30"]
    assert "Консолидированного текста 713/30 у нас нет" in row["notes"]
    assert row["act_page_url"].startswith("https://mosreg.ru/")
    # Сами поправки при этом лежат в библиотеке распознанным текстом — и это
    # проверяется, а не обещается. Сканы не хранятся (решение владельца).
    assert (ROOT / "docs" / "normative" / "mo_rngp_1080pp_20260901.ocr.txt").is_file()


def test_the_page_takes_its_scopes_from_the_rows(monkeypatch) -> None:
    """Плитки и кнопки отбора считаются по данным, а не перечислены в разметке.

    Перечисленный список отстаёт от реестра: строка с новой областью — а
    «Правовая рамка продукта» появилась именно так — не получила бы ни плитки,
    ни кнопки и читалась бы как отсутствующая.
    """
    rows = registry._load_registry() + [{
        "id": "test-scope",
        "scope": "Проверочная область",
        "title": "Акт проверочной области",
        "cited_as": ["000-ПП"],
        "engine_usage": [{"module": "\u2014", "usage": "проверочная строка, в расчёте не участвует"}],
    }]
    monkeypatch.setattr(registry, "_merged_registry", lambda: rows)
    core = SimpleNamespace(_is_admin_request=_checker(answer=False))

    page = registry._page(_request(), core)

    assert "<div><b>1</b><span>Проверочная область</span></div>" in page
    assert 'data-filter="Проверочная область"' in page


def test_the_page_says_how_much_of_the_contour_is_covered(monkeypatch) -> None:
    """Строка охвата называет числа, а не обещает полноту.

    «Подтверждено» без «требует сверки» читается как проверенный целиком
    реестр, а объявленная цепочка без числа поправок в библиотеке — как полная.
    """
    rows = registry._load_registry()
    cover = registry.coverage(rows)
    assert cover["acts"] == len(rows)
    assert cover["steps"] >= cover["steps_in_library"] > 0
    assert 0 < cover["chained"] <= cover["acts"]

    monkeypatch.setattr(registry, "_merged_registry", lambda: rows)
    core = SimpleNamespace(_is_admin_request=_checker(answer=False))
    page = registry._page(_request(), core)
    line = page.split('<p class="coverline">', 1)[1].split("</p>", 1)[0]
    for number in (cover["acts"], cover["verified"], cover["review"],
                   cover["chained"], cover["steps"], cover["steps_in_library"]):
        assert str(number) in line, f"строка охвата не называет {number}: {line}"


# --- ревизия редакций 16.10.2026 (docs/normative_audit_msk_mo_2026-10.md, T5) --------------

def _rows() -> dict[str, dict]:
    return {row["id"]: row for row in registry._load_registry()}


def _chain(row: dict) -> dict[str, dict]:
    return {str(s.get("number")): s for s in registry.chain_steps(row)}


def test_the_healthcare_card_has_a_text_and_names_the_27_sqm_ceiling() -> None:
    """2150-ПП стоял без ссылки на текст; 16.10.2026 сводный текст прочитан.

    Ссылку на источник берут у источника: адрес — тот, что читали, а не
    сконструированный. Верхний предел 27 м² ННП на посещение (разд. 1.4 в
    ред. 2579-ПП) — расхождение с вводным полем движка, и карточка обязана
    его назвать, а не молчать «нормы города нет».
    """
    row = _rows()["moscow-2150-pp"]
    assert row["source_url"].startswith("https://www.rnk.ru/npd/doc/docid/727795415")
    assert row["status"] != "source_link_missing"
    assert "27 м²" in row["latest_amendment"] and "61-ПП" in row["latest_amendment"]
    assert "61-ПП" in row["watch_terms"]
    modules = {u["module"]: u["usage"] for u in row["engine_usage"]}
    assert "SOCIAL_NORMS_PER_1000" in modules.get("engine/norms.py", "")
    assert "social_clinic_norm_sqm" in modules.get("engine/inputs.py", "")


def test_the_945_chain_knows_2755_and_1856_and_who_counts_what() -> None:
    """Между 2579-ПП и 2118-ПП стоят 2755-ПП и 1856-ПП — разобраны, не «не сверено».

    Постоянные места считает `engine/norms.py` (moscow_permanent_parking_2118),
    приобъектные — `parking_norms.py` (X2, К1, К2); карточка прежде приписывала
    постоянные места parking_norms.py.
    """
    row = _rows()["moscow-945-pp"]
    chain = _chain(row)
    for number in ("2755-ПП", "1856-ПП"):
        assert chain[number]["status"].startswith("разобран"), number
        assert chain[number].get("touches"), number
        assert any(number in line for line in row["amendment_history"]), number
        assert number in row["watch_terms"], number
    modules = {u["module"]: u["usage"] for u in row["engine_usage"]}
    assert "moscow_permanent_parking_2118" in modules.get("engine/norms.py", "")
    assert "К1" in modules.get("parking_norms.py", "") and "К2" in modules["parking_norms.py"]
    assert "постоянные" not in modules["parking_norms.py"]


def test_the_sp_42_card_is_marked_superseded() -> None:
    """СП 42.13330.2016 заменён СП 42.13330.2026 с 12.07.2026 (приказ № 368/пр).

    Словаря статусов для «заменён» в модуле нет; честный статус — «нужен
    первичный источник» (текста 2026 года в библиотеке нет), а факт замены
    стоит в самой карточке: в `superseded_by` и в строке редакции, которую
    читатель видит.
    """
    row = _rows()["rf-sp-42"]
    assert "СП 42.13330.2026" in row["superseded_by"] and "368/пр" in row["superseded_by"]
    assert row["superseded_from"] == "2026-07-12"
    assert "12.07.2026" in row["latest_amendment"]
    assert row["status"] not in ("verified", "review_required", "current")
    assert registry._status_label(row["status"])[0] != row["status"], "статус вне словаря модуля"
    assert "СП 42.13330.2026" in row["watch_terms"] and "СП 42.13330.2026" in row["cited_as"]


def test_the_593_card_describes_the_current_formula_not_the_2013_one() -> None:
    """Формула 2013 года (П = С × (КС2 − КС1), ставки по плотности) не действует с 01.04.2022."""
    import json

    row = _rows()["moscow-593pp-vri"]
    text = json.dumps(row, ensure_ascii=False)
    assert "П = С" not in text and "П=С" not in text
    assert "коэффициент местоположения" in text
    assert "812-ПП" in row["latest_amendment"] and "812-ПП" in row["watch_terms"]


OCTOBER_REVISION = (
    "moscow-2152-pp", "moscow-2151-pp", "moscow-2150-pp", "moscow-945-pp", "moscow-593pp-vri",
    "moscow-273pp-land-rent", "moscow-1874-pp", "moscow-331-pp-krt", "moscow-3135-pp",
    "rf-sp-42", "mo-114r-market-price", "mo-713-30",
)


def test_the_october_revision_is_dated_and_its_chains_agree_with_the_history() -> None:
    """Каждая тронутая карточка датирована сверкой; ряд, история и маркеры не расходятся.

    Номер поправки живёт в трёх местах: ряд (`amendment_chain`), учтённые
    изменения (`amendment_history`) и маркеры сторожа (`watch_terms`), по
    которым проба узнаёт страницу публикатора. Разойдясь, они молчат: ряд
    знает поправку, а сторож объявляет её новостью каждую неделю.
    """
    rows = _rows()
    for key in OCTOBER_REVISION:
        row = rows[key]
        assert row["current_as_of"] == "2026-10-16", key
        if key == "mo-713-30":
            continue  # ряд 713/30 — 29 поправок, история ведётся с 774-ПП
        history = " ".join(row.get("amendment_history") or [])
        for number, step in _chain(row).items():
            assert number in history, f"{key}: {number} есть в ряду, но не в истории"
            if "16.10.2026" in str(step.get("known_from") or ""):
                assert number in row["watch_terms"], f"{key}: {number} не в маркерах сторожа"
    # 114-Р: номер и дата сверены по скану — карточка больше не ждёт этого.
    assert rows["mo-114r-market-price"]["status"] == "verified"
    assert "сверены по скану" in rows["mo-114r-market-price"]["latest_amendment"]
    assert "16.10.2026" in rows["mo-713-30"]["notes"]


def test_the_774_pack_names_the_mosreg_copy_without_a_click_id() -> None:
    """Тот же скан 774-ПП лежит и на портале Правительства МО; ссылка — без хвоста поиска."""
    import urllib.parse

    text = (ROOT / "data" / "normatives" / "mo" / "pp_774_2026-07-02.md").read_text("utf-8")
    links = [word for word in text.split() if "mosreg.ru/download/document/1363640" in word]
    assert links, "ссылки на копию скана на mosreg.ru нет"
    for link in links:
        assert not urllib.parse.urlsplit(link).query, link


# --- четыре документа, которых не было в библиотеке (решение владельца 18.10.2026) ----------
#
# Реквизиты и действующие редакции прочитаны 18.10.2026: 435/18 — по официальным
# публикациям 1317-ПП и 869-ПП (pravo.gov.ru) и сводному тексту meganorm.ru; своды
# правил — по ГАРАНТ, meganorm.ru, legalacts.ru и sudact.ru (Минстрой из песочницы
# не открылся). Здесь закреплено то, что прочитано, а не то, что помнилось:
# в рабочих записях 435/18 значился «от 17.10.2017» и «правилами благоустройства».

NEW_CARDS = {
    "mo-435-18-comfort-standards": {
        "cited": "435/18",
        "adopted_at": "2021-06-01",
        "title_has": ("от 01.06.2021 № 435/18", "стандартов жилого помещения и комфортности проживания"),
        "redaction": ("869-ПП", "1317-ПП"),
        "source_url": "http://publication.pravo.gov.ru/document/5000202607270006",
    },
    "rf-sp-113": {
        "cited": "СП 113.13330.2023",
        "adopted_at": "2023-10-05",
        "effective_from": "2023-11-06",
        "title_has": ("СП 113.13330.2023", "Стоянки автомобилей"),
        "redaction": ("584/пр", "803/пр", "938/пр", "630/пр", "718/пр"),
        "source_url": "https://sudact.ru/law/prikaz-minstroia-rossii-ot-05102023-n-718pr/",
    },
    "rf-sp-396": {
        "cited": "СП 396.1325800.2018",
        "adopted_at": "2018-08-01",
        "effective_from": "2019-02-02",
        "title_has": ("СП 396.1325800.2018", "Улицы и дороги населенных пунктов"),
        "redaction": ("927/пр", "1017/пр", "852/пр", "474/пр"),
        "source_url": "https://base.garant.ru/72167138/",
    },
    "rf-sp-59": {
        "cited": "СП 59.13330.2020",
        "adopted_at": "2020-12-30",
        "effective_from": "2021-07-01",
        "title_has": ("СП 59.13330.2020", "маломобильных групп населения"),
        "redaction": ("938/пр", "630/пр", "833/пр", "434/пр", "904/пр"),
        "source_url": "https://base.garant.ru/400382837/",
    },
}


def test_the_four_new_documents_are_in_the_registry_with_their_redaction() -> None:
    """Карточка есть, источник назван, действующая редакция названа номерами.

    Последняя поправка стоит первой в `redaction`: она обязана быть и в строке
    редакции, которую видит читатель, и в маркерах сторожа — иначе сторож
    будет приносить её как новость каждую неделю.
    """
    rows = _rows()
    missing = [key for key in NEW_CARDS if key not in rows]
    assert not missing, f"в реестре нет карточек: {missing}"
    for key, want in NEW_CARDS.items():
        row = rows[key]
        for part in want["title_has"]:
            assert part in row["title"], f"{key}: в заголовке нет «{part}»"
        assert row["adopted_at"] == want["adopted_at"], key
        if "effective_from" in want:
            assert row["effective_from"] == want["effective_from"], key
        assert row["source_url"] == want["source_url"], f"{key}: источник не тот, что читали"
        assert "18.10.2026" in row["source_label"], f"{key}: не сказано, когда прочитан источник"
        assert row["current_as_of"] == "2026-10-18", key
        latest, *earlier = want["redaction"]
        assert latest in row["latest_amendment"], f"{key}: действующая редакция ({latest}) не названа"
        assert latest in row["watch_terms"], f"{key}: {latest} не в маркерах сторожа"
        history = " ".join(row["amendment_history"])
        for number in want["redaction"]:
            assert number in history or number in row["latest_amendment"], f"{key}: {number}"
        for number, step in _chain(row).items():
            assert number in history, f"{key}: {number} есть в ряду, но не в истории"
        # Где документ работает — названо, и «не участвует» названо причиной.
        modules = {u["module"]: u["usage"] for u in row["engine_usage"]}
        assert "не участвует" in modules.get("—", ""), f"{key}: не сказано, что расчёт его не применяет"


def test_the_registry_recognises_the_numbers_of_the_new_documents() -> None:
    """`cited_numbers` — единственный ответ на «этот номер закрыт контуром»."""
    known = registry.cited_numbers(list(_rows().values()))
    for key, want in NEW_CARDS.items():
        assert want["cited"].lower() in known, f"{key}: номер {want['cited']} не опознан"
    # Короткое написание без года — им ссылаются РНГП МО и сами своды правил.
    for short in ("сп 113.13330", "сп 396.1325800", "сп 59.13330"):
        assert short in known, short
    # Заменённая редакция стоянок узнаётся тоже: на неё ссылаются старые документы.
    assert "сп 113.13330.2016" in known


def test_the_comfort_standards_carry_their_real_requisites() -> None:
    """435/18 — от 01.06.2021, «стандарты … комфортности проживания», а не 17.10.2017.

    Номер своего акта берётся из заголовка: у сводов правил «№» в заголовке нет,
    и «(с изменениями № 1–4)» там стоять не должно — `own_number` прочёл бы
    «1–4» номером самого свода.
    """
    rows = _rows()
    row = rows["mo-435-18-comfort-standards"]
    assert registry.own_number(row) == "435/18"
    assert "17.10.2017" not in json.dumps(row, ensure_ascii=False)
    assert row["scope"] == "Московская область"
    chain = _chain(row)
    assert set(chain) == {"1317-ПП", "869-ПП"}
    assert chain["869-ПП"]["eo_number"] == "5000202607270006"
    assert chain["1317-ПП"]["eo_number"] == "5000202312280003"
    for key in ("rf-sp-113", "rf-sp-396", "rf-sp-59"):
        assert registry.own_number(rows[key]) == "", key


def test_the_kind_of_force_is_named() -> None:
    """Обязательный норматив и свод правил добровольного применения — разные ответы.

    По перечню ПП РФ № 815 (ред. № 914) обязательны части СП 59.13330.2020;
    СП 113 и СП 396 в действующей редакции перечня нет. 435/18 обязателен в
    сфере, которую называет сам (КРТ жилой застройки с переселением), и через
    отсылки РНГП МО.
    """
    rows = _rows()
    assert "частично обязательный" in rows["rf-sp-59"]["notes"]
    assert "815" in rows["rf-sp-59"]["notes"]
    for key in ("rf-sp-113", "rf-sp-396"):
        notes = rows[key]["notes"]
        assert "добровольного применения" in notes and "815" in notes, key
        assert "его нет" in notes, key
    notes = rows["mo-435-18-comfort-standards"]["notes"]
    assert "на обязательной основе" in notes and "подлежат учету" in notes
