"""Пользователи бота: анкеты, хранилище проектов, передача проекта,
знакомство, новые площадки КРТ с ядра в бот, рассылки и вход на сайт через бота.

Не самостоятельный модуль. `main_legacy.py` выполняет этот файл в своём
пространстве имён на том месте, где этот код стоял раньше
(`_engine_part("bot_users")`), поэтому здесь видны все имена движка,
а подмены `core.<имя>` из `main.py` и тестов действуют и на этот код.
Отдельно не импортировать: второй импорт поднял бы вторую копию движка.
"""
# ruff: noqa

# --- анкеты и пользователи: то, что должно пережить всё ----------------------
#
# Журнал обращений подметается через `_USAGE_KEEP_DAYS` и живёт на том хосте,
# который обслужил запрос: на Render он кончается вместе с контейнером. Анкета
# и факт «человек пришёл» — самые редкие и самые дорогие записи из всех, что мы
# собираем, и держать их там нельзя. Поэтому они лежат файлами рядом с
# профилями знакомства: на ядре, в смонтированном томе, без срока.
#
# Найдено разбором журнала 23.08.2026: на 711 расчётов пришлись 2 знакомства и
# 1 анкета, а «сколько у нас пользователей» ответить было нечем — вопросы
# Платону писались вовсе без `chat_id`, и 74 живых вопроса легли под нулём.


def _surveys_dir() -> Path:
    return _PROJECTS_DIR.parent / "surveys"


def _users_dir() -> Path:
    return _PROJECTS_DIR.parent / "users"


