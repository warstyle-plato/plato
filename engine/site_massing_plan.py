"""План расстановки корпусов от Платона: фоновый запрос, хранение, свежесть.

Решение владельца (23.10.2026, AskUserQuestion): расстановку предлагает
модель, движок проверяет и хранит. Модель решает планировочное — какой корпус
в какой квартал и на какой фронт, где двор, где башня, порядок очередей вдоль
участка; геометрию строит и проверяет движок (`engine/site_massing_blocks.py`).

- Один источник. План лежит на диске (`data/platon_state/massing_plan`) под
  отпечатком входов схемы: контур без отступов, корпуса (площадь, этажность,
  очередь), отступ, версия методики. Схему строит `site_massing_layout`, а её
  читают страница, PDF и карта участка — модель для них отдельно не зовётся.
- Свежесть. Входы поменялись — отпечаток другой, прежнего плана для них нет.
  Последний план участка помнится указателем по контуру: тогда схема говорит,
  что план устарел, и до нового показывает расстановку движка.
- Не синхронно. Запрос модели идёт в фоновой нити; расчёт его не ждёт. Пока
  плана нет — расстановка движка и фраза «план готовится»; страница спрашивает
  `/site-massing/plan/{key}` и пересчитывает схему, когда план готов. Два
  воркера не зовут модель дважды: замок — файл на диске.
- Маршрут модели — единый `_openai_responses_request` (`engine/agent.py`).
- Ответ модели — строгий JSON; не прошёл проверку движка — отклонён с
  названной причиной (одна повторная попытка с этой причиной), на схеме
  расстановка движка.

Не самостоятельный модуль: `main_legacy.py` выполняет файл в пространстве
имён движка (`_engine_part("site_massing_plan")`).
"""
# ruff: noqa

# Версия методики плана: меняется кварталы/фронты/схема ответа — прежние
# планы не подходят.
LAYOUT_PLAN_VERSION = 3
# Замок запроса старше этого — запрос считается потерянным (воркер упал).
LAYOUT_PLAN_LOCK_SECONDS = 600
# Неудавшийся запрос (сеть, модель молчит) повторяется не раньше, чем через.
LAYOUT_PLAN_RETRY_SECONDS = 1800
LAYOUT_PLAN_ATTEMPTS = 2
_SITE_MASSING_PLAN_DIR = Path(os.getenv("SITE_MASSING_PLAN_DIR", "").strip()
                              or Path(__file__).resolve().parent / "data" / "platon_state" / "massing_plan")
_SITE_MASSING_PLAN_RUNNING: set[str] = set()
_SITE_MASSING_PLAN_LOCK = threading.Lock()

SITE_MASSING_PLAN_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["placements", "summary"],
    "properties": {
        "summary": {"type": "string"},
        "placements": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["corpus", "front", "offset_m", "inset_m", "length_m", "depth_m", "ring_m"],
            "properties": {"corpus": {"type": "string"}, "front": {"type": "string"},
                           "offset_m": {"type": "number"}, "inset_m": {"type": "number"},
                           "length_m": {"type": "number"}, "depth_m": {"type": "number"},
                           # Пятно любой формы — только у корпуса с free_shape.
                           "ring_m": {"type": ["array", "null"], "items": {
                               "type": "array", "items": {"type": "number"}}}}}},
    },
}

