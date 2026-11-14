"""AHR budget minus observed paid cash. Read-only, source-bound, never bank coverage."""
from __future__ import annotations
import calendar
import contextlib
import datetime as dt
from decimal import Decimal, InvalidOperation
import hashlib
import html
import io
import json
import math
import os
from pathlib import Path
import re
import stat

import developaid_actuals as actuals
import developaid_admin_expenses_source as source
import developaid_budget_funding_source as rss_source
import developaid_monthly_budget as monthly
import developaid_monitor as monitor

ARTICLE='project_management'
FACTOR=1000  # Existing native cf_1_new contract; never an observed-header declaration.
STRONG={'по договору и коду РСС','по договору'}
FIELDS=(('budget','Бюджет АХР по сохранённой ФМ'),('paid_observed_net','Учтено оплат АХР'),
        ('balance_after_observed_payments','Остаток после учтённых оплат'),('observed_overspend','Перерасход по учтённым оплатам'))


def number(v):
    if v is None or isinstance(v,bool):return None
    try:x=Decimal(str(v).replace(' ','').replace('\xa0','').replace('\u202f','').replace(',','.'))
    except (InvalidOperation,ValueError):return None
    return x if x.is_finite() else None


def scalar(v):
    if v is None:return None
    x=float(v)
    return x if math.isfinite(x) else None


def total(values):
    values=list(values);known=[v for v in values if v is not None]
    return sum(known,Decimal(0)) if known and len(known)==len(values) else None


def fm_budget(data):
    from openpyxl import load_workbook
    from openpyxl.utils.cell import coordinate_from_string,column_index_from_string
    leaves,headers,units=source._cells(data)
    sums={k:total(number(r['cells'][k]['cached_value']) for r in leaves) for k in ('total','fact','plan')}
    columns={k:column_index_from_string(coordinate_from_string(ref)[0])-1 for k,ref in headers.items()}
    parent=None;tax=[];all_tax_codes=[]
    with contextlib.closing(load_workbook(io.BytesIO(data),read_only=True,data_only=True,keep_links=False)) as book:
        sheet=book['cf_1_new']
        for index,cells in enumerate(sheet.iter_rows(max_col=max(2,*columns.values())+1),1):
            code=str(cells[2].value or '').strip().rstrip('.')
            if code!='2.4' and not(code=='2.4.5' or code.startswith('2.4.5.')):continue
            row={'code':code,'row':index,'cells':{k:f'{coordinate_from_string(headers[k])[0]}{index}' for k in columns},
                 **{k:scalar(number(source._raw(cells[c])['cached_value'])*FACTOR) if number(source._raw(cells[c])['cached_value']) is not None else None for k,c in columns.items()}}
            if code=='2.4':
                if parent is not None:raise source.SourceProblem('codes_ambiguous')
                parent=row
            else:tax.append(row);all_tax_codes.append(code)
    tax_leaves=[r for r in tax if not any(c.startswith(r['code']+'.') for c in all_tax_codes)]
    tax_known=len(set(all_tax_codes))==len(all_tax_codes)
    taxes={k:(scalar(total(number(r[k]) for r in tax_leaves)) if tax_leaves else 0.0) if tax_known else None for k in sums}
    normalized={k:scalar(v*FACTOR) if v is not None else None for k,v in sums.items()}
    all_children={k:scalar(number(normalized[k])+number(taxes[k])) if normalized[k] is not None and taxes[k] is not None else None for k in sums}
    differences={k:scalar(number(parent[k])-number(all_children[k])) if parent and parent[k] is not None and all_children[k] is not None else None for k in sums}
    return {'budget':normalized['total'],'fm_columns_context_only':normalized,'taxes_separate':taxes,
        'parent_2_4':parent,'all_child_leaf_sum_including_tax':all_children,'parent_minus_all_children':differences,
        'parent_minus_non_tax_leaves':{k:scalar(number(parent[k])-number(normalized[k])) if parent and parent[k] is not None and normalized[k] is not None else None for k in sums},
        'leaf_count':len(leaves),'cells':{k:[r['cells'][k]['cell'] for r in leaves] for k in sums},
        'factor_to_rubles':FACTOR,'unit_basis':'existing_native_finmodel_contract','raw_unit_evidence':units,
        'budget_definition':'non-tax leaf2.4; parent is diagnostic only; financing excluded'}


