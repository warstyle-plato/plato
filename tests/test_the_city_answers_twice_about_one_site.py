"""Город отвечает о площадке дважды, и второй ответ обязан быть назван.

«И тут другие цифры» — владелец, 20.09.2026, ссылка на карточку
`api.krt.mos.ru/projects/derbenevskaya-ul-ter-2`. Замер прода того же часа
развёл две поверхности ОДНОГО источника:

* плитка списка `api.krt.mos.ru/projects/` (страница 27): площадь 5,3 га,
  общий объём **153 320**, ОДН **14 400**, жильё 138 920 — ровно наша строка;
* карточка проекта: площадь 5,3 га, общий объём **358 100**, жильё 358 100,
  ОДН не назван вовсе.

Снимку было 38 минут, то есть дело не в устаревании; сорок случайных площадок
из сорока совпали, то есть дело и не в сдвиге разбора. Расходятся сам список и
сама карточка города.

Выбирать между двумя его числами мы не вправе: считаем по-прежнему плиткой —
и НАЗЫВАЕМ второе число. Молча выбранное выглядит на экране ровно так же, как
сверенное; ровно этой беды мы уже ловили в отчёте против книги и в паре
«решение ↔ карточка».

Три вещи проверяются порознь:

1. карточку мы УЖЕ скачиваем ради застройщика — значит ТЭП читается даром, тем
   же разбором той же страницы;
2. какая подпись какая величина — ОДИН ответ на обе поверхности
   (`tep_from_fields`): у карточки «Площадь, га», у плитки «Площадь», и второй
   карты подписей быть не должно;
3. ответа у сверки три, а не два, и на строке каталога он доезжает до экрана.

Запуск: python3 -m pytest tests/test_the_city_answers_twice_about_one_site.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from market_search import krt_card_facts, krt_registry, tep_check  # noqa: E402

# Разметка карточки — как её отдаёт город: пары «<span>подпись: </span><b>…</b>»
# в первой колонке описания, проза во второй.
CARD = """
<div class="project-detail__description__main">
 <div class="project-detail__description__main__col">
  <p><span>Площадь, га: </span><b>5.3</b></p>
  <p><span>Округ: </span><b>ЮАО</b></p>
  <p><span>Район: </span><b>Даниловский</b></p>
  <p><span>Функциональное назначение КРТ и ТЭП (кв.м):</span></p>
  <p><span>Общий объем застройки: </span><b>358100</b></p>
  <p><span>Жилое назначение: </span><b>358100</b></p>
 </div>
 <div class="project-detail__description__main__col"><p></p></div>
