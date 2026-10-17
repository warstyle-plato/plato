"""Производные машино-мест в сохранённом проекте — числа движка, а не хвост.

Файл «Архитектора Власова» (владелец, 15.10.2026, прод 0.25.83): пара мест
подземного паркинга помечена нормой (`_parking_by_norm`), в ней 201 место и
7 538 м², в строке ТЭП 109 гостевых — умолчание шаблона (1 199 мест / 11), —
и у ДОО 250 переданных мест при нуле мест. Движок по файлу считает 201 место,
7 537,5 м², 19 гостевых и 182 к продаже, а в файле после сохранения оставались
109 и 7 538. Причин было три:

* обратная запись гостевых стояла только в одиночной ветке расчёта — проект
  с очередями хранил хвост вечно;
* страница ставила в строку ТЭП число поля, даже когда пару поставила норма, —
  округлённую площадь, а у устаревшей пары и чужие места (201 при норме 264);
* снимок для файла и хранилища брал строку как есть, и выгрузка записи из
  списка несла число, которого движок для неё не считал.

Проверяется на отрисованной странице: загрузка снимка → расчёт → снимок для
сохранения; и на движке.

Запуск: python3 -m pytest tests/test_saved_parking_tail_heals.py -q
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import browser  # noqa: E402
import main_legacy as core  # noqa: E402

PORT = 18977


def vlasov_settings() -> dict:
    """Файл настроек той же формы, что у «Власова»: 227 квартир по 60 м² дают
    по 2118-ПП 182 постоянных + 19 гостевых = 201 место."""
    data = json.loads((ROOT / "tests" / "fixtures" / "project_settings_donskoy_0_25_78.json")
                      .read_text(encoding="utf-8"))
    data["name"] = "Власова (форма)"
    data["inputs"].update({
        "_parking_by_norm": ["underground"], "_parking_by_hand": [],
        "underground_manual_spaces": 201, "underground_manual_gns_sqm": 7538,
        "underground_area_per_space_sqm": 37.5, "parking_design_mode": "maximum",
        "parking_k1": 0.75, "parking_k2": 0.7, "parking_price_th": 10000})
    data["inputs"].get("_class_manual", []).append("underground_area_per_space_sqm")
    data["tep"]["apartments"] = {"gns": 15133.3, "total_area": 13620, "useful": 13620,
                                 "saleable": 13620, "transfer": 0, "units": 227}
    data["tep"]["underground_parking"] = {"gns": 7538, "total_area": 7538, "useful": 0,
                                          "saleable": 0, "transfer": 0, "units": 201,
                                          "guest_units": 109}
    data["tep"]["kindergarten"] = {"gns": 0, "total_area": 0, "transfer": 0, "units": 0,
                                   "transfer_units": 250}
    return data


def _engine_row(data: dict, key: str) -> dict:
    result = core.calculate(core.CalcRequest(
        inputs={**core.DEFAULT_INPUTS, **data["inputs"]},
        tep=copy.deepcopy(data["tep"]), rates=[]))
    return next(r for r in result["tep"]["rows"] if r["key"] == key)


def test_the_engine_ignores_the_tail() -> None:
    row = _engine_row(vlasov_settings(), "underground_parking")
    assert (row["units"], row["gns"], row["guest_units"], row["saleable_units"]) == \
        (201, 7537.5, 19, 182)
    assert _engine_row(vlasov_settings(), "kindergarten")["transfer_units"] == 0


PROBE = r"""async ([data, phased]) => {
  if (phased) data.phasing = Object.assign(makeDefaultPhasing(2), {enabled: true, user_enabled: true});
  // Снимок для файла собирают те же функции, что у кнопок; на коде до правки
  // их нет — тогда снимок строкой как есть, и проверка падает на числах.
  const fileTep = (source, fresh) => typeof persistedTep === 'function'
    ? persistedTep(source, fresh) : JSON.parse(JSON.stringify(source));
  // Расчёт ждётся по признаку, а не по времени: `calculate` возвращает null,
  // если его перебил запущенный следом (номер расчёта), и тогда записывает
  // тот, следующий. Признак «движок ответил на ЭТУ загрузку» — отданный хвост
  // (`derivedState().tail.settled`); без функции (код до правки) — ответ есть.
  const answered = async () => {
    await calculate();
    for (let i = 0; i < 600; i++) {
      const tail = typeof derivedState === 'function' ? derivedState().tail : {settled: true};
      if (tail && tail.settled && ((phaseBundle && phaseBundle.consolidated) || lastResult)) return;
      await new Promise(r => setTimeout(r, 50));
    }
    throw new Error('расчёт после загрузки так и не ответил');
  };
  const copy = value => JSON.parse(JSON.stringify(value === undefined ? null : value));
  applyProjectSnapshot(data);
  const beforeCalc = projectStorePayload().payload.tep.underground_parking;
  await answered();
  // Снимок живой строки — сразу после ответа: дальше её снимает повторная загрузка.
  const live = copy(tep.underground_parking), kg = copy(tep.kindergarten);
  const result = (phaseBundle && phaseBundle.consolidated) || lastResult;
  const row = result.tep.rows.find(r => r.key === 'underground_parking');
  renderResult();
  const table = (document.getElementById('report') || document.body).innerText;
  const noticeEl = document.getElementById('pageNotice');
  const notice = noticeEl ? noticeEl.innerText.trim() : '';
  const stored = projectStorePayload().payload.tep;
  // Повторная загрузка того, что сохранили: числа уже движка — сказать нечего.
  if (noticeEl) noticeEl.remove();
  const again = JSON.parse(JSON.stringify(data));
  again.tep = stored;
  applyProjectSnapshot(again);
  await answered();
  const againEl = document.getElementById('pageNotice');
  // Выгрузка записи из списка без открытия: снимок без расчёта.
  const recordFile = fileTep(data.tep, false);
  return {phased: !!phaseBundle, row: {units: row.units, gns: row.gns, guest: row.guest_units,
          sold: row.saleable_units},
          live, kg, stored: stored.underground_parking,
          storedKg: stored.kindergarten, beforeCalc, recordFile: recordFile.underground_parking,
          recordKg: recordFile.kindergarten, notice, journal: window.__journal || [],
          tableSaysFixed: /исправлено при загрузке/.test(table),
          againNotice: againEl ? againEl.innerText.trim() : '',
          fields: [inputs.underground_manual_spaces, inputs.underground_manual_gns_sqm]};
}"""


@pytest.fixture(scope="module")
def page_states() -> dict:
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright

    path = browser.chromium_or_skip()
    got = {}
    with browser.serve(core.app, PORT) as base, sync_playwright() as pw:
        with pw.chromium.launch(executable_path=str(path)) as engine:
            for phased in (False, True):
                page = engine.new_page(viewport={"width": 1440, "height": 900})
                journal: list = []
                page.on("request", lambda r, j=journal: j.append(r.post_data_json)
                        if r.url.endswith("/tep-corrections") else None)
                page.goto(base, wait_until="domcontentloaded")
                page.wait_for_timeout(1500)
                got[phased] = page.evaluate(PROBE, [vlasov_settings(), phased])
                page.wait_for_timeout(300)
                got[phased]["journal"] = journal
                page.close()
    return got


@pytest.mark.parametrize("phased", [False, True])
def test_the_page_row_is_the_engine_row(page_states, phased) -> None:
    state = page_states[phased]
    assert state["phased"] is phased, state
    assert state["row"] == {"units": 201, "gns": 7537.5, "guest": 19, "sold": 182}, state
    live = state["live"]
    assert (live["units"], live["gns"], live["guest_units"]) == (201, 7537.5, 19), state
    assert state["kg"]["transfer_units"] == 0, state


@pytest.mark.parametrize("phased", [False, True])
def test_the_saved_file_carries_the_engine_numbers(page_states, phased) -> None:
    state = page_states[phased]
    assert state["stored"]["guest_units"] == 19, state
    assert state["stored"]["gns"] == 7537.5, state
    assert state["storedKg"]["transfer_units"] == 0, state


def test_a_snapshot_without_a_calculation_carries_no_derived_numbers(page_states) -> None:
    # Отсутствие — «выведет движок», а не ноль и не чужое число.
    state = page_states[False]
    assert "guest_units" not in state["beforeCalc"], state
    assert "guest_units" not in state["recordFile"], state
    assert "transfer_units" not in state["recordKg"], state


def test_the_table_is_silent_and_the_notice_names_the_numbers(page_states) -> None:
    # Владелец, 16.10.2026: «Зачем эта надпись? … Убрать из таблицы».
    # Исправление молча в таблице, одна строка во всплывающем уведомлении.
    state = page_states[False]
    assert not state["tableSaysFixed"], state
    notice = state["notice"]
    assert notice.startswith("В файле исправлены устаревшие числа"), notice
    assert "гостевые места 109 → 19 (норматив)" in notice, notice
    assert "переданные места ДОО 250 → 0" in notice, notice


def test_the_journal_gets_the_same_list(page_states) -> None:
    journal = page_states[False]["journal"]
    assert len(journal) == 1, journal
    got = {(c["key"], c["was"], c["now"]) for c in journal[0]["corrections"]}
    assert got == {("underground_parking", 109, 19), ("kindergarten", 250, 0)}, journal
    assert journal[0]["text"] == page_states[False]["notice"]


def test_a_healed_file_loads_without_a_notice(page_states) -> None:
    assert page_states[False]["againNotice"] == "", page_states[False]


def test_the_route_writes_the_journal(monkeypatch) -> None:
    from fastapi.testclient import TestClient
    seen = []
    monkeypatch.setattr(core, "usage_track", lambda kind, **kw: seen.append((kind, kw)))
    answer = TestClient(core.app).post("/tep-corrections", json={
        "text": "x", "corrections": [{"key": "underground_parking", "field": "guest_units",
                                      "was": 109, "now": 19}, {"key": "bad", "was": "?"}]})
    assert answer.json() == {"ok": True, "recorded": 1}
    assert seen[0][0] == "tep_corrections"
    assert seen[0][1]["corrections"] == [{"key": "underground_parking", "field": "guest_units",
                                          "was": 109.0, "now": 19.0}]

def test_object_guest_spaces_round_half_up_like_the_book() -> None:
    # Книга считает гостевые объекта `ROUND(места × доля; 0)` — половина вверх.
    # round() Python вёл её к чётному: 25 мест × 10% давали 2 у движка и 3 в
    # книге, и проданных мест у движка было на одно больше.
    x = {**core.DEFAULT_INPUTS, "offices_enabled": True, "offices_gba_sqm": 40000.0,
         "offices_saleable_sqm": 24000.0, "offices_parking_under_spaces": 25,
         "offices_parking_guest_pct": 10, "_parking_by_hand": ["offices"]}
    t = copy.deepcopy(core.TEP_DEFAULT)
    t["offices"].update(gns=40000, total_area=37600, saleable=24000)
    result = core.calculate(core.CalcRequest(inputs=x, tep=t, rates=[]))
    row = next(r for r in result["tep"]["rows"] if r["key"] == "offices")
    assert (row["parking_units"], row["parking_guest_units"]) == (25, 3), row
