"""Платон Сергеевич: локальные сценарии кнопок и маршруты /agent/*.

Локальные ответы кнопок (_local_*), /agent/status, запуск разговора
_plato_chat_launch, /agent/selftest, /agent/chat, /agent/document,
/agent/document/answer (вопросы по документу по одному), /agent/result.

Не самостоятельный модуль. `main_legacy.py` выполняет этот файл в своём
пространстве имён на том месте, где этот код стоял раньше
(`_engine_part("agent_routes")`), поэтому здесь видны все имена движка,
а подмены `core.<имя>` из `main.py` и тестов действуют и на этот код.
Отдельно не импортировать: второй импорт поднял бы вторую копию движка.
"""
# ruff: noqa

# --- локальные сценарии кнопок ---------------------------------------------

def _agent_num(value: Any, digits: int = 1) -> str:
    text = f"{float(value or 0):,.{digits}f}"
    return text.replace(",", " ").replace(".", ",")


def _agent_mln(value: Any) -> str:
    return f"{_agent_num(value, 1)} млн ₽"


def _agent_x(value: Any) -> str:
    return f"{_agent_num(value, 3)}x"


def _agent_scope_of(bundle: dict[str, Any]) -> str:
    """Охват суждения по умолчанию — весь проект.

    Банк смотрит лимит в целом, и ради этого заведены режимы переноса долга
    между очередями (владелец, 04.09.2026: «банк смотрит лимит в целом, для
    этого мы и вводили режимы перевода долга между очередями»). Подбор по
    слабейшей очереди отказывал «ни при какой цене» проекту с LLCR 1,23x.
    Слабейшая очередь называется рядом, а не судит; по ней считают только
    по явной просьбе (`scope=weakest_phase`).
    """
    return "consolidated"


def _local_expense_structure(req: AgentChatRequest, bundle: dict[str, Any]) -> str:
    data = _tool_explain_metric(req, bundle, "expense_structure", "consolidated")
    totals = data.get("totals") or {}
    lines = [f"**Структура расходов · {data.get('scope')}**", ""]
    for item in data.get("expense_structure") or []:
        lines.append(f"- {item.get('label')}: **{_agent_mln(item.get('value_mln'))}** "
                     f"({_agent_num(item.get('share_pct'), 1)}%)")
    lines += [
        "",
        f"Полные расходы: **{_agent_mln(totals.get('total_expenses_mln'))}**, из них "
        f"CAPEX {_agent_mln(totals.get('capex_mln'))}, "
        f"коммерческие {_agent_mln(totals.get('commercial_costs_mln'))}, "
        f"проценты и комиссии {_agent_mln(totals.get('financing_cost_mln'))}, "
        f"налог {_agent_mln(totals.get('profit_tax_mln'))}.",
    ]
    return "\n".join(lines)


def _local_llcr_breakdown(req: AgentChatRequest, bundle: dict[str, Any]) -> str:
    data = _tool_explain_metric(req, bundle, "llcr", _agent_scope_of(bundle))
    numerator = data.get("numerator_components") or {}
    denominator = data.get("denominator_components") or {}
    value = float(data.get("value_x") or 0)
    target = float(data.get("target_x") or 0)
    lines = [
        f"**LLCR = {_agent_x(value)}** · {data.get('scope')} · банковская цель {_agent_x(target)}",
        "",
        str(data.get("formula") or ""),
        "",
        f"**Числитель — {_agent_mln(data.get('numerator_mln'))}:**",
        f"- выручка проекта: {_agent_mln(numerator.get('project_revenue_mln'))}",
        f"- минус коммерческие расходы: {_agent_mln(numerator.get('minus_commercial_costs_mln'))}",
        f"- минус налог на прибыль: {_agent_mln(numerator.get('minus_profit_tax_mln'))}",
        f"- минус CAPEX: {_agent_mln(numerator.get('minus_capex_mln'))}",
        f"- плюс выборка ПФ: {_agent_mln(numerator.get('plus_pf_draw_mln'))}",
        "",
        f"**Знаменатель — {_agent_mln(data.get('denominator_mln'))}:**",
        f"- выборка ПФ: {_agent_mln(denominator.get('pf_draw_mln'))}",
        f"- проценты и комиссии: {_agent_mln(denominator.get('actual_financing_cost_mln'))}",
    ]
    if value < target:
        lines += ["", f"До цели не хватает {_agent_x(target - value)}: числитель должен вырасти "
                      "(выручка) или знаменатель снизиться (долг и его стоимость)."]
    phases = data.get("phase_llcr") or []
    if phases:
        lines += ["", "**По очередям:** " + ", ".join(
            # Ключ у строки очереди — `name` (`_phase_llcr`), и другого нет.
            # Спрошенный `phase` давал «None — 1,260x» четыре раза подряд: имя
            # очереди — это и есть ответ на «какая слабее», а None не отвечает
            # ни на что и выглядит поломкой расчёта, а не подписи.
            f"{p.get('name') or '—'} — {_agent_x(p.get('llcr_x'))}" for p in phases)]
    return "\n".join(lines)


