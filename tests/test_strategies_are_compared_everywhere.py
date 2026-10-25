"""«Сравнение стратегий» — один блок движка на странице, в полном PDF и в тизере.

Владелец, 24.10.2026: «Для объектов с разными вариантами продажи, помимо
чувствительности, можно предусмотреть сравнение стратегий продажи?» —
решение «Блок „Сравнение стратегий“ везде». Образец (страница, страница PDF,
строка тизера на офисе Пролетарский пр-т, вл. 20) утверждён владельцем.

* Числа стратегий — пути движка (`office_paths` / `retail_paths`): каждая
  стратегия — полный расчёт модели. Блок (`strategy_compare_block`) только
  переводит их в строки; страница, PDF и тизер его печатают.
* Книга офиса сравнивает те же три способа формулами — её числа совпадают
  с блоком.
* Точки безразличия — подбор полным пересчётом модели вне запроса расчёта
  (`strategy_compare_for_report`, `/strategy-compare`): подставленное
  значение действительно уравнивает NPV стратегий.

Запуск: python3 -m pytest tests/test_strategies_are_compared_everywhere.py -q
"""

from __future__ import annotations

import copy
import io
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import developaid_nonres_strategy as ns  # noqa: E402
import main_legacy as core  # noqa: E402
from test_an_office_shows_sale_and_rent_side_by_side import _spec  # noqa: E402

ROWS = ("Выручка", "Чистая прибыль", "NPV проекта при ставке 20%", "IRR проекта",
        "Наибольшая сумма собственных денег в проекте", "Когда вложенные собственные деньги вернутся",
        "Покрытие кредита проектного финансирования (LLCR)",
        "Глазами инвестора: собственные деньги с учётом кредита", "IRR собственных денег",
        "NPV собственных денег при ставке 20%", "Чистый доход от аренды за год после заполнения (NOI)",
        "Доходность на затраты: чистый доход от аренды к затратам на создание "
        "(для сравнения: ставка капитализации 10,5%)",
        "Стоимость здания для покупателя-инвестора (чистый доход / ставка капитализации)",
        "Покрытие платежей по кредиту арендой (DSCR, наименьшее)")


def _bundle(**over) -> tuple[dict, dict, dict]:
    x, t = _spec(**over)
    return core._run_authoritative_model(x, t, [], {}), x, t


@pytest.fixture(scope="module")
def office() -> dict:
    bundle, x, t = _bundle(offices_strategy=ns.STRATEGY_DIRECT, project_name="Пролетарский пр-т, вл. 20")
    return {"bundle": bundle, "x": x, "t": t,
            "block": core.strategy_compare_for_report(bundle, x, t, [], {})}


def _retail_spec(**over) -> tuple[dict, dict]:
    x = copy.deepcopy(core.DEFAULT_INPUTS)
    t = copy.deepcopy(core.TEP_DEFAULT)
    for key in core.MKD_PRODUCTS:
        for col in ("gns", "total_area", "useful", "saleable", "transfer", "units"):
            t[key][col] = 0
    for key in core.NONRESIDENTIAL_CLEARED_INPUTS:
        x[key] = 0
    x.update(project_kind=core.PROJECT_KIND_NONRESIDENTIAL, retail_enabled=True, retail_gba_sqm=10000,
             retail_saleable_sqm=6000, retail_strategy=ns.STRATEGY_INCOME, purchase_price_mln=300)
    x.update(over)
    t.setdefault("standalone_retail", {}).update(gns=10000, total_area=9500, useful=6000, saleable=6000)
    return x, t


# --- блок движка ----------------------------------------------------------------

def test_the_block_reads_the_paths_of_the_engine(office) -> None:
    result = office["bundle"]["consolidated"]
    paths = result["office_paths"]["paths"]
    item = office["block"]["items"][0]
    assert [c["key"] for c in item["columns"]] == [p["key"] for p in paths]
    assert tuple(r["label"] for r in item["rows"]) == ROWS
    for row in item["rows"]:
        assert row["values"] == [p.get(row["key"]) for p in paths], row["key"]
    best = max(paths, key=lambda p: p["npv"])["key"]
    assert best == result["office_paths"]["better"] == item["best"] == ns.STRATEGY_DDU
    marks = {c["key"]: c["tags"] for c in item["columns"]}
    assert marks == {"ddu": ["лучшая по NPV"], "direct": ["выбрана в проекте"], "income": [],
                     "income_hold": []}