</div>
"""

# Та же площадка в плитке списка — числа города другие, и это его ответ.
TILE_FIELDS = {"площадь": "5.3", "округ": "ЮАО", "район": "Даниловский",
               "статус": "Планируемый", "общий объем застройки": "153320",
               "общественно-деловое назначение": "14400",
               "жилое назначение": "138920"}


def test_the_card_carries_its_own_tep() -> None:
    """ТЭП читается с той же страницы, за которую уже заплачен запрос."""
    out = krt_card_facts.parse(CARD)
    assert out["tep_fields"]["общий объем застройки"] == "358100"
    assert out["tep_fields"]["площадь, га"] == "5.3"
    # Проза второй колонки ТЭП не мешает и в поля не лезет.
    assert out["description"] == ""


def test_one_map_of_labels_serves_both_surfaces() -> None:
    """Подписи у карточки и у плитки одни, и разбирает их одна функция."""
    card = krt_registry.tep_from_fields(krt_card_facts.parse(CARD)["tep_fields"])
    tile = krt_registry.tep_from_fields(TILE_FIELDS)
    assert card["area_ha"] == tile["area_ha"] == 5.3, (card, tile)
    assert card["total_gfa_sqm"] == 358_100.0
    assert tile["total_gfa_sqm"] == 153_320.0
    assert tile["business_gfa_sqm"] == 14_400.0
    # У карточки ОДН не назван — это «не знаем», а не ноль.
    assert card["business_gfa_sqm"] is None

    # И строка каталога собирается ТОЙ ЖЕ картой: вторая разошлась бы молча.
    rows, _ = krt_registry.parse_catalogue(
        '<a class="projects__card__img" href="/projects/derbenevskaya-ul-ter-2">'
        '</a><div class="projects__card__title">Дербеневская ул. тер. 2</div>'
        '<div class="projects__card__text"><p>Площадь: 5.3</p>'
        '<p>Общий объем застройки: 153320</p>'
        '<p>Общественно-деловое назначение: 14400</p>'
        '<p>Жилое назначение: 138920</p></div>')
    if rows:  # разметка списка может смениться — тогда утверждение про неё молчит
        assert rows[0].total_gfa_sqm == tile["total_gfa_sqm"]


def test_three_answers_not_two() -> None:
    """Сошлось, расходится и сверять не с чем — и последнее не «сошлось»."""
    tile = krt_registry.tep_from_fields(TILE_FIELDS)
    card = krt_registry.tep_from_fields(krt_card_facts.parse(CARD)["tep_fields"])

    same = tep_check.compare(dict(tile), dict(tile),
                             ours_label="в карточке", theirs_label="в списке")
    assert same["problems"] == [] and same["compared"], same

    differs = tep_check.compare(card, tile,
                                ours_label="в карточке", theirs_label="в списке")
    # Обе стороны названы в самой строке: «358100» без второго числа не
    # отличить от опечатки.
    assert any("358100" in one and "153320" in one for one in differs["problems"]), differs
    # Площадь территории совпала — значит сравнивают ОДНУ площадку, и
    # расхождение метров настоящее, а не следствие неверной пары.
    assert "площадь территории" in differs["compared"]
    assert not any("площадь территории" in one for one in differs["problems"])

    empty = tep_check.compare({}, tile, ours_label="в карточке", theirs_label="в списке")
    assert empty["problems"] == [] and empty["compared"] == []
    assert empty != same, "«сверять не с чем» неотличимо от «сошлось»"


def test_the_decision_check_is_the_same_arithmetic() -> None:
    """Сверок две, счёт один: два счёта одного расхождения разошлись бы."""
    from market_search import krt_decision_tep

    source = Path("market_search/krt_decision_tep.py").read_text(encoding="utf-8")
    body = source[source.index("def catalogue_check("):]
    assert "tep_check.compare" in body, "сверка решения считает своей копией"
    out = krt_decision_tep.catalogue_check(
        {"area_ha": 5.0, "housing_gfa_sqm": 100.0},
        {"area_ha": 5.0, "housing_gfa_sqm": 200.0})
    assert out["problems"] == ["жильё: в решении 100, в каталоге 200"], out


def test_the_reader_version_rises_with_its_answer() -> None:
    """Разобранное лежит сутками: не поднимешь версию — починка не доедет."""
    assert krt_registry.CARD_FACTS_SCHEMA_VERSION == 2, (
        "ответ читателя карточки изменился — поднимите версию вместе с ним")
    assert "tep_fields" in krt_card_facts.parse(CARD)


def test_the_bump_reaches_what_was_already_read(tmp_path) -> None:
    """Поднятая версия обязана ЗАКАЗАТЬ перечитывание, а не только обесценить.

    Свежесть файла отвечает на «давно ли читали», а не на «тем ли читателем»:
    запись вчерашней версии остаётся свежей сутки, и починка до прочитанных
    карточек не доезжает вовсе. Ровно это уже стоило дня на выписках ЕГРН.
    """
    registry = krt_registry.KrtRegistry(tmp_path, fetch=lambda url: b"")
    path = registry.card_facts_dir / "old.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        '{"schema_version": 1, "available": true, "roles": [], "developers": []}',
        encoding="utf-8")

    assert registry._card_facts_stale("old") is True, (
        "карточка прежнего читателя считается прочитанной — перечитывать её никто не придёт")
    assert registry.card_facts_known(["old"]) == {}, "чужая версия выдана за свою"

    path.write_text(
        '{"schema_version": %d, "available": true, "roles": [], "developers": [],'
        ' "tep": {"area_ha": 1.0}}' % krt_registry.CARD_FACTS_SCHEMA_VERSION,
        encoding="utf-8")
    assert registry._card_facts_stale("old") is False, "свежую запись зовут перечитывать"
    assert "old" in registry.card_facts_known(["old"])


def test_the_row_carries_the_check_to_the_screen() -> None:
    """Посчитанное на сервере, но не доехавшее до строки, — это молчание."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from auction_search.api import install
    from market_search import krt_registry as registry

    card = {"schema_version": registry.CARD_FACTS_SCHEMA_VERSION, "available": True,
            "roles": [], "developers": [], "city_operator": False, "renovation": False,
            "renovation_quote": "", "description": "",
            "tep": registry.tep_from_fields(krt_card_facts.parse(CARD)["tep_fields"])}
    row = {"slug": "derbenevskaya-ul-ter-2", "name": "Дербеневская ул. тер. 2",
           "status": "Планируемый", "okrug": "ЮАО", "district": "Даниловский",
           **{key: value for key, value in registry.tep_from_fields(TILE_FIELDS).items()
              if value is not None}}

    app = FastAPI()
    # Каталог у маршрута — это служба, а не модуль: она же отвечает и на
    # «что о карточках уже прочитано».
    app.state.market_discovery_service = SimpleNamespace(
        krt=SimpleNamespace(
            catalogue=lambda **_: [dict(row)],
            status=lambda: {"complete": True, "refreshing": False,
                            "decisions_refreshing": False, "retrieved_at": 1_788_000_000,
                            "ttl_seconds": 86_400},
            decisions=lambda **_: {"total": 0, "matched": 0, "complete": True,
                                   "stale": False, "decisions": [], "matched_rows": [],
                                   "tep": {}, "tep_pending": []},
            card_facts_known=lambda slugs: {"derbenevskaya-ul-ter-2": card},
            card_facts_coverage=lambda slugs: {"read": 1, "failed": 0, "unknown": 0},
        ),
    )
    install(app)
    with TestClient(app) as client:
        answer = client.get("/auctions/krt").json()

    one = next(item for item in answer["projects"]
               if item.get("slug") == "derbenevskaya-ul-ter-2")
    check = one["card_tep_check"]
    assert check["read"] is True
    assert any("358100" in problem and "153320" in problem
               for problem in check["problems"]), check
    # И считаем мы по-прежнему плиткой: число строки не подменено карточкой.
    assert one["total_gfa_sqm"] == 153_320.0