def selected_months(parsed_files):
    """Files arrive in canonical newest-upload order. Latest NULL is final."""
    selected={}
    for origin,parsed in parsed_files:
        for month,value in parsed.get('months',{}).items():
            if month not in selected:
                selected[month]={'fact':(value.get('extra',{}).get('admin')or{}).get('fact'),
                    'plan':(value.get('extra',{}).get('admin')or{}).get('plan'),'source':{k:v for k,v in origin.items() if not k.startswith('_')},
                    'basis':'monthly_budget_admin_fact','monthly_semantics':'explicit month header + FACT subcolumn'}
    return selected


def calculate(budget, payments, register, crosswalk, bdds, cut):
    cut=dt.date.fromisoformat(cut);events=[];future=0;eligible=[];fingerprints={};duplicate_rows=set();duplicate_months=set()
    for item in payments.get('rows',[]):
        day=item.get('date')
        if day is not None and day>cut:future+=1;continue
        eligible.append(item)
        if day is not None:
            key=(day,item.get('amount'),item.get('estimate_code'),item.get('contractor'),item.get('contract'),item.get('source'))
            if key in fingerprints:duplicate_rows.update((item.get('source_row'),fingerprints[key]))
            fingerprints[key]=item.get('source_row')
    actuals.payments_by_article({'rows':eligible,'total':None},register,crosswalk=crosswalk,
                               classification_observer=events.append)
    rss_months={};uncertain={};unknown_date=0
    for event in events:
        possible=event['scope_unknown'] or ARTICLE in event['possible_articles']
        day=event['date'];month=day.replace(day=1).isoformat() if day else None
        if month and possible and event['source_row'] in duplicate_rows:duplicate_months.add(month)
        if day is None:
            if possible:unknown_date+=1
            continue
        if event['article']==ARTICLE:
            cell=rss_months.setdefault(month,{'amount':Decimal(0),'rows':0,'strong':Decimal(0),'basis':{}})
            amount=number(event['amount'])
            if amount is not None:
                cell['amount']+=amount;cell['rows']+=1
                cell['basis'][event['basis']]=cell['basis'].get(event['basis'],Decimal(0))+amount
                if event['basis'] in STRONG:cell['strong']+=amount
            if event['basis']not in STRONG:uncertain[month]=uncertain.get(month,0)+1
        elif possible and (event['article'] is None or event['basis']not in STRONG):
            uncertain[month]=uncertain.get(month,0)+1
    months=sorted(set(m for m in bdds if m<=cut.replace(day=1).isoformat())|set(rss_months)|set(uncertain)|{cut.replace(day=1).isoformat()})
    if months:
        start=dt.date.fromisoformat(months[0]);all_months=[]
        while start<=cut:
            all_months.append(start.isoformat())
            if len(all_months)>1200:raise ValueError('period outside supported history')
            start=(start.replace(day=28)+dt.timedelta(days=4)).replace(day=1)
        months=all_months
    chosen=[];paid=[];missing=[];soft=[]
    for month in months:
        day=dt.date.fromisoformat(month);closed=dt.date(day.year,day.month,calendar.monthrange(day.year,day.month)[1])<=cut
        doc=bdds.get(month);booked=number(doc.get('fact')) if doc else None;cash=rss_months.get(month)
        if closed and booked is not None:
            amount=booked;origin='budget_month_fact';complete=True
        elif cash is not None:
            amount=cash['amount'];origin='rss_observed';complete=not uncertain.get(month) and month not in duplicate_months
        else:
            amount=None;origin='unknown';complete=False
        if amount is not None:paid.append(amount)
        if not complete:missing.append(month)
        if origin=='rss_observed' and uncertain.get(month):soft.append(month)
        chosen.append({'month':month,'source':origin,'paid':scalar(amount),'coverage_known':complete,
            'budget_fact':scalar(booked),'budget_fact_included':origin=='budget_month_fact',
            'budget_current_month_not_dated':not closed and booked is not None,
            'budget_source':doc.get('source') if doc else None,
            'rss_observed_context':scalar(cash['amount']) if cash else None,
            'rss_classification_basis':{k:scalar(v)for k,v in (cash or{}).get('basis',{}).items()},
            'possible_ahr_unresolved_rows':uncertain.get(month,0),'duplicate_suspected':month in duplicate_months})
    known=sum(paid,Decimal(0)) if paid else None;B=number(budget.get('budget'))
    balance=B-known if B is not None and known is not None else None
    complete=not missing and not unknown_date
    return {'state':'ok' if complete else 'partial','scope':'current_saved_budget_minus_observed_paid_at_cut',
        'cut':cut.isoformat(),'budget':scalar(B),'paid_observed_net':scalar(known),'paid_known_part':scalar(known),
        'balance_after_observed_payments':scalar(balance),'observed_overspend':scalar(max(Decimal(0),-balance)) if balance is not None else None,
        'remaining_need':None,  # No source attests complete paid history since project start.
        'remaining_need_state':'project_start_coverage_not_attested',
        'coverage':{'known_for_observed_period':complete,'missing_or_uncertain_months':missing,
            'unknown_date_possible_ahr_rows':unknown_date,'classified_not_strong_months':soft,
            'future_rows_excluded':future,'duplicate_suspected_months':sorted(duplicate_months),
            'possible_ahr_unresolved_by_month':uncertain,
            'excluded_non_ahr_classified_rows':sum(e['article'] is not None and e['article']!=ARTICLE for e in events),
            'project_start_coverage_not_attested':True},
        'months':chosen,'fm':budget,'financial_acceptance':False,
        'paid_classification_basis':{m:{k:scalar(v)for k,v in cell['basis'].items()}for m,cell in rss_months.items()},
        'source_preference':'closed-month BDDS admin FACT replaces RSS month; otherwise dated RSS known part; never add both',
        'warning':'Показан остаток после учтённых оплат. Неполные периоды и неоднозначные платежи могут изменить его; это не подтверждённая потребность и не граница оценки.' if not complete else
                  'Расчёт по загруженным данным; полнота с начала проекта отдельно не подтверждена.'}


