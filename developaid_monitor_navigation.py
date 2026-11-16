"""One presentation and bounded UI context for Monitor and its management report.

The product destinations remain owned by management_contour.ROLES. This module
does not change the cabinet, authentication, data readers or saved source state.
"""
from __future__ import annotations

from html import escape
import json

import management_contour

VIEWS = (('monitor', 'ГПР: план и факт'), ('money', 'Деньги'),
         ('contracts', 'Договоры'), ('data', 'Данные и настройки'))

STYLE = """
/* shared-monitor-navigation */
.monitor-page-header{background:#fff;border-bottom:1px solid #dde5ed;padding:14px 22px;color:#16202b;font:15px/1.55 -apple-system,Segoe UI,Roboto,sans-serif}
.monitor-page-header .brand{display:block;margin-bottom:10px;line-height:0}
.monitor-page-header .brand img{height:26px;width:auto;display:block;mix-blend-mode:multiply}
.monitor-page-header h1{font-size:17px;margin:0}
.monitor-page-header .sub{color:#5b6b7d;font-size:13px;margin-top:2px}
.monitor-global-shell{box-sizing:border-box;display:flow-root;max-width:1080px;margin:0 auto;padding:22px 22px 0;color:#16202b;font:15px/1.55 -apple-system,Segoe UI,Roboto,sans-serif}
.monitor-host>.wrap{padding-top:0}
.monitor-tabs a{text-decoration:none;display:inline-flex;align-items:center}
@media print{.monitor-page-header,.monitor-global-shell,.monitor-tabs{display:none!important}}
"""


def markup(current: str) -> str:
    """Use the cabinet's actual global component, including every note."""
    return management_contour.markup(current)


def header_markup(current: str) -> str:
    """One host header for both pages, using the existing cabinet brand asset."""
    title, note = {
        '/monitor': ('Монитор проекта', 'Работы по ГПР, сроки и деньги проекта.'),
        '/report': ('Сводка руководству', 'Стройка, продажи, финансирование и бюджет за неделю или за месяц — для решений и рассылки'),
    }[current]
    return ('<header class="monitor-page-header">'
            '<a class="brand" href="/" title="DevelopAid"><img src="/guide/assets/logo.webp" alt="ПЛАТО" height="26"></a>'
            f'<h1>{escape(title)}</h1><div class="sub">{escape(note)} · версия __VERSION__</div></header>')


def view_markup(current: str) -> str:
    """Local project views belong below its context, outside the global menu."""
    views = []
    for key, name in VIEWS:
        if current == '/monitor':
            views.append(f'<button class="btn alt" type="button" id="{key}Tab" role="tab" '
                         f'aria-selected="{str(key == "monitor").lower()}" '
                         f'aria-controls="{key}Panel" tabindex="{0 if key == "monitor" else -1}" '
                         f'data-monitor-view="{key}">{escape(name)}</button>')
        else:
            views.append(f'<a class="btn alt" href="/monitor#tab={key}" data-monitor-view="{key}">{escape(name)}</a>')
    semantics = ' role="tablist"' if current == '/monitor' else ''
    return ('<nav class="monitor-tabs" aria-label="Виды Монитора"' + semantics + '>' + ''.join(views) + '</nav>')


