from __future__ import annotations

import base64
import io
import re
import zipfile
from pathlib import Path

MAIN = Path("main.py")
TEMPLATE_B64 = "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...TRUNCATED_FOR_BREVITY..."


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected 1 occurrence, found {count}")
    return text.replace(old, new, 1)


text = MAIN.read_text(encoding="utf-8")

text = replace_once(
    text,
    'MANUAL_TEP_TEMPLATE_VERSION = "DevelopAid_TEP_1"',
    'MANUAL_TEP_TEMPLATE_VERSION = "DevelopAid_TEP_2"',
    "template version",
)

text, count = re.subn(
    r'^MANUAL_TEP_TEMPLATE_B64 = "[A-Za-z0-9+/=]+"$',
    'MANUAL_TEP_TEMPLATE_B64 = "' + TEMPLATE_B64 + '"',
    text,
    count=1,
    flags=re.MULTILINE,
)
if count != 1:
    raise RuntimeError(f"template payload: expected 1 occurrence, found {count}")

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

old_project_fields = '''    project_name = str(_find_parameter(rows, "Название проекта") or "").strip()[:120]
    site_area_ha = _manual_tep_number(_find_parameter(rows, "Площадь территории"), "Площадь территории")
'''
new_project_fields = '''    project_name = str(_find_parameter(rows, "Название проекта") or "").strip()[:120]
    region = str(_find_parameter(rows, "Регион / город") or "").strip()[:160]
    site_area_ha = _manual_tep_number(_find_parameter(rows, "Площадь территории"), "Площадь территории")
'''
text = replace_once(text, old_project_fields, new_project_fields, "project metadata")

text = replace_once(
    text,
    '''        "project_name": project_name,
        "site_area_ha": site_area_ha,
''',
    '''        "project_name": project_name,
        "region": region,
        "site_area_ha": site_area_ha,
''',
    "parsed return region",
)

text = replace_once(
    text,
    '{"text": "Загрузить Excel-шаблон", "callback_data": "tep_template"}',
    '{"text": "Скачать Excel-шаблон ТЭП", "callback_data": "tep_template"}',
    "start button",
)

text = replace_once(
    text,
    '"<b>Шаблон ручного ввода ТЭП DevelopAid</b>\\n\\n"',
    '"<b>Excel-шаблон исходного ТЭП DevelopAid</b>\\n\\n"',
    "template caption title",
)
text = replace_once(
    text,
    '"1. Заполните жёлтые ячейки.\\n"',
    '"1. Заполните общие сведения и жёлтые ячейки ТЭП.\\n"',
    "template caption step 1",
)
text = replace_once(
    text,
    '"2. Не меняйте коды и названия строк.\\n"',
    '"2. Не переименовывайте лист, не меняйте коды и не удаляйте строки.\\n"',
    "template caption step 2",
)
text = replace_once(
    text,
    '"3. Отправьте заполненный .xlsx обратно в этот чат.\\n\\n"',
    '"3. Сохраните файл в формате .xlsx и отправьте его обратно в этот чат.\\n\\n"',
    "template caption step 3",
)
text = replace_once(
    text,
    '"Бот проверит файл и покажет сводку перед открытием модели."',
    '"Бот проверит структуру, покажет сводку и предложит открыть проект в DevelopAid."',
    "template caption result",
)

old_manual_header = '''    summary = parsed.get("summary") or {}
    project_name = str(parsed.get("project_name") or "Без названия")
    manual_session = {
'''
new_manual_header = '''    summary = parsed.get("summary") or {}
    project_name = str(parsed.get("project_name") or "Без названия")
    region = str(parsed.get("region") or "").strip()
    region_line = f"Регион: <b>{html.escape(region)}</b>\\n" if region else ""
    manual_session = {
'''
text = replace_once(text, old_manual_header, new_manual_header, "manual summary header")

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

MAIN.write_text(text, encoding="utf-8")

payload = base64.b64decode(TEMPLATE_B64, validate=True)
with zipfile.ZipFile(io.BytesIO(payload)) as archive:
    names = set(archive.namelist())
    required = {"xl/workbook.xml", "xl/worksheets/sheet1.xml"}
    missing = required - names
    if missing:
        raise RuntimeError("template package missing: " + ", ".join(sorted(missing)))
    workbook_xml = archive.read("xl/workbook.xml").decode("utf-8", errors="replace")
    if "ТЭП DevelopAid" not in workbook_xml:
        raise RuntimeError("template sheet name not found")
    combined = b"\n".join(archive.read(name) for name in names if name.endswith(".xml"))
    if b"DevelopAid_TEP_2" not in combined:
        raise RuntimeError("template version marker not found")

print("Telegram TEP template v2 applied successfully")
