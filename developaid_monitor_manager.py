"""Management aggregation for Project Monitor.

Keeps the weekly contract unchanged: fixed PM/GPR baseline + one RSS 6.1.2.
Physical progress is read only from ``Реестр выполненных работ``. Payments are
read only from ``Реестр платежей``. This module only aggregates those facts for
a director-friendly drill-down: control block -> DevelopAid article -> RSS -> WBS.
"""
from __future__ import annotations

import datetime
import re
from pathlib import Path
from typing import Any

import developaid_actuals as actuals
import developaid_monitor as monitor

_RISK = {"ОТСТАВАНИЕ", "НЕТ ТЕМПА / РИСК"}
_INSTALLED = False
_ORIGINAL_BUILD = None
_ORIGINAL_GANTT = None


def _natural(value: Any) -> tuple:
    return tuple((0, int(p)) if p.isdigit() else (1, p.lower())
                 for p in re.findall(r"\d+|[^\d]+", str(value or "")))


def _codes(value: Any) -> list[str]:
    return list(dict.fromkeys(x.rstrip(".") for x in re.findall(r"\d+(?:\.\d+)+", str(value or ""))))


def _control(code: str) -> str:
    if code.startswith("2.1"): return "Подготовка"
    if code.startswith(("2.2", "2.3")): return "Основные объекты"
    if code.startswith("2.4"): return "Наружные сети"
    if code.startswith("2.5"): return "Благоустройство"
    if code.startswith("2.6"): return "Служба заказчика"
    if code.startswith("2.7"): return "Проектирование"
    if code.startswith(("2.8", "2.9")): return "Резерв"
    return "Прочие СМР"


def _detail(code: str) -> str:
    if code.startswith("2.1"): return "Подготовительные работы"
    if code.startswith("2.2.1"): return "Основное строительство — подземная часть"
    if code.startswith(("2.2.2", "2.2.3", "2.3")): return "Основное строительство — надземная часть + ВИС"
    if code.startswith("2.4"): return "Наружные инженерные сети"
    if code.startswith("2.5"): return "Благоустройство"
    return _control(code)


def _baseline_mapping(project: str) -> dict[str, dict[str, str]]:
    """Use Project Control's RSS FACT crosswalk when it is embedded in baseline."""
    path = monitor._baseline_file(project)
    if path is None:
        return {}
    from openpyxl import load_workbook
    wb = load_workbook(path, read_only=True, data_only=True)
    try:
        if "РСС ФАКТ" not in wb.sheetnames:
            return {}
        out, header = {}, {}
        for values in wb["РСС ФАКТ"].iter_rows(values_only=True):
            norm = [re.sub(r"\s+", " ", str(v or "").strip().lower().replace("ё", "е")) for v in values]
            if not header and "код рсс" in norm and "статья developaid" in norm:
                header = {"code": norm.index("код рсс"), "article": norm.index("статья developaid")}
                if "статья рсс" in norm: header["rss_name"] = norm.index("статья рсс")
                continue
            if not header: continue
            code = actuals._code(values[header["code"]] if header["code"] < len(values) else None)
            if not code: continue
            article = str(values[header["article"]] or "").strip() if header["article"] < len(values) else ""
            rss_name = str(values[header.get("rss_name", -1)] or "").strip() if 0 <= header.get("rss_name", -1) < len(values) else ""
            low = article.lower().replace("ё", "е")
            detail = _detail(code)
            if "подзем" in low: detail = "Основное строительство — подземная часть"
            elif "надзем" in low or "назем" in low or "вис" in low: detail = "Основное строительство — надземная часть + ВИС"
            elif "подготов" in low: detail = "Подготовительные работы"
            elif "наруж" in low: detail = "Наружные инженерные сети"
            elif "благо" in low: detail = "Благоустройство"
            out[code] = {"rss_name": rss_name, "detail": detail, "control": _control(code)}
        return out
    finally:
        wb.close()


def _descendants(estimate: dict[str, Any], root: str) -> set[str]:
    children: dict[str, set[str]] = {}
    for row in estimate["rows"]:
        parent = str(row.get("parent") or "")
        if parent: children.setdefault(parent, set()).add(row["code"])
    selected, stack = set(), [root]
    while stack:
        code = stack.pop()
        if code in selected: continue
        selected.add(code); stack.extend(children.get(code, ()))
    return selected


