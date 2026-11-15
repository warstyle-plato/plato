"""Бот Telegram: диалог, отправка, вебхук и маршруты /telegram/*.

Не самостоятельный модуль. `main_legacy.py` выполняет этот файл в своём
пространстве имён на том месте, где этот код стоял раньше
(`_engine_part("bot_telegram")`), поэтому здесь видны все имена движка,
а подмены `core.<имя>` из `main.py` и тестов действуют и на этот код.
Отдельно не импортировать: второй импорт поднял бы вторую копию движка.
"""
# ruff: noqa
import document_intake_protocol as document_protocol

_TELEGRAM_PUBLIC_BASE_URL = (
    os.environ.get("TELEGRAM_PUBLIC_BASE_URL")
    or os.environ.get("RENDER_EXTERNAL_URL")
    or "https://plato-development-investment-model.onrender.com"
).rstrip("/")

# Вебхук и мини-приложение живут по разным адресам, когда бот на Render, а
# модель — там, где доступен НСПД: адрес вебхука должен остаться на Render,
# иначе Telegram перестанет доставлять обновления, а кнопка «Открыть модель»
# должна вести на ядро, иначе в модели не заработают ни адреса, ни область.
_TELEGRAM_WEB_APP_BASE_URL = (
    os.environ.get("TELEGRAM_WEBAPP_URL")
    or os.environ.get("TELEGRAM_WEB_APP_BASE_URL")
    or _TELEGRAM_PUBLIC_BASE_URL
).rstrip("/")
_TELEGRAM_RUNTIME: dict[str, Any] = {
    "configured": False,
    "username": "",
    "last_error": "",
    "configured_at": "",
}
_TELEGRAM_DIALOGS: dict[int, dict[str, Any]] = {}
_TELEGRAM_DIALOG_LOCK = threading.Lock()
_TELEGRAM_DIALOG_TTL_SECONDS = 6 * 60 * 60
_TELEGRAM_INTAKE_READ_SECONDS = 240
import contextvars as _telegram_contextvars
_TELEGRAM_INTAKE_LOCKED = _telegram_contextvars.ContextVar("telegram_intake_locked", default=None)
_TELEGRAM_INTAKE_AFTER_LOCK = _telegram_contextvars.ContextVar("telegram_intake_after_lock", default=None)


