from pathlib import Path
import re

path = Path("main.py")
source = path.read_text(encoding="utf-8")

helper_pattern = re.compile(
    r'def _telegram_send_document_bytes\(chat_id: int,content: bytes,filename: str,caption: str = ""\) -> Any:\n'
    r'.*?\n\s*return result\.get\("result"\)\n',
    re.S,
)
helper_replacement = '''def _telegram_send_document_bytes(
    chat_id: int,
    content: bytes,
    filename: str,
    caption: str = "",
    content_type: str | None = None,
) -> Any:
    token = _telegram_token()
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN не задан")
    if content_type is None:
        content_type = (
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            if filename.lower().endswith(".xlsx")
            else "application/pdf"
        )
    boundary = "----DevelopAidBoundary" + hashlib.sha256(os.urandom(16)).hexdigest()[:20]
    body = io.BytesIO()

    def field(name: str, value: str) -> None:
        body.write(f"--{boundary}\\r\\n".encode())
        body.write(f'Content-Disposition: form-data; name="{name}"\\r\\n\\r\\n'.encode())
        body.write(str(value).encode("utf-8"))
        body.write(b"\\r\\n")

    field("chat_id", str(int(chat_id)))
    if caption:
        field("caption", caption)
        field("parse_mode", "HTML")
    body.write(f"--{boundary}\\r\\n".encode())
    body.write(
        f'Content-Disposition: form-data; name="document"; filename="{filename}"\\r\\n'.encode("utf-8")
    )
    body.write(f"Content-Type: {content_type}\\r\\n\\r\\n".encode("ascii"))
    body.write(content)
    body.write(b"\\r\\n")
    body.write(f"--{boundary}--\\r\\n".encode())
    request = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendDocument",
        data=body.getvalue(),
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            result = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        raise RuntimeError(f"Telegram API sendDocument: HTTP {exc.code}: {detail}") from exc
    if not result.get("ok"):
        raise RuntimeError(
            "Telegram API sendDocument: " + str(result.get("description") or "неизвестная ошибка")
        )
    return result.get("result")
'''
source, helper_count = helper_pattern.subn(helper_replacement, source, count=1)
if helper_count != 1:
    raise SystemExit(f"document helper patch count: {helper_count}")

template_pattern = re.compile(
    r'def _telegram_send_template\(chat_id: int\) -> Any:\n.*?\n\s*\)\n\n\n(?=def _telegram_download_document)',
    re.S,
)
template_replacement = '''def _telegram_send_template(chat_id: int) -> Any:
    return _telegram_send_document_bytes(
        chat_id,
        base64.b64decode(MANUAL_TEP_TEMPLATE_B64),
        MANUAL_TEP_TEMPLATE_FILENAME,
        (
            "<b>Шаблон ручного ввода ТЭП DevelopAid</b>\\n\\n"
            "1. Заполните жёлтые ячейки.\\n"
            "2. Не меняйте коды и названия строк.\\n"
            "3. Отправьте заполненный .xlsx обратно в этот чат.\\n\\n"
            "Бот проверит файл и покажет сводку перед открытием модели."
        ),
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


'''
source, template_count = template_pattern.subn(template_replacement, source, count=1)
if template_count != 1:
    raise SystemExit(f"template sender patch count: {template_count}")

source = source.replace('version="0.12.25"', 'version="0.12.26"')
source = source.replace('Версия: 0.12.25', 'Версия: 0.12.26')
source = source.replace('"version": "0.12.25"', '"version": "0.12.26"')
source = source.replace('Development-Model/0.12.25', 'Development-Model/0.12.26')

path.write_text(source, encoding="utf-8")
