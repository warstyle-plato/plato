"""Карта территории рисует каждый участок, а какого нарисовать нельзя — называет.

Жалоба с прода (КРТ Нагатино, 20 участков): тизер показывал 10 — номера
проекта брались через `_pdf_screening_numbers`, обрезанный до десяти ради
скрининга полного PDF, — а на карте из середины контура пропал ряд участков.
Теперь тизер читает все номера проекта, карта спрашивает поиск частями (у него
предел 500 символов запроса) и сверяет ответ с номером, а не с местом в списке:
по промаху НСПД отдаёт соседа. Подпись и таблица — одно число участков.
"""
from __future__ import annotations

import copy
import io
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import main as _wrapper  # noqa: E402

core = _wrapper.core

NUMBERS = [f"77:05:0004001:{n}" for n in (2046, 40, 2049, 2045, 2475, 2047, 2048, 41, 2476, 2050,
                                           2051, 2052, 42, 43, 2477, 2478, 2053, 2054, 44, 2479)]
COLUMNS = 10
X0, Y0, SIDE = 4_182_000.0, 7_487_000.0, 100.0
BACKDROP = (40, 90, 200)


def _square(index: int) -> list[list[float]]:
    """Сетка вплотную: без одного участка в середине видна дыра."""
    x = X0 + (index % COLUMNS) * SIDE
    y = Y0 + (index // COLUMNS) * SIDE
    return [[x, y], [x + SIDE, y], [x + SIDE, y + SIDE], [x, y + SIDE]]


def _center(index: int) -> tuple[float, float]:
    ring = _square(index)
    return (ring[0][0] + ring[1][0]) / 2, (ring[0][1] + ring[2][1]) / 2


@pytest.fixture
def nspd(monkeypatch):
    """Фальшивый НСПД: `answers[number]` — что поиск вернул по номеру."""
    from PIL import Image
    asked: dict[str, object] = {}
    answers = {n: {"found": True, "cadastral_number": n, "contour_merc": [_square(i)]}
               for i, n in enumerate(NUMBERS)}
    asked["queries"] = []

    def fake_lookup(req):
        # Как настоящий `land_lookup`: больше 500 символов — отказ, в ответе
        # только спрошенные номера.
        if len(req.query) > 500:
            raise core.HTTPException(status_code=400, detail="Слишком длинный запрос")
        asked["queries"].append(req.query)
        asked_numbers = re.findall(r"\d{2}:\d{2}:\d{6,8}:\d+", req.query)
        return {"results": [answers.get(n, {"found": False, "cadastral_number": n})
                            for n in asked_numbers]}

    def fake_map_image(bbox=""):
        parts = [float(v) for v in bbox.split(",")]
        asked["bbox"] = parts
        width = 800
        height = int(round(width * (parts[3] - parts[1]) / (parts[2] - parts[0])))
        buffer = io.BytesIO()
        Image.new("RGB", (width, height), BACKDROP).save(buffer, format="PNG")
        return type("R", (), {"body": buffer.getvalue()})()

    monkeypatch.setattr(core, "land_lookup", fake_lookup)
    monkeypatch.setattr(core, "land_map_image", fake_map_image)
    # Карты улиц в песочнице нет: тизер берёт кадастровую подложку, как в боте.
    monkeypatch.setattr(core, "land_basemap", lambda bbox="", width=1024: (_ for _ in ()).throw(
        RuntimeError("карта улиц недоступна")))
    return answers, asked


def _drawn(png: bytes, asked: dict) -> list[bool]:
    """Закрашен ли центр каждого участка (полупрозрачная заливка контура)."""
    from PIL import Image
    image = Image.open(io.BytesIO(png)).convert("RGB")
    min_x, min_y, max_x, max_y = asked["bbox"]
    out = []
    for index in range(len(NUMBERS)):
        cx, cy = _center(index)
        px = int((cx - min_x) / (max_x - min_x) * image.width)
        py = int((max_y - cy) / (max_y - min_y) * image.height)
        out.append(image.getpixel((px, py)) != BACKDROP)
    return out


def test_every_parcel_of_the_territory_is_on_the_map(nspd):
    _, asked = nspd
    png, caption = core._territory_image_png(NUMBERS)
    assert all(any(n in q for q in asked["queries"]) for n in NUMBERS)
    assert _drawn(png, asked) == [True] * len(NUMBERS)
    assert f"Территория из {len(NUMBERS)} участков" in caption
    # Пять номеров из десяти без «ещё» читаются как «на карте пять участков».
    assert f"и ещё {len(NUMBERS) - 5}" in caption
    assert "нет границ" not in caption


def test_a_neighbour_is_not_drawn_in_place_of_the_asked_parcel(nspd):
    """По номеру из середины поиск вернул соседа: соседа не выдают за
    запрошенный участок, дыра на карте названа в подписи."""
    answers, asked = nspd
    hole = 2
    answers[NUMBERS[hole]] = dict(answers[NUMBERS[hole + 1]])
    png, caption = core._territory_image_png(NUMBERS)
    drawn = _drawn(png, asked)
    assert drawn[hole] is False and sum(drawn) == len(NUMBERS) - 1
    assert f"Территория из {len(NUMBERS)} участков" in caption
    assert f"контур нарисован для {len(NUMBERS) - 1} из {len(NUMBERS)}" in caption
    assert NUMBERS[hole] in caption.split("контур нарисован")[1]


def test_a_parcel_without_geometry_is_named(nspd):
    answers, _ = nspd
    answers[NUMBERS[7]] = {"found": True, "cadastral_number": NUMBERS[7], "contour_merc": []}
    answers[NUMBERS[8]] = {"found": False, "cadastral_number": NUMBERS[8]}
    _, caption = core._territory_image_png(NUMBERS)
    tail = caption.split("контур нарисован")[1]
    assert f"для {len(NUMBERS) - 2} из {len(NUMBERS)}" in tail
    assert NUMBERS[7] in tail and NUMBERS[8] in tail


def test_the_same_parcel_written_differently_is_one_parcel(nspd):
    """Ведущие нули в части номера — тот же участок, а не пропажа."""
    answers, asked = nspd
    answers[NUMBERS[1]] = dict(answers[NUMBERS[1]], cadastral_number="77:05:4001:040")
    png, caption = core._territory_image_png(NUMBERS)
    assert _drawn(png, asked) == [True] * len(NUMBERS)
    assert "нет границ" not in caption


def test_the_map_and_the_table_count_the_same_parcels(nspd):
    """Подпись под картой и строка таблицы тизера — одно число участков."""
    import teaser_pdf
    _, caption = core._territory_image_png(NUMBERS)
    fm = teaser_pdf._Formats(core._pdf_num)
    rows = teaser_pdf._site_rows({"cadastral_numbers": NUMBERS}, {}, fm)
    label = next(label for label, _, _ in rows if label.startswith("Кадастровые номера"))
    assert f"({len(NUMBERS)})" in label
    assert f"Территория из {len(NUMBERS)} участков" in caption


def test_a_thirty_parcel_territory_is_asked_in_parts(nspd):
    """Предел проекта — 30 участков; одним запросом это больше 500 символов,
    и вся карта пропадала. Частями — каждый участок на карте."""
    answers, asked = nspd
    extra = [f"77:05:0004001:{3000 + i}" for i in range(10)]
    for i, n in enumerate(extra):
        answers[n] = {"found": True, "cadastral_number": n, "contour_merc": [_square(len(NUMBERS) + i)]}
    made = core._territory_image_png(NUMBERS + extra)
    assert made is not None
    assert len(asked["queries"]) > 1 and all(len(q) <= 500 for q in asked["queries"])
    assert "Территория из 30 участков" in made[1] and "нет границ" not in made[1]


def test_the_teaser_takes_every_number_of_the_project(nspd):
    """Сквозь всю цепочку: 20 номеров во вводных → 20 в таблице тизера,
    20 в подписи карты, 20 контуров на карте."""
    import teaser_pdf
    from pypdf import PdfReader
    _, asked = nspd
    inputs = copy.deepcopy(core.DEFAULT_INPUTS)
    inputs["_land_lookup"] = {"query": ", ".join(NUMBERS)}
    tep = copy.deepcopy(core.TEP_DEFAULT)
    site = core._teaser_site({}, inputs)
    assert site["cadastral_numbers"] == NUMBERS
    made = core._teaser_map_png(site)
    assert made is not None
    png, caption = made
    assert _drawn(png, asked) == [True] * len(NUMBERS)
    bundle = core._run_authoritative_model(inputs, tep, [], None)
    pdf = core.build_teaser_pdf(bundle, inputs, tep, None, site, made)
    text = " ".join(" ".join(page.extract_text() for page in PdfReader(io.BytesIO(pdf)).pages).split())
    assert f"Кадастровые номера ({len(NUMBERS)})" in text
    assert f"Территория из {len(NUMBERS)} участков" in text
    assert f"ещё {len(NUMBERS) - teaser_pdf.MAX_CADASTRAL_SHOWN}" in text


def test_the_full_report_screening_still_takes_ten():
    """Полный PDF по-прежнему скринит первые десять (скрининг дорог), а список
    проекта — все номера: обрезка живёт у одного читателя, а не в источнике."""
    inputs = {"_land_lookup": {"query": ", ".join(NUMBERS + NUMBERS[:3])}}
    assert core._project_cadastral_numbers(inputs) == NUMBERS
    assert core._pdf_screening_numbers(inputs) == NUMBERS[:10]
