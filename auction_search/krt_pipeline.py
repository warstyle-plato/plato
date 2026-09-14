from __future__ import annotations

from pathlib import Path

from auction_search import (
    egrn_archive, egrn_extracts, egrn_store, krt_notice, lot_documents,
)
from auction_search.documents import (
    DocumentAuthorizationRequired,
    DocumentExtractionError,
    DocumentTemporaryRefusal,
    download_document,
    extract_document_paragraphs,
)
from auction_search.krt import extract_krt_obligations, extract_krt_program
from auction_search.models import AuctionLot, LotKind


_PROGRAM_DOC_TYPES = {"krt_decision", "agreement", "notice", "annex", "other"}
_OBLIGATION_DOC_TYPES = {"agreement", "notice", "annex", "krt_decision", "other"}
# Где искать таблицу состава территории. Раньше здесь стояли «извещение» и
# «приложение» — виды, которых Росэлторг не ставит: тип он выводит из ИМЕНИ
# файла по словам «извещ»/«прилож», а площадка зовёт документ «Территория.
# Лотовая документация.pdf» и «Территория.Сведения о земельных участках.pdf».
# Живой счёт по лоту 21000005000000033023 (14.09.2026): 14 «прочее», 13
# «договор», 3 «ЕГРН» и ни одного «извещения» — гейт не срабатывал ни разу, а
# состав приезжал запасным перечнем проекта решения.
#
# Поэтому таблицу ищет сам разбор, в тех же вложениях, что программу и
# обязательства: их байты уже в руках, а `krt_notice` отвечает «таблицы здесь
# нет» даром и пустым разбором прочитанного не вытесняет.
_NOTICE_DOC_TYPES = _PROGRAM_DOC_TYPES


def krt_territory():
    """Склад состава территории. Импортируется при вызове, а не на модуле:
    `krt_territory` тянет `nagatino_parcels`, а тот — этот же пайплайн через
    маршруты, и круговой импорт разрешался бы порядком загрузки."""
    from auction_search import krt_territory as module

    return module


def store_key(lot: AuctionLot | dict) -> str:
    """Ключ лота на складе скачанного. Один ответ на «чей это файл».

    Берётся номер процедуры площадки: адрес лота у Росэлторга меняется вместе
    со строкой запроса, а номер — то, чем лот зовут и люди, и сама площадка.
    Нет номера — канонический ключ лота, тот же, которым он сводится внутри
    DevelopAid.

    Принимает и сам лот, и его словарь: связка «площадка ↔ лот» хранится
    словарём, и ключ склада ей нужен тот же. Свой второй разбор номера из
    адреса лота был бы второй реализацией формата площадки — а формат этот
    объявлен в её адаптере.
    """
    if isinstance(lot, dict):
        source = lot.get("source") or {}
        external = str(source.get("external_lot_id") or "").strip()
        return external or str(lot.get("canonical_key") or "")
    external = str(getattr(lot.source, "external_lot_id", "") or "").strip()
    return external or lot.canonical_key


def _bytes_of(document, *, store: Path | None, key: str,
              deadline: float | None,
              not_kept: list[dict] | None = None) -> tuple[bytes, str, str]:
    """Байты вложения: сперва склад, потом площадка. Откуда взяли — часть ответа.

    Склад отвечает на «это уже скачано», и его ответ сильнее нового запроса:
    площадка отдаёт файл через раз, и второй разбор того же лота не имеет права
    зависеть от её настроения. Отказ склада (нет места, вложение больше предела)
    разбор не рвёт — байты уже в руках, — но и не молчит.
    """
    if store is not None:
        kept = lot_documents.load(store, key, document.url)
        if kept is not None:
            data, content_type, _entry = kept
            if not document.access_status:
                document.access_status = "public"
            document.auth_required = False
            return data, content_type, "склад"
    data, content_type, authenticated = download_document(
        document.url, deadline=deadline)
    document.access_status = "authenticated" if authenticated else "public"
    document.auth_required = False
    if store is not None:
        try:
            lot_documents.save(store, key, document.url, data=data,
                               content_type=content_type,
                               title=document.title or "")
        except (lot_documents.Refused, OSError) as exc:
            # Склад — ускорение, а не источник истины: не принял, значит
            # следующий разбор снова спросит площадку. Но и не молчит: не
            # положенное на склад названо поимённо в своде, иначе «второй
            # разбор снова качает» выглядит поломкой без причины.
            if not_kept is not None:
                not_kept.append({"document": document.title or document.url,
                                 "why": str(exc)})
    return data, content_type, "площадка"