def _local_goal_seek(req: AgentChatRequest, bundle: dict[str, Any], variable: str) -> str:
    data = _tool_goal_seek(
        req, bundle, variable, "llcr", _AGENT_BANK_LLCR_TARGET,
        "at_least", "maximum_variable", _agent_scope_of(bundle), None, None,
    )
    if not data.get("available"):
        reason = str(data.get("reason") or "причина не указана").rstrip(".")
        return f"Подбор параметра недоступен: {reason}."
    current = data.get("current") or {}
    solution = data.get("solution") or {}
    label = str(data.get("variable_label") or variable)
    lines = [
        f"**{label}: максимум {_agent_num(solution.get('variable'), 1)} при LLCR ≥ "
        f"{_agent_x(data.get('target_value'))}** · {data.get('scope_label')}",
        "",
        f"- сейчас: {_agent_num(current.get('variable'), 1)} → LLCR {_agent_x(current.get('metric'))}",
        f"- на пределе: {_agent_num(solution.get('variable'), 1)} → LLCR {_agent_x(solution.get('metric'))}",
        f"- запас: {_agent_num(solution.get('change_abs'), 1)}"
        + (f" ({_agent_num(solution.get('change_pct'), 1)}%)" if solution.get("change_pct") is not None else ""),
    ]
    if data.get("threshold_beyond_bound"):
        lines += ["", "Порог упёрся в границу поиска — реальный предел может лежать дальше."]
    if data.get("non_monotonic"):
        ranges = ", ".join(f"{_agent_num(a, 1)}–{_agent_num(b, 1)}" for a, b in data.get("feasible_ranges") or [])
        lines += ["", f"LLCR меняется неровно: порог держится на нескольких отрезках ({ranges}); "
                      "показан наибольший."]
    lines += ["", "Подбор выполнен полным пересчётом модели DevelopAid; текущая модель не изменена."]
    return "\n".join(lines)


def _local_max_purchase_price(req: AgentChatRequest, bundle: dict[str, Any]) -> str:
    return _local_goal_seek(req, bundle, "purchase_price_mln")


def _local_max_construction_cost(req: AgentChatRequest, bundle: dict[str, Any]) -> str:
    return _local_goal_seek(req, bundle, "main_construction_cost_th_per_sqm")


def _local_find_anomalies(req: AgentChatRequest, bundle: dict[str, Any]) -> str:
    data = _tool_find_anomalies(req, bundle, _agent_scope_of(bundle))
    anomalies = data.get("anomalies") or []
    if not anomalies:
        return ("**Существенных аномалий не найдено.** Проверены ТЭП, выручка, CAPEX, "
                "маржа, очереди и финансирование по текущей модели.")
    order = {"high": 0, "medium": 1, "low": 2}
    anomalies = sorted(anomalies, key=lambda a: order.get(str(a.get("severity")), 3))
    severity_mark = {"high": "существенно", "medium": "заметно", "low": "на контроль"}
    lines = [f"**Найдено отклонений: {len(anomalies)}**", ""]
    for item in anomalies:
        mark = severity_mark.get(str(item.get("severity")), str(item.get("severity")))
        lines.append(f"- **[{mark}]** {item.get('message')}")
    return "\n".join(lines)


def _local_phase_recovery(req: AgentChatRequest, bundle: dict[str, Any]) -> str:
    data = _tool_phase_recovery_options(req, bundle, _AGENT_BANK_LLCR_TARGET)
    if not data.get("available"):
        summary = (bundle.get("consolidated") or {}).get("summary") or {}
        return (f"Проект одноочередный, оздоравливать отдельную очередь не требуется. "
                f"LLCR проекта — {_agent_x(summary.get('llcr'))} при цели "
                f"{_agent_x(_AGENT_BANK_LLCR_TARGET)}.")
    lines = [
        f"**Слабейшая очередь — {data.get('weakest_phase')}: LLCR "
        f"{_agent_x(data.get('baseline_min_llcr_x'))} при цели {_agent_x(data.get('target_llcr_x'))}**",
        "",
        "Варианты, посчитанные полным пересчётом (лучшие первыми):",
        "",
    ]
    for index, option in enumerate((data.get("ranked_options") or [])[:5], start=1):
        achieved = "достигает цели" if option.get("achieves_target") else "цели не достигает"
        lines.append(
            f"{index}. **{option.get('name')}** — минимальный LLCR "
            f"{_agent_x(option.get('min_llcr_x'))} ({achieved}), прибыль "
            f"{'+' if float(option.get('net_profit_change_mln') or 0) >= 0 else ''}"
            f"{_agent_num(option.get('net_profit_change_mln'), 1)} млн ₽ к базе. "
            f"{option.get('feasibility') or ''}"
        )
    fallback = data.get("fallback_thresholds") or {}
    for key, title in (("max_purchase_price", "Предельная цена входа"),
                       ("max_construction_cost", "Предельная ставка строительства")):
        item = fallback.get(key) or {}
        if item.get("available"):
            solution = item.get("solution") or {}
            lines.append(f"- {title}: {_agent_num(solution.get('variable'), 1)} "
                         f"(LLCR {_agent_x(solution.get('metric'))}).")
    return "\n".join(lines)