SITE_MASSING_PLAN_INSTRUCTIONS = (
    "Ты — архитектор-градостроитель. Расставь корпуса на участке так, как это делает город в "
    "документах КРТ. Участок уже разрезан на кварталы, у каждого квартала есть фронты — "
    "стороны, вдоль которых встают секции. Правила: секции жилых очередей стоят по периметру "
    "квартала вдоль фронтов и замыкают двор; где этажей больше — башня (квадратное пятно) на "
    "углу квартала; очереди идут подряд вдоль участка — первая с одного конца, следующие "
    "дальше; школа, детский сад и офисы — отдельными зданиями в кварталах, где участок шире, "
    "корпуса одного здания рядом. Геометрия: корпус — прямоугольник на фронте, от точки "
    "фронта на расстоянии offset_m от его начала вдоль фронта на length_m, внутрь квартала на "
    "depth_m; inset_m — сдвиг от линии фронта внутрь квартала (0 — на самом фронте, больше — "
    "внутренний ряд). length_m × depth_m должно равняться площади пятна корпуса (±1 %); "
    "глубина — depth_m корпуса (жилая секция 18 м, офис 24 м), башни — сторона квадрата. offset_m + length_m не больше длины "
    "фронта; inset_m + depth_m не больше глубины квартала от этого фронта. Между любыми "
    "двумя корпусами не меньше 12 м, у общего угла соседних фронтов отступай от угла не "
    "меньше глубины секции плюс 12 м. Каждый корпус — ровно один раз. В brief есть "
    "расстановка движка, которая проходит проверку; улучши её планировочно или оставь, где "
    "лучше нельзя. Для всех корпусов, кроме free_shape, ring_m — null. Корпус с free_shape=true "
    "— отдельное нежилое здание: его пятно может быть любым многоугольником ring_m (точки "
    "[x, y] в метрах в тех же координатах, что site_inner_contour_m, без повтора первой точки, "
    "не больше 24 точек, без самопересечений), целиком внутри site_inner_contour_m (это участок "
    "с отступом от границ), площадью footprint_sqm ±1 %. Если прямоугольник такой площади на "
    "участке не встаёт, поверни здание по форме участка: повтори его границы, срежь углы, "
    "оставь двор-атриум или проезд — но площадь пятна та же. Для такого корпуса front — пустая "
    "строка, offset_m, inset_m, length_m, depth_m — 0. summary — одна-две фразы для посетителя-непрофессионала о замысле: где "
    "дворы, где башни, как идут очереди. Отвечай только JSON по схеме.")


# Жилой проект (владелец 31.10.2026): Платон не ставит прямоугольники, а
# выбирает один из вариантов посадки движка (`engine/site_massing_variants.py`)
# и объясняет выбор посетителю.
SITE_MASSING_VARIANT_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["variant", "summary"],
    "properties": {"variant": {"type": "string"}, "summary": {"type": "string"}},
}

SITE_MASSING_VARIANT_INSTRUCTIONS = (
    "Ты — архитектор-градостроитель. Движок разобрал участок жилого проекта (части участка, их "
    "размеры и направление по сторонам света) и построил несколько вариантов посадки одних и тех "
    "же домов: квартальная (дома по периметру кварталов с угловыми секциями, двор без машин), "
    "меридиональная (дома рядами с севера на юг), комбинированная и рядами вдоль участка. У "
    "каждого варианта есть числа: сколько домов встало и не встало, самая далёкая от домов точка "
    "участка, доля участка без домов и где этот кусок, доля пятна домов, вытянутых с севера на "
    "юг, сколько домов вытянуты с запада на восток, сколько угловых домов. Выбери вариант, "
    "который лучше как городская застройка: все дома должны встать (вариант, где встало меньше "
    "домов, чем в лучшем, выбирать нельзя); на участке не должно оставаться пустого куска сбоку; "
    "лучше дворы, закрытые домами, и дома с севера на юг; учитывай форму частей участка. "
    "variant — id варианта из списка. summary — одна-две фразы для посетителя-непрофессионала: "
    "почему этот вариант, где дворы и как дома стоят по солнцу. Отвечай только JSON по схеме.")


def massing_variant_check(variants: dict[str, Any], variant: Any) -> str | None:
    """Годится ли выбранный Платоном вариант → None или причина простыми словами."""
    if not isinstance(variant, str) or variant not in variants:
        return f"Платон выбрал вариант «{variant}», которого нет."
    best = min(v["metrics"]["unplaced"] for v in variants.values())
    if variants[variant]["metrics"]["unplaced"] > best:
        return (f"В варианте «{LAYOUT_VARIANT_NAMES.get(variant, variant)}», который выбрал Платон, "
                "встаёт меньше домов, чем в лучшем варианте.")
    return None