def _refusal_kind(exc: Exception) -> str:
    """Три ответа, и слить их нельзя: нас не пустили, площадка отказала
    временно, документ не разобрался. Первый лечится сессией, второй — вторым
    заходом, третий — читателем."""
    if isinstance(exc, DocumentAuthorizationRequired):
        return "auth_required"
    if isinstance(exc, DocumentTemporaryRefusal):
        return "temporary"
    return "extraction_error"


def enrich_krt_from_official_documents(
        lot: AuctionLot, *, store_dir: Path | str | None = None,
        deadline: float | None = None) -> AuctionLot:
    """Programme, obligations and EGRN holders from official ETP attachments only.

    Extraction/auth failures are retained in `lot.raw['krt_document_warnings']`;
    the lot is never silently treated as having no obligations merely because a
    document is a scan or the ETP requires an authenticated service-account session.

    У вложений два разных вопроса, и вложение с выписками отвечает на свой:
    программа и обязательства живут в решении, договоре и извещении, а
    правообладатель участка — в выписке ЕГРН (`lot.raw['egrn']`, свод —
    `egrn_summary`). Прежде такие вложения пропускались одной строкой вместе с
    ГПЗУ, то есть собственники до лота не доезжали вовсе.

    Байты берутся ОДИН раз на вложение и через склад (`store_dir`): дальше их
    разбирают разные читатели, а площадка отдаёт файл через раз. Второй разбор
    того же лота поэтому спрашивает площадку только о том, чего она не отдала, —
    это и есть второй проход, и он не стоит ни одного лишнего мегабайта.

    Состояний у вложения три, и слить их нельзя: прочитано, площадка не отдала
    (с причиной), не спрашивали намеренно (ГПЗУ — программы в нём нет). Счёт
    ведётся в `lot.raw['krt_documents']`, потому что «прочитано 21 из 26» и
    «документов 26» на экране отвечают на разные вопросы.
    """
    if lot.lot_kind != LotKind.KRT:
        return lot

    program = list(lot.krt_program)
    obligations = list(lot.obligations)
    warnings: list[dict[str, str]] = []

    parcels: list[dict] = []
    egrn_documents: list[dict] = []
    key = store_key(lot)
    store = Path(store_dir) if store_dir else None
    ledger: dict[str, object] = {
        "asked": 0, "fetched": 0, "read": 0, "from_store": 0,
        "refused": [], "skipped": [], "again": [],
    }
    not_kept: list[dict] = []

    def refuse(document, exc: Exception) -> None:
        """Записать отказ по вложению — один раз и во все места, где его ждут.

        Мест три, и каждое читает своё: общие предупреждения (по ним считается
        полнота разбора), счёт вложений (по нему говорит экран) и сам блок
        выписок (без записи в нём свод отвечает «не спрашивали» там, где
        площадка отказала). Две копии этой записи разошлись бы молча — и одна
        уже разошлась: у вложения ЕГРН вид отказа брался по месту в коде, а не
        у самого отказа, и «нужен вход» превращался в «не разобралось».
        """
        kind = _refusal_kind(exc)
        if kind == "auth_required":
            document.access_status = "auth_required"
            document.auth_required = True
        row = {"document": document.title, "url": document.url,
               "error": str(exc), "kind": kind}
        warnings.append(row)
        ledger["refused"].append(row)
        if kind == "temporary":
            # Временный отказ спрашивается снова при следующем разборе:
            # прочитанное к тому времени лежит на складе, и заново едет
            # только неотданное.
            ledger["again"].append({"document": document.title,
                                    "url": document.url})
        if document.document_type == "egrn":
            # На лоте 21000005000000033023 Росэлторг ответил 503 по трём
            # вложениям — ответ площадки, выданный за отсутствие вопроса.
            egrn_documents.append({
                "document": document.title, "url": document.url,
                "entries": 0, "read": 0, "unread": [], "companions": [],
                "duplicates": [], "error": str(exc), "kind": kind,
            })

    for document in lot.documents:
        if document.document_type == "gpzu":
            # Намеренный пропуск: у ГПЗУ нет ни программы, ни обязательств. Он
            # назван, а не молчит — молча пропущенное вложение на экране
            # неотличимо от неотданного площадкой.
            ledger["skipped"].append({
                "document": document.title, "url": document.url,
                "why": "ГПЗУ: программы и обязательств в нём нет",
            })
            continue

        ledger["asked"] = int(ledger["asked"]) + 1
        try:
            data, content_type, came_from = _bytes_of(
                document, store=store, key=key, deadline=deadline,
                not_kept=not_kept)
        except DocumentExtractionError as exc:
            refuse(document, exc)
            continue

        ledger["fetched"] = int(ledger["fetched"]) + 1
        if came_from == "склад":
            ledger["from_store"] = int(ledger["from_store"]) + 1

        if document.document_type == "egrn":
            found = egrn_archive.read(data, name=document.title or document.url)
            parcels.extend(found["records"])
            egrn_documents.append({
                "document": document.title,
                "url": document.url,
                "entries": found["entries"],
                "read": found["read"],
                "unread": found["unread"],
                "companions": found["companions"],
                "duplicates": found["duplicates"],
            })
            ledger["read"] = int(ledger["read"]) + 1
            # Разобранное ложится на тот же склад, куда кладёт присланный
            # руками зип: склад отвечает на «что мы знаем об объектах этого
            # лота», и второй ответ на этот вопрос разошёлся бы с первым.
            # Прежде разбор загрузчика жил только в ответе маршрута — то есть
            # свод территории читать его было нечем, и площадка выглядела
            # непрочитанной при двадцати шести прочитанных вложениях.
            if store is not None:
                try:
                    egrn_store.save(store, key, found,
                                    document.title or document.url)
                except Exception as exc:  # noqa: BLE001 — отказ склада назван
                    not_kept.append({"document": document.title,
                                     "url": document.url,
                                     "why": f"склад разобранного: {exc}"[:200]})
            # Запись, которую не прочитали, — наш пробел, и он назван: молча
            # выброшенная выписка читается как отсутствие собственника.
            if found["unread"]:
                warnings.append({
                    "document": document.title,
                    "url": document.url,
                    "error": "не прочитано: " + "; ".join(
                        f"{item['name']} — {item['reason']}" for item in found["unread"][:20]),
                    "kind": "egrn_unread",
                })
            continue

        if document.document_type in _NOTICE_DOC_TYPES and store is not None:
            # Приложение 2 к извещению — состав территории: участок, объекты на
            # нём и их судьба. Таблица стоит в ОДНОМ вложении из многих, и
            # неудача на остальных её не отменяет — пустой разбор прочитанного
            # не вытесняет (`remember_notice`). Читается тем же `krt_notice`,
            # которым читается извещение Нагатино: второй разбор той же
            # таблицы однажды ответил бы про один документ иначе.
            try:
                notice = krt_notice.read_bytes(data)
            except Exception as exc:  # noqa: BLE001 — отказ разбора назван, а не молчит
                # Отказ пишется у того вложения, где таблицу искали и не
                # разобрали. Прежде он писался только у вида «извещение» —
                # то есть у вида, которого площадка не ставит.
                ledger["skipped"].append({
                    "document": document.title, "url": document.url,
                    "why": f"состав территории не разобран: {exc}"[:200]})
            else:
                krt_territory().remember_notice(
                    key, notice, document=document.title or document.url,
                    root=Path(store))

        try:
            paragraphs = extract_document_paragraphs(document, data, content_type)
        except DocumentExtractionError as exc:
            refuse(document, exc)
            continue
        ledger["read"] = int(ledger["read"]) + 1

        if document.document_type in _PROGRAM_DOC_TYPES:
            program.extend(
                extract_krt_program(
                    paragraphs,
                    source_url=document.url,
                    source_document=document.title,
                    fetched_at=document.fetched_at or lot.source.fetched_at,
                )
            )
        if document.document_type in _OBLIGATION_DOC_TYPES:
            obligations.extend(
                extract_krt_obligations(
                    paragraphs,
                    source_url=document.url,
                    source_document=document.title,
                    fetched_at=document.fetched_at or lot.source.fetched_at,
                )
            )

    lot.krt_program = _dedupe_program(program)
    lot.obligations = _dedupe_obligations(obligations)
    if egrn_documents:
        lot.raw["egrn"] = {
            "records": parcels,
            "lands": sum(1 for item in parcels if item.get("kind") == "land"),
            "builds": sum(1 for item in parcels if item.get("kind") == "build"),
            "documents": egrn_documents,
        }
    lot.raw["krt_documents"] = ledger
    if store is not None:
        # Предел склада проверяется здесь, а не «когда-нибудь»: функция,
        # написанная сводить склад к пределу, и позвана должна быть — иначе
        # предел объявлен и не действует, а диск у нас уже кончался молча.
        swept = lot_documents.sweep(store)
        # Склад — не украшение ответа: молчащий склад неотличим от
        # отсутствующего, а кончающийся диск виден в числах раньше, чем в
        # поведении. Выселенное называется: молча вычищенный лот читается как
        # «его и не качали».
        ledger["store"] = {**lot_documents.state(store),
                           "evicted": swept["evicted"],
                           "not_kept": not_kept}
    if warnings:
        lot.raw["krt_document_warnings"] = warnings
    lot.raw["krt_auth_required"] = any(w.get("kind") == "auth_required" for w in warnings)
    lot.raw["krt_extraction_complete"] = bool(lot.documents) and not warnings
    return lot


