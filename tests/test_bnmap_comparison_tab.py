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


def test_the_tab_lives_on_the_market_page_and_nowhere_else() -> None:
    """Кабинет разнесён на три вида, и клон рыночного отчёта живёт на рынке.

    Умолчание `cabinet_page()` — титул, и блока там быть не должно: разметку
    `_cut` режет кусками, а плейсхолдер вне куска вылез бы на всех трёх
    страницах, и заметить это было бы негде.
    """
    market = cabinet.cabinet_page("market")
    assert bnmap_ui.PLACEHOLDER not in market
    assert 'id="bnmap"' in market and "Тестовый отчёт bnMAP" in market
    for view in ("home", "sales"):
        page = cabinet.cabinet_page(view)
        assert 'id="bnmap"' not in page, f"вкладка вылезла на вид «{view}»"
        assert bnmap_ui.PLACEHOLDER not in page


def test_the_blocks_are_drawn_by_the_report_renderer() -> None:
    """Своей вёрстки блоков у вкладки нет: две вёрстки одного отчёта разойдутся."""
    script = re.search(r"<script>(.*?)</script>", bnmap_ui.markup(), re.S).group(1)
    assert "blockCard(" in script, "вкладка рисует блоки сама"
    # Помощник кабинета, а не свой: верхнеуровневый слушатель на элементе,
    # которого на этом виде нет, роняет весь скрипт кабинета.
    assert "on('#bngo'" in script and "const $=" not in script
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
    """Показ, а не третий счёт: блоки считает отчёт, bnMAP отдаёт числа.

    Запрещается место, а не слово. Прежде запрет стоял на строке «median», и
    под него попало чтение уже посчитанной медианы из блока — единственное
    правильное обращение к ней. Позеленить это можно было бы ровно одним
    способом: посчитать медиану самим. Поэтому запрещены вычисления —
    арифметика и вызов, — а чтение готового свойства разрешено прямо здесь.
    """
    body = (ROOT / "market_search" / "bnmap_ui.py").read_text()
    code = "\n".join(line.split("#")[0] for line in body.splitlines())
    for sign in (" / ", " * ", "sum(", "median(", "statistics"):
        assert sign not in code, f"во вкладке считают: {sign}"
    # Чтение посчитанного сервером — не счёт, и выглядит оно так:
    assert ".median)" in code, "вкладка перестала брать медиану у блока отчёта"


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


def test_the_price_history_comes_back_as_three_series() -> None:
    """История у bnMAP есть, и она не одна: свой ряд и два ряда рынка.

    Владелец, 31.08.2026: «почему никакой истории нет». История была
    отброшена — «история цены мало интересна для оценки» относилось к
    помесячному ряду карточки соседа, а не к динамике самого проекта. Ряд
    `location` живого ответа несёт восемнадцать месяцев: цена проекта, средняя
    пяти ближайших и средняя всей локации.
    """
    location = {
        "2025-03-01": {"current_project_metrprice_avg": 631549.56,
                       "five_projects_metrprice_avg": 433558.1,
                       "location_buildings": {"metrprice_avg": 552630.9, "expo_num": 7693}},
        "2025-04-01": {"current_project_metrprice_avg": 631793.46,
                       "five_projects_metrprice_avg": 425359.54,
                       "location_buildings": {"metrprice_avg": 563015.49, "expo_num": 7606}},
        # Месяц до выхода проекта в продажу: ноль здесь значит «ряда ещё не
        # было», а не «цена ноль». Нарисованный, он показал бы обвал цены.
        "2025-02-01": {"current_project_metrprice_avg": 0,
                       "five_projects_metrprice_avg": 400000.0,
                       "location_buildings": {"metrprice_avg": 540000.0, "expo_num": 7000}},
    }
    own, market = bnmap._price_series(location)
    assert [row["month"] for row in own] == ["2025-03", "2025-04"]
    assert own[0]["value"] == 631549.56
    assert [row["name"] for row in market] == ["пять ближайших, средняя", "локация, средняя"]
    assert len(market[0]["points"]) == 3
    # Две готовые средние — не выборка проектов, и полосу квартилей по ним
    # строить нельзя: подпись «верх выборки» назвала бы их тем, чем они не
    # являются.
    assert all(row["aggregate"] for row in market)
    assert len(bnmap._exposure_series(location)) == 3


