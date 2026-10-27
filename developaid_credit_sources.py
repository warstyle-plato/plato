"""Данные погашения кредитов — из того, что уже загружено в систему.

Владелец (27.10.2026): «Откуда я возьму эти файлы и данные? Они все есть или в
НКЛ, или в РСС, или в модели. Ничего нового ты не получишь». Поэтому расчёт
(`developaid_credit_repayment`) получает наборы отсюда, а ручная загрузка в
Монитор остаётся только поправкой поверх найденного, с подписью источника.

Откуда что:

* условия НКЛ — разобранные договоры (`credit_repayment.PRESETS`,
  выписка `docs/projects/kutuzov_credit_terms.md`), проект привязан к ним
  явным списком имён (`PRESETS[...]["projects"]`, через псевдонимы Монитора);
* выдачи кредита — реестр платежей РСС, платежи из заёмных средств
  (`actuals.borrowed`) — тот же источник, что строка «Выборка кредита» сводки.
  РСС не называет, какой НКЛ платил: выдача ложится на первую линию в пределах
  её лимита на дату, остаток — на следующую (допущение, называется);
* долг, начисленные и отложенные проценты на дату РСС — досчитываются от первой
  выдачи по условиям договоров (погашений до первой даты графика нет);
* эскроу — поступило: графики поступлений по договорам из отчёта о продажах;
  дальше — тот же прогноз, что «Эскроу по кварталам» и «к вводу» сводки
  (`contracting.keeping_at`): рассрочка подписанных договоров и новые продажи
  по нынешнему темпу, равномерно до ввода. Раскрытие в сумме — ровно это число;
* прогнозные выдачи — до лимита каждой НКЛ к концу её доступности (владелец:
  «будущие выборки до РНВ = лимит»): сроки — план остатка ПФ финмодели сверх
  уже выбранного, недостающее до лимита — в последний день доступности;
* ставка — «Ставка кредита ПФ» финмодели: снижается вслед за покрытием —
  итоговая, берётся как есть; иначе базовая, ключевая = она минус маржа;
* раскрытие — утверждённый срок ввода (`management_report._commissioning`, тот
  же `schedule`, что у сводки); прогноз Монитора — отдельной строкой допущений;
* план банка (эскроу и продажи по кварталам) — лист плана банка отчёта о продажах.

Чего нет ни в договорах, ни в РСС, ни в модели — называется в разделе словами:
что именно и где его не нашлось.
"""

from __future__ import annotations

import datetime
from pathlib import Path
from typing import Any

import developaid_credit_repayment as credit
from market_search import contracting

M = credit.M


def preset_for(project: str) -> str | None:
    """Условия кредитов, к которым явно привязан проект (с учётом псевдонимов)."""
    import developaid_monitor as monitor

    folder = monitor._project_dir(project)
    for name, preset in credit.PRESETS.items():
        if any(monitor._project_dir(alias) == folder for alias in preset.get("projects") or []):
            return name
    return None


def _set(name: str, as_of: str, source: str, data: dict[str, Any]) -> dict[str, Any]:
    return {"name": name, "as_of": as_of, "source": source, "unit": "₽", "data": data}


def _month_end(month: str) -> str:
    return credit._month_end(month).isoformat()


def _draws(project: str, end: datetime.date) -> dict[str, Any]:
    """Выдачи кредита по реестру платежей последнего РСС не позже ``end``."""
    import developaid_actuals as actuals
    import developaid_monitor as monitor

    rss = monitor._latest(project, "estimate", ".xlsx", end.isoformat())
    if rss is None:
        return {"missing": f"выдачи кредита: в Мониторе нет отчёта РСС на {end:%d.%m.%Y}"}
    rows = actuals.read_payments(rss)["rows"]
    day = rss.stem[:10]
    draws = sorted((row["date"], float(row.get("amount") or 0.0)) for row in rows
                   if row.get("date") and actuals.borrowed(row.get("source"))
                   and row["date"].isoformat() <= day)
    if not draws:
        return {"missing": f"выдачи кредита: в реестре платежей РСС от "
                           f"{credit.ddmmyyyy(day)} нет платежей из заёмных средств"}
    return {"as_of": day, "draws": draws,
            "source": f"реестр платежей РСС от {credit.ddmmyyyy(day)}, платежи из заёмных средств"}