def _read_file(path,limit=source.MAX_SOURCE):
    parent=os.open('/',os.O_RDONLY|os.O_DIRECTORY)
    try:
        for component in Path(path).absolute().parts[1:-1]:
            child=os.open(component,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=parent)
            os.close(parent);parent=child
        fd=os.open(Path(path).name,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=parent)
    finally:os.close(parent)
    try:
        before=os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink!=1 or before.st_size>limit:raise ValueError('unsafe or oversized saved source')
        pieces=[];size=0
        while True:
            part=os.read(fd,min(65536,limit+1-size))
            if not part:break
            pieces.append(part);size+=len(part)
            if size>limit:raise ValueError('saved source size limit')
        after=os.fstat(fd)
        if(before.st_dev,before.st_ino,before.st_size,before.st_mtime_ns)!=(after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns):raise ValueError('source changed')
        data=b''.join(pieces)
        return data,hashlib.sha256(data).hexdigest()
    finally:os.close(fd)


def _namespace(project):
    """Native one-hop alias selection, without creating a project directory."""
    audit=source.audit
    base=monitor._SNAPSHOT_DIR.absolute()
    reader=audit.Reader(base,'aliases')
    try:
        aliases=reader.read('.aliases.json')
        value=audit._json(aliases[0]) if aliases else {'aliases':{}}
        if not isinstance(value,dict) or not isinstance(value.get('aliases'),dict):raise ValueError('project_identity_invalid')
        original=audit._namespace(monitor._slug(project))
        selected=audit._namespace(value['aliases'].get(original,original))
        if selected in value['aliases'] and value['aliases'][selected]!=selected:raise ValueError('project_identity_invalid')
        native=audit.Reader(base/selected,'finance')
        try:
            info=os.fstat(native.rootfd);native.check_identity()
            identity={'namespace_sha256':hashlib.sha256(selected.encode()).hexdigest(),
                'aliases_sha256':aliases[1]['sha256'] if aliases else None}
            return base/selected,identity,(info.st_dev,info.st_ino)
        finally:native.close()
    finally:reader.close()


def _budget_listing(root,cut):
    """Same native eligibility/upload order; fixed existing directory, no mkdir."""
    project=source.audit.Reader(root,'finance')
    try:
        try:folder=os.open('budget',os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=project.rootfd)
        except FileNotFoundError:return [],None
        try:
            info=os.fstat(folder);manifest=root/'budget'/monthly._UPLOADS
            try:
                raw,digest=_read_file(manifest,65536);uploads=source.audit._json(raw)
                if not isinstance(uploads,dict) or any(not isinstance(k,str) or not isinstance(v,str) for k,v in uploads.items()):raise ValueError('budget_upload_order_invalid')
            except FileNotFoundError:uploads={};digest=None
            entries=[]
            with os.scandir(folder) as scanned:
                for entry in scanned:
                    if not entry.name.endswith('.xlsx'):continue
                    path=root/'budget'/entry.name
                    if not monthly._known_by(path,cut):continue
                    details=entry.stat(follow_symlinks=False)
                    if not stat.S_ISREG(details.st_mode) or details.st_nlink!=1:raise ValueError('unsafe_budget_file')
                    stamp=uploads[entry.name] if entry.name in uploads else dt.datetime.fromtimestamp(details.st_mtime,dt.timezone.utc).isoformat(timespec='microseconds')
                    entries.append((path,stamp,(details.st_dev,details.st_ino,details.st_size,details.st_mtime_ns)))
                    if len(entries)>128:raise ValueError('too_many_budget_files')
            entries.sort(key=lambda x:(x[1],x[0].name),reverse=True)
            project.check_identity()
            return [x[0] for x in entries],(info.st_dev,info.st_ino,digest,tuple((x[0].name,x[1],x[2]) for x in entries))
        finally:os.close(folder)
    finally:project.close()


