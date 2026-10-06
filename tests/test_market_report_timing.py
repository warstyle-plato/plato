"""«Отчёт по рынку»: плановый ввод, стадии конкурентов и сравнение с нами.

Владелец (06.10.2026): плановый ввод и стадии уже есть в «Как посчитана цена» —
вставить их для сравнения и в отчёт по рынку. Проверяется:

* поля соседа в отчёте — те же, что у «Как посчитана цена» (один владелец
  `analog_timing`), а не второй расчёт;
* сравнение с нашим проектом: ввод раньше/одновременно/позже, кто продаёт в
  наше окно, цены аналогов той же стадии;
* пустое поле приходит причиной, а не молчаливым прочерком;
* на отрисованной карточке (настоящий `timingCard` страницы кабинета на node)
  видно всё это — и проверка падает на подделке, печатающей прочерк.
"""

from __future__ import annotations

import json
import math
import re
import sys
from datetime import date
from html.parser import HTMLParser
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import page_blocks  # noqa: E402
from market_search import timing  # noqa: E402
from market_search.cabinet import CABINET_PAGE  # noqa: E402
from market_search.metrics import BLOCK_PRICE  # noqa: E402
from market_search.service_v6 import MarketDiscoveryService  # noqa: E402

SITE = (55.7500, 37.6000)

# id: имя, цена, страница проекта (даты), стадия Пульса
PEERS = {
    11: ("Альфа", 400_000,
         {"sales_start": "2025-03-01", "commissioning": "2029-03-01",
          "commissioning_first": "2028-06-01", "commissioning_raw": "28/II-29/I",
          "source": "Пульс Продаж Новостроек · онлайн",
          "sources": {"sales_start": "pulse_project_page", "commissioning": "pulse_project_page"}},
         {"raw": "Котлован", "source": "pulse_project_page", "as_of": "2026-10-01",
          "distribution": [{"raw": "Котлован", "buildings": 2},
                           {"raw": "Монолитные работы", "buildings": 1}],
          "latest_raw": "Монолитные работы", "rule": "самая ранняя незавершённая"}),
    12: ("Бета", 600_000,
         {"sales_start": "2023-01-01", "commissioning": "2026-09-01",
          "source": "Пульс Продаж Новостроек · онлайн"},
         {}),
    13: ("Гамма", 450_000, {}, {"reason": "на странице проекта нет подписи «Стадия строительства»"}),
    14: ("Дельта", 500_000,
         {"commissioning": "2030-12-01", "source": "Пульс Продаж Новостроек · онлайн"},
         {"raw": "Котлован", "source": "pulse_project_page"}),
}


def _service(tmp_path: Path) -> MarketDiscoveryService:
    service = MarketDiscoveryService(tmp_path)
    service.verified_prices.today = date(2026, 10, 6)
    projects = [
        {"complex_id": cid, "name": name, "developer": "—", "address": f"Москва, {name}",
         "latitude": SITE[0] + 0.004 * n, "longitude": SITE[1]}
        for n, (cid, (name, *_rest)) in enumerate(PEERS.items(), 1)
    ]

    def near(lat, lon, radius_km):
        out = []
        for row in projects:
            dy = (row["latitude"] - lat) * 111.0
            dx = (row["longitude"] - lon) * 111.0 * math.cos(math.radians(lat))
            out.append((round(math.hypot(dx, dy), 3), SimpleNamespace(**row)))
        return sorted(out, key=lambda item: item[0])

    metrics = {cid: {"complex_id": cid, "price_per_sqm": row[1], "observed_at": "2026-10-01"}
               for cid, row in PEERS.items()}
    service.pulse = SimpleNamespace(
        available=True,
        segments=lambda: {cid: "Комфорт" for cid in PEERS},
        near=near,
        metrics=lambda cid: dict(metrics.get(cid, {})),
        price=lambda cid: {"price_per_sqm": PEERS[cid][1], "observed_at": "2026-10-01"},
        project_totals=lambda cid: {},
        find_project=lambda query: None,
        price_history=lambda ids, months=12: {},
        remaining=lambda cid: {},
        project_dates=lambda cid: dict(PEERS[cid][2]),
        project_stage=lambda cid: dict(PEERS[cid][3]),
        project_facts=lambda cid: {},
    )
    service.cards.card = lambda cid: {}
    return service