def _local_purchase_evaluation(req: AgentChatRequest, bundle: dict[str, Any]) -> str:
    offer = n(req.inputs, "purchase_price_mln", 0.0)
    data = _tool_evaluate_purchase_offer(req, bundle, offer, _AGENT_BANK_LLCR_TARGET)
    comparison = data.get("comparison") or {}
    at_offer = data.get("at_offer") or {}
    lines = [
        f"**Оценка цены покупки {_agent_mln(offer)}** · цель LLCR {_agent_x(data.get('target_llcr_x'))}",
        "",
        f"- LLCR при этой цене: {_agent_x(at_offer.get('min_llcr_x'))}",
    ]
    if comparison.get("ceiling_mln") is not None:
        lines.append(f"- расчётный потолок цены: {_agent_mln(comparison.get('ceiling_mln'))}")
        above = float(comparison.get("offer_above_ceiling_mln") or 0)
        if above > 0:
            lines.append(f"- цена выше потолка на {_agent_mln(above)} "
                         f"({_agent_num(comparison.get('offer_above_ceiling_pct'), 1)}%)")
        else:
            lines.append(f"- запас до потолка: {_agent_mln(-above)}")
    decision = data.get("decision")
    if decision:
        lines += ["", str(decision)]
    holds = data.get("if_seller_holds_price") or {}
    price_needed = (holds.get("required_apartment_start_price") or {}).get("solution") or {}
    cost_allowed = (holds.get("max_construction_cost") or {}).get("solution") or {}
    if price_needed or cost_allowed:
        lines += ["", "**Если продавец не двигается:**"]
        if price_needed:
            lines.append(f"- нужна стартовая цена квартир от {_agent_num(price_needed.get('variable'), 1)} тыс. ₽/м²")
        if cost_allowed:
            lines.append(f"- либо себестоимость строительства не выше {_agent_num(cost_allowed.get('variable'), 1)} тыс. ₽/м²")
    return "\n".join(lines)


# Сценарий кнопки -> подпись стадии и локальный обработчик. Ответ собирается
# движком и форматируется детерминированно; модель не вызывается вовсе.
_AGENT_LOCAL_SCENARIOS: dict[str, tuple[str, Any]] = {
    "expense_structure": ("Структура расходов", _local_expense_structure),
    "llcr_breakdown": ("Разбор LLCR", _local_llcr_breakdown),
    "max_purchase_price": ("Подбор предельной цены покупки", _local_max_purchase_price),
    "max_construction_cost": ("Подбор предельной себестоимости", _local_max_construction_cost),
    "anomalies": ("Поиск аномалий", _local_find_anomalies),
    "phase_recovery": ("Оздоровление слабой очереди", _local_phase_recovery),
    "purchase_evaluation": ("Оценка цены покупки", _local_purchase_evaluation),
}

_AGENT_TOOL_LABELS = {
    "explain_metric": "разбор показателя",
    "trace_metric": "трассировка показателя",
    "goal_seek": "подбор параметра",
    "simulate_change": "сценарий с изменёнными вводными",
    "normalize_market_benchmark": "нормализация бенчмарка",
    "prepare_model_patch": "подготовка изменения вводных",
    "find_anomalies": "поиск аномалий",
    "evaluate_purchase_offer": "оценка цены покупки",
    "diagnose_project_logic": "диагностика логики проекта",
    "phase_recovery_options": "варианты оздоровления очереди",
    "get_methodology": "справка по методике",
    "get_user_guide": "читает руководство пользователя",
    "where_to_edit": "ищет поле на экране",
    "search_project_knowledge": "читает записи проекта",
    "calculate_mpt_benefit": "считает льготу МПТ по 1874-ПП",
}