def test_the_tab_draws_the_verdict_by_the_report_renderers() -> None:
    """Выводы рисуются теми же функциями, что и в действующем отчёте."""
    script = re.search(r"<script>(.*?)</script>", bnmap_ui.markup(), re.S).group(1)
    for call in ("verdictCard(", "findingsCard(", "essayCard(", "finalCard("):
        assert call in script, f"вкладка не зовёт {call} — значит рисует вывод сама"
    page = cabinet.cabinet_page("market")
    # Те же функции объявлены один раз и зовутся обеими поверхностями: пока
    # вывод стоял вставкой внутри `showReport`, второй источник мог показать
    # его только второй вёрсткой.
    for name in ("function verdictCard(", "function findingsCard(", "function essayCard("):
        assert page.count(name) == 1, name
    assert "html+=verdictCard(d);" in page and "html+=essayCard(d);" in page


def test_the_empty_sales_chart_names_its_own_reason() -> None:
    """Причина пустоты приходит снаружи, а не зашита под «Пульс».

    У «Пульса» помесячных продаж нет там, где проекта нет в отчёте по «Москве
    старой»; у bnMAP их нет вовсе — метод такого ряда не отдаёт. Одна фраза на
    две разные причины назвала бы второму источнику чужую.
    """
    page = cabinet.cabinet_page("market")
    assert "function salesChart(rows, key, unit, digits, note)" in page
    assert "salesChart(ctx.sales,'sold','ДДУ',0,ctx.salesNote)" in page
    script = re.search(r"<script>(.*?)</script>", bnmap_ui.markup(), re.S).group(1)
    note = re.search(r"salesNote:\s*'((?:[^']|\\')*)'", script)
    assert note, "вкладка не называет причину пустого графика"
    assert "Москву старую" not in note.group(1), "второму источнику подставлена чужая причина"
    assert any("помесячные продажи" in line.lower() for line in bnmap.CLONE_GAPS)


def test_the_distance_filter_only_narrows_and_says_so() -> None:
    """Радиуса у источника нет — значит выбор только отсекает присланное.

    У `analytics.reportNearBy` параметра радиуса в каталоге методов нет вовсе:
    кого считать соседом, решает bnMAP. Изобразить выбор, которого у источника
    нет, значит пообещать выборку, которой не будет.
    """
    markup = bnmap_ui.markup()
    assert 'id="bnrad"' in markup and "radius_km=" in markup
    assert "расширить выборку нечем" in markup
    assert any("радиус" in line.lower() for line in bnmap.CLONE_GAPS)
    shown = bnmap_ui._selection({"given": 5, "used": 2, "radius_km": 0.5, "farthest_km": 0.44})
    assert "прислал bnMAP" in shown and ">5<" in shown and ">2<" in shown
    assert "не дальше 0.5 км" in shown and "может только отсечь" in shown


def _page_function(name: str) -> str:
    """Функция страницы целиком — по скобкам, а не по соседней строке.

    Вырезать «до следующего комментария» уже стоило десяти разом упавших
    проверок: комментарий переписали, и все они сказали `substring not found`
    вместо того, что сломалось. Функция — контракт: её граница считается
    скобками.
    """
    page = cabinet.cabinet_page("market")
    start = page.index(f"function {name}(")
    depth, index = 0, page.index("{", start)
    for position in range(index, len(page)):
        if page[position] == "{":
            depth += 1
        elif page[position] == "}":
            depth -= 1
            if depth == 0:
                return page[start:position + 1]
    raise AssertionError(f"функция {name} не закрылась")


