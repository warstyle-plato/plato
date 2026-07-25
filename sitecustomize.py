"""Runtime compatibility and onboarding patch for DevelopAid v0.12.26."""

from __future__ import annotations

import importlib.abc
import importlib.machinery
import sys
import threading
import time
from types import ModuleType


_ONBOARDING_CSS = r"""
<style id="developaid-onboarding-style">
.da-help-btn{position:fixed;right:22px;bottom:22px;z-index:980;border:1px solid #111;background:#111;color:#fff;padding:11px 15px;font-weight:700;cursor:pointer;box-shadow:0 8px 24px rgba(0,0,0,.18)}
.da-onboarding-overlay{position:fixed;inset:0;background:rgba(0,0,0,.38);z-index:2000;display:none;align-items:center;justify-content:center;padding:20px}.da-onboarding-overlay.open{display:flex}
.da-onboarding{width:min(720px,96vw);max-height:90vh;overflow:auto;background:#fff;border:1px solid #111;padding:26px}.da-onboarding h2{margin:0 0 6px;font-size:24px}.da-onboarding-sub{margin:0 0 20px;color:#666;font-size:13px}
.da-onboarding-step{display:none}.da-onboarding-step.active{display:block}.da-onboarding-step h3{margin:0 0 10px;font-size:18px}.da-onboarding-step p{margin:0;color:#444;line-height:1.6;font-size:14px}
.da-onboarding-progress{font-size:11px;color:#777;margin-bottom:12px}.da-onboarding-actions{display:flex;gap:8px;justify-content:space-between;align-items:center;margin-top:24px;flex-wrap:wrap}.da-onboarding-actions .right{display:flex;gap:8px}.da-onboarding-actions button{border:1px solid #111;background:#fff;padding:9px 13px;font-weight:700;cursor:pointer}.da-onboarding-actions button.primary{background:#111;color:#fff}
@media(max-width:700px){.da-help-btn{right:12px;bottom:12px}.da-onboarding{padding:20px}}
</style>
"""

_ONBOARDING_HTML = r"""
<button class="da-help-btn" id="daHelpBtn" type="button">Как пользоваться</button>
<div class="da-onboarding-overlay" id="daOnboardingOverlay" aria-hidden="true">
  <div class="da-onboarding" role="dialog" aria-modal="true" aria-labelledby="daOnboardingTitle">
    <h2 id="daOnboardingTitle">Как пользоваться DevelopAid</h2>
    <p class="da-onboarding-sub">Первый расчёт за несколько минут</p>
    <div class="da-onboarding-progress" id="daOnboardingProgress"></div>
    <section class="da-onboarding-step" data-step="0"><h3>1. Что делает DevelopAid</h3><p>Модель помогает быстро оценить девелоперский проект: проверить экономику, структуру финансирования, долговую нагрузку, продажи и запас по цене покупки участка.</p></section>
    <section class="da-onboarding-step" data-step="1"><h3>2. С чего начать</h3><p>Создайте проект по кадастровому номеру, выберите готовый пример либо внесите ТЭП вручную. Очередность включайте только тогда, когда проект действительно реализуется этапами.</p></section>
    <section class="da-onboarding-step" data-step="2"><h3>3. Что обязательно проверить</h3><p>Площадь и продаваемые метры, цену реализации, себестоимость, стоимость участка, сроки ИРД и строительства, темп продаж и параметры финансирования.</p></section>
    <section class="da-onboarding-step" data-step="3"><h3>4. Как проходит расчёт</h3><p>DevelopAid строит календарь проекта и рассчитывает продажи, затраты, БРИДЖ, проектное финансирование, эскроу, налоги и итоговую доходность.</p></section>
    <section class="da-onboarding-step" data-step="4"><h3>5. На что смотреть в результате</h3><p>Сначала оцените прибыль, рентабельность, собственные средства, пиковый долг, LLCR и допустимую цену покупки участка. Затем проверьте календарь и чувствительность.</p></section>
    <section class="da-onboarding-step" data-step="5"><h3>6. Отчёты</h3><p>После расчёта откройте управленческий отчёт и скачайте PDF. В нём собраны ключевые показатели, графики финансирования и календарный план проекта.</p></section>
    <section class="da-onboarding-step" data-step="6"><h3>7. Коротко о терминах</h3><p>БРИДЖ — финансирование до перехода на проектный кредит. LLCR показывает запас денежного потока для обслуживания долга. Очередность — отдельный календарь и экономика каждой очереди.</p></section>
    <div class="da-onboarding-actions">
      <button type="button" id="daSkip">Пропустить</button>
      <div class="right"><button type="button" id="daPrev">Назад</button><button type="button" class="primary" id="daNext">Далее</button></div>
    </div>
  </div>
</div>
"""

