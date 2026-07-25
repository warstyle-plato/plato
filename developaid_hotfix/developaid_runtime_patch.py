from __future__ import annotations

import os
import re
import sys
from pathlib import Path

_HOTFIX_MARKER = "# _DEVELOPAID_TELEGRAM_HELP_CLOSE_V01233"


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
    raise RuntimeError("DevelopAid startup patch: main.py not found")


def _replace_regex(text: str, pattern: str, replacement: str, label: str, *, flags: int = 0) -> str:
    updated, count = re.subn(pattern, replacement, text, count=1, flags=flags)
    if count != 1:
        raise RuntimeError(f"DevelopAid startup patch: marker not found: {label}")
    return updated


def _patch_main(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    if _HOTFIX_MARKER in text:
        return

    for old in ("0.12.29", "0.12.30", "0.12.31", "0.12.32"):
        text = text.replace(f'version="{old}"', 'version="0.12.33"')
        text = text.replace(f'"version": "{old}"', '"version": "0.12.33"')
        text = text.replace(f"Версия: {old}", "Версия: 0.12.33")

    handler_marker = "def _telegram_handle_message(message: dict[str, Any]) -> None:\n"
    help_function = r'''def _telegram_send_help(chat_id: int) -> None:
    _telegram_send_message(
        chat_id,
        "<b>Как работать с DevelopAid</b>\n\n"
        "<b>1. Создайте исходный ТЭП</b>\n"
        "• для московского участка — отправьте один или несколько кадастровых номеров;\n"
        "• для проекта в другом регионе или без кадастра — ответьте на вопросы бота;\n"
        "• либо скачайте Excel-шаблон, заполните известные параметры и отправьте файл обратно в чат.\n\n"
        "Кадастровый автоматический расчёт использует нормативный калькулятор Москвы. "
        "Для других регионов ТЭП, градостроительные платежи и локальные нормативы необходимо "
        "вводить или уточнять вручную.\n\n"
        "<b>2. Проверьте проект в мини-приложении</b>\n"
        "После загрузки ТЭП можно изменить состав и площади продуктов, цены и темпы продаж, "
        "себестоимость, сроки ИРД и строительства, прогноз ключевой ставки, условия БРИДЖа "
        "и проектного финансирования.\n\n"
        "Для крупного проекта можно включить очередность, распределить квартиры, коммерцию, "
        "паркинг, общепроектные расходы и социальные объекты между очередями, а также настроить "
        "строительство или денежную компенсацию социальной нагрузки.\n\n"
        "<b>3. Получите инвестиционный вывод</b>\n"
        "DevelopAid считает выручку, CAPEX, EBITDA, чистую прибыль, NPV, LLCR, потребность "
        "в БРИДЖе и ПФ, динамику долга и эскроу. Блок «Инвестиционная оценка» показывает "
        "предварительную целесообразность покупки и допустимую цену входа по текущим предпосылкам.\n\n"
        "<b>4. Спросите Платона Сергеевича Федоскина</b>\n"
        "AI-консультант работает с текущей моделью: объясняет показатели, отвечает на вопросы, "
        "сравнивает сценарии и помогает подобрать цену покупки, цены продаж, СМР, сроки и параметры "
        "финансирования. Изменения применяются только после подтверждения пользователя.\n\n"
        "<b>5. Сформируйте результат</b>\n"
        "В приложении доступны сводный отчёт, сравнение очередей, календарный план и PDF "
        "с ключевыми графиками.\n\n"
        "<i>Расчёт является предварительной инвестиционной моделью, а не отчётом оценщика "
        "и не решением банка. Доплата по коэффициенту Д пока автоматически не прогнозируется.</i>",
        reply_markup={"inline_keyboard": [
            [{"text": "Расчёт по кадастровым номерам", "callback_data": "flow_cad_yes"}],
            [{"text": "Собрать ТЭП без кадастра", "callback_data": "flow_cad_no"}],
            [{"text": "Открыть мини-приложение DevelopAid", "web_app": {"url": _telegram_web_app_url(chat_id, [])}}],
        ]},
    )


'''
    if "def _telegram_send_help(" not in text:
        if handler_marker not in text:
            raise RuntimeError("DevelopAid startup patch: Telegram handler not found")
        text = text.replace(handler_marker, help_function + handler_marker, 1)

    if 'if command == "/help":' not in text:
        text = _replace_regex(
            text,
            r'(?m)^    if command in \{"/start", "/help", "/menu"\}:\n'
            r'        _telegram_start_message\(chat_id, user_id\)\n'
            r'        return\n',
            '    if command in {"/start", "/menu"}:\n'
            '        _telegram_start_message(chat_id, user_id)\n'
            '        return\n'
            '    if command == "/help":\n'
            '        if not _telegram_user_allowed(user_id):\n'
            '            _telegram_start_message(chat_id, user_id)\n'
            '        else:\n'
            '            _telegram_send_help(chat_id)\n'
            '        return\n',
            "command /help",
        )

    if 'if data == "show_help":\n            _telegram_send_help(chat_id)' not in text:
        text = _replace_regex(
            text,
            r'(?ms)^        if data == "show_help":\n.*?^            return\n(?=        if data\.startswith\("flow_"\):)',
            '        if data == "show_help":\n'
            '            _telegram_send_help(chat_id)\n'
            '            return\n',
            "show_help callback",
        )

    welcome_marker = (
        '        "маржинальность и LLCR, а также сформирует PDF-отчёт с графиками и календарным планом.\\n\\n"\n'
    )
    welcome_addition = (
        welcome_marker
        + '        "В мини-приложении Платон Сергеевич Федоскин отвечает на вопросы по текущему расчёту, "\n'
        + '        "помогает подобрать цену покупки и другие параметры и предлагает изменения для подтверждения.\\n\\n"\n'
    )
    if "Платон Сергеевич Федоскин отвечает на вопросы по текущему расчёту" not in text:
        if welcome_marker not in text:
            raise RuntimeError("DevelopAid startup patch: welcome text marker not found")
        text = text.replace(welcome_marker, welcome_addition, 1)

    send_marker = "async function sendTelegramResult(){\n"
    close_helper = r'''function closeTelegramWebAppAfterResult(){
 const tg=window.Telegram&&window.Telegram.WebApp;
 if(!tg)return false;
 try{if(typeof tg.disableClosingConfirmation==='function')tg.disableClosingConfirmation()}catch(e){}
 try{if(tg.MainButton)tg.MainButton.hide()}catch(e){}
 try{if(tg.BackButton)tg.BackButton.hide()}catch(e){}
 const closeNow=()=>{try{tg.close()}catch(e){}};
 setTimeout(closeNow,150);
 setTimeout(closeNow,700);
 setTimeout(closeNow,1500);
 return true;
}

'''
    if "function closeTelegramWebAppAfterResult()" not in text:
        if send_marker not in text:
            raise RuntimeError("DevelopAid startup patch: sendTelegramResult not found")
        text = text.replace(send_marker, close_helper + send_marker, 1)

    send_start = text.index(send_marker)
    send_end = text.index("\n}\n\nasync function applyGlavapu()", send_start)
    send_block = text[send_start:send_end]
    if "closeTelegramWebAppAfterResult();" not in send_block:
        send_block, count = re.subn(
            r"(?m)^(\s*)if\(window\.Telegram\.WebApp\.HapticFeedback\)window\.Telegram\.WebApp\.HapticFeedback\.notificationOccurred\('success'\);\s*$",
            lambda match: match.group(0) + "\n" + match.group(1) + "closeTelegramWebAppAfterResult();",
            send_block,
            count=1,
        )
        if count != 1:
            raise RuntimeError("DevelopAid startup patch: result success marker not found")
    text = text[:send_start] + send_block + text[send_end:]

    text = re.sub(
        r'(?ms)^\s*if\(window\.Telegram&&window\.Telegram\.WebApp&&telegramResultSent\)\{\n'
        r'\s*setTimeout\(\(\)=>window\.Telegram\.WebApp\.close\(\),700\);\n\s*\}\n',
        '    if(telegramResultSent)closeTelegramWebAppAfterResult();\n',
        text,
        count=1,
    )

    required = [
        'version="0.12.33"',
        "def _telegram_send_help",
        'if command == "/help"',
        'if data == "show_help":\n            _telegram_send_help(chat_id)',
        "function closeTelegramWebAppAfterResult()",
        "closeTelegramWebAppAfterResult();",
    ]
    missing = [marker for marker in required if marker not in text]
    if missing:
        raise RuntimeError("DevelopAid startup patch: missing markers: " + ", ".join(missing))

    text += f"\n{_HOTFIX_MARKER}\n"
    compile(text, str(path), "exec")
    path.write_text(text, encoding="utf-8")


def apply_patch() -> None:
    _patch_main(_find_main_file())
