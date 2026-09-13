"""Presentation-only progress indicator for cadastral TEP calculation."""

from __future__ import annotations

_STYLE = r'''<style id="tep-progress-style">
#tepProgress{margin:12px 0 14px;padding:12px 14px;border:1px solid #d8d8d3;background:#fafaf8}
#tepProgressTop{display:flex;justify-content:space-between;gap:12px;margin-bottom:8px;font-size:13px;font-weight:700;color:#222}
#tepProgressTrack{height:7px;background:#e7e7e2;overflow:hidden}
#tepProgressFill{height:100%;width:0;background:#2f7d57;transition:width .25s ease}
#tepProgress[data-stage="2"] #tepProgressFill,#tepProgress[data-stage="3"] #tepProgressFill{background:#b77719}
#tepProgressText{margin-top:9px;font-size:13px;line-height:1.35;color:#555}
#tepProgress[data-error="1"]{border-color:#b43b31;background:#fff7f5}
#tepProgress[data-error="1"] #tepProgressFill{background:#b43b31}
#tepProgress[data-error="1"] #tepProgressText{color:#8d2d26}
</style>'''

_SCRIPT = r'''<script id="tep-progress-script">
(function(){
 if(window.__tepProgressInstalled)return;window.__tepProgressInstalled=true;
 function box(status){
  let b=document.getElementById('tepProgress');if(b)return b;
  b=document.createElement('div');b.id='tepProgress';b.hidden=true;
  b.innerHTML='<div id="tepProgressTop"><span>Расчёт ТЭП</span><span id="tepProgressPct">0%</span></div><div id="tepProgressTrack"><div id="tepProgressFill"></div></div><div id="tepProgressText"></div>';
  status.parentNode.insertBefore(b,status.nextSibling);return b;
 }
 function subject(){
  const t=(document.body&&document.body.innerText||'').toLowerCase();
  if(t.indexOf('субъект рф\nмосква')>=0||t.indexOf('субъект рф москва')>=0)return 'moscow';
  if(t.indexOf('московская область')>=0)return 'mo';
  return '';
 }
 function nums(){const e=document.getElementById('cadastralNumbers');return String(e&&e.value||'').split(/[\s,;]+/).filter(Boolean)}
 function sourceText(){
  const s=subject();if(s==='moscow')return 'Получаю расчёт ГлавАПУ…';if(s==='mo')return 'Применяю нормативы РНГП Московской области…';
  const a=nums();if(a.length&&a.every(n=>/^77:/.test(n)))return 'Получаю расчёт ГлавАПУ…';
  if(a.length&&a.every(n=>/^50:/.test(n)))return 'Определяю нормативный источник…';
  return 'Формирую ТЭП по допущениям движка…';
 }
 function render(status){
  const raw=String(status.textContent||'').trim();if(!raw)return;
  let stage=0,m=raw.match(/([1-4])\s*из\s*4/);if(m)stage=Number(m[1]);
  else if(/главапу|рнгп|норматив|считаю тэп/i.test(raw))stage=2;
  else if(/считываю|таблиц/i.test(raw))stage=3;else if(/сверк|готов|посчитан|применен/i.test(raw))stage=4;
  if(!stage)return;
  const err=/ошиб|не удалось|таймаут|отказ/i.test(raw),b=box(status);b.hidden=false;b.dataset.stage=String(stage);b.dataset.error=err?'1':'0';
  const pct=stage*25;document.getElementById('tepProgressFill').style.width=pct+'%';document.getElementById('tepProgressPct').textContent=err?'Ошибка':pct+'%';
  let text=raw.replace(/^\s*[1-4]\s*из\s*4\s*[·—-]?\s*/,'');
  if(stage===1)text='Формирую территорию по кадастровым номерам…';
  if(stage===2)text=sourceText();
  if(stage===3){const s=sourceText();text=/ГлавАПУ/.test(s)?'Считываю готовый ТЭП ГлавАПУ…':/РНГП/.test(s)?'Собираю ТЭП по нормативам РНГП…':'Проверяю рассчитанный ТЭП…'}
  if(stage===4&&!err)text='Подготавливаю ТЭП к применению…';
  document.getElementById('tepProgressText').textContent=text;
 }
 function init(){const status=document.getElementById('cadastralStatus');if(!status)return;box(status);new MutationObserver(()=>render(status)).observe(status,{childList:true,subtree:true,characterData:true});const btn=document.getElementById('cadastralAnalyzeButton');if(btn)btn.addEventListener('click',()=>{const b=box(status);b.hidden=false;b.dataset.stage='1';b.dataset.error='0';document.getElementById('tepProgressFill').style.width='25%';document.getElementById('tepProgressPct').textContent='25%';document.getElementById('tepProgressText').textContent='Формирую территорию по кадастровым номерам…'},true);render(status)}
 if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',init);else init();
})();
</script>'''


def install(core) -> None:
    page = getattr(core, "PAGE", "")
    if not isinstance(page, str) or "tep-progress-script" in page:
        return
    addition = _STYLE + _SCRIPT
    core.PAGE = page.replace("</body>", addition + "</body>", 1) if "</body>" in page else page + addition