def _report(service, **kwargs):
    return service.build_report(f"{SITE[0]:.5f}, {SITE[1]:.5f}", codes=[BLOCK_PRICE],
                                include_timing=True, **kwargs)


def _by_name(rows):
    return {row["name"]: row for row in rows}


# --- сервер -----------------------------------------------------------------

FIELDS = ("sales_start", "commissioning", "commissioning_first", "commissioning_raw",
          "calendar_progress_pct", "stage_label", "construction_stage",
          "construction_stage_label", "construction_stage_origin",
          "construction_stage_distribution", "construction_stage_latest_label",
          "construction_stage_reason", "date_source")


def test_report_fields_are_the_price_page_fields(tmp_path: Path) -> None:
    service = _service(tmp_path)
    report = _by_name(_report(service)["peers"])
    hint = service.price_hint(address="Москва", latitude=SITE[0], longitude=SITE[1],
                              include_projects=True)
    shown = _by_name(hint["projects"])
    assert set(report) == set(shown) == {"Альфа", "Бета", "Гамма", "Дельта"}
    for name in report:
        for key in FIELDS:
            assert report[name].get(key) == shown[name].get(key), (name, key)
    alpha = report["Альфа"]
    assert alpha["commissioning"] == "2029-03-01"
    assert alpha["commissioning_first"] == "2028-06-01"
    assert alpha["construction_stage_distribution"][0] == {"raw": "Котлован", "buildings": 2}


def test_empty_fields_carry_a_reason(tmp_path: Path) -> None:
    gamma = _by_name(_report(_service(tmp_path))["peers"])["Гамма"]
    assert gamma["commissioning"] is None
    assert "срок ввода не назван" in gamma["commissioning_reason"]
    assert gamma["calendar_reason"] == "нет ни старта продаж, ни планового ввода"
    assert "Стадия строительства" in gamma["construction_stage_reason"]


def test_without_our_dates_the_comparison_says_why(tmp_path: Path) -> None:
    got = _report(_service(tmp_path))["timing"]
    assert got["commissioning"]["available"] is False
    assert "нет проекта в Пульсе" in got["commissioning"]["reason"]
    assert got["overlap"]["available"] is False
    # Стадия для сравнения у площадки — объявленная подсказка, а не догадка.
    assert got["same_stage"]["stage"]["code"] == "pit"


def test_our_dates_against_competitors(tmp_path: Path) -> None:
    report = _report(_service(tmp_path), project_sales_start="2026-12",
                     project_commissioning="2029-06")
    got = report["timing"]
    assert got["subject"]["origin"] == "manual"
    com = got["commissioning"]
    # Альфа −3 мес. — одновременно; Бета раньше; Дельта позже; у Гаммы срока нет.
    assert (com["earlier"], com["same"], com["later"], com["unknown"]) == (1, 1, 1, 1)
    ov = got["overlap"]
    assert ov["window"] == {"from": "2026-12", "to": "2029-06"}
    assert {row["name"] for row in ov["peers"]} == {"Альфа", "Дельта"}
    assert ov["unknown"] == 1
    peers = _by_name(report["peers"])
    assert peers["Бета"]["vs_ours"]["overlap"] is False
    assert peers["Гамма"]["vs_ours"]["overlap"] is None
    assert peers["Гамма"]["vs_ours"]["overlap_reason"]
    same = got["same_stage"]
    assert same["stage"]["code"] == "pit"
    assert {row["name"] for row in same["peers"]} == {"Альфа", "Дельта"}
    assert same["median_price_per_sqm"] == 450_000


def test_sold_out_peer_does_not_sell_with_us() -> None:
    subject = {"sales_start": "2026-12", "commissioning": "2029-06"}
    peer = {"name": "Распродан", "sales_start": "2025-01-01", "commissioning": "2029-01-01",
            "remaining_units": 0, "price_per_sqm": 1}
    got = timing.compare(subject, [peer], "2026-10-06")
    assert got["overlap"]["count"] == 0
    assert peer["vs_ours"]["overlap"] is False
    assert "распродан" in peer["vs_ours"]["overlap_reason"]