def test_the_lead_and_the_teaser_say_the_approved_sample(office) -> None:
    item, block = office["block"]["items"][0], office["block"]
    assert item["lead"] == ("В проекте выбрана продажа блоками после ввода. Выгоднее всего продажа по ДДУ "
                            "с эскроу: её NPV выше на 26,2 млн ₽. Ни одна из четырёх стратегий при нынешних "
                            "ценах не окупает проект.")
    assert block["teaser"] == ("Лучшая стратегия — продажа по ДДУ (эскроу), выгоднее выбранной продажи "
                               "блоками на 26,2 млн ₽ по NPV.")
    npv = next(r for r in item["rows"] if r["key"] == "npv")
    assert npv["cells"] == ["−1 747,4 млн ₽", "−1 773,6 млн ₽", "−2 830,3 млн ₽",
                            "−2 597,5 млн ₽"]


def test_the_chosen_best_strategy_names_the_runner_up() -> None:
    bundle, _, _ = _bundle(offices_strategy=ns.STRATEGY_DDU)
    block = core.strategy_compare_block(bundle["consolidated"])
    assert block["teaser"] == ("Выбранная стратегия — продажа по ДДУ — лучшая из четырёх по NPV; следующая, "
                               "продажа блоками, уступает ей 26,2 млн ₽.")


def test_the_payback_is_the_rule_of_the_owner_section() -> None:
    """Срок возврата — тем же правилом, что «Окупаемость собственных средств»."""
    bundle, _, _ = _bundle(offices_strategy=ns.STRATEGY_DIRECT, offices_price_th_per_sqm=600)
    result = bundle["consolidated"]
    direct = next(p for p in result["office_paths"]["paths"] if p["key"] == ns.STRATEGY_DIRECT)
    assert direct["payback_month"] == result["report"]["equity_participation"]["payback_month"]
    assert direct["payback_month"]
    row = next(r for r in result["strategy_compare"]["items"][0]["rows"] if r["key"] == "payback_month")
    assert row["cells"][1] == "с " + core._month_label(direct["payback_month"])


def test_the_retail_object_is_compared_too() -> None:
    x, t = _retail_spec()
    result = core.calculate(core.CalcRequest(inputs=x, tep=t, rates=[]))
    assert "office_paths" not in result
    paths = result["retail_paths"]["paths"]
    assert {p["key"] for p in paths} == {ns.STRATEGY_DDU, ns.STRATEGY_DIRECT, ns.STRATEGY_INCOME,
                                          "income_hold"}
    assert all("error" not in p for p in paths)
    item = result["strategy_compare"]["items"][0]
    assert item["product"] == "standalone_retail" and item["current"] == ns.STRATEGY_INCOME
    # Путь проекта — основной расчёт, без второго счёта.
    income = next(p for p in paths if p["key"] == ns.STRATEGY_INCOME)
    assert income["npv"] == result["summary"]["npv"]


def test_the_investor_sees_the_rent_kept_and_sold() -> None:
    """Владелец, 24.10.2026: «доходный метод для инвестора почему не сравнить?» —
    рядом с арендой и продажей здания стоит аренда с удержанием, и у всех
    стратегий есть строки инвестора: деньги собственника с кредитом, чистый
    доход от аренды, доходность на затраты, стоимость здания, покрытие кредита."""
    bundle, x, t = _bundle(offices_strategy=ns.STRATEGY_DIRECT)
    paths = {p["key"]: p for p in bundle["consolidated"]["office_paths"]["paths"]}
    hold = paths["income_hold"]
    assert hold["label"] == "Аренда и удержание здания" and hold["exit_mode"] == ns.EXIT_HOLD
    # Удержание — полный расчёт движка с выходом «удержание», а не пересчёт здесь.
    assert hold["npv"] == _npv(x, t, ns.STRATEGY_INCOME, offices_exit_mode=ns.EXIT_HOLD)
    assert hold["npv"] != paths["income"]["npv"]
    item = bundle["consolidated"]["strategy_compare"]["items"][0]
    rows = {r["key"]: r["cells"] for r in item["rows"]}
    assert rows["yield_on_cost"] == ["аренды нет", "аренды нет", "6,4%", "6,4%"]
    assert rows["irr_equity"] == ["N/A — долг не погашен", "−52,1%", "−32,0%", "−17,2%"]
    assert rows["exit_value"][:2] == ["здание продаётся по частям"] * 2
    # Проект на удержании: четвёртый столбец — аренда с продажей здания.
    held, _, _ = _bundle(offices_strategy=ns.STRATEGY_INCOME, offices_exit_mode=ns.EXIT_HOLD)
    data = held["consolidated"]["office_paths"]
    labels = {p["key"]: p["label"] for p in data["paths"]}
    assert labels["income"] == "Аренда и удержание здания" and labels["income_sale"] == "Аренда и продажа здания"
    assert data["current"] == ns.STRATEGY_INCOME
    assert next(p for p in data["paths"] if p["key"] == "income_sale")["npv"] == pytest.approx(paths["income"]["npv"])


