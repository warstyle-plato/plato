"""Сначала ответ источника, потом его разбор.

ГИС Торги были написаны наоборот: имена полей взяты из «уверенности модели»,
разбор готов, источник включён. Живой ответ опроверг почти каждое имя, а сам
источник оказался про другой рынок — приватизацию госимущества, — и выяснилось
это у владельца на экране, тридцатью гаражами по 0,2 млн ₽.

Его собственная таблица (372 лота с исходом, 25.08.2026) объясняет, почему:
44% выборки — банкротство, и оно продаётся лучше всего, а из 130 лотов с
указанной площадкой на наших стоят 49 — остальные 81 на площадках банкротства,
которых мы не читаем.

Поэтому у ЕФРСБ пока ЕСТЬ ТОЛЬКО ПРОБА. Пустой список читался бы как «лотов
нет», выдуманный разбор — как найденные лоты; ни того ни другого быть не
должно, пока ответ не увиден.

Запуск: python3 -m pytest tests/test_a_source_is_proved_before_it_is_parsed.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from auction_search.adapters import fedresurs  # noqa: E402


def source() -> str:
    return (ROOT / "auction_search" / "adapters" / "fedresurs.py").read_text()


def test_the_probe_exists_and_says_it_parses_nothing() -> None:
    assert hasattr(fedresurs, "probe")
    got = fedresurs.probe()
    assert got["host"] == "bankrot.fedresurs.ru"
    assert "разбора нет" in got["parsing"]
    assert got["attempts"], "проба обязана назвать, что именно спрашивала"


def test_every_attempt_names_what_was_asked_and_what_came_back() -> None:
    """Догадка, названная вслух, — работа; выданная за разбор — поломка."""
    for attempt in fedresurs.probe()["attempts"]:
        assert attempt["url"].startswith("https://")
        assert attempt.get("http_status") is not None or attempt.get("reason")


def test_there_is_no_parser_yet() -> None:
    """Ни discover, ни fetch_lot: несверенный источник хуже отсутствующего."""
    assert not hasattr(fedresurs, "to_lot")
    assert "def discover_moscow" not in source()
    assert "def fetch_lot" not in source()


def test_the_probe_does_not_invent_field_names() -> None:
    """Имена полей покажет ответ; здесь их быть не должно."""
    body = source()
    for invented in ("lotName", "biddType", "priceMin", "cadastralNumber"):
        assert invented not in body, f"имя поля {invented} не сверено, а уже записано"


def test_the_certificate_check_is_not_disabled() -> None:
    """Российский госсайт лечится корнем, а не выключенной проверкой."""
    body = source()
    for forbidden in ("CERT_NONE", "check_hostname = False", "_create_unverified"):
        assert forbidden not in body
    assert "trust_context" in body, "корни Минцифры добавляются, как у ГИС Торгов"


def test_the_endpoint_is_wired() -> None:
    api = (ROOT / "auction_search" / "api.py").read_text()
    assert "/auctions/fedresurs/probe" in api
    assert "fedresurs_probe" in api


# --- вторая проба: настоящим браузером ---------------------------------------
# Простой запрос упёрся в капчу Qrator: корень отдаёт 401 со скриптом защиты
# (живой ответ с ядра 26.08.2026). Обходить её мы не будем — от этого она и
# поставлена. Браузер проходит вызов штатно, как браузер человека; покажет
# капчу и ему — это тоже ответ, и он называется вслух.


def shared() -> str:
    return (ROOT / "auction_search" / "adapters" / "browser_probe.py").read_text()


def test_the_browser_probe_reports_instead_of_bypassing() -> None:
    """Капча опознаётся и называется, а не обходится — от этого она и стоит."""
    body = shared()
    assert "def probe_browser(" in body
    assert "CHALLENGE_MARKERS" in body and "qauth_show_captcha" in body
    # Ни решения капчи, ни подмены себя за другого: это ровно то, от чего защита.
    for forbidden in ("anticaptcha", "2captcha", "rucaptcha", "solve_captcha",
                      "qauth_token", "bypass"):
        assert forbidden not in (body + source()).lower(), f"обход защиты: {forbidden}"


def test_the_probe_is_declared_once_for_all_sources() -> None:
    """Две копии разошлись бы на признаках отказа, и одна считала бы страницу
    «403 Forbidden» удачей."""
    body = source()
    assert "browser_probe" in body, "ЕФРСБ зовёт общую пробу"
    assert "sync_playwright" not in body, "своей реализации у читателя быть не должно"


def test_the_browser_is_launched_by_the_shared_launcher() -> None:
    """Второго пути к Chromium не заводим: он уже есть у движка."""
    body = shared()
    assert "import browser_launch" in body
    assert "browser_launch.launch(" in body
    assert "chromium.launch(" not in body


def test_the_probe_collects_the_calls_the_page_makes() -> None:
    """У SPA данные приезжают отдельными вызовами — их адреса и нужны."""
    body = shared()
    assert '"xhr"' in body and '"fetch"' in body
    assert "data_calls" in body


def test_a_blocked_probe_says_why() -> None:
    """Из песочницы хост закрыт: отказ обязан назвать причину, а не молчать."""
    from auction_search.adapters import fedresurs as module
    got = module.probe_browser(seconds=5)
    assert got["ok"] is False
    assert got.get("reason"), "молчаливый отказ читался бы как «лотов нет»"
    assert got["url"].startswith("https://bankrot.fedresurs.ru")


def test_the_browser_endpoint_is_wired() -> None:
    api = (ROOT / "auction_search" / "api.py").read_text()
    assert "/auctions/fedresurs/browser" in api
    assert "fedresurs_browser" in api


def test_a_page_of_refusal_is_not_a_loaded_source() -> None:
    """«403 Forbidden» в заголовке при ok:true — отказ, а не пустой источник.

    Живой ответ с ядра 26.08.2026: браузер загрузил страницу, капчи не было, и
    заголовок оказался «403 Forbidden» — никаких запросов за данными страница
    не сделала. Путь через ЕФРСБ закрыт и браузером; обходить защиту мы не
    станем, но и выдавать отказ за отсутствие лотов нельзя.
    """
    body = shared()
    assert '"blocked"' in body
    assert "REFUSAL_TITLE_MARKS" in body
    assert "Forbidden" in body and "403" in body


def test_the_probe_asks_the_address_it_is_given() -> None:
    """`/TradeList.aspx` — старый путь; человек открывает корень."""
    api = (ROOT / "auction_search" / "api.py").read_text()
    block = api[api.index("async def auction_fedresurs_browser("):]
    block = block[:block.index("\n    @app.get")]
    assert "url: str = Query(default=\"\")" in block
    assert "FEDRESURS_SEARCH_PAGE" in block, "пустой параметр оставляет прежнюю страницу"


# --- Площадки банкротства: та же проба, тот же запрет разбора по догадке ---

def etp_source() -> str:
    return (ROOT / "auction_search" / "adapters" / "etp_probe.py").read_text()


def test_the_platform_probe_uses_the_shared_browser_probe() -> None:
    """Своей реализации у площадок нет: она уже заведена один раз."""
    body = etp_source()
    assert "from auction_search.adapters.browser_probe import probe_browser" in body
    assert "sync_playwright" not in body


def test_one_platform_per_call() -> None:
    """Пять по сорок секунд не уложатся ни в один шлюз, а ответ, не дошедший
    до человека, — это ответ, которого нет."""
    from auction_search.adapters import etp_probe as module

    assert set(module.SLUGS) == {
        "sberbank-ast", "etpgpb", "fabrikant", "alfalot", "etprf"}
    for slug in module.SLUGS:
        assert module.platform_urls(slug), slug


def test_an_unknown_platform_is_named_not_guessed() -> None:
    from auction_search.adapters import etp_probe as module

    got = module.probe_browser_platform("чужая площадка")
    assert got["ok"] is False
    assert "неизвестная площадка" in got["reason"]
    assert got["known"], "перечисляем, что можно спросить"


def test_the_platform_probe_still_parses_nothing() -> None:
    """Разбор по догадке кончился гаражами на экране владельца."""
    body = etp_source()
    assert "разбора нет" in body
    for invented in ("lot_id", "external_lot_id", "start_price", "AuctionLot"):
        assert invented not in body, f"в пробе появился разбор: {invented}"


def test_the_platform_browser_route_is_wired() -> None:
    api = (ROOT / "auction_search" / "api.py").read_text()
    assert '"/auctions/etp/probe/browser"' in api
    block = api[api.index("async def auction_etp_probe_browser("):]
    block = block[:block.index("\n    # Срок на сбор каталога")]
    assert "platform" in block and "known" in block, "без параметра — список площадок"


def test_the_probe_says_who_we_introduced_ourselves_as() -> None:
    """Половина защит режет незнакомый User-Agent: 403 роботу и 403 всем
    выглядят одинаково, пока имя клиента не названо рядом."""
    body = etp_source()
    assert '"user_agent": USER_AGENT' in body


def test_a_refusal_carries_a_hint_that_tells_the_two_apart() -> None:
    from auction_search.adapters import etp_probe as module

    assert "робот" in module._refusal_hint(403)
    assert "лимит" in module._refusal_hint(429)
    assert module._refusal_hint(200) == "", "у удачи подсказки быть не должно"


def test_a_broken_chain_points_at_the_roots_not_at_switching_the_check_off() -> None:
    """Проверку не выключаем — от неё и толк; издателя спрашивают у самого
    сертификата и кладут в каталог корней, как уже чинилась ГИС Торги."""
    body = etp_source()
    assert "CERTIFICATE_VERIFY_FAILED" in body
    assert "Authority Information Access" in body
    assert "Проверку не отключаем" in body
    for forbidden in ("CERT_NONE", "check_hostname = False", "_create_unverified"):
        assert forbidden not in body, f"выключение проверки: {forbidden}"


def test_the_summary_comes_first_and_fits_a_screen() -> None:
    """Вывод, обрезанный на второй площадке из пяти, — это ответ, которого нет."""
    from auction_search.adapters import etp_probe as module

    rows = module.summary({"platforms": [
        {"name": "A", "attempts": [{"url": "u1", "http_status": 403, "reason": "no"},
                                   {"url": "u2", "http_status": 200}]},
        {"name": "B", "attempts": [{"url": "u3", "reason": "SSL"}]},
    ]})
    assert [row["platform"] for row in rows] == ["A", "B"]
    # Удачная попытка вытесняет неудачную: площадка, ответившая хоть одним
    # адресом, не должна выглядеть закрытой.
    assert rows[0]["http_status"] == 200 and rows[0]["url"] == "u2"
    assert rows[1]["reason"] == "SSL"

    body = etp_source()
    assert 'return {"summary": summary(report), **report}' in body, "сводка стоит первой"


def test_a_word_in_the_source_is_not_a_captcha() -> None:
    """27.08.2026 проба объявила капчу у Сбербанк-АСТ и ЭТП ГПБ, которые
    загрузились полностью и сходили за данными: слово лежало в скрипте формы
    входа. Ложная тревога здесь дороже пропуска — по ней вычеркнули бы
    открытую площадку."""
    from auction_search.adapters import browser_probe as module

    assert "captcha" not in module.CHALLENGE_MARKERS, "голое слово — не признак защиты"
    assert "__qrator" in module.CHALLENGE_MARKERS
    body = shared()
    assert 'report["captcha"] = False' in body, "сходила за данными — значит не капча"
    assert "captcha_note" in body, "поправку объясняем, а не делаем молча"


def test_a_post_carries_its_body() -> None:
    """У Сбербанк-АСТ весь каталог ходит в один `/api/Processing/main`: адрес
    есть, а читателя из него не напишешь."""
    body = shared()
    assert "post_data" in body
    assert 'request.method != "GET"' in body


def test_third_party_analytics_does_not_drown_the_addresses() -> None:
    """Нужные адреса тонули между Яндекс.Метрикой и Mindbox."""
    from auction_search.adapters import browser_probe as module

    assert "mc.yandex.ru" in module.THIRD_PARTY and "mindbox.ru" in module.THIRD_PARTY
    body = shared()
    assert "third_party_calls" in body, "сколько отсеяли — говорим, а не прячем"
