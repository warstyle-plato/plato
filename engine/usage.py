"""Учёт использования: журнал событий, свод, анкета, реестр профилей.

Построчный журнал событий по дням, usage_track, выборка и свод, свод
анкеты, выгрузка CSV и реестр профилей.

Не самостоятельный модуль. `main_legacy.py` выполняет этот файл в своём
пространстве имён на том месте, где этот код стоял раньше
(`_engine_part("usage")`), поэтому здесь видны все имена движка,
а подмены `core.<имя>` из `main.py` и тестов действуют и на этот код.
Отдельно не импортировать: второй импорт поднял бы вторую копию движка.
"""
# ruff: noqa

# --- Кто пользуется и о чём спрашивает --------------------------------------
# Пользователей считали по ощущениям, а вопросы читали через плечо. Ни того, ни
# другого не хватает, чтобы решать, что делать дальше: непонятно, растёт ли
# аудитория, и непонятно, о чём её спрашивают чаще всего.
#
# Журнал — построчный файл на день. Строка пишется одним `write` в режиме
# добавления: воркеров два, и перезаписывать общий файл им нельзя. Хранится
# полгода, чистится при записи. Выключается переменной, потому что журнал
# пользовательских текстов — это данные людей, и решение хранить их принимает
# владелец, а не код.

_USAGE_DIR = Path(_env_str("DEVELOPAID_USAGE_DIR", "").strip()
                  or (Path(__file__).resolve().parent / "data" / "usage"))
_USAGE_KEEP_DAYS = max(1, int(_env_float("DEVELOPAID_USAGE_KEEP_DAYS", 180.0)))
_USAGE_TEXT_LIMIT = 500
_USAGE_LOCK = threading.Lock()
_USAGE_SWEPT: dict[str, str] = {}


def _usage_enabled() -> bool:
    return _env_str("DEVELOPAID_USAGE_JOURNAL", "on").strip().lower() not in {
        "off", "0", "no", "false", "выкл"}


def _usage_day(at: float) -> str:
    return datetime.fromtimestamp(at, tz=timezone.utc).strftime("%Y-%m-%d")


def _usage_path(day: str) -> Path:
    return _USAGE_DIR / f"events-{day}.jsonl"


def _usage_sweep(today: str) -> None:
    """Старое удаляется раз в день, а не на каждой записи."""
    if _USAGE_SWEPT.get("day") == today:
        return
    _USAGE_SWEPT["day"] = today
    try:
        cutoff = (datetime.now(tz=timezone.utc)
                  - timedelta(days=_USAGE_KEEP_DAYS)).strftime("%Y-%m-%d")
        for path in _USAGE_DIR.glob("events-*.jsonl"):
            if path.stem[len("events-"):] < cutoff:
                path.unlink(missing_ok=True)
    except OSError:
        pass


def usage_track(kind: str, *, surface: str = "bot", chat_id: int = 0, user_id: int = 0,
                name: str = "", text: str = "", **extra: Any) -> None:
    """Одно событие в журнал. Молча — учёт не имеет права ронять ответ."""
    if not _usage_enabled():
        return
    at = time.time()
    record = {
        "at": round(at, 3),
        "surface": surface,
        "kind": kind,
        "chat": int(chat_id or 0),
        "user": int(user_id or 0),
        "name": str(name or "")[:80],
        "text": str(text or "").strip()[:_USAGE_TEXT_LIMIT],
    }
    record.update({key: value for key, value in extra.items() if value not in (None, "")})
    day = _usage_day(at)
    try:
        with _USAGE_LOCK:
            _USAGE_DIR.mkdir(parents=True, exist_ok=True)
            _usage_sweep(day)
            with _usage_path(day).open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    except (OSError, TypeError, ValueError):
        pass
    # Человек и его анкета живут дольше журнала: журнал подметается через
    # полгода и умирает вместе с контейнером Render, а на вопросы «сколько у
    # нас пользователей» и «что нам написали» отвечать надо всегда.
    users_touch(record["chat"], surface=record["surface"], kind=kind,
                name=record["name"])
    if kind == "survey":
        survey_store(record)


def usage_events(days: int = 30) -> list[dict[str, Any]]:
    """События за последние N суток, по возрастанию времени."""
    events: list[dict[str, Any]] = []
    now = datetime.now(tz=timezone.utc)
    for back in range(max(1, int(days))):
        path = _usage_path((now - timedelta(days=back)).strftime("%Y-%m-%d"))
        if not path.is_file():
            continue
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except ValueError:
                    continue  # оборванная строка не отменяет остальной день
                if isinstance(record, dict):
                    events.append(record)
        except OSError:
            continue
    events.sort(key=lambda item: float(item.get("at") or 0))
    return events