def test_a_ready_made_average_is_a_line_and_not_a_quartile_band() -> None:
    """Готовая средняя источника в полосу квартилей не идёт.

    bnMAP не даёт помесячной цены по каждому соседу — он присылает две уже
    посчитанные средние: пять ближайших и всю локацию. Пущенные в полосу, они
    подписались бы «верх выборки» и «низ выборки», то есть были бы названы
    выборкой соседей, которой не являются. Проверяем не текстом, а прогоном
    настоящего графика: рисунок должен назвать линии их именами и объяснить,
    почему полосы нет.
    """
    page = cabinet.cabinet_page("market")
    helpers = "\n".join(line for line in page.splitlines()
                        if line.startswith("const num=") or line.startswith("const esc="))
    assert "const num=" in helpers and "const esc=" in helpers, "помощники страницы не нашлись"
    body = helpers + "\n" + _page_function("trendChart")
    script = (body + "\nconst PICKED=['#1367AE','#C4581B'];\n"
              "const out=trendChart([\n"
              "  {name:'объект',own:true,points:[{month:'2025-03',value:600000},"
              "{month:'2025-04',value:610000}]},\n"
              "  {name:'пять ближайших, средняя',aggregate:true,"
              "points:[{month:'2025-03',value:430000},{month:'2025-04',value:425000}]},\n"
              "  {name:'локация, средняя',aggregate:true,"
              "points:[{month:'2025-03',value:550000},{month:'2025-04',value:560000}]}\n"
              "]);\nconsole.log(out);\n")
    path = ROOT / "tests" / "_bnmap_trend.js"
    path.write_text(script, encoding="utf-8")
    try:
        done = subprocess.run([_node(), str(path)], capture_output=True, text=True)
        assert done.returncode == 0, done.stderr
    finally:
        path.unlink(missing_ok=True)
    drawn = done.stdout
    assert "верх выборки" not in drawn and "низ выборки" not in drawn
    assert "пять ближайших" in drawn and "локация" in drawn
    assert "Полосы квартилей здесь нет" in drawn
    assert "<svg" in drawn, "график не нарисовался вовсе"


def test_the_neighbours_carry_their_coordinates_to_the_map() -> None:
    """Координаты у bnMAP есть — строкой, и разобрать их обязан сервер.

    Карту рисует общий рендерер, он ждёт два числа. Строка «55.716254,
    37.433176» приходит в списке соседей `radius`; неразобранная, она оставила
    бы карту пустой при полном ответе источника.
    """
    row = bnmap._metric_row(CARD, "Объект", 0, "2026-08-25", "55.716254, 37.433176")
    assert row["latitude"] == 55.716254 and row["longitude"] == 37.433176
    # Непонятная строка — это «точки нет», а не ноль: нулевые координаты
    # поставили бы проект в Гвинейский залив, и выглядело бы это как данные.
    blank = bnmap._metric_row(CARD, "Объект", 0, "2026-08-25", "—")
    assert blank["latitude"] is None and blank["longitude"] is None


def test_the_tab_shows_the_map_and_the_bubbles_by_the_report_renderers() -> None:
    """Карта соседей и «Карта рынка» — те же функции, что в отчёте."""
    script = re.search(r"<script>(.*?)</script>", bnmap_ui.markup(), re.S).group(1)
    for call in ("geoCard(", "bubbleCard(", "wireBubbles("):
        assert call in script, f"вкладка не зовёт {call}"
    # Контейнер пузырьков свой: два `id=\"bubble\"` на одной странице сделали бы
    # вторую карточку невидимой для переключателя.
    assert "'bnbubble'" in script
    page = cabinet.cabinet_page("market")
    for name in ("function geoCard(", "function bubbleCard(", "function wireBubbles("):
        assert page.count(name) == 1, name
    assert "html+=geoCard(market, s, peers);" in page
    assert "html+=bubbleCard(market, 'bubble');" in page


