"""Executive presentation of supplied schedule facts; no forecasting formulas."""
from __future__ import annotations

import html
import math

from developaid_schedule_visual import date_text, styles, unit_text


def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def stalled_text(items, basis=None):
    """Keep a known risk visible, with its supplied cause and no new forecast."""
    if not items:
        return ""
    shown = []
    for item in items[:3]:
        name = "«" + str(item.get("name") or item.get("id") or "Работа") + "»"
        if item.get("object"):
            name += " (" + str(item["object"]) + ")"
        reason = item.get("reason")
        if not reason:
            reason = ("В ГПР нет измеренного прироста процента выполнения."
                      if item.get("basis") == "gpr" or basis == "gpr" else
                      "Темп по актам слишком мал для надёжной оценки окончания."
                      if _number(item.get("monthly_rate")) else
                      "Подтверждённого темпа для прогноза нет.")
        shown.append(name + ": " + str(reason).rstrip(". ") + ".")
    text = "Работы почти стоят: " + " ".join(shown)
    if len(items) > 3:
        text += f" Ещё работ без прогноза: {len(items) - 3}."
    return text


def model(timeline: dict, *, stalled=None) -> dict:
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
        if (task.get("quantity_metric") or {}).get("ratio") is not None:
            facts.append({"name": task.get("name") or task.get("task_id"), "kind": "weighted_quantity",
                          "progress": task["quantity_metric"]["ratio"], "basis": task["quantity_metric"]["label"],
                          "date": task.get("progress_date"), "date_basis": "snapshot",
                          "observation_history": task.get("observation_history")})
        for component in task.get("components") or []:
            done, plan = component.get("completed_quantity"), component.get("plan_quantity")
            if _number(done):
                facts.append({"name": task.get("name") or task.get("task_id"),
                              "component": component.get("component_id") or "", "kind": "quantity",
                              "done": done, "plan": plan if _number(plan) else None,
                              "unit": component.get("unit") or "",
                              "date": component.get("observation_date") or component.get("period_end"),
                              "date_basis": component.get("progress_date_basis"),
                              "progress": component.get("progress"),
                              "observation_history": component.get("observation_history")})
    for cohort in physical.get("source_cohorts") or []:
        measured = cohort.get("model") or {}
        if _number(measured.get("progress")):
            facts.append({"name": cohort.get("source_scope") or cohort.get("source_name") or "Общая группа КС",
                          "kind": "source_cohort", "progress": measured["progress"],
                          "date": measured.get("progress_date"), "date_basis": measured.get("progress_date_basis"),
                          "basis": measured.get("progress_basis"), "task_ids": cohort.get("task_ids") or [],
                          "observation_history": measured.get("observation_history"),
                          "source_conflict": cohort.get("source_conflict")})
        else:
            for component in measured.get("components") or []:
                if _number(component.get("completed_quantity")):
                    facts.append({"name": cohort.get("source_scope") or cohort.get("source_name") or "Общая группа КС",
                                  "kind": "quantity", "done": component["completed_quantity"],
                                  "plan": component.get("plan_quantity"), "unit": component.get("unit") or "",
                                  "date": component.get("observation_date") or component.get("period_end"),
                                  "date_basis": component.get("progress_date_basis"),
                                  "shared_task_ids": cohort.get("task_ids") or []})
    covered_summaries, covered_components = [], []
    for group in physical.get('covered_source_groups') or []:
        measured, coverage = group.get('model') or {}, group.get('coverage') or {}
        context = {'name': group.get('source_name') or 'Раздел КС', 'source_scope': group.get('source_scope') or '',
            'contractor': group.get('contractor'), 'contract': group.get('contract'), 'period_year': group.get('period_year'),
            'source_group_id': group.get('group_id'), 'source_scope_only': True,
            'target_scope_confirmed': False, 'scope_reason': group.get('scope_reason') or '',
            'coverage': coverage, 'date': measured.get('progress_date'),
            'date_basis': measured.get('progress_date_basis'), 'basis': measured.get('progress_basis'),
            'observation_history': measured.get('observation_history')}
        if _number(measured.get('progress')):
            covered_summaries.append(dict(context, kind='covered_source_scope', progress=measured['progress']))
        else:
            for component in measured.get('components') or []:
                if _number(component.get('completed_quantity')):
                    covered_components.append(dict(context, kind='quantity',
                        component=component.get('name') or component.get('component_id'),
                        done=component['completed_quantity'], plan=component.get('plan_quantity'),
                        unit=component.get('unit') or '', progress=component.get('progress'),
                        date=component.get('observation_date') or component.get('period_end'),
                        date_basis=component.get('progress_date_basis'),
                        observation_history=component.get('observation_history')))
    # Present ongoing known source measures first. The full, qualified list
    # remains in the appendix; none of these is a whole-GPR-package fraction.
    covered_summaries.sort(key=lambda fact: not (0 < fact['progress'] < 1))
    facts.extend(covered_summaries)
    facts.extend(covered_components)
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
            "approved_source": rnv.get("approved_source"), "approved_rnv": rnv.get("approved_rnv", rnv.get("approved")),
            "owner_rnv": rnv.get("owner_rnv"), "plan_conflicts": rnv.get("plan_conflicts") or [],
            "planned_construction_finish": rnv.get("planned_construction_finish"),
            "plan_label": rnv.get("plan_label") or "План ввода",
            "plan_date": rnv.get("plan_date") or rnv.get("approved"),
            "forecast_label": qualification, "caveat": caveat,
            "delay_days": rnv.get("delay_days") if forecast else None,
            "driver": driver.get("name") or "", "driver_reason": driver.get("reason") or "",
            "driver_method": driver.get("method"), "facts": facts, "source_status": status,
            "completed_facts": physical.get("completed_facts"),
            "completed_facts_html": physical.get("completed_facts_html") or "",
            "stalled_text": stalled_text(stalled or [], rnv.get("basis")),
            "action": action, "reasons": reasons,
            "source_label": "ГПР и накопительные" if any(f["kind"] != "done" for f in facts) else "ГПР",
            # Comparison is a separate operation; no result does not imply no files.
            "version_comparison": timeline.get("version_comparison") or {"state": "not_calculated"}}