def survey_store(record: dict[str, Any]) -> str:
    """Одна анкета — один файл, навсегда. Возвращает имя файла или пустую строку.

    Имя несёт время и chat, чтобы файлы сортировались по дате и повторная
    запись той же анкеты не плодила копий: анкета приходит двумя записями
    (оценки и комментарий), и у каждой своё время.
    """
    try:
        at = float(record.get("at") or time.time())
    except (TypeError, ValueError):
        at = time.time()
    stamp = datetime.fromtimestamp(at, tz=timezone.utc).strftime("%Y%m%d-%H%M%S")
    name = f"{stamp}-{int(record.get('chat') or 0)}.json"
    try:
        directory = _surveys_dir()
        directory.mkdir(parents=True, exist_ok=True)
        payload = dict(record)
        payload["at"] = round(at, 3)
        (directory / name).write_text(
            json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    except (OSError, TypeError, ValueError):
        return ""
    return name


def survey_records() -> list[dict[str, Any]]:
    """Все сохранённые анкеты по возрастанию времени."""
    records: list[dict[str, Any]] = []
    try:
        paths = sorted(_surveys_dir().glob("*.json"))
    except OSError:
        paths = []
    for path in paths:
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(record, dict):
            record.setdefault("kind", "survey")
            records.append(record)
    records.sort(key=lambda item: float(item.get("at") or 0))
    return records


def users_touch(chat_id: int, *, surface: str = "", kind: str = "",
                name: str = "") -> None:
    """Отметить живого человека. Молча — учёт не имеет права ронять ответ.

    Зовётся из `usage_track`, то есть из единственного места, где сходятся все
    обращения: ветка, добавленная позже, иначе молча выпадет из счёта. Пишем
    только тех, у кого есть `chat_id`, — вход через телеграм и есть наше
    определение пользователя (решение владельца, 23.08.2026).
    """
    chat = int(chat_id or 0)
    if not chat:
        return
    try:
        directory = _users_dir()
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{chat}.json"
        record: dict[str, Any] = {}
        if path.is_file():
            try:
                loaded = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    record = loaded
            except (OSError, ValueError):
                record = {}
        now = round(time.time(), 3)
        record["chat"] = chat
        record.setdefault("first_seen", now)
        record["last_seen"] = now
        if name:
            record["name"] = str(name)[:80]
        if surface:
            surfaces = record.get("surfaces")
            record["surfaces"] = sorted({*(surfaces if isinstance(surfaces, list) else []),
                                         str(surface)})
        if kind:
            kinds = record.get("kinds")
            kinds = kinds if isinstance(kinds, dict) else {}
            kinds[str(kind)] = int(kinds.get(str(kind)) or 0) + 1
            record["kinds"] = kinds
        path.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
    except (OSError, TypeError, ValueError):
        return


def users_registry_summary(days: int = 30) -> dict[str, Any]:
    """Сколько у нас пользователей — по входам через телеграм.

    Реестр переживает и выкатку, и подметание журнала: он лежит файлами на
    ядре. «Всего» — это все, кого мы вообще видели; «за окно» — те, кто пришёл
    впервые за последние N суток. Смешивать их в одно число нельзя: первое
    отвечает на «сколько у нас людей», второе на «сколько пришло за неделю».
    """
    people: list[dict[str, Any]] = []
    try:
        paths = sorted(_users_dir().glob("*.json"))
    except OSError:
        paths = []
    for path in paths:
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(record, dict) and int(record.get("chat") or 0):
            people.append(record)
    people.sort(key=lambda item: float(item.get("first_seen") or 0), reverse=True)
    edge = time.time() - max(1, int(days)) * 86400
    fresh = [item for item in people if float(item.get("first_seen") or 0) >= edge]
    active = [item for item in people if float(item.get("last_seen") or 0) >= edge]

    def profile_name(chat: int) -> str:
        try:
            record = profile_read(chat) or {}
        except Exception:
            record = {}
        name = str(record.get("name") or "").strip()
        company = str(record.get("company") or "").strip()
        return f"{name} ({company})" if name and company else name

    return {
        "days": int(days),
        "total": len(people),
        "new_in_window": len(fresh),
        "active_in_window": len(active),
        "recent": [{
            "chat": int(item.get("chat") or 0),
            "name": profile_name(int(item.get("chat") or 0)) or str(item.get("name") or ""),
            "first_seen": float(item.get("first_seen") or 0),
            "last_seen": float(item.get("last_seen") or 0),
            "surfaces": item.get("surfaces") or [],
            "kinds": item.get("kinds") or {},
        } for item in people[:15]],
        "dir": str(_users_dir()),
    }


def usage_admin_ids() -> set[int]:
    """Кому показывать статистику. Пусто — значит никому: список чужих вопросов
    не та вещь, которую отдают по умолчанию."""
    raw = _env_str("DEVELOPAID_ADMIN_IDS", "")
    ids: set[int] = set()
    for piece in re.split(r"[,\s;]+", raw or ""):
        piece = piece.strip()
        if piece.lstrip("-").isdigit():
            ids.add(int(piece))
    return ids


# ---------------------------------------------------------------------------
# Хранилище проектов
#
# Проект живёт в браузере: `localStorage` держит один-единственный набор, и
# второй участок затирает первый. Смотреть площадки подряд можно, вернуться к
# позавчерашней — нет.
#
# Хранится не всё подряд, а то, что явно сохранили: просмотр площадки — это
# черновик, и складывать каждый пересчёт значит завести свалку вместо полки.
#
# Место хранения — ядро на Яндексе, а не Render. Две причины, и обе жёсткие:
# диск Render живёт до следующей выкатки, а привязанные к человеку данные
# россиян по 152-ФЗ (ст. 18.1) обязаны лежать в России. Поэтому Render свои
# запросы пересылает на ядро и у себя не хранит ничего.
#
# С 15.08.2026 (решение владельца) хранилище общее: владельца опознаёт
# подписанная телеграм-сессия — мини-приложения или входа через бота, — и
# каждый chat_id живёт в своём каталоге со своим лимитом. Регистрации нет:
# личность и так выдаёт бот. Данные лежат на ядре в России; текст согласия
# на обработку — на владельце проекта.
# ---------------------------------------------------------------------------

_PROJECTS_DIR = Path(_env_str("DEVELOPAID_PROJECTS_DIR", "").strip()
                     or (Path(__file__).resolve().parent / "data" / "projects"))
_PROJECTS_LIMIT = max(1, int(_env_float("DEVELOPAID_PROJECTS_LIMIT", 200.0)))
_PROJECT_PAYLOAD_LIMIT = 4 * 1024 * 1024


def _projects_remote_url(path: str) -> str:
    """Адрес ядра, если мы не ядро. Пусто — храним у себя."""
    return _core_api_url(path) if _MO_CALC_API_URL else ""


def _project_owner(session: str = "", key: str = "") -> int:
    """Кто сохраняет. Опознаём двумя способами, оба сводятся к «это владелец».

    Подписанная Telegram-сессия — из мини-приложения или входа через бота —
    несёт chat_id: каждый пользователь бота хранит свои проекты в своём
    каталоге (решение владельца, 15.08.2026). Ключ администратора остаётся
    входом без телеграма; не задан — способ выключён, а не открыт всем.
    """
    if session:
        chat_id = int(_telegram_verify_session(session).get("chat_id") or 0)
        if chat_id:
            return chat_id
        raise HTTPException(status_code=403, detail="В сессии нет владельца — войдите заново.")
    admins = usage_admin_ids()
    if not admins:
        raise HTTPException(
            status_code=503,
            detail="Хранилище проектов не настроено: задайте DEVELOPAID_ADMIN_IDS.")
    secret = _env_str("DEVELOPAID_ADMIN_KEY", "").strip()
    # Сравниваем байтами: `compare_digest` отказывается работать со строками,
    # где есть не-ASCII, а ключ владелец задаёт какой захочет.
    if secret and key and hmac.compare_digest(str(key).encode("utf-8"), secret.encode("utf-8")):
        return sorted(admins)[0]
    # Пустой `DEVELOPAID_ADMIN_KEY` отказывал теми же словами, что неверный
    # ключ: человек вводил его снова и снова, а принимать было нечему
    # (замечание владельца, 18.08.2026). Причины разные — и ответы разные.
    if not secret:
        raise HTTPException(
            status_code=403,
            detail=("Ключи на этом сервере не принимаются: DEVELOPAID_ADMIN_KEY "
                    "не задан. Войдите через Telegram — кнопка в «Личном кабинете»."))
    if not key:
        raise HTTPException(
            status_code=403,
            detail=("Войдите через Telegram (кнопка в «Личном кабинете») либо "
                    "введите ключ администратора — иначе сервер не знает, чей "
                    "это проект."))
    raise HTTPException(
        status_code=403,
        detail=("Ключ администратора не подошёл. Проверьте его или войдите "
                "через Telegram — кнопка в «Личном кабинете»."))


def _project_dir(owner: int) -> Path:
    return _PROJECTS_DIR / str(int(owner))


def _project_path(owner: int, project_id: str) -> Path:
    # Имя файла приходит снаружи: всё, кроме нашего же алфавита, — отказ, иначе
    # «../../» уводит запись за пределы каталога владельца.
    if not re.fullmatch(r"[0-9a-f]{12}", str(project_id or "")):
        raise HTTPException(status_code=400, detail="Неверный идентификатор проекта")
    return _safe_child(_project_dir(owner), f"{project_id}.json",
                       http_detail="Неверный идентификатор проекта")


def _project_card(record: dict[str, Any]) -> dict[str, Any]:
    """Строка списка: имя, время и несколько чисел, чтобы узнать проект не открывая."""
    summary = record.get("summary") or {}
    return {
        "id": record.get("id"),
        "name": record.get("name"),
        "saved_at": record.get("saved_at"),
        "version": record.get("version"),
        "cadastral": record.get("cadastral") or [],
        "summary": {key: summary.get(key) for key in
                    ("revenue_mln", "net_profit_mln", "llcr", "purchase_price_mln")},
        # Не сам код, а признак: запись поверх обновляет то, что видит
        # получатель ссылки, и предупредить об этом надо ДО записи. Код в
        # списке был бы выдачей секрета там, где хватает «да/нет».
        "has_share": bool(record.get("share_code")),
    }


def project_save(owner: int, name: str, payload: dict[str, Any],
                 summary: dict[str, Any] | None = None,
                 cadastral: list[str] | None = None,
                 project_id: str = "") -> dict[str, Any]:
    body = json.dumps(payload or {}, ensure_ascii=False)
    if len(body.encode("utf-8")) > _PROJECT_PAYLOAD_LIMIT:
        raise HTTPException(status_code=413, detail="Проект слишком велик для хранилища")
    directory = _project_dir(owner)
    directory.mkdir(parents=True, exist_ok=True)
    existing = sorted(directory.glob("*.json"))
    if not project_id and len(existing) >= _PROJECTS_LIMIT:
        raise HTTPException(
            status_code=507,
            detail=f"В хранилище уже {len(existing)} проектов — удалите ненужные.")
    # Ссылка на проект переживает его правку. Иначе после сохранения код
    # терялся, «Поделиться» выпускало второй, а первый продолжал жить и
    # показывать старые числа: две живые ссылки на один проект, и та, что у
    # получателя, — устаревшая.
    share_code = ""
    if project_id:
        try:
            previous = json.loads(_project_path(owner, project_id).read_text(encoding="utf-8"))
            share_code = str(previous.get("share_code") or "")
        except (OSError, ValueError, HTTPException):
            share_code = ""
    record = {
        "id": project_id or hashlib.sha256(
            f"{owner}:{time.time()}:{name}".encode("utf-8")).hexdigest()[:12],
        "owner": int(owner),
        "name": str(name or "Без названия").strip()[:120] or "Без названия",
        # До миллисекунд: два сохранения подряд попадали в одну секунду, и
        # список сортировался как придётся.
        "saved_at": datetime.now(tz=timezone.utc).isoformat(timespec="milliseconds"),
        "version": VERSION,
        "cadastral": [str(item)[:40] for item in (cadastral or [])][:20],
        "summary": summary or {},
        "payload": payload or {},
    }
    if share_code:
        record["share_code"] = share_code
    path = _project_path(owner, record["id"])
    # Запись через временный файл: воркеров два, и оборванная запись оставила
    # бы битый JSON вместо проекта.
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
    temporary.replace(path)
    return _project_card(record)


def project_list(owner: int) -> list[dict[str, Any]]:
    directory = _project_dir(owner)
    cards: list[dict[str, Any]] = []
    for path in directory.glob("*.json") if directory.is_dir() else []:
        # Анкета переехала в свой каталог, но у тех, кто заполнил её раньше,
        # файл ещё лежит здесь: список проектов о нём знать не должен.
        if path.name == "profile.json":
            continue
        try:
            cards.append(_project_card(json.loads(path.read_text(encoding="utf-8"))))
        except Exception:
            continue  # битый файл не должен прятать остальные
    cards.sort(key=lambda item: str(item.get("saved_at") or ""), reverse=True)
    return cards


def project_open(owner: int, project_id: str) -> dict[str, Any]:
    path = _project_path(owner, project_id)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Проект не найден")
    return json.loads(path.read_text(encoding="utf-8"))


# --- передача проекта другому человеку ---------------------------------------
# «А если я другому пользователю хочу скинуть проект, посчитанный мной? Не PDF,
# а именно набор параметров для дальнейшей работы» (владелец, 20.08.2026).
# Решение владельца: ссылку открывает любой, кто её получил, и живёт она
# бессрочно.
#
# Ссылка отдаёт снимок, а не сам проект: получатель видит то, что ему прислали,
# и правки автора задним числом эту картину не меняют. Копия, а не общий
# доступ — два человека, уверенные, что смотрят одно и то же, худший исход для
# финмодели, и изображать совместную работу нельзя.
#
# Раз ссылка вечная и открытая, её обязательно можно отозвать: у публичной
# ссылки без выключателя нет способа передумать. Код у проекта один и тот же —
# повторное «Поделиться» обновляет снимок по прежней ссылке, а не плодит их.
def _shared_dir() -> Path:
    return _PROJECTS_DIR.parent / "shared"


def _shared_path(code: str) -> Path:
    # Код приходит снаружи и превращается в имя файла: всё, кроме нашего
    # алфавита, — отказ, иначе «../../» уводит чтение за пределы каталога.
    if not re.fullmatch(r"[A-Za-z0-9_-]{8,64}", str(code or "")):
        raise HTTPException(status_code=400, detail="Неверная ссылка на проект")
    return _safe_child(_shared_dir(), f"{code}.json",
                       http_detail="Неверная ссылка на проект")


def _shared_author(owner: int) -> str:
    """Кем подписан снимок. Имя — из знакомства, если человек его оставил."""
    try:
        profile = profile_read(owner) or {}
    except Exception:
        return ""
    name = str(profile.get("name") or "").strip()
    company = str(profile.get("company") or "").strip()
    if name and company:
        return f"{name} ({company})"
    return name


def project_share(owner: int, project_id: str) -> dict[str, Any]:
    """Сделать снимок проекта и вернуть код ссылки."""
    record = project_open(owner, project_id)
    code = str(record.get("share_code") or "")
    if not re.fullmatch(r"[A-Za-z0-9_-]{8,64}", code):
        # Ссылка открыта для всех, у кого она есть, — значит, подобрать её быть
        # не должно: код случайный и длинный, а не порядковый номер.
        code = secrets.token_urlsafe(12)
    snapshot = {
        "code": code,
        "shared_at": datetime.now(tz=timezone.utc).isoformat(timespec="seconds"),
        "author": _shared_author(owner),
        "name": record.get("name"),
        "saved_at": record.get("saved_at"),
        "version": record.get("version"),
        "cadastral": record.get("cadastral") or [],
        "summary": record.get("summary") or {},
        "payload": record.get("payload") or {},
    }
    directory = _shared_dir()
    directory.mkdir(parents=True, exist_ok=True)
    path = _shared_path(code)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(snapshot, ensure_ascii=False), encoding="utf-8")
    temporary.replace(path)

    record["share_code"] = code
    own = _project_path(owner, project_id)
    temporary = own.with_suffix(".tmp")
    temporary.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
    temporary.replace(own)
    return {"code": code, "shared_at": snapshot["shared_at"], "name": snapshot["name"]}


def project_unshare(owner: int, project_id: str) -> dict[str, Any]:
    """Отозвать ссылку. Снимок удаляется, сам проект остаётся."""
    record = project_open(owner, project_id)
    code = str(record.get("share_code") or "")
    if code:
        try:
            _shared_path(code).unlink(missing_ok=True)
        except HTTPException:
            pass
    record.pop("share_code", None)
    path = _project_path(owner, project_id)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
    temporary.replace(path)
    return {"unshared": project_id}


def project_shared(code: str) -> dict[str, Any]:
    """Снимок по ссылке. Входа не требует — решение владельца."""
    path = _shared_path(code)
    if not path.is_file():
        raise HTTPException(
            status_code=404,
            detail="Ссылка не найдена: её отозвали или адрес набран с ошибкой.")
    return json.loads(path.read_text(encoding="utf-8"))


