"""Публичный реестр нормативной базы DevelopAid.

GET  /normatives           публичная страница;
GET  /api/normatives       данные реестра;
POST /api/normatives/check техническая проверка источников, только для
                           существующего администратора DevelopAid.

Важно: HTTP-проверка источника не подтверждает юридическую актуальность
редакции. Она только фиксирует доступность и изменение содержимого; после
изменения карточка требует содержательной сверки.
"""
from __future__ import annotations

import hashlib
import html
import json
import os
import re
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse

_ROOT = Path(__file__).resolve().parent
_REGISTRY_PATH = _ROOT / "data" / "normatives" / "registry.json"
_STATE_PATH = Path(
    os.getenv("NORMATIVES_STATE_FILE", "").strip()
    or (_ROOT / "data" / "normatives" / "check_state.json")
)
_STATE_LOCK = threading.RLock()
_HEADERS = {"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _load_registry() -> list[dict[str, Any]]:
    raw = json.loads(_REGISTRY_PATH.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise RuntimeError("data/normatives/registry.json должен содержать список")
    return [row for row in raw if isinstance(row, dict)]


def _load_state() -> dict[str, Any]:
    with _STATE_LOCK:
        try:
            raw = json.loads(_STATE_PATH.read_text(encoding="utf-8"))
            return raw if isinstance(raw, dict) else {}
        except Exception:
            return {}


def _save_state(state: dict[str, Any]) -> None:
    with _STATE_LOCK:
        _STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = _STATE_PATH.with_suffix(_STATE_PATH.suffix + ".tmp")
        tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(_STATE_PATH)


def _is_admin(request: Request, core: Any) -> bool:
    """Используем единую авторизацию DevelopAid, второй секрет не заводим.

    Гейт движка принимает ДВЕ СТРОКИ — сессию и ключ, — а сюда передавался
    целиком `Request`: он молча вставал на место сессии, ключ до проверки не
    доезжал вовсе, и `TypeError`, ради которого стоял запасной путь, не
    возникал никогда. Значит владелец не опознавался НИ РАЗУ: кнопка проверки
    источников не показывалась никому, а `POST /api/normatives/check` отвечал
    403 всем и всегда. Ошибка того же рода, что «пустой параметр в `bool`»:
    снаружи кнопка выглядит существующей, а нажать её нельзя.
    """
    checker = getattr(core, "_is_admin_request", None)
    if not callable(checker):
        return False
    params = getattr(request, "query_params", {}) or {}
    cookies = getattr(request, "cookies", {}) or {}
    session = str(params.get("session") or cookies.get("developaid_session") or "")
    key = str(params.get("key") or cookies.get("developaid_admin_key") or "")
    try:
        return bool(checker(session, key))
    except Exception:
        return False


def _fmt_date(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return "—"
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).strftime("%d.%m.%Y")
    except ValueError:
        return text


def _status_label(status: str) -> tuple[str, str]:
    """Наш внутренний контур: очередь сверки редакций. Виден администратору."""
    return {
        "verified": ("Актуальность сверена", "ok"),
        "verified_in_engine_source_pack": ("Подтверждено source pack движка", "ok"),
        "review_required": ("Требует ревизии", "warn"),
        "manual_source_required": ("Нужен первичный источник", "warn"),
    }.get(status, (status or "Статус не задан", "muted"))


# Что показывать ЧИТАТЕЛЮ. «Требует ревизии» — отметка НАША: мы не сверили
# консолидированную редакцию. Человеку она говорит «половине нашей базы не
# верьте», при том что расчёт на этих нормах уже идёт (владелец, 07.09.2026:
# «Зачем пользователю видеть что источник требует проверки»). Читателя касается
# другое: какая редакция учтена и не изменился ли документ у публикатора —
# и то и другое приходит от ИСТОЧНИКА, а не из нашей очереди.
_READER_SOURCE_NEWS = {
    "changed": ("Источник изменился — редакция уточняется", "warn"),
    "unreachable": ("Источник сейчас не отвечает", "muted"),
    "repealed": ("В источниках: документ утратил силу", "bad"),
    "amended": ("В источниках: вышла новая редакция", "warn"),
}


# Номер акта в том виде, в каком его печатают: «1080-ПП», «774-ПП», «713/30»,
# «214-ФЗ», «ДИПП-ПР-34/20».
_ACT_NUMBER_RE = re.compile(r"\b\d+[-/][0-9A-Za-zА-Яа-яЁё]+", re.I)


def accounted_numbers(entry: dict[str, Any]) -> set[str]:
    """Редакции, которые в реестре УЖЕ учтены, — номерами.

    Нужны затем, чтобы находка не светилась вечно. Поиск будет приносить одну и
    ту же публикацию каждую неделю и после того, как мы её разобрали: «вышла
    новая редакция» на карточке 713/30 стояло бы всегда, а постоянная приписка
    перестаёт читаться — и настоящую следующую поправку под ней уже не увидеть.
    """
    parts = [str(entry.get("latest_amendment") or "")]
    parts += [str(x) for x in (entry.get("amendment_history") or [])]
    # Цепочка — это «какие поправки существуют», и учтённой делает не наличие
    # акта в ряду, а разбор его содержания: пока он не разобран, находка о нём
    # остаётся новостью. Читать надо сам ряд, а не второй список рядом с ним.
    for step in chain_steps(entry):
        if str(step.get("status") or "").startswith("разобран"):
            parts.append(str(step.get("number") or ""))
    return {match.group(0).lower() for match in _ACT_NUMBER_RE.finditer(" ".join(parts))}


def chain_steps(entry: dict[str, Any]) -> list[dict[str, Any]]:
    """Ряд поправок к акту — так, как его объявил сам акт."""
    steps = entry.get("amendment_chain")
    return [s for s in steps if isinstance(s, dict)] if isinstance(steps, list) else []


def chain_counts(entry: dict[str, Any]) -> dict[str, int]:
    """Сколько поправок в ряду, сколько у нас файлом и сколько не получено.

    Число молчания здесь такое же обязательное, как у сторожа: «29 поправок»
    без «8 не получено» читается как полная библиотека.
    """
    steps = chain_steps(entry)
    return {
        "all": len(steps),
        "in_library": sum(1 for s in steps if s.get("file")),
        "studied": sum(1 for s in steps if str(s.get("status") or "").startswith("разобран")),
        "missing": sum(1 for s in steps if str(s.get("status") or "") == "не получен"),
    }


def own_number(entry: dict[str, Any]) -> str:
    """Номер самого акта — первый «№ …» его заголовка."""
    match = re.search(r"№\s*([0-9][^\s,«»]*)", str(entry.get("title") or ""))
    return match.group(1).strip().lower().rstrip(".,;") if match else ""


def signal_is_accounted(signal: dict[str, Any], entry: dict[str, Any]) -> bool:
    """Названа ли в находке только та редакция, которую мы уже учли.

    Номер в цитате есть и он наш учтённый — новостью это быть перестало.
    Номера в цитате нет вовсе — решать нечем, и находка остаётся новостью:
    «не поняли» безопаснее выдавать за новость, чем за учтённое.
    """
    known = accounted_numbers(entry)
    if not known:
        return False
    numbers = {m.group(0).lower() for m in _ACT_NUMBER_RE.finditer(str(signal.get("quote") or ""))}
    # Собственный номер базового акта ничего не говорит о редакции: он стоит и
    # в поправке, и в самом акте. Берётся он из заголовка, а не из watch_terms:
    # там рядом лежат номера УЧТЁННЫХ поправок (мы сами их туда кладём, чтобы
    # проба узнавала страницу публикатора), и вычитание всего списка глушило бы
    # ровно те находки, ради которых список и заведён.
    own = own_number(entry)
    if own:
        numbers -= {own}
    return bool(numbers) and numbers.issubset(known)


def source_signals(check: dict[str, Any], entry: dict[str, Any] | None = None,
                   ) -> list[dict[str, Any]]:
    """Находки открытых источников о судьбе акта. Отвечает ОДНО место.

    Читателей у находки стало трое — подпись карточки, сама карточка и
    счётчик сторожа, — и «где они лежат» должно быть объявлено один раз:
    перечисление в трёх местах расходится молча.
    """
    sources = check.get("sources") if isinstance(check, dict) else None
    if not isinstance(sources, dict):
        return []
    signals = [item for item in (sources.get("signals") or []) if isinstance(item, dict)]
    if entry is None:
        return signals
    return [item for item in signals if not signal_is_accounted(item, entry)]


def _reader_label(entry: dict[str, Any], check: dict[str, Any]) -> tuple[str, str]:
    """Новость от источника — или учтённая редакция. Наша очередь молчит.

    Находка открытых источников сильнее отпечатка ссылки: «страницу
    переписали» — это про страницу, а «акт утратил силу» — про сам акт.
    Прежде ключи `repealed` и `amended` в этой карте были МЁРТВЫМИ: сюда
    приходил результат пробы, а она таких значений не возвращает вовсе, и
    находки поиска не показывались нигде, кроме очереди боту. Ровно это и
    значило «проверки не выкидывают изменения».
    """
    signals = source_signals(check, entry)
    if signals:
        worst = "repealed" if any(s.get("kind") == "repealed" for s in signals) else "amended"
        return _READER_SOURCE_NEWS[worst]
    check_result = str(check.get("result") or "") if isinstance(check, dict) else ""
    if check_result in _READER_SOURCE_NEWS:
        return _READER_SOURCE_NEWS[check_result]
    stamp = _fmt_date(entry.get("current_as_of"))
    return (f"Учтено на {stamp}" if stamp and stamp != "—" else "Учтено", "ok")


def _decode(body: bytes, content_type: str) -> tuple[str, str]:
    """Текст читается той кодировкой, которую объявил сервер.

    Страницы правовых порталов приходят в windows-1251, а разбор читал их как
    utf-8 с `errors="ignore"`: кириллица при этом пропадает целиком, и ни одно
    русское слово документа не находится НИКОГДА. На проде 09.09.2026 это дало
    «своих слов не найдено» у источников, где они есть, а следом — ложное
    «содержимое изменилось». Чем прочитано — часть ответа, поэтому имя
    кодировки уезжает в запись проверки.
    """
    declared = ""
    match = re.search(r"charset=\s*\"?([\w\-]+)", content_type or "")
    if match:
        declared = match.group(1).strip().lower()
    for name in (declared, "utf-8", "cp1251"):
        if not name:
            continue
        try:
            return body.decode(name), name
        except (UnicodeDecodeError, LookupError):
            continue
    # Ни одна кодировка не подошла целиком — читаем как есть и говорим об этом:
    # молча испорченный текст неотличим от текста, где слов и правда нет.
    return body.decode("utf-8", errors="ignore"), "utf-8 с потерями"


# --- опознание документа по его собственному имени ---------------------------
#
# Набор обрывков (`watch_terms`) опознаёт документ ровно до первого падежа:
# реестр называет акт «Об утверждении НОРМАТИВОВ градостроительного
# проектирования Московской области», а сам акт и все, кто о нём пишет, —
# «нормативЫ». Точное совпадение строки не находит такое имя НИКОГДА, и на
# проде 19.09.2026 это дало пять источников из пятнадцати с «контрольные
# маркеры документа не найдены» на страницах, где имя акта стоит первой
# строкой. То же в обратную сторону: поправку к акту ищут по его номеру, а
# акт, изложивший абзац в новой редакции, номера базового акта в заголовке не
# называет — он называет ИМЯ («О внесении изменений в нормативы
# градостроительного проектирования Московской области», 1080-ПП от
# 01.09.2026, и мы его не увидели).
#
# Отсюда сравнение по корням. Стемминг здесь грубый и намеренно свой: снимаем
# окончание, а не разбираем морфологию — библиотеки в образе нет, а вопрос
# стоит ровно один: «это то же слово в другом падеже?».
_NAME_ENDINGS = (
    "ого", "его", "ому", "ему", "ыми", "ими", "ами", "иями", "ями",
    "ях", "ах", "ям", "ам", "ов", "ев", "ей", "ой", "ый", "ий", "ая", "яя",
    "ое", "ее", "ые", "ие", "ую", "юю", "ом", "ем", "ья", "ью", "ия", "ии",
    "а", "я", "ы", "и", "о", "е", "у", "ю", "ь", "й",
)
# Служебные слова в имени не опознают ничего: «о», «в», «и» стоят в любом
# тексте, и пускать их в сравнение значит считать совпадением предлог.
_NAME_STOP = {
    "о", "об", "обо", "и", "в", "во", "на", "по", "для", "при", "с", "со",
    "из", "к", "не", "или", "от", "до", "за", "том", "числе", "иных", "иные",
    "а", "также", "город", "города", "городе", "прочие",
}
# Сколько имени должно стоять ПОДРЯД. Два разных вопроса — два порога, и это не
# вкус: 945-ПП Москвы зовётся «Об утверждении нормативов градостроительного
# проектирования города Москвы в области транспорта…», и с 713/30 области у него
# совпадают пять слов из шести как МНОЖЕСТВО. Подряд — четыре, потому что на
# пятом стоит «Москвы» против «Московской». Поэтому находка о судьбе акта
# требует непрерывного отрезка почти во всё имя, а опознание страницы, которую
# мы сами и указали, — меньшего.
NAME_SIGNAL_RUN_SHARE = 0.8
NAME_RECOGNISE_RUN_SHARE = 0.6
_WORD_RE = re.compile(r"[а-яёa-z0-9][а-яёa-z0-9./\-]*", re.I)


def _stem(word: str) -> str:
    """Слово без окончания. Короткое слово не трогаем: там снимать нечего."""
    low = word.lower().replace("ё", "е")
    if any(ch.isdigit() for ch in low) or len(low) < 5:
        return low
    for ending in _NAME_ENDINGS:
        if low.endswith(ending) and len(low) - len(ending) >= 4:
            return low[: -len(ending)]
    return low


def _stems(text: str) -> list[str]:
    """Значимые корни текста по порядку.

    Отсев служебных слов обязан быть ОДИН на имя и на текст: сняв «города» из
    имени и оставив его в тексте, мы разрываем отрезок ровно там, где он
    совпадает, и собственное имя акта не находится в собственном заголовке.
    """
    out: list[str] = []
    for word in _WORD_RE.findall(str(text or "")):
        low = word.lower().replace("ё", "е")
        if low in _NAME_STOP or len(low) < 4:
            continue
        out.append(_stem(low))
    return out


def act_name(entry: dict[str, Any]) -> str:
    """Собственное имя акта — то, что в заголовке стоит в кавычках.

    Берётся из реестра, а не заводится полем: имя у акта уже есть, и второй
    его экземпляр разошёлся бы с первым молча.
    """
    match = re.search(r"«([^»]+)»", str(entry.get("title") or ""))
    return match.group(1).strip() if match else ""


def name_stems(entry: dict[str, Any]) -> list[str]:
    """Значимые слова имени по порядку — порядок здесь и есть улика."""
    return _stems(act_name(entry))


def name_run(text: str, words: list[str]) -> int:
    """Длина самого длинного отрезка имени, стоящего в тексте ПОДРЯД.

    Считаем по строке корней: окно имени либо стоит в тексте, либо нет, и
    поиск подстроки отвечает на это быстрее, чем обход словами.
    """
    if not words:
        return 0
    haystack = " " + " ".join(_stems(text)) + " "
    for size in range(len(words), 0, -1):
        for start in range(0, len(words) - size + 1):
            needle = " " + " ".join(words[start:start + size]) + " "
            if needle in haystack:
                return size
    return 0


def name_recognised(text: str, entry: dict[str, Any], share: float) -> bool:
    """Назван ли в тексте сам акт. Имени нет в реестре — ответа нет, а не «да»."""
    words = name_stems(entry)
    if not words:
        return False
    need = max(1, int(len(words) * share + 0.999))
    return name_run(text, words) >= need


def _probe(entry: dict[str, Any], previous: dict[str, Any]) -> dict[str, Any]:
    url = str(entry.get("source_url") or "").strip()
    checked_at = _now_iso()
    if not url:
        return {"checked_at": checked_at, "result": "no_source", "message": "Источник не задан"}

    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "DevelopAid-Normatives/1.1 (+https://developaid.ru/normatives)",
            "Accept": "text/html,application/pdf,application/json;q=0.9,*/*;q=0.8",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as response:
            body = response.read(2_500_000)
            http_status = int(getattr(response, "status", 200) or 200)
            content_type = str(response.headers.get("Content-Type") or "").lower()
            last_modified = str(response.headers.get("Last-Modified") or "").strip()
    except urllib.error.HTTPError as exc:
        return {
            "checked_at": checked_at,
            "result": "unreachable",
            "http_status": int(exc.code),
            "message": f"Источник ответил HTTP {exc.code}",
        }
    except Exception as exc:
        return {
            "checked_at": checked_at,
            "result": "unreachable",
            "message": f"Источник недоступен: {type(exc).__name__}",
        }

    digest = hashlib.sha256(body).hexdigest()
    old_digest = str(previous.get("sha256") or "")
    # Отпечаток сравнивается с отпечатком ТОЙ ЖЕ страницы. Ссылку в реестре
    # меняем мы сами — когда акт переиздан, источником становится публикация
    # новой поправки, — и без этой оговорки наша собственная правка реестра
    # объявлялась бы «содержимое источника изменилось» и уезжала сообщением в
    # чат. Прежнего адреса в записи не было вовсе, поэтому отличить свою правку
    # от чужой было нечем.
    old_url = str(previous.get("url") or "")
    same_source = (not old_url) or old_url == url
    changed = bool(old_digest and same_source and old_digest != digest)
    terms = [str(x).strip() for x in entry.get("watch_terms", []) if str(x).strip()]
    found: list[str] = []
    missing: list[str] = []
    is_text = any(kind in content_type for kind in ("text/", "json", "xml"))
    charset = ""
    named = False
    words = name_stems(entry)
    if is_text and (terms or words):
        decoded, charset = _decode(body, content_type)
        low = decoded.lower()
        for term in terms:
            (found if term.lower() in low else missing).append(term)
        # Документ опознаёт и собственное имя — оно на странице стоит в том
        # падеже, который ей нужен, а обрывок реестра в своём. Порог здесь
        # мягче, чем у находки о судьбе акта, и это безопасно: страницу мы
        # указали сами, чужой сюда не приходит.
        named = name_recognised(decoded, entry, NAME_RECOGNISE_RUN_SHARE)

    # Порядок ответов здесь и есть утверждение. «Содержимое изменилось» — это
    # заявление О ДОКУМЕНТЕ, и делать его, не найдя в теле ни одного его
    # собственного слова, нельзя: чаще это значит, что скачана не та страница —
    # обёртка, редирект или заглушка. Пока документ не опознан, честный ответ
    # «нужна ревизия», а не «сменилась редакция». Прежде проверка маркеров
    # стояла в `elif` ПОСЛЕ `changed` и до неё не доходило вовсе: на проде
    # 09.09.2026 шесть источников из семи объявили смену редакции, не найдя у
    # себя ни одного своего слова. Хуже того, переход объявляется один раз
    # (`_changes_between`), и застрявший в ложном «изменилось» источник
    # настоящую смену редакции уже не объявит никогда.
    unrecognised = bool(is_text and (terms or words) and not found and not named)
    if unrecognised:
        result = "review_required"
        message = ("Источник доступен, но ни контрольные маркеры, ни имя документа "
                   "в теле не найдены"
                   + (" — содержимое изменилось, и это похоже не на новую редакцию, "
                      "а на другую страницу" if changed else ""))
    elif changed:
        result = "changed"
        message = "Содержимое источника изменилось — нужна ревизия редакции"
    else:
        result = "ok"
        message = ("Источник доступен; содержимое не изменилось с предыдущей проверкой"
                   if old_digest
                   else "Источник доступен; зафиксирован контрольный отпечаток")

    return {
        "checked_at": checked_at,
        "result": result,
        "http_status": http_status,
        "url": url,
        "content_type": content_type,
        "charset": charset,
        "last_modified": last_modified,
        "sha256": digest,
        "changed": changed,
        "found_terms": found,
        "missing_terms": missing,
        # Чем опознан документ: своими обрывками или собственным именем. Без
        # этого «маркеры не найдены, но страница опознана» неотличимо от
        # «опознали по обрывку».
        "found_name": named,
        "message": message,
    }


def _merged_registry() -> list[dict[str, Any]]:
    checks = _load_state().get("checks")
    checks = checks if isinstance(checks, dict) else {}
    rows: list[dict[str, Any]] = []
    for item in _load_registry():
        row = dict(item)
        row["check"] = checks.get(str(item.get("id") or ""), {})
        rows.append(row)
    return rows


_ANNOUNCE_PATH = Path(
    os.getenv("NORMATIVES_ANNOUNCE_FILE", "").strip()
    or (_ROOT / "data" / "normatives" / "announcements.jsonl")
)
_ANNOUNCE_LOCK = threading.Lock()

# Результаты, о которых стоит будить человека. «Источник не задан» сюда не
# входит: это наш пробел, он и так виден в справочнике, а сообщение о нём
# приходило бы после каждой проверки и перестало бы читаться.
_ANNOUNCE_RESULTS = {"changed", "review_required", "unreachable"}


def _queue_announcements(changes: list[dict[str, Any]]) -> None:
    """Сложить находки в очередь для бота.

    Отправляет не ядро: до api.telegram.org достаёт только хост с вебхуком.
    Ядро копит, он забирает — тот же путь, что у знакомств и новинок каталога.
    """
    if not changes:
        return
    with _ANNOUNCE_LOCK:
        try:
            _ANNOUNCE_PATH.parent.mkdir(parents=True, exist_ok=True)
            with _ANNOUNCE_PATH.open("a", encoding="utf-8") as handle:
                for item in changes:
                    handle.write(json.dumps(item, ensure_ascii=False) + "\n")
        except Exception:
            pass          # рассылка — удобство: молчание лучше падения проверки


def take_announcements() -> list[dict[str, Any]]:
    """Забрать очередь и очистить её. Забирает только один: файл переименовывается."""
    with _ANNOUNCE_LOCK:
        path = _ANNOUNCE_PATH
        if not path.exists():
            return []
        taken = path.with_suffix(path.suffix + ".taken")
        try:
            path.replace(taken)
        except Exception:
            return []
    records: list[dict[str, Any]] = []
    try:
        for line in taken.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                item = json.loads(line)
            except Exception:
                continue
            if isinstance(item, dict):
                records.append(item)
        taken.unlink()
    except Exception:
        pass
    return records


def queued_count() -> int:
    """Сколько находок ждёт бота. Очередь читается, а не изымается.

    Забрать её может только один — файл переименовывается, — и второй
    читатель унёс бы уведомление ради ответа на вопрос, дошло ли уведомление.
    """
    try:
        if not _ANNOUNCE_PATH.exists():
            return 0
        return sum(1 for line in _ANNOUNCE_PATH.read_text(encoding="utf-8").splitlines()
                   if line.strip())
    except Exception:
        return 0


def watch_state() -> dict[str, Any]:
    """Состояние сторожа нормативной базы — числом, а не молчанием.

    Снаружи «в базе ничего не менялось», «сторож выключен», «проверка ни разу
    не заходила» и «очередь копится, а забрать её некому» — одно и то же
    молчание. Ровно этим вопросом уже отвечал `/auctions/krt/watch`; здесь та
    же половина ответа, только про нормативы. Пара к нему — `/normatives/delivery`
    на хосте с ботом: очередь копится тут, а забирают её там.
    """
    state = _load_state()
    checks = state.get("checks")
    checks = checks if isinstance(checks, dict) else {}
    entries = {str(row.get("id") or ""): row for row in _load_registry()}
    results: dict[str, int] = {}
    signals = 0
    asked = 0
    for item_id, item in checks.items():
        if isinstance(item, dict):
            key = str(item.get("result") or "unknown")
            results[key] = results.get(key, 0) + 1
            sources = item.get("sources")
            if isinstance(sources, dict):
                if sources.get("asked"):
                    asked += 1
                # Считаем то же, что показывает карточка: учтённая редакция в
                # счётчике находок — это находка, которой на экране нет.
                if source_signals(item, entries.get(str(item_id) or "")):
                    signals += 1
    hours = max(1.0, float(os.getenv("NORMATIVES_WATCH_HOURS", "24") or 24))
    search_hours = max(hours, float(os.getenv("NORMATIVES_SEARCH_HOURS", "168") or 168))
    return {
        "enabled": os.getenv("NORMATIVES_WATCH", "1").strip() not in {"0", "false", "no"},
        "entries": len(_load_registry()),
        "checked": len(checks),
        "results": results,
        "last_run_at": state.get("last_run_at") or "",
        "last_search_at": state.get("last_search_at") or "",
        "link_period_hours": hours,
        "search_period_hours": search_hours,
        "link_check_due": _watch_due(hours),
        "search_due": _watch_due(search_hours, key="last_search_at"),
        # Платный поиск отвечает на «отменён ли акт»: без ключа он не идёт
        # вовсе, и тогда отмена до нас не доедет никаким путём.
        "search_available": _search_client() is not None,
        # Сколько актов спрошено у открытых источников и у скольких есть
        # находка о судьбе акта. Ноль находок при нуле спрошенных и ноль
        # находок при пятнадцати спрошенных — разные ответы, а снаружи оба
        # выглядели молчанием.
        "searched": asked,
        "signals": signals,
        "queued": queued_count(),
    }


def _changes_between(before: dict[str, Any], after: dict[str, Any],
                     entries: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """Что изменилось с прошлой проверки — построчно и с причиной.

    Сообщается ПЕРЕХОД, а не состояние: источник, который лежит третью неделю,
    новостью не является, и повторять о нём каждую проверку значит приучить
    не читать эти сообщения вовсе.
    """
    changes: list[dict[str, Any]] = []
    for entry_id, check in after.items():
        entry = entries.get(entry_id) or {}
        # Находка открытых источников — новость сама по себе, даже когда ссылка
        # жива и не переписана: акт отменяют, не трогая наш PDF.
        signals = source_signals(check or {}, entry)
        was_signals = source_signals(before.get(entry_id) or {}, entry)
        if signals and len(signals) != len(was_signals):
            first = signals[0]
            changes.append({
                "id": entry_id,
                "scope": str(entry.get("scope") or ""),
                "short_name": str(entry.get("short_name") or entry.get("title") or entry_id),
                "result": "repealed" if first["kind"] == "repealed" else "amended",
                "was": "",
                "message": first["quote"],
                "source_url": first.get("url") or str(entry.get("source_url") or ""),
                "checked_at": str((check or {}).get("checked_at") or ""),
            })
        result = str((check or {}).get("result") or "")
        if result not in _ANNOUNCE_RESULTS:
            continue
        was = str(((before.get(entry_id) or {}) or {}).get("result") or "")
        if was == result:
            continue
        entry = entries.get(entry_id) or {}
        changes.append({
            "id": entry_id,
            "scope": str(entry.get("scope") or ""),
            "short_name": str(entry.get("short_name") or entry.get("title") or entry_id),
            "result": result,
            "was": was,
            "message": str((check or {}).get("message") or ""),
            "source_url": str(entry.get("source_url") or ""),
            "checked_at": str((check or {}).get("checked_at") or ""),
        })
    return changes


# --- что о документе пишут в открытых источниках ----------------------------
#
# Отпечаток страницы отвечает на «страницу по ссылке переписали?» — и это НЕ тот
# вопрос (владелец, 06.09.2026: «искать обновление надо не так»). Страница
# правовой системы меняется от баннера и счётчика, а акт может быть отменён при
# байт-в-байт том же PDF: у файла в библиотеке отпечаток не изменится НИКОГДА —
# то есть именно там, где проверка нужнее всего, она молчит по построению.
#
# Спрашивать надо по ИМЕНИ документа: что о нём пишут — «утратил силу»,
# «недействующая редакция», «внесены изменения». Ответ поисковика не решение, а
# находка: она несёт цитату и ссылку, а реестр правит человек.

_REPEAL_MARKERS = (
    "утратил силу", "утратило силу", "утратила силу", "признан утратившим силу",
    "признано утратившим силу", "признании утратившим силу",
    "недействующая редакция", "не действует",
    "отменено", "отменён", "прекратил действие",
)
# Акт правят СВОИМИ словами, и главного из них здесь не было. Поправку город и
# область называют «О внесении изменений в …» — ровно так озаглавлено 1080-ПП
# от 01.09.2026, — а набор знал только «внесены изменения» и «в редакции от».
# Поиск по своему слову вместо слова источника даёт честный ноль на полном
# источнике: восемнадцать дней поправка к РНГП МО лежала опубликованной, и
# недельный поиск её не опознал.
#
# «признать утратившим силу» в повелительной форме в набор НЕ идёт намеренно:
# так отменяют абзац внутри поправки («абзац тринадцатый признать утратившим
# силу»), а не сам акт, и ложная тревога «акт отменён» — худшая из возможных.
_AMEND_MARKERS = ("внесены изменения", "внесено изменение", "в редакции от",
                  "изложен в новой редакции", "новая редакция",
                  "внесении изменений", "внесении изменения",
                  "вносятся изменения")


def watch_query(entry: dict[str, Any]) -> str:
    """Запрос строится из реквизитов самого акта, а не из его ссылки.

    Ссылка отвечает за «где лежит», а спрашиваем мы «что с ним стало».
    """
    name = str(entry.get("short_name") or "").split("—")[0].strip()
    if not name:
        name = str(entry.get("title") or "")[:60]
    return f"{name} утратил силу или внесены изменения"


def _sentences(text: str) -> list[str]:
    return [part.strip() for part in re.split(r"(?<=[.!?;])\s+|\n", str(text or "")) if part.strip()]


def _self_named_markers(entry: dict[str, Any], markers: tuple[str, ...]) -> tuple[str, ...]:
    """Маркеры, стоящие в САМОМ имени акта: для него они не улика.

    214-ФЗ зовётся «Об участии в долевом строительстве … и о внесении
    изменений в некоторые законодательные акты Российской Федерации», а
    1745-ПП области — «О внесении изменений в Порядок…». Процитируй заголовок
    — и «внесении изменений» найдётся в нём всегда, то есть находка была бы
    вечной и пустой. Прочие маркеры у таких актов работают: отмену их имя не
    называет.
    """
    name = act_name(entry).lower()
    return tuple(marker for marker in markers if name and marker in name)


def find_repeal_signals(entry: dict[str, Any], docs: list[dict[str, Any]],
                        ) -> list[dict[str, Any]]:
    """Находки о судьбе акта — только там, где рядом назван САМ акт.

    Иначе сниппет про соседний акт заберёт находку себе: ровно этим у нас уже
    отдавались чужие адреса и чужие застройщики в модуле рынка. Якорь обязан
    стоять в ТОМ ЖЕ предложении, что и слова об отмене: «отменено» через абзац
    от нашего номера не значит ничего.

    Якорь бывает двух видов, и второго не хватало. Номер — жёсткий, но акт,
    переиздающий абзац, номера базового акта в заголовке не называет: 1080-ПП
    озаглавлен «О внесении изменений в нормативы градостроительного
    проектирования Московской области», и по номеру «713/30» его не поймать
    ничем. Второй якорь — собственное ИМЯ акта, сверенное по корням и
    непрерывным отрезком почти во всё имя: у 945-ПП Москвы с областным 713/30
    совпадают пять слов из шести как множество и только четыре подряд, и
    порог отрезка эту подмену отсекает.
    """
    anchors = [str(term).strip().lower() for term in (entry.get("watch_terms") or [])
               if str(term).strip()]
    anchors = [a for a in anchors if any(ch.isdigit() for ch in a)]
    words = name_stems(entry)
    if not anchors and not words:
        return []
    repeal = tuple(m for m in _REPEAL_MARKERS
                   if m not in _self_named_markers(entry, _REPEAL_MARKERS))
    amend = tuple(m for m in _AMEND_MARKERS
                  if m not in _self_named_markers(entry, _AMEND_MARKERS))
    found: list[dict[str, Any]] = []
    for doc in docs or []:
        text = " ".join(str(doc.get(key) or "") for key in ("title", "snippet", "text"))
        for sentence in _sentences(text):
            low = sentence.lower()
            by_number = any(anchor in low for anchor in anchors)
            anchored_by = ""
            if by_number:
                anchored_by = "номер"
            elif words and name_recognised(sentence, entry, NAME_SIGNAL_RUN_SHARE):
                anchored_by = "имя"
            if not anchored_by:
                continue
            kind = ""
            if any(marker in low for marker in repeal):
                kind = "repealed"
            elif any(marker in low for marker in amend):
                kind = "amended"
            if not kind:
                continue
            found.append({
                "kind": kind,
                # Чем найдено — часть ответа: находка по имени слабее находки
                # по номеру, и читатель обязан видеть, какая из двух перед ним.
                "anchored_by": anchored_by,
                "quote": sentence[:400],
                "url": str(doc.get("url") or ""),
                "source": str(doc.get("title") or "")[:200],
            })
            break                  # одна находка на документ: цитат хватает одной
    # Отмена важнее правки: если сказано и то и другое, показываем худшее первым.
    found.sort(key=lambda item: 0 if item["kind"] == "repealed" else 1)
    return found[:5]


def _search_client() -> Any:
    """Поиск берётся у движка, а не заводится второй.

    У рыночного модуля он уже есть — с ключом, кэшем и своей ценой. Второй
    клиент значил бы второй счёт за те же запросы и вторую жизнь у настроек.
    """
    try:
        from market_search.yandex_search import YandexSearchClient
    except Exception:                                # noqa: BLE001
        return None
    try:
        client = YandexSearchClient(_ROOT / "data")
    except Exception:                                # noqa: BLE001
        return None
    return client if getattr(client, "configured", False) else None


def _search_signals(entry: dict[str, Any], client: Any) -> dict[str, Any]:
    """Что об акте пишут в открытых источниках.

    Поиск платный, поэтому запрос один на акт и ходит он раз в неделю, а не
    вместе с каждой проверкой ссылки. Пустой ответ — это «не нашли», а не
    «действует»: разницу называем вслух, иначе молчание читается как
    подтверждение актуальности.
    """
    if client is None:
        return {"asked": False, "reason": "поиск не настроен"}
    query = watch_query(entry)
    try:
        docs = client.search(query, groups_on_page=10)
    except Exception as error:                       # noqa: BLE001
        return {"asked": False, "query": query, "reason": f"поиск не ответил: {error}"}
    rows = []
    for doc in docs or []:
        rows.append({"title": getattr(doc, "title", "") or "",
                     "snippet": getattr(doc, "snippet", "") or "",
                     "url": getattr(doc, "url", "") or ""})
    signals = find_repeal_signals(entry, rows)
    # Немой отказ чинить нечем. «Спросили, принесено десять, наш акт не назван
    # ни в одном» и «поиск не ответил» снаружи выглядят одним нулём находок, а
    # чинятся по-разному: первое — вопрос к запросу, второе — к поиску. Поэтому
    # заголовки того, что принесли, лежат рядом с числом; это публичная выдача,
    # секретов в ней нет.
    return {"asked": True, "asked_at": _now_iso(), "query": query,
            "checked": len(rows), "signals": signals,
            "seen": [{"title": row["title"][:160], "url": row["url"]} for row in rows[:5]]}


def _run_check(search: bool = False) -> dict[str, Any]:
    old = _load_state().get("checks")
    old = old if isinstance(old, dict) else {}
    checks: dict[str, Any] = {}
    entries: dict[str, dict[str, Any]] = {}
    client = _search_client() if search else None
    for entry in _load_registry():
        entry_id = str(entry.get("id") or "")
        entries[entry_id] = entry
        was = old.get(entry_id) or {}
        checks[entry_id] = _probe(entry, was)
        if search:
            # Два разных вопроса — два разных ответа рядом: «ссылка жива и не
            # переписана» и «что об акте пишут». Свести их в один результат
            # значит потерять тот, который важнее.
            checks[entry_id]["sources"] = _search_signals(entry, client)
        elif isinstance(was.get("sources"), dict):
            # Ответ платного поиска живёт своим сроком — недельным, — а запись
            # проверки собирается заново каждый день. Пока находки не
            # переносились, ежедневная сверка ссылок ЗАТИРАЛА их через сутки:
            # на проде 19.09.2026 `last_search_at` стоял 14.09, а `sources` не
            # было ни у одного из пятнадцати источников. То есть единственное
            # место, где видно «вышла новая редакция», исчезало само, и
            # доставка объявляла одну и ту же находку заново каждую неделю —
            # сообщается ПЕРЕХОД, а сравнивать было не с чем.
            checks[entry_id]["sources"] = was["sources"]
    state = {"last_run_at": _now_iso(), "checks": checks}
    if search:
        # Отметка платного захода своя: иначе ежедневная проверка ссылки
        # сдвигала бы срок недельного поиска и он не наступал бы никогда.
        state["last_search_at"] = state["last_run_at"]
    else:
        was = str(_load_state().get("last_search_at") or "")
        if was:
            state["last_search_at"] = was
    _save_state(state)
    changes = _changes_between(old, checks, entries)
    _queue_announcements(changes)
    state["changes"] = changes
    return state


def _li(values: Any) -> str:
    return "".join(f"<li>{html.escape(str(value))}</li>" for value in (values or []))


def _card(entry: dict[str, Any], admin: bool = False) -> str:
    check = entry.get("check") if isinstance(entry.get("check"), dict) else {}
    check_result = str(check.get("result") or "")
    label, badge = _reader_label(entry, check)
    # Наша очередь сверки и HTTP-код источника — рабочий контур, а не сведения
    # для читателя. Показываем их тому, кто может по ним что-то сделать.
    admin_badge = ""
    if admin:
        inner_label, inner_badge = _status_label(str(entry.get("status") or ""))
        admin_badge = ('<span class="badge %s">%s</span>'
                       % (inner_badge, html.escape(inner_label)))

    usage = "".join(
        "<li><b>%s</b><span>%s</span></li>"
        % (
            html.escape(str(row.get("module") or "")),
            html.escape(str(row.get("usage") or "")),
        )
        for row in entry.get("engine_usage", [])
        if isinstance(row, dict)
    )
    counts = chain_counts(entry)
    chain_html = ""
    if counts["all"]:
        rows = []
        for step in chain_steps(entry):
            where = (
                "файл в библиотеке" if step.get("file")
                else html.escape(str(step.get("reason") or "файла нет"))
            )
            rows.append(
                "%s № %s — %s · %s"
                % (
                    html.escape(str(step.get("act_date") or "—")),
                    html.escape(str(step.get("number") or "—")),
                    html.escape(str(step.get("status") or "—")),
                    where,
                )
            )
        chain_html = (
            "<details class='history'><summary>Ряд поправок — %d, из них файлом %d,"
            " разобрано %d, не получено %d</summary><ul>%s</ul></details>"
            % (counts["all"], counts["in_library"], counts["studied"],
               counts["missing"], "".join("<li>%s</li>" % r for r in rows))
        )

    history = entry.get("amendment_history") or []
    history_html = ""
    if history:
        history_html = (
            "<details class='history'><summary>Цепочка учтённых изменений — %d"
            "</summary><ul>%s</ul></details>" % (len(history), _li(history))
        )

    # Сообщение пробы и HTTP-код — тоже рабочий контур: читателю «HTTP 200»
    # не говорит ничего, а «источник не отвечает» он узнает из подписи выше.
    check_html = ""
    if admin:
        check_html = (
            "<div class='probe'><span>%s</span><small>Проверено: %s · HTTP %s</small></div>"
            % (
                html.escape(str(check.get("message") or "")),
                html.escape(str(check.get("checked_at") or "—").replace("T", " ")),
                html.escape(str(check.get("http_status") or "—")),
            )
        ) if check else (
            "<div class='probe'><span>Техническая проверка источника "
            "ещё не запускалась.</span></div>"
        )

    # Находка о судьбе акта — новость, и место у неё на карточке, а не только
    # в очереди боту: сообщение отвечает тому, кто не открывал страницу, а
    # страницу открывает тот, кто пришёл за основанием под числом.
    news_html = ""
    all_signals = source_signals(check)
    signals = source_signals(check, entry)
    accounted = [item for item in all_signals if item not in signals]
    if not signals and accounted:
        # Молча выброшенная находка читается как её отсутствие, поэтому она
        # называется — но тоном «это уже учтено», а не тревогой.
        news_html = ("<div class='news calm'><h3>Что об акте пишут в открытых "
                     "источниках</h3><ul><li><b>Названа редакция, которая у нас "
                     "уже учтена</b><span>%s</span></li></ul></div>"
                     % html.escape(str(accounted[0].get("quote") or ""))[:400])
    if signals:
        rows = []
        for item in signals[:2]:
            title = ("В источниках: документ утратил силу"
                     if item.get("kind") == "repealed"
                     else "В источниках: вышла новая редакция")
            link = str(item.get("url") or "")
            # Чем найдено — часть ответа, и сказать это надо по-русски:
            # значение поля («имя», «номер») в строку не подставляется, у него
            # своя форма.
            found_by = {"имя": "по имени акта", "номер": "по номеру акта"}.get(
                str(item.get("anchored_by") or ""), "")
            rows.append(
                "<li><b>%s</b><span>%s</span>%s%s</li>" % (
                    html.escape(title),
                    html.escape(str(item.get("quote") or ""))[:400],
                    (' <em>найдено %s</em>' % html.escape(found_by)) if found_by else "",
                    (' <a href="%s" target="_blank" rel="noopener">источник ↗</a>'
                     % html.escape(link, quote=True)) if link.startswith("http") else "",
                ))
        asked_at = str((check.get("sources") or {}).get("asked_at") or "")
        news_html = (
            "<div class='news'><h3>Что об акте пишут в открытых источниках</h3>"
            "<ul>%s</ul><small>Это находка поиска, а не решение: реестр правит "
            "человек после сверки редакции%s.</small></div>" % (
                "".join(rows),
                (" · спрошено " + html.escape(_fmt_date(asked_at.split("T")[0])))
                if asked_at else "",
            ))

    notes = html.escape(str(entry.get("notes") or ""))
    # Ссылка на несуществующее — такая же ложь, как подпись под чужим числом:
    # `href="#"` выглядит источником и никуда не ведёт. Источник бывает и не
    # адресом (первичный текст акта на руках, PDF в docs/normative), и тогда
    # подпись говорит это словами, а ссылки нет вовсе.
    source_raw = str(entry.get("source_url") or "").strip()
    source_label = html.escape(str(entry.get("source_label") or "Источник"))
    if source_raw:
        source_link = (f'<a href="{html.escape(source_raw, quote=True)}" '
                       f'target="_blank" rel="noopener">{source_label} ↗</a>')
    else:
        source_link = f'<span class="nomuted">{source_label}</span>'
    # Публикация РЕДАКЦИИ и страница САМОГО акта — разные адреса, и второй
    # спросили прямо: «сам 713/30 лежит вообще у нас где-то?» (владелец,
    # 19.09.2026). Публикация поправки заморожена днём выхода и
    # консолидированного текста не содержит; страница акта на портале региона
    # ведёт к нему и к приложениям. Пока ссылка была одна, ответить на «где
    # взять сам акт» карточка не могла.
    act_page = str(entry.get("act_page_url") or "").strip()
    if act_page.startswith("http"):
        act_label = html.escape(str(entry.get("act_page_label") or "Страница акта"))
        source_link += (f' <a href="{html.escape(act_page, quote=True)}" '
                        f'target="_blank" rel="noopener">{act_label} ↗</a>')
    # Тринадцать развёрнутых карточек — стена, которую не читают (владелец,
    # 07.09.2026: «вся информация должна быть свернута и при необходимости
    # только открыта из списка»). Свёрнутая строка отвечает на «что это и на
    # что влияет», раскрытая — на всё остальное. Порог тот же, что у списков
    # карточки КРТ: длинный список сворачивается, и в заголовке стоит суть, а
    # не одно имя, иначе закрытый список читается как отсутствующий.
    affects = [str(x) for x in (entry.get('affects') or []) if str(x).strip()]
    gist = affects[0] if affects else str(entry.get('title') or '')
    return f"""
<details class="ncard" data-scope="{html.escape(str(entry.get('scope') or ''))}">
  <summary class="nhead">
    <div><div class="eyebrow">{html.escape(str(entry.get('scope') or ''))}</div>
    <h2>{html.escape(str(entry.get('short_name') or ''))}</h2>
    <div class="gist">{html.escape(gist)}</div></div>
    <span class="badge {badge}">{html.escape(label)}</span>{admin_badge}
  </summary>
  <p class="full-title">{html.escape(str(entry.get('title') or ''))}</p>
  <div class="meta">
    <div><b>Принят</b><span>{_fmt_date(entry.get('adopted_at'))}</span></div>
    <div><b>Учтён с</b><span>{_fmt_date(entry.get('effective_from'))}</span></div>
    <div><b>Реестр актуален на</b><span>{_fmt_date(entry.get('current_as_of'))}</span></div>
  </div>
  <div class="amend"><b>Текущая учтённая редакция</b>
    <span>{html.escape(str(entry.get('latest_amendment') or '—'))}</span></div>
  {news_html}
  {history_html}
  {chain_html}
  <div class="twocol">
    <section><h3>На что влияет</h3><ul>{_li(entry.get('affects'))}</ul></section>
    <section><h3>Где используется в движке</h3><ul class="usage">{usage}</ul></section>
  </div>
  <div class="source-row">
    {source_link}
    {check_html}
  </div>
  {f'<p class="notes">{notes}</p>' if notes else ''}
</details>"""


def guide_reference_html(css_prefix: str = "gnorm") -> str:
    """Справочник нормативной базы для руководства: три колонки по уровням.

    Состав берётся из САМОГО реестра, а не переписывается в руководство: копию
    негде обновлять, а разошедшись, она пообещала бы читателю основание,
    которого под числом нет. У каждой позиции — к чему относится и ссылка на
    оригинальный исходник; проверить нас можно только по нему.

    Реестр не прочитался — это говорится вслух. Пустой блок и отсутствующий
    выглядят одинаково, а значат разное.
    """
    try:
        rows = _merged_registry()
    except Exception as error:                       # noqa: BLE001 - причина важнее типа
        return (f'<p class="{css_prefix}-fail">Справочник нормативной базы не собран: '
                f'{html.escape(str(error))}.</p>')
    if not rows:
        return (f'<p class="{css_prefix}-fail">Справочник нормативной базы пуст — '
                'реестр не прочитан.</p>')

    columns: list[tuple[str, list[dict[str, Any]]]] = []
    for scope in ("Москва", "Московская область", "Общие для РФ"):
        got = [row for row in rows if row.get("scope") == scope]
        if got:
            columns.append((scope, got))
    # Уровень, которого нет в перечислении, не пропадает молча: он встаёт своей
    # колонкой под собственным именем.
    known = {scope for scope, _ in columns}
    for row in rows:
        scope = str(row.get("scope") or "").strip() or "Прочее"
        if scope not in known:
            known.add(scope)
            columns.append((scope, [r for r in rows if str(r.get("scope") or "") == scope]))

    parts = []
    for scope, items in columns:
        cells = []
        for row in items:
            name = html.escape(str(row.get("short_name") or row.get("title") or ""))
            url = str(row.get("source_url") or "").strip()
            title = html.escape(str(row.get("title") or ""))
            affects = [str(x) for x in (row.get("affects") or []) if str(x).strip()]
            what = html.escape("; ".join(affects[:2])) if affects else ""
            amendment = html.escape(str(row.get("latest_amendment") or "").split(";")[0].strip())
            link = (f'<a href="{html.escape(url)}" target="_blank" rel="noopener">исходник</a>'
                    if url else '<span class="{0}-nolink">ссылки на исходник нет</span>'.format(css_prefix))
            cells.append(
                f'<li><b title="{title}">{name}</b>'
                + (f'<span>{what}</span>' if what else "")
                + (f'<em>в редакции: {amendment}</em>' if amendment else "")
                + f'<span class="{css_prefix}-src">{link}</span></li>')
        parts.append(f'<div class="{css_prefix}-col"><h4>{html.escape(scope)}</h4>'
                     f'<ul>{"".join(cells)}</ul></div>')
    return f'<div class="{css_prefix}-grid">{"".join(parts)}</div>'


def _watch_note(watch: dict[str, Any]) -> str:
    """Строка «что сделал сторож» — под кнопками, там, где на неё смотрят.

    Без неё «изменений не приходило» неотличимо от «сторож не заходил», «поиск
    не настроен» и «находки лежат в очереди, а забрать их некому».
    """
    if not watch.get("enabled"):
        return ('<div class="watchnote">Сторож выключен '
                '(<code>NORMATIVES_WATCH=0</code>): проверка сама не заходит.</div>')
    parts: list[str] = []
    # `_fmt_date` на пустом значении отдаёт прочерк, а прочерк читается как
    # «не знаем». Здесь ответ другой и он известен: проверка не заходила ни разу.
    def when(key: str) -> str:
        return _fmt_date(watch.get(key)) if str(watch.get(key) or "").strip() else "ни разу"

    parts.append("Ссылки сверены: " + when("last_run_at"))
    if watch.get("search_available"):
        parts.append("открытые источники спрошены: " + when("last_search_at"))
    else:
        parts.append("открытые источники не спрашиваются — поиск не настроен")
    signals = int(watch.get("signals") or 0)
    # Ноль находок при нуле спрошенных и ноль находок при пятнадцати
    # спрошенных — разные ответы, и оба выглядели молчанием.
    if int(watch.get("searched") or 0):
        parts.append(f"находок о судьбе актов: {signals}" if signals
                     else "находок о судьбе актов нет")
    queued = int(watch.get("queued") or 0)
    # Ноль в очереди — это ответ, а не пустая строка: он и означает «переходов
    # с прошлой проверки не было», то есть сообщать боту нечего.
    parts.append(f"в очереди боту: {queued}" if queued
                 else "в очереди боту пусто — переходов с прошлой проверки не было")
    return '<div class="watchnote">' + html.escape(" · ".join(parts)) + "</div>"


def _legal_footer() -> str:
    """Подвал документов ИП: состав разбирается из `PAGE`, копии здесь нет.

    Движок берётся модулем, а не переданным `core`: у страницы он бывает
    подставным, а подвал обязан быть тем же, что на остальных поверхностях.
    """
    import guide
    import main_legacy

    return guide.legal_footer_html(main_legacy)


def _page(request: Request, core: Any) -> str:
    admin = _is_admin(request, core)
    rows = _merged_registry()
    scopes = ("Москва", "Московская область", "Общие для РФ")
    counts = {scope: sum(1 for row in rows if row.get("scope") == scope) for scope in scopes}
    cards = "".join(_card(row, admin=admin) for row in rows)

    footer = _legal_footer()

    adminbar = ""
    if admin:
        # Две кнопки, потому что вопроса два и цена у них разная. «Проверить
        # ссылки» отвечает на «страницу переписали?» — отпечаток, бесплатно.
        # «Спросить об отмене» ходит в открытые источники: только он видит,
        # что акт утратил силу или вышел в новой редакции, и он платный.
        # Одна кнопка на оба вопроса обещала бы ответ, которого не давала.
        watch = watch_state()
        search_btn = (
            '<button id="searchBtn" onclick="checkAll(true)">'
            'Спросить об отмене и редакциях (платный поиск)</button>'
            if watch.get("search_available") else
            '<span class="nomuted">Поиск по открытым источникам не настроен — '
            'отмену акта спросить нечем</span>'
        )
        adminbar = (
            '<div class="adminbar"><b>Режим администратора DevelopAid</b>'
            '<button id="checkBtn" onclick="checkAll(false)">Проверить ссылки</button>'
            + search_btn +
            '<span id="checkMsg"></span></div>'
            + _watch_note(watch)
        )

    return f"""<!doctype html><html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Нормативная база — DevelopAid</title>
<style>
.watchnote{{margin-top:8px;font-size:13px;color:#6d7480;line-height:1.5}}
.nomuted{{font-size:13px;color:#6d7480}}
:root{{--bg:#f5f6f8;--paper:#fff;--ink:#17191d;--muted:#6d7480;--line:#e2e5e9;
--accent:#20252b;--ok:#166534;--okbg:#ecfdf3;--warn:#92400e;--warnbg:#fff7ed;
--bad:#991b1b;--badbg:#fef2f2}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);
font:15px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}}a{{color:inherit}}
.shell{{max-width:1180px;margin:auto;padding:28px 22px 64px}}
.brandbar{{padding:4px 0 0}}.brandbar img{{display:block;width:min(360px,58vw);height:auto;mix-blend-mode:multiply}}.brandline{{height:8px;background:#050505;margin-top:12px}}
.legal-footer{{display:flex;gap:18px;flex-wrap:wrap;padding:14px 0 4px;font-size:11px;color:var(--muted);border-top:1px solid var(--line)}}.legal-footer a{{color:var(--muted)}}
.top{{display:flex;justify-content:space-between;align-items:center;gap:16px;margin-bottom:26px}}
.brand{{font-weight:800}}.top a{{text-decoration:none;border:1px solid var(--line);
padding:9px 14px;border-radius:10px;background:#fff}}h1{{font-size:34px;line-height:1.1;margin:0 0 8px}}
.lead{{color:var(--muted);max-width:900px;margin:0 0 22px}}
.summary{{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin:18px 0 24px}}
.summary div{{background:#fff;border:1px solid var(--line);border-radius:14px;padding:16px}}
.summary b{{font-size:28px;display:block}}.summary span{{color:var(--muted)}}
.filters{{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:18px}}
.filters button{{border:1px solid var(--line);background:#fff;border-radius:999px;padding:8px 12px;cursor:pointer}}
.filters button.active{{background:var(--accent);color:#fff;border-color:var(--accent)}}
.ncard{{background:#fff;border:1px solid var(--line);border-radius:18px;padding:22px;margin-bottom:14px}}
.ncard>summary{{cursor:pointer;list-style:none}}
.ncard>summary::-webkit-details-marker{{display:none}}
.ncard[open]>summary{{border-bottom:1px solid var(--line);padding-bottom:14px;margin-bottom:4px}}
.gist{{color:var(--muted);margin-top:6px;font-size:13px}}
.nhead{{display:flex;justify-content:space-between;align-items:flex-start;gap:14px}}
.eyebrow{{text-transform:uppercase;letter-spacing:.08em;font-size:11px;color:var(--muted);font-weight:700}}
h2{{font-size:21px;margin:4px 0 0}}.full-title{{color:#454b55;margin:12px 0 16px}}
.badge{{white-space:nowrap;border-radius:999px;padding:6px 9px;font-size:12px;font-weight:700}}
.badge.ok{{color:var(--ok);background:var(--okbg)}}.badge.warn{{color:var(--warn);background:var(--warnbg)}}
.badge.bad{{color:var(--bad);background:var(--badbg)}}.badge.muted{{color:var(--muted);background:#f3f4f6}}
.meta{{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin:12px 0}}
.meta div,.amend{{border:1px solid var(--line);border-radius:12px;padding:12px}}
.meta b,.amend b{{display:block;font-size:11px;text-transform:uppercase;letter-spacing:.05em;color:var(--muted);margin-bottom:4px}}
.news{{margin:12px 0 0;border:1px solid var(--warn);background:var(--warnbg);border-radius:12px;padding:12px 14px}}
.news h3{{margin:0 0 6px}}.news li b,.news li span{{display:block}}.news li span{{color:#454b55;font-size:13px}}
.news small{{display:block;margin-top:8px;color:var(--muted);font-size:12px}}
.news.calm{{border-color:var(--line);background:#fff}}
.history{{margin:10px 0 0;border:1px solid var(--line);border-radius:12px;padding:9px 12px}}
.history summary{{cursor:pointer;font-weight:700;font-size:13px}}
.twocol{{display:grid;grid-template-columns:1fr 1fr;gap:20px;margin-top:18px}}
h3{{font-size:14px;margin:0 0 8px}}ul{{margin:0;padding-left:19px}}li{{margin:5px 0}}
.usage li b,.usage li span{{display:block}}.usage li span{{color:var(--muted);font-size:13px}}
.source-row{{display:flex;justify-content:space-between;gap:16px;align-items:flex-start;
border-top:1px solid var(--line);padding-top:16px;margin-top:18px}}
.source-row>a{{font-weight:700;text-decoration:none}}.probe{{text-align:right;color:var(--muted)}}
.probe span,.probe small{{display:block}}.notes{{font-size:13px;color:var(--muted);margin:12px 0 0}}
.adminbar{{position:sticky;top:10px;z-index:5;display:flex;align-items:center;gap:10px;
background:#17191d;color:#fff;border-radius:12px;padding:12px 14px;margin-bottom:18px;
box-shadow:0 8px 30px rgba(0,0,0,.12)}}.adminbar button{{border:0;border-radius:8px;padding:9px 12px;cursor:pointer}}
#checkMsg{{font-size:13px;opacity:.8}}.foot{{color:var(--muted);font-size:13px;margin-top:26px}}
.hidden{{display:none!important}}
@media(max-width:760px){{.summary,.meta,.twocol{{grid-template-columns:1fr}}
.nhead,.source-row,.top{{display:block}}.badge{{display:inline-block;margin-top:10px}}
.probe{{text-align:left;margin-top:10px}}h1{{font-size:28px}}.adminbar{{position:static;display:block}}
.adminbar>*{{margin:4px 0;max-width:100%}}}}
</style></head><body><div class="shell">
<div class="brandbar"><a href="/" title="DevelopAid"><img src="/guide/assets/logo.webp" alt="ПЛАТО"></a><div class="brandline"></div></div>
<div class="top"><div class="brand">Нормативная база</div>
<a href="/">Вернуться в DevelopAid</a></div>
<h1>Нормативная документация движка</h1>
<p class="lead">Рабочая карта нормативных зависимостей: какая редакция учтена,
на какое правило или число она влияет и в каком модуле DevelopAid применяется.</p>
{adminbar}
<div class="summary"><div><b>{counts['Москва']}</b><span>Москва</span></div>
<div><b>{counts['Московская область']}</b><span>Московская область</span></div>
<div><b>{counts['Общие для РФ']}</b><span>Общие для РФ</span></div></div>
<div class="filters"><button class="active" data-filter="all">Все</button>
<button data-filter="Москва">Москва</button>
<button data-filter="Московская область">Московская область</button>
<button data-filter="Общие для РФ">Общие для РФ</button></div>
<div id="cards">{cards}</div>
<p class="foot">«Реестр актуален на» — дата содержательной сверки карточки.
Кнопка администратора проверяет доступность и изменение источника, но не подменяет
юридическую проверку консолидированной редакции.</p>
{footer}</div>
<script>
document.querySelectorAll('.filters button').forEach(btn=>btn.addEventListener('click',()=>{{
 document.querySelectorAll('.filters button').forEach(x=>x.classList.remove('active'));
 btn.classList.add('active');const f=btn.dataset.filter;
 document.querySelectorAll('.ncard').forEach(c=>c.classList.toggle('hidden',f!=='all'&&c.dataset.scope!==f));
}}));
async function checkAll(search){{
 const ids=['checkBtn','searchBtn'].map(i=>document.getElementById(i)).filter(Boolean);
 const m=document.getElementById('checkMsg');
 ids.forEach(b=>b.disabled=true);
 // Кнопка называет, что делает ИМЕННО она: «проверяю источники» на обеих
 // читалось бы как один и тот же вопрос, а вопроса два.
 m.textContent=search?'Спрашиваю открытые источники об отмене и редакциях…'
                     :'Сверяю ссылки реестра…';
 try{{const r=await fetch('/api/normatives/check'+(search?'?search=1':''),{{method:'POST'}});
 if(!r.ok){{
  // Ответ разбирают, зная, что он может быть не ответом: причина отказа
  // приезжает текстом, и «HTTP 503» вместо неё — поломка разбора, а не ответ.
  let why='HTTP '+r.status;
  try{{const t=await r.text();const j=JSON.parse(t);why=j.detail||why;}}catch(_){{}}
  throw new Error(why);
 }}
 m.textContent='Готово. Обновляю…';location.reload();}}
 catch(e){{m.textContent='Ошибка: '+e.message;ids.forEach(b=>b.disabled=false);}}
}}
</script></body></html>"""


def install(app: Any, core: Any) -> None:
    @app.get("/normatives", response_class=HTMLResponse, include_in_schema=False)
    @app.get("/normatives/", response_class=HTMLResponse, include_in_schema=False)
    async def normatives_page(request: Request) -> HTMLResponse:
        return HTMLResponse(_page(request, core), headers=_HEADERS)

    @app.get("/api/normatives", include_in_schema=False)
    def normatives_api() -> JSONResponse:
        state = _load_state()
        return JSONResponse(
            {"items": _merged_registry(), "last_run_at": state.get("last_run_at")},
            headers=_HEADERS,
        )

    # Очередь находок забирает движок (`/internal/normatives/announcements`):
    # у него общая с ботом подпись, а до api.telegram.org с ядра не дойти.
    app.state.normatives_announcements_take = take_announcements

    @app.get("/api/normatives/watch", include_in_schema=False)
    def normatives_watch() -> JSONResponse:
        """Состояние сторожа: измеримо со стороны, без ключа и без адресатов.

        «Молчащая проверка неотличима от отсутствующей» — счётчик молчания и
        отвечает на «мне ничего не пришло»: заходил ли сторож, когда, что
        нашёл и сколько находок ждёт бота.
        """
        return JSONResponse(watch_state(), headers=_HEADERS)

    @app.post("/api/normatives/check", include_in_schema=False)
    def normatives_check(request: Request, search: str = "") -> JSONResponse:
        """Проверка источников. `search=1` — платный вопрос об отмене акта.

        Вопроса два, и они разные: «страницу переписали?» отвечает отпечаток
        ссылки (бесплатно, каждый заход), «акт отменён или вышла новая
        редакция?» — поиск по открытым источникам, и он платный. Кнопка,
        обещавшая второе и делавшая первое, отвечала на не тот вопрос:
        владелец просил проверять, что документы «не получили изменений
        редакции или вовсе отменены», а отмену отпечаток не видит по
        построению — акт отменяют, не трогая нашу страницу.
        """
        if not _is_admin(request, core):
            raise HTTPException(status_code=403, detail="Только администратор DevelopAid")
        wanted = str(search or "").strip().lower() in {"1", "true", "yes", "on"}
        if wanted and _search_client() is None:
            # Отказ называет причину: молча пройдя без поиска, кнопка второй
            # раз пообещала бы ответ, которого не давала.
            raise HTTPException(
                status_code=503,
                detail="Поиск по открытым источникам не настроен — отмену акта спросить нечем.")
        return JSONResponse({"ok": True, "searched": wanted, **_run_check(search=wanted)},
                            headers=_HEADERS)

    # Проверка по расписанию: кнопка отвечает тому, кто открыл страницу, а
    # сообщение — тому, кто не открывал. Раз в сутки, воркеров два — работу
    # берёт один по возрасту состояния. Выключается NORMATIVES_WATCH=0;
    # расписание, зависящее от календаря, иначе срабатывает в прогоне тестов
    # ровно в тот день, когда его никто не ждёт.
    if os.getenv("NORMATIVES_WATCH", "1").strip() not in {"0", "false", "no"}:
        threading.Thread(target=_watch_loop, name="normatives-watch", daemon=True).start()


def _watch_due(hours: float, key: str = "last_run_at") -> bool:
    """Пора ли проверять. Пустое состояние — пора: мы ещё ни разу не смотрели."""
    stamp = str(_load_state().get(key) or "").strip()
    if not stamp:
        return True
    try:
        was = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except Exception:
        return True
    return (datetime.now(timezone.utc) - was).total_seconds() >= hours * 3600.0


def _watch_loop() -> None:
    """Ссылку смотрим сутками, открытые источники — раз в неделю.

    Поиск платный, и вопросы у них разные: отпечаток отвечает «страницу
    переписали?», поиск — «что с актом стало». Второе меняется медленно, а
    стоит денег, поэтому и спрашивается реже.
    """
    hours = max(1.0, float(os.getenv("NORMATIVES_WATCH_HOURS", "24") or 24))
    search_hours = max(hours, float(os.getenv("NORMATIVES_SEARCH_HOURS", "168") or 168))
    while True:
        try:
            if _watch_due(hours):
                _run_check(search=_watch_due(search_hours, key="last_search_at"))
        except Exception:
            pass          # сторож — удобство: молчание лучше падения фонового потока
        time.sleep(1800)
