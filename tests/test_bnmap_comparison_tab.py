"""Вкладка bnMAP: клон отчёта, посчитанный блоками отчёта.

Владелец, 30.08.2026: «может, просто на боевом поле соберёшь отчёт
клонированный по „Пульсу“ и добавишь, например, те же комнатности, которых там
нет — посмотреть, можно ли сделать такой же отчёт и что-то добавить».

Отсюда устройство. Блоки считает `metrics.build_blocks` — та самая функция,
которой считается действующий отчёт; рисует их `blockCard` кабинета — тот самый
рендерер. Меняется источник строк, а не арифметика и не вёрстка: иначе
сравнение источников превратилось бы в сравнение двух наших реализаций.

И вторая половина просьбы: то, для чего блока в отчёте нет вовсе —
комнатность и скидки — показывается своими таблицами, а чего источник не дал,
называется вслух.

Запуск: python3 -m pytest tests/test_bnmap_comparison_tab.py -q
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from market_search import bnmap, bnmap_ui, cabinet, metrics  # noqa: E402


# Карточка соседа в том виде, в каком её отдаёт `analytics.reportNearBy`
# (снято с живого ответа 30.08.2026). Числа свои — важна форма; чужим данным в
# репозитории не место.
CARD = {
    "object_id": "2855", "project": "Объект", "class": "Бизнес",
    "agreement": "ДДУ с эскроу", "stage": "157", "start_sales_date": "13.03.2025",
    "date_state_commission": "2027-09-30", "interior": "Без отделки",
    "discount": "со скидкой", "desc": "Скидка 5-11% при 100% оплате.",
    "metrprice_avg": {"metrprice_avg_total": 715927, "metrprice_avg_st": 764610,
                      "metrprice_avg_1": 758421, "metrprice_avg_2": 675137,
                      "metrprice_avg_3": 688265, "metrprice_avg_4": 780937},
    "apart_total": {"expo": "57", "square_avg": "60.679"},
    "sum_avg": {"apart_total": 43429138},
    "pace_lots": 3, "pace_lots_pre_12": 4, "unrealized_count": 165, "forecast_month": 55,
}
NEIGHBOUR = {**CARD, "object_id": "1539", "project": "Сосед", "class": "Бизнес-",
             "metrprice_avg": {"metrprice_avg_total": 504904, "metrprice_avg_1": 534629},
             "apart_total": {"expo": "115", "square_avg": "64.0"},
             "pace_lots": 13, "unrealized_count": 412, "discount": "со скидкой",
             "desc": "Скидка 17% при 100% оплате / ипотеке. " + "Ещё условие. " * 30}


def payload() -> dict:
    subject = bnmap._metric_row(CARD, "Объект", 0, "2026-08-25")
    peer = bnmap._metric_row(NEIGHBOUR, "Сосед", 0.55, "2026-08-25")
    return {
        "found": {"how": "совпадение по названию или адресу", "object_id": 2855,
                  "candidates": [{"name": "Объект", "object_id": 2855}]},
        "subject": subject, "peers": [peer],
        "blocks": metrics.build_blocks(subject, [peer]),
        "gaps": list(bnmap.CLONE_GAPS), "unnamed_peers": ["Безымянный"],
        "account": {"tools": ["irn"]}, "asked_date": "2026-08-25", "errors": [],
    }


def test_the_row_fits_the_contract_of_the_report_blocks() -> None:
    """Строка bnMAP ложится в те же ключи, которыми считается наш отчёт."""
    row = bnmap._metric_row(CARD, "Объект", 0, "2026-08-25")
    for key in ("price_per_sqm", "units_per_month", "remaining_units",
                "lot_count", "lot_area_avg", "segment", "name"):
        assert key in row, key
    assert row["price_per_sqm"] == 715927
    # Средняя площадь экспозиции — НЕ средний проданный лот: блок сравнивает
    # именно эти две величины, и подменять одну другой значит сравнить число
    # само с собой.
    assert row["lot_area_avg"] == 60.679
    assert "sold_lot_avg" not in row


def test_the_clone_is_counted_by_the_report_and_not_by_a_second_arithmetic() -> None:
    body = (ROOT / "market_search" / "bnmap.py").read_text()
    assert "metrics.build_blocks" in body, "клон считает мимо блоков отчёта"
    assert "statistics" not in body and "median" not in body, "в модуле завелась своя медиана"
    blocks = {block["code"]: block for block in payload()["blocks"]}
    assert blocks["price"]["subject"]["price_per_sqm"] == 715927
    assert blocks["price"]["peers"]["median"] == 504904
    assert blocks["pace"]["peers"]["peer_median_over_subject"] == 4.3
    # Срок распродажи наш блок считает сам; у bnMAP он приходит готовым, и
    # рядом их можно сверить.
    assert blocks["stock"]["subject"]["months_to_sell"] == 55.0
    assert payload()["subject"]["months_by_source"] == 55.0


def test_absorption_says_why_it_is_empty() -> None:
    """Пустой блок без причины читается как «у проекта этого нет»."""
    blocks = {block["code"]: block for block in payload()["blocks"]}
    assert not blocks["absorption"]["subject"]
    assert blocks["absorption"]["notes"], "блок молчит вместо того, чтобы назвать причину"
    assert any("поглощение" in line.lower() for line in bnmap.CLONE_GAPS)


def test_the_tab_shows_what_the_report_has_no_block_for() -> None:
    html = bnmap_ui.render(payload())
    assert "Цена метра по комнатности" in html and "764 610" in html
    assert "Скидки и условия покупки" in html and "Скидка 5-11%" in html
    assert "Чего bnMAP не дал" in html and "Безымянный" in html
    assert "Объект опознан" in html and "2855" in html


def test_long_discount_terms_are_cut_by_word() -> None:
    """Обрубок посреди числа читается как другое число."""
    short = bnmap_ui._short(NEIGHBOUR["desc"])
    assert short.endswith("…") and len(short) < 170
    assert not re.search(r"\d…$", short), "число обрезано посередине"


def test_the_tab_is_on_the_cabinet_page_and_the_placeholder_is_filled() -> None:
    page = cabinet.cabinet_page()
    assert bnmap_ui.PLACEHOLDER not in page
    assert 'id="bnmap"' in page and "Тестовый отчёт bnMAP" in page


def test_the_blocks_are_drawn_by_the_report_renderer() -> None:
    """Своей вёрстки блоков у вкладки нет: две вёрстки одного отчёта разойдутся."""
    script = re.search(r"<script>(.*?)</script>", bnmap_ui.markup(), re.S).group(1)
    assert "blockCard(" in script, "вкладка рисует блоки сама"
    body = (ROOT / "market_search" / "bnmap_ui.py").read_text()
    assert "медиана соседей" not in body, "подписи блоков продублированы во вкладке"


def test_the_tab_script_parses() -> None:
    """Незакрытая кавычка убивает страницу молча — проверяем узлом."""
    script = re.search(r"<script>(.*?)</script>", bnmap_ui.markup(), re.S).group(1)
    path = ROOT / "tests" / "_bnmap_tab.js"
    path.write_text(script, encoding="utf-8")
    try:
        done = subprocess.run([_node(), "--check", str(path)], capture_output=True, text=True)
        assert done.returncode == 0, done.stderr
    finally:
        path.unlink(missing_ok=True)


def _node() -> str:
    for name in ("node", "nodejs"):
        try:
            subprocess.run([name, "--version"], capture_output=True, check=True)
            return name
        except Exception:  # noqa: BLE001
            continue
    import pytest

    pytest.skip("node в образе нет")


def test_the_tab_counts_nothing_itself() -> None:
    """Показ, а не третий счёт: блоки считает отчёт, bnMAP отдаёт числа."""
    body = (ROOT / "market_search" / "bnmap_ui.py").read_text()
    code = "\n".join(line.split("#")[0] for line in body.splitlines())
    for sign in (" / ", " * ", "sum(", "median"):
        assert sign not in code, f"во вкладке считают: {sign}"


def test_only_methods_with_a_seen_answer_may_be_called() -> None:
    session = bnmap.Session(ROOT / "tests" / "_bnmap_tmp")
    assert session.call("analytics.magicDeals", {}) is None
    assert any("не сверен" in line for line in session.errors)


def test_the_report_route_is_registered_and_gated() -> None:
    body = (ROOT / "market_search" / "api.py").read_text()
    assert '@app.get("/market/bnmap/report")' in body
    route = body[body.index('@app.get("/market/bnmap/report")'):]
    assert "cabinet_module.require_cabinet(request)" in route[:2000]
    assert "bnmap.clone_report" in route[:2000]


def test_the_object_is_found_by_words_coordinates_or_number(monkeypatch, tmp_path) -> None:
    known = [
        {"object_id": 28, "name": "Матч Поинт", "address": "Василисы Кожиной ул., вл. 13",
         "latitude": 55.736242, "longitude": 37.499905},
        {"object_id": 1539, "name": "Prime Park / Прайм Парк", "address": "Ленинградский пр-т",
         "latitude": 55.794, "longitude": 37.52},
    ]
    monkeypatch.setattr(bnmap, "directory", lambda *a, **k: known)
    assert bnmap.find(tmp_path, "1539")["how"] == "номер введён руками"
    assert bnmap.find(tmp_path, "прайм парк")["object_id"] == 1539
    assert bnmap.find(tmp_path, "Василисы Кожиной")["object_id"] == 28
    by_point = bnmap.find(tmp_path, "55.7362, 37.4999")
    assert by_point["object_id"] == 28 and by_point["candidates"][0]["distance_km"] < 0.1


def test_bnmap_stands_beside_the_report_and_not_inside_it() -> None:
    """Действующий отчёт собирает «Пульс», и bnMAP в него не входит."""
    for name in ("service_v6.py", "pulse.py"):
        assert "bnmap" not in (ROOT / "market_search" / name).read_text().lower(), name


def test_the_flat_mix_and_deal_prices_are_shown() -> None:
    """Сделки по объекту закрыты у платформы и открыты у службы отчётов.

    `analytics.objectDeals` отвечает «нет инструмента deals», а
    `getReportSalesBalancesTypeRooms` и `getReportSalesBalancesPriceInDeals`
    отдают агрегаты по тем же сделкам бесплатно. Это две разные двери в один
    дом, и знать про вторую важнее, чем про первую.
    """
    data = {
        **payload(),
        "rooms_balance": [
            {"type": "1", "pboCount": 88, "pdoCount": 25, "pboLeft": 63, "pboLeftShare": 72},
            {"type": "ст", "pboCount": 23, "pdoCount": 14, "pboLeft": 9, "pboLeftShare": 39},
        ],
        "deal_prices": {"years": [{"year": 2026, "1": 686087, "2": 734921, "3": 787165}]},
    }
    html = bnmap_ui.render(data)
    assert "Квартирография и вымывание" in html and "63" in html and "72 %" in html
    # «ст» — это студии, и подпись разворачивается: сырой ключ на экране
    # читается как чужой код, а не как тип квартиры.
    assert "Студии" in html and ">ст<" not in html
    assert "Цена в сделках" in html and "734 921" in html


def test_commercial_and_parking_are_named_as_closed_not_as_absent() -> None:
    """«Источник не знает» и «нам не продали» — разные утверждения.

    В объектной модели bnMAP машино-места, кладовые и нежилое лежат своими
    полями; закрыт инструмент, а не данные. Сказать «этого нет» значит соврать
    про источник и закрыть вопрос, который на самом деле про деньги.
    """
    gaps = " ".join(bnmap.CLONE_GAPS)
    assert "машино-места" in gaps and "commercialNumParking" in gaps
    assert "не куплен" in gaps
    assert bnmap.VERIFIED["commercial.get"].startswith("403")


def test_the_same_class_is_grouped_by_the_source_label() -> None:
    """«Считаем как считает источник» — решение владельца 30.08.2026.

    У bnMAP класс дробный: «Бизнес+», «Бизнес», «Бизнес−». Наша лестница из пяти
    ступеней сводит их в один «бизнес», и тогда медиана своего класса совпадает
    с общей — тонкость источника пропадает молча. На Кутузов Сити это разница
    между «дороже соседей на треть» и «дешевле своего класса»: смотря что
    считать своим классом.
    """
    subject = bnmap._metric_row(CARD, "Объект", 0, "2026-08-25")
    same = bnmap._metric_row({**CARD, "object_id": "7", "class": "Бизнес"},
                             "Тот же класс", 1.0, "2026-08-25")
    lower = bnmap._metric_row({**NEIGHBOUR, "class": "Бизнес-"}, "Ступенью ниже", 0.5, "2026-08-25")
    price = [b for b in metrics.build_blocks(subject, [same, lower]) if b["code"] == "price"][0]
    assert price["peers"]["same_class"]["count"] == 1, "дробная метка источника схлопнулась"
    assert price["peers"]["same_class"]["names"] == ["Тот же класс"]
    assert any("«Бизнес»" in note for note in price["notes"])
    # Запятая предложения — не разделитель тысяч.
    assert not any("  " in note for note in price["notes"])


def test_the_pulse_path_keeps_the_ladder() -> None:
    """У «Пульса» дробных меток нет, и его сборка этой правкой не двигается."""
    subject = {"name": "Свой", "price_per_sqm": 700000, "segment": "Бизнес"}
    peers = [{"name": "Сосед", "price_per_sqm": 500000, "segment": "бизнес"},
             {"name": "Премиальный", "price_per_sqm": 900000, "segment": "Премиум"}]
    price = [b for b in metrics.build_blocks(subject, peers) if b["code"] == "price"][0]
    assert price["peers"]["same_class"]["count"] == 1
    assert price["peers"]["same_class"]["names"] == ["Сосед"]
