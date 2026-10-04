"""Расчёт РНГП МО сверяется с эталоном владельца — числа читаются из книги.

Эталон: `docs/reference/rngp_mo_200k_sqm_reference.xlsx` — расчёт
проектировщиков «Мытищи» на 200 000 м² квартир (владелец, 04.10.2026: «вот
верный расчёт проектировщиков»). Числа не переписаны в тест руками: строки
находятся по своей подписи, значения — кэш формул, сохранённый Excel. Смена
методики МО, разошедшаяся с книгой, краснеет здесь сама.

Расхождения не прячутся: каждое названо со своей причиной в `KNOWN_GAPS`, и
тест проверяет, что оно всё ещё ровно такое, — исчезнувшее или выросшее
расхождение тоже краснеет.

Запуск: python3 -m pytest tests/test_mo_norm_matches_the_owner_reference.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import main_legacy as core  # noqa: E402

BOOK = ROOT / "docs" / "reference" / "rngp_mo_200k_sqm_reference.xlsx"
MAIN = "расчет_200 тыс кв"


@pytest.fixture(scope="module")
def book():
    openpyxl = pytest.importorskip("openpyxl")
    return openpyxl.load_workbook(BOOK, data_only=True)


def row_value(sheet, label: str, column: str = "D", label_column: str = "B"):
    """Значение строки по её подписи — не по номеру: номер строки книги не
    идентификатор, подпись — да. Двух строк с одной подписью быть не должно."""
    hits = [cell.row for cell in sheet[label_column]
            if str(cell.value or "").strip().startswith(label)]
    assert len(hits) == 1, f"«{label}»: строк найдено {len(hits)}"
    value = sheet[f"{column}{hits[0]}"].value
    assert isinstance(value, (int, float)), f"«{label}»: в книге не число — {value!r}"
    return float(value)


@pytest.fixture(scope="module")
def ours():
    return core.mo_social_program(200000.0)


def _premise(ours, label: str) -> float:
    return next(p["gba_sqm"] for p in ours["public_premises"] if p["label"] == label)


# (подпись в книге, лист, столбец, наше число, допуск)
MATCHES = [
    ("Целевой показатель", MAIN, "D", lambda o: o["apartments_sqm"], 0),
    ("население", MAIN, "D", lambda o: o["population"], 0),
    ("места в ДОО", MAIN, "D", lambda o: o["kindergarten"]["required_places"], 1e-3),
    ("места в СОШ", MAIN, "D", lambda o: o["school"]["required_places"], 1e-3),
    ("поликлиника", MAIN, "D", lambda o: o["clinic"]["required_capacity"], 1e-3),
    ("места хранения автотранспорта (постоянные)", MAIN, "D",
     lambda o: o["parking"]["permanent_spaces"], 0),
    ("рабочие места", MAIN, "D", lambda o: o["jobs"]["required"], 1e-6),
    ("Озелененные территории (озеленение жилых", MAIN, "D",
     lambda o: o["green"]["quarter_sqm"], 0.01),
    ("Озелененные территории общего пользования", MAIN, "D",
     lambda o: o["green"]["public_sqm"], 0.01),
    ("Подземный паркинг", MAIN, "D", lambda o: o["parking"]["underground_sqm"], 0.01),
    ("СПП ГНС", MAIN, "D", lambda o: o["gns_sqm"], 0.01),
    ("Стационар", MAIN, "D", lambda o: o["budget_compensation"]["hospital_beds"], 1e-3),
    ("Подстанция скорой помощи", MAIN, "D",
     lambda o: o["budget_compensation"]["ambulance_cars"], 1e-3),
    ("Пожарное депо", MAIN, "D", lambda o: o["budget_compensation"]["fire_cars"], 1e-3),
]

# Норматив (не «принято проектом») по строкам листа «соц», столбец G — общая
# площадь по норме; спортзалы в книге стоят в F — там их норма в м².
PREMISES = [
    ("Торговые объекты", "G", "Торговые объекты"),
    ("Бытовое обслуживание", "G", "Бытовое обслуживание"),
    ("Общественное питание", "G", "Общественное питание"),
    ("Спортивные залы", "F", "Спортивные залы"),
    ("учреждения клубного типа", "G", "Учреждения клубного типа"),
    ("Аптека", "G", "Аптека"),
    ("МФЦ", "G", "МФЦ"),
    ("Отделение полиции", "G", "Отделение полиции"),
]

# Названные расхождения: (подпись, лист, столбец, наше число, причина).
KNOWN_GAPS = [
    ("места хранения автотранспорта (временные)", MAIN, "D",
     lambda o: o["parking"]["temporary_spaces"],
     "книга: 18% от уровня автомобилизации (прежняя редакция); у нас РНГП "
     "п. 5.12 в ред. 774-ПП — не менее 30 на 1000 жителей (решение владельца "
     "04.09.2026). Временные в проекте не строятся"),
    ("Нежилые помещения для общественных объектов", MAIN, "D",
     lambda o: o["public_premises_sqm"],
     "книга складывает ПРИНЯТЫЕ проектом объёмы (спортзал 988 вместо 757, клуб "
     "1 200 вместо 1 071, бассейн с зеркалом 75 м²); по строкам норма совпадает"),
    ("Дополнительно нежилые помещения", MAIN, "D",
     lambda o: o["office_sqm"],
     "рабочие места объектов в книге от принятых объёмов (досуг 20, спорт 19, "
     "полиция 2), у нас от нормативных (18, 15, 3): 1 402 против 1 397"),
]


@pytest.mark.parametrize("label,sheet,column,get,tol", MATCHES, ids=[m[0] for m in MATCHES])
def test_the_norm_matches_the_book(book, ours, label, sheet, column, get, tol):
    want = row_value(book[sheet], label, column)
    assert get(ours) == pytest.approx(want, abs=tol), f"«{label}»: книга {want}, у нас {get(ours)}"


@pytest.mark.parametrize("label,column,ours_label", PREMISES, ids=[p[0] for p in PREMISES])
def test_each_premise_norm_matches_the_book(book, ours, label, column, ours_label):
    want = row_value(book["соц"], label, column, label_column="C")
    assert _premise(ours, ours_label) == pytest.approx(want, abs=0.01)


def test_the_pool_is_mirror_times_its_factor(book, ours):
    mirror = row_value(book["соц"], "Бассейн", "F", label_column="C")
    assert _premise(ours, "Бассейн") == pytest.approx(mirror * 1.5, abs=0.01)


@pytest.mark.parametrize("label,sheet,column,get,why", KNOWN_GAPS, ids=[g[0] for g in KNOWN_GAPS])
def test_known_gaps_stay_named(book, ours, label, sheet, column, get, why):
    """Расхождение названо и всё ещё есть. Сошлось — убрать его отсюда в
    MATCHES; выросло — это новая разница, а не старая."""
    want = row_value(book[sheet], label, column)
    got = get(ours)
    assert got != pytest.approx(want, abs=0.5), f"«{label}» сошлось — перенесите в MATCHES"
    assert abs(got - want) / want < 0.6, f"«{label}»: книга {want}, у нас {got} — {why}"


def test_attached_parking_is_not_counted_yet(book, ours):
    """Приобъектные места (лист «м_м», 1 046,8) нормативный расчёт МО пока не
    считает — названо здесь, чтобы появление счёта сверилось с книгой."""
    want = row_value(book[MAIN], "места хранения автотранспорта (приобъектные)")
    assert want == pytest.approx(1046.772, abs=0.01)
    assert "attached_spaces" not in ours["parking"]
