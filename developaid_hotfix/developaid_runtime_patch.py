from __future__ import annotations

import os
import sys
from pathlib import Path

_HOTFIX_MARKER = "# _DEVELOPAID_TELEGRAM_HELP_CLOSE_V01230"


def _find_main_file() -> Path:
    candidates = [
        Path.cwd() / "main.py",
        Path("/opt/render/project/src/main.py"),
    ]
    render_root = os.environ.get("RENDER_PROJECT_ROOT")
    if render_root:
        candidates.extend([
            Path(render_root) / "main.py",
            Path(render_root) / "src" / "main.py",
        ])
    for entry in sys.path:
        if entry:
            candidates.append(Path(entry) / "main.py")

    seen: set[str] = set()
    for candidate in candidates:
        try:
            resolved = candidate.resolve()
        except Exception:
            resolved = candidate
        key = str(resolved)
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


def _replace_once(text: str, old: str, new: str, label: str) -> str:
    if new in text:
        return text
    if old not in text:
        raise RuntimeError(f"DevelopAid startup patch: marker not found: {label}")
    return text.replace(old, new, 1)


def _patch_main(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    if _HOTFIX_MARKER in text:
        return

    text = text.replace('version="0.12.29"', 'version="0.12.30"')
    text = text.replace('"version": "0.12.29"', '"version": "0.12.30"')
    text = text.replace('Версия: 0.12.29', 'Версия: 0.12.30')

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
        "<b>4. Задайте вопрос Платону Сергеевичу Федоскину</b>\n"
        "Встроенный AI-консультант работает с текущей моделью. Ему можно написать обычным языком: "
        "«почему такой LLCR», «за сколько максимум можно купить», «какая цена продаж нужна», "
        "«что будет при росте СМР» или «подбери параметры проекта».\n\n"
        "Платон Сергеевич может выполнить сценарный пересчёт и подготовить изменения вводных. "
        "Самостоятельно модель он не меняет: новые параметры применяются только после подтверждения "
        "кнопкой «Применить в модель».\n\n"
        "<b>5. Сформируйте результат</b>\n"
        "В приложении доступны сводный отчёт, сравнение очередей, календарный план и PDF "
        "с ключевыми графиками.\n\n"
        "<i>Расчёт является предварительной инвестиционной моделью, а не отчётом оценщика "
        "и не решением банка. Доплата по коэффициенту Д пока автоматически не прогнозируется.</i>",
        reply_markup={"inline_keyboard": [
            [{"text": "Расчёт по кадастровым номерам", "callback_data": "flow_cad_yes"}],
            [{"text": "Собрать ТЭП без кадастра", "callback_data": "flow_cad_no"}],
            [{
                "text": "Открыть мини-приложение DevelopAid",
                "web_app": {"url": _telegram_web_app_url(chat_id, [])},
            }],
        ]},
    )


'''
    if "def _telegram_send_help(" not in text:
        if handler_marker not in text:
            raise RuntimeError("DevelopAid startup patch: Telegram handler marker not found")
        text = text.replace(handler_marker, help_function + handler_marker, 1)

    old_commands = '''    if command in {"/start", "/help", "/menu"}:
        _telegram_start_message(chat_id, user_id)
        return
'''
    new_commands = '''    if command in {"/start", "/menu"}:
        _telegram_start_message(chat_id, user_id)
        return
    if command == "/help":
        if not _telegram_user_allowed(user_id):
            _telegram_start_message(chat_id, user_id)
        else:
            _telegram_send_help(chat_id)
        return