def _telegram_intake_serialized(function):
    """Serialize one chat's intake read/modify/write across native workers."""
    import functools
    @functools.wraps(function)
    def locked(chat_id, *args, **kwargs):
        import fcntl
        import stat
        chat_id = int(chat_id)
        if _TELEGRAM_INTAKE_LOCKED.get() == chat_id:
            return function(chat_id, *args, **kwargs)
        if function.__name__ == "_telegram_handle_dialog_text":
            state = _telegram_dialog_get(chat_id) or {}
            if state.get("step") not in {"await_intake_answer", "intake_document_reading", "intake_document_failed"}:
                return function(chat_id, *args, **kwargs)
        _PLATO_STAGE_DIR.mkdir(parents=True, exist_ok=True)
        fd = os.open(_PLATO_STAGE_DIR / f"intake_dialog_{chat_id}.lock",
                     os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise RuntimeError("Блокировка шага разбора недоступна.")
            fcntl.flock(fd, fcntl.LOCK_EX)
            token = _TELEGRAM_INTAKE_LOCKED.set(chat_id)
            deferred = []
            delivery = _TELEGRAM_INTAKE_AFTER_LOCK.set(deferred)
            try:
                result = function(chat_id, *args, **kwargs)
            finally:
                _TELEGRAM_INTAKE_AFTER_LOCK.reset(delivery)
                _TELEGRAM_INTAKE_LOCKED.reset(token)
        finally:
            os.close(fd)
        for operation, positional, named in deferred:
            operation(*positional, **named)
        return result
    return locked


def _telegram_intake_after_lock(operation, *args, **kwargs):
    deferred = _TELEGRAM_INTAKE_AFTER_LOCK.get()
    if deferred is None:
        return operation(*args, **kwargs)
    deferred.append((operation, args, kwargs))
    return None


@_telegram_intake_serialized
def _telegram_intake_begin(chat_id: int, filename: str) -> str:
    """Claim a document operation before IO; no lock is held during reading."""
    nonce = os.urandom(16).hex()
    started = time.time()
    dialog = _telegram_dialog_get(chat_id) or {}
    previous_step = str((dialog.get("document_read") or {}).get("previous_step") or dialog.get("step") or "")
    dialog["document_read"] = {"id": nonce, "filename": str(filename or "")[:240],
                               "status": "loading", "previous_step": previous_step,
                               "started_at":started,"deadline_at":started+_TELEGRAM_INTAKE_READ_SECONDS}
    dialog["step"] = "intake_document_reading"
    _telegram_dialog_save(chat_id, dialog)
    return nonce


def _telegram_intake_current(chat_id: int, nonce: str, *, allow_failed: bool = False) -> bool:
    dialog = _telegram_dialog_get(chat_id) or {}
    active = dialog.get("document_read") or {}
    return bool(nonce and active.get("id") == nonce
                and (active.get("status") in {"loading","ready"} or allow_failed))


@_telegram_intake_serialized
def _telegram_intake_commit(chat_id: int, nonce: str, commit):
    """Run only short local publication after a fresh operation comparison."""
    dialog = _telegram_dialog_get(chat_id) or {}
    active = dialog.get("document_read") or {}
    if not nonce or active.get("id") != nonce or active.get("status") != "loading":
        return False, None
    return True, commit(dialog)


def _telegram_intake_callback_data(intake_id: str, action: str, *parts) -> str:
    if (not re.fullmatch(r"[0-9a-f]{32}", str(intake_id or ""))
            or action not in {"questions", "region", "opt", "defer", "rechoose", "mode", "review"}):
        raise ValueError("Кнопка не связана с текущим разбором.")
    data = ":".join(["intake2_"+action, intake_id, *(str(part) for part in parts)])
    if len(data.encode("utf-8")) > 64:
        raise ValueError("Кнопка разбора превышает допустимый размер.")
    return data


def _telegram_dialog_path(chat_id: int) -> Path:
    return _PLATO_STAGE_DIR / f"dialog_{int(chat_id)}.json"


def _telegram_intake_expired(active: dict) -> bool:
    import math
    deadline = active.get("deadline_at")
    return active.get("status") == "loading" and (type(deadline) not in (int,float)
        or not math.isfinite(deadline) or time.time() >= deadline)


@_telegram_intake_serialized
def _telegram_intake_expire(chat_id: int, expected_source: str):
    try:
        raw = _telegram_dialog_path(chat_id).read_bytes()
    except FileNotFoundError:
        return None
    if hashlib.sha256(raw).hexdigest() != expected_source:
        return _telegram_dialog_get(chat_id)
    current = json.loads(raw)
    current["_source_sha256"] = expected_source
    active = current.get("document_read") or {}
    if _telegram_intake_expired(active):
        current["document_read"] = {**active,"status":"interrupted","failure":"document_read_interrupted"}
        current["step"] = "intake_document_failed"
        _telegram_dialog_save(chat_id,current)
    return current


def _telegram_dialog_get(chat_id: int) -> dict[str, Any] | None:
    now = int(time.time())
    with _TELEGRAM_DIALOG_LOCK:
        current = _TELEGRAM_DIALOGS.get(int(chat_id))
    # Disk is authoritative across workers, including an updated choice or
    # cancellation made while this worker still has an older cached step.
    try:
        raw = _telegram_dialog_path(chat_id).read_bytes()
        current = json.loads(raw)
        if isinstance(current, dict):
            current["_source_sha256"] = hashlib.sha256(raw).hexdigest()
    except FileNotFoundError:
        with _TELEGRAM_DIALOG_LOCK:
            _TELEGRAM_DIALOGS.pop(int(chat_id), None)
        return None
    except (OSError, ValueError):
        raise RuntimeError("Сохранённый шаг не прочитан; ответ ещё не принят.") from None
    if not isinstance(current, dict):
        raise RuntimeError("Формат сохранённого шага не прочитан; ответ ещё не принят.")
    if _telegram_intake_expired(current.get("document_read") or {}):
        return _telegram_intake_expire(chat_id,current["_source_sha256"])
    if now - int(current.get("updated_at") or 0) > _TELEGRAM_DIALOG_TTL_SECONDS:
        cleared = _telegram_dialog_clear(chat_id, expected_source=current.get("_source_sha256"))
        return _telegram_dialog_get(chat_id) if cleared is False else None
    with _TELEGRAM_DIALOG_LOCK:
        _TELEGRAM_DIALOGS[int(chat_id)] = copy.deepcopy(current)
    return copy.deepcopy(current)


@_telegram_intake_serialized
def _telegram_dialog_save(chat_id: int, dialog: dict[str, Any]) -> None:
    saved = copy.deepcopy(dialog)
    expected_source = saved.pop("_source_sha256", None)
    saved["updated_at"] = int(time.time())
    try:
        import agent_access
        try:
            before_raw = _telegram_dialog_path(chat_id).read_bytes()
            before = json.loads(before_raw)
        except FileNotFoundError:
            before_raw = None
            before = {}
        if not isinstance(before, dict):
            raise RuntimeError("Формат сохранённого шага не прочитан; продолжение пока не подтверждено.")
        expected = dialog.get("_revision", 0)
        actual = before.get("_revision", 0)
        if (type(expected) is not int or type(actual) is not int or expected < 0 or actual < 0
                or ("_revision" in dialog and expected != actual)
                or (expected_source is not None and expected_source != (
                    hashlib.sha256(before_raw).hexdigest() if before_raw is not None else None))):
            raise RuntimeError("Шаг уже изменился. Продолжите с текущего вопроса.")
        saved["_revision"] = actual + 1
        agent_access.write_json(_telegram_dialog_path(chat_id), saved)
    except (OSError, TypeError, ValueError):
        raise RuntimeError("Шаг не удалось сохранить; продолжение пока не подтверждено.") from None
    with _TELEGRAM_DIALOG_LOCK:
        _TELEGRAM_DIALOGS[int(chat_id)] = saved
    dialog["_revision"] = saved["_revision"]
    dialog["_source_sha256"] = hashlib.sha256(json.dumps(saved, ensure_ascii=False).encode()).hexdigest()


@_telegram_intake_serialized
def _telegram_dialog_clear(chat_id: int, *, expected_source: str | None = None) -> bool:
    if expected_source is not None:
        try:
            raw = _telegram_dialog_path(chat_id).read_bytes()
        except FileNotFoundError:
            raw = None
        if raw is not None and hashlib.sha256(raw).hexdigest() != expected_source:
            return False  # A newer worker refreshed the dialogue while TTL was checked.
    with _TELEGRAM_DIALOG_LOCK:
        _TELEGRAM_DIALOGS.pop(int(chat_id), None)
    try:
        _telegram_dialog_path(chat_id).unlink(missing_ok=True)
    except OSError:
        raise RuntimeError("Сохранённый шаг не удалось отменить; отмена пока не подтверждена.") from None
    return True


def _telegram_dialog_number(text: str, *, site_area: bool = False) -> float:
    normalized = str(text or "").lower().replace("ё", "е")
    normalized = re.sub(r"(?<=\d)[\s\u00a0\u202f](?=\d)", "", normalized)
    match = re.search(r"[-+]?\d+(?:[.,]\d+)?", normalized)
    if not match:
        raise ValueError("Не вижу числа")
    value = float(match.group(0).replace(",", "."))
    if re.search(r"\bмлн\b", normalized):
        value *= 1_000_000
    elif re.search(r"\bтыс\.?\b", normalized):
        value *= 1_000
    if site_area and not re.search(r"\bга\b", normalized) and re.search(r"м[²2]|кв\.?\s*м", normalized):
        value /= 10_000
    if not math.isfinite(value) or value <= 0:
        raise ValueError("Значение должно быть больше нуля")
    return value


def _telegram_token() -> str:
    return os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()


def _telegram_webhook_secret() -> str:
    token = _telegram_token()
    return hashlib.sha256(("plato-webhook:" + token).encode("utf-8")).hexdigest()


def _telegram_webhook_enabled() -> bool:
    """Регистрировать ли вебхук у Telegram.

    Когда бот и мини-приложение развёрнуты по разным адресам, токен нужен обоим:
    подпись сессии считается им же, и без токена мини-приложение отвечает
    «Telegram-сессия недействительна». Но вебхук у бота один, поэтому на хосте
    с моделью регистрацию надо выключить — иначе он уведёт обновления на себя.
    """
    return os.environ.get("TELEGRAM_WEBHOOK_ENABLED", "1").strip().lower() not in {
        "0", "false", "no", "off",
    }


def _telegram_document_read_response(response, deadline: float, max_bytes: int) -> bytes:
    """One read per remaining socket deadline; no accumulated/trickle read()."""
    import document_processing
    length = response.headers.get('Content-Length') if getattr(response,'headers',None) is not None else None
    if length is not None:
        try:declared=int(length)
        except (ValueError,TypeError):raise ValueError('Telegram передал некорректный размер ответа.') from None
        if not 0 <= declared <= max_bytes:
            raise ValueError('Ответ Telegram превышает допустимый размер.')
    read = getattr(response,'read1',None)
    if read is None:
        raise RuntimeError('Ограниченное потоковое чтение ответа Telegram недоступно.')
    chunks,size=[],0
    while True:
        document_processing.delivery_check()
        left = deadline-time.monotonic()
        if left <= 0:raise TimeoutError('Telegram response deadline')
        stream=response
        for _ in range(3):
            sock=getattr(getattr(stream,'raw',None),'_sock',None)
            if sock is not None:
                sock.settimeout(left)
                break
            stream=getattr(stream,'fp',None)
            if stream is None:break
        chunk=read(min(64*1024,max_bytes+1-size))
        document_processing.delivery_check()
        if time.monotonic() >= deadline:raise TimeoutError('Telegram response deadline')
        if not chunk:break
        size += len(chunk)
        if size > max_bytes:raise ValueError('Ответ Telegram превышает допустимый размер.')
        chunks.append(chunk)
    if length is not None and size != declared:
        raise ValueError('Ответ Telegram пришёл не полностью. Источник не принят.')
    return b''.join(chunks)


def _telegram_api(method: str, payload: dict[str, Any] | None = None, *, timeout: float = 15) -> Any:
    token = _telegram_token()
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN не задан")
    request = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/{method}",
        data=json.dumps(payload or {}, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    import document_processing
    if document_processing.notification_active() and method != 'sendMessage':
        raise document_processing.Cancelled('A failure notice cannot download or read a source')
    document_deadline = document_processing.delivery_deadline()
    until = time.monotonic()+timeout
    if document_deadline is not None:
        until = min(until,document_deadline)
    timeout = until-time.monotonic()
    if timeout <= 0:
        raise document_processing.Expired()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = _telegram_document_read_response(response,until,1024*1024)
            body = json.loads(raw.decode('utf-8'))
    except urllib.error.HTTPError as exc:
        with exc:
            raw = _telegram_document_read_response(exc,until,1024*1024)
        detail = raw.decode('utf-8',errors='replace')[:500]
        raise RuntimeError(f"Telegram API: HTTP {exc.code}: {detail}") from exc
    except (document_processing.Cancelled,document_processing.Expired):
        raise
    except Exception as exc:
        raise RuntimeError(f"Telegram API недоступен: {exc}") from exc
    if not body.get("ok"):
        raise RuntimeError("Telegram API: " + str(body.get("description") or "неизвестная ошибка"))
    return body.get("result")


def _telegram_allowed_user_ids() -> set[int]:
    raw = os.environ.get("TELEGRAM_ALLOWED_USER_IDS", "").strip()
    result: set[int] = set()
    for value in re.split(r"[\s,;]+", raw):
        if value and value.lstrip("-").isdigit():
            result.add(int(value))
    return result


def _telegram_user_allowed(user_id: int) -> bool:
    allowed = _telegram_allowed_user_ids()
    return not allowed or int(user_id) in allowed


def _telegram_overrides_digest(overrides: dict[str, Any]) -> str:
    raw = json.dumps(overrides, ensure_ascii=False, sort_keys=True,
                     separators=(",", ":"), allow_nan=False).encode("utf-8")
    if len(raw) > 24_000:
        raise ValueError("Параметры требуют повторной проверки карточки")
    return hashlib.sha256(raw).hexdigest()


def _telegram_qualified_application_binding(overrides: dict[str, Any], scope: str) -> str:
    # Disclosure signatures grant no authority over arbitrary cash. The
    # application binding separately attests these exact confirmed overrides.
    record = overrides[intake_qualification.KEY]
    body = {'scope':scope, 'sha256':_telegram_overrides_digest(overrides),
        'source_binding':record['binding'], 'owner':record['owner'], 'recipient':record['recipient']}
    raw = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
    return hmac.new(_intake_qualification_key('telegram'),
        b'plato/document-qualification/application/v1\0'+raw, hashlib.sha256).hexdigest()


def _telegram_application_proof(overrides: dict[str, Any], proof: Any) -> dict[str, Any] | None:
    # This checks a signed server attestation; the generic session issuer does
    # not manufacture one. Only canonical card/CAD confirmation paths issue it.
    if not isinstance(proof, dict) or set(proof) != {"schema", "scope", "binding", "sha256"}:
        return None
    if (type(proof.get("schema")) is not int or proof["schema"] != 1
            or not isinstance(proof.get('scope'), str)
            or proof['scope'] not in {"confirmed_card", "confirmed_cad", "confirmed_patch"}
            or not re.fullmatch(r"[0-9a-f]{64}", str(proof.get("binding") or ""))):
        return None
    try:
        qualification = _intake_qualification_state(overrides)
        if (qualification is not None and not qualification.get('verified')) or (
                proof['scope'] == 'confirmed_card' and qualification is None):
            return None
        if qualification is not None:
            if not hmac.compare_digest(proof['binding'], _telegram_qualified_application_binding(overrides, proof['scope'])):
                return None
            if proof['scope'] == 'confirmed_card':
                facts = {k:v for k,v in overrides.items() if k not in {intake_qualification.KEY, intake_qualification.PACKET}}
                if not hmac.compare_digest(overrides[intake_qualification.KEY]['overrides_sha256'], _telegram_overrides_digest(facts)):
                    return None
        if not hmac.compare_digest(str(proof.get("sha256") or ""), _telegram_overrides_digest(overrides)):
            return None
    except (ValueError, TypeError, OverflowError):
        return None
    return dict(proof)


def _telegram_carry_application_proof(session: dict[str, Any]) -> dict[str, Any] | None:
    overrides = session.get('calc_overrides') or {}
    proof = _telegram_application_proof(overrides, session.get('overrides_application'))
    record = overrides.get(intake_qualification.KEY)
    if record is not None and (not isinstance(record, dict) or not session.get('chat_id')
            or record.get('recipient') != _intake_qualification_recipient(session['chat_id'])):
        return None
    return proof


def _telegram_confirmed_patch_proof(session: dict[str, Any], overrides: dict[str, Any],
                                     changes: dict[str, Any]) -> dict[str, Any] | None:
    # A confirmed change may extend a validated base, never promote an old
    # unvalidated saved dictionary. Every changed value has native field type.
    base = session.get("calc_overrides") or {}
    prior = _telegram_carry_application_proof(session)
    if (base and prior is None) or not changes:
        return None
    expected = dict(base)
    for key, value in changes.items():
        if key not in DEFAULT_INPUTS:
            return None
        default = DEFAULT_INPUTS[key]
        if isinstance(default, bool):
            if not isinstance(value, bool):return None
        elif isinstance(default, (int, float)):
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not teaser_card._finite_value(value):return None
        elif not isinstance(value, str):
            return None
        expected[key] = value
    if expected != overrides:
        return None
    digest = _telegram_overrides_digest(overrides)
    binding = (_telegram_qualified_application_binding(overrides, 'confirmed_patch')
        if intake_qualification.KEY in overrides else hashlib.sha256(json.dumps({"base": prior, "changes": changes},
        sort_keys=True, ensure_ascii=False, allow_nan=False).encode("utf-8")).hexdigest())
    return {"schema": 1, "scope": "confirmed_patch", "binding": binding, "sha256": digest}


def _telegram_session(
    chat_id: int,
    cadastral_numbers: list[str],
    lifetime_seconds: int = 86400,
    manual_tep: dict[str, Any] | None = None,
    calc_overrides: dict[str, Any] | None = None,
    application_proof: dict[str, Any] | None = None,
    calculation_qualification: dict[str, Any] | None = None,
) -> str:
    token = _telegram_token()
    if not token:
        raise RuntimeError("Telegram-бот не настроен")
    payload = {
        "chat_id": int(chat_id),
        "cad": list(cadastral_numbers),
        "exp": int(time.time()) + int(lifetime_seconds),
    }
    if manual_tep:
        payload["manual_tep"] = manual_tep
    if calc_overrides:
        payload["calc_overrides"] = calc_overrides
        proof = _telegram_application_proof(calc_overrides, application_proof)
        qualification = calc_overrides.get(intake_qualification.KEY)
        if qualification is not None and (
                not isinstance(qualification, dict)
                or qualification.get('recipient') != _intake_qualification_recipient(chat_id)):
            proof = None
        if proof is not None:
            payload["overrides_application"] = proof
    if calculation_qualification is not None and not (calc_overrides or {}).get(intake_qualification.KEY):
        state = _intake_qualification_state({intake_qualification.KEY:calculation_qualification})
        recipient = calculation_qualification.get('recipient') if isinstance(calculation_qualification, dict) else None
        if state and state.get('verified') and recipient in (None, _intake_qualification_recipient(chat_id)):
            payload['calculation_qualification'] = calculation_qualification
        else:
            payload['qualification_review_required'] = True
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
    if len(raw) > 24_000:
        raise RuntimeError("Ручной ТЭП слишком велик для Telegram-сессии")
    encoded = base64.urlsafe_b64encode(raw).rstrip(b"=")
    signature = hmac.new(token.encode("utf-8"), encoded, hashlib.sha256).digest()[:20]
    return encoded.decode("ascii") + "." + base64.urlsafe_b64encode(signature).rstrip(b"=").decode("ascii")


def _telegram_verify_session(value: str) -> dict[str, Any]:
    token = _telegram_token()
    if not token:
        # Подпись сессии считается токеном бота. Без него проверка не пройдёт
        # никогда, и «сессия истекла» уводит в ложном направлении: истекать там
        # нечему, просто хост не знает, чем проверять.
        raise HTTPException(
            status_code=503,
            detail=(
                "На этом сервере не задан TELEGRAM_BOT_TOKEN, поэтому подпись Telegram-сессии "
                "проверить нечем. Задайте тот же токен, что у бота, и TELEGRAM_WEBHOOK_ENABLED=0, "
                "чтобы этот сервер не забрал вебхук себе."
            ),
        )
    try:
        encoded_text, signature_text = str(value or "").split(".", 1)
        encoded = encoded_text.encode("ascii")
        supplied = base64.urlsafe_b64decode(signature_text + "=" * (-len(signature_text) % 4))
        expected = hmac.new(token.encode("utf-8"), encoded, hashlib.sha256).digest()[:20]
        if not hmac.compare_digest(supplied, expected):
            raise ValueError("signature")
        raw = base64.urlsafe_b64decode(encoded_text + "=" * (-len(encoded_text) % 4))
        payload = json.loads(raw.decode("utf-8"))
        if int(payload.get("exp") or 0) < int(time.time()):
            raise ValueError("expired")
        payload["chat_id"] = int(payload["chat_id"])
        raw_cad = payload.get("cad") or []
        payload["cad"] = _parse_cadastral_numbers(raw_cad) if raw_cad else []
        manual_tep = payload.get("manual_tep")
        if manual_tep is not None and not isinstance(manual_tep, dict):
            raise ValueError("manual_tep")
        calc_overrides = payload.get("calc_overrides")
        if calc_overrides is not None and not isinstance(calc_overrides, dict):
            raise ValueError("calc_overrides")
        # Демо-доступ проверяющих (`engine/review_demo.py`) отзывается владельцем
        # раньше срока подписи: отозванная ссылка гасит и выданную по ней сессию.
        demo_alive = globals().get("demo_session_alive")
        if callable(demo_alive) and not demo_alive(payload["chat_id"]):
            raise ValueError("demo revoked")
        return payload
    except Exception as exc:
        raise HTTPException(status_code=403, detail="Telegram-сессия недействительна или истекла") from exc


class _DocumentProtocolNoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def _telegram_document_target() -> str:
    origin = document_protocol.admitted_origin(os.environ.get(document_protocol.ADMISSION_ENV, ''),
                                               _TELEGRAM_WEB_APP_BASE_URL)
    url = origin + document_protocol.CAPABILITY_PATH
    started = time.monotonic()
    try:
        opener = urllib.request.build_opener(_DocumentProtocolNoRedirect())
        try:
            req = urllib.request.Request(url, headers={'Accept': 'application/json',
                'Accept-Encoding': 'identity', 'Cache-Control': 'no-store'})
            with opener.open(req, timeout=5) as response:
                if (response.status != 200 or response.geturl() != url
                        or response.headers.get_content_type() != 'application/json'
                        or response.headers.get('Content-Encoding', 'identity').lower() != 'identity'
                        or response.headers.get('Content-Range')):
                    raise document_protocol.ProtocolHold('core_protocol')
                document_protocol.parse_capability(response.read(4097))
                if time.monotonic() - started > 5:
                    raise document_protocol.ProtocolHold('core_unavailable')
        finally:
            opener.close()
    except Exception:
        raise document_protocol.ProtocolHold('core_unavailable') from None
    return origin


def _telegram_web_app_url(
    chat_id: int,
    cadastral_numbers: list[str],
    manual_tep: dict[str, Any] | None = None,
    calc_overrides: dict[str, Any] | None = None,
    mode: str | None = None,
    application_proof: dict[str, Any] | None = None,
    calculation_qualification: dict[str, Any] | None = None,
) -> str:
    qualified = (isinstance(calc_overrides, dict) and intake_qualification.KEY in calc_overrides
                 or calculation_qualification is not None)
    entry = (_telegram_document_target() + document_protocol.ENTRY_PATH if qualified
             else _TELEGRAM_WEB_APP_BASE_URL + '/')
    fragment: dict[str, str] = {
        "telegram_session": _telegram_session(
            chat_id,
            cadastral_numbers,
            manual_tep=manual_tep,
            calc_overrides=calc_overrides,
            application_proof=application_proof,
            calculation_qualification=calculation_qualification,
        ),
    }
    if cadastral_numbers:
        fragment["cad"] = ", ".join(cadastral_numbers)
    if mode:
        fragment["mode"] = str(mode)
    # v=VERSION ломает кэш Telegram WebView: без него после выкатки открывалась
    # старая сборка страницы, и починки «не доезжали» до мини-приложения.
    return (entry + "?telegram=1&v="
            + urllib.parse.quote(VERSION) + "#" + urllib.parse.urlencode(fragment))


def _telegram_send_message(
    chat_id: int,
    text: str,
    *,
    reply_markup: dict[str, Any] | None = None,
) -> Any:
    payload: dict[str, Any] = {
        "chat_id": int(chat_id),
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup
    return _telegram_intake_after_lock(_telegram_api, "sendMessage", payload)


def _telegram_send_document_bytes(
    chat_id: int,
    content: bytes,
    filename: str,
    caption: str = "",
    content_type: str = "application/octet-stream",
) -> Any:
    token = _telegram_token()
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN не задан")
    boundary = "----DevelopAidBoundary" + hashlib.sha256(os.urandom(16)).hexdigest()[:20]
    body = io.BytesIO()

    def field(name: str, value: str) -> None:
        body.write(f"--{boundary}\r\n".encode())
        body.write(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode())
        body.write(str(value).encode("utf-8"))
        body.write(b"\r\n")

    field("chat_id", str(int(chat_id)))
    if caption:
        field("caption", caption)
        field("parse_mode", "HTML")
    body.write(f"--{boundary}\r\n".encode())
    body.write(
        f'Content-Disposition: form-data; name="document"; filename="{filename}"\r\n'.encode("utf-8")
    )
    body.write(f"Content-Type: {content_type}\r\n\r\n".encode("ascii"))
    body.write(content)
    body.write(b"\r\n")
    body.write(f"--{boundary}--\r\n".encode())
    request = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendDocument",
        data=body.getvalue(),
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            result = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        raise RuntimeError(f"Telegram API sendDocument: HTTP {exc.code}: {detail}") from exc
    if not result.get("ok"):
        raise RuntimeError("Telegram API sendDocument: " + str(result.get("description") or "неизвестная ошибка"))
    return result.get("result")


def _telegram_send_photo_bytes(
    chat_id: int,
    content: bytes,
    filename: str,
    caption: str = "",
) -> Any:
    """sendPhoto тем же multipart, что и документы: фото видно в чате сразу."""
    token = _telegram_token()
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN не задан")
    boundary = "----DevelopAidBoundary" + hashlib.sha256(os.urandom(16)).hexdigest()[:20]
    body = io.BytesIO()

    def field(name: str, value: str) -> None:
        body.write(f"--{boundary}\r\n".encode())
        body.write(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode())
        body.write(str(value).encode("utf-8"))
        body.write(b"\r\n")

    field("chat_id", str(int(chat_id)))
    if caption:
        field("caption", caption)
        field("parse_mode", "HTML")
    body.write(f"--{boundary}\r\n".encode())
    body.write(
        f'Content-Disposition: form-data; name="photo"; filename="{filename}"\r\n'.encode("utf-8")
    )
    body.write(b"Content-Type: image/png\r\n\r\n")
    body.write(content)
    body.write(b"\r\n")
    body.write(f"--{boundary}--\r\n".encode())
    request = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendPhoto",
        data=body.getvalue(),
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            result = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        raise RuntimeError(f"Telegram API sendPhoto: HTTP {exc.code}: {detail}") from exc
    if not result.get("ok"):
        raise RuntimeError("Telegram API sendPhoto: " + str(result.get("description") or "неизвестная ошибка"))
    return result.get("result")


# Поле окружения вокруг контура на карте улиц: столько же, сколько у кадра
# первой страницы полного PDF и у карты на сайте — участок читается только
# вместе с улицами и кварталами вокруг.
_MAP_CONTEXT_METRES = 250.0
_MAP_BASEMAP_CAPTION = {"nspd": "подложка — публичная карта НСПД",
                        "osm": "подложка — карта улиц OpenStreetMap"}


def _map_context_bbox(points: list[Any], target_aspect: float,
                      context_m: float = _MAP_CONTEXT_METRES) -> tuple[float, float, float, float] | None:
    """Рамка карты вокруг контура: поле окружения и пропорция слота.

    Один расчёт рамки на тизер и первую страницу PDF: две копии одной
    геометрии расходятся, и контур ложится рядом с подложкой, а выглядит это
    как неточность ЕГРН. Поле — не меньше `context_m` и не меньше 22 % от
    размера контура; затем рамка растягивается до пропорции слота.
    """
    if not points:
        return None
    xs = [float(p[0]) for p in points]
    ys = [float(p[1]) for p in points]
    min_x, max_x, min_y, max_y = min(xs), max(xs), min(ys), max(ys)
    span_x, span_y = max_x - min_x, max_y - min_y
    if not (span_x > 0 and span_y > 0):
        return None
    pad_x = max(span_x * 0.22, context_m)
    pad_y = max(span_y * 0.22, context_m)
    min_x, max_x, min_y, max_y = min_x - pad_x, max_x + pad_x, min_y - pad_y, max_y + pad_y
    span_x, span_y = max_x - min_x, max_y - min_y
    aspect = max(float(target_aspect or 1.0), 0.1)
    if span_x / span_y < aspect:
        extra = (span_y * aspect - span_x) / 2.0
        min_x, max_x = min_x - extra, max_x + extra
    elif span_x / span_y > aspect:
        extra = (span_x / aspect - span_y) / 2.0
        min_y, max_y = min_y - extra, max_y + extra
    return min_x, min_y, max_x, max_y


_TERRITORY_LOOKUP_CHUNK = 15


def _territory_image_png(numbers: list[str], basemap: str = "nspd",
                         aspect: float | None = None) -> tuple[bytes, str] | None:
    """Картинка территории: контуры ЕГРН поверх подложки — с подписью.

    Одна на бота и на тизер: та же картинка, что на сайте в карточке участка.
    Контуры приходят из /land/lookup (`contour_merc`). Подложек две, и
    подпись называет, какая стоит:
    - `nspd` — публичная кадастровая карта крупным планом (/land/map-image),
      как в боте: видны соседние участки;
    - `osm` — карта улиц с полем окружения не меньше 250 м (/land/basemap,
      та же склейка, что у первой страницы полного PDF), в пропорции
      `aspect`: участок в контексте реальной карты города (владелец,
      22.09.2026 — «класть контур на карту окружения»).
    Оба маршрута на Render пересылают на ядро сами. Нет контура или подложки
    — `None`: голый контур на белом фоне — шум, а не информация (владелец,
    16.08.2026), и расчёт от картинки не зависит.
    """
    if basemap not in _MAP_BASEMAP_CAPTION:
        raise ValueError(f"неизвестная подложка карты: {basemap!r}")
    # Поиск берёт не больше 500 символов запроса — это ~23 номера; территория
    # КРТ бывает до 30 участков. Частями по 15: иначе вся карта пропадала.
    results: list[dict[str, Any]] = []
    for start in range(0, len(numbers), _TERRITORY_LOOKUP_CHUNK):
        part = numbers[start:start + _TERRITORY_LOOKUP_CHUNK]
        data = land_lookup(LandLookupRequest(query=", ".join(part), limit=max(10, len(part))))
        results.extend(data.get("results") or [])
    found, missing = _territory_contours(numbers, results)
    rings = [ring for item in found for ring in item["contour_merc"]
             if isinstance(ring, list) and len(ring) >= 3]
    points = [p for ring in rings for p in ring
              if isinstance(p, (list, tuple)) and len(p) >= 2]
    if not points:
        return None
    from PIL import Image, ImageDraw, ImageFont
    if basemap == "osm":
        bbox = _map_context_bbox(points, aspect or 1.0)
        if bbox is None:
            return None
        b_min_x, b_min_y, b_max_x, b_max_y = bbox
        try:
            response = land_basemap(
                bbox=f"{b_min_x:.1f},{b_min_y:.1f},{b_max_x:.1f},{b_max_y:.1f}", width=960)
            backdrop = Image.open(io.BytesIO(bytes(response.body))).convert("RGBA")
        except Exception:
            return None
    else:
        min_x = min(p[0] for p in points); max_x = max(p[0] for p in points)
        min_y = min(p[1] for p in points); max_y = max(p[1] for p in points)
        span = max(max_x - min_x, max_y - min_y, 1.0)
        pad = max(span * 0.08, 25.0)
        b_min_x, b_min_y = min_x - pad, min_y - pad
        b_max_x, b_max_y = max_x + pad, max_y + pad
        try:
            response = land_map_image(
                bbox=f"{b_min_x:.1f},{b_min_y:.1f},{b_max_x:.1f},{b_max_y:.1f}")
            backdrop = Image.open(io.BytesIO(bytes(response.body))).convert("RGBA")
        except Exception:
            return None
    w, h = backdrop.size
    overlay = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    overlay_draw = ImageDraw.Draw(overlay)
    pixel_rings = []
    for ring in rings:
        px = [((p[0] - b_min_x) / (b_max_x - b_min_x) * w,
               (b_max_y - p[1]) / (b_max_y - b_min_y) * h)
              for p in ring if isinstance(p, (list, tuple)) and len(p) >= 2]
        if len(px) < 3:
            continue
        pixel_rings.append(px)
        # Полупрозрачная заливка — как на сайте: участок видно пятном, а
        # карта под ним остаётся читаемой.
        overlay_draw.polygon(px, fill=(245, 245, 243, 90))
    if not pixel_rings:
        return None
    image = Image.alpha_composite(backdrop, overlay).convert("RGB")
    draw = ImageDraw.Draw(image)
    for px in pixel_rings:
        closed = px + [px[0]]
        # Белая подкладка под тёмной линией: граница читается на пёстрой карте.
        draw.line(closed, fill=(255, 255, 255), width=7, joint="curve")
        draw.line(closed, fill=(180, 35, 24), width=3, joint="curve")
    if basemap == "osm":
        # Атрибуция — часть картинки: условие OpenStreetMap, а не украшение.
        label = "© OpenStreetMap"
        font = ImageFont.load_default()
        box = draw.textbbox((0, 0), label, font=font)
        tw, th = box[2] - box[0], box[3] - box[1]
        x0, y0 = 8, image.height - th - 8
        draw.rectangle((x0 - 4, y0 - 3, x0 + tw + 4, y0 + th + 3), fill=(255, 255, 255))
        draw.text((x0, y0), label, fill=(40, 40, 40), font=font)
    out = io.BytesIO()
    image.save(out, format="PNG")
    return out.getvalue(), _territory_caption(numbers, found, missing, basemap)


def _cadastral_key(number: Any) -> str:
    """Номер для сверки: части без ведущих нулей — «77:05:0004001:040» и
    «77:05:4001:40» один участок, а соседний номер — другой."""
    parts = str(number or "").strip().split(":")
    return ":".join(str(int(p)) if p.isdigit() else p for p in parts)


def _territory_contours(numbers: list[str], results: list[dict[str, Any]]
                        ) -> tuple[list[dict[str, Any]], list[str]]:
    """Контуры территории, сверенные с запрошенными номерами.

    Ответ поиска сопоставляется с номером по самому номеру, а не по месту в
    списке: по промаху НСПД может отдать соседний участок, и тогда на карте
    рисовался сосед, а нужный участок молча пропадал из середины контура.
    Возвращает найденные с контуром (по одному на номер, в порядке запроса) и
    номера, контура которых в источнике нет, — их подпись называет."""
    by_key: dict[str, dict[str, Any]] = {}
    for item in results:
        if not (item.get("found") and item.get("contour_merc")):
            continue
        by_key.setdefault(_cadastral_key(item.get("cadastral_number")), item)
    found: list[dict[str, Any]] = []
    missing: list[str] = []
    seen: set[str] = set()
    for number in numbers:
        key = _cadastral_key(number)
        if key in seen:
            continue
        seen.add(key)
        item = by_key.get(key)
        if item is None:
            missing.append(number)
        else:
            found.append(item)
    return found, missing


def _territory_caption(numbers: list[str], found: list[dict[str, Any]],
                       missing: list[str], basemap: str) -> str:
    """Подпись карты: число участков — то же, что в таблице (запрошенные
    номера), перечень не обрывается молча, а недорисованные названы."""
    total = len({_cadastral_key(n) for n in numbers})
    shown = [str(item.get("cadastral_number") or "") for item in found]
    listed = ", ".join(shown[:5]) + (f" и ещё {len(shown) - 5}" if len(shown) > 5 else "")
    if total == 1 and not missing:
        caption = f"Контур участка {listed} · границы ЕГРН"
    else:
        caption = f"Территория из {total} участков: {listed} · границы ЕГРН"
    if missing:
        names = ", ".join(missing[:5]) + (f" и ещё {len(missing) - 5}" if len(missing) > 5 else "")
        caption += (f" · контур нарисован для {len(found)} из {total}: "
                    f"у участков {names} нет границ в источнике (НСПД)")
    return caption + " · " + _MAP_BASEMAP_CAPTION[basemap]


def _telegram_territory_photo(chat_id: int, numbers: list[str]) -> bool:
    """Картинка территории в чат — та же, что уходит в тизер (`_territory_image_png`).

    В боте её не было вовсе (замечание владельца, 16.08.2026). Любой сбой —
    просто нет фото: картинка украшение, расчёт от неё не зависит, поэтому
    наружу не роняется ничего.
    """
    try:
        made = _territory_image_png(numbers)
        if not made:
            return False
        _telegram_send_photo_bytes(chat_id, made[0], "territory.png", made[1])
        return True
    except Exception as exc:
        logging.info("Фото территории пропущено: %s", exc)
        return False

def _telegram_territory_photo_async(chat_id: int, numbers: list[str]) -> None:
    """Фото уходит фоном: сбор контуров и подложки ходит в НСПД и не должен
    держать ответ вебхука — правило «тяжёлое не считается внутри запроса»."""
    threading.Thread(
        target=_telegram_territory_photo, args=(chat_id, list(numbers)),
        name="territory-photo", daemon=True,
    ).start()


def _telegram_send_template(chat_id: int) -> Any:
    try:
        encoded = MANUAL_TEP_TEMPLATE_B64_PATH.read_text(encoding="ascii").strip()
        content = base64.b64decode(encoded, validate=True)
    except Exception as exc:
        raise RuntimeError("Excel-шаблон ТЭП повреждён или не найден") from exc
    if not content.startswith(b"PK"):
        raise RuntimeError("Excel-шаблон ТЭП повреждён")
    return _telegram_send_document_bytes(
        chat_id,
        content,
        MANUAL_TEP_TEMPLATE_FILENAME,
        (
            "<b>Excel-шаблон исходного ТЭП DevelopAid</b>\n\n"
            "1. Заполните общие сведения и жёлтые ячейки ТЭП.\n"
            "2. Не переименовывайте лист, не меняйте коды и не удаляйте строки.\n"
            "3. Сохраните файл в формате .xlsx и отправьте его обратно в этот чат.\n\n"
            "Бот проверит структуру, покажет сводку и предложит открыть проект в DevelopAid."
        ),
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


# Бот принимает не только шаблон ТЭП: тизер, справка по участку и решение ГЗК
# приходят в чат тем же способом, и переписывать их в модель руками — та самая
# работа, которую разбор снимает.
_TELEGRAM_DOCUMENT_EXTENSIONS = (".xlsx", ".pdf", ".png", ".jpg", ".jpeg")
_TELEGRAM_DOCUMENT_MAX_BYTES = 20 * 1024 * 1024


def _telegram_download_document(document: dict[str, Any], *,
    extensions: tuple[str,...] = _TELEGRAM_DOCUMENT_EXTENSIONS,
    max_bytes: int = _TELEGRAM_DOCUMENT_MAX_BYTES) -> tuple[bytes,str]:
    mime_extensions = {'application/pdf':'.pdf','image/png':'.png','image/jpeg':'.jpg',
        'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet':'.xlsx'}
    filename = str(document.get('file_name') or '').strip()[:180]
    if not filename:
        extension = mime_extensions.get(str(document.get('mime_type') or '').lower())
        if extension is None:
            raise ValueError('Telegram не передал имя или поддерживаемый тип файла. Пришлите PDF, XLSX, JPEG или PNG.')
        filename = 'Документ'+extension
    if not filename.lower().endswith(tuple(extensions)):
        raise ValueError('Бот принимает '+' и '.join(extensions)+': шаблон ТЭП, выгрузку ГлавАПУ или документ по участку')
    try:
        declared_size = int(document.get('file_size') or 0)
    except (ValueError,TypeError):
        raise ValueError('Telegram передал некорректный размер файла.') from None
    if declared_size < 0:
        raise ValueError('Telegram передал некорректный размер файла.')
    if declared_size > max_bytes:
        raise ValueError(f'Файл слишком большой. Лимит — {max_bytes//(1024*1024)} МБ')
    file_id = str(document.get('file_id') or '')
    if not file_id:
        raise ValueError('Telegram не передал идентификатор файла')
    return _telegram_file_bytes(file_id,max_bytes),filename


def _telegram_file_bytes(file_id: str, max_bytes: int) -> bytes:
    """One native getFile/download, capped bytes and remaining wall-clock IO."""
    import document_processing
    if type(max_bytes) is not int or not 0 < max_bytes <= 20*1024*1024:
        raise ValueError('Недопустимый предел размера файла Telegram.')
    document_processing.check()
    info = _telegram_api('getFile',{'file_id':file_id},timeout=document_processing.remaining(15)) or {}
    document_processing.check()
    if not isinstance(info,dict):
        raise ValueError('Telegram не подготовил сведения о файле.')
    file_path = str(info.get('file_path') or '')
    if not file_path:
        raise ValueError('Telegram не подготовил файл к загрузке')
    until = time.monotonic()+document_processing.remaining(20)
    url = f"https://api.telegram.org/file/bot{_telegram_token()}/{urllib.parse.quote(file_path,safe='/')}"
    def remaining():
        document_processing.check()
        left = until-time.monotonic()
        if left <= 0:
            raise TimeoutError('Telegram download deadline')
        return left
    try:
        with urllib.request.urlopen(url,timeout=remaining()) as response:
            data = _telegram_document_read_response(response,until,max_bytes)
            if not data:
                raise ValueError('Telegram вернул пустой файл. Пришлите документ заново.')
    except (document_processing.Cancelled,document_processing.Expired,ValueError):
        raise
    except Exception as exc:
        raise RuntimeError('Файл из Telegram не скачан ('+type(exc).__name__+'). Повторите загрузку.') from None
    return data


def _telegram_money_mln(value: Any) -> str:
    try:
        amount = float(value or 0)
    except Exception:
        amount = 0.0
    if abs(amount) >= 1000:
        return f"{amount / 1000:,.2f}".replace(",", " ").replace(".", ",") + " млрд ₽"
    return f"{amount:,.1f}".replace(",", " ").replace(".", ",") + " млн ₽"


def _telegram_number(value: Any, digits: int = 1) -> str:
    try:
        number = float(value or 0)
    except Exception:
        number = 0.0
    return f"{number:,.{digits}f}".replace(",", " ").replace(".", ",")


def _telegram_dialog_data_lines(data: dict[str, Any]) -> list[str]:
    fields = (
        ("site_area_ha", "территория", "га", 4),
        ("project_total_gns_sqm", "ГНС надземной части проекта", "м²", 0),
        ("apartments_gns_sqm", "жилая ГНС", "м²", 0),
        ("apartments_saleable_sqm", "продаваемая площадь квартир", "м²", 0),
        ("residential_density_spp_th_ha", "плотность по СПП", "тыс. м²/га", 2),
        ("commercial_saleable_sqm", "продаваемая коммерция", "м²", 0),
        ("commercial_gns_sqm", "ГНС коммерции", "м²", 0),
        ("parking_spaces", "паркинг", "м/м", 0),
        ("kindergarten_places", "ДОО", "мест", 0),
        ("school_places", "школа", "мест", 0),
        ("clinic_capacity", "поликлиника", "пос./смену", 0),
    )
    lines = [
        f"• {label} — {_telegram_number(data.get(key), digits)} {unit}"
        for key, label, unit, digits in fields
        if data.get(key) is not None
    ]
    if str(data.get("district") or "").strip():
        lines.append("• район — " + html.escape(str(data["district"])))
    return lines


def _telegram_dialog_has_primary(data: dict[str, Any]) -> bool:
    return any(
        float(data.get(key) or 0) > 0
        for key in (
            "project_total_gns_sqm", "apartments_gns_sqm",
            "apartments_saleable_sqm", "residential_density_spp_th_ha",
        )
    )


def _telegram_dialog_merge(data: dict[str, Any], recognized: dict[str, Any]) -> int:
    allowed = {
        "project_name", "district", "site_area_ha", "project_total_gns_sqm",
        "apartments_saleable_sqm", "apartments_gns_sqm", "residential_density_spp_th_ha",
        "commercial_saleable_sqm", "commercial_gns_sqm", "parking_spaces", "storage_units",
        "kindergarten_places", "school_places", "clinic_capacity",
        "land_rights_cost_mln", "social_compensation_mln",
    }
    count = 0
    for key in allowed:
        value = recognized.get(key)
        if value is None or value == "":
            continue
        data[key] = value
        count += 1
    return count


def _telegram_dialog_primary_menu(chat_id: int) -> None:
    _telegram_send_message(
        chat_id,
        "<b>Что известно по объёму застройки?</b>\n\n"
        "Выберите один основной показатель. Остальные DevelopAid рассчитает из него.",
        reply_markup={"inline_keyboard": [
            [{"text": "ГНС проекта", "callback_data": "flow_primary_gns"}],
            [{"text": "Продаваемая площадь квартир", "callback_data": "flow_primary_saleable"}],
            [{"text": "Плотность застройки", "callback_data": "flow_primary_density"}],
            [{"text": "Знаю несколько показателей", "callback_data": "flow_primary_multiple"}],
            [{"text": "Начать заново", "callback_data": "flow_restart"}],
        ]},
    )


def _telegram_dialog_extras_menu(chat_id: int, dialog: dict[str, Any]) -> None:
    dialog["step"] = "extras"
    _telegram_dialog_save(chat_id, dialog)
    lines = _telegram_dialog_data_lines(dialog.get("data") or {})
    known = "\n".join(lines) if lines else "• пока ничего"
    _telegram_send_message(
        chat_id,
        "<b>Основы собраны</b>\n\n"
        "Сейчас известно:\n" + known + "\n\n"
        "Добавьте любые известные параметры. Когда закончите, нажмите "
        "<b>«Рассчитать недостающее»</b> — DevelopAid заполнит остальное ориентировочно по нормативам.",
        reply_markup={"inline_keyboard": [
            [
                {"text": "Коммерция", "callback_data": "flow_extra_commercial"},
                {"text": "Паркинг", "callback_data": "flow_extra_parking"},
            ],
            [
                {"text": "Соцобъекты", "callback_data": "flow_extra_social"},
                {"text": "Район", "callback_data": "flow_extra_district"},
            ],
            [{"text": "Другие параметры сообщением", "callback_data": "flow_extra_other"}],
            [{"text": "Рассчитать недостающее", "callback_data": "flow_calculate"}],
            [{"text": "Начать заново", "callback_data": "flow_restart"}],
        ]},
    )


def _telegram_dialog_callback(chat_id: int, user_id: int, action: str) -> None:
    if action == "flow_restart":
        _telegram_dialog_clear(chat_id)
        _telegram_start_message(chat_id, user_id)
        return
    if action == "flow_cad_yes":
        _telegram_dialog_save(chat_id, {"step": "await_cadastre", "data": {}})
        _telegram_send_message(
            chat_id,
            "<b>Введите все кадастровые номера</b>\n\n"
            "Можно через запятую или каждый с новой строки. Например:\n"
            "<code>77:02:0016009:1934, 77:02:0016009:1935</code>",
        )
        return
    if action == "flow_address":
        _telegram_dialog_save(chat_id, {"step": "await_address", "data": {}})
        _telegram_send_message(
            chat_id,
            "<b>Введите адрес участка</b>\n\n"
            "Например: <code>Московская область, Мытищи, Олимпийский проспект, 29</code>.\n"
            "Можно и координатами через запятую: <code>55.9105, 37.7365</code>.\n\n"
            "DevelopAid найдёт участок в ЕГРН и посчитает территорию. "
            "Выдача фильтруется до земельных участков — квартир и машино-мест в ней не будет.",
        )
        return
    if action == "flow_cad_no":
        _telegram_dialog_save(chat_id, {"step": "await_site_area", "data": {}})
        _telegram_send_message(
            chat_id,
            "<b>Какая площадь территории?</b>\n\n"
            "Напишите в гектарах или квадратных метрах, например: <code>2,4 га</code> или <code>24 000 м²</code>.",
        )
        return

    dialog = _telegram_dialog_get(chat_id)
    if not dialog:
        _telegram_send_message(chat_id, "Расчёт не найден или устарел. Начнём заново.")
        _telegram_start_message(chat_id, user_id)
        return

    if action == "flow_cad_choose_class":
        _telegram_cad_class_menu(chat_id, dialog)
        return
    if action in {"flow_cad_class_comfort", "flow_cad_class_business", "flow_cad_class_elite"}:
        key = action.removeprefix("flow_cad_class_")
        preset = PROJECT_CLASS_PRESETS[key]
        data = dialog.setdefault("data", {})
        data["project_class"] = key
        data["prices_custom"] = False
        data["apartment_price_th"] = float(preset["apartment_price_th"])
        data["commercial_price_th"] = float(preset["commercial_price_th"])
        data["parking_price_th"] = float(preset["parking_price_th"])
        data["smr_th_per_sqm"] = _telegram_class_smr(key)
        _telegram_send_cad_calculate_button(chat_id, dialog)
        return
    if action == "flow_cad_class_custom":
        data = dialog.setdefault("data", {})
        if str(data.get("project_class") or "") not in PROJECT_CLASS_PRESETS:
            _telegram_cad_class_menu(chat_id, dialog)
            return
        dialog["step"] = "await_cad_apartment_price"
        data["prices_custom"] = True
        _telegram_dialog_save(chat_id, dialog)
        _telegram_send_message(
            chat_id,
            "<b>Изменить цены реализации</b>\n\n"
            "СМР останется из выбранного класса.\n\n"
            "Введите цену продажи жилья в тыс. ₽/м², например <code>420</code> или <code>1,2 млн</code>.",
        )
        return

    prompts = {
        "flow_primary_gns": (
            "project_total_gns_sqm", "await_value",
            "<b>Введите ГНС надземной части проекта</b> без паркинга и соцобъектов, в м².",
        ),
        "flow_primary_saleable": (
            "apartments_saleable_sqm", "await_value",
            "<b>Введите продаваемую площадь квартир</b> в м².",
        ),
        "flow_primary_density": (
            "residential_density_spp_th_ha", "await_value",
            "<b>Введите плотность застройки</b> в тыс. м² СПП на гектар, например <code>28,5</code>.",
        ),
        "flow_extra_parking": (
            "parking_spaces", "await_value",
            "<b>Сколько машино-мест предусмотрено?</b> Введите общее количество.",
        ),
        "flow_extra_district": (
            "district", "await_text",
            "<b>Введите район Москвы</b>, например <code>Коммунарка</code>. Если это другой регион — напишите город или район.",
        ),
    }
    if action in prompts:
        key, step, prompt = prompts[action]
        dialog["step"] = step
        dialog["pending_key"] = key
        _telegram_dialog_save(chat_id, dialog)
        _telegram_send_message(chat_id, prompt)
        return
    if action == "flow_primary_multiple":
        dialog["step"] = "await_primary_multiple"
        _telegram_dialog_save(chat_id, dialog)
        _telegram_send_message(
            chat_id,
            "<b>Напишите известные показатели одним сообщением</b>\n\n"
            "Например: <code>ГНС проекта 70 000 м², квартиры 42 000 м² продаваемой площади, коммерция 2 500 м²</code>.",
        )
        return
    if action == "flow_extra_commercial":
        _telegram_send_message(
            chat_id,
            "<b>Что известно по встроенной коммерции?</b>",
            reply_markup={"inline_keyboard": [
                [{"text": "Продаваемая площадь", "callback_data": "flow_commercial_saleable"}],
                [{"text": "ГНС коммерции", "callback_data": "flow_commercial_gns"}],
                [{"text": "Назад", "callback_data": "flow_extras"}],
            ]},
        )
        return
    if action in {"flow_commercial_saleable", "flow_commercial_gns"}:
        dialog["step"] = "await_value"
        dialog["pending_key"] = (
            "commercial_saleable_sqm" if action.endswith("saleable") else "commercial_gns_sqm"
        )
        _telegram_dialog_save(chat_id, dialog)
        label = "продаваемую площадь" if action.endswith("saleable") else "ГНС"
        _telegram_send_message(chat_id, f"<b>Введите {label} встроенной коммерции</b> в м².")
        return
    if action == "flow_extra_social":
        dialog["step"] = "await_social"
        _telegram_dialog_save(chat_id, dialog)
        _telegram_send_message(
            chat_id,
            "<b>Введите известные мощности соцобъектов</b>\n\n"
            "Например: <code>ДОО 150 мест, школа 300 мест, поликлиника 100 посещений в смену</code>. "
            "Можно указать только один объект.",
        )
        return
    if action == "flow_extra_other":
        dialog["step"] = "await_other"
        _telegram_dialog_save(chat_id, dialog)
        _telegram_send_message(
            chat_id,
            "<b>Напишите остальные известные параметры одним сообщением</b>\n\n"
            "DevelopAid распознает их и вернёт вас в меню проверки.",
        )
        return
    if action in {"flow_extras", "flow_edit"}:
        _telegram_dialog_extras_menu(chat_id, dialog)
        return
    if action == "flow_calculate":
        try:
            parsed = build_freeform_tep("", raw_values=dialog.get("data") or {})
        except (ValueError, RuntimeError) as exc:
            _telegram_send_message(chat_id, "<b>Пока не могу рассчитать ТЭП.</b>\n" + html.escape(str(exc)))
            return
        _telegram_send_tep_review(chat_id, parsed, dialog_mode=True)
        return


@_telegram_intake_serialized
def _telegram_handle_dialog_text(chat_id: int, text: str) -> bool:
    dialog = _telegram_dialog_get(chat_id)
    if not dialog:
        return False
    step = str(dialog.get("step") or "")
    if (step in {"await_intake_answer", "intake_document_reading", "intake_document_failed"}
            and _TELEGRAM_INTAKE_LOCKED.get() != int(chat_id)):
        return _telegram_handle_dialog_text(chat_id, text)
    data = dialog.setdefault("data", {})
    try:
        if step in {"intake_document_reading", "intake_document_failed"}:
            if str(text).strip().lower() in {"стоп", "/стоп", "/stop", "отмена"}:
                previous = (dialog.pop("document_read", None) or {}).get("previous_step")
                if (dialog.get("intake") or {}).get("id"):
                    dialog["step"] = previous or "intake_card"
                    _telegram_dialog_save(chat_id, dialog)
                    _telegram_send_message(chat_id, "Чтение отменено. Возвращаю сохранённый разбор.")
                    _telegram_intake_ask_next(chat_id, dialog)
                else:
                    _telegram_dialog_clear(chat_id)
                    _telegram_send_message(chat_id, "Чтение документа отменено.")
                return True
            _telegram_send_message(chat_id,
                "Разбор ещё не завершён; ответ на предыдущую карточку пока не принят. "
                "Команда /cancel отменит чтение."
                if (dialog.get("document_read") or {}).get("status") == "loading" else
                "Разбор документа не завершён. Предыдущие ответы сохранены; "
                "вернуться к ним можно через /calc.")
            return True
        if step == "await_address":
            _telegram_dialog_clear(chat_id)
            _telegram_handle_address(chat_id, text)
            return True
        if step == "await_cadastre":
            # В поле для номеров могут прислать адрес — не заставляем начинать заново.
            try:
                numbers = _parse_cadastral_numbers(text)
            except HTTPException:
                if not _looks_like_address(text):
                    raise
                _telegram_dialog_clear(chat_id)
                _telegram_handle_address(chat_id, text)
                return True
            _telegram_dialog_clear(chat_id)
            _telegram_handle_cadastral_numbers(chat_id, numbers, text)
            return True
        if step == "await_site_area":
            data["site_area_ha"] = _telegram_dialog_number(text, site_area=True)
            dialog["step"] = "choose_primary"
            _telegram_dialog_save(chat_id, dialog)
            _telegram_dialog_primary_menu(chat_id)
            return True
        if step == "await_cad_apartment_price":
            data["apartment_price_th"] = _telegram_econ_value_th(text)
            dialog["step"] = "await_cad_commercial_price"
            _telegram_dialog_save(chat_id, dialog)
            _telegram_send_message(chat_id, "<b>Цена продажи нежилья / коммерции</b>\n\nВведите в тыс. ₽/м², например <code>450</code>.")
            return True
        if step == "await_cad_commercial_price":
            data["commercial_price_th"] = _telegram_econ_value_th(text)
            dialog["step"] = "await_cad_parking_price"
            _telegram_dialog_save(chat_id, dialog)
            _telegram_send_message(chat_id, "<b>Цена машино-места</b>\n\nВведите в тыс. ₽ за место, например <code>2500</code>, или <code>2,5 млн</code>.")
            return True
        if step == "await_cad_parking_price":
            data["parking_price_th"] = _telegram_econ_value_th(text)
            _telegram_send_cad_calculate_button(chat_id, dialog)
            return True
        if step == "await_intake_answer":
            intake = dialog.get("intake") or {}
            queue = _telegram_intake_card(chat_id, dialog)
            if queue is None:
                return True
            index = int(queue.get("index") or 0)
            said = str(text or "").strip()
            try:
                _telegram_intake_expect_shown(queue, intake)
            except HTTPException as exc:
                if exc.status_code != 409:raise
                _telegram_intake_queue_conflict(chat_id, dialog, {"index":index,"action":"answer","value":said})
                return True
            pending = intake.get("pending_choice") or {}
            choice = int(pending.get("choice", -1)) if int(pending.get("index", -1)) == index else -1
            legacy = choice >= 0 and pending.get("intake_id") != queue.get("id")
            if said.lower() in {"стоп", "/стоп", "/stop", "хватит", "отмена", "/cancel"}:
                # Прекратить разговор — законный ответ, а не сбой. Отвеченное
                # до этого не выбрасывается: человек уже потратил на него время.
                _telegram_intake_answer(chat_id, dialog, index=index, action="stop",
                    choice=-1 if legacy else choice, proposal=pending if legacy else None)
                return True
            if said in {"-", "—", "?"} or said.lower() in {"пропустить", "не знаю"}:
                _telegram_intake_answer(chat_id, dialog, index=index, action="skip",
                    choice=-1 if legacy else choice, proposal=pending if legacy else None)
                return True
            if legacy:
                _telegram_send_message(chat_id,
                    "Предыдущий выбор сохранён как предложение. Сначала подтвердите способ учёта "
                    "для текущего документа кнопкой; денежная сумма пока не принята.")
                _telegram_intake_ask_next(chat_id, dialog)
                return True
            cards = queue.get("cards") or []
            if not 0 <= index < len(cards):
                _telegram_intake_ask_next(chat_id, dialog)
                return True
            options = (cards[index].get("options") or []) if index < len(cards) else []
            if choice < 0 and said.isdigit() and 1 <= int(said) <= len(options):
                # «2» — номер варианта, если вариантов столько есть.
                choice, said = int(said) - 1, ""
            if choice < 0:
                matching = [n for n, option in enumerate(options)
                            if str(option.get("label") or "").strip().lower() == said.lower()]
                if len(matching) == 1:
                    choice, said = matching[0], ""
            if choice < 0 and cards[index].get("adds") and any(option.get("target") for option in options):
                _telegram_send_message(chat_id, "Сначала выберите вариант учёта кнопкой или его номером.")
                _telegram_intake_ask_next(chat_id, dialog)
                return True
            if (not said and 0 <= choice < len(options) and options[choice].get("target")
                    and options[choice].get("value") is None):
                intake["pending_choice"] = {"index": index, "choice": choice, "intake_id": queue["id"],
                    **_telegram_intake_queue_binding(queue)}
                dialog["intake"] = intake
                _telegram_dialog_save(chat_id, dialog)
                _telegram_intake_amount_prompt(chat_id, cards[index], index, choice, queue["id"], _intake_question_token(queue))
                return True
            _telegram_intake_answer(chat_id, dialog, index=index, action="answer",
                                    choice=choice, value=said)
            return True
        if step == "await_value":
            key = str(dialog.get("pending_key") or "")
            if not key:
                raise ValueError("Не найден ожидаемый показатель")
            value = _telegram_dialog_number(text)
            if key in {"parking_spaces", "storage_units"}:
                value = int(round(value))
            data[key] = value
            dialog.pop("pending_key", None)
            _telegram_dialog_extras_menu(chat_id, dialog)
            return True
        if step == "await_text":
            key = str(dialog.get("pending_key") or "")
            value = str(text or "").strip()[:120]
            if not value:
                raise ValueError("Ответ пустой")
            data[key] = value
            dialog.pop("pending_key", None)
            _telegram_dialog_extras_menu(chat_id, dialog)
            return True
        if step in {"await_primary_multiple", "await_social", "await_other", "extras"}:
            recognized = _recognize_freeform_tep_text(text)
            if step == "await_social":
                recognized = {
                    key: recognized.get(key)
                    for key in ("kindergarten_places", "school_places", "clinic_capacity")
                }
            added = _telegram_dialog_merge(data, recognized)
            if not added:
                raise ValueError("Не удалось распознать ни одного показателя")
            if step == "await_primary_multiple" and not _telegram_dialog_has_primary(data):
                raise ValueError("Укажите ГНС, продаваемую площадь квартир либо плотность")
            _telegram_dialog_extras_menu(chat_id, dialog)
            return True
        if step == "choose_primary":
            _telegram_dialog_primary_menu(chat_id)
            return True
    except (ValueError, RuntimeError, HTTPException) as exc:
        detail = exc.detail if isinstance(exc, HTTPException) else str(exc)
        _telegram_send_message(
            chat_id,
            "<b>Не удалось принять ответ.</b>\n" + html.escape(str(detail)) + "\n\nПопробуйте ещё раз или нажмите /start.",
        )
        return True
    return False


def _telegram_calc_menu(chat_id: int) -> None:
    """Второй уровень «Расчёта модели»: четыре способа взять ТЭП.

    В плоском списке команд они стояли четырьмя похожими строками, и выбирать
    приходилось между функциями, которые на вид не отличались. Расчёт при этом
    один и тот же — разное только то, откуда берутся исходные данные, и здесь
    это видно.
    """
    rows = [
        [{"text": "Свои вводные, без кадастра", "callback_data": "flow_cad_no"}],
        [{"text": "По адресу участка", "callback_data": "flow_address"}],
        [{"text": "По кадастровому номеру", "callback_data": "flow_cad_yes"}],
        [{"text": "Скачать Excel-шаблон ТЭП", "callback_data": "tep_template"}],
    ]
    if ((dialog := _telegram_dialog_get(chat_id) or {}).get("intake") or {}).get("id"):
        rows.insert(0, [{"text": "Продолжить разбор сохранённого тизера",
                          "callback_data": _telegram_intake_callback_data(
                              dialog["intake"]["id"], "questions")}])
    _telegram_send_message(
        chat_id,
        "<b>Расчёт модели</b>\n"
        "Откуда взять ТЭП проекта?",
        reply_markup={"inline_keyboard": rows},
    )


def _report_mailing_call(path: str, code: str, chat_id: int, **fields: Any) -> dict[str, Any]:
    """Маршрут рассылки сводки на ядре — по сети с Render, напрямую на ядре."""
    payload = {"chat_id": int(chat_id), "sign": _web_login_sign(code, int(chat_id)), **fields}
    remote = _projects_remote_url(path)
    if remote:
        return _core_post(remote, payload, 60.0)
    handler = {"/internal/report/subscribe": internal_report_subscribe,
               "/internal/report/unsubscribe": internal_report_unsubscribe,
               "/internal/report/outbox": internal_report_outbox,
               "/internal/report/sent": internal_report_sent}[path]
    return handler(ReportMailingInternalRequest(**payload))


def _report_slot_words(slot: dict[str, Any]) -> str:
    when = datetime.fromisoformat(str(slot.get("at"))).strftime("%d.%m.%Y")
    what = "за неделю" if slot.get("kind") == "week" else "за месяц"
    return f"{when} в 9:00 по Москве ({what})"


def _telegram_report_subscribe(chat_id: int, start: str, name: str) -> None:
    try:
        got = _report_mailing_call("/internal/report/subscribe", "report-subscribe",
                                   chat_id, start=start, name=name)
    except HTTPException as exc:
        _telegram_send_message(chat_id, "<b>Подписка не оформлена.</b>\n"
                               + html.escape(str(exc.detail)))
        return
    except Exception as exc:  # noqa: BLE001 — человек должен узнать, что не вышло
        _telegram_send_message(chat_id, "<b>Подписка не оформлена.</b>\n"
                               + html.escape(f"Сервер сводок не ответил: {exc}"))
        return
    _telegram_send_message(
        chat_id,
        f"<b>Вы подписаны на сводку руководству по проекту «{html.escape(got['project'])}».</b>\n"
        "Сводка приходит сообщением и PDF: за неделю — по понедельникам, за месяц — "
        "1-го числа, в 9:00 по Москве. Ближайшая — "
        f"{_report_slot_words(got.get('next') or {})}.\n"
        "Отписаться: /report_stop")


def _telegram_report_unsubscribe(chat_id: int) -> None:
    try:
        got = _report_mailing_call("/internal/report/unsubscribe", "report-unsubscribe", chat_id)
    except Exception as exc:  # noqa: BLE001
        detail = exc.detail if isinstance(exc, HTTPException) else exc
        _telegram_send_message(chat_id, "<b>Отписка не прошла.</b>\n"
                               + html.escape(f"Сервер сводок не ответил: {detail}"))
        return
    projects = got.get("projects") or []
    _telegram_send_message(
        chat_id,
        ("<b>Вы отписаны от сводки</b> по "
         + ", ".join(f"«{html.escape(name)}»" for name in projects) + ".")
        if projects else "Подписок на сводку руководству у этого чата нет.")


_INVITE_SOURCE_RE = re.compile(r"^[A-Za-z0-9_-]{1,32}$")


def _telegram_invite_source(payload: str) -> str:
    """Метка приглашения из «/start <метка>».

    Payload приходит снаружи, поэтому в журнал попадает только то, что похоже
    на метку: буквы, цифры, дефис и подчёркивание. Подтверждение входа на сайт
    (`login_…`) меткой не считается — это другой сценарий.
    """
    value = str(payload or "").strip()
    if not value or value.startswith(("login_", "rep_")):
        return ""
    return value if _INVITE_SOURCE_RE.match(value) else ""


def _telegram_sender_name(message: dict[str, Any]) -> str:
    """Имя для журнала: как человек подписан в Telegram."""
    sender = (message or {}).get("from") or {}
    parts = [str(sender.get("first_name") or ""), str(sender.get("last_name") or "")]
    name = " ".join(part for part in parts if part).strip()
    login = str(sender.get("username") or "").strip()
    if login:
        name = f"{name} @{login}".strip()
    return name


def _telegram_start_message(chat_id: int, user_id: int, source: str = "") -> None:
    if not _telegram_user_allowed(user_id):
        _telegram_send_message(
            chat_id,
            "<b>Доступ к DevelopAid пока не открыт.</b>\n"
            f"Ваш Telegram ID: <code>{user_id}</code>\n"
            "Добавьте его в TELEGRAM_ALLOWED_USER_IDS в Render.",
        )
        return
    _telegram_dialog_clear(chat_id)
    # Пришедшему по приглашению первой идёт кнопка сайта: он ещё не знает ни
    # адреса, ни того, что тут есть. Читать список сценариев бота он не станет —
    # ему нужно увидеть расчёт, а не меню.
    invited = [[{"text": "Открыть DevelopAid — полный расчёт",
                 "web_app": {"url": _telegram_web_app_url(chat_id, [])}}]] if source else []
    # Приветствие говорит теми же словами, что список команд слева внизу:
    # те же решения и в том же порядке (решение владельца, 18.08.2026). Прежде
    # здесь стояли восемь конкретных входов, а в списке команд — шесть решений,
    # и один продукт объяснялся двумя разными словарями. Способ («по кадастру,
    # по адресу, без кадастра, шаблон») спрашивается вторым уровнем — тем же
    # `_telegram_calc_menu`, что и у команды /calc.
    button = {"inline_keyboard": invited + [
        [{"text": "Расчёт модели", "callback_data": "calc_menu"}],
        [{"text": "Открыть готовую модель", "web_app": {"url": _telegram_web_app_url(chat_id, [])}}],
        [{"text": "Расчёт ВРИ и ТЭП", "callback_data": "vritep_start"}],
        # Сюда расширение вставляет «Льгота МПТ» — перед помощью, как в списке команд.
        [{"text": "Платон Сергеевич", "callback_data": "ask_platon"}],
        [{"text": "Что умеет DevelopAid", "callback_data": "show_help"}],
    ]}
    _telegram_send_message(
        chat_id,
        ("<b>Спасибо, что зашли посмотреть.</b> Это рабочая версия, и нам важно, "
         "что в ней не сходится с вашей практикой — кнопка выше открывает расчёт, "
         "войти отдельно не нужно.\n\n" if source else "")
        + "<b>Добро пожаловать в DevelopAid</b>\n\n"
        "Если на переговорах в «Кофемании» нужно за пять минут отфильтровать 50–60 земельных участков, "
        "на встрече — на пальцах объяснить региональному девелоперу, почему трёхлетний БРИДЖ не позволяет "
        "купить проект по 100 тысяч рублей за метр, или вы просто решили немного оптимизировать расходы "
        "на аналитиков перед покупкой проекта в Ховрино — <b>DevelopAid вам поможет</b>.\n\n"
        "Модель работает с проектами <b>по всей России</b>, а не только в Москве.\n\n"
        "Считает плату за изменение ВРИ (Москва и область) и собирает ТЭП "
        "по нормативам ГлавАПУ прямо из кадастра.\n\n"
        "Начать расчёт можно:\n"
        "• по кадастровым номерам участков;\n"
        "• без кадастра, ответив на вопросы бота;\n"
        "• загрузив заполненный Excel-шаблон.\n\n"
        "После первичного расчёта проект можно открыть в мини-приложении и настроить практически всё:\n"
        "• ТЭП и состав продуктов;\n"
        "• цены и темпы продаж;\n"
        "• себестоимость и сроки строительства;\n"
        "• прогноз ключевой ставки;\n"
        "• БРИДЖ и проектное финансирование;\n"
        "• очередность проекта;\n"
        "• распределение расходов и социальной нагрузки;\n"
        "• строительство или компенсацию социальных объектов;\n"
        "• сценарии изменения доходов и затрат.\n\n"
        "DevelopAid рассчитает экономику, потребность в финансировании, динамику долга и эскроу, прибыль, "
        "маржинальность и LLCR, а также сформирует PDF-отчёт с графиками и календарным планом — "
        "и живую Excel-модель со всеми формулами: открывайте, проверяйте, показывайте банку.\n\n"
        "<i>Доплату по коэффициенту Д, увы, пока не предсказывает.</i>\n\n"
        "<b>С чего начнём?</b>",
        reply_markup=button,
    )


def _telegram_document_begin(chat_id: int, filename: str) -> dict:
    import document_processing
    deadline = time.monotonic()+240
    request = _telegram_agent_request(chat_id)
    nonce = _telegram_intake_begin(chat_id,filename)
    persisted = (_telegram_dialog_get(chat_id) or {}).get('document_read') or {}
    if persisted.get('id') != nonce:
        raise document_processing.Cancelled()
    deadline = min(deadline,time.monotonic()+max(0,float(persisted['deadline_at'])-time.time()))
    return {'chat_id':chat_id,'nonce':nonce,'root':Path(_PLATO_STAGE_DIR).absolute(),
            'request':request,'actor':request.scope['plato_actor'],'deadline':deadline}


def _telegram_document_current(operation: dict, *, allow_failed: bool = False) -> bool:
    return (Path(_PLATO_STAGE_DIR).absolute() == operation['root'] and
            _telegram_intake_current(operation['chat_id'],operation['nonce'],allow_failed=allow_failed))


def _telegram_document_closed(operation: dict) -> bool:
    if not _telegram_document_current(operation,allow_failed=True):
        return False
    read = (_telegram_dialog_get(operation['chat_id']) or {}).get('document_read') or {}
    return read.get('id') == operation['nonce'] and read.get('status') in {'failed','interrupted'}


def _telegram_document_reply(operation: dict, text: str, *, reply_markup=None, allow_failed=False) -> bool:
    import document_processing
    from telegram_intake_text import split_intake_html
    current = (lambda:_telegram_document_closed(operation)) if allow_failed else (
        lambda:_telegram_document_current(operation))
    if not current():
        return False
    parts = split_intake_html(text)
    try:
        # Failed processing is already closed in state. Its best-effort error
        # notification still has the native15s send budget, never a new read.
        scope = (document_processing.notification(current=current) if allow_failed else
                 document_processing.operation(current=current,seconds=15))
        with scope:
            for index,part in enumerate(parts):
                if not current():
                    return False
                _telegram_send_intake_text(operation['chat_id'],part,
                    reply_markup=reply_markup if index==len(parts)-1 else None)
    except document_processing.Cancelled:
        return False
    return True


def _telegram_document_interrupted(operation) -> None:
    if operation is None or not _telegram_document_current(operation,allow_failed=True):
        return
    state = (_telegram_dialog_get(operation['chat_id']) or {}).get('document_read') or {}
    if state.get('status') == 'interrupted':
        _telegram_document_reply(operation,'<b>Ожидание чтения документа завершено.</b>\n'
            'Процесс был прерван или превысил время ожидания. Результат этого чтения неизвестен и не принят в расчёт. '
            'Пришлите документ снова или явно вернитесь к предыдущей карточке.',allow_failed=True)


def _telegram_document_publish(operation: dict, filename: str, *, queue=None, context=None):
    """Only bounded local publication holds the native chat lock."""
    import document_processing
    document_processing.check()
    def commit(dialog):
        if not _telegram_document_current(operation):
            raise document_processing.Cancelled()
        fresh = _telegram_agent_request(operation['chat_id']).scope['plato_actor']
        if fresh.metadata() != operation['actor'].metadata():
            raise document_processing.Cancelled()
        if queue is not None:
            _intake_queue_publish(queue,operation['actor'],short=True)
            dialog['intake'] = {'id':queue['id'],'filename':filename,
                                'region':operation.get('region','')}
            dialog['step'] = 'intake_card'
        else:
            dialog.pop('intake',None)
            dialog['step'] = 'manual_ready'
        dialog['document_read'].update(status='ready',filename=filename,
            source_sha256=operation.get('source_sha256'))
        _telegram_dialog_save(operation['chat_id'],dialog)
        # Native memory persistence is local JSON; no provider/send is called.
        return (_telegram_platon_remember_document(operation['chat_id'],context)
                if context is not None else '')
    accepted,result = _telegram_intake_commit(operation['chat_id'],operation['nonce'],commit)
    if not accepted:
        raise document_processing.Cancelled()
    return result


def _telegram_document_fail(operation, reason: str, heading: str = 'Разбор не завершён.', *, error=None) -> None:
    if operation is None:
        return
    def commit(dialog):
        dialog['step'] = 'intake_document_failed'
        dialog['document_read'].update(status='failed')
        _telegram_dialog_save(operation['chat_id'],dialog)
    accepted,_ = _telegram_intake_commit(operation['chat_id'],operation['nonce'],commit)
    if not accepted:
        if error is not None and _telegram_document_current(operation,allow_failed=True):
            state = _telegram_dialog_get(operation['chat_id']) or {}
            if (state.get('document_read') or {}).get('status') == 'ready':
                raise error  # Saved card: preserve native send-error/429 handling above.
        _telegram_document_interrupted(operation)
        return
    if error is not None:
        where = _error_location(error)
        if '429' in where or 'Too Many Requests' in where:
            raise error  # Native top-level rate-limit handling must not send again.
    _telegram_document_reply(operation,'<b>'+html.escape(heading)+'</b>\n'+html.escape(reason)
        +'\n\nДанные этого чтения в расчёт не приняты. Повторите загрузку или введите данные вручную.',allow_failed=True)


def _telegram_document_error(exc, stage: str) -> str:
    import document_processing
    if isinstance(exc,document_processing.Expired):
        return document_processing.Expired.public_message
    if isinstance(exc,ValueError):
        return str(exc)
    if isinstance(exc,HTTPException):
        if exc.status_code == 503:
            return 'Разбор не удалось сохранить на сервере. Продолжение и расчёт не начаты.'
        if exc.status_code in (401,403):
            return 'Доступ к разбору изменился. Откройте документ из своего чата заново.'
        if exc.status_code == 504:
            return 'Истекло время ожидания разбора. Модель не завершила чтение документа.'
    return 'Не завершён этап «'+stage+'» ('+type(exc).__name__+'). Источник не подтверждён.'


def _telegram_handle_intake_url(chat_id: int, url: str) -> None:
    import document_source
    import document_processing
    operation = None
    try:
        operation = _telegram_document_begin(chat_id,'Документ по ссылке')
        with document_processing.operation(current=lambda:_telegram_document_current(operation),deadline=operation['deadline']):
            _telegram_document_reply(operation,'<b>Ссылка принята. Загружаю документ…</b>')
            _intake_queue_cleanup()
            loaded = document_source.read_url(url,timeout=document_processing.remaining(20))
            document_processing.check()
            operation['source_sha256'] = hashlib.sha256(
                loaded.get('data') or str(loaded.get('text') or '').encode('utf-8')).hexdigest()
            document = ({'text':loaded['text'],'pages':1,'pages_read':1,
                         'filename':loaded['filename'],'recognized':False,'reason':''}
                        if 'text' in loaded else document_intake.extract_text(loaded['data'],loaded['filename']))
            document['source'] = loaded['source']
            _telegram_handle_intake_document(chat_id,loaded.get('data') or b'',loaded['filename'],
                                            document_override=document,_operation=operation)
    except document_processing.Cancelled:
        _telegram_document_interrupted(operation)
        return
    except Exception as exc:
        reason = str(exc) if isinstance(exc,document_source.DocumentSourceError) else _telegram_document_error(exc,'загрузка ссылки')
        if operation is None:
            _telegram_send_intake_text(chat_id,'<b>Не удалось начать чтение ссылки.</b>\n'+html.escape(reason))
        else:
            _telegram_document_fail(operation,reason,'Не удалось прочитать ссылку.',error=exc)


def _telegram_handle_glavapu_document(chat_id: int, data: bytes, filename: str, *, _operation=None) -> bool:
    """Файл формата калькулятора ГлавАПУ, присланный прямо в чат.

    Подпись к выгрузке кнопки «Посчитать ВРИ и ТЭП» обещает, что файл
    «можно загрузить в DevelopAid как обычный ТЭП», — а чат принимал только
    шаблон DevelopAid, и обещание работало лишь через мини-приложение."""
    try:
        parsed = parse_glavapu_xlsx(data, filename)
    except Exception:
        return False
    normalized = parsed.get("normalized") or {}
    # Разбор не отказывается от чужой книги: он ищет свои подписи, ничего не
    # находит и возвращает набор из одних None. Дальше файл шёл как «распознан»,
    # и человек получал сводку из нулей — «территория 0,0000 га, квартиры 0 м²»
    # — вместо ответа, что это не тот формат. Считаем по числам: из 61 ключа
    # непустым в чужом файле остаётся один, и тот не вычитан, а подставлен
    # разбором по умолчанию (suggested_social_mode).
    if not any(isinstance(value, (int, float)) and not isinstance(value, bool) and value
               for value in normalized.values()):
        return False
    mappings = parsed.get("mappings") or {}
    session = {
        "project_name": "",
        "region": "Москва",
        "site_area_ha": normalized.get("site_area_ha") or 0,
        "source": parsed.get("source") or {},
        "inputs": {
            **(mappings.get("inputs") or {}),
            "_glavapu_import": {
                "source": parsed.get("source") or {},
                "normalized": normalized,
                "recognized": parsed.get("recognized") or [],
                "warnings": parsed.get("warnings") or [],
                "mappings": mappings,
            },
        },
        "tep": mappings.get("tep") or {},
    }
    button = {"inline_keyboard": [[{
        "text": "Открыть ТЭП в DevelopAid",
        "web_app": {"url": _telegram_web_app_url(chat_id, [], session)},
    }]]}
    if _operation is not None:
        _telegram_document_publish(_operation,filename)
    sender = (_telegram_send_message if _operation is None else
              lambda chat,text,**kwargs:_telegram_document_reply(_operation,text,**kwargs))
    sender(
        chat_id,
        "<b>Файл калькулятора ГлавАПУ распознан</b>\n"
        f"Территория: <b>{_telegram_number(normalized.get('site_area_ha'), 4)} га</b>\n"
        f"Квартиры: <b>{_telegram_number(normalized.get('apartment_area_sqm'), 0)} м²</b>\n"
        f"Смена ВРИ: <b>{_telegram_money_mln(normalized.get('change_vri_mln'))}</b>\n"
        f"Социальная компенсация: <b>{_telegram_money_mln(normalized.get('social_compensation_total_mln'))}</b>\n\n"
        "Проверьте сводку и откройте модель — ТЭП перенесётся целиком.",
        reply_markup=button,
    )
    return True


def _telegram_agent_request(chat_id: int) -> Request:
    """Server-owned public actor for this exact Telegram chat, never an admin."""
    request = _agent_bind_bot_request(Request({
        "type": "http", "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1", "method": "POST", "scheme": "https",
        "path": "/telegram/intake", "raw_path": b"/telegram/intake",
        "query_string": b"", "headers": [],
        "client": ("telegram", int(chat_id)), "server": ("developaid", 443),
    }), chat_id)
    request.scope["plato_actor"] = _agent_resolve_actor(None, request)
    return request


def _telegram_platon_remember_document(chat_id: int, context: dict[str, Any]) -> str:
    """Положить разобранный документ в разговор с Платоном.

    Разговор Платона в чате ведёт обёртка (`main.py`): она и подменяет эту
    функцию своим хранилищем. Без обёртки разговора нет — и класть некуда,
    о чём сказано вслух, а не промолчано.
    """
    return "разговор с Платоном в этом процессе не ведётся"


def _telegram_document_memory_reason(outcome: Any) -> str:
    """Closed public causes; persistence diagnostics never leave the server."""
    text = str(outcome or "").casefold()
    if "read-only" in text or "read only" in text or "только для чтения" in text:
        return "диск доступен только для чтения"
    if "permission" in text or "access denied" in text or "недостаточно прав" in text:
        return "недостаточно прав для записи разговора"
    if "no space" in text or "disk full" in text or "нет места" in text:
        return "на диске недостаточно свободного места"
    if "разговор с платоном в этом процессе не ведётся" in text:
        return "хранилище разговора в этом процессе не подключено"
    return "хранилище разговора сейчас недоступно"


def _telegram_handle_intake_document(chat_id: int, data: bytes, filename: str,
        document_override: dict[str,Any] | None = None, *, _operation=None) -> None:
    """Prepare outside locks; only current native operation can publish a card."""
    import document_processing
    operation = _operation
    stage = 'начало чтения'
    try:
        if operation is None:
            operation = _telegram_document_begin(chat_id,filename)
        with document_processing.operation(current=lambda:_telegram_document_current(operation),
                                           deadline=operation['deadline']):
            _telegram_document_reply(operation,'<b>Документ принят. Читаю страницы…</b>')
            _intake_queue_cleanup()
            stage = 'чтение PDF и распознавание'
            document = (copy.deepcopy(document_override) if document_override is not None
                        else document_intake.extract_text(data,filename))
            document_processing.check()
            if not document.get('source') and data:
                document['source'] = {'kind':'upload','sha256':hashlib.sha256(data).hexdigest()}
            if data:
                actual = hashlib.sha256(data).hexdigest()
                if (document.get('source') or {}).get('sha256') not in (None,actual):
                    raise ValueError('Отпечаток документа не совпал с прочитанными байтами. Источник не принят.')
                operation['source_sha256'] = actual
            else:
                operation['source_sha256'] = hashlib.sha256(json.dumps(
                    {'text':document.get('text'),'source':document.get('source')},
                    sort_keys=True,ensure_ascii=False).encode('utf-8')).hexdigest()
            if not document.get('text'):
                _telegram_document_fail(operation,str(document.get("reason") or 'В документе нет читаемого текста.'),
                                        'Документ принят, но прочитать его не удалось.')
                return
            _telegram_document_reply(operation,'<b>Читаю «'+html.escape(filename)+'»…</b>\n'
                +'Страниц: '+str(document.get('pages'))+'. Сначала покажу, что нашёл и что уйдёт в расчёт; вопросы — потом.')
            stage = 'разбор текста моделью'
            got = document_intake_read(document,operation['request'])
            document_processing.check()
            if got.get('reason'):
                _telegram_document_fail(operation,str(got['reason']),'Разбор не удался.')
                return
            stage = 'проверка участка'
            region = _telegram_intake_region(_intake_cadastral_numbers(got))
            document_processing.check()
            operation['region'] = region
            stage = 'подготовка карточки'
            queue,card = _intake_queue_prepare(filename,got,document,dict(DEFAULT_INPUTS),
                {key:dict(value)for key,value in TEP_DEFAULT.items()},by_parcel=True,
                parcel_region=region,actor=operation['actor'])
            context = document_intake.chat_context(document,got)
            document_processing.check()
            text = _telegram_intake_card_text(card,first=True,recognized=bool(document.get('recognized')))
            if card.get('ready'):
                markup = None
            else:
                left = int(card['questions']['total'])-int(card['questions']['index'])
                text += ('\n\nМодель пока не менялась. Дальше — '+str(left)+' '
                    +_telegram_plural(left,'вопрос','вопроса','вопросов')+' о том, чего в тизере нет, по одному.')
                markup = {'inline_keyboard':[[{'text':'Перейти к вопросам',
                    'callback_data':_telegram_intake_callback_data(card['id'],'questions')}]]}
            stage = 'сохранение карточки'
            remembered = _telegram_document_publish(operation,filename,queue=queue,context=context)
            if card.get('ready'):
                markup = _telegram_intake_calc_markup(chat_id,card,region)
            text += ('\n\n<i>Документ в разговоре: спрашивайте по нему — Платон ответит по тексту. Новый документ заменит этот.</i>'
                if not remembered else '\n\n<i>Документ в разговор не попал: '
                + _telegram_document_memory_reason(remembered)
                + '. Карточка сохранена отдельно. Следующий вопрос Платон увидит без него.</i>')
            _telegram_document_reply(operation,text,reply_markup=markup)
    except document_processing.Cancelled:
        _telegram_document_interrupted(operation)
        return
    except Exception as exc:
        reason = _telegram_document_error(exc,stage)
        if operation is None:
            _telegram_send_intake_text(chat_id,'<b>Не удалось начать чтение документа.</b>\n'+html.escape(reason))
        else:
            _telegram_document_fail(operation,reason,'Разбор не удался.',error=exc)


def _telegram_send_intake_text(chat_id: int, text: str, *, reply_markup=None) -> None:
    """Deliver the whole saved card; attach its action to the final part only."""
    from telegram_intake_text import split_intake_html
    parts = split_intake_html(text)
    for index, part in enumerate(parts):
        _telegram_send_message(chat_id, part,
                               reply_markup=reply_markup if index == len(parts) - 1 else None)


def _telegram_intake_card_text(card: dict[str, Any], *, first: bool, recognized: bool = False) -> str:
    """Карточка разбора словами чата. Строки — из `teaser_card.build`."""
    lines = [("<b>Что я прочитал в тизере</b>" if first else "<b>Итог разбора перед расчётом</b>")
             + f" · «{html.escape(str(card.get('filename') or 'документ'))}»"]
    if card.get("document_reason"):
        lines.append("<i>" + html.escape(card["document_reason"]) + "</i>")
    for refused in card.get("refused") or []:
        lines.append("Не взято: " + html.escape(str(refused.get("label") or refused.get("key")))
                     + " — " + html.escape(str(refused.get("reason") or "")))
    if recognized or card.get("recognized"):
        lines.append("<i>Документ — скан: текст распознан по картинке, сверьте числа с документом.</i>")
    lines.append("\n<b>1. Что найдено в тизере</b>")
    for row in card.get("found") or []:
        value = row.get("value")
        value = ", ".join(str(part) for part in value) if isinstance(value, list) else str(value)
        lines.append(f"• {html.escape(row['label'])}: <b>{html.escape(value)}</b> "
                     f"{html.escape(str(row.get('unit') or ''))}, {html.escape(row['page_text'])}. "
                     f"{html.escape(row['status'])}.")
    if not card.get("found"):
        lines.append("В тизере не нашлось чисел, которые понимает модель.")
    lines.append("\n<b>2. Что уйдёт в расчёт</b>")
    for row in card.get("to_engine") or []:
        lines.append(f"• {html.escape(row['label'])}: <b>{html.escape(row['shown'])}</b>\n"
                     f"  <i>{html.escape(str(row.get('origin') or '')[:180])}</i>")
    if not card.get("to_engine"):
        lines.append("Из тизера в расчёт ничего не идёт.")
    missing = card.get("missing") or []
    if missing:
        lines.append("\n<b>3. Чего нет в тизере — что возьмётся вместо этого</b>")
        for row in missing:
            lines.append(f"• {html.escape(row['label'])}: {html.escape(row['shown'])}. "
                         f"<i>{html.escape(row['origin'])}</i>")
    if card.get("region_note"):
        lines.append("\n<b>" + html.escape(card["region_note"]) + "</b>")
    for note in card.get("notes") or []:
        lines.append(f"\n<i>{html.escape(str(note)[:300])}</i>")
    for line in card.get("dropped") or []:
        lines.append(f"\nНе взято: {html.escape(str(line)[:200])}")
    return "\n".join(lines)


def _telegram_intake_region(numbers: list[str]) -> str:
    """Чьими нормами считать участок тизера: «moscow», «mo», «other», «mixed», «unknown».

    Тот же выбор, что у присланного номера (`cadastral_route`): номер другого
    кадастрового округа — сразу «other»; 50:… решает территория ГлавАПУ (у
    Новой Москвы номера тоже 50:). Без номеров — пусто.
    """
    if not numbers:
        return ""
    route = cadastral_route(numbers, None)
    if route in ("other", "mixed"):
        return route
    try:
        analysis = analyze_cadastral_territory(CadastralAnalysisRequest(cadastral_numbers=numbers))
    except Exception:  # noqa: BLE001
        analysis = None
    route = cadastral_route(numbers, analysis)
    if analysis is None and route == "mo":
        # 50:… без ответа ГлавАПУ — это и Новая Москва (ТиНАО), и область.
        # Угадывать по номеру нельзя: Новая Москва посчиталась бы чужими нормами
        # молча (решение владельца 25.10.2026). Карточка говорит об этом, а
        # кнопка спрашивает ГлавАПУ ещё раз.
        return "unknown"
    return route


def _telegram_intake_calc_markup(chat_id: int, card: dict[str, Any],
                                 region: str = "") -> dict[str, Any] | None:
    """Кнопка «Всё верно, считать»: мини-приложение получает ровно карточку.

    Москва — экспресс-расчёт по участку (ТЭП ГлавАПУ, затем строки карточки).
    Область и другой регион — режим `intake`: страница считает участок тем же
    путём, что и на сайте (нормы области; для другого региона — госреестр и
    наши умолчания), и кладёт строки карточки поверх. Участки разных регионов
    одним расчётом не считаются — кнопки нет, причина в карточке.
    """
    numbers = [str(number) for number in card.get("cadastral_numbers") or []]
    if numbers and region == "mixed":
        return None
    if numbers and region == "unknown":
        return {"inline_keyboard": [[{"text": "Проверить участок ещё раз",
                                      "callback_data": _telegram_intake_callback_data(card["id"], "region")}]]}
    overrides = teaser_card.calc_overrides(card)
    mode = "intake" if not numbers or region in ("mo", "other") else None
    try:
        # Read the current owned queue and rebuild with the current validators.
        # A previously saved output dictionary alone cannot attest its units.
        queue = _intake_queue_load(str(card.get("id") or ""),
                                  request=_telegram_agent_request(chat_id))
        current = teaser_card_view(queue, dict(DEFAULT_INPUTS),
            {key: dict(value) for key, value in TEP_DEFAULT.items()},
            by_parcel=True, parcel_region=region)
        if (not current.get("ready") or teaser_card.calc_overrides(current) != overrides
                or list(current.get("cadastral_numbers") or []) != numbers):
            return None
        digest = _telegram_overrides_digest(overrides)
        proof = {"schema": 1, "scope": "confirmed_card", "sha256": digest,
                 "binding": _telegram_qualified_application_binding(overrides, 'confirmed_card')}
        url = _telegram_web_app_url(chat_id, numbers, calc_overrides=overrides, mode=mode,
                                    application_proof=proof)
    except document_protocol.ProtocolHold:
        card['calculation_error'] = document_protocol.UNAVAILABLE_MESSAGE
        return None
    except Exception:  # noqa: BLE001
        card['calculation_error'] = ('Кнопка расчёта не выдана: не удалось подтвердить текущие условия документа. '
            'Уточните оценки в карточке или пришлите нужную часть документа отдельно.')
        return None
    label = "Считать без неуточнённых обязательств" if current.get("conditional") else "Всё верно, считать"
    keyboard = [[{"text": label, "web_app": {"url": url}}]]
    for item in current['calculation_qualification_record']['obligations']:
        keyboard.append([{'text':'Уточнить обязательство '+str(item['index']+1),
            'callback_data':_telegram_intake_callback_data(queue['id'], 'review', item['index'],
                _intake_question_token(queue)[:8])}])
    return {"inline_keyboard": keyboard}


def _intake_cadastral_numbers(extraction: dict[str, Any]) -> list[str]:
    """Кадастровые номера из разбора — тем же разбором, что и везде.

    Модель выписывает их то списком, то строкой через запятую, то с подписью
    «КН». Опознаёт номер одно выражение на всё приложение: второе разошлось бы
    с первым ровно на том номере, ради которого его писали.
    """
    for item in extraction.get("fields") or []:
        if item.get("key") != "cadastral_numbers":
            continue
        raw = item.get("value")
        text = ", ".join(str(part) for part in raw) if isinstance(raw, (list, tuple)) else str(raw or "")
        found = _CADASTRAL_NUMBER_RE.findall(text.replace("：", ":"))
        # Порядок сохраняем, повторы убираем: один участок дважды — это
        # территория из двух участков, которой нет.
        seen, numbers = set(), []
        for number in found:
            if number not in seen:
                seen.add(number)
                numbers.append(number)
        return numbers
    return []


def _telegram_open_model_button(chat_id: int) -> dict[str, Any] | None:
    """Кнопка «открыть модель» — удобство, а не условие ответа.

    Ссылка мини-приложения собирается по токену бота, и без него не собирается
    вовсе. Ронять из-за неё разбор документа нельзя: человек потерял бы и свои
    ответы, и прочитанное из файла ради кнопки.
    """
    try:
        url = _telegram_web_app_url(chat_id, [], None)
    except Exception:  # noqa: BLE001
        return None
    return {"inline_keyboard": [[{
        "text": "Открыть модель в DevelopAid",
        "web_app": {"url": url},
    }]]}


def _telegram_intake_card(chat_id: int, dialog: dict[str, Any]) -> dict[str, Any] | None:
    intake = dialog.get("intake") or {}
    try:
        queue = _intake_queue_load(str(intake.get("id") or ""),
                                   request=_telegram_agent_request(chat_id))
        teaser_card.review_saved_state(queue)
    except HTTPException as exc:
        dialog.pop("intake", None)
        dialog.pop("step", None)
        _telegram_dialog_save(chat_id, dialog)
        _telegram_send_message(chat_id, html.escape(str(exc.detail)))
        return None
    return queue


def _telegram_intake_queue_binding(queue: dict[str, Any]) -> dict[str, Any]:
    return {"queue_revision": queue.get("revision", 0),
            "question_token": _intake_question_token(queue)}


def _telegram_intake_expect_shown(queue: dict[str, Any], intake: dict[str, Any],
                                  pending: dict[str, Any] | None = None) -> None:
    binding = pending if pending is not None else {
        "queue_revision": intake.get("shown_queue_revision"),
        "question_token": intake.get("shown_question_token")}
    _intake_queue_expect(queue, binding.get("queue_revision"), binding.get("question_token"))


@_telegram_intake_serialized
def _telegram_intake_queue_conflict(chat_id: int, dialog: dict[str, Any], proposal: dict[str, Any]) -> None:
    # Preserve only a bounded unapplied proposal in the existing dialog. It is
    # never replayed into the queue or automatically retried after a conflict.
    current = _telegram_dialog_get(chat_id) or {}
    if (current.get("intake") or {}).get("id") != (dialog.get("intake") or {}).get("id"):
        _telegram_send_message(chat_id, "Текущий документ уже изменился. Предыдущий ответ не применён; откройте его карточку через /calc.")
        return
    intake = current.get("intake") or {}
    kept = {key: proposal.get(key) for key in ("index", "choice", "action", "mode") if key in proposal}
    kept["value"] = str(proposal.get("value") or "")[:512]
    kept["status"] = "not_applied_queue_changed"
    if intake.get("pending_choice"):
        kept["route_proposal"] = copy.deepcopy(intake["pending_choice"])
    intake["unapplied_answer"] = kept
    for key in ("pending_choice", "pending", "shown_queue_revision", "shown_question_token"):
        intake.pop(key, None)
    current["intake"] = intake
    _telegram_dialog_save(chat_id, current)
    _telegram_send_message(chat_id, "Карточка уже изменилась. Этот ответ сохранён только как предложение и не применён. Подтвердите текущий вопрос заново.")
    _telegram_intake_ask_next(chat_id, current)


def _telegram_intake_amount_prompt(chat_id: int, ask: dict, index: int, choice: int, intake_id: str, question_token: str) -> None:
    option = (ask.get("options") or [])[choice]
    text = (html.escape(str(ask.get("question") or "")) + "\n\nВыбрано: <b>"
        + html.escape(str(option.get("label") or "")) + "</b>.\n\n"
        "Денежная оценка этого обязательства пока не указана. Нужна его стоимость в млн ₽. "
        "Площадь и денежные платежи за покупку не подставляются вместо этой оценки.\n"
        "Введите сумму сообщением, например <code>2,5 млн ₽</code>, или отложите оценку кнопкой ниже. "
        "Выбранный способ учёта сохранится; обязательство пока не добавится в денежный расчёт.\n\n"
        "«Не знаю» или «-» — отложить оценку; «стоп» — закончить остальные вопросы.")
    _telegram_send_intake_text(chat_id, text, reply_markup={"inline_keyboard": [
        [{"text": "Уточнить стоимость позже", "callback_data": _telegram_intake_callback_data(intake_id, "defer", index, choice, question_token[:8])}],
        [{"text": "Вернуться к вариантам", "callback_data": _telegram_intake_callback_data(intake_id, "rechoose", index, question_token[:8])}]]})


def _telegram_intake_confirmation_prompt(chat_id: int, pending: dict, intake_id: str) -> None:
    c = pending["confirm"]
    _telegram_send_message(chat_id,
        f"В поле «{html.escape(c['label'])}» уже стоит {_telegram_number(c['current'], 2)} "
        f"{html.escape(c['unit'])}. Ответ добавляет {_telegram_number(c['adding'], 2)} "
        f"{html.escape(c['unit'])}. Как поступить?",
        reply_markup={"inline_keyboard": [
            [{"text": "Прибавить", "callback_data": _telegram_intake_callback_data(intake_id, "mode", pending["nonce"], "add")}],
            [{"text": "Заменить", "callback_data": _telegram_intake_callback_data(intake_id, "mode", pending["nonce"], "replace")}]]})


@_telegram_intake_serialized
def _telegram_intake_region_commit(chat_id: int, intake_id: str, region: str) -> None:
    dialog = _telegram_dialog_get(chat_id) or {}
    if ((dialog.get("intake") or {}).get("id") != intake_id
            or (dialog.get("document_read") or {}).get("status") == "loading"):
        return
    dialog["intake"]["region"] = region
    _telegram_dialog_save(chat_id, dialog)
    _telegram_intake_ask_next(chat_id, dialog)


def _telegram_intake_region_refresh(chat_id: int, intake_id: str, numbers: list[str]) -> None:
    # Territory IO happens only after the callback's chat lock has been released.
    region = _telegram_intake_region(numbers)
    _telegram_intake_region_commit(chat_id, intake_id, region)


@_telegram_intake_serialized
def _telegram_intake_ask_next(chat_id: int, dialog: dict[str, Any]) -> None:
    """Следующий вопрос о недостающем — или итоговая карточка с кнопкой расчёта."""
    queue = _telegram_intake_card(chat_id, dialog)
    if queue is None:
        return
    binding = _telegram_intake_queue_binding(queue)
    intake = dialog.setdefault("intake", {})
    intake["shown_queue_revision"] = binding["queue_revision"]
    intake["shown_question_token"] = binding["question_token"]
    for key in ("pending_choice", "pending"):
        saved = intake.get(key) or {}
        if saved and (saved.get("queue_revision") != binding["queue_revision"]
                      or saved.get("question_token") != binding["question_token"]):
            intake["unapplied_answer"] = {"status":"not_applied_queue_changed",
                "route_proposal":copy.deepcopy(saved),"value":str(saved.get("value") or "")[:512]}
            intake.pop(key,None)
    _telegram_dialog_save(chat_id, dialog)
    pending = intake.get("pending_choice") or {}
    index = int(queue.get("index") or 0)
    cards = queue.get("cards") or []
    confirm = (dialog.get("intake") or {}).get("pending") or {}
    if (confirm.get("index") == index and confirm.get("nonce") and confirm.get("confirm")
            and confirm.get("intake_id") == queue["id"]):
        probe = teaser_card.answer(copy.deepcopy(queue), dict(DEFAULT_INPUTS),
            {key:dict(value)for key,value in TEP_DEFAULT.items()}, index=index, action="answer",
            choice=int(confirm.get("choice",-1)), value=str(confirm.get("value") or ""),
            spp_split=MKD_SPP_SPLIT, presets=PROJECT_CLASS_PRESETS)
        if probe.get("confirm"):
            if probe["confirm"] != confirm["confirm"]:
                confirm = {**confirm,"confirm":probe["confirm"],"nonce":os.urandom(4).hex()}
                dialog["intake"]["pending"] = confirm
                _telegram_dialog_save(chat_id,dialog)
            _telegram_intake_confirmation_prompt(chat_id,confirm,queue["id"])
            return
        dialog["intake"]["pending_proposal"] = dialog["intake"].pop("pending")
        _telegram_dialog_save(chat_id,dialog)
        _telegram_send_message(chat_id,"Сохранённая оценка требует проверки. Подтвердите текущий вариант и введите сумму заново.")
    if pending.get("index") == index and index < len(cards):
        choice = pending.get("choice")
        options = cards[index].get("options") or []
        if type(choice) is int and 0 <= choice < len(options) and options[choice].get("value") is None:
            if pending.get("intake_id") != queue["id"]:
                _telegram_send_intake_text(chat_id,
                    "<b>Подтвердите текущий документ: " + html.escape(str(queue.get("filename") or ""))
                    + "</b>\n" + html.escape(str(cards[index].get("question") or ""))
                    + "\n\nРанее выбранный способ учёта сохранён как предложение. "
                      "Для этого документа он ещё не подтверждён; деньги не добавлены. Выберите вариант заново.",
                    reply_markup={"inline_keyboard": [[{"text":str(o.get("label") or "")[:60],
                        "callback_data":_telegram_intake_callback_data(queue["id"],"opt",index,n,binding["question_token"][:8])}]
                        for n,o in enumerate(options)]})
                return
            _telegram_intake_amount_prompt(chat_id, cards[index], index, choice, queue["id"], _intake_question_token(queue))
            return
    region = str((dialog.get("intake") or {}).get("region") or "")
    try:
        card = teaser_card_view(queue, dict(DEFAULT_INPUTS),
                                {key: dict(value) for key, value in TEP_DEFAULT.items()},
                                by_parcel=True, parcel_region=region)
    except HTTPException as exc:
        if exc.status_code != 413:
            raise
        _telegram_send_message(chat_id, 'Кнопка расчёта не выдана: '+html.escape(str(exc.detail))
            +' Карточка и ваши ответы сохранены; при необходимости пришлите нужную часть документа отдельно.')
        return
    ask = card["questions"]["card"]
    if ask is None:
        dialog["step"] = "intake_ready"
        _telegram_dialog_save(chat_id, dialog)
        text = _telegram_intake_card_text(card, first=False)
        text += ("\n\nРасчёт начнётся только кнопкой ниже и возьмёт ровно то, что в разделе "
                 "«Что уйдёт в расчёт»; остальное — как в разделе 3.")
        if card.get("conditional"):
            text += ("\n\n<b>Предварительный расчёт:</b> неуточнённые обязательства "
                     "в денежный расчёт не включены. Кнопка подтверждает только показанные вводные.")
        markup = _telegram_intake_calc_markup(chat_id, card, region)
        if card.get('calculation_error'):
            text += '\n\n<b>'+html.escape(card['calculation_error'])+'</b>'
        _telegram_send_intake_text(chat_id, text, reply_markup=markup)
        return
    dialog["step"] = "await_intake_answer"
    _telegram_dialog_save(chat_id, dialog)
    index, total = card["questions"]["index"], card["questions"]["total"]
    text = f"<b>Вопрос {index + 1} из {total}</b>\n" + html.escape(str(ask.get("question")))
    buttons = [[{"text": str(option.get("label"))[:60],
                 "callback_data": _telegram_intake_callback_data(queue["id"], "opt", index, number, binding["question_token"][:8])}]
               for number, option in enumerate(ask.get("options") or [])]
    hint = "Выберите вариант кнопкой"
    if not ask.get("kind") and ask.get("key"):
        hint += f" или впишите число сообщением ({html.escape(str(ask.get('unit') or ''))})"
    text += f"\n\n<i>{hint}. «-» — пропустить вопрос, «стоп» — закончить вопросы.</i>"
    _telegram_send_intake_text(chat_id, text,
                           reply_markup={"inline_keyboard": buttons} if buttons else None)


@_telegram_intake_serialized
def _telegram_intake_answer(chat_id: int, dialog: dict[str, Any], *, index: int, action: str,
                            choice: int = -1, value: str = "", mode: str = "", proposal=None) -> None:
    """Ответ на вопрос по тизеру — в разбор на диске, не в модель."""
    queue = _telegram_intake_card(chat_id, dialog)
    if queue is None:
        return
    unapplied = {"index":index,"choice":choice,"action":action,"value":value,"mode":mode}
    try:
        _telegram_intake_expect_shown(queue, dialog.get("intake") or {})
    except HTTPException as exc:
        if exc.status_code != 409:raise
        _telegram_intake_queue_conflict(chat_id, dialog, unapplied)
        return
    inputs = dict(DEFAULT_INPUTS)
    tep = {key: dict(item) for key, item in TEP_DEFAULT.items()}
    got = teaser_card.answer(queue, inputs, tep, index=index, action=action, choice=choice,
                             value=value, mode=mode, spp_split=MKD_SPP_SPLIT,
                             presets=PROJECT_CLASS_PRESETS)
    if got.get("stale"):
        _telegram_send_message(chat_id, "На этот вопрос уже ответили. Продолжаю с текущего.")
        _telegram_intake_ask_next(chat_id, dialog)
        return
    if got.get("confirm"):
        c = got["confirm"]
        dialog["intake"] = {**(dialog.get("intake") or {}),
                            "pending": {"index": index, "choice": choice, "value": value,
                                        "nonce": os.urandom(4).hex(), "confirm": c,"intake_id":queue["id"],
                                        **_telegram_intake_queue_binding(queue)}}
        _telegram_dialog_save(chat_id, dialog)
        _telegram_intake_confirmation_prompt(chat_id, dialog["intake"]["pending"], queue["id"])
        return
    if got.get("invalid"):
        record = got.get("answer") or {}
        for refused in record.get("refused") or []:
            _telegram_send_message(chat_id, html.escape(str(refused.get("reason") or "Ответ не принят.")))
        _telegram_intake_ask_next(chat_id, dialog)
        return
    if proposal is not None:
        record = got["answer"]
        record["pending_proposal"] = copy.deepcopy(proposal)
        record["refused"] = [{"key":"", "label":"Предыдущий способ учёта", "value":"",
            "reason":"Предыдущий выбор сохранён как неподтверждённое предложение; "
                     "денежная оценка не принята и в расчёт не включена."}]
    try:
        _intake_queue_save(queue)
    except HTTPException as exc:
        if exc.status_code != 409:raise
        _telegram_intake_queue_conflict(chat_id, dialog, unapplied)
        return
    (dialog.get("intake") or {}).pop("pending_choice", None)
    (dialog.get("intake") or {}).pop("pending", None)
    _telegram_dialog_save(chat_id, dialog)
    record = got["answer"]
    if action == "stop":
        acknowledgement = "Вопросы закончены."
    elif action == "skip":
        acknowledgement = "Пропущено."
    else:
        acknowledgement = "Ответ: " + html.escape(str(record.get("answer") or value))
    lines = [acknowledgement]
    if record.get("deferred"):
        lines.append("Сохранено: " + html.escape(str(record.get("answer") or "")))
    for row in record.get("applied") or []:
        lines.append("в карточку: " + html.escape(str(row.get("label") or row.get("key")))
                     + " — " + html.escape(str(row.get("shown") or _telegram_number(row.get("now"), 2))))
    for row in record.get("refused") or []:
        lines.append("в расчёт не пойдёт: " + html.escape(str(row.get("label") or row.get("key")))
                     + " — " + html.escape(str(row.get("reason") or "")))
    _telegram_send_intake_text(chat_id, "\n".join(lines))
    _telegram_intake_ask_next(chat_id, dialog)


@_telegram_intake_serialized
def _telegram_intake_callback(chat_id: int, data: str) -> None:
    """Кнопки разбора тизера: к вопросам, вариант ответа, прибавить/заменить."""
    dialog = _telegram_dialog_get(chat_id) or {}
    if (dialog.get("document_read") or {}).get("status") == "loading":
        _telegram_send_message(chat_id, "Результат разбора ещё не получен. Кнопка предыдущей карточки не применена; /cancel отменит ожидание.")
        return
    if not (dialog.get("intake") or {}).get("id"):
        _telegram_send_message(chat_id, "Разбор этого тизера не найден. Пришлите документ заново.")
        return
    queue = _telegram_intake_card(chat_id, dialog)
    if queue is None:
        return
    parts = str(data).split(":")
    supplied = parts[1] if len(parts)>1 and re.fullmatch(r"[0-9a-f]{32}", parts[1]) else None
    if not data.startswith("intake2_") or supplied != queue.get("id"):
        _telegram_send_message(chat_id,
            "Эта старая кнопка не подтверждает текущий документ. Показываю его вопрос заново; ответы сохранены.")
        _telegram_intake_ask_next(chat_id, dialog)
        return
    action = parts[0].removeprefix("intake2_")
    if action in {"opt","defer","rechoose","mode","review"}:
        intake = dialog.get("intake") or {}
        pending = intake.get("pending") or {} if action == "mode" else None
        expected_token = str((pending or {}).get("question_token") if action == "mode"
                             else intake.get("shown_question_token") or "")
        supplied_token = parts[-1] if action != "mode" and len(parts) >= 4 else None
        try:
            if action != "mode" and (not re.fullmatch(r"[0-9a-f]{8}", str(supplied_token or ""))
                                       or supplied_token != expected_token[:8]):
                raise HTTPException(409, "Вопрос уже изменился")
            _telegram_intake_expect_shown(queue, intake, pending)
        except HTTPException as exc:
            if exc.status_code != 409:raise
            _telegram_intake_queue_conflict(chat_id, dialog, {"action":action,"value":""})
            return
        if action != "mode":parts=parts[:-1]
    data = ":".join([parts[0].replace("intake2_", "intake_", 1), *parts[2:]])
    if data.startswith('intake_review:'):
        value = data.removeprefix('intake_review:')
        if value.isascii() and value.isdigit():
            _telegram_intake_answer(chat_id, dialog, index=int(value), action='review')
        return
    if data == "intake_questions":
        _telegram_intake_ask_next(chat_id, dialog)
        return
    if data == "intake_region":
        queue = _telegram_intake_card(chat_id, dialog)
        if queue is None:
            return
        numbers = [str(n) for n in teaser_card_view(
            queue, dict(DEFAULT_INPUTS), dict(TEP_DEFAULT)).get("cadastral_numbers") or []]
        _telegram_intake_after_lock(_telegram_intake_region_refresh, chat_id, queue["id"], numbers)
        return
    if data.startswith("intake_mode:"):
        pending = (dialog.get("intake") or {}).get("pending") or {}
        if not pending:
            _telegram_intake_ask_next(chat_id, dialog)
            return
        values = data.removeprefix("intake_mode:").split(":")
        if (len(values) != 2 or values[0] != pending.get("nonce")
                or values[1] not in {"add", "replace"}
                or pending.get("intake_id") != queue["id"]
                or pending.get("index") != int(queue.get("index") or 0)):
            _telegram_intake_ask_next(chat_id, dialog)
            return
        dialog["intake"].pop("pending", None)
        _telegram_intake_answer(chat_id, dialog, index=int(pending["index"]), action="answer",
                                choice=int(pending["choice"]), value=str(pending["value"]),
                                mode=values[1])
        return
    if data.startswith("intake_rechoose:"):
        queue = _telegram_intake_card(chat_id, dialog)
        if queue is None:
            return
        if data == f"intake_rechoose:{int(queue.get('index') or 0)}":
            dialog["intake"].pop("pending_choice", None)
            dialog["intake"].pop("pending", None)
            _telegram_dialog_save(chat_id, dialog)
        _telegram_intake_ask_next(chat_id, dialog)
        return
    if data.startswith(("intake_opt:", "intake_defer:")):
        try:
            _, index_text, choice_text = data.split(":")
            index, choice = int(index_text), int(choice_text)
        except ValueError:
            return
        queue = _telegram_intake_card(chat_id, dialog)
        if queue is None:
            return
        try:
            _telegram_intake_expect_shown(queue, dialog.get("intake") or {})
        except HTTPException as exc:
            if exc.status_code != 409:raise
            _telegram_intake_queue_conflict(chat_id, dialog, {"index":index,"choice":choice,"action":"answer","value":""})
            return
        cards = queue.get("cards") or []
        if index != int(queue.get("index") or 0) or not 0 <= index < len(cards):
            _telegram_send_message(chat_id, "Этот вопрос уже изменился. Продолжаю с текущего.")
            _telegram_intake_ask_next(chat_id, dialog)
            return
        ask = cards[index] if 0 <= index < len(cards) else {}
        options = ask.get("options") or []
        if not 0 <= choice < len(options):
            _telegram_intake_ask_next(chat_id, dialog)
            return
        option = options[choice] if 0 <= choice < len(options) else {}
        if data.startswith("intake_defer:"):
            pending = dialog["intake"].get("pending_choice") or {}
            if (any(pending.get(k) != v for k,v in {"index":index,"choice":choice,"intake_id":queue["id"],
                    **_telegram_intake_queue_binding(queue)}.items()) or ask.get("kind")
                    or not ask.get("adds") or not option.get("target") or option.get("value") is not None):
                _telegram_intake_ask_next(chat_id, dialog)
                return
            _telegram_intake_answer(chat_id, dialog, index=index, action="skip", choice=choice)
            return
        if (not ask.get("kind") and option.get("target")
                and option.get("value") is None):
            # У варианта нет числа: его впишет человек следующим сообщением.
            dialog["intake"] = {**dialog["intake"], "pending_choice": {
                "index": index, "choice": choice, "intake_id": queue["id"],
                **_telegram_intake_queue_binding(queue)}}
            dialog["intake"].pop("pending", None)
            dialog["step"] = "await_intake_answer"
            _telegram_dialog_save(chat_id, dialog)
            _telegram_intake_amount_prompt(chat_id, ask, index, choice, queue["id"], _intake_question_token(queue))
            return
        _telegram_intake_answer(chat_id, dialog, index=index, action="answer", choice=choice)


def _telegram_handle_manual_document(chat_id: int, document: dict[str,Any]) -> None:
    import document_processing
    operation = None
    stage = 'загрузка файла'
    try:
        operation = _telegram_document_begin(chat_id,str(document.get('file_name') or 'Документ'))
        with document_processing.operation(current=lambda:_telegram_document_current(operation),
                                           deadline=operation['deadline']):
            _telegram_document_reply(operation,'<b>Файл принят. Загружаю его из Telegram…</b>')
            _intake_queue_cleanup()
            data,filename = _telegram_download_document(document)
            operation['source_sha256'] = hashlib.sha256(data).hexdigest()
            document_processing.check()
            if filename.lower().endswith(('.pdf','.png','.jpg','.jpeg')):
                _telegram_handle_intake_document(chat_id,data,filename,_operation=operation)
                return
            stage = 'чтение таблицы XLSX'
            _telegram_document_reply(operation,'<b>Файл загружен. Читаю таблицу ТЭП…</b>')
            try:
                parsed = parse_manual_tep_xlsx(data,filename)
            except (ValueError,RuntimeError):
                document_processing.check()
                if _telegram_handle_glavapu_document(chat_id,data,filename,_operation=operation):
                    return
                raise
            document_processing.check()
            text,markup = _telegram_manual_document_reply(chat_id,parsed)
            _telegram_document_publish(operation,filename)
            _telegram_document_reply(operation,text,reply_markup=markup)
    except document_processing.Cancelled:
        _telegram_document_interrupted(operation)
        return
    except Exception as exc:
        reason = _telegram_document_error(exc,stage)
        heading = 'Не удалось принять файл.' if stage=='загрузка файла' else 'Не удалось принять ручной ТЭП.'
        if operation is None:
            _telegram_send_intake_text(chat_id,'<b>'+heading+'</b>\n'+html.escape(reason))
        else:
            _telegram_document_fail(operation,reason,heading,error=exc)


def _telegram_manual_document_reply(chat_id: int, parsed: dict) -> tuple[str,dict]:
    summary = parsed.get("summary") or {}
    project_name = str(parsed.get("project_name") or "Без названия")
    region = str(parsed.get("region") or "").strip()
    region_line = f"Регион: <b>{html.escape(region)}</b>\n" if region else ""
    manual_session = {
        "project_name": parsed.get("project_name") or "",
        "region": parsed.get("region") or "",
        "site_area_ha": parsed.get("site_area_ha") or 0,
        "source": parsed.get("source") or {},
        "inputs": parsed.get("inputs") or {},
        "tep": parsed.get("tep") or {},
    }
    button = {
        "inline_keyboard": [[{
            "text": "Открыть ТЭП в DevelopAid",
            "web_app": {"url": _telegram_web_app_url(chat_id, [], manual_session)},
        }]]
    }
    return (
        "<b>Ручной ТЭП распознан</b>\n"
        f"Проект: <b>{html.escape(project_name)}</b>\n"
        f"{region_line}"
        f"Территория: <b>{_telegram_number(parsed.get('site_area_ha'), 4)} га</b>\n"
        f"ГНС: <b>{_telegram_number(summary.get('total_gns_sqm'), 0)} м²</b>\n"
        f"Продаваемая площадь: <b>{_telegram_number(summary.get('total_saleable_sqm'), 0)} м²</b>\n"
        f"Квартиры: <b>{_telegram_number(summary.get('apartment_saleable_sqm'), 0)} м²</b>\n"
        f"Паркинг: <b>{_telegram_number(summary.get('parking_spaces'), 0)} м/м</b>\n"
        f"Смена ВРИ: <b>{_telegram_money_mln(summary.get('land_rights_cost_mln'))}</b>\n"
        f"Социальная компенсация: <b>{_telegram_money_mln(summary.get('social_compensation_mln'))}</b>\n\n"
        "Проверьте сводку и откройте модель. Финансовые параметры можно настроить уже в DevelopAid.",
        button,
    )


def _telegram_handle_freeform_tep(chat_id: int, text: str) -> None:
    try:
        parsed = build_freeform_tep(text)
    except (ValueError, RuntimeError) as exc:
        # Сбой модели — не нехватка данных: заголовок «не хватает» отправлял
        # человека переписывать верный текст, хотя дело было не в нём.
        title = ("Не удалось распознать текст."
                 if isinstance(exc, FreeformTepRecognitionError)
                 else "Не хватает исходных данных.")
        _telegram_send_message(
            chat_id,
            f"<b>{title}</b>\n"
            + html.escape(str(exc))
            + f".\n\nПример: <code>{html.escape(FREEFORM_TEP_EXAMPLE)}</code>",
        )
        return

    _telegram_send_tep_review(chat_id, parsed, dialog_mode=False)


def _telegram_send_tep_review(chat_id: int, parsed: dict[str, Any], *, dialog_mode: bool) -> None:
    summary = parsed.get("summary") or {}
    entered = set(parsed.get("entered_fields") or [])

    def source_mark(key: str) -> str:
        return "введено" if key in entered else "расчёт"

    manual_session = {
        "project_name": parsed.get("project_name") or "",
        "site_area_ha": parsed.get("site_area_ha") or 0,
        "source": parsed.get("source") or {},
        "inputs": parsed.get("inputs") or {},
        "tep": parsed.get("tep") or {},
    }
    keyboard = [[{
            "text": "Подтвердить и открыть DevelopAid",
            "web_app": {"url": _telegram_web_app_url(chat_id, [], manual_session)},
        }]]
    if dialog_mode:
        keyboard.append([
            {"text": "Изменить данные", "callback_data": "flow_edit"},
            {"text": "Начать заново", "callback_data": "flow_restart"},
        ])
    button = {"inline_keyboard": keyboard}
    provided = "\n".join("• " + html.escape(item) for item in parsed.get("provided") or [])
    calculated = (
        f"• наземная ГНС проекта — {_telegram_number(summary.get('total_gns_sqm'), 0)} м²\n"
        f"• плотность СПП — {_telegram_number(summary.get('density_spp_th_ha'), 2)} тыс. м²/га\n"
        f"• население — {_telegram_number(summary.get('population'), 0)} чел.\n"
        f"• квартир — {_telegram_number(summary.get('apartment_units'), 0)} шт.\n"
        f"• подземный паркинг — {_telegram_number(summary.get('parking_spaces'), 0)} м/м "
        f"({source_mark('parking_spaces')})\n"
        f"• нормативная социальная потребность — "
        f"ДОО {_telegram_number(summary.get('required_kindergarten_places'), 0)} мест; "
        f"школа {_telegram_number(summary.get('required_school_places'), 0)} мест; "
        f"поликлиника {_telegram_number(summary.get('required_clinic_capacity'), 0)} пос./смену\n"
        f"• мощности, принятые в модель — "
        f"ДОО {_telegram_number(summary.get('kindergarten_places'), 0)} мест ({source_mark('kindergarten_places')}); "
        f"школа {_telegram_number(summary.get('school_places'), 0)} мест ({source_mark('school_places')}); "
        f"поликлиника {_telegram_number(summary.get('clinic_capacity'), 0)} пос./смену "
        f"({source_mark('clinic_capacity')})"
    )
    assumptions = parsed.get("assumptions") or []
    assumptions_text = "\n".join("• " + html.escape(item) for item in assumptions[:8])
    message_text = (
        "<b>Проверьте ТЭП перед созданием проекта</b>\n\n"
        "<b>Вы указали</b>\n" + provided + "\n\n"
        "<b>DevelopAid рассчитал ориентировочно</b>\n" + calculated
    )
    if assumptions_text:
        message_text += "\n\n<b>Допущения и ограничения</b>\n" + assumptions_text
    message_text += "\n\nЕсли всё верно — подтвердите."
    if dialog_mode:
        message_text += " Для корректировки нажмите «Изменить данные»."
    else:
        message_text += " Любой показатель можно исправить следующим сообщением целиком."
    _telegram_send_message(chat_id, message_text, reply_markup=button)


# _DEVELOPAID_MINIMAL_CAD_PRICING_V01216

def _telegram_econ_value_th(text: str) -> float:
    """Parse a user-entered economic value and return thousand rubles."""
    normalized = str(text or "").lower().replace("ё", "е")
    normalized = re.sub(r"(?<=\d)[\s\u00a0\u202f](?=\d)", "", normalized)
    match = re.search(r"[-+]?\d+(?:[.,]\d+)?", normalized)
    if not match:
        raise ValueError("Не вижу числа")
    value = float(match.group(0).replace(",", "."))
    if re.search(r"\bмлн\b", normalized):
        value *= 1000.0
    if not math.isfinite(value) or value <= 0:
        raise ValueError("Значение должно быть больше нуля")
    return value


# Ставка СМР класса жила здесь второй копией — 110 / 190 / 300, теми же
# числами, что в `PROJECT_CLASS_PRESETS`. Совпадение и было опасно: поправят
# профиль класса, а бот останется на прежнем, и экспресс-расчёт разойдётся с
# сайтом молча — та же болезнь, что была у `VERSION` и у списка полей страницы.
# Копии больше нет; ставка берётся у профиля, как и цены.
def _telegram_class_smr(key: str) -> float:
    """Ставка основного строительства класса — из профиля класса."""
    return float(PROJECT_CLASS_PRESETS[key]["main_above_th_per_sqm"])


def _telegram_cad_class_menu(chat_id: int, dialog: dict[str, Any]) -> None:
    dialog["step"] = "choose_cad_class"
    _telegram_dialog_save(chat_id, dialog)
    _telegram_send_message(
        chat_id,
        "<b>Класс жилья / параметры экспресс-расчёта</b>\n\n"
        "Выберите класс. Он сразу задаёт базовые цены реализации и себестоимость СМР. "
        "Перед расчётом DevelopAid покажет все принятые параметры.\n\n"
        "• <b>Комфорт</b> — жильё 350 тыс. ₽/м²; нежильё 350 тыс. ₽/м²; "
        "м/м 1,5 млн ₽; СМР 110 тыс. ₽/м² ГНС.\n"
        "• <b>Бизнес</b> — жильё 650 тыс. ₽/м²; нежильё 650 тыс. ₽/м²; "
        "м/м 5 млн ₽; СМР 190 тыс. ₽/м² ГНС.\n"
        "• <b>Элитный</b> — жильё 1,5 млн ₽/м²; нежильё 1,5 млн ₽/м²; "
        "м/м 20 млн ₽; СМР 300 тыс. ₽/м² ГНС.\n\n"
        "СМР включает общестрой, благоустройство и резервы; наружные инженерные сети учитываются отдельно.",
        reply_markup={"inline_keyboard": [
            [{"text": "Комфорт", "callback_data": "flow_cad_class_comfort"}],
            [{"text": "Бизнес", "callback_data": "flow_cad_class_business"}],
            [{"text": "Элитный", "callback_data": "flow_cad_class_elite"}],
            [{"text": "Начать заново", "callback_data": "flow_restart"}],
        ]},
    )


def _telegram_send_cad_calculate_button(chat_id: int, dialog: dict[str, Any]) -> None:
    data = dialog.get("data") or {}
    numbers = list(data.get("cadastral_numbers") or [])
    if not numbers:
        raise ValueError("Не найдены кадастровые номера текущего расчёта")
    overrides = {
        "project_class": str(data.get("project_class") or ""),
        "apartment_price_th": float(data.get("apartment_price_th") or 0),
        "commercial_price_th": float(data.get("commercial_price_th") or 0),
        "parking_price_th": float(data.get("parking_price_th") or 0),
        "smr_th_per_sqm": float(data.get("smr_th_per_sqm") or 0),
    }
    values = [
        overrides["apartment_price_th"], overrides["commercial_price_th"],
        overrides["parking_price_th"], overrides["smr_th_per_sqm"],
    ]
    if (overrides["project_class"] not in PROJECT_CLASS_PRESETS
            or not all(math.isfinite(value) and value > 0 for value in values)):
        raise ValueError("Не заполнены параметры выбранного класса")
    class_label = PROJECT_CLASS_PRESETS.get(overrides["project_class"], {}).get("label") or "—"
    prices_note = " · цены изменены вручную" if bool(data.get("prices_custom")) else ""
    digest = _telegram_overrides_digest(overrides)
    proof = {"schema": 1, "scope": "confirmed_cad", "sha256": digest,
             "binding": hashlib.sha256(json.dumps({"cad": numbers, "overrides": overrides},
                 sort_keys=True, allow_nan=False).encode("utf-8")).hexdigest()}
    url = _telegram_web_app_url(chat_id, numbers, calc_overrides=overrides, application_proof=proof)
    dialog["step"] = "ready_cad_calculation"
    dialog["calc_overrides"] = overrides
    _telegram_dialog_save(chat_id, dialog)
    _telegram_send_message(
        chat_id,
        "<b>Параметры перед расчётом</b>\n\n"
        f"Класс: <b>{html.escape(class_label)}</b>{html.escape(prices_note)}\n"
        f"• жильё — {_telegram_number(overrides['apartment_price_th'], 0)} тыс. ₽/м²\n"
        f"• нежильё — {_telegram_number(overrides['commercial_price_th'], 0)} тыс. ₽/м²\n"
        f"• машино-место — {_telegram_number(overrides['parking_price_th'] / 1000, 2)} млн ₽\n"
        f"• СМР — {_telegram_number(overrides['smr_th_per_sqm'], 0)} тыс. ₽/м² ГНС\n\n"
        "СМР: общестрой + благоустройство + резервы; наружные инженерные сети — отдельно.\n"
        "Остальные предпосылки — умолчания DevelopAid текущей версии: прежние правки "
        "в мини-приложении на экспресс-расчёт не переносятся.\n\n"
        "После подтверждения DevelopAid получит ТЭП ГлавАПУ и рассчитает проект.",
        reply_markup={"inline_keyboard": [
            [{"text": "Рассчитать проект", "web_app": {"url": url}}],
            [{"text": "Изменить цены", "callback_data": "flow_cad_class_custom"}],
            [{"text": "Выбрать другой класс", "callback_data": "flow_cad_choose_class"}],
        ]},
    )


def _telegram_mo_vri_fee(vri: dict[str, Any]) -> str:
    """Плата за смену ВРИ словами: сумма, а без суммы — «не рассчитана».

    None у `payment_used_rub` — отсутствие ответа (нет Кд, нет Кср), и ноль на
    его месте читался бы как ответ источника. Причину называет `payment_basis`
    рядом — второй копии текста здесь нет.
    """
    amount = vri.get("payment_used_rub")
    if amount is None:
        return "не рассчитана"
    return _telegram_money_mln(float(amount) / 1_000_000)


def _telegram_mo_parsed(mo: dict[str, Any]) -> dict[str, Any]:
    """Расчёт по Подмосковью в формате карточки ТЭП бота."""
    social = mo.get("social") or {}
    territory = mo.get("territory") or {}
    vri = mo.get("vri") or {}
    tep = mo.get("tep") or {}
    site_area_ha = float(territory.get("site_area_ha") or 0)
    apartments = float(social.get("apartments_sqm") or 0)
    gns = float(social.get("gns_sqm") or 0)
    provided = [
        f"участок — {_telegram_number(site_area_ha, 4)} га по ЕГРН",
        f"плотность — {_telegram_number(mo.get('density_sqm_per_ha'), 0)} м² квартир на 1 га",
        f"квартиры — {_telegram_number(apartments, 0)} м²",
    ]
    if territory.get("district"):
        provided.append(f"округ — {territory['district']}")
    assumptions = [
        "социальная нагрузка рассчитана по нормативам РНГП Московской области",
        f"плата за смену ВРИ — {_telegram_mo_vri_fee(vri)} "
        f"({vri.get('payment_basis') or 'не определена'})",
    ]
    assumptions.extend(str(item) for item in (mo.get("warnings") or [])[:4])
    return {
        "project_name": territory.get("district") or "Проект в Подмосковье",
        "site_area_ha": site_area_ha,
        "source": {
            "type": "mo_calculator",
            "cadastral_numbers": territory.get("cadastral_numbers") or [],
            "district": territory.get("district") or "",
        },
        "inputs": mo.get("inputs") or {},
        "tep": tep,
        "provided": provided,
        "assumptions": assumptions,
        "entered_fields": [],
        "summary": {
            "total_gns_sqm": gns,
            "density_spp_th_ha": (gns / 1000.0 / site_area_ha) if site_area_ha else 0,
            "population": social.get("population") or 0,
            "apartment_units": (tep.get("apartments") or {}).get("units") or 0,
            "parking_spaces": (social.get("parking") or {}).get("permanent_spaces") or 0,
            "required_kindergarten_places": (social.get("kindergarten") or {}).get("required_places") or 0,
            "required_school_places": (social.get("school") or {}).get("required_places") or 0,
            "required_clinic_capacity": (social.get("clinic") or {}).get("required_capacity") or 0,
            "kindergarten_places": (social.get("kindergarten") or {}).get("places") or 0,
            "school_places": (social.get("school") or {}).get("places") or 0,
            "clinic_capacity": (social.get("clinic") or {}).get("capacity") or 0,
        },
    }


def _telegram_plural(count: int, one: str, few: str, many: str) -> str:
    """Русское склонение по числу: 1 участок, 2 участка, 5 участков."""
    count = abs(int(count))
    if count % 100 // 10 == 1:
        return many
    last = count % 10
    if last == 1:
        return one
    if 2 <= last <= 4:
        return few
    return many


def _telegram_mo_sources_message(mo: dict[str, Any]) -> str:
    """Нормативы, по которым посчитано, и предупреждения расчёта."""
    upks = mo.get("upks") or {}
    source = upks.get("source") or {}
    vri = mo.get("vri") or {}
    lines = ["<b>Исходные нормативы</b>"]
    land = source.get("land") or {}
    oks = source.get("oks") or {}
    if land.get("report"):
        lines.append(f"УПКС земли: {html.escape(str(land['report']))}")
    if oks.get("report"):
        lines.append(f"УПКС ОКС: {html.escape(str(oks['report']))}")
    if vri.get("market_price_document"):
        lines.append(
            f"Кср: {html.escape(str(vri['market_price_document']))}"
            + (f" · {html.escape(str(vri.get('market_price_period')))}" if vri.get("market_price_period") else "")
        )
    if vri.get("kd_document"):
        lines.append(f"Кд: {html.escape(str(vri['kd_document']))}")

    warnings = list(mo.get("warnings") or [])
    for item in vri.get("warnings") or []:
        if item not in warnings:
            warnings.append(item)
    if warnings:
        lines.append("")
        lines.append("<b>Предупреждения</b>")
        lines.extend("• " + html.escape(str(item)) for item in warnings)
    return "\n".join(lines)


def _telegram_handle_mo_numbers(chat_id: int, numbers: list[str], query: str = "") -> None:
    # В ядро уходит исходный текст пользователя: он может быть адресом или
    # координатами, а не списком номеров, и разбирать его должно ядро.
    request_query = _land_text(query) or ", ".join(numbers)
    if numbers:
        progress = f"Получил {len(numbers)} участ{_telegram_plural(len(numbers), 'ок', 'ка', 'ков')}."
    else:
        progress = "Получил запрос."
    _telegram_send_message(
        chat_id, f"{progress} Запрашиваю сведения ЕГРН и выполняю расчёт…"
    )
    try:
        mo = mo_calculate_via_core(request_query, limit=_LAND_LOOKUP_MAX_RESULTS)
    except HTTPException as exc:
        _telegram_send_message(
            chat_id,
            "<b>Не удалось рассчитать участок в Подмосковье.</b>\n" + html.escape(str(exc.detail)),
        )
        return
    territory = mo.get("territory") or {}
    social = mo.get("social") or {}
    vri = mo.get("vri") or {}
    requested = len(numbers)
    found = int(territory.get("parcel_count") or 0)
    parcels = f"<b>{found}</b>" + (f" из {requested}" if requested and found != requested else "")
    # Потерянный участок — потерянные гектары: площадь, квартиры и вся
    # социалка занижены, и молчать об этом рядом с площадью нельзя.
    missing_note = ""
    if requested and found < requested:
        missing_note = (
            f"⚠️ <b>Без сведений ЕГРН: {requested - found} участков — площадь и весь "
            "расчёт занижены.</b> Повторите запрос: НСПД отвечает не с первого раза. "
            "Номера — в предупреждениях ниже.\n"
        )
    _telegram_send_message(
        chat_id,
        "<b>Участок в Московской области</b>\n"
        f"Участков: {parcels}\n"
        f"Площадь: <b>{_telegram_number(territory.get('site_area_ha'), 4)} га</b>\n"
        f"{missing_note}"
        f"Округ: <b>{html.escape(str(territory.get('district') or '—'))}</b>\n"
        f"Кадастровый квартал: <b>{html.escape(str(territory.get('quarter') or '—'))}</b>\n\n"
        f"Плотность: {_telegram_number(mo.get('density_sqm_per_ha'), 0)} м² квартир на 1 га\n"
        f"Квартиры: {_telegram_number(social.get('apartments_sqm'), 0)} м²\n"
        f"Население: {_telegram_number(social.get('population'), 0)} чел.\n\n"
        f"<b>Социальная нагрузка</b>\n"
        f"ДОО: {_telegram_number((social.get('kindergarten') or {}).get('places'), 0)} мест\n"
        f"СОШ: {_telegram_number((social.get('school') or {}).get('places'), 0)} мест\n"
        f"Поликлиника: {_telegram_number((social.get('clinic') or {}).get('capacity'), 0)} пос./смену\n"
        f"Машино-места: {_telegram_number((social.get('parking') or {}).get('permanent_spaces'), 0)} шт.\n\n"
        f"Смена ВРИ: <b>{_telegram_mo_vri_fee(vri)}</b>\n"
        f"Основание: {html.escape(str(vri.get('payment_basis') or '—'))}",
    )
    _telegram_send_message(chat_id, _telegram_mo_sources_message(mo))
    # Картинка территории — как на сайте: контуры ЕГРН поверх карты НСПД.
    _telegram_territory_photo_async(chat_id, numbers)
    _telegram_send_tep_review(chat_id, _telegram_mo_parsed(mo), dialog_mode=False)


def cadastral_route(numbers: list[str], analysis: dict[str, Any] | None) -> str:
    """Куда считать участок: «moscow», «mo», «other», «mixed» или «error».

    Кадастровый номер 50:* принадлежит не только Московской области — у Новой
    Москвы кадастры тоже начинаются с 50. Поэтому один префикс никогда не
    выбирает областные правила: сначала спрашиваем ГлавАПУ, и только если
    территория не московская, уходим в областной расчёт. А вот номер другого
    кадастрового округа (66:, 78:…) — точно не Москва и не область: такой
    участок идёт в режим «Другой регион», а не в московский калькулятор.
    """
    outside = [number for number in numbers if project_regions.outside_moscow_region(number)]
    if outside:
        return "other" if len(outside) == len(numbers) else "mixed"
    if bool(((analysis or {}).get("territory") or {}).get("inside_moscow")):
        return "moscow"
    region_only = bool(numbers) and all(
        str(number).strip().startswith(_MO_REGION_CODE + ":") for number in numbers
    )
    if region_only:
        return "mo"
    return "moscow" if analysis else "error"


# Ручной ввод ТЭП описывает объём: «Участок 2,4 га. Квартиры 42 000 м²». Адрес
# таких единиц не содержит, и по ним свободный текст отличается от адреса —
# иначе описание проекта уходило бы искать в ЕГРН и ждало бы там три минуты.
_TEP_TEXT_MARKERS = re.compile(
    r"\d\s*(га|гa|m2|м2|м²|кв\.?\s*м|тыс|мест|шт|млн|млрд)", re.IGNORECASE
)


# Вопрос — не адрес. Без этой проверки «Какая цена объекта оптимальна?» уходило
# искать участок в ЕГРН, и пользователь получал «участок не найден» вместо ответа.
_QUESTION_MARKERS = re.compile(
    r"\?|^\s*(как|какая|какой|какие|каков|почему|зачем|сколько|что|чем|где|когда|стоит ли|можно ли|"
    r"объясни|посчитай|сравни|проверь|покажи|расскажи|оцени|подскажи)\b",
    re.IGNORECASE,
)


def _looks_like_question(text: str) -> bool:
    return bool(_QUESTION_MARKERS.search(str(text or "").strip()))


# Адрес должен выглядеть адресом. Прежнее правило считало адресом любой текст
# из трёх букв, и реплика в диалоге — «кроме пункта 2 остальные сопоставимы по
# другим очередям» — уходила искать участок в ЕГРН.
_ADDRESS_WORDS = re.compile(
    r"\b(?:город|посёлок|поселок|село|деревня|станица|хутор|микрорайон|квартал|"
    r"улица|проспект|проезд|шоссе|бульвар|набережная|переулок|площадь|тупик|"
    r"аллея|владение|корпус|строение|область|район|край|округ|"
    r"москва|московская|санкт-петербург|петербург|севастополь|подмосковье|"
    r"мкр|просп|наб|пер|пл|бул|ул|пр-т|пр-кт|б-р|р-н|обл|стр|корп|влд|вл|"
    r"снт|днп|пгт|тер)\b",
    re.IGNORECASE,
)
# Сокращения через точку: «г. Химки», «ул. Мишина», «д. 46».
_ADDRESS_SHORTHAND = re.compile(r"(?:^|[\s,])(?:г|гор|с|д|п|ул|пр|ш|пер|пл|наб|обл|р|к|стр|вл)\.",
                                re.IGNORECASE)
# «Что-то, что-то, 46» — форма адреса даже без слов-указателей.
_ADDRESS_SHAPE = re.compile(r"^[^,]+,[^,]+,\s*\d+[А-Яа-яA-Za-z/-]*\s*$")


def _looks_like_address(text: str) -> bool:
    value = str(text or "").strip()
    if not value or len(value) > 300:
        return False
    if _TEP_TEXT_MARKERS.search(value) or _looks_like_question(value):
        return False
    if not re.search(r"[А-Яа-яЁёA-Za-z]{3}", value):
        return False
    return bool(
        _ADDRESS_WORDS.search(value)
        or _ADDRESS_SHORTHAND.search(value)
        or _ADDRESS_SHAPE.match(value)
    )


def _telegram_handle_address(chat_id: int, query: str) -> bool:
    """Ищет участок по адресу через ядро. Возвращает False, если ничего не нашлось."""
    _telegram_send_message(chat_id, "Ищу участок по адресу в ЕГРН…")
    try:
        found = land_lookup_via_core(query, limit=_LAND_LOOKUP_MAX_RESULTS)
    except HTTPException as exc:
        _telegram_send_message(
            chat_id,
            "<b>Не удалось найти участок по адресу.</b>\n" + html.escape(str(exc.detail)),
        )
        return True
    results = [item for item in (found.get("results") or []) if item.get("cadastral_number")]
    if not results:
        hidden = int(found.get("hidden_count") or 0)
        note = (
            f"\nПо этому адресу нашлись только объекты недвижимости ({hidden}), а не земельные участки."
            if hidden else ""
        )
        _telegram_send_message(
            chat_id,
            "<b>Участок по этому адресу не найден.</b>" + note
            + "\n\nПопробуйте уточнить адрес или пришлите кадастровый номер.",
        )
        return True

    numbers = [str(item["cadastral_number"]) for item in results]
    lines = [
        f"• <code>{html.escape(str(item['cadastral_number']))}</code>"
        + (f" · {_telegram_number(item.get('area_sqm'), 0)} м²" if item.get("area_sqm") else "")
        + (f" · {html.escape(str(item.get('address')))}" if item.get("address") else "")
        for item in results[:10]
    ]
    more = f"\n…и ещё {len(numbers) - 10}" if len(numbers) > 10 else ""
    _telegram_send_message(
        chat_id,
        f"<b>Нашёл по адресу: {len(numbers)} участ{_telegram_plural(len(numbers), 'ок', 'ка', 'ков')}</b>\n"
        + "\n".join(lines) + more + "\n\nСчитаю по ним территорию…",
    )
    _telegram_handle_cadastral_numbers(chat_id, numbers, ", ".join(numbers))
    return True


def _telegram_handle_other_region(chat_id: int, numbers: list[str]) -> None:
    """Участок вне Москвы и области: данные госреестра и честный ответ о нормах.

    Норм этого региона у нас нет (решение владельца 19.10.2026): ТЭП считается
    по плотности, которую задаёт человек, а соцобъекты, парковку и плату за
    ВРИ он вписывает сам. Это делается в мини-приложении; бот показывает, что
    знает госреестр, и говорит, чего у нас нет.
    """
    try:
        found = [item for item in (land_lookup_via_core(", ".join(numbers)).get("results") or [])
                 if item and item.get("found")]
    except HTTPException as exc:
        found = []
        _telegram_send_message(
            chat_id, "Сведения госреестра получить не удалось: " + html.escape(str(exc.detail)))
    lines = []
    for item in found[:10]:
        parts = [f"<b>{html.escape(str(item.get('cadastral_number') or ''))}</b>"]
        if item.get("region"):
            parts.append(html.escape(str(item["region"])))
        if item.get("area_ha"):
            parts.append(f"{_telegram_number(item['area_ha'], 4)} га")
        if item.get("permitted_use"):
            parts.append("разрешённое использование: " + html.escape(str(item["permitted_use"])))
        if item.get("cadastral_value_mln"):
            parts.append(f"кадастровая стоимость {_telegram_number(item['cadastral_value_mln'], 1)} млн ₽")
        lines.append(" · ".join(parts))
    _telegram_send_message(
        chat_id,
        "<b>Участок не в Москве и не в Московской области.</b>\n"
        + ("\n".join(lines) + "\n\n" if lines else "")
        + "Норм этого региона у нас нет, поэтому ТЭП считается по плотности, которую задаёте вы: "
        "для начала мы берём 30 000 м² квартир на гектар — это наше допущение. Плату за смену "
        "ВРИ ставим нулём, а места в детских садах, школах и поликлинике и машино-места — "
        "нашими умолчаниями; поправьте их под свой участок. "
        "Всё это делается в мини-приложении: откройте его и введите тот же номер.",
    )


def _telegram_handle_cadastral_numbers(chat_id: int, numbers: list[str], query: str = "") -> None:
    route = cadastral_route(numbers, None)
    if route == "other":
        _telegram_handle_other_region(chat_id, numbers)
        return
    if route == "mixed":
        _telegram_send_message(
            chat_id,
            "<b>Участки из разных регионов.</b>\nВ одном запросе есть участки Москвы или "
            "Московской области и участки другого региона. Посчитайте их по отдельности: "
            "для другого региона норм у нас нет, и считается он иначе.")
        return
    analysis: dict[str, Any] | None = None
    failure = ""
    try:
        analysis = analyze_cadastral_territory(CadastralAnalysisRequest(cadastral_numbers=numbers))
    except HTTPException as exc:
        failure = str(exc.detail)
    route = cadastral_route(numbers, analysis)
    if route == "mo":
        _telegram_handle_mo_numbers(chat_id, numbers, query)
        return
    if route == "error" or analysis is None:
        _telegram_send_message(
            chat_id, "<b>Не удалось сформировать территорию.</b>\n" + html.escape(failure)
        )
        return
    recognized = analysis.get("recognized") or numbers
    territory = analysis.get("territory") or {}
    district = " · ".join(
        str(value) for value in (
            territory.get("administrative_district"),
            territory.get("district"),
        ) if value
    ) or "—"
    dialog = {
        "step": "choose_cad_class",
        "data": {
            "cadastral_numbers": list(recognized),
            "territory": territory,
        },
    }
    _telegram_dialog_save(chat_id, dialog)
    # Встроенной панорамы в боте нет (бесплатный тариф Яндекса — только сайт
    # без входа), поэтому — обычная ссылка на Яндекс Карты, тот же шаблон.
    center = territory.get("center") or {}
    panorama = yandex_panorama_url(center.get("lat"), center.get("lng"))
    panorama_line = (
        f'<a href="{html.escape(panorama)}">Открыть панораму в Яндекс Картах</a>\n'
        if panorama else "")
    _telegram_send_message(
        chat_id,
        "<b>Территория сформирована</b>\n"
        f"Участков: <b>{int(territory.get('parcel_count') or len(recognized))}</b>\n"
        f"Площадь: <b>{_telegram_number(territory.get('area_ha'), 4)} га</b>\n"
        f"Район: <b>{html.escape(district)}</b>\n"
        f"Кадастровый квартал: <b>{html.escape(str(territory.get('cadastral_quarter') or '—'))}</b>\n"
        + panorama_line + "\n"
        "Кадастровый расчёт ТЭП остаётся прежним. Перед расчётом выберите класс — он задаст базовые цены и СМР.",
    )
    # Картинка территории — как на сайте: контуры ЕГРН поверх карты НСПД.
    _telegram_territory_photo_async(chat_id, recognized)
    _telegram_cad_class_menu(chat_id, dialog)


_TELEGRAM_MOSCOW = timezone(timedelta(hours=3))


def _site_chat_store(chat_id: int, text: str, taken_at: str,
                     project: str = "", title: str = "") -> dict[str, Any]:
    """Отдать отчёт ядру. На ядре — тот же маршрут, но без сети.

    Второй реализации хранения не заводим: разойдясь, бот и загрузка положили
    бы один отчёт в два места, и оба выглядели бы верными.
    """
    payload = {
        "chat_id": int(chat_id or 0),
        "sign": _web_login_sign("monitor-daily", int(chat_id or 0)),
        "text": str(text or ""),
        "project": str(project or ""),
        "taken_at": str(taken_at or ""),
        "title": str(title or ""),
    }
    url = _core_api_url("/internal/monitor/daily")
    if url:
        return _core_post(url, payload, 30.0)
    return internal_monitor_daily(SiteChatReportRequest(**payload))


def _sales_chat_store(chat: dict[str, Any], message: dict[str, Any], text: str,
                      taken_at: str, *, action: str = "report", batch_id: str = "",
                      sent_message_id: int = 0, project: str = "") -> dict[str, Any]:
    """Отчёт отдела продаж — ядру, той же дорогой, что сводка стройки."""
    chat_id = int((chat or {}).get("id") or 0)
    sender = message.get("from") or {}
    author = " ".join(str(sender.get(k) or "").strip()
                      for k in ("first_name", "last_name")).strip()
    original = message.get("reply_to_message") or {}
    original_sender = original.get("from") or {}
    payload = {
        "chat_id": chat_id,
        "sign": _web_login_sign("monitor-sales", chat_id),
        "title": str((chat or {}).get("title") or ""),
        "author": author,
        "text": str(text or ""),
        "taken_at": str(taken_at or ""),
        "action": action,
        "project": project,
        "batch_id": batch_id,
        "message_id": int(sent_message_id or message.get("message_id") or 0),
        "author_id": int(sender.get("id") or 0),
        "telegram_date": int(message.get("date") or 0),
        "reply_to_id": int(original.get("message_id") or 0),
        "reply_text": str(original.get("text") or ""),
        "reply_from_id": int(original_sender.get("id") or 0),
        "reply_is_bot": bool(original_sender.get("is_bot")),
    }
    url = _core_api_url("/internal/monitor/sales-chat")
    if url:
        return _core_post(url, payload, 30.0)
    return internal_monitor_sales_chat(SalesChatRequest(**payload))


# Снимок для сводки: самый крупный размер не длиннее этой стороны. В PDF фото
# идёт на полстраницы (около 9 см) — 1280 точек хватает с запасом, а полный
# размер занимал бы диск ядра в разы больше.
_SITE_PHOTO_SIDE = 1280


def _site_photo_size(sizes: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not sizes:
        return None
    fit = [s for s in sizes if max(int(s.get("width") or 0), int(s.get("height") or 0))
           <= _SITE_PHOTO_SIDE]
    pick = fit or sizes
    return max(pick, key=lambda s: int(s.get("width") or 0) * int(s.get("height") or 0))


def _site_photo_store(chat: dict[str, Any], message: dict[str, Any]) -> dict[str, Any]:
    """Скачать фото из чата стройки и отдать ядру — та же дорога, что у отчётов."""
    import developaid_site_photos as site_photos

    size = _site_photo_size(list(message.get("photo") or []))
    if not size:
        return {"bound": "", "error": "в сообщении нет размеров фото"}
    data = _telegram_file_bytes(str(size.get("file_id") or ""), site_photos.MAX_BYTES)
    stamp = message.get("date")
    try:
        moment = datetime.fromtimestamp(int(stamp), _TELEGRAM_MOSCOW)
    except (TypeError, ValueError, OSError):
        moment = datetime.now(_TELEGRAM_MOSCOW)
    sender = message.get("from") or {}
    author = " ".join(str(sender.get(k) or "").strip()
                      for k in ("first_name", "last_name")).strip()
    chat_id = int((chat or {}).get("id") or 0)
    payload = {
        "chat_id": chat_id,
        "sign": _web_login_sign("monitor-photo", chat_id),
        "photo_id": str(size.get("file_unique_id") or "")[:80],
        "data": base64.b64encode(data).decode("ascii"),
        "day": moment.date().isoformat(),
        "at": moment.isoformat(timespec="seconds"),
        "author": author or str(sender.get("username") or ""),
        "caption": str(message.get("caption") or ""),
        "message_id": int(message.get("message_id") or 0),
    }
    url = _core_api_url("/internal/monitor/photo")
    if url:
        return _core_post(url, payload, 60.0)
    return internal_monitor_photo(SitePhotoRequest(**payload))


def _site_photo_job(chat: dict[str, Any], message: dict[str, Any]) -> None:
    """Фоном: вебхук не ждёт скачивания. Исход — в счётчике `/status`."""
    try:
        answer = _site_photo_store(chat, message)
    except Exception as exc:  # noqa: BLE001 — причина уходит в /status
        _telegram_group_seen(chat, "фото не сохранено: " + str(exc)[:80])
        return
    if answer.get("bound"):
        _telegram_group_seen(chat, "фото сохранено для сводки проекта «"
                             + str(answer["bound"]) + "»", project=str(answer["bound"]))
    else:
        _telegram_group_seen(chat, "фото не сохранено: группа не авторизована — доступ разрешает владелец в кабинете")


def _site_photo_async(chat: dict[str, Any], message: dict[str, Any]) -> None:
    threading.Thread(target=_site_photo_job, args=(chat, message),
                     name="site-photo", daemon=True).start()


def _telegram_group_seen(chat: dict[str, Any], outcome: str = "", *, project: str = "") -> None:
    """Счётчик увиденного в группах — иначе молчание нечем объяснить.

    «Privacy mode не сняли», «бота не переподключили» и «мост не дописан»
    снаружи выглядят одинаково: бот молчит. А с 13.09.2026 он молчит и по
    решению владельца («в чат ничего не надо»), то есть молчание перестало
    быть признаком поломки вовсе — значит счётчик тут не удобство, а
    единственный ответ на «дошло ли». Рядом с числом лежит ИСХОД последнего
    разбора: привязка, принятая сводка с числами, отказ с причиной.
    """
    seen = getattr(app.state, "telegram_group_seen", None)
    if seen is None:
        seen = {}
        app.state.telegram_group_seen = seen
    key = str(int((chat or {}).get("id") or 0))
    row = seen.setdefault(key, {"title": "", "count": 0, "last": "", "outcome": ""})
    row["title"] = str((chat or {}).get("title") or row["title"])
    row["count"] = int(row["count"]) + 1
    row["last"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    if outcome:
        row["outcome"] = str(outcome)
        row["project"] = str(project or "")


def _telegram_bindings_line(user_id: int) -> str:
    """Closed group/project metadata only under a current owner-issued grant.

    The core verifies the group scope and key generation. A mailing subscription
    or Telegram login alone does not authorize this status data.
    """
    who = int(user_id or 0)
    if not who:
        return ""
    try:
        payload = {"chat_id": who, "sign": _web_login_sign("monitor-chats", who)}
    except HTTPException:
        return ""  # no transport signature: the core cannot verify this request
    try:
        url = _core_api_url("/internal/monitor/site-chats")
        got = (_core_post(url, payload, 15.0) if url
               else internal_monitor_site_chats(SiteChatsRequest(**payload)))
    except Exception as exc:
        return "\nПривязки чатов: не получил с сервера — " + html.escape(str(exc)[:120]) + "."
    if got.get("authorized") is not True or got.get("chat_id") != who:
        return ""
    projects = got.get("projects") or []
    chat_projects = {int(chat): str(row.get("project") or "")
                     for row in projects for chat in row.get("chat_ids") or []}
    seen = _telegram_group_seen_line(chat_projects=chat_projects)
    if not projects:
        return ("\nПривязки чатов: доступ группы к проекту разрешает владелец в закрытом кабинете." + seen)
    lines = []
    for row in projects:
        chats = ", ".join(f"«{html.escape(title)}»" if title else "чат без названия"
                          for title in row.get("chats") or [])
        site = (f"сводка с площадки — последняя {_telegram_day(row['site_last'])}"
                if row.get("site_last") else "сводок с площадки нет")
        if not row.get("sales_project"):
            sales = "с отчётом о продажах не связан"
        elif row.get("sales_last"):
            sales = f"отчёт продаж — последний {_telegram_day(row['sales_last'])}"
        else:
            sales = "отчётов продаж из чата нет"
        lines.append(f"«{html.escape(str(row.get('project') or ''))}»: {chats}; {site}; {sales}")
    return "\nПривязки чатов (на сервере):\n• " + "\n• ".join(lines) + seen


def _telegram_day(value: str) -> str:
    try:
        return datetime.fromisoformat(str(value)[:10]).strftime("%d.%m.%Y")
    except ValueError:
        return str(value)


def _telegram_group_seen_line(*, chat_projects: dict[int, str] | None = None) -> str:
    """Строка о группах для /status: что бот оттуда увидел и чем это кончилось.

    Пустой счётчик — это ответ, а не прочерк: privacy mode Telegram по
    умолчанию включён, и тогда обычных сообщений группы бот не получает вовсе.
    Отличить это от «мост не дописан» иначе нечем.

    Счёт идёт с запуска ЭТОГО воркера, и так и написано: воркеров два, память
    у них раздельная, и пустая строка у второго — не «бот ничего не видел».
    Сама привязка при этом живёт на ядре и выкатку переживает.
    """
    seen = getattr(app.state, "telegram_group_seen", None) or {}
    if not seen:
        return ("\nГруппы: сообщений не видел ни одного (счёт с запуска этого воркера). "
                "Если ждёте сводку с площадки — у бота включён privacy mode либо его "
                "не переподключили к группе.")
    scoped = []
    for key, row in seen.items():
        if chat_projects is not None:
            if int(key) not in chat_projects:
                continue
            # An owner may deliberately move this group to a different scope.
            # Do not expose its cached outcomes from the previously granted project.
            if row.get("project") != chat_projects[int(key)]:
                row = dict(row, outcome="")
        scoped.append(row)
    rows = sorted(scoped, key=lambda row: int(row.get("count") or 0), reverse=True)
    if not rows:
        return ""
    parts = []
    for row in rows[:5]:
        line = f"{row.get('title') or 'без имени'} — {int(row.get('count') or 0)}"
        if row.get("outcome"):
            line += "; " + str(row.get("outcome"))
        parts.append(line)
    return "\nГруппы (с запуска этого воркера):\n• " + "\n• ".join(parts)


def _telegram_group_reply(message: dict[str, Any], text: str) -> bool:
    """Ответ уходит в ЛИЧКУ тому, кто написал, а не в групповой чат.

    Решение владельца 13.09.2026: «в чат ничего не надо». Но человек, набравший
    `/site`, обязан узнать, сработало ли, — молчание в ответ на команду
    неотличимо от сломанной команды. Личка это и есть ответ ему: он сам начал,
    и группа при этом не видит ничего.

    Не начинавшему разговор с ботом Telegram написать не даст — это не поломка,
    а его настройка, и тогда исход остаётся в счётчике `/status`.
    """
    user_id = int((message.get("from") or {}).get("id") or 0)
    if not user_id:
        return False
    try:
        _telegram_send_message(user_id, text)
    except Exception:
        return False
    return True


def _telegram_group_message(chat: dict[str, Any], message: dict[str, Any]) -> None:
    """Групповой чат: бот не пишет туда ничего и никогда.

    Прежде на КАЖДОЕ сообщение из группы он отвечал «DevelopAid работает в
    личном чате с ботом». Пока privacy mode был включён, он видел только
    команды, и это почти не замечалось; со снятым privacy в рабочем чате на
    четырнадцать человек это стало бы потоком. Первая правка оставила ответы
    на адресованное — сводку и `/site`; владелец снял и их: «в чат ничего не
    надо» (13.09.2026).

    Отсюда правило: у группы бот только ЧИТАТЕЛЬ. Что он прочёл, видно в двух
    местах — в личке у того, кто написал команду, и в `/status`.
    """
    chat_id = int((chat or {}).get("id") or 0)
    if not chat_id:
        return
    if message.get("photo"):
        # Фото из чата стройки — кандидат в сводку руководству. Выбирает
        # человек на странице сводки; здесь только сохраняем. Подпись к фото
        # дальше читается как обычно: вдруг это и есть отчёт.
        _site_photo_async(chat, message)
    text = str(message.get("text") or message.get("caption") or "").strip()
    if not text:
        _telegram_group_seen(chat)
        return

    head = text.split(maxsplit=1)[0].lower() if text.startswith("/") else ""
    command = head.split("@", 1)[0]

    if command == "/site":
        _telegram_group_seen(chat, "чат не привязан автоматически: нужна авторизация владельца в кабинете")
        _telegram_group_reply(
            message,
            "Доступ группы к проекту разрешает владелец в закрытом кабинете Монитора.\n"
            "Telegram ID этой группы: <code>" + str(chat_id) + "</code>.\n"
            "Укажите там проект и этот ID. Ключ администратора вводится только в кабинете.")
        return

    parsed = None
    try:
        import developaid_monitor_daily as daily

        parsed = daily.parse_daily_report(text)
    except Exception:
        parsed = None
    stamp = message.get("date")
    try:
        taken_at = datetime.fromtimestamp(
            int(stamp), _TELEGRAM_MOSCOW).date().isoformat()
    except (TypeError, ValueError, OSError):
        taken_at = ""
    # Ответ на вопрос Платона — отдельный маршрут, до распознавания отчёта.
    # Не читаем посторонние ответы/ботов и не отвечаем в группу квитанцией.
    from market_search import sales_dialogue

    original = message.get("reply_to_message") or {}
    original_sender = original.get("from") or {}
    bot_id = str(_telegram_token() or "").partition(":")[0]
    if (not (message.get("from") or {}).get("is_bot") and bot_id.isdigit()
            and str(original_sender.get("id") or "") == bot_id
            and original_sender.get("is_bot")
            and sales_dialogue.is_question(str(original.get("text") or ""))):
        try:
            result = _sales_chat_store(chat, message, text, taken_at, action="reply")
            outcome = ("ответ Платону сохранён" if result.get("reply_saved")
                       else "ответ Платону не сохранён: сообщение вопроса не найдено")
            if result.get("reply_saved") and result.get("reply_unattributed"):
                outcome += " без привязки к проекту: исторический вопрос"
            _telegram_group_seen(chat, outcome)
        except Exception as exc:
            _telegram_group_seen(chat, "ответ Платону не сохранён: " + str(exc)[:80])
        return
    if not parsed or not parsed.get("contractors"):
        from market_search import salesroom

        if salesroom.is_sales_report(text):
            # Ежедневный отчёт отдела продаж (владелец, 24.10.2026: «может
            # туда тоже бота посадить? Для отчётов по звонкам, броням»).
            try:
                answer = _sales_chat_store(chat, message, text, taken_at)
            except Exception as exc:
                _telegram_group_seen(chat, "отчёт продаж не сохранён: " + str(exc)[:80])
                return
            if not answer.get("bound"):
                _telegram_group_seen(chat, "отчёт продаж прочитан, но группа не авторизована — доступ разрешает владелец в кабинете")
            elif not answer.get("sales_project"):
                _telegram_group_seen(chat, "отчёт продаж прочитан, но проект «"
                                     + str(answer.get("bound")) + "» не связан с отчётом "
                                     "о продажах — свяжите на странице сводки")
            else:
                _telegram_group_seen(chat, "отчёт продаж" + (" за " + taken_at if taken_at else "")
                                     + " → «" + str(answer.get("sales_project")) + "»",
                                     project=str(answer.get("bound") or ""))
                # Вопросы Платона по сверке с выгрузкой договоров — одним
                # коротким сообщением в тот же чат (их собирает ядро).
                if answer.get("ask_error"):
                    _telegram_group_seen(chat, "вопросы Платона не собраны: "
                                         + str(answer["ask_error"])[:80])
                if answer.get("ask"):
                    try:
                        # Recheck current core authorization immediately before disclosure.
                        expected_project = str(answer.get("bound") or "")
                        checked = _sales_chat_store(chat, message, "", taken_at, action="send",
                                                    project=expected_project)
                        if (checked.get("authorized") is not True or not expected_project
                                or checked.get("bound") != expected_project):
                            raise HTTPException(403, "Ядро не подтвердило доступ группы к проекту.")
                        sent = _telegram_send_message(int(chat.get("id") or 0), str(answer["ask"]))
                    except Exception as exc:
                        _telegram_group_seen(chat, "вопрос Платона не отправлен: "
                                             + str(exc)[:80])
                        return
                    sent_id = int((sent or {}).get("message_id") or 0)
                    if answer.get("ask_id") and sent_id:
                        try:
                            delivery = _sales_chat_store(
                                chat, message, "", taken_at, action="delivered",
                                batch_id=str(answer["ask_id"]), sent_message_id=sent_id,
                                project=str(answer.get("bound") or ""))
                            if not delivery.get("delivered"):
                                _telegram_group_seen(chat, "вопрос отправлен, связь с сообщением не сохранена")
                        except Exception as exc:
                            _telegram_group_seen(chat, "вопрос отправлен, связь с сообщением не сохранена: "
                                                 + str(exc)[:80])
            return
        # Не отчёт — просто считаем. Рабочая переписка нас не касается.
        _telegram_group_seen(chat)
        return

    try:
        answer = _site_chat_store(chat_id, text, taken_at,
                                  title=str((chat or {}).get("title") or ""))
    except Exception as exc:
        _telegram_group_seen(chat, "сводка не сохранена: " + str(exc)[:80])
        return
    if not answer.get("bound"):
        # Сводка есть, а проекта нет — класть её некуда. Это наш пробел, и он
        # обязан быть виден: молча выброшенный отчёт читается как «сводки не
        # было». В чат при этом не пишем — там о нашей привязке не знают.
        _telegram_group_seen(chat, "сводка прочитана, но группа не авторизована — доступ разрешает владелец в кабинете")
        return
    _telegram_group_seen(
        chat,
        "сводка" + (" за " + taken_at if taken_at else "") + ": подрядчиков "
        + str(len(parsed.get("contractors") or []))
        + ", ИТР " + str(parsed.get("itr_total") or 0)
        + ", рабочих " + str(parsed.get("workers_total") or 0)
        + " → «" + str(answer.get("bound")) + "»", project=str(answer.get("bound") or ""))


def _telegram_is_group(chat: dict[str, Any] | None) -> bool:
    """Групповой ли это чат. Один ответ на оба входа — движка и обёртки.

    Опознаём ПОЛОЖИТЕЛЬНО, а не «всё, что не private». Telegram `type`
    присылает всегда, а собранное в коде сообщение его не несёт — и правило
    «не private, значит группа» онемляло личку: три проверки Платона разом
    получили пустой ответ там, где бот обязан ответить. Молчащий в личке бот
    выглядит сломанным, и умолчанием это не лечится.

    Типа нет — смотрим номер чата: отрицательный бывает только у групп и
    каналов. Это признак самой группы, а не догадка о её отсутствии.
    """
    kind = str((chat or {}).get("type") or "").strip().lower()
    if kind:
        return kind in {"group", "supergroup", "channel"}
    try:
        return int((chat or {}).get("id") or 0) < 0
    except (TypeError, ValueError):
        return False


def _telegram_handle_message(message: dict[str, Any]) -> None:
    chat = message.get("chat") or {}
    sender = message.get("from") or {}
    chat_id = int(chat.get("id") or 0)
    user_id = int(sender.get("id") or chat_id)
    if not chat_id:
        return
    if _telegram_is_group(chat):
        _telegram_group_message(chat, message)
        return
    text = str(message.get("text") or "").strip()
    command = text.split(maxsplit=1)[0].split("@", 1)[0].lower() if text.startswith("/") else ""
    if command in {"/start", "/help", "/menu"}:
        # «/start login_<код>» — подтверждение входа на сайт: человек пришёл
        # по ссылке со страницы, код связывается с его chat_id, и страница
        # забирает сессию. Отвечаем по делу и не разворачиваем меню.
        start_payload = text.split(maxsplit=1)[1].strip() if " " in text else ""
        # Сразу вход не подтверждается: ссылку мог прислать чужой человек,
        # запросивший код у себя, — тогда молчаливое подтверждение отдало бы
        # ему сессию этого чата. Бот спрашивает и показывает код для сверки.
        if command == "/start" and start_payload.startswith("login_"):
            _telegram_web_login_ask(chat_id, start_payload[len("login_"):])
            return
        # «/start rep_<код>» — приглашение на сводку руководству по проекту:
        # ссылку создаёт владелец на странице сводки. Подписка живёт на ядре.
        if command == "/start" and start_payload.startswith("rep_"):
            _telegram_report_subscribe(chat_id, start_payload, _telegram_sender_name(message))
            return
        # «/start <метка>» — переход по приглашению: ссылку кладут в канал, и
        # адрес сайта человек заранее не знает. Метка приезжает в payload, и с
        # первого нажатия известно, кто пришёл и откуда: chat_id, имя, источник.
        # Иначе от публикации на пятьсот человек остаётся только счётчик заходов
        # без единого имени, а спросить потом некого.
        source = _telegram_invite_source(start_payload)
        if source:
            usage_track("invite", surface="bot", chat_id=chat_id, user_id=user_id,
                        name=_telegram_sender_name(message), source=source)
        _telegram_start_message(chat_id, user_id, source=source)
        return
    if command == "/report_stop":
        _telegram_report_unsubscribe(chat_id)
        return
    if command == "/status":
        status = "подключён" if _TELEGRAM_RUNTIME.get("configured") else "запускается"
        _telegram_send_message(
            chat_id,
            f"<b>DevelopAid bot:</b> {status}\nTelegram ID: <code>{user_id}</code>\nВерсия: {VERSION}"
            + _telegram_bindings_line(user_id),
        )
        return
    if command == "/cancel":
        _telegram_dialog_clear(chat_id)
        _telegram_start_message(chat_id, user_id)
        return
    if not _telegram_user_allowed(user_id):
        _telegram_start_message(chat_id, user_id)
        return
    if command == "/template":
        _telegram_send_template(chat_id)
        return
    if command == "/calc":
        _telegram_calc_menu(chat_id)
        return
    if command == "/cadastre":
        _telegram_dialog_callback(chat_id, user_id, "flow_cad_yes")
        return
    if command == "/address":
        _telegram_dialog_callback(chat_id, user_id, "flow_address")
        return
    if command == "/tep":
        _telegram_dialog_callback(chat_id, user_id, "flow_cad_no")
        return
    if command in {"/model", "/plato"}:
        _telegram_send_message(
            chat_id,
            "<b>Модель DevelopAid</b>\n\n"
            "Откройте полную модель для настройки экономики, финансирования и сценариев.",
            reply_markup={"inline_keyboard": [[{
                "text": "Открыть модель DevelopAid",
                "web_app": {"url": _telegram_web_app_url(chat_id, [])},
            }]]},
        )
        return
    if command == "/example":
        _telegram_send_message(
            chat_id,
            "<b>Пример свободного ввода</b>\n\n"
            "<code>Проект Северный. Участок 2,4 га. Квартиры — 42 000 м² продаваемой площади. "
            "Коммерция — 2 500 м². Подземный паркинг — 620 мест. ДОО — 150 мест.</code>",
        )
        return
    if message.get("photo"):
        photo = max(message["photo"], key=lambda p: int(p.get("width") or 0) * int(p.get("height") or 0))
        _telegram_handle_manual_document(chat_id, {**photo, "file_name": "тизер.jpg"})
        return
    if re.fullmatch(r"https://\S+", text):
        import document_source
        try:
            loaded = document_source.read_url(text)
            document = ({"text": loaded["text"], "pages": 1, "pages_read": 1,
                         "filename": loaded["filename"], "recognized": False, "reason": ""}
                        if "text" in loaded else document_intake.extract_text(loaded["data"], loaded["filename"]))
            document["source"] = loaded["source"]
            _telegram_handle_intake_document(chat_id, b"", loaded["filename"], document_override=document)
        except document_source.DocumentSourceError as exc:
            _telegram_send_message(chat_id, "Не удалось прочитать ссылку: " + html.escape(str(exc)))
        return
    document = message.get("document")
    if isinstance(document, dict):
        _telegram_handle_manual_document(chat_id, document)
        return
    if _telegram_handle_dialog_text(chat_id, text):
        return

    try:
        numbers = _parse_cadastral_numbers(text)
    except HTTPException:
        # Адрес раньше уходил в сбор ТЭП вручную, и бот спрашивал площадь в
        # гектарах вместо того, чтобы найти участок — хотя веб-версия ищет.
        if _looks_like_address(text) and _telegram_handle_address(chat_id, text):
            return
        _telegram_handle_freeform_tep(chat_id, text)
        return
    _telegram_handle_cadastral_numbers(chat_id, numbers, text)


_WEB_LOGIN_CODE_RE = re.compile(r"[0-9a-f]{6,64}")


def _telegram_web_login_ask(chat_id: int, code: str) -> None:
    """Вопрос «войти на сайт?» с кодом для сверки и двумя кнопками."""
    code = str(code or "").strip().lower()
    if not _WEB_LOGIN_CODE_RE.fullmatch(code):
        _telegram_send_message(
            chat_id, "<b>Вход не подтверждён.</b>\nВ ссылке нет кода входа — "
                     "нажмите «Войти» на сайте ещё раз.")
        return
    _telegram_send_message(
        chat_id,
        "<b>Войти на сайт DevelopAid под вашим Telegram?</b>\n\n"
        f"Код входа: <b>{html.escape(_web_login_display(code))}</b>\n\n"
        "Подтверждайте, только если вы сами только что нажали «Войти» на сайте "
        "и на вашем экране виден этот же код. Если ссылку прислал другой "
        "человек, нажмите «Нет»: иначе он войдёт на сайт от вашего имени и "
        "увидит ваши проекты.",
        reply_markup={"inline_keyboard": [
            [{"text": "Да, это я — войти", "callback_data": f"login_ok:{code}"}],
            [{"text": "Нет, я не входил", "callback_data": f"login_no:{code}"}],
        ]})


def _telegram_web_login_answer(chat_id: int, data: str, name: str) -> None:
    """Ответ на кнопку вопроса о входе: подтверждение — только по «Да»."""
    verdict, _, code = data.partition(":")
    if verdict != "login_ok":
        _telegram_send_message(
            chat_id, "<b>Вход отклонён.</b> На сайт по этой ссылке никто не войдёт: "
                     "код сгорит сам через несколько минут.")
        return
    if not _WEB_LOGIN_CODE_RE.fullmatch(code):
        _telegram_send_message(chat_id, "<b>Вход не подтверждён.</b>\nКод входа не похож на код.")
        return
    try:
        _web_login_confirm(code, chat_id, name)
        _telegram_send_message(
            chat_id,
            "<b>Вход на сайт подтверждён.</b> Вернитесь во вкладку браузера — "
            "она подхватит вход сама в течение пары секунд.")
    except HTTPException as exc:
        _telegram_send_message(
            chat_id, "<b>Вход не подтверждён.</b>\n" + html.escape(str(exc.detail)))
    except Exception as exc:
        _telegram_send_message(
            chat_id, "<b>Вход не подтверждён.</b>\n" + html.escape(str(exc)))


def _telegram_handle_update(update: dict[str, Any]) -> None:
    message = update.get("message")
    if isinstance(message, dict):
        _telegram_handle_message(message)
        return
    query = update.get("callback_query")
    if isinstance(query, dict):
        sender = query.get("from") or {}
        user_id = int(sender.get("id") or 0)
        message = query.get("message") or {}
        chat_id = int(((message.get("chat") or {}).get("id")) or user_id)
        query_id = str(query.get("id") or "")
        data = str(query.get("data") or "")
        if query_id:
            try:
                _telegram_api("answerCallbackQuery", {"callback_query_id": query_id})
            except Exception:
                pass
        if not chat_id:
            return
        # Вход на сайт — только из личного чата: сессия выдаётся на chat_id, а
        # кнопку в группе может нажать любой её участник.
        if data.startswith(("login_ok:", "login_no:")):
            if chat_id > 0 and chat_id == user_id:
                _telegram_web_login_answer(chat_id, data, _telegram_sender_name(query))
            return
        if not _telegram_user_allowed(user_id):
            _telegram_start_message(chat_id, user_id)
            return
        if data == "tep_template":
            _telegram_send_template(chat_id)
            return
        if data == "calc_menu":
            # Второй уровень «Расчёта модели» — тот же, что у команды /calc:
            # выбор способа живёт в одном месте, а не в двух похожих меню.
            _telegram_calc_menu(chat_id)
            return
        if data == "show_help":
            _telegram_send_message(
                chat_id,
                "<b>Что умеет DevelopAid</b>\n\n"
                "Отправьте кадастровый номер, адрес или координаты — методику бот выберет сам:\n\n"
                "• <b>Москва</b>, включая Троицкий и Новомосковский округа, — нормативные ТЭП "
                "по калькулятору ГлавАПУ;\n"
                "• <b>Московская область</b> — нормативы РНГП МО и плата за смену ВРИ по УПКС "
                "и распоряжению № 114-Р;\n"
                "• <b>другой регион</b> — сведения ЕГРН по участку, ТЭП вводится экспертно: "
                "ответами на вопросы бота или через Excel-шаблон.\n\n"
                "Дальше одинаково для всех: продажи, затраты, налоги, БРИДЖ, ПФ и эскроу, "
                "прогноз ключевой ставки и сценарии, очередность с распределением общепроектных "
                "расходов и социальной нагрузки, PDF-отчёт и выгрузка модели в Excel.\n\n"
                "Подробная пошаговая инструкция — команда /help.",
                reply_markup={"inline_keyboard": [[{
                    "text": "Открыть мини-приложение DevelopAid",
                    "web_app": {"url": _telegram_web_app_url(chat_id, [])},
                }]]},
            )
            return
        if data.startswith(("intake_", "intake2_")):
            _telegram_intake_callback(chat_id, data)
            return
        if data.startswith("flow_"):
            _telegram_dialog_callback(chat_id, user_id, data)


def _telegram_configure() -> None:
    if not _telegram_token():
        _TELEGRAM_RUNTIME.update(configured=False, last_error="TELEGRAM_BOT_TOKEN не задан")
        return
    errors: list[str] = []
    try:
        info = _telegram_api("getMe")
        _TELEGRAM_RUNTIME["username"] = str((info or {}).get("username") or "")
        if _telegram_webhook_enabled():
            _telegram_api("setWebhook", {
                "url": _TELEGRAM_PUBLIC_BASE_URL + "/telegram/webhook",
                "secret_token": _telegram_webhook_secret(),
                "allowed_updates": ["message", "callback_query"],
                "drop_pending_updates": False,
            })
        else:
            # Второй экземпляр с тем же токеном обязан молчать: вебхук у Telegram
            # один на бота, и перерегистрация увела бы обновления с хоста, где
            # бот действительно живёт. Токен здесь нужен только чтобы проверять
            # подпись сессии мини-приложения и отправлять готовую карточку.
            _TELEGRAM_RUNTIME["webhook_mode"] = "выключен: вебхук держит другой хост"
        _telegram_api("setMyCommands", {"commands": TELEGRAM_BOT_COMMANDS})
        try:
            _telegram_api("setChatMenuButton", {
                "menu_button": {
                    "type": "commands",
                }
            })
        except Exception as exc:
            errors.append(str(exc))
        _TELEGRAM_RUNTIME.update(
            configured=True,
            last_error="; ".join(errors),
            configured_at=datetime.now(timezone.utc).isoformat(),
        )
    except Exception as exc:
        _TELEGRAM_RUNTIME.update(configured=False, last_error=str(exc))


@app.on_event("startup")
def _start_telegram_configuration() -> None:
    if _telegram_token():
        threading.Thread(target=_telegram_configure, daemon=True).start()


@app.get("/telegram/status")
def telegram_status() -> dict[str, Any]:
    allowed = _telegram_allowed_user_ids()
    return {
        "enabled": bool(_telegram_token()),
        "configured": bool(_TELEGRAM_RUNTIME.get("configured")),
        "username": _TELEGRAM_RUNTIME.get("username") or "",
        "bot_url": (
            "https://t.me/" + str(_TELEGRAM_RUNTIME.get("username"))
            if _TELEGRAM_RUNTIME.get("username") else ""
        ),
        "webhook_url": _TELEGRAM_PUBLIC_BASE_URL + "/telegram/webhook",
        "access_mode": "allowlist" if allowed else "open",
        "allowed_users_count": len(allowed),
        "configured_at": _TELEGRAM_RUNTIME.get("configured_at") or "",
        "last_error": _TELEGRAM_RUNTIME.get("last_error") or "",
        # Кто считает ТЭП: настоящий калькулятор или наш пересказ методики.
        # Без этого «бот опять посчитал не то» проверяется только скриншотами.
        "glavapu_headless": {
            "enabled": _GLAVAPU_HEADLESS_ENABLED,
            "runs": _GLAVAPU_HEADLESS.get("runs", 0),
            "fallbacks": _GLAVAPU_HEADLESS.get("fallbacks", 0),
            # Сколько раз расчёт не дождался свободного браузера: если растёт,
            # машине мало памяти под параллельные запуски.
            "queue_timeouts": _GLAVAPU_HEADLESS.get("waits", 0),
            "parallel_slots": _GLAVAPU_HEADLESS_SLOTS,
            # Секунды расчёта по шагам: «считает минуту» — это диагноз, а не
            # жалоба, только когда видно, какой шаг эту минуту берёт.
            "last_ms": dict(_GLAVAPU_HEADLESS.get("last_ms") or {}),
            # Повторный расчёт того же участка обязан быть мгновенным: если
            # попаданий нет, значит браузер поднимается там, где не должен.
            "cache_hits": _GLAVAPU_TEP_CACHE_HITS["hits"],
            "cache_size": len(_GLAVAPU_TEP_CACHE),
            # Пока предохранитель взведён, расчёт идёт формулами сразу, а не
            # после полутора минут ожидания. Причина — в last_error.
            "blocked_for_seconds": max(0, int(_GLAVAPU_HEADLESS_BLOCKED_UNTIL["at"]
                                              - time.monotonic())),
            "browser_warm": bool(_GLAVAPU_BROWSER_THREAD
                                 and _GLAVAPU_BROWSER_THREAD.is_alive()),
            "last_ok": _GLAVAPU_HEADLESS.get("last_ok", ""),
            "last_error": _GLAVAPU_HEADLESS.get("last_error", ""),
        },
        "version": VERSION,
    }


def _telegram_process_update(update: dict[str, Any]) -> None:
    try:
        _telegram_handle_update(update)
    except Exception as exc:
        # Причина доносится в чат вместе с местом: «попробуйте через минуту»
        # не лечит ничего, если через минуту сломается то же самое, а логи
        # хостинга недоступны. Здесь это работало наоборот всех прочих веток —
        # верхний перехват оставлял себе всё, что до него долетело.
        where = _error_location(exc)
        _TELEGRAM_RUNTIME["last_error"] = where
        message = update.get("message") if isinstance(update, dict) else None
        if not isinstance(message, dict) and isinstance(update, dict):
            query = update.get("callback_query")
            message = query.get("message") if isinstance(query, dict) else None
        chat = (message or {}).get("chat") if isinstance(message, dict) else None
        chat_id = (chat or {}).get("id") if isinstance(chat, dict) else None
        if _telegram_is_group(chat):
            # В группу бот не пишет НИЧЕГО и никогда — верхний перехват не
            # исключение. Он им и был: 429 «Too Many Requests» приезжал
            # ответом в тот самый чат, где бот и без того наговорил лишнего
            # (экран владельца, 14.09.2026). Исход группы виден в `/status`.
            chat_id = None
        if chat_id and "429" not in where and "Too Many Requests" not in where:
            # Отказ по частоте не докладывают ещё одним сообщением: причина
            # ошибки — как раз лишние сообщения, и доклад её усиливает. Он
            # остаётся в `/status` строкой last_error.
            try:
                _telegram_send_message(
                    int(chat_id),
                    "<b>Не удалось завершить запрос.</b>\n"
                    f"<i>{html.escape(where[:300])}</i>\n\n"
                    "Если повторится — пришлите эту строку: в ней файл, строка и функция.",
                )
            except Exception:
                pass


@app.post("/telegram/webhook")
async def telegram_webhook(request: Request) -> dict[str, bool]:
    token = _telegram_token()
    supplied = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
    if not token or not hmac.compare_digest(supplied, _telegram_webhook_secret()):
        raise HTTPException(status_code=403, detail="Invalid Telegram webhook secret")
    # Секрет проверен выше, то есть сюда доходит только тот, у кого он есть.
    # Разбор всё равно идёт через общий сторож: тело, которое не разобралось
    # или пришло не объектом, — это не Telegram, а `_telegram_process_update`
    # на списке падал бы в ПОТОКЕ, то есть молча (ошибка, ушедшая только в
    # лог, — это ошибка, которой нет).
    update = await json_object(request)
    threading.Thread(target=_telegram_process_update, args=(update,), daemon=True).start()
    return {"ok": True}


@app.post("/telegram/session-data")
def telegram_session_data(req: TelegramSessionRequest) -> dict[str, Any]:
    session = _telegram_verify_session(req.session)
    chat_id = int(session["chat_id"])
    if not _telegram_user_allowed(chat_id):
        raise HTTPException(status_code=403, detail="Доступ к боту закрыт")
    overrides = session.get("calc_overrides") or {}
    review = bool(overrides) and _telegram_carry_application_proof(session) is None
    qualification = overrides.get(intake_qualification.KEY)
    if qualification is not None and (
            not isinstance(qualification, dict)
            or qualification.get('recipient') != _intake_qualification_recipient(chat_id)):
        review = True
    result = {
        "cadastral_numbers": session.get("cad") or [],
        "manual_tep": session.get("manual_tep"),
        "calc_overrides": {} if review else overrides,
        "overrides_review_required": review,
    }
    carried = session.get('calculation_qualification')
    if carried is not None:
        state = _intake_qualification_state({intake_qualification.KEY:carried})
        recipient = carried.get('recipient') if isinstance(carried, dict) else None
        if state and state.get('verified') and recipient in (None, _intake_qualification_recipient(chat_id)):
            result['calculation_qualification'] = carried
        else:
            result['qualification_review_required'] = True
    if session.get('qualification_review_required') is True:
        result['qualification_review_required'] = True
    return result


@app.post(document_protocol.SESSION_PATH)
def telegram_session_data_qualified(req: TelegramSessionRequest) -> dict[str, Any]:
    return {**telegram_session_data(req), 'document_protocol': document_protocol.capability()}
