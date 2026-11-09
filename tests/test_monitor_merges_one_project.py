"""Один проект под двумя именами сводится в один, ничего не теряя.

«Почему разница между Гродненской и Кутузов Сити? Это один проект»
(владелец, 21.10.2026; главное имя — «Кутузов Сити»).

Проверки:
- проверка только показывает план и ничего не трогает;
- объединение не перезаписывает главный проект: недостающее переезжает,
  журналы дописываются, отметки одного источника сливаются (главный сильнее),
  разное с одним именем ложится рядом и называется;
- старое имя ведёт в главный каталог (чат стройки, бот, ссылки), в списке
  остаётся одно имя, прежний каталог сохранён в `.merged/`;
- получатели рассылки и ссылка-приглашение старого имени переходят к главному;
- на отрисованной странице проверка и объединение делаются кнопками.

Запуск: python3 -m pytest tests/test_monitor_merges_one_project.py -q
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from test_management_report_model import PROJECT, _gpr_book, _project

import developaid_management_report as report
import developaid_monitor as monitor
import developaid_monitor_merge as merge
import developaid_project_notes as notes
import developaid_report_mailing as mailing

MAIN = "Кутузов Сити"
PORT = 18805

# Монитор и сводка — только по ключу администратора (решение владельца
# 02.11.2026): страница и маршруты открываются ключом, а не сессией.
ADMIN_TEST_KEY = "browser-admin-key"


@pytest.fixture(autouse=True)
def _admin_key(monkeypatch):
    monkeypatch.setenv("DEVELOPAID_ADMIN_KEY", ADMIN_TEST_KEY)


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(monitor, "_SNAPSHOT_DIR", tmp_path / "monitor")
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))


def _two_names(*, same_source=False):
    _project()  # «Гродненская»: ГПР, ГПР-факт, РСС
    original = (monitor._project_dir(PROJECT)/'baseline'/'gpr.xlsx').read_bytes()
    monitor.store_schedule(MAIN, original if same_source else _gpr_book({"1": 0.9}), None, "2026-08-21")
    notes.add(PROJECT, "Арбитраж", "Иск подан", "Иванов")
    notes.add(MAIN, "Разрешение на ввод", "Готовим пакет", "Петров")
    monitor.store_work_fact(PROJECT, [{"id": "1", "progress": 0.5},
                                      {"id": "2", "progress": 1.0}], "2026-10-17")
    monitor.store_work_fact(MAIN, [{"id": "1", "progress": 0.7}], "2026-10-17")
    return (monitor._project_dir(MAIN) / "baseline" / "gpr.xlsx").read_bytes()


def test_the_check_only_shows_the_plan():
    _two_names()
    plan = merge.merge(PROJECT, MAIN, "Иванов")
    assert plan["applied"] is False
    assert plan["counts"]["move"] >= 2  # ГПР-факт и РСС
    assert plan["counts"]["append"] == 1 and plan["counts"].get("combine",0) == 0
    assert "baseline/gpr.xlsx" in plan["conflicts"]
    assert 'work_fact/2026-10-17.json' in plan['conflicts']
    assert [item["project"] for item in monitor.projects()] == [PROJECT, MAIN]


def test_merging_keeps_the_main_project_and_adds_what_it_lacks():
    main_gpr = _two_names(same_source=True)
    token = mailing.invite(PROJECT, "Иванов")["start"]
    mailing.subscribe(token, 501, "Пётр")
    done = merge.merge(PROJECT, MAIN, "Иванов", apply=True)
    assert done["applied"] and done["subscribers_moved"] == 1

    assert [item["project"] for item in monitor.projects()] == [MAIN]
    folder = monitor._project_dir(MAIN)
    assert (folder / "baseline" / "gpr.xlsx").read_bytes() == main_gpr
    assert (folder / ".merged-from-Гродненская" / "baseline" / "meta.json").exists()
    assert sorted(p.name for p in (folder / "schedule_fact").glob("*.xlsx")) == [
        "2026-10-09.xlsx", "2026-10-16.xlsx"]
    assert {n["topic"] for n in notes.notes(MAIN)} == {"Арбитраж", "Разрешение на ввод"}
    facts = monitor.work_facts(MAIN)
    assert facts["1"]["progress"] == 0.7 and facts["2"]["progress"] == 1.0

    # Старое имя ведёт в главный каталог: и чтение, и запись.
    assert monitor._project_dir(PROJECT) == folder
    notes.add(PROJECT, "Из чата стройки", "по старому имени", "бот")
    assert "Из чата стройки" in {n["topic"] for n in notes.notes(MAIN)}
    parked = list((monitor._SNAPSHOT_DIR / ".merged").glob("Гродненская-*"))
    assert len(parked) == 1 and (parked[0] / "baseline" / "gpr.xlsx").exists()
    log = (monitor._SNAPSHOT_DIR / ".merged" / "log.jsonl").read_text(encoding="utf-8")
    assert json.loads(log)["by"] == "Иванов"

    # Weekly history survives under the main name, with its real date/value.
    weekly = report.physical(MAIN, "week", "2026-10-16")
    assert weekly["fact_snapshot"] == weekly["snapshot"] == "2026-10-16"
    assert weekly["source"]["fact"] == "2026-10-16"
    assert weekly["fact"] == pytest.approx((180 * .55 + 89 * .40) / 269)
    # Later manual facts from both projects supersede it, without pretending
    # that the weekly file is the source of the current percentages.
    got = report.physical(MAIN, "week", "2026-10-18")
    assert got["snapshot"] == "2026-10-17" and got["fact_snapshot"] is None
    assert got["source"]["manual_works"] == 2
    assert got["source"]["manual_last"] == "2026-10-17"
    assert got["source"]["weekly_present"] is True
    assert got["fact"] == pytest.approx((180 * .7 + 89 * 1.0) / 269)
    assert [row["chat_id"] for row in mailing.subscribers(MAIN)] == [501]
    assert mailing.subscribe(token, 502, "Мария") == MAIN

    with pytest.raises(KeyError):
        merge.merge(PROJECT, MAIN, "Иванов", apply=True)


def test_merging_different_sources_keeps_foreign_equal_id_facts_in_their_archive():
    main_gpr = _two_names()
    source_sha = monitor._baseline_state(PROJECT)['source_sha256']
    target_sha = monitor._baseline_state(MAIN)['source_sha256']
    assert source_sha != target_sha
    done = merge.merge(PROJECT,MAIN,'Проверяющий',apply=True)
    folder = monitor._project_dir(MAIN)
    assert (folder/'baseline'/'gpr.xlsx').read_bytes() == main_gpr
    assert 'work_fact/2026-10-17.json' in done['conflicts']
    assert 'schedule_fact/2026-10-16.xlsx' in done['conflicts']
    archived = folder/'.merged-from-Гродненская'
    foreign = json.loads((archived/'work_fact'/'2026-10-17.json').read_text())
    assert foreign['source_sha256'] == source_sha
    assert {row['id']:row['progress'] for row in foreign['rows']} == {'1':.5,'2':1}
    assert json.loads((archived/'schedule_fact'/'2026-10-16.source.json').read_text())['source_sha256'] == source_sha
    current = monitor.work_facts(MAIN)
    assert current['1']['progress'] == .7 and '2' not in current
    before_manual = report.physical(MAIN,'week','2026-10-16')
    assert before_manual['source']['baseline'] == '2026-08-21'
    assert before_manual['fact_snapshot'] is None
    assert before_manual['fact'] == pytest.approx(180*.9/269)
    after_manual = report.physical(MAIN,'week','2026-10-18')
    assert after_manual['source']['manual_works'] == 1
    assert after_manual['fact'] == pytest.approx(180*.7/269)


def test_identical_source_legacy_facts_keep_their_history_and_gain_explicit_provenance():
    import hashlib
    main_gpr = _two_names(same_source=True)
    for project in (PROJECT,MAIN):
        folder = monitor._project_dir(project)
        for path in (folder/'work_fact').glob('*.json'):
            value = json.loads(path.read_text());value.pop('source_sha256',None)
            path.write_text(json.dumps(value))
        for path in (folder/'schedule_fact').glob('*.source.json'):
            path.unlink()
    merge.merge(PROJECT,MAIN,'Проверяющий',apply=True)
    record = json.loads((monitor._project_dir(MAIN)/'work_fact'/'2026-10-17.json').read_text())
    assert record['source_sha256'] == hashlib.sha256(main_gpr).hexdigest()
    assert {row['id']:row['progress'] for row in record['rows']} == {'1':.7,'2':1}
    assert report.physical(MAIN,'week','2026-10-16')['fact_snapshot'] == '2026-10-16'


def test_legacy_facts_of_another_plan_do_not_gain_the_main_projects_source():
    _two_names()
    source = monitor._project_dir(PROJECT)
    record = source/'work_fact'/'2026-10-17.json'
    value = json.loads(record.read_text());value.pop('source_sha256')
    record.write_text(json.dumps(value))
    for path in (source/'schedule_fact').glob('*.source.json'):
        path.unlink()
    done = merge.merge(PROJECT,MAIN,'Проверяющий',apply=True)
    assert 'work_fact/2026-10-17.json' in done['conflicts']
    assert 'schedule_fact/2026-10-16.xlsx' in done['conflicts']
    assert '2' not in monitor.work_facts(MAIN)
    assert report.physical(MAIN,'week','2026-10-16')['fact_snapshot'] is None


def test_main_baseline_does_not_adopt_a_missing_foreign_version_journal(monkeypatch):
    import datetime as dt
    import developaid_schedule_versions as versions
    old = _two_names(same_source=True)
    monkeypatch.setattr(versions,'_now',lambda:dt.datetime(2026,11,9,12,tzinfo=dt.timezone.utc))
    changed = _gpr_book({'1':.8,'2':.6})
    preview = monitor.schedule_version_preview(PROJECT,changed,'2026-11-09')
    monitor.approve_schedule_version(PROJECT,changed,'2026-11-09',
        expected_previous_sha256=preview['expected_previous_sha256'],
        expected_source_sha256=preview['source_sha256'])
    plan = merge.merge(PROJECT,MAIN,'Проверяющий')
    assert 'baseline/schedule_versions.json' in plan['conflicts']
    merge.merge(PROJECT,MAIN,'Проверяющий',apply=True)
    assert monitor._baseline_file(MAIN,'2026-11-09').read_bytes() == old
    assert monitor._baseline_state(MAIN,'2026-11-09')['revision'] == 0
    assert not (monitor._project_dir(MAIN)/'baseline'/'schedule_versions.json').exists()
    assert (monitor._project_dir(MAIN)/'.merged-from-Гродненская'/'baseline'/'schedule_versions.json').exists()


def test_merge_preserves_an_explicit_permit_row_in_the_main_source():
    import datetime as dt
    import io
    from openpyxl import load_workbook
    _project()
    workbook = load_workbook(io.BytesIO(_gpr_book({})))
    ws = workbook['ГПР']
    ws.append(['permit','3','Ввод','Проект','Получение разрешения на ввод','Работа',0,
               dt.date(2027,9,19),dt.date(2027,9,20),'',2])
    output = io.BytesIO();workbook.save(output)
    main = output.getvalue()
    monitor.store_schedule(MAIN,main,None,'2026-08-21')
    merge.merge(PROJECT,MAIN,'Проверяющий',apply=True)
    assert monitor._baseline_file(MAIN,'2026-10-18').read_bytes() == main
    selected = monitor._read_baseline_gpr(MAIN,'2026-10-18')
    milestone = next(row for row in selected['works'] if row['name']=='Получение разрешения на ввод')
    assert milestone['finish'] == dt.date(2027,9,20)
    construction = [row for row in selected['works'] if row['name']!='Получение разрешения на ввод']
    assert max(row['finish'] for row in construction) == dt.date(2026,12,28)


def test_the_route_names_an_unknown_project(monkeypatch):
    from fastapi import HTTPException

    import main_legacy as core

    _two_names()
    monkeypatch.setattr(core, "_require_web_access", lambda *_a, **_k: None)
    # Пропуск монитора — ключ администратора; здесь проверяется сам маршрут.
    monkeypatch.setattr(core, "_require_admin_key", lambda *_a, **_k: None)
    with pytest.raises(HTTPException) as unknown:
        core.monitor_merge(core.MonitorMergeRequest(source="Нет такого", target=MAIN))
    assert unknown.value.status_code == 404
    with pytest.raises(HTTPException) as same:
        core.monitor_merge(core.MonitorMergeRequest(source=MAIN, target=MAIN))
    assert same.value.status_code == 400


def test_the_page_checks_and_merges(monkeypatch):
    from browser import chromium_or_skip, serve

    chrome = chromium_or_skip()
    from playwright.sync_api import sync_playwright

    import main_legacy as core

    _two_names()
    monkeypatch.setattr(core, "_require_web_access", lambda *_a, **_k: None)
    # Пропуск монитора — ключ администратора; здесь проверяется сам маршрут.
    monkeypatch.setattr(core, "_require_admin_key", lambda *_a, **_k: None)
    with serve(core.app, PORT) as base, sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=str(chrome))
        try:
            tab = browser.new_page()
            errors: list[str] = []
            tab.on("pageerror", lambda e: errors.append(str(e)))
            tab.on("dialog", lambda d: d.accept())
            tab.add_init_script("localStorage.setItem('developaid_web_session','проба');localStorage.setItem('plato_projects_key','browser-admin-key');"
                                f"localStorage.setItem('mgmt_report_project','{MAIN}')")
            tab.goto(f"{base}/report", wait_until="domcontentloaded")
            tab.wait_for_selector("#mergeCard:not(.hidden)")
            source, target = tab.input_value("#mergeSource"), tab.input_value("#mergeTarget")
            disabled = tab.is_disabled("#mergeApplyBtn")
            tab.click("#mergeCheckBtn")
            tab.wait_for_function("document.getElementById('mergePlan').textContent.length>0")
            plan = tab.inner_text("#mergePlan")
            tab.click("#mergeApplyBtn")
            tab.wait_for_function(
                "document.getElementById('mergeMsg').textContent.startsWith('Готово')")
            options = tab.eval_on_selector_all("#project option", "o=>o.map(x=>x.value)")
            hidden = tab.locator("#mergeCard").get_attribute("class")
        finally:
            browser.close()
    assert not errors, errors
    assert (source, target) == (PROJECT, MAIN) and disabled
    assert "перенесётся файлов" in plan and "baseline/gpr.xlsx" in plan
    assert options == [MAIN] and "hidden" in hidden
