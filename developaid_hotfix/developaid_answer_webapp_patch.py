from __future__ import annotations

import os
import re
import sys
from pathlib import Path

_MARKER = "# _DEVELOPAID_TELEGRAM_ANSWER_WEBAPP_QUERY_V01234"


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

    for old in ("0.12.29", "0.12.30", "0.12.31", "0.12.32", "0.12.33"):
        text = text.replace(f'version="{old}"', 'version="0.12.34"')
        text = text.replace(f'"version": "{old}"', '"version": "0.12.34"')
        text = text.replace(f"Версия: {old}", "Версия: 0.12.34")

    if "web_app_query_id: str" not in text:
        pattern = (
            r"(class TelegramResultRequest\(BaseModel\):\n"
            r"\s+session: str\n"
            r"\s+summary: dict\[str, Any\]\n)"
        )
        text, count = re.subn(pattern, r'\1    web_app_query_id: str = ""\n', text, count=1)
        if count != 1:
            raise RuntimeError("DevelopAid answerWebAppQuery patch: TelegramResultRequest not found")

    result_start = text.index('@app.post("/telegram/result")')
    result_end = text.index("\n\n\ndef _server_preset_meta", result_start)
    result_block = text[result_start:result_end]

    delivery_line = "    _telegram_send_message(chat_id, text, reply_markup=button)"
    delivery_block = '''    answered_web_app = False
    web_app_close_error = ""
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
                    "message_text": "Расчёт DevelopAid завершён. Итоговая карточка и PDF отправлены ботом."
                },
            }
            _telegram_api("answerWebAppQuery", {
                "web_app_query_id": web_app_query_id,
                "result": inline_result,
            })
            answered_web_app = True
        except Exception as exc:
            web_app_close_error = str(exc)
            _TELEGRAM_RUNTIME["last_error"] = "answerWebAppQuery: " + web_app_close_error
    _telegram_send_message(chat_id, text, reply_markup=button)'''

    if "web_app_close_error =" not in result_block:
        result_block = _replace_once(
            result_block,
            delivery_line,
            delivery_block,
            "answerWebAppQuery delivery",
        )

    if '"closed_by_telegram": answered_web_app' not in result_block:
        result_block = _replace_once(
            result_block,
            '    return {"ok": True}',
            '    return {"ok": True, "closed_by_telegram": answered_web_app, "query_id_present": bool(web_app_query_id), "close_error": web_app_close_error}',
            "closed_by_telegram response",
        )
    text = text[:result_start] + result_block + text[result_end:]

    send_start = text.index("async function sendTelegramResult(){\n")
    send_end = text.index("\n}\n\nasync function applyGlavapu()", send_start)
    send_block = text[send_start:send_end]

    if "const webAppQueryId=" not in send_block:
        send_block, count = re.subn(
            r"(?m)^(\s*)persistLocalSilently\(\);\s*$",
            lambda match: (
                f"{match.group(1)}persistLocalSilently();\n"
                f"{match.group(1)}const tg=window.Telegram&&window.Telegram.WebApp;\n"
                f"{match.group(1)}const rawInitData=tg?String(tg.initData||''):'';\n"
                f"{match.group(1)}const webAppQueryId=tg?String((tg.initDataUnsafe&&tg.initDataUnsafe.query_id)||new URLSearchParams(rawInitData).get('query_id')||''):'';"
            ),
            send_block,
            count=1,
        )
        if count != 1:
            raise RuntimeError("DevelopAid answerWebAppQuery patch: persistLocalSilently marker not found")

    if "web_app_query_id:webAppQueryId" not in send_block:
        send_block = _replace_once(
            send_block,
            "body:JSON.stringify({session:telegramSession,summary:payload})",
            "body:JSON.stringify({session:telegramSession,summary:payload,web_app_query_id:webAppQueryId})",
            "query_id submit",
        )

    send_block = send_block.replace(
        "if(!result.closed_by_telegram)closeTelegramWebAppAfterResult();",
        "closeTelegramWebAppAfterResult();",
        1,
    )
    if "closeTelegramWebAppAfterResult();" not in send_block:
        send_block, count = re.subn(
            r"(?m)^(\s*)if\(window\.Telegram\.WebApp\.HapticFeedback\)window\.Telegram\.WebApp\.HapticFeedback\.notificationOccurred\('success'\);\s*$",
            lambda match: match.group(0) + "\n" + match.group(1) + "closeTelegramWebAppAfterResult();",
            send_block,
            count=1,
        )
        if count != 1:
            raise RuntimeError("DevelopAid answerWebAppQuery patch: client close fallback not found")

    text = text[:send_start] + send_block + text[send_end:]

    required = [
        'version="0.12.34"',
        "web_app_query_id: str",
        'answerWebAppQuery',
        'web_app_close_error =',
        '"closed_by_telegram": answered_web_app',
        "const webAppQueryId=",
        "web_app_query_id:webAppQueryId",
        "closeTelegramWebAppAfterResult();",
    ]
    missing = [marker for marker in required if marker not in text]
    if missing:
        raise RuntimeError("DevelopAid answerWebAppQuery patch: missing markers: " + ", ".join(missing))

    text += f"\n{_MARKER}\n"
    compile(text, str(path), "exec")
    path.write_text(text, encoding="utf-8")