def project_delete(owner: int, project_id: str) -> dict[str, Any]:
    path = _project_path(owner, project_id)
    if path.is_file():
        path.unlink()
    return {"deleted": project_id}


class ProjectRequest(BaseModel):
    session: str = ""
    key: str = ""
    id: str = ""
    name: str = ""
    payload: dict[str, Any] = {}
    summary: dict[str, Any] = {}
    cadastral: list[str] = []


def _projects_forward(path: str, req: ProjectRequest) -> dict[str, Any] | None:
    """Render ничего не хранит: его дело — донести запрос до ядра."""
    url = _projects_remote_url(path)
    if not url:
        return None
    return _core_post(url, req.model_dump(), 30.0)


@app.get("/projects/status")
def projects_status() -> dict[str, Any]:
    """Есть ли смысл показывать кнопки: настроено ли хранилище и чем входить."""
    return {
        # Хранилище настроено, когда есть чем опознать владельца: подписью
        # сессии (токен бота) или списком администраторов под ключ.
        "configured": bool(_telegram_token()) or bool(usage_admin_ids()),
        "accepts_key": bool(_env_str("DEVELOPAID_ADMIN_KEY", "").strip()),
        "accepts_login": bool(_telegram_token()) and bool(_web_login_bot_username()),
        "remote": bool(_projects_remote_url("/projects/list")),
        "limit": _PROJECTS_LIMIT,
        # Расчёт экономики за входом. Без токена бота гейт выключен — страница
        # не должна запирать дверь, которую сервер не запирает.
        "calc_requires_login": bool(_telegram_token()),
    }


@app.post("/projects/save")
def projects_save(req: ProjectRequest) -> dict[str, Any]:
    forwarded = _projects_forward("/projects/save", req)
    if forwarded is not None:
        return forwarded
    owner = _project_owner(req.session, req.key)
    # Знакомство спрашивают там, где человек оставляет у нас работу, а не на
    # каждом запросе: расчёт открыт, а сохранённый проект уже чей-то. Спрашивают
    # у вошедшего через Telegram; админский ключ — это сам владелец, ему
    # представляться некому.
    if req.session and not profile_complete(profile_read(owner)):
        raise HTTPException(
            status_code=428,
            detail="Заполните знакомство: имя, компания и откуда узнали о нас.")
    return project_save(owner, req.name, req.payload, req.summary, req.cadastral, req.id)


@app.post("/projects/list")
def projects_list(req: ProjectRequest) -> dict[str, Any]:
    forwarded = _projects_forward("/projects/list", req)
    if forwarded is not None:
        return forwarded
    return {"projects": project_list(_project_owner(req.session, req.key))}


@app.post("/projects/open")
def projects_open(req: ProjectRequest) -> dict[str, Any]:
    forwarded = _projects_forward("/projects/open", req)
    if forwarded is not None:
        return forwarded
    return project_open(_project_owner(req.session, req.key), req.id)


@app.post("/projects/delete")
def projects_delete(req: ProjectRequest) -> dict[str, Any]:
    forwarded = _projects_forward("/projects/delete", req)
    if forwarded is not None:
        return forwarded
    return project_delete(_project_owner(req.session, req.key), req.id)


def _class_overrides_path(owner: int) -> Path:
    directory = _PROJECTS_DIR.parent / "class_overrides"
    directory.mkdir(parents=True, exist_ok=True)
    return directory / f"{int(owner)}.json"