def test_the_route_asks_for_timing() -> None:
    from market_search.api import ReportRequest

    req = ReportRequest(query="Москва", project_commissioning="2029-06")
    assert req.project_commissioning == "2029-06"
    source = (ROOT / "market_search" / "api.py").read_text(encoding="utf-8")
    route = source[source.index('@app.post("/market/report")'):]
    route = route[:route.index("@app.post", 10)]
    assert "include_timing=True" in route
    assert "project_commissioning=req.project_commissioning" in route


# --- отрисованная страница --------------------------------------------------

class _Cells(HTMLParser):
    """Текст карточки и ячейки таблицы сроков — то, что видит человек."""

    def __init__(self) -> None:
        super().__init__()
        self.rows: list[list[str]] = []
        self.text: list[str] = []
        self._cell: list[str] | None = None
        self._table = False

    def handle_starttag(self, tag, attrs):
        if tag == "table" and dict(attrs).get("id") == "timingTable":
            self._table = True
        if self._table and tag == "tr":
            self.rows.append([])
        if self._table and tag in ("td", "th"):
            self._cell = []

    def handle_endtag(self, tag):
        if tag == "table":
            self._table = False
        if tag in ("td", "th") and self._cell is not None:
            self.rows[-1].append(" ".join("".join(self._cell).split()))
            self._cell = None

    def handle_data(self, data):
        self.text.append(data)
        if self._cell is not None:
            self._cell.append(data)


def _render(report: dict, page: str = CABINET_PAGE) -> _Cells:
    out, _ = page_blocks.run(f"const d={json.dumps(report, ensure_ascii=False)};",
                             "console.log(timingCard(d));", page=page)
    cells = _Cells()
    cells.feed(out.replace(" ", " "))
    return cells


def _check(cells: _Cells) -> None:
    text = " ".join("".join(cells.text).split())
    head, *rows = cells.rows
    assert head[1] == "Плановый ввод (последний корпус)"
    assert head[3] == "Стадия строительства" and head[4] == "Календарная стадия"
    table = {row[0]: row for row in rows}
    alpha = table["Альфа"]
    assert alpha[1].startswith("март 2029") and alpha[2] == "июнь 2028"
    assert "Котлован — 2 корп.; Монолитные работы — 1 корп." in alpha[3]
    assert alpha[4].startswith("ранняя стадия")
    assert alpha[5].startswith("одновременно с нами") and alpha[6].startswith("да")
    gamma = table["Гамма"]
    assert gamma[1].startswith("нет данных: срок ввода не назван")
    assert gamma[4] == "нет данных: нет ни старта продаж, ни планового ввода"
    # Ни одной пустой или «прочерковой» ячейки: пустое — это причина.
    for row in rows:
        for cell in row:
            assert cell and cell not in ("—", "-"), row
    assert "Продают одновременно с нами: 2: Дельта (31 мес.), Альфа (28 мес.)" in text
    assert "медиана 450 000 ₽/м²" in text
    assert "Раньше нас вводятся 1, одновременно — 1, позже — 1, без срока ввода — 1" in text


def test_the_card_shows_timing_on_the_rendered_page(tmp_path: Path) -> None:
    report = _report(_service(tmp_path), project_sales_start="2026-12",
                     project_commissioning="2029-06")
    _check(_render(report))


def test_the_check_fails_on_a_silent_dash(tmp_path: Path) -> None:
    """Подделка: пустой ввод печатается прочерком — проверка обязана упасть."""
    report = _report(_service(tmp_path), project_sales_start="2026-12",
                     project_commissioning="2029-06")
    fake = CABINET_PAGE.replace(":noData(p.commissioning_reason)}</td>`", ":'—'}</td>`", 1)
    assert fake != CABINET_PAGE
    with pytest.raises(AssertionError):
        _check(_render(report, fake))


def test_the_card_is_in_the_report_and_out_of_print_controls() -> None:
    body = page_blocks.function("render", CABINET_PAGE)
    assert "html+=timingCard(d);" in body
    assert re.search(r"@media print\{\s*\.tm-form\{display:none\}", CABINET_PAGE)
