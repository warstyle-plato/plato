"""bnMAP: сначала ответ источника, потом его разбор.

Доступ к bnMAP.pro прислан владельцем 30.08.2026 вместе с просьбой о тестовом
рыночном отчёте на другом источнике. Отчёт на нём пока не собирается, и это не
забывчивость: из песочницы `bnmap.pro` и `api.bnmap.pro` закрыты сетевой
политикой — 403 на CONNECT, — то есть живого ответа не видел никто.

Ровно так уже начинались ГИС Торги: имена полей взяты из «уверенности модели»,
разбор готов, источник включён. Живой ответ опроверг почти каждое имя, а сам
источник оказался про другой рынок, и выяснилось это у владельца на экране.

Поэтому у bnMAP есть только проба. Пустой список читался бы как «в bnMAP
такого проекта нет», выдуманный разбор — как найденные цены; ни того ни
другого быть не должно, пока ответ не увиден.

Запуск: python3 -m pytest tests/test_bnmap_is_probed_before_it_is_parsed.py -q
"""

from __future__ import annotations

import json
import re
import sys
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from market_search import bnmap  # noqa: E402
from auction_search.adapters import browser_probe  # noqa: E402


def source() -> str:
    return (ROOT / "market_search" / "bnmap.py").read_text()


@lru_cache(maxsize=1)
def probed() -> dict:
    """Один живой прогон пробы на весь файл: она ходит по сети."""
    return bnmap.probe()


def test_the_probe_exists_and_says_it_parses_nothing() -> None:
    got = probed()
    assert got["host"] == "bnmap.pro"
    assert "разбора нет" in got["parsing"]
    assert got["attempts"], "проба обязана назвать, что именно спрашивала"


def test_every_attempt_names_what_was_asked_and_what_came_back() -> None:
    """Догадка, названная вслух, — работа; выданная за разбор — поломка."""
    for attempt in probed()["attempts"]:
        assert attempt["url"].startswith("https://")
        assert attempt.get("http_status") is not None or attempt.get("reason")


def test_there_is_no_parser_yet() -> None:
    """Ни справочника, ни цены: несверенный источник хуже отсутствующего."""
    body = source()
    for absent in ("def projects", "def price", "def near", "def segments",
                   "def find_project", "def price_history", "def to_row"):
        assert absent not in body, f"в bnmap.py появился разбор: {absent}"
    for absent in ("projects", "price", "near", "segments"):
        assert not hasattr(bnmap, absent)


def test_the_probe_does_not_invent_field_names() -> None:
    """Имена полей bnMAP покажет его ответ; здесь их быть не может.

    В списке и чужие имена «Пульса»: у второго источника они свои, и принять
    одни за другие — та же ошибка, только тише.
    """
    body = source()
    for invented in ("complexId", "priceSqm", "flat_sqm_price", "avg_sale_speed",
                     "living_count", "sqm_price", "buildings_count"):
        assert invented not in body, f"имя поля взято из головы: {invented}"


def test_access_lives_in_the_environment_and_not_in_the_repository() -> None:
    """Присланные почта и пароль лежат на ядре, а не в коде."""
    body = source()
    assert 'os.getenv("BNMAP_LOGIN"' in body
    assert 'os.getenv("BNMAP_PASSWORD"' in body
    assert not re.search(r"[\w.-]+@[\w.-]+\.(ru|com|pro)", body), "в модуле чужая почта"


def test_the_probe_never_prints_the_login(monkeypatch) -> None:
    """Логин — чужая рабочая почта, и диагностический маршрут ей не место."""
    monkeypatch.setenv("BNMAP_LOGIN", "someone@example-tenant.ru")
    monkeypatch.setenv("BNMAP_PASSWORD", "s3cret-not-real")
    got = json.dumps(bnmap.probe(), ensure_ascii=False)
    assert "someone@example-tenant.ru" not in got
    assert "s3cret-not-real" not in got
    assert '"credentials_set": true' in got.lower()


def test_the_browser_probe_says_the_source_is_off_instead_of_showing_nothing(
    monkeypatch,
) -> None:
    """Выключенный источник называется, а не притворяется пустым."""
    monkeypatch.delenv("BNMAP_LOGIN", raising=False)
    monkeypatch.delenv("BNMAP_PASSWORD", raising=False)
    got = bnmap.probe_browser()
    assert got["ok"] is False
    assert "BNMAP_LOGIN" in got["reason"]


def test_the_browser_probe_is_the_shared_one() -> None:
    """Своей копии пробы у модуля нет: вторая разошлась бы на признаках отказа."""
    body = source()
    assert "from auction_search.adapters.browser_probe import probe_browser" in body
    assert "sync_playwright" not in body


def test_the_shared_probe_wipes_the_credentials_out_of_its_answer() -> None:
    """Доступ приезжает и туда, где ключ невинен: в `email` и в адрес страницы."""
    report = {
        "final_url": "https://bnmap.pro/?email=someone@example-tenant.ru",
        "data_calls": [{"request_body_head": '{"email":"someone@example-tenant.ru",'
                                             '"password":"s3cret-not-real"}'}],
    }
    clean = browser_probe._without_secrets(
        report, ("someone@example-tenant.ru", "s3cret-not-real")
    )
    text = json.dumps(clean, ensure_ascii=False)
    assert "someone@example-tenant.ru" not in text
    assert "s3cret-not-real" not in text
    assert "[redacted]" in text