def class_overrides_read(owner: int) -> dict[str, dict[str, float]]:
    try:
        raw = json.loads(_class_overrides_path(owner).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return raw if isinstance(raw, dict) else {}


def class_overrides_write(owner: int, payload: Any) -> dict[str, Any]:
    """Личные значения ставок классов — умолчание для НОВЫХ применений класса.

    Решение владельца (24.08.2026): база классов одна и общая, а человек может
    держать личную перекрышку. Поля валидируются по самому пресету — списка-
    копии нет; равное базе значение не хранится, чтобы файл не костенел, когда
    база меняется выпуском.
    """
    overrides: dict[str, dict[str, float]] = {}
    for class_key, fields in (payload or {}).items():
        preset = PROJECT_CLASS_PRESETS.get(str(class_key))
        if not preset or not isinstance(fields, dict):
            continue
        kept: dict[str, float] = {}
        for field, value in fields.items():
            if field == "label" or field not in preset:
                continue
            try:
                number = float(value)
            except (TypeError, ValueError):
                continue
            if not math.isfinite(number) or number <= 0:
                continue
            if abs(number - float(preset[field])) > 1e-9:
                kept[field] = number
        if kept:
            overrides[str(class_key)] = kept
    path = _class_overrides_path(owner)
    if overrides:
        path.write_text(json.dumps(overrides, ensure_ascii=False), encoding="utf-8")
    elif path.exists():
        path.unlink()
    return {"overrides": overrides}


@app.post("/classes/overrides/get", include_in_schema=False)
def classes_overrides_get(req: ProjectRequest) -> dict[str, Any]:
    forwarded = _projects_forward("/classes/overrides/get", req)
    if forwarded is not None:
        return forwarded
    owner = _project_owner(req.session, req.key)
    return {"overrides": class_overrides_read(owner)}


@app.post("/classes/overrides/save", include_in_schema=False)
def classes_overrides_save(req: ProjectRequest) -> dict[str, Any]:
    forwarded = _projects_forward("/classes/overrides/save", req)
    if forwarded is not None:
        return forwarded
    owner = _project_owner(req.session, req.key)
    return class_overrides_write(owner, req.payload)


@app.post("/projects/share")
def projects_share(req: ProjectRequest) -> dict[str, Any]:
    forwarded = _projects_forward("/projects/share", req)
    if forwarded is not None:
        return forwarded
    return project_share(_project_owner(req.session, req.key), req.id)


@app.post("/projects/unshare")
def projects_unshare(req: ProjectRequest) -> dict[str, Any]:
    forwarded = _projects_forward("/projects/unshare", req)
    if forwarded is not None:
        return forwarded
    return project_unshare(_project_owner(req.session, req.key), req.id)


@app.post("/projects/shared")
def projects_shared(req: ProjectRequest) -> dict[str, Any]:
    """Открыть присланный проект. Вход не нужен: ссылку открывает любой, кто её
    получил (решение владельца, 20.08.2026) — иначе её нельзя послать тому, кто
    сервисом ещё не пользовался, а именно так им и делятся."""
    forwarded = _projects_forward("/projects/shared", req)
    if forwarded is not None:
        return forwarded
    return project_shared(req.id)


# ---------------------------------------------------------------------------
# Знакомство: кто зашёл, как зовут, из какой компании и откуда узнал о нас
# (решение владельца, 18.08.2026).
#
# Личность подтверждает Telegram — вход уже доказывает, что за экраном живой
# аккаунт, и даёт chat_id. Анкета добавляет то, что подтвердить нечем и незачем
# делать вид, что подтверждено: имя, компанию, источник. Хранится рядом с
# проектами, тем же владельцем и в том же общем хранилище на ядре.

_PROFILE_FIELD_LIMIT = 200
_PROFILE_SOURCES = (
    "Телеграм-канал", "Рекомендация коллеги", "Поиск в интернете",
    "Конференция или мероприятие", "Соцсети", "Другое",
)


class ProfileRequest(BaseModel):
    session: str = ""
    key: str = ""
    name: str = ""
    company: str = ""
    role: str = ""
    source: str = ""
    contact: str = ""
    consent: bool = False


def _profile_path(owner: int) -> Path:
    # Анкета лежит рядом с проектами, но не среди них: список читает из
    # каталога владельца все *.json, и знакомство показывалось строкой в «Моих
    # проектах» — с именем человека, прочерками и кнопкой «Удалить» (боевая
    # проверка владельца, 18.08.2026).
    return _PROJECTS_DIR.parent / "profiles" / f"{int(owner)}.json"


def _profile_legacy_path(owner: int) -> Path:
    """Где анкета лежала до переезда. Читаем, пока не переписана."""
    return _project_dir(owner) / "profile.json"


def _profile_text(value: Any) -> str:
    # Поле приходит снаружи: режем по длине и убираем перевод строки, чтобы
    # анкета не превращалась в способ прислать нам страницу текста.
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text[:_PROFILE_FIELD_LIMIT]


def profile_read(owner: int) -> dict[str, Any]:
    for path in (_profile_path(owner), _profile_legacy_path(owner)):
        if not path.is_file():
            continue
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _profile_store(owner: int, record: dict[str, Any]) -> None:
    """Пишет анкету на новое место и убирает её со старого."""
    path = _profile_path(owner)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
    temporary.replace(path)
    _profile_legacy_path(owner).unlink(missing_ok=True)


def profile_complete(record: dict[str, Any]) -> bool:
    """Заполненной анкета считается, когда есть имя, компания и источник."""
    return all(_profile_text(record.get(key)) for key in ("name", "company", "source"))


def profile_write(owner: int, req: ProfileRequest) -> dict[str, Any]:
    name, company = _profile_text(req.name), _profile_text(req.company)
    source = _profile_text(req.source)
    if not name or not company or not source:
        raise HTTPException(
            status_code=400,
            detail="Заполните имя, компанию и откуда узнали о нас.")
    if not bool(req.consent):
        raise HTTPException(
            status_code=400,
            detail="Без согласия на обработку персональных данных анкету принять нельзя.")
    previous = profile_read(owner)
    record = {
        "chat_id": int(owner),
        "name": name,
        "company": company,
        "role": _profile_text(req.role),
        "source": source,
        "contact": _profile_text(req.contact),
        "telegram_name": _profile_text(previous.get("telegram_name")),
        "consent": True,
        "consent_at": previous.get("consent_at") or datetime.now().isoformat(timespec="seconds"),
        "created": previous.get("created") or datetime.now().isoformat(timespec="seconds"),
        "updated": datetime.now().isoformat(timespec="seconds"),
    }
    _profile_store(owner, record)
    return {"saved": True, "profile": record, "first_time": not bool(previous)}


def _profile_remember_telegram_name(owner: int, name: str) -> None:
    """Имя из Telegram — подсказка для анкеты, а не сама анкета."""
    name = _profile_text(name)
    if not name or not owner:
        return
    record = profile_read(owner)
    if _profile_text(record.get("telegram_name")) == name:
        return
    record["telegram_name"] = name
    record.setdefault("chat_id", int(owner))
    _profile_store(owner, record)


# Объявлена ВЫШЕ маршрутов, которые её принимают, и это не вкусовщина.
# Файл стоит на `from __future__ import annotations`: аннотация — строка, и
# FastAPI разбирает её в момент навешивания декоратора. Пока класс лежал ниже,
# имя в тот момент не существовало, тип не опознавался, и `req` уезжал в
# ПАРАМЕТРЫ СТРОКИ ЗАПРОСА вместо тела: всякий POST с телом получал 422
# «loc: query.req». Так молчали разом все три канала уведомлений — новые
# площадки КРТ, новые регистрации и нормативы; на проде 09.09.2026 в очереди
# ядра лежало 168 новостей, а бот каждые 15 минут получал отказ.
class WebLoginConfirmRequest(BaseModel):
    code: str = ""
    chat_id: int = 0
    sign: str = ""
    name: str = ""


def _profile_forward(path: str, req: ProfileRequest) -> dict[str, Any] | None:
    url = _projects_remote_url(path)
    if not url:
        return None
    return _core_post(url, req.model_dump(), 30.0)


@app.post("/profile/get")
def profile_get(req: ProfileRequest) -> dict[str, Any]:
    """Анкета владельца сессии: заполнена ли и чем подставить поля."""
    forwarded = _profile_forward("/profile/get", req)
    if forwarded is not None:
        return forwarded
    owner = _project_owner(req.session, req.key)
    record = profile_read(owner)
    return {
        "chat_id": owner,
        "complete": profile_complete(record),
        "profile": record,
        "sources": list(_PROFILE_SOURCES),
    }


@app.post("/profile/save")
def profile_save(req: ProfileRequest) -> dict[str, Any]:
    forwarded = _profile_forward("/profile/save", req)
    if forwarded is not None:
        # Ядро до api.telegram.org не достаёт, поэтому о новом знакомстве
        # владельцу сообщает тот хост, у которого есть Telegram.
        if forwarded.get("first_time"):
            _profile_announce(forwarded.get("profile") or {})
        return forwarded
    saved = profile_write(_project_owner(req.session, req.key), req)
    if saved.get("first_time"):
        _profile_announce(saved.get("profile") or {})
    return saved


def _profile_pending_path() -> Path:
    return _PROJECTS_DIR.parent / "profile_announcements.jsonl"


def _profile_remember_announcement(record: dict[str, Any]) -> None:
    """Кладёт знакомство в очередь для того, у кого есть Telegram.

    Анкета сохраняется на ядре, а до api.telegram.org достаёт только Render —
    сообщение «новая регистрация» иначе не ушло бы никуда. Ядро складывает
    знакомство на диск, Render забирает его тем же путём, каким пересылает
    проекты (18.08.2026).
    """
    try:
        path = _profile_pending_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:
        # Очередь — доставка, а не регистрация: анкета уже сохранена.
        pass


def _profile_take_announcements() -> list[dict[str, Any]]:
    """Забирает накопленные знакомства. Забрать может только один: файл
    переименовывается, и второй читатель получает его отсутствие."""
    path = _profile_pending_path()
    taken = path.with_suffix(".taken")
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
                records.append(json.loads(line))
            except Exception:
                continue
    finally:
        taken.unlink(missing_ok=True)
    return records


@app.post("/internal/profile/announcements")
def profile_announcements(req: WebLoginConfirmRequest) -> dict[str, Any]:
    """Знакомства, которые ещё некому было объявить. Только для своего хоста.

    Подпись — тем же токеном бота, что и подтверждение входа: секрет общий у
    ядра и Render, а посторонний его не знает. Отдаём разом и удаляем: это
    доставка, а не хранилище.
    """
    expected = _web_login_sign("profile-announcements", int(req.chat_id or 0))
    if not hmac.compare_digest(str(req.sign or "").encode("utf-8"),
                               expected.encode("utf-8")):
        raise HTTPException(status_code=403, detail="Подпись не сошлась.")
    return {"announcements": _profile_take_announcements(),
            "notifications": chat_notification_overrides()}


# --- новые площадки КРТ: с ядра в бот ---------------------------------------
# Каталог krt.mos.ru читается на ядре, и новизну решает `first_seen` там же.
# До api.telegram.org с ядра не дойти, поэтому здесь ровно тот же приём, что у
# знакомств: ядро копит, хост с вебхуком забирает по общей подписи и шлёт.
# Второго пути не заводим — он разошёлся бы с первым на первой же правке.
#
# Подписчики живут ТОЖЕ на ядре, рядом с профилями: диск бота на Render
# переживает только до следующей выкатки, и список подписок исчезал бы вместе
# с контейнером — молча, как исчезал журнал.


class SiteChatReportRequest(BaseModel):
    """Отчёт с площадки из группового чата — от бота к ядру.

    Модель объявлена ВЫШЕ своего маршрута намеренно: файл стоит на
    `from __future__ import annotations`, аннотация читается строкой в момент
    навешивания декоратора, и объявленная ниже модель молча уводит тело
    запроса в параметры строки. Это уже стоило нам трёх молчащих каналов
    уведомлений (09.09.2026).
    """

    chat_id: int = 0
    sign: str = ""
    title: str = ""
    text: str = ""
    project: str = ""
    taken_at: str = ""


class SitePhotoRequest(BaseModel):
    """Снимок из чата стройки — от бота к ядру (выше маршрута, см. выше)."""

    chat_id: int = 0
    sign: str = ""
    photo_id: str = ""
    data: str = ""
    day: str = ""
    at: str = ""
    author: str = ""
    caption: str = ""
    message_id: int = 0


# Имя проекта из чата становится ИМЕНЕМ КАТАЛОГА на диске (`_project_dir` у
# монитора). Внутри оно чистится, но чистка — это молчаливая правка чужого
# значения: «Гродненская/../../etc» превратилась бы в другое имя, и человек
# увидел бы отчёт не там, где ждал. Поэтому проверка стоит на границе и
# отказывает, а не исправляет. Разделители пути и «..» запрещены прямо.
_SITE_NAME_EXTRA = " -—–.,«»\"'()№"


def _site_project_name(value: Any) -> str:
    """Годное имя проекта или пустая строка. Пустая — это отказ, а не «любое».

    Имя не просто проверяется, а ПЕРЕСОБИРАЕТСЯ из разрешённых знаков и обязано
    совпасть с исходным: совпало — возвращаем собранное, разошлось — отказ. Так
    в путь уезжает строка, построенная нами, а не пришедшая снаружи, и при этом
    молчаливой правки чужого значения нет — её место занимает названный отказ.
    """
    name = str(value or "").strip()
    if not name or len(name) > 64 or ".." in name:
        return ""
    built = "".join(ch for ch in name if ch.isalnum() or ch in _SITE_NAME_EXTRA)
    if built != name:
        return ""
    return built


def _site_chats_path() -> Path:
    """Реестр «чат стройки → проект». На ядре, рядом с профилями.

    Диск бота на Render живёт до следующей выкатки, а привязка обязана её
    пережить: иначе после каждого выпуска отчёты падали бы в никуда, и
    выглядело бы это как «бот перестал читать».
    """
    return _PROJECTS_DIR.parent / "site_chats.json"


def _site_chats() -> dict[str, str]:
    try:
        raw = json.loads(_site_chats_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(raw, dict):
        return {}
    found: dict[str, str] = {}
    for key, value in (raw.get("chats") or {}).items():
        name = str(value or "").strip()
        try:
            number = int(key)
        except (TypeError, ValueError):
            continue
        safe = _site_project_name(name)
        if number and safe:
            found[str(number)] = safe
    return found


def _site_chat_project(chat_id: int) -> str:
    return _site_chats().get(str(int(chat_id or 0)), "")


def _site_chat_bind(chat_id: int, project: str) -> str:
    """Привязать чат к проекту. Пустое имя снимает привязку."""
    chats = _site_chats()
    key = str(int(chat_id or 0))
    name = _site_project_name(project)
    if str(project or "").strip() and not name:
        raise HTTPException(400, "Имя проекта не годится для каталога на диске: "
                                 "уберите косые черты и точки подряд.")
    if name:
        chats[key] = name
    else:
        chats.pop(key, None)
    path = _site_chats_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"chats": chats}, ensure_ascii=False, indent=1),
                    encoding="utf-8")
    return name


def _krt_subscribers_path() -> Path:
    return _PROJECTS_DIR.parent / "krt_subscribers.json"