def _plan_enabled() -> bool:
    return os.getenv("SITE_MASSING_PLATO", "1").strip().lower() not in {"0", "false", "no", "off"}


def _plan_configured() -> bool:
    """Платон доступен этому серверу: прокси на Render или свой ключ."""
    return bool(_PLATO_AI_URL or os.getenv("OPENAI_API_KEY", "").strip())


def _plan_hash(data: Any) -> str:
    raw = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]


def site_massing_plan_key(corpora: list[dict[str, Any]], site: list[list[list[float]]],
                          setback: float, mode: str = "placements") -> tuple[str, str]:
    """Отпечаток входов плана и отпечаток участка (только контур)."""
    rings = [[[round(p[0], 1), round(p[1], 1)] for p in r] for r in site]
    site_key = _plan_hash({"v": LAYOUT_PLAN_VERSION, "rings": rings})
    key = _plan_hash({"v": LAYOUT_PLAN_VERSION, "mode": mode, "rings": rings,
                      "setback": round(float(setback), 2),
                      "corpora": [[c["id"], round(float(c["area_sqm"]), 1), c["storeys_shown"],
                                   c["phase"], c.get("object")] for c in corpora]})
    return key, site_key


def _plan_path(name: str) -> Path:
    return _SITE_MASSING_PLAN_DIR / f"{name}.json"