def test_a_pair_of_axes_without_data_is_named_and_not_drawn_empty() -> None:
    """Пустое поле читается как «про рынок сказать нечего».

    У bnMAP нет ни поглощения в метрах, ни среднего ПРОДАННОГО лота — приходит
    средняя площадь экспозиции, а это другая величина. Две пары осей из шести
    построить не на чем: они не рисуются пустыми, а называются под графиком.
    """
    body = "\n".join(line for line in cabinet.cabinet_page("market").splitlines()
                     if line.startswith("const num=") or line.startswith("const esc="))
    script = (body + "\n" + _page_function("bubbleViews") + "\n"
              + "const VIEWS=[{id:'pace',name:'Цена и темп',x:'units_per_month',y:'price_per_sqm'},"
              + "{id:'speed',name:'Цена и скорость',x:'area_per_month',y:'price_per_sqm'},"
              + "{id:'lot',name:'Цена и размер лота',x:'sold_lot_avg',y:'price_per_sqm'}];\n"
              + "const rows=[{price_per_sqm:700000,units_per_month:3,lot_area_avg:60},"
              + "{price_per_sqm:500000,units_per_month:13,lot_area_avg:64}];\n"
              + "console.log(bubbleViews(rows).map(v=>v.id).join(','));\n")
    path = ROOT / "tests" / "_bnmap_views.js"
    path.write_text(script, encoding="utf-8")
    try:
        done = subprocess.run([_node(), str(path)], capture_output=True, text=True)
        assert done.returncode == 0, done.stderr
    finally:
        path.unlink(missing_ok=True)
    assert done.stdout.strip() == "pace", done.stdout
    # И сама ось названа своим именем: лот в проекте — не проданный лот.
    page = cabinet.cabinet_page("market")
    assert "средний лот в проекте, м²" in page and "средний проданный лот, м²" in page


def test_the_budget_of_a_lot_is_not_the_price_of_a_metre() -> None:
    """`sumRmin`/`sumRmax` — рубли за лот, и в колонки «мин/макс» ₽/м² не идут.

    Соблазн понятен: у отчёта в таблице цены есть пустые колонки «мин» и
    «макс», а у bnMAP есть два числа с похожими именами. Но это бюджет лота, и
    подставленный туда он выглядел бы ценой метра в двадцать миллионов —
    ошибкой, которая не выглядит ошибкой, потому что стоит в своей колонке.
    """
    card = {**CARD, "apart_total": {"expo": "57", "square_avg": "60.679",
                                    "sumRmin": "20363689.00", "sumRavg": "43429137.95",
                                    "sumRmax": "105136857.00", "metrPriceRAvg": "715927.02"}}
    row = bnmap._metric_row(card, "Объект", 0, "2026-08-25")
    assert row["budget_min"] == 20363689.0 and row["budget_max"] == 105136857.0
    assert "price_per_sqm_min" not in row and "price_per_sqm_max" not in row
    html = bnmap_ui._budgets([], row)
    assert "Бюджет лота" in html and "20 363 689" in html
    assert "не за метр" in html, "таблица не говорит, что это рубли за лот"


def test_the_tab_shows_what_pulse_has_no_field_for() -> None:
    """Апартаменты и сроки ввода — то, чего у «Пульса» нет вовсе.

    Апартаменты стоят в общей медиане наравне с квартирами, хотя это другой
    правовой статус и другой покупатель; у bnMAP признак есть, и он назван.
    """
    row = bnmap._metric_row({**CARD, "apartments": 1, "dsc_count": 3,
                             "initial_dsc": "2027-09-30",
                             "before_date_state_commission": 13,
                             "createTimeMax": "2026-08-22"},
                            "Объект", 0, "2026-08-25")
    html = bnmap_ui._delivery([], row)
    assert "Сроки ввода и статус" in html
    assert "апартаменты" in html and "2027-09-30" in html and "2026-08-22" in html
    # Ноль — это «квартиры», а не «неизвестно»: пустое поле и явный ноль
    # означают разное.
    flats = bnmap_ui._delivery([], bnmap._metric_row(
        {**CARD, "apartments": 0, "dsc_count": 1}, "Объект", 0, "2026-08-25"))
    assert "квартиры" in flats


