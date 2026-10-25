"""Потолок цены входа: один подбор и одни плитки «Инвестиционного решения»
для страницы, тизера и полного PDF.

Подбор — многократный полный пересчёт модели (`_tool_goal_seek`) по тому
показателю долга, которым движок судит проект (`goal_seek_debt_metric`), с
его порогом и охватом (`_agent_scope_of`). Зовут его `/ia/goal-seek` страницы
и фоновые сборки тизера и PDF — второй реализации нет.

Ответ несёт отпечаток вводных и подпись сервера. Сборка отчёта берёт ответ,
присланный страницей, без пересчёта, только если отпечаток совпал с вводными
отчёта и подпись верна; иначе подбирает сама — в той же фоновой задаче.

Плитки (`entry_price_tiles`) и подпись под ними (`entry_price_stamp`) —
единственное место их текста: страница рисует плитки из ответа сервера,
тизер и PDF — из того же словаря.

Не самостоятельный модуль. `main_legacy.py` выполняет этот файл в своём
пространстве имён (`_engine_part("entry_price_ceiling")`), поэтому здесь
видны все имена движка. Отдельно не импортировать.
"""
# ruff: noqa

ENTRY_PRICE_VARIABLE = "purchase_price_mln"
ENTRY_PRICE_TITLE = "Инвестиционное решение"
# Поля, которые сервер выводит из ответа сам и которые подписью не покрыты.
_ENTRY_PRICE_DERIVED = ("signature", "title", "tiles", "stamp", "verdict", "source", "page_mismatch")


