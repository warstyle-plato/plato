"""Клик по дому в подсказках проверяет обе формы адреса и сравнивает составы.

Бот находит «Мишина 46», потому что в НСПД уходит строка, набранная
человеком. Подсказка DaData подменяет её нормализованной формой
(«г Москва, ул Мишина, д 46»), которую текстовый поиск НСПД понимает хуже, —
и промах выглядел как «участка нет». Позже той же парой форм разошлась
Гродненская: по сырой строке НСПД видел два участка территории, по подсказке —
один, и оба ответа выглядели достоверно. Поэтому сравниваются составы
найденного, а не «нашлось/пусто»: расширение принимается только внутри
кадастровых кварталов подсказки — жадному геокодеру, собирающему «Мишина 46»
по всей стране, хода нет.

Решение вынесено в чистую функцию houseQueryDecision; здесь через node
гоняется её настоящий код из overlay.js, а не пересказ.

Запуск: python3 -m pytest tests/test_ia_preview_house_click_checks_both_address_forms.py -q
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

_OVERLAY = Path(__file__).resolve().parent.parent / "ia_preview" / "assets" / "overlay.js"

LABEL = "г Москва, ул Гродненская, д 12"
TYPED = "Гродненская 12"
HOME = "77:07:0008006:3"
NEIGHBOUR = "77:07:0008006:25"
STRANGER = "39:15:0000000:1"


def _decision_source() -> str:
    source = _OVERLAY.read_text(encoding="utf-8")
    start = source.index("function houseQueryDecision")
    end = source.index("\n  }", start)
    return source[start : end + len("\n  }")]


def run_decision_cases() -> dict:
    node = shutil.which("node")
    if not node:
        pytest.skip("node недоступен")
    script = _decision_source() + f"""