def _krt_subscribers() -> list[int]:
    try:
        raw = json.loads(_krt_subscribers_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if not isinstance(raw, dict):
        return []
    found: list[int] = []
    for value in raw.get("chat_ids") or []:
        try:
            number = int(value)
        except (TypeError, ValueError):
            continue
        if number and number not in found:
            found.append(number)
    return sorted(found)


def _krt_subscribe(chat_id: int, wanted: bool) -> bool:
    """Включает или выключает подписку. Возвращает состояние ПОСЛЕ правки.

    Возвращаем состояние, а не «сделано»: повторное «подписаться» и настоящая
    подписка на экране обязаны выглядеть одинаково, иначе человек жмёт кнопку
    второй раз, чтобы убедиться, и снимает подписку.
    """
    chat_id = int(chat_id or 0)
    if not chat_id:
        return False
    current = _krt_subscribers()
    if wanted and chat_id not in current:
        current.append(chat_id)
    elif not wanted and chat_id in current:
        current.remove(chat_id)
    path = _krt_subscribers_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"chat_ids": sorted(set(current))},
                                   ensure_ascii=False), encoding="utf-8")
    except OSError as exc:
        raise HTTPException(status_code=503, detail=f"Подписка не сохранена: {exc}")
    return chat_id in current

# --- рассылки бота -----------------------------------------------------------
# Бот пишет в чат сам, без вопроса, по четырём поводам. Выключателя у них не
# было ни одного: «/krt выкл» отвечало «подписка выключена» и владельца при
# этом не трогало вовсе — рассылка шла ему по признаку владельца, мимо
# подписки, — а нормативы, регистрации и ежедневная сводка выключателя не имели
# в принципе. Молчать по просьбе человека обязана КАЖДАЯ рассылка, иначе
# «как сделать, чтобы не писал» отвечается «никак».
#
# Список объявлен один раз: копий у него нет ровно потому же, почему нет копии
# VERSION — их негде обновлять. Отсюда его берут и бот, и его команда, и свод.
NOTIFICATION_CHANNELS = [
    # ключ, имя в чате, кому идёт, пока человек не сказал иначе
    ("krt", "Новые площадки КРТ", "subscribers"),
    ("normatives", "Изменения в нормативной базе", "owner"),
    ("profiles", "Новые регистрации", "owner"),
    ("digest", "Ежедневная сводка обращений", "owner"),
]
NOTIFICATION_CHANNEL_KEYS = [key for key, _title, _who in NOTIFICATION_CHANNELS]


def notification_channel_title(channel: str) -> str:
    for key, title, _who in NOTIFICATION_CHANNELS:
        if key == channel:
            return title
    return channel


def _notifications_path() -> Path:
    return _PROJECTS_DIR.parent / "chat_notifications.json"


def chat_notification_overrides() -> dict[str, dict[str, bool]]:
    """Что человек сказал про рассылки. Ключа нет — он не говорил ничего.

    Три состояния, а не два: «не задано», «включено» и «выключено». Отсутствие
    ключа читать как «выключено» нельзя — тогда первая же выкатка обнулила бы
    подписки; читать как «включено» нельзя тем более — выключенное вернулось бы
    само.
    """
    try:
        raw = json.loads(_notifications_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    chats = raw.get("chats") if isinstance(raw, dict) else None
    if not isinstance(chats, dict):
        return {}
    found: dict[str, dict[str, bool]] = {}
    for chat, value in chats.items():
        if not isinstance(value, dict):
            continue
        state = {key: bool(flag) for key, flag in value.items()
                 if key in NOTIFICATION_CHANNEL_KEYS and isinstance(flag, bool)}
        if state:
            found[str(chat)] = state
    return found


def notification_enabled(channel: str, *, owner: bool = False,
                         subscribed: bool = False,
                         override: dict[str, bool] | None = None) -> bool:
    # `override` — состояние ЭТОГО чата целиком, а не один флаг. Поданный сюда
    # булев флаг читался бы как «человек ничего не говорил»: правило молчало
    # бы верно, а список состояний рядом показывал бы обратное.
    """Получает ли этот чат эту рассылку. Один ответ на оба хоста.

    Решает ядро, а рассылает бот, и файла с решением у бота нет — поэтому
    правило принимает уже прочитанные признаки: ядро подаёт свои файлы, бот —
    карту, полученную вместе с очередью. Две реализации этого правила однажды
    разошлись бы, и обе выглядели бы верными.
    """
    if override is not None and not isinstance(override, dict):
        raise TypeError("override — состояние чата целиком, а не один флаг")
    said = (override or {}).get(channel)
    if said is not None:
        return bool(said)
    who = next((w for key, _title, w in NOTIFICATION_CHANNELS if key == channel), "owner")
    if who == "subscribers":
        # Владелец получает каталог и без подписки: он и есть тот, ради кого
        # тот читается. Но это УМОЛЧАНИЕ, а не признак владельца — сказанное
        # им «выключить» сильнее.
        return bool(subscribed or owner)
    return bool(owner)


def chat_notification_set(chat_id: int, channel: str, wanted: bool) -> bool:
    """Записывает сказанное человеком. Возвращает состояние ПОСЛЕ правки.

    Возвращаем состояние, а не «сделано»: повторное «выключить» и настоящая
    отписка на экране обязаны выглядеть одинаково.
    """
    chat_id = int(chat_id or 0)
    if not chat_id:
        return False
    if channel not in NOTIFICATION_CHANNEL_KEYS:
        raise HTTPException(status_code=400, detail=f"Нет такой рассылки: {channel}")
    chats = chat_notification_overrides()
    state = dict(chats.get(str(chat_id)) or {})
    state[channel] = bool(wanted)
    chats[str(chat_id)] = state
    path = _notifications_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"chats": chats}, ensure_ascii=False, indent=1),
                        encoding="utf-8")
    except OSError as exc:
        raise HTTPException(status_code=503, detail=f"Настройка не сохранена: {exc}")
    return bool(wanted)


def krt_recipients() -> list[int]:
    """Кому идут новинки каталога, кроме владельцев.

    Подписка живёт двумя файлами по историческим причинам: прежний список
    подписчиков и сказанное человеком. Второй сильнее — иначе выключивший
    рассылку продолжал бы её получать, пока лежит в первом.
    """
    overrides = chat_notification_overrides()
    found = {int(chat) for chat in _krt_subscribers()}
    for chat, state in overrides.items():
        said = state.get("krt")
        if said is None:
            continue
        try:
            number = int(chat)
        except (TypeError, ValueError):
            continue
        if said:
            found.add(number)
        else:
            found.discard(number)
    return sorted(number for number in found if number)


class ChatNotificationRequest(BaseModel):
    chat_id: int = 0
    sign: str = ""
    channel: str = ""
    # None — «просто скажи, как сейчас». Узнавать состояние записью нельзя:
    # не дошедший второй запрос оставил бы человека с чужой настройкой.
    on: bool | None = None


class KrtSubscribeRequest(BaseModel):
    chat_id: int = 0
    sign: str = ""
    # None — «просто скажи, подписан ли». Узнавать состояние записью нельзя:
    # переключатель, который сперва отписывает, чтобы прочитать, оставляет
    # человека отписанным, если второй запрос не дошёл.
    on: bool | None = None


@app.post("/internal/krt/announcements")
def krt_announcements(req: WebLoginConfirmRequest) -> dict[str, Any]:
    """Новые площадки КРТ и кому их объявить. Только для своего хоста.

    Отдаём подписчиков тем же ответом, что и новинки: два запроса ради одного
    сообщения — это два места, где список может разъехаться со своей рассылкой.

    Очередь считает тот же `KrtRanking`, что помечает площадки «новыми» на
    экране: второй ответ на вопрос «это новое?» однажды разошёлся бы с первым,
    и в чат приехало бы не то, что видно в каталоге.
    """
    expected = _web_login_sign("krt-announcements", int(req.chat_id or 0))
    if not hmac.compare_digest(str(req.sign or "").encode("utf-8"),
                               expected.encode("utf-8")):
        raise HTTPException(status_code=403, detail="Подпись не сошлась.")
    take = getattr(app.state, "krt_announcements_take", None)
    if take is None:
        # Модуль торгов не установлен — сказать это честно. Пустой список
        # читался бы как «новых площадок нет».
        raise HTTPException(status_code=503,
                            detail="Каталог КРТ на этом хосте не установлен.")
    return {"announcements": take(), "subscribers": krt_recipients(),
            "notifications": chat_notification_overrides()}


@app.post("/internal/normatives/announcements")
def normatives_announcements(req: WebLoginConfirmRequest) -> dict[str, Any]:
    """Изменения в нормативной базе — для хоста с вебхуком. Подпись общая.

    Проверку источников ведёт ядро: до правовых порталов ходит оно. До
    api.telegram.org достаёт только хост с ботом, поэтому ядро копит находки,
    а он их объявляет — тот же путь, что у знакомств и новинок каталога КРТ.
    """
    expected = _web_login_sign("normatives-announcements", int(req.chat_id or 0))
    if not hmac.compare_digest(str(req.sign or "").encode("utf-8"),
                               expected.encode("utf-8")):
        raise HTTPException(status_code=403, detail="Подпись не сошлась.")
    take = getattr(app.state, "normatives_announcements_take", None)
    if take is None:
        # Реестра на этом хосте нет — сказать это честно: пустой список
        # читался бы как «в нормативной базе ничего не менялось».
        raise HTTPException(status_code=503,
                            detail="Нормативный реестр на этом хосте не установлен.")
    return {"announcements": take(), "notifications": chat_notification_overrides()}