def usage_summary(days: int = 30) -> dict[str, Any]:
    """Свод: сколько людей, сколько новых, что нажимают, о чём спрашивают.

    Читается весь журнал, а не окно свода: «новый» — это тот, кого раньше не
    было вообще, а не тот, кого не было последний месяц. По окну в тридцать дней
    вернувшийся через полгода человек считался новым. Команда ручная, файлов за
    полгода меньше двух сотен — цена чтения того стоит.
    """
    events = usage_events(max(days, _USAGE_KEEP_DAYS))
    now = time.time()

    def users_since(seconds: float) -> set[int]:
        return {int(e.get("user") or 0) for e in events
                if e.get("surface") == "bot" and float(e.get("at") or 0) >= now - seconds
                and int(e.get("user") or 0)}

    window = [e for e in events if float(e.get("at") or 0) >= now - days * 86400]
    seen_before: dict[int, float] = {}
    for event in events:
        user = int(event.get("user") or 0)
        if user and user not in seen_before:
            seen_before[user] = float(event.get("at") or 0)

    commands: dict[str, int] = {}
    buttons: dict[str, int] = {}
    questions: list[dict[str, Any]] = []
    for event in window:
        kind = str(event.get("kind") or "")
        text = str(event.get("text") or "")
        if kind == "command":
            key = text.split(maxsplit=1)[0].split("@", 1)[0].lower()
            commands[key] = commands.get(key, 0) + 1
        elif kind == "button":
            buttons[text] = buttons.get(text, 0) + 1
        elif kind == "question":
            questions.append(event)

    return {
        "days": int(days),
        "users_today": len(users_since(86400)),
        "users_7d": len(users_since(7 * 86400)),
        "users_30d": len(users_since(30 * 86400)),
        "users_window": len({int(e.get("user") or 0) for e in window
                             if e.get("surface") == "bot" and int(e.get("user") or 0)}),
        "new_users_window": len([user for user, first in seen_before.items()
                                 if first >= now - days * 86400]),
        "events_window": len(window),
        "questions_bot": len([q for q in questions if q.get("surface") == "bot"]),
        "questions_site": len([q for q in questions if q.get("surface") == "site"]),
        "top_commands": sorted(commands.items(), key=lambda kv: -kv[1])[:8],
        "top_buttons": sorted(buttons.items(), key=lambda kv: -kv[1])[:8],
        "last_questions": questions[-15:],
        "enabled": _usage_enabled(),
        "keep_days": _USAGE_KEEP_DAYS,
        "dir": str(_USAGE_DIR),
    }


