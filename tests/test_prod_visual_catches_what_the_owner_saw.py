"""Визуальная проверка прода ловит то, что владелец ловил по скриншотам.

`scripts/prod_visual.py` после выката смотрит отрисованные страницы прода.
Здесь её судьи и снимок страницы проверяются на подделках: страница с
«undefined», пустым блоком и таблицей шире телефона обязана дать замечания,
чистая — ни одного; число PDF, расходящееся со страницей, — замечание, то же
число с другим округлением — нет. Старое замечание не уходит автору нового
выката.

Запуск: python3 -m pytest tests/test_prod_visual_catches_what_the_owner_saw.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

import prod_visual as pv  # noqa: E402

BROKEN = """<!doctype html><html><head><meta name=viewport content="width=device-width">
<style>body{margin:0;font:14px sans-serif} .clip{width:40px;overflow:hidden;white-space:nowrap}</style></head>
<body>
<div class="card" id="rsIncome"><div class="section-title">Структура выручки</div>
  <table style="width:600px"><tr><td>NPV проекта (до финансирования)</td><td>undefined млрд ₽</td></tr>
  <tr><td>Чистая прибыль проекта</td><td>—</td></tr></table></div>
<div class="card" id="emptyCard"><div class="section-title">Сравнение стратегий</div></div>
<div class="clip">Очень длинная подпись плитки</div>
<p style="display:none">NaN скрыт и человеку не виден</p>
<p>Пересчитать производные по вводным · без учёта ГНС; дальше по пресету проекта.</p>
<div class="ia-verdict" id="iaVerdict"><div class="section-title">Инвестиционное решение</div>
  <h2 id="iaVerdictTitle">Экономика проходит</h2><div class="ia-verdict-grid"></div>
  <div class="ia-stamp" id="iaVerdictStamp"></div></div>
</body></html>"""

CLEAN = """<!doctype html><html><head><meta name=viewport content="width=device-width">
<style>body{margin:0;font:14px sans-serif}</style></head><body>
<div class="card"><div class="section-title">Ключевые показатели</div>
  <table><tr><td>NPV проекта (до финансирования)</td><td>1,23 млрд ₽</td></tr>
  <tr><td>IRR проекта (до финансирования)</td><td>18,4%</td></tr></table></div>
<div class="ia-verdict" id="iaVerdict"><div class="section-title">Инвестиционное решение</div>
  <h2 id="iaVerdictTitle">Экономика проходит</h2>
  <div class="ia-verdict-grid"><div class="ia-verdict-cell"><span>Максимум цены входа</span><b>1 450 млн ₽</b>
  <small>При LLCR не ниже 1,20x.</small></div></div>
  <div class="ia-stamp" id="iaVerdictStamp">Подбор выполнен полным пересчётом модели.</div></div>
