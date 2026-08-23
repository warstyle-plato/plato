"""Карточка КРТ показывает посчитанное, а не запускает счёт заново.

Три вещи проверяются на настоящем коде страницы торгов и страницы модели:

* карточка при открытии идёт за готовым отчётом, а не за пересчётом;
* «Передать в DevelopAid» кладёт в мост те самые вводные, которыми отчёт
  посчитан, — своей сборки модели на странице нет;
* мост на стороне калькулятора накладывает их одной общей функцией
  `applyProjectSnapshot`, а не четвёртой копией того же кода.

Запуск: python3 -m pytest tests/test_krt_card_shows_what_was_counted.py -q
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import main_legacy as core  # noqa: E402
from auction_search import bridge  # noqa: E402
from auction_search.ui import auctions_page  # noqa: E402


def page_script(html: str) -> str:
    start = html.rindex("<script>")
    return html[start + len("<script>"):html.rindex("</script>")]


def test_the_auctions_page_script_parses() -> None:
    """340 килобайт одним блоком: сломанный синтаксис не даёт ни одной функции."""
    node = shutil.which("node")
    if not node:
        pytest.skip("node недоступен")
    done = subprocess.run([node, "--check", "-"], input=page_script(auctions_page()),
                          capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr[:800]


def test_the_card_opens_the_stored_report() -> None:
    script = page_script(auctions_page())
    assert "loadKrtReport(x)" in script, "карточка идёт за готовым отчётом"
    assert "/report'" in script or "/report\"" in script or "+'/report'" in script
    assert "'Пересчитать сейчас'" in script or "Пересчитать сейчас" in script


def test_a_missing_report_is_not_a_failure() -> None:
    """404 значит «ещё не считали» — это ответ, а не поломка."""
    script = page_script(auctions_page())
    body = script[script.index("async function loadKrtReport("):]
    body = body[:body.index("\nfunction renderKrtReport(")]
    assert "r.status===404" in body
    assert "r.status===401" in body, "закрытый кабинет называется своим именем"


def test_the_handoff_sends_the_counted_inputs_not_a_new_model() -> None:
    script = page_script(auctions_page())
    body = script[script.index("async function handoffKrt("):]
    body = body[:body.index("\nasync function askPlatoAboutKrt(")]
    assert "/handoff" in body, "вводные берутся с сервера, а не собираются здесь"
    assert "krt_model:{inputs:d.inputs,tep:d.tep,phasing:d.phasing}" in body
    assert "developaid.auction.pending.v1" in body, "тот же мост, что у лотов"


def test_the_list_always_shows_a_number(script_free: None = None) -> None:
    """Балл не вытесняется вердиктом модели: сравнивать надо число с числом."""
    script = page_script(auctions_page())
    body = script[script.index("function renderKrt("):]
    body = body[:body.index("\nfunction krtSiteMap(")]
    assert "${sc.score} · ${esc(sc.label)}" in body
    assert "Модель · ${esc(light.label)}" not in body, "вердикт больше не заменяет балл"
    assert "krtScoreNote(sc)" in body, "рядом сказано, что балл снизило"
    assert "x.is_new" in body, "новая площадка помечается"


def test_the_market_blocks_are_rendered_by_one_function() -> None:
    """Свежий запрос и сохранённый отчёт рисуют соседей одной разметкой."""
    script = page_script(auctions_page())
    assert script.count("<h3>Рынок рядом</h3>") == 1


def test_the_bridge_applies_the_snapshot_through_the_shared_function() -> None:
    assert "applyProjectSnapshot(model)" in bridge.BRIDGE_SCRIPT
    assert "pending.krt_model" in bridge.BRIDGE_SCRIPT
    assert "confirm(" in bridge.BRIDGE_SCRIPT, "чужая модель заменяет расчёт с согласия"


def test_the_model_page_has_that_shared_function() -> None:
    assert "function applyProjectSnapshot(" in core.PAGE
    body = core.PAGE[core.PAGE.index("function applyProjectSnapshot("):]
    body = body[:body.index("\n}\n")]
    assert "Object.assign(cloneValue(INPUT_DEFAULT)" in body
    assert "cloneValue(TEP_DEFAULT)" in body
    assert "makeDefaultPhasing(1)" in body