def _split(loans: list[dict[str, Any]], draws: list[tuple[datetime.date, float]]
           ) -> tuple[dict[str, list[dict[str, Any]]], list[str]]:
    """Выдача — на первую линию в пределах её лимита на дату, остаток — дальше."""
    drawn = {loan["id"]: 0.0 for loan in loans}
    out: dict[str, list[dict[str, Any]]] = {loan["id"]: [] for loan in loans}
    over = 0.0
    for day, amount in draws:
        left = amount
        for loan in loans:
            opened = min(credit._day(d) for d, _ in loan.get("limit_steps") or
                         [(loan["availability_end"], 0)])
            if day < opened or day > credit._day(loan["availability_end"]):
                continue
            room = max(0.0, credit._limit_on(loan, day) - drawn[loan["id"]])
            take = min(room, left)
            if take > 0:
                out[loan["id"]].append({"date": day.isoformat(), "amount": take})
                drawn[loan["id"]] += take
                left -= take
            if left <= 1.0:
                break
        if left > 1.0:
            # Лимитов не хватило — выдача остаётся на первой открытой линии и
            # называется: расчёт не прячет то, что не сходится с договорами.
            first = next((loan for loan in loans if day <= credit._day(
                loan["availability_end"])), loans[0])
            out[first["id"]].append({"date": day.isoformat(), "amount": left})
            drawn[first["id"]] += left
            over += left
    notes = []
    if over > 1.0:
        notes.append(f"Выдачи по РСС на {credit.mln(over)} млн ₽ превышают лимиты по договорам "
                     "на свои даты — они отнесены на первую открытую линию.")
    return out, notes


def _plan_draws(loans: list[dict[str, Any]], credit_plan: dict[str, Any] | None,
                drawn_total: float, after: str) -> list[tuple[datetime.date, float]] | None:
    """Прогнозные выдачи: план остатка ПФ финмодели сверх уже выбранного."""
    queues = (credit_plan or {}).get("queues") or []
    plan: dict[str, float] = {}
    for queue in queues:
        for month, value in (queue.get("pf") or {}).items():
            plan[month] = plan.get(month, 0.0) + float(value or 0.0)
    if not plan:
        return None
    last = max(credit._day(loan["availability_end"]) for loan in loans).strftime("%Y-%m")
    running, out = drawn_total, []
    for month in sorted(plan):
        if month <= after[:7] or month > last:
            continue
        if plan[month] > running + 1.0:
            out.append((credit._day(f"{month}-15"), plan[month] - running))
            running = plan[month]
    return out


def _fit(loans: list[dict[str, Any]], drawn: dict[str, float], day: datetime.date,
         amount: float, overflow: bool) -> list[tuple[dict[str, Any], float]]:
    """Как выдача ложится на линии по `_split`: первая открытая в пределах лимита
    на дату, дальше следующая; ``overflow`` — остаток сверх лимитов на первую
    открытую (так `_split` делает с фактом), иначе остаток не выдаётся."""
    left, out = amount, []
    for loan in loans:
        opened = min(credit._day(d) for d, _ in loan.get("limit_steps") or
                     [(loan["availability_end"], 0)])
        if day < opened or day > credit._day(loan["availability_end"]):
            continue
        take = min(max(0.0, credit._limit_on(loan, day) - drawn[loan["id"]]), left)
        if take > 0:
            out.append((loan, take))
            left -= take
        if left <= 1.0:
            break
    if overflow and left > 1.0:
        first = next((loan for loan in loans if day <= credit._day(loan["availability_end"])),
                     loans[0])
        out.append((first, left))
    return out


