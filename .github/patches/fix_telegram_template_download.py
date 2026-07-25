from pathlib import Path

path = Path("main.py")
text = path.read_text(encoding="utf-8")

old_helper = '''def _telegram_send_document_bytes(chat_id: int,content: bytes,filename: str,caption: str = "") -> Any:
    token=_telegram_token()
    if not token: raise RuntimeError("TELEGRAM_BOT_TOKEN не задан")
    boundary="----DevelopAidBoundary"+hashlib.sha256(os.urandom(16)).hexdigest()[:20];body=io.BytesIO()
    def field(name: str,value: str) -> None:
        body.write(f"--{boundary}\\r\\n".encode());body.write(f'Content-Disposition: form-data; name="{name}"\\r\\n\\r\\n'.encode());body.write(str(value).encode("utf-8"));body.write(b"\\r\\n")
    field("chat_id",str(int(chat_id)))
    if caption: field("caption",caption);field("parse_mode","HTML")
    body.write(f"--{boundary}\\r\\n".encode());body.write(f'Content-Disposition: form-data; name="document"; filename="{filename}"\\r\\n'.encode("utf-8"));body.write(b"Content-Type: application/pdf\\r\\n\\r\\n");body.write(content);body.write(b"\\r\\n");body.write(f"--{boundary}--\\r\\n".encode())
    request=urllib.request.Request(f"https://api.telegram.org/bot{token}/sendDocument",data=body.getvalue(),headers={"Content-Type":f"multipart/form-data; boundary={boundary}"},method="POST")
    try:
        with urllib.request.urlopen(request,timeout=30) as response: result=json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail=exc.read().decode("utf-8",errors="replace")[:500];raise RuntimeError(f"Telegram API sendDocument: HTTP {exc.code}: {detail}") from exc
    if not result.get("ok"): raise RuntimeError("Telegram API sendDocument: "+str(result.get("description") or "неизвестная ошибка"))
    return result.get("result")
'''

new_helper = '''def _telegram_send_document_bytes(
    chat_id: int,
    content: bytes,
    filename: str,
    caption: str = "",
    content_type: str = "application/octet-stream",
) -> Any:
    token = _telegram_token()
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN не задан")
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
        raise RuntimeError("Telegram API sendDocument: " + str(result.get("description") or "неизвестная ошибка"))
    return result.get("result")
'''

if text.count(old_helper) != 1:
    raise RuntimeError(f"document helper anchor count: {text.count(old_helper)}")
text = text.replace(old_helper, new_helper, 1)

old_template = '''def _telegram_send_template(chat_id: int) -> Any:
    return _telegram_api(
        "sendDocument",
        {
            "chat_id": int(chat_id),
            "document": _TELEGRAM_PUBLIC_BASE_URL + "/templates/tep",
            "caption": (
                "<b>Excel-шаблон исходного ТЭП DevelopAid</b>\\n\\n"
                "1. Заполните общие сведения и жёлтые ячейки ТЭП.\\n"
                "2. Не переименовывайте лист, не меняйте коды и не удаляйте строки.\\n"
                "3. Сохраните файл в формате .xlsx и отправьте его обратно в этот чат.\\n\\n"
                "Бот проверит структуру, покажет сводку и предложит открыть проект в DevelopAid."
            ),
            "parse_mode": "HTML",
        },
    )
'''

new_template = '''def _telegram_send_template(chat_id: int) -> Any:
    try:
        encoded = MANUAL_TEP_TEMPLATE_B64_PATH.read_text(encoding="ascii").strip()
        content = base64.b64decode(encoded, validate=True)
    except Exception as exc:
        raise RuntimeError("Excel-шаблон ТЭП повреждён или не найден") from exc
    if not content.startswith(b"PK"):
        raise RuntimeError("Excel-шаблон ТЭП повреждён")
    return _telegram_send_document_bytes(
        chat_id,
        content,
        MANUAL_TEP_TEMPLATE_FILENAME,
        (
            "<b>Excel-шаблон исходного ТЭП DevelopAid</b>\\n\\n"
            "1. Заполните общие сведения и жёлтые ячейки ТЭП.\\n"
            "2. Не переименовывайте лист, не меняйте коды и не удаляйте строки.\\n"
            "3. Сохраните файл в формате .xlsx и отправьте его обратно в этот чат.\\n\\n"
            "Бот проверит структуру, покажет сводку и предложит открыть проект в DevelopAid."
        ),
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
'''

if text.count(old_template) != 1:
    raise RuntimeError(f"template function anchor count: {text.count(old_template)}")
text = text.replace(old_template, new_template, 1)

text = text.replace('version="0.12.27"', 'version="0.12.28"', 1)
text = text.replace('"version": "0.12.27"', '"version": "0.12.28"', 1)
text = text.replace('Версия: 0.12.27', 'Версия: 0.12.28', 1)

path.write_text(text, encoding="utf-8")