def _budget_months(paths):
    selected={};origins=[];errors=[];blocked=set();unknown_scope=False;read_bytes=0
    for path in paths:
        try:
            raw,digest=_read_file(path);read_bytes+=len(raw)
            if read_bytes>256*1024*1024:raise ValueError('budget_read_limit')
            origin={'sha256':digest,'file':path.stem[:10],'_path':str(path)}
            origins.append(origin)
            parsed=monthly.read_budget(raw)
            choices=selected_months([(origin,parsed)])
            for month,item in choices.items():
                if month not in selected and month not in blocked and not unknown_scope:selected[month]=item
        except Exception:
            # Newer successfully parsed facts stay known. A bad source prevents
            # fallback only within its filename period, or all older/unseen
            # months when its scope cannot be established.
            errors.append({'file':path.stem[:10],'state':'unreadable'})
            parts=path.stem.split('_')
            if len(parts)==3 and all(re.fullmatch(r'[0-9]{4}-[0-9]{2}',v) for v in parts[1:]):
                try:
                    first=dt.date.fromisoformat(parts[1]+'-01');last=dt.date.fromisoformat(parts[2]+'-01')
                    if last<first or (last.year-first.year)*12+last.month-first.month>1200:raise ValueError()
                    while first<=last:
                        blocked.add(first.isoformat());first=(first.replace(day=28)+dt.timedelta(days=4)).replace(day=1)
                except ValueError:unknown_scope=True
            else:unknown_scope=True
    return selected,origins,errors


def for_project(project,cut):
    """Independent source components survive another source's read failure."""
    empty={'budget':None};errors={};budget=empty;fm=None;meta={};identity={};rss=None;rss_id={};bdds={};origins=[]
    try:
        day=dt.date.fromisoformat(str(cut));root,namespace,root_stamp=_namespace(project)
        try:
            fm,meta,identity=source._copy(project)
            if any(identity.get(k)!=v for k,v in namespace.items()):raise ValueError('finance_namespace_changed')
        except Exception:fm=None;errors['fm']='unavailable'
        if fm is not None:
            try:budget=fm_budget(fm)
            except Exception:errors['fm_budget']='unavailable'
        try:
            rss,_,rss_id=rss_source._rss_copy(project,day.isoformat())
            if rss is not None and any(rss_id.get(k)!=v for k,v in namespace.items()):raise ValueError('rss_namespace_changed')
        except Exception:rss=None;errors['rss']='unavailable'
        listing=None
        try:
            paths,listing=_budget_listing(root,day.isoformat());bdds,origins,budget_errors=_budget_months(paths)
            if budget_errors:errors['budget_files']=budget_errors
        except Exception:errors['budget_files']='unavailable'
        register={'rows':[]};crosswalk=None;registry_known=crosswalk_known=False
        if fm is not None:
            try:register=actuals.read_register(io.BytesIO(fm));registry_known=True
            except Exception:errors['register']='unavailable'
            try:crosswalk=actuals.read_article_crosswalk(io.BytesIO(fm));crosswalk_known=True
            except Exception:errors['crosswalk']='unavailable'
        payments={'rows':[]}
        if rss is not None:
            try:payments=actuals.read_payments(io.BytesIO(rss),include_incomplete=True)
            except Exception:errors['rss']='parse_error'
        # Check each independently pinned component again. Failure drops that
        # component, not known money from unrelated saved sources.
        if fm is not None:
            try:
                _,again_meta,again_id=source._copy(project)
                if meta!=again_meta or identity!=again_id:raise ValueError('finance_changed')
            except Exception:budget=empty;register={'rows':[]};crosswalk=None;registry_known=crosswalk_known=False;errors['fm']='changed_or_unavailable'
        if rss is not None:
            try:
                _,_,again_id=rss_source._rss_copy(project,day.isoformat())
                if rss_id!=again_id:raise ValueError('rss_changed')
            except Exception:payments={'rows':[]};errors['rss']='changed_or_unavailable'
        if listing is not None:
            try:
                if _budget_listing(root,day.isoformat())[1]!=listing:raise ValueError('budget_changed')
                if any(_read_file(Path(item['_path']))[1]!=item['sha256'] for item in origins):raise ValueError('budget_bytes_changed')
            except Exception:bdds={};origins=[];errors['budget_files']='changed_or_unavailable'
        if _namespace(project)!=(root,namespace,root_stamp):raise ValueError('project_namespace_changed')
        result=calculate(budget,payments,register,crosswalk,bdds,day.isoformat())
        result['coverage']['source_errors']=errors
        result['coverage']['rss_source_state']=rss_id.get('state','unavailable')
        if errors:
            result['remaining_need']=None;result['state']='partial'
            result['warning']='Часть сохранённых источников не прочитана. Известные бюджет и оплаты сохранены. '+result['warning']
        result['sources']={'fm':{**identity,'version_date':meta.get('taken_at')},'rss':rss_id,
            'budget_files':[{k:v for k,v in item.items() if not k.startswith('_')} for item in origins],'registry_available':registry_known,'crosswalk_available':crosswalk_known}
        return result
    except Exception:
        return {'state':'missing','budget':None,'paid_observed_net':None,'balance_after_observed_payments':None,
            'observed_overspend':None,'remaining_need':None,'financial_acceptance':False,
            'warning':'Расчёт АХР по сохранённым источникам не получен. Обновите просмотр; повторная загрузка файлов не требуется.'}