# Скрыт из схемы, как и все маршруты монитора: это дорога хост-хост под общей
# подписью, а не публичный метод. Правило держит
# `test_the_routes_are_hidden_and_gated` — оно и поймало пропуск на CI.
@app.post("/internal/monitor/daily", include_in_schema=False)
def internal_monitor_daily(req: SiteChatReportRequest) -> dict[str, Any]:
    """Отчёт из чата стройки: бот на Render принял, ядро сохранило.

    Ядро до api.telegram.org не достаёт, а монитор живёт на ядре — значит
    дорога та же, что у уведомлений: подпись общим токеном бота. Разбор при
    этом один на всех (`store_daily_report`), второго не заводим: он однажды
    разошёлся бы с тем, что читает маршрут загрузки.
    """
    expected = _web_login_sign("monitor-daily", int(req.chat_id or 0))
    if not hmac.compare_digest(str(req.sign or "").encode("utf-8"),
                               expected.encode("utf-8")):
        raise HTTPException(status_code=403, detail="Подпись не сошлась.")
    if req.project:
        return {"bound": _site_chat_bind(int(req.chat_id or 0), req.project)}
    project = _site_project_name(_site_chat_project(int(req.chat_id or 0)))
    if not project:
        # «Чат не привязан» — это ответ, а не отказ: человеку надо сказать, чем
        # привязать, иначе отчёт молча падает в никуда и выглядит принятым.
        return {"bound": ""}
    import developaid_monitor_daily as daily

    try:
        stored = daily.store_daily_report(project, req.text, req.taken_at or None)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return {"bound": project, "stored": stored}


class SalesChatRequest(BaseModel):
    """Отчёт отдела продаж из группового чата — от бота к ядру.

    Модель — выше маршрута, по той же причине, что у `SiteChatReportRequest`.
    """

    chat_id: int = 0
    sign: str = ""
    title: str = ""
    author: str = ""
    text: str = ""
    taken_at: str = ""


@app.post("/internal/monitor/sales-chat", include_in_schema=False)
def internal_monitor_sales_chat(req: SalesChatRequest) -> dict[str, Any]:
    """Отчёт из чата отдела продаж: бот принял, ядро дописало в источник.

    Чат привязан к проекту Монитора той же командой `/site`; отчёт ложится в
    проект отчёта о продажах, связанный с ним на странице сводки, — источник
    «чат отдела продаж», тот же, что даёт выгрузка чата. Подпись — своим кодом.
    """
    expected = _web_login_sign("monitor-sales", int(req.chat_id or 0))
    if not hmac.compare_digest(str(req.sign or "").encode("utf-8"),
                               expected.encode("utf-8")):
        raise HTTPException(status_code=403, detail="Подпись не сошлась.")
    project = _site_project_name(_site_chat_project(int(req.chat_id or 0)))
    if not project:
        return {"bound": "", "sales_project": ""}
    import developaid_management_report as management_report
    from market_search import salesroom, sales_store

    sales_project = ((management_report.sales_link(project) or {}).get("sales_project") or "")
    if not sales_project:
        # Проект Монитора не связан с отчётом о продажах — дописывать некуда.
        # Это ответ, а не отказ: в /status видно, чего не хватает.
        return {"bound": project, "sales_project": ""}
    where = sales_store.default_dir()
    kept = sales_store.load(where, sales_project)
    current = ((kept.get("sources") or {}).get("salesroom") or {}).get("data")
    day = str(req.taken_at or "")[:10]
    updated = salesroom.append_message(current, day, str(req.author or ""), req.text,
                                       str(req.title or ""))
    sales_store.save(where, sales_project, {"salesroom": updated},
                     f"чат «{req.title or ''}» — бот")
    return {"bound": project, "sales_project": sales_project,
            "messages": len(updated.get("messages") or [])}


@app.post("/internal/monitor/photo", include_in_schema=False)
def internal_monitor_photo(req: SitePhotoRequest) -> dict[str, Any]:
    """Снимок из чата стройки: бот на Render скачал, ядро сохранило.

    Подпись — общим токеном бота, как у отчётов (`internal_monitor_daily`),
    но своим кодом: подпись отчёта не должна открывать дорогу файлам.
    """
    expected = _web_login_sign("monitor-photo", int(req.chat_id or 0))
    if not hmac.compare_digest(str(req.sign or "").encode("utf-8"),
                               expected.encode("utf-8")):
        raise HTTPException(status_code=403, detail="Подпись не сошлась.")
    project = _site_project_name(_site_chat_project(int(req.chat_id or 0)))
    if not project:
        return {"bound": ""}
    import developaid_site_photos as site_photos

    try:
        data = base64.b64decode(req.data or "", validate=True)
        stored = site_photos.store(project, data, req.photo_id, req.day, req.author,
                                   req.caption, req.at, req.message_id)
    except ValueError as exc:  # и binascii.Error — он подкласс ValueError
        raise HTTPException(400, str(exc))
    return {"bound": project, "stored": {k: v for k, v in stored.items() if k != "data"}}


@app.post("/internal/krt/subscribe")
def krt_subscribe(req: KrtSubscribeRequest) -> dict[str, Any]:
    """Подписка на новые площадки КРТ. Подпись — тем же общим токеном."""
    expected = _web_login_sign("krt-subscribe", int(req.chat_id or 0))
    if not hmac.compare_digest(str(req.sign or "").encode("utf-8"),
                               expected.encode("utf-8")):
        raise HTTPException(status_code=403, detail="Подпись не сошлась.")
    chat_id = int(req.chat_id or 0)
    if req.on is None:
        return {"subscribed": notification_enabled(
            "krt", subscribed=chat_id in _krt_subscribers(),
            override=chat_notification_overrides().get(str(chat_id)))}
    # Пишем в общее хранилище настроек, а не в прежний список: два ответа на
    # «получает ли этот чат каталог» однажды разошлись бы, и оба выглядели бы
    # верными. Прежний список остаётся читаемым — подписавшиеся до этой правки
    # не теряют подписку.
    return {"subscribed": chat_notification_set(chat_id, "krt", bool(req.on))}


@app.post("/internal/notifications")
def chat_notifications(req: ChatNotificationRequest) -> dict[str, Any]:
    """Что бот шлёт этому чату сам, без вопроса. Подпись — общим токеном.

    `chat_id=0` — отдать всю карту: бот забирает её раз в круг и решает по ней
    про владельцев, у которых своего файла нет.
    """
    expected = _web_login_sign("chat-notifications", int(req.chat_id or 0))
    if not hmac.compare_digest(str(req.sign or "").encode("utf-8"),
                               expected.encode("utf-8")):
        raise HTTPException(status_code=403, detail="Подпись не сошлась.")
    chat_id = int(req.chat_id or 0)
    if not chat_id:
        return {"chats": chat_notification_overrides()}
    if req.on is not None and req.channel:
        chat_notification_set(chat_id, str(req.channel), bool(req.on))
    return {"chat": chat_notification_overrides().get(str(chat_id)) or {},
            "subscribed": chat_id in _krt_subscribers()}


def _profile_announce(record: dict[str, Any]) -> None:
    """Новое знакомство — в чат владельцу. Молча, если сообщить нечем."""
    # Сказанное человеком сильнее признака владельца и на этом пути тоже:
    # выключатель, действующий только на одной из двух дорог, не выключатель.
    overrides = chat_notification_overrides()
    everyone = usage_admin_ids()
    admins = {chat for chat in everyone
              if notification_enabled("profiles", owner=True,
                                      override=overrides.get(str(chat)))}
    if everyone and not admins:
        # Выключено всеми, кому это шлют. Очередь НЕ копим: отложенное
        # молчание — это та же рассылка, только позже.
        return
    if not admins or not _telegram_token() or not _telegram_webhook_enabled():
        # Telegram здесь недоступен — знакомство ждёт того, у кого он есть.
        _profile_remember_announcement(record)
        return
    _telegram_send_profile_card(record, admins)


def _telegram_send_profile_card(record: dict[str, Any], admins: set[int]) -> None:
    lines = [
        "<b>Новая регистрация</b>",
        f"Имя: {html.escape(str(record.get('name') or '—'))}",
        f"Компания: {html.escape(str(record.get('company') or '—'))}",
    ]
    if record.get("role"):
        lines.append(f"Роль: {html.escape(str(record['role']))}")
    lines.append(f"Узнал(а) о нас: {html.escape(str(record.get('source') or '—'))}")
    if record.get("contact"):
        lines.append(f"Контакт: {html.escape(str(record['contact']))}")
    if record.get("telegram_name"):
        lines.append(f"Telegram: {html.escape(str(record['telegram_name']))}")
    lines.append(f"chat_id: <code>{int(record.get('chat_id') or 0)}</code>")
    for admin in sorted(admins):
        try:
            _telegram_send_message(admin, "\n".join(lines))
        except Exception:
            # Уведомление — не часть регистрации: анкета уже сохранена.
            pass