@app.get("/agent/status")
def agent_status() -> dict[str, Any]:
    return {
        # Ключа на этом сервере может не быть вовсе: думает Платон Сергеевич
        # через сервис, адрес которого задан в PLATO_AI_URL.
        "enabled": bool(
            (_PLATO_AI_URL and _PLATO_AI_PROXY_SECRET)
            or os.getenv("OPENAI_API_KEY", "").strip()
        ),
        "thinks_via": "внешний сервис" if _PLATO_AI_URL else "этот сервер",
        # Маршрут виден снаружи: хостинг закрыт, и лезть в журнал за строкой
        # «Platon route» с чужой машины нечем.
        "route": _plato_route(),
        "proxy_configured": bool(_PLATO_AI_URL and _PLATO_AI_PROXY_SECRET),
        # Обратная схема: ядро не зовёт сервис модели, а ждёт, пока заберут.
        "pull_queue": {
            "enabled": _PLATO_PULL_ENABLED,
            "waiting_jobs": len(list(_PLATO_STAGE_DIR.glob("job_*.json")))
                            if _PLATO_STAGE_DIR.exists() else 0,
            "worker_here": bool(_PLATO_PULL_URL and not _PLATO_AI_URL),
            # Сколько назад за очередью приходил сервис модели: единственный
            # факт, отличающий «разбор не запущен» от «Render заснул».
            "puller_seen_ago_seconds": _plato_puller_seen_ago(),
            "diagnosis": _plato_puller_diagnosis() if _PLATO_PULL_ENABLED else "",
        },
        # Пинг против засыпания сервиса модели: видно, живёт ли он и когда
        # последний раз отзывался, — иначе «Ошибка AI (504)» объяснять нечем.
        "keepalive": {
            "enabled": bool(_PLATO_KEEPALIVE["enabled"]),
            "every_minutes": _PLATO_KEEPALIVE_MINUTES if _PLATO_AI_URL else 0.0,
            "url": _plato_keepalive_url(),
            "last_ok": _PLATO_KEEPALIVE["last_ok"],
            "last_error": _PLATO_KEEPALIVE["last_error"],
        },
        "model": os.getenv("OPENAI_AGENT_MODEL", "gpt-5.6"),
        "reasoning_effort": _agent_reasoning_effort(
            os.getenv("OPENAI_AGENT_MODEL", "gpt-5.6").strip() or "gpt-5.6") or "default",
        "agent_name": "Платон Сергеевич Федоскин",
        "mode": "reasoning_agent_with_confirmed_input_patches",
        "bank_llcr_target": _AGENT_BANK_LLCR_TARGET,
        "tools": [t["name"] for t in _AGENT_TOOLS],
        "methodology_rules": len(_DevelopAid_METHODOLOGY),
    }


# Предел свободного вопроса человека и предел машинного задания — разные
# величины, и объявлены они рядом, чтобы второй не считался копией первого.
_PLATO_QUESTION_LIMIT = 4000
_PLATO_MESSAGE_LIMITS = {
    # Разбор присланного документа: шапка задания плюс сам документ.
    "document_intake": document_intake.DOCUMENT_TEXT_BUDGET + 8000,
}


def _plato_chat_launch(
    req: AgentChatRequest, request: Request,
) -> tuple[str, threading.Event, dict[str, Any]]:
    """Проверки, кэш и запуск работы фоном.

    Возвращает номер запуска, признак завершения и общий с работой словарь
    результата. Ждать завершения — дело зовущего: у окна на это двадцать
    секунд, у бота столько, сколько нужно.
    """
    _agent_rate_limit(request)
    message = str(req.message or "").strip()
    if not message:
        raise HTTPException(status_code=400, detail="Введите вопрос.")
    # Предел — у ЧЕЛОВЕЧЕСКОГО вопроса; машинное задание с документом им мерить
    # нельзя. Одна шапка задания разбора занимает 2 516 знаков, и на документ
    # от четырёх тысяч оставалось 1 484 — меньше страницы делового PDF: тизер
    # отклонялся всегда, а человек читал «Вопрос слишком длинный», то есть
    # претензию к себе (владелец, 04.09.2026). Бюджет считают на всё сообщение,
    # и у сообщения, собранного нами, он свой.
    limit = _PLATO_MESSAGE_LIMITS.get(
        str(req.scenario or "").strip(), _PLATO_QUESTION_LIMIT)
    if len(message) > limit:
        raise HTTPException(
            status_code=400,
            detail=f"Вопрос слишком длинный: {len(message)} знаков при пределе {limit}.")

    started = time.monotonic()
    trace_id = str(req.trace_id or "").strip().lower()
    if not _TRACE_ID_RE.fullmatch(trace_id):
        trace_id = os.urandom(6).hex()
    scenario = str(req.scenario or "").strip()
    if scenario and scenario not in _AGENT_LOCAL_SCENARIOS:
        scenario = ""
    _plato_stage_cleanup()

    # Кэш смотрится до пересчёта модели: повторный вопрос по тем же вводным
    # не должен стоить ни пересчёта, ни похода в модель.
    cache_key = _plato_answer_key(req, scenario)
    outcome: dict[str, Any] = {}
    done = threading.Event()
    cached = _plato_answer_get(cache_key)
    if cached is not None:
        _plato_trace_write(trace_id, "done", "Ответ найден в кэше")
        _PLATON_LOG.info("Platon [%s] cache hit (%.2fs)", trace_id, time.monotonic() - started)
        outcome["result"] = cached
        outcome["cached"] = True
        done.set()
        return trace_id, done, outcome

    def _remember_failure(exc: Exception) -> None:
        """Неудача тоже кладётся под номер запуска.

        Иначе окно, потерявшее соединение, опрашивает результат до самого конца
        и не узнаёт, что работа давно упала: «забираю готовый ответ» висит
        пять минут вместо честной причины.
        """
        detail = getattr(exc, "detail", None) or str(exc)
        _plato_answer_put("run" + trace_id, {
            "answer": "", "error": str(detail)[:500],
            "model": "", "source": "error", "response_id": None,
            "tools_used": [], "proposals": [],
        })

    def _work() -> dict[str, Any]:
        _plato_trace_write(trace_id, "model", "Пересчитываю модель DevelopAid")
        try:
            bundle = _run_authoritative_model(req.inputs, req.tep, req.rates, req.phasing)
        except KeyError as exc:
            # Неполные вводные — ответ человеку, а не пятисотка. Модель строится
            # по всему набору полей, и отсутствие одного роняло вызов с голым
            # `KeyError` в лог: снаружи это выглядело поломкой сервиса, а не
            # нехваткой данных. Поле называется — иначе искать его негде.
            raise HTTPException(
                status_code=422,
                detail=(f"Не хватает вводных для расчёта модели: нет поля {exc}. "
                        "Передайте полный набор вводных или умолчания движка."),
            ) from exc

        if scenario:
            stage_label, handler = _AGENT_LOCAL_SCENARIOS[scenario]
            _plato_trace_write(trace_id, "local", f"Считаю движком: {stage_label.lower()}")
            result = {
                "answer": handler(req, bundle),
                "model": "developaid-engine",
                "source": "local",
                "response_id": None,
                "tools_used": [{"name": scenario, "arguments": {}}],
                "proposals": [],
            }
            _PLATON_LOG.info("Platon [%s] local scenario %s (%.2fs)",
                             trace_id, scenario, time.monotonic() - started)
        else:
            result = _call_openai_tool_agent(req, bundle, trace_id=trace_id)
            _PLATON_LOG.info("Platon [%s] llm answer, %d tool calls (%.2fs)",
                             trace_id, len(result.get("tools_used") or []),
                             time.monotonic() - started)

        _plato_answer_put(cache_key, result)
        # Ответ кладётся ещё и под номер запуска: соединение до окна короче
        # работы, и забирают его отдельным запросом. На диск — потому что
        # воркеров два, и опрос попадёт в другой.
        _plato_answer_put("run" + trace_id, result)
        _plato_trace_write(trace_id, "done", "Готово")
        _PLATON_LOG.info(
            "Platon [%s] done route=%s model=%s kind=%s %.2fs",
            trace_id, _plato_route(), result.get("model") or "-",
            "scenario:" + scenario if scenario else "free", time.monotonic() - started)
        return result

    def _worker() -> None:
        try:
            outcome["result"] = _work()
        except Exception as exc:
            _remember_failure(exc)
            _plato_trace_write(trace_id, "done", "Не получилось")
            outcome["error"] = exc
        finally:
            done.set()

    # Работа идёт фоном, а не внутри запроса. Прежде запрос держали до конца, и
    # это упиралось в чужие сроки на всём пути: nginx рвёт на шестидесяти
    # секундах, мобильный Safari на своём, Render — на своём. Тяжёлый вопрос
    # гоняет модель с инструментами по нескольку раундов и не укладывается ни в
    # один из них: работа доходила до конца, а человек видел «Load failed» или
    # вечное «думает». Теперь длительность работы не упирается ни в чей таймаут.
    threading.Thread(target=_worker, name="platon-" + trace_id, daemon=True).start()
    return trace_id, done, outcome