def _to_limit(loans: list[dict[str, Any]], past: list[tuple[datetime.date, float]],
              future: list[tuple[datetime.date, float]], as_of: str
              ) -> tuple[list[tuple[datetime.date, float]], list[tuple[str, datetime.date, float]]]:
    """Довести выдачи каждой НКЛ до лимита к концу её периода доступности.

    Владелец, 27.10.2026: «Долг будет равен сумме лимита! Посмотри в НКЛ период
    доступности. Он раньше РНВ»; «будущие выборки до РНВ = лимит». План
    финмодели задаёт сроки выдач; чего ему не хватает до лимита, добирается в
    последний день доступности. Уже прошедший конец доступности не трогается:
    невыбранное там не выдать.
    """
    # План финмодели может требовать выдачу, когда свободного лимита на дату
    # нет (обе линии выбраны до лимита этого года). Такую выдачу банк не даст:
    # она урезается до свободного лимита на свою дату тем же порядком линий,
    # что у `_split`, а не ложится сверх лимита — иначе расчёт обнуляет её и
    # пишет «выше свободного лимита» (владелец на проде, 27.10.2026: «опять
    # какая-то чушь»). Недостающее до лимита добирается ниже, в конец доступности.
    drawn = {loan["id"]: 0.0 for loan in loans}
    for day, amount in sorted(past):
        for loan, part in _fit(loans, drawn, day, amount, overflow=True):
            drawn[loan["id"]] += part
    fitted = []
    for day, amount in sorted(future):
        parts = _fit(loans, drawn, day, amount, overflow=False)
        for loan, part in parts:
            drawn[loan["id"]] += part
        taken = sum(part for _, part in parts)
        if taken > 1.0:
            fitted.append((day, taken))
    future = fitted
    split, _ = _split(loans, sorted(past + future))
    out, topped = list(future), []
    for loan in loans:
        end = credit._day(loan["availability_end"])
        if end.isoformat() <= as_of[:10]:
            continue
        drawn = sum(d["amount"] for d in split[loan["id"]] if credit._day(d["date"]) <= end)
        gap = credit._limit_on(loan, end) - drawn
        if gap > 1.0:
            out.append((end, gap))
            topped.append((loan["short"], end, gap))
    return sorted(out), topped


def _model_rates(credit_plan: dict[str, Any] | None) -> tuple[dict[str, float],
                                                                 dict[str, float]]:
    """«Ставка кредита ПФ» (% годовых) и «Отношение эскроу к кредиту ПФ» по месяцам."""
    rates: dict[str, float] = {}
    cover: dict[str, float] = {}
    for queue in (credit_plan or {}).get("queues") or []:
        for month, value in (queue.get("rate") or {}).items():
            if value and month not in rates:
                value = float(value)
                rates[month] = value * 100 if value < 1 else value
        for month, value in (queue.get("coverage") or {}).items():
            if value is not None and month not in cover:
                cover[month] = float(value)
    return rates, cover


def rate_kind(rates: dict[str, float], cover: dict[str, float]) -> str:
    """Какая ставка в модели: ``base`` (ключевая + маржа) или ``effective`` (льготная).

    По договору льготная ставка зависит от покрытия долга эскроу. Если ставка
    модели меняется вместе с покрытием той же модели — растёт покрытие, падает
    ставка, — это уже итоговая ставка со скидкой. Одно число на весь срок или
    движение не вслед за покрытием — базовая (ключевая + маржа).
    """
    months = sorted(m for m in rates if m in cover)
    if len({round(rates[m], 4) for m in rates}) <= 1 or len(months) < 3:
        return "base"
    xs = [cover[m] for m in months]
    ys = [rates[m] for m in months]
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    sx = sum((x - mx) ** 2 for x in xs) ** 0.5
    sy = sum((y - my) ** 2 for y in ys) ** 0.5
    if not sx or not sy:
        return "base"
    corr = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / (sx * sy)
    return "effective" if corr < -0.5 else "base"