def documents_summary(lot: AuctionLot) -> dict | None:
    """Сколько вложений спросили, сколько прочитали и что площадка не отдала.

    Посчитанное за маршрутом и никем не показанное неотличимо от
    непосчитанного: счёт лежал в `lot.raw`, а `include_raw` у карточки выключен —
    на экране стояло «Документов 26» и ни слова о том, что четыре из них
    площадка не отдала.

    «Документов 26» и «прочитано 21 из 26» — разные утверждения, и первое без
    второго читается как «разобрали двадцать шесть».
    """
    ledger = lot.raw.get("krt_documents")
    if not isinstance(ledger, dict):
        return None
    refused = [dict(row) for row in (ledger.get("refused") or [])]
    skipped = [dict(row) for row in (ledger.get("skipped") or [])]
    again = [dict(row) for row in (ledger.get("again") or [])]
    by_kind: dict[str, int] = {}
    for row in refused:
        kind = str(row.get("kind") or "")
        by_kind[kind] = by_kind.get(kind, 0) + 1
    return {
        "total": len(lot.documents),
        "asked": int(ledger.get("asked") or 0),
        # «Скачали» и «прочитали» — разные числа: фотоархив лота 33444
        # приезжает целиком и текста не содержит вовсе.
        "fetched": int(ledger.get("fetched") or 0),
        "read": int(ledger.get("read") or 0),
        "from_store": int(ledger.get("from_store") or 0),
        "refused": refused,
        "refused_by_kind": by_kind,
        "skipped": skipped,
        "ask_again": again,
        "store": ledger.get("store") or None,
    }


