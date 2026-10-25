"""Пока страница грузится, прежний интерфейс не выдаёт себя за готовый.

Телефон владельца, 25.10.2026, мобильная сеть: на экране целиком прежний вид —
«Класс», «Сценарий», вкладки «Вводные / ТЭП / ВРИ…» — без «Личного кабинета»
и без нового интерфейса. Причина — устройство документа: прежняя шапка лежит
в первых процентах полутора мегабайт `PAGE`, главный скрипт (он и открывает
кабинет) выполняется только дочитанным, а слой подключён в самом конце. Пока
документ идёт по медленной сети, человек видит мёртвую прежнюю страницу и
ничего не знает о том, что она ещё грузится.

Проверяется на отрисованной странице, документ отдаётся с остановкой:

- до запуска слоя прежний вид закрыт экраном загрузки;
- если загрузка затянулась, экран говорит об этом и даёт «Обновить страницу»;
- дочитанная страница включает слой и снимает экран;
- не загрузился файл слоя или слой не запустился — экран снят, на прежнем
  виде плашка с причиной, а не тишина;
- подделка: та же страница без сторожа показывает прежний вид посреди
  загрузки — значит, проба различает исправное и сломанное.

Запуск: python3 -m pytest tests/test_ia_old_view_is_not_shown_while_loading.py -q
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Пауза посреди документа длиннее порога «медленно» сторожа (12 с).
_HOLD_S = 13.5

_STATE_JS = """() => {
  const root = document.documentElement;
  const scenario = document.getElementById('scenarioSelect');
  const reload = document.querySelector('.ia-boot-reload');
  const fail = document.getElementById('iaBootFail');
  return {
    cls: root.className,
    curtain: getComputedStyle(root, '::after').content,
    scenarioShown: !!scenario && getComputedStyle(scenario).visibility === 'visible'
      && scenario.getBoundingClientRect().width > 0,
    reloadShown: !!reload && getComputedStyle(reload).display !== 'none'
      && getComputedStyle(reload).visibility === 'visible',
    fail: fail ? fail.textContent : '',
    iaOn: !!document.body && document.body.classList.contains('ia-on'),
  };
}"""


def _slow_app():
    """Приложение прода плюс `/slow` и `/slow-bare`: корень с остановкой.

    Документ отдаётся до середины главного скрипта, затем пауза. `/slow-bare` —
    подделка: тот же документ без сторожа в <head>.
    """
    import main_registry
    from fastapi.testclient import TestClient
    from starlette.responses import StreamingResponse

    import ia_preview

    page = TestClient(main_registry.app).get("/").text
    head = ia_preview._head_injection()
    assert head in page, "сторож загрузки не стоит в <head> корня"
    bare = page.replace(head, "", 1)
    cut = page.index("<script", page.index("<body")) + 4000

    def streamer(text: str):
        async def body():
            yield text[:cut].encode("utf-8")
            await asyncio.sleep(_HOLD_S)
            yield text[cut:].encode("utf-8")
        return body

    inner = main_registry.app

    async def app(scope, receive, send):
        if scope["type"] == "http" and scope["path"] in ("/slow", "/slow-bare"):
            text = page if scope["path"] == "/slow" else bare
            response = StreamingResponse(streamer(text)(), media_type="text/html; charset=utf-8")
            await response(scope, receive, send)
            return
        await inner(scope, receive, send)

    return app


@pytest.fixture(scope="module")
def runs() -> dict:
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright

    import browser

    path = browser.chromium_or_skip()
    out: dict = {}
    with browser.serve(_slow_app(), 18193) as base, sync_playwright() as pw:
        with pw.chromium.launch(executable_path=str(path)) as engine:
            def phone():
                return engine.new_page(viewport={"width": 390, "height": 844})

            # Исправная страница с остановкой посреди документа.
            page = phone()
            page.goto(f"{base}/slow", wait_until="commit")
            page.wait_for_selector("#scenarioSelect", state="attached")
            page.wait_for_timeout(1500)
            out["early"] = page.evaluate(_STATE_JS)
            page.wait_for_timeout(int((_HOLD_S - 0.5) * 1000) - 1500)
            out["slow"] = page.evaluate(_STATE_JS)
            page.wait_for_function("document.documentElement.classList.contains('ia-ready')",
                                   timeout=60_000)
            out["done"] = page.evaluate(_STATE_JS)
            page.close()

            # Подделка: без сторожа посреди загрузки виден прежний вид.
            page = phone()
            page.goto(f"{base}/slow-bare", wait_until="commit")
            page.wait_for_selector("#scenarioSelect", state="attached")
            page.wait_for_timeout(1500)
            out["bare"] = page.evaluate(_STATE_JS)
            page.close()

            # Файл слоя не загрузился.
            page = phone()
            page.route("**/ia/assets/overlay.js", lambda route: route.abort("failed"))
            page.goto(f"{base}/", wait_until="load")
            page.wait_for_selector("#iaBootFail", timeout=20_000)
            out["aborted"] = page.evaluate(_STATE_JS)
            page.close()

            # Файл пришёл, но слой не запустился.
            page = phone()
            page.route("**/ia/assets/overlay.js",
                       lambda route: route.fulfill(status=200, body="/* пусто */",
                                                   content_type="application/javascript"))
            page.goto(f"{base}/", wait_until="load")
            page.wait_for_selector("#iaBootFail", timeout=20_000)
            out["silent"] = page.evaluate(_STATE_JS)
            page.close()
    return out


def test_the_old_view_is_covered_while_the_page_loads(runs) -> None:
    early = runs["early"]
    assert "ia-loading" in early["cls"], early
    assert "Загружаем" in early["curtain"], early
    assert not early["scenarioShown"], f"посреди загрузки виден прежний «Сценарий»: {early}"
    assert not early["iaOn"], "проба снята не посреди загрузки — слой уже включён"


def test_the_probe_sees_the_old_view_without_the_guard(runs) -> None:
    bare = runs["bare"]
    assert bare["scenarioShown"], f"проба не видит прежний вид даже без сторожа: {bare}"


def test_a_slow_load_says_so_and_offers_a_reload(runs) -> None:
    slow = runs["slow"]
    assert "ia-loading" in slow["cls"], slow
    assert "связь медленная" in slow["curtain"], slow
    assert slow["reloadShown"], f"нет кнопки «Обновить страницу»: {slow}"
    assert not slow["scenarioShown"], slow


def test_the_loaded_page_turns_the_layer_on(runs) -> None:
    done = runs["done"]
    assert done["iaOn"], done
    assert "ia-loading" not in done["cls"], done
    assert done["curtain"] in ("none", "normal", ""), done
    assert not done["reloadShown"], done
    assert not done["fail"], done


def test_a_missing_layer_file_is_named_on_the_screen(runs) -> None:
    aborted = runs["aborted"]
    assert "ia-loading" not in aborted["cls"], aborted
    assert "Новый интерфейс не включился" in aborted["fail"], aborted
    assert "не загрузился" in aborted["fail"], aborted
    assert aborted["scenarioShown"], "экран загрузки не снят — человек остался перед заставкой"


def test_a_layer_that_never_started_is_named_on_the_screen(runs) -> None:
    silent = runs["silent"]
    assert "ia-loading" not in silent["cls"], silent
    assert "не запустился" in silent["fail"], silent