def collect(project: str, sales_project: str = "", sales_dir: Path | None = None,
            end: Any = None, commissioning: dict[str, str] | None = None,
            shift: dict[str, Any] | None = None,
            escrow_plan: dict[str, Any] | None = None) -> dict[str, Any]:
    """Наборы для расчёта из загруженного: {"preset", "history", "datasets", "missing", "notes"}.

    ``escrow_plan`` — сценарий «по плану финмодели» сводки: {"series": ряд
    эскроу финмодели по месяцам, "cut": месяц раскрытия, после которого ряд
    уже гасит кредит} — эскроу после даты РСС растёт до плана, а не по темпу.

    ``history`` — наборы от первой выдачи (досчитать долг и проценты до даты РСС),
    ``datasets`` — наборы на дату РСС для прогноза, кроме состояния кредита: его
    дописывает `inputs_for` после досчёта истории.
    """
    end = credit._day(end) if end else datetime.date.today()
    preset_id = preset_for(project)
    out: dict[str, Any] = {"preset": preset_id, "history": None, "datasets": {},
                           "missing": [], "notes": []}
    if not preset_id:
        return out
    loans = credit.PRESETS[preset_id]["loans"]
    datasets = out["datasets"]
    missing, notes = out["missing"], out["notes"]

    found = _draws(project, end)
    contracts_part, credit_plan, bank, sales_at = None, None, None, ""
    if str(sales_project or "").strip():
        from market_search import sales_store

        kept = sales_store.load(sales_dir or sales_store.default_dir(), sales_project)
        sources = kept.get("sources") or {}
        contracts_part = sources.get("contracting") or {}
        credit_plan = ((sources.get("credit") or {}).get("data")) or None
        bank = ((sources.get("bank_plan") or {}).get("data")) or None
        sales_at = str(contracts_part.get("at") or "")[:10]
    else:
        missing.append("эскроу, продажи и финмодель: проект не связан с отчётом о продажах "
                       "(страница «Сводка руководству», выбор отчёта о продажах)")
    rows = ((contracts_part or {}).get("data") or {}).get("rows") or []
    if sales_project and not rows:
        missing.append(f"поступления на эскроу: в отчёте о продажах «{sales_project}» нет "
                       "листа контрактации")
    if sales_project and not credit_plan:
        missing.append(f"план выдач, план эскроу и ставка: в отчёте о продажах «{sales_project}» "
                       "нет финмодели (лист «КРЕДИТЫ»)")

    # Ставка — из финмодели; ручной прогноз ключевой, если загружен, важнее.
    rates, cover = _model_rates(credit_plan)
    if rates:
        kind = rate_kind(rates, cover)
        margin = loans[0]["margin_pp"]
        if kind == "base":
            path = [{"from": f"{m}-01", "rate": rates[m] - margin} for m in sorted(rates)]
            words = (f"финмодель, «Ставка кредита ПФ» минус маржа {loans[0]['short']} "
                     f"{margin:g} п. п.").replace(".", ",", 1)
            notes.append(f"Ставка: в финмодели «Ставка кредита ПФ» не меняется вслед за "
                         f"покрытием эскроу, поэтому она принята базовой — ключевая плюс "
                         f"{f'{margin:g}'.replace('.', ',')} п. п. по {loans[0]['short']}"
                         + ". Скидка за покрытие эскроу считается по ступеням договора. "
                         "Если в модели ставка уже со скидкой, проценты здесь занижены.")
        else:
            path = [{"from": f"{m}-01", "rate": rates[m]} for m in sorted(rates)]
            words = "финмодель, «Ставка кредита ПФ» — итоговая ставка, взята как есть"
            notes.append("Ставка: в финмодели «Ставка кредита ПФ» снижается вслед за ростом "
                         "покрытия эскроу — это уже итоговая ставка со скидкой. Она взята как "
                         "есть для обоих кредитов, ступени договора повторно не применяются; "
                         "если банк считает иначе, проценты изменятся.")
            for loan in loans:
                datasets[f"terms.{loan['id']}"] = _set(
                    f"terms.{loan['id']}", sales_at or end.isoformat(), "финмодель", {
                        "rate": {"value": "model",
                                 "source": "итоговая ставка финмодели («Ставка кредита ПФ»)"}})
        # Ряд ставки финмодели может начинаться позже первой выдачи по РСС: без
        # ставки за ранние месяцы отсрочка (проценты с первой выдачи) не
        # считается, и пустыми выходят проценты первого платежа.
        draws = found.get("draws") or []
        first = draws[0][0].strftime("%Y-%m") if draws else ""
        if first and path[0]["from"][:7] > first:
            rate = f"{path[0]['rate']:.2f}".replace(".", ",")
            notes.append(f"Ставка финмодели начинается с {credit.ddmmyyyy(path[0]['from'])}, а "
                         f"выдачи по РСС — с {credit.ddmmyyyy(draws[0][0])}: за более ранние "
                         f"месяцы принята первая ставка финмодели ({rate} %).")
            path.insert(0, {"from": f"{first}-01", "rate": path[0]["rate"]})
        datasets["key_rate"] = _set("key_rate", sales_at or end.isoformat(), words,
                                    {"path": path})
    elif credit_plan:
        missing.append("прогноз ставки: в финмодели (лист «КРЕДИТЫ») нет строки «Ставка "
                       "кредита ПФ»")

    if "missing" in found:
        missing.append(found["missing"])
    as_of = found.get("as_of") or end.isoformat()

    # Раскрытие — в утверждённый срок ввода (тот же `schedule`, что у сводки);
    # без него — плановая дата из условий.
    terms = credit.PRESETS[preset_id]["terms"]
    if commissioning and commissioning.get("date"):
        when, words = commissioning["date"][:10], f"срок ввода — {commissioning['source']}"
        # Та же дата — «плановая дата раскрытия» проверки достаточности (А п. 8.2.60):
        # проценты до раскрытия считаются до утверждённого ввода, а не до даты условий.
        datasets["terms.project"] = _set("terms.project", as_of, words, {
            "planned_disclosure": {"value": when, "source": f"{words}: раскрытие эскроу "
                                   "в дату ввода"}})
    else:
        when = terms["planned_disclosure"]["value"]
        words = "утверждённого срока ввода нет — плановая дата раскрытия из условий (допущение)"

    # Эскроу: поступило — графики договоров (то, что случилось); дальше — тот же
    # прогноз, что «Эскроу по кварталам» и «к вводу» сводки (`keeping_at`):
    # рассрочка подписанных договоров и новые продажи по темпу, равномерно до ввода.
    payments, signed = [], []
    for row in rows:
        for step in row.get("escrow_schedule") or []:
            if step.get("amount"):
                payments.append({"date": _month_end(step["month"]), "month_only": True,
                                 "amount": float(step["amount"]),
                                 **({"contract": row["contract"]} if row.get("contract") else {})})
        if row.get("signed") and row.get("amount"):
            signed.append({"month": str(row["signed"])[:7], "amount": float(row["amount"])})
    contracts_source = (f"графики поступлений на эскроу по договорам, отчёт о продажах "
                        f"«{sales_project}» от {credit.ddmmyyyy(sales_at)}") if sales_at else ""
    if rows:
        balance = sum(p["amount"] for p in payments if p["date"][:7] <= as_of[:7])
        ahead: dict[str, list[dict[str, Any]]] = {"contracts": [], "sales": []}
        pace = _escrow_pace(rows, credit_plan, when)
        if escrow_plan is not None:
            ahead = _plan_forecast(escrow_plan, balance, as_of, when)
            pace = None
            notes.append("Поступления на эскроу до ввода — по плану финмодели (ряд эскроу "
                         "листа «КРЕДИТЫ» до раскрытия): после даты РСС остаток растёт до "
                         "плана, а не по нынешнему темпу.")
        elif pace:
            ahead, extra = _escrow_forecast(pace, as_of, when)
            balance += extra
            out["escrow_at_disclosure"] = contracting.keeping_at(pace, when[:7])
            notes.append(
                "Поступления на эскроу до ввода — тот же прогноз, что в «Эскроу по "
                f"кварталам»: остаток по рассрочке подписанных договоров "
                f"{credit.mln(pace['owed'])} млн ₽ и новые продажи по нынешнему темпу "
                f"{credit.mln(pace['sales_pace'])} млн ₽ в месяц, равномерно до ввода. "
                "Если продажи пойдут медленнее, к раскрытию на эскроу будет меньше и "
                "дефицит вырастет.")
        datasets["escrow"] = _set("escrow", as_of, contracts_source + " — поступило по "
                                  f"{credit.ddmmyyyy(as_of)}", {"balance": balance, "history": []})
        datasets["contracts"] = _set("contracts", as_of, contracts_source + (
            "; дальше — до плана эскроу финмодели" if escrow_plan is not None and
            ahead["contracts"] else
            "; дальше — рассрочка по подписанным договорам, равномерно до ввода"
            if ahead["contracts"] else ""),
            {"payments": payments + ahead["contracts"], "signed": signed})
        # Расторгнутые договоры контрактация не показывает: их поступлений в
        # графиках уже нет, отдельного прогноза возвратов в системе нет.
        datasets["refunds"] = _set("refunds", as_of, "расторгнутые договоры в контрактации не "
                                   "показываются — их поступлений в графиках нет",
                                   {"payments": []})
        if escrow_plan is not None:
            datasets["sales"] = _set("sales", as_of, "новые продажи — внутри ряда эскроу "
                                     "финмодели", {"payments": []})
        elif pace:
            datasets["sales"] = _set("sales", as_of, "новые продажи по нынешнему темпу "
                                     "подписания, равномерно до ввода (как в «Эскроу по "
                                     "кварталам» сводки)", {"payments": ahead["sales"]})

    datasets["disclosure"] = _set("disclosure", as_of, f"{words}; раскрытие всего эскроу в "
                                  "дату ввода (допущение: регистрация может сдвинуть позже)",
                                  {"items": [{"date": when, "amount": None, "confirmed": False,
                                              "final": True}]})
    for name, words in (("free_cash", "свободные деньги проекта"),
                        ("extra", "подтверждённое дополнительное финансирование")):
        datasets[name] = _set(name, as_of, f"{words} — нет ни в договорах, ни в РСС, ни в "
                              "финмодели: расчёт при их отсутствии", {"items": []})
    notes.append("Расчёт — при отсутствии дофинансирования и свободных денег проекта: их нет "
                 "ни в договорах, ни в РСС, ни в финмодели. Всё, что не покрыто раскрытием "
                 "эскроу, показано дефицитом; свободные деньги, если они есть, уменьшат его "
                 "на свою сумму.")
    datasets["letters_of_credit"] = _set(
        "letters_of_credit", as_of, "остатков на аккредитивах по кредитам нет ни в РСС, ни в "
        "финмодели — приняты равными нулю", {"balance": 0.0, "by_loan": {
            loan["id"]: 0.0 for loan in loans}})
    notes.append("Аккредитивы не учтены: остатков на них по кредитам нет ни в РСС, ни в "
                 "финмодели. По договору деньги на аккредитивах идут по пониженной ставке, "
                 "поэтому проценты здесь оценены сверху.")
    notes.append(f"Раскрытие эскроу принято в дату ввода {credit.ddmmyyyy(when)} ({words}). "
                 "На деле банк раскрывает эскроу после регистрации, это может быть позже — "
                 "тогда платежи до раскрытия потребуют больше денег вне эскроу.")
    if shift and shift.get("date") and shift["date"][:10] > when:
        notes.append(f"По темпу работ ввод может сдвинуться на {credit.ddmmyyyy(shift['date'])} "
                     f"({shift.get('source') or 'прогноз Монитора'}). Тогда эскроу раскроется "
                     "позже, и платежи банку до раскрытия придётся покрывать деньгами вне "
                     "эскроу; расчёт выше — к утверждённому сроку.")
    if bank:
        datasets["business_plan"] = _set("business_plan", sales_at or as_of,
                                         f"план банка, лист «{bank.get('sheet') or ''}»",
                                         _bank_plan(bank))

    if "draws" not in found:
        return out
    split, split_notes = _split(loans, found["draws"])
    notes += split_notes
    notes.append("РСС не называет, с какого кредита шла выдача: принято, что выдачи идут "
                 f"сначала по {loans[0]['short']} в пределах её лимита на дату, остаток — по "
                 f"{loans[-1]['short']}. Общий долг от этого не меняется; меняется, какой "
                 "кредит и когда гасится и какая ставка к нему применяется.")
    drawn_total = sum(amount for _, amount in found["draws"])
    future = _plan_draws(loans, credit_plan, drawn_total, as_of)
    if future is None:
        notes.append("Сроков будущих выдач в финмодели нет (строка «Проектное финансирование "
                     "(нараст)»): весь невыбранный лимит взят в последний день периода "
                     "доступности.")
    future, topped = _to_limit(loans, found["draws"], future or [], as_of)
    if topped:
        notes.append("Будущие выдачи до конца периода доступности доводят долг до лимита "
                     "(решение владельца 27.10.2026: «будущие выборки до РНВ = лимит»): сроки — "
                     "по плану финмодели, недостающее до лимита — в последний день доступности: "
                     + "; ".join(f"{short} — {credit.mln(amount, 1)} млн ₽ на "
                                 f"{credit.ddmmyyyy(day)}" for short, day, amount in topped)
                     + ".")
    start = (credit._day(found["draws"][0][0].replace(day=1)) - datetime.timedelta(days=1))
    if payments:
        first = credit._day(min(p["date"] for p in payments)).replace(day=1)
        start = min(start, first - datetime.timedelta(days=1))
    history: dict[str, Any] = {}
    for loan in loans:
        lid = loan["id"]
        history[f"facts.{lid}"] = _set(f"facts.{lid}", start.isoformat(), found["source"], {
            "debt": 0.0, "drawn": 0.0, "accrued_interest": 0.0, "accrued_fee": 0.0,
            "operations": []})
        history[f"deferred.{lid}"] = _set(f"deferred.{lid}", start.isoformat(),
                                          "досчёт от первой выдачи",
                                          {"deferred": 0.0, "interest_on_deferred": 0.0})
        history[f"plan.{lid}"] = _set(f"plan.{lid}", start.isoformat(), found["source"],
                                      {"draws": split[lid], "prepayments": []})
    for name in ("key_rate", "contracts", "sales", "refunds"):
        if name in datasets:
            history[name] = datasets[name]
    if rows:
        history["escrow"] = _set("escrow", start.isoformat(), contracts_source,
                                 {"balance": 0.0, "history": []})
    history["disclosure"] = _set("disclosure", start.isoformat(), "до даты РСС раскрытий нет",
                                 {"items": []})
    out["history"] = {"datasets": history, "start": start.isoformat(), "as_of": as_of,
                      "future": future, "split": split}
    return out