def _plato_chat_result(trace_id: str, outcome: dict[str, Any]) -> dict[str, Any]:
    if outcome.get("error") is not None:
        raise outcome["error"]
    return {**outcome["result"], "cached": bool(outcome.get("cached")), "trace_id": trace_id}


_PLATO_SELFTEST = {"at": 0.0, "result": None}
_PLATO_SELFTEST_INTERVAL = 20.0
_PLATO_SELFTEST_BUDGET = max(15.0, _env_float("PLATO_SELFTEST_SECONDS", 60.0))


@app.get("/agent/selftest")
def agent_selftest(request: Request) -> dict[str, Any]:
    """Проходит цепочку до модели и называет, где она встала.

    «Платон не отвечает» разбиралось скриншотами и логом закрытого хостинга, а
    вопрос всегда один: доходит ли вызов до модели и сколько это занимает.
    Проверка идёт тем же маршрутом, что и настоящий вопрос, — с тем же секретом,
    билетом и опросом, — но коротким сроком и запросом на один токен: она
    отвечает «дошло или нет», а не решает задачу.
    """
    _agent_rate_limit(request)
    now = time.monotonic()
    if _PLATO_SELFTEST["result"] and now - float(_PLATO_SELFTEST["at"]) < _PLATO_SELFTEST_INTERVAL:
        # Проверка стоит токенов: частым обновлением страницы её не гоняют.
        return {**_PLATO_SELFTEST["result"], "cached": True}

    model = os.getenv("OPENAI_AGENT_MODEL", "gpt-5.6").strip() or "gpt-5.6"
    started = time.monotonic()
    outcome: dict[str, Any] = {
        "route": _plato_route(),
        "model": model,
        "budget_seconds": int(_PLATO_SELFTEST_BUDGET),
        "keepalive": {
            "last_ok": _PLATO_KEEPALIVE["last_ok"],
            "last_error": _PLATO_KEEPALIVE["last_error"],
            "url": _plato_keepalive_url(),
        },
    }
    try:
        response = _openai_responses_request({
            "model": model,
            "instructions": "Ответь одним словом: ок.",
            "input": [{"role": "user", "content": "ок?"}],
            "max_output_tokens": 16,
            "store": False,
        }, budget_seconds=_PLATO_SELFTEST_BUDGET)
        outcome.update(ok=True, seconds=round(time.monotonic() - started, 1),
                       response_id=str(response.get("id") or ""))
    except HTTPException as exc:
        outcome.update(ok=False, seconds=round(time.monotonic() - started, 1),
                       status=exc.status_code, error=str(exc.detail)[:500])
    except Exception as exc:
        outcome.update(ok=False, seconds=round(time.monotonic() - started, 1),
                       status=502, error=f"{type(exc).__name__}: {str(exc)[:400]}")
    outcome["verdict"] = _plato_selftest_verdict(outcome)
    _PLATO_SELFTEST.update(at=time.monotonic(), result=outcome)
    _PLATON_LOG.info("Platon selftest route=%s ok=%s %.1fs %s",
                     outcome["route"], outcome.get("ok"), outcome.get("seconds", 0),
                     outcome.get("error", ""))
    return {**outcome, "cached": False}