def test_a_project_without_a_choice_has_no_block() -> None:
    x, t = _retail_spec(retail_enabled=False, above_parking_enabled=True)
    result = core.calculate(core.CalcRequest(inputs=x, tep=t, rates=[]))
    assert "strategy_compare" not in result and core.strategy_compare_block(result) is None


def test_the_block_stands_in_the_decision_section(office) -> None:
    sections = office["bundle"]["consolidated"]["report"]["object_report"]["sections"]
    refs = [b.get("ref") for s in sections if s["key"] == "decision" for b in s["blocks"]]
    assert refs.index("strategy_compare") == refs.index("goal_seek") + 1


# --- точки безразличия ------------------------------------------------------------

def _npv(x, t, strategy, **over) -> float:
    xx = copy.deepcopy(x)
    xx.update(offices_strategy=strategy, **over)
    token = core.OFFICE_PATHS_ON.set(False)
    try:
        return core.calculate(core.CalcRequest(inputs=xx, tep=copy.deepcopy(t), rates=[]))["summary"]["npv"]
    finally:
        core.OFFICE_PATHS_ON.reset(token)


def test_the_found_points_really_level_the_strategies(office) -> None:
    x, t = office["x"], office["t"]
    points = {p["kind"]: p for p in office["block"]["items"][0]["points"]}
    assert set(points) == {"rent", "cap", "price"}
    ddu = _npv(x, t, ns.STRATEGY_DDU)
    tolerance = abs(ddu) * 1e-3
    assert _npv(x, t, ns.STRATEGY_INCOME, offices_rent_th_per_sqm_month=points["rent"]["value"] / 12) \
        == pytest.approx(ddu, abs=tolerance)
    assert _npv(x, t, ns.STRATEGY_INCOME, offices_exit_cap_pct=points["cap"]["value"]) \
        == pytest.approx(ddu, abs=tolerance)
    assert _npv(x, t, ns.STRATEGY_DIRECT, offices_price_th_per_sqm=points["price"]["value"]) \
        == pytest.approx(ddu, abs=tolerance)
    # Контрпример: прежнее значение поля стратегии не уравнивает — разрыв во
    # много раз шире допуска, с которым подобранное значение уравнивает. С
    # выручкой по ДДУ от раскрытия эскроу (214-ФЗ, владелец 25.10.2026)
    # продажа по ДДУ и блоками сблизились: разрыв 26,2 млн ₽ — 15 допусков.
    assert abs(_npv(x, t, ns.STRATEGY_DIRECT) - ddu) > 10 * tolerance
    assert points["rent"]["text"] == ("Аренда станет так же выгодна, как продажа по ДДУ, если ставка аренды "
                                      "вырастет до 54,6 тыс. ₽ за м² в год (сейчас 30,0 тыс. ₽).")
    assert points["price"]["text"] == ("Продажа блоками сравняется с продажей по ДДУ, если блоки продавать "
                                       "по 276,5 тыс. ₽ за м² (сейчас 273,0 тыс. ₽).")


def test_the_calculation_itself_does_not_search(office) -> None:
    """Подбор — не часть расчёта: блок результата приходит без точек."""
    block = office["bundle"]["consolidated"]["strategy_compare"]
    assert all(item["points"] == [] for item in block["items"])
    assert not block["points_ready"] and "ещё подбираются" in block["stamp"]
    assert office["block"]["points_ready"] and "подбором полным пересчётом" in office["block"]["stamp"]