def _escrow_pace(rows: list[dict[str, Any]], credit_plan: dict[str, Any] | None,
                 when: str) -> dict[str, Any] | None:
    """Замер и темп эскроу — тот же вызов, что у сводки («Эскроу по кварталам»)."""
    if not credit_plan:
        return None
    got = contracting.escrow_sufficiency({}, rows, credit_plan, settle=when[:7])
    queues = got.get("queues") or []
    pace = queues[0] if queues else None
    if not pace or pace.get("owed") is None or not pace.get("data_month"):
        return None
    return pace


def _next_month(month: str) -> str:
    year, number = int(month[:4]), int(month[5:7])
    return f"{year + number // 12}-{number % 12 + 1:02d}"


def _escrow_forecast(pace: dict[str, Any], as_of: str, when: str
                     ) -> tuple[dict[str, list[dict[str, Any]]], float]:
    """Помесячные поступления по `keeping_at` до месяца ввода.

    Рассрочка подписанных договоров — «contracts», новые продажи по темпу —
    «sales»: сумма по месяц ввода равна прогнозу «к вводу» сводки. Месяцы до
    даты остатка (выгрузка продаж старше РСС) ложатся в сам остаток — второй
    раз они не считаются. Поступление месяца ввода датировано днём ввода.
    """
    settle, data_month = when[:7], pace["data_month"]
    out: dict[str, list[dict[str, Any]]] = {"contracts": [], "sales": []}
    months, month = [], data_month
    while month < settle:
        month = _next_month(month)
        months.append(month)
    if not months:
        return out, 0.0
    owed, sales_pace = float(pace["owed"] or 0.0), float(pace.get("sales_pace") or 0.0)
    folded = 0.0
    for month in months:
        steps = {"contracts": owed / len(months), "sales": sales_pace}
        if month <= as_of[:7]:
            folded += sum(steps.values())
            continue
        day = when if month == settle else _month_end(month)
        for kind, amount in steps.items():
            if amount > 0.5:
                out[kind].append({"date": day, "month_only": True, "amount": amount,
                                  "sale_month": month})
    return out, folded