</body></html>"""


@pytest.fixture(scope="module")
def scans() -> dict:
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright
    import browser

    path = browser.chromium_or_skip()
    out = {}
    with sync_playwright() as pw, pw.chromium.launch(executable_path=str(path)) as engine:
        for name, html in (("broken", BROKEN), ("clean", CLEAN)):
            for size, viewport in (("wide", pv.DESKTOP), ("phone", pv.PHONE)):
                page = engine.new_page(viewport=viewport)
                page.set_content(html)
                out[name, size] = page.evaluate(pv.SCAN_JS, {})
                page.close()
    return out


def _kinds(found: list[pv.Finding]) -> set[str]:
    return {f.kind for f in found}


def test_a_broken_page_is_caught(scans) -> None:
    found = pv.judge_scan(scans["broken", "wide"], "стенд", required=("verdict",))
    kinds = _kinds(found)
    assert "«undefined» в тексте" in kinds
    assert any(f.severity == pv.BREAK and "undefined" in f.kind for f in found)
    assert "заголовок без содержимого" in kinds
    assert "обрезанный текст" in kinds
    assert "прочерк или ноль вместо числа" in kinds
    assert "обязательный блок пуст" in kinds  # «Инвестиционное решение» без плиток
    assert any(k.startswith("жаргон") and "телеграф" in k for k in kinds)
    # Скрытый узел человек не видит — это не замечание.
    assert not any("NaN" in f.kind for f in found)


def test_a_wide_table_on_the_phone_is_caught(scans) -> None:
    found = pv.judge_scan(scans["broken", "phone"], "стенд", layout_only=True)
    overflow = [f for f in found if f.kind == "прокрутка вбок"]
    assert overflow and "#rsIncome" in overflow[0].where


def test_a_clean_page_has_no_findings(scans) -> None:
    assert pv.judge_scan(scans["clean", "wide"], "стенд", required=("verdict",)) == []
    assert pv.judge_scan(scans["clean", "phone"], "стенд", layout_only=True) == []


def test_a_missing_required_block_is_a_break(scans) -> None:
    found = pv.judge_scan(scans["clean", "wide"], "стенд", required=("verdict", "strategy"))
    assert [(f.severity, f.kind, f.where) for f in found] == [
        (pv.BREAK, "обязательный блок не показан", "Сравнение стратегий")]


def test_the_same_number_matches_up_to_rounding() -> None:
    assert pv.same_number("1,23 млрд ₽", "Чистая прибыль проекта 1 234 млн ₽")
    assert pv.same_number("18,4%", "IRR проекта (до финансирования) 18,42 %")
    assert not pv.same_number("1,23 млрд ₽", "Чистая прибыль проекта 1 284 млн ₽")
    assert not pv.same_number("18,4%", "18,4 млн ₽")  # другой род числа


def test_a_number_differing_from_the_page_is_reported(scans) -> None:
    pairs = scans["clean", "wide"]["pairs"]
    same = "NPV проекта (до финансирования) 1 230 млн ₽ IRR проекта (до финансирования) 18,4% " \
           "Максимум цены входа 1,45 млрд ₽"
    assert pv.judge_numbers(pairs, same, "PDF", "жильё") == []
    fake = same.replace("1 230 млн", "1 330 млн")
    found = pv.judge_numbers(pairs, fake, "PDF", "жильё")
    assert [f.where for f in found] == ["NPV проекта (до финансирования)"]
    assert "1,23 млрд ₽" in found[0].text and "1 330 млн" in found[0].text


def test_only_new_findings_go_to_the_author() -> None:
    old = pv.Finding(pv.NOTE, "Главная, жильё", "телеграф", "#iaVerdictStamp", "Подбор 25.10.2026 07:26")
    fresh = pv.Finding(pv.BREAK, "Главная, офис", "«undefined» в тексте", "#rsIncome", "undefined млрд ₽")
    # Первый прогон: прошлого нет — автора у замечаний нет, автору выката не пишем.
    pv.mark_new([old, fresh], None)
    assert not old.new and not fresh.new
    assert pv.author_note([old, fresh], "https://x", {}) == ""
    # Дата в тексте сменилась — замечание то же, а не новое.
    seen = pv.Finding(old.severity, old.surface, old.kind, old.where, "Подбор 26.10.2026 08:01")
    pv.mark_new([old, fresh], {"findings": [{"key": seen.key}]})
    assert not old.new and fresh.new
    note = pv.author_note([old, fresh], "https://x", {})
    assert "#rsIncome" in note and "#iaVerdictStamp" not in note


def test_the_visual_check_runs_after_the_smoke_in_the_same_dispatch() -> None:
    text = (ROOT / ".github/workflows/prod-smoke.yml").read_text(encoding="utf-8")
    job = text.split("\n  visual:\n", 1)
    assert len(job) == 2, "в prod-smoke.yml нет задания visual"
    body = job[1]
    assert "needs: smoke" in body and "if: ${{ !cancelled() }}" in body
    assert "scripts/prod_visual.py" in body and "--baseline" in body
    assert "\n  workflow_run:" not in text  # диспатч от сборки — см. шапку workflow