def _plato_selftest_verdict(outcome: dict[str, Any]) -> str:
    """Человеческий вывод: что делать с этим результатом.

    Голый код ошибки требует знать устройство цепочки; здесь оно уже известно,
    и незачем заставлять человека вспоминать, чья это сторона.
    """
    if outcome.get("ok"):
        # Маршрутов три, и «через этот сервер» верно только для одного. В
        # обратной схеме ответ тоже приходит с Render — просто он сам за ним
        # пришёл, и называть это «своим сервером» значит путать.
        where = {
            "render_proxy": "через Render",
            "render_pull": "через Render, по очереди заданий",
        }.get(outcome["route"], "на этом сервере")
        return f"Цепочка работает: ответ за {outcome.get('seconds')} с {where}."
    error = str(outcome.get("error") or "")
    if outcome["route"] == "render_pull":
        if "не забрал задание" in error or outcome.get("status") == 504:
            return ("Сервис модели не забирает задания из очереди. Проверьте, что на нём "
                    "задан PLATO_PULL_URL и он перезапущен: ключ и модель ни при чём.")
        return "Задание забрали, но ответ вернулся ошибкой — текст в поле error."
    if outcome["route"] == "render_proxy":
        if "не ответил за" in error or outcome.get("status") == 504:
            return ("Сервис модели на Render не отвечает этому серверу. Ключ и модель "
                    "ни при чём: до них вызов не доходит. Проверьте, поднят ли сервис "
                    "и та ли версия на нём выкачена.")
        if outcome.get("status") == 403:
            return "PLATO_AI_PROXY_SECRET на двух машинах разный."
        if outcome.get("status") == 503:
            return "Маршрут задан не полностью: смотрите текст ошибки."
        return "Вызов до Render дошёл, но вернулся ошибкой — текст в поле error."
    if "OPENAI_API_KEY" in error:
        return "Ключ OpenAI на этом сервере не задан."
    return "Вызов модели с этого сервера не прошёл — текст в поле error."


@app.post("/agent/chat")
def agent_chat(req: AgentChatRequest, request: Request) -> dict[str, Any]:
    """Вопрос Платону. Соединение держится ровно до передачи работы опросу."""
    # Каждый вопрос — платный вызов модели, поэтому с сайта Платон доступен
    # после входа через Telegram (мягкий гейт: расчёт остаётся открытым).
    # Бот и /ia/goal-seek сюда не приходят — они зовут функции напрямую.
    # Платон на каждом вопросе пересчитывает модель проекта (`_work`) — это
    # расчёт того же участка, и право на него решает та же функция.
    require_calc_access(req.session, req.access_key, "Платон отвечает", inputs=req.inputs)
    # Учёт здесь, а не в общей части: бот идёт тем же путём, но его вопросы уже
    # записаны в журнал как сообщения — иначе каждый считался бы дважды.
    # chat_id здесь не был передан вовсе, и все вопросы ложились под нулём:
    # соседний `/calculate` его пишет, а этот — нет (разбор журнала 23.08.2026).
    usage_track("question", surface="site", text=str(req.message or ""),
                chat_id=_web_identity_chat_id(str(getattr(req, "session", "") or "")),
                scenario=str(req.scenario or ""))
    return plato_answer_handoff(req, request)


def plato_answer_handoff(req: AgentChatRequest, request: Request) -> dict[str, Any]:
    """Вопрос Платону для окна: соединение держится до передачи работы опросу.

    Тот, кто спрашивает из браузера, ДОЛЖЕН идти этим путём, а не `plato_answer`.
    Цепочка ядро → Render → OpenAI одним соединением не держится: у nginx свои
    шестьдесят секунд, у мобильного Safari свои, и вопрос с инструментами не
    укладывается ни в один — работа доходит до конца и уносится в никуда.
    Кабинет рынка ходил через `plato_answer` и получал в браузер страницу
    ошибки вместо ответа: «комментарии Платона так и не подключились»
    (владелец, 26.08.2026).
    """
    trace_id, done, outcome = _plato_chat_launch(req, request)
    if not done.wait(_PLATO_CHAT_HANDOFF_SECONDS):
        _PLATON_LOG.info("Platon [%s] handed off to polling after %ds",
                         trace_id, int(_PLATO_CHAT_HANDOFF_SECONDS))
        return {"pending": True, "trace_id": trace_id}
    return _plato_chat_result(trace_id, outcome)