def _metrics(estimate: dict[str, Any], works: dict[str, Any], code: str,
             cut: datetime.date) -> dict[str, Any]:
    matched = _descendants(estimate, code)
    eac = float((estimate["by_code"].get(code) or {}).get("estimate") or 0.0)
    rows = [r for r in works["rows"] if r.get("construction") and r.get("code") in matched
            and r.get("date") and r["date"] <= cut]
    accepted = sum(float(r.get("amount") or 0.0) for r in rows)
    recent = sum(float(r.get("amount") or 0.0) for r in rows if r["date"] > cut-datetime.timedelta(days=92))
    return {"eac": eac, "accepted": accepted,
            "progress": accepted/eac if eac > 0 else None,
            "rate": recent/eac/3 if eac > 0 else None,
            "last": max((r["date"] for r in rows), default=None)}


def _status(start: datetime.date, finish: datetime.date, cut: datetime.date,
            plan: float, fact: float | None, rate: float | None,
            forecast: datetime.date | None) -> str:
    if cut < start: return "ПО ПЛАНУ: НЕ НАЧАТО"
    if fact is None: return "НЕТ ДАННЫХ РСС"
    if fact >= 1: return "ЗАВЕРШЕНО"
    if (not rate or rate <= 1e-9) and fact < plan: return "НЕТ ТЕМПА / РИСК"
    if forecast and forecast > finish: return "ОТСТАВАНИЕ"
    return "В СРОК" if fact >= plan else "ОТСТАВАНИЕ"


def _forecast(cut: datetime.date, fact: float | None, rate: float | None,
              last: datetime.date | None) -> datetime.date | None:
    if fact is None: return None
    if fact >= 1: return last or cut
    if rate and rate > 1e-9:
        return cut + datetime.timedelta(days=round((1-max(0, fact))/rate*30.4375))
    return None


def _summary(children: list[dict[str, Any]], cut: datetime.date,
             name: str, key: str, level: str) -> dict[str, Any]:
    start, finish = min(x["plan_start"] for x in children), max(x["plan_finish"] for x in children)
    eac = sum(float(x.get("eac") or 0) for x in children)
    if eac > 0:
        plan = sum(float(x.get("plan_progress") or 0)*float(x.get("eac") or 0) for x in children)/eac
        accepted = sum(float(x.get("accepted") or 0) for x in children)
        fact = accepted/eac
        recent = sum(float(x.get("rate_3m") or 0)*float(x.get("eac") or 0)*3 for x in children)
        rate = recent/eac/3
    else:
        plan = sum(float(x.get("plan_progress") or 0) for x in children)/max(1, len(children)); accepted=0; fact=rate=None
    forecasts = [x.get("forecast_finish") for x in children if x.get("forecast_finish")]
    forecast = max(forecasts) if forecasts else None
    status = _status(start, finish, cut, plan, fact, rate, forecast)
    if any(x.get("status") == "НЕТ ТЕМПА / РИСК" for x in children) and status not in {"ЗАВЕРШЕНО","ПО ПЛАНУ: НЕ НАЧАТО"}:
        status = "НЕТ ТЕМПА / РИСК"
    duration=max(1,(finish-start).days)
    fact_date=start+datetime.timedelta(days=round(duration*min(max(fact or 0,0),1))) if fact is not None else None
    return {"key":key,"level":level,"name":name,"plan_start":start,"plan_finish":finish,
            "plan_progress":plan,"actual_progress":fact,"actual_equivalent_date":fact_date,
            "accepted":accepted,"eac":eac,"rate_3m":rate,"forecast_finish":forecast,
            "delta_days":(forecast-finish).days if forecast else None,"status":status,"children":children}


