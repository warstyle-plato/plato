"""Права на расчёт: бесплатный участок, оплаченные участки, подписка.

Решения владельца 21.10.2026: без входа расчёт не запускается; после входа —
один участок бесплатно; дальше — оплата участка на 30 дней или подписка.
Участок — набор кадастровых номеров: тот же набор в любом порядке (и его
часть) — тот же участок, новый номер — новый. Администраторы — без ограничений.

Здесь закреплено:

- решение принимает одна функция, и её читают ВСЕ маршруты расчёта: страница,
  поэтапный расчёт, чувствительность, PDF, тизер, Excel, Платон, подбор цены,
  DevelopAid 2.0 и отчёт в Telegram — проверка идёт по читателям;
- отказ называет причину и что сделать, а не «403»;
- выдача по одному платёжу повторно не продлевает;
- запись прав под замком: два процесса не теряют выдачи друг друга;
- Render спрашивает ядро подписанным запросом, чужая подпись — отказ;
- страница на 402 не просит войти того, кто уже вошёл.

Запуск: python3 -m pytest tests/test_paid_access_rights.py -q
"""

from __future__ import annotations

import multiprocessing
import sys
from pathlib import Path

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import page_blocks

import main as _wrapper

core = _wrapper.core
client = TestClient(core.app)


def _mounted_client() -> TestClient:
    """Слой IA и DevelopAid 2.0 ставят свои маршруты отдельно — тем же
    `install`, что и прод, на свежее приложение."""
    from fastapi import FastAPI

    from developaid_v2 import install as install_v2
    from ia_preview import install as install_ia

    app = FastAPI()
    install_ia(app, core)
    install_v2(app)
    return TestClient(app)


mounted = _mounted_client()
MOUNTED = {"/ia/goal-seek", "/api/v2/calculate"}

CHAT = 6060
A1, A2, B = "50:20:0010101:11", "50:20:0010101:12", "50:20:0010101:99"
MODEL = {"tep": {k: dict(v) for k, v in core.TEP_DEFAULT.items()}, "rates": []}


def model_for(*numbers: str) -> dict:
    return {**MODEL, "inputs": {**core.DEFAULT_INPUTS, "cadastral_numbers": " ".join(numbers)}}


