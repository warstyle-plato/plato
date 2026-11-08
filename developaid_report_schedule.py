"""Executive presentation of supplied schedule facts; no forecasting formulas."""
from __future__ import annotations

import html
import math

from developaid_schedule_visual import date_text, styles, unit_text


def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def model(timeline: dict) -> dict:
    """Keep the qualification and known natural facts independent of pace."""
    rnv = timeline.get("rnv") or {}
    physical = timeline.get("physical") or {}
    state = rnv.get("state", "unknown")
    forecast = (rnv.get("forecast") if state in {"complete", "estimate"}
                else rnv.get("indicative_forecast") if state == "partial" else None)
    qualification = ("Прогноз ввода" if state == "complete" else
                     "Оценка окончания работ" if state == "estimate" else
                     "Оценка по части работ" if state == "partial" else "Оценка окончания")
    caveat = ("" if state == "complete" else
              "Оценка работ не подтверждает дату получения разрешения на ввод." if forecast else
              "Окончание работ пока не оценено.")
    facts = []
    for task in physical.get("tasks") or []:
        if task.get("actual_finish"):
            facts.append({"name": task.get("name") or task.get("task_id"), "kind": "done",
                          "date": task["actual_finish"]})
        for component in task.get("components") or []:
            done, plan = component.get("completed_quantity"), component.get("plan_quantity")
            if _number(done):
                facts.append({"name": task.get("name") or task.get("task_id"),
                              "component": component.get("component_id") or "", "kind": "quantity",
                              "done": done, "plan": plan if _number(plan) else None,
                              "unit": component.get("unit") or "", "date": component.get("period_end")})
    status = physical.get("evidence_status") or {
        "state": "unavailable", "reason": "Состояние натуральных объёмов пока не проверено.",
        "action": "Команде: проверьте источники и соответствия работ в Мониторе."}
    action = status.get("action") or ""
    if state in {"partial", "unknown"} and not action:
        action = "Команде: уточните оставшиеся работы и оценку их окончания в Мониторе."
    driver = next(iter(rnv.get("driving_chain") or []), {})
    if driver.get("method") == "plan" and state != "complete":
        caveat = "По плану ГПР; темп ещё не подтверждён. " + caveat
    reasons = list(rnv.get("reasons") or [])
    if rnv.get("basis") == "gpr":
        from developaid_schedule_gpr_forecast import ESTIMATE_NOTE
        reasons = ["Оценка относится к строительным работам. Этапы получения разрешения на ввод ею не подтверждены."
                   if reason == ESTIMATE_NOTE else reason for reason in reasons]
    return {"state": state, "approved": rnv.get("approved"), "forecast": forecast,
            "forecast_label": qualification, "caveat": caveat,
            "delay_days": rnv.get("delay_days") if forecast else None,
            "driver": driver.get("name") or "", "facts": facts, "source_status": status,
            "action": action, "reasons": reasons,
            "source_label": "ГПР и накопительные" if any(f["kind"] == "quantity" for f in facts) else "ГПР",
            # Comparison is a separate operation; no result does not imply no files.
            "version_comparison": timeline.get("version_comparison") or {"state": "not_calculated"}}


def fact_text(fact):
    if fact["kind"] == "done":
        return f"{fact['name']}: завершение подтверждено {date_text(fact['date'])}."
    number = lambda value: f"{value:g}".replace(".", ",")
    amount = number(fact["done"])
    if fact.get("plan") is not None:
        amount += " из " + number(fact["plan"])
    return (f"{fact['name']}: {amount} {unit_text(fact['unit'])}"
            + (f" на {date_text(fact['date'])}" if fact.get("date") else "") + ".")


def conclusion(block):
    parts = []
    if block.get("approved"):
        parts.append("План ввода — " + date_text(block["approved"]) + ".")
    if block.get("forecast"):
        parts.append(block["forecast_label"] + " — " + date_text(block["forecast"]) + ".")
        delay = block.get("delay_days")
        if _number(delay) and delay > 0:
            parts.append(f"Оценка позже плана на {delay:g} дн."
                         if block["state"] != "partial" else
                         f"По работам с оценкой — отставание {delay:g} дн.")
        elif _number(delay) and block["state"] == "complete":
            parts.append("Прогноз в пределах плана.")
    if block.get("caveat"):
        parts.append(block["caveat"])
    if block.get("driver"):
        parts.append("На срок влияет работа «" + block["driver"] + "».")
    return " ".join(parts)


def render(block):
    esc = lambda v: html.escape(str(v if v is not None else ""), quote=True)
    forecast = date_text(block.get("forecast")) if block.get("forecast") else "Не определена"
    delta = block.get("delay_days")
    delay = (f"{delta:+g} дн." if _number(delta) and block.get("forecast") else "Не определено")
    print_style = ('<style>.report-source-appendix{display:none}'
                   '@media print{.report-source-screen{display:none!important}'
                   '.report-source-appendix{display:block;break-before:page;page-break-before:always}}</style>')
    out = [styles(), print_style, '<section class="dependency-timeline schedule-overview executive-schedule">',
           '<h3>Сроки и выполнение работ</h3><div class="schedule-rnv-cards">',
           '<div><span>План ввода</span><strong>'+esc(date_text(block.get("approved")))+'</strong></div>',
           '<div class="schedule-warning"><span>'+esc(block["forecast_label"])+
           '</span><strong>'+esc(forecast)+'</strong></div>',
           '<div><span>'+('Отклонение по части работ' if block["state"] == "partial" else 'Отклонение от плана')+
           '</span><strong>'+esc(delay)+'</strong></div></div>']
    if block.get("caveat"):
        out.append('<p class="schedule-note executive-qualification">'+esc(block["caveat"])+'</p>')
    if block.get("driver"):
        out.append('<p><b>На срок влияет:</b> '+esc(block["driver"])+'.</p>')
    if block.get("facts"):
        out.append('<h4>Подтверждённое выполнение</h4><ul class="executive-facts">')
        out.extend('<li>'+esc(fact_text(f))+'</li>' for f in block["facts"][:5])
        out.append('</ul>')
        if len(block["facts"]) > 5:
            out.append('<p class="schedule-note">Ещё подтверждённых показаний: '+str(len(block["facts"])-5)+
                       '. Полный перечень — в источниках оценки.</p>')
    status = block["source_status"]
    if status.get("state") != "confirmed":
        out.append('<p class="executive-source-state">'+esc(status.get("reason"))+'</p>')
    if block.get("action"):
        out.append('<p class="executive-action"><b>'+esc(block["action"])+'</b></p>')
    out.append('</section>')
    return ''.join(out)


def details(block):
    esc = html.escape
    out = ['<div class="executive-source-content"><h3>Основания оценки сроков</h3>']
    if len(block.get("facts") or []) > 5:
        out.append('<h4>Все подтверждённые показания</h4><ul>')
        out.extend('<li>'+esc(fact_text(f))+'</li>' for f in block["facts"])
        out.append('</ul>')
    out.extend('<p class="note">'+esc(str(reason))+'</p>' for reason in block.get("reasons") or [])
    out.append('<p class="note">Разные натуральные объёмы показаны отдельно; общего физического процента по ним нет.</p>')
    comparison = block.get("version_comparison") or {}
    if comparison.get("state") == "not_calculated":
        out.append('<p class="note">Сравнение версий ГПР пока не рассчитано.</p>')
    out.append('</div>')
    return ''.join(out)