def survey_summary(days: int = 30) -> dict[str, Any]:
    """Свод теста: откуда пришли, докуда дошли, как оценили, что написали.

    Воронка считается по людям, а не по событиям: один человек, посчитавший
    десять проектов, — это один дошедший, а не десять. Средние оценки —
    по подпунктам и по разделам, и рядом всегда число ответов: среднее по
    двум ответам выглядит так же солидно, как по двадцати, и вводит в
    заблуждение сильнее всего.

    Свободные тексты не сворачиваются ни во что: их читают целиком. Ради них
    анкета и затевалась.
    """
    events = usage_events(max(days, _USAGE_KEEP_DAYS))
    now = time.time()
    window = [e for e in events if float(e.get("at") or 0) >= now - days * 86400]

    # Метка источника приезжает один раз, при нажатии Start. Дальше события
    # приходят без неё, поэтому источник восстанавливается по chat_id.
    source_by_chat: dict[int, str] = {}
    for event in events:
        if str(event.get("kind")) == "invite":
            chat = int(event.get("chat") or 0)
            if chat:
                source_by_chat[chat] = str(event.get("source") or "")

    def people(kind: str) -> set[int]:
        return {int(e.get("chat") or 0) for e in window
                if str(e.get("kind")) == kind and int(e.get("chat") or 0)}

    invited = people("invite")
    funnel = {
        "перешли по ссылке": len(invited),
        "искали участок": len(people("land")),
        "посчитали": len(people("calc")),
        "выгрузили PDF": len(people("pdf")),
        "ответили на анкету": len(people("survey")),
    }
    by_source: dict[str, int] = {}
    for chat in invited:
        key = source_by_chat.get(chat) or "без метки"
        by_source[key] = by_source.get(key, 0) + 1

    # Анкеты берутся из хранилища, а не только из журнала: журнал подметается,
    # а анкета должна лежать вечно. Журнальные оставлены для тех, что записаны
    # до появления хранилища; дубли снимаются по времени и чату.
    surveys = [e for e in window if str(e.get("kind")) == "survey"]
    seen_surveys = {(round(float(e.get("at") or 0), 3), int(e.get("chat") or 0))
                    for e in surveys}
    for stored in survey_records():
        at = float(stored.get("at") or 0)
        if at < now - days * 86400:
            continue
        if (round(at, 3), int(stored.get("chat") or 0)) in seen_surveys:
            continue
        surveys.append(stored)
    surveys.sort(key=lambda item: float(item.get("at") or 0))
    scores: dict[str, list[int]] = {}
    for survey in surveys:
        for key, value in (survey.get("ratings") or {}).items():
            if key in FEEDBACK_ITEMS:
                scores.setdefault(key, []).append(int(value))

    def average(values: list[int]) -> float:
        return round(sum(values) / len(values), 2) if values else 0.0

    items = [{"key": key, "label": FEEDBACK_ITEMS[key],
              "avg": average(values), "count": len(values)}
             for key, values in scores.items()]
    items.sort(key=lambda row: (row["avg"], -row["count"]))

    groups = []
    for group_key, title, members in FEEDBACK_GROUPS:
        collected = [score for item in members for score in scores.get(item[0], [])]
        groups.append({"key": group_key, "label": title,
                       "avg": average(collected), "count": len(collected)})

    # Кто ответил. Анкета не анонимная — она привязана к chat_id, — но по одному
    # номеру ничего не понять, и владелец видел «— : не верю числам» без всякого
    # автора. Имя берётся тремя источниками по убыванию надёжности: знакомство
    # (имя и компания, их человек написал сам), имя из Telegram в журнале,
    # номер чата. Профиль лежит на ядре, поэтому на Render остаются два
    # последних — там и живут ответы из бота.
    def who(chat: int) -> str:
        chat = int(chat or 0)
        if not chat:
            return "аноним"
        profile = {}
        try:
            profile = profile_read(chat) or {}
        except Exception:
            profile = {}
        name = str(profile.get("name") or "").strip() or name_by_chat.get(chat, "")
        company = str(profile.get("company") or "").strip()
        if name and company:
            return f"{name} ({company})"
        return name or f"chat {chat}"

    name_by_chat: dict[int, str] = {}
    for event in events:
        chat = int(event.get("chat") or 0)
        name = str(event.get("name") or "").strip()
        if chat and name:
            name_by_chat[chat] = name

    notes: list[dict[str, Any]] = []
    for survey in surveys:
        for group_key, text in (survey.get("problems") or {}).items():
            title = next((g[1] for g in FEEDBACK_GROUPS if g[0] == group_key), group_key)
            notes.append({"at": survey.get("at"), "chat": survey.get("chat"),
                          "who": who(survey.get("chat")),
                          "role": survey.get("role", ""), "group": title, "text": text})
        # Свободные поля — тоже комментарий, и раньше они не доходили никуда:
        # свод читал только привязанные к разделу. В боте комментарий один и
        # приходит именно так, то есть пропала бы вся его половина.
        for field, title in (("impression", "Общее впечатление"),
                             ("mistakes", "Что пошло не так")):
            text = str(survey.get(field) or "").strip()
            if text:
                notes.append({"at": survey.get("at"), "chat": survey.get("chat"),
                              "who": who(survey.get("chat")),
                              "role": survey.get("role", ""), "group": title,
                              "text": text})

    # Ответы поимённо. Средние показывают состояние сервиса, а этот список —
    # разговор с конкретным человеком: что он поставил и что написал. Анкета
    # приходит двумя записями (оценки и комментарий), поэтому они складываются
    # по chat_id, а не показываются двумя строками.
    people: dict[int, dict[str, Any]] = {}
    for survey in sorted(surveys, key=lambda s: float(s.get("at") or 0)):
        chat = int(survey.get("chat") or 0)
        person = people.setdefault(chat, {
            "chat": chat, "who": who(chat), "at": survey.get("at"),
            "surface": survey.get("surface", ""), "role": survey.get("role", ""),
            "scores": {}, "texts": [],
        })
        person["at"] = survey.get("at") or person["at"]
        if survey.get("role"):
            person["role"] = survey.get("role")
        for key, value in (survey.get("ratings") or {}).items():
            if key in FEEDBACK_ITEMS:
                person["scores"][key] = int(value)
        for text in list((survey.get("problems") or {}).values()) + [
                survey.get("impression"), survey.get("mistakes")]:
            text = str(text or "").strip()
            if text:
                person["texts"].append(text)
    respondents = []
    for person in people.values():
        scores = list(person["scores"].values())
        respondents.append({
            "chat": person["chat"], "who": person["who"], "at": person["at"],
            "surface": person["surface"], "role": person["role"],
            "rated": len(scores), "avg": average(scores),
            "texts": person["texts"],
            "lowest": sorted(
                ({"label": FEEDBACK_ITEMS[key], "score": score}
                 for key, score in person["scores"].items()),
                key=lambda row: row["score"])[:3],
        })
    respondents.sort(key=lambda row: float(row["at"] or 0), reverse=True)

    return {
        "days": int(days),
        "funnel": funnel,
        "by_source": sorted(by_source.items(), key=lambda kv: -kv[1]),
        "answers": len(surveys),
        "roles": sorted({str(s.get("role") or "—") for s in surveys}),
        # Слабейшие подпункты идут первыми: свод читают, чтобы понять, что чинить.
        "weakest": items[:8],
        "strongest": list(reversed(items[-5:])),
        "groups": groups,
        "notes": notes,
        "respondents": respondents,
    }