'''
    text = _replace_once(text, old_commands, new_commands, "command /help")

    old_callback = '''        if data == "show_help":
            _telegram_send_message(
                chat_id,
                "<b>Что умеет DevelopAid</b>\\n\\n"
                "• рассчитывает ТЭП по кадастровым номерам и принимает ручной ТЭП;\\n"
                "• моделирует продажи, затраты, налоги, БРИДЖ, ПФ и эскроу;\\n"
                "• позволяет настраивать прогноз ключевой ставки и сценарии;\\n"
                "• считает одноочередные и многоочередные проекты;\\n"
                "• распределяет общепроектные расходы и социальную нагрузку по очередям;\\n"
                "• формирует PDF-отчёт с графиками и календарным Gantt.\\n\\n"
                "Для детальной настройки откройте мини-приложение DevelopAid.",
                reply_markup={"inline_keyboard": [[{
                    "text": "Открыть мини-приложение DevelopAid",
                    "web_app": {"url": _telegram_web_app_url(chat_id, [])},
                }]]},
            )
            return
'''
    new_callback = '''        if data == "show_help":
            _telegram_send_help(chat_id)
            return
'''
    text = _replace_once(text, old_callback, new_callback, "show_help callback")

    welcome_old = '''        "DevelopAid рассчитает экономику, потребность в финансировании, динамику долга и эскроу, прибыль, "
        "маржинальность и LLCR, а также сформирует PDF-отчёт с графиками и календарным планом.\\n\\n"
'''
    welcome_new = '''        "DevelopAid рассчитает экономику, потребность в финансировании, динамику долга и эскроу, прибыль, "
        "маржинальность и LLCR, а также сформирует PDF-отчёт с графиками и календарным планом.\\n\\n"
        "В мини-приложении Платон Сергеевич Федоскин может ответить на вопросы по текущей модели, "
        "подобрать цену покупки и другие параметры, а затем предложить изменения для вашего подтверждения.\\n\\n"
'''
    text = _replace_once(text, welcome_old, welcome_new, "welcome Platon text")

    send_marker = "async function sendTelegramResult(){\n"
    close_helper = r'''function closeTelegramWebAppAfterResult(){
 const tg=window.Telegram&&window.Telegram.WebApp;
 if(!tg||telegramMode==='edit')return false;
 try{if(typeof tg.disableClosingConfirmation==='function')tg.disableClosingConfirmation()}catch(e){}
 try{if(tg.MainButton)tg.MainButton.hide()}catch(e){}
 try{if(tg.BackButton)tg.BackButton.hide()}catch(e){}
 const closeNow=()=>{try{tg.close()}catch(e){}};
 setTimeout(closeNow,300);
 setTimeout(closeNow,1100);
 return true;
}

'''
    if "function closeTelegramWebAppAfterResult()" not in text:
        if send_marker not in text:
            raise RuntimeError("DevelopAid startup patch: sendTelegramResult marker not found")
        text = text.replace(send_marker, close_helper + send_marker, 1)

    send_start = text.index(send_marker)
    send_end = text.index("\n}\n\nasync function applyGlavapu()", send_start)
    send_block = text[send_start:send_end]

    success_old = """    if(window.Telegram&&window.Telegram.WebApp){
      window.Telegram.WebApp.ready();
      if(window.Telegram.WebApp.HapticFeedback)window.Telegram.WebApp.HapticFeedback.notificationOccurred('success');
    }
"""
    success_new = """    if(window.Telegram&&window.Telegram.WebApp){
      window.Telegram.WebApp.ready();
      if(window.Telegram.WebApp.HapticFeedback)window.Telegram.WebApp.HapticFeedback.notificationOccurred('success');
      closeTelegramWebAppAfterResult();
    }
"""
    send_block = _replace_once(send_block, success_old, success_new, "Telegram result success close")
    text = text[:send_start] + send_block + text[send_end:]

    old_cad_close = """    if(window.Telegram&&window.Telegram.WebApp&&telegramResultSent){
     setTimeout(()=>window.Telegram.WebApp.close(),700);
    }
"""
    new_cad_close = """    if(telegramResultSent)closeTelegramWebAppAfterResult();
"""
    text = _replace_once(text, old_cad_close, new_cad_close, "cadastral close")

    text += f"\n{_HOTFIX_MARKER}\n"
    path.write_text(text, encoding="utf-8")


def apply_patch() -> None:
    _patch_main(_find_main_file())