def money(value,compact=False):
    if value is None:return 'нет данных'
    if compact and abs(value)>=1000000:return f'{value/1000000:,.2f}'.replace(',',' ').replace('.',',')+' млн ₽'
    return f'{value:,.2f}'.replace(',',' ').replace('.',',')+' ₽'


def tiles(model):
    notes={'budget':'По сохранённой ФМ; налоги отдельно.',
           'paid_observed_net':'Известная часть оплат по загруженным источникам.',
           'balance_after_observed_payments':'Промежуточный остаток; полнота оплат не подтверждена.',
           'observed_overspend':'По учтённым оплатам; без добавления в бюджет.'}
    return [{'label':label,'value':money(model.get(key),compact=True),'note':notes[key],
             'group':'admin_expenses_cash','tone':'missing' if model.get(key)is None else ''}for key,label in FIELDS]


def render(model,source_html='',*,show_tiles=True):
    esc=lambda v:html.escape(str(v));out=['<section class="admin-expenses-cash"><h3>Административные расходы</h3>',
        '<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px">']
    for tile in tiles(model) if show_tiles else []:out.append(f'<div><small>{esc(tile["label"])}</small><div style="font-size:20px;font-weight:700">{esc(tile["value"])}</div></div>')
    out+=['</div>',f'<p>{esc(model.get("warning")or "")}</p>',
           '<p>Оплаты из месячного бюджета и РСС за один месяц не складываются. Эти расходы уже входят в бюджет проекта.</p>']
    if source_html:
        unit_note='Бюджет рассчитан по принятому формату сохранённой ФМ. Единица хранения в шапке отдельно не подтверждена.' if (model.get('fm',{}).get('raw_unit_evidence') or {}).get('state')!='observed' else 'Бюджет рассчитан по принятому формату сохранённой ФМ.'
        out.append('<details class="admin-fm-source"'+(' open' if not show_tiles else '')+'><summary>Данные ФМ</summary><p>'+esc(unit_note)+'</p>'+source_html+'</details>')
    out.append('<details><summary>Состав и охват оплат</summary>'+''.join(f'<p>{esc(label)}: {esc(money(model.get(key)))}</p>' for key,label in FIELDS)+'<table><tr><th>Месяц</th><th>Учтено</th><th>Источник</th></tr>')
    for row in model.get('months',[]):out.append(f'<tr><td>{esc(row["month"][:7])}</td><td>{esc(money(row["paid"]))}</td><td>{esc({"budget_month_fact":"Факт месячного бюджета","rss_observed":"Оплаты РСС","unknown":"Нет полного факта"}[row["source"]])}</td></tr>')
    out.append('</table></details></section>');return ''.join(out)
