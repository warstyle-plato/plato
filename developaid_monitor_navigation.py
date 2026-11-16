"""One presentation and bounded UI context for Monitor and its management report.

The product destinations remain owned by management_contour.ROLES. This module
does not change the cabinet, authentication, data readers or saved source state.
"""
from __future__ import annotations

from html import escape
import json

from management_contour import PLACEHOLDER, ROLES

VIEWS = (('monitor', 'ГПР: план и факт'), ('money', 'Деньги'),
         ('contracts', 'Договоры'), ('data', 'Данные и настройки'))

STYLE = """
/* shared-monitor-navigation */
.monitor-navigation{margin:0 0 18px;padding:14px;background:#fff;border:1px solid #d9e2ec;border-radius:10px}
.monitor-navigation-title{font-size:12px;font-weight:700;color:#526579;margin-bottom:10px}
.monitor-navigation-groups{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:16px}
.monitor-navigation-group{min-width:0;border-left:3px solid #1f4e8c;padding-left:12px}
.monitor-navigation-group>b{display:block;color:#24374b;font-size:13px;margin-bottom:6px}
.monitor-navigation a,.monitor-navigation button{box-sizing:border-box;display:block;max-width:100%;font:inherit;font-size:13px;line-height:1.4;text-align:left;text-decoration:none;color:#1f4e8c;background:none;border:0;border-radius:5px;padding:5px 7px;margin:2px 0;white-space:normal;overflow-wrap:anywhere;cursor:pointer}
.monitor-navigation a:hover,.monitor-navigation button:hover{background:#f0f4f9}
.monitor-navigation [aria-current="page"],.monitor-navigation [aria-selected="true"]{background:#eaf1fa;color:#163d70;font-weight:700}
.monitor-navigation a:focus-visible,.monitor-navigation button:focus-visible{outline:2px solid #1f4e8c;outline-offset:2px}
.monitor-navigation-views{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:3px;margin:7px 0 0;padding-top:7px;border-top:1px solid #e1e7ee}
.monitor-navigation-views a,.monitor-navigation-views button{font-size:12px;margin:0;width:100%;min-height:36px}
@media(max-width:640px){.monitor-navigation{padding:12px}.monitor-navigation-groups{grid-template-columns:minmax(0,1fr);gap:10px}.monitor-navigation-group{padding-left:9px}.monitor-navigation-group>b{margin-bottom:2px}.monitor-navigation-views{grid-template-columns:repeat(2,minmax(0,1fr))}.monitor-navigation a,.monitor-navigation button{padding:6px 7px}}
@media print{.monitor-navigation{display:none!important}}
"""


def markup(current: str) -> str:
    """Same seven destinations and four Monitor views, with host-only semantics."""
    groups = []
    for role in ROLES:
        links = []
        for link in role['links']:
            href = str(link['href'])
            here = ' aria-current="page"' if href == current else ''
            links.append(f'<a href="{escape(href, quote=True)}"{here}>{escape(str(link["name"]))}</a>')
            if href == '/monitor':
                views = []
                for key, name in VIEWS:
                    if current == '/monitor':
                        views.append(f'<button type="button" id="{key}Tab" role="tab" '
                                     f'aria-selected="{str(key == "monitor").lower()}" '
                                     f'aria-controls="{key}Panel" tabindex="{0 if key == "monitor" else -1}" '
                                     f'data-monitor-view="{key}">{escape(name)}</button>')
                    else:
                        views.append(f'<a href="/monitor#tab={key}" data-monitor-view="{key}">{escape(name)}</a>')
                semantics = ' role="tablist" aria-label="Разделы проекта"' if current == '/monitor' else ''
                links.append('<div class="monitor-navigation-views"' + semantics + '>' + ''.join(views) + '</div>')
        groups.append('<div class="monitor-navigation-group"><b>' + escape(str(role['role']))
                      + '</b>' + ''.join(links) + '</div>')
    return ('<nav class="monitor-navigation" aria-label="Разделы DevelopAid">'
            '<div class="monitor-navigation-title">Разделы DevelopAid</div>'
            '<div class="monitor-navigation-groups">' + ''.join(groups) + '</div></nav>')


SCRIPT = r"""
// UI state only. Credentials, fetched results and source/edit drafts never enter this store.
window.createMonitorNavigation=function(config){
 const STORE='developaid_monitor_navigation_v1',views=__MONITOR_NAVIGATION_VIEWS__;
 const fieldSets={monitor:['contractsSearch','contractsFilter','physicalReviewView','physicalReviewSearch','physicalReviewFilter','physicalSearch','physicalTask','physicalItems'],report:['reportKind','reportSales']},fields=fieldSets[config.page];
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
  const nav=document.querySelector('.monitor-navigation');
  // Native tab handlers can clear physical controls. Keep the available UI
  // first; later captures retain its hint while those controls are unavailable.
  nav.addEventListener('click',()=>capture(),true);
  nav.addEventListener('click',e=>{const a=e.target.closest('a,button');if(!a)return;capture();const tab=a.dataset.monitorView;if(config.page==='monitor'&&tab){e.preventDefault();const next='#tab='+tab;if(location.hash!==next)history.pushState(null,'',next);changed(tab);}});
  for(const id of ['project','cut'])for(const event of ['input','change'])byId(id).addEventListener(event,()=>{const next=context();if(same(next,active))return;capture(active);active=next;
   // The report's existing onchange starts its request synchronously. Its new
   // scope's period must be in place before that native handler reads it.
   if(config.page==='report'){const kind=cleanFields(scope(next)?.report).reportKind??defaults.reportKind;if(Array.from(byId('reportKind').options).some(o=>o.value===kind))byId('reportKind').value=kind;}
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
    return page.replace(PLACEHOLDER, markup(current)).replace('__MONITOR_NAVIGATION_SCRIPT__', SCRIPT)
