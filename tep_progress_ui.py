"""Visible progress for the long cadastral -> TEP calculation.

Presentation-only patch: the calculation pipeline and its four existing stages stay
exactly as they are.  We only render the stage that the page already reports as a
proper progress block, so a slow ГлавАПУ step no longer looks like a frozen page.
"""

from __future__ import annotations

from typing import Any


_CSS_ANCHOR = ".import-status{font-size:12px;color:#666;margin-top:10px}"
_CSS = r"""
.tep-progress-card{margin-top:10px;padding:14px 16px;border:1px solid #f0b8bc;background:#fff3f4;color:#222}
.tep-progress-top{display:flex;align-items:flex-start;justify-content:space-between;gap:12px}
.tep-progress-title{font-size:14px;font-weight:700;color:#111}
.tep-progress-step{font-size:11px;color:#8a3e46;white-space:nowrap}
.tep-progress-message{font-size:12px;line-height:1.45;color:#555;margin-top:3px}
.tep-progress-track{height:8px;background:#eadfe0;margin-top:10px;overflow:hidden}
.tep-progress-fill{height:100%;background:#e52f3b;transition:width .25s ease}
.tep-progress-stages{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:6px;margin-top:10px}
.tep-progress-stage{font-size:10px;line-height:1.25;color:#999;border-top:2px solid #ddd;padding-top:5px}
.tep-progress-stage.done{color:#555;border-color:#777}
.tep-progress-stage.current{color:#a4131d;border-color:#e52f3b;font-weight:700}
.tep-progress-hint{font-size:10px;line-height:1.4;color:#777;margin-top:10px}
@media(max-width:700px){
 .tep-progress-card{padding:13px 12px}
 .tep-progress-stages{grid-template-columns:1fr 1fr;gap:7px 10px}
 .tep-progress-title{font-size:13px}
}
"""

_JS_ANCHOR = "async function obtainCadastralTep(preAnalysis){"
_JS = r"""
const TEP_PROGRESS_LABELS=[
 'Территория и ЕГРН',
 'Расчёт ГлавАПУ',
 'Чтение ТЭП',
 'Подготовка результата'
];
function setTepProgress(status,step,total,message){
 if(!status)return;
 const safeStep=Math.max(1,Math.min(Number(step)||1,Number(total)||4));
 const safeTotal=Math.max(1,Number(total)||4);
 const percent=Math.max(1,Math.min(100,Math.round(safeStep/safeTotal*100)));
 const stages=TEP_PROGRESS_LABELS.map((label,index)=>{
  const n=index+1;
  const state=n<safeStep?' done':(n===safeStep?' current':'');
  return '<div class="tep-progress-stage'+state+'">'+n+'. '+label+'</div>';
 }).join('');
 status.innerHTML='<div class="tep-progress-card" role="status" aria-live="polite">'+
  '<div class="tep-progress-top"><div><div class="tep-progress-title">Идёт расчёт ТЭП…</div>'+
  '<div class="tep-progress-message">'+escapeHtml(String(message||''))+'</div></div>'+
  '<div class="tep-progress-step">Шаг '+safeStep+' из '+safeTotal+' · '+percent+'%</div></div>'+
  '<div class="tep-progress-track" role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow="'+percent+'">'+
  '<div class="tep-progress-fill" style="width:'+percent+'%"></div></div>'+
  '<div class="tep-progress-stages">'+stages+'</div>'+
  '<div class="tep-progress-hint">Расчёт может занять от 30 секунд до 2 минут. Уже найденные сведения об участке остаются видны ниже — страницу обновлять не нужно.</div>'+
  '</div>';
}

"""

_REPLACEMENTS = {
    "status.textContent='1 из 4 · Формирую территорию по кадастровым номерам…';":
        "setTepProgress(status,1,4,'Формирую территорию по кадастровым номерам…');",
    "status.textContent='2 из 4 · Открываю штатный расчёт ГлавАПУ…';":
        "setTepProgress(status,2,4,'Открываю штатный расчёт ГлавАПУ…');",
    "status.textContent='3 из 4 · Считываю готовую таблицу ТЭП ГлавАПУ…';":
        "setTepProgress(status,3,4,'Считываю готовую таблицу ТЭП ГлавАПУ…');",
    "status.textContent='4 из 4 · Подготавливаю сверку перед применением…';":
        "setTepProgress(status,4,4,'Подготавливаю сверку перед применением…');",
}


def _patch_page(page: str) -> str:
    if "tep-progress-card" in page:
        return page
    if _CSS_ANCHOR not in page:
        raise RuntimeError("DevelopAid TEP progress: CSS anchor not found")
    if _JS_ANCHOR not in page:
        raise RuntimeError("DevelopAid TEP progress: JS anchor not found")

    patched = page.replace(_CSS_ANCHOR, _CSS_ANCHOR + _CSS, 1)
    patched = patched.replace(_JS_ANCHOR, _JS + _JS_ANCHOR, 1)
    for old, new in _REPLACEMENTS.items():
        if old not in patched:
            raise RuntimeError(f"DevelopAid TEP progress: stage anchor not found: {old}")
        patched = patched.replace(old, new, 1)
    return patched


def install(base: Any) -> None:
    """Install the presentation patch on the shared PAGE used by production."""
    core = getattr(base, "core", base)
    page = _patch_page(str(core.PAGE))
    core.PAGE = page
    if hasattr(base, "PAGE"):
        base.PAGE = page
