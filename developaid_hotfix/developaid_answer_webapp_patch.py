from __future__ import annotations

import os
import re
import sys
from pathlib import Path

_MARKER = "# _DEVELOPAID_TELEGRAM_ANSWER_WEBAPP_QUERY_V01235"


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

    for old in ("0.12.29", "0.12.30", "0.12.31", "0.12.32", "0.12.33", "0.12.34"):
        text = text.replace(f'version="{old}"', 'version="0.12.35"')
        text = text.replace(f'"version": "{old}"', '"version": "0.12.35"')
        text = text.replace(f"Версия: {old}", "Версия: 0.12.35")

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
            telegram_answer = _telegram_api("answerWebAppQuery", {
                "web_app_query_id": web_app_query_id,
                "result": inline_result,
            })
            if isinstance(telegram_answer, dict) and telegram_answer.get("ok") is False:
                raise RuntimeError(str(telegram_answer.get("description") or telegram_answer))
            answered_web_app = True
        except Exception as exc:
            web_app_close_error = str(exc)
            _TELEGRAM_RUNTIME["last_error"] = "answerWebAppQuery: " + web_app_close_error
    else:
        web_app_close_error = "query_id отсутствует: приложение открыто не через Web App-кнопку Telegram"
        _TELEGRAM_RUNTIME["last_error"] = "answerWebAppQuery: " + web_app_close_error
    _TELEGRAM_RUNTIME["last_web_app_close"] = {
        "query_id_present": bool(web_app_query_id),
        "closed_by_telegram": answered_web_app,
        "error": web_app_close_error,
        "at": int(time.time()),
    }
    _telegram_send_message(chat_id, text, reply_markup=button)'''

    if "last_web_app_close" not in result_block:
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

    if "data-close-diagnostic" not in send_block:
        diagnostic = '''    if(!result.closed_by_telegram){
      const diagnostic=document.createElement('div');
      diagnostic.setAttribute('data-close-diagnostic','1');
      diagnostic.className='import-error';
      diagnostic.textContent='Telegram не подтвердил закрытие: '+(result.close_error||'query_id не принят')+'. Закройте окно стрелкой; диагностика сохранена в /status.';
      if(status)status.appendChild(diagnostic);
    }
'''
        marker = "    telegramResultSent=true;\n"
        if marker not in send_block:
            raise RuntimeError("DevelopAid answerWebAppQuery patch: telegramResultSent marker not found")
        send_block = send_block.replace(marker, marker + diagnostic, 1)

    text = text[:send_start] + send_block + text[send_end:]

    status_marker = '''            f"Версия: {app.version}",
'''
    if "last_web_app_close" not in text[text.index("if command == \"/status\""):text.index("if command == \"/status\"") + 2000]:
        status_addition = '''            f"Версия: {app.version}",
            (lambda close: (
                "Закрытие Mini App: "
                + ("Telegram подтвердил" if close.get("closed_by_telegram") else "не подтверждено")
                + ("; query_id есть" if close.get("query_id_present") else "; query_id отсутствует")
                + (("; ошибка: " + str(close.get("error"))) if close.get("error") else "")
            ))(_TELEGRAM_RUNTIME.get("last_web_app_close", {})),
'''
        if status_marker in text:
            text = text.replace(status_marker, status_addition, 1)

    required = [
        'version="0.12.35"',
        "web_app_query_id: str",
        'answerWebAppQuery',
        'telegram_answer = _telegram_api',
        'last_web_app_close',
        "const webAppQueryId=",
        "web_app_query_id:webAppQueryId",
        "data-close-diagnostic",
    ]
    missing = [marker for marker in required if marker not in text]
    if missing:
        raise RuntimeError("DevelopAid answerWebAppQuery patch: missing markers: " + ", ".join(missing))

    text += f"\n{_MARKER}\n"
    compile(text, str(path), "exec")
    path.write_text(text, encoding="utf-8")