def _management(project: str, rss: Path, schedule: dict[str, Any]) -> list[dict[str, Any]]:
    estimate, works = actuals.read_estimate(rss), actuals.read_completed_works(rss)
    mapping, cut = _baseline_mapping(project), monitor._day(schedule["cut"])
    tasks_by_code: dict[str,list[dict[str,Any]]] = {}
    for task in schedule["rows"]:
        for code in _codes(task.get("code")): tasks_by_code.setdefault(code,[]).append(task)
    rss_rows=[]
    for code,tasks in tasks_by_code.items():
        start,finish=min(t["plan_start"] for t in tasks),max(t["plan_finish"] for t in tasks)
        m=_metrics(estimate,works,code,cut)
        weights=[max(1,(t["plan_finish"]-t["plan_start"]).days) for t in tasks]
        plan=sum(t["plan_progress"]*w for t,w in zip(tasks,weights))/sum(weights)
        forecast=_forecast(cut,m["progress"],m["rate"],m["last"])
        meta=mapping.get(code,{})
        rss_rows.append({"key":f"rss:{code}","level":"rss","code":code,
            "name":meta.get("rss_name") or (estimate["by_code"].get(code) or {}).get("article") or code,
            "control":meta.get("control") or _control(code),"detail":meta.get("detail") or _detail(code),
            "plan_start":start,"plan_finish":finish,"plan_progress":plan,"actual_progress":m["progress"],
            "actual_equivalent_date":start+datetime.timedelta(days=round(max(1,(finish-start).days)*min(max(m["progress"] or 0,0),1))) if m["progress"] is not None else None,
            "accepted":m["accepted"],"eac":m["eac"],"rate_3m":m["rate"],"forecast_finish":forecast,
            "delta_days":(forecast-finish).days if forecast else None,
            "status":_status(start,finish,cut,plan,m["progress"],m["rate"],forecast),"children":tasks})
    rss_rows.sort(key=lambda x:_natural(x["code"]))
    buckets: dict[tuple[str,str],list[dict[str,Any]]] = {}
    for row in rss_rows: buckets.setdefault((row["control"],row["detail"]),[]).append(row)
    details=[]
    for (control,detail),children in buckets.items():
        x=_summary(children,cut,detail,f"detail:{control}:{detail}","detail");x["control"]=control;x["sort_code"]=min((c["code"] for c in children),key=_natural);details.append(x)
    details.sort(key=lambda x:_natural(x["sort_code"]))
    cb: dict[str,list[dict[str,Any]]] = {}
    for row in details: cb.setdefault(row["control"],[]).append(row)
    controls=[]
    for control,children in cb.items():
        x=_summary(children,cut,control,f"control:{control}","control");x["sort_code"]=min((c["sort_code"] for c in children),key=_natural);controls.append(x)
    controls.sort(key=lambda x:_natural(x["sort_code"]))
    return controls


def _payment_baseline(project: str) -> dict[str, Any]:
    """Read project-level and control-block Plan from fixed CF ПЛАН-ФАКТ."""
    from openpyxl import load_workbook
    folder=monitor._project_dir(project)/"baseline"
    path=next((p for p in (folder/"finance.xlsx",folder/"gpr.xlsx") if p.exists()),None)
    if not path: return {"known":False,"series":{},"by_article":{}}
    wb=load_workbook(path,read_only=True,data_only=True)
    try:
        if "CF ПЛАН-ФАКТ" not in wb.sheetnames: return {"known":False,"series":{},"by_article":{}}
        rows=list(wb["CF ПЛАН-ФАКТ"].iter_rows(values_only=True)); plan_row=date_row=total_row=None
        for i,row in enumerate(rows):
            norm=[str(v or "").strip().lower().replace("ё","е") for v in row]
            if plan_row is None and norm.count("план")>=2:
                plan_row=i
                for j in range(i-1,max(-1,i-6),-1):
                    if sum(isinstance(v,(datetime.date,datetime.datetime)) for v in rows[j])>=2: date_row=j;break
            if row and str(row[0] or "").strip().lower()=="итого проект": total_row=i
        if plan_row is None or date_row is None or total_row is None: return {"known":False,"series":{},"by_article":{}}
        dates={};last=None
        for col,v in enumerate(rows[date_row]):
            if isinstance(v,datetime.datetime): last=v.date().replace(day=1)
            elif isinstance(v,datetime.date): last=v.replace(day=1)
            if last: dates[col]=last
        cols=[c for c,v in enumerate(rows[plan_row]) if str(v or "").strip().lower()=="план"]
        def series(row):
            out={}
            for c in cols:
                if c not in dates: continue
                v=actuals._money(row[c] if c<len(row) else None);out[dates[c].isoformat()]=v*(1e6 if abs(v)<100000 else 1)
            return out
        total=series(rows[total_row]);by={}
        for row in rows[plan_row+1:total_row]:
            label=str(row[0] or "").strip() if row else ""
            if label: by[label]=series(row)
        return {"known":bool(total),"series":total,"by_article":by}
    finally: wb.close()


