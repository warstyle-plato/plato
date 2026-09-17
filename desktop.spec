# Build on the target OS: python -m PyInstaller --clean desktop.spec
from pathlib import Path
import sys
from PyInstaller.utils.hooks import collect_submodules

root = Path(SPECPATH)
# Explicit public assets only. Never package runtime data/, presets/, .env,
# customer projects or the entire repository directory.
datas = [(str(root / 'main_legacy.py'), '.'),
         (str(root / 'desktop/static'), 'desktop/static'),
         (str(root / 'desktop/fonts'), 'desktop/fonts'),
         (str(root / 'templates/DevelopAid_model_v4.xlsx'), 'templates'),
         (str(root / 'data/normatives/registry.json'), 'data/normatives')]
for name in ('mo_market_price.csv', 'mo_vri_kd.csv', 'moscow_parking_k2.csv', 'upks_oks_quarters.csv.gz'):
    datas.append((str(root / 'data' / name), 'data'))
# main.py dynamically loads main_legacy.py; analyze that module too so its
# dependencies are present in the frozen app. No production app is started.
hidden = ['main_legacy', 'httpx', 'uvicorn.logging', 'uvicorn.loops.asyncio',
          'uvicorn.protocols.http.h11_impl', 'uvicorn.lifespan.on']
hidden += collect_submodules('reportlab')
a = Analysis([str(root / 'desktop_entry.py')], pathex=[str(root)], datas=datas,
             hiddenimports=hidden, excludes=['tkinter', 'PyQt5', 'PyQt6', 'PySide6'],
             noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='DevelopAid',
          debug=False, strip=False, upx=False, console=False)
collection = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='DevelopAid')
if sys.platform == 'darwin':
    app = BUNDLE(collection, name='DevelopAid.app', bundle_identifier='ru.developaid.desktop',
                 info_plist={'NSHighResolutionCapable': True})
