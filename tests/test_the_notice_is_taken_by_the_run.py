"""Извещение лота берётся прогоном, а не рукой.

«Почему ты не берешь извещения тогда? они же есть у всех кто на торгах! и лежит
в росэлторге» (владелец, 14.09.2026). Он прав: состав территории появлялся
ТОЛЬКО когда человек нажимал «Разобрать лот» — разбор вложений зовётся из
маршрута одного лота и из CLI, а прогон каталога не звал его вовсе. Замер прода
14.09.2026: из одиннадцати площадок с живым лотом состав из извещения был у
ОДНОЙ, той, которую я разобрал рукой.

Утверждения здесь такие.

**Проход читает извещение сам** — по связке «площадка ↔ лот», без нажатия.

**Второй заход за то же не платит.** Разобранный состав не спрашивается больше
никогда: торги идут по одному извещению.

**Три ответа, и слить их нельзя.** Состав прочитан; вложения прочитаны, а
таблицы в них нет (ответ ДОКУМЕНТОВ, живёт сутки); площадка вложения не отдала
(её ответ, спрашивается через полчаса). Причина у площадки называет, ЧЕЙ это
пробел — наш, документов или площадки.

**Срок сильнее списка.** Недочитанное названо числом и дочитывается следующим
заходом: молча брошенный лот читался бы как «состава у него нет».

**Проход стоит в пути сторожа**, а не маршрута: минуты внешних запросов в
ответе маршрута — это шлюз, отдающий свою страницу на 504 вместо каталога.

Запуск: python3 -m pytest tests/test_the_notice_is_taken_by_the_run.py -q
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from auction_search import krt_pipeline, krt_territory  # noqa: E402

NOTICE_PDF = ROOT / "reference_data" / "krt" / "nagatino-auction-notice-2026-08-14.pdf"
NOTICE_URL = "https://www.roseltorg.ru/file/notice.pdf"
DECISION_PDF = ROOT / "reference_data" / "krt" / "nagatino-decision-draft.pdf"
KEY = "21000005000000033023/1"
LOT_URL = "https://www.roseltorg.ru/procedure/21000005000000033023/1"
BY_SITE = {"nizhnie-polya": [{"title": "Лот 1 · КРТ", "url": LOT_URL,
                              "store_key": KEY}]}


def _lot(*, kind=None, title="Территория.Лотовая документация.pdf"):
    from auction_search.models import (
        AuctionDocument, AuctionLot, AuctionSource, LotKind, SourceKind,
    )

    return AuctionLot(
        source=AuctionSource(platform=SourceKind.ROSELTORG, lot_url=LOT_URL,
                             external_lot_id=KEY,
                             fetched_at="2026-09-14T06:00:00Z"),
        lot_kind=kind or LotKind.KRT,
        title="КРТ: право на заключение договора",
        documents=[AuctionDocument(title=title, url=NOTICE_URL,
                                   document_type="other")],
    )


def _platform(body: bytes | None = None, content_type: str = "application/pdf"):
    def download(url, **_kwargs):
        assert url == NOTICE_URL, url
        return (body if body is not None else NOTICE_PDF.read_bytes()), \
            content_type, False

    return download


def _fetcher(calls: list[str], lot=None):
    def fetch(url: str):
        calls.append(url)
        return lot if lot is not None else _lot()

    return fetch


def test_the_run_reads_the_notice_without_a_hand_press(tmp_path, monkeypatch):
    """Состав территории приезжает проходом по связке, а не нажатием."""
    monkeypatch.setattr(krt_pipeline, "download_document", _platform())
    calls: list[str] = []

    got = krt_pipeline.read_notices(BY_SITE, fetch_lot=_fetcher(calls),
                                    store_dir=tmp_path)

    assert calls == [LOT_URL], calls
    assert (got["lots"], got["asked"], got["read"]) == (1, 1, 1), got
    stored = krt_territory.stored_notice(KEY, root=tmp_path)
    assert stored["lands"], "состав территории проходом не прочитан"
    assert stored["document"] == "Территория.Лотовая документация.pdf", stored


def test_a_second_pass_does_not_pay_for_what_is_already_read(tmp_path, monkeypatch):
    """Разобранный состав не спрашивается больше никогда: одно извещение на торги."""
    monkeypatch.setattr(krt_pipeline, "download_document", _platform())
    krt_pipeline.read_notices(BY_SITE, fetch_lot=_fetcher([]), store_dir=tmp_path)

    def bomb(url: str):
        raise AssertionError("площадку спросили о прочитанном составе")

    again = krt_pipeline.read_notices(BY_SITE, fetch_lot=bomb, store_dir=tmp_path)
    assert (again["already"], again["asked"]) == (1, 0), again


def test_no_table_is_the_documents_answer_and_lives_a_day(tmp_path, monkeypatch):
    """«Таблицы состава в вложениях нет» — ответ документов, и он свой срок живёт.

    Спрашивать площадку об этом каждые три часа значит платить минутами за один
    и тот же ответ; спрашивать раз в сутки — лотовую документацию дополняют, но
    не каждый час.
    """
    # Вложение ЧИТАЕМОЕ (906 абзацев), и таблицы состава в нём нет:
    # неоткрывшийся документ — это отказ площадки, а не ответ «таблицы нет», и
    # путать их нельзя.
    monkeypatch.setattr(krt_pipeline, "download_document",
                        _platform(DECISION_PDF.read_bytes()))
    first = krt_pipeline.read_notices(BY_SITE, fetch_lot=_fetcher([]),
                                      store_dir=tmp_path)
    assert (first["no_table"], first["read"]) == (1, 0), first
    assert krt_territory.stored_attempt(KEY, root=tmp_path)["outcome"] == "no_table"

    soon = krt_pipeline.read_notices(
        BY_SITE, fetch_lot=lambda url: (_ for _ in ()).throw(
            AssertionError("спросили раньше срока")),
        store_dir=tmp_path, now=lambda: time.time() + 3600)
    assert (soon["waiting"], soon["asked"]) == (1, 0), soon

    calls: list[str] = []
    later = krt_pipeline.read_notices(
        BY_SITE, fetch_lot=_fetcher(calls), store_dir=tmp_path,
        now=lambda: time.time() + krt_territory.NO_TABLE_TTL_SECONDS + 60)
    assert calls == [LOT_URL], "через сутки площадку не спросили заново"
    assert later["asked"] == 1, later


def test_a_platform_refusal_is_asked_again_sooner(tmp_path):
    """Отказ площадки — её ответ, а не свойство лота: полчаса, а не сутки.

    Росэлторг отдаёт файл через раз, и записанный навсегда отказ означал бы, что
    состав территории у площадки не появится больше никогда.
    """
    def refuse(url: str):
        raise RuntimeError("HTTP 503 после трёх попыток")

    first = krt_pipeline.read_notices(BY_SITE, fetch_lot=refuse,
                                      store_dir=tmp_path)
    assert first["refused"] == 1, first
    attempt = krt_territory.stored_attempt(KEY, root=tmp_path)
    assert attempt["outcome"] == "refused"
    assert "503" in attempt["why"], attempt

    assert not krt_territory.notice_due(KEY, root=tmp_path, now=time.time() + 600)
    assert krt_territory.notice_due(
        KEY, root=tmp_path,
        now=time.time() + krt_territory.REFUSED_TTL_SECONDS + 60)


def test_the_budget_is_stronger_than_the_list_and_says_so(tmp_path):
    """Срок держит поток сторожа, а недочитанное названо числом, а не молчанием."""
    def bomb(url: str):
        raise AssertionError("лот спрошен после истечения срока")

    got = krt_pipeline.read_notices(BY_SITE, fetch_lot=bomb, store_dir=tmp_path,
                                    budget_seconds=0)
    assert (got["out_of_time"], got["asked"]) == (1, 0), got
    # И отметки попытки на брошенном лоте нет: «не успели» — это не «спросили».
    assert krt_territory.stored_attempt(KEY, root=tmp_path) == {}


def test_a_lot_that_is_not_krt_does_not_poison_the_pass(tmp_path, monkeypatch):
    """Один лот не роняет проход: так уже падал весь сбор из-за одной карточки.

    И это НЕ перебой площадки: вторым заходом через полчаса «читателя нет» не
    лечится, а карточку лота спрашивали бы 48 раз в сутки за один и тот же
    ответ. Поэтому свой ответ, свой срок и своя причина на экране.
    """
    from auction_search.models import LotKind

    monkeypatch.setattr(krt_pipeline, "download_document", _platform())
    got = krt_pipeline.read_notices(
        BY_SITE, fetch_lot=lambda url: _lot(kind=LotKind.LAND_SALE),
        store_dir=tmp_path)
    assert (got["unsupported"], got["refused"]) == (1, 0), got
    assert krt_territory.stored_notice(KEY, root=tmp_path)["lands"] == []
    assert krt_territory.stored_attempt(KEY, root=tmp_path)["outcome"] == "unsupported"
    # Срок у него длинный — как у ответа документов, а не как у перебоя.
    assert not krt_territory.notice_due(
        KEY, root=tmp_path,
        now=time.time() + krt_territory.REFUSED_TTL_SECONDS + 60)
    assert krt_territory.notice_due(
        KEY, root=tmp_path,
        now=time.time() + krt_territory.NO_TABLE_TTL_SECONDS + 60)
    why = krt_territory.stored_notice(KEY, root=tmp_path)["problem"]
    assert "нашим разбором не читается" in why, why
    assert "площадка не отдала" not in why, why


def test_the_empty_reason_names_whose_gap_it_is(tmp_path):
    """Три разных ответа под похожими словами: наш пробел, документов, площадки."""
    ours = krt_territory.stored_notice(KEY, root=tmp_path)["problem"]
    assert "наш пробел" in ours, ours

    krt_territory.remember_attempt(KEY, outcome="no_table", documents=26,
                                   root=tmp_path)
    documents = krt_territory.stored_notice(KEY, root=tmp_path)["problem"]
    assert "таблицы состава" in documents, documents
    assert "26" in documents, documents

    krt_territory.remember_attempt(KEY, outcome="refused", why="HTTP 503",
                                   root=tmp_path)
    platform = krt_territory.stored_notice(KEY, root=tmp_path)["problem"]
    assert "площадка не отдала" in platform, platform
    assert "503" in platform, platform
    assert len({ours, documents, platform}) == 3, "три ответа слились в один"


def _app(tmp_path, monkeypatch):
    """Приложение с одним КРТ-лотом в выдаче — тем путём, которым ходит сторож."""
    from types import SimpleNamespace

    from fastapi import FastAPI

    from auction_search import api as api_module
    from market_search.krt_registry import KrtRegistry

    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    registry = KrtRegistry(tmp_path)
    app = FastAPI()
    app.state.market_discovery_service = SimpleNamespace(
        krt=SimpleNamespace(
            catalogue=lambda **_kw: [dict(SITE)],
            status=lambda: {"complete": True, "refreshing": False},
            find=lambda query: None,
            decisions=lambda **_kw: {"rows": [], "complete": True},
            tender_lots_known=registry.tender_lots_known,
            remember_tender_lots=registry.remember_tender_lots,
        ),
    )
    api_module.install(app)
    return app


SITE = {"slug": "nizhnie-polya", "name": "Нижние Поля ул.", "okrug": "ЮВАО",
        "status": "Планируемый", "area_ha": 21.3}


def test_the_pass_stands_where_the_lots_are_collected(tmp_path, monkeypatch):
    """Состав приезжает тем же заходом, что собирает лоты, — без нажатия.

    Утверждение узкое и главное: проход зовётся из пути сторожа. Прежде разбор
    вложений звался только из маршрута одного лота, то есть по нажатию
    «Разобрать лот», и «извещение лота ещё не разбиралось» было НАШИМ пробелом,
    выданным на экране за ответ документов.
    """
    from auction_search import api as api_module

    app = _app(tmp_path, monkeypatch)
    lot = {"title": "Аукцион на право заключения договора о комплексном развитии "
                    "территории по адресу: г. Москва, Нижние Поля ул., площадью 21,3 га",
           "address": "г. Москва, Нижние Поля ул.",
           "source": {"lot_url": LOT_URL, "external_lot_id": KEY},
           "url": LOT_URL, "application_deadline": "2026-12-01"}

    monkeypatch.setattr(api_module.AuctionSearchService, "discover_moscow",
                        lambda self, **_kw: [lot])
    monkeypatch.setattr(api_module, "_public_lot_dict", lambda one: dict(one))
    monkeypatch.setattr(krt_pipeline, "download_document", _platform())
    fetched: list[str] = []

    class _Adapter:
        def fetch_lot(self, url):
            fetched.append(url)
            return _lot()

    monkeypatch.setattr(api_module, "_adapter_for", lambda url: _Adapter())

    by_site = app.state.krt_tender_links_collect()

    assert by_site.get(SITE["slug"]), ("лот с площадкой не связался — "
                                       "проверять проход было бы не на чем")
    assert fetched == [LOT_URL], (
        "проход за извещениями не позван оттуда, где собираются лоты")
    stored = krt_territory.stored_notice(KEY, root=tmp_path / "market")
    assert stored["lands"], "состав территории не приехал без нажатия"


def test_the_pass_can_be_turned_off_and_says_so(tmp_path, monkeypatch):
    """Выключенный проход — ответ, а не поломка: у молчания есть счётчик."""
    from fastapi.testclient import TestClient

    monkeypatch.setenv("AUCTION_KRT_NOTICES", "0")
    app = _app(tmp_path, monkeypatch)
    assert app.state.krt_notices_read({}) == {}, "выключенный проход всё же ходил"

    state = TestClient(app).get("/auctions/krt/watch").json()["notices"]
    assert state["enabled"] is False, state
    assert state["budget_seconds"] > 0, state
    # «Здесь он ещё не заходил» и «прочитал ноль» — разные ответы.
    assert state["last_run"] == {}, state


def _textless_pdf() -> bytes:
    """Скан: PDF есть, текста в нём нет. Ровно два таких вложения лежат у лота
    МКАД, 41 км — «Постановление» и «Схема границ», и площадка отдала оба."""
    from io import BytesIO

    from reportlab.pdfgen import canvas

    buf = BytesIO()
    page = canvas.Canvas(buf)
    page.rect(10, 10, 50, 50, fill=1)
    page.showPage()
    page.save()
    return buf.getvalue()


def test_an_unreadable_attachment_is_our_gap_not_a_platform_refusal(
        tmp_path, monkeypatch):
    """Площадка отдала, а прочитать не смогли МЫ — и так это и называется.

    Замер лота 21000005000000031293/1 с прода 21.09.2026:
    `asked 27, fetched 27, read 24, from_store 27` — Росэлторг отдал ВСЁ, ни
    одного отказа площадки. Три «неотданных» несут `kind: extraction_error`:
    два скана PDF и архив со скриншотами. А на экране стояло «площадка не
    отдала вложения лота: не отдано вложений: 3 … Спросим снова» — наш пробел,
    приписанный источнику, и обещание второго захода, который ничего не
    изменит: байты уже на складе.

    Виды отказа разведены `_refusal_kind` давно; причина выбиралась по НАЛИЧИЮ
    отказа, а не по его виду.
    """
    monkeypatch.setattr(krt_pipeline, "download_document",
                        _platform(_textless_pdf()))

    got = krt_pipeline.read_notices(BY_SITE, fetch_lot=_fetcher([]),
                                    store_dir=tmp_path)

    assert (got["unread"], got["refused"]) == (1, 0), got
    attempt = krt_territory.stored_attempt(KEY, root=tmp_path)
    assert attempt["outcome"] == "unread", attempt

    problem = krt_territory._attempt_problem(attempt)
    assert "площадка не отдала" not in problem.lower(), problem
    assert "наш пробел" in problem, problem
    assert "Спросим снова" not in problem, (
        "второй заход ничего не изменит — байты уже на складе")

    # Срок — как у ответа документов, а не как у перебоя площадки: заново
    # качать нечего, до починки читателя ответ будет тот же.
    assert not krt_territory.notice_due(
        KEY, root=tmp_path,
        now=time.time() + krt_territory.REFUSED_TTL_SECONDS + 60)
    assert krt_territory.notice_due(
        KEY, root=tmp_path,
        now=time.time() + krt_territory.NO_TABLE_TTL_SECONDS + 60)


def test_a_platform_refusal_among_ours_still_blames_the_platform(
        tmp_path, monkeypatch):
    """Перебой площадки рядом с нашим сканом решает за обоих — и это верно.

    «Таблицы нет» тут утверждать нельзя: она могла стоять как раз в
    неотданном, и спрашивать надо снова через полчаса, а не через сутки.
    Предохранитель здесь обязателен — на чистом скане ответ ДРУГОЙ (`unread`),
    и без разных вложений проверка была бы зелена при любом правиле.
    """
    from auction_search.documents import DocumentTemporaryRefusal
    from auction_search.models import AuctionDocument

    lot = _lot()
    held = "https://www.roseltorg.ru/file/held.pdf"
    lot.documents.append(AuctionDocument(
        title="Территория.Сведения о земельных участках.pdf", url=held,
        document_type="other"))

    def download(url, **_kwargs):
        if url == held:
            raise DocumentTemporaryRefusal("HTTP 503 после трёх попыток")
        return _textless_pdf(), "application/pdf", False

    monkeypatch.setattr(krt_pipeline, "download_document", download)

    got = krt_pipeline.read_notices(
        BY_SITE, fetch_lot=_fetcher([], lot=lot), store_dir=tmp_path)

    assert (got["refused"], got["unread"]) == (1, 0), got
    attempt = krt_territory.stored_attempt(KEY, root=tmp_path)
    assert attempt["outcome"] == "refused", attempt
    assert "не отдано вложений" in attempt["why"], attempt
    assert krt_territory.notice_due(
        KEY, root=tmp_path,
        now=time.time() + krt_territory.REFUSED_TTL_SECONDS + 60)