SCRIPT = r"""
// UI state only. Credentials, fetched results and source/edit drafts never enter this store.
window.createMonitorNavigation=function(config){
 const STORE='developaid_monitor_navigation_v1',views=__MONITOR_NAVIGATION_VIEWS__;
 const fieldSets={monitor:['contractsSearch','contractsFilter','physicalReviewView','physicalReviewSearch','physicalReviewFilter','physicalSearch','physicalTask','physicalItems'],report:['reportKind']},fields=fieldSets[config.page];
 const byId=id=>document.getElementById(id),plain=x=>x&&typeof x==='object'&&!Array.isArray(x);
 const text=(v,n)=>typeof v==='string'&&v.length<=n&&!/[\u0000-\u001f]/.test(v)?v:'';
 const day=v=>/^\d{4}-\d{2}-\d{2}$/.test(v||'')?v:'';
 const sourceFields=['physicalTask','physicalItems'];
 function sourceToken(value){if(!plain(value)||Object.keys(value).sort().join(',')!=='snapshot_id,source_kind,source_sha256,version'||value.version!==1||value.source_kind!=='gpr'||typeof value.source_sha256!=='string'||!/^[0-9a-f]{64}$/.test(value.source_sha256)||typeof value.snapshot_id!=='string'||!/^\d{4}-\d{2}-\d{2}-[0-9a-f]{64}$/.test(value.snapshot_id))return null;const date=value.snapshot_id.slice(0,10);try{if(date.startsWith('0000')||new Date(date+'T00:00:00Z').toISOString().slice(0,10)!==date)return null;}catch(e){return null;}return{version:1,source_kind:value.source_kind,source_sha256:value.source_sha256,snapshot_id:value.snapshot_id};}
 function currentSource(){const value=config.sourceToken?.();return Array.isArray(value)&&value.length===3?sourceToken({version:1,source_kind:value[0],source_sha256:value[1],snapshot_id:value[2]}):null;}
 const sameSource=(a,b)=>a&&b&&a.version===b.version&&a.source_kind===b.source_kind&&a.source_sha256===b.source_sha256&&a.snapshot_id===b.snapshot_id;
 const context=()=>({project:text(byId('project').value.trim(),200),cut:day(byId('cut').value)});
 const same=(a,b)=>a&&b&&a.project===b.project&&a.cut===b.cut;
 const cleanFields=(value,page=config.page)=>{const out={};if(!plain(value))return out;for(const id of fieldSets[page]){const v=value[id];if(typeof v==='string'&&text(v,256)===v)out[id]=v;else if(id==='physicalItems'&&Array.isArray(v)&&v.length<=100&&v.every(x=>typeof x==='string'&&text(x,256)===x))out[id]=v.slice();}return out;};
 function read(){try{const raw=sessionStorage.getItem(STORE);if(!raw||raw.length>32768)return null;const v=JSON.parse(raw);if(!plain(v)||v.version!==1||!Array.isArray(v.scopes)||v.scopes.length>8)return null;const scopes=v.scopes.filter(x=>plain(x)&&text(x.project,200)&&day(x.cut)).map(x=>{const item={project:x.project,cut:x.cut,view:views.includes(x.view)?x.view:'monitor',monitor:cleanFields(x.monitor,'monitor'),report:cleanFields(x.report,'report')},token=sourceToken(x.physicalSource);if(token)item.physicalSource=token;else for(const id of sourceFields)delete item.monitor[id];return item;});const c=plain(v.current)&&text(v.current.project,200)&&day(v.current.cut)?{project:v.current.project,cut:v.current.cut}:null;return{version:1,current:c,scopes};}catch(e){return null;}}
 let state=read()||{version:1,current:null,scopes:[]},active=null,pending={},pendingSource=null,restoring=false,connected=false;
 const defaults={},getValue=e=>e.multiple?Array.from(e.selectedOptions,x=>x.value):e.value;
 for(const id of fields){const e=byId(id);if(e&&!['reportSales','physicalTask','physicalItems'].includes(id))defaults[id]=getValue(e);}
 function write(){try{const raw=JSON.stringify(state);if(raw.length<=32768)sessionStorage.setItem(STORE,raw);}catch(e){}}
 function scope(c,create=false){let item=state.scopes.find(x=>same(x,c));if(!item&&create&&c.project&&c.cut){item={...c,view:'monitor',monitor:{},report:{}};state.scopes.push(item);if(state.scopes.length>8)state.scopes.shift();}return item;}
 function capture(c=active){if(!c||!c.project||!c.cut||restoring)return;const item=scope(c,true),values=cleanFields(item[config.page]),token=config.page==='monitor'?currentSource():null;if(token&&!sameSource(token,item.physicalSource)){for(const id of sourceFields){delete values[id];delete pending[id];}pendingSource=null;item.physicalSource=token;}for(const id of fields){const e=byId(id),sourceField=sourceFields.includes(id);if(e&&(!config.fieldReady||config.fieldReady(id))&&(!sourceField||token))values[id]=pending[id]!==undefined&&(!sourceField||sameSource(token,pendingSource))?pending[id]:getValue(e);}item[config.page]=cleanFields(values);if(config.page==='monitor')item.view=config.view();write();}
 function restoreFields(){const c=context();if(!same(c,active))return;restoring=true;let changed=false;
  for(const id of fields){const e=byId(id);if(!e||config.fieldReady&&!config.fieldReady(id))continue;const value=pending[id];if(value===undefined)continue;
   if(sourceFields.includes(id)){const token=currentSource();if(!token)continue;if(!sameSource(token,pendingSource)){const item=scope(c);for(const field of sourceFields){delete pending[field];if(item)delete item.monitor[field];}if(item)delete item.physicalSource;pendingSource=null;write();continue;}}
   if(e.tagName==='SELECT'){const wanted=Array.isArray(value)?value:[value],available=Array.from(e.options).filter(x=>!x.disabled).map(x=>x.value);if(!wanted.every(x=>available.includes(x)))continue;if(e.multiple){const before=JSON.stringify(getValue(e));for(const o of e.options)o.selected=!o.disabled&&wanted.includes(o.value);changed=changed||before!==JSON.stringify(getValue(e));}else if(e.value!==value){e.value=value;changed=true;}}
   else if(e.value!==value){e.value=value;changed=true;}delete pending[id];
  }
  restoring=false;if(changed&&config.filtersRestored)config.filtersRestored();
 }
 function queueHints(saved){pending={...pending,...cleanFields(saved?.[config.page])};pendingSource=sourceToken(saved?.physicalSource);if(!pendingSource)for(const id of sourceFields)delete pending[id];restoreFields();}
 function useContext(){const c=context();active=c;pending={...defaults};state.current=c.project&&c.cut?c:null;queueHints(scope(c));write();}
 function hash(){const raw=location.hash.slice(1),q=new URLSearchParams(raw.startsWith('contracts?')?raw.slice(10):raw);return{deep:raw.startsWith('contracts?')||q.get('tab')==='contracts'&&!!q.get('contract'),view:views.includes(q.get('tab'))?q.get('tab'):null};}
 function changed(tab){if(config.page!=='monitor')return;const c=context();if(!same(active,c))useContext();const item=scope(c,true);if(item)item.view=tab;state.current=c;capture(c);queueHints(item);}
 function restoreContext(){const c=state.current;if(c&&(!config.resolved||config.resolved(c.project))&&!hash().deep){byId('project').value=c.project;byId('cut').value=c.cut;}useContext();}
 function restoreView(){if(config.page!=='monitor')return;const h=hash();if(h.deep){if(!same(active,context()))useContext();return;}const wanted=h.view||scope(context())?.view||'monitor';if(config.view()!==wanted)config.select(wanted);changed(wanted);}
 function forget(){state={version:1,current:null,scopes:[]};pending={};pendingSource=null;active=null;try{sessionStorage.removeItem(STORE);}catch(e){}}
 function connect(){if(connected)return;connected=true;active=context();
  const navs=document.querySelectorAll('.contour,.monitor-tabs');
  for(const nav of navs){
  // Native tab handlers can clear physical controls. Keep the available UI
  // first; later captures retain its hint while those controls are unavailable.
  nav.addEventListener('click',()=>capture(),true);
  nav.addEventListener('click',e=>{const a=e.target.closest('a,button');if(!a)return;capture();const tab=a.dataset.monitorView;if(config.page==='monitor'&&tab){e.preventDefault();const next='#tab='+tab;if(location.hash!==next)history.pushState(null,'',next);changed(tab);}});
  }
  for(const id of ['project','cut'])for(const event of ['input','change'])byId(id).addEventListener(event,()=>{const next=context();if(same(next,active))return;const previous=active;capture(active);active=next;
   // The report's existing onchange starts its request synchronously. Its new
   // scope's period must be in place before that native handler reads it.
   if(config.page==='report'){const kind=cleanFields(scope(next)?.report).reportKind??(previous?.project===next.project?byId('reportKind').value:defaults.reportKind);if(Array.from(byId('reportKind').options).some(o=>o.value===kind)){byId('reportKind').value=kind;const item=scope(next,true);if(item)item.report.reportKind=kind;}}
   queueMicrotask(()=>{if(same(next,context()))useContext();});},true);
  for(const id of fields){const e=byId(id);if(e)for(const event of ['input','change'])e.addEventListener(event,()=>{delete pending[id];capture();});}
  window.addEventListener('pagehide',()=>capture());window.addEventListener('beforeunload',()=>capture());
  // History and legacy hash listeners can clear the native controls too.
  for(const event of ['popstate','hashchange'])window.addEventListener(event,()=>capture(),true);
  window.addEventListener('popstate',restoreView);window.addEventListener('hashchange',restoreView);
  window.addEventListener('storage',e=>{if(e.key===null||['developaid_web_session','plato_projects_key','session','developaid_session','key','developaid_key'].includes(e.key))forget();});
  for(const id of ['keyBtn','loginBtn','logoutBtn'])byId(id)?.addEventListener('click',forget,true);
  new MutationObserver(()=>{if(Object.keys(pending).length)restoreFields();}).observe(document.getElementById('privateArea'),{childList:true,subtree:true});
 }
 return{project:()=>state.current?.project||'',restoreContext,restoreView,connect,changed,ready:()=>{restoreContext();},save:()=>capture()};
};
""".replace('__MONITOR_NAVIGATION_VIEWS__', json.dumps([key for key, _ in VIEWS]))


def apply(page: str, current: str) -> str:
    """Only these hosts opt in; existing cabinet/global contour calls stay exact."""
    if '/* shared-monitor-navigation */' not in page:
        page = page.replace('</style>', STYLE + '\n</style>', 1)
    return (page.replace('__DEVELOPAID_CONTOUR_STYLE__', management_contour.STYLE)
            .replace(management_contour.PLACEHOLDER, markup(current))
            .replace('__MONITOR_PAGE_HEADER__', header_markup(current))
            .replace('__MONITOR_VIEW_TABS__', view_markup(current))
            .replace('__MONITOR_NAVIGATION_SCRIPT__', SCRIPT))