def fact_text(fact):
    if fact["kind"] == "done":
        return f"{fact['name']}: завершение подтверждено {date_text(fact['date'])}."
    number = lambda value: f"{value:g}".replace(".", ",")
    if fact['kind'] == 'covered_source_scope':
        identity = ' · '.join(str(value) for value in (fact.get('contractor'), fact.get('contract'), fact.get('period_year')) if value)
        return (f"{fact['name']}: {number(fact['progress']*100)}% по объёмам охваченного раздела КС"
                + (' от '+date_text(fact['date']) if fact.get('date') else '')
                + ('; '+identity if identity else '')
                + ('; '+fact['source_scope'] if fact.get('source_scope') else '')
                + '. '+str(fact.get('scope_reason') or 'Полнота всего пакета ГПР не подтверждена.'))
    if fact["kind"] in {"source_cohort", "weighted_quantity"}:
        snapshot = fact.get("date_basis") == "snapshot"
        return (f"{fact['name']}: {number(fact['progress']*100)}% "
                + ("по ведомости" if snapshot else "по датированным периодам")
                + ((" от " if snapshot else " на ") + date_text(fact["date"]) if fact.get("date") else "")
                + (f"; общий объём для {len(fact['task_ids'])} работ, отдельные проценты не выделены"
                   if fact["kind"] == "source_cohort" else "; " + str(fact.get("basis") or "")) + ".")
    amount = number(fact["done"])
    if fact.get("plan") is not None:
        amount += " из " + number(fact["plan"])
    name = fact["name"] + (" / " + str(fact["component"]) if fact.get("source_scope_only") and fact.get("component") else "")
    return (f"{name}: {amount} {unit_text(fact['unit'])}"
            + ((" по ведомости от " if fact.get("date_basis") == "snapshot" else " на ")
               + date_text(fact['date']) if fact.get("date") else "")
            + ("; общий объём группы" if fact.get("shared_task_ids") else "")
            + ("; охваченная часть КС, полный пакет ГПР не подтверждён" if fact.get("source_scope_only") else "") + ".")


def conclusion(block):
    parts = []
    if block.get("approved"):
        parts.append("План ввода — " + date_text(block["approved"]) + ".")
    elif block.get("planned_construction_finish"):
        parts.append("План окончания строительных работ — " + date_text(block["planned_construction_finish"]) + ". Срок РНВ в этом ГПР не указан.")
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
    if block.get("stalled_text"):
        parts.append(block["stalled_text"])
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
           '<div><span>'+esc(block.get("plan_label") or "План ввода")+'</span><strong>'+esc(date_text(block.get("plan_date") or block.get("approved")))+'</strong></div>',
           '<div class="schedule-warning"><span>'+esc(block["forecast_label"])+
           '</span><strong>'+esc(forecast)+'</strong></div>',
           '<div><span>'+('Отклонение по части работ' if block["state"] == "partial" else 'Отклонение от плана')+
           '</span><strong>'+esc(delay)+'</strong></div></div>']
    if block.get("caveat"):
        out.append('<p class="schedule-note executive-qualification">'+esc(block["caveat"])+'</p>')
    out.append(block.get('completed_facts_html') or '')
    if block.get("driver"):
        out.append('<p><b>На срок влияет:</b> '+esc(block["driver"])+'.</p>')
    if block.get("stalled_text"):
        out.append('<p class="executive-stalled">'+esc(block["stalled_text"])+'</p>')
    if block.get("facts"):
        out.append('<h4>Выполнение по источникам</h4><ul class="executive-facts">')
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
    owner = block.get('owner_rnv')
    if owner:
        out.append('<p>План РНВ владельца: '+esc(date_text(owner['date']))+'. '+
                   esc(owner.get('note') or '')+'</p>')
    inventory = block.get('completed_facts') or {}
    if len(inventory.get('qualified_task_completions') or []) > 3:
        from developaid_schedule_completed_facts import render as completed_render
        out.append(completed_render(inventory, expanded=True))
    if block.get("driver_reason"):
        out.append('<p class="note">Основание оценки работы «'+esc(str(block.get("driver") or ""))+
                   '»: '+esc(str(block["driver_reason"]))+'</p>')
    if len(block.get("facts") or []) > 5:
        out.append('<h4>Все подтверждённые показания</h4><ul>')
        out.extend('<li>'+esc(fact_text(f))+'</li>' for f in block["facts"])
        out.append('</ul>')
    out.extend('<p class="note">'+esc(str(reason))+'</p>' for reason in block.get("reasons") or [])
    out.append('<p class="note">Общий процент разных видов работ показан только при известных полных весах стоимости СМР. '
               'Объём общей группы не распределяется между отдельными работами.</p>')
    comparison = block.get("version_comparison") or {}
    if comparison.get("state") == "not_calculated":
        out.append('<p class="note">Сравнение версий ГПР пока не рассчитано.</p>')
    out.append('</div>')
    return ''.join(out)