def _plan_forecast(plan: dict[str, Any], balance: float, as_of: str, when: str
                   ) -> dict[str, list[dict[str, Any]]]:
    """Поступления, доводящие эскроу до плана финмодели на каждый месяц до ввода.

    Ряд финмодели — накопленный остаток; после месяца раскрытия он уже гасит
    кредит, поэтому берётся на месяц раскрытия (``cut``). Остаток выше плана
    не уменьшается: поступление не бывает отрицательным.
    """
    out: dict[str, list[dict[str, Any]]] = {"contracts": [], "sales": []}
    series, cut = plan.get("series") or {}, plan.get("cut") or ""
    settle, month, running = when[:7], as_of[:7], balance
    while month < settle:
        month = _next_month(month)
        target = contracting.plan_on(series, min(month, cut) if cut else month)
        if target is None or target <= running + 0.5:
            continue
        day = when if month == settle else _month_end(month)
        out["contracts"].append({"date": day, "month_only": True, "amount": target - running})
        running = target
    return out


def _bank_plan(bank: dict[str, Any]) -> dict[str, Any]:
    """План банка: остаток эскроу на конец квартала и продажи по кварталам.

    Первый квартал плана банка несёт продажи с начала проекта — с кварталом его
    сравнивать нельзя, он в план продаж не идёт.
    """

    escrow = contracting.bank_escrow_plan(bank)

    def quarter_end(quarter: str) -> str:
        year, part = quarter.split(" Q")
        return _month_end(f"{year}-{int(part) * 3:02d}")

    gross = bank.get("gross_by_quarter") or {}
    quarters = sorted(gross, key=quarter_end)
    return {"escrow": [{"date": quarter_end(q), "amount": v}
                       for q, v in sorted(escrow.items(), key=lambda x: quarter_end(x[0]))],
            "ddu": [{"quarter": q, "amount": float(gross[q])} for q in quarters[1:]]}
