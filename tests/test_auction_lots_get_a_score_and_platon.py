"""У лота тот же балл, что у КРТ, и Платона можно спросить не уходя со страницы.

Список торгов показывал тип, площадь, цену и число документов — сравнивать лоты
между собой приходилось глазами. Балл собран тем же правилом, что у КРТ:
потенциал лота и **названные** снижения за то, чего у лота нет. Поднимать нечем:
своей экономики у лота до разбора не существует.

Разговор с Платоном стоит там же, где смотрят список: уводить человека на
другую страницу, чтобы спросить про то, что у него перед глазами, значит
заставить его переписать вопрос по памяти. Числа в вопрос кладутся готовыми —
их считает движок.

Запуск: python3 -m pytest tests/test_auction_lots_get_a_score_and_platon.py -q
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from auction_search.ui import auctions_page  # noqa: E402


def script() -> str:
    page = auctions_page()
    return page[page.rindex("<script>") + len("<script>"):page.rindex("</script>")]


def function_source(name: str) -> str:
    body = script()
    start = body.index(f"function {name}(")
    depth = 0
    for position in range(body.index("{", start), len(body)):
        if body[position] == "{":
            depth += 1
        elif body[position] == "}":
            depth -= 1
            if depth == 0:
                return body[start:position + 1]
    raise AssertionError(f"не найдена функция {name}")


def lot_score(lot: dict) -> dict:
    node = shutil.which("node")
    if not node:
        pytest.skip("node недоступен")
    body = script()
    parts = []
    for name in ("const LOT_BASE_BY_KIND=", "const LOT_SMALL_SQM="):
        start = body.index(name)
        parts.append(body[start:body.index("\n", start)])
    parts += [function_source(name) for name in ("lotDeadlineDays", "lotScore", "lotScoreNote")]
    program = "\n".join(parts) + f"\nconsole.log(JSON.stringify(lotScore({json.dumps(lot)})));"
    done = subprocess.run([node, "-e", program], capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr[:600]
    return json.loads(done.stdout)


FULL = {"lot_kind": "krt", "land_area_sqm": 94000, "current_price_rub": 1_840_000_000,
        "application_deadline": "2099-10-14T10:00:00",
        "cadastral_numbers": ["77:05:0004001:1042"], "documents": [1, 2, 3],
        "screening": {"ready_for_financial_model": True, "requires_krt_terms": True,
                      "concerns": []}}


def test_a_complete_lot_loses_nothing() -> None:
    got = lot_score(FULL)
    assert got["cut"] == 0
    assert got["score"] == got["base"] > 0


def test_a_lot_without_a_cadastral_number_loses_points() -> None:
    got = lot_score({**FULL, "cadastral_numbers": []})
    assert any("кадастровый номер" in cut["label"] for cut in got["cuts"])
    assert got["score"] < got["base"]


def test_an_expired_deadline_is_the_heaviest_deduction() -> None:
    expired = lot_score({**FULL, "application_deadline": "2000-01-01T10:00:00"})
    missing_docs = lot_score({**FULL, "documents": []})
    assert expired["cut"] > missing_docs["cut"]
    assert any("истёк" in cut["label"] for cut in expired["cuts"])


def test_a_missing_deadline_is_not_an_expired_one() -> None:
    """«Срока нет» — это «не опубликован», а не «прошёл»."""
    got = lot_score({**FULL, "application_deadline": None})
    assert not any("истёк" in cut["label"] for cut in got["cuts"])


def test_every_deduction_says_what_it_is() -> None:
    got = lot_score({"lot_kind": "land_sale", "land_area_sqm": 21000,
                     "current_price_rub": None, "application_deadline": "2000-01-01T10:00:00",
                     "cadastral_numbers": [], "documents": [],
                     "screening": {"ready_for_financial_model": False,
                                   "concerns": ["ВРИ не тот", "границы не уточнены"]}})
    assert got["cuts"], "снижение без объяснения — это просто другое число"
    for cut in got["cuts"]:
        assert cut["label"] and cut["points"] > 0
    assert got["cut"] <= 95, "балл не должен схлопываться в ноль"
    assert got["score"] >= 0


def test_the_score_never_exceeds_the_potential() -> None:
    for lot in (FULL, {**FULL, "documents": []}, {**FULL, "current_price_rub": None}):
        got = lot_score(lot)
        assert got["score"] <= got["base"]


# --- Платон и подвал -------------------------------------------------------------

def test_the_page_can_ask_platon_without_leaving_it() -> None:
    body = script()
    assert "async function askPlato(" in body
    assert "'/cabinet/ask'" in body, "тот же маршрут, что у кабинета рынка — своего не заводим"
    assert "/agent/result/" in body, "за долгим ответом ходят по номеру запуска"
    assert "r.status===401" in body, "закрытый кабинет называется своим именем"


def test_the_question_carries_the_numbers_and_forbids_inventing_them() -> None:
    body = function_source("askDigest")
    assert "ОТОБРАНО ЛОТОВ" in body and "ОТОБРАНО ПЛОЩАДОК КРТ" in body
    assert "ВЫБРАН" in body
    program = script()
    assert "не пересчитывай их" in program
    # Строка склеена из кусков в исходнике — ищем то, что в нём есть целиком.
    assert "выдумывай" in program and "скажи, что данных нет" in program


def test_the_footer_carries_the_same_portrait_as_the_cabinet() -> None:
    page = auctions_page()
    assert 'class="plato-footer"' in page
    assert "/assets/platon-quote.webp" in page


def test_the_lots_table_has_the_score_column() -> None:
    page = auctions_page()
    head = page[page.index("<th>Лот</th>"):]
    head = head[:head.index("</thead>")]
    assert "<th>Оценка Платона</th>" in head


# Масштаб лота у двух источников лежит в РАЗНЫХ полях: у городских ЭТП это
# площадь участка, у ГИС Торгов — площадь здания. Пока балл читал только
# участок, гараж 26 м² и имущественный комплекс 190 000 м² получали одну и ту
# же прибавку — ноль.

BUILDING = {"lot_kind": "property_complex", "building_area_sqm": 26_000,
            "current_price_rub": 480_000_000, "application_deadline": "2099-10-14T10:00:00",
            "cadastral_numbers": ["77:01:0004023:1"], "documents": [1],
            "screening": {"concerns": []}}


def test_a_building_lot_is_measured_by_its_own_metres() -> None:
    big = lot_score(BUILDING)
    small = lot_score({**BUILDING, "building_area_sqm": 900})
    assert big["base"] > small["base"], "190 000 м² и 900 м² не могут стоить одинаково"


def test_a_garage_is_not_a_development_site() -> None:
    got = lot_score({**BUILDING, "building_area_sqm": 26})
    assert any("не площадка" in cut["label"] for cut in got["cuts"])
    assert got["score"] < lot_score(BUILDING)["score"]


def test_a_lot_without_metres_is_not_called_small() -> None:
    """«Метров нет» — это не «метров мало»: снижать не за что."""
    got = lot_score({**BUILDING, "building_area_sqm": None})
    assert not any("не площадка" in cut["label"] for cut in got["cuts"])
