"""Карта территории рисует каждый участок, а какого нарисовать нельзя — называет.

Жалоба с прода (КРТ из 10 участков): из середины контура пропал ряд участков,
а подпись называла пять номеров из десяти. Поиск НСПД по промаху отдаёт
соседний объект, и карта рисовала соседа вместо запрошенного участка, считая
его найденным. Теперь ответ сверяется с номером, а не с местом в списке;
подпись и таблица тизера показывают одно число участков.
"""
from __future__ import annotations

import io
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import main as _wrapper  # noqa: E402

core = _wrapper.core

NUMBERS = [f"77:05:0004001:{n}" for n in (2046, 40, 2049, 2045, 2475, 2047, 2048, 41, 2476, 2050)]
X0, Y0, SIDE = 4_182_000.0, 7_487_000.0, 100.0
BACKDROP = (40, 90, 200)


def _square(index: int) -> list[list[float]]:
    """Сетка 5×2 вплотную: без одного участка в середине видна дыра."""
    x = X0 + (index % 5) * SIDE
    y = Y0 + (index // 5) * SIDE
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

    def fake_lookup(req):
        asked["query"] = req.query
        return {"results": [answers[n] for n in NUMBERS]}

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
    assert all(NUMBERS[i] in asked["query"] for i in range(len(NUMBERS)))
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