def test_a_failed_search_names_its_reason(office, monkeypatch) -> None:
    def broken(*args, **kwargs):
        raise RuntimeError("нет памяти")
    monkeypatch.setattr(core, "strategy_indifference", broken)
    block = core.strategy_compare_for_report(office["bundle"], office["x"], office["t"], [], {})
    assert "не подобраны: модель не пересчиталась (нет памяти)" in block["stamp"]


# --- книга офиса ------------------------------------------------------------------

def test_the_office_book_agrees_with_the_block(office) -> None:
    openpyxl = pytest.importorskip("openpyxl")
    import office_workbook as ow

    content, _, meta = core.build_project_workbook(office["x"], office["t"], [], {}, project_name="Офис")
    assert meta.get("office_book") is True
    book = openpyxl.load_workbook(io.BytesIO(content))
    evaluator = ow.evaluate(book)
    sheet = book[ow.CHECK_SHEET]
    in_book = {(sheet[f"A{r}"].value, sheet[f"B{r}"].value): evaluator.cell(ow.CHECK_SHEET, f"C{r}")
               for r in range(5, sheet.max_row + 1)}
    item = office["block"]["items"][0]
    labels = {"revenue": ("Выручка", False), "net_profit": ("Чистая прибыль", False),
              "npv": ("NPV проекта", False), "irr_project": ("IRR проекта", True),
              "equity_peak": ("Пик собственных денег", False), "llcr": ("LLCR проектного финансирования", True)}
    sections = {p["key"]: ow.section_of(p) for p in ow.PATHS}
    compared = 0
    for row in item["rows"]:
        if row["key"] not in labels:
            continue
        label, ratio = labels[row["key"]]
        for column, value in zip(item["columns"], row["values"]):
            # Аренда с другим выходом — столбец блока, но не способ книги.
            if value is None or column["key"] not in sections:
                continue
            got = in_book[(sections[column["key"]], label)]
            want = ow._engine_number(value, ratio)
            assert got == pytest.approx(want, rel=1e-6, abs=1e-6), (column["key"], label)
            compared += 1
    assert compared == 16


# --- PDF и тизер ----------------------------------------------------------------------

def _pdf_text(data: bytes) -> str:
    pymupdf = pytest.importorskip("pymupdf")
    with pymupdf.open(stream=data, filetype="pdf") as doc:
        return "\n".join(page.get_text() for page in doc)


def _flat(text: str) -> str:
    return " ".join(text.split())


def test_the_full_pdf_prints_the_block(office) -> None:
    pytest.importorskip("reportlab")
    result = office["bundle"]["consolidated"]
    text = _flat(_pdf_text(core._build_developaid_pdf({
        "result": result, "inputs": office["x"], "tep": office["t"], "rates": [], "phasing": {},
        "scenario": "base", "project_name": "Пролетарский", "strategy_compare": office["block"]})))
    item = office["block"]["items"][0]
    assert "Сравнение стратегий" in text
    assert _flat(item["lead"]) in text
    for column in item["columns"]:
        assert _flat(column["label"]) in text
    assert "лучшая по NPV" in text and "выбрана в проекте" in text
    for cell in next(r for r in item["rows"] if r["key"] == "npv")["cells"]:
        assert cell in text
    for point in item["points"]:
        assert _flat(point["text"]) in text


def test_the_pdf_build_searches_in_the_background(office, monkeypatch) -> None:
    """Сборка PDF с сайта не берёт блок из присланного: подбирает сама."""
    seen = []
    real = core.strategy_compare_for_report

    def spy(*args, **kwargs):
        seen.append(True)
        return real(*args, **kwargs)
    monkeypatch.setattr(core, "strategy_compare_for_report", spy)
    captured = {}
    monkeypatch.setattr(core, "_build_developaid_pdf", lambda payload: captured.update(payload) or b"%PDF")
    monkeypatch.setattr(core, "_teaser_write", lambda *a, **k: None)
    core._report_build("0" * 16, {"inputs": office["x"], "tep": office["t"], "rates": [], "phasing": {},
                                  "result": office["bundle"]["consolidated"],
                                  "strategy_compare": {"items": [{"lead": "подделка"}]}})
    assert seen and captured["strategy_compare"]["items"][0]["lead"] == office["block"]["items"][0]["lead"]