def _payments(project: str, rss: Path) -> dict[str, Any]:
    baseline=_payment_baseline(project);p=actuals.read_payments(rss);total_fact={};article_fact={};code_fact={}
    for r in p["rows"]:
        if not r.get("date"): continue
        month=r["date"].replace(day=1).isoformat();amount=float(r.get("amount") or 0);code=str(r.get("estimate_code") or "").rstrip(".");article=_control(code) if code else "Не сопоставлено"
        total_fact[month]=total_fact.get(month,0)+amount;article_fact.setdefault(article,{})[month]=article_fact.setdefault(article,{}).get(month,0)+amount
        if code: code_fact.setdefault(code,{})[month]=code_fact.setdefault(code,{}).get(month,0)+amount
    months=sorted(set(total_fact)|set(baseline["series"]));rows=[]
    for m in months:
        plan=float(baseline["series"].get(m,0)) if baseline["known"] else None;fact=float(total_fact.get(m,0));rows.append({"month":m,"plan":plan,"fact":fact,"delta":fact-plan if plan is not None else None})
    articles=[]
    for name in sorted(set(baseline["by_article"])|set(article_fact)):
        ps,fs=baseline["by_article"].get(name,{}),article_fact.get(name,{});articles.append({"article":name,"plan":ps,"fact":fs,"plan_total":sum(ps.values()),"fact_total":sum(fs.values())})
    return {"known":baseline["known"],"source":"CF ПЛАН-ФАКТ" if baseline["known"] else "","rows":rows,
            "plan_total":sum(baseline["series"].values()) if baseline["known"] else None,"fact_total":sum(total_fact.values()),
            "last_fact":monitor._iso(p.get("last")),"articles":articles,"by_code_fact":code_fact,"fact_source":"Реестр платежей"}


def _attach_payments(nodes: list[dict[str,Any]], cash: dict[str,Any]) -> None:
    by_article={x["article"]:x for x in cash.get("articles",[])};by_code=cash.get("by_code_fact",{})
    def visit(n):
        if n.get("level")=="control":
            x=by_article.get(n["name"],{});n["payments"]={"plan":x.get("plan",{}),"fact":x.get("fact",{}),"plan_total":x.get("plan_total"),"fact_total":x.get("fact_total",0)}
        elif n.get("level")=="rss":
            f=by_code.get(n.get("code",""),{});n["payments"]={"plan":{},"fact":f,"plan_total":None,"fact_total":sum(f.values())}
        for c in n.get("children",[]):
            if isinstance(c,dict) and c.get("level"): visit(c)
    for n in nodes: visit(n)


def _build(project: str, cut: Any, programme=None, upto: str="") -> dict[str,Any]:
    view=_ORIGINAL_BUILD(project,cut,programme=programme,upto=upto);rss=monitor._latest(project,"estimate",".xlsx",upto)
    if rss is None: return view
    management=_management(project,rss,view["schedule"]);cash=_payments(project,rss);_attach_payments(management,cash)
    view["schedule"]["management"]=monitor._plain(management);view["schedule"]["fact_source"]="Реестр выполненных работ";view["payments"]=monitor._plain(cash)
    works=actuals.read_completed_works(rss);view["money"]["accepted"]=float(works.get("construction_dated") or 0);view["money"]["payment_fact"]=float(cash.get("fact_total") or 0)
    return view


def _gantt(project: str, cut: Any, upto: str="") -> dict[str,Any]:
    view=_build(project,cut,upto=upto);s=view["schedule"]
    return {"cut":view["cut"],"management":s.get("management",[]),"rows":s.get("rows",[]),"works":len(s.get("rows",[])),"overdue":s.get("risks",0),"baseline_end":s.get("baseline_end"),"forecast_end":s.get("forecast_end"),"source":{"schedule":"fixed-baseline","estimate":view["source"]["estimate"],"with_baseline":True,"fact":"Реестр выполненных работ","payments":"Реестр платежей"}}


def install() -> None:
    global _INSTALLED,_ORIGINAL_BUILD,_ORIGINAL_GANTT
    if _INSTALLED:return
    _ORIGINAL_BUILD,_ORIGINAL_GANTT=monitor.build,monitor.gantt;monitor.build,monitor.gantt=_build,_gantt;_INSTALLED=True
