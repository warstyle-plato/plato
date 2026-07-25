from __future__ import annotations

import os
import sys
from pathlib import Path

_MARKER = "# _DEVELOPAID_TELEGRAM_ANSWER_WEBAPP_QUERY_V01231"


def _find_main_file() -> Path:
    candidates = [Path.cwd() / "main.py", Path("/opt/render/project/src/main.py")]
    render_root = os.environ.get("RENDER_PROJECT_ROOT")
    if render_root:
        candidates.extend([Path(render_root) / "main.py", Path(render_root) / "src" / "main.py"])
    candidates.extend(Path(item) / "main.py" for item in sys.path if item)
    seen: set[str] = set()
    for candidate in candidates:
        try:
            key = str(candidate.resolve())
        except Exception:
            key = str(candidate)
        if key in seen:
            continue
        seen.add(key)
        if not candidate.is_file():
            continue
        try:
            head = candidate.read_text(encoding="utf-8")[:5000]
        except Exception:
            continue
        if "DevelopAid Development Investment Model" in head:
            return candidate
    raise RuntimeError("DevelopAid answerWebAppQuery patch: main.py not found")


def _replace_once(text: str, old: str, new: str, label: str) -> str:
    if new in text:
        return text
    if old not in text:
        raise RuntimeError(f"DevelopAid answerWebAppQuery patch: marker not found: {label}")
    return text.replace(old, new, 1)


def apply_patch() -> None:
    path = _find_main_file()
    text = path.read_text(encoding="utf-8")
    if _MARKER in text:
        return

    text = text.replace('version="0.12.30"', 'version="0.12.31"')
    text = text.replace('"version": "0.12.30"', '"version": "0.12.31"')
    text = text.replace('Версия: 0.12.30', 'Версия: 0.12.31')

    text = _replace_once(
        text,
        '''class TelegramResultRequest(BaseModel):
    session: str
    summary: dict[str, Any]
''',
        '''class TelegramResultRequest(BaseModel):
    session: str
    summary: dict[str, Any]
    web_app_query_id: str = ""
''',
        "TelegramResultRequest",
    )

    result_start = text.index('@app.post("/telegram/result")')
    result_end = text.index("\n\n\ndef _server_preset_meta", result_start)
    result_block = text[result_start:result_end]
    result_block = _replace_once(
        result_block,
        '    _telegram_send_message(chat_id, text, reply_markup=button)\n',
        '''    answered_web_app = False
    web_app_query_id = str(req.web_app_query_id or "").strip()
    if web_app_query_id:
        try:
            inline_result = {
                "type": "article",
                "id": hashlib.sha256(
                    f"{web_app_query_id}:{chat_id}:{time.time_ns()}".encode("utf-8")
                ).hexdigest()[:32],
                "title": "Расчёт DevelopAid готов",
                "input_message_content": {
                    "message_text": text,
                    "parse_mode": "HTML",
                },
                "reply_markup": button,
            }
            _telegram_api("answerWebAppQuery", {
                "web_app_query_id": web_app_query_id,
                "result": inline_result,
            })
            answered_web_app = True
        except Exception as exc:
            _TELEGRAM_RUNTIME["last_error"] = "answerWebAppQuery: " + str(exc)
    if not answered_web_app:
        _telegram_send_message(chat_id, text, reply_markup=button)
''',
        "answerWebAppQuery delivery",
    )
    result_block = _replace_once(
        result_block,
        '    return {"ok": True}\n',
        '    return {"ok": True, "closed_by_telegram": answered_web_app}\n',
        "closed_by_telegram response",
    )
    text = text[:result_start] + result_block + text[result_end:]

    send_start = text.index("async function sendTelegramResult(){\n")
    send_end = text.index("\n}\n\nasync function applyGlavapu()", send_start)
    send_block = text[send_start:send_end]
    send_block = _replace_once(
        send_block,
        '''  persistLocalSilently();
  const payload={
''',
        '''  persistLocalSilently();
  const tg=window.Telegram&&window.Telegram.WebApp;
  const webAppQueryId=tg&&tg.initDataUnsafe?String(tg.initDataUnsafe.query_id||''):'';
  const payload={
''',
        "query_id capture",
    )
    send_block = _replace_once(
        send_block,
        '      body:JSON.stringify({session:telegramSession,summary:payload})\n',
        '      body:JSON.stringify({session:telegramSession,summary:payload,web_app_query_id:webAppQueryId})\n',
        "query_id submit",
    )
    send_block = _replace_once(
        send_block,
        '''      closeTelegramWebAppAfterResult();
''',
        '''      if(!result.closed_by_telegram)closeTelegramWebAppAfterResult();
''',
        "client close fallback",
    )
    text = text[:send_start] + send_block + text[send_end:]

    text = text.replace(
        "if(!tg||telegramMode==='edit')return false;",
        "if(!tg)return false;",
        1,
    )
    text = text.replace(
        "   if(tg){setTimeout(()=>tg.close(),700)}",
        "   if(tg)closeTelegramWebAppAfterResult();",
        1,
    )

    text += f"\n{_MARKER}\n"
    path.write_text(text, encoding="utf-8")