def test_the_tab_asks_platon_about_its_own_numbers() -> None:
    """У вкладки свой вопрос и своя сводка — но путь к Платону один.

    На странице два свода сразу: отчёт по «Пульсу» и этот. Общее поле вопроса
    отдало бы Платону числа последнего построенного, а человек спрашивал бы о
    том, что перед глазами. Поэтому поле своё, а `askPlatoIn` — общая: копия
    опроса стала бы вторым местом, где чинят обрыв длинного ответа.
    """
    markup = bnmap_ui.markup()
    assert 'id="bnask"' in markup and 'id="bnq"' in markup and 'id="bnaskbtn"' in markup
    script = re.search(r"<script>(.*?)</script>", markup, re.S).group(1)
    assert "askPlatoIn(" in script and "platoAnswer(" not in script
    page = cabinet.cabinet_page("market")
    assert page.count("async function askPlatoIn(") == 1
    assert "askPlatoIn({field:'#ask', out:'#askout'" in page
    # Сводка вкладки называет свой источник и границы выборки: подставить ей
    # сводку «Пульса» значило бы спросить не о том, что показано.
    assert "bnMAP.pro (второй источник" in script
    assert "Радиуса у метода нет" in script
    assert "Источник НЕ даёт:" in script, "в вопрос не едет список того, чего нет"


def test_the_premium_card_is_drawn_by_the_report_too() -> None:
    """«Что стоит премия» — та же `deepCard`, и на bnMAP она частичная.

    Денежной части у неё здесь не будет: остатка В МЕТРАХ источник не даёт, а
    перемножить остаток лотов на среднюю площадь экспозиции значит выдать свою
    оценку за данные. Сроки распродажи считаются и показываются.
    """
    from market_search import verdict

    script = re.search(r"<script>(.*?)</script>", bnmap_ui.markup(), re.S).group(1)
    assert "deepCard(data)" in script
    row = bnmap._metric_row(CARD, "Объект", 0, "2026-08-25")
    peer = bnmap._metric_row(NEIGHBOUR, "Сосед", 0.55, "2026-08-25")
    money = verdict.price_of_premium(row, [peer])
    assert "months_own_pace" in money and "months_peer_pace" in money
    assert "premium_on_remainder" not in money, "остаток в метрах взялся из ниоткуда"
    assert "remaining_area" not in row


def test_the_tab_draws_the_map_and_the_neighbours_in_a_real_browser(tmp_path) -> None:
    """Спор «видно или не видно» решает экран, а не рассуждение о коде.

    Строковые проверки говорят, что `geoCard` зовётся, а вопрос был другой:
    появляются ли на карте соседи. Здесь страница открывается настоящим
    браузером, ответ bnMAP подменяется, кнопка нажимается — и в разметке
    считаются кружки соседей и полосы вымывания. Без Chromium это пропуск, а не
    зелёный прогон на пустом месте.
    """
    import json

    import pytest

    play = pytest.importorskip("playwright.sync_api")

    import browser_launch

    subject = bnmap._metric_row(CARD, "Объект", 0, "2026-08-25", "55.716254, 37.433176")
    peers = [
        bnmap._metric_row({**NEIGHBOUR, "object_id": "1"}, "Сосед 1", 0.55, "2026-08-25",
                          "55.712190, 37.428307"),
        bnmap._metric_row({**NEIGHBOUR, "object_id": "2"}, "Сосед 2", 0.65, "2026-08-25",
                          "55.712940, 37.441630"),
        bnmap._metric_row({**NEIGHBOUR, "object_id": "3"}, "Сосед 3", 0.75, "2026-08-25",
                          "55.709622, 37.435227"),
    ]
    answer = {
        "found": {"how": "совпадение по названию", "object_id": 2855, "candidates": []},
        "subject": subject, "peers": peers,
        "blocks": metrics.build_blocks(subject, peers),
        "analysis": {}, "price_series": [], "market_series": [], "exposure_series": [],
        "selection": {"given": 3, "used": 3, "no_price": 0, "farthest_km": 0.75},
        "rooms_bands": [
            {"band": "1к", "pool_units": None, "sold_units": 40.0, "left_units": 10.0,
             "pool_share": None, "sold_share": 0.8, "left_share": 0.2, "skew": None},
            {"band": "2к", "pool_units": None, "sold_units": 10.0, "left_units": 40.0,
             "pool_share": None, "sold_share": 0.2, "left_share": 0.8, "skew": None},
        ],
        "gaps": [], "unnamed_peers": [], "account": {"tools": []},
        "asked_date": "2026-08-25", "errors": [], "html": "",
    }

    page = cabinet.cabinet_page("market").replace("__DEVELOPAID_VERSION__", "test")
    file = tmp_path / "market.html"
    file.write_text(page, encoding="utf-8")
    with play.sync_playwright() as pw:
        try:
            browser = browser_launch.launch(pw)
        except Exception as exc:  # noqa: BLE001
            pytest.skip(f"Chromium недоступен: {exc}")
        try:
            tab = browser.new_page()
            errors: list[str] = []
            tab.on("pageerror", lambda exc: errors.append(str(exc)))
            tab.route("**/*", lambda route: route.abort()
                      if route.request.url.startswith("http") else route.continue_())
            tab.goto(file.as_uri())
            tab.evaluate(
                "answer => { window.fetch = () => Promise.resolve("
                "{ok:true, status:200, text:() => Promise.resolve(JSON.stringify(answer))}); }",
                answer)
            # Блок свёрнут: человек его раскрывает, и тест делает то же самое.
            tab.evaluate("() => { document.getElementById('bnmap').open = true; }")
            tab.click("#bngo")
            tab.wait_for_selector("#bnout .card", timeout=15000)
            drawn = tab.inner_html("#bnout")
            tab.close()
        finally:
            browser.close()
    assert not errors, errors
    assert "Где соседи" in drawn, "карта соседей не нарисовалась"
    # Кружок объекта плюс по кружку на соседа — иначе карта пустая, а выглядит
    # исправной: кольца расстояний рисуются и без единой точки.
    assert drawn.count("<circle") >= 4, f"на карте нет точек соседей: {drawn.count('<circle')}"
    for name in ("Сосед 1", "Сосед 2", "Сосед 3"):
        assert name in drawn, f"{name} не попал на страницу"
    assert "Вымывание по комнатности" in drawn
    assert "Карта рынка" in drawn


