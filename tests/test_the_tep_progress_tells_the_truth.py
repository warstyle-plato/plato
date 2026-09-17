"""Полоса «Расчёт ТЭП» показывает то, что объявил писатель, — и уходит с готовым.

Экран владельца 14.09.2026: зелёная строка «ТЭП посчитан штатным калькулятором
ГлавАПУ: 0,6509 га» — то есть расчёт кончился, — а под ней полоса на 50% с
подписью «Получаю расчёт ГлавАПУ…», и упала она туда с 75%. Вопрос был двойной:
«к чему эта полоса динамики если расчет сделан, а она упала с 75 проц до 50?»

Причина не в вёрстке. `tep_progress_ui` читал `textContent` чужой строки
состояния и УГАДЫВАЛ стадию регуляркой по словам, а ветка `/главапу|.../ → 2`
стояла выше ветки `/готов|посчитан/ → 4`. Финальная строка несёт оба слова,
поэтому готовый результат попадал в стадию 2. Путь через iframe при этом успел
дойти до «3 из 4» (75%), сорвался, докатился серверным расчётом — и его успех
отбросил полосу назад.

Писатель своё состояние объявляет сам, и объявляет дважды: номером («2 из 4 ·
…») и СТРУКТУРОЙ — `class="import-ok"` у финала, `class="import-error"` у
отказа. Чтение `textContent` выбрасывает ровно эту структуру и заменяет её
догадкой по прозе. Здесь проверяется, что догадки больше нет.

Проверяется это настоящим Chromium на живой странице: в исходнике сломанный и
починенный модуль выглядят одинаково, а предмет здесь — что видно на экране.

Запуск: python3 -m pytest tests/test_the_tep_progress_tells_the_truth.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tests import browser  # noqa: E402

PORT = 18123

# Ровно те строки, которые пишет страница (main_legacy.py, поток получения ТЭП).
STEP_1 = "1 из 4 · Формирую территорию по кадастровым номерам…"
STEP_2 = "2 из 4 · Открываю штатный расчёт ГлавАПУ…"
STEP_3 = "3 из 4 · Считываю готовую таблицу ТЭП ГлавАПУ…"
STEP_4 = "4 из 4 · Подготавливаю сверку перед применением…"
DONE_OK = ('<span class="import-ok">ТЭП посчитан штатным калькулятором '
           'ГлавАПУ: 0,6509 га.</span> Проверьте значения ниже и нажмите '
           '«Применить к Вводным и ТЭП».')
DONE_IFRAME = ('<span class="import-ok">ТЭП получены из ГлавАПУ: 0,6509 га.'
               '</span> Проверьте значения ниже и нажмите «Применить».')
FAILED = ('<span class="import-error">Не удалось определить территорию: '
          'таймаут.</span>')
SERVER_STEP = "Считаю ТЭП на сервере…"


@pytest.fixture(scope="module")
def page():
    chrome = browser.chromium_or_skip()
    from playwright.sync_api import sync_playwright

    # Дверь, в которую ходят: прод поднимается из `main_registry`, и полосу
    # ставит он (`install_tep_progress_ui`). Импорт `main` даёт страницу БЕЗ
    # неё — проверка тогда зелена на любом коде, потому что мерить нечего.
    import main_registry

    with browser.serve(main_registry.app, PORT) as origin:
        with sync_playwright() as pw:
            browser_ = pw.chromium.launch(executable_path=str(chrome))
            tab = browser_.new_page()
            tab.goto(origin + "/", wait_until="domcontentloaded")
            yield tab
            browser_.close()


def show(tab, html: str) -> dict:
    """Написать строку состояния так, как её пишет страница, и снять полосу."""
    return tab.evaluate(
        """(html)=>new Promise(done=>{
             const s=document.getElementById('cadastralStatus');
             s.innerHTML=html;
             setTimeout(()=>{
               const b=document.getElementById('tepProgress');
               const pct=document.getElementById('tepProgressPct');
               const text=document.getElementById('tepProgressText');
               done({
                 exists: !!b,
                 shown: !!b && !b.hidden,
                 pct: pct ? pct.textContent : null,
                 width: b && !b.hidden
                   ? document.getElementById('tepProgressFill').style.width : null,
                 text: text ? text.textContent : null,
                 stage: b ? (b.dataset.stage || '') : null,
                 error: b ? (b.dataset.error || '') : null,
               });
             }, 60);
           })""", html)


def test_the_finished_line_does_not_look_like_work_in_progress(page) -> None:
    """Готовый результат — не «Получаю расчёт ГлавАПУ…» и не половина пути."""
    show(page, STEP_3)
    got = show(page, DONE_OK)
    assert got["shown"] is False, (
        "полоса осталась на экране при готовом расчёте: " + repr(got))


def test_the_bar_never_falls_backwards(page) -> None:
    """75% → 50% на одном прогоне — полоса, которая врёт по построению."""
    show(page, STEP_1)
    show(page, STEP_2)
    third = show(page, STEP_3)
    assert third["pct"] == "75%", third
    final = show(page, DONE_OK)
    assert final["shown"] is False or final["pct"] in ("100%", "Готово"), final


def test_the_other_finished_line_is_finished_too(page) -> None:
    """Финал у пути через iframe свой по словам и тот же по структуре."""
    show(page, STEP_2)
    got = show(page, DONE_IFRAME)
    assert got["shown"] is False, got


def test_a_numbered_step_shows_its_own_number_and_words(page) -> None:
    """Стадию объявляет писатель номером, а подпись — его же словами."""
    got = show(page, STEP_2)
    assert got["pct"] == "50%", got
    assert got["text"] == "Открываю штатный расчёт ГлавАПУ…", got


def test_a_failure_stays_on_screen_and_says_so(page) -> None:
    """Отказ полосу не снимает: молча исчезнувшая ошибка — ошибка без причины."""
    show(page, STEP_2)
    got = show(page, FAILED)
    assert got["shown"] is True and got["error"] == "1", got


def test_an_unnumbered_step_does_not_invent_a_percent(page) -> None:
    """У серверного пути стадий нет — значит нет и процента.

    Прежде «Считаю ТЭП на сервере…» попадало в ту же ветку по слову и
    рисовалось как ровно половина пути. Половина чего — неизвестно никому.
    """
    show(page, STEP_1)
    got = show(page, SERVER_STEP)
    assert got["shown"] is True, got
    assert got["pct"] != "50%", ("процент выдуман для шага без номера: "
                                 + repr(got))
    assert got["text"] == SERVER_STEP, got


STANDING = ("На внешние сервисы уходят только кадастровые номера или строка "
            "поиска; финансовая модель не передаётся.")


def test_the_standing_note_under_the_field_raises_nothing(page) -> None:
    """Постоянная подпись — не ход работы, и полосы она не поднимает.

    Она стоит под полем всегда. Считай её «шагом без номера» — полоса
    поднялась бы при загрузке страницы и осталась бы висеть навечно: ветка
    «всё остальное» — не «всё остальное», а утверждение.
    """
    page.evaluate("()=>{const b=document.getElementById('tepProgress');"
                  "if(b)b.hidden=true}")
    got = show(page, STANDING)
    assert got["shown"] is False, got


def test_a_run_that_started_shows_its_unnumbered_words(page) -> None:
    """Предохранитель к проверке выше: после нажатия те же слова видны.

    Иначе «полоса не поднимается» проходило бы и у модуля, который не
    показывает её никогда.
    """
    page.evaluate("()=>document.getElementById('cadastralAnalyzeButton').click()")
    got = show(page, SERVER_STEP)
    assert got["shown"] is True and got["text"] == SERVER_STEP, got
