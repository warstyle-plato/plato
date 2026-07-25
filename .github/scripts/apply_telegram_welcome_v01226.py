from pathlib import Path

path = Path("main.py")
text = path.read_text(encoding="utf-8")

old_button = '''    button = {"inline_keyboard": [
        [{"text": "ТЭП по кадастровым номерам", "callback_data": "flow_cad_yes"}],
        [{"text": "Собрать ТЭП без кадастра", "callback_data": "flow_cad_no"}],
        [{"text": "Скачать Excel-шаблон ТЭП", "callback_data": "tep_template"}],
        [{"text": "Открыть модель DevelopAid", "web_app": {"url": _telegram_web_app_url(chat_id, [])}}],
    ]}
'''
new_button = '''    button = {"inline_keyboard": [
        [{"text": "Расчёт по кадастровым номерам", "callback_data": "flow_cad_yes"}],
        [{"text": "Собрать ТЭП без кадастра", "callback_data": "flow_cad_no"}],
        [{"text": "Загрузить Excel-шаблон", "callback_data": "tep_template"}],
        [{"text": "Открыть мини-приложение DevelopAid", "web_app": {"url": _telegram_web_app_url(chat_id, [])}}],
        [{"text": "Что умеет DevelopAid", "callback_data": "show_help"}],
    ]}
'''
if old_button not in text:
    raise SystemExit("start keyboard block not found")
text = text.replace(old_button, new_button, 1)

old_message = '''        "<b>DevelopAid · быстрый расчёт девелоперского проекта</b>\\n\\n"
        "Я могу:\\n"
        "• получить ТЭП ГлавАПУ по кадастровым номерам;\\n"
        "• собрать ТЭП без кадастра — задам вопросы и рассчитаю недостающее по нормативам;\\n"
        "• принять заполненный Excel-шаблон;\\n"
        "• открыть DevelopAid для подробной экономики и сценарного анализа.\\n\\n"
        "Выберите способ работы. Вернуться сюда можно в любой момент через кнопку "
        "<b>Menu</b> у строки ввода или командой /start.",
'''
new_message = '''        "<b>Добро пожаловать в DevelopAid</b>\\n\\n"
        "Если на переговорах в «Кофемании» нужно за пять минут отфильтровать 50–60 земельных участков, "
        "на встрече — на пальцах объяснить региональному девелоперу, почему трёхлетний БРИДЖ не позволяет "
        "купить проект по 100 тысяч рублей за метр, или вы просто решили немного оптимизировать расходы "
        "на аналитиков перед покупкой проекта в Ховрино — <b>DevelopAid вам поможет</b>.\\n\\n"
        "Модель работает с проектами <b>по всей России</b>, а не только в Москве.\\n\\n"
        "Начать расчёт можно:\\n"
        "• по кадастровым номерам участков;\\n"
        "• без кадастра, ответив на вопросы бота;\\n"
        "• загрузив заполненный Excel-шаблон.\\n\\n"
        "После первичного расчёта проект можно открыть в мини-приложении и настроить практически всё:\\n"
        "• ТЭП и состав продуктов;\\n"
        "• цены и темпы продаж;\\n"
        "• себестоимость и сроки строительства;\\n"
        "• прогноз ключевой ставки;\\n"
        "• БРИДЖ и проектное финансирование;\\n"
        "• очередность проекта;\\n"
        "• распределение расходов и социальной нагрузки;\\n"
        "• строительство или компенсацию социальных объектов;\\n"
        "• сценарии изменения доходов и затрат.\\n\\n"
        "DevelopAid рассчитает экономику, потребность в финансировании, динамику долга и эскроу, прибыль, "
        "маржинальность и LLCR, а также сформирует PDF-отчёт с графиками и календарным планом.\\n\\n"
        "<i>Доплату по коэффициенту Д, увы, пока не предсказывает.</i>\\n\\n"
        "<b>С чего начнём?</b>",
'''
if old_message not in text:
    raise SystemExit("start message block not found")
text = text.replace(old_message, new_message, 1)

old_callback = '''        if data == "tep_template":
            _telegram_send_template(chat_id)
            return
        if data.startswith("flow_"):
'''
new_callback = '''        if data == "tep_template":
            _telegram_send_template(chat_id)
            return
        if data == "show_help":
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
        if data.startswith("flow_"):
'''
if old_callback not in text:
    raise SystemExit("callback insertion point not found")
text = text.replace(old_callback, new_callback, 1)

text = text.replace('Версия: 0.12.25', 'Версия: 0.12.26')
text = text.replace('"version": "0.12.25",', '"version": "0.12.26",')

compile(text, "main.py", "exec")
path.write_text(text, encoding="utf-8")