def egrn_summary(lot: AuctionLot) -> dict | None:
    """Кто правообладатель по выпискам лота. Второго ответа об этом нет.

    Личность сводится тем же `holder_key`, которым её сводит страница Нагатино:
    одна компания приходит и капсом, и обычным письмом, а субъект РФ то
    «Москва», то «город Москва» — сложенные по имени, они дают двух владельцев
    вместо одного. Право оперативного управления собственностью не считается:
    девять строений квартала записаны за городом, а держит их ГБУ.

    Незарегистрированное право — ответ документа, а не наш пробел, поэтому оно
    стоит своим числом, а не подмешивается к владельцам.

    Состояний три, и слить их нельзя. Вложений с выписками у лота нет — свода
    нет вовсе (`None`), это «не спрашивали». Вложения есть, а площадка
    отказала — свод есть, владельцев в нём нет, и отказ назван поимённо с
    причиной: 503 Росэлторга это ответ площадки, а не отсутствие вопроса.
    Прочитали — владельцы по ИНН.

    И у пустого ответа причина стоит рядом с числами (`reason`): машинной
    выписки в лоте может не быть вовсе — у Росэлторга выписки лотовой
    документации приходят печатными PDF (13.09.2026: пять живых КРТ-лотов, 32
    PDF и ни одного XML). «Владельцев нет» и «читать было нечего» на экране
    неразличимы, пока причина не написана.
    """
    egrn = lot.raw.get("egrn")
    if not egrn:
        return None
    return egrn_view(egrn)


