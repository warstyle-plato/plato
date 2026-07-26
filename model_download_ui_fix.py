from __future__ import annotations

from typing import Any

VERSION = "0.12.52"


def apply(runtime: Any) -> None:
    """Make model export a clear one-click XLSX download.

    The existing Excel backend remains unchanged. This patch repurposes the old
    ZIP button as the primary XLSX action, removes the duplicate XLSX control,
    and leaves the phase ZIP only as an additional option when phasing is active.
    """
    page = str(getattr(runtime.core, "PAGE", ""))
    if not page or "exportModelExcel" not in page or "developaid-model-download-fix" in page:
        runtime._RUNTIME_VERSION = VERSION
        runtime.app.version = VERSION
        return

    marker = "</body>"
    script = r'''
<script id="developaid-model-download-fix">
(function(){
  function installNormalModelDownload(){
    const oldButton=document.getElementById('exportModelButton');
    if(oldButton){
      oldButton.textContent='Скачать Excel-модель';
      oldButton.title='Скачать текущую финансовую модель в формате XLSX';
      oldButton.onclick=async function(){
        const original=this.textContent;
        this.disabled=true;
        this.textContent='Формирую Excel…';
        try{await exportModelExcel('consolidated');}
        finally{this.disabled=false;this.textContent=original;}
      };
    }

    const duplicate=document.getElementById('exportExcelConsolidated');
    if(duplicate) duplicate.style.display='none';

    const packageButton=document.getElementById('exportExcelPackage');
    if(packageButton){
      const enabled=Boolean(window.phasing&&phasing.enabled&&Number(phasing.phase_count||0)>1);
      packageButton.style.display=enabled?'':'none';
      packageButton.textContent='Скачать модели по очередям (ZIP)';
    }
  }

  document.addEventListener('DOMContentLoaded',function(){
    installNormalModelDownload();
    setTimeout(installNormalModelDownload,800);
    setTimeout(installNormalModelDownload,1800);
  });
  window.addEventListener('load',installNormalModelDownload);
})();
</script>
'''
    if marker in page:
        runtime.core.PAGE = page.replace(marker, script + marker, 1)

    runtime._RUNTIME_VERSION = VERSION
    runtime.app.version = VERSION