def test_the_teaser_prints_one_line(office) -> None:
    pytest.importorskip("reportlab")
    text = _flat(_pdf_text(core.build_teaser_pdf(office["bundle"], office["x"], office["t"], {})))
    assert "Сравнение стратегий. " + office["block"]["teaser"] in text


# --- страница: браузер ----------------------------------------------------------------

PORT = 18997

SET = r"""([id, value]) => {
  const el = document.querySelector(`[data-field="${id}"] input, [data-field="${id}"] select`);
  if (el.type === 'checkbox') el.checked = value; else el.value = value;
  el.onchange();
}"""

READ = r"""() => {
  openTab('report', null);
  const card = document.querySelector('#rsObj-decision [data-strategy-compare-card]');
  const table = card && card.querySelector('table.strategy-compare-table');
  const seen = el => !!el && el.offsetParent !== null;
  const prev = card && card.previousElementSibling;
  return {
    shown: seen(table),
    after: prev ? (prev.querySelector('.section-title') || {}).textContent : null,
    head: table ? [...table.querySelectorAll('thead th')].map(th => th.innerText.replace(/\s+/g, ' ').trim()) : [],
    best: table ? [...table.querySelectorAll('thead th.best')].map(th => th.dataset.strategy) : [],
    rows: table ? [...table.querySelectorAll('tbody tr')].map(tr => [...tr.cells].map(c => c.innerText.trim())) : [],
    lead: card ? (card.querySelector('.strategy-compare-lead') || {}).textContent : '',
    points: card ? [...card.querySelectorAll('.strategy-points li')].map(li => li.textContent) : [],
    stamp: card ? (card.querySelector('.strategy-compare-stamp') || {}).textContent : '',
    engine: lastResult.strategy_compare,
    inputs, tep};
}"""


@pytest.fixture(scope="module")
def page_state() -> dict:
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright
    import browser

    path = browser.chromium_or_skip()
    out: dict = {}
    with browser.serve(core.app, PORT) as base, sync_playwright() as pw:
        with pw.chromium.launch(executable_path=str(path)) as engine:
            page = engine.new_page(viewport={"width": 1440, "height": 900})
            errors: list[str] = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(base, wait_until="domcontentloaded")
            browser.wait_for_result(page)
            page.evaluate(SET, ["offices_enabled", True])
            browser.wait_for_result(page)
            page.evaluate("() => { applyProjectKind('nonresidential'); closeProjectKindDialog(); }")
            browser.wait_for_result(page)
            page.evaluate(SET, ["offices_strategy", "direct"])
            browser.wait_for_result(page)
            out["before"] = page.evaluate(READ)
            # Точки приходят отдельным запросом после расчёта.
            page.wait_for_function(
                "() => document.querySelectorAll('[data-strategy-compare-card] .strategy-points li').length > 0",
                timeout=60_000)
            out["after"] = page.evaluate(READ)
            out["errors"] = errors
            page.close()
    return out


def test_the_page_draws_the_block_of_the_engine(page_state) -> None:
    state = page_state["after"]
    assert page_state["errors"] == []
    assert state["shown"]
    item = state["engine"]["items"][0]
    assert state["head"] == ["Показатель"] + [
        " ".join([c["label"], *c["tags"]]) for c in item["columns"]]
    assert state["rows"] == [[r["label"]] if r.get("section") else [r["label"], *r["cells"]]
                             for r in item["rows"]]
    assert state["best"] == [item["best"]]
    assert state["lead"] == item["lead"]
    assert "выбрана в проекте" in next(h for h in state["head"] if "Продажа блоками" in h)


def test_the_page_points_are_the_engine_search(page_state) -> None:
    state = page_state["after"]
    x, t = state["inputs"], state["tep"]
    bundle = core._run_authoritative_model(x, t, [], {})
    block = core.strategy_compare_for_report(bundle, x, t, [], {})
    assert state["points"] == [p["text"] for p in block["items"][0]["points"]]
    assert len(state["points"]) == 3 and "подбором полным пересчётом" in state["stamp"]


def test_the_page_shows_the_table_before_the_search(page_state) -> None:
    before = page_state["before"]
    assert before["shown"] and before["rows"]