# ---------------------------------------------------------------------------
# Вход на сайт через телеграм-бота (решение владельца, 15.08.2026).
#
# Личность пользователя уже есть у бота — chat_id: на ней держатся проекты,
# сессии мини-приложения и журнал обращений. Сайт получает ту же личность без
# второй регистрации: страница просит одноразовый код, человек жмёт Start в
# боте по ссылке t.me/<бот>?start=login_<код>, бот подтверждает код, страница
# коротким опросом забирает подписанную сессию — ту же, что у мини-приложения,
# поэтому и проверка одна (`_telegram_verify_session`).
#
# Коды живут на ядре, как и проекты: бот на Render доносит подтверждение
# внутренним вызовом с подписью токеном бота, страница забирает сессию через
# пересылку — тем же путём, что /projects/*. Код одноразовый и короткоживущий,
# сессия входа длинная. Вход мягкий: смотреть и считать можно без него, за
# входом — сохранение проектов, Платон и PDF (они стоят денег или хранят
# данные). Без TELEGRAM_BOT_TOKEN весь механизм честно выключен: проверять
# подпись нечем, и порядок остаётся прежним.
# ---------------------------------------------------------------------------

_WEB_LOGIN_TTL_SECONDS = 300
_WEB_LOGIN_SESSION_SECONDS = 30 * 86400


def _web_login_dir() -> Path:
    directory = _PROJECTS_DIR.parent / "web_login"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _web_login_path(code: str) -> Path:
    # Код приходит снаружи: всё, кроме нашего алфавита, — отказ, иначе «../»
    # уводит запись за пределы каталога (то же правило, что у проектов).
    if not re.fullmatch(r"[0-9a-f]{12}", str(code or "")):
        raise HTTPException(status_code=400, detail="Неверный код входа.")
    return _safe_child(_web_login_dir(), f"{code}.json",
                       http_detail="Неверный код входа.")


def _web_login_sign(code: str, chat_id: int) -> str:
    """Подпись внутреннего подтверждения: бот на Render и ядро делят токен."""
    token = _telegram_token()
    if not token:
        raise HTTPException(
            status_code=503,
            detail="TELEGRAM_BOT_TOKEN не задан — вход через бота недоступен.")
    raw = f"web-login:{code}:{int(chat_id)}".encode("utf-8")
    digest = hmac.new(token.encode("utf-8"), raw, hashlib.sha256).digest()[:20]
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def _web_login_bot_username() -> str:
    # Ядро до api.telegram.org не достаёт (направление закрыто), getMe там не
    # проходит — имя бота задаётся переменной. На Render его знает getMe.
    return (str(_TELEGRAM_RUNTIME.get("username") or "")
            or _env_str("TELEGRAM_BOT_USERNAME", "").strip())


class WebLoginClaimRequest(BaseModel):
    code: str = ""


class FeedbackRequest(BaseModel):
    role: str = ""
    region: str = ""
    ratings: dict[str, Any] = {}
    problems: dict[str, Any] = {}
    impression: str = ""
    mistakes: str = ""
    projects: list[str] = []
    session: str = ""
    source: str = ""


def _feedback_clean(req: FeedbackRequest) -> dict[str, Any]:
    """Разбор анкеты: наружу выходит только то, о чём спрашивали.

    Поля приходят из браузера, то есть могут быть любыми. Профиль сверяется со
    списком, оценки — целые от одного до пяти, всё остальное режется по длине.
    Пустая оценка — это «не пользовался», и она не единица: непользовавшийся,
    засчитанный единицей, портит средние сильнее, чем отсутствие ответа.
    """
    groups = {group[0] for group in FEEDBACK_GROUPS}
    ratings: dict[str, int] = {}
    for key, value in (req.ratings or {}).items():
        if str(key) not in FEEDBACK_ITEMS:
            continue
        try:
            score = int(value)
        except (TypeError, ValueError):
            continue
        if 1 <= score <= 5:
            ratings[str(key)] = score
    # Комментарий — один на раздел: девять полей ввода это работа, за которую
    # никто не подписывался, а один на раздел человек пишет там, где ему есть
    # что сказать.
    problems = {str(key): str(value).strip()[:_USAGE_TEXT_LIMIT]
                for key, value in (req.problems or {}).items()
                if str(key) in groups and str(value or "").strip()}
    return {
        "role": req.role if req.role in FEEDBACK_ROLES else "",
        "region": req.region if req.region in FEEDBACK_REGIONS else "",
        "ratings": ratings,
        "problems": problems,
        "impression": str(req.impression or "").strip()[:_USAGE_TEXT_LIMIT],
        "mistakes": str(req.mistakes or "").strip()[:_USAGE_TEXT_LIMIT],
        "projects": [str(name).strip()[:80] for name in (req.projects or [])[:20]
                     if str(name or "").strip()],
        "source": _telegram_invite_source(req.source),
    }


@app.post("/feedback")
def feedback_submit(req: FeedbackRequest) -> dict[str, Any]:
    """Анкета обратной связи. Вход не требуется: гейт мягкий, а мнение того,
    кто не вошёл, нужно не меньше — он и бросил, скорее всего, раньше."""
    data = _feedback_clean(req)
    if not (data["ratings"] or data["impression"] or data["mistakes"]):
        raise HTTPException(status_code=400, detail="Анкета пустая.")
    usage_track("survey", surface="site",
                chat_id=_web_identity_chat_id(req.session),
                text=data["impression"], **data)
    return {"ok": True}


class InternalSummaryRequest(BaseModel):
    days: int = 30
    sign: str = ""


class InternalUserRequest(BaseModel):
    chat: int = 0
    name: str = ""
    surface: str = "telegram"
    kind: str = ""
    sign: str = ""


@app.post("/internal/user/touch")
def internal_user_touch(req: InternalUserRequest) -> dict[str, Any]:
    """Человек из бота — в реестр на ядре.

    `usage_track` пишет реестр там, где обслужен запрос, а бот живёт на Render:
    его пользователи обнулялись каждой выкаткой ровно так же, как анкеты
    (замечание владельца, 23.08.2026 — «в боте тоже всё обнуляется, не видно
    никакой истории»). Реестр один и лежит на ядре, рядом с профилями.
    """
    chat = int(req.chat or 0)
    expected = _web_login_sign("user-touch", chat)
    if not hmac.compare_digest(str(req.sign or "").encode("utf-8"),
                               expected.encode("utf-8")):
        raise HTTPException(status_code=403, detail="Подпись не сошлась.")
    if not chat:
        raise HTTPException(status_code=400, detail="Нужен chat.")
    users_touch(chat, surface=str(req.surface or "telegram"),
                kind=str(req.kind or ""), name=str(req.name or ""))
    return {"ok": True}


class InternalUsersListRequest(BaseModel):
    sign: str = ""


@app.post("/internal/users/list")
def internal_users_list(req: InternalUsersListRequest) -> dict[str, Any]:
    """Весь реестр людей — чтобы бот восстановил историю после выкатки.

    Реестр бота лежит в sqlite на Render и умирает вместе с контейнером:
    «в боте тоже всё обнуляется, не видно никакой истории» (владелец,
    23.08.2026). Ядро отдаёт свою копию, и бот на старте наполняет из неё свою
    таблицу — история перестаёт зависеть от того, когда была последняя выкатка.
    """
    expected = _web_login_sign("users-list", 0)
    if not hmac.compare_digest(str(req.sign or "").encode("utf-8"),
                               expected.encode("utf-8")):
        raise HTTPException(status_code=403, detail="Подпись не сошлась.")
    records: list[dict[str, Any]] = []
    try:
        paths = sorted(_users_dir().glob("*.json"))
    except OSError:
        paths = []
    for path in paths:
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(record, dict) and int(record.get("chat") or 0):
            records.append(record)
    return {"users": records}


class InternalSurveyRequest(BaseModel):
    record: dict[str, Any] = {}
    sign: str = ""


@app.post("/internal/survey/save")
def internal_survey_save(req: InternalSurveyRequest) -> dict[str, Any]:
    """Анкета из бота — на хранение к ядру.

    Бот живёт на Render, где диск кончается вместе с контейнером: анкета,
    заполненная в чате, переживала ровно до следующей выкатки. Хранилище одно
    и лежит на ядре, рядом с профилями; подпись — общим токеном бота, как у
    свода: анкета несёт слова человека и посторонним не отдаётся.
    """
    record = req.record if isinstance(req.record, dict) else {}
    chat = int(record.get("chat") or 0)
    expected = _web_login_sign("survey-save", chat)
    if not hmac.compare_digest(str(req.sign or "").encode("utf-8"),
                               expected.encode("utf-8")):
        raise HTTPException(status_code=403, detail="Подпись не сошлась.")
    record.setdefault("kind", "survey")
    name = survey_store(record)
    if not name:
        raise HTTPException(status_code=500, detail="Анкета не сохранена.")
    users_touch(chat, surface=str(record.get("surface") or "telegram"),
                kind="survey", name=str(record.get("name") or ""))
    return {"ok": True, "stored": name}


@app.post("/internal/usage/summary")
def internal_usage_summary(req: InternalSummaryRequest) -> dict[str, Any]:
    """Свод учёта и анкет этого хоста — для того, у кого есть Telegram.

    Журнал пишется там, где обслужен запрос: сайт живёт на ядре, бот на Render,
    и `/survey` в боте видел только свою половину — анкеты, заполненные на
    сайте, не показывались никому (18.08.2026). Подпись — общим токеном бота,
    как у подтверждения входа: свод несёт свободные тексты людей и посторонним
    не отдаётся.
    """
    days = max(1, min(365, int(req.days or 30)))
    expected = _web_login_sign("usage-summary", days)
    if not hmac.compare_digest(str(req.sign or "").encode("utf-8"),
                               expected.encode("utf-8")):
        raise HTTPException(status_code=403, detail="Подпись не сошлась.")
    return {"usage": usage_summary(days), "survey": survey_summary(days),
            # Знакомства лежат здесь же, на ядре: у бота их нет вовсе, а
            # вопрос «сколько зарегистрировалось» задают ему.
            "registry": profile_registry_summary(days),
            # Пользователи — вход через телеграм. Реестр лежит на ядре и
            # переживает выкатку, в отличие от sqlite бота на Render.
            "users": users_registry_summary(days),
            # Сырые события — чтобы выгрузка собиралась из обеих половин, а не
            # из той, что пережила последнюю выкатку.
            "events": usage_events(days)}


