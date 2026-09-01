"""ТЭП считает сам калькулятор ГлавАПУ, а наши формулы — фолбэк.

Копировать методику оказалось тупиком: плата за ВРИ разошлась со штатным
калькулятором на 1,75%, компенсация за соцобъекты — на 19%, и оба раза
расхождение находил человек на скриншотах. Ставки индексируются поквартально,
коэффициенты меняются, и пересказ отстаёт на неизвестный срок, продолжая
выглядеть достоверно.

Теперь сервер запускает настоящий калькулятор браузером без экрана — той же
последовательностью, что отрабатывает скрытый iframe на сайте. Формулы
остаются запасным путём: при недоступности ГлавАПУ или сломанной автоматизации
отчёт честно говорит, что расчёт запасной, вместо тихой выдачи устаревшего.

Запуск: python3 -m pytest tests -q
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import main as wrapper  # noqa: E402

core = wrapper.core

_NUMBERS = ["77:01:0005006:7684"]


def test_the_headless_run_is_off_until_switched_on():
    """По умолчанию выключено: Chromium есть не на каждой машине, и выкатка
    не должна ронять расчёт там, где его нет."""
    assert core._GLAVAPU_HEADLESS_ENABLED is False


def test_the_server_path_prefers_the_real_calculator(monkeypatch):
    """Включённый флаг ведёт расчёт в настоящий калькулятор, а не в формулы."""
    seen = {}

    def fake_rows(numbers, area_ha):
        seen["numbers"] = list(numbers)
        seen["area"] = area_ha
        return [{"code": "60", "name": "Озеленение", "unit": "га", "value": "1"}]

    def fake_analysis(request):
        return {"territory": {"area_ha": 0.1963}, "recognized": _NUMBERS,
                "coefficients": {}, "warnings": []}

    def fake_import(request):
        seen["imported"] = True
        return {"normalized": {"spp_total_sqm": 6870}, "source": {}, "warnings": []}

    monkeypatch.setattr(core, "_GLAVAPU_HEADLESS_ENABLED", True)
    monkeypatch.setattr(core, "_glavapu_headless_rows", fake_rows)
    monkeypatch.setattr(core, "analyze_cadastral_territory", fake_analysis)
    monkeypatch.setattr(core, "import_cadastral_tep", fake_import)

    result = core.cadastral_tep_server(
        core.CadastralAnalysisRequest(cadastral_numbers=", ".join(_NUMBERS)))
    assert seen["numbers"] == _NUMBERS
    assert seen["imported"] is True
    assert "Штатный калькулятор" in result["source"]["format"]


def test_a_broken_automation_falls_back_to_the_formulas(monkeypatch):
    """Худший исход нового пути — сегодняшнее поведение, а не сломанный бот:
    упавший калькулятор уводит расчёт в формулы, а не в ошибку."""
    def boom(numbers, area_ha):
        raise TimeoutError("калькулятор не отдал таблицу")

    def fake_analysis(request):
        return {"territory": {"area_ha": 0.1963}, "recognized": _NUMBERS,
                "coefficients": {}, "warnings": []}

    calls = {}

    def fake_quick(region, query, **kwargs):
        calls["fallback"] = True
        return {"file": b"", "filename": "x.xlsx"}

    def fake_parse(data, filename):
        return {"normalized": {}, "source": {}, "warnings": []}

    monkeypatch.setattr(core, "_GLAVAPU_HEADLESS_ENABLED", True)
    monkeypatch.setattr(core, "_glavapu_headless_rows", boom)
    monkeypatch.setattr(core, "analyze_cadastral_territory", fake_analysis)
    monkeypatch.setattr(core, "vri_tep_quick", fake_quick)
    monkeypatch.setattr(core, "parse_glavapu_xlsx", fake_parse)

    result = core.cadastral_tep_server(
        core.CadastralAnalysisRequest(cadastral_numbers=", ".join(_NUMBERS)))
    assert calls.get("fallback") is True, "формулы обязаны подхватить"
    assert any("запасной" in str(w) or "формулами" in str(w)
               for w in result["warnings"]), "человек должен знать, что расчёт запасной"
    assert core._GLAVAPU_HEADLESS["last_error"], "сбой обязан оставлять след"


def test_the_status_tells_who_counted():
    """«Бот опять посчитал не то» проверяется статусом, а не скриншотами."""
    from fastapi.testclient import TestClient
    status = TestClient(core.app).get("/telegram/status").json()["glavapu_headless"]
    assert {"enabled", "runs", "fallbacks", "last_ok", "last_error"} <= set(status)


def test_the_automation_repeats_the_page_steps():
    """Серверные шаги — те же, что у скрытого iframe: другая последовательность
    молча дала бы другой расчёт."""
    import inspect
    # Шаг перехода к расчётам живёт своей функцией с 01.09.2026: голый click()
    # девяносто секунд стучался в disabled-кнопку и отдавал стек Playwright
    # вместо ответа калькулятора. Проверка смотрит на автоматизацию целиком —
    # привязанная к телу одной функции, она падает при любом выносе кода и
    # молчит о том, что сломалось на самом деле.
    source = (inspect.getsource(core._glavapu_drive_page)
              + inspect.getsource(core._glavapu_proceed))
    for step in ("Участок", "fill_numbers", "Отправить", "Перейти к расчётам"):
        assert step in source, step
    assert "_glavapu_proceed(" in inspect.getsource(core._glavapu_drive_page), \
        "шаг перехода к расчётам выпал из последовательности"
    # Поле кадастровых номеров ищется по нескольким признакам: один жёсткий
    # селектор — это обещание, что вёрстка genplan.tech не изменится, а она
    # изменилась, и расчёт девяносто секунд ждал элемент, которого нет.
    assert "#id-cad-numbers-text-field" in core._GLAVAPU_NUMBER_FIELD_SELECTORS
    assert len(core._GLAVAPU_NUMBER_FIELD_SELECTORS) >= 4
    # Готовность таблицы определяется как на странице: коды 60 и 54, ≥60 строк.
    assert '"60" in codes' in source and '"54" in codes' in source
    assert "len(rows) >= 60" in source


def test_only_one_browser_runs_at_a_time():
    """Ядро — 2 vCPU и 4 ГБ, воркеров два, Chromium берёт 300–400 МБ:
    два одновременных запуска клали бы не расчёт, а весь контейнер."""
    assert core._GLAVAPU_HEADLESS_SLOTS == 1
    import inspect
    source = inspect.getsource(core._glavapu_headless_rows)
    assert "_GLAVAPU_HEADLESS_LOCK.acquire" in source
    assert "_GLAVAPU_HEADLESS_LOCK.release" in source
    # Ожидание в очереди конечно: не дождался — уходим на формулы, а не висим.
    assert "_GLAVAPU_HEADLESS_QUEUE_SECONDS" in source


def test_the_container_flags_are_set_for_a_small_machine():
    """В контейнере /dev/shm мал, и без флага Chromium падает молча."""
    assert "--disable-dev-shm-usage" in core._GLAVAPU_HEADLESS_ARGS
    assert "--no-sandbox" in core._GLAVAPU_HEADLESS_ARGS


# --- скорость ---------------------------------------------------------------

class _FakePage:
    def __init__(self, counter):
        self.counter, self.url, self._closed = counter, "", False

    def set_default_timeout(self, ms): pass

    def route(self, pattern, handler):
        self.counter["routed"] += 1

    def is_closed(self): return self._closed


class _FakeBrowser:
    def __init__(self, counter):
        self.counter, self._connected = counter, True

    def is_connected(self): return self._connected

    def new_page(self):
        self.counter["pages"] += 1
        return _FakePage(self.counter)

    def close(self): self._connected = False


class _FakeChromium:
    def __init__(self, counter): self.counter = counter

    def launch(self, headless=True, args=None):
        self.counter["launches"] += 1
        return _FakeBrowser(self.counter)


class _FakeSyncPlaywright:
    def __init__(self, counter): self.chromium = _FakeChromium(counter)

    def __enter__(self): return self

    def __exit__(self, *exc): return False


@pytest.fixture
def fake_browser(monkeypatch):
    """Подменяет Playwright: Chromium в песочнице нет, а считать нужно не его,
    а число запусков."""
    import types
    counter = {"launches": 0, "pages": 0, "routed": 0}
    module = types.ModuleType("playwright.sync_api")
    module.sync_playwright = lambda: _FakeSyncPlaywright(counter)
    root = types.ModuleType("playwright")
    root.sync_api = module
    monkeypatch.setitem(sys.modules, "playwright", root)
    monkeypatch.setitem(sys.modules, "playwright.sync_api", module)
    monkeypatch.setattr(core, "_GLAVAPU_BROWSER_THREAD", None)
    monkeypatch.setattr(core, "_GLAVAPU_HEADLESS_IDLE_SECONDS", 5.0)
    yield counter
    # Поток простоя уходит сам — дожидаемся, чтобы подменённый Playwright
    # не пережил тест.
    thread = core._GLAVAPU_BROWSER_THREAD
    if thread is not None:
        thread.join(timeout=20)


def test_the_browser_is_reused_between_calculations(fake_browser, monkeypatch):
    """Холодный старт Chromium и первая загрузка страницы калькулятора со всеми
    ассетами платились каждым расчётом заново — отсюда и минута. Браузер живёт
    между расчётами, и второй расчёт начинается с готовой машины."""
    monkeypatch.setattr(core, "_glavapu_drive_page",
                        lambda page, numbers, area, timings: [{"code": "60"}])

    core._glavapu_headless_rows(_NUMBERS, 0.19)
    core._glavapu_headless_rows(_NUMBERS, 0.19)

    assert fake_browser["launches"] == 1, "второй расчёт обязан взять тёплый браузер"
    assert fake_browser["pages"] == 1
    assert fake_browser["routed"] == 1, "лишнее в загрузке режется один раз"


def test_a_failed_run_throws_the_browser_away(fake_browser, monkeypatch):
    """Упавший прогон мог оставить страницу в неизвестном состоянии. Считать на
    ней дальше — значит выдать чужой ТЭП под своим именем, поэтому браузер
    рвётся, а следующий расчёт начинает с нуля."""
    def boom(page, numbers, area, timings):
        raise RuntimeError("калькулятор сломался посреди расчёта")

    monkeypatch.setattr(core, "_glavapu_drive_page", boom)
    with pytest.raises(RuntimeError):
        core._glavapu_headless_rows(_NUMBERS, 0.19)

    monkeypatch.setattr(core, "_glavapu_drive_page",
                        lambda page, numbers, area, timings: [{"code": "60"}])
    core._glavapu_headless_rows(_NUMBERS, 0.19)
    assert fake_browser["launches"] == 2, "после сбоя браузер поднимается заново"


def test_the_steps_are_timed(fake_browser, monkeypatch):
    """«Считает около минуты» — это диагноз только тогда, когда видно, какой
    шаг её берёт. Без замера ускорять пришлось бы наугад."""
    monkeypatch.setattr(core, "_glavapu_drive_page",
                        lambda page, numbers, area, timings: timings.update(
                            {"load": 900, "parcel": 2500, "table": 4000}) or [{"code": "60"}])
    core._glavapu_headless_rows(_NUMBERS, 0.19)

    from fastapi.testclient import TestClient
    status = TestClient(core.app).get("/telegram/status").json()["glavapu_headless"]
    assert status["last_ms"]["table"] == 4000
    assert status["last_ms"]["total"] >= 0, "общее время расчёта тоже видно"
    assert status["browser_warm"] is True


def test_the_page_is_cleaned_between_calculations():
    """Страница переиспользуется — хранилище прошлого прогона обязано стираться:
    восстановленный оттуда чужой участок дал бы правдоподобный чужой ТЭП."""
    import inspect
    source = inspect.getsource(core._glavapu_drive_page)
    assert "localStorage.clear()" in source and "sessionStorage.clear()" in source


def test_the_ready_territory_is_not_asked_for_twice(monkeypatch):
    """Страница собирает территорию перед расчётом и держит её в руках. Тот же
    вопрос ГлавАПУ второй раз за один клик стоил внешнего запроса впустую."""
    analysis = {"recognized": _NUMBERS, "territory": {"area_ha": 0.1963},
                "coefficients": {"rent": 1.0}, "warnings": []}
    asked = {"count": 0}

    def counted(request):
        asked["count"] += 1
        return analysis

    monkeypatch.setattr(core, "analyze_cadastral_territory", counted)
    monkeypatch.setattr(core, "_GLAVAPU_HEADLESS_ENABLED", True)
    monkeypatch.setattr(core, "_glavapu_headless_rows",
                        lambda numbers, area_ha: [{"code": "60", "name": "x",
                                                   "unit": "га", "value": "1"}])
    monkeypatch.setattr(core, "import_cadastral_tep",
                        lambda request: {"normalized": {}, "source": {}, "warnings": []})

    core.cadastral_tep_server(core.CadastralAnalysisRequest(
        cadastral_numbers=", ".join(_NUMBERS), cadastral_analysis=analysis))
    assert asked["count"] == 0, "готовая территория обязана приниматься как есть"


def test_a_territory_of_other_parcels_is_refused(monkeypatch):
    """Присланная территория принимается только для запрошенных участков:
    иначе ТЭП посчитался бы по чужим коэффициентам, выглядя безупречно."""
    stranger = {"recognized": ["77:09:0004014:13"], "territory": {"area_ha": 5.0},
                "coefficients": {"rent": 2.0}, "warnings": []}
    mine = {"recognized": _NUMBERS, "territory": {"area_ha": 0.1963},
            "coefficients": {"rent": 1.0}, "warnings": []}
    monkeypatch.setattr(core, "analyze_cadastral_territory", lambda request: mine)
    used = core._cadastral_analysis_for(_NUMBERS, stranger)
    assert used is mine, "чужая территория обязана быть пересобрана"


def test_the_status_counts_queue_timeouts():
    from fastapi.testclient import TestClient
    status = TestClient(core.app).get("/telegram/status").json()["glavapu_headless"]
    assert "queue_timeouts" in status and "parallel_slots" in status


def test_the_calculation_is_forwarded_to_the_core(monkeypatch):
    """Браузер живёт на ядре: там свой образ, четыре гигабайта и нет
    засыпания. Render пересылает расчёт туда же, куда и анализ территории."""
    seen = {}

    def fake_core_url(path):
        return "https://core.example" + path if path == "/cadastral/tep-server" else ""

    def fake_post(url, payload, timeout):
        seen["url"] = url
        seen["timeout"] = timeout
        return {"normalized": {}, "source": {"format": "ядро"}, "warnings": []}

    monkeypatch.setattr(core, "_core_api_url", fake_core_url)
    monkeypatch.setattr(core, "_core_post", fake_post)
    result = core.cadastral_tep_server(
        core.CadastralAnalysisRequest(cadastral_numbers=", ".join(_NUMBERS)))
    assert seen["url"].endswith("/cadastral/tep-server")
    assert result["source"]["format"] == "ядро"
    # Срок ожидания — общий с остальными вызовами ядра: браузер медленнее
    # формул, и короткий таймаут рвал бы честный расчёт.
    assert seen["timeout"] == core._MO_CALC_TIMEOUT_SECONDS


def test_a_silent_core_still_answers_from_here(monkeypatch):
    """Ядро не ответило — считаем формулами здесь, а не отдаём ошибку."""
    monkeypatch.setattr(core, "_core_api_url",
                        lambda path: "https://core.example" + path)

    def boom(url, payload, timeout):
        raise TimeoutError("ядро молчит")

    calls = {}

    def fake_quick(region, query, **kwargs):
        calls["local"] = True
        return {"file": b"", "filename": "x.xlsx"}

    monkeypatch.setattr(core, "_core_post", boom)
    monkeypatch.setattr(core, "vri_tep_quick", fake_quick)
    monkeypatch.setattr(core, "parse_glavapu_xlsx",
                        lambda data, filename: {"normalized": {}, "source": {}, "warnings": []})
    core.cadastral_tep_server(
        core.CadastralAnalysisRequest(cadastral_numbers=", ".join(_NUMBERS)))
    assert calls.get("local") is True


# --- чужая страница живёт своей жизнью ---------------------------------------

def test_the_onboarding_tour_is_dismissed_before_every_click():
    """Обучающий тур genplan.tech (react-joyride) висит поверх интерфейса с
    затемнением и перехватывает клики: Playwright повторил попытку 168 раз и
    ушёл в таймаут. В браузере человека тур закрыт однажды и больше не
    появляется, свежий Chromium на сервере видит его каждый раз."""
    import inspect
    source = inspect.getsource(core._glavapu_drive_page)
    assert source.count("dismiss_tour()") >= 4, (
        "тур показывается по шагам — снимать его надо перед каждым кликом")
    # Порядок обязателен: сначала снять оверлей, потом кликать. Ищем именно
    # соседство вызовов — определения функций стоят выше по тексту.
    import re
    assert re.search(r"dismiss_tour\(\)\s*\n\s*open_parcel_dialog\(\)", source), \
        "клик по «Участок» обязан идти сразу после снятия тура"


def test_the_tour_is_hidden_without_touching_the_page_dom():
    """Узлы тура не удаляются. React считает портал своим и при следующем
    обновлении обращается к нему — удаление роняло всё приложение, калькулятор
    показывал экран «Перезагрузить страницу», и расчёт упирался в отсутствие
    полей. Стиль гасит тур так же надёжно, а чужой DOM цел."""
    js = core._GLAVAPU_DISMISS_TOUR_JS
    assert 'data-action="skip"' in js and "button.click()" in js
    assert "#react-joyride-portal" in js
    assert "display: none" in js and "pointer-events: none" in js
    assert ".remove()" not in js, "удаление чужих узлов роняет приложение"


def test_a_crashed_calculator_is_reloaded_not_stared_at():
    """Экран ошибки калькулятора несёт свою кнопку перезагрузки — жмём её и
    даём приложению собраться, вместо того чтобы искать поля на экране,
    где их нет по определению."""
    import inspect
    source = inspect.getsource(core._glavapu_drive_page)
    assert "def recover_if_crashed()" in source
    assert "Перезагрузить страницу" in source
    # Проверка идёт до шагов: искать поля на экране ошибки бессмысленно.
    assert source.find("recover_if_crashed()\n") < source.find("open_parcel_dialog()\n")


def test_the_failure_names_the_culprit(monkeypatch):
    """Причина срыва обязана быть в статусе, а не только в логах контейнера:
    «<div id=react-joyride-portal> intercepts pointer events» — это готовый
    диагноз, за которым не надо идти на сервер."""
    def boom(numbers, area_ha):
        raise TimeoutError(
            '<div id="react-joyride-portal">…</div> subtree intercepts pointer events\n'
            "  - retrying click action\n  - waiting 500ms")

    monkeypatch.setattr(core, "_GLAVAPU_HEADLESS_ENABLED", True)
    monkeypatch.setattr(core, "_glavapu_headless_rows", boom)
    monkeypatch.setattr(core, "analyze_cadastral_territory", lambda req: {
        "territory": {"area_ha": 0.1963}, "recognized": _NUMBERS,
        "coefficients": {"rent": 0.1281}, "warnings": []})
    monkeypatch.setattr(core, "vri_tep_quick",
                        lambda region, query, **kwargs: {"file": b"", "filename": "x.xlsx"})
    monkeypatch.setattr(core, "parse_glavapu_xlsx",
                        lambda data, filename: {"normalized": {}, "source": {}, "warnings": []})
    core.cadastral_tep_server(core.CadastralAnalysisRequest(
        cadastral_numbers=", ".join(_NUMBERS)))
    assert "react-joyride-portal" in core._GLAVAPU_HEADLESS["last_error"]


def test_the_warm_up_also_kills_the_tour():
    """Прогрев открывает страницу заранее — пусть заодно закроет тур: тогда
    первый настоящий расчёт не тратит на него ни попытки."""
    import inspect
    source = inspect.getsource(core._glavapu_drive_page)
    warm = source[source.find("if not numbers:"):]
    assert "dismiss_tour()" in warm.split("return")[0]


def test_a_missing_field_reports_what_the_page_actually_has():
    """Срыв на поиске поля обязан приносить вёрстку, а не только таймаут:
    иначе каждая правка селектора — это ещё один круг переписки."""
    import inspect
    source = inspect.getsource(core._glavapu_drive_page)
    assert "_GLAVAPU_VISIBLE_FIELDS_JS" in source
    assert "Поля:" in source and "Кнопки:" in source
    js = core._GLAVAPU_VISIBLE_FIELDS_JS
    # Видимость — по прямоугольнику: у всего внутри position:fixed (а диалоги
    # MUI именно такие) offsetParent равен null, и поле в открытом диалоге не
    # попало бы в список вовсе.
    assert "getBoundingClientRect" in js
    assert "offsetParent" not in js
    assert "placeholder" in js and "el.id" in js


def test_the_parcel_button_is_found_by_more_than_its_role():
    """«Участок» может оказаться и кнопкой, и вкладкой, и пунктом меню. Промах
    здесь виден не сразу: клик проходит вхолостую, панель не открывается, а
    падает уже поиск поля — и причина выглядит чужой."""
    import inspect
    source = inspect.getsource(core._glavapu_drive_page)
    assert "def open_parcel_dialog()" in source
    for role in ('get_by_role("button", name="Участок")',
                 'get_by_role("tab", name="Участок")',
                 'get_by_text("Участок", exact=True)'):
        assert role in source, role
    assert "не нажалась ни одним способом" in source