def plato_answer(req: AgentChatRequest, request: Request) -> dict[str, Any]:
    """Тот же вопрос, но для того, кому соединение держать не перед кем.

    Бот живёт в этом же процессе и ждёт ответ в своём потоке: отдавать ему
    «работа принята» бессмысленно — забирать результат ему неоткуда, и человек
    в телеграме получил бы вместо ответа пустоту.
    """
    trace_id, done, outcome = _plato_chat_launch(req, request)
    if not done.wait(_PLATO_AGENT_WAIT_SECONDS):
        raise HTTPException(
            status_code=504,
            detail=(f"Платон Сергеевич не ответил за {int(_PLATO_AGENT_WAIT_SECONDS)} с. "
                    "Повторите вопрос."))
    return _plato_chat_result(trace_id, outcome)


@app.post("/agent/document")
def agent_document(req: AgentDocumentRequest, request: Request) -> dict[str, Any]:
    """Разобрать документ по участку и показать, что из него можно взять.

    Три хода: что написано (с цитатой), что из этого следует (считает движок),
    чего в документе нет (спрашивается). Ничего не подставляется молча —
    применение отдельным вызовом с уже подтверждёнными ключами.
    """
    _require_web_access(req.session, req.access_key, "Разбор документа")
    # Применение уже разобранного: модель второй раз не зовём — она бы
    # прочитала документ заново и могла ответить иначе на тех же страницах.
    if req.accept:
        got = document_intake.apply_intake(
            req.extraction or {}, req.inputs or {}, req.tep or {}, accept=req.accept,
            spp_split=MKD_SPP_SPLIT)
        usage_track("document_apply", surface="site",
                    text=str(req.filename or ""))
        return {"applied": got["applied"], "refused": got["refused"],
                "inputs": got["inputs"], "tep": got["tep"]}

    try:
        data = base64.b64decode(str(req.content_b64 or ""), validate=True)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"Файл не прочитался: {exc}") from exc
    if not data:
        raise HTTPException(status_code=400, detail="Пустой файл")
    if len(data) > _DOCUMENT_INTAKE_MAX_BYTES:
        raise HTTPException(
            status_code=413,
            detail=(f"Файл больше {_DOCUMENT_INTAKE_MAX_BYTES // (1024 * 1024)} МБ. "
                    "Пришлите нужные страницы отдельно."))
    document = document_intake.extract_text(data, req.filename)
    if not document.get("text"):
        # Скан — не пустой документ, и выдавать «ничего не нашли» за ответ
        # нельзя: человек решит, что в файле пусто. Гейт по признаку скана
        # отказывал бы и распознанному — то есть ровно там, где сработало.
        return {"document": document, "fields": [], "questions": [], "notes": [],
                "reason": document.get("reason") or "в документе нет текста"}

    usage_track("document", surface="site", text=str(req.filename or ""))
    # Та же порция, что уходит в вопрос (`intake_prompt`): ответ сообщает,
    # сколько документа прочитано. Без неё окно получало HTTP 500 уже ПОСЛЕ
    # ответа модели — работа была сделана и выброшена.
    portion = document_intake.intake_text(document)
    payload = AgentChatRequest(
        message=document_intake.intake_prompt(document),
        inputs=dict(req.inputs or DEFAULT_INPUTS),
        tep={key: dict(value) for key, value in (req.tep or TEP_DEFAULT).items()},
        scenario="document_intake",
    )
    answer = plato_answer(payload, request)
    got = document_intake.parse_intake(str(answer.get("answer") or ""))
    # Сколько документа прочитано — часть ответа: непрочитанный хвост, о
    # котором не сказано, читается как «в документе этого нет».
    return {"document": {**{key: value for key, value in document.items() if key != "text"},
                         "read_chars": portion["read_chars"],
                         "total_chars": portion["total_chars"],
                         "trimmed": portion["trimmed"]},
            # Документ остаётся в разговоре: следующий вопрос окно шлёт вместе
            # с ним, и Платон отвечает по документу, а не по пустому месту.
            "context": document_intake.chat_context(document, got),
            **got,
            "queue": _intake_queue_start(str(req.filename or ""), got.get("questions") or [])}


# --- вопросы по документу: по одному, очередь на диске ------------------------
# Воркеров два, и ответ на первый вопрос может прийти не в тот, что разбирал
# документ: очередь живёт в каталоге стадий Платона, а не в памяти процесса.
_INTAKE_QUEUE_TTL = 3 * 24 * 3600


def _intake_queue_path(intake_id: str) -> Path:
    if not _TRACE_ID_RE.match(str(intake_id or "")):
        raise HTTPException(status_code=400, detail="Неверный номер очереди вопросов")
    return _safe_child(_PLATO_STAGE_DIR, f"intake_{intake_id}.json")