@app.get("/auth/telegram/qr", include_in_schema=False)
def web_login_qr(code: str = "") -> Response:
    """QR со ссылкой входа: подтвердить с телефона, когда на компьютере нет
    Telegram.

    На десктопе без приложения ссылка `t.me/…` открывает страницу «поставьте
    Telegram», и вход упирается в тупик (замечание владельца, 18.08.2026).
    Код тот же самый и живёт те же минуты — QR не даёт новых прав, он лишь
    переносит ссылку на другой экран.
    """
    if not re.fullmatch(r"[0-9a-f]{6,64}", str(code or "")):
        raise HTTPException(status_code=400, detail="Код входа не похож на код.")
    username = _web_login_bot_username()
    if not username:
        raise HTTPException(status_code=503, detail="Имя бота неизвестно: задайте TELEGRAM_BOT_USERNAME.")
    try:
        import segno
    except Exception:
        # Образ собран без библиотеки — это не повод ронять вход: страница
        # покажет ссылку, а QR спрячет.
        raise HTTPException(status_code=503, detail="QR на этом сервере не собран.")
    buffer = io.BytesIO()
    segno.make(f"https://t.me/{username}?start=login_{code}", error="m").save(
        buffer, kind="svg", scale=4, border=2, dark="#111111")
    return Response(buffer.getvalue(), media_type="image/svg+xml",
                    headers={"Cache-Control": "no-store"})


@app.post("/auth/telegram/start")
def web_login_start() -> dict[str, Any]:
    """Одноразовый код входа и ссылка на бота."""
    if not _telegram_token():
        raise HTTPException(
            status_code=503,
            detail="Вход через Telegram не настроен на этом сервере.")
    remote = _projects_remote_url("/auth/telegram/start")
    if remote:
        data = _core_post(remote, {}, 30.0)
    else:
        code = hashlib.sha256(os.urandom(32)).hexdigest()[:12]
        path = _web_login_path(code)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps({"created": time.time()}), encoding="utf-8")
        temporary.replace(path)
        data = {"code": code}
    username = _web_login_bot_username()
    if not username:
        raise HTTPException(
            status_code=503,
            detail="Имя бота неизвестно: задайте TELEGRAM_BOT_USERNAME.")
    return {
        "code": data["code"],
        "link": f"https://t.me/{username}?start=login_{data['code']}",
        "display_code": _web_login_display(data["code"]),
        "ttl_seconds": _WEB_LOGIN_TTL_SECONDS,
    }


def _web_login_display(code: str) -> str:
    """Код входа так, как его сверяют глазами: на странице и в боте одинаково.

    Сверка нужна, потому что ссылку входа может прислать чужой человек: он
    запросил код у себя, и если бот подтвердит вход молча, сессию заберёт он.
    """
    code = str(code or "").lower()
    return "-".join(code[i:i + 4] for i in range(0, len(code), 4)).upper()


def _web_login_record(code: str) -> tuple[Path, dict[str, Any]]:
    path = _web_login_path(code)
    if not path.is_file():
        raise HTTPException(
            status_code=404,
            detail="Код входа не найден или истёк — запросите вход на сайте заново.")
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        record = {}
    if time.time() - float(record.get("created") or 0) > _WEB_LOGIN_TTL_SECONDS:
        path.unlink(missing_ok=True)
        raise HTTPException(
            status_code=410,
            detail="Код входа истёк — запросите вход на сайте заново.")
    return path, record


def _web_login_confirm(code: str, chat_id: int, name: str = "") -> dict[str, Any]:
    """Связывает код с chat_id. Зовётся ботом — локально или через ядро.

    Имя из Telegram передаётся тем же запросом: анкета знакомства подставляет
    его в поле, чтобы человек правил, а не набирал.
    """
    remote = _projects_remote_url("/auth/telegram/confirm")
    if remote:
        return _core_post(
            remote,
            {"code": code, "chat_id": int(chat_id), "name": str(name or ""),
             "sign": _web_login_sign(code, chat_id)},
            30.0)
    path, record = _web_login_record(code)
    record["chat_id"] = int(chat_id)
    record["confirmed"] = time.time()
    _profile_remember_telegram_name(int(chat_id), name)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(record), encoding="utf-8")
    temporary.replace(path)
    return {"ok": True}


@app.post("/auth/telegram/confirm")
def web_login_confirm(req: WebLoginConfirmRequest) -> dict[str, Any]:
    """Внутренний приём подтверждения от бота: подпись — токеном бота."""
    expected = _web_login_sign(req.code, req.chat_id)
    # Байтами: `compare_digest` отказывается от строк с не-ASCII, а снаружи
    # может прийти что угодно.
    if not hmac.compare_digest(str(req.sign or "").encode("utf-8"),
                               expected.encode("utf-8")):
        raise HTTPException(status_code=403, detail="Подпись подтверждения не сошлась.")
    if not int(req.chat_id or 0):
        raise HTTPException(status_code=400, detail="Пустой chat_id.")
    return _web_login_confirm(req.code, int(req.chat_id), req.name)


@app.post("/auth/telegram/claim")
def web_login_claim(req: WebLoginClaimRequest) -> dict[str, Any]:
    """Страница забирает сессию по коду. Код сгорает при выдаче."""
    remote = _projects_remote_url("/auth/telegram/claim")
    if remote:
        return _core_post(remote, {"code": req.code}, 30.0)
    path, record = _web_login_record(req.code)
    chat_id = int(record.get("chat_id") or 0)
    if not chat_id:
        return {"ready": False}
    path.unlink(missing_ok=True)
    session = _telegram_session(chat_id, [], lifetime_seconds=_WEB_LOGIN_SESSION_SECONDS)
    profile = profile_read(chat_id)
    return {"ready": True, "session": session, "chat_id": chat_id,
            "profile_complete": profile_complete(profile), "profile": profile}


def _web_identity_chat_id(session: str) -> int:
    """chat_id из сессии входа; 0 — сессии нет или подпись не сошлась."""
    if not str(session or "").strip():
        return 0
    try:
        return int(_telegram_verify_session(session).get("chat_id") or 0)
    except HTTPException:
        return 0


def _web_access_allowed(session: str, key: str) -> bool:
    """Пропуск к платным поверхностям: сессия входа или ключ администратора."""
    if _web_identity_chat_id(session):
        return True
    secret = _env_str("DEVELOPAID_ADMIN_KEY", "").strip()
    return bool(secret and key
                and hmac.compare_digest(str(key).encode("utf-8"), secret.encode("utf-8")))


def team_chat_ids() -> set[int]:
    """Команда владельца: администраторы и явный список `DEVELOPAID_TEAM_IDS`
    (по умолчанию пуст — решение владельца 22.10.2026)."""
    ids = set(usage_admin_ids())
    for piece in re.split(r"[,\s;]+", _env_str("DEVELOPAID_TEAM_IDS", "") or ""):
        if piece.strip().lstrip("-").isdigit():
            ids.add(int(piece.strip()))
    return ids


def team_access_allowed(session: str, key: str) -> bool:
    """«Команда владельца» — отдельный от «вошёл» уровень: данные проектов
    владельца (монитор, сводка руководству, споры, бюджеты, рассылка) не для
    клиентов. Команда — ключ администратора, ключ кабинета рынка или вход
    человека из `team_chat_ids()`. Демо-доступ проверяющих — никогда."""
    secret = _env_str("DEVELOPAID_ADMIN_KEY", "").strip()
    if secret and key and hmac.compare_digest(str(key).encode("utf-8"), secret.encode("utf-8")):
        return True
    team_key = globals().get("_access_team_key")
    if callable(team_key) and team_key():
        return True
    chat = _web_identity_chat_id(session)
    demo = globals().get("demo_chat")
    if not chat or (callable(demo) and demo(chat)):
        return False
    return chat in team_chat_ids()


def _require_team_access(session: str, key: str, what: str) -> None:
    """Пропуск к данным команды. Без токена бота механизм выключен, как и вход."""
    if not _telegram_token():
        return
    if team_access_allowed(session, key):
        return
    if _web_identity_chat_id(session):
        raise HTTPException(
            status_code=403,
            detail=(f"{what} — раздел для команды владельца DevelopAid. Вход через Telegram "
                    "открывает расчёт и ваш личный кабинет, а данные проектов команды закрыты. "
                    "Если вы в команде, попросите владельца добавить вас."))
    _require_web_access("", "", what)


def _require_web_access(session: str, key: str, what: str) -> None:
    # Без токена бота проверять подпись нечем — механизм честно выключен, и
    # поведение остаётся прежним (открытым), а не запертым для всех.
    if not _telegram_token():
        return
    if _web_access_allowed(session, key):
        return
    raise HTTPException(
        status_code=401,
        detail=(f"{what} — после входа через Telegram. Нажмите «Войти через "
                "Telegram», подтвердите вход в боте и повторите."))