const LABEL = {json.dumps(LABEL)};
const TYPED = {json.dumps(TYPED)};
const HOME = {json.dumps(HOME)};
const NEIGHBOUR = {json.dumps(NEIGHBOUR)};
const STRANGER = {json.dumps(STRANGER)};
console.log(JSON.stringify({{
  suggestion_works: houseQueryDecision(LABEL, TYPED, [HOME], [HOME]),
  typed_rescues: houseQueryDecision(LABEL, TYPED, [], [HOME]),
  both_empty: houseQueryDecision(LABEL, TYPED, [], []),
  probe_unavailable: houseQueryDecision(LABEL, TYPED, null, null),
  nothing_typed: houseQueryDecision(LABEL, "", [], null),
  territory_wider: houseQueryDecision(LABEL, TYPED, [HOME], [HOME, NEIGHBOUR]),
  greedy_geocoder: houseQueryDecision(LABEL, TYPED, [HOME], [HOME, STRANGER]),
  typed_misses_home: houseQueryDecision(LABEL, TYPED, [HOME], [NEIGHBOUR, STRANGER]),
  typed_probe_failed: houseQueryDecision(LABEL, TYPED, [HOME], null),
  typed_across_regions: houseQueryDecision(LABEL, TYPED, [], [HOME, STRANGER, "66:23:0501021:45"]),
  typed_one_region: houseQueryDecision(LABEL, TYPED, [], [HOME, NEIGHBOUR]),
}}));
"""
    result = subprocess.run(
        [node, "-e", script], capture_output=True, text=True, check=True
    )
    return json.loads(result.stdout)


def test_working_suggestion_runs_without_noise():
    cases = run_decision_cases()
    assert cases["suggestion_works"] == {"query": LABEL, "note": ""}
    assert cases["typed_probe_failed"] == {"query": LABEL, "note": ""}


def test_typed_text_rescues_with_a_warning():
    """Сработал только набранный текст — им и ищем, и об этом сказано."""
    case = run_decision_cases()["typed_rescues"]
    assert case["query"] == TYPED
    assert LABEL in case["note"] and TYPED in case["note"]
    assert "бот" in case["note"]


def test_a_wider_territory_follows_the_typed_text():
    """Гродненская: по сырой строке участков больше — считаем как бот, вслух."""
    case = run_decision_cases()["territory_wider"]
    assert case["query"] == TYPED
    assert "шире" in case["note"] and "бот" in case["note"]
    assert "2" in case["note"] and "1" in case["note"]


def test_the_greedy_geocoder_stays_outside():
    """Чужой квартал в наборе сырой строки — расширение не принимается.

    «Мишина 46» по всей стране — реальный случай: свободный текст собирал
    участки Москвы, Калининграда и Татарстана разом. Такое расхождение — не
    территория, и подсказка остаётся ключом поиска.
    """
    cases = run_decision_cases()
    assert cases["greedy_geocoder"] == {"query": LABEL, "note": ""}
    assert cases["typed_misses_home"] == {"query": LABEL, "note": ""}


def test_both_misses_fall_back_to_the_chain_and_say_so():
    """Обе формы пусты: штатная цепочка доведёт до координат — с пояснением."""
    case = run_decision_cases()["both_empty"]
    assert case["query"] == LABEL
    assert "координат" in case["note"]


def test_unavailable_probe_is_not_a_verdict():
    """Сеть упала — проверка не судья: подсказка идёт как раньше, без плашек."""
    cases = run_decision_cases()
    assert cases["probe_unavailable"] == {"query": LABEL, "note": ""}
    assert cases["nothing_typed"] == {"query": LABEL, "note": ""}


def test_the_layer_wires_the_decision_in():
    """Функция решения без вызова — мёртвый груз: проверяем проводку.

    Клик по дому идёт через resolveHouse, обе формы проверяются параллельно,
    набранный текст запоминается и в подсказках, и в перехвате свободного
    текста, а проверка бьёт в тот же /land/lookup, что и штатная цепочка.
    """
    source = _OVERLAY.read_text(encoding="utf-8")
    assert "resolveHouse(item.label" in source
    assert source.count("lastTypedQuery = ") >= 2, "набранный текст нигде не запоминается"
    assert "fetch('/land/lookup'" in source
    # Подсказка спрашивается в той форме, которой ищет НСПД: каноническое
    # «д 18» он не находит, и запасной путь по сырому тексту срабатывал там,
    # где расхождения нет вовсе.
    assert "houseQueryDecision(asked, typed, probes[0], probes[1])" in source
    assert "nspdAddress(label)" in source
    assert "Promise.all([" in source, "формы проверяются по очереди — плата в цепочку геокодера"
    # Проверка возвращает состав участков, а не «нашлось»: сравнивать больше нечем.
    assert "x.kind === 'land'" in source


def test_a_street_name_repeated_across_the_country_is_not_an_address():
    """«Мишина 46»: подсказка не распозналась, а по тексту участки нашлись в
    Калининграде, Свердловской области и Москве — и все пять ссыпались в поле
    (скриншот владельца, 18.08.2026). Разные округа — это разные улицы с
    одинаковым названием, а не территория."""
    case = run_decision_cases()["typed_across_regions"]
    assert case["query"] == "", "считать по пяти регионам хуже, чем не считать"
    assert "разных регионах" in case["note"]
    assert "уточните адрес" in case["note"] and "кадастровый номер" in case["note"]


def test_one_region_still_rescues():
    """Несколько участков одного округа — это по-прежнему территория адреса."""
    case = run_decision_cases()["typed_one_region"]
    assert case["query"] == TYPED
    assert "не распознал" in case["note"]


def test_an_empty_query_stops_the_calculation():
    source = _OVERLAY.read_text(encoding="utf-8")
    body = source[source.index("function resolveHouse("):]
    body = body[:body.index("function wireSuggest(")]
    assert "if (!decision.query)" in body
    assert "return;" in body[body.index("if (!decision.query)"):]


def test_the_click_puts_the_chosen_address_into_the_field():
    """Клик по подсказке выглядел несработавшим: поле оставалось с набранным
    текстом, и выбор было не видно."""
    source = _OVERLAY.read_text(encoding="utf-8")
    body = source[source.index("} else if (houseLevel) {"):]
    body = body[:body.index("} else {")]
    assert "suggestField.value = item.label" in body
    assert body.index("suggestField.value") < body.index("resolveHouse("), (
        "адрес подставляется до запуска поиска")



def test_the_suggestion_is_asked_in_the_form_nspd_searches() -> None:
    """«д 18» НСПД не находит, «18» находит — спрашиваем второй формой.

    Плашка «подсказку поиск НСПД не распознал» вылезала почти на каждом адресе
    с домом (экран владельца, 01.09.2026), и причина была не в НСПД и не в
    подсказке: мы спрашивали неподходящей формой, а потом честно сообщали, что
    сработал запасной путь.
    """
    import shutil
    import subprocess

    node = shutil.which("node")
    if not node:
        import pytest as _pytest
        _pytest.skip("node недоступен")
    source = _OVERLAY.read_text(encoding="utf-8")
    start = source.index("function nspdAddress(")
    body = source[start:source.index("\n  }", start) + 4]
    script = body + """
const cases = [
  ['г Москва, ул Гродненская, д 18', 'г Москва, ул Гродненская, 18'],
  ['г Москва, ул Веерная, влд. 1', 'г Москва, ул Веерная, 1'],
  ['г Москва, ул Гродненская, 18', 'г Москва, ул Гродненская, 18'],
  // «Стр» и «корп» остаются: это часть адреса, а не форма записи номера дома.
  ['ул Мишина, д 46, стр 2', 'ул Мишина, 46, стр 2'],
];
for (const [given, want] of cases) {
  const got = nspdAddress(given);
  if (got !== want) { console.log('FAIL ' + given + ' -> ' + got); process.exit(1); }
}
console.log('OK');
"""
    done = subprocess.run([node, "-e", script], capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stdout + done.stderr