@pytest.fixture(autouse=True)
def paid(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123456:paid-access-test-token")
    monkeypatch.setenv("DEVELOPAID_ADMIN_IDS", "777")
    monkeypatch.setenv("DEVELOPAID_ADMIN_KEY", "kluch")
    monkeypatch.delenv("DEVELOPAID_FREE_PLOTS", raising=False)
    # Замок включается вместе с оплатой (`DEVELOPAID_PAYWALL`); здесь проверяется
    # он сам, а выключенный — отдельными проверками ниже.
    monkeypatch.setenv("DEVELOPAID_PAYWALL", "1")
    monkeypatch.setattr(core, "_MO_CALC_API_URL", "")
    core._ACCESS_REMOTE_CACHE.clear()
    yield


def session(chat: int = CHAT, cad: list[str] | None = None) -> str:
    return core._telegram_session(chat, cad or [])


def use(*numbers: str, chat: int = CHAT) -> dict:
    return core.access_use(chat, core.access_plot(cadastral=list(numbers)), surface="test")


def test_the_first_plot_is_free_and_the_same_set_stays_open():
    first = use(A1, A2)
    assert first["allowed"] and first["basis"] == "free"
    # Тот же набор в другом порядке и его часть — тот же участок.
    assert use(A2, A1)["allowed"]
    assert use(A1)["allowed"]
    assert core.access_status(CHAT)["free_left"] == 0


def test_a_neighbour_number_is_a_new_plot_and_the_refusal_says_what_to_do():
    use(A1)
    refused = use(A1, B)
    assert not refused["allowed"] and refused["code"] == "paid_needed"
    text = refused["detail"]
    assert "Бесплатный участок уже использован" in text and A1 in text
    assert "10 000 ₽" in text and "100 000 ₽" in text
    # Оплаты на сайте ещё нет — сказано, куда идти, а не к несуществующей кнопке.
    assert "напишите нам в бот" in text


def test_the_free_allowance_is_a_setting(monkeypatch):
    monkeypatch.setenv("DEVELOPAID_FREE_PLOTS", "2")
    assert use(A1)["allowed"] and use(B)["allowed"]
    refused = use("50:20:0010101:55")
    assert not refused["allowed"] and refused["detail"].startswith("Бесплатные участки")
    monkeypatch.setenv("DEVELOPAID_FREE_PLOTS", "0")
    assert use("50:20:0010101:56", chat=CHAT + 5)["detail"].startswith("Расчёт экономики платный")


def test_a_project_without_a_number_is_its_own_plot():
    project = core.access_plot({"_project_uid": "p0123456789ab"})
    assert project["kind"] == "project"
    assert core.access_use(CHAT, project)["allowed"]
    other = core.access_plot({"_project_uid": "p999999999999"})
    assert not core.access_use(CHAT, other)["allowed"]
    # Ни номера, ни проекта — не участок: бесплатный на это не тратится.
    nothing = core.access_use(CHAT + 1, core.access_plot({}))
    assert not nothing["allowed"] and nothing["code"] == "no_plot"
    assert core.access_status(CHAT + 1)["free_left"] == 1


def test_a_payment_is_granted_once_however_often_it_is_reported():
    use(A1)
    plot = core.access_plot(cadastral=[B])
    core.access_grant(CHAT, plot=plot, payment_id="pay-1")
    until = core.access_status(CHAT)["plots"][0]["until"]
    assert core.access_grant(CHAT, plot=plot, payment_id="pay-1")["repeated"]
    assert core.access_status(CHAT)["plots"][0]["until"] == until
    assert use(B)["allowed"]


def test_a_subscription_opens_every_plot():
    use(A1)
    core.access_grant(CHAT, subscription=True, payment_id="sub-1")
    assert use(B)["basis"] == "subscription"
    assert core.access_use(CHAT, core.access_plot({}))["allowed"]


def test_the_journal_records_grants_and_refusals():
    use(A1)
    use(B)
    events = [(row["event"], row.get("source") or row.get("code"))
              for row in core.access_journal_read() if row.get("chat") == CHAT]
    assert ("grant", "free") in events and ("refuse", "paid_needed") in events


def _grant_in_child(chat: int, index: int) -> None:
    core.access_grant(chat, plot=core.access_plot(cadastral=[f"50:20:0010101:{100 + index}"]),
                      payment_id=f"pay-{index}")


def test_two_workers_do_not_lose_each_others_grants(tmp_path, monkeypatch):
    if "fork" not in multiprocessing.get_all_start_methods():
        pytest.skip("нет fork: воркеры не поднять процессами")
    context = multiprocessing.get_context("fork")
    workers = [context.Process(target=_grant_in_child, args=(CHAT, i)) for i in range(12)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(30)
    assert len(core.access_status(CHAT)["plots"]) == 12


# --- все читатели одного решения ---------------------------------------------

def _refused_on_b(response) -> None:
    assert response.status_code == 402, response.text
    assert "Бесплатный участок уже использован" in response.json()["detail"]


ROUTES = {
    "/calculate": lambda s: model_for(B) | {"session": s},
    "/calculate-phased": lambda s: model_for(B) | {"session": s, "phasing": {"enabled": True, "phase_count": 2}},
    "/analysis/sensitivity": lambda s: model_for(B) | {"session": s},
    "/report/workbook": lambda s: model_for(B) | {"session": s},
    "/report/teaser": lambda s: model_for(B) | {"session": s},
    "/report/pdf": lambda s: {"result": {}, "inputs": {}, "cadastral_numbers": [B], "session": s},
    "/agent/chat": lambda s: model_for(B) | {"session": s, "message": "что с LLCR?"},
    "/ia/goal-seek": lambda s: model_for(B) | {"session": s},
    "/strategy-compare": lambda s: model_for(B) | {"session": s},
    "/loan-term-pick": lambda s: model_for(B) | {"session": s, "prefix": "offices"},
    "/api/v2/calculate": lambda s: model_for(B) | {"session": s},
}


@pytest.mark.parametrize("path", sorted(ROUTES))
def test_every_calculation_route_reads_the_same_decision(path):
    use(A1)
    _refused_on_b((mounted if path in MOUNTED else client).post(path, json=ROUTES[path](session())))


@pytest.mark.parametrize("path", sorted(ROUTES))
def test_without_a_login_nothing_is_calculated(path):
    body = ROUTES[path]("")
    answer = (mounted if path in MOUNTED else client).post(path, json=body)
    assert answer.status_code == 401, answer.text
    assert "Telegram" in answer.json()["detail"]


def test_the_report_to_telegram_reads_it_too():
    use(A1)
    answer = client.post("/telegram/result", json={"session": session(cad=[B]), "summary": {}})
    _refused_on_b(answer)


def test_the_paid_plot_opens_the_calculation():
    use(A1)
    answer = client.post("/calculate", json=model_for(A1) | {"session": session()})
    assert answer.status_code == 200 and "finance" in answer.json()


def test_admins_count_without_limits():
    use(A1, chat=777)
    assert client.post("/calculate", json=model_for(B) | {"session": session(777)}).status_code == 200
    assert client.post("/calculate", json=model_for(B) | {"access_key": "kluch"}).status_code == 200


def test_the_bot_refuses_in_words(monkeypatch):
    use(A1)
    sent: list[str] = []
    monkeypatch.setattr(_wrapper, "_send_message", lambda chat, text, **kw: sent.append(text))
    assert not _wrapper._bot_calc_allowed(CHAT, model_for(B), "Расчёт Excel-модели")
    assert "нет доступа" in sent[-1] and "Бесплатный участок уже использован" in sent[-1]
    assert _wrapper._bot_calc_allowed(CHAT, model_for(A1), "Расчёт Excel-модели")


# --- Render спрашивает ядро ----------------------------------------------------

def test_render_asks_the_core_with_a_signature(monkeypatch):
    calls: list[dict] = []

    def core_post(url, payload, timeout):
        calls.append(payload)
        answer = client.post("/internal/access/use", json=payload)
        if answer.status_code != 200:
            raise HTTPException(status_code=502, detail=answer.json()["detail"])
        return answer.json()

    monkeypatch.setattr(core, "_MO_CALC_API_URL", "https://core.example/mo/calculate")
    monkeypatch.setattr(core, "_core_post", core_post)
    assert core.calc_access_for_chat(CHAT, "Расчёт", cadastral=[A1])["allowed"]
    assert calls and calls[0]["key"] == f"cad:{A1}"
    with pytest.raises(HTTPException) as refused:
        core.calc_access_for_chat(CHAT, "Расчёт", cadastral=[B])
    assert refused.value.status_code == 402


def test_the_core_rejects_a_forged_request():
    forged = {"chat": CHAT, "kind": "cadastral", "cadastral": [A1], "key": f"cad:{A1}", "sign": "x"}
    assert client.post("/internal/access/use", json=forged).status_code == 403
    signed_other = {**forged, "cadastral": [B], "sign": core._access_sign(f"cad:{A1}", CHAT)}
    assert client.post("/internal/access/use", json=signed_other).status_code == 400


# --- страница ---------------------------------------------------------------

def _locked_html(status: int) -> str:
    prelude = ("const box={style:{},innerHTML:'',classList:{add(){},remove(){}}};"
               "const document={getElementById:()=>box};"
               "let lastResult=1,phaseBundle=1;"
               "const fetch=()=>Promise.reject(new Error('нет сети'));")
    out, _ = page_blocks.run(prelude, f"renderCalcLocked('Причина от сервера',{status});"
                                     "console.log(box.innerHTML);")
    return out


def test_the_page_does_not_ask_a_logged_in_person_to_log_in():
    paid = _locked_html(402)
    assert "Причина от сервера" in paid and "openLogin" not in paid
    assert "openLogin" in _locked_html(401)


def test_the_page_sends_the_session_with_every_calculation():
    page = core.PAGE
    for anchor in ("fetch('/report/workbook'", "fetch('/analysis/sensitivity'"):
        start = page.index(anchor)
        assert "activeSession()" in page[start:start + 600], anchor
    assert "inputs._project_uid=newProjectUid()" in page


def test_without_a_bot_token_every_surface_is_open(monkeypatch):
    """Решение одно и для сайта, и для бота: без токена выключено везде."""
    use(A1)
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    assert core.calc_access_for_chat(CHAT, "Расчёт", cadastral=[B])["basis"] == "open"


# --- выключатель замка и ключ команды ----------------------------------------

def test_with_the_paywall_off_the_calculation_works_as_before(monkeypatch):
    """Замок выключен по умолчанию: вошедший считает любой участок, а без входа
    расчёт закрыт, как и прежде."""
    use(A1)
    monkeypatch.delenv("DEVELOPAID_PAYWALL")
    assert not core.paywall_enabled()
    answer = client.post("/calculate", json=model_for(B) | {"session": session()})
    assert answer.status_code == 200, answer.text
    assert client.post("/calculate", json=model_for(B)).status_code == 401
    # Учёт в выключенном режиме ничего не тратит и не пишет.
    assert [g["label"] for g in core.access_status(CHAT)["plots"]] == [A1]


def test_with_the_paywall_on_the_refusal_names_the_reason():
    use(A1)
    answer = client.post("/calculate", json=model_for(B) | {"session": session()})
    assert answer.status_code == 402
    assert "Бесплатный участок уже использован" in answer.json()["detail"]


def test_the_market_cabinet_key_opens_everything(monkeypatch):
    """Ключ кабинета рынка — команда владельца: полный доступ, как у администратора."""
    monkeypatch.setenv("MARKET_CABINET_KEY", "team-test-key")
    use(A1)
    body = model_for(B) | {"session": session()}
    assert client.post("/calculate", json=body).status_code == 402
    answer = client.post("/calculate", json=body, headers={"X-Market-Key": "team-test-key"})
    assert answer.status_code == 200, answer.text
    # И без входа через Telegram — ключ сам по себе пропуск, как ключ администратора.
    cookie_client = TestClient(core.app, cookies={"market_cabinet": "team-test-key"})
    assert cookie_client.post("/calculate", json=model_for(B)).status_code == 200
    wrong = client.post("/calculate", json=model_for(B), headers={"X-Market-Key": "wrong-key"})
    assert wrong.status_code == 401


# --- экономика каталога КРТ ---------------------------------------------------

def _registry_client(**kw) -> TestClient:
    import main_registry  # noqa: PLC0415 — полное приложение с разделом торгов

    return TestClient(main_registry.app, **kw)


def test_the_krt_economics_reads_the_same_decision(monkeypatch):
    """Рейтинг каталога КРТ — экономика: без входа закрыт, при включённом замке
    весь каталог — по подписке, а ключ кабинета рынка открывает всё."""
    monkeypatch.setenv("MARKET_CABINET_KEY", "team-test-key")
    registry = _registry_client()
    refused = registry.get("/auctions/krt/ranking")
    assert refused.status_code == 401 and "Telegram" in refused.json()["detail"]
    use(A1)
    paid = registry.get("/auctions/krt/ranking", headers={"X-Developaid-Session": session()})
    assert paid.status_code == 402 and "по подписке" in paid.json()["detail"]
    # Раздел торгов берёт движок из `sys.modules["developaid_core"]`, а соседняя
    # проверка (`test_a_decision_site_is_modelled_too`) кладёт туда свою копию.
    # На проде копия одна; здесь выдаём подписку в каждой, какую мог взять раздел.
    for engine in {id(m): m for m in (core, sys.modules.get("developaid_core")) if m}.values():
        engine.access_grant(CHAT, subscription=True, payment_id="sub-krt")
    assert registry.get("/auctions/krt/ranking",
                        headers={"X-Developaid-Session": session()}).status_code == 200
    team = registry.get("/auctions/krt/ranking", headers={"X-Market-Key": "team-test-key"})
    assert team.status_code == 200


def test_with_the_paywall_off_the_krt_economics_needs_only_a_login(monkeypatch):
    monkeypatch.delenv("DEVELOPAID_PAYWALL")
    registry = _registry_client()
    assert registry.get("/auctions/krt/ranking").status_code == 401
    assert registry.get("/auctions/krt/ranking",
                        headers={"X-Developaid-Session": session()}).status_code == 200


def test_the_catalog_pages_send_the_session():
    from auction_search import krt_investment_card, ui  # noqa: PLC0415

    for source in (Path(ui.__file__).read_text(encoding="utf-8"),
                   Path(krt_investment_card.__file__).read_text(encoding="utf-8")):
        assert "'X-Developaid-Session'" in source