_ONBOARDING_JS = r"""
<script id="developaid-onboarding-script">
(()=>{
 const overlay=document.getElementById('daOnboardingOverlay');
 const steps=[...document.querySelectorAll('.da-onboarding-step')];
 const progress=document.getElementById('daOnboardingProgress');
 const next=document.getElementById('daNext');
 const prev=document.getElementById('daPrev');
 let current=0;
 function render(){steps.forEach((el,i)=>el.classList.toggle('active',i===current));progress.textContent=`Шаг ${current+1} из ${steps.length}`;prev.style.visibility=current?'visible':'hidden';next.textContent=current===steps.length-1?'Начать расчёт':'Далее'}
 function open(){overlay.classList.add('open');overlay.setAttribute('aria-hidden','false');render()}
 function close(){overlay.classList.remove('open');overlay.setAttribute('aria-hidden','true');localStorage.setItem('developaidOnboardingSeen','1')}
 document.getElementById('daHelpBtn').onclick=open;
 document.getElementById('daSkip').onclick=close;
 prev.onclick=()=>{if(current>0){current--;render()}};
 next.onclick=()=>{if(current<steps.length-1){current++;render()}else close()};
 overlay.addEventListener('click',e=>{if(e.target===overlay)close()});
 document.addEventListener('keydown',e=>{if(e.key==='Escape'&&overlay.classList.contains('open'))close()});
 if(!localStorage.getItem('developaidOnboardingSeen'))setTimeout(open,350);
})();
</script>
"""


def _inject_onboarding(page: str) -> str:
    if "developaid-onboarding-script" in page:
        return page
    page = page.replace("</head>", _ONBOARDING_CSS + "\n</head>", 1)
    page = page.replace("</body>", _ONBOARDING_HTML + "\n" + _ONBOARDING_JS + "\n</body>", 1)
    return page


def _patch_main(module: ModuleType) -> None:
    if getattr(module, "_developaid_v01226_patched", False):
        return

    def send_document_bytes(chat_id: int, content: bytes, filename: str, caption: str = "", content_type: str | None = None):
        token = module._telegram_token()
        if not token:
            raise RuntimeError("TELEGRAM_BOT_TOKEN не задан")
        if content_type is None:
            content_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" if filename.lower().endswith(".xlsx") else "application/pdf"
        boundary = "----DevelopAidBoundary" + module.hashlib.sha256(module.os.urandom(16)).hexdigest()[:20]
        body = module.io.BytesIO()
        def field(name: str, value: str) -> None:
            body.write(f"--{boundary}\r\n".encode())
            body.write(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode())
            body.write(str(value).encode("utf-8")); body.write(b"\r\n")
        field("chat_id", str(int(chat_id)))
        if caption:
            field("caption", caption); field("parse_mode", "HTML")
        body.write(f"--{boundary}\r\n".encode())
        body.write(f'Content-Disposition: form-data; name="document"; filename="{filename}"\r\n'.encode("utf-8"))
        body.write(f"Content-Type: {content_type}\r\n\r\n".encode("ascii")); body.write(content); body.write(b"\r\n")
        body.write(f"--{boundary}--\r\n".encode())
        request = module.urllib.request.Request(f"https://api.telegram.org/bot{token}/sendDocument", data=body.getvalue(), headers={"Content-Type": f"multipart/form-data; boundary={boundary}"}, method="POST")
        try:
            with module.urllib.request.urlopen(request, timeout=30) as response:
                result = module.json.loads(response.read().decode("utf-8"))
        except module.urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:500]
            raise RuntimeError(f"Telegram API sendDocument: HTTP {exc.code}: {detail}") from exc
        if not result.get("ok"):
            raise RuntimeError("Telegram API sendDocument: " + str(result.get("description") or "неизвестная ошибка"))
        return result.get("result")

    def send_template(chat_id: int):
        return send_document_bytes(chat_id, module.base64.b64decode(module.MANUAL_TEP_TEMPLATE_B64), module.MANUAL_TEP_TEMPLATE_FILENAME, "<b>Шаблон ручного ввода ТЭП DevelopAid</b>\n\n1. Заполните жёлтые ячейки.\n2. Не меняйте коды и названия строк.\n3. Отправьте заполненный .xlsx обратно в этот чат.\n\nБот проверит файл и покажет сводку перед открытием модели.", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    if hasattr(module, "PAGE"):
        module.PAGE = _inject_onboarding(module.PAGE)
    module._telegram_send_document_bytes = send_document_bytes
    module._telegram_send_template = send_template
    if hasattr(module, "app"):
        module.app.version = "0.12.26"
    module._developaid_v01226_patched = True


class _MainPatchLoader(importlib.abc.Loader):
    def __init__(self, wrapped: importlib.abc.Loader) -> None:
        self._wrapped = wrapped
    def create_module(self, spec):
        creator = getattr(self._wrapped, "create_module", None)
        return creator(spec) if creator else None
    def exec_module(self, module: ModuleType) -> None:
        self._wrapped.exec_module(module)
        _patch_main(module)


class _MainPatchFinder(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname != "main":
            return None
        spec = importlib.machinery.PathFinder.find_spec(fullname, path)
        if spec is None or spec.loader is None:
            return None
        spec.loader = _MainPatchLoader(spec.loader)
        return spec


def _patch_script_main() -> None:
    for _ in range(600):
        module = sys.modules.get("__main__")
        if module is not None and hasattr(module, "PAGE") and hasattr(module, "app"):
            try:
                _patch_main(module)
            finally:
                return
        time.sleep(0.05)


sys.meta_path.insert(0, _MainPatchFinder())
threading.Thread(target=_patch_script_main, name="developaid-v01226-patch", daemon=True).start()