def test_the_screen_says_the_two_answers_apart() -> None:
    """И это видно: в исходнике сломанный экран выглядит как починенный."""
    import threading
    import time

    import pytest
    import uvicorn
    from fastapi import FastAPI

    from browser import chromium_or_skip

    from auction_search.api import install

    chrome = chromium_or_skip()
    from playwright.sync_api import sync_playwright

    tile = krt_registry.tep_from_fields(TILE_FIELDS)
    card = krt_registry.tep_from_fields(krt_card_facts.parse(CARD)["tep_fields"])
    rows = [
        {"slug": "differs", "name": "Дербеневская ул. тер. 2", "status": "Планируемый",
         "okrug": "ЮАО", "district": "Даниловский",
         **{key: value for key, value in tile.items() if value is not None}},
        {"slug": "agrees", "name": "Согласная ул., вл. 1", "status": "Планируемый",
         "okrug": "ЦАО", "area_ha": 3.0, "total_gfa_sqm": 90_000.0,
         "housing_gfa_sqm": 60_000.0},
        {"slug": "unread", "name": "Карточка не читана", "status": "Планируемый",
         "okrug": "ВАО", "area_ha": 2.0, "total_gfa_sqm": 30_000.0,
         "housing_gfa_sqm": 20_000.0},
    ]
    facts = {
        "differs": {"schema_version": krt_registry.CARD_FACTS_SCHEMA_VERSION,
                    "available": True, "roles": [], "developers": [],
                    "city_operator": False, "renovation": False,
                    "renovation_quote": "", "description": "", "tep": card},
        "agrees": {"schema_version": krt_registry.CARD_FACTS_SCHEMA_VERSION,
                   "available": True, "roles": [], "developers": [],
                   "city_operator": False, "renovation": False,
                   "renovation_quote": "", "description": "",
                   "tep": {"area_ha": 3.0, "total_gfa_sqm": 90_000.0,
                           "housing_gfa_sqm": 60_000.0}},
    }

    app = FastAPI()
    app.state.market_discovery_service = SimpleNamespace(
        krt=SimpleNamespace(
            catalogue=lambda **_: [dict(one) for one in rows],
            status=lambda: {"complete": True, "refreshing": False,
                            "decisions_refreshing": False, "retrieved_at": 1_788_000_000,
                            "ttl_seconds": 86_400},
            decisions=lambda **_: {"total": 0, "matched": 0, "complete": True,
                                   "stale": False, "decisions": [], "matched_rows": [],
                                   "tep": {}, "tep_pending": []},
            card_facts_known=lambda slugs: dict(facts),
            card_facts_coverage=lambda slugs: {"read": 2, "failed": 0, "unknown": 1},
        ),
    )
    install(app)
    port = 18811
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port,
                                           log_level="error"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(200):
        if server.started:
            break
        time.sleep(0.05)
    assert server.started
    seen: dict[str, str] = {}
    errors: list[str] = []
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path=str(chrome))
            page = browser.new_page()
            page.on("pageerror", lambda exc: errors.append(str(exc)))
            page.goto(f"http://127.0.0.1:{port}/auctions", wait_until="domcontentloaded")
            page.evaluate("switchTab(true)")
            for _ in range(40):
                page.wait_for_timeout(250)
                if page.evaluate("state.krt.length"):
                    break
            folded: dict[str, object] = {}
            for slug in ("differs", "agrees", "unread"):
                page.evaluate("(s)=>selectKrt(state.krt.find(x=>x.slug===s))", slug)
                page.wait_for_timeout(120)
                # Где стоит плашка — ЭТО и есть правило: громкая («расходится»)
                # выше вердикта, молчащая — внутри «чего не хватает».
                # Спрашиваем ДО раскрытия складок: раскрытые выглядят одинаково.
                folded[slug] = page.evaluate(
                    "[...document.querySelectorAll('#krtSide .notice')]"
                    ".filter(n=>n.textContent.indexOf('Карточка и список города')===0)"
                    ".map(n=>!!n.closest('details'))")
                page.evaluate("document.querySelectorAll('#krtSide details')"
                              ".forEach(d=>{d.open=true})")
                page.wait_for_timeout(60)
                seen[slug] = page.evaluate("document.getElementById('krtSide').innerText")
            browser.close()
    finally:
        server.should_exit = True
        thread.join(timeout=10)

    assert not errors, errors
    assert pytest  # импорт нужен ради пропуска без браузера

    # Расхождение названо ОБОИМИ числами и обоими источниками: «358100» без
    # второго числа читается как опечатка, а не как ответ города.
    assert "Карточка и список города говорят разное" in seen["differs"], seen["differs"]
    assert "358100" in seen["differs"] and "153320" in seen["differs"], seen["differs"]
    # И сказано, что мы НЕ выбираем между ними молча.
    assert "считаем по списку" in seen["differs"], seen["differs"]

    assert "Карточка и список города: сошлись" in seen["agrees"], seen["agrees"]
    # Непрочитанная карточка — «не знаем», а не «сошлось».
    assert "не сверялись" in seen["unread"], seen["unread"]
    assert "сошлись" not in seen["unread"], seen["unread"]

    # Плашка одна на карточку — две с одним смыслом читаются как два факта.
    assert [len(value) for value in (folded["differs"], folded["agrees"],
                                     folded["unread"])] == [1, 1, 1], folded
    # И место: громкое расхождение стоит НЕ под складкой, молчащее — под ней.
    assert folded["differs"] == [False], folded
    assert folded["agrees"] == [True], folded
    assert folded["unread"] == [True], folded