def test_the_checklist_covers_everything_the_report_takes_from_the_source() -> None:
    """Что источник обязан ответить — берётся из отчёта, а не из воображения.

    Иначе список замрёт на дне, когда его писали: отчёт начнёт спрашивать у
    «Пульса» новое, а bnMAP объявят готовым по прежней мерке. Метод-выключатель
    `available` из счёта исключён — он про доступы, а не про данные.
    """
    report_code = (ROOT / "market_search" / "service_v6.py").read_text()
    used = set(re.findall(r"self\.pulse\.([a-z_]+)", report_code)) - {"available"}
    named = {name for row in bnmap.WANTED for name in row["у Пульса"]}
    missing = sorted(used - named)
    assert not missing, (
        "отчёт берёт у источника то, чего нет в списке требований к bnMAP: "
        + ", ".join(missing)
    )


def test_the_login_step_fills_submits_and_leaves_no_login_in_the_answer(
    tmp_path, monkeypatch
) -> None:
    """Вход проверяется настоящим браузером, а не пересказом.

    Проверять такое строками нельзя: искомый вызов есть и в сломанном коде.
    Страница здесь своя, местная — до самого bnMAP из песочницы не достучаться,
    — но форма входа у неё настоящая, и заполняет её тот же шаг, что пойдёт на
    источник. Заодно видно главное: логин, который страница напечатала на себе,
    в ответ пробы не попадает.
    """
    login, password = "someone@example-tenant.ru", "s3cret-not-real"
    monkeypatch.setenv("BNMAP_LOGIN", login)
    monkeypatch.setenv("BNMAP_PASSWORD", password)
    page = tmp_path / "login.html"
    page.write_text(
        "<html><body><form id=f>"
        "<input type=email name=email><input type=password name=password>"
        "<button type=submit>Войти</button></form>"
        "<script>document.getElementById('f').addEventListener('submit',function(e){"
        "e.preventDefault();"
        "var who=document.querySelector('input[type=email]').value;"
        "document.body.innerHTML='<p>Кабинет: '+who+'</p>';});</script>"
        "</body></html>",
        encoding="utf-8",
    )

    got = bnmap.probe_browser(url=page.as_uri(), seconds=20.0)

    step = got.get("after_load") or {}
    assert step.get("signed_in") is True, step
    assert "поля заполнены" in step.get("steps", [])
    text = json.dumps(got, ensure_ascii=False)
    assert login not in text, "логин доехал до ответа пробы"
    assert password not in text
    assert "Кабинет: [redacted]" in got.get("text_head", "")


def test_the_catalogue_is_asked_of_the_source_and_not_copied_into_us() -> None:
    """Список методов ведёт сервис, а не мы: копию негде обновлять.

    Клиент платформы строит из этого ответа весь свой API — имя `a.b.c`
    становится `POST /a.b.c`. Переписанный в наш код список устарел бы молча,
    как устаревали копии `VERSION` и долей ТЭП.
    """
    got = bnmap.catalogue()
    assert got["asked"] == bnmap.GATEWAY
    assert got.get("methods") or got.get("reason"), "каталог обязан назвать причину пустоты"
    # В модуле живут только те методы, чей ответ увиден, — это журнал проверок,
    # а не копия каталога. Каталог у сервиса на два с половиной сотни имён; как
    # только в исходнике окажется имя, которого никто не спрашивал, это уже
    # копия, и она устареет молча.
    # Имена ищутся по группам самого каталога (`analytics`, `layers`, `v1`…),
    # иначе в улов попадают домен и имя файла куки.
    groups = sorted({name.split(".")[0] for name in bnmap.VERIFIED})
    named = set(re.findall(r'"((?:%s)\.[A-Za-z_.]+)"' % "|".join(groups), source()))
    unknown = sorted(named - set(bnmap.VERIFIED))
    assert not unknown, "в модуле имена методов, чей ответ не увиден: " + ", ".join(unknown)
    assert len(bnmap.VERIFIED) < 40, "журнал проверок разросся до копии каталога"


def test_no_method_is_matched_to_our_checklist_before_its_answer_is_seen() -> None:
    """Имя метода обещает, но не отвечает.

    `analytics.objectDeals` звучит как сделки объекта, `layers.data` — как
    справочник проектов. Что лежит в их `content`, не видел никто: содержательные
    методы отвечают 401 без токена. Сопоставление, написанное по смыслу имени, —
    это ГИС Торги во второй раз.
    """
    for row in bnmap.WANTED:
        assert "у bnMAP" not in row, f"строка «{row['вопрос']}» сопоставлена по догадке"


def test_bnmap_stands_beside_the_report_and_not_inside_it() -> None:
    """Действующий отчёт собирает «Пульс», и bnMAP в него не входит.

    Владелец сказал это прямо (30.08.2026): «не сломай текущий рыночный отчет,
    этот пока тест для сравнения что лучше». Пока два источника не сверены на
    живых числах, менять в отчёте нечего — а подключить второй источник «на
    пробу» ровно в тот момент, когда он ещё ничего не отвечает, значит получить
    отчёт, у которого половина чисел ниоткуда.

    Сторож дешёвый и ловит главное: отчёт не должен знать про bnMAP, пока это
    решение не принято вслух.
    """
    report = (ROOT / "market_search" / "service_v6.py").read_text()
    assert "bnmap" not in report.lower(), "bnMAP просочился в сборку отчёта"
    pulse = (ROOT / "market_search" / "pulse.py").read_text()
    assert "bnmap" not in pulse.lower(), "bnMAP просочился в читателя «Пульса»"