def entry_price_fingerprint(inputs: dict[str, Any] | None, tep: dict[str, Any] | None,
                            rates: list[Any] | None, phasing: dict[str, Any] | None,
                            variable: str = ENTRY_PRICE_VARIABLE,
                            target: float | None = None) -> str:
    """Отпечаток подбора: вводные расчёта (`_calculation_fingerprint`), ставки,
    что подбирали, к какому порогу и какой версией движка. Совпал — это тот же
    подбор; не совпало хоть что-то — подбор другой."""
    base = _calculation_fingerprint(inputs, tep, phasing)
    extra = json.dumps({"rates": rates or [], "variable": variable,
                        "target": None if target is None else round(float(target), 6),
                        "engine": VERSION},
                       ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(f"{base}|{extra}".encode("utf-8")).hexdigest()[:16]


def _entry_price_canonical(value: Any) -> Any:
    """Число после JSON браузера теряет «.0» (2000.0 → 2000): подпись считает
    числа в одном виде, иначе честный ответ страницы не узнаётся."""
    if isinstance(value, bool) or value is None or isinstance(value, str):
        return value
    if isinstance(value, (int, float)):
        return repr(float(value))
    if isinstance(value, dict):
        return {str(k): _entry_price_canonical(v) for k, v in value.items()
                if k not in _ENTRY_PRICE_DERIVED}
    if isinstance(value, (list, tuple)):
        return [_entry_price_canonical(v) for v in value]
    return str(value)


def _entry_price_key() -> str:
    """Ключ подписи — токен бота: он один у обоих воркеров и у Render с ядром."""
    return _telegram_token()


def _entry_price_signature(data: dict[str, Any]) -> str | None:
    """Подпись ответа подбора ключом бота: без неё число, присланное страницей,
    нельзя отличить от вписанного руками. Нет ключа — подписи нет, и отчёт
    подбирает сам."""
    token = _entry_price_key()
    if not token:
        return None
    raw = json.dumps(_entry_price_canonical(data), ensure_ascii=False, sort_keys=True,
                     separators=(",", ":")).encode("utf-8")
    return hmac.new(token.encode("utf-8"), b"entry-price:" + raw, hashlib.sha256).hexdigest()[:40]


def entry_price_ceiling(bundle: dict[str, Any], inputs: dict[str, Any], tep: dict[str, Any],
                        rates: list[Any], phasing: dict[str, Any],
                        variable: str = ENTRY_PRICE_VARIABLE,
                        target: float | None = None) -> dict[str, Any]:
    """Максимум цены входа, при котором показатель долга проекта не ниже
    порога банка. `bundle` — уже посчитанная модель тех же вводных."""
    metric = goal_seek_debt_metric(bundle)
    threshold = float(target if target is not None else (metric.get("target") or DEBT_METRIC_TARGET))
    stamp = {"engine_version": VERSION,
             "computed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
             "fingerprint": entry_price_fingerprint(inputs, tep, rates, phasing, variable, threshold)}
    if not metric.get("key"):
        data = {"available": False, "target_metric": None,
                "metric_label": metric.get("label"),
                "reason": metric.get("reason") or "Показателя долга у проекта нет.", **stamp}
    else:
        req = AgentChatRequest(message="", inputs=inputs, tep=tep, rates=rates, phasing=phasing)
        # Шаги подбора читают показатель долга, а не сравнение стратегий: без
        # выключения каждый шаг стоил бы трёх расчётов (`OFFICE_PATHS_ON`).
        token = OFFICE_PATHS_ON.set(False)
        try:
            data = dict(_tool_goal_seek(req, bundle, variable, metric["key"], threshold,
                                        "at_least", "maximum_variable", _agent_scope_of(bundle),
                                        None, None))
        finally:
            OFFICE_PATHS_ON.reset(token)
        data.setdefault("target_metric", metric["key"])
        data.update({"metric_label": metric.get("label"), **stamp})
    data["target"] = threshold
    data["signature"] = _entry_price_signature(data)
    return data


def entry_price_for_report(bundle: dict[str, Any], inputs: dict[str, Any], tep: dict[str, Any],
                           rates: list[Any], phasing: dict[str, Any],
                           supplied: Any = None) -> dict[str, Any]:
    """Потолок для тизера и PDF. Звать только из фоновой сборки: подбор —
    десятки полных пересчётов.

    Ответ страницы (`supplied`) берётся как есть, когда его отпечаток совпал с
    вводными отчёта и подпись сервера верна. Иначе — подбор здесь же; отказ
    подбора становится причиной в плитке, а не пустым числом."""
    metric = goal_seek_debt_metric(bundle)
    target = float(metric.get("target") or DEBT_METRIC_TARGET)
    expected = entry_price_fingerprint(inputs, tep, rates, phasing, ENTRY_PRICE_VARIABLE, target)
    page_mismatch = False
    if isinstance(supplied, dict) and supplied.get("fingerprint"):
        signature = _entry_price_signature(supplied)
        if (supplied.get("fingerprint") == expected and signature
                and hmac.compare_digest(str(supplied.get("signature") or ""), signature)):
            return {**supplied, "source": "page"}
        page_mismatch = True
    try:
        data = entry_price_ceiling(bundle, inputs, tep, rates, phasing, ENTRY_PRICE_VARIABLE, target)
    except Exception as exc:
        logging.exception("entry price ceiling failed")
        data = {"available": False, "error": True, "target_metric": metric.get("key"),
                "target": target, "engine_version": VERSION,
                "computed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "reason": f"Подбор цены не выполнен: модель не пересчиталась ({exc})."}
    return {**data, "source": "report", "page_mismatch": page_mismatch}


# --- Плитки -------------------------------------------------------------

def _tile_mult(value: Any) -> str:
    try:
        return f"{float(value):.2f}".replace(".", ",") + "x"
    except (TypeError, ValueError):
        return "—"


def _tile_mln(value: Any) -> str:
    """«3 474,5 млн ₽», «2 000 млн ₽» — как `mlnLabel` страницы: до одного знака."""
    try:
        number = round(float(value), 1)
    except (TypeError, ValueError):
        return "—"
    text = f"{number:,.1f}".replace(",", " ").replace(".", ",")
    if text.endswith(",0"):
        text = text[:-2]
    return text + " млн ₽"


def _tile_scope_genitive(label: str) -> str:
    if label.startswith("слабейшая очередь"):
        return "слабейшей очереди" + label[len("слабейшая очередь"):]
    if label == "Весь проект":
        return "всего проекта"
    return label


def _entry_price_weakest(bundle: dict[str, Any]) -> dict[str, Any] | None:
    weakest = None
    for item in bundle.get("phases") or []:
        value = (((item or {}).get("result") or {}).get("summary") or {}).get("llcr")
        if value is None:
            continue
        if weakest is None or float(value) < weakest["llcr"]:
            weakest = {"name": item.get("name") or "очередь", "llcr": float(value)}
    return weakest


def entry_price_verdict(bundle: dict[str, Any]) -> dict[str, str]:
    """Заголовок карточки решения: проходит / на границе / не проходит —
    по показателю долга и его порогам из движка; без показателя — по прибыли."""
    result = bundle.get("consolidated") or {}
    summary = result.get("summary") or {}
    metric = goal_seek_debt_metric(bundle)
    if not metric.get("key"):
        ok = float(summary.get("net_profit") or 0) > 0
        return {"title": "Экономика проходит по прибыли" if ok else "Экономика не проходит",
                "tone": "edge" if ok else "fail"}
    value = summary.get("llcr") if metric["key"] == "llcr" else metric.get("value")
    name = "LLCR" if metric["key"] == "llcr" else "DSCR"
    target = float(metric.get("target") or DEBT_METRIC_TARGET)
    floor = float(metric.get("floor") or 1.05)
    if value is None:
        return {"title": f"{name} не рассчитан", "tone": ""}
    if float(value) >= target:
        return {"title": "Экономика проходит", "tone": "pass"}
    if float(value) >= floor:
        return {"title": "Экономика на границе", "tone": "edge"}
    return {"title": "Экономика не проходит", "tone": "fail"}


def entry_price_tiles(bundle: dict[str, Any], inputs: dict[str, Any],
                      goal: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Четыре плитки «Инвестиционного решения»: покрытие долга, цена входа,
    максимум цены входа, запас к цене. `goal` — ответ подбора или None,
    пока его нет."""
    result = bundle.get("consolidated") or {}
    summary = result.get("summary") or {}
    metric = goal_seek_debt_metric(bundle)
    by_llcr = metric.get("key") == "llcr"
    name = "DSCR" if metric.get("key") == "dscr" else "LLCR"
    target = float(metric.get("target") or DEBT_METRIC_TARGET)
    target_text = f"{target:.2f}".replace(".", ",") + "x"
    goal = goal if isinstance(goal, dict) else None
    found = (goal or {}).get("solution") if goal and goal.get("available") else None
    refused = bool(goal) and not found and isinstance(goal.get("closest_tested"), dict)
    scope = str((goal or {}).get("scope_label") or "")

    weakest = _entry_price_weakest(bundle) if by_llcr and bundle.get("mode") == "phased" else None
    value = summary.get("llcr") if by_llcr else metric.get("value")
    if weakest:
        cover = {"label": "LLCR (свод / слабейшая очередь)",
                 "value": f"{_tile_mult(value)} / {_tile_mult(weakest['llcr'])}",
                 "note": f"Ориентир банка — {target_text}; судит свод, слабейшая — {weakest['name']}."}
    elif metric.get("key"):
        cover = {"label": "LLCR (расчётный)" if by_llcr else str(metric.get("label") or name),
                 "value": _tile_mult(value),
                 "note": f"Ориентир банка — {target_text}"
                         + ("." if by_llcr else "; доход объекта на проценты и тело кредита.")}
    else:
        # Причину называет движок (`debt_metric.reason`): у гостиницы, у
        # аренды без кредита и у прямой продажи она своя.
        cover = {"label": str(metric.get("label") or "Покрытие кредита"), "value": "не считается",
                 "note": str(metric.get("reason") or "Показателя покрытия у проекта нет."), "wait": True}

    current = ((goal or {}).get("current") or {}).get("variable") if found else None
    price = float(current if current is not None
                  else (inputs or {}).get(ENTRY_PRICE_VARIABLE) or 0.0)
    entry = ({"label": "Цена входа", "value": _tile_mln(price), "note": "Текущая цена приобретения."}
             if price > 0 else
             {"label": "Цена входа", "value": "не задана", "wait": True,
              "note": "Заполните «Стоимость покупки» в Экономике — сейчас всё посчитано "
                      "как для бесплатного участка."})

    if not metric.get("key"):
        ceiling = {"label": "Максимум цены входа", "value": "не подбирается", "wait": True,
                   "note": "Потолок цены ищется по порогу покрытия долга, а показателя "
                           "покрытия у проекта нет: " + str(metric.get("reason") or "").rstrip(".")
                           + ". Смотрите прибыль и IRR."}
        margin = {"label": "Запас к цене", "value": "—", "note": "Нет потолка — нет и запаса.", "wait": True}
    elif found:
        ceiling = {"label": "Максимум цены входа", "value": _tile_mln(found.get("variable")),
                   "note": f"При {name} не ниже {target_text}" + (f" · {scope}" if scope else "") + "."}
        if goal.get("non_monotonic") and goal.get("feasible_ranges"):
            # Решатель нашёл несколько отрезков цены, где порог держится:
            # показан наибольший, а отрезки названы.
            ranges = ", ".join(f"от {_tile_mln(a)} до {_tile_mln(b)}" if a != b else _tile_mln(a)
                               for a, b in goal["feasible_ranges"])
            ceiling["note"] += (f" {name} меняется с ценой неровно: порог держится на нескольких "
                                f"отрезках цены ({ranges}), здесь показан наибольший.")
        change = float(found.get("change_abs") or 0.0)
        margin = {"label": "Запас к цене", "value": _tile_mln(change),
                  "note": "Цена ниже потолка." if change >= 0
                  else f"Цена выше потолка — покупка не проходит по {name}."}
    elif refused:
        closest = goal.get("closest_tested") or {}
        who = _tile_scope_genitive(scope) if scope else "проекта"
        at = ("даже при нулевой цене входа" if float(closest.get("variable") or 0) == 0
              else "ближе всего при " + _tile_mln(closest.get("variable")))
        got = "" if closest.get("metric") is None else " — там выходит " + _tile_mult(closest["metric"]) + (
            f" ({closest['scope_label']})" if closest.get("scope_label") and closest.get("scope_label") != scope else "")
        ceiling = {"label": "Максимум цены входа", "value": "не достигается", "wait": True,
                   "note": f"{name} {target_text} у {who} не достигается {at}{got}."}
        margin = {"label": "Запас к цене", "value": "—", "wait": True,
                  "note": "Порог не достигается ни при какой цене входа"
                          + (f" у {_tile_scope_genitive(scope)}" if scope else "") + " — дело не в цене."}
    elif goal:
        ceiling = {"label": "Максимум цены входа", "value": "не подобран", "wait": True,
                   "note": str(goal.get("reason") or "Подбор не выполнен.")}
        margin = {"label": "Запас к цене", "value": "—", "wait": True,
                  "note": "Без потолка запас не считается."}
    else:
        ceiling = {"label": "Максимум цены входа", "value": "не подобран", "wait": True,
                   "note": f"Подбор цены при {name} {target_text} для этого документа не выполнялся."}
        margin = {"label": "Запас к цене", "value": "—", "wait": True,
                  "note": "Считается после подбора максимума."}
    return [cover, entry, ceiling, margin]


def entry_price_stamp(goal: dict[str, Any] | None, has_metric: bool = True) -> str:
    """Подпись под плитками: кто подобрал, какой версией и когда."""
    if not has_metric or not isinstance(goal, dict) or not goal.get("engine_version"):
        return ""
    when = str(goal.get("computed_at") or "")
    try:
        when = datetime.fromisoformat(when).astimezone(timezone.utc).strftime("%d.%m.%Y %H:%M UTC")
    except ValueError:
        pass
    version = goal["engine_version"]
    if goal.get("error"):
        return f"Подбор не выполнен движком DevelopAid {version}: {goal.get('reason') or 'причина не указана'}"
    text = (f"Подбор выполнен полным пересчётом модели DevelopAid {version} · {when}. "
            "Текущая модель не изменена.")
    if goal.get("threshold_beyond_bound"):
        text += " Порог упёрся в границу поиска — предел может лежать дальше."
    if goal.get("page_mismatch"):
        text += (" Подбор со страницы относился к другим вводным, поэтому для этого "
                 "документа цена подобрана заново.")
    return text


def entry_price_block(bundle: dict[str, Any], inputs: dict[str, Any],
                      goal: dict[str, Any] | None) -> dict[str, Any]:
    """Блок «Инвестиционное решение» целиком — для тизера, PDF и страницы."""
    has_metric = bool(goal_seek_debt_metric(bundle).get("key"))
    return {"title": ENTRY_PRICE_TITLE, "verdict": entry_price_verdict(bundle),
            "tiles": entry_price_tiles(bundle, inputs, goal),
            "stamp": entry_price_stamp(goal, has_metric)}