def _intake_queue_save(queue: dict[str, Any]) -> None:
    path = _intake_queue_path(queue["id"])
    _PLATO_STAGE_DIR.mkdir(parents=True, exist_ok=True)
    # Через временный файл: соседний воркер не должен прочитать половину.
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(queue, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)
    cutoff = time.time() - _INTAKE_QUEUE_TTL
    for stale in _PLATO_STAGE_DIR.glob("intake_*.json"):
        try:
            if stale.stat().st_mtime < cutoff:
                stale.unlink()
        except OSError:
            pass


def _intake_queue_view(queue: dict[str, Any]) -> dict[str, Any]:
    cards = queue.get("cards") or []
    index = int(queue.get("index") or 0)
    return {"id": queue["id"], "index": index, "total": len(cards),
            "filename": queue.get("filename") or "",
            "card": cards[index] if index < len(cards) else None,
            "answers": queue.get("answers") or []}


def _intake_queue_start(filename: str, questions: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Завести очередь вопросов. Вопросов нет — очереди нет."""
    if not questions:
        return None
    queue = {"id": os.urandom(16).hex(), "filename": filename, "index": 0, "answers": [],
             "cards": [document_intake.question_card(item) for item in questions]}
    try:
        _intake_queue_save(queue)
    except OSError as exc:
        # Без диска вопросы задать можно, а принять ответ в другом воркере —
        # нет. Говорим об этом прямо, а не теряем ответ на втором вопросе.
        return {"error": f"очередь вопросов не записалась на диск: {exc}"}
    return _intake_queue_view(queue)


@app.post("/agent/document/answer")
def agent_document_answer(req: AgentDocumentAnswerRequest) -> dict[str, Any]:
    """Ответ на текущий вопрос: применить к полю, записать, отдать следующий."""
    _require_web_access(req.session, req.access_key, "Разбор документа")
    path = _intake_queue_path(req.intake_id)
    try:
        queue = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise HTTPException(status_code=404, detail=(
            "Вопросы по этому документу не найдены на сервере (прошло больше трёх "
            "дней или сервер перезапущен с чистого диска). Приложите документ заново."))
    view = _intake_queue_view(queue)
    if req.index != view["index"]:
        # Двойное нажатие или вторая вкладка: отвечали на вопрос, который уже
        # закрыт. Чужой вопрос этим ответом не закрываем — отдаём текущий.
        return {"stale": True, "queue": view, "applied": [], "refused": [],
                "inputs": req.inputs, "tep": req.tep}
    card = view["card"]
    if card is None:
        return {"queue": view, "applied": [], "refused": [], "inputs": req.inputs, "tep": req.tep}
    action = str(req.action or "answer")
    if action == "answer":
        ledger = dict(queue.get("ledger") or {})
        got = document_intake.answer_card(card, req.inputs or {}, req.tep or {},
                                          choice=req.choice, typed=req.value,
                                          ledger=ledger, mode=str(req.mode or ""))
        if got.get("confirm"):
            # В поле уже своё число: прибавить или заменить — решает человек,
            # и вопрос остаётся открытым, пока он не ответит.
            return {"queue": view, "confirm": got["confirm"], "answer": got["answer"],
                    "applied": [], "refused": [], "inputs": req.inputs, "tep": req.tep}
        queue["ledger"] = ledger
    else:
        got = {"answer": "", "inputs": req.inputs, "tep": req.tep,
               "applied": [], "refused": []}
    answers = list(queue.get("answers") or [])
    # Итог по документу печатает было → стало каждого поля, а не одни имена:
    # «→ в модели: Цена сделки» не говорит, какое число туда легло.
    answers.append({"question": card.get("question"), "answer": got["answer"],
                    "applied": [row.get("label") or row.get("key") for row in got["applied"]],
                    "changes": got["applied"],
                    "refused": got["refused"]})
    queue["answers"] = answers
    # «Закончить» закрывает очередь целиком: отвеченное остаётся.
    queue["index"] = len(queue.get("cards") or []) if action == "stop" else view["index"] + 1
    _intake_queue_save(queue)
    usage_track("document_answer", surface="site", text=str(queue.get("filename") or ""))
    return {"queue": _intake_queue_view(queue), "answer": got["answer"],
            "applied": got["applied"], "refused": got["refused"],
            "inputs": got["inputs"], "tep": got["tep"]}


@app.get("/agent/result/{trace_id}")
def agent_result(trace_id: str) -> dict[str, Any]:
    """Готовый ответ по номеру запуска.

    Нужен, когда соединение с окном оборвалось: работа на сервере при этом
    доходит до конца, и терять её из-за таймаута промежуточного звена
    неправильно — человек уже подождал.
    """
    if not _TRACE_ID_RE.fullmatch(str(trace_id or "").strip().lower()):
        raise HTTPException(status_code=400, detail="Неверный идентификатор запроса.")
    stored = _plato_answer_get("run" + str(trace_id).strip().lower())
    if stored is None:
        return {"pending": True}
    return {**stored, "cached": False, "pending": False, "trace_id": trace_id}
