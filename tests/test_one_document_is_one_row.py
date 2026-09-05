"""Один документ — одна строка списка КРТ, даже когда его опубликовали дважды.

Проект решения о КРТ город кладёт сразу в два раздела портала: у Департамента
городского имущества и у Департамента инвестиционной и промышленной политики.
Для нас это две записи выдачи с разными идентификаторами — и на экране выходили
две одинаковые строки подряд («Котляково (территория № 1)», «Свиблово
(территория 1)», «Бескудниково (территория 2)»), различить которые человек не
мог ничем.

Замер на живом прод-ответе `/auctions/krt` 05.09.2026: из 298 площадок-решений
38 стоят парами, и во ВСЕХ 38 группах совпадают заголовок, площадь и день
публикации, а различается только раздел портала. Ни одной группы с одинаковым
разделом нет — то есть правило схлопывает ровно вторую публикацию и ничего
кроме неё.

Записи ниже — настоящие, из того же ответа.

Запуск: python3 -m pytest tests/test_one_document_is_one_row.py -q
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from auction_search.api import (  # noqa: E402
    _publication_section, _without_second_publication, krt_decision_rows,
)

# Котляково: один документ у двух ведомств, один и тот же день (16.02.2022).
KOTLYAKOVO = [
    {"slug": "decision:265145220", "name": "в производственной зоне № 32 «Котляково» (территория № 1)",
     "area_ha": 10.33, "draft_decision_at": 1645021704, "department": "ДИПП",
     "draft_decision_url": "https://www.mos.ru/dipp/documents/view/265145220/"},
    {"slug": "decision:266482220", "name": "в производственной зоне № 32 «Котляково» (территория № 1)",
     "area_ha": 10.33, "draft_decision_at": 1644993344, "department": "ДГИ",
     "draft_decision_url": "https://www.mos.ru/dgi/documents/view/266482220/"},
]

# Алабушево: пара от 30.12.2021 — дубль, а документ от 20.05.2022
# самостоятельный. Схлопнуть его значило бы спрятать более позднее решение.
ALABUSHEVO = [
    {"slug": "decision:269714220", "name": "Алабушево", "area_ha": 10.07,
     "draft_decision_at": 1653033038, "department": "ДГИ",
     "draft_decision_url": "https://www.mos.ru/dgi/documents/view/269714220/"},
    {"slug": "decision:263486220", "name": "Алабушево", "area_ha": 10.07,
     "draft_decision_at": 1640859659, "department": "ДИПП",
     "draft_decision_url": "https://www.mos.ru/dipp/documents/view/263486220/"},
    {"slug": "decision:266471220", "name": "Алабушево", "area_ha": 10.07,
     "draft_decision_at": 1640845608, "department": "ДГИ",
     "draft_decision_url": "https://www.mos.ru/dgi/documents/view/266471220/"},
]


def test_the_same_document_in_two_sections_is_one_row() -> None:
    """Две записи одного проекта решения дают одну строку — и она это говорит."""
    kept = _without_second_publication(list(KOTLYAKOVO))
    assert len(kept) == 1, "на экране осталось две одинаковых строки"
    # Остаётся ранняя публикация, а вторая НАЗЫВАЕТСЯ: молча убранная строка
    # читается как пропавшая площадка, а не как та же самая.
    assert kept[0]["slug"] == "decision:266482220"
    assert [one["department"] for one in kept[0]["also_published"]] == ["ДИПП"]
    assert kept[0]["also_published"][0]["url"].endswith("/265145220/")


def test_two_documents_of_one_territory_both_stay() -> None:
    """День публикации в ключе — граница правила, а не придирка.

    По одной территории у города бывают РАЗНЫЕ документы, и более позднее
    решение мы прятать не вправе.
    """
    kept = _without_second_publication(list(ALABUSHEVO))
    assert len(kept) == 2, "схлопнулись документы разных дат"
    dates = sorted(int(one["draft_decision_at"]) for one in kept)
    assert dates == [1640845608, 1653033038]
    later = [one for one in kept if one["draft_decision_at"] == 1653033038][0]
    assert not later.get("also_published"), "самостоятельный документ назван дублем"


def test_two_documents_of_one_department_are_not_collapsed() -> None:
    """Совпали заголовок, площадь и день, а раздел ОДИН — решать за город нечем.

    Это две записи одного ведомства, и какая из них лишняя, знает город, а не
    мы. Схлопывается только вторая ПУБЛИКАЦИЯ — та же бумага в другом разделе.
    """
    same_department = [
        {**KOTLYAKOVO[0], "slug": "decision:1"},
        {**KOTLYAKOVO[0], "slug": "decision:2",
         "draft_decision_url": "https://www.mos.ru/dipp/documents/view/2/"},
    ]
    assert len(_without_second_publication(same_department)) == 2


def test_the_section_is_read_from_the_address() -> None:
    """Раздел портала — часть адреса документа, а не догадка о ведомстве."""
    assert _publication_section("https://www.mos.ru/dgi/documents/view/266482220/") == "dgi"
    assert _publication_section("https://www.mos.ru/dipp/documents/view/265145220/") == "dipp"
    assert _publication_section("") == ""
    assert _publication_section("https://www.mos.ru/dgi/") == ""


def test_the_collapse_happens_where_the_rows_are_built() -> None:
    """Сборка строк одна на экран и на прогон публикаций — схлопывание в ней же.

    Иначе прогон ходил бы по 298 площадкам там, где на экране 260, и платил бы
    за второй заход по тому же документу.
    """
    found = {
        "decisions": [
            {"id": "265145220", "url": KOTLYAKOVO[0]["draft_decision_url"],
             "title": "Проект решения ... Котляково (территория № 1)",
             "address": "в производственной зоне № 32 «Котляково» (территория № 1)",
             "published_at": 1645021704, "department": "ДИПП"},
            {"id": "266482220", "url": KOTLYAKOVO[1]["draft_decision_url"],
             "title": "Проект решения ... Котляково (территория № 1)",
             "address": "в производственной зоне № 32 «Котляково» (территория № 1)",
             "published_at": 1644993344, "department": "ДГИ"},
        ],
        "tep": {"265145220": {"read": True, "area_ha": 10.33},
                "266482220": {"read": True, "area_ha": 10.33}},
    }
    rows = krt_decision_rows(found)
    assert len(rows) == 1
    assert rows[0]["slug"] == "decision:266482220"


def test_the_route_says_how_many_were_collapsed() -> None:
    """Счёт убранных доезжает до экрана: молчание читается как пропажа."""
    from types import SimpleNamespace

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    import auction_search.api as auction_api

    app = FastAPI()
    app.state.market_discovery_service = SimpleNamespace(
        krt=SimpleNamespace(
            catalogue=lambda **_: [],
            status=lambda: {"complete": True, "refreshing": False},
            decisions=lambda: {
                "decisions": [
                    {"id": "265145220", "url": KOTLYAKOVO[0]["draft_decision_url"],
                     "address": KOTLYAKOVO[0]["name"], "published_at": 1645021704,
                     "department": "ДИПП"},
                    {"id": "266482220", "url": KOTLYAKOVO[1]["draft_decision_url"],
                     "address": KOTLYAKOVO[1]["name"], "published_at": 1644993344,
                     "department": "ДГИ"},
                    # Решение без идентификатора строкой не становится вовсе, и
                    # разность с числом ДОКУМЕНТОВ назвала бы схлопнутым наш
                    # собственный пропуск.
                    {"id": "", "url": "", "address": "без номера", "published_at": 0},
                ],
                "tep": {},
            },
        ),
    )
    auction_api.install(app)
    payload = TestClient(app).get("/auctions/krt").json()
    assert payload["no_card_count"] == 1
    assert payload["second_publications"] == 1


def test_the_screen_names_the_second_publication() -> None:
    """Настоящими функциями страницы, а не пересказом.

    Под таблицей — счёт убранных строк, в карточке — адрес второй публикации с
    именем ведомства: «dipp» читателю не говорит ничего.
    """
    import auction_search.ui as ui

    page = ui.auctions_page()
    body = page[page.index("function renderKrtSnapshotNote("):]
    body = body[:body.index("\nfunction ")]
    assert "krtSecondPublications" in body, "счёт убранных на экран не выходит"

    card = page[page.index("function krtPassport("):page.index("function krtTenderBlock(")]
    script = (
        "const esc=s=>String(s);\n"
        "const fmtArea=v=>String(v);\n"
        "const krtNumber=(x,k)=>Number(x[k]||0);\n"
        "const krtTepSourceNote=()=>'источник';\n"
        "const krtStatusCell=()=>'проект решения';\n"
        "const krtPassportValue=()=>'—';\n"
        + card
        + "\nconsole.log(krtPassport({slug:'a',name:'Котляково',no_card:true,"
          "draft_decision_url:'https://www.mos.ru/dgi/documents/view/266482220/',"
          "also_published:[{url:'https://www.mos.ru/dipp/documents/view/265145220/',"
          "section:'dipp',department:'ДИПП'}]}));\n"
    )
    out = subprocess.run(["node", "-e", script], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    drawn = out.stdout
    assert "265145220" in drawn, "адреса второй публикации в карточке нет"
    assert "ДИПП" in drawn, "ведомство не названо — раздел портала читателю немой"


def test_the_count_is_printed_under_the_table() -> None:
    """Строка под таблицей называет число убранных, а не молчит о них."""
    import auction_search.ui as ui

    page = ui.auctions_page()
    body = page[page.index("function renderKrtSnapshotNote("):]
    body = body[:body.index("\nfunction ")]
    script = (
        "const state={krtSnapshot:{at:0,ttl:0,refreshing:false,complete:true},"
        "krtSecondPublications:38};\n"
        "let written='';\n"
        "const $=()=>({set textContent(v){written=v},set innerHTML(v){written=v}});\n"
        + body
        + "\nrenderKrtSnapshotNote();console.log(JSON.stringify(written));\n"
    )
    out = subprocess.run(["node", "-e", script], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    said = json.loads(out.stdout.strip().splitlines()[-1])
    assert "38" in said, said