def usage_csv(days: int = 30, events: list[dict[str, Any]] | None = None) -> bytes:
    """Выгрузка для разбора вопросов не глазами.

    Точка с запятой и BOM — чтобы Excel открыл кириллицу и не склеил колонки.

    События можно передать снаружи: журнал пишется там, где обслужен запрос,
    и выгрузка бота без событий ядра — половина картины. Пустая таблица при
    этом читается как «людей не было», хотя это «диск Render пережил выкатку
    и не пережил».
    """
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=";")
    writer.writerow(["время (UTC)", "поверхность", "событие", "chat_id", "user_id",
                     "кто", "текст"])
    rows = usage_events(days) if events is None else sorted(
        events, key=lambda event: float(event.get("at") or 0))
    for event in rows:
        writer.writerow([
            datetime.fromtimestamp(float(event.get("at") or 0),
                                   tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
            event.get("surface", ""), event.get("kind", ""),
            event.get("chat", ""), event.get("user", ""),
            event.get("name", ""), str(event.get("text") or "").replace("\n", " "),
        ])
    return ("﻿" + buffer.getvalue()).encode("utf-8")


def profile_registry_summary(days: int = 30) -> dict[str, Any]:
    """Сколько людей заполнило знакомство и кто это.

    Знакомство — единственная запись, которая переживает выкатку: журнал
    обращений живёт на том хосте, который обслужил запрос, а на Render его диск
    кончается вместе с контейнером. Профили лежат на ядре файлами, поэтому
    «сколько зарегистрировалось» считается по ним, а не по журналу.

    Слова человека остаются словами человека: телеграм подтверждает аккаунт,
    имя и компанию подтвердить нечем — так и записано в самой анкете.
    """
    directory = _PROJECTS_DIR.parent / "profiles"
    people: list[dict[str, Any]] = []
    try:
        paths = sorted(directory.glob("*.json"))
    except OSError:
        paths = []
    for path in paths:
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(record, dict):
            continue
        people.append(record)

    def moment(record: dict[str, Any]) -> float:
        raw = str(record.get("created") or record.get("updated") or "")
        try:
            return datetime.fromisoformat(raw).timestamp()
        except ValueError:
            return 0.0

    people.sort(key=moment, reverse=True)
    edge = time.time() - max(1, int(days)) * 86400
    fresh = [record for record in people if moment(record) >= edge]

    sources: dict[str, int] = {}
    for record in people:
        key = str(record.get("source") or "").strip() or "не сказали"
        sources[key] = sources.get(key, 0) + 1

    return {
        "days": int(days),
        "total": len(people),
        "window": len(fresh),
        "complete": len([r for r in people if profile_complete(r)]),
        "by_source": sorted(sources.items(), key=lambda kv: -kv[1])[:8],
        "recent": [{
            "chat": int(record.get("chat_id") or 0),
            "name": str(record.get("name") or ""),
            "company": str(record.get("company") or ""),
            "role": str(record.get("role") or ""),
            "source": str(record.get("source") or ""),
            "contact": str(record.get("contact") or ""),
            "created": str(record.get("created") or ""),
        } for record in people[:15]],
        "dir": str(directory),
    }