def _plan_read(name: str) -> dict[str, Any] | None:
    try:
        data = json.loads(_plan_path(name).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _plan_write(name: str, data: dict[str, Any]) -> None:
    _SITE_MASSING_PLAN_DIR.mkdir(parents=True, exist_ok=True)
    tmp = _plan_path(name).with_suffix(f".{os.getpid()}.{threading.get_ident()}.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, _plan_path(name))


def _plan_take_lock(key: str) -> bool:
    """Замок запроса на диске: второй воркер видит, что план уже готовится."""
    _SITE_MASSING_PLAN_DIR.mkdir(parents=True, exist_ok=True)
    lock = _SITE_MASSING_PLAN_DIR / f"{key}.lock"
    try:
        fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        try:
            age = time.time() - lock.stat().st_mtime
        except OSError:
            return False
        if age < LAYOUT_PLAN_LOCK_SECONDS:
            return False
        lock.unlink(missing_ok=True)
        return _plan_take_lock(key)
    os.close(fd)
    return True


def _plan_pending(key: str) -> bool:
    lock = _SITE_MASSING_PLAN_DIR / f"{key}.lock"
    try:
        return time.time() - lock.stat().st_mtime < LAYOUT_PLAN_LOCK_SECONDS
    except OSError:
        return False


def site_massing_plan_status(key: str) -> dict[str, Any]:
    """Состояние плана по отпечатку — для страницы, которая ждёт план."""
    rec = _plan_read(key) or {}
    status = rec.get("status") or ("pending" if _plan_pending(key) else "none")
    return {"key": key, "status": status}


def _plan_brief(corpora: list[dict[str, Any]], blocks: list[dict[str, Any]],
                site: list[list[list[float]]] | None = None) -> dict[str, Any]:
    """Что получает Платон: кварталы с фронтами, корпуса и расстановка движка."""
    kinds = {"school": "школа", "kindergarten": "детский сад"}
    out_blocks = []
    for b in blocks:
        fronts = b["fronts"]
        out_blocks.append({
            "id": b["id"], "order_along_site": b["order"], "length_m": b["length_m"],
            "width_m": b["width_m"], "area_sqm": b["area_sqm"],
            "fronts": [{"id": f["id"], "length_m": f["length_m"], "depth_room_m": f["room_m"],
                        "side": "граница участка" if f["side"] == "boundary" else "внутренний проезд",
                        "next_front": fronts[(i + 1) % len(fronts)]["id"]}
                       for i, f in enumerate(fronts)]})
    out_corpora = [{"id": c["id"], "name": c["label"],
                    "kind": ("жилая очередь" if c["phase"] > 0 else
                             kinds.get(str(c.get("object") or ""), str(c.get("object_kind") or "здание"))),
                    "phase": c["phase"], "footprint_sqm": round(float(c["area_sqm"]), 1),
                    "storeys": c["storeys_shown"], "free_shape": bool(c.get("free_shape")),
                    "depth_m": float(c.get("depth_m") or LAYOUT_CORPUS_DEPTH_M),
                    "length_at_depth_m": round(float(c["area_sqm"])
                                               / float(c.get("depth_m") or LAYOUT_CORPUS_DEPTH_M), 1)}
                   for c in corpora]
    return {"blocks": out_blocks, "corpora": out_corpora,
            "site_inner_contour_m": [[[round(p[0], 1), round(p[1], 1)] for p in r]
                                     for r in site or []],
            "engine_layout": [c["place"] for c in corpora if c.get("place")],
            "rules": {"section_depth_m": LAYOUT_CORPUS_DEPTH_M, "min_gap_m": LAYOUT_GAP_IN_ROW_M}}


def _plan_job(key: str, site_key: str, corpora: list[dict[str, Any]],
              blocks: list[dict[str, Any]], site: list[list[list[float]]]) -> None:
    """Фоновая нить: запрос Платону, проверка движком, запись плана."""
    started = time.time()
    record: dict[str, Any] = {"key": key, "site_key": site_key, "version": LAYOUT_PLAN_VERSION}
    try:
        brief = _plan_brief(corpora, blocks, site)
        model = (os.getenv("OPENAI_MASSING_MODEL") or os.getenv("OPENAI_AGENT_MODEL", "gpt-5.6")).strip()
        record["model"] = model
        message = json.dumps(brief, ensure_ascii=False)
        reason = None
        for attempt in range(LAYOUT_PLAN_ATTEMPTS):
            payload = {"model": model, "instructions": SITE_MASSING_PLAN_INSTRUCTIONS,
                       "input": [{"role": "user", "content": message}],
                       "text": {"format": {"type": "json_schema", "name": "site_massing_plan",
                                           "strict": True, "schema": SITE_MASSING_PLAN_SCHEMA}},
                       "max_output_tokens": 12000, "store": False}
            text = _extract_openai_text(_openai_responses_request(payload, 240.0))
            try:
                answer = json.loads(text)
            except ValueError:
                answer = None
            if not isinstance(answer, dict):
                reason = "Ответ Платона — не JSON по схеме."
            else:
                trial = copy.deepcopy(corpora)
                reason = massing_place_plan(trial, blocks, answer.get("placements")) \
                    or massing_check(trial, site)
                if reason is None:
                    record.update(status="ready", placements=answer["placements"],
                                  summary=str(answer.get("summary") or "")[:400],
                                  attempts=attempt + 1)
                    break
            message = (json.dumps(brief, ensure_ascii=False)
                       + "\n\nПрошлый план не прошёл проверку движка: " + reason
                       + " Исправь и пришли план целиком.")
        if record.get("status") != "ready":
            record.update(status="rejected", reason=reason, attempts=LAYOUT_PLAN_ATTEMPTS)
    except HTTPException as exc:
        record.update(status="failed", reason=str(exc.detail)[:300])
    except Exception as exc:
        logging.exception("site massing plan failed")
        record.update(status="failed", reason=f"{type(exc).__name__}: {exc}"[:300])
    record["seconds"] = round(time.time() - started, 1)
    record["created_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    try:
        _plan_write(key, record)
        if record["status"] in ("ready", "rejected"):
            _plan_write(f"site-{site_key}", {"key": key})
    finally:
        (_SITE_MASSING_PLAN_DIR / f"{key}.lock").unlink(missing_ok=True)
        with _SITE_MASSING_PLAN_LOCK:
            _SITE_MASSING_PLAN_RUNNING.discard(key)


def _plan_job_variants(key: str, site_key: str, brief: dict[str, Any],
                       variants: dict[str, Any]) -> None:
    """Фоновая нить жилого проекта: Платон выбирает вариант посадки."""
    started = time.time()
    record: dict[str, Any] = {"key": key, "site_key": site_key, "version": LAYOUT_PLAN_VERSION,
                              "mode": "variants"}
    try:
        model = (os.getenv("OPENAI_MASSING_MODEL") or os.getenv("OPENAI_AGENT_MODEL", "gpt-5.6")).strip()
        record["model"] = model
        message = json.dumps(brief, ensure_ascii=False)
        reason = None
        for attempt in range(LAYOUT_PLAN_ATTEMPTS):
            payload = {"model": model, "instructions": SITE_MASSING_VARIANT_INSTRUCTIONS,
                       "input": [{"role": "user", "content": message}],
                       "text": {"format": {"type": "json_schema", "name": "site_massing_variant",
                                           "strict": True, "schema": SITE_MASSING_VARIANT_SCHEMA}},
                       "max_output_tokens": 2000, "store": False}
            text = _extract_openai_text(_openai_responses_request(payload, 240.0))
            try:
                answer = json.loads(text)
            except ValueError:
                answer = None
            if not isinstance(answer, dict):
                reason = "Ответ Платона — не JSON по схеме."
            else:
                reason = massing_variant_check(variants, answer.get("variant"))
                if reason is None:
                    record.update(status="ready", variant=answer["variant"],
                                  summary=str(answer.get("summary") or "")[:400],
                                  attempts=attempt + 1)
                    break
            message = (json.dumps(brief, ensure_ascii=False)
                       + "\n\nПрошлый выбор не прошёл проверку движка: " + reason
                       + " Выбери заново.")
        if record.get("status") != "ready":
            record.update(status="rejected", reason=reason, attempts=LAYOUT_PLAN_ATTEMPTS)
    except HTTPException as exc:
        record.update(status="failed", reason=str(exc.detail)[:300])
    except Exception as exc:
        logging.exception("site massing variant choice failed")
        record.update(status="failed", reason=f"{type(exc).__name__}: {exc}"[:300])
    record["seconds"] = round(time.time() - started, 1)
    record["created_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    try:
        _plan_write(key, record)
        if record["status"] in ("ready", "rejected"):
            _plan_write(f"site-{site_key}", {"key": key})
    finally:
        (_SITE_MASSING_PLAN_DIR / f"{key}.lock").unlink(missing_ok=True)
        with _SITE_MASSING_PLAN_LOCK:
            _SITE_MASSING_PLAN_RUNNING.discard(key)


def site_massing_plan_lookup(x: dict[str, Any], corpora: list[dict[str, Any]],
                             site: list[list[list[float]]], setback: float,
                             blocks: list[dict[str, Any]], shape_origin: str,
                             variants: dict[str, Any] | None = None,
                             analysis: dict[str, Any] | None = None) -> dict[str, Any]:
    """План для этих входов → {status, key, …}; нет плана — запускает фоновый
    запрос (если Платон доступен) и сразу отвечает «готовится».

    Состояния: `ready` (план есть, проверяет его вызывающий), `pending`,
    `rejected` и `failed` (с причиной), `unavailable` (Платон не подключён),
    `off` (выключено переменной `SITE_MASSING_PLATO`), `square` (контура нет —
    расставлять не на чем). `stale` — у участка был план для других входов.

    `variants` — жилой проект: Платон выбирает вариант посадки движка, а не
    ставит корпуса сам (план с `mode` = `variants`)."""
    if shape_origin != "contour" or not blocks or not corpora:
        return {"status": "square"}
    mode = "variants" if variants else "placements"
    key, site_key = site_massing_plan_key(corpora, site, setback, mode)
    rec = _plan_read(key)
    if rec and rec.get("status") in ("ready", "rejected"):
        return {**rec, "key": key, "mode": mode}
    pointer = _plan_read(f"site-{site_key}") or {}
    stale = bool(pointer.get("key")) and pointer.get("key") != key
    base = {"key": key, "stale": stale}
    if rec and rec.get("status") == "failed":
        try:
            age = time.time() - _plan_path(key).stat().st_mtime
        except OSError:
            age = 0.0
        if age < LAYOUT_PLAN_RETRY_SECONDS:
            return {**rec, **base}
    if not _plan_enabled():
        return {**base, "status": "off"}
    if not _plan_configured():
        return {**base, "status": "unavailable"}
    with _SITE_MASSING_PLAN_LOCK:
        running = key in _SITE_MASSING_PLAN_RUNNING
        if not running and _plan_take_lock(key):
            _SITE_MASSING_PLAN_RUNNING.add(key)
            if variants:
                brief = massing_variants_brief(variants, analysis or {}, corpora)
                metrics = {k: {"metrics": copy.deepcopy(v["metrics"])} for k, v in variants.items()}
                threading.Thread(target=_plan_job_variants, name=f"massing-plan-{key}", daemon=True,
                                 args=(key, site_key, brief, metrics)).start()
                return {**base, "status": "pending", "mode": mode}
            # Нити — копии: расчёт продолжает работать со своими корпусами.
            snapshot = [{k: copy.deepcopy(v) for k, v in c.items()
                         if k in ("id", "label", "phase", "object", "object_kind", "area_sqm",
                                  "storeys_shown", "place", "depth_m", "free_shape")}
                        for c in corpora]
            threading.Thread(target=_plan_job, name=f"massing-plan-{key}", daemon=True,
                             args=(key, site_key, snapshot, copy.deepcopy(blocks),
                                   copy.deepcopy(site))).start()
    return {**base, "status": "pending"}


def site_massing_plan_note(plan: dict[str, Any], grid: bool = False) -> dict[str, Any]:
    """Состояние плана для схемы: происхождение расстановки и фраза для посетителя."""
    status = plan.get("status") or "square"
    gap = _fmt_ru(LAYOUT_GAP_IN_ROW_M)
    # Посетителю — только то, что нарисовано (владелец 25.10.2026): как шла
    # расстановка, кто её предлагал и почему план не принят, — внутренняя
    # кухня; причина остаётся в ответе (`reason`, `status`) для команды.
    note = ""
    origin = "engine"
    if status == "ready":
        note = ("Расстановку корпусов предложил помощник Платон: все корпуса стоят внутри "
                f"участка с отступом от границ, не ближе {gap} м друг к другу, пятна и этажность — "
                "те же, что в расчёте.")
        if plan.get("summary"):
            note += f" Замысел: {str(plan['summary']).strip()}"
        origin = "plato"
    note = note.replace("..", ".")
    if status == "ready" and plan.get("mode") == "variants":
        name = LAYOUT_VARIANT_NAMES.get(str(plan.get("variant")), str(plan.get("variant")))
        note = f"Вариант посадки «{name}» выбрал помощник Платон."
        if plan.get("summary"):
            note += f" {str(plan['summary']).strip()}"
    out = {k: v for k, v in plan.items()
           if k in ("status", "key", "stale", "reason", "summary", "mode")}
    out.update(status=status, origin=origin, note=note[:1].upper() + note[1:] if note else "")
    return out


@app.get("/site-massing/plan/{key}")
def site_massing_plan_route(key: str) -> dict[str, Any]:
    """Готов ли план расстановки: страница спрашивает, пока он готовится, и
    пересчитывает схему, когда ответ пришёл. Отдаёт только состояние."""
    if not re.fullmatch(r"[0-9a-f]{20}", key or ""):
        raise HTTPException(status_code=400, detail="Неверный номер плана расстановки.")
    return site_massing_plan_status(key)
