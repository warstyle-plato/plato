from __future__ import annotations

import base64
import io
import json
import os
import re
import urllib.request
import zipfile
from pathlib import Path

MAIN = Path("main.py")
CHECKED_OUT_TEMPLATE = Path("templates/DevelopAid_Шаблон_ТЭП.xlsx")
TEMPLATE_B64_PATH = Path("templates/DevelopAid_Шаблон_ТЭП.xlsx.b64")
TEMPLATE_BLOB_SHA = "211c3eb01078f82789b6b17bd71a3190e5ea2b8d"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected 1 occurrence, found {count}")
    return text.replace(old, new, 1)


def valid_xlsx(payload: bytes) -> bool:
    try:
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            return {
                "xl/workbook.xml",
                "xl/worksheets/sheet1.xml",
                "xl/worksheets/sheet2.xml",
            }.issubset(archive.namelist())
    except zipfile.BadZipFile:
        return False


def load_template_payload() -> bytes:
    if CHECKED_OUT_TEMPLATE.is_file():
        checked_out = CHECKED_OUT_TEMPLATE.read_bytes()
        if valid_xlsx(checked_out):
            return checked_out

    request = urllib.request.Request(
        f"https://api.github.com/repos/warstyle-plato/plato/git/blobs/{TEMPLATE_BLOB_SHA}",
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "DevelopAid-template-integration",
            **(
                {"Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}"}
                if os.environ.get("GITHUB_TOKEN")
                else {}
            ),
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        blob = json.loads(response.read().decode("utf-8"))
    payload = base64.b64decode(str(blob.get("content") or ""), validate=False)
    if not valid_xlsx(payload):
        raise RuntimeError("GitHub blob does not contain a valid XLSX package")
    return payload


payload = load_template_payload()
with zipfile.ZipFile(io.BytesIO(payload)) as archive:
    xml_payload = b"\n".join(
        archive.read(name) for name in archive.namelist() if name.endswith(".xml")
    )
    if "ТЭП DevelopAid".encode("utf-8") not in xml_payload:
        raise RuntimeError("Worksheet 'ТЭП DevelopAid' is missing")
    if b"DevelopAid_TEP_2" not in xml_payload:
        raise RuntimeError("Template version marker DevelopAid_TEP_2 is missing")

TEMPLATE_B64_PATH.write_text(base64.b64encode(payload).decode("ascii"), encoding="ascii")

text = MAIN.read_text(encoding="utf-8")

text = replace_once(
    text,
    'MANUAL_TEP_TEMPLATE_FILENAME = "DevelopAid_Шаблон_ТЭП.xlsx"\n'
    'MANUAL_TEP_TEMPLATE_VERSION = "DevelopAid_TEP_1"\n',
    'MANUAL_TEP_TEMPLATE_FILENAME = "DevelopAid_Шаблон_ТЭП.xlsx"\n'
    'MANUAL_TEP_TEMPLATE_B64_PATH = Path(__file__).resolve().parent / "templates" / "DevelopAid_Шаблон_ТЭП.xlsx.b64"\n'
    'MANUAL_TEP_TEMPLATE_VERSION = "DevelopAid_TEP_2"\n',
    "template constants",
)

text, removed = re.subn(
    r'^MANUAL_TEP_TEMPLATE_B64 = "[A-Za-z0-9+/=]+"\n',
    "",
    text,
    count=1,
    flags=re.MULTILINE,
)
if removed != 1:
    raise RuntimeError(f"embedded template removal: expected 1 occurrence, found {removed}")

old_sheet_lookup = '''    sheet_name = next((name for name in tables if name.strip().lower() == "тэп plato"), None)
    if not sheet_name:
        sheet_name = next((name for name in tables if "тэп" in name.lower() and "plato" in name.lower()), None)
'''
new_sheet_lookup = '''    sheet_name = next(
        (
            name for name in tables
            if name.strip().lower() in {"тэп developaid", "тэп plato"}
        ),
        None,
    )
    if not sheet_name:
        sheet_name = next(
            (
                name for name in tables
                if "тэп" in name.lower()
                and ("developaid" in name.lower() or "plato" in name.lower())
            ),
            None,
        )
'''
text = replace_once(text, old_sheet_lookup, new_sheet_lookup, "sheet lookup")

text = replace_once(
    text,
    '''    project_name = str(_find_parameter(rows, "Название проекта") or "").strip()[:120]
    site_area_ha = _manual_tep_number(_find_parameter(rows, "Площадь территории"), "Площадь территории")
''',
    '''    project_name = str(_find_parameter(rows, "Название проекта") or "").strip()[:120]
    region = str(_find_parameter(rows, "Регион / город") or "").strip()[:160]
    site_area_ha = _manual_tep_number(_find_parameter(rows, "Площадь территории"), "Площадь территории")
''',
    "project metadata",
)

text = replace_once(
    text,
    '''        "project_name": project_name,
        "site_area_ha": site_area_ha,
''',
    '''        "project_name": project_name,
        "region": region,
        "site_area_ha": site_area_ha,
''',
    "parsed region",
)

old_route = '''@app.get("/templates/tep")
def download_manual_tep_template():
    try:
        content = base64.b64decode(MANUAL_TEP_TEMPLATE_B64, validate=True)
    except Exception as exc:
        raise HTTPException(status_code=500, detail="Шаблон ТЭП повреждён") from exc
    encoded_name = urllib.parse.quote(MANUAL_TEP_TEMPLATE_FILENAME)
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Cache-Control": "public, max-age=3600",
            "Content-Disposition": f"attachment; filename=DevelopAid_TEP_template.xlsx; filename*=UTF-8''{encoded_name}",
        },
    )
'''
new_route = '''@app.get("/templates/tep")
def download_manual_tep_template():
    try:
        encoded = MANUAL_TEP_TEMPLATE_B64_PATH.read_text(encoding="ascii").strip()
        content = base64.b64decode(encoded, validate=True)
    except Exception as exc:
        raise HTTPException(status_code=500, detail="Excel-шаблон ТЭП повреждён или не найден") from exc
    encoded_name = urllib.parse.quote(MANUAL_TEP_TEMPLATE_FILENAME)
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Cache-Control": "public, max-age=3600",
            "Content-Disposition": f"attachment; filename=DevelopAid_TEP_template.xlsx; filename*=UTF-8''{encoded_name}",
        },
    )
'''
text = replace_once(text, old_route, new_route, "template endpoint")

text = replace_once(
    text,
    '{"text": "Загрузить Excel-шаблон", "callback_data": "tep_template"}',
    '{"text": "Скачать Excel-шаблон ТЭП", "callback_data": "tep_template"}',
    "start button",
)

caption_replacements = {
    "<b>Шаблон ручного ввода ТЭП DevelopAid</b>": "<b>Excel-шаблон исходного ТЭП DevelopAid</b>",
    "1. Заполните жёлтые ячейки.": "1. Заполните общие сведения и жёлтые ячейки ТЭП.",
    "2. Не меняйте коды и названия строк.": "2. Не переименовывайте лист, не меняйте коды и не удаляйте строки.",
    "3. Отправьте заполненный .xlsx обратно в этот чат.": "3. Сохраните файл в формате .xlsx и отправьте его обратно в этот чат.",
    "Бот проверит файл и покажет сводку перед открытием модели.": "Бот проверит структуру, покажет сводку и предложит открыть проект в DevelopAid.",
}
for old, new in caption_replacements.items():
    text = replace_once(text, old, new, f"caption: {old}")

text = replace_once(
    text,
    '''    summary = parsed.get("summary") or {}
    project_name = str(parsed.get("project_name") or "Без названия")
    manual_session = {
''',
    '''    summary = parsed.get("summary") or {}
    project_name = str(parsed.get("project_name") or "Без названия")
    region = str(parsed.get("region") or "").strip()
    region_line = f"Регион: <b>{html.escape(region)}</b>\\n" if region else ""
    manual_session = {
''',
    "manual summary metadata",
)

text = replace_once(
    text,
    '''        "project_name": parsed.get("project_name") or "",
        "site_area_ha": parsed.get("site_area_ha") or 0,
''',
    '''        "project_name": parsed.get("project_name") or "",
        "region": parsed.get("region") or "",
        "site_area_ha": parsed.get("site_area_ha") or 0,
''',
    "manual session region",
)

text = replace_once(
    text,
    '''        "<b>Ручной ТЭП распознан</b>\\n"
        f"Проект: <b>{html.escape(project_name)}</b>\\n"
        f"Территория: <b>{_telegram_number(parsed.get('site_area_ha'), 4)} га</b>\\n"
''',
    '''        "<b>Ручной ТЭП распознан</b>\\n"
        f"Проект: <b>{html.escape(project_name)}</b>\\n"
        f"{region_line}"
        f"Территория: <b>{_telegram_number(parsed.get('site_area_ha'), 4)} га</b>\\n"
''',
    "manual summary region line",
)

text = text.replace("0.12.26", "0.12.27")
MAIN.write_text(text, encoding="utf-8")
print("Telegram TEP template v2 integration applied")
