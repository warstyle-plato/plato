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


def test_the_browser_probe_reports_instead_of_bypassing() -> None:
    body = source()
    assert "def probe_browser(" in body
    assert "QRATOR_MARKERS" in body, "капча опознаётся и называется, а не обходится"
    # Ни решения капчи, ни подмены себя за другого: это ровно то, от чего защита.
    for forbidden in ("anticaptcha", "2captcha", "rucaptcha", "solve_captcha",
                      "qauth_token", "bypass"):
        assert forbidden not in body.lower(), f"обход защиты: {forbidden}"


def test_the_browser_is_launched_by_the_shared_launcher() -> None:
    """Второго пути к Chromium не заводим: он уже есть у движка."""
    body = source()
    assert "import browser_launch" in body
    assert "browser_launch.launch(" in body
    assert "chromium.launch(" not in body


def test_the_probe_collects_the_calls_the_page_makes() -> None:
    """У SPA данные приезжают отдельными вызовами — их адреса и нужны."""
    body = source()
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