def egrn_view(egrn: dict) -> dict:
    """Блок выписок → свод. Один свод на лот и на присланный руками архив.

    Зип с выписками приходит и загрузчиком, и рукой человека, и свод у них
    обязан быть один: два сборщика на один вопрос однажды ответят про одну
    площадку разное, и обе картинки будут выглядеть верными.
    """
    records = egrn.get("records") or []
    owners: dict[str, dict] = {}
    without = 0
    withheld = 0
    for record in records:
        state = egrn_extracts.owner_state(record)
        if state == "withheld":
            # Право зарегистрировано, а имени в этом виде выписки нет. Считать
            # это «правообладатель не назван реестром» нельзя: лечится оно своим
            # запросом в ЕГРН, а не перечитыванием того же файла.
            withheld += 1
            continue
        owner = egrn_extracts.owner_of(record)
        if state != "named" or not owner or not owner.get("name"):
            without += 1
            continue
        row = owners.setdefault(owner["key"], {
            "name": owner.get("name") or "", "inn": owner.get("inn") or "",
            "ogrn": owner.get("ogrn") or "", "kind": owner.get("kind") or "",
            "objects": 0, "area_sqm": 0.0,
        })
        row["objects"] += 1
        row["area_sqm"] += float(record.get("area_sqm") or 0)
    documents = egrn.get("documents") or []
    refused = [{"document": item.get("document") or "",
                "url": item.get("url") or "",
                "reason": item.get("error") or "",
                "kind": item.get("kind") or ""}
               for item in documents if item.get("error")]
    answered = [item for item in documents if not item.get("error")]
    companions = [companion for item in answered
                  for companion in (item.get("companions") or [])]
    print_forms = sum(1 for companion in companions
                      if companion.get("kind") == "print_form")
    # Чем прочитаны сами записи: печатная форма отвечает не на все вопросы
    # машинной, и «владельцев нет» при четырнадцати печатных формах значит
    # другое, чем при четырнадцати машинных выписках.
    from_print = sum(1 for record in records
                     if record.get("source") == "print_form")
    scanned = sum(1 for record in records if record.get("text_source") == "ocr")
    unread = sum(len(item.get("unread") or []) for item in answered)
    rows = sorted(owners.values(), key=lambda row: (-row["objects"], row["name"]))
    return {
        "documents": len(documents),
        "answered": len(answered),
        "refused": refused,
        "records": len(records),
        "lands": egrn.get("lands", 0),
        "builds": egrn.get("builds", 0),
        "owners": rows,
        "without_registered_owner": without,
        "holders_withheld": withheld,
        "from_print_form": from_print,
        "recognised": scanned,
        "unread": unread,
        "companions": len(companions),
        "print_forms": print_forms,
        "reason": _egrn_reason(len(documents), len(answered), len(records),
                               len(rows), without, withheld, unread),
    }


def _egrn_reason(documents: int, answered: int, records: int, owners: int,
                 without: int, withheld: int, unread: int) -> str:
    """Почему владельцев не видно. Пустая строка — видно, объяснять нечего.

    Прежняя причина «машинной выписки в лоте нет — приехала только печатная
    форма, а разбор написан по XML» СНЯТА: печатная форма читается с 0.23.41.
    Оговорка «мы этого не читаем» устаревает молча и продолжает читаться как
    правда — это уже стоило нам двух неверных строк на экране.
    """
    if owners:
        return ""
    if answered == 0:
        return (f"площадка не отдала ни одного вложения с выписками "
                f"(спросили {documents})")
    if records == 0 and unread:
        return f"выписки не прочитаны: {unread}"
    if records == 0:
        return "во вложении нет выписок"
    parts = []
    if withheld:
        parts.append(
            f"у {withheld} объект(ов) право зарегистрировано, а имени "
            "правообладателя выписка об объекте недвижимости не раскрывает — "
            "нужен свой запрос в ЕГРН")
    if without:
        parts.append(f"у {without} объект(ов) право собственности не "
                     "зарегистрировано — так сказано в выписках")
    return "; ".join(parts)


def _norm(value: str | None) -> str:
    return " ".join((value or "").lower().split())


def _dedupe_program(items):
    out = []
    seen: set[tuple] = set()
    for item in items:
        key = (item.category, item.area_sqm, item.quantity, _norm(item.source_text))
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def _dedupe_obligations(items):
    out = []
    seen: set[tuple] = set()
    for item in items:
        key = (item.category, item.quantity, item.unit, _norm(item.source_text))
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out