def test_the_price_in_deals_is_a_monthly_series_and_zero_is_not_a_price() -> None:
    """Цена в сделках по месяцам — то, чего у «Пульса» нет вовсе.

    Живой ответ 31.08.2026: `months` с полями по комнатности и `yearMonth`
    «07.2025». Ноль в клетке означает «сделок такой комнатности в этом месяце
    не было»; нарисованный, он рвёт линию до нуля и читается как обвал цены —
    ровно та же ошибка, что «пропуск в ряду не ноль» в плане банка.
    """
    rows = bnmap._deal_series({"months": [
        {"1": 657839, "2": 0, "yearMonth": "07.2025"},
        {"1": 574394, "2": 632767, "yearMonth": "08.2025"},
        {"1": 730096, "2": 691571, "yearMonth": "09.2025"},
    ]})
    by_name = {row["name"]: row for row in rows}
    assert set(by_name) == {"сделки, 1к", "сделки, 2к"}
    assert [p["month"] for p in by_name["сделки, 1к"]["points"]] == \
        ["2025-07", "2025-08", "2025-09"]
    # Июль у двушек выпал целиком, а не встал нулём.
    assert [p["month"] for p in by_name["сделки, 2к"]["points"]] == ["2025-08", "2025-09"]
    # Разрезы одного проекта — не выборка соседей: полосы квартилей по ним быть
    # не должно, иначе проект сравнивается сам с собой.
    assert all(row["aggregate"] for row in rows)
    script = re.search(r"<script>(.*?)</script>", bnmap_ui.markup(), re.S).group(1)
    assert "Цена в сделках по месяцам" in script and "trendChart(data.deal_series)" in script


def test_the_sample_cannot_be_widened_and_the_module_says_so() -> None:
    """Ответ на главный вопрос о выборке: расширить её нечем — это сверено.

    Карточка произвольного объекта закрыта региональной лицензией, а «соседи по
    классу» отдают ту же пятёрку. Значит выборку по справочнику координат
    собрать нельзя, и обещать этого нигде не надо.
    """
    assert bnmap.VERIFIED["analytics.balloon"].startswith("403")
    assert "объект и пять ближайших" in bnmap.VERIFIED["analytics.reportNearByProjectClass"]
    for name in ("analytics.balloon", "analytics.reportNearByProjectClass"):
        assert name not in bnmap.REPORT_METHODS, f"{name} зовётся, хотя данных не даёт"
