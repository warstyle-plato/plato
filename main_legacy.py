
from __future__ import annotations

import calendar
import base64
import concurrent.futures
import contextvars
import functools
import csv
import gzip
import copy
import hashlib
import hmac
import html
import http.client
import json
import logging
import os
import queue
import threading
import time
import math
import io
import secrets
import re
import shutil
import ssl
import zipfile

# Кем Платон думает — переключатель, а не найденный ключ:
# перевод запроса и ответа живёт на границе поставщика.
import plato_provider
# Подписи величин — у словаря терминов, здесь только чтение.
from terms_glossary import (CORE_ABOVE_AREA, CORE_TOTAL_AREA, CORE_UNDER_AREA, OBJECTS_TOTAL_AREA, SALEABLE_AREA,
                            TERMS, TOTAL_AREA, capex_unit_base, page_terms, unit_label)
import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape as xml_escape

# Запуск Chromium — общий: его заводят и ГлавАПУ, и печать отчёта, и ломается
# он у обоих сразу, а наружу выходит по-разному.
import browser_launch
import glavapu_scenario
import site_position
import vri_benefits
# Профиль освоения стройки: им движок разносит СМР, им же отчёт о рынке считает
# готовность дома по датам. Одна кривая на оба вопроса.
import build_curve
import socket
import urllib.parse
import urllib.error
import urllib.request
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from math import ceil, pow, exp
from typing import Any, Callable, NamedTuple
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse, Response
from pydantic import BaseModel

# Факт действующего проекта — РСС, реестр договоров, помесячные ряды — и
# наложение этого факта на плановую модель. Отдельным модулем по той же
# причине: он о выгрузках и их разборе, движок — об экономике.
import developaid_actuals
import developaid_nonres_strategy as nonres_strategy
import developaid_hotel_strategy as hotel_strategy
import hotel_presets
from developaid_finance_math import (
    LOSS_CARRY_USE_LIMIT as _LOSS_CARRY_USE_LIMIT,
    equity_npv as _equity_npv,
    monthly_irr as _monthly_irr,
    monthly_npv as _monthly_npv,
    profit_tax_schedule as _profit_tax_schedule,
)
import developaid_monitor
import developaid_monitor_daily
import developaid_monitor_scenarios
from developaid_monitor_page import MONITOR_PAGE as _MONITOR_PAGE_RAW

# Перевод документов проекта (ГПЗУ, ППТ, соглашения ВРИ и МПТ, справки по
# техприсоединению) в продукты и деньги модели живёт отдельным модулем: он о
# документах, движок — об экономике, и смешивать их незачем.
import document_intake
from request_body import json_object
import v4_book_polish
import v4_dashboard
import v4_entry_sheet
import v4_nonres_sheet
import nonres_workbook
import hotel_workbook
import v4_value_cache
import presentation as _presentation
import teaser_pdf as _teaser_pdf
import management_contour
import parking_norms
import plato_question
import project_preset

# Единственное место, где живёт номер версии. Копий было четырнадцать —
# тринадцать литералов здесь и своя в обёртке, — и полтора десятка выпусков их
# поднимали разом вручную. Стоило один раз поднять только обёртку, и стенд стал
# неотличим от невыкаченного: бот показывал 0.13.6, а `/health`, страница и
# заголовок ответа — 0.13.4. Обёртка `main.py` берёт значение отсюда же.
VERSION = "0.25.57"
# Коммит, из которого собран образ. Версия отвечает на «что выпущено», коммит —
# на «что сейчас крутится»: одна версия живёт много правок, и по ней не отличить
# выкаченный образ от собранного часом раньше. Значение запекается сборкой
# (ARG APP_COMMIT), запуску его задавать неоткуда — вне контейнера пусто.
COMMIT = (os.getenv("APP_COMMIT") or "").strip()[:40]
USER_AGENT = f"DevelopAid-Development-Model/{VERSION}"
# Плейсхолдер для страницы: PAGE — raw-строка с JS, и `.format` в ней применять
# нельзя, там свои фигурные скобки.
VERSION_PLACEHOLDER = "__DEVELOPAID_VERSION__"
# Список полей и умолчания жили на странице отдельной копией. Поле,
# добавленное в движок, на странице не появлялось: движок его считал,
# а нарисовать было некому. Теперь копия одна, подставляется на импорте.
FIELD_GROUPS_PLACEHOLDER = "__DEVELOPAID_FIELD_GROUPS__"
INPUT_DEFAULT_PLACEHOLDER = "__DEVELOPAID_INPUT_DEFAULT__"
# Поле, которое правят в настройках класса, а не во «Вводных» (решение
# владельца, 14.09.2026: «убрать норматив м²/чел из Вводных» — «Да»).
# Объявление поля при этом ОДНО и остаётся в `FIELD_GROUPS`: подпись и
# единицу берут оттуда и таблица классов (`classFieldLabel`,
# `class_field_unit`), и строка отклонений в PDF, — вычеркни запись, и
# в окне классов встанет сырой ключ без меры, то есть та же болезнь, что
# уже ловилась на именах статей расходов. Список короткий и явный: «скрывать
# всё, что есть в профиле класса» скрыло бы ставки, которым место во
# «Вводных» (владелец, 13.09.2026: «в водных будет привычный рублей на гнс,
# а в настройках класса нормы на человека»).
CLASS_ONLY_INPUTS_PLACEHOLDER = "__DEVELOPAID_CLASS_ONLY_INPUTS__"
SITE_ONLY_INPUTS_PLACEHOLDER = "__DEVELOPAID_SITE_ONLY_INPUTS__"
# Состав ТЭП страница держала своей копией — и та отстала: продукта
# «Прочие обязательные объекты» в ней не было вовсе. Движок его считал,
# очередность подписывала, а сброс возвращал набор без него. Лечится тем
# же способом, что поля и умолчания: копию негде обновлять, потому что
# копии нет.
TEP_DEFAULT_PLACEHOLDER = "__DEVELOPAID_TEP_DEFAULT__"
# Формы исполнения соцнагрузки страница держала своей копией, и третий режим
# в неё не попал: движок его считал, книга предлагала, а на странице выбрать
# было нельзя. Та же болезнь, что с полями и умолчаниями, — лечится так же.
SOCIAL_MODES_PLACEHOLDER = "__DEVELOPAID_SOCIAL_MODES__"
# Анкета обратной связи. Разделы объявлены здесь и подставляются на страницу
# тем же способом: список, живущий в двух местах, разойдётся при первой правке,
# а свод начнёт считать средние по разделам, которых уже нет.
FEEDBACK_FORM_PLACEHOLDER = "__DEVELOPAID_FEEDBACK_FORM__"

# Анкета: разделы с подпунктами и комментарием к каждому (структура владельца,
# 17.08.2026). Плоский список из девяти строк не годился: «Участок» — это и
# ввод адреса, и расчёт ТЭП, и очерёдность, и низкая оценка разделу не говорит,
# что из этого чинить. Отчёт, PDF и книга оцениваются по критериям, а не одним
# баллом: «красиво» ничего не значит, а «отправил бы банку» значит всё.
FEEDBACK_GROUPS: list[list[Any]] = [
    ["site", "Участок", [
        ["site_address", "Ввод адреса и кадастра", ""],
        ["site_egrn", "Сведения ЕГРН и карта", ""],
        ["site_tep", "Расчёт ТЭП", ""],
        ["site_tep_edit", "Редактирование ТЭП", ""],
        ["site_phasing", "Очерёдность", ""],
    ]],
    ["inputs", "Вводные", [
        ["inputs_presets", "Предустановки и класс проекта", ""],
        ["inputs_coverage", "Набор параметров", "хватает ли их"],
        ["inputs_scenarios", "Сценарии", ""],
        ["inputs_clarity", "Понятность полей", ""],
    ]],
    ["report", "Отчёт на экране", [
        ["report_completeness", "Полнота информации", ""],
        ["report_metrics", "Набор метрик", ""],
        ["report_clarity", "Простота восприятия", ""],
        # Метрики могут быть полными, восприятие простым, а человек результату
        # всё равно не верит. Это надо знать раньше всего остального.
        ["report_trust", "Доверие к цифрам", ""],
    ]],
    ["pdf", "PDF-отчёт", [
        ["pdf_completeness", "Полнота", ""],
        ["pdf_clarity", "Простота восприятия", ""],
        ["pdf_shareable", "Готовность показать банку или партнёру", ""],
    ]],
    ["excel", "Excel-модель", [
        # Первой строкой: книгу отдают живой ради того, чтобы её проверили.
        ["excel_correct", "Правильность расчёта", ""],
        ["excel_formulas", "Прозрачность формул", ""],
        ["excel_edit", "Удобство правки", ""],
    ]],
    ["platon", "Платон Сергеевич", [
        ["platon_useful", "Польза ответов", ""],
        ["platon_clarity", "Понятность", ""],
    ]],
    ["general", "Общее", [
        # Общая оценка стоит первой: её ставят все, а разделы — по желанию.
        # В боте анкета начинается с неё и часто ею и заканчивается.
        ["general_overall", "Общая оценка", ""],
        ["general_ui", "Интерфейс", ""],
        ["general_obvious", "Понятно без объяснений", ""],
    ]],
]

# Плоский список подпунктов — по нему сверяются пришедшие оценки.
FEEDBACK_ITEMS: dict[str, str] = {
    item[0]: item[1] for group in FEEDBACK_GROUPS for item in group[2]}

# Профиль — два поля списком. Печатать ничего не нужно: анкету заполняют между
# делом, и каждое поле ввода стоит доли ответивших.
FEEDBACK_ROLES = ["Брокер", "Девелопер", "Банк", "Оценщик", "Другое"]
FEEDBACK_REGIONS = ["Москва", "Московская область", "Регионы", "Всё вместе"]

# Куски движка лежат в engine/*.py. Каждый выполняется в пространстве имён
# этого модуля на том месте, где его код стоял раньше: так остаются одна
# копия движка (`developaid_core`) и прежний порядок объявлений, а подмены
# core.<имя> из main.py и тестов действуют на весь код, где бы он ни лежал.
# Обычный import здесь не годится: он поднял бы вторую копию движка, а
# подмены не доходили бы до вызовов внутри куска.
_ENGINE_PARTS_DIR = Path(__file__).resolve().parent / "engine"


def _engine_part(name: str) -> None:
    path = _ENGINE_PARTS_DIR / f"{name}.py"
    exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), globals())


app = FastAPI(title="DevelopAid Development Investment Model", version=VERSION)

# Нативное меню Telegram объявляется один раз — как VERSION. Список ставили
# два места: движок при настройке вебхука и обёртка на старте, побеждал
# последний — и /vritep из меню пропадал, хотя команда работала.
# Меню — шесть решений, а не тринадцать команд. Список Telegram плоский, и
# тринадцать строк в нём читались простынёй, где всё одинаково важно: пять
# входов в ТЭП вперемешку с Платоном и служебным, «ТЭП по кадастровым номерам»
# и «Посчитать ВРИ и ТЭП» на вид неразличимы.
#
# Вложенности в меню нет, но есть второй уровень — inline-кнопки. Пункт меню =
# решение, второй уровень = уточнение: «Расчёт модели» спрашивает, откуда взять
# ТЭП, «Расчёт ВРИ и ТЭП» — где участок. Способ выбирается там, где видно, что
# это выбор одного и того же, а не четыре разные функции подряд.
#
# Остальные команды работают по-прежнему и названы в помощи: команда вне меню,
# о которой негде узнать, просто спрятана.
TELEGRAM_BOT_COMMANDS = [
    {"command": "calc", "description": "Расчёт модели"},
    {"command": "model", "description": "Открыть готовую модель"},
    {"command": "vritep", "description": "Расчёт ВРИ и ТЭП"},
    {"command": "platon", "description": "Платон Сергеевич — ИИ-аналитик проекта"},
    {"command": "feedback", "description": "Оценить DevelopAid"},
    {"command": "help", "description": "Помощь · все команды"},
]
# Команды вне меню. Список нужен помощи и проверке: он держит их видимыми для
# человека и не даёт молча потерять разбор.
TELEGRAM_EXTRA_COMMANDS = [
    {"command": "start", "description": "Приветствие и все кнопки сразу"},
    {"command": "tep", "description": "Расчёт модели: свои вводные"},
    {"command": "address", "description": "Расчёт модели: по адресу"},
    {"command": "cadastre", "description": "Расчёт модели: по кадастровому номеру"},
    {"command": "template", "description": "Скачать Excel-шаблон ТЭП"},
    {"command": "comment", "description": "Платон о текущем ТЭП"},
    {"command": "cancel", "description": "Прервать диалог и начать заново"},
    {"command": "status", "description": "Статус и версия"},
    {"command": "notify", "description": "Что бот пишет сам — и как выключить"},
]
# Куда расширения вставляют свои пункты. Прежде они дописывали в конец, и
# расчёт льготы МПТ оказывался последним — ниже помощи. Якорем задано место:
# среди расчётов, перед Платоном.
TELEGRAM_MENU_EXTENSION_ANCHOR = "platon"

# Вводные проекта — пресеты, классы, отдельно стоящие объекты, группы
# и разделы вводных, виды проекта, тела запросов — вынесены в
# engine/inputs.py и выполняются здесь же, в пространстве имён движка:
# порядок объявлений и подмены core.<имя> остаются прежними.
_engine_part("inputs")


# Чтение ТЭП — выгрузка ГлавАПУ, ручной шаблон, свободный текст,
# соцнормы Москвы, build_freeform_tep, пресеты проекта — вынесено в
# engine/tep_import.py и выполняется здесь же, в пространстве имён движка:
# порядок объявлений и подмены core.<имя> остаются прежними.
_engine_part("tep_import")


# Недельный монитор действующего проекта — маршруты /monitor/* и его
# страница — вынесен в engine/monitor.py и выполняется здесь же, в
# пространстве имён движка: порядок объявлений и подмены core.<имя>
# остаются прежними.
_engine_part("monitor")


# Маршруты импорта — пресет проекта, ассеты, ТЭП из Excel и анализ
# территории ГлавАПУ — вынесены в engine/tep_import_routes.py и
# выполняются здесь же, в пространстве имён движка: порядок объявлений
# и подмены core.<имя> остаются прежними.
_engine_part("tep_import_routes")


# НСПД и зоны — поиск участка, скрининг ЗОУИТ, карты, геокодеры,
# land_lookup и маршруты ТЭП по участку — вынесены в engine/nspd.py и
# выполняются здесь же, в пространстве имён движка: порядок объявлений
# и подмены core.<имя> остаются прежними.
_engine_part("nspd")


# Калькулятор Подмосковья — УПКС, соцпрограмма РНГП МО, плата за ВРИ,
# mo_calculate и переадресация на ядро — вынесен в engine/mo_calc.py и
# выполняется здесь же, в пространстве имён движка: порядок объявлений
# и подмены core.<имя> остаются прежними.
_engine_part("mo_calc")


# Быстрый ТЭП по ВРИ — скелет ТЭП ГлавАПУ, vri_tep_quick, прокси
# генплана, книга из строк — вынесен в engine/vri_tep.py и выполняется
# здесь же, в пространстве имён движка: порядок объявлений и подмены
# core.<имя> остаются прежними.
_engine_part("vri_tep")


# Выгрузка полной модели в XLSX — ячейки, стили, листы, диаграммы —
# вынесена в engine/xlsx_export.py и выполняется здесь же, в пространстве
# имён движка: порядок объявлений и подмены core.<имя> остаются прежними.
_engine_part("xlsx_export")


# Нормативы — плата за ВРИ вручную, индексы Москвы, парковки, кладовые,
# пересчёт от базы ГлавАПУ, соцнормы — вынесены в engine/norms.py и
# выполняются здесь же, в пространстве имён движка: порядок объявлений
# и подмены core.<имя> остаются прежними.
_engine_part("norms")


# Штатный калькулятор ГлавАПУ на сервере — браузер, дрейф-контроль,
# сценарии, ТЭП по кадастровым номерам — вынесен в engine/glavapu.py и
# выполняется здесь же, в пространстве имён движка: порядок объявлений
# и подмены core.<имя> остаются прежними.
_engine_part("glavapu")


# Бот Telegram вынесен в engine/bot_telegram.py и выполняется здесь же,
# в пространстве имён движка: порядок объявлений и подмены core.<имя>
# остаются прежними.
_engine_part("bot_telegram")


# PDF-отчёт проекта — гарнитуры, разделы и вёрстка _build_developaid_pdf —
# вынесен в engine/report_pdf.py и выполняется здесь же, в пространстве
# имён движка: порядок объявлений и подмены core.<имя> остаются прежними.
_engine_part("report_pdf")


# Состав выгружаемой модели — колонки, подписи и листы XLSX — вынесен
# в engine/xlsx_model.py и выполняется здесь же, в пространстве имён
# движка: порядок объявлений и подмены core.<имя> остаются прежними.
_engine_part("xlsx_model")


# Единая книга проекта v4 — вводные, объекты, соцобъекты, сборка книги
# и маршрут /report/workbook — вынесена в engine/xlsx_book_v4.py и
# выполняется здесь же, в пространстве имён движка: порядок объявлений
# и подмены core.<имя> остаются прежними.
_engine_part("xlsx_book_v4")


# Выгрузка в шаблон ПЛАТО — заполнение шаблона, консолидатор, новая книга,
# сверка audit_plato_workbook — вынесена в engine/plato_template.py и
# выполняется здесь же, в пространстве имён движка: порядок объявлений
# и подмены core.<имя> остаются прежними.
_engine_part("plato_template")


# Маршрут /report/pdf и тизер — фоновая сборка, опрос по билету,
# build_teaser_pdf, участок и карта — вынесены в engine/report_teaser.py
# и выполняются здесь же, в пространстве имён движка: порядок объявлений
# и подмены core.<имя> остаются прежними.
_engine_part("report_teaser")


def _telegram_object_value(row: dict[str, Any]) -> str:
    """Строка раздела объектной вёрстки (`report.layout.sections`) для бота."""
    unit, value = row.get("unit"), row.get("value")
    if unit in ("rub", "mln"):
        return "—" if value is None else _telegram_money_mln(float(value) / 1e6)
    if unit == "sqm":
        return "—" if value is None else _telegram_number(value, 0) + " м²"
    if unit == "count":
        return "—" if value is None else _telegram_number(value, 0)
    if unit == "th":
        return "—" if value is None else _telegram_number(value, 1) + " тыс ₽/м²"
    if unit == "rub_unit":
        return "—" if value is None else _telegram_number(value, 0) + " ₽"
    if unit == "years":
        return "—" if value is None else _telegram_number(value, 1)
    if unit == "date":
        text = str(value or "")
        return ".".join(reversed(text[:7].split("-"))) if text else "—"
    return _telegram_tile(row)


def _telegram_object_sections(layout: dict[str, Any]) -> str:
    """Карточка проекта без жилья — разделы его вёрстки в порядке движка
    (`report_layout.kind` = объектная) с краткими строками каждого. Вердикт —
    тот, что собрал движок в разделе «Решение»; второго здесь нет."""
    if layout.get("kind") != REPORT_KIND_OBJECT:
        return ""
    sections = [s for s in layout.get("sections") or [] if s.get("brief") is not None]
    if not sections:
        return ""
    out = []
    for index, section in enumerate(sections, 1):
        lines = [f"<b>{index}. {html.escape(str(section.get('title') or ''))}</b>"]
        for row in section.get("brief") or []:
            label = html.escape(str(row.get("label") or ""))
            if section.get("key") == "decision" and row.get("label") == "Вывод":
                lines.append(f"• <b>{html.escape(str(row.get('value') or ''))}</b>")
            elif section.get("key") == "decision" and row.get("label") == "Основание":
                lines.append(f"• {html.escape(str(row.get('value') or ''))}")
            else:
                lines.append(f"• {label} — {_telegram_object_value(row)}")
        out.append("\n".join(lines))
    return "\n\n".join(out) + "\n\n"


def _telegram_tile(tile: dict[str, Any]) -> str:
    """Плитка нежилья (`report_layout`) строкой бота."""
    unit, value = tile.get("unit"), tile.get("value")
    if unit == "rub":
        return _telegram_money_mln(tile.get("value_mln"))
    if unit == "pct":
        return _telegram_number(float(value or 0) * 100, 1) + "%"
    if unit == "mult":
        return "—" if value is None else _telegram_number(value, 2) + "x"
    return html.escape(str(value or "—"))


@app.post("/telegram/result")
def telegram_result(req: TelegramResultRequest,
                    background: BackgroundTasks = None) -> dict[str, bool]:
    session = _telegram_verify_session(req.session)
    chat_id = int(session["chat_id"])
    if not _telegram_user_allowed(chat_id):
        raise HTTPException(status_code=403, detail="Доступ к боту закрыт")
    summary = req.summary or {}
    session_numbers = session.get("cad") or []
    raw_result_numbers = summary.get("cadastral_numbers") or []
    result_numbers = _parse_cadastral_numbers(raw_result_numbers) if raw_result_numbers else []
    numbers = session_numbers or result_numbers
    if session_numbers and result_numbers and session_numbers != result_numbers:
        raise HTTPException(status_code=403, detail="Кадастровые номера не совпадают с Telegram-сессией")

    irr = summary.get("irr_equity")
    irr_text = "N/A"
    if irr is not None:
        try:
            irr_text = _telegram_number(float(irr) * 100, 1) + "%"
        except Exception:
            pass
    margin_text = _telegram_number(float(summary.get("margin") or 0) * 100, 1) + "%"
    parking = float(summary.get("parking_spaces") or 0)
    project_name = str(summary.get("project_name") or "").strip()
    source_label = str(summary.get("source_label") or "ТЭП DevelopAid").strip()
    purchase_assessment = _purchase_feasibility(
        summary.get("purchase_price_mln"),
        summary.get("net_profit_mln"),
        summary.get("llcr"),
        max(
            float(summary.get("calculated_bridge_mln") or 0),
            float(summary.get("pf_uncovered_peak_mln") or 0),
        ),
        summary.get("ending_pf_mln"),
        summary.get("default_date"),
        summary.get("pf_shortfall_mln"),
        summary.get("pf_shortfall_month"),
        _layout_dscr(summary.get("layout")),
        _layout_no_debt_cover(summary.get("layout")),
    )
    # Продукт с ГНС и без продаваемой площади делает вердикт бессмысленным:
    # расходы полные, выручки нет, и «нецелесообразна» относится к дырке
    # в ТЭП, а не к проекту. Об этом надо сказать раньше вывода.
    broken_products = _tep_cost_without_revenue(
        (summary.get("report_payload") or {}).get("tep") or {}
    )
    if broken_products:
        purchase_assessment = {
            "status": "not_available",
            "title": "Вывод не сформирован — ТЭП неполный",
            "text": (
                "Нет продаваемой площади: " + ", ".join(broken_products)
                + ". Себестоимость считается от ГНС и учтена полностью, выручки по этим "
                "продуктам нет — расчёт показывает убыток по этой причине, а не из-за "
                "экономики проекта. Проверьте ТЭП и повторите расчёт."
            ),
        }
    if numbers:
        scope_line = f"Участки: <code>{html.escape(', '.join(numbers))}</code>\n"
    elif project_name:
        scope_line = f"Проект: <b>{html.escape(project_name)}</b>\n"
    else:
        scope_line = ""
    # Остаток непосредственно после раскрытия и долг на конец проекта — разные
    # риски. Первый может быть закрыт последующими продажами, поэтому он должен
    # быть виден даже тогда, когда ending_pf уже равен нулю.
    rve_pf_shortfall_mln = float(summary.get("rve_pf_shortfall_mln") or 0)
    if rve_pf_shortfall_mln > 0.5:
        rve_warning = (
            "⚠️ <b>Эскроу не погашает ПФ полностью в РВЭ</b>\n"
            f"• не покрыто при раскрытии — {_telegram_money_mln(rve_pf_shortfall_mln)}\n"
            # «Остаток должен быть погашен последующими продажами» — состояние,
            # которого в жизни не бывает: в дату раскрытия банк либо
            # переоформляет долг, либо фиксирует неисполнение (владелец,
            # 30.08.2026). На странице эту фразу сняли тогда же, а здесь она
            # осталась второй копией и продолжала читаться как правда.
            "• в эту дату банк либо переоформляет долг, либо фиксирует "
            "неисполнение; условий модель не знает и считает по допущению, что "
            "остаток обслуживается продажами следующих периодов.\n\n"
        )
    else:
        rve_warning = ""
    # Непогашенный ПФ — это дефолт по кредиту, а не строка детализации. Раньше
    # остаток считался, но никуда не выводился, и карточка выглядела безупречно
    # при долге в миллиарды. Порог 0,5 млн отсекает копеечные хвосты округления.
    ending_pf_mln = float(summary.get("ending_pf_mln") or 0)
    if ending_pf_mln > 0.5:
        debt_warning = (
            "⚠️ <b>Долг ПФ не погашается к концу проекта</b>\n"
            f"• остаток — {_telegram_money_mln(ending_pf_mln)}\n"
            "• выручки через эскроу не хватает на полное погашение проектного "
            "финансирования — для банка это риск дефолта.\n\n"
        )
    else:
        debt_warning = ""
    # Нехватка одобренного лимита — своя плашка, а не строка в общем списке:
    # у неё другой адресат. Дефолт говорит «долг не вернуть», а это — «денег
    # на стройку не дали», и дальше посчитано так, будто дали.
    pf_gap_mln = float(summary.get("pf_shortfall_mln") or 0)
    if pf_gap_mln > 0.5:
        _gap_month = str(summary.get("pf_shortfall_month") or "")
        _gap_since = (f" (впервые {_month_in_words(_gap_month)})"
                      if len(_gap_month) >= 7 else "")
        debt_warning = (
            "⚠️ <b>Финансирование не закрыто</b>\n"
            f"• одобренного лимита ПФ не хватает на "
            f"{_telegram_money_mln(pf_gap_mln)}{_gap_since}\n"
            "• дальше посчитано так, будто эти деньги проект получил: "
            "источника у них в модели нет, стоимость не учтена.\n\n"
        ) + debt_warning
    # Нежилой проект без ДДУ: квартир, соцнагрузки, БРИДЖа, ПФ и LLCR у него
    # нет — строки банка заменяет кредит объекта (`report.layout` движка).
    layout = summary.get("layout") if isinstance(summary.get("layout"), dict) else {}
    housing = bool(layout.get("housing", True))
    bank = bool(layout.get("project_finance", True))
    housing_lines = (
        f"• квартиры — {_telegram_number(summary.get('apartment_area_sqm'), 0)} м²\n"
        if housing else "")
    social_line = (
        f"• социальная нагрузка — {_telegram_money_mln(summary.get('social_compensation_mln'))}\n"
        if housing else "")
    if bank:
        bank_lines = (
            f"• LLCR — {_telegram_number(summary.get('llcr'), 2)}x\n"
            f"• расчётный БРИДЖ — {_telegram_money_mln(summary.get('calculated_bridge_mln'))}\n"
            f"• Пиковая (непокрытая эскроу) задолженность ПФ — {_telegram_money_mln(summary.get('pf_uncovered_peak_mln'))}\n\n")
    else:
        bank_lines = "".join(
            f"• {html.escape(str(tile.get('label') or '')).lower()} — {_telegram_tile(tile)}\n"
            for tile in layout.get("nonres_tiles") or []) + "\n"
    object_text = _telegram_object_sections(layout)
    text = (
        "<b>Расчёт DevelopAid готов</b>\n"
        + scope_line +
        f"Источник ТЭП: <b>{html.escape(source_label)}</b>\n\n"
        + object_text
        + "<i>Вывод предварительный и основан только на текущих вводных DevelopAid; цены, сроки и себестоимость можно изменить в модели.</i>"
    ) if object_text else (
        "<b>Расчёт DevelopAid готов</b>\n"
        + scope_line +
        f"Источник ТЭП: <b>{html.escape(source_label)}</b>\n\n"
        "<b>ТЭП</b>\n"
        f"• территория — {_telegram_number(summary.get('site_area_ha'), 4)} га\n"
        + housing_lines +
        f"• смена ВРИ — {_telegram_money_mln(summary.get('change_vri_mln'))}\n"
        + social_line +
        f"• подземный паркинг — {_telegram_number(parking, 0)} м/м\n\n"
        "<b>Предварительная экономика</b>\n"
        f"• цена покупки — {_telegram_money_mln(summary.get('purchase_price_mln'))}\n"
        + (f"• выкуп ЗУ/ОКС у третьих лиц — {_telegram_money_mln(summary.get('land_buyout_mln'))} "
           "(кадастровая стоимость, не цена сделки)\n"
           if float(summary.get("land_buyout_mln") or 0) > 0 else "") +
        f"• выручка — {_telegram_money_mln(summary.get('revenue_mln'))}\n"
        f"• расходы всего — {_telegram_money_mln(summary.get('total_expenses_mln'))}\n"
        f"• EBITDA — {_telegram_money_mln(summary.get('ebitda_mln'))}\n"
        f"• чистая прибыль — {_telegram_money_mln(summary.get('net_profit_mln'))}\n"
        f"• маржинальность — {margin_text}\n"
        + bank_lines
        + rve_warning + debt_warning +
        "<b>Оценка целесообразности покупки</b>\n"
        f"• <b>{html.escape(purchase_assessment['title'])}</b>\n"
        f"• {html.escape(purchase_assessment['text'])}\n\n"
        "<i>Вывод предварительный и основан только на текущих вводных DevelopAid; цены, сроки и себестоимость можно изменить в модели.</i>"
    )
    button = {
        "inline_keyboard": [[{
            "text": "Открыть и изменить расчёт",
            "web_app": {"url": _telegram_web_app_url(
                chat_id,
                numbers,
                session.get("manual_tep"),
                session.get("calc_overrides"),
                mode="edit",
            )},
        }]]
    }
    _telegram_send_message(chat_id, text, reply_markup=button)
    report_payload=summary.get("report_payload")
    if isinstance(report_payload,dict) and isinstance(report_payload.get("result"),dict):
        # PDF и Excel-модель собираются десятки секунд, и пока они собирались,
        # мини-приложение ждало ответа на этот запрос: в чат всё уже пришло, а
        # окно висело с надписью «Отправляю в чат…». Отвечаем сразу, вложения
        # уходят следом.
        if background is not None:
            background.add_task(_telegram_send_attachments, chat_id, report_payload,
                                project_name, list(numbers))
        else:
            _telegram_send_attachments(chat_id, report_payload, project_name, list(numbers))
    return {"ok": True}


# Что обязано совпасть у всех поверхностей. Слева путь в результате расчёта,
# справа — подпись для человека и допуск: доли сверяются абсолютной разницей,
# деньги — относительной.
_PARITY_FIELDS: list[tuple[str, str, str]] = [
    ("summary.llcr", "LLCR", "ratio"),
    ("summary.revenue", "выручка", "money"),
    ("summary.total_expenses", "расходы", "money"),
    ("summary.ebitda", "EBITDA", "money"),
    ("summary.net_profit", "чистая прибыль", "money"),
    ("summary.financing_cost", "проценты и комиссии", "money"),
    ("summary.social_payment", "социальная нагрузка", "money"),
    ("report.financing.actual_bridge", "пик БРИДЖа", "money"),
    ("report.financing.pf_peak", "выборка ПФ", "money"),
    ("inputs.land_rights_cost_mln", "ВРИ", "money"),
]


def _parity_value(result: dict[str, Any], path: str) -> float | None:
    node: Any = result
    for part in path.split("."):
        if not isinstance(node, dict):
            return None
        node = node.get(part)
    return float(node) if isinstance(node, (int, float)) else None


def _parity_mismatch(server: dict[str, Any], client: dict[str, Any]) -> list[str]:
    """Расхождения присланного расчёта с пересчитанным на сервере.

    Карточка и PDF строились по результату из мини-приложения, а Excel-модель
    пересчитывалась на сервере из тех же вводных. Пока обе стороны совпадают,
    разницы не видно; стоит браузеру остаться на прежней версии страницы — и
    PDF показывает одну экономику, детализация другую, причём обе выглядят
    достоверно. Поэтому расхождение ищется явно, а не предполагается.
    """
    problems: list[str] = []
    for path, label, kind in _PARITY_FIELDS:
        theirs = _parity_value(client, path)
        ours = _parity_value(server, path)
        if theirs is None or ours is None:
            continue
        if kind == "ratio":
            differs = abs(theirs - ours) > 0.005
        else:
            scale = max(abs(ours), abs(theirs), 1.0)
            differs = abs(theirs - ours) / scale > 0.001
        if differs:
            problems.append(f"{label}: {theirs:,.4g} против {ours:,.4g}")
    return problems


def _telegram_send_attachments(
    chat_id: int,
    report_payload: dict[str, Any],
    project_name: str,
    numbers: list[str],
) -> None:
    """PDF-отчёт и Excel-модель вдогонку к карточке."""
    # Чувствительность в отчёт с сайта попадает по кнопке на вкладке, но в боте
    # мини-приложение закрывается сразу после расчёта — до вкладки не добраться,
    # и раздел не появлялся никогда. Считаем сами: 0,25 с на одноочередной
    # проект и около секунды на трёхочередной, а вложения и так идут в фоне.
    # Один расчёт на обе поверхности. Прежде PDF строился по результату из
    # мини-приложения, а Excel-модель считалась здесь заново — два источника на
    # одни вводные, и разошедшийся браузер давал разную экономику в отчёте и в
    # детализации. Теперь считаем один раз и отдаём обеим.
    try:
        bundle = _run_authoritative_model(
            report_payload.get("inputs") or {},
            report_payload.get("tep") or {},
            report_payload.get("rates") or [],
            report_payload.get("phasing") or {},
        )
        server_result = bundle["consolidated"]
        problems = _parity_mismatch(
            {**server_result, "inputs": report_payload.get("inputs") or {}},
            {**(report_payload.get("result") or {}), "inputs": report_payload.get("inputs") or {}},
        )
        report_payload = {**report_payload, "result": server_result,
                          "phases": bundle.get("phases") or []}
        if problems:
            # Хостинг закрыт, и молча подменить числа нельзя: человек увидит
            # в PDF не то, что было на экране, и не поймёт почему.
            _TELEGRAM_RUNTIME["last_error"] = "Паритет: " + "; ".join(problems[:4])
            try:
                _telegram_send_message(chat_id, (
                    "<b>Расчёт в окне разошёлся с расчётом на сервере.</b>\n"
                    "В отчёт и модель взяты числа сервера: " + "; ".join(problems[:4])
                    + ".\nЧаще всего это старая страница в браузере — обновите её."
                ))
            except Exception:
                pass
    except Exception as exc:
        # Пересчёт не удался — отдаём то, что прислали: отчёт нужнее сверки.
        _TELEGRAM_RUNTIME["last_error"] = "Пересчёт для отчёта: " + _error_location(exc)

    if not report_payload.get("sensitivity"):
        try:
            report_payload = {**report_payload, "sensitivity": run_sensitivity(
                report_payload.get("inputs") or {},
                report_payload.get("tep") or {},
                report_payload.get("rates") or [],
                report_payload.get("phasing") or {},
            )}
        except Exception as exc:
            # Без анализа отчёт всё равно нужен: раздел просто не появится.
            _TELEGRAM_RUNTIME["last_error"] = "Чувствительность: " + _error_location(exc)
    try:
        pdf_bytes=_build_developaid_pdf(report_payload);scope=project_name or ("_".join(number.replace(":","-") for number in numbers[:2]) if numbers else "project");safe_scope=re.sub(r"[^0-9A-Za-zА-Яа-я_-]+","_",scope).strip("_")[:60] or "project"
        _telegram_send_document_bytes(chat_id,pdf_bytes,f"DevelopAid_Report_{safe_scope}.pdf",caption="<b>PDF-отчёт DevelopAid</b> · актуальный расчёт проекта")
    except Exception as exc:
        _TELEGRAM_RUNTIME["last_error"]="PDF: "+str(exc)
        try: _telegram_send_message(chat_id,"<i>Карточка рассчитана, но PDF временно не сформирован.</i>")
        except Exception: pass
    try:
        # Авторитетный расчёт мог не состояться (bundle не существует) —
        # книга тогда собирается без подсказок, но обязана собраться.
        workbook_hints = None
        try:
            workbook_hints = _v4_finance_hints(bundle) or None
        except Exception:
            workbook_hints = None
        model_bytes, model_filename, model_meta = build_project_workbook(
            report_payload.get("inputs") or {},
            report_payload.get("tep") or {},
            report_payload.get("rates") or [],
            report_payload.get("phasing") or {},
            project_name=str(report_payload.get("project_name") or project_name or ""),
            scenario=str(report_payload.get("scenario") or "base"),
            finance_hints=workbook_hints,
        )
        if model_meta.get("missing"):
            _TELEGRAM_RUNTIME["last_error"] = "Книга v4, без соответствия: " + "; ".join(
                str(item) for item in model_meta["missing"][:6])
        _telegram_send_document_bytes(
            chat_id,
            model_bytes,
            model_filename,
            caption=(
                "<b>Полная модель DevelopAid</b> · Excel считает формулами "
                "из текущих вводных"
                + (" · очереди на листе «Вводные»" if model_meta.get("phased") else "")
                + ". Откройте в Excel: предпросмотр формулы не считает."
            ),
            content_type=_XLSX_MEDIA_TYPE,
        )
    except Exception as exc:
        # Молчать нельзя: человек получал карточку и PDF, а модель просто не
        # приходила — и выглядело это как «отчёт есть, а модели нет».
        _TELEGRAM_RUNTIME["last_error"]="Модель: "+_error_location(exc)
        try:
            _telegram_send_message(
                chat_id,
                "<b>Excel-модель не собралась.</b>\n"
                f"<i>{html.escape(_error_location(exc)[:300])}</i>\n\n"
                "Карточка и PDF выше посчитаны и верны — не хватает только выгрузки. "
                "Соберите её заново командой /model.",
            )
        except Exception:
            pass


def _server_preset_meta(preset_id: str) -> dict[str, Any]:
    meta = SERVER_TEP_PRESETS.get(preset_id)
    if not meta:
        raise HTTPException(status_code=404, detail="Предустановка не найдена")
    path = PRESET_DIR / meta["filename"]
    if not path.exists():
        raise HTTPException(status_code=500, detail=f"Файл предустановки отсутствует на сервере: {meta['filename']}")
    return {**meta, "id": preset_id, "path": path}


def _is_admin_request(session: str = "", key: str = "") -> bool:
    """Владелец сервиса: свой chat_id в списке или ключ администратора."""
    secret = _env_str("DEVELOPAID_ADMIN_KEY", "").strip()
    if secret and key and hmac.compare_digest(str(key).encode("utf-8"),
                                              secret.encode("utf-8")):
        return True
    chat_id = _web_identity_chat_id(str(session or ""))
    return bool(chat_id) and chat_id in usage_admin_ids()


def _require_admin(session: str, key: str, what: str) -> None:
    """Готовые примеры и пресеты — витрина владельца, а не посторонних.

    В них лежат настоящие проекты с ценами, сроками и экономикой (решение
    владельца, 18.08.2026): показывать их каждому, кто открыл сайт, нельзя.
    Механизм честно выключен там, где владельца опознать нечем — иначе на
    машине без настроек примеры пропали бы у всех, включая самого владельца.
    """
    if not usage_admin_ids() and not _env_str("DEVELOPAID_ADMIN_KEY", "").strip():
        return
    if _is_admin_request(session, key):
        return
    raise HTTPException(status_code=403, detail=f"{what} — только для владельца сервиса.")


@app.get("/presets")
def list_server_presets(session: str = "", key: str = "") -> dict[str, Any]:
    _require_admin(session, key, "Готовые примеры")
    items = []
    for preset_id, meta in SERVER_TEP_PRESETS.items():
        path = PRESET_DIR / meta["filename"]
        items.append({
            "id": preset_id,
            "name": meta["name"],
            "filename": meta["filename"],
            "description": meta["description"],
            "available": path.exists(),
            "download_url": f"/presets/{preset_id}/download",
        })
    return {"presets": items}


@app.get("/presets/{preset_id}")
def get_server_preset(preset_id: str, session: str = "", key: str = "") -> dict[str, Any]:
    _require_admin(session, key, "Готовые примеры")
    meta = _server_preset_meta(preset_id)
    try:
        payload = parse_glavapu_xlsx(meta["path"].read_bytes(), meta["filename"])
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Не удалось разобрать серверную предустановку: {exc}") from exc
    payload["source"]["preset_id"] = preset_id
    payload["source"]["preset_name"] = meta["name"]
    payload["source"]["server_preset"] = True
    payload["warnings"] = [
        f"Загружена серверная предустановка «{meta['name']}».",
        *payload.get("warnings", []),
    ]
    return payload


@app.get("/presets/{preset_id}/download")
def download_server_preset(preset_id: str, session: str = "", key: str = ""):
    _require_admin(session, key, "Файл предустановки")
    meta = _server_preset_meta(preset_id)
    return FileResponse(
        path=str(meta["path"]),
        filename=meta["filename"],
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )



def d(value: str | date) -> date:
    return value if isinstance(value, date) else date.fromisoformat(str(value))


def add_months(value: str | date, months: int) -> date:
    value = d(value)
    m = value.month - 1 + int(months)
    year = value.year + m // 12
    month = m % 12 + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def months_between(start: date, end: date) -> int:
    return (end.year - start.year) * 12 + end.month - start.month


def month_range(start: date, end: date) -> list[date]:
    cur = date(start.year, start.month, 1)
    end = date(end.year, end.month, 1)
    out = []
    while cur <= end:
        out.append(cur)
        cur = add_months(cur, 1)
    return out


def social_cash_payment_date(x: dict[str, Any], permit: date) -> date:
    """Когда платится денежная компенсация за соцобъекты.

    Компенсация — условие получения РнС, и банк держит её в лимите БРИДЖа
    наравне с покупкой и проектированием. Значит она платится в период
    доступности БРИДЖа: после РнС линия уже рефинансирована в ПФ, и платить
    ею нечего. Решение владельца, 18.08.2026: «верно как банк».

    Прежде движок платил строго в заданную дату, а книга — за месяц до РнС
    своей формулой (`Вводные!B18`), в дату из вводных не заглядывая вовсе:
    поля не было в карте записи. Пока дата умолчания совпадала с «месяцем до
    РнС», обе стороны сходились случайно; стоило срокам проекта разъехаться с
    ней — и пик БРИДЖа расходился ровно на сумму компенсации (4712,5 млн в
    книге против 4132,8 у движка), а следом стоимость финансирования и прибыль.

    Дату из вводных функция уважает, пока та укладывается в бридж-период:
    компенсацию платят и раньше — при подписании договора о развитии, задолго
    до разрешения.
    """
    deadline = add_months(permit, -1)
    raw = str(x.get("social_comp_date") or "").strip()
    if not raw:
        return deadline
    try:
        wanted = d(raw)
    except ValueError:
        return deadline
    return min(wanted, deadline)


def generate_rate_curve(
    start_date: date,
    start_rate_pct: float,
    target_high_pct: float = 11.0,
    target_base_pct: float = 9.0,
    target_low_pct: float = 7.0,
    normalization_months: int = 24,
    total_months: int = 180,
    shape: float = 2.0,
) -> list[dict[str, Any]]:
    """Smooth mean-reversion-like curve that reaches the target exactly at the horizon.

    Internal names are kept for compatibility:
    high = conservative, base = base, low = optimistic.
    """
    horizon = max(1, int(normalization_months))
    shape = max(0.05, float(shape))
    denom = 1.0 - exp(-shape)
    targets = {
        "high": float(target_high_pct),
        "base": float(target_base_pct),
        "low": float(target_low_pct),
    }

    out: list[dict[str, Any]] = []
    for i in range(max(total_months, horizon) + 1):
        month = add_months(start_date, i)
        if i >= horizon:
            progress = 1.0
        else:
            progress = (1.0 - exp(-shape * i / horizon)) / denom

        row: dict[str, Any] = {"date": month.isoformat()}
        for key, target in targets.items():
            row[key] = float(start_rate_pct) + (target - float(start_rate_pct)) * progress
        out.append(row)
    return out


def fetch_current_cbr_key_rate() -> dict[str, Any]:
    """Fetch the latest announced key-rate decision from the Bank of Russia.

    The historical table can lag a newly announced decision until its effective
    date. The press-release feed is therefore authoritative for the web button;
    the historical table remains a secondary source.
    """
    fallback = {
        "rate": 14.0,
        "date": "2026-07-24",
        "live": False,
        "source": "Банк России — резервное значение на дату сборки",
    }

    try:
        feed_url = "https://www.cbr.ru/rss/RssPress"
        req = urllib.request.Request(
            feed_url,
            headers={
                "User-Agent": f"Mozilla/5.0 {USER_AGENT}",
                "Accept-Language": "ru-RU,ru;q=0.9",
            },
        )
        raw = urllib.request.urlopen(req, timeout=6).read()
        root = ET.fromstring(raw)
        decisions: list[tuple[date, float]] = []
        for item in root.findall(".//item"):
            title = (item.findtext("title") or "").replace("\xa0", " ").strip()
            normalized = title.lower()
            if "ключевую ставку" not in normalized or "принял решение" not in normalized:
                continue
            rate_match = re.search(
                r"(?:до|на\s+уровне)\s*([0-9]+(?:[.,][0-9]+)?)\s*%",
                title,
                flags=re.I,
            )
            date_matches = re.findall(r"(\d{2}\.\d{2}\.\d{4})", title)
            if not rate_match or not date_matches:
                continue
            decision_date = datetime.strptime(date_matches[-1], "%d.%m.%Y").date()
            decision_rate = float(rate_match.group(1).replace(",", "."))
            decisions.append((decision_date, decision_rate))
        if decisions:
            latest_date, latest_rate = max(decisions, key=lambda item: item[0])
            return {
                "rate": latest_rate,
                "date": latest_date.isoformat(),
                "live": True,
                "source": "Банк России — решение Совета директоров",
            }
    except Exception:
        pass

    try:
        today = date.today()
        start = today - timedelta(days=45)
        query = urllib.parse.urlencode({
            "UniDbQuery.Posted": "True",
            "UniDbQuery.From": start.strftime("%d.%m.%Y"),
            "UniDbQuery.To": today.strftime("%d.%m.%Y"),
        })
        url = "https://www.cbr.ru/hd_base/keyrate/?" + query
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": f"Mozilla/5.0 {USER_AGENT}",
                "Accept-Language": "ru-RU,ru;q=0.9",
            },
        )
        html = urllib.request.urlopen(req, timeout=6).read().decode("utf-8", errors="ignore")
        rows = re.findall(
            r"<td[^>]*>\s*(\d{2}\.\d{2}\.\d{4})\s*</td>\s*"
            r"<td[^>]*>\s*([0-9]+(?:,[0-9]+)?)\s*</td>",
            html,
            flags=re.I | re.S,
        )
        if not rows:
            return fallback

        parsed = []
        for dt_text, rate_text in rows:
            dt = date(int(dt_text[6:10]), int(dt_text[3:5]), int(dt_text[0:2]))
            rate = float(rate_text.replace(",", "."))
            parsed.append((dt, rate))
        latest_date, latest_rate = max(parsed, key=lambda item: item[0])
        return {
            "rate": latest_rate,
            "date": latest_date.isoformat(),
            "live": True,
            "source": "Банк России",
        }
    except Exception:
        return fallback


def rate_lookup(rates: list[dict[str, Any]], month: date, scenario: str) -> float:
    scenario = scenario if scenario in ("high", "base", "low") else "base"
    if not rates:
        return 0.0
    selected = float(rates[0].get(scenario, 0.0))
    for row in rates:
        if d(row["date"]) <= month:
            selected = float(row.get(scenario, selected))
        else:
            break
    return selected / 100.0


# Месяцы пониженного спроса — январь и май-август. Тот же список зашит в
# шаблоне ПЛАТО (лист ПОДБОР_КВ.М, строка 56), и расходиться с ним нельзя:
# иначе два расчёта по одним и тем же вводным дают разную выручку.
_SEASONAL_LOW_MONTHS = (1, 5, 6, 7, 8)


# График «сколько @ когда»: «30%@0; 40%@6; 30%@12» — доли по месяцам от точки
# отсчёта, «500@0; 300@12» — суммы в млн ₽. Разделитель пар не фиксируем, как
# у ступеней ставки: пара опознаётся формой «число[%] @ месяц», иначе запятая
# работает и разделителем, и десятичной точкой сразу.
#
# Пары ищутся не регуляркой `(\d+(?:[.,]\d+)?)\s*(%)?\s*@\s*(\d+)` через
# `findall`, а сканером `_scan_number_pairs` с тем же результатом: без якоря
# регулярка пробовала `\d+` с каждой цифры длинного числа, а `\s*(%)?\s*`
# делил пробелы надвое — строка из цифр или пробелов без «@» стоила квадрата.


def _scan_number_pairs(text: str, separators: str,
                       right_fraction: bool) -> list[tuple[str, str, str]]:
    """Все пары «число [%] разделитель число» слева направо, без перекрытий.

    Ровно то, что давал `re.findall` по
    ``(\d+(?:[.,]\d+)?)\s*(%)?\s*[разделитель]\s*(\d+(?:[.,]\d+)?)`` (у правого
    числа дробь — только при ``right_fraction``), но за линейное время:
    каждая позиция просматривается ограниченное число раз. Цифра и пробел — в
    смысле `re` для строк: `str.isdecimal` и `str.isspace`.
    Кортеж: (левое число, «%» или "", правое число).
    """
    n = len(text)

    def digits(i: int) -> int:
        while i < n and text[i].isdecimal():
            i += 1
        return i

    def spaces(i: int) -> int:
        while i < n and text[i].isspace():
            i += 1
        return i

    def tail(i: int) -> tuple[str, str, int] | None:
        # `\s*(%)?\s*<разделитель>\s*<число>` с позиции i; перебор с возвратом
        # тут ничего не находит: пробел не бывает ни «%», ни разделителем.
        i = spaces(i)
        percent = ""
        if i < n and text[i] == "%":
            percent, i = "%", spaces(i + 1)
        if i >= n or text[i] not in separators:
            return None
        start = spaces(i + 1)
        end = digits(start)
        if end == start:
            return None
        if (right_fraction and end + 1 < n and text[end] in ".,"
                and text[end + 1].isdecimal()):
            end = digits(end + 1)
        return percent, text[start:end], end

    found: list[tuple[str, str, str]] = []
    pos = 0
    while pos < n:
        if not text[pos].isdecimal():
            pos += 1
            continue
        whole = digits(pos)
        # Сперва — с дробью (жадный `?`), потом без неё, как у регулярки.
        attempt = None
        if whole + 1 < n and text[whole] in ".," and text[whole + 1].isdecimal():
            fraction = digits(whole + 1)
            got = tail(fraction)
            if got is not None:
                attempt = (text[pos:fraction], got)
        if attempt is None:
            got = tail(whole)
            if got is not None:
                attempt = (text[pos:whole], got)
        if attempt is None:
            # С любой цифры того же числа исход тот же: сразу за его конец.
            pos = whole
            continue
        left, (percent, right, end) = attempt
        found.append((left, percent, right))
        pos = end
    return found


def parse_month_schedule(value: Any) -> tuple[list[tuple[float, int]], bool, list[str]]:
    """Пары (величина, месяц) из строки; второй элемент — доли ли это (%).

    Смешивать доли и суммы в одном графике нельзя: такая строка возвращается
    пустой с предупреждением, а не угадывается.
    """
    found = _scan_number_pairs(str(value or ""), "@", right_fraction=False)
    items: list[tuple[float, int]] = []
    kinds: set[bool] = set()
    warnings: list[str] = []
    for raw_value, percent, raw_month in found:
        try:
            amount = float(raw_value.replace(",", "."))
            month = int(raw_month)
        except (TypeError, ValueError):
            continue
        if amount < 0 or month < 0:
            continue
        items.append((amount, month))
        kinds.add(bool(percent))
    if len(kinds) > 1:
        return [], False, ["график смешивает доли и суммы — не применён, платёж целиком в дату сделки"]
    if str(value or "").strip() and not items:
        warnings.append("график не распознан — ожидается вид «30%@0; 70%@6» или «500@0; 300@6»")
    items.sort(key=lambda item: item[1])
    return items, (True in kinds), warnings


def purchase_payment_plan(price: float, value: Any, start: date, end: date
                          ) -> tuple[list[tuple[date, float]], list[str]]:
    """Платежи за покупку по датам. Пусто — вся цена в дату сделки, как было.

    Доли, не сходящиеся к 100%, приводятся к 100% с предупреждением; суммы,
    не сходящиеся к цене, — остаток (или излишек) относится на дату сделки и
    называется. Платёж за горизонтом расчёта ложится в последний месяц и тоже
    называется: молча выпавший из горизонта платёж — это исчезнувшая цена.
    """
    items, is_percent, warnings = parse_month_schedule(value)
    if price <= 0:
        return [], warnings
    if not items:
        return [(start, price)], warnings
    if is_percent:
        total = sum(amount for amount, _ in items)
        if total <= 0:
            return [(start, price)], warnings + ["доли графика нулевые — платёж целиком в дату сделки"]
        if abs(total - 100.0) > 0.01:
            warnings.append(f"доли графика дают {total:g}% — приведены к 100%")
        payments = [(month, price * amount / total) for amount, month in items]
    else:
        payments = [(month, amount * 1_000_000) for amount, month in items]
        rest = price - sum(amount for _, amount in payments)
        if abs(rest) > 0.5:
            sign = "остаток" if rest > 0 else "излишек"
            warnings.append(f"суммы графика дают {sum(a for _, a in payments) / 1e6:,.1f} млн ₽ при цене "
                            f"{price / 1e6:,.1f}: {sign} {abs(rest) / 1e6:,.1f} млн ₽ отнесён на дату сделки"
                            .replace(",", " "))
            payments.insert(0, (0, rest))
    out: dict[date, float] = defaultdict(float)
    clamped = 0
    for month, amount in payments:
        when = add_months(start, int(month))
        if when > end:
            when = end
            clamped += 1
        out[when] += amount
    if clamped:
        warnings.append(f"платежей за горизонтом расчёта: {clamped} — отнесены на последний месяц")
    return sorted(out.items()), warnings


def schedule_weights(value: Any, start: date) -> tuple[dict[date, float] | None, list[str]]:
    """Профиль продаж объекта: доли по месяцам от старта продаж. None — профиля нет."""
    items, is_percent, warnings = parse_month_schedule(value)
    if not items:
        return None, warnings
    if not is_percent:
        return None, warnings + ["профиль продаж задаётся долями (%) — суммы не применены"]
    total = sum(amount for amount, _ in items)
    if total <= 0:
        return None, warnings + ["доли профиля продаж нулевые — профиль не применён"]
    if abs(total - 100.0) > 0.01:
        warnings.append(f"доли профиля продаж дают {total:g}% — приведены к 100%")
    weights: dict[date, float] = defaultdict(float)
    for amount, month in items:
        weights[add_months(start, month)] += amount / total
    return dict(weights), warnings


STAGE_READINESS_PCT = (25, 50, 75, 100)


def stage_ladder_factor(stages: list[Any], construction_start: date, construction_months: int,
                        ) -> tuple[Callable[[date], float] | None, list[dict[str, Any]], list[str]]:
    """Лестница цены по строительной готовности: «Рост цены — этап 1…4».

    Этап k наступает при готовности k×25% — на четверти, половине, трёх
    четвертях срока строительства и на вводе; с этого месяца цена выше на
    заданный процент, этапы перемножаются. Так были заведены поля шаблона
    ПЛАТО («этапные скачки цены по строительной готовности»), и по их образцу
    лестница сделана всем продуктам (владелец, 02.09.2026: «не сносить
    этапы, а сделать на их примере»). Ни один этап не задан — лестницы нет,
    цену ведёт ежемесячный рост.
    """
    growth: list[float] = []
    warnings: list[str] = []
    for index, value in enumerate(stages, 1):
        try:
            growth.append(float(str(value).replace(",", ".").replace("%", "").strip() or 0) / 100.0)
        except (TypeError, ValueError):
            growth.append(0.0)
            warnings.append(f"рост цены — этап {index}: «{value}» не число, этап пропущен")
    if not any(growth):
        return None, [], warnings
    months = max(1, int(construction_months or 0))
    rows: list[dict[str, Any]] = []
    for index, value in enumerate(growth, 1):
        reached = add_months(construction_start, -(-months * index // 4))
        rows.append({
            "stage": index,
            "readiness_pct": STAGE_READINESS_PCT[index - 1],
            "date": reached,
            "growth_pct": round(value * 100.0, 6),
        })

    def factor(month: date) -> float:
        result = 1.0
        for row in rows:
            if month >= row["date"]:
                result *= 1.0 + row["growth_pct"] / 100.0
        return result

    return factor, rows, warnings


def stage_ladder_text(rows: list[dict[str, Any]]) -> str:
    """«этап 1 · 25% · 07.2028: +5%; …» — только заданные этапы."""
    parts = []
    for row in rows or []:
        growth = float(row.get("growth_pct") or 0)
        if not growth:
            continue
        when = row.get("date")
        when_text = when.strftime("%m.%Y") if isinstance(when, date) else str(when or "")[:7]
        parts.append(f"этап {row['stage']} · {row['readiness_pct']}% · {when_text}: {growth:+g}%")
    return "; ".join(parts)


def sales_weights(
    start: date,
    rve: date,
    share_before: float,
    residual_months: int,
    seasonal: float = 0.0,
    pace: float = 0.0,
) -> dict[date, float]:
    """Доли продаж по месяцам: сезонность и смещение темпа к поздним месяцам.

    Повторяет распределение шаблона ПЛАТО. Сезонность действует на всём сроке
    продаж, смещение темпа — только до РВЭ, нарастая линейно от старта продаж.
    Веса нормируются отдельно до и после РВЭ, поэтому доля продаж до РВЭ
    остаётся ровно заданной.
    """
    pre_months = max(1, months_between(start, rve))
    residual_months = max(0, int(residual_months))
    share_before = max(0.0, min(1.0, share_before))

    def season(month: date) -> float:
        return 1.0 + seasonal if month.month in _SEASONAL_LOW_MONTHS else 1.0

    pre = [(add_months(start, i), season(add_months(start, i)) * (1.0 + pace * min(1.0, i / pre_months)))
           for i in range(pre_months)]
    post = [(add_months(rve, i), season(add_months(rve, i))) for i in range(residual_months)]

    weights: dict[date, float] = defaultdict(float)
    pre_total = sum(w for _, w in pre)
    if pre_total > 0:
        for month, w in pre:
            weights[month] += share_before * w / pre_total
    post_total = sum(w for _, w in post)
    if post_total > 0:
        for month, w in post:
            weights[month] += (1.0 - share_before) * w / post_total
    return dict(weights)


def sales_schedule(
    quantity: float,
    start_price: float,
    start: date,
    rve: date,
    share_before: float,
    residual_months: int,
    growth_before: float,
    growth_after: float,
    seasonal: float = 0.0,
    pace: float = 0.0,
    weights_override: dict[date, float] | None = None,
    price_factor: Callable[[date], float] | None = None,
) -> dict[date, float]:
    """Выручка по месяцам. Профиль продаж и лестница цены, если заданы,
    замещают распределение «доля до РВЭ + остаток» и ежемесячный рост:
    объект с одним покупателем продаётся не «85% равномерно до РВЭ», а
    «60% в сделку, 40% через год» (владелец, 02.09.2026)."""
    out: dict[date, float] = defaultdict(float)
    if quantity <= 0 or start_price <= 0:
        return dict(out)

    pre_months = max(1, months_between(start, rve))
    weights = (dict(weights_override) if weights_override is not None
               else sales_weights(start, rve, share_before, residual_months, seasonal, pace))
    price_at_rve = start_price * pow(1 + growth_before, pre_months)

    for month, weight in weights.items():
        if price_factor is not None:
            # Лестница ведёт цену до ввода; после РВЭ — ежемесячный рост от
            # достигнутой ступени, как и без лестницы.
            price = start_price * price_factor(month)
            if month >= rve:
                price *= pow(1 + growth_after, months_between(rve, month))
        elif month < rve:
            price = start_price * pow(1 + growth_before, months_between(start, month))
        else:
            price = price_at_rve * pow(1 + growth_after, months_between(rve, month))
        out[month] += quantity * weight * price

    return dict(out)


def quantity_schedule(
    quantity: float,
    start: date,
    rve: date,
    share_before: float,
    residual_months: int,
    seasonal: float = 0.0,
    pace: float = 0.0,
    weights_override: dict[date, float] | None = None,
) -> dict[date, float]:
    """Physical sales volume by month, using the same phasing as sales_schedule()."""
    out: dict[date, float] = defaultdict(float)
    if quantity <= 0:
        return dict(out)
    weights = (dict(weights_override) if weights_override is not None
               else sales_weights(start, rve, share_before, residual_months, seasonal, pace))
    for month, weight in weights.items():
        out[month] += quantity * weight
    return dict(out)


def spread_evenly(target: dict[date, float], amount: float, start: date, months: int) -> None:
    months = max(1, int(months))
    if not amount:
        return
    each = amount / months
    for i in range(months):
        target[add_months(start, i)] += each


# NPV и IRR — `developaid_finance_math` (одна реализация на движок и модули
# объектов); движок зовёт их прежними именами, импорт — в шапке файла.


# Доходность капитала при непогашенном долге (решение владельца 29.09.2026,
# ревизия книги, решение 2): если ПФ к концу проекта не погашен, IRR и NPV не
# числа, а «N/A — долг не погашен». Порог тот же, что у книги:
# `КОНСОЛИДАТОР!N8` = IF('CF'!B19>0.5 млн, "N/A (долг не погашен)", …), и тот
# же, по которому PDF зовёт прибыль бумажной. Решение принимает одна функция
# ниже; страница, PDF, тизер, Telegram и Платон читают её признак, а не
# сравнивают остаток долга сами. Отсутствие числа — не ноль.
EQUITY_RETURNS_UNREPAID_DEBT_MIN_RUB = 500_000.0
EQUITY_RETURNS_DEBT_UNREPAID = "debt_unrepaid"
EQUITY_RETURNS_NA_DEBT_LABEL = "N/A — долг не погашен"


def _apply_equity_returns_verdict(summary: dict[str, Any] | None) -> dict[str, Any] | None:
    """Снимает IRR и NPV, если долг ПФ к концу проекта не погашен.

    Пишет `summary["equity_returns"]` — единственный признак для всех
    поверхностей — и при дефолте заменяет `npv`/`irr_equity` на None.
    Повторный вызов на уже решённой сводке ничего не меняет.
    """
    if not isinstance(summary, dict) or "equity_returns" in summary:
        return summary
    ending = float(summary.get("ending_pf") or 0.0)
    if ending > EQUITY_RETURNS_UNREPAID_DEBT_MIN_RUB:
        summary["npv"] = None
        summary["npv_equity"] = None
        summary["irr_equity"] = None
        summary["equity_returns"] = {
            "status": EQUITY_RETURNS_DEBT_UNREPAID,
            "label": EQUITY_RETURNS_NA_DEBT_LABEL,
            "reason": (f"ПФ не погашен к концу проекта: остаток "
                       f"{ending / 1_000_000:,.1f} млн ₽".replace(",", " ")),
            "ending_pf": ending,
        }
    else:
        summary["equity_returns"] = {"status": "ok", "label": None, "reason": "",
                                     "ending_pf": ending}
    return summary


def equity_returns_na_label(summary: dict[str, Any] | None) -> str | None:
    """Подпись вместо IRR/NPV, если движок их снял; None — числа есть."""
    verdict = (summary or {}).get("equity_returns") or {}
    if verdict.get("status") == EQUITY_RETURNS_DEBT_UNREPAID:
        return str(verdict.get("label") or EQUITY_RETURNS_NA_DEBT_LABEL)
    return None


def _apply_equity_returns_to_result(result: dict[str, Any]) -> dict[str, Any]:
    if isinstance(result, dict):
        _apply_equity_returns_verdict(result.get("summary"))
    return result


def _iso(value: date) -> str:
    return value.isoformat()


# Мощности соцобъектов зовутся одинаково во вводных, в потребности и в ТЭП —
# три имени объявлены один раз, иначе разница «требуется минус построено»
# считалась бы по разным ключам в разных местах.
_SOCIAL_UNITS = ("kindergarten_places", "school_places", "clinic_capacity")


def social_required_program(
    x: dict, t: dict | None = None, built: dict[str, float] | None = None
) -> dict[str, Any]:
    """Расчётная потребность города — база платежа, а не обязательство строить.

    В Москве социалка исполняется деньгами, и компенсация посчитана ОТ
    потребности: строки 30–32 выгрузки ГлавАПУ. В проект доезжали только
    «фактические» места (строки 18/22/26) — то, что застройщик строит сам, а у
    компенсационного проекта это нули, — и `syncTep` доглушал строки ДОО, СОШ и
    поликлиники при режиме «Денежная компенсация». Выходило, что платим за 250
    мест, а числа 250 в проекте нет нигде: ни во вводных, ни в ТЭП, ни в отчёте
    («в Москве всё падает в компенсацию, но места никуда справочно не
    заносятся», владелец, 02.09.2026).

    Метры при этом строить нельзя: объект возводит город, и попади его площадь
    в ТЭП, она вошла бы в ГНС проекта — в знаменатель всех удельных
    показателей. Поэтому здесь только мощности и только справочно.

    Источник называется вслух: расчёт города сильнее нашего норматива, а
    «не от чего считать» — не то же самое, что «потребности нет».

    При режиме «Строительство и компенсация» тем же числом отвечается вопрос,
    на который ответить было нечем: что именно закрывает денежная часть.
    Показывается РАЗНИЦА между требованием и построенным — но не утверждается,
    что компенсация посчитана городом именно от неё: сумма приходит из
    выгрузки, и чем она набрана, документ не раскрывает.
    """
    def with_gap(answer: dict[str, Any]) -> dict[str, Any]:
        if not answer.get("available") or built is None:
            return answer
        answer["built"] = {key: round(float(built.get(key) or 0.0), 1) for key in _SOCIAL_UNITS}
        answer["gap"] = {
            key: round(max(0.0, float(answer.get(key) or 0.0) - float(built.get(key) or 0.0)), 1)
            for key in _SOCIAL_UNITS
        }
        answer["fully_built"] = not any(answer["gap"].values())
        return answer

    imported = (x.get("_glavapu_import") or {}).get("normalized", {}) or {}
    from_city = {
        "kindergarten_places": n(imported, "required_kindergarten_places"),
        "school_places": n(imported, "required_school_places"),
        "clinic_capacity": n(imported, "required_clinic_capacity"),
    }
    district = str(imported.get("district") or "").strip()
    if any(value > 0 for value in from_city.values()):
        return with_gap({
            "available": True,
            "source": "glavapu",
            "basis": "расчёт ГлавАПУ по выгрузке — по этим мощностям посчитана компенсация",
            "district": district,
            **{key: round(value, 1) for key, value in from_city.items()},
        })

    apartments = n((t or {}).get("apartments") or {}, "saleable")
    if apartments <= 0:
        return {
            "available": False,
            "source": "unknown",
            "basis": "площадь квартир в ТЭП не задана — считать потребность не от чего",
        }
    if str(x.get("vri_region") or "msk") == "mo":
        # В области норматив свой, и он у движка уже есть. Вторая формула здесь
        # дала бы на один проект два норматива, оба на вид верных.
        program = mo_social_program(apartments)
        return with_gap({
            "available": True,
            "source": "mo_norm",
            "basis": "норматив РНГП Московской области по площади квартир",
            "district": district,
            "population": program["population"],
            "kindergarten_places": program["kindergarten"]["places"],
            "school_places": program["school"]["places"],
            "clinic_capacity": program["clinic"]["capacity"],
        })
    zone_two = district_zone_two(district)
    population = apartments / 33.0
    return with_gap({
        "available": True,
        "source": "norm",
        "basis": (
            "норматив Москвы, "
            + ("вторая" if zone_two else "первая")
            + " зона нормирования"
            + (f", район «{district}»" if district
               else "; район не назван — принята первая зона")
        ),
        "district": district,
        "zone_two": zone_two,
        "population": int(math.ceil(population)),
        "kindergarten_places": math.ceil(
            moscow_social_places("kindergarten", population, zone_two=zone_two)),
        "school_places": math.ceil(
            moscow_social_places("school", population, zone_two=zone_two)),
        "clinic_capacity": math.ceil(
            moscow_social_places("clinic", population, zone_two=zone_two)),
    })


def effective_social_program(x: dict) -> dict[str, float]:
    imported = (x.get("_glavapu_import") or {}).get("normalized", {})

    def choose(input_key: str, required_key: str) -> float:
        explicit = n(x, input_key)
        required = n(imported, required_key)
        if (str(x.get("social_mode", "Строительство")) in ("Строительство", SOCIAL_MODE_BOTH)
                and explicit <= 0 and required > 0):
            return required
        return explicit

    return {
        "kindergarten_places": choose("kindergarten_places", "required_kindergarten_places"),
        "school_places": choose("school_places", "required_school_places"),
        "clinic_capacity": choose("clinic_capacity", "required_clinic_capacity"),
    }


# ---------------------------------------------------------------------------
# Плата за изменение ВРИ: обязательство, график платежей и источники оплаты.
#
# Плата за смену ВРИ — не разовый расход на дату РнС. Она возникает по
# соглашению, может гаситься рассрочкой с процентами на остаток и делится
# между БРИДЖем, ПФ и собственным капиталом. От этого зависят лимит БРИДЖа,
# потребность в ПФ, проценты и, следом, NPV, IRR и LLCR.
# ---------------------------------------------------------------------------

VRI_DEFAULTS: dict[str, Any] = {
    "vri_required": True,
    "vri_region": "msk",                  # msk | mo
    "land_right": "ownership",            # ownership | lease
    "vri_obligation_date": "",            # пусто — дата РнС
    "vri_payment_mode": "lump",           # lump | installment
    "vri_installment_years": 3,           # Москва: 1, 3 или 6
    "vri_periodicity_months": 3,          # Москва: квартальные платежи
    "vri_schedule_mode": "auto",          # auto | manual
    "vri_interest_enabled": "",           # пусто — по региону: Москва да, МО нет
    "vri_interest_spread_pp": 3.0,        # ключевая + 3 п.п.
    "vri_early_repay_after_pf": False,
    "vri_pf_open_date": "",               # пусто — дата РнС
    "vri_in_bank_budget": True,
    "vri_financing_mode": "auto",         # auto — как весь проект; shares — явные доли
    "vri_share_bridge_pct": 0.0,
    "vri_share_pf_pct": 0.0,
    "vri_share_equity_pct": 0.0,
    "vri_security_cost_mln": 0.0,         # расходы на обеспечение обязательства
    "vri_obligation_date_mode": "before_rns_1m",  # at_rns | before_rns_1m | before_rns_3m | after_purchase | manual
    "vri_months_after_purchase": 12,
    "vri_initial_pct": 0.0,               # доля первого платежа при рассрочке
    "vri_relief_mode": "none",            # none | percent | amount
    "vri_relief_pct": 0.0,
    "vri_relief_mln": 0.0,
    # Зачёт переданных муниципалитету площадей (практика Подмосковья).
    "vri_transfer_offset_mln": 0.0,
}

# Москва: рассрочка по постановлению даётся на 1, 3 или 6 лет.
_VRI_MSK_TERMS = (1, 3, 6)

# Московская область: рассрочка зависит от суммы обязательства. Официальные
# диапазоны в модель не зашиты — их задаёт пользователь списком
# {"limit_mln": …, "years": …, "periodicity_months": …}; последняя строка без
# limit_mln работает как «свыше». Пока список пуст, применяется срок из ввода
# и в отчёт уходит предупреждение.
_VRI_MO_RANGES_KEY = "vri_mo_ranges"


def vri_benefits_for(x: dict[str, Any], t: dict[str, Any]) -> dict[str, Any]:
    """Льготы по плате за ВРИ (МПТ, передача квартир) и рабочие места проекта.

    Считаются всегда, когда в проекте есть нежилые объекты или передача
    квартир, — как предложение рядом с платой; экономику не меняют, пока
    человек не внесёт сумму в льготу (`vri_relief_mode = amount`).
    Отказ расчёта виден с местом, а не пустым блоком.
    """
    objects = [{"key": obj.key, "product": obj.product,
                "label": obj.tep_label or obj.label,
                "enabled": (bool(x.get(obj.enabled_key)) if obj.enabled_key in (x or {})
                            else None),
                "purpose": (x or {}).get(obj.purpose_key) if obj.purpose_key else None}
               for obj in STANDALONE_OBJECTS]
    try:
        return vri_benefits.compute(x or {}, t or {}, objects)
    except Exception as exc:  # noqa: BLE001 — отказ доходит до страницы с местом
        return {"applicable": False, "rows": [],
                "reason": "расчёт льгот не выполнен: " + _error_location(exc)}


def vri_relief(x: dict[str, Any], gross: float) -> tuple[float, float]:
    """Льгота по плате за ВРИ: доля или фиксированная сумма. Возвращает (льгота, к оплате).

    Обязательство может быть уменьшено решением города — например, при
    строительстве социальных объектов за свой счёт. Льгота срезается с валовой
    суммы до построения графика: рассрочка, проценты и резерв считаются уже от
    того, что реально предстоит заплатить.
    """
    gross = max(0.0, float(gross or 0.0))
    mode = str(x.get("vri_relief_mode") or "none").strip().lower()
    if mode == "percent":
        relief = gross * max(0.0, min(100.0, n(x, "vri_relief_pct", 0.0))) / 100.0
    elif mode == "amount":
        relief = max(0.0, n(x, "vri_relief_mln", 0.0)) * 1_000_000
    else:
        relief = 0.0
    # Передача площадей муниципалитету в зачёт платы — практика Подмосковья:
    # застройщик отдаёт метры и на их стоимость уменьшает обязательство. Сумма
    # зачёта берётся из соглашения, а не считается нами по цене продажи:
    # муниципалитет засчитывает по своей оценке, и она другая. Зачёт идёт
    # поверх льготы: это разные основания, и складывать их правильно.
    relief += max(0.0, n(x, "vri_transfer_offset_mln", 0.0)) * 1_000_000
    relief = min(gross, relief)
    return relief, gross - relief


def _vri_flag(value: Any, default: bool) -> bool:
    if value is None or value == "":
        return default
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "да", "yes", "on"}
    return bool(value)


def _vri_date(value: Any, fallback: date) -> date:
    text = str(value or "").strip()
    if not text:
        return fallback
    try:
        return d(text)
    except Exception:
        return fallback


def _vri_region(value: Any) -> str:
    text = str(value or "").strip().lower()
    if text in {"mo", "50", "мо", "московская область", "подмосковье", "region", "мособласть"}:
        return "mo"
    return "msk"


def _vri_mo_range(x: dict[str, Any], amount: float) -> dict[str, Any] | None:
    """Срок и периодичность рассрочки МО по диапазону суммы обязательства."""
    rows = x.get(_VRI_MO_RANGES_KEY) or []
    parsed: list[tuple[float, dict[str, Any]]] = []
    for item in rows:
        if not isinstance(item, dict):
            continue
        raw_limit = item.get("limit_mln")
        limit = float("inf") if raw_limit in (None, "") else float(raw_limit) * 1_000_000
        parsed.append((limit, item))
    if not parsed:
        return None
    for limit, item in sorted(parsed, key=lambda pair: pair[0]):
        if amount <= limit:
            return {
                "years": max(1, int(float(item.get("years") or 1))),
                "periodicity": max(1, int(float(item.get("periodicity_months") or 3))),
                "limit_mln": None if limit == float("inf") else limit / 1_000_000,
            }
    return None


_VRI_DATE_LABELS = {
    "at_rns": "в дату РнС",
    "before_rns_1m": "за месяц до РнС",
    "before_rns_3m": "за три месяца до РнС",
    "after_purchase": "через N месяцев после покупки",
    "manual": "введена вручную",
}


def vri_obligation_date(x: dict[str, Any], permit: date) -> tuple[date, str, bool]:
    """Дата возникновения обязательства по ВРИ: (дата, пояснение, оценочная ли).

    Соглашение о смене ВРИ подписывается до получения РнС, поэтому дата не
    обязана совпадать с РнС. Платёж до открытия ПФ несёт БРИДЖ, а не ПФ, —
    сдвиг даты меняет пик БРИДЖа, и режим лучше выбирать осознанно.
    """
    mode = str(x.get("vri_obligation_date_mode") or "before_rns_1m").strip().lower()
    raw = str(x.get("vri_obligation_date") or "").strip()
    if raw:
        try:
            return d(raw), "Дата известна — введена вручную", False
        except Exception:
            pass
    if mode == "manual":
        return permit, "Выбран ручной режим, но дата не задана — принята дата РнС", True
    if mode == "before_rns_1m":
        return add_months(permit, -1), "Оценочная дата — за месяц до РнС", True
    if mode == "before_rns_3m":
        return add_months(permit, -3), "Оценочная дата — за три месяца до РнС", True
    if mode == "after_purchase":
        months = max(0, int(n(x, "vri_months_after_purchase", 12)))
        start = d(x.get("project_start", "2027-01-01"))
        return add_months(start, months), f"Оценочная дата — через {months} мес. после покупки", True
    if mode == "at_rns":
        return permit, "Оценочная дата — в дату РнС", True
    return add_months(permit, -1), "Оценочная дата — за месяц до РнС", True


def _vri_settings(x: dict[str, Any], permit: date, amount: float = 0.0) -> dict[str, Any]:
    region = _vri_region(x.get("vri_region"))
    obligation_date, obligation_basis, obligation_estimated = vri_obligation_date(x, permit)
    interest_default = region == "msk"
    years = int(n(x, "vri_installment_years", VRI_DEFAULTS["vri_installment_years"]) or 3)
    periodicity = int(n(x, "vri_periodicity_months", VRI_DEFAULTS["vri_periodicity_months"]) or 3)
    mo_range = None
    if region == "msk":
        if years not in _VRI_MSK_TERMS:
            years = min(_VRI_MSK_TERMS, key=lambda item: abs(item - years))
        periodicity = 3
    else:
        mo_range = _vri_mo_range(x, amount)
        if mo_range:
            years = mo_range["years"]
            periodicity = mo_range["periodicity"]
    return {
        "required": _vri_flag(x.get("vri_required"), VRI_DEFAULTS["vri_required"]),
        "region": region,
        "land_right": str(x.get("land_right") or VRI_DEFAULTS["land_right"]),
        "obligation_date": obligation_date,
        "obligation_basis": obligation_basis,
        "obligation_estimated": obligation_estimated,
        "initial_pct": max(0.0, min(100.0, n(x, "vri_initial_pct", 0.0))),
        "payment_mode": str(x.get("vri_payment_mode") or VRI_DEFAULTS["vri_payment_mode"]).strip().lower(),
        "years": max(1, years),
        "periodicity": max(1, periodicity),
        "mo_range": mo_range,
        "schedule_mode": str(x.get("vri_schedule_mode") or VRI_DEFAULTS["vri_schedule_mode"]).strip().lower(),
        "interest_enabled": _vri_flag(x.get("vri_interest_enabled"), interest_default),
        "spread": n(x, "vri_interest_spread_pp", VRI_DEFAULTS["vri_interest_spread_pp"]) / 100.0,
        "early_repay": _vri_flag(x.get("vri_early_repay_after_pf"), VRI_DEFAULTS["vri_early_repay_after_pf"]),
        "pf_open": _vri_date(x.get("vri_pf_open_date"), permit),
        "in_bank_budget": _vri_flag(x.get("vri_in_bank_budget"), VRI_DEFAULTS["vri_in_bank_budget"]),
        "financing_mode": str(x.get("vri_financing_mode") or VRI_DEFAULTS["vri_financing_mode"]).strip().lower(),
        "share_bridge": n(x, "vri_share_bridge_pct", 0.0) / 100.0,
        "share_pf": n(x, "vri_share_pf_pct", 0.0) / 100.0,
        "share_equity": n(x, "vri_share_equity_pct", 0.0) / 100.0,
        "security_cost": n(x, "vri_security_cost_mln", 0.0) * 1_000_000,
    }


def _vri_payment_dates(settings: dict[str, Any], *, after_initial: bool = False) -> list[date]:
    """Даты платежей по обязательству ВРИ.

    Рассрочка начинается в дату обязательства, а не через период после неё.
    Прежде первый платёж отодвигался на целый период, и при дате обязательства
    за месяц до РнС — умолчание — вся рассрочка оказывалась уже за РнС: до
    получения разрешения не платилось ничего, хотя соглашение подписано раньше.
    Исключение одно: если задан первый взнос, он и есть платёж в дату
    обязательства, а регулярные платежи идут следом.
    """
    start = settings["obligation_date"]
    if settings["payment_mode"] != "installment":
        return [start]
    periodicity = settings["periodicity"]
    count = max(1, int(round(settings["years"] * 12 / periodicity)))
    offset = 1 if after_initial else 0
    return [add_months(start, periodicity * (index + offset)) for index in range(count)]


def _vri_manual_rows(x: dict[str, Any]) -> list[tuple[date, float]]:
    rows: list[tuple[date, float]] = []
    for item in x.get("vri_manual_schedule") or []:
        if not isinstance(item, dict):
            continue
        try:
            when = d(str(item.get("date")))
        except Exception:
            continue
        amount = float(item.get("principal_mln") or item.get("amount_mln") or 0.0) * 1_000_000
        if amount:
            rows.append((when, amount))
    return sorted(rows, key=lambda pair: pair[0])


def _vri_split_payment(
    amount: float, before_pf: bool, settings: dict[str, Any]
) -> tuple[float, float, float]:
    """Разносит платёж на БРИДЖ, ПФ и собственный капитал."""
    def fallback() -> tuple[float, float, float]:
        # Если банк ВРИ не финансирует, платёж не может лечь ни на ПФ, ни на
        # БРИДЖ: бридж — тоже банковские деньги. Всё остаётся на капитале.
        if not settings["in_bank_budget"]:
            return 0.0, 0.0, amount
        if before_pf:
            return amount, 0.0, 0.0
        return 0.0, amount, 0.0

    if settings["financing_mode"] != "shares":
        return fallback()
    total = settings["share_bridge"] + settings["share_pf"] + settings["share_equity"]
    if total <= 0:
        return fallback()
    bridge = amount * settings["share_bridge"] / total
    pf = amount * settings["share_pf"] / total
    equity = amount * settings["share_equity"] / total
    if pf and (before_pf or not settings["in_bank_budget"]):
        # ПФ ещё не открыт (или банк ВРИ не финансирует): его долю принимает
        # БРИДЖ до РнС и собственный капитал — когда банковского бюджета нет.
        if before_pf and settings["in_bank_budget"]:
            bridge += pf
        else:
            equity += pf
        pf = 0.0
    if not settings["in_bank_budget"] and bridge:
        equity += bridge
        bridge = 0.0
    return bridge, pf, equity


def build_vri_schedule(
    x: dict[str, Any],
    amount_rub: float,
    permit: date,
    rates: list[dict[str, Any]] | None = None,
    scenario: str = "base",
) -> dict[str, Any]:
    """График платежей по обязательству ВРИ с процентами и источниками оплаты."""
    amount = max(0.0, float(amount_rub or 0.0))
    settings = _vri_settings(x, permit, amount)
    warnings: list[str] = []

    def public(extra: dict[str, Any]) -> dict[str, Any]:
        return {
            **settings,
            "obligation_date": settings["obligation_date"].isoformat(),
            "pf_open": settings["pf_open"].isoformat(),
            **extra,
        }

    if amount > 0 and not settings["required"]:
        # Плата задана, а признак снят — противоречие, и разрешать его в пользу
        # «не платим» нельзя: сумма всё равно сидит в расходах, а графика нет,
        # то есть расход есть, а денег на него никто не занимает. Наружу это
        # выходило расхождением объёма долга с книгой. Снятый признак при
        # ненулевой плате чаще всего означает не «ВРИ не нужна», а поле,
        # которого не было в сохранённом проекте: страница рисует чекбокс по
        # `!!inputs[id]` и возвращает явный false, затирая умолчание.
        settings["required"] = True
        warnings.append(
            "Признак «Требуется изменение ВРИ» снят, но плата задана — "
            "платежи разнесены по дате обязательства."
        )

    if (
        amount > 0
        and not settings["in_bank_budget"]
        and settings["financing_mode"] != "shares"
        and settings["share_equity"] <= 0
    ):
        # Тот же случай, что и с признаком выше: снятый флаг банковского бюджета
        # означает «плату вносим своими деньгами», и долг падает на всю сумму
        # ВРИ. На проекте 77:09:0004014:13 это давало LLCR 1,16x вместо 1,07x —
        # разница в целую инвестиционную оценку, а в отчёте не видно ничего.
        # Осознанный отказ от банковского финансирования выражается долями:
        # заданный собственный капитал или режим «shares» здесь не трогаются.
        settings["in_bank_budget"] = True
        warnings.append(
            "Признак «ВРИ включена в банковский бюджет» снят, а доли оплаты не заданы — "
            "плата отнесена на банковское финансирование. Если платите своими деньгами, "
            "укажите долю собственного капитала."
        )

    if not settings["required"] or amount <= 0:
        return {
            "enabled": False,
            "region": settings["region"],
            "payment_mode": settings["payment_mode"],
            "rows": [],
            "totals": {
                "amount": 0.0, "principal": 0.0, "interest": 0.0, "security_cost": 0.0,
                "before_pf": 0.0, "after_pf": 0.0, "bridge": 0.0, "pf": 0.0,
                "equity": 0.0, "cash": 0.0,
            },
            "settings": public({}),
            "warnings": warnings,
        }

    manual = _vri_manual_rows(x) if settings["schedule_mode"] == "manual" else []
    if settings["schedule_mode"] == "manual" and not manual:
        warnings.append("Выбран ручной график ВРИ, но платежи не заданы — применён автоматический график.")
    if manual:
        planned = manual
        manual_total = sum(value for _, value in planned)
        if abs(manual_total - amount) > 1.0:
            warnings.append(
                f"Ручной график ВРИ на {manual_total / 1_000_000:.1f} млн ₽ не совпадает "
                f"с суммой обязательства {amount / 1_000_000:.1f} млн ₽."
            )
    else:
        initial = amount * settings["initial_pct"] / 100.0
        has_initial = initial > 0 and settings["payment_mode"] == "installment"
        dates = _vri_payment_dates(settings, after_initial=has_initial)
        if has_initial:
            # Первый взнос платится в дату обязательства, остаток дробится
            # на регулярные платежи графика.
            share = (amount - initial) / len(dates)
            planned = [(settings["obligation_date"], initial)]
            planned += [(when, share) for when in dates]
        else:
            share = amount / len(dates)
            planned = [(when, share) for when in dates]

    if settings["payment_mode"] == "installment" and settings["region"] == "mo":
        if settings["interest_enabled"]:
            warnings.append(
                "Для Московской области проценты по рассрочке начисляются только если это "
                "прямо предусмотрено соглашением."
            )
        if settings["schedule_mode"] != "manual" and not settings["mo_range"]:
            warnings.append(
                "Диапазоны рассрочки Московской области не заданы — срок и периодичность "
                "взяты из ввода."
            )

    rows: list[dict[str, Any]] = []
    balance = amount
    accrued = 0.0
    cursor = settings["obligation_date"]
    early_done = False
    for index, (when, principal) in enumerate(planned, start=1):
        # Проценты на остаток по ключевой ставке плюс спред, помесячно до даты платежа.
        if settings["interest_enabled"] and balance > 0:
            month = cursor
            while month < when:
                if rates:
                    key_rate = rate_lookup(rates, month, scenario)
                else:
                    key_rate = n(x, "rate_start_pct", 0.0) / 100.0
                accrued += balance * (key_rate + settings["spread"]) / 12.0
                month = add_months(month, 1)
        cursor = when
        pay_principal = min(principal, balance)
        if (
            settings["early_repay"]
            and not early_done
            and settings["payment_mode"] == "installment"
            and when >= settings["pf_open"]
        ):
            pay_principal = balance
            early_done = True
        interest = accrued
        accrued = 0.0
        balance = max(0.0, balance - pay_principal)
        before_pf = when < settings["pf_open"]
        bridge, pf, equity = _vri_split_payment(pay_principal + interest, before_pf, settings)
        rows.append({
            "date": when.isoformat(),
            "period": index,
            "principal": round(pay_principal, 2),
            "interest": round(interest, 2),
            "total": round(pay_principal + interest, 2),
            "balance_after": round(balance, 2),
            "before_pf": before_pf,
            "bridge": round(bridge, 2),
            "pf": round(pf, 2),
            "equity": round(equity, 2),
        })
        if early_done:
            break
    if balance > 1.0:
        warnings.append(
            f"После последнего платежа остаётся непогашенный остаток {balance / 1_000_000:.1f} млн ₽."
        )

    security = settings["security_cost"]
    if security:
        before_pf = settings["obligation_date"] < settings["pf_open"]
        bridge, pf, equity = _vri_split_payment(security, before_pf, settings)
        rows.insert(0, {
            "date": settings["obligation_date"].isoformat(), "period": 0,
            "principal": 0.0, "interest": 0.0, "total": round(security, 2),
            "balance_after": round(amount, 2), "before_pf": before_pf,
            "bridge": round(bridge, 2), "pf": round(pf, 2), "equity": round(equity, 2),
            "security": True,
        })

    totals = {
        "amount": round(amount, 2),
        "principal": round(sum(row["principal"] for row in rows), 2),
        "interest": round(sum(row["interest"] for row in rows), 2),
        "security_cost": round(security, 2),
        "before_pf": round(sum(row["total"] for row in rows if row["before_pf"]), 2),
        "after_pf": round(sum(row["total"] for row in rows if not row["before_pf"]), 2),
        "bridge": round(sum(row["bridge"] for row in rows), 2),
        "pf": round(sum(row["pf"] for row in rows), 2),
        "equity": round(sum(row["equity"] for row in rows), 2),
        "cash": round(sum(row["total"] for row in rows), 2),
    }
    return {
        "enabled": True,
        "region": settings["region"],
        "payment_mode": settings["payment_mode"],
        "rows": rows,
        "totals": totals,
        "settings": public({}),
        "warnings": warnings,
    }


def build_operating_model(x: dict, t: dict, rates: list[dict[str, Any]] | None = None) -> dict:
    project_start = d(x.get("project_start", "2027-01-01"))
    # Минимум применяется здесь, а не только при разносе расходов: РнС в день
    # старта — это и есть тот нулевой период, на котором книга и движок
    # расходятся целиком.
    permit = add_months(project_start, max(IRD_MONTHS_MIN, int(n(x, "ird_months", 18))))
    sales_start = add_months(permit, int(n(x, "sales_lag_months", 0)))
    rve = add_months(permit, int(n(x, "construction_months", 24)))
    residual = int(n(x, "residual_sales_months", 6))
    end = add_months(rve, max(residual + 3, 12))

    apartment = t.get("apartments", {})
    commercial = t.get("ground_commercial", {})
    underground = t.get("underground_parking", {})
    storage = t.get("storage", {})

    core_above_gns = n(apartment, "gns") + n(commercial, "gns")
    # Своего гаража у встроенной коммерции нет: её машино-места лежат в общем
    # подземном паркинге проекта, который тут и стоит. Отдельный гараж был бы
    # вторым счётом тех же мест, а приобъектная стоянка — асфальт, метров она
    # не занимает вовсе.
    core_under_gns = sum(n(t.get(key) or {}, "gns") for key in UNDERGROUND_PRODUCTS)
    core_total_gns = core_above_gns + core_under_gns
    # Благоустройство считается по физической площади двора: она своя база и в
    # строительный объём не входит вовсе. Ответ объявлен один раз и назван
    # основанием — «столько-то на человека × столько-то человек».
    landscaping_sqm, landscaping_basis = landscaping_area(x, t)
    # Деньги считаются ЗДЕСЬ и один раз, вместе со своим основанием. Прежде
    # читался только рубль (`landscaping_cost(...)[0]`), а основание брали у
    # ПЛОЩАДИ — и при заданной ставке подпись советовала «задайте ставку на
    # метр ГНС», то есть сделать то, что уже сделано. Двор и деньги отвечают
    # на разные вопросы, значит и оснований у них два.
    landscaping_amount, landscaping_money_basis = landscaping_cost(
        x, t, project_above_gns(t))

    revenue: dict[date, float] = defaultdict(float)
    revenue_by_product: dict[str, float] = {}
    revenue_product_schedules: dict[str, dict[date, float]] = {}
    quantity_product_schedules: dict[str, dict[date, float]] = {}

    def add_product(
        name: str,
        schedule: dict[date, float],
        physical_schedule: dict[date, float],
    ) -> None:
        revenue_product_schedules[name] = dict(schedule)
        quantity_product_schedules[name] = dict(physical_schedule)
        revenue_by_product[name] = sum(schedule.values())
        for month, value in schedule.items():
            revenue[month] += value

    share = n(x, "share_before_rve_pct", 85) / 100
    # Запасное значение — то же умолчание, что видит форма, а не своя константа.
    growth_pre = n(x, "monthly_growth_pre_pct", DEFAULT_INPUTS["monthly_growth_pre_pct"]) / 100
    growth_post = n(x, "monthly_growth_post_pct", 0.25) / 100
    # Сезонность и смещение темпа были в интерфейсе, но на расчёт не влияли:
    # уходили только в шаблон ПЛАТО. Из-за этого шаблон и модель по одним и тем
    # же вводным давали разную выручку.
    seasonal = n(x, "seasonal_reduction_pct", -15) / 100
    pace = n(x, "pace_adjustment_pct", 25) / 100

    # Лестница цены квартир — с неё идея и началась (владелец, 02.09.2026:
    # «делать и квартирам — на них и строилась эта идея»). Этапы строительной
    # готовности — как в полях шаблона ПЛАТО, по их образцу. Одна на все
    # четыре основных продукта, как и ежемесячный рост: шаблон ведёт цены
    # паркинга и кладовых от цены квартир той же пропорцией.
    core_factor, core_stage_rows, core_ladder_warnings = stage_ladder_factor(
        [x.get(f"growth_stage{k}_pct") for k in (1, 2, 3, 4)],
        permit, int(n(x, "construction_months", 24)))
    core_schedule_note = {
        "sales_profile": "",
        "price_stages": [{**row, "date": row["date"].isoformat()} for row in core_stage_rows],
        "price_ladder": stage_ladder_text(core_stage_rows),
        "profile_applied": False,
        "steps_applied": core_factor is not None,
        "warnings": core_ladder_warnings,
    }

    def core_product(name: str, quantity: float, price_th: float) -> None:
        # Все четыре основных продукта индексируются одним темпом: шаблон ведёт
        # цены паркинга и кладовых от цены квартир той же пропорцией.
        add_product(name, sales_schedule(
            quantity, price_th * 1000, sales_start, rve, share, residual,
            growth_pre, growth_post, seasonal, pace, price_factor=core_factor,
        ), quantity_schedule(quantity, sales_start, rve, share, residual, seasonal, pace))

    core_product("apartments", n(apartment, "saleable"), n(x, "apartment_price_th"))
    core_product("ground_commercial", n(commercial, "saleable"), n(x, "commercial_price_th"))
    # Гостевые места не продаются: по нормативу они обслуживают посетителей и
    # остаются общим имуществом. Модель продавала весь паркинг целиком — на
    # 369 местах это 34 несуществующие продажи (владелец, 21.08.2026). В книгу
    # правило было записано давно, а движок его не исполнял.
    core_product("underground_parking", underground_saleable_spaces(underground),
                 n(x, "parking_price_th"))
    core_product("storage", storage_saleable_spaces(storage), n(x, "storage_price_th"))

    standalone_capex = {}
    # Гараж объекта копится ОТДЕЛЬНО от здания: удельная «на свою ГНС»
    # обязана воспроизводить вводную ставку, а гараж считается по подземному
    # метру. Сложенные в одно число, они дают третий показатель, который не
    # сравнить ни со сметой, ни со своей же вводной — 249 тыс ₽/м² при
    # вводной 200.
    standalone_garage_capex: dict[str, float] = {}
    object_schedule_notes: dict[str, dict[str, Any]] = {"core": core_schedule_note}

    # Паркинг объектов разложен по строкам ТЭП раньше (`apply_object_parking`),
    # и деньги его оттуда ЧИТАЮТ, а не считают второй раз: два счёта одной
    # величины однажды разошлись бы, и обе цифры выглядели бы верными.
    # Продаваемая объекта — `standalone_object_saleable`: та же формула, что
    # в книге, на той же GBA вводных, что и себестоимость объекта.
    def object_parking_row(tep_key: str) -> dict[str, Any]:
        return (t or {}).get(tep_key) or {}

    def object_saleable(tep_key: str, field: str) -> float:
        return standalone_object_saleable(x, t, tep_key)

    def object_parking_capex(tep_key: str) -> float:
        """Свой подземный паркинг объекта стоит подземного метра.

        Отдельной ставки у приобъектного паркинга нет — она была бы числом,
        которого никто не задавал. Метры считаются по ставке подземной части
        проекта, и это названо на экране.
        """
        return n(object_parking_row(tep_key), "under_gns") * n(x, "main_under_th_per_sqm") * 1000

    def object_schedule(prefix: str, sales_start: date, construction_start: date,
                        construction_months: int,
                        ) -> tuple[dict[date, float] | None, Callable[[date], float] | None]:
        """Профиль продаж объекта из текстового поля и лестница цены по его
        этапам строительной готовности."""
        weights, notes = schedule_weights(x.get(f"{prefix}_sales_profile"), sales_start)
        factor, rows, more = stage_ladder_factor(
            [x.get(f"{prefix}_growth_stage{k}_pct") for k in (1, 2, 3, 4)],
            construction_start, construction_months)
        object_schedule_notes[prefix] = {
            "sales_profile": str(x.get(f"{prefix}_sales_profile") or "").strip(),
            "price_stages": [{**row, "date": row["date"].isoformat()} for row in rows],
            "price_ladder": stage_ladder_text(rows),
            "profile_applied": weights is not None,
            "steps_applied": factor is not None,
            "warnings": notes + more,
        }
        return weights, factor

    # Выручка и CAPEX отдельно стоящих объектов — ОДИН обход реестра, а не
    # блок на объект. Четыре почти одинаковых блока различались ровно тремя
    # вещами (умолчание срока стройки, умолчание роста цены и признак «чем
    # меряется»), и все три теперь стоят строкой в `STANDALONE_OBJECTS`:
    # «поставить пару ОСЗ» перестало означать пятый такой блок.
    #
    # Календарь продаж каждого объекта складывается тут же (`sold`): его
    # читают продажи мест его гаража ниже. Собранный там второй раз, он
    # однажды разошёлся бы с этим, и обе половины выглядели бы верными.
    sold: dict[str, dict[str, Any]] = {}
    nonres_plans: dict[str, dict[str, Any]] = {}
    for obj in standalone_objects():
        if not b(x, obj.enabled_key):
            revenue_by_product[obj.key] = 0.0
            standalone_capex[obj.key] = 0.0
            continue
        months = int(n(x, f"{obj.prefix}_months", obj.default_months))
        build_start = d(x[f"{obj.prefix}_start"])
        # Себестоимость считается на том же, чем объект меряется: у метровых
        # это ГНС × ставка метра, у наземного паркинга места × ставка места.
        if obj.measure == "spaces":
            volume = n(x, f"{obj.prefix}_spaces")
            standalone_capex[obj.key] = volume * n(x, obj.rate_cost) * 1_000_000
            price = n(x, obj.rate_price) * 1_000_000
        else:
            standalone_capex[obj.key] = n(x, f"{obj.prefix}_gba_sqm") * n(x, obj.rate_cost) * 1000
            volume = object_saleable(obj.key, f"{obj.prefix}_saleable_sqm")
            price = n(x, obj.rate_price) * 1000
        if obj.garage:
            standalone_garage_capex[obj.key] = object_parking_capex(obj.key)
            standalone_capex[obj.key] += standalone_garage_capex[obj.key]
        # Признак продажи гасит ВЫРУЧКУ, а не стройку: переданный объект
        # строится за те же деньги и ведёт себя как соцобъект.
        if obj.sale_gate and not object_is_sold(x, obj):
            revenue_by_product[obj.key] = 0.0
            continue
        sales_start = d(x[f"{obj.prefix}_sales_start"])
        end_ref = add_months(build_start, months)
        # Прямая продажа и доходный метод идут мимо эскроу проекта: продукта
        # ДДУ у объекта нет, его деньги считает `developaid_nonres_strategy`
        # в финансировании, где известна ключевая ставка. Здесь — только план.
        strategy = (nonres_strategy.object_strategy(x, obj.prefix)
                    if obj.strategies else nonres_strategy.STRATEGY_DDU)
        if strategy != nonres_strategy.STRATEGY_DDU:
            revenue_by_product[obj.key] = 0.0
            nonres_plans[obj.key] = {
                "key": obj.key, "prefix": obj.prefix, "label": obj.label,
                "title": obj.tep_label or obj.label,
                "strategy": strategy, "commissioning": end_ref,
                "area_sqm": volume, "price_rub_sqm": price,
                "price_start": sales_start,
                "growth_pre": n(x, f"{obj.prefix}_growth_pre_pct", obj.growth_pre_default) / 100,
                "growth_post": n(x, f"{obj.prefix}_growth_post_pct", obj.growth_post_default) / 100,
                "parking_spaces": 0.0, "parking_price_rub": 0.0,
                "selling_share": (n(x, "marketing_pct") + n(x, "selling_pct")) / 100,
                # Плата за резервирование лимита — та же вводная, что у
                # БРИДЖа и ПФ, но с лимита НКЛ объекта (владелец, 05.10.2026).
                "reservation_fee_pct": n(x, "reservation_fee_pct"),
                # Плата за невыбранный лимит — та же вводная, что у ПФ.
                "limit_fee_pct": n(x, "limit_fee_pct"),
                # РнС делит кредит объекта на две НКЛ: участок и проект — до
                # неё, строительная — с неё.
                "permit": permit,
                "params": {suffix: x.get(f"{obj.prefix}_{suffix}")
                           for suffix in nonres_strategy.STRATEGY_FIELD_DEFAULTS},
            }
            continue
        share_value = n(x, f"{obj.prefix}_share_before_rve_pct", 85) / 100
        residual = int(n(x, f"{obj.prefix}_residual_months", 6))
        growth_pre = n(x, f"{obj.prefix}_growth_pre_pct", obj.growth_pre_default) / 100
        growth_post = n(x, f"{obj.prefix}_growth_post_pct", obj.growth_post_default) / 100
        weights, factor = object_schedule(obj.prefix, sales_start, build_start, months)
        add_product(obj.key, sales_schedule(
            volume, price, sales_start, end_ref, share_value, residual,
            growth_pre, growth_post,
            weights_override=weights, price_factor=factor,
        ), quantity_schedule(
            volume, sales_start, end_ref, share_value, residual,
            weights_override=weights,
        ))
        sold[obj.key] = {"sales_start": sales_start, "end_ref": end_ref,
                         "share": share_value, "residual": residual,
                         "growth_pre": growth_pre, "growth_post": growth_post,
                         "weights": weights, "factor": factor}

    # Места гаражей объектов продаются машино-местами (владелец,
    # 05.09.2026: «продают машиноместами конечно»). Число мест берётся со
    # СТРОК ТЭП, куда его положил `apply_object_parking`, — тогда очередь,
    # считаемая своим срезом ТЭП, получает свою долю мест сама, без второго
    # списка «чей это паркинг».
    #
    # Продукт один, а сроки у каждого объекта свои, поэтому ряды складываются:
    # места офисника продаются по календарю офисника, места встроенной
    # коммерции — по календарю дома. Один общий календарь продал бы паркинг
    # офиса третьей очереди вместе с квартирами первой.
    default_parking_price = n(x, "parking_price_th") * 1000

    def object_parking_price(tep_key: str, prefix: str) -> float:
        """Средняя стартовая цена продаваемых мест по фактическому размещению.

        Для продаваемого гаража (сейчас это только офисник) подземные места и
        места на первых этажах имеют разные вводные. Ноль сохраняет обратную
        совместимость: берётся общая цена подземного машино-места проекта.
        Гостевая доля применяется ко всему гаражу, поэтому одна и та же доля
        непродаваемых мест не меняет вес under/over в средней цене.
        """
        row = object_parking_row(tep_key)
        under = max(0.0, n(row, "parking_under_units"))
        over = max(0.0, n(row, "parking_over_units"))
        total = under + over
        if total <= 0:
            return default_parking_price
        under_mln = n(x, f"{prefix}_parking_under_price_mln_per_space")
        over_mln = n(x, f"{prefix}_parking_over_price_mln_per_space")
        under_price = under_mln * 1_000_000 if under_mln > 0 else default_parking_price
        over_price = over_mln * 1_000_000 if over_mln > 0 else default_parking_price
        return (under * under_price + over * over_price) / total

    def sell_object_parking(tep_key: str, prefix: str,
                            sales_start: date, end_ref: date,
                            share_value: float, residual_months: int,
                            growth_pre: float, growth_post: float,
                            weights: dict[date, float] | None = None,
                            factor: Callable[[date], float] | None = None,
                            seasonal_value: float | None = None,
                            pace_value: float | None = None,
                            ) -> tuple[dict[date, float], dict[date, float]] | None:
        spaces = n((t or {}).get(tep_key) or {}, "parking_saleable_units")
        if spaces <= 0:
            return None
        parking_price = object_parking_price(tep_key, prefix)
        extra = {} if seasonal_value is None else {"seasonal": seasonal_value, "pace": pace_value}
        value = sales_schedule(spaces, parking_price, sales_start, end_ref,
                               share_value, residual_months, growth_pre, growth_post,
                               weights_override=weights, price_factor=factor, **extra)
        units = quantity_schedule(spaces, sales_start, end_ref, share_value,
                                  residual_months, weights_override=weights,
                                  **({} if seasonal_value is None
                                     else {"seasonal": seasonal_value, "pace": pace_value}))
        return value, units

    # Встроенной коммерции МКД здесь нет: её машино-места лежат в общем
    # подземном паркинге проекта, у которого своя строка ТЭП и своя выручка.
    # Свой гараж у неё был бы вторым счётом тех же мест.
    # Гараж продаётся календарём СВОЕГО объекта — тем же, что посчитан выше.
    # У наземного паркинга гаража нет вовсе, и в `sold` он стоит без него:
    # обход спрашивает реестр, а не перечисляет объекты по памяти.
    # Чем и когда продаются места — для отчёта о продукте: стартовая цена и
    # календарь у них СВОИ, офисника, а не квартир. Отчёт брал цену места
    # дома и сроки дома, и темп мест офиса третьей очереди считался по
    # календарю квартир первой.
    object_parking_plan: list[dict[str, Any]] = []
    object_parking_capex_share: dict[str, float] = {}
    for obj in standalone_objects():
        if not obj.garage:
            continue
        # Паркинг — продукт СВОЕГО объекта: у каждого своя строка выручки
        # (`object_parking_product_key`), а не одна общая на все ОСЗ.
        product_key = object_parking_product_key(obj.key)
        revenue_by_product[product_key] = 0.0
        if obj.key in nonres_plans and obj.garage_sellable:
            # Места офисника при прямой продаже уходят ДКП вместе с объектом, при
            # доходном методе — сдаются. Гостевые не продаются и не сдаются.
            nonres_plans[obj.key]["parking_spaces"] = n(
                object_parking_row(obj.key), "parking_saleable_units")
            nonres_plans[obj.key]["parking_price_rub"] = object_parking_price(obj.key, obj.prefix)
        plan = sold.get(obj.key)
        if plan is None:
            continue
        sale = sell_object_parking(obj.key, obj.prefix, plan["sales_start"], plan["end_ref"],
                                   plan["share"], plan["residual"],
                                   plan["growth_pre"], plan["growth_post"],
                                   plan["weights"], plan["factor"])
        if sale is not None:
            add_product(product_key, dict(sale[0]), dict(sale[1]))
        spaces = n(object_parking_row(obj.key), "parking_saleable_units")
        if spaces > 0:
            # Во что места обошлись САМОМУ объекту: его подземный гараж и метры
            # здания под местами первых этажей по ставке здания. Эта доля
            # статьи объекта признаётся продажами мест, а не метров офиса, и
            # к пулу дома не имеет никакого отношения (владелец, 27.09.2026:
            # «весь гараж и подземный и наземный должен иметь отношение в
            # затратах и выручке только своего объекта, но никак не МКД»).
            row = object_parking_row(obj.key)
            over_gba = min(n(row, "parking_over_gba_sqm"),
                           max(0.0, n(x, f"{obj.prefix}_gba_sqm")))
            parking_capex = (standalone_garage_capex.get(obj.key, 0.0)
                             + over_gba * n(x, obj.rate_cost) * 1000)
            object_capex = standalone_capex.get(obj.key, 0.0)
            object_parking_capex_share[obj.key] = (
                min(1.0, parking_capex / object_capex) if object_capex > 0 else 0.0)
            object_parking_plan.append({
                "key": obj.key, "spaces": spaces,
                "price_th": object_parking_price(obj.key, obj.prefix) / 1000,
                "sales_start": plan["sales_start"], "end_ref": plan["end_ref"],
                "share": plan["share"], "residual": plan["residual"]})

    # Scenario model:
    # base = 100% revenue / 100% project costs
    # conservative = 90% revenue / 110% project costs
    # optimistic = 110% revenue / 90% project costs
    revenue_multiplier = n(x, "scenario_revenue_multiplier", 1.0)
    cost_multiplier = n(x, "scenario_cost_multiplier", 1.0)

    # Keep the base revenue profile so variable operating expenses can be
    # scenarioed independently from the income side.
    base_revenue = dict(revenue)

    if abs(revenue_multiplier - 1.0) > 1e-12:
        revenue = defaultdict(float, {
            month: value * revenue_multiplier for month, value in revenue.items()
        })
        for key in list(revenue_by_product):
            revenue_by_product[key] *= revenue_multiplier
        for key in list(revenue_product_schedules):
            revenue_product_schedules[key] = {
                month: value * revenue_multiplier
                for month, value in revenue_product_schedules[key].items()
            }

    # Льгота срезается сразу: и резерв, и график рассрочки должны считаться от
    # суммы к оплате, а не от валового обязательства.
    vri_gross = n(x, "land_rights_cost_mln") * 1_000_000
    vri_relief_amount, vri_net = vri_relief(x, vri_gross)

    # База статей проекта (ИРД, П, РД, подготовка, сети, ввод, содержание
    # площадки). У жилого и смешанного проекта — суммарная площадь МКД:
    # ставка объекта там «под ключ» и эти статьи уже несёт. У чисто нежилого
    # ставка объекта — только СМР здания, и статьи идут по тем же ставкам от
    # суммарной площади объектов в ГНС (`object_rate_is_turnkey`).
    objects_area = objects_total_area(x, t)
    article_gns = n(x, "hotel_gba_sqm") if is_hotel(x) else core_total_gns
    project_articles_sqm = article_gns if is_hotel(x) else core_total_gns + objects_area
    # Имя базы: у нежилого проекта она — площадь объектов (МКД там нет).
    project_articles_term = OBJECTS_TOTAL_AREA if without_housing(x) else CORE_TOTAL_AREA

    amounts = {
        "land_rights": vri_net,
        "ird": project_articles_sqm * n(x, "ird_th_per_sqm") * 1000,
        "design_p": project_articles_sqm * n(x, "design_p_th_per_sqm") * 1000,
        "design_rd": project_articles_sqm * n(x, "design_rd_th_per_sqm") * 1000,
        "author_supervision": 0.0,
        "technical_supervision": 0.0,
        # Снос считается от площади СНОСИМОГО, а не от новой ГНС: это разные
        # метры, и удельная ставка подготовительных работ здесь не годится.
        # Расселение — отдельное обязательство КРТ и отдельные деньги.
        # Ни то ни другое не соцнагрузка: соцнагрузка компенсируется деньгами
        # и входит в расчётный лимит БРИДЖа, а снос — нет.
        "demolition": n(x, "demolition_area_sqm") * n(x, "demolition_cost_th_per_sqm") * 1000,
        "resettlement": n(x, "resettlement_cost_mln") * 1_000_000,
        "preparation": project_articles_sqm * n(x, "preparation_th_per_sqm") * 1000,
        "main_above": core_above_gns * n(x, "main_above_th_per_sqm") * 1000,
        "main_under": core_under_gns * n(x, "main_under_th_per_sqm") * 1000,
        "utilities": project_articles_sqm * n(x, "utilities_th_per_sqm") * 1000,
        # Ставка на метр ГНС сильнее методики двора, когда она задана:
        # привычный сметчику показатель — просьба владельца. База — НАЗЕМНАЯ
        # ГНС ПРОЕКТА, та же, которой меряют удельные и которой считает свод
        # «Статистики»: одно имя на экране обязано значить одно число, иначе
        # «₽/м² ГНС» поля и «₽/м² ГНС» свода — два разных показателя под одной
        # подписью (владелец, 16.09.2026: «на м2 ГНС видимо пишут грамотные
        # люди»). Прежняя база — метры дома без соцобъектов и ОСЗ — давала на
        # умолчаниях 140 381 м² против 145 381, то есть тот же показатель на
        # 3,5% выше при тех же деньгах.
        "landscaping": landscaping_amount,
        "commissioning": project_articles_sqm * n(x, "commissioning_th_per_sqm") * 1000,
        "site_maintenance": project_articles_sqm * n(x, "site_maintenance_th_per_sqm") * 1000,
        # Статьи объектов — по реестру, а не перечислением: снятый оттуда
        # объект иначе валит расчёт KeyError'ом, то есть список тут второй.
        **{obj.key: standalone_capex.get(obj.key, 0.0) for obj in standalone_objects()},
        # Гостиница — статьи своего типа проекта: здание и мебель с
        # оборудованием. Считаются здесь, один раз; расчёт гостиницы получает
        # их готовыми помесячно (`hotel_plan`).
        **hotel_capex_amounts(x),
    }

    social_program = effective_social_program(x)
    social_construction_breakdown = {
        "kindergarten": social_program["kindergarten_places"] * n(x, "kindergarten_cost_mln_per_place") * 1_000_000,
        "school": social_program["school_places"] * n(x, "school_cost_mln_per_place") * 1_000_000,
        "clinic": social_program["clinic_capacity"] * n(x, "clinic_cost_mln_per_unit") * 1_000_000,
    }
    social_construction_total = sum(social_construction_breakdown.values())
    imported_social_compensation = n(x, "social_compensation_mln") * 1_000_000
    social_mode = str(x.get("social_mode", "Строительство"))
    if social_mode == "Денежная компенсация":
        social_total = imported_social_compensation if imported_social_compensation > 0 else social_construction_total
    elif social_mode == SOCIAL_MODE_BOTH:
        # Обе формы разом. Редкий, но реальный случай: школу и садик проект
        # строит сам, а за спортивный объект платит деньгами. Прежде режимы
        # исключали друг друга, и денежная нагрузка либо отменяла стройку,
        # либо молча не считалась вовсе — на Румянцеве это 1,15 млрд ₽.
        social_total = social_construction_total + imported_social_compensation
    else:
        social_total = social_construction_total
    amounts["social"] = social_total

    # Optional absolute base-cost overrides used only by the phasing wrapper.
    # Ordinary single-phase calculations do not set this field and are unchanged.
    cost_overrides = x.get("_cost_override_mln") or {}
    for override_key, override_value_mln in cost_overrides.items():
        if override_key in amounts and override_value_mln is not None:
            amounts[override_key] = float(override_value_mln) * 1_000_000

    # СМР объектов (здание и свой гараж) — в базах генподряда, техзаказчика и
    # управления только у чисто нежилого проекта: там ставка объекта — СМР.
    # У жилого и смешанного ставка «под ключ», вознаграждение генподрядчика и
    # техзаказчик в ней уже есть, и процент сверху был двойным счётом
    # (решение владельца 06.10.2026, `object_rate_is_turnkey`).
    object_works = sum(amounts[obj.key] for obj in standalone_objects()
                       if not object_rate_is_turnkey(x, obj))
    works_base = (
        amounts["main_above"] + amounts["main_under"] + amounts["social"]
        + object_works
        # Мебель и оборудование — поставка, а не работы: генподряд и
        # технадзор на неё не начисляются.
        + amounts.get("hotel", 0.0)
    )
    design_base = amounts["design_p"] + amounts["design_rd"]

    # Author supervision is modeled as a percentage of design P + RD.
    # No arbitrary fixed-million hardcode is used.
    amounts["author_supervision"] = design_base * n(x, "author_supervision_pct", 0.0) / 100

    # Project management is a separate developer overhead:
    # salaries of the project team, office/admin support and other management overheads.
    # The base mirrors the original Excel logic conceptually: design/surveys,
    # preparation, main construction, utilities, landscaping and site maintenance.
    management_base = (
        amounts["ird"]
        + amounts["design_p"] + amounts["design_rd"] + amounts["author_supervision"]
        + amounts["preparation"]
        + amounts["main_above"] + amounts["main_under"] + object_works
        + amounts["utilities"]
        + amounts["landscaping"]
        + amounts["site_maintenance"]
    )
    amounts["project_management"] = management_base * n(x, "project_management_pct", 5.0) / 100

    # Technical customer / construction control is a different cost item.
    # No separate rate exists in the source Inputs, so default is 0% until explicitly set.
    amounts["technical_supervision"] = works_base * n(x, "technical_supervision_pct", 0.0) / 100

    amounts["gc_fee"] = works_base * n(x, "gc_fee_pct") / 100

    base_for_overheads = sum(value for key, value in amounts.items()
                             if key not in RESERVE_EXCLUDED_ARTICLES)
    amounts["reserve"] = base_for_overheads * n(x, "reserve_pct") / 100

    # Смета объекта — то, что начислено ОТ его стройки: генподряд и
    # технический заказчик берут процент с базы работ, куда объект входит
    # своей статьёй, резерв — процент со всех статей. Доля объекта в них —
    # тот же процент с его денег, а не распределение: сумма долей и остатка
    # равна статье. Владельцу «Основное строительство», «Технический заказчик»
    # и «Резерв» общими строками не говорили, что это стройка офиса
    # (05.10.2026). Гараж — внутри статьи объекта, в той же доле, что при
    # расчёте (статью может перебить очередь).
    object_cost_parts: dict[str, dict[str, float]] = {}
    for obj in standalone_objects():
        own = float(amounts.get(obj.key) or 0.0)
        if own <= 0:
            continue
        # Объект «под ключ» в базу работ не входит (`object_rate_is_turnkey`,
        # решение владельца 06.10.2026): генподряд и техзаказчик в его ставке,
        # и доли процентов у него нет. Иначе own/works_base дало бы объекту
        # долю чужого генподряда — СМР дома.
        share = (0.0 if object_rate_is_turnkey(x, obj) or not works_base
                 else own / works_base)
        gc_part = amounts["gc_fee"] * share
        tz_part = amounts["technical_supervision"] * share
        planned = float(standalone_capex.get(obj.key) or 0.0)
        garage = (float(standalone_garage_capex.get(obj.key) or 0.0) * own / planned
                  if planned else 0.0)
        object_cost_parts[obj.key] = {
            "building": own - garage, "garage": garage,
            "gc_fee": gc_part, "technical_supervision": tz_part,
            "reserve": (own + gc_part + tz_part) * n(x, "reserve_pct") / 100,
        }

    capex: dict[date, float] = defaultdict(float)
    # Помесячная детализация по статьям: тот же расклад, что и в общем ряду,
    # но с разбивкой — нужна для выгрузки финмодели и сверки с эталоном.
    capex_by_article: dict[str, dict[date, float]] = defaultdict(lambda: defaultdict(float))

    def add_capex(article: str, month: date, amount: float) -> None:
        capex[month] += amount
        capex_by_article[article][month] += amount

    def spread_article(article: str, amount: float, start: date, months: int) -> None:
        bucket: dict[date, float] = defaultdict(float)
        spread_evenly(bucket, amount, start, months)
        for bucket_month, bucket_value in bucket.items():
            add_capex(article, bucket_month, bucket_value)

    def spread_s_curve(article: str, amount: float, start: date, months: int) -> None:
        # S-кривая книги (лист CF_x, строка 12) объявлена одним местом —
        # `build_curve`. Копия здесь была бы не удобством, а вторым мнением об
        # одном процессе: этой же кривой отчёт о рынке считает готовность дома
        # по датам, и разойтись им нельзя.
        if not amount:
            return
        for index, share in enumerate(build_curve.monthly_shares(months)):
            add_capex(article, add_months(start, index), amount * share)

    # Покупка платится по графику, если он задан: часть в сделку, часть
    # рассрочкой, выкуп чужих объектов по КРТ своими сроками (владелец,
    # 02.09.2026). Лимит БРИДЖа считается от всей цены — это формула банка;
    # выборка следует за платежами, и отложенный платёж сам снижает проценты.
    purchase_payments, purchase_warnings = purchase_payment_plan(
        n(x, "purchase_price_mln") * 1_000_000, x.get("purchase_schedule"), project_start, end)
    # Выкуп ЗУ/ОКС у третьих лиц — строка стоимости сделки рядом с ценой
    # участка (решение владельца, 29.09.2026: «при переносе из расчёта КРТ эти
    # суммы выкупа должны идти в стоимость сделки»). Платится графиком покупки
    # в той же пропорции; без цены участка — графиком сделки сам по себе.
    # Статья та же — «purchase»: лимит БРИДЖа, НДС, очереди и книга видят
    # сделку целиком, а разбивку на две строки дают вводные.
    buyout_total = n(x, "land_buyout_mln") * 1_000_000
    buyout_payments: list[tuple[date, float]] = []
    if buyout_total > 0:
        paid_for_price = sum(amount for _, amount in purchase_payments)
        if paid_for_price > 0:
            buyout_payments = [(when, buyout_total * amount / paid_for_price)
                               for when, amount in purchase_payments]
        else:
            buyout_payments, buyout_warnings = purchase_payment_plan(
                buyout_total, x.get("purchase_schedule"), project_start, end)
            purchase_warnings = list(purchase_warnings) + [
                f"выкуп ЗУ/ОКС: {w}" for w in buyout_warnings]
    for when, amount in [*purchase_payments, *buyout_payments]:
        add_capex("purchase", when, amount)
    purchase_schedule_info = {
        "total_mln": n(x, "purchase_price_mln") + n(x, "land_buyout_mln"),
        "price_mln": n(x, "purchase_price_mln"),
        "buyout_mln": n(x, "land_buyout_mln"),
        "custom": bool(str(x.get("purchase_schedule") or "").strip()),
        "rows": [{"date": when.isoformat(), "amount_mln": amount / 1_000_000,
                  "share": (amount / (n(x, "purchase_price_mln") * 1_000_000)
                            if n(x, "purchase_price_mln") > 0 else 0.0),
                  "offset_months": months_between(project_start, when)}
                 for when, amount in purchase_payments],
        "warnings": purchase_warnings,
    }

    # Плата за смену ВРИ идёт по собственному графику: единовременно или
    # рассрочкой с процентами на остаток. Проценты по рассрочке — отдельная
    # статья, они не смешиваются с процентами по кредитам. Доля, оплаченная
    # собственным капиталом, исключается из базы долгового финансирования.
    vri = build_vri_schedule(
        x, amounts["land_rights"], permit, rates, str(x.get("rate_scenario", "base"))
    )
    vri["totals"]["gross"] = round(vri_gross, 2)
    vri["totals"]["relief"] = round(vri_relief_amount, 2)
    if vri_relief_amount > 0 and not vri["enabled"]:
        vri["totals"]["amount"] = round(vri_net, 2)
    vri_equity_by_month: dict[date, float] = defaultdict(float)
    if vri["enabled"]:
        for row in vri["rows"]:
            when = d(row["date"])
            if when < project_start:
                # Обязательство возникло раньше очереди: платёж относим на её
                # старт, иначе он выпадет за горизонт расчёта и потеряется.
                when = project_start
                row["shifted_to_start"] = True
            if row["principal"]:
                add_capex("land_rights", when, row["principal"])
            if row["interest"]:
                add_capex("vri_interest", when, row["interest"])
            if row.get("security"):
                add_capex("vri_security", when, row["total"])
            if row["equity"]:
                vri_equity_by_month[when] += row["equity"]
        if any(row.get("shifted_to_start") for row in vri["rows"]):
            vri["warnings"].append(
                "Часть платежей ВРИ приходится на период до старта расчёта — "
                "они отнесены на первый месяц."
            )
    else:
        add_capex("land_rights", permit, amounts["land_rights"])
    # Проект, пришедший файлом или ссылкой, страницу не проходил, и обнулить
    # плату там было некому. Молчать нельзя: в КРТ платы за смену ВРИ нет, и
    # оставшееся число идёт в CAPEX, в лимит БРИДЖа и в книгу как настоящее.
    # Сами не убираем — вводная принадлежит человеку, а не расчёту; говорим.
    #
    # Строка стоит ПОСЛЕ всей развилки, а не внутри неё: вставленная между
    # `if` и `else`, она увела бы себе чужой `else` — и разовый платёж за ВРИ
    # начислялся бы ПОВЕРХ графика рассрочки. Семьдесят проверок паритета
    # поймали это сразу, но на экране такая правка выглядит как одна строка
    # текста.
    if (str(x.get("social_area_source") or "norm") == "manual"
            and n(x, "land_rights_cost_mln") > 0):
        # Разделитель разрядов меняется У ЧИСЛА, а не у всей фразы: применённый
        # к строке целиком, он съедает и запятые прозы.
        _kept = f"{n(x, 'land_rights_cost_mln'):,.0f}".replace(",", " ")
        vri["warnings"].append(
            "Соцобъекты заданы требованием КРТ, а плата за смену ВРИ "
            f"{_kept} млн ₽ осталась во вводных: в КРТ вид использования "
            "меняется условием договора, отдельного платежа городу нет. "
            "Уберите плату или снимите режим.")
    amounts["vri_interest"] = vri["totals"]["interest"]
    amounts["vri_security"] = vri["totals"]["security_cost"]
    amounts["land_rights_gross"] = vri_gross
    amounts["land_rights_relief"] = vri_relief_amount

    ird_months = max(IRD_MONTHS_MIN, int(n(x, "ird_months", 18)))
    spread_article("ird", amounts["ird"], project_start, ird_months)
    # Project design cash flow is concentrated toward RnS rather than spread evenly from acquisition.
    # This materially improves bridge timing and follows the schedule logic of the current workbook.
    design_window = min(6, ird_months)
    spread_article("design_p", amounts["design_p"], add_months(permit, -design_window), design_window)
    spread_article("design_rd", amounts["design_rd"], add_months(permit, -design_window), design_window)
    # Снос и расселение идут до РнС, вместе с подготовительными работами:
    # строить на занятой площадке нельзя.
    spread_article("demolition", amounts["demolition"], add_months(permit, -design_window), design_window)
    spread_article("resettlement", amounts["resettlement"], add_months(permit, -design_window), design_window)
    spread_article("preparation", amounts["preparation"], add_months(permit, -design_window), design_window)

    construction_months = max(1, int(n(x, "construction_months", 24)))
    spread_s_curve("main_above", amounts["main_above"], permit, construction_months)
    spread_s_curve("main_under", amounts["main_under"], permit, construction_months)
    spread_s_curve("utilities", amounts["utilities"], permit, construction_months)
    spread_s_curve("site_maintenance", amounts["site_maintenance"], permit, construction_months)
    spread_s_curve("author_supervision", amounts["author_supervision"], permit, construction_months)
    spread_s_curve("technical_supervision", amounts["technical_supervision"], permit, construction_months)
    spread_article("landscaping", amounts["landscaping"], add_months(rve, -3), 3)
    spread_article("commissioning", amounts["commissioning"], add_months(rve, -3), 3)

    # Управление проектом — следом за расходами, которыми оно вызвано: равный
    # календарный разнос от старта до РВЭ сажал полный штаб с первого дня и
    # догружал БРИДЖ сотнями миллионов при реальных тратах в одно проектирование.
    management_profile: dict[date, float] = defaultdict(float)
    for profile_article in MANAGEMENT_PROFILE_ARTICLES:
        for profile_month, profile_value in capex_by_article[profile_article].items():
            management_profile[profile_month] += profile_value
    management_total = sum(management_profile.values())
    if management_total > 0:
        for profile_month, profile_value in management_profile.items():
            add_capex("project_management", profile_month,
                      amounts["project_management"] * profile_value / management_total)
    else:
        spread_article("project_management", amounts["project_management"],
                       project_start, max(1, months_between(project_start, rve)))

    social_mode_now = str(x.get("social_mode", "Строительство"))
    social_cash_date = social_cash_payment_date(x, permit)
    if social_mode_now in ("Строительство", SOCIAL_MODE_BOTH):
        if social_program["kindergarten_places"]:
            spread_article("social", social_construction_breakdown["kindergarten"],
                           d(x["kindergarten_start"]), int(n(x, "kindergarten_months", 24)))
        if social_program["school_places"]:
            spread_article("social", social_construction_breakdown["school"],
                           d(x["school_start"]), int(n(x, "school_months", 30)))
        if social_program["clinic_capacity"]:
            spread_article("social", social_construction_breakdown["clinic"],
                           d(x["clinic_start"]), int(n(x, "clinic_months", 24)))
        # Каждая стройка идёт своим графиком, а денежная часть — одним
        # платежом в свою дату: это разные обязательства с разными сроками.
        if social_mode_now == SOCIAL_MODE_BOTH and imported_social_compensation > 0:
            add_capex("social", social_cash_date, imported_social_compensation)
    else:
        add_capex("social", social_cash_date, social_total)

    # Отдельно стоящий объект строится так же, как жилой дом, — S-кривой, а не
    # ровно по месяцам (решение владельца, 30.08.2026). Ровный расход стоял
    # здесь не как решение, а как недосмотр: главный корпус движок уже считал
    # S-кривой, и обе функции у него были. Книга при этом всегда считала
    # объекты S-кривой, и на очереди с офисами это давало 43 млн ₽ в месяц
    # разницы четыре месяца подряд — итог CAPEX сходился, профиль нет. Меньше
    # потрачено — меньше долг, выше покрытие эскроу, другая ступень лестницы
    # ставки ПФ: 14,75 млн ₽ расхождения по стоимости финансирования.
    for obj in standalone_objects():
        if not amounts.get(obj.key):
            continue
        spread_s_curve(obj.key, amounts[obj.key], d(x[f"{obj.prefix}_start"]),
                       int(n(x, f"{obj.prefix}_months", obj.default_months)))
    # Гостиница строится в окне проекта — от РнС до РВЭ; мебель и оборудование
    # — последние полгода перед вводом (или вся стройка, если она короче).
    if "hotel" in amounts:
        spread_s_curve("hotel", amounts["hotel"], permit, construction_months)
        ffe_window = max(1, min(HOTEL_FFE_MONTHS, construction_months))
        spread_article("hotel_ffe", amounts["hotel_ffe"], add_months(rve, -ffe_window),
                       ffe_window)

    # GC, reserve and project management belong to the construction phase rather than the pre-RnS bridge period.
    # This is closer to the timing used in the current Excel cash-flow model.
    spread_s_curve("gc_fee", amounts["gc_fee"], permit, construction_months)
    spread_s_curve("reserve", amounts["reserve"], permit, construction_months)

    # Apply expense scenario to ALL project-side cash outflows exactly once:
    # acquisition, VRI, social burden, design, construction, overheads, etc.
    if abs(cost_multiplier - 1.0) > 1e-12:
        capex = defaultdict(float, {
            month: value * cost_multiplier for month, value in capex.items()
        })
        capex_by_article = defaultdict(lambda: defaultdict(float), {
            article: defaultdict(float, {
                month: value * cost_multiplier for month, value in schedule.items()
            })
            for article, schedule in capex_by_article.items()
        })
        for key in list(amounts):
            amounts[key] *= cost_multiplier
        for parts in object_cost_parts.values():
            for key in parts:
                parts[key] *= cost_multiplier

    # Marketing + selling expenses are also scenarioed as expenses relative to BASE,
    # not reduced merely because conservative revenue is lower.
    operating: dict[date, float] = defaultdict(float)
    for month, value in base_revenue.items():
        operating[month] += (
            value
            * (n(x, "marketing_pct") + n(x, "selling_pct")) / 100
            * cost_multiplier
        )

    # A standalone KRT object may finish after the residential phase. Keep it in
    # the financing, tax and cash-flow horizon instead of only adding its revenue
    # to the project total.
    dated_flows = list(revenue) + list(capex) + list(operating)
    if dated_flows:
        end = max(end, max(dated_flows))

    # Долговое финансирование видит все расходы проекта, кроме той части платы
    # за ВРИ, которую собственник закрывает капиталом: она не создаёт ни выборки
    # БРИДЖа, ни выборки ПФ.
    debt_capex = dict(capex)
    for month, equity_value in vri_equity_by_month.items():
        debt_capex[month] = max(0.0, debt_capex.get(month, 0.0) - equity_value)
    # Объект вне ДДУ строится на свой кредит и капитал, а не на БРИДЖ и ПФ
    # проекта: банк ПФ эскроу-покрытия от него не получает и его не кредитует.
    # Затраты остаются в CAPEX проекта — прибыль и налог их видят.
    for key, plan in nonres_plans.items():
        plan["capex"] = dict(capex_by_article.get(key) or {})
        plan["revenue_multiplier"] = revenue_multiplier
        plan["cost_multiplier"] = cost_multiplier
        for month, value in plan["capex"].items():
            debt_capex[month] = max(0.0, debt_capex.get(month, 0.0) - value)
        end = max(end, nonres_strategy.plan_horizon_end(plan))
    # Нежилой проект: банк кредитует долю ВСЕЙ стоимости — участка, проекта,
    # сетей, надбавок, — а не только стройки здания (владелец, 04.10.2026:
    # «банк даёт деньги в какой-то пропорции, остальное даёшь сам»). Общие
    # затраты, которые иначе выбирали бы БРИДЖ и ПФ без единого рубля эскроу,
    # уходят в кредит объектов вне ДДУ долей их стройки. Доля объектов на ДДУ
    # остаётся на ПФ — у них эскроу есть. В смешанном проекте общие затраты
    # несёт ПФ жилья, как прежде.
    if nonres_plans and is_nonresidential(x):
        object_keys = {obj.key for obj in standalone_objects()}
        object_capex = {key: sum((capex_by_article.get(key) or {}).values()) for key in object_keys}
        objects_total = sum(object_capex.values())
        shares = {key: object_capex[key] / objects_total
                  for key in nonres_plans if objects_total > 0}
        for month in list(debt_capex):
            ddu_objects = sum((capex_by_article.get(key) or {}).get(month, 0.0)
                              for key in object_keys if key not in nonres_plans)
            common = max(0.0, debt_capex[month] - ddu_objects)
            if common <= 0:
                continue
            for key, share in shares.items():
                plan = nonres_plans[key]
                plan.setdefault("common_capex", {})
                plan["common_capex"][month] = common * share
            debt_capex[month] -= common * sum(shares.values())

    # Гостиничный проект: всё, что проект тратит, — затраты гостиницы. Банк
    # ПФ её не кредитует (эскроу нет); кредит — свой, гостиничный, и его
    # считает `developaid_hotel_strategy` вместе с номерами и USALI. Участок и
    # плата за ВРИ — без НДС и не амортизируются.
    hotel_plan: dict[str, Any] | None = None
    if is_hotel(x):
        land: dict[date, float] = defaultdict(float)
        for article in HOTEL_LAND_ARTICLES:
            for month, value in (capex_by_article.get(article) or {}).items():
                land[month] += value
        hotel_params = hotel_strategy.params_from_inputs(x)
        hotel_plan = {
            "commissioning": rve, "start": project_start,
            "capex": {month: value for month, value in capex.items() if value},
            "capex_ffe": dict(capex_by_article.get("hotel_ffe") or {}),
            "capex_land": dict(land),
            "params": hotel_params,
            "revenue_multiplier": revenue_multiplier,
            "missing": [f.label for f in hotel_strategy.missing_fields(
                hotel_params, with_capex=True)],
        }
        debt_capex = {month: 0.0 for month in debt_capex}
        end = max(end, hotel_strategy.plan_horizon_end(hotel_plan))

    return {
        "project_start": project_start,
        "permit": permit,
        "sales_start": sales_start,
        "rve": rve,
        "end": end,
        "revenue": dict(revenue),
        "revenue_by_product": revenue_by_product,
        "revenue_product_schedules": revenue_product_schedules,
        "quantity_product_schedules": quantity_product_schedules,
        "capex": dict(capex),
        "capex_by_article": {article: dict(schedule) for article, schedule in capex_by_article.items()},
        "debt_capex": debt_capex,
        "nonres_plans": nonres_plans,
        "hotel_plan": hotel_plan,
        # Общие затраты (участок, проект, сети) кредитует НКЛ объектов, а не
        # БРИДЖ и ПФ: так устроен чисто нежилой проект. Читает финансирование —
        # лимит БРИДЖа такому проекту не считается. Гостиничный проект так же:
        # все его затраты несёт кредит гостиницы (`hotel_plan`).
        "common_on_object_loans": bool((nonres_plans and is_nonresidential(x)) or hotel_plan),
        "operating": dict(operating),
        "capex_amounts": amounts,
        # Гараж объекта внутри его статьи, но со своей базой: здание меряется
        # своей ГНС, гараж — подземным метром. Без этой пары удельная объекта
        # молча смешивает два показателя.
        "standalone_garage_capex": dict(standalone_garage_capex),
        "object_cost_parts": object_cost_parts,
        "object_parking_plan": list(object_parking_plan),
        # Доля статьи объекта, которая приходится на его ПРОДАВАЕМЫЙ паркинг.
        # Долей, а не суммой: статья объекта может быть перебита очередью
        # (`_cost_override_mln`), и доля переносится на то, что осталось.
        "object_parking_capex_share": dict(object_parking_capex_share),
        "purchase_schedule": purchase_schedule_info,
        "object_schedule_notes": object_schedule_notes,
        "core_above_gns": core_above_gns,
        "core_under_gns": core_under_gns,
        # База статей проекта и её имя — один ответ для PDF, страницы и книг.
        "project_articles_sqm": project_articles_sqm,
        "project_articles_area": project_articles_term.key,
        # База благоустройства — своя, физическая: она не строительный объём, и
        # едет наружу вместе с основанием, чтобы читатель видел, чем посчитано.
        "landscaping_area_sqm": landscaping_sqm,
        "landscaping_basis": landscaping_basis,
        # Чем посчитаны ДЕНЬГИ. У двора и у рубля основания разные: заданная
        # ставка двор не читает вовсе, и его основание рядом с суммой читается
        # как её причина.
        "landscaping_money_basis": landscaping_money_basis,
        # Показатель МЕТОДИКИ, а не применённый. Пока он считался из денег, а
        # деньги — из заданной руками ставки, подпись «очистите поле —
        # вернётся методика (30)» повторяла введённое число: на умолчаниях
        # методика даёт 0,31, то есть предложенное действие обещало не тот
        # исход почти в сто раз. Считается всегда и независимо от поля.
        "landscaping_by_class": (landscaping_sqm
                                 * float(x.get("landscaping_th_per_sqm") or 0.0) * 1000),
        # Чем посчитаны ДЕНЬГИ: заданная ставка двор не читает вовсе, и
        # основание двора рядом с суммой читается как её причина.
        "landscaping_by_rate": float(x.get("landscaping_gns_th_per_sqm") or 0.0) > 0,
        "social_program": social_program,
        "social_construction_breakdown": social_construction_breakdown,
        "social_cash_date": social_cash_date,
        "imported_social_compensation": imported_social_compensation,
        "vri": vri,
        "vri_equity": dict(vri_equity_by_month),
    }


# --- ступенчатая специальная ставка ------------------------------------------
# В договорах НКЛ надбавка к ключевой ступенчатая: BVX003 — 3,47% при покрытии
# эскроу 100–110%, 1,75% при 110–120%, 0,03% при 120–130%, дальше 0,01%. У нас
# ставка была одна на всё покрытие, и модель завышала проценты сильным
# проектам. Таблица индивидуальна для каждого НКЛ, поэтому «типовую» зашивать
# нельзя: ступени вводятся полем, пустое поле оставляет одну ставку.
# Пары ищет `_scan_number_pairs` (см. график платежей): регулярка
# `(\d+(?:[.,]\d+)?)\s*%?\s*[:=\-–—]\s*(\d+(?:[.,]\d+)?)` через `findall`
# давала тот же ответ за квадрат шагов на длинных строках цифр и пробелов.
_PF_STEP_SEPARATORS = ":=-–—"


def pf_special_steps(value: Any) -> list[tuple[float, float]]:
    """Ступени «покрытие → ставка» из строки. Доли, а не проценты.

    Принимаем то, что человек перепишет из договора: «100:3,47; 110:1,75»,
    «100% - 3.47%», с переносами строк. Разделитель пар не фиксируем — пара
    опознаётся по самой форме «число : число», иначе запятая работает и
    разделителем, и десятичной точкой сразу, а в договоре она десятичная.
    """
    if isinstance(value, (list, tuple)):
        pairs = []
        for item in value:
            if isinstance(item, (list, tuple)) and len(item) >= 2:
                pairs.append((str(item[0]), str(item[1])))
        found = pairs
    else:
        found = [(left, right) for left, _percent, right in _scan_number_pairs(
            str(value or ""), _PF_STEP_SEPARATORS, right_fraction=True)]
    steps: list[tuple[float, float]] = []
    for raw_coverage, raw_rate in found:
        try:
            coverage = float(str(raw_coverage).replace(",", ".").strip())
            rate = float(str(raw_rate).replace(",", ".").strip())
        except (TypeError, ValueError):
            continue
        # Покрытие пишут и процентами (110), и разами (1,1). Ниже трёх — это
        # разы: покрытие 3% лестницей не описывают, а покрытие 3× бывает.
        if coverage > 3:
            coverage /= 100.0
        if coverage <= 0 or rate < 0:
            continue
        steps.append((coverage, rate / 100.0))
    steps.sort(key=lambda step: step[0])
    return steps


def pf_special_steps_formula(coverage_ref: str, steps: list[tuple[float, float]],
                             base: str,
                             refs: list[tuple[str, str]] | None = None) -> str:
    """Лестница ступеней формулой Excel: вложенные IF по покрытию.

    Методику правят в двух местах — в движке и в книге. Ставку ПФ так уже
    теряли: правка ушла в движок, строка 57 листа «КРЕДИТЫ» осталась прежней,
    и книга показала 360,3 млн ₽ процентов против 746,5 млн ₽ в отчёте. Чтобы
    это не повторилось, формулу собирает тот же код, что считает ступени.

    `refs` — пары ячеек (порог, ставка) вместо зашитых чисел: человек работает
    книгой и правит лестницу как вводную, а не как формулу по всем месячным
    колонкам (владелец, 20.08.2026: «сейчас-то надбавка — это вводная»).
    Пустой порог выключает ступень: в сравнении пустая ячейка читается нулём,
    и защита «порог > 0» гасит ветку. Без неё было бы наоборот — покрытие
    всегда не меньше пустоты, и стёртая ступень срабатывала бы всегда.
    """
    formula = base
    if refs:
        assert len(refs) == len(steps)
        for (edge_ref, rate_ref), _ in zip(refs, steps):
            formula = (f"IF(AND({edge_ref}>0,{coverage_ref}>={edge_ref}),"
                       f"{rate_ref},{formula})")
        return formula
    for edge, rate in steps:
        formula = f"IF({coverage_ref}>={edge:.6g},{rate:.8g},{formula})"
    return formula


def pf_special_rate_at(coverage: float, steps: list[tuple[float, float]],
                       default_rate: float) -> float:
    """Ставка ступени по фактическому покрытию месяца.

    Ниже первой ступени действует обычная специальная ставка: лестница в
    договоре начинается со стопроцентного покрытия, и придумывать за банк то,
    что ниже, мы не будем.
    """
    rate = default_rate
    for edge, step_rate in steps:
        if coverage + 1e-9 >= edge:
            rate = step_rate
        else:
            break
    return rate


def underground_guest_spaces(row: dict[str, Any]) -> int:
    """Гостевые места подземного паркинга — те, что не продаются.

    Точное число приходит с импортом ГлавАПУ и хранится рядом с местами. Когда
    его нет (места введены руками), оно выводится из самого норматива: гостевые
    — десятая часть постоянных, значит из S = P + ceil(P/10) следует P ≈ S/1,1,
    и гостевых остаётся S/11. На 369 местах это 34 — ровно столько, сколько
    насчитал владелец.
    """
    try:
        total = float(row.get("units") or 0)
    except (TypeError, ValueError):
        total = 0.0
    known = row.get("guest_units")
    if known not in (None, ""):
        try:
            # Гостевых не бывает больше, чем мест построено: такое число —
            # чужое (умолчания шаблона или прежний ТЭП: 109 гостевых на 69
            # местах), а не решение проекта, и продаж оно не обнуляет.
            return max(0, min(int(round(float(known))), int(round(max(0.0, total)))))
        except (TypeError, ValueError):
            pass
    return max(0, int(round(total / 11.0))) if total > 0 else 0


def transferred_units(row: dict[str, Any]) -> float:
    """Переданные единицы продукта: построены, но не продаются.

    У продуктов, которые продаются метрами, переданное живёт в колонке
    «передаваемая» и вычитается из продаваемой площади. У паркинга и кладовых
    продаётся ШТУКА, и метры про них ничего не говорят: гараж, отданный
    городу, уменьшил бы площадь, а места продолжили бы продаваться все.
    Поэтому у штучных продуктов переданное — своё число, в штуках
    (владелец, 04.09.2026: «если хочу так же коммерцию отдать или
    машиноместа?»). Механизм «строим, но не продаём» у паркинга уже есть —
    гостевые места, — и переданные идут той же дорогой.
    """
    try:
        return max(0.0, float(row.get("transfer_units") or 0))
    except (TypeError, ValueError):
        return 0.0


def underground_saleable_spaces(row: dict[str, Any]) -> float:
    """Продаваемые машино-места: всё, кроме гостевых и переданных."""
    try:
        total = float(row.get("units") or 0)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, total - underground_guest_spaces(row) - transferred_units(row))


def storage_saleable_spaces(row: dict[str, Any]) -> float:
    """Продаваемые кладовые: построенные минус переданные."""
    try:
        total = float(row.get("units") or 0)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, total - transferred_units(row))


# Ряды объекта вне ДДУ, которые едут в месячные строки финансирования. Свод
# очередей складывает их как прочие потоки, остаток кредита — как остаток.
NONRES_ROW_FLOWS = (
    "nonres_revenue", "nonres_costs", "nonres_vat_paid", "nonres_loan_draw",
    "nonres_loan_interest", "nonres_loan_interest_paid", "nonres_loan_fee",
    "nonres_loan_repayment", "nonres_cash_to_equity", "nonres_residual_value",
)
NONRES_ROW_STOCKS = ("nonres_loan_balance",)


def nonres_overlay(x: dict, rates: list[dict[str, Any]], op: dict) -> dict[str, Any]:
    """Деньги ТЦ и офисов вне ДДУ — один расчёт на объект.

    План объекта (затраты, ввод, цена, вводные стратегии) собирает
    `build_operating_model`; здесь он получает ключевую ставку сценария и
    превращается в помесячные ряды `developaid_nonres_strategy.object_flows`.
    Все поверхности читают итог отсюда — из `finance["nonres"]` и месячных
    строк, — а не считают объект заново.
    """
    plans = op.get("nonres_plans") or {}
    objects: dict[str, Any] = {}
    monthly: dict[str, dict[date, float]] = defaultdict(lambda: defaultdict(float))
    if not plans:
        return {"objects": objects, "monthly": {}, "totals": {}}
    scenario = str(x.get("rate_scenario", "low"))
    vat_rate = max(0.0, n(x, "vat_pct", 22)) / 100

    def key_rate(month: date) -> float:
        return rate_lookup(rates, month, scenario)

    for key, plan in plans.items():
        flows = nonres_strategy.object_flows(plan, key_rate, vat_rate=vat_rate)
        flows["title"] = plan.get("title") or key
        flows["params"] = dict(plan.get("params") or {})
        flows["financing"] = object_financing(flows)
        flows["result"] = object_result(
            flows, start=op["project_start"],
            discount_rate=n(x, "discount_rate_pct", 20) / 100,
            tax_rate=n(x, "profit_tax_pct", 25) / 100)
        # Исходные данные книги нежилого проекта: что движок дал объекту
        # (CAPEX по месяцам, общие затраты, ключевая ставка), — всё остальное
        # книга считает своими формулами и сверяет с итогом движка.
        flows["book"] = {
            "strategy": plan["strategy"], "title": flows["title"],
            "commissioning": plan["commissioning"].isoformat(),
            "price_start": (plan.get("price_start") or plan["commissioning"]).isoformat(),
            "area_sqm": float(plan.get("area_sqm") or 0.0),
            "parking_spaces": float(plan.get("parking_spaces") or 0.0),
            "price_rub_sqm": float(plan.get("price_rub_sqm") or 0.0),
            "parking_price_rub": float(plan.get("parking_price_rub") or 0.0),
            "growth_pre": float(plan.get("growth_pre") or 0.0),
            "growth_post": float(plan.get("growth_post") or 0.0),
            "selling_share": float(plan.get("selling_share") or 0.0),
            "revenue_multiplier": float(plan.get("revenue_multiplier", 1.0) or 1.0),
            "cost_multiplier": float(plan.get("cost_multiplier", 1.0) or 1.0),
            "vat_rate": vat_rate,
            "params": dict(plan.get("params") or {}),
            "months": [{"month": mm.isoformat(),
                        "capex": float((plan.get("capex") or {}).get(mm, 0.0) or 0.0),
                        "common": float((plan.get("common_capex") or {}).get(mm, 0.0) or 0.0),
                        "key_rate": key_rate(mm)}
                       for mm in flows["months"]],
        }
        objects[key] = flows
        series = flows["monthly"]

        def get(name: str, month: date) -> float:
            return float((series.get(name) or {}).get(month, 0.0) or 0.0)

        object_rows: list[dict[str, Any]] = []
        result_series = flows["result"]["monthly"]
        for month in flows["months"]:
            row = {
                "nonres_revenue": get("sale_revenue", month) + get("rent_revenue", month)
                + get("exit_revenue", month) + get("residual_value", month),
                "nonres_residual_value": get("residual_value", month),
                "nonres_costs": get("selling_cost", month) + get("opex", month)
                + get("property_tax", month) + get("exit_cost", month),
                "nonres_vat_paid": get("vat_paid", month),
                "nonres_vat_charged": get("vat_charged", month),
                "nonres_loan_draw": get("loan_draw", month),
                "nonres_loan_interest": get("loan_interest_cap", month)
                + get("loan_interest_paid", month),
                "nonres_loan_interest_paid": get("loan_interest_paid", month),
                "nonres_loan_fee": get("loan_fee", month),
                "nonres_loan_repayment": get("loan_repayment", month),
                "nonres_loan_balance": get("loan_balance", month),
                "nonres_cash_to_equity": get("cash_to_equity", month),
                "nonres_capex": float(plan["capex"].get(month, 0.0) or 0.0),
                "nonres_tax_margin": get("tax_margin", month),
                "nonres_common_capex": float(flows["common_by_month"].get(month, 0.0) or 0.0),
            }
            for name, value in row.items():
                monthly[name][month] += value
            # Строка объекта для книги: те же ряды плюс его собственный итог —
            # налог объекта и поток его капитала (`object_result`).
            object_rows.append({
                "month": month.isoformat(), **row,
                **{name: float((result_series.get(name) or {}).get(month, 0.0) or 0.0)
                   for name in OBJECT_RESULT_SERIES}})
        flows["rows"] = object_rows
        flows["years"] = object_years(flows)
    totals = {name: float(sum(values.values())) for name, values in monthly.items()}
    return {"objects": objects,
            "monthly": {name: dict(values) for name, values in monthly.items()},
            "totals": totals}


def object_years(flows: dict[str, Any]) -> list[dict[str, Any]]:
    """Ряды объекта по календарным годам — суммы месячных рядов `object_flows`.

    Не второй расчёт, а свёртка: выручка ДКП, аренда, выход, эксплуатация,
    налог на имущество и NOI года — суммы тех же месяцев; загрузка — средняя
    по месяцам эксплуатации года; доля выручки ДКП — накопленным итогом от
    всей выручки ДКП объекта. Схема рядов общая для любого объекта вне ДДУ.
    """
    series = flows.get("monthly") or {}
    sale_total = float(sum((series.get("sale_revenue") or {}).values()))
    years: dict[int, dict[str, Any]] = {}
    occupancy: dict[int, list[float]] = defaultdict(list)
    for month in flows.get("months") or []:
        year = years.setdefault(month.year, {
            "year": month.year, "sale_revenue": 0.0, "rent_revenue": 0.0,
            "exit_revenue": 0.0, "opex": 0.0, "property_tax": 0.0, "noi": 0.0})
        for name in ("sale_revenue", "rent_revenue", "exit_revenue", "opex", "property_tax"):
            year[name] += float((series.get(name) or {}).get(month, 0.0) or 0.0)
        if month in (series.get("occupancy") or {}):
            occupancy[month.year].append(float(series["occupancy"][month] or 0.0))
    sold = 0.0
    out = []
    for key in sorted(years):
        year = years[key]
        year["noi"] = (year["rent_revenue"] - year["opex"] - year["property_tax"]
                       if year["rent_revenue"] else 0.0)
        values = occupancy.get(key) or []
        year["occupancy"] = sum(values) / len(values) if values else None
        sold += year["sale_revenue"]
        year["sold_share"] = sold / sale_total if sale_total else None
        out.append(year)
    return out


# Строка расходов объектов вне ДДУ в структуре расходов и в экономике
# проекта — одна подпись на все поверхности.
NONRES_COSTS_LABEL = "Объекты вне ДДУ: продажи ДКП, эксплуатация, налог на имущество, выход"
# Гостиничный проект пишет в те же ряды свою эксплуатацию (`hotel_overlay`):
# ДКП и «вне ДДУ» у неё нет, и подпись нежилья читалась бы чужой.
HOTEL_COSTS_LABEL = ("Гостиница — эксплуатация: расходы по USALI, вознаграждение оператора, "
                     "резерв FF&E, налог на имущество, страхование, выход")


def nonres_costs_label(inputs: dict[str, Any]) -> str:
    """Подпись строки расходов объектов вне ДДУ — одна на структуру расходов
    и «Экономику проекта»."""
    return HOTEL_COSTS_LABEL if is_hotel(inputs or {}) else NONRES_COSTS_LABEL
# Чистое возмещение НДС — строка структуры расходов со знаком минус.
VAT_REFUND_LABEL = "НДС к возмещению — уменьшает расходы"


# Помесячные ряды итога объекта (`object_result`), которые едут в строки
# объекта для книги.
OBJECT_RESULT_SERIES = ("object_profit_tax", "object_equity_flow")


def _payback(flows: list[float], months: list[date]) -> dict[str, Any]:
    """Окупаемость капитала: месяц, с которого накопленный поток больше не
    уходит в минус. Без вложений окупаться нечему; ушёл в минус к концу —
    «не окупается», а не «срок не задан»."""
    first = next((i for i, value in enumerate(flows) if value < 0), None)
    if first is None:
        return {"month": None, "months": None, "reason": "вложений капитала нет"}
    cumulative, last_negative = 0.0, None
    for index, value in enumerate(flows):
        cumulative += value
        if cumulative < -0.5:
            last_negative = index
    if last_negative is None or last_negative + 1 >= len(flows):
        return {"month": None, "months": None,
                "reason": "не окупается за горизонт объекта"}
    return {"month": months[last_negative + 1],
            "months": last_negative + 1 - first, "reason": ""}


def object_result(flows: dict[str, Any], *, start: date, discount_rate: float,
                  tax_rate: float) -> dict[str, Any]:
    """Итог объекта вне ДДУ — как будто он отдельный проект.

    Читает только ряды объекта (`developaid_nonres_strategy.object_flows`):
    стройку, долю общих затрат проекта, которую кредитует его кредит, кредит,
    деньги собственнику и налоговую маржу. Схема рядов не офисная — гостиница
    или другой объект с тем же набором рядов получает итог той же функцией.

    * Затраты объекта — своя стройка и доля общих затрат; собственный капитал —
      затраты минус выборка кредита объекта.
    * Доля общих затрат признаётся в налоговой базе тем же графиком, что
      стройка объекта (`cost_recognized`): продано — списано, удержано —
      амортизируется; при удержании непризнанный остаток ждёт сделки.
    * Налог — объекта как отдельного плательщика, тем же правилом переноса
      убытка (`_profit_tax_schedule`), что у проекта. Проект платит налог со
      всей базы сразу, поэтому сумма налогов объектов с налогом проекта не
      обязана совпадать — совпадает база (`nonres_reconciliation`).
    * IRR и NPV — на поток капитала объекта после налога, NPV — по ставке
      дисконтирования проекта на дату начала проекта. При удержании оценка
      стоимости — не деньги: IRR показан с ней и без неё, денежный итог и
      окупаемость — без неё.
    """
    months: list[date] = list(flows["months"])
    series = flows["monthly"]
    capex = flows.get("capex_by_month") or {}
    common = flows.get("common_by_month") or {}
    cost_basis = float(flows.get("cost_basis") or 0.0)

    def get(name: str, month: date) -> float:
        return float((series.get(name) or {}).get(month, 0.0) or 0.0)

    capex_total = float(sum(capex.values()))
    common_total = float(sum(common.values()))
    # Затраты вне месяцев объекта в его поток не попали бы молча: капитал и
    # IRR вышли бы лучше, чем есть. Такого графика быть не должно — названо.
    outside = sorted(mm for mm in (*capex, *common) if mm not in set(months))
    if outside:
        flows.setdefault("warnings", []).append(
            "Затраты объекта вне его горизонта ("
            + ", ".join(mm.strftime("%m.%Y") for mm in outside[:3])
            + ") не вошли в поток капитала объекта — итог объекта неполон.")
    common_recognized: dict[date, float] = {}
    for month in months:
        share = (get("cost_recognized", month) / cost_basis if cost_basis
                 else (1.0 if month == flows["commissioning"] else 0.0))
        common_recognized[month] = common_total * share
    margins = {mm: get("tax_margin", mm) - common_recognized[mm] for mm in months}
    financing = {mm: get("loan_interest_cap", mm) + get("loan_interest_paid", mm)
                 + get("loan_fee", mm) for mm in months}
    tax_by_month, _detail = _profit_tax_schedule(months, margins, financing, None, tax_rate)
    profit_before_tax = float(sum(margins.values()) - sum(financing.values()))
    profit_tax = float(sum(tax_by_month.values()))

    equity_flow = {mm: (get("cash_to_equity", mm) - float(capex.get(mm, 0.0) or 0.0)
                        - float(common.get(mm, 0.0) or 0.0) - tax_by_month.get(mm, 0.0))
                   for mm in months}
    residual = {mm: get("residual_value", mm) for mm in months}
    lead = [0.0] * max(0, months_between(start, months[0])) if months else []
    with_value = lead + [equity_flow[mm] for mm in months]
    cash_only = lead + [equity_flow[mm] - residual[mm] for mm in months]
    residual_total = float(sum(residual.values()))
    loan_draw = float(sum((series.get("loan_draw") or {}).values()))
    peak, cumulative = 0.0, 0.0
    for value in cash_only:
        cumulative += value
        peak = min(peak, cumulative)
    payback = _payback(cash_only[len(lead):], months)
    return {
        "capex": capex_total,
        "common_capex": common_total,
        "cost_total": capex_total + common_total,
        "loan_draw": loan_draw,
        "equity_invested": capex_total + common_total - loan_draw,
        "equity_peak": -peak,
        "common_recognized": float(sum(common_recognized.values())),
        "tax_margin": float(sum(margins.values()) + sum(common_recognized.values())),
        "financing_cost": float(sum(financing.values())),
        "profit_before_tax": profit_before_tax,
        "profit_tax": profit_tax,
        "profit_after_tax": profit_before_tax - profit_tax,
        "equity_pre_tax": float(sum(equity_flow.values()) + profit_tax),
        "equity_cash": float(sum(cash_only)),
        "residual_value": residual_total,
        "equity_with_value": float(sum(with_value)),
        "irr": _monthly_irr(with_value),
        "irr_cash": _monthly_irr(cash_only) if residual_total else None,
        "npv": _monthly_npv(with_value, discount_rate),
        "discount_rate": discount_rate,
        "payback_month": payback["month"],
        "payback_months": payback["months"],
        "payback_reason": payback["reason"],
        "monthly": {"object_profit_tax": dict(tax_by_month),
                    "object_equity_flow": dict(equity_flow)},
    }


REPAYMENT_LABELS = {
    nonres_strategy.REPAY_ANNUITY: "Аннуитет на срок кредита с баллоном в конце",
    nonres_strategy.REPAY_SWEEP: "Из всего NOI по мере поступления",
    nonres_strategy.REPAY_BULLET: "Одним платежом при выходе",
}
DIRECT_REPAYMENT_LABEL = ("Из выручки ДКП по мере продаж — проданные помещения "
                          "выходят из залога, аннуитета нет")


def object_financing(flows: dict[str, Any]) -> dict[str, Any]:
    """Кредит объекта вне ДДУ — как банк его увидит: условия, выборка, долг на
    ввод, платёж, баллон, чем погашено и обслуживание по годам.

    Только читает ряды `object_flows` (выборка, проценты, погашение, остаток,
    ставка) — второго расчёта кредита нет. Погашение разложено по причине:
    плановое тело аннуитета, баллон в срок, остаток при выходе, из выручки
    ДКП / NOI. Сумма частей — всё погашение, и это проверяется тестом.
    Схема не офисная: любой объект с этими рядами получает тот же отчёт.
    """
    series = flows["monthly"]
    params = flows.get("params") or {}
    months: list[date] = list(flows["months"])
    commissioning: date = flows["commissioning"]
    horizon_end: date = flows["horizon_end"]
    kpi = flows.get("kpi") or {}
    strategy = flows["strategy"]

    def get(name: str, month: date) -> float:
        return float((series.get(name) or {}).get(month, 0.0) or 0.0)

    def total(name: str) -> float:
        return float(sum((series.get(name) or {}).values()))

    def num(key: str, default: float) -> float:
        try:
            value = params.get(key)
            return default if value in (None, "") else float(value)
        except (TypeError, ValueError):
            return default

    repayment = str(params.get("debt_repayment") or "").strip().lower()
    if repayment not in REPAYMENT_LABELS:
        repayment = nonres_strategy.REPAY_ANNUITY
    if strategy == nonres_strategy.STRATEGY_DIRECT:
        scheme, scheme_label = "sale", DIRECT_REPAYMENT_LABEL
    else:
        scheme, scheme_label = repayment, REPAYMENT_LABELS[repayment]
    share = max(0.0, min(0.95, num("loan_share_pct", 60.0) / 100.0))
    capex = flows.get("capex_by_month") or {}
    draw_total = total("loan_draw")
    draw_object = float(sum(float(v or 0.0) * share for mm, v in capex.items()
                            if mm <= commissioning))
    maturity: date | None = kpi.get("loan_maturity")
    # Погашение по причине.
    parts = {"scheduled": 0.0, "balloon": 0.0, "exit": 0.0, "cash": 0.0}
    balloon_month: date | None = None
    for month in months:
        repaid = get("loan_repayment", month)
        if not repaid:
            continue
        amort = get("loan_amortization", month)
        if amort:
            parts["scheduled"] += amort
            repaid -= amort
        if repaid <= 0:
            continue
        if scheme == nonres_strategy.REPAY_ANNUITY and maturity and month == maturity:
            parts["balloon"] += repaid
            balloon_month = month
        elif month == horizon_end and scheme != "sale":
            parts["exit"] += repaid
        else:
            parts["cash"] += repaid
    after = [mm for mm in months if mm > commissioning]
    first_payment = next(((get("loan_interest_paid", mm) + get("loan_amortization", mm), mm)
                          for mm in after if get("loan_amortization", mm)), (0.0, None))
    payments = [get("loan_interest_paid", mm) + get("loan_amortization", mm)
                for mm in after if get("loan_amortization", mm)]
    weight = sum(get("loan_balance", mm) for mm in months)
    avg_rate = (sum(get("loan_rate", mm) * get("loan_balance", mm) for mm in months) / weight
                if weight else 0.0)
    # Обслуживание по календарным годам: что выбрано, начислено, погашено,
    # остаток на конец года и покрытие платежей NOI.
    years: list[dict[str, Any]] = []
    for year in sorted({mm.year for mm in months}):
        span = [mm for mm in months if mm.year == year]
        operating = [mm for mm in span if mm >= commissioning]
        noi = (sum(get("rent_revenue", mm) - get("opex", mm) - get("property_tax", mm)
                   for mm in operating)
               if strategy == nonres_strategy.STRATEGY_INCOME and operating else None)
        interest_paid = sum(get("loan_interest_paid", mm) for mm in span)
        amort = sum(get("loan_amortization", mm) for mm in span)
        service = interest_paid + amort
        years.append({
            "year": year,
            "draw": sum(get("loan_draw", mm) for mm in span),
            "interest": sum(get("loan_interest_cap", mm) + get("loan_interest_paid", mm) for mm in span),
            "interest_capitalized": sum(get("loan_interest_cap", mm) for mm in span),
            "repayment": sum(get("loan_repayment", mm) for mm in span),
            "scheduled": amort,
            "balance_end": get("loan_balance", span[-1]),
            "noi": noi,
            "dscr": (noi / service) if (noi is not None and service > 0) else None,
        })
    peak = max([get("loan_balance", mm) for mm in months] or [0.0])
    return {
        "strategy": strategy,
        "scheme": scheme,
        "scheme_label": scheme_label,
        "loan_share": share,
        "spread": num("loan_spread_pp", 4.0) / 100.0,
        "fee_share": num("loan_fee_pct", 1.0) / 100.0,
        "term_years": int(num("loan_term_years", 10)) if scheme == nonres_strategy.REPAY_ANNUITY else None,
        "balloon_share": num("loan_balloon_pct", 20.0) / 100.0 if scheme == nonres_strategy.REPAY_ANNUITY else None,
        "maturity": maturity,
        "horizon_end": horizon_end,
        "commissioning": commissioning,
        "rate_at_commissioning": get("loan_rate", commissioning),
        "avg_rate": avg_rate,
        "draw_total": draw_total,
        "draw_object": min(draw_object, draw_total),
        "draw_common": max(0.0, draw_total - draw_object),
        # Комиссия за выдачу и плата за резервирование лимита — раздельно;
        # в ряду `loan_fee` они лежат вместе.
        "fee": (total("loan_fee") - total("loan_reservation_fee")
                - total("loan_commitment_fee")),
        "reservation_fee": total("loan_reservation_fee"),
        "commitment_fee": total("loan_commitment_fee"),
        "limit": float((flows.get("totals") or {}).get("loan_limit") or 0.0),
        "limit_land": float((flows.get("totals") or {}).get("loan_limit_land") or 0.0),
        "limit_build": float((flows.get("totals") or {}).get("loan_limit_build") or 0.0),
        "interest_capitalized": total("loan_interest_cap"),
        "interest_paid": total("loan_interest_paid"),
        "debt_at_commissioning": get("loan_balance", commissioning),
        "first_payment": first_payment[0],
        "first_payment_month": first_payment[1],
        "avg_payment": (sum(payments) / len(payments)) if payments else 0.0,
        "balloon_planned": float(kpi.get("loan_balloon") or 0.0) if scheme == nonres_strategy.REPAY_ANNUITY else 0.0,
        "balloon_paid": parts["balloon"],
        "balloon_month": balloon_month,
        "repaid_scheduled": parts["scheduled"],
        "repaid_at_exit": parts["exit"],
        "repaid_from_cash": parts["cash"],
        "repaid_total": total("loan_repayment"),
        "repaid_month": kpi.get("loan_repaid_month"),
        "peak": peak,
        "dscr_min": kpi.get("dscr_min"),
        "icr_min": kpi.get("icr_min"),
        "years": years,
    }


def nonres_reconciliation(nonres: dict[str, Any], rows: list[dict[str, Any]],
                          tax_margin_by_product: dict[str, float]) -> dict[str, Any]:
    """Сходится ли сумма итогов объектов с тем, что нежильё внесло в проект.

    Деньги: поток капитала объектов до налога — это то, что проект получил
    строкой `nonres_cash_to_equity`, минус стройка объектов и доля общих
    затрат, которые проект оплатил. База налога: маржа объектов в базе проекта
    (`tax_margin_by_product`) за вычетом процентов и комиссий кредита объектов.
    Разошлось — итог объекта посчитан не из того, что вошло в проект, и это
    видно в отчёте, а не только в тесте.
    """
    objects = list((nonres.get("objects") or {}).values())
    if not objects:
        return {}
    def rows_sum(name: str) -> float:
        return float(sum(float(row.get(name, 0.0) or 0.0) for row in rows))
    project_equity = (rows_sum("nonres_cash_to_equity")
                      - float((nonres.get("totals") or {}).get("nonres_capex", 0.0))
                      - float((nonres.get("totals") or {}).get("nonres_common_capex", 0.0)))
    objects_equity = float(sum(f["result"]["equity_pre_tax"] for f in objects))
    project_base = (float(sum(tax_margin_by_product.get(key, 0.0)
                              for key in (nonres.get("objects") or {})))
                    - rows_sum("nonres_loan_interest") - rows_sum("nonres_loan_fee"))
    objects_base = float(sum(f["result"]["profit_before_tax"] + f["result"]["common_recognized"]
                             for f in objects))
    ok = abs(project_equity - objects_equity) <= 1.0 and abs(project_base - objects_base) <= 1.0
    return {"project_equity": project_equity, "objects_equity": objects_equity,
            "project_tax_base": project_base, "objects_tax_base": objects_base, "ok": ok}


# Гостиничный проект (`PROJECT_KIND_HOTEL`). Мебель и оборудование ставятся
# последние полгода перед вводом; участок и плата за ВРИ — статьи без НДС и
# без амортизации (`hotel_plan["capex_land"]`).
HOTEL_FFE_MONTHS = 6
HOTEL_LAND_ARTICLES = ("purchase", "land_rights", "vri_interest", "vri_security")


def hotel_capex_amounts(x: dict[str, Any]) -> dict[str, float]:
    """Статьи CAPEX гостиницы: здание (ГНС × ставка) и FF&E (номера × ставка).

    Только у гостиничного проекта: у остальных статей нет вовсе, а не нули —
    иначе в структуре затрат жилого проекта появились бы пустые строки.
    """
    if not is_hotel(x):
        return {}
    return {
        "hotel": n(x, "hotel_gba_sqm") * n(x, "hotel_cost_th_per_sqm") * 1000,
        "hotel_ffe": n(x, "hotel_keys") * n(x, "hotel_ffe_th_per_key") * 1000,
    }


def hotel_overlay(x: dict, rates: list[dict[str, Any]], op: dict) -> dict[str, Any]:
    """Деньги гостиничного проекта — один расчёт на проект.

    План (все затраты проекта по месяцам, ввод = РВЭ, вводные гостиницы)
    собирает `build_operating_model`; здесь он получает ключевую ставку
    сценария, ставки налогов и дисконтирования проекта и превращается в ряды
    `developaid_hotel_strategy.hotel_flows`. Ряды «объекта вне ДДУ»
    (`nonres_*`) складываются с нежилыми в `simulate_financing`, итог для
    отчёта — `finance["hotel"]`. Страница, PDF, книга и бот читают его, а не
    считают гостиницу заново.

    Незаполненные вводные не превращаются в нули: гостиница не считается, и
    итог называет, чего не хватает (`summary["missing"]`).
    """
    plan = op.get("hotel_plan")
    empty = {"flows": None, "monthly": {}, "summary": None}
    if not plan:
        return empty
    if plan.get("missing"):
        return {**empty, "summary": {"computed": False, "missing": list(plan["missing"]),
                                     "commissioning": plan["commissioning"].isoformat()}}
    scenario = str(x.get("rate_scenario", "low"))
    vat_rate = max(0.0, n(x, "vat_pct", 22)) / 100
    tax_rate = n(x, "profit_tax_pct", 25) / 100
    discount_rate = n(x, "discount_rate_pct", 20) / 100

    def key_rate(month: date) -> float:
        return rate_lookup(rates, month, scenario)

    flows = hotel_strategy.hotel_flows(plan, key_rate, vat_rate=vat_rate,
                                       profit_tax_rate=tax_rate,
                                       discount_rate=discount_rate)
    series = flows["monthly"]

    def get(name: str, month: date) -> float:
        return float((series.get(name) or {}).get(month, 0.0) or 0.0)

    monthly: dict[str, dict[date, float]] = defaultdict(dict)
    for month in flows["months"]:
        row = {
            "nonres_revenue": get("revenue", month) + get("exit_revenue", month)
            + get("residual_value", month),
            "nonres_residual_value": get("residual_value", month),
            "nonres_costs": get("opex", month) + get("property_tax", month)
            + get("insurance", month) + get("exit_cost", month),
            "nonres_vat_paid": get("vat_paid", month),
            "nonres_loan_draw": get("loan_draw", month),
            "nonres_loan_interest": get("loan_interest_cap", month)
            + get("loan_interest_paid", month),
            "nonres_loan_interest_paid": get("loan_interest_paid", month),
            "nonres_loan_fee": get("loan_fee", month),
            "nonres_loan_repayment": get("loan_repayment", month),
            "nonres_loan_balance": get("loan_balance", month),
            "nonres_cash_to_equity": get("cash_to_equity", month),
            "nonres_capex": get("capex", month),
            "nonres_tax_margin": get("tax_margin", month),
        }
        for name, value in row.items():
            if value:
                monthly[name][month] = value
    # Исходные данные книги гостиницы: что движок дал расчёту (затраты по
    # месяцам, ключевая ставка, ставки проекта), — остальное книга считает
    # своими формулами и сверяет с итогом движка.
    book = {
        "commissioning": plan["commissioning"].isoformat(),
        "start": plan["start"].isoformat(),
        "params": dict(flows["params"]),
        # Набранное в проекте как есть: пустое — пустое, а не умолчание. По
        # нему книга пишет происхождение («умолчание: …» или ориентир).
        "raw_params": dict(plan["params"]),
        # Происхождение — по текущему ориентиру: проект, сохранённый с прежним
        # ключом, не печатает прежний текст (`hotel_presets.current_origins`).
        "origins": hotel_presets.current_origins(x.get(hotel_presets.ORIGINS_KEY)),
        "vat_rate": vat_rate, "profit_tax_rate": tax_rate, "discount_rate": discount_rate,
        "revenue_multiplier": float(plan.get("revenue_multiplier", 1.0) or 1.0),
        # Книга считает смету от тех же вводных. Помесячные суммы ниже —
        # только контрольный снимок; они больше не являются базой её CAPEX.
        "capex_spec": {
            "inputs": {key: n(x, key, default) for key, default in
                       hotel_workbook.CAPEX_INPUT_DEFAULTS.items()},
            "ird_min": IRD_MONTHS_MIN,
            "ffe_months": HOTEL_FFE_MONTHS,
            "reserve_excluded": sorted(RESERVE_EXCLUDED_ARTICLES),
            "management_profile": list(MANAGEMENT_PROFILE_ARTICLES),
            "forecast": [(add_months(plan["start"], index).isoformat(),
                          key_rate(add_months(plan["start"], index)))
                         for index in range(max(360, len(flows["months"]) + 12))],
            "purchase_plan": [(months_between(plan["start"], month),
                               value / sum((op.get("capex_by_article", {}).get("purchase") or {}).values()))
                              for month, value in (op.get("capex_by_article", {}).get("purchase") or {}).items()
                              if value],
            "vri_net": float((op.get("capex_amounts") or {}).get("land_rights", 0.0))
                       / (n(x, "scenario_cost_multiplier", 1.0) or 1.0),
            "vri_enabled": bool((op.get("vri") or {}).get("enabled")),
            "engine_articles": {
                key: {months_between(plan["start"], month): value
                      for month, value in schedule.items() if value}
                for key, schedule in (op.get("capex_by_article") or {}).items()
                if key not in hotel_workbook.FORMULA_CAPEX_ARTICLES
                or (key == "land_rights" and (op.get("vri") or {}).get("enabled"))
            },
            "article_labels": dict(_MONTHLY_CAPEX_LABELS),
        },
        "months": [{"month": mm.isoformat(),
                    "capex": float(plan["capex"].get(mm, 0.0) or 0.0),
                    "capex_ffe": float(plan["capex_ffe"].get(mm, 0.0) or 0.0),
                    "capex_land": float(plan["capex_land"].get(mm, 0.0) or 0.0),
                    "key_rate": key_rate(mm)}
                   for mm in flows["months"]],
    }
    return {"flows": flows, "monthly": dict(monthly),
            "summary": hotel_summary(flows, book)}


def hotel_summary(flows: dict[str, Any], book: dict[str, Any]) -> dict[str, Any]:
    """Итог гостиницы для отчёта: годовой USALI, итоги и показатели, без месяцев."""
    def plain(value: Any) -> Any:
        return value.isoformat() if isinstance(value, date) else value

    kpi = {key: plain(value) for key, value in flows["kpi"].items()}
    return {
        "computed": True, "missing": [],
        "commissioning": flows["commissioning"].isoformat(),
        "horizon_end": flows["horizon_end"].isoformat(),
        "annual": [dict(row) for row in flows["annual"]],
        "totals": dict(flows["totals"]),
        "kpi": kpi,
        "warnings": list(flows["warnings"]),
        "params": dict(flows["params"]),
        "book": book,
    }


def simulate_financing(x: dict, t: dict, rates: list[dict[str, Any]], op: dict) -> dict:
    project_start = op["project_start"]
    permit = op["permit"]
    rve = op["rve"]
    end = op["end"]
    months = month_range(project_start, end)
    scenario = str(x.get("rate_scenario", "low"))
    interest_mode = str(x.get("bridge_interest_mode", "Капитализация в ПФ"))

    # БРИДЖем банк считает то, что существует ДО РнС (решение владельца,
    # 04.09.2026: «банк конечно считаем бриджем то что существует до рнс»).
    # Прежде лимит брал ВСЮ цену покупки, не глядя на график платежей: при
    # рассрочке «40% в сделку, 60% через 30 мес.» при РнС на 18-м месяце в
    # лимит уезжали все 7,5 млрд, хотя 4,5 из них платит уже ПФ — лимит
    # завышался ровно на эту часть («почему мы все 7.5 включаем в расчётный
    # бридж если по графику ясно, что часть будет уже в ПФ?»).
    def _before_permit(article: str) -> float:
        schedule = (op.get("capex_by_article") or {}).get(article) or {}
        return sum(value for month, value in schedule.items() if month < permit)

    bridge_limit_parts = {
        "purchase": _before_permit("purchase"),
        "design_p": _before_permit("design_p"),
        "design_rd": _before_permit("design_rd"),
        "social": 0.0,
    }
    if str(x.get("social_mode")) == "Денежная компенсация":
        bridge_limit_parts["social"] = _before_permit("social")
    elif str(x.get("social_mode")) == SOCIAL_MODE_BOTH:
        # В лимит БРИДЖа входит только денежная часть: стройку соцобъектов
        # банк финансирует проектным финансированием после РнС, и включать её
        # в БРИДЖ значило бы просить лимит дважды. Дата платежа обрезана
        # методикой до «РнС − 1 мес.», но проверяется она здесь, а не
        # подразумевается: правило живёт у читателя.
        if social_cash_payment_date(x, permit) < permit:
            bridge_limit_parts["social"] = n(x, "social_compensation_mln") * 1_000_000
    # Чисто нежилой проект БРИДЖа не открывает: участок и проект в доле
    # кредита берёт НКЛ объектов (`object_flows`), и плата за резервирование
    # считается с её лимита там же. Лимит БРИДЖа от тех же оплат был второй
    # комиссией за кредит, которого нет (владелец, 05.10.2026).
    if op.get("common_on_object_loans"):
        bridge_limit_parts = {key: 0.0 for key in bridge_limit_parts}
    calculated_bridge_limit = sum(bridge_limit_parts.values())

    # Часть первоначального финансирования может идти не из банка: собственные
    # деньги, заём учредителя, перехваченный чужой долг. Эти средства тратятся
    # раньше БРИДЖа, процентов не несут и не возвращаются — это вклад, а не
    # кредит. Прежде модель считала весь разрыв до ПФ банковским, и проект с
    # собственным входом выглядел дороже, чем он есть.
    own_funds_total = max(0.0, n(x, "pre_pf_own_funds_mln") * 1_000_000)

    # In the unified-project-cash mode the phased wrapper passes only cash
    # that an earlier queue has already released after its own debt service.
    # The schedule is dated: a receipt in July cannot fund another queue in
    # June.  This is deliberately an internal input of the atomic engine; a
    # standalone project never invents project cash for itself.
    # Накопленная касса проекта доезжает до очереди всегда: банк заберёт её в
    # РВЭ, если раскрытого эскроу не хватило (владелец, 31.08.2026). А вот
    # финансировать ею расходы до РнС — отдельное решение, это стратегия
    # «единая касса проекта». Пул один, поэтому дважды одни деньги не потратить.
    project_cash_funds_costs = bool(x.get("_phase_project_cash_funds_costs"))
    # Признак, а не умолчание: книга сметания пока не знает, и включённое по
    # умолчанию оно развело бы движок с выгрузкой молча — на проверочном
    # проекте это 246 млн ₽ стоимости финансирования и 185 млн чистой прибыли.
    # Тем же порядком заводили перенос долга между очередями.
    sweep_project_cash = bool(x.get("_phase_sweep_project_cash"))
    # Доля поступлений, которую банк забирает напрямую в погашение у очереди,
    # передавшей свой долг дальше. Остальное остаётся проекту резервом:
    # застройщику из этих денег платить содержание, налоги и комиссии
    # (владелец, 31.08.2026).
    cash_sweep_share = min(max(n(x, "_phase_cash_sweep_pct", 80.0) / 100.0, 0.0), 1.0)
    bank_sweep_schedule: dict[date, float] = {}
    for raw_month, raw_value in (x.get("_phase_bank_sweep_schedule") or {}).items():
        try:
            bank_sweep_schedule[d(raw_month)] = max(0.0, float(raw_value or 0.0))
        except Exception:
            continue
    project_cash_schedule: dict[date, float] = defaultdict(float)
    for raw_month, raw_value in (x.get("_phase_project_cash_schedule") or {}).items():
        try:
            month = d(raw_month)
            value = max(0.0, float(raw_value or 0.0))
        except (TypeError, ValueError):
            continue
        if value > 0:
            project_cash_schedule[month] += value

    # Одобренный лимит ПФ. Пусто — движок ведёт себя как прежде: лимит
    # выводится из потребности, и выборка ничем не ограничена. Задан — он
    # становится потолком, а всё, что сверх него, выходит отдельной величиной
    # «непокрытая потребность», а не дофинансируется молча.
    #
    # На Гродненской это ровно тот случай, ради которого поле заведено: книга
    # выбирает лимит на 99,92% и показывает маржу 10,7% и LLCR 1,13, потому что
    # считает по лимиту, который включает ещё не одобренный дофинанс. Разрыв в
    # такой модели не виден нигде — он равен нулю по построению.
    approved_pf_limit = max(0.0, n(x, "pf_limit_approved_mln") * 1_000_000)
    # Потолок очереди приходит от обёртки очередей СВОИМ ключом — её лимит
    # НКЛ; без него ключа нет и потолка нет. Общий лимит проекта очередь не
    # ограничивает (владелец, 20.09.2026): он ожидание на все очереди, а НКЛ
    # каждой считается заново при её открытии; обёртка обнуляет копию поля.
    _cap_given = x.get("_pf_limit_cap_mln")
    if _cap_given is not None:
        approved_pf_limit = max(0.0, float(_cap_given or 0.0) * 1_000_000)
        pf_cap_set = True
    else:
        pf_cap_set = approved_pf_limit > 0

    # Лестница разбирается один раз на расчёт, а не в каждом месяце: строку
    # человек вводит руками, и разбирать её сотню раз незачем.
    special_steps = pf_special_steps(x.get("pf_special_steps"))
    base_special_rate = n(x, "pf_special_pct") / 100

    # Финансирование до среза — факт, а не расчёт. Остатки долга и эскроу
    # приходят из книги, уплаченные проценты — из реестра платежей. Это то же
    # правило, что для CAPEX и продаж, и финансирование было последним, что ему
    # не подчинялось: движок выводил проценты из долга, ставки и покрытия, хотя
    # они уже начислены и заплачены. Считать их заново значит спорить с
    # банковской выпиской.
    #
    # Месяцы до среза берут остатки из факта и не начисляют ничего; с месяца
    # среза расчёт идёт как обычно, но стартует не с нуля, а с этих остатков.
    financing_fact = op.get("financing_fact") or {}
    fact_cut = financing_fact.get("cut")

    def run(pf_limit: float | None, cap: float | None = None) -> dict:
        own_funds_left = own_funds_total
        own_funds_used = 0.0
        project_cash_available = sum(
            value for month, value in project_cash_schedule.items()
            if month < project_start)
        project_cash_used = 0.0
        # Сколько накопленной кассы проекта ушло банку в РВЭ и в каком месяце.
        project_cash_sweep = 0.0
        sweep_month: date | None = None
        # Сколько эта очередь отдала банку по кэш-свипу после передачи долга.
        bank_sweep_out_total = 0.0
        bank_sweep_out_by_month: dict[date, float] = {}
        bank_sweep_out = 0.0
        # Возврат проекту: свип пришёл, а гасить уже нечего.
        bank_sweep_returned = 0.0
        sweep_returned = 0.0
        pf_shortfall_total = 0.0
        pf_shortfall_month: date | None = None
        bridge_balance = 0.0
        sales_after_rve = 0.0
        escrow_and_sales = 0.0
        # Раскрытие эскроу и продажи после ввода — РАЗНЫЕ события, и складывать
        # их в один накопленный ряд значит показать разблокировку заработанного
        # как выручку месяца. Ступенька в 70 млрд читалась как «после ввода
        # продали на 70» (владелец, 01.09.2026), хотя продаж в этот месяц ноль:
        # это деньги предыдущих двух лет, снятые с эскроу-счетов разом.
        escrow_released_cum = 0.0
        bridge_interest_payable = 0.0
        pf_balance = 0.0
        pf_interest_payable = 0.0
        escrow = 0.0

        bridge_draw_total = bridge_repayment_total = 0.0
        bridge_interest_total = bridge_cap_total = 0.0
        bridge_fee = calculated_bridge_limit * n(x, "reservation_fee_pct") / 100

        pf_draw_total = pf_repayment_total = 0.0
        pf_interest_total = pf_cap_total = pf_limit_fee_total = 0.0
        # Долг предыдущей очереди, принятый в ПФ этой по генеральному
        # соглашению (решение владельца, 27.08.2026). Это НЕ выборка: деньги
        # не приходят и расходов не финансируют, меняется только должник.
        # Поэтому счётчик свой: в pf_draw_total ему нельзя — оттуда он попал
        # бы в ЧИСЛИТЕЛЬ LLCR, ничем не уравновешенный (выборка уравновешена
        # CAPEX, который на неё куплен, а перенос не покупает ничего).
        carried_debt_in = 0.0
        # Остаток принятого долга на балансе. Нужен затем, что `pf_balance`
        # несёт ОБЕ величины — своё тело и принятое, — а лимит и плата за
        # невыбранный считаются только по своему: принятый долг лимита не
        # выбирает (решение владельца, 27.08.2026). Сложенные в один остаток,
        # они занижали свободный лимит ровно на принятое, и книга повторяла
        # это той же формулой — паритет молчал, потому что обе поверхности
        # ошибались одинаково.
        carried_balance = 0.0

        def own_pf_principal() -> float:
            """Тело ПФ, выбранное САМОЙ очередью, — база лимита и платы за него.

            Погашения уменьшают общий остаток, а какую его часть они гасят,
            договор не разделяет: обязательство одно. Здесь принято, что
            гасится сперва своё, — на плату это не влияет вовсе (её берут
            только до РВЭ, а до РВЭ эта линия не гасится), а потолок от такого
            допущения только смягчается, и смягчается он в ту сторону, ради
            которой правило и написано.
            """
            return max(pf_balance - carried_balance, 0.0)
        carried_debt = max(n(x, "_phase_carried_debt_mln") * 1_000_000, 0.0)
        # Месяц приёма долга. Владелец (29.08.2026): обязательство переходит
        # тогда, когда эскроу предыдущей очереди раскрылось и его не хватило,
        # — то есть в её РВЭ, а не в дату открытия нашей линии. Раньше своего
        # РнС принять его в ПФ всё равно нельзя: линии ещё нет, поэтому пол —
        # `permit`. Прежняя версия клала сюда итоговый непогашенный остаток
        # предыдущей очереди в дату НАШЕГО открытия ПФ: число из будущего в
        # прошлом, и очередь платила проценты за долг, которого ещё нет.
        carried_debt_month = permit
        _carried_at = str(x.get("_phase_carried_debt_month") or "").strip()
        if _carried_at:
            try:
                carried_debt_month = max(permit, d(_carried_at))
            except Exception:
                carried_debt_month = permit
        # Долг уходит из этой очереди в её же РВЭ: период доступности кончился,
        # эскроу раскрыто, и то, чего не хватило, банк переоформляет на
        # следующую линию. Без этого признака остаток висел на закрытой линии
        # до конца горизонта — на контрольном проекте год по полной базовой
        # ставке 13,5% (покрытие после раскрытия нулевое), 691,3 млн ₽
        # процентов, — а остаточные продажи уходили в погашение вместо кассы
        # застройщика.
        debt_leaves_at_rve = bool(x.get("_phase_debt_leaves_at_rve"))
        debt_left_at_rve = 0.0
        # Линия закрыта: после РВЭ, если раскрытого эскроу не хватило. Не
        # выбирает, не начисляет и не собирает — что бы дальше ни случилось с
        # долгом, переоформили его или объявили дефолт.
        line_closed = False
        # Линия, рассчитавшаяся в РВЭ: раскрытый эскроу закрыл долг целиком,
        # период доступности кончился, и выбирать из неё больше нечего —
        # расходы после РВЭ платит касса, а не закрытый НКЛ.
        line_settled = False
        rve_unpaid = 0.0
        defaulted_at: date | None = None
        pf_reservation_fee = (pf_limit or 0.0) * n(x, "reservation_fee_pct") / 100 if pf_limit else 0.0
        transferred_bridge_interest = 0.0

        weighted_bridge_num = weighted_bridge_key_num = weighted_bridge_den = 0.0
        weighted_pf_num = weighted_pf_den = 0.0
        weighted_pf_base_num = weighted_pf_key_num = 0.0
        # Сколько месяцев отработала каждая ступень: без этого процент нечем
        # объяснить банку — видна средняя, а из чего она сложилась, нет.
        step_months: dict[float, int] = {}
        rows = []

        for month in months:
            project_cash_available += project_cash_schedule.get(month, 0.0)
            sales = op["revenue"].get(month, 0.0)
            project_costs = op["debt_capex"].get(month, 0.0) + op["operating"].get(month, 0.0)

            key_rate = rate_lookup(rates, month, scenario)
            bridge_rate = key_rate + n(x, "bridge_spread_pp") / 100
            bridge_cap_rate = key_rate + n(x, "bridge_cap_spread_pp") / 100
            pf_base_rate = key_rate + n(x, "pf_spread_pp") / 100
            # Ставка ступени выбирается по покрытию этого месяца, а не по
            # среднему за проект: покрытие растёт по мере продаж, и в этом весь
            # смысл лестницы. Само покрытие считается ниже, после выборки ПФ.
            special_rate = base_special_rate

            bridge_draw = bridge_repayment = bridge_interest = bridge_cap = 0.0
            own_draw = project_cash_draw = sweep_draw = bank_sweep_out = 0.0
            sweep_returned = 0.0
            pf_draw = pf_repayment = pf_interest = pf_cap = limit_fee = 0.0
            interest_payment = 0.0
            escrow_release = 0.0

            if fact_cut and month < fact_cut:
                # Остаток, которого в факте нет, — это «не менялся», а не ноль:
                # выгрузка кончается раньше среза, и обнулить долг значило бы
                # погасить его выгрузкой.
                pf_balance = financing_fact.get("pf_balance", {}).get(month, pf_balance)
                bridge_balance = financing_fact.get(
                    "bridge_balance", {}).get(month, bridge_balance)
                escrow = financing_fact.get("escrow", {}).get(month, escrow)
                pf_interest = financing_fact.get("interest", {}).get(month, 0.0)
                pf_interest_total += pf_interest
                coverage = escrow / pf_balance if pf_balance > 0 else 0.0
                pf_rate = 0.0
                rows.append({
                    "month": month.isoformat(), "sales": sales,
                    "project_costs": project_costs, "key_rate": key_rate,
                    "bridge_rate": bridge_rate, "bridge_draw": 0.0,
                    "project_cash_draw": 0.0, "own_funds_draw": 0.0,
                    "bridge_repayment": 0.0,
                    "bridge_balance": bridge_balance, "bridge_interest": 0.0,
                    "bridge_capitalization": 0.0, "pf_draw": 0.0,
                    "pf_repayment": 0.0, "pf_balance": pf_balance,
                    "escrow": escrow, "escrow_release": 0.0,
                    "coverage": coverage, "pf_rate": pf_rate,
                    "pf_interest": pf_interest, "pf_interest_capitalization": 0.0,
                    "limit_fee": 0.0, "interest_payment": pf_interest,
                })
                continue

            if month < rve:
                escrow += sales

            # BРИДЖ finances project cash needs before RnS.
            if month < permit:
                need = max(project_costs, 0.0)
                # В едином потоке уже заработанный cash проекта идёт первым:
                # он уменьшает новую внешнюю потребность. Затем используются
                # заявленные собственные средства, остаток выбирается БРИДЖем.
                project_cash_draw = (min(project_cash_available, need)
                                     if project_cash_funds_costs else 0.0)
                project_cash_available -= project_cash_draw
                project_cash_used += project_cash_draw
                need -= project_cash_draw
                own_draw = min(own_funds_left, need)
                own_funds_left -= own_draw
                own_funds_used += own_draw
                bridge_draw = max(0.0, need - own_draw)
                bridge_balance += bridge_draw
                bridge_draw_total += bridge_draw
                if bridge_balance > 0:
                    bridge_interest = bridge_balance * bridge_rate / 12
                    bridge_cap = bridge_interest_payable * bridge_cap_rate / 12
                    bridge_interest_payable += bridge_interest + bridge_cap
                    bridge_interest_total += bridge_interest
                    bridge_cap_total += bridge_cap
                    weighted_bridge_num += bridge_balance * bridge_rate
                    weighted_bridge_key_num += bridge_balance * key_rate
                    weighted_bridge_den += bridge_balance

            # At RnS, refinance bridge body. Bridge interest is transferred as accrued PF interest by default.
            if month == permit:
                bridge_repayment = bridge_balance
                bridge_repayment_total += bridge_repayment
                pf_draw += bridge_balance
                bridge_balance = 0.0

                transferred_bridge_interest = bridge_interest_payable
                if interest_mode == "Капитализация в ПФ":
                    pf_interest_payable += bridge_interest_payable
                else:
                    project_costs += bridge_interest_payable
                bridge_interest_payable = 0.0

            if month >= permit:
                # PF finances all project costs; escrow is not available before RVE.
                # Но после того как долг ушёл с этой линии в РВЭ, линии больше
                # нет: период доступности кончился, НКЛ закрыт. Выбирать из
                # него расходы остаточного периода нельзя — они платятся
                # кассой. Прежде очередь после передачи долга продолжала
                # выбирать по 57 млн в месяц и тут же гасить их продажами, с
                # процентами по полной базовой ставке: та же фикция закрытой
                # линии, только мельче.
                # То же и у линии, которая в РВЭ рассчиталась полностью:
                # поздний платёж рассрочки за покупку (625 млн в июле 2031 на
                # «Нагатино») выбирался с закрытой линии, гасить его было уже
                # нечем — продажи кончились, — и проект с LLCR 1,23x и 35 млрд
                # прибыли назывался дефолтным на 625 млн.
                if not line_closed and not line_settled:
                    pf_draw += max(project_costs, 0.0)
                if cap is not None:
                    # Потолок считается от остатка на начало месяца: погашения
                    # в этом месяце идут ниже по циклу и свободного лимита
                    # сейчас ещё не дают. Капитализированные проценты лимит не
                    # выбирают (решение владельца 04.08.2026) — потолок держит
                    # только тело долга, и только СВОЁ: принятый долг лимита не
                    # выбирает. В месяц приёма это выходило само собой (он
                    # ложится на баланс ниже по циклу), а в следующие месяцы
                    # уже нет — и потолок съедался чужим обязательством.
                    room = max(cap - own_pf_principal(), 0.0)
                    if pf_draw > room:
                        pf_shortfall_total += pf_draw - room
                        if pf_shortfall_month is None:
                            pf_shortfall_month = month
                        pf_draw = room
                pf_balance += pf_draw
                pf_draw_total += pf_draw
                # Принятый долг ложится на баланс после проверки потолка:
                # лимит этой очереди он не выбирает (решение владельца,
                # 27.08.2026) — банк переносит обязательство, а не выдаёт
                # новые деньги. Но проценты на него идут как на тело ПФ, и
                # покрытие эскроу он разбавляет: покрывать приходится больше.
                if month == carried_debt_month and carried_debt > 0:
                    pf_balance += carried_debt
                    carried_balance += carried_debt
                    carried_debt_in += carried_debt

                coverage = escrow / pf_balance if pf_balance > 0 else 0.0

                # Базовая ставка (ключ + спред ПФ) начисляется на часть долга, не покрытую
                # эскроу; покрытая часть считается по специальной ставке. Средняя ставка по
                # кредиту — их взвешенная сумма. Излишек эскроу сверх долга ставку ниже
                # специальной не опускает: покрывать больше 100% нечего.
                weight = min(coverage, 1.0)
                special_rate = pf_special_rate_at(coverage, special_steps, base_special_rate)
                if special_steps and pf_balance > 0:
                    step_months[special_rate] = step_months.get(special_rate, 0) + 1
                pf_rate = pf_base_rate * (1 - weight) + special_rate * weight

                if pf_balance > 0 and not line_closed:
                    pf_interest = pf_balance * pf_rate / 12
                    pf_cap = pf_interest_payable * pf_rate / 12
                    pf_interest_payable += pf_interest + pf_cap
                    pf_interest_total += pf_interest
                    pf_cap_total += pf_cap
                    weighted_pf_num += pf_balance * pf_rate
                    weighted_pf_base_num += pf_balance * pf_base_rate
                    weighted_pf_key_num += pf_balance * key_rate
                    weighted_pf_den += pf_balance

                    # Плата за невыбранный лимит — только в период доступности
                    # линии: с открытия ПФ до РВЭ. После РВЭ эскроу раскрыт и
                    # лимита, за который платят, больше нет — решение владельца
                    # («после РВЭ платить не за что, всё погашено»). Прежде
                    # плата тикала, пока жив долг, и на Мытищах давала +465 млн
                    # комиссий к книге.
                    if pf_limit and month < rve:
                        # База — СВОЁ тело: принятый долг лимита не выбирает,
                        # значит и свободного лимита не уменьшает. Прежде он
                        # входил сюда вместе со своим, и на проверочном проекте
                        # с переносом 6,95 млрд плата выходила больше должной.
                        limit_fee = (max(pf_limit - own_pf_principal(), 0.0)
                                     * n(x, "limit_fee_pct") / 100 / 12)
                        pf_interest_payable += limit_fee
                        pf_limit_fee_total += limit_fee

                # Release escrow at RVE; subsequent sales also repay PF.
                available_for_repayment = 0.0
                if month == rve:
                    escrow_release = escrow
                    available_for_repayment = escrow_release
                    escrow = 0.0
                elif month > rve:
                    available_for_repayment = sales

                # Линия закрыта — свой долг гасить нечем, но продажи идут, и по
                # кэш-свипу доля поступлений уходит банку в погашение долга,
                # который теперь несёт следующая очередь. Расписание собирает
                # обёртка: своего баланса чужой очереди этот расчёт не знает.
                if line_closed and month > rve and sweep_project_cash and sales > 0:
                    bank_sweep_out = sales * cash_sweep_share
                    bank_sweep_out_total += bank_sweep_out
                    bank_sweep_out_by_month[month] = bank_sweep_out

                if available_for_repayment > 0 and pf_balance > 0 and not line_closed:
                    pf_repayment = min(available_for_repayment, pf_balance)
                    pf_balance -= pf_repayment
                    pf_repayment_total += pf_repayment

                # Кэш-свип: очередь передала долг, но продавать не перестала,
                # и банк забирает долю её поступлений напрямую в погашение —
                # обычно 80%, остальное остаётся проекту резервом (владелец,
                # 31.08.2026). Деньги приходят помесячно, а не одним куском в
                # РВЭ: долг гасится раньше, и процентов меньше. Доля берётся от
                # ВЫРУЧКИ, а не от свободной кассы: банк смотрит на поступления
                # на счёт, а не на то, что у застройщика осталось после трат.
                incoming = bank_sweep_schedule.get(month, 0.0)
                if incoming > 0:
                    swept = (min(incoming, pf_balance)
                             if pf_balance > 0 and not line_closed else 0.0)
                    if swept > 0:
                        project_cash_sweep += swept
                        sweep_draw = swept
                        pf_balance -= swept
                        # Свип гасит ПРИНЯТЫЙ долг: он и заведён ради него —
                        # очередь передала обязательство и продавать не
                        # перестала, банк забирает долю её поступлений в
                        # погашение того, что переехало. Отнеси его на своё
                        # тело — и свободный лимит вырос бы на уже погашенное,
                        # а с ним и плата за невыбранный: 14,6 млн ₽ на
                        # проверочном проекте, при неизменной своей выборке.
                        carried_balance = max(carried_balance - swept, 0.0)
                        pf_repayment_total += swept
                        pf_repayment += swept
                        sweep_month = month
                    # Банк забирает не больше, чем ему должны. Долг закрыт —
                    # свип прекращается, и то, что передавшая очередь уже
                    # отдала сверх нужного, возвращается проекту. Без этого
                    # деньги растворялись бы: из её кассы вычтены, а долг ими
                    # не гасится.
                    returned = incoming - swept
                    if returned > 0:
                        bank_sweep_returned += returned
                        sweep_returned = returned

                # Момент истины. Раскрытого эскроу не хватило — период
                # доступности кончился, НКЛ закрывается, и дальше у долга ровно
                # два исхода: банк переоформляет его на линию следующей очереди
                # или фиксирует дефолт (владелец, 30.08.2026: «банк не будет
                # ждать, пока продажи покроют остаток долга»). Третьего —
                # остаток живёт на закрытой линии и год гасится остаточными
                # продажами — в жизни не бывает, а модель показывала именно
                # его. Деньги от продаж после этой даты остаются застройщику.
                if month == rve and pf_balance > 0:
                    rve_unpaid = pf_balance
                    if debt_leaves_at_rve:
                        # Долг переоформлен: линия этой очереди закрывается —
                        # не выбирает, не начисляет и не собирает.
                        line_closed = True
                        debt_left_at_rve = pf_balance
                        pf_balance = 0.0
                    else:
                        # Дефолт назван, но модель на нём не обрывается
                        # (владелец, 30.08.2026): «не закрывай, лучше просто
                        # показывай, что по факту модель — дефолт на такой-то
                        # очереди и надо будет согласие банка на перенос долга
                        # на следующую или реструктуризация». Вариантов у банка
                        # много, и если эскроу не наполнился из-за продаж —
                        # это форс-мажор, которого в НКЛ и не могло быть.
                        # Условий реструктуризации мы не знаем, поэтому дальше
                        # считаем прежним допущением — остаток обслуживается
                        # продажами следующих периодов, — и называем его вслух.
                        defaulted_at = month
                elif month == rve and not line_closed:
                    # Долга в РВЭ не осталось — НКЛ закрыт: дальше расходы
                    # очереди идут из её кассы, выборок и процентов нет.
                    line_settled = True

                # Current Excel pays accumulated interest at RVE and current interest thereafter.
                if month >= rve and pf_interest_payable > 0:
                    interest_payment = pf_interest_payable
                    pf_interest_payable = 0.0
            else:
                coverage = 0.0
                pf_rate = 0.0

            sales_after_rve_month = sales if month > rve else 0.0
            sales_after_rve += sales_after_rve_month
            # Деньги, пришедшие на долг, накопленным итогом: раскрытый эскроу
            # и то, что продалось после него. Линия «продажи после раскрытия»
            # считалась от нуля и рядом с эскроу в десятки миллиардов не
            # значила ничего — «пунктир не от нуля, а от окончания эскроу»
            # (владелец, 01.09.2026). Так она и продолжает кривую счёта: там,
            # где эскроу кончился, начинается она.
            escrow_and_sales += escrow_release + sales_after_rve_month
            escrow_released_cum += escrow_release
            rows.append({
                "month": month.isoformat(),
                "sales": sales,
                # Чем гасится остаток после раскрытия: накопленные продажи
                # следующих месяцев. Без них последняя точка графика читается
                # как обрыв расчёта, а не как непогашенный долг.
                "sales_after_rve": sales_after_rve_month,
                "sales_after_rve_cumulative": sales_after_rve,
                "escrow_released_cumulative": escrow_released_cum,
                "escrow_and_sales_cumulative": escrow_and_sales,
                "project_costs": project_costs,
                "key_rate": key_rate,
                "bridge_rate": bridge_rate,
                "bridge_draw": bridge_draw,
                "project_cash_draw": project_cash_draw,
                # Касса проекта, ушедшая банку в РВЭ. Отдельно от draw: то
                # финансирует расходы до РнС, это гасит долг — разные события,
                # и складывать их в одну строку значит потерять оба.
                "project_cash_sweep": sweep_draw,
                # Ушло банку по кэш-свипу с продаж этой очереди после передачи
                # долга: её касса это теряет, а долг следующей уменьшает.
                "bank_sweep_out": bank_sweep_out,
                "bank_sweep_returned": sweep_returned,
                "own_funds_draw": own_draw,
                # Погашение тела БРИДЖа рефинансированием строка не отдавала, а
                # поток на собственный капитал его спрашивал: получал ноль и
                # считал выборку ПФ на РнС чистым притоком. Тело заходило дважды —
                # сначала выборкой БРИДЖа, потом выборкой ПФ, — и IRR улетал.
                "bridge_repayment": bridge_repayment,
                "bridge_balance": bridge_balance,
                "bridge_interest": bridge_interest,
                "bridge_capitalization": bridge_cap,
                "pf_draw": pf_draw,
                "pf_repayment": pf_repayment,
                "pf_balance": pf_balance,
                # Начисленное к уплате — вне лимита и вне тела: проценты и
                # комиссии копятся на своём счёте и платятся кассой. Без этой
                # строки график сравнивал эскроу с телом, то есть отвечал не на
                # тот вопрос: банку в раскрытие причитается тело И начисленное.
                "pf_payable": pf_interest_payable,
                # Обязательство перед банком — готовым числом, а не суммой на
                # каждой поверхности: страница, PDF и книга иначе сложили бы
                # его каждая по-своему.
                "pf_obligation": pf_balance + pf_interest_payable,
                "escrow": escrow,
                "escrow_release": escrow_release,
                "coverage": coverage,
                "pf_rate": pf_rate,
                # Ставка ступени этого месяца — рядом с покрытием, из которого
                # она выбрана: помесячная таблица должна отвечать «почему
                # столько», не отсылая к вводным.
                "pf_special_rate": special_rate,
                "pf_interest": pf_interest,
                "pf_interest_capitalization": pf_cap,
                "limit_fee": limit_fee,
                "interest_payment": interest_payment,
            })

        rve_row = next((row for row in rows if d(row.get("month")) == rve), {})
        rve_pf_shortfall = max(0.0, float(rve_row.get("pf_balance", 0.0) or 0.0))
        rve_escrow_release = max(
            0.0, float(rve_row.get("escrow_release", 0.0) or 0.0))
        # Body immediately before disclosure: what was repaid plus what stayed
        # outstanding. This is the comparison users expect at RVE; the peak
        # uncovered debt and the ending balance answer different questions.
        # Эскроу гасит СВОЙ ПФ, а излишек уходит в кассу проекта. Поэтому
        # раскрытое и погашенное — разные величины, и без второй три числа
        # рядом не вычитаются: у одной очереди эскроу больше её долга, у
        # другой меньше, а в своде они складываются (владелец, 25.08.2026:
        # «107,75 − 106,2 = 1,55, а показано 7,73»).
        rve_pf_repayment = max(0.0, float(rve_row.get("pf_repayment", 0.0) or 0.0))
        rve_pf_before_repayment = rve_pf_shortfall + rve_pf_repayment

        return {
            "rows": rows,
            "escrow_cover": _escrow_cover(rows, rve),
            "calculated_bridge_limit": calculated_bridge_limit,
            # Из чего сложился лимит — считает движок, а не вычитают экран и
            # печать. Прежде обе поверхности выводили «Приобретение проекта»
            # как «итог минус социалка минус П минус РД»: два вычитания на
            # одну величину однажды разошлись бы, и обе строки выглядели бы
            # верными.
            "calculated_bridge_parts": dict(bridge_limit_parts),
            "bridge_fee": bridge_fee,
            "bridge_draw_total": bridge_draw_total,
            "bridge_repayment_total": bridge_repayment_total,
            "bridge_interest": bridge_interest_total,
            "bridge_capitalization": bridge_cap_total,
            "transferred_bridge_interest": transferred_bridge_interest,
            "peak_bridge": max((r["bridge_balance"] for r in rows), default=0.0),
            "project_cash_used": project_cash_used,
            # Накопленная касса проекта, ушедшая банку в РВЭ этой очереди.
            "project_cash_sweep": project_cash_sweep,
            "project_cash_sweep_month": sweep_month.isoformat() if sweep_month else None,
            "bank_sweep_out": bank_sweep_out_total,
            "bank_sweep_returned": bank_sweep_returned,
            "bank_sweep_out_schedule": {
                month.isoformat(): value for month, value in bank_sweep_out_by_month.items()},
            "cash_sweep_pct": cash_sweep_share * 100.0,
            "project_cash_available_unused": project_cash_available,
            "own_funds_used": own_funds_used,
            "own_funds_available": own_funds_total,
            "avg_bridge_rate": weighted_bridge_num / weighted_bridge_den if weighted_bridge_den else 0.0,
            "avg_bridge_key_rate": weighted_bridge_key_num / weighted_bridge_den if weighted_bridge_den else 0.0,
            "current_key_rate": n(x, "rate_start_pct", 14.0) / 100,
            "bridge_spread": n(x, "bridge_spread_pp") / 100,
            "current_bridge_rate": (
                n(x, "rate_start_pct", 14.0) + n(x, "bridge_spread_pp")
            ) / 100,
            "bridge_rate_at_project_start": (
                rate_lookup(rates, project_start, scenario)
                + n(x, "bridge_spread_pp") / 100
            ),

            "pf_draw_total": pf_draw_total,
            "carried_debt_in": carried_debt_in,
            # Сколько ушло отсюда на линию следующей очереди в РВЭ. Обнулённый
            # остаток без этой величины читается как «рассчиталась сама».
            "debt_left_at_rve": debt_left_at_rve,
            "debt_carried_out": debt_left_at_rve,
            # Сколько не покрыл раскрытый эскроу и когда линия закрылась.
            # Дефолт — это дата, а не только сумма на конец горизонта: банк
            # фиксирует его в раскрытие, а не через год остаточных продаж.
            "rve_unpaid": rve_unpaid,
            "default_date": defaulted_at.isoformat() if defaulted_at else None,
            "pf_repayment_total": pf_repayment_total,
            "pf_reservation_fee": pf_reservation_fee,
            "pf_interest": pf_interest_total,
            "pf_interest_capitalization": pf_cap_total,
            "pf_limit_fee": pf_limit_fee_total,
            "peak_pf": max((r["pf_balance"] for r in rows), default=0.0),
            "peak_uncovered_pf": max((max(r["pf_balance"] - r["escrow"], 0.0) for r in rows), default=0.0),
            # Покрытие эскроу — то, от чего зависит ставка ПФ, и в книге оно
            # отдельной строкой. Без него нельзя ни свериться, ни проверить
            # тестом, дошёл ли расчёт до ступеней: на умолчаниях покрытие
            # упирается в 0,96× и ветка со ступенями не исполняется вовсе.
            "peak_escrow": max((r["escrow"] for r in rows), default=0.0),
            "peak_coverage": max(
                (r["escrow"] / r["pf_balance"] for r in rows if r["pf_balance"] > 0),
                default=0.0),
            "avg_pf_rate": weighted_pf_num / weighted_pf_den if weighted_pf_den else 0.0,
            "avg_pf_effective_rate": weighted_pf_num / weighted_pf_den if weighted_pf_den else 0.0,
            "avg_pf_base_rate": weighted_pf_base_num / weighted_pf_den if weighted_pf_den else 0.0,
            "avg_pf_key_rate": weighted_pf_key_num / weighted_pf_den if weighted_pf_den else 0.0,
            "pf_special_rate": base_special_rate,
            # Ступени с числом месяцев — по возрастанию покрытия, как в договоре.
            "pf_special_steps": [
                {"coverage_from_pct": round(edge * 100, 2),
                 "rate_pct": round(rate * 100, 4),
                 "months": int(step_months.get(rate, 0))}
                for edge, rate in special_steps],
            "ending_pf": pf_balance,
            "rve_pf_before_repayment": rve_pf_before_repayment,
            "rve_escrow_release": rve_escrow_release,
            "rve_pf_shortfall": rve_pf_shortfall,
            "rve_pf_repayment": rve_pf_repayment,
            "ending_interest_payable": pf_interest_payable,
            "pf_shortfall": pf_shortfall_total,
            # Датой, а не объектом: результат уезжает в JSON на страницу и в
            # бот, и `date` там ломает сериализацию молча — на отчёте, а не на
            # расчёте.
            "pf_shortfall_month": pf_shortfall_month.isoformat() if pf_shortfall_month else "",
        }

    # First pass determines the calculated PF limit; Excel rounds the financing requirement to 10m.
    first = run(None)
    pf_limit = ceil(first["pf_draw_total"] / 10_000_000) * 10_000_000 if first["pf_draw_total"] else 0.0
    if pf_cap_set:
        result = run(approved_pf_limit, cap=approved_pf_limit)
    else:
        result = run(pf_limit)
    # «Лимит ПФ» — тот, по которому живёт проект: одобренный, если он задан.
    # Комиссии за лимит и резервирование берутся с него же.
    result["pf_limit"] = approved_pf_limit if pf_cap_set else pf_limit
    result["pf_limit_cap_source"] = str(x.get("_pf_limit_cap_source") or
                                        ("project" if pf_cap_set else ""))
    # Сколько лимита проект просит на самом деле — считается свободным
    # прогоном, без потолка. Сравнение с одобренным и есть цена вопроса.
    result["pf_limit_required"] = pf_limit
    result["pf_limit_approved"] = approved_pf_limit

    # ТЦ и офисы вне ДДУ: их деньги складываются с проектом здесь, один раз.
    # Месячные строки получают их ряды — по ним считаются поток капитала, свод
    # очередей и пик долга; итоги — в прибыль, налог и НДС ниже.
    nonres = nonres_overlay(x, rates, op)
    # Гостиница — те же ряды «объекта вне ДДУ»: выручка мимо эскроу, свой
    # кредит, свой НДС и налоговая маржа. Сложенные здесь один раз, они идут в
    # поток капитала, прибыль, налог и НДС тем же путём, что ТЦ и офисы.
    hotel = hotel_overlay(x, rates, op)
    for name, series in hotel["monthly"].items():
        target = nonres["monthly"].setdefault(name, {})
        for month, value in series.items():
            target[month] = target.get(month, 0.0) + value
    nonres["totals"] = {name: float(sum(values.values()))
                        for name, values in nonres["monthly"].items()}
    nonres_monthly = nonres["monthly"]
    nonres_totals = nonres["totals"]
    for row in result["rows"]:
        month = d(row["month"])
        for name in (*NONRES_ROW_FLOWS, *NONRES_ROW_STOCKS):
            row[name] = float((nonres_monthly.get(name) or {}).get(month, 0.0) or 0.0)
    for key, flows in nonres["objects"].items():
        op["revenue_by_product"][key] = flows["totals"]["revenue"]
    if hotel["flows"]:
        op["revenue_by_product"]["hotel"] = sum(
            (hotel["monthly"].get("nonres_revenue") or {}).values())
    nonres_capex = nonres_totals.get("nonres_capex", 0.0)

    # Выручка эскроу-проекта — база доли вычета НДС и LLCR; общая — прибыли.
    project_revenue = sum(op["revenue"].values())
    total_revenue = project_revenue + nonres_totals.get("nonres_revenue", 0.0)
    total_capex = sum(op["capex"].values())
    commercial_costs = sum(op["operating"].values())
    nonres_costs = nonres_totals.get("nonres_costs", 0.0)

    financing_cost = (
        result["bridge_interest"] + result["bridge_capitalization"] + result["bridge_fee"]
        + result["pf_interest"] + result["pf_interest_capitalization"]
        + result["pf_limit_fee"] + result["pf_reservation_fee"]
        + nonres_totals.get("nonres_loan_interest", 0.0)
        + nonres_totals.get("nonres_loan_fee", 0.0)
    )
    profit_before_tax = (total_revenue - total_capex - commercial_costs - nonres_costs
                         - financing_cost)

    # Profit tax follows the workbook's cumulative realization method.
    # Core products share one residual cost pool; every standalone KRT object
    # recognizes its own construction cost by physical m2 / parking spaces sold.
    # Список объявлен один раз — `COST_POOL_PRODUCTS`. Перечисленный здесь
    # руками, он уже разошёлся с отчётом и с книгой на `object_parking`.
    core_products = COST_POOL_PRODUCTS
    # ФОК стоит в этом списке ТОЛЬКО когда продаётся. У переданного городу
    # выручки нет вовсе, и собственный пул расходов ему признавать нечем:
    # стоимость постройки осталась бы непризнанной до конца проекта. Переданный
    # ФОК ведёт себя как соцобъект — его CAPEX уходит в общий пул `core`.
    # Признак — свой у каждого экземпляра ФОКа.
    krt_products = tuple(
        obj.key for obj in standalone_objects()
        if not obj.sale_gate or (b(x, obj.enabled_key) and object_is_sold(x, obj))
    )
    # Состав пула и состав его стоимостей — один список, а не два: разойдись
    # они, объект попал бы в выручку и не попал в расход, и обе строки
    # выглядели бы верными.
    product_costs = {key: op["capex_amounts"].get(key, 0.0) for key in krt_products}
    # Паркинг объекта — часть СВОЕГО объекта (владелец, 27.09.2026): его гараж
    # и метры под местами первых этажей лежат в статье объекта и признаются
    # вместе с ней, продажами объекта. Так это устроено и в книге: выручка
    # мест идёт в выручку очереди, а расход — в пул объекта (`'ОБЪЕКТЫ'!B28`
    # по проданным метрам строки 22), и к пулу дома они не относятся. Своего
    # расхода у продукта мест поэтому нет, но выручка его в базу входит.
    for parking_key in OBJECT_PARKING_PRODUCT_KEYS.values():
        if any((op.get("revenue_product_schedules") or {}).get(parking_key) or {}):
            product_costs[parking_key] = 0.0
            krt_products = krt_products + (parking_key,)
    # Гостиница признаёт ВСЕ затраты проекта сама — амортизацией здания и
    # мебели, участок — при продаже (`developaid_hotel_strategy`). Пул дома у
    # гостиничного проекта пуст: второй раз те же затраты не признаются.
    if hotel["flows"]:
        product_costs["hotel"] = total_capex
    core_cost = max(
        total_capex + commercial_costs - sum(product_costs.values()), 0.0
    )
    tax_cost_by_product = {"core": core_cost, **product_costs}

    revenue_schedules = op.get("revenue_product_schedules", {})
    quantity_schedules = op.get("quantity_product_schedules", {})
    tax_margin_schedules: dict[str, dict[date, float]] = {}

    core_quantity_total = sum(
        sum(quantity_schedules.get(key, {}).values()) for key in core_products
    )
    core_months = set()
    for key in core_products:
        core_months.update(revenue_schedules.get(key, {}))
        core_months.update(quantity_schedules.get(key, {}))
    core_margin: dict[date, float] = {}
    # По порядку, а не порядком множества — та же причина, что ниже у продуктов.
    for month in sorted(core_months):
        revenue_month = sum(
            revenue_schedules.get(key, {}).get(month, 0.0) for key in core_products
        )
        quantity_month = sum(
            quantity_schedules.get(key, {}).get(month, 0.0) for key in core_products
        )
        recognized_cost = (
            core_cost * quantity_month / core_quantity_total
            if core_quantity_total else 0.0
        )
        core_margin[month] = revenue_month - recognized_cost
    if core_cost and not core_quantity_total:
        core_margin[rve] = core_margin.get(rve, 0.0) - core_cost
    tax_margin_schedules["core"] = core_margin

    for key in krt_products:
        quantity_total = sum(quantity_schedules.get(key, {}).values())
        unit_cost = product_costs[key] / quantity_total if quantity_total else 0.0
        # Месяцы обходятся ПО ПОРЯДКУ, а не порядком множества. Ключи здесь
        # строки, а порядок множества строк меняет `PYTHONHASHSEED` от процесса
        # к процессу: сумма float'ов складывалась каждый раз иначе, и один и тот
        # же расчёт на одних вводных давал разный последний разряд —
        # `tax_margin_by_product` не воспроизводился сам с собой. Ловится это
        # только двумя ПРОЦЕССАМИ: внутри одного порядок один и тот же, и в
        # прогоне поломка невидима. Сортировка здесь ещё и естественная —
        # расписание складывают по возрастанию месяца.
        product_months = sorted(set(revenue_schedules.get(key, {}))
                                | set(quantity_schedules.get(key, {})))
        tax_margin_schedules[key] = {
            month: (
                revenue_schedules.get(key, {}).get(month, 0.0)
                - quantity_schedules.get(key, {}).get(month, 0.0) * unit_cost
            )
            for month in product_months
        }

    # Объект вне ДДУ признаёт выручку и затраты своим графиком (ДКП по
    # проданным метрам, аренда — амортизацией), и маржа уже за вычетом его НДС.
    for key, flows in nonres["objects"].items():
        tax_margin_schedules[key] = dict(flows["monthly"].get("tax_margin") or {})
    if hotel["flows"]:
        tax_margin_schedules["hotel"] = dict(hotel["flows"]["monthly"].get("tax_margin") or {})

    tax_margin_by_month: dict[date, float] = defaultdict(float)
    tax_margin_by_product = {}
    for key, schedule in tax_margin_schedules.items():
        tax_margin_by_product[key] = sum(schedule.values())
        for month, value in schedule.items():
            tax_margin_by_month[month] += value

    # Проценты признаются на конец КАЖДОГО МЕСЯЦА, независимо от даты выплат
    # (п. 8 ст. 272 НК). Прежде база вычитала УПЛАЧЕННОЕ — `interest_payment`, —
    # а платится в этой модели всё разом в РВЭ: до раскрытия эскроу проценты
    # отсрочены. То есть вычет уезжал на год-полтора вперёд от месяца, в
    # котором расход возник, а остаток (проценты БРИДЖа, оплаченные капиталом
    # на РнС) вообще доезжал до конца горизонта строкой сверки. Пока очереди
    # прибыльны, разницы нет: база копится нарастающим итогом и всё равно
    # доходит до налога. Она появляется там, где есть УБЫТОЧНАЯ очередь и год
    # закрывается с убытком: половинное ограничение ст. 283 считает по годам, и
    # год, в котором расход признан, решает, сколько убытка можно зачесть.
    #
    # В начисление входит ровно то, из чего сложена стоимость финансирования:
    # проценты БРИДЖа и их капитализация, проценты ПФ и их капитализация, плата
    # за лимит. Капитализация — это проценты на отсроченные проценты, расход
    # того же месяца; путать её с капитализацией в ДОЛГЕ нельзя: та лимит ПФ не
    # выбирает (решение владельца 04.08.2026) и живёт отдельным обязательством,
    # а здесь речь только о базе налога.
    #
    # Комиссии выдачи стоят своими датами: они и не в месячных строках.
    financing_deductions: dict[date, float] = defaultdict(float)
    for row in result["rows"]:
        financing_deductions[d(row["month"])] += (
            float(row.get("bridge_interest", 0.0) or 0.0)
            + float(row.get("bridge_capitalization", 0.0) or 0.0)
            + float(row.get("pf_interest", 0.0) or 0.0)
            + float(row.get("pf_interest_capitalization", 0.0) or 0.0)
            + float(row.get("limit_fee", 0.0) or 0.0)
            + float(row.get("nonres_loan_interest", 0.0) or 0.0)
            + float(row.get("nonres_loan_fee", 0.0) or 0.0)
        )
    financing_deductions[project_start] += result["bridge_fee"]
    financing_deductions[permit] += result["pf_reservation_fee"]

    # Reconcile rounding and any residual accrued amount to the final period so
    # the schedule equals the project's reported interest and fee total exactly.
    financing_reconciliation = financing_cost - sum(financing_deductions.values())
    if abs(financing_reconciliation) > 0.01:
        financing_deductions[end] += financing_reconciliation

    # НДС. Жильё по ДДУ освобождено (пп. 23.1 п. 3 ст. 149 НК), нежилое —
    # облагается: ПСН, офисы, паркинг и кладовые. Решение владельца
    # (15.08.2026), методика снята с книги внешней модели: там ставка 22%,
    # отдельная статья БДДС и «Начало уплаты НДС» ровно в дату РВЭ.
    #
    # Затраты в модели заданы с НДС, поэтому входящий налог уже сидит в них.
    # К вычету идёт не весь: при освобождённых операциях доля, приходящаяся на
    # них, остаётся в себестоимости (п. 4 ст. 170 НК). Отсюда частая ошибка
    # «стройка 10 млрд — вернут 1,8»: возвращают только долю нежилого.
    vat_rate = max(0.0, n(x, "vat_pct", 22)) / 100
    # Облагается всё, кроме квартир: продажа жилых помещений освобождена
    # (пп. 22-23 п. 3 ст. 149 НК), машино-места и коммерция — нет. Список
    # продуктов здесь не перечисляется: паркинг отдельно стоящих объектов
    # завели позже обоих пулов и ни в один не вписали, поэтому 166,0 млн его
    # выручки выпадали из базы — 4,7 млн НДС, ровно на которые книга и отчёт
    # расходились при совпадающих до сотой доли CAPEX, выручке и EBITDA. Книга
    # считает то же самое и без списка: вся выручка минус строка квартир.
    # Берём ключи самих графиков выручки — продукт, заведённый завтра,
    # попадает в базу тем, что у него есть выручка, а не тем, что о нём
    # вспомнили.
    vat_taxable_products = tuple(
        key for key in revenue_schedules if key != "apartments"
    )
    vat_schedule: dict[date, float] = {}
    vat_charged = vat_input_deductible = 0.0
    if vat_rate > 0:
        gross_to_tax = vat_rate / (1 + vat_rate)
        taxable_revenue = sum(
            sum(revenue_schedules.get(key, {}).values()) for key in vat_taxable_products
        )
        # Начисление — по передаче объекта, а не по признанию выручки: до
        # раскрытия эскроу оплаты застройщику нет, и база возникает актом
        # после ввода (ст. 167 НК). Всё, что продано до РВЭ, начисляется в РВЭ.
        # Начисление целиком в дату РВЭ: так устроена внешняя модель, с
        # которой сверялись («Начало уплаты НДС» = РВЭ), и так книга считает
        # тем же одним выражением. Хвост остаточных продаж платится на
        # несколько месяцев раньше срока — в запас, а не в оптимизм.
        charged_by_month: dict[date, float] = {rve: taxable_revenue * gross_to_tax}
        vat_charged = sum(charged_by_month.values())
        # Входящий НДС — со строительных и коммерческих затрат. Покупка
        # участка, плата за ВРИ и проценты по кредитам НДС не облагаются,
        # поэтому в базу вычета не входят.
        # База берётся от итога CAPEX, а не суммированием словаря статей: в нём
        # живут теневые ключи вроде land_rights_gross, и слепая сумма задваивала
        # плату за ВРИ — книга и движок расходились ровно на неё.
        # Исключаем по вводным, а не по словарю статей: покупка в него не
        # попадает вовсе (уходит прямо в месячный CAPEX), а плата за ВРИ лежит
        # там дважды — вместе с теневым land_rights_gross. Книга вычитает те же
        # две ячейки, B15 и B16, поэтому обе поверхности сходятся.
        vat_bearing_costs = (
            total_capex + commercial_costs
            - n(x, "purchase_price_mln") * 1_000_000
            - n(x, "land_buyout_mln") * 1_000_000
            - n(x, "land_rights_cost_mln") * 1_000_000
            - op["capex_amounts"].get("vri_interest", 0.0)
            - op["capex_amounts"].get("vri_security", 0.0)
            # Входящий НДС объекта вне ДДУ принимает к вычету сам объект.
            - nonres_capex
        )
        deductible_share = taxable_revenue / project_revenue if project_revenue else 0.0
        vat_input_deductible = vat_bearing_costs * gross_to_tax * deductible_share
        # Вычет накапливается по ходу стройки, начисление приходит после ввода —
        # значит к моменту передачи он уже есть, и живыми деньгами уходит
        # только разница.
        due = max(vat_charged - vat_input_deductible, 0.0)
        if due > 0:
            vat_schedule[rve] = due
    vat = sum(vat_schedule.values())
    # Из базы налога на прибыль уходит НДС к уплате, а не начисленный:
    # выручка признаётся без налога (минус начисленный), а затраты — без
    # входящего в части, принятой к вычету (плюс вычет). В сумме это ровно
    # чистый НДС. Вычитать начисленный значило бы дважды учесть вычет.
    vat_charged_by_month = dict(vat_schedule)
    # НДС объекта вне ДДУ — его собственный зачёт по месяцам, а маржа объекта
    # уже без него: в базу налога он второй раз не идёт.
    for month, value in (nonres_monthly.get("nonres_vat_paid") or {}).items():
        if value:
            vat_schedule[month] = vat_schedule.get(month, 0.0) + value
    vat = sum(vat_schedule.values())
    vat_charged += nonres_totals.get("nonres_vat_charged", 0.0)
    vat_input_deductible += (nonres_totals.get("nonres_vat_charged", 0.0)
                             - nonres_totals.get("nonres_vat_paid", 0.0))

    tax_rate = n(x, "profit_tax_pct", 25) / 100
    margins = {month: (tax_margin_by_month.get(month, 0.0)
                       - vat_charged_by_month.get(month, 0.0)) for month in months}
    profit_tax_schedule, tax_detail = _profit_tax_schedule(
        months, margins, financing_deductions, rve, tax_rate)
    tax_rows = []
    row_by_month = {d(row["month"]): row for row in result["rows"]}
    for month, line in zip(months, tax_detail):
        margin_month = margins.get(month, 0.0)
        financing_month = financing_deductions.get(month, 0.0)
        tax_month = profit_tax_schedule.get(month, 0.0)
        if month in row_by_month:
            row_by_month[month]["taxable_margin"] = margin_month
            row_by_month[month]["financing_tax_deduction"] = financing_month
            row_by_month[month]["taxable_profit_cumulative"] = line["taxable_base"]
            row_by_month[month]["loss_carry_forward"] = line["loss_carry_forward"]
            row_by_month[month]["profit_tax"] = tax_month
        tax_rows.append({
            "month": month.isoformat(),
            "margin": margin_month,
            "financing_deduction": financing_month,
            "taxable_profit_cumulative": line["taxable_base"],
            "loss_used": line["loss_used"],
            "loss_carry_forward": line["loss_carry_forward"],
            "profit_tax": tax_month,
        })
    profit_tax = sum(profit_tax_schedule.values())


    # LLCR methodology mirrors the current workbook presentation:
    # numerator = project receipts - operating/tax - investment + PF inflow.
    # denominator = PF principal + interest/commissions, excluding duplicated transferred bridge interest.
    # LLCR — покрытие ПФ: объект вне ДДУ в нём не участвует ни выручкой, ни
    # затратами, ни НДС (его кредит — не ПФ). Налог на прибыль общий.
    llcr_numerator = (project_revenue - commercial_costs - profit_tax
                      - (vat - nonres_totals.get("nonres_vat_paid", 0.0))
                      - (total_capex - nonres_capex) + result["pf_draw_total"])

    # To reproduce Excel's correction concept, create a "reported" total where transferred bridge interest
    # appears in both bridge and PF buckets, then subtract it once.
    reported_interest_and_fees = financing_cost + result["transferred_bridge_interest"]
    # Принятый от предыдущей очереди долг входит в ЗНАМЕНАТЕЛЬ и не входит в
    # числитель (решение владельца, 27.08.2026: «долг должен появиться»).
    # Иначе очередь, которой перенесли обязательство, показала бы покрытие,
    # которого у неё нет: первая перестала быть дефолтной, а во второй долг
    # не появился — два достоверных на вид отчёта на одних вводных.
    # На своде этот же долг вычитается один раз (он не новые деньги, а часть
    # выборки предыдущей очереди) — тем же приёмом, что и перенесённые
    # проценты БРИДЖа строкой выше.
    llcr_denominator = (
        result["pf_draw_total"] + result["carried_debt_in"]
        + reported_interest_and_fees - result["transferred_bridge_interest"]
    )
    llcr = llcr_numerator / llcr_denominator if llcr_denominator else 0.0

    result.update({
        "financing_cost": financing_cost,
        "profit_tax": profit_tax,
        # Ставка едет вместе с результатом: свод очередей пересчитывает
        # налог как один налогоплательщик и обязан взять ту же ставку,
        # а не вторую копию из мастер-вводных.
        "profit_tax_rate": tax_rate,
        "vat": vat,
        "vat_charged": vat_charged,
        "vat_input_deductible": vat_input_deductible,
        "vat_schedule": {month.isoformat(): value for month, value in vat_schedule.items()},
        "profit_tax_schedule": {
            month.isoformat(): value for month, value in profit_tax_schedule.items()
        },
        "tax_rows": tax_rows,
        "tax_margin_by_product": tax_margin_by_product,
        "tax_cost_by_product": tax_cost_by_product,
        "financing_tax_deductions": sum(financing_deductions.values()),
        "financing_tax_reconciliation": financing_reconciliation,
        "profit_before_tax": profit_before_tax,
        "llcr": llcr,
        "llcr_numerator": llcr_numerator,
        "llcr_denominator": llcr_denominator,
        "reported_interest_and_fees": reported_interest_and_fees,
        "total_revenue": total_revenue,
        "total_capex": total_capex,
        "commercial_costs": commercial_costs,
        "nonres_costs": nonres_costs,
        "nonres": nonres_summary(nonres, nonres_reconciliation(
            nonres, result["rows"], tax_margin_by_product)),
        "hotel": hotel["summary"],
    })
    return result


def nonres_summary(nonres: dict[str, Any],
                   reconciliation: dict[str, Any] | None = None) -> dict[str, Any]:
    """Итог объектов вне ДДУ для отчёта; помесячно — только строки объекта для
    книги (`rows`), сырые ряды движка остаются внутри."""
    objects = []
    for key, flows in (nonres.get("objects") or {}).items():
        kpi = dict(flows["kpi"])
        for _when in ("exit_month", "loan_repaid_month", "loan_maturity"):
            if kpi.get(_when):
                kpi[_when] = kpi[_when].isoformat()
        outcome = {name: value for name, value in (flows.get("result") or {}).items()
                   if name != "monthly"}
        if outcome.get("payback_month"):
            outcome["payback_month"] = outcome["payback_month"].isoformat()
        financing = dict(flows.get("financing") or {})
        for _when in ("maturity", "horizon_end", "commissioning", "first_payment_month",
                      "balloon_month", "repaid_month"):
            if isinstance(financing.get(_when), date):
                financing[_when] = financing[_when].isoformat()
        objects.append({
            "key": key, "title": flows.get("title") or key, "strategy": flows["strategy"],
            "exit_mode": (flows.get("params") or {}).get("exit_mode"),
            "strategy_label": nonres_strategy.STRATEGY_LABELS[flows["strategy"]],
            "commissioning": flows["commissioning"].isoformat(),
            "horizon_end": flows["horizon_end"].isoformat(),
            "totals": dict(flows["totals"]), "kpi": kpi,
            "warnings": list(flows["warnings"]),
            "book": flows.get("book"),
            "result": outcome,
            "financing": financing,
            "rows": list(flows.get("rows") or []),
            "years": list(flows.get("years") or []),
        })
    out = {"objects": objects, "totals": dict(nonres.get("totals") or {})}
    if reconciliation:
        out["reconciliation"] = reconciliation
    return out


def report_layout(inputs: dict[str, Any], finance: dict[str, Any],
                  equity_cf: list[float]) -> dict[str, Any]:
    """Какие блоки отчёта у проекта есть — одно решение для всех поверхностей.

    Страница, PDF, тизер и бот читают его, а не решают сами. Нежилой проект
    без ДДУ (владелец, 04.10.2026: отчёт, тизер и книга «самостоятельные»)
    не печатает ни квартир, ни БРИДЖа, ПФ, эскроу и LLCR — их у него нет; его
    шапка — деньги объектов: кредит, капитал, NOI, DSCR, выход.
    """
    rows = finance.get("rows") or []
    project_finance = any(
        float(row.get(key) or 0.0) > 0.0
        for row in rows for key in ("bridge_draw", "pf_draw", "escrow"))
    objects = (finance.get("nonres") or {}).get("objects") or []
    tiles: list[dict[str, Any]] = []
    if objects:
        cumulative = worst = 0.0
        for value in equity_cf:
            cumulative += float(value or 0.0)
            worst = min(worst, cumulative)
        totals = [item.get("totals") or {} for item in objects]
        kpis = [item.get("kpi") or {} for item in objects]
        dscr = [k["dscr_min"] for k in kpis if k.get("dscr_min") is not None]
        noi = sum(float(k.get("stabilized_noi") or 0.0) for k in kpis)
        capex = sum(float(t.get("capex") or 0.0) for t in totals)
        exit_value = sum(float(k.get("exit_value") or 0.0) for k in kpis)
        tiles = [
            {"label": "Кредит объектов — пик", "value": sum(float(t.get("loan_peak") or 0.0) for t in totals), "unit": "rub"},
            {"label": "Собственный капитал — пик потребности", "value": -worst, "unit": "rub"},
        ]
        if noi:
            tiles += [
                {"label": "Стабилизированный NOI, год", "value": noi, "unit": "rub"},
                {"label": "Доходность на затраты", "value": noi / capex if capex else 0.0, "unit": "pct"},
            ]
        if dscr:
            tiles.append({"label": "DSCR — минимум по годам", "value": min(dscr), "unit": "mult"})
        if exit_value:
            tiles.append({"label": "Стоимость объектов на выходе", "value": exit_value, "unit": "rub"})
    # Гостиница — те же «деньги объекта» в шапке: кредит, капитал, EBITDA,
    # DSCR, выход. Плитки читают из `finance.hotel`, итога, вошедшего в поток.
    hotel = finance.get("hotel") or {}
    if hotel.get("computed"):
        kpi = hotel.get("kpi") or {}
        sale = kpi.get("exit_mode") == hotel_strategy.EXIT_SALE
        tiles += [
            {"label": "Кредит гостиницы — пик", "value": kpi.get("loan_peak"), "unit": "rub"},
            {"label": "Собственный капитал — пик потребности", "value": kpi.get("equity_peak"),
             "unit": "rub"},
            {"label": "EBITDA стабилизированного года", "value": kpi.get("stabilized_ebitda"),
             "unit": "rub"},
            {"label": "Доходность на затраты (EBITDA / CAPEX без НДС)",
             "value": kpi.get("yield_on_cost"), "unit": "pct"},
        ]
        if kpi.get("dscr_min") is not None:
            tiles.append({"label": "DSCR — минимум по годам", "value": kpi.get("dscr_min"),
                          "unit": "mult"})
        tiles.append({"label": ("Выход: продажа гостиницы" if sale
                                else "Стоимость гостиницы — оценка удержания"),
                      "value": kpi.get("exit_value"), "unit": "rub"})
    for tile in tiles:
        if tile["unit"] == "rub":
            tile["value_mln"] = float(tile["value"] or 0.0) / 1e6
    housing = not without_housing(inputs)
    # Своя вёрстка — у проекта без жилья и без ПФ, чьи объекты идут вне ДДУ
    # (владелец, 05.10.2026: «вёрстка нежилых объектов, где они не идут в
    # проекте с жильём, должна быть своей»). Жилой и смешанный — как были.
    # Гостиница — тоже объект вне ДДУ (владелец, 07.10.2026: «тизер и отчёт
    # не соответствуют типу гостиницы») — та же рамка, свой наполнитель.
    kind = (REPORT_KIND_OBJECT if not housing and not project_finance and (objects or hotel)
            else REPORT_KIND_HOUSING)
    return {"housing": housing,
            "project_finance": project_finance,
            "nonres_strategy": bool(objects),
            "hotel": bool(hotel),
            "nonres_tiles": tiles,
            "debt_metric": debt_metric(finance, project_finance, objects),
            "kind": kind,
            "sections": [{"key": key, "title": title}
                         for key, title in REPORT_SECTIONS[kind]]}


# Разделы отчёта — один список на страницу, PDF, тизер и бота. Жилой — прежний
# разбор проекта; объектный — разбор объекта вне ДДУ, утверждённый владельцем
# (05.10.2026): решение → объект → стратегия → доходы → затраты →
# финансирование → экономика собственника → чувствительность → календарь.
# Список не офисный: гостиница встаёт в ту же рамку.
REPORT_KIND_HOUSING = "housing"
REPORT_KIND_OBJECT = "object"
REPORT_SECTIONS: dict[str, tuple[tuple[str, str], ...]] = {
    REPORT_KIND_HOUSING: (
        ("site", "Участок и продукт"), ("summary", "Итог"), ("phases", "Очереди проекта"),
        ("expenses", "Расходы"), ("income", "Доходы"), ("finance", "Финансирование"),
        ("sensitivity", "Чувствительность"), ("calendar", "Календарный план"),
    ),
    REPORT_KIND_OBJECT: (
        ("decision", "Решение"), ("object", "Объект и участок"),
        ("strategy", "Стратегия реализации"), ("income", "Доходы"),
        ("costs", "Затраты"), ("finance", "Финансирование"),
        ("owner", "Экономика собственника"), ("sensitivity", "Чувствительность"),
        ("calendar", "Календарь"),
    ),
}


def _row(label: str, value: Any, unit: str, **extra: Any) -> dict[str, Any]:
    return {"label": label, "value": value, "unit": unit, **extra}


def _sum_object_costs(results: list[dict[str, Any]]) -> dict[str, dict[str, float]]:
    """Смета объектов свода — сумма очередей, а не второй расчёт."""
    out: dict[str, dict[str, float]] = {}
    for result in results:
        for key, parts in ((result or {}).get("object_costs") or {}).items():
            bucket = out.setdefault(key, {})
            for name, value in parts.items():
                bucket[name] = bucket.get(name, 0.0) + float(value or 0.0)
    return out


# Статьи общих затрат проекта в разделе «Затраты» объектной вёрстки: подпись
# и ключи CAPEX движка. Генподряд, техзаказчик и резерв идут сюда остатком —
# то, что начислено не от стройки объектов.
OBJECT_COMMON_COSTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Смена ВРИ / земельные права", ("land_rights", "vri_security")),
    ("Проценты по рассрочке ВРИ", ("vri_interest",)),
    ("ИРД, проектирование и авторский надзор",
     ("ird", "design_p", "design_rd", "author_supervision")),
    ("Снос и расселение", ("demolition", "resettlement")),
    ("Подготовка территории", ("preparation",)),
    ("Наружные инженерные сети", ("utilities",)),
    ("Благоустройство", ("landscaping",)),
    ("Сдача и ввод", ("commissioning",)),
    ("Содержание стройплощадки", ("site_maintenance",)),
    ("СМР основного здания проекта", ("main_above", "main_under")),
    ("Социальные объекты", ("social",)),
    ("Управление проектом", ("project_management",)),
)
# Части сметы объекта: ключ `object_cost_parts` → подпись.
OBJECT_COST_PARTS: tuple[tuple[str, str], ...] = (
    ("building", "Здание — СМР по ставке объекта"),
    ("garage", "Подземный гараж объекта"),
    ("gc_fee", "Вознаграждение генподрядчика — доля объекта"),
    ("technical_supervision", "Технический заказчик / стройконтроль — доля объекта"),
    ("reserve", "Резерв — доля объекта"),
)
_OBJECT_BY_KEY = {obj.key: obj for obj in STANDALONE_OBJECTS}


def _object_param_rows(obj: StandaloneObject | None, params: dict[str, Any],
                       strategy: str) -> list[dict[str, Any]]:
    """Вводные стратегии объекта — подписи, единицы и варианты из описания
    формы (`_object_strategy_fields`), а не своим списком."""
    if obj is None:
        return []
    wanted = {nonres_strategy.STRATEGY_DIRECT: "Прямая продажа",
              nonres_strategy.STRATEGY_INCOME: "Доходный метод"}.get(strategy)
    rows: list[dict[str, Any]] = []
    for field in _object_strategy_fields(obj):
        key, label, unit, kind = field[0], field[1], field[2], field[3]
        if key == f"{obj.prefix}_strategy" or standalone_object_section(obj, key) != wanted:
            continue
        value = params.get(key.removeprefix(f"{obj.prefix}_"))
        if value is None:
            continue
        if kind == "select":
            names = {str(v): str(name) for v, name in field[4]}
            rows.append(_row(label, names.get(str(value), str(value)), "text"))
        else:
            rows.append(_row(label, float(value), "num",
                             suffix=str(unit).split(";")[0].split(",")[0]))
    return rows


def _object_calendar(report: dict[str, Any], objects: list[dict[str, Any]]) -> dict[str, Any]:
    """Календарь объекта: подготовка, стройка, кредит — полосы движка; продажи,
    заполнение, аренда и выход — из рядов объекта. Жилых вех («Старт
    продаж» эскроу, «РВЭ», «Окончание продаж» квартир) у него нет."""
    keep_groups = {"Подготовка", "Финансирование", "Отдельные объекты"}
    keep_milestones = {"Сделка / начало проекта", "РнС"}
    events = [dict(e) for e in ((report.get("calendar") or {}).get("events") or [])
              if e.get("group") in keep_groups or e.get("label") in keep_milestones]
    for item in objects:
        title = item.get("title") or item.get("key")
        start = str(item.get("commissioning") or "")[:10]
        end = str(item.get("horizon_end") or "")[:10]
        if item.get("strategy") == nonres_strategy.STRATEGY_INCOME and start:
            leaseup = int(float(((item.get("book") or {}).get("params") or {})
                                .get("leaseup_months") or 0))
            if leaseup > 0:
                events.append({"label": f"Заполнение — {title}", "start": start,
                               "end": _iso(add_months(d(start), leaseup)),
                               "group": "Аренда", "kind": "bar"})
            events.append({"label": f"Аренда — {title}", "start": start, "end": end or start,
                           "group": "Аренда", "kind": "bar"})
            hold = item.get("exit_mode") == nonres_strategy.EXIT_HOLD
            if end:
                events.append({"label": (f"Конец удержания (оценка) — {title}" if hold
                                         else f"Выход: продажа — {title}"),
                               "start": end, "end": end, "group": "Выход",
                               "kind": "milestone"})
        else:
            sold = [r["month"] for r in item.get("rows") or []
                    if float(r.get("nonres_revenue") or 0) > 0]
            if sold:
                events.append({"label": f"Продажи ДКП — {title}", "start": sold[0][:10],
                               "end": sold[-1][:10], "group": "Продажи", "kind": "bar"})
    if not events:
        return {}
    return {"start": min(e["start"] for e in events), "end": max(e["end"] for e in events),
            "events": sorted(events, key=lambda e: (e["start"], e["end"]))}


def _object_sensitivity(objects: list[dict[str, Any]], deal_rub: float,
                        metric_key: str | None) -> dict[str, Any]:
    """Факторы нежилья для чувствительности: те, что двигают ЭТИ объекты."""
    keys: list[str] = []
    for item in objects:
        obj = _OBJECT_BY_KEY.get(str(item.get("key")))
        if obj is None:
            continue
        for spec in _SENSITIVITY_PARAMETERS:
            if spec.get("object") == obj.prefix and item.get("strategy") in spec["strategies"]:
                keys.append(spec["key"])
    if deal_rub > 0:
        keys.append("purchase_price_mln")
    keys.append("discount_rate_pct")
    return {"metric": "dscr" if metric_key == "dscr" else "irr_equity_pct",
            "parameters": keys}


def object_report(result: dict[str, Any]) -> dict[str, Any]:
    """Отчёт проекта без жилья — девять разделов (`REPORT_SECTIONS`) из уже
    посчитанного: `finance.nonres`, смета объектов (`object_costs`),
    `report.nonres_financing`, `report.equity_participation`, сводка и
    `report.layout.debt_metric`. Второго расчёта нет — только раскладка.

    Каждый раздел — `{key, title, brief, blocks}`: `brief` — несколько строк
    для бота и тизера, `blocks` — таблицы для страницы и PDF. Блок со ссылкой
    (`ref`) рисуется своей таблицей движка (кредит объекта, собственное
    участие, карта, чувствительность, календарь).
    """
    report = result.get("report") or {}
    layout = report.get("layout") or {}
    if layout.get("kind") != REPORT_KIND_OBJECT:
        return {}
    summary = result.get("summary") or {}
    finance = result.get("finance") or {}
    if finance.get("hotel"):
        return hotel_object_report(result)
    objects = (finance.get("nonres") or {}).get("objects") or []
    tep = {str(row.get("key")): row for row in (result.get("tep") or {}).get("rows") or []}
    capex = result.get("capex") or {}
    parts = result.get("object_costs") or {}
    deal = result.get("deal") or {}
    equity = report.get("equity_participation") or {}
    metric = layout.get("debt_metric") or {}
    na = equity_returns_na_label(summary)
    deal_rub = float(deal.get("total_mln") or 0.0) * 1e6
    income_any = any(o.get("strategy") == nonres_strategy.STRATEGY_INCOME for o in objects)
    sections: dict[str, dict[str, Any]] = {}

    # 1. Решение ------------------------------------------------------------
    verdict = _purchase_feasibility(
        deal.get("price_mln"), float(summary.get("net_profit") or 0) / 1e6,
        summary.get("llcr"), 0.0, float(summary.get("ending_pf") or 0) / 1e6,
        None, 0.0, None, _layout_dscr(layout), _layout_no_debt_cover(layout))
    debt_row = (_row(str(metric.get("label") or "DSCR"), metric.get("value"), "mult")
                if metric.get("key") else
                _row(str(metric.get("label") or "Покрытие кредита"),
                     str(metric.get("reason") or "не считается"), "text"))
    irr = summary.get("irr_equity") if na is None else None
    decision = [
        _row("Чистая прибыль проекта", summary.get("net_profit"), "rub"),
        debt_row,
        (_row("IRR собственника", irr, "pct") if irr is not None
         else _row("IRR собственника", na or "не считается — поток не меняет знак", "text")),
        (_row("NPV собственника" + (f" @{float(equity.get('discount_rate') or 0) * 100:.4g}%"
                                    .replace(".", ",") if equity else ""),
              equity.get("npv"), "rub") if equity and na is None
         else _row("NPV собственника", na or "—", "text")),
        _row("Пик собственных средств", equity.get("peak") if equity else _equity_need(result), "rub"),
        _row("Цена входа (участок, сделка)", deal_rub, "rub"),
    ]
    sections["decision"] = {
        "brief": [_row("Вывод", verdict["title"], "text"),
                  _row("Основание", verdict["text"], "text"), *decision[:4]],
        "verdict": verdict,
        "goal_seek": {"variable": "purchase_price_mln", "metric": metric.get("key"),
                      "label": metric.get("label"), "target": metric.get("target"),
                      "reason": metric.get("reason")},
        "blocks": [{"title": "Вывод", "kind": "verdict",
                    "rows": [_row(verdict["title"], verdict["text"], "text")]},
                   {"title": "Ключевые показатели", "rows": decision},
                   {"ref": "goal_seek", "title": "Максимальная цена входа по "
                    + str(metric.get("label") or "покрытию кредита")}],
    }

    # 2. Объект и участок ---------------------------------------------------
    object_blocks, gns_total, area_total = [], 0.0, 0.0
    for item in objects:
        row = tep.get(str(item.get("key"))) or {}
        book = item.get("book") or {}
        income = item.get("strategy") == nonres_strategy.STRATEGY_INCOME
        area = float(book.get("area_sqm") or 0.0)
        gns = float(row.get("gns") or 0.0)
        gns_total += gns
        area_total += area
        rows = [_row("Наземная площадь в ГНС", gns, "sqm"),
                _row("Общая площадь", row.get("total_area"), "sqm"),
                _row("Арендопригодная площадь" if income else "Продаваемая площадь", area, "sqm")]
        if float(row.get("under_gns") or 0):
            rows.append(_row("Подземный гараж — площадь", row.get("under_gns"), "sqm"))
        if float(row.get("parking_units") or 0):
            rows.append(_row("Машино-места объекта", row.get("parking_units"), "count"))
            for key, label in (("parking_under_units", "в т.ч. подземные"),
                               ("parking_over_units", "в т.ч. на первых этажах"),
                               ("parking_saleable_units",
                                "в т.ч. сдаются / продаются" if income else "в т.ч. продаются")):
                if float(row.get(key) or 0):
                    rows.append(_row(label, row.get(key), "count"))
        rows += [_row("Ввод объекта", item.get("commissioning"), "date")]
        object_blocks.append({"title": item.get("title"), "rows": rows})
    sections["object"] = {
        "brief": [_row("Наземная площадь в ГНС", gns_total, "sqm"),
                  _row("Арендопригодная / продаваемая площадь", area_total, "sqm")],
        "blocks": [*object_blocks, {"ref": "site", "title": "Участок"}],
    }

    # 3. Стратегия реализации ----------------------------------------------
    strategy_blocks, brief = [], []
    for item in objects:
        obj = _OBJECT_BY_KEY.get(str(item.get("key")))
        book = item.get("book") or {}
        income = item.get("strategy") == nonres_strategy.STRATEGY_INCOME
        rows = [_row("Стратегия", item.get("strategy_label"), "text")]
        if not income and float(book.get("price_rub_sqm") or 0):
            rows.append(_row("Стартовая цена ДКП", float(book["price_rub_sqm"]) / 1000, "th"))
        rows += _object_param_rows(obj, book.get("params") or {}, str(item.get("strategy")))
        brief.append(_row(str(item.get("title")), item.get("strategy_label"), "text"))
        years = [y for y in item.get("years") or []
                 if (y.get("occupancy") is not None if income else y.get("sale_revenue"))]
        columns = ([["year", "Год", "text"], ["occupancy", "Загрузка, средняя за год", "pct"]]
                   if income else
                   [["year", "Год", "text"], ["sale_revenue", "Выручка ДКП", "mln"],
                    ["sold_share", "Продано накопленным итогом, доля выручки", "pct"]])
        strategy_blocks.append({"title": item.get("title"), "rows": rows})
        if years:
            strategy_blocks.append({"title": ("График заполнения — " if income
                                              else "График продаж — ") + str(item.get("title")),
                                    "columns": columns, "years": years})
    sections["strategy"] = {"brief": brief, "blocks": strategy_blocks}

    # 4. Доходы ------------------------------------------------------------
    income_blocks = []
    totals = {name: sum(float((o.get("totals") or {}).get(name) or 0.0) for o in objects)
              for name in ("sale_revenue", "rent_revenue", "exit_revenue", "noi",
                           "opex", "property_tax", "selling_cost", "exit_cost", "vat_paid")}
    for item in objects:
        income = item.get("strategy") == nonres_strategy.STRATEGY_INCOME
        hold = income and item.get("exit_mode") == nonres_strategy.EXIT_HOLD
        t, kpi = item.get("totals") or {}, item.get("kpi") or {}
        if income:
            rows = [_row("Арендная выручка за срок удержания", t.get("rent_revenue"), "rub"),
                    _row("NOI за срок удержания", t.get("noi"), "rub"),
                    _row("Стабилизированный NOI, год", kpi.get("stabilized_noi"), "rub"),
                    _row("Доходность на затраты (NOI / CAPEX)", kpi.get("yield_on_cost"), "pct"),
                    _row("Стоимость объекта — оценка удержания, без сделки" if hold
                         else "Выход: продажа по ставке капитализации",
                         kpi.get("exit_value"), "rub")]
            columns = [["year", "Год", "text"], ["rent_revenue", "Аренда", "mln"],
                       ["opex", "Эксплуатация", "mln"], ["property_tax", "Налог на имущество", "mln"],
                       ["noi", "NOI", "mln"], ["exit_revenue", "Выход", "mln"]]
        else:
            rows = [_row("Выручка прямых продаж (ДКП, без эскроу)", t.get("sale_revenue"), "rub"),
                    _row("Расходы на продажу", t.get("selling_cost"), "rub")]
            columns = [["year", "Год", "text"], ["sale_revenue", "Выручка ДКП", "mln"],
                       ["property_tax", "Налог на имущество (непроданное)", "mln"]]
        years = [y for y in item.get("years") or []
                 if any(float(y.get(c[0]) or 0) for c in columns[1:])]
        income_blocks.append({"title": item.get("title"), "rows": rows})
        if years:
            income_blocks.append({"title": "По годам — " + str(item.get("title")),
                                  "columns": columns, "years": years})
    income_brief = []
    if totals["sale_revenue"]:
        income_brief.append(_row("Выручка ДКП", totals["sale_revenue"], "rub"))
    if totals["rent_revenue"]:
        income_brief += [_row("Арендная выручка", totals["rent_revenue"], "rub"),
                         _row("NOI за срок удержания", totals["noi"], "rub")]
    exit_value = sum(float((o.get("kpi") or {}).get("exit_value") or 0.0) for o in objects
                     if o.get("strategy") == nonres_strategy.STRATEGY_INCOME)
    if exit_value:
        income_brief.append(_row("Стоимость выхода", exit_value, "rub"))
    sections["income"] = {"brief": income_brief, "blocks": income_blocks}

    # 5. Затраты -----------------------------------------------------------
    cost_blocks, objects_cost = [], 0.0
    attributed: dict[str, float] = defaultdict(float)
    for item in objects:
        key = str(item.get("key"))
        own = parts.get(key) or {}
        if not own:
            continue
        row = tep.get(key) or {}
        area = float((item.get("book") or {}).get("area_sqm") or 0.0)
        gns = float(row.get("gns") or 0.0)
        total = sum(float(v or 0.0) for v in own.values())
        objects_cost += total
        for name, value in own.items():
            attributed[name] += float(value or 0.0)
        rows = [_row(label, own.get(name), "rub") for name, label in OBJECT_COST_PARTS
                if float(own.get(name) or 0.0)]
        rows += [_row("Итого смета объекта", total, "rub"),
                 _row("на м² наземной ГНС объекта", total / gns / 1000 if gns else None, "th"),
                 _row("на м² арендопригодной / продаваемой", total / area / 1000 if area else None,
                      "th")]
        cost_blocks.append({"title": "Смета объекта — " + str(item.get("title")), "rows": rows})
    common_rows = []
    if deal_rub:
        common_rows.append(_row("Участок — стоимость сделки", deal_rub, "rub"))
    for label, keys in OBJECT_COMMON_COSTS:
        value = sum(float(capex.get(k) or 0.0) for k in keys)
        if value > 0.5:
            common_rows.append(_row(label, value, "rub"))
    for name, label in (("gc_fee", "Вознаграждение генподрядчика — вне объектов"),
                        ("technical_supervision", "Технический заказчик — вне объектов"),
                        ("reserve", "Резерв — вне объектов")):
        rest = float(capex.get(name) or 0.0) - attributed.get(name, 0.0)
        if rest > 0.5:
            common_rows.append(_row(label, rest, "rub"))
    nonres_keys = {str(o.get("key")) for o in objects}
    for obj in STANDALONE_OBJECTS:
        value = float(capex.get(obj.key) or 0.0)
        if value > 0.5 and obj.key not in nonres_keys:
            common_rows.append(_row(f"Объект {obj.label} — продаётся не этим отчётом",
                                    value, "rub"))
    common_total = sum(float(r["value"] or 0.0) for r in common_rows)
    common_rows.append(_row("Итого общие затраты", common_total, "rub") if common_rows else
                       _row("Общих затрат нет", "все затраты стройки начислены от объектов",
                            "text"))
    operating = [_row("Эксплуатация (OPEX)", totals["opex"], "rub"),
                 _row("Налог на имущество", totals["property_tax"], "rub"),
                 _row("Расходы на продажу ДКП", totals["selling_cost"], "rub"),
                 _row("Затраты на выход", totals["exit_cost"], "rub")]
    operating = [r for r in operating if float(r["value"] or 0.0)]
    operating.append(_row("Итого эксплуатация, налог на имущество и продажа",
                          sum(float(r["value"]) for r in operating), "rub"))
    sections["costs"] = {
        "brief": [_row("Смета объектов", objects_cost, "rub"),
                  _row("Общие затраты", common_total, "rub"),
                  _row("Расходы всего", summary.get("total_expenses"), "rub")],
        "blocks": [*cost_blocks,
                   {"title": "Общие затраты проекта — участок, ИРД, проект, сети",
                    "rows": common_rows},
                   {"title": "Эксплуатация и налог на имущество", "rows": operating},
                   {"title": "Итог", "rows": [
                       _row("Затраты стройки — смета объектов и общие",
                            capex.get("total"), "rub"),
                       _row("Расходы проекта всего (с процентами, НДС и налогами)",
                            summary.get("total_expenses"), "rub")]}],
    }

    # 6. Финансирование ----------------------------------------------------
    loan_peak = sum(float((o.get("totals") or {}).get("loan_peak") or 0.0) for o in objects)
    sections["finance"] = {
        "brief": [_row("Кредит объектов — пик", loan_peak, "rub"), debt_row,
                  _row("Собственные средства до ввода",
                       (equity.get("parts") or {}).get("in_build"), "rub")],
        "blocks": [{"ref": "nonres_financing", "title": "Кредит объекта"},
                   {"ref": "equity_participation", "title": "Собственное участие"}],
    }

    # 7. Экономика собственника --------------------------------------------
    nonres_costs = next((float(e.get("value") or 0.0) for e in report.get("expense_structure") or []
                         if e.get("label") == (report.get("nonres_costs_label")
                                               or NONRES_COSTS_LABEL)), 0.0)
    pnl = [_row("Выручка", summary.get("revenue"), "rub")]
    if income_any:
        pnl.append(_row("NOI объектов за горизонт", totals["noi"], "rub"))
    pnl += [_row("Затраты стройки (смета объектов и общие)", summary.get("capex"), "rub"),
            _row("Эксплуатация, налог на имущество, продажа и выход", nonres_costs, "rub")]
    if float(summary.get("commercial_costs") or 0):
        pnl.append(_row("Коммерческие расходы", summary.get("commercial_costs"), "rub"))
    pnl += [_row("EBITDA", summary.get("ebitda"), "rub"),
            _row("Проценты и комиссии", summary.get("financing_cost"), "rub"),
            _row("Прибыль до налога", summary.get("profit_before_tax"), "rub"),
            _row("Налог на прибыль", summary.get("profit_tax"), "rub"),
            # НДС движок вычитает после налога на прибыль: чистая прибыль =
            # прибыль до налога − налог − НДС к уплате.
            _row("НДС к уплате", summary.get("vat"), "rub"),
            _row("Чистая прибыль", summary.get("net_profit"), "rub")]
    returns = [decision[2], decision[3]]
    if equity:
        returns.append(_row("Окупаемость собственных средств",
                            equity.get("payback_month") or "не окупается за горизонт проекта",
                            "date" if equity.get("payback_month") else "text"))
    owner_blocks = [{"title": "Отчёт о прибылях и убытках", "rows": pnl},
                    {"title": "Доходность собственника", "rows": returns}]
    if equity.get("years"):
        owner_blocks.append({"title": "Поток собственника по годам",
                             "columns": equity.get("columns") or [], "years": equity["years"]})
    for item in objects:
        hold = (item.get("strategy") == nonres_strategy.STRATEGY_INCOME
                and item.get("exit_mode") == nonres_strategy.EXIT_HOLD)
        rows = object_result_rows(item.get("result") or {}, hold=hold)
        if rows:
            owner_blocks.append({"title": "Итог объекта — " + str(item.get("title")),
                                 "rows": [r for r in rows if r.get("unit") != "section"]})
    sections["owner"] = {
        "brief": [_row("EBITDA", summary.get("ebitda"), "rub"),
                  _row("Чистая прибыль", summary.get("net_profit"), "rub"), *returns[:2]],
        "blocks": owner_blocks,
    }

    # 8. Чувствительность ---------------------------------------------------
    sensitivity = _object_sensitivity(objects, deal_rub, metric.get("key"))
    meta_labels = {spec["key"]: _sensitivity_label(spec, {})[0] for spec in _SENSITIVITY_PARAMETERS}
    sections["sensitivity"] = {
        "brief": [_row("Факторы", ", ".join(meta_labels.get(k, k) for k in sensitivity["parameters"]
                                            if k in meta_labels and _SENSITIVITY_BY_KEY[k].get("object")),
                       "text")],
        "sensitivity": sensitivity,
        "blocks": [{"ref": "sensitivity", "title": "Чувствительность по факторам объекта"}],
    }

    # 9. Календарь ----------------------------------------------------------
    calendar = _object_calendar(report, objects)
    brief = [_row(str(e["label"]), e["start"], "date") for e in calendar.get("events") or []
             if e.get("group") in ("Отдельные объекты", "Выход")][:4]
    sections["calendar"] = {"brief": brief, "calendar": calendar,
                            "blocks": [{"ref": "calendar", "title": "Календарный план объекта"}]}

    return {"kind": REPORT_KIND_OBJECT,
            "sections": [{"key": key, "title": title, **sections[key]}
                         for key, title in REPORT_SECTIONS[REPORT_KIND_OBJECT]]}


def _hotel_verdict(hotel: dict[str, Any], metric: dict[str, Any]) -> dict[str, str]:
    """Вывод по гостинице — по её собственным показателям: NPV проекта при
    ставке дисконтирования и покрытие кредита (DSCR, пороги 1,00x и 1,20x).
    Цена участка здесь не основание: у гостиницы её может не быть вовсе."""
    if not hotel.get("computed"):
        missing = ", ".join(hotel.get("missing") or []) or "вводные гостиницы"
        return {"status": "not_available", "title": "Вывод не сформирован",
                "text": f"Гостиница не считается — не заданы: {missing}."}
    kpi = hotel.get("kpi") or {}
    npv = float(kpi.get("npv_project") or 0.0)
    rate = _telegram_number(float(kpi.get("discount_rate") or 0.0) * 100, 1)
    irr = kpi.get("irr_project")
    irr_text = (f"IRR проекта {_telegram_number(float(irr) * 100, 1)}%" if irr is not None
                else "IRR проекта не считается")
    dscr = metric.get("value") if metric.get("key") == "dscr" else None
    if npv < 0:
        return {"status": "negative", "title": "Предварительно нецелесообразна",
                "text": f"NPV проекта при ставке {rate}% отрицательный: {irr_text} — ниже "
                        "ставки дисконтирования."}
    if dscr is not None and float(dscr) < DEBT_METRIC_FLOOR["dscr"]:
        return {"status": "negative", "title": "Предварительно нецелесообразна",
                "text": f"{irr_text}, но EBITDA не покрывает обслуживания кредита: DSCR "
                        f"{_telegram_number(float(dscr), 2)}x — ниже 1,00x."}
    if dscr is not None and float(dscr) < DEBT_METRIC_TARGET - 1e-9:
        return {"status": "review", "title": "Требует пересмотра условий",
                "text": f"NPV проекта при ставке {rate}% положительный ({irr_text}), но DSCR "
                        f"кредита {_telegram_number(float(dscr), 2)}x — ниже целевых 1,20x: "
                        "проверить ADR, загрузку, долю кредита, ставку и срок."}
    tail = (f", DSCR кредита — не ниже {_telegram_number(float(dscr), 2)}x" if dscr is not None
            else "")
    return {"status": "positive", "title": "Предварительно целесообразна",
            "text": f"NPV проекта при ставке {rate}% положительный, {irr_text}{tail}."}


# Строки годовых таблиц гостиничного отчёта: (ключ годовой строки, подпись,
# единица). Ключи — годового свода `developaid_hotel_strategy.annual_table`;
# составные (`departments_expense` и т. п.) складывает `_hotel_years`.
HOTEL_YEARS_RAMP = (("year", "Год", "text"), ("occupancy", "Загрузка", "pct"),
                    ("adr", "ADR, ₽ без НДС", "rub_unit"), ("revpar", "RevPAR, ₽ без НДС", "rub_unit"),
                    ("rooms_sold", "Проданные номеро-ночи", "count"))
HOTEL_YEARS_INCOME = (("year", "Год", "text"), ("rooms_revenue", "Номерной фонд", "mln"),
                      ("fnb_revenue", "F&B", "mln"), ("other_revenue", "Прочие департаменты", "mln"),
                      ("vat_relief", "Льгота НДС", "mln"), ("revenue", "Выручка всего", "mln"))
HOTEL_YEARS_COSTS = (("year", "Год", "text"),
                     ("departments_expense", "Расходы департаментов", "mln"),
                     ("undistributed", "A&G, S&M, POM, Utilities", "mln"),
                     ("gop", "GOP", "mln"),
                     ("operator_fees", "Вознаграждение оператора", "mln"),
                     ("ffe_reserve", "Резерв FF&E", "mln"),
                     ("fixed_charges", "Налог на имущество и страхование", "mln"),
                     ("ebitda", "EBITDA", "mln"))
HOTEL_YEARS_LOAN = (("year", "Год", "text"), ("loan_draw", "Выборка", "mln"),
                    ("interest", "Проценты", "mln"), ("loan_repayment", "Погашение тела", "mln"),
                    ("loan_balance", "Долг на конец года", "mln"),
                    ("debt_service", "Обслуживание долга", "mln"), ("dscr", "DSCR", "mult"))
HOTEL_YEARS_OWNER = (("year", "Год", "text"), ("ebitda", "EBITDA", "mln"),
                     ("capex", "CAPEX с НДС", "mln"), ("profit_tax", "Налог на прибыль", "mln"),
                     ("fcff", "Поток проекта до финансирования (FCFF)", "mln"),
                     ("equity_cf", "Поток капитала (FCFE)", "mln"),
                     ("equity_cumulative", "Поток капитала накопленным итогом", "mln"))


def _hotel_years(annual: list[dict[str, Any]], columns: tuple[tuple[str, str, str], ...],
                 *, operating: bool = False) -> dict[str, Any]:
    """Годовая таблица раздела из годового свода гостиницы — без второго
    расчёта: составные колонки — суммы строк того же года."""
    years, cumulative = [], 0.0
    for row in annual:
        cumulative += float(row.get("equity_cf") or 0.0)
        if operating and not row.get("rooms_available"):
            continue
        item = dict(row)
        item["departments_expense"] = sum(float(row.get(k) or 0.0)
                                          for k in ("rooms_expense", "fnb_expense", "other_expense"))
        item["undistributed"] = sum(float(row.get(k) or 0.0) for k in ("ag", "sm", "pom", "utilities"))
        item["operator_fees"] = float(row.get("base_fee") or 0.0) + float(row.get("incentive_fee") or 0.0)
        item["fixed_charges"] = float(row.get("property_tax") or 0.0) + float(row.get("insurance") or 0.0)
        item["equity_cumulative"] = cumulative
        years.append({c[0]: item.get(c[0]) for c in columns})
    return {"columns": [list(c) for c in columns], "years": years}


def _hotel_rate_text(params: dict[str, Any]) -> str:
    """Ставка кредита гостиницы словами — той формулой, что в `hotel_flows`."""
    financing = str(params.get("financing") or hotel_strategy.FINANCING_COMMERCIAL)
    num = lambda key: _telegram_number(float(params.get(key) or 0.0), 2)  # noqa: E731
    if financing == hotel_strategy.FINANCING_PREFERENTIAL:
        return f"{num('pref_key_share_pct')}% ключевой ставки + {num('pref_margin_pp')} п.п."
    if financing == hotel_strategy.FINANCING_COMMERCIAL:
        return f"ключевая ставка + {num('loan_spread_pp')} п.п."
    return "без кредита"


def hotel_object_report(result: dict[str, Any]) -> dict[str, Any]:
    """Отчёт гостиничного проекта — те же девять разделов объектной рамки
    (`REPORT_SECTIONS`), наполненные гостиницей: номера, класс, ГНС, ADR,
    загрузка и RevPAR, выручка департаментов и годовой USALI, GOP и EBITDA,
    CAPEX (здание, FF&E, на номер), кредит гостиницы, выход, NPV/IRR/PBP/DPBP
    и календарь «стройка → ввод → выход на загрузку → стабилизация → выход».

    Все числа — из `finance.hotel` (тот же расчёт, что вошёл в поток и
    прибыль проекта), сметы движка (`capex`) и сводки; второго расчёта нет.
    """
    report = result.get("report") or {}
    layout = report.get("layout") or {}
    finance = result.get("finance") or {}
    summary = result.get("summary") or {}
    hotel = finance.get("hotel") or {}
    metric = layout.get("debt_metric") or {}
    verdict = _hotel_verdict(hotel, metric)
    dates = result.get("dates") or {}
    if not hotel.get("computed"):
        missing = _row("Гостиница не считается — не заданы",
                       ", ".join(hotel.get("missing") or []) or "вводные гостиницы", "text")
        sections = {key: {"brief": [missing], "blocks": [{"title": title, "rows": [missing]}]}
                    for key, title in REPORT_SECTIONS[REPORT_KIND_OBJECT]}
        sections["decision"] = {
            "brief": [_row("Вывод", verdict["title"], "text"),
                      _row("Основание", verdict["text"], "text")],
            "verdict": verdict,
            "blocks": [{"title": "Вывод", "kind": "verdict",
                        "rows": [_row(verdict["title"], verdict["text"], "text")]}]}
        sections["sensitivity"]["sensitivity"] = {"metric": "npv_mln", "parameters": []}
        sections["calendar"]["calendar"] = {}
        return {"kind": REPORT_KIND_OBJECT, "hotel": True,
                "sections": [{"key": key, "title": title, **sections[key]}
                             for key, title in REPORT_SECTIONS[REPORT_KIND_OBJECT]]}

    kpi, totals = hotel.get("kpi") or {}, hotel.get("totals") or {}
    params = hotel.get("params") or {}
    annual = list(hotel.get("annual") or [])
    capex = result.get("capex") or {}
    tep_row = next((r for r in (result.get("tep") or {}).get("rows") or []
                    if r.get("key") == "hotel"), {})
    keys = float(kpi.get("keys") or 0.0)
    gns = float(tep_row.get("gns") or params.get("gba_sqm") or 0.0)
    stars = hotel_strategy.class_label(params.get("stars")) or "не задан"
    sale = kpi.get("exit_mode") == hotel_strategy.EXIT_SALE
    multiple = kpi.get("valuation") == hotel_strategy.VALUATION_MULTIPLE
    financing = str(params.get("financing") or hotel_strategy.FINANCING_COMMERCIAL)
    loan_on = financing != hotel_strategy.FINANCING_NONE
    rate_pct = _telegram_number(float(kpi.get("discount_rate") or 0.0) * 100, 1)
    labels = {f.key: f.label for f in hotel_strategy.FIELDS}
    choice = lambda key, pairs: dict(pairs).get(str(params.get(key) or ""), "—")  # noqa: E731
    pct_param = lambda key: float(params.get(key) or 0.0) / 100.0  # noqa: E731
    debt_row = (_row(str(metric.get("label") or "DSCR"), metric.get("value"), "mult")
                if metric.get("key") else
                _row(str(metric.get("label") or "Покрытие кредита"),
                     str(metric.get("reason") or "не считается"), "text"))
    irr_row = lambda label, value: (_row(label, value, "pct") if value is not None  # noqa: E731
                                    else _row(label, "не считается — поток не меняет знак", "text"))
    pbp_row = lambda label, value: (_row(label, value, "years") if value is not None  # noqa: E731
                                    else _row(label, "не окупается за срок расчёта", "text"))
    sections: dict[str, dict[str, Any]] = {}

    # 1. Решение ------------------------------------------------------------
    decision = [
        _row(f"NPV проекта @{rate_pct}%", kpi.get("npv_project"), "rub"),
        irr_row("IRR проекта", kpi.get("irr_project")),
        _row(f"NPV собственного капитала @{rate_pct}%", kpi.get("npv_equity"), "rub"),
        irr_row("IRR собственного капитала", kpi.get("irr_equity")),
        pbp_row("Срок окупаемости проекта (PBP), лет от начала", kpi.get("pbp_years")),
        pbp_row("Дисконтированный срок окупаемости (DPBP), лет", kpi.get("dpbp_years")),
        pbp_row("Окупаемость собственного капитала, лет", kpi.get("equity_pbp_years")),
        debt_row,
        _row("Затраты проекта (CAPEX) с НДС", kpi.get("capex"), "rub"),
        _row("Собственный капитал — пик вложений", kpi.get("equity_peak"), "rub"),
        _row("Доля собственного капитала в CAPEX", kpi.get("equity_share"), "pct"),
    ]
    sections["decision"] = {
        "brief": [_row("Вывод", verdict["title"], "text"),
                  _row("Основание", verdict["text"], "text"),
                  decision[0], decision[1], decision[3], debt_row],
        "verdict": verdict,
        "blocks": [{"title": "Вывод", "kind": "verdict",
                    "rows": [_row(verdict["title"], verdict["text"], "text")]},
                   {"title": "Ключевые показатели", "rows": decision},
                   {"title": hotel_strategy.IRR_METHOD_TITLE,
                    "rows": [_row(name, text, "text")
                             for name, text in hotel_strategy.IRR_METHOD_NOTES]}],
    }

    # 2. Объект и участок ---------------------------------------------------
    hold_years = float(params.get("hold_years") or 0.0)
    object_rows = [
        _row("Класс гостиницы", stars, "text"),
        _row("Номерной фонд", keys, "count"),
        _row("Площадь гостиницы (ГНС)", gns, "sqm"),
        _row("ГНС на номер", gns / keys if keys else None, "num", suffix="м²/номер"),
        _row("Ввод гостиницы", hotel.get("commissioning"), "date"),
        _row("Срок эксплуатации в расчёте", hold_years, "num", suffix="лет"),
        _row("Конец срока расчёта", hotel.get("horizon_end"), "date"),
    ]
    sections["object"] = {
        "brief": object_rows[:3] + [object_rows[4]],
        "blocks": [{"title": "Гостиница", "rows": object_rows}, {"ref": "site", "title": "Участок"}],
    }

    # 3. Стратегия реализации ----------------------------------------------
    exit_label = choice("exit_mode", hotel_strategy.EXITS)
    strategy_text = hotel_strategy.exit_summary(params)
    market = [
        _row("Стратегия", strategy_text, "text"),
        _row(labels["adr_rub"] + ", ₽/сутки без НДС", params.get("adr_rub"), "rub_unit"),
        _row("Дата цены ADR", params.get("adr_price_date") or hotel.get("book", {}).get("start")
             or dates.get("project_start"), "date"),
        _row(labels["index_pct"], pct_param("index_pct"), "pct"),
        _row(labels["occ_start_pct"], pct_param("occ_start_pct"), "pct"),
        _row(labels["occ_target_pct"], pct_param("occ_target_pct"), "pct"),
        _row(labels["ramp_months"], params.get("ramp_months"), "num", suffix="мес."),
        _row(labels["fnb_pct"] + ", доля выручки номеров", pct_param("fnb_pct"), "pct"),
        _row(labels["other_pct"] + ", доля номеров и F&B", pct_param("other_pct"), "pct"),
        _row(labels["vat_relief_years"], params.get("vat_relief_years"), "num", suffix="лет с ввода"),
    ]
    exit_rows = [
        _row("Конец срока", exit_label, "text"),
        _row("Оценка выхода", choice("valuation", hotel_strategy.VALUATIONS), "text"),
        (_row(labels["exit_multiple"], params.get("exit_multiple"), "num", suffix="x") if multiple
         else _row(labels["exit_cap_pct"], pct_param("exit_cap_pct"), "pct")),
        _row("EBITDA следующих 12 месяцев после срока", kpi.get("forward_ebitda"), "rub"),
        _row("Стоимость выхода — продажа" if sale else "Стоимость гостиницы — оценка удержания",
             kpi.get("exit_value"), "rub"),
    ]
    if sale:
        exit_rows.append(_row(labels["exit_cost_pct"], pct_param("exit_cost_pct"), "pct"))
    sections["strategy"] = {
        "brief": [_row("Стратегия", strategy_text, "text"), market[1], market[5], exit_rows[4]],
        "blocks": [{"title": "Номера, цена и загрузка", "rows": market},
                   {"title": "Выход на загрузку по годам",
                    **_hotel_years(annual, HOTEL_YEARS_RAMP, operating=True)},
                   {"title": "Выход", "rows": exit_rows}],
    }

    # 4. Доходы ------------------------------------------------------------
    stab_year = kpi.get("stabilized_year")
    income_rows = [
        _row("Выручка номерного фонда", totals.get("rooms_revenue"), "rub"),
        _row("Выручка F&B", totals.get("fnb_revenue"), "rub"),
        _row("Выручка прочих департаментов", totals.get("other_revenue"), "rub"),
        _row("Льгота НДС на проживание", totals.get("vat_relief"), "rub"),
        _row("Выручка за срок", totals.get("revenue"), "rub"),
    ]
    if sale:
        income_rows.append(_row("Выручка выхода (продажа)", totals.get("exit_revenue"), "rub"))
    stabilized = [
        _row("Год", str(stab_year or "—"), "text"),
        _row("Загрузка", kpi.get("stabilized_occupancy"), "pct"),
        _row("ADR, ₽ без НДС", kpi.get("stabilized_adr"), "rub_unit"),
        _row("RevPAR, ₽ без НДС", kpi.get("stabilized_revpar"), "rub_unit"),
        _row("Выручка", kpi.get("stabilized_revenue"), "rub"),
        _row("GOP", kpi.get("stabilized_gop"), "rub"),
        _row("EBITDA", kpi.get("stabilized_ebitda"), "rub"),
    ]
    sections["income"] = {
        "brief": [_row("Выручка за срок", totals.get("revenue"), "rub"),
                  _row(f"Выручка стабилизированного года ({stab_year or '—'})",
                       kpi.get("stabilized_revenue"), "rub"),
                  _row("RevPAR стабилизированного года, ₽ без НДС",
                       kpi.get("stabilized_revpar"), "rub_unit")],
        "blocks": [{"title": "Выручка по департаментам за срок", "rows": income_rows},
                   {"title": "Стабилизированный год", "rows": stabilized},
                   {"title": "Выручка по годам (USALI)",
                    **_hotel_years(annual, HOTEL_YEARS_INCOME, operating=True)}],
    }

    # 5. Затраты -----------------------------------------------------------
    capex_rows = [
        _row("Здание — ГНС × ставка стройки", capex.get("hotel"), "rub"),
        _row("Мебель и оборудование (FF&E) — номера × ставка", capex.get("hotel_ffe"), "rub"),
    ]
    deal_rub = float((result.get("deal") or {}).get("total_mln") or 0.0) * 1e6
    if deal_rub:
        capex_rows.append(_row("Участок — стоимость сделки", deal_rub, "rub"))
    for label, article_keys in OBJECT_COMMON_COSTS:
        value = sum(float(capex.get(k) or 0.0) for k in article_keys)
        if value > 0.5:
            capex_rows.append(_row(label, value, "rub"))
    for name, label in (("gc_fee", "Вознаграждение генподрядчика"),
                        ("technical_supervision", "Технический заказчик / стройконтроль"),
                        ("reserve", "Резерв")):
        if float(capex.get(name) or 0.0) > 0.5:
            capex_rows.append(_row(label, capex.get(name), "rub"))
    capex_total = float(kpi.get("capex") or 0.0)
    capex_rows += [
        _row("Итого CAPEX с НДС", capex_total, "rub"),
        _row("в т.ч. НДС (возмещается кварталом позже)", kpi.get("capex_vat"), "rub"),
        _row("CAPEX без НДС", kpi.get("capex_net"), "rub"),
        _row("CAPEX на номер с НДС", kpi.get("capex_per_key"), "rub_unit"),
        _row("CAPEX на м² ГНС с НДС", capex_total / gns / 1000 if gns else None, "th"),
    ]
    usali_rows = [_row(label, totals.get(key), "rub") for key, label in (
        ("rooms_expense", "Расходы номерного фонда"), ("fnb_expense", "Расходы F&B"),
        ("other_expense", "Расходы прочих департаментов"), ("ag", "Административные (A&G)"),
        ("sm", "Продажи и маркетинг (S&M)"), ("pom", "Эксплуатация и ремонт (POM)"),
        ("utilities", "Коммунальные (Utilities)"), ("base_fee", "Базовое вознаграждение оператора"),
        ("incentive_fee", "Поощрительное вознаграждение оператора"),
        ("ffe_reserve", "Резерв на замену FF&E"), ("property_tax", "Налог на имущество"),
        ("insurance", "Страхование имущества"))]
    operating_total = (float(totals.get("opex") or 0.0) + float(totals.get("property_tax") or 0.0)
                       + float(totals.get("insurance") or 0.0))
    usali_rows += [_row("Итого расходы эксплуатации", operating_total, "rub"),
                   _row("GOP за срок", totals.get("gop"), "rub"),
                   _row("GOP, доля выручки департаментов", kpi.get("gop_margin"), "pct"),
                   _row("EBITDA за срок", totals.get("ebitda"), "rub"),
                   _row("Рентабельность EBITDA", kpi.get("ebitda_margin"), "pct")]
    sections["costs"] = {
        "brief": [_row("CAPEX с НДС", capex_total, "rub"),
                  _row("CAPEX на номер с НДС", kpi.get("capex_per_key"), "rub_unit"),
                  _row("Расходы эксплуатации за срок", operating_total, "rub")],
        "blocks": [{"title": "CAPEX гостиницы", "rows": capex_rows},
                   {"title": "Расходы эксплуатации за срок (USALI)", "rows": usali_rows},
                   {"title": "Расходы и EBITDA по годам",
                    **_hotel_years(annual, HOTEL_YEARS_COSTS, operating=True)}],
    }

    # 6. Финансирование ----------------------------------------------------
    terms = [_row("Финансирование", choice("financing", hotel_strategy.FINANCINGS), "text")]
    if loan_on:
        limit = params.get("loan_limit_th_per_key")
        terms += [
            _row(labels["loan_share_pct"], pct_param("loan_share_pct"), "pct"),
            _row("Ставка", _hotel_rate_text(params), "text"),
            (_row(labels["loan_limit_th_per_key"], float(limit) * 1000 * keys, "rub")
             if limit not in (None, "") else _row(labels["loan_limit_th_per_key"], "без лимита", "text")),
            _row(labels["loan_fee_pct"], pct_param("loan_fee_pct"), "pct"),
            _row(labels["loan_term_years"], params.get("loan_term_years"), "num", suffix="лет"),
            _row(labels["grace_months"], params.get("grace_months"), "num", suffix="мес."),
            _row(labels["repayment"], choice("repayment", hotel_strategy.REPAYMENTS), "text"),
        ]
        if params.get("repayment") == hotel_strategy.REPAY_SCULPTED:
            terms.append(_row(labels["dscr_target"], params.get("dscr_target"), "mult"))
    loan_rows = [
        _row("Выборка кредита", totals.get("loan_draw"), "rub"),
        _row("Пик долга", kpi.get("loan_peak"), "rub"),
        _row("Проценты за срок (до ввода капитализируются)", totals.get("loan_interest"), "rub"),
        _row("Комиссия за выдачу", totals.get("loan_fee"), "rub"),
        _row("Первая выдача", kpi.get("loan_first_draw"), "date"),
        (_row("Кредит погашен", kpi.get("loan_repaid_month"), "date") if kpi.get("loan_repaid_month")
         else _row("Кредит погашен", "в конце срока — выходом или капиталом", "text")),
        debt_row,
    ]
    equity_rows = [
        _row("Собственный капитал — пик вложений", kpi.get("equity_peak"), "rub"),
        _row("Доля собственного капитала в CAPEX", kpi.get("equity_share"), "pct"),
    ]
    finance_blocks = [{"title": "Условия кредита гостиницы", "rows": terms}]
    if loan_on:
        finance_blocks += [{"title": "Выборка, долг и погашение", "rows": loan_rows},
                           {"title": "Кредит по годам", **_hotel_years(annual, HOTEL_YEARS_LOAN)}]
    finance_blocks.append({"title": "Собственный капитал", "rows": equity_rows})
    sections["finance"] = {
        "brief": [terms[0], _row("Кредит гостиницы — пик", kpi.get("loan_peak"), "rub"), debt_row,
                  equity_rows[0]],
        "blocks": finance_blocks,
    }

    # 7. Экономика собственника --------------------------------------------
    pnl = [
        _row("Выручка проекта (эксплуатация и выход)", summary.get("revenue"), "rub"),
        _row("EBITDA гостиницы за срок (USALI)", totals.get("ebitda"), "rub"),
        _row("Затраты стройки (CAPEX)", summary.get("capex"), "rub"),
        _row("Проценты и комиссии", summary.get("financing_cost"), "rub"),
        _row("Прибыль до налога", summary.get("profit_before_tax"), "rub"),
        _row("Налог на прибыль", summary.get("profit_tax"), "rub"),
        _row("НДС к уплате (минус — возмещение НДС стройки)", summary.get("vat"), "rub"),
        _row("Чистая прибыль проекта", summary.get("net_profit"), "rub"),
    ]
    returns = [decision[0], decision[1], decision[2], decision[3], decision[4], decision[5],
               decision[6]]
    sections["owner"] = {
        "brief": [_row("EBITDA гостиницы за срок", totals.get("ebitda"), "rub"),
                  _row("Чистая прибыль проекта", summary.get("net_profit"), "rub"),
                  decision[2], decision[3]],
        "blocks": [{"title": "Прибыль проекта за срок", "rows": pnl},
                   {"title": "Доходность", "rows": returns},
                   {"title": "Потоки по годам", **_hotel_years(annual, HOTEL_YEARS_OWNER)}],
    }

    # 8. Чувствительность ---------------------------------------------------
    parameters = [f"hotel_{key}" for key in _HOTEL_SENSITIVITY_GROUPS
                  if hotel_strategy._is_needed(hotel_strategy.FIELD_BY_KEY[key], params)
                  and float(params.get(key) or 0.0)]
    if deal_rub > 0:
        parameters.append("purchase_price_mln")
    parameters.append("discount_rate_pct")
    sensitivity = {"metric": "npv_mln", "parameters": parameters}
    sections["sensitivity"] = {
        "brief": [_row("Факторы", ", ".join(labels[key] for key in _HOTEL_SENSITIVITY_GROUPS
                                             if f"hotel_{key}" in parameters), "text")],
        "sensitivity": sensitivity,
        "blocks": [{"ref": "sensitivity", "title": "Чувствительность по факторам гостиницы"}],
    }

    # 9. Календарь ----------------------------------------------------------
    calendar = _hotel_calendar(report, hotel, dates)
    sections["calendar"] = {
        "brief": [_row(label, value, "date") for label, value in calendar.get("dates") or []
                  if label != "Начало проекта"],
        "calendar": calendar,
        "blocks": [{"ref": "calendar", "title": "Календарный план гостиницы"}],
    }

    return {"kind": REPORT_KIND_OBJECT, "hotel": True,
            "sections": [{"key": key, "title": title, **sections[key]}
                         for key, title in REPORT_SECTIONS[REPORT_KIND_OBJECT]]}


def _hotel_calendar(report: dict[str, Any], hotel: dict[str, Any],
                    dates: dict[str, Any]) -> dict[str, Any]:
    """Календарь гостиницы: подготовка (полосы движка) → стройка → ввод →
    выход на загрузку → стабилизация → кредит → выход. Жилых вех (эскроу,
    продажи квартир, БРИДЖ — банк ПФ гостиницу не кредитует) в нём нет."""
    kpi = hotel.get("kpi") or {}
    params = hotel.get("params") or {}
    events = [dict(e) for e in ((report.get("calendar") or {}).get("events") or [])
              if e.get("group") == "Подготовка"
              or e.get("label") in ("Сделка / начало проекта", "РнС")]
    opening = str(hotel.get("commissioning") or "")[:10]
    end = str(hotel.get("horizon_end") or "")[:10]
    permit = str(dates.get("permit") or "")[:10]
    if not opening:
        return {}
    if permit and permit < opening:
        events.append({"label": "Строительство гостиницы", "start": permit, "end": opening,
                       "group": "Строительство", "kind": "bar"})
    events.append({"label": "Ввод гостиницы", "start": opening, "end": opening,
                   "group": "Ключевые вехи", "kind": "milestone"})
    ramp = int(float(params.get("ramp_months") or 0))
    ramp_end = _iso(add_months(d(opening), ramp)) if ramp > 0 else opening
    if ramp > 0:
        events.append({"label": "Выход на целевую загрузку", "start": opening, "end": ramp_end,
                       "group": "Эксплуатация", "kind": "bar"})
    stab_year = kpi.get("stabilized_year")
    if stab_year:
        events.append({"label": f"Стабилизированный год ({stab_year})",
                       "start": f"{int(stab_year)}-01-01", "end": f"{int(stab_year)}-12-01",
                       "group": "Эксплуатация", "kind": "bar"})
    if end:
        events.append({"label": "Эксплуатация", "start": opening, "end": end,
                       "group": "Эксплуатация", "kind": "bar"})
    first_draw = str(kpi.get("loan_first_draw") or "")[:10]
    repaid = str(kpi.get("loan_repaid_month") or "")[:10] or end
    if first_draw and repaid:
        events.append({"label": "Кредит гостиницы", "start": first_draw, "end": repaid,
                       "group": "Финансирование", "kind": "bar"})
    sale = kpi.get("exit_mode") == hotel_strategy.EXIT_SALE
    if end:
        events.append({"label": "Выход: продажа гостиницы" if sale
                       else "Конец срока: оценка удержания",
                       "start": end, "end": end, "group": "Выход", "kind": "milestone"})
    key_dates = [("Начало проекта", str(dates.get("project_start") or "")[:10]),
                 ("РнС", permit), ("Ввод гостиницы", opening),
                 ("Выход на целевую загрузку", ramp_end),
                 ("Выход: продажа" if sale else "Конец срока (оценка)", end)]
    return {"start": min(e["start"] for e in events), "end": max(e["end"] for e in events),
            "events": sorted(events, key=lambda e: (e["start"], e["end"])),
            "dates": [(label, value) for label, value in key_dates if value]}


def _finalize_result(result: dict[str, Any] | None) -> dict[str, Any] | None:
    """Выход расчёта: решение о доходности капитала, затем объектный отчёт —
    он читает уже решённые IRR и NPV. Краткие строки разделов ложатся в
    `report.layout.sections`: их читают бот и тизер."""
    _apply_equity_returns_to_result(result)
    if not isinstance(result, dict):
        return result
    report = result.get("report")
    if not isinstance(report, dict) or "object_report" in report:
        return result
    built = object_report(result)
    report["object_report"] = built
    layout = report.get("layout")
    if built and isinstance(layout, dict):
        layout["sections"] = [{"key": s["key"], "title": s["title"], "brief": s["brief"]}
                              for s in built["sections"]]
    return result

# Пороги покрытия долга: ориентир банка и нижняя граница «на грани». У LLCR
# проекта с ПФ — прежние пороги карточки решения; у DSCR кредита объекта — те
# же, что у вердикта (`_purchase_feasibility_base`): ниже 1,00x NOI не
# покрывает платежа.
DEBT_METRIC_TARGET = 1.20
DEBT_METRIC_FLOOR = {"llcr": 1.05, "dscr": 1.00}


def debt_metric(finance: dict[str, Any], project_finance: bool,
                objects: list[dict[str, Any]]) -> dict[str, Any]:
    """Чем мерить долг проекта — одно решение для карточки решения, подбора
    цены входа, PDF и бота.

    Проект с БРИДЖем и ПФ меряет LLCR. Проект без них — DSCR кредита объектов
    (минимум по годам и объектам): LLCR там считать не из чего, и −8,68x на
    экране было не ответом, а делением нуля ПФ. Кредит, который гасится
    выручкой ДКП, покрытия NOI не имеет — тогда показателя нет, и сказано
    почему, а не печатается ноль.
    """
    hotel = finance.get("hotel")
    if isinstance(hotel, dict) and not project_finance:
        # Гостиничный проект меряет свой кредит: DSCR = EBITDA ÷ обслуживание
        # по годам (`developaid_hotel_strategy`), тот же минимум, что в плитке.
        kpi = hotel.get("kpi") or {}
        if hotel.get("computed") and kpi.get("dscr_min") is not None:
            return {"key": "dscr", "label": "DSCR кредита гостиницы — минимум по годам",
                    "value": float(kpi["dscr_min"]), "target": DEBT_METRIC_TARGET,
                    "floor": DEBT_METRIC_FLOOR["dscr"]}
        if not hotel.get("computed"):
            reason = "Гостиница не считается — не заданы её вводные, DSCR нет."
        elif float(kpi.get("loan_peak") or 0.0) <= 0.0:
            reason = "У гостиницы нет кредита — покрывать нечего, DSCR не считается."
        else:
            reason = ("Кредит гостиницы не обслуживается из EBITDA ни в одном году "
                      "эксплуатации — DSCR не считается.")
        return {"key": None, "label": "Покрытие кредита гостиницы", "value": None,
                "target": DEBT_METRIC_TARGET, "floor": None, "reason": reason}
    if project_finance or not objects:
        return {"key": "llcr", "label": "LLCR", "value": finance.get("llcr"),
                "target": DEBT_METRIC_TARGET, "floor": DEBT_METRIC_FLOOR["llcr"]}
    values = [float(k["dscr_min"]) for k in ((o.get("kpi") or {}) for o in objects)
              if k.get("dscr_min") is not None]
    if values:
        return {"key": "dscr", "label": "DSCR кредита объектов — минимум по годам",
                "value": min(values), "target": DEBT_METRIC_TARGET,
                "floor": DEBT_METRIC_FLOOR["dscr"]}
    return {"key": None, "label": "Покрытие кредита объектов", "value": None,
            "target": DEBT_METRIC_TARGET, "floor": None,
            "reason": "Кредит объектов гасится выручкой прямых продаж — платежа из NOI "
                      "нет, DSCR не считается. Проверка — что кредит погашен: "
                      "см. «Финансирование объекта»."}


def nonres_report(nonres: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Таблица «Нежильё — стратегия реализации»: одна на страницу, PDF и бот.

    Строки собираются из `finance.nonres` — того же итога, что вошёл в
    прибыль и поток. Строка, которой у стратегии нет, не печатается нулём:
    у прямой продажи нет NOI, у аренды — выручки ДКП.
    """
    out: list[dict[str, Any]] = []
    reconciliation = (nonres or {}).get("reconciliation") or {}
    for item in (nonres or {}).get("objects") or []:
        totals, kpi = item.get("totals") or {}, item.get("kpi") or {}
        income = item.get("strategy") == nonres_strategy.STRATEGY_INCOME
        hold = income and item.get("exit_mode") == nonres_strategy.EXIT_HOLD
        rows: list[dict[str, Any]] = [
            {"label": "Стратегия", "value": item.get("strategy_label"), "unit": "text"},
            {"label": "Ввод объекта", "value": item.get("commissioning"), "unit": "date"},
            {"label": "Конец горизонта объекта", "value": item.get("horizon_end"), "unit": "date"},
            {"label": "Затраты стройки объекта", "value": totals.get("capex"), "unit": "rub"},
        ]
        if not income:
            rows.append({"label": "Выручка прямых продаж (ДКП, без эскроу)",
                         "value": totals.get("sale_revenue"), "unit": "rub"})
        else:
            rows += [
                {"label": "Арендная выручка за срок удержания",
                 "value": totals.get("rent_revenue"), "unit": "rub"},
                {"label": "NOI за срок удержания", "value": totals.get("noi"), "unit": "rub"},
                {"label": "Стабилизированный NOI, год", "value": kpi.get("stabilized_noi"),
                 "unit": "rub"},
                {"label": "Доходность на затраты (NOI / CAPEX)",
                 "value": kpi.get("yield_on_cost"), "unit": "pct"},
                {"label": ("Стоимость объекта — оценка удержания, без сделки" if hold
                           else "Выход: продажа по ставке капитализации"),
                 "value": kpi.get("exit_value"), "unit": "rub"},
            ]
        # Кредит объекта — в своём отчёте «Финансирование объекта»
        # (`nonres_financing_report`), здесь его не дублируем.
        rows.append({"label": "НДС объекта к уплате", "value": totals.get("vat_paid"), "unit": "rub"})
        rows += object_result_rows(item.get("result") or {}, hold=hold)
        warnings = list(item.get("warnings") or [])
        if reconciliation and not reconciliation.get("ok"):
            warnings.append(
                "Итог объекта не сходится с вкладом нежилья в проект: поток капитала "
                f"объектов {reconciliation.get('objects_equity', 0) / 1e6:,.1f} млн ₽ "
                f"против {reconciliation.get('project_equity', 0) / 1e6:,.1f} млн ₽ в проекте, "
                f"база налога {reconciliation.get('objects_tax_base', 0) / 1e6:,.1f} "
                f"против {reconciliation.get('project_tax_base', 0) / 1e6:,.1f} млн ₽ "
                "(сверка `nonres_reconciliation`).".replace(",", " "))
        out.append({"key": item.get("key"), "title": item.get("title"),
                    "strategy": item.get("strategy"), "rows": rows,
                    "warnings": warnings})
    return out


# Годовой USALI отчёта: строки в порядке USALI, деньги — в рублях.
HOTEL_REPORT_USALI_ROWS: tuple[tuple[str, str, str], ...] = (
    ("occupancy", "Загрузка", "pct"),
    ("adr", "ADR, ₽ без НДС", "rub_unit"),
    ("revpar", "RevPAR, ₽ без НДС", "rub_unit"),
    ("rooms_revenue", "Выручка номерного фонда", "rub"),
    ("fnb_revenue", "Выручка F&B", "rub"),
    ("other_revenue", "Выручка прочих департаментов", "rub"),
    ("vat_relief", "Льгота НДС на проживание", "rub"),
    ("revenue", "Выручка всего", "rub"),
    ("gop", "GOP", "rub"),
    ("ebitda", "EBITDA", "rub"),
    ("profit_tax", "Налог на прибыль", "rub"),
    ("debt_service", "Обслуживание долга", "rub"),
    ("dscr", "DSCR", "mult"),
    ("fcff", "Поток до финансирования (FCFF)", "rub"),
    ("equity_cf", "Поток капитала (FCFE)", "rub"),
)


def hotel_report(hotel: dict[str, Any] | None) -> dict[str, Any] | None:
    """Блок «Гостиница — эксплуатация»: одна таблица на страницу, PDF и бот.

    Строки собираются из `finance.hotel` — того же итога, что вошёл в
    прибыль, налог и поток проекта. Незаполненная гостиница не печатается
    нулями: блок называет, каких вводных нет.
    """
    if not hotel:
        return None
    if not hotel.get("computed"):
        return {"computed": False, "missing": list(hotel.get("missing") or []),
                "rows": [], "usali": {"years": [], "rows": []}, "warnings": []}
    kpi, totals = hotel.get("kpi") or {}, hotel.get("totals") or {}
    params = hotel.get("params") or {}
    stars = hotel_strategy.class_label(params.get("stars")) or "не задан"
    sale = kpi.get("exit_mode") == hotel_strategy.EXIT_SALE
    valuation = dict(hotel_strategy.VALUATIONS).get(str(kpi.get("valuation") or ""), "")
    financing = dict(hotel_strategy.FINANCINGS).get(str(params.get("financing") or ""), "")
    rows: list[dict[str, Any]] = [
        {"label": "Класс", "value": stars, "unit": "text"},
        {"label": "Номерной фонд", "value": kpi.get("keys"), "unit": "count"},
        {"label": "Ввод гостиницы", "value": hotel.get("commissioning"), "unit": "date"},
        {"label": "Конец срока расчёта", "value": hotel.get("horizon_end"), "unit": "date"},
        {"label": "Затраты проекта с НДС", "value": kpi.get("capex"), "unit": "rub"},
        {"label": "Затраты на номер с НДС", "value": kpi.get("capex_per_key"), "unit": "rub_unit"},
        {"label": "ADR первого года, без НДС", "value": kpi.get("adr_first_year"), "unit": "rub_unit"},
        {"label": f"Стабилизированный год ({kpi.get('stabilized_year') or '—'}): загрузка",
         "value": kpi.get("stabilized_occupancy"), "unit": "pct"},
        {"label": "RevPAR стабилизированного года, без НДС",
         "value": kpi.get("stabilized_revpar"), "unit": "rub_unit"},
        {"label": "Выручка за срок", "value": totals.get("revenue"), "unit": "rub"},
        {"label": "в т.ч. льгота НДС на проживание", "value": totals.get("vat_relief"), "unit": "rub"},
        {"label": "GOP за срок (доля выручки департаментов)", "value": kpi.get("gop_margin"),
         "unit": "pct"},
        {"label": "EBITDA за срок", "value": totals.get("ebitda"), "unit": "rub"},
        {"label": "Рентабельность EBITDA", "value": kpi.get("ebitda_margin"), "unit": "pct"},
        {"label": "Доходность на затраты (EBITDA стаб. года / CAPEX без НДС)",
         "value": kpi.get("yield_on_cost"), "unit": "pct"},
        {"label": ("Выход: продажа — " if sale else "Оценка удержания — ") + valuation.split(":")[0].lower(),
         "value": kpi.get("exit_value"), "unit": "rub"},
        {"label": "Финансирование", "value": financing, "unit": "text"},
        {"label": "Кредит — выборка", "value": totals.get("loan_draw"), "unit": "rub"},
        {"label": "Кредит — пик долга", "value": kpi.get("loan_peak"), "unit": "rub"},
        {"label": "Кредит — проценты и комиссии",
         "value": float(totals.get("loan_interest") or 0) + float(totals.get("loan_fee") or 0),
         "unit": "rub"},
        {"label": "Кредит погашен", "value": kpi.get("loan_repaid_month"), "unit": "date"},
        {"label": "DSCR — минимум по годам", "value": kpi.get("dscr_min"), "unit": "mult"},
        {"label": "Налог на прибыль за срок", "value": totals.get("profit_tax"), "unit": "rub"},
        {"label": "NPV проекта", "value": kpi.get("npv_project"), "unit": "rub"},
        {"label": "IRR проекта", "value": kpi.get("irr_project"), "unit": "pct"},
        {"label": "NPV собственного капитала", "value": kpi.get("npv_equity"), "unit": "rub"},
        {"label": "IRR собственного капитала", "value": kpi.get("irr_equity"), "unit": "pct"},
        {"label": "Срок окупаемости (PBP), лет от начала проекта", "value": kpi.get("pbp_years"),
         "unit": "years"},
        {"label": "Дисконтированный срок окупаемости (DPBP), лет",
         "value": kpi.get("dpbp_years"), "unit": "years"},
    ]
    annual = [row for row in hotel.get("annual") or [] if row.get("rooms_available")]
    usali = {
        "years": [row["year"] for row in annual],
        "rows": [{"key": key, "label": label, "unit": unit,
                  "values": [row.get(key) for row in annual]}
                 for key, label, unit in HOTEL_REPORT_USALI_ROWS],
    }
    return {"computed": True, "missing": [], "rows": rows, "usali": usali,
            "warnings": list(hotel.get("warnings") or [])}


def _month_label(value: Any) -> str:
    return ".".join(reversed(str(value)[:7].split("-"))) if value else "—"


def nonres_financing_report(nonres: dict[str, Any] | None) -> list[dict[str, Any]]:
    """«Финансирование объекта»: кредит каждого объекта вне ДДУ блоками.

    Одна таблица на страницу, PDF, книгу и тизер; читает `object_financing`
    из `finance.nonres`. Блоки: условия, выборка и долг на ввод, погашение
    (платёж, тело, баллон, выход), обслуживание; плюс таблица по годам.
    Строка, которой у схемы нет, не печатается: у прямой продажи нет
    аннуитета и баллона, у погашения из NOI — срока и баллона.
    """
    out: list[dict[str, Any]] = []
    for item in (nonres or {}).get("objects") or []:
        f = item.get("financing") or {}
        if not f:
            continue
        annuity = f.get("scheme") == nonres_strategy.REPAY_ANNUITY
        rows: list[dict[str, Any]] = [
            {"label": "Условия кредита", "value": None, "unit": "section"},
            {"label": "Схема погашения", "value": f.get("scheme_label"), "unit": "text"},
            {"label": "Доля кредита в затратах", "value": f.get("loan_share"), "unit": "pct"},
            {"label": "Ставка", "value": "ключевая + " + f"{float(f.get('spread') or 0) * 100:.4g}".replace(".", ",") + " п.п.",
             "unit": "text"},
            {"label": "Ставка на вводе", "value": f.get("rate_at_commissioning"), "unit": "pct"},
            {"label": "Средняя ставка за срок (по остатку долга)", "value": f.get("avg_rate"), "unit": "pct"},
        ]
        if annuity:
            maturity_after_exit = (f.get("maturity") and f.get("horizon_end")
                                   and str(f["maturity"]) > str(f["horizon_end"]))
            rows += [
                {"label": "Срок кредита",
                 "value": f"{f.get('term_years')} лет от первой выдачи — до {_month_label(f.get('maturity'))}"
                          + (" (позже выхода: остаток гасится при выходе)" if maturity_after_exit else ""),
                 "unit": "text"},
                {"label": "Баллон в конце срока", "value": f.get("balloon_share"), "unit": "pct"},
            ]
        rows += [
            {"label": "Выборка и долг на ввод", "value": None, "unit": "section"},
            {"label": "Выборка кредита", "value": f.get("draw_total"), "unit": "rub"},
        ]
        if f.get("draw_common"):
            rows += [
                {"label": "в т.ч. на стройку объекта", "value": f.get("draw_object"), "unit": "rub"},
                {"label": "в т.ч. на общие затраты проекта", "value": f.get("draw_common"), "unit": "rub"},
            ]
        if f.get("limit_land") and f.get("limit_build"):
            rows += [
                {"label": "Лимит НКЛ на участок и проект (до РнС)", "value": f.get("limit_land"),
                 "unit": "rub"},
                {"label": "Лимит строительной НКЛ (с РнС)", "value": f.get("limit_build"), "unit": "rub"},
            ]
        if f.get("reservation_fee"):
            rows.append({"label": "Плата за резервирование лимита НКЛ", "value": f.get("reservation_fee"),
                         "unit": "rub"})
        if f.get("commitment_fee"):
            rows.append({"label": "Плата за невыбранный лимит НКЛ", "value": f.get("commitment_fee"),
                         "unit": "rub"})
        rows += [
            {"label": "Комиссия за выдачу", "value": f.get("fee"), "unit": "rub"},
            {"label": "Проценты до ввода — капитализированы в долг",
             "value": f.get("interest_capitalized"), "unit": "rub"},
            {"label": f"Долг на ввод ({_month_label(f.get('commissioning'))})",
             "value": f.get("debt_at_commissioning"), "unit": "rub"},
            {"label": "Пик долга", "value": f.get("peak"), "unit": "rub"},
            {"label": "Погашение", "value": None, "unit": "section"},
        ]
        if annuity and f.get("first_payment"):
            rows += [
                {"label": f"Аннуитетный платёж — первый ({_month_label(f.get('first_payment_month'))}), в месяц",
                 "value": f.get("first_payment"), "unit": "mln"},
                {"label": "Аннуитетный платёж — средний, в месяц", "value": f.get("avg_payment"), "unit": "mln"},
                {"label": "Погашено плановым телом аннуитета", "value": f.get("repaid_scheduled"), "unit": "rub"},
                {"label": "Баллон по графику (доля долга на ввод)", "value": f.get("balloon_planned"), "unit": "rub"},
            ]
            if f.get("balloon_paid"):
                rows.append({"label": f"Баллон погашен в срок ({_month_label(f.get('balloon_month'))})",
                             "value": f.get("balloon_paid"), "unit": "rub"})
        if f.get("repaid_from_cash"):
            rows.append({"label": ("Погашено из выручки ДКП" if f.get("scheme") == "sale"
                                   else "Погашено из NOI по мере поступления"),
                         "value": f.get("repaid_from_cash"), "unit": "rub"})
        if f.get("repaid_at_exit"):
            rows.append({"label": f"Остаток долга погашен при выходе ({_month_label(f.get('horizon_end'))})",
                         "value": f.get("repaid_at_exit"), "unit": "rub"})
        rows += [
            {"label": "Погашено всего", "value": f.get("repaid_total"), "unit": "rub"},
            {"label": "Кредит погашен полностью", "value": _month_label(f.get("repaid_month")), "unit": "text"},
            {"label": "Обслуживание", "value": None, "unit": "section"},
            {"label": "Проценты после ввода — уплачены", "value": f.get("interest_paid"), "unit": "rub"},
            {"label": "Проценты и комиссии — всего",
             "value": float(f.get("interest_capitalized") or 0) + float(f.get("interest_paid") or 0)
                      + float(f.get("fee") or 0) + float(f.get("reservation_fee") or 0)
                      + float(f.get("commitment_fee") or 0), "unit": "rub"},
        ]
        if f.get("dscr_min") is not None:
            rows += [
                {"label": "DSCR — минимум по годам (NOI / проценты и тело)",
                 "value": f.get("dscr_min"), "unit": "mult"},
                {"label": "Покрытие процентов NOI (ICR) — минимум", "value": f.get("icr_min"), "unit": "mult"},
            ]
        years = list(f.get("years") or [])
        # Колонка без единого значения (NOI и DSCR у прямой продажи) не рисуется.
        columns = [list(c) for c in NONRES_FINANCING_YEAR_COLUMNS
                   if any(y.get(c[0]) is not None for y in years)]
        out.append({"key": item.get("key"), "title": item.get("title"),
                    "strategy": item.get("strategy"), "rows": rows,
                    "years": years, "columns": columns})
    return out


EQUITY_YEAR_COLUMNS: tuple[tuple[str, str, str], ...] = (
    ("year", "Год", "text"),
    ("contributed", "Вложено собственником", "mln"),
    ("returned", "Получено собственником", "mln"),
    ("net", "Чистый поток", "mln"),
    ("cumulative", "Накопленный на конец года", "mln"),
)


def equity_participation_report(months: list[date], equity_cf: list[float],
                                finance: dict[str, Any], *, discount_rate: float,
                                irr: float | None) -> dict[str, Any]:
    """«Собственное участие» проекта без ПФ: сколько, когда и на что вложил
    собственник, сколько и когда получил обратно, и чем это кончилось.

    Читает поток собственного капитала проекта (`cashflow.equity`) — тот же
    ряд, по которому считан IRR проекта, — и строки финансирования для
    раскладки по причинам. Второго расчёта нет: сумма частей равна потоку.

    Вложения: до ввода объектов — доля стройки и общих затрат сверх кредита;
    после ввода — то, чего NOI не хватило на платежи, налоги и расходы; при
    выходе — довнесение на погашение остатка долга. Возврат: возмещение НДС
    стройки, деньги по ходу (продажи ДКП, аренда после обслуживания долга),
    выход. Оценка удержанного объекта — не деньги: она названа отдельно, а
    денежный итог показан без неё.
    """
    objects = (finance.get("nonres") or {}).get("objects") or []
    if not objects or not months or not equity_cf:
        return {}
    # В проекте с ПФ поток капитала несёт и жильё, и раскладка «до ввода
    # объектов / после» была бы неправдой; там собственное участие — в
    # банковских блоках. Признак тот же, что у `report_layout`.
    if any(float(r.get(k) or 0.0) > 0.0 for r in finance.get("rows") or []
           for k in ("bridge_draw", "pf_draw", "escrow")):
        return {}
    rows = {str(r.get("month"))[:10]: r for r in finance.get("rows") or []}
    commissioning = max(str(o.get("commissioning")) for o in objects)
    # Выход — у доходного метода (продажа или конец удержания); у прямой
    # продажи конец горизонта — просто последний месяц продаж.
    exits = {str(o.get("horizon_end"))[:10] for o in objects
             if o.get("strategy") == nonres_strategy.STRATEGY_INCOME}

    def row(month: date) -> dict[str, Any]:
        return rows.get(month.isoformat()) or {}

    parts = {"in_build": 0.0, "in_operation": 0.0, "in_exit": 0.0,
             "out_vat": 0.0, "out_running": 0.0, "out_exit": 0.0}
    residual_total = 0.0
    cash_only: list[float] = []
    years: dict[int, dict[str, float]] = {}
    for month, flow in zip(months, equity_cf):
        key = month.isoformat()
        residual = float(row(month).get("nonres_residual_value") or 0.0)
        residual_total += residual
        cash = float(flow or 0.0) - residual
        cash_only.append(cash)
        year = years.setdefault(month.year, {"contributed": 0.0, "returned": 0.0})
        if cash < 0:
            year["contributed"] += -cash
            if key <= commissioning:
                parts["in_build"] += -cash
            elif key in exits:
                parts["in_exit"] += -cash
            else:
                parts["in_operation"] += -cash
        elif cash > 0:
            year["returned"] += cash
            refund = min(cash, max(0.0, -float(row(month).get("nonres_vat_paid") or 0.0)))
            parts["out_vat"] += refund
            if key in exits:
                parts["out_exit"] += cash - refund
            else:
                parts["out_running"] += cash - refund
    contributed = parts["in_build"] + parts["in_operation"] + parts["in_exit"]
    returned = parts["out_vat"] + parts["out_running"] + parts["out_exit"]
    cumulative = worst = 0.0
    worst_month: date | None = None
    last_negative: int | None = None
    for index, (month, cash) in enumerate(zip(months, cash_only)):
        cumulative += cash
        if cumulative < worst:
            worst, worst_month = cumulative, month
        if cumulative < -0.5:
            last_negative = index
    payback = (months[last_negative + 1] if last_negative is not None
               and last_negative + 1 < len(months) else None)
    capex = float(finance.get("total_capex") or 0.0)
    draw = float(sum(float(r.get("nonres_loan_draw") or 0.0) for r in finance.get("rows") or []))
    hold = residual_total > 0
    running = 0.0
    year_rows = []
    for year in sorted(years):
        net = years[year]["returned"] - years[year]["contributed"]
        running += net
        year_rows.append({"year": year, "contributed": years[year]["contributed"],
                          "returned": years[year]["returned"], "net": net, "cumulative": running})

    def money(label: str, value: float, unit: str = "rub") -> dict[str, Any]:
        return {"label": label, "value": value, "unit": unit}

    rate_label = f"{discount_rate * 100:.4g}".replace(".", ",")
    out_rows: list[dict[str, Any]] = [
        {"label": "Источники финансирования стройки", "value": None, "unit": "section"},
        money("Затраты проекта (CAPEX, с НДС)", capex),
        money("Кредит объектов — выборка", draw),
        money("Собственные средства до ввода", parts["in_build"]),
        {"label": "Доля собственных средств в затратах",
         "value": parts["in_build"] / capex if capex else None, "unit": "pct"},
        {"label": "Вложения собственника", "value": None, "unit": "section"},
        money("Вложено всего", contributed),
        money("в т.ч. до ввода — стройка и общие затраты сверх кредита", parts["in_build"]),
    ]
    if parts["in_operation"]:
        out_rows.append(money("в т.ч. после ввода — дефицит: NOI и продаж не хватило на платежи "
                              "по кредиту, налоги и расходы", parts["in_operation"]))
    if parts["in_exit"]:
        out_rows.append(money("в т.ч. при выходе — довнесение на погашение долга", parts["in_exit"]))
    out_rows += [
        money("Пик потребности в собственных средствах"
              + (f" ({_month_label(worst_month.isoformat())})" if worst_month else ""), -worst),
        {"label": "Возврат собственнику", "value": None, "unit": "section"},
        money("Получено всего" + (" — деньгами, без оценки" if hold else ""), returned),
    ]
    if parts["out_vat"]:
        out_rows.append(money("в т.ч. возмещение НДС стройки", parts["out_vat"]))
    if parts["out_running"]:
        out_rows.append(money("в т.ч. по ходу — продажи ДКП, аренда после обслуживания долга и налогов",
                              parts["out_running"]))
    if parts["out_exit"]:
        out_rows.append(money("в т.ч. при выходе — после погашения долга", parts["out_exit"]))
    if hold:
        out_rows.append(money("Оценка удержанного объекта — без сделки, не деньги", residual_total))
    out_rows += [
        {"label": "Результат собственника", "value": None, "unit": "section"},
        money("Чистый денежный результат (получено − вложено)" + (", без оценки" if hold else ""),
              returned - contributed),
        {"label": "Мультипликатор капитала (получено / вложено)" + (", без оценки" if hold else ""),
         "value": returned / contributed if contributed else None, "unit": "mult"},
    ]
    if irr is not None:
        out_rows.append({"label": "IRR собственного капитала" + (" — с оценкой" if hold else ""),
                         "value": irr, "unit": "pct"})
    else:
        out_rows.append({"label": "IRR собственного капитала",
                         "value": "не считается — поток не меняет знак", "unit": "text"})
    if hold:
        cash_irr = _monthly_irr(cash_only)
        out_rows.append({"label": "IRR собственного капитала — только деньги",
                         "value": cash_irr if cash_irr is not None
                         else "не считается — деньги не возвращают вложенное",
                         "unit": "pct" if cash_irr is not None else "text"})
    npv = _monthly_npv(list(equity_cf), discount_rate)
    out_rows += [
        money(f"NPV собственного капитала @{rate_label}%" + (" — с оценкой" if hold else ""),
              npv),
        {"label": "Окупаемость собственных средств" + (" — без оценки" if hold else ""),
         "value": (_month_label(payback.isoformat()) if payback
                   else "не окупается за горизонт проекта"), "unit": "text"},
    ]
    return {"rows": out_rows, "years": year_rows,
            "columns": [list(c) for c in EQUITY_YEAR_COLUMNS],
            "contributed": contributed, "returned": returned, "parts": parts,
            "residual": residual_total,
            # Итог собственника ключами, а не подписями строк: разделы
            # «Решение» и «Экономика собственника» читают их отсюда.
            "irr": irr, "npv": npv, "discount_rate": discount_rate, "hold": hold,
            "peak": -worst, "peak_month": worst_month.isoformat() if worst_month else None,
            "payback_month": payback.isoformat() if payback else None}


# Колонки таблицы «по годам» — одна раскладка для страницы, PDF и книги.
NONRES_FINANCING_YEAR_COLUMNS: tuple[tuple[str, str, str], ...] = (
    ("year", "Год", "text"),
    ("draw", "Выборка", "mln"),
    ("interest", "Проценты начислены", "mln"),
    ("repayment", "Погашено тела", "mln"),
    ("balance_end", "Долг на конец года", "mln"),
    ("noi", "NOI", "mln"),
    ("dscr", "DSCR", "mult"),
)


def object_result_rows(result: dict[str, Any], *, hold: bool) -> list[dict[str, Any]]:
    """Блок «Итог объекта» таблицы — из `object_result`, без пересчёта.

    Строки не офисные: любой объект со своим итогом печатает тот же блок.
    Чего нет — того и не печатаем нулём: IRR без смены знака потока назван
    причиной, окупаемость за горизонт — тоже.
    """
    if not result:
        return []
    rate = float(result.get("discount_rate") or 0.0)

    def irr_row(label: str, value: Any, flow: float) -> dict[str, Any]:
        if value is not None:
            return {"label": label, "value": value, "unit": "pct"}
        reason = ("не считается — поток не возвращает вложенное" if flow < 0
                  else "не считается — поток не меняет знак")
        return {"label": label, "value": reason, "unit": "text"}

    rows: list[dict[str, Any]] = [{"label": "Итог объекта", "value": None, "unit": "section"}]
    if result.get("common_capex"):
        rows += [
            {"label": "Затраты объекта — стройка и доля общих затрат проекта",
             "value": result.get("cost_total"), "unit": "rub"},
            {"label": "в т.ч. доля общих затрат проекта (участок, проект, сети)",
             "value": result.get("common_capex"), "unit": "rub"},
        ]
    else:
        rows.append({"label": "Затраты объекта", "value": result.get("cost_total"), "unit": "rub"})
    rows += [
        {"label": "Собственный капитал объекта (затраты − кредит объекта)",
         "value": result.get("equity_invested"), "unit": "rub"},
        {"label": "Собственный капитал объекта — пик потребности",
         "value": result.get("equity_peak"), "unit": "rub"},
        {"label": ("Прибыль объекта до налога — без оценки, сделки нет" if hold
                   else "Прибыль объекта до налога"),
         "value": result.get("profit_before_tax"), "unit": "rub"},
        {"label": "Налог на прибыль объекта (как отдельного плательщика)",
         "value": result.get("profit_tax"), "unit": "rub"},
        {"label": ("Прибыль объекта после налога — без оценки" if hold
                   else "Прибыль объекта после налога"),
         "value": result.get("profit_after_tax"), "unit": "rub"},
        {"label": ("Денежный поток капитала объекта — итог без оценки" if hold
                   else "Денежный поток капитала объекта — итог"),
         "value": result.get("equity_cash"), "unit": "rub"},
    ]
    if hold:
        rows += [
            {"label": "Оценка объекта на конец горизонта — без сделки",
             "value": result.get("residual_value"), "unit": "rub"},
            {"label": "Поток капитала объекта с оценкой — итог",
             "value": result.get("equity_with_value"), "unit": "rub"},
            irr_row("IRR капитала объекта — с оценкой (часть результата без сделки)",
                    result.get("irr"), float(result.get("equity_with_value") or 0.0)),
            irr_row("IRR капитала объекта — только деньги, без оценки",
                    result.get("irr_cash"), float(result.get("equity_cash") or 0.0)),
        ]
    else:
        rows.append(irr_row("IRR капитала объекта", result.get("irr"),
                            float(result.get("equity_cash") or 0.0)))
    rows += [
        {"label": (f"NPV капитала объекта @{rate * 100:.4g}%"
                   + (" — с оценкой" if hold else "")),
         "value": result.get("npv"), "unit": "rub"},
        {"label": ("Срок окупаемости капитала — без оценки" if hold
                   else "Срок окупаемости капитала"),
         "value": (f"{result['payback_months']} мес. от первого вложения — "
                   + ".".join(reversed(str(result["payback_month"])[:7].split("-")))
                   if result.get("payback_months") is not None
                   else result.get("payback_reason") or "—"),
         "unit": "text"},
    ]
    return rows


# Суммы подстроки объекта, которые свод по очередям складывает. Удельные среди
# них нет — их считают заново от сложенных сумм и баз.
_STANDALONE_ITEM_SUMS = ("value", "building_value", "garage_value", "gns_sqm",
                         "saleable_sqm", "units", "garage_gns_sqm", "garage_units",
                         "over_units")


def object_parking_costs(op: dict[str, Any]) -> dict[str, float]:
    """Затраты продаваемого паркинга каждого объекта — доля статьи объекта.

    Паркинг объекта принадлежит объекту: его гараж и места первых этажей
    построены в статье объекта, и к пулу дома (`COST_POOL_PRODUCTS`) он
    отношения не имеет. Налог признаёт их вместе со статьёй объекта, как
    книга; отчёт о продуктах показывает эту долю строкой мест, чтобы маржа
    офиса не несла стоимость мест, выручка которых стоит соседней строкой.
    """
    amounts = op.get("capex_amounts") or {}
    return {key: float(amounts.get(key, 0.0) or 0.0) * float(share or 0.0)
            for key, share in (op.get("object_parking_capex_share") or {}).items()
            if share}


def _object_parking_spec(plan: list[dict[str, Any]], fallback: dict[str, Any]) -> dict[str, Any]:
    """Цена и календарь продукта «паркинг объектов» — от его объектов.

    Мест у нескольких объектов — цена средневзвешенная по местам, календарь
    от самого раннего старта до самого позднего конца. Без продаваемых мест
    остаётся прежнее умолчание: продукта тогда в выручке нет.
    """
    spaces = sum(item["spaces"] for item in plan)
    if spaces <= 0:
        return dict(fallback)
    return {
        "start_price": sum(item["price_th"] * item["spaces"] for item in plan) / spaces,
        "share": sum(item["share"] * item["spaces"] for item in plan) / spaces,
        "start": min(item["sales_start"] for item in plan),
        "end_ref": max(item["end_ref"] for item in plan),
        "residual": max(int(item["residual"]) for item in plan),
    }


def _space_label(value: float) -> str:
    return f"{value:,.0f}".replace(",", " ")


def standalone_expense_item_rates(item: dict[str, Any]) -> dict[str, Any]:
    """Удельные подстроки «в т.ч.» объекта — одна функция на очередь и на свод.

    Прежде их считали два места: движок очереди разводил здание и гараж, а
    свод по очередям складывал только деньги и делил их целиком на наземную
    ГНС здания. На своде гараж возвращался в «ставку здания», и 200 тыс ₽/м²
    вводной показывались как 316 — третий показатель, не сравнимый ни со
    сметой, ни со своей вводной. Второго счёта нет: оба места зовут эту.

    На входе — суммы и базы (`value`, `building_value`, `garage_value`,
    `gns_sqm`, `saleable_sqm`, `units`, `garage_gns_sqm`, `garage_units`,
    `over_units`); на выходе к ним добавлены удельные и строки `lines`,
    которые экран и печать рисуют одинаково. Каждая строка несёт СВОЮ базу
    словами: в колонках проектной таблицы она иначе читалась бы проектной.
    """
    out = dict(item)
    value = _number_or_zero(out.get("value"))
    if out.get("basis") == "units":
        units = _number_or_zero(out.get("units"))
        out["basis_label"] = f"{_space_label(units)} мест" if units else "мест не задано"
        out["per_unit_mln"] = value / units / 1_000_000 if units else 0.0
        out["lines"] = [{"label": f"{out.get('label')} · {out['basis_label']}",
                         "value": value, "gns_th": None, "saleable_th": None,
                         "per_unit_mln": out["per_unit_mln"], "basis": "место"}]
        return out
    garage = _number_or_zero(out.get("garage_value"))
    building = _number_or_zero(out.get("building_value")) if "building_value" in out \
        else max(0.0, value - garage)
    gns = _number_or_zero(out.get("gns_sqm"))
    saleable = _number_or_zero(out.get("saleable_sqm"))
    garage_gns = _number_or_zero(out.get("garage_gns_sqm"))
    garage_units = _number_or_zero(out.get("garage_units"))
    over_units = _number_or_zero(out.get("over_units"))
    out["building_value"] = building
    out["garage_value"] = garage
    out["basis_label"] = (f"{_space_label(gns)} м² ГНС объекта" if gns
                          else "площадь объекта не задана")
    if garage > 0:
        out["basis_label"] += (
            f" + гараж {_space_label(garage_gns)} м² подземной"
            + (f" на {_space_label(garage_units)} мест" if garage_units else ""))
    # Удельная — на ЗДАНИЕ и его площадь: она обязана воспроизводить вводную
    # ставку. Гараж стоит рядом своим числом на своей базе.
    out["per_own_gns_th"] = building / gns / 1000 if gns else 0.0
    out["per_own_saleable_th"] = building / saleable / 1000 if saleable else 0.0
    out["garage_per_gns_th"] = garage / garage_gns / 1000 if garage_gns else 0.0
    out["garage_per_unit_mln"] = garage / garage_units / 1_000_000 if garage_units else 0.0
    building_basis = (f"{_space_label(gns)} м² ГНС здания" if gns
                      else "площадь объекта не задана")
    if over_units:
        # Места первых этажей лежат в ГНС здания и стоят его ставки: отдельной
        # строки у них нет, но что часть метров — паркинг, сказано.
        building_basis += f", из них {_space_label(over_units)} мест на первых этажах"
    lines = [{"label": f"{out.get('label')} — здание · {building_basis}",
              "value": building, "gns_th": out["per_own_gns_th"],
              "saleable_th": out["per_own_saleable_th"], "per_unit_mln": None,
              "basis": "свой м²"}]
    if garage > 0:
        lines.append({
            "label": (f"{out.get('label')} — свой подземный гараж · "
                      f"{_space_label(garage_gns)} м²"
                      + (f", {_space_label(garage_units)} мест" if garage_units else "")),
            "value": garage, "gns_th": out["garage_per_gns_th"], "saleable_th": None,
            "per_unit_mln": out["garage_per_unit_mln"] or None, "basis": "м² подземной"})
    out["lines"] = lines
    return out


def standalone_expense_note(row_value: float, total_area: float, saleable: float) -> str:
    """Почему у строки «Отдельные объекты» и её подстрок разные удельные.

    Владелец увидел в одной таблице 132,7 у строки и 316,2 у её подстроки и
    спросил, что это. Ответ обязан стоять рядом числами, а не общими словами:
    строка делит деньги на площадь ВСЕГО проекта, подстрока — на свою.
    """
    def area(value: float) -> str:
        return _space_label(value) + " м²"

    def rate(value: float, base: float) -> str:
        per = value / base / 1000 if base else 0.0
        return f"{per:,.1f}".replace(",", " ").replace(".", ",")
    return (
        "Строка «Отдельные объекты» — те же деньги, делённые на площадь ВСЕГО "
        f"проекта ({area(total_area)} {TOTAL_AREA.genitive} → {rate(row_value, total_area)}; "
        f"{area(saleable)} продаваемой → {rate(row_value, saleable)}): так она "
        "складывается в итог таблицы. Подстроки «в т.ч.» делят "
        "деньги объекта на ЕГО базу — здание на свою ГНС и свою продаваемую, "
        "свой подземный гараж на свои метры и места, наземный паркинг на "
        "машино-место; в итог они не складываются."
    )


# --- Базы удельных показателей ---------------------------------------------
# Решение владельца 29.09.2026 (ревизия книги, решение 4): каждый удельный
# делится на СВОЮ базу и подписывается ею; база берётся из кода — из того,
# на что начислены деньги, а не из заголовка таблицы.
#   полные расходы, CAPEX и все расходные строки — на суммарную площадь в ГНС
#     (наземная + подземная, `construction_volume_sqm`);
#   СМР наземной части — на наземную ГНС МКД (на неё начислено);
#   СМР подземной части — на подземную площадь МКД;
#   выручка, цена, EBITDA и чистая прибыль — на продаваемую площадь.
# Вторая колонка «на м² продаваемой» остаётся у расходов для сравнения с ценой
# (ответы владельца 03.10.2026). Выбор базы — здесь, слова — в terms_glossary.
UNIT_BASE_TOTAL = TOTAL_AREA.key
UNIT_BASE_SALEABLE = SALEABLE_AREA.key
UNIT_BASE_CORE_ABOVE = CORE_ABOVE_AREA.key
UNIT_BASE_CORE_UNDER = CORE_UNDER_AREA.key

# Строки «Удельной экономики»: ключ, подпись, база.
UNIT_ECONOMICS_ROWS: tuple[tuple[str, str, str], ...] = (
    ("revenue", "Выручка", UNIT_BASE_SALEABLE),
    ("capex", "CAPEX", UNIT_BASE_TOTAL),
    ("commercial_costs", "Маркетинг и продажи", UNIT_BASE_TOTAL),
    ("ebitda", "EBITDA", UNIT_BASE_SALEABLE),
    ("financing_cost", "Проценты и комиссии", UNIT_BASE_TOTAL),
    ("profit_tax", "Налог на прибыль", UNIT_BASE_TOTAL),
    ("vat", "НДС", UNIT_BASE_TOTAL),
    ("total_expenses", "Полные расходы", UNIT_BASE_TOTAL),
    ("net_profit", "Чистая прибыль", UNIT_BASE_SALEABLE),
)

# Статьи «Удельных расходов строительства»: подпись и ключи CAPEX. Внутренние
# инженерные сети отдельной статьёй не живут: они в составе СМР своей части.
CONSTRUCTION_COST_ITEMS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("ИРД", ("ird",)),
    ("Проектирование (П, РД) и авторский надзор",
     ("design_p", "design_rd", "author_supervision")),
    ("Подготовка территории", ("preparation",)),
    ("СМР наземной части", ("main_above",)),
    ("СМР подземной части", ("main_under",)),
    ("Наружные инженерные сети", ("utilities",)),
    ("Благоустройство", ("landscaping",)),
    ("Сдача и ввод", ("commissioning",)),
    ("Содержание стройплощадки", ("site_maintenance",)),
    ("Вознаграждение генподрядчика", ("gc_fee",)),
    ("Технический заказчик / стройконтроль", ("technical_supervision",)),
    ("Управление проектом", ("project_management",)),
    ("Резерв", ("reserve",)),
)

def unit_bases(total_area: float, saleable: float, core_above: float,
               core_under: float) -> dict[str, float]:
    """Площади баз удельных, м² — одна выборка на расчёт."""
    return {UNIT_BASE_TOTAL: float(total_area or 0.0),
            UNIT_BASE_SALEABLE: float(saleable or 0.0),
            UNIT_BASE_CORE_ABOVE: float(core_above or 0.0),
            UNIT_BASE_CORE_UNDER: float(core_under or 0.0)}


def unit_rates(value: float, base: str, bases: dict[str, float]) -> dict[str, Any]:
    """Удельное на свою базу и на продаваемую; подпись базы — из словаря.

    Нулевая база — `None`, а не ноль: «0 тыс. ₽/м²» читался бы ответом.
    """
    def per(area: float) -> float | None:
        return float(value or 0.0) / area / 1000 if area else None

    return {"base": base, "base_label": unit_label(base),
            "per_base_th": per(bases.get(base, 0.0)),
            "per_saleable_th": per(bases.get(UNIT_BASE_SALEABLE, 0.0))}


def unit_economics_rows(values: dict[str, float], bases: dict[str, float]) -> list[dict[str, Any]]:
    return [{"key": key, "label": label, "total": float(values.get(key) or 0.0),
             **unit_rates(values.get(key) or 0.0, base, bases)}
            for key, label, base in UNIT_ECONOMICS_ROWS]


def construction_cost_rows(capex: dict[str, float], bases: dict[str, float]) -> list[dict[str, Any]]:
    rows = []
    for label, keys in CONSTRUCTION_COST_ITEMS:
        value = sum(float(capex.get(key) or 0.0) for key in keys)
        if value <= 0:
            continue
        rows.append({"label": label, "keys": list(keys), "value": value,
                     **unit_rates(value, capex_unit_base(keys[0]), bases)})
    return rows


def capex_unit_rows(capex: dict[str, float], bases: dict[str, float]) -> dict[str, dict[str, Any]]:
    """Удельные каждой статьи CAPEX и итога — для таблицы «Структура затрат»."""
    return {str(key): unit_rates(float(value or 0.0), capex_unit_base(key), bases)
            for key, value in (capex or {}).items() if isinstance(value, (int, float))}


def calculate(req: CalcRequest) -> dict:
    # Решение о доходности капитала принимается один раз, на выходе расчёта:
    # у раннего выхода (наложение фактов) и у основного пути одно правило.
    return _finalize_result(_calculate_economics(req))


def prepared_calculation(x: dict, t: dict, rates: list[dict[str, Any]] | None) -> dict[str, Any]:
    """Вводные, ТЭП и кривая ставки — такими, какими их считает движок.

    Одна подготовка на всех читателей: расчёт (`_calculate_economics`) и книга
    нежилого проекта (`nonres_book_spec`) берут вводные отсюда, а не
    повторяют порядок правок ТЭП у себя. Правит переданные словари так же,
    как правил расчёт до выноса.
    """
    if not rates:
        rates = generate_rate_curve(
            d(x.get("rate_start_date", date.today().isoformat())),
            n(x, "rate_start_pct", 14.0),
            n(x, "rate_target_high_pct", 11.0),
            n(x, "rate_target_base_pct", 9.0),
            n(x, "rate_target_low_pct", 7.0),
            int(n(x, "rate_normalization_months", 24)),
            180,
            n(x, "rate_curve_shape", 2.0),
        )

    # Строка подземного паркинга — производная от вводных, и ответ у неё ОДИН
    # (`underground_tep_row`). Здесь была своя ветвистая копия порядка
    # «отказ → руками → выгрузка», у которой не было последней ступени —
    # норматива: проект без ручных полей и без выгрузки оставался с тем, что
    # прислали, и правка норматива 35 → 40 не двигала ничего. Кладовые при
    # этом лежат на том же этаже, и движок считал их дважды.
    apply_underground_tep_row(x, t)
    apply_storage_tep_row(x, t)

    # Тип проекта решает, что из присланного СЧИТАЕТСЯ: нежилой проект
    # продукты МКД и жилые вводные не считает нигде — ни в ТЭП, ни в деньгах.
    # Стоит это после строк МКД (их писатели иначе собрали бы паркинг дома
    # заново из оставшихся мест) и до соцобъектов (их строки идут от мест,
    # которые здесь обнуляются). Остаток называется по присланному — это
    # расхождение вводных с типом, а не часть расчёта.
    kind_leftovers = nonresidential_leftovers(x, t)
    x, t = residential_excluded(x, t)
    # Состав объектов — тем же порядком: экземпляр вне проекта не считается,
    # а непринятое из присланного называется (`object_instance_notes`).
    instance_notes = object_instance_notes(x)
    x, t = object_instances_applied(x, t)

    # Соцобъект приводится к вводным здесь же, где чинится подземный паркинг,
    # и по той же причине: строка ТЭП у него — производная, а хранимая
    # производная расходится с правилом молча. Прежде одиночный расчёт не
    # считал её ВОВСЕ и брал присланное: правка «площади ДОО» во вводных не
    # двигала ни строку, ни строительный объём, а тот же садик в своде
    # очередей выходил другим.
    apply_social_tep_rows(x, t)
    # Наземный паркинг — той же природы: места задаёт человек, метры из них
    # выводятся, и без этого объект строится, а его площади нет нигде.
    apply_above_parking_tep_row(x, t)

    # Паркинг объектов раскладывается ДО построения модели: он
    # трогает продаваемую объекта, а значит выручку, и после счёта денег
    # правка ТЭП была бы правкой того, что уже посчитано.
    object_parking = apply_object_parking(x, t)
    return {"x": x, "t": t, "rates": rates, "kind_leftovers": kind_leftovers,
            "instance_notes": instance_notes, "object_parking": object_parking}


def _calculate_economics(req: CalcRequest) -> dict:
    prepared = prepared_calculation(req.inputs, req.tep, req.rates)
    x, t, rates = prepared["x"], prepared["t"], prepared["rates"]
    kind_leftovers = prepared["kind_leftovers"]
    instance_notes = prepared["instance_notes"]
    object_parking = prepared["object_parking"]

    op = build_operating_model(x, t, rates)
    # Прошлое действующего проекта не выдумывается — оно случилось. Наложение
    # стоит здесь, между построением модели и финансированием: подменённые ряды
    # доходят до долга, налогов и LLCR сами, и второй реализации не возникает.
    actuals_report: dict[str, Any] = {}
    if getattr(req, "actuals", None):
        overlaid = developaid_actuals.overlay(op, req.actuals)
        op = overlaid["op"]
        actuals_report = overlaid["report"]
    fin = simulate_financing(x, t, rates, op)

    tep_rows = []
    for key, row in t.items():
        # Гостевые машино-места строятся и стоят денег, но не продаются. Число
        # едет в строку ТЭП, а не выводится каждой поверхностью заново: книга
        # считала объём продаж от всех мест и продавала гостевые вместе с
        # остальными — выручка расходилась с движком на их стоимость.
        guest = float(underground_guest_spaces(row)) if key == "underground_parking" else 0.0
        given = transferred_units(row)
        units = n(row, "units")
        tep_rows.append({
            "key": key,
            "label": row.get("label", key),
            "gns": n(row, "gns"),
            "total_area": n(row, "total_area"),
            "useful": n(row, "useful"),
            "saleable": n(row, "saleable"),
            "transfer": n(row, "transfer"),
            "units": units,
            "guest_units": guest,
            # Переданные штуки строятся и стоят денег, но не продаются — как
            # гостевые места. Число едет строкой ТЭП, а не выводится каждой
            # поверхностью заново.
            "transfer_units": given,
            # У соцобъекта units — мощность (места ДОО/СОШ или посещения
            # поликлиники), а не товарные единицы. Такие места строятся как
            # обязательство, но не продаются участникам проекта.
            "saleable_units": (
                0.0 if key in SOCIAL_TEP_FIELDS
                else max(0.0, units - guest - given)
            ),
            # Гараж отдельно стоящего объекта живёт полем на его же строке, и
            # до отчёта эти поля не доезжали вовсе: строка собирается по
            # списку ключей, а их в списке не было. Свод очередей складывает
            # строки отчётов — значит подземная площадь и места гаража на
            # своде выходили нулём при живом гараже в каждой очереди.
            "under_gns": n(row, "under_gns"),
            "parking_units": n(row, "parking_units"),
            "parking_saleable_units": n(row, "parking_saleable_units"),
            # Где стоят места объекта: гараж под землёй и первые этажи в ГНС
            # здания. ТЭП печатает их строкой «в т.ч. паркинг объекта».
            "parking_under_units": n(row, "parking_under_units"),
            "parking_over_units": n(row, "parking_over_units"),
            # Продаётся у объекта остаток после мест первых этажей; строка
            # держит площадь здания. Число — `apply_object_parking`.
            "parking_saleable_after_sqm": n(row, "parking_saleable_after_sqm"),
            "parking_guest_units": n(row, "parking_guest_units"),
        })
        # Строка вне состава проекта (`row_outside_project`): нули в ней —
        # не «продукт пуст», а «продукта в этом проекте нет».
        tep_rows[-1]["excluded"] = row_outside_project(x, key, tep_rows[-1])
        # Есть ли продукт в проекте — тот же ответ, что у тизера и полного PDF
        # (`row_listed`); его читают поверхности, которым состава мало.
        tep_rows[-1]["listed"] = row_listed(tep_rows[-1])

    # Свод складывает только складываемое. Штук в списке нет: они
    # группируются мерой счёта, потому что квартира, машино-место и место в
    # детском саду — разные величины.
    tep_total = {key: sum(row[key] for row in tep_rows) for key in TEP_SUMMABLE_FIELDS}
    tep_total["units_by_measure"] = tep_units_by_measure(tep_rows)
    tep_total["saleable_units_by_measure"] = tep_units_by_measure(
        tep_rows, "saleable_units", "parking_saleable_units")

    total_revenue = fin["total_revenue"]
    total_capex = fin["total_capex"]
    after_finance_pre_tax = fin["profit_before_tax"]
    net_profit = after_finance_pre_tax - fin["profit_tax"] - fin.get("vat", 0.0)

    # Report-level project metrics.
    monetizable_saleable_sqm = sold_saleable_sqm(t, x)
    apartment_saleable_sqm = n(t.get("apartments", {}), "saleable")
    core_gns = op["core_above_gns"] + op["core_under_gns"]

    construction_capex = sum(op["capex_amounts"].get(k, 0.0) for k in (
        "ird", "design_p", "design_rd", "author_supervision", "preparation",
        "main_above", "main_under", "utilities", "landscaping",
        "commissioning", "site_maintenance", "gc_fee", "reserve"
    ))
    # Расходы объектов вне ДДУ — продажи ДКП, эксплуатация, налог на
    # имущество, выход (`finance.nonres_costs`). Прибыль до налога их
    # вычитала, а EBITDA, «Расходы всего» и структура расходов — нет: на
    # экране EBITDA − проценты не давала прибыль до налога (владелец,
    # 05.10.2026: «15,52 − 1,12 = 14,40, а у нас 12,45?»).
    nonres_costs = float(fin.get("nonres_costs", 0.0) or 0.0)
    full_project_cost = total_capex + fin["commercial_costs"] + nonres_costs + fin["financing_cost"] + fin["profit_tax"] + fin.get("vat", 0.0)
    avg_apartment_price = (
        op["revenue_by_product"].get("apartments", 0.0) / apartment_saleable_sqm / 1000
        if apartment_saleable_sqm else 0.0
    )
    full_cost_per_saleable = full_project_cost / monetizable_saleable_sqm / 1000 if monetizable_saleable_sqm else 0.0
    construction_cost_per_gns = construction_capex / core_gns / 1000 if core_gns else 0.0
    ebitda = total_revenue - total_capex - fin["commercial_costs"] - nonres_costs
    ebitda_per_saleable = ebitda / monetizable_saleable_sqm / 1000 if monetizable_saleable_sqm else 0.0
    net_profit_per_saleable = net_profit / monetizable_saleable_sqm / 1000 if monetizable_saleable_sqm else 0.0

    # ГНС — НАЗЕМНАЯ площадь здания, и подземная в неё не входит: под землёй
    # наружных стен не бывает, а у подземной части своя экономика — свой метр
    # стройки и свой продукт, продаваемый местами (решение владельца,
    # 04.09.2026). Пока подземная стояла в базе, удельный «на метр ГНС» был на
    # пятую часть ниже того же показателя по наземной площади, и сравнить его
    # с чужой сметой было нельзя. Строительный объём — сумма обеих — остаётся
    # рядом своим числом: на нём считаются общие статьи.
    # Свой подземный паркинг объекта лежит полем на его же строке: строкой
    # проекта он поехал бы по очередям чужими правилами. В наземную ГНС он не
    # входит — под землёй наружных стен не бывает и у объекта тоже.
    object_under_gns = sum(n(row, "under_gns") for row in t.values())
    underground_gns_sqm = (sum(n(t.get(key) or {}, "gns") for key in UNDERGROUND_PRODUCTS)
                           + object_under_gns)
    construction_volume_sqm = sum(n(row, "gns") for row in t.values()) + object_under_gns
    project_gns_sqm = project_above_gns(t)
    total_expenses = full_project_cost

    def per_sqm_th(value: float, area: float) -> float:
        return value / area / 1000 if area else 0.0

    # Базы удельных — одна выборка; строки и их базы объявлены движком
    # (`UNIT_ECONOMICS_ROWS`, `CONSTRUCTION_COST_ITEMS`), решение 4 ревизии.
    bases = unit_bases(construction_volume_sqm, monetizable_saleable_sqm,
                       op["core_above_gns"], op["core_under_gns"])
    unit_economics = unit_economics_rows({
        "revenue": total_revenue, "capex": total_capex,
        "commercial_costs": fin["commercial_costs"], "ebitda": ebitda,
        "financing_cost": fin["financing_cost"], "profit_tax": fin["profit_tax"],
        "vat": fin.get("vat", 0.0), "total_expenses": total_expenses,
        "net_profit": net_profit}, bases)

    # Удельные расходы строительства: статьи стройки в деньгах и на м² своей
    # базы. СМР делится на ту часть, на которую начислено (наземная ГНС МКД,
    # подземная площадь МКД): прежде подземное СМР делилось на НАЗЕМНУЮ ГНС
    # проекта, и 23 тыс ₽/м² читались ставкой за подземный метр, а она 190.
    construction_costs = construction_cost_rows(op["capex_amounts"], bases)

    # Темп продаж квартир в штуках. В метрах он есть везде, но продаются
    # квартиры штуками: «40 квартир в месяц» проверяется отделом продаж и
    # рынком, а «2 400 м² в месяц» — нет. Пересчёт идёт через среднюю площадь
    # квартиры из ТЭП, поэтому меняется вместе с ней.
    apartment_units_total = n(t.get("apartments", {}), "units")
    avg_apartment_sqm = (apartment_saleable_sqm / apartment_units_total
                         if apartment_units_total else 0.0)
    apartment_sales: dict[str, Any] = {}
    apartment_quantity = op.get("quantity_product_schedules", {}).get("apartments") or {}
    if avg_apartment_sqm > 0 and apartment_quantity:
        monthly = [(month, sqm / avg_apartment_sqm)
                   for month, sqm in sorted(apartment_quantity.items()) if sqm > 0]
        before_rve = [units for month, units in monthly if month <= op["rve"]]
        apartment_sales = {
            "units_total": apartment_units_total,
            "avg_unit_sqm": avg_apartment_sqm,
            "avg_unit_price_mln": (avg_apartment_sqm * avg_apartment_price / 1000
                                   if avg_apartment_price else 0.0),
            "pace_pre_rve_units": sum(before_rve) / len(before_rve) if before_rve else 0.0,
            "pace_units": sum(u for _, u in monthly) / len(monthly) if monthly else 0.0,
            "peak_units": max((u for _, u in monthly), default=0.0),
            "months": len(monthly),
            "rows": [{"month": month.isoformat(), "units": units} for month, units in monthly],
        }

    # Expense structure: categories are mutually exclusive and sum to total expenses.
    # Стоимость сделки — цена участка и выкуп ЗУ/ОКС у третьих лиц одной
    # группой: обе строки платятся графиком сделки. Разбивка — в `summary`.
    purchase_value = (n(x, "purchase_price_mln") + n(x, "land_buyout_mln")) * 1_000_000
    expense_groups = [
        ("Цена приобретения", purchase_value),
        ("Смена ВРИ / земельные права",
         op["capex_amounts"].get("land_rights", 0.0)
         + op["capex_amounts"].get("vri_security", 0.0)),
        ("Проценты по рассрочке ВРИ", op["capex_amounts"].get("vri_interest", 0.0)),
        ("ИРД и проектирование",
         op["capex_amounts"].get("ird", 0.0)
         + op["capex_amounts"].get("design_p", 0.0)
         + op["capex_amounts"].get("design_rd", 0.0)
         + op["capex_amounts"].get("author_supervision", 0.0)),
        ("Основное строительство",
         op["capex_amounts"].get("preparation", 0.0)
         + op["capex_amounts"].get("main_above", 0.0)
         + op["capex_amounts"].get("main_under", 0.0)
         + op["capex_amounts"].get("utilities", 0.0)
         + op["capex_amounts"].get("landscaping", 0.0)
         + op["capex_amounts"].get("commissioning", 0.0)
         + op["capex_amounts"].get("site_maintenance", 0.0)
         + op["capex_amounts"].get("gc_fee", 0.0)),
        # Снос и расселение — статьи CAPEX движка и книги (строки 36 и 37), и
        # в структуре расходов их не было вовсе: итог таблицы не сходился с
        # CAPEX ровно на них. Подписи — те же, что у статей (`_MONTHLY_CAPEX_LABELS`).
        (_MONTHLY_CAPEX_LABELS["demolition"], op["capex_amounts"].get("demolition", 0.0)),
        (_MONTHLY_CAPEX_LABELS["resettlement"], op["capex_amounts"].get("resettlement", 0.0)),
        ("Отдельные объекты",
         sum(op["capex_amounts"].get(_o.key, 0.0) for _o in STANDALONE_OBJECTS)),
        # Статьи гостиницы (`hotel_capex_amounts`) есть только у гостиничного
        # проекта; у остальных сумма ноль, и строка не встаёт.
        ("Гостиница — здание, мебель и оборудование",
         op["capex_amounts"].get("hotel", 0.0) + op["capex_amounts"].get("hotel_ffe", 0.0)),
        ("Социальная нагрузка", op["capex_amounts"].get("social", 0.0)),
        ("Управление проектом",
         op["capex_amounts"].get("project_management", 0.0)),
        ("Технический заказчик / стройконтроль",
         op["capex_amounts"].get("technical_supervision", 0.0)),
        ("Резерв",
         op["capex_amounts"].get("reserve", 0.0)),
        ("Маркетинг и продажи", fin["commercial_costs"]),
        (nonres_costs_label(x), float(fin.get("nonres_costs", 0.0) or 0.0)),
        ("Проценты и комиссии", fin["financing_cost"]),
        ("Налог на прибыль", fin["profit_tax"]),
        # НДС виден отдельной строкой: он не налог на прибыль и не
        # стройка, и прятать его внутри «налогов» значит скрыть от
        # человека статью, которая растёт вместе с долей нежилого.
        # Возмещение больше начисленного (гостиница со льготой 0 % на
        # проживание) — строка со знаком минус: «Расходы всего» его учитывают,
        # и без строки структура расходилась бы с итогом ровно на него.
        (VAT_REFUND_LABEL if float(fin.get("vat", 0.0) or 0.0) < 0 else "НДС",
         fin.get("vat", 0.0)),
    ]
    # Отдельно стоящий объект меряется СВОЕЙ площадью, а наземный паркинг —
    # своими местами (владелец, 04.09.2026: «по сути это разные объекты и
    # должны на свои площади равняться»; «в случае с парковыми на ед м-м»).
    # Колонки строки остаются проектными — они складываются в итог таблицы, —
    # а под ней стоят подстроки «в т.ч.» со своей базой у каждого объекта.
    # Прежде этого не было вовсе: расходы объектов делились на метры ВСЕГО
    # проекта, и при вводной себестоимости 200 тыс ₽/м² GBA в таблице стояло
    # 20,1 — в десять раз ниже, и сравнить это ни со сметой, ни со своей же
    # вводной было нельзя. Рядом жила вторая беда: в числителе строки стоит и
    # наземный паркинг, у которого метров в знаменателе нет вовсе — он
    # продаётся местами.
    standalone_items = []
    # Список объектов — тот, что объявлен в движке, а не перечисление руками:
    # ФОК завели четвёртым 05.09.2026, в это перечисление он не вошёл, и его
    # 3 616 млн ₽ (19% строки) стояли в итоге и не были названы ни одной
    # подстрокой. То же правило, что у корзин находок: корзина, заведённая
    # позже, в перечисление не попадает. Имя берётся у `product_labels` —
    # второго ответа на «как зовётся продукт» не бывает.
    _labels = product_labels()
    _object_names = {"offices": "Офисы / МФОЦ", "standalone_retail": "ТЦ / коммерция ОСЗ"}
    for _obj in STANDALONE_OBJECTS:
        key = _obj.key
        label = _object_names.get(key) or _labels.get(key) or key
        amount = op["capex_amounts"].get(key, 0.0)
        if amount <= 0:
            continue
        row = t.get(key) or {}
        own_gns = n(row, "gns")
        # Удельная на продаваемый — на ПРОДАННЫЕ метры: под местами первых
        # этажей офис не продаётся.
        own_saleable = object_sold_saleable(x, t, key)
        # Гараж объекта стоит подземного метра и в его наземной ГНС не лежит:
        # делённый на неё, он поднимал удельную с вводных 200 до 249 тыс ₽/м²,
        # и сравнить это ни со сметой, ни со своей же вводной было нельзя.
        # Здание меряется своей площадью, гараж — своим метром и своими
        # местами, и обе базы названы рядом.
        garage = float((op.get("standalone_garage_capex") or {}).get(key) or 0.0)
        # Делитель берётся оттуда же, откуда взялся числитель: CAPEX наземного
        # паркинга считается как `above_parking_spaces × себестоимость места`,
        # и строка ТЭП тут вторым источником быть не может — при вызове мимо
        # страницы она приходит нулём, и «за место» вышло бы делением на ноль.
        own_units = (n(x, f"{_obj.prefix}_spaces") if _obj.measure == "spaces"
                     else n(row, "units"))
        item = {"key": key, "label": label, "value": amount,
                "gns_sqm": own_gns, "saleable_sqm": own_saleable,
                "units": own_units,
                # Мера продукта у наземного паркинга — место, и делить его
                # деньги на метры значит отвечать не на тот вопрос.
                "basis": "units" if _obj.measure == "spaces" else "area"}
        if _obj.measure != "spaces":
            # Гараж — это ПОДЗЕМНЫЕ места: места первых этажей лежат в ГНС
            # здания и стоят его ставки. Прежде в подпись гаража шли все места
            # объекта, и «35 000 м² подземной на 2 778 мест» делили гараж на
            # места, которых в нём нет.
            item.update({"building_value": max(0.0, amount - garage),
                         "garage_value": garage,
                         "garage_gns_sqm": n(row, "under_gns"),
                         "garage_units": n(row, "parking_under_units"),
                         "over_units": n(row, "parking_over_units")})
        standalone_items.append(standalone_expense_item_rates(item))

    expense_structure = []
    expense_base = sum(value for _, value in expense_groups)
    for label, value in expense_groups:
        if value == 0 or (value < 0 and label != VAT_REFUND_LABEL):
            continue
        entry = {
            "label": label,
            "value": value,
            "share": value / expense_base if expense_base else 0.0,
            # Расход — на суммарную площадь в ГНС и на продаваемую (решение 4).
            **unit_rates(value, UNIT_BASE_TOTAL, bases),
        }
        if label == "Отдельные объекты" and standalone_items:
            entry["items"] = standalone_items
            entry["items_note"] = standalone_expense_note(
                value, construction_volume_sqm, monetizable_saleable_sqm)
        expense_structure.append(entry)
    expense_structure.sort(key=lambda item: item["value"], reverse=True)

    # Project/equity cash flow proxy for NPV / IRR.
    row_by_month = {d(r["month"]): r for r in fin["rows"]}
    timeline = month_range(op["project_start"], op["end"])
    project_cf = []
    equity_cf = []
    for month in timeline:
        revenue_m = op["revenue"].get(month, 0.0)
        capex_m = op["capex"].get(month, 0.0)
        opex_m = op["operating"].get(month, 0.0)
        fr = row_by_month.get(month, {})
        bridge_draw = float(fr.get("bridge_draw", 0.0) or 0.0)
        bridge_repay = float(fr.get("bridge_repayment", 0.0) or 0.0)
        pf_draw = float(fr.get("pf_draw", 0.0) or 0.0)
        pf_repay = float(fr.get("pf_repayment", 0.0) or 0.0)
        int_pay = float(fr.get("interest_payment", 0.0) or 0.0)
        # Limit fees are capitalized into interest payable inside the financing
        # engine and therefore already included in interest_payment when paid.
        fees = 0.0
        tax = float(fr.get("profit_tax", 0.0) or 0.0)
        # ТЦ и офисы вне ДДУ: их выручка приходит мимо эскроу, в свой месяц.
        # Проекту — начисленные проценты кредита объекта, капиталу — его
        # собственный остаток после кредита (`nonres_cash_to_equity`); CAPEX
        # объекта уже в `capex_m`.
        nonres_project = (
            float(fr.get("nonres_revenue", 0.0) or 0.0)
            - float(fr.get("nonres_costs", 0.0) or 0.0)
            - float(fr.get("nonres_vat_paid", 0.0) or 0.0)
            - float(fr.get("nonres_loan_interest", 0.0) or 0.0)
            - float(fr.get("nonres_loan_fee", 0.0) or 0.0)
        )
        project_cf.append(revenue_m - capex_m - opex_m - int_pay - fees - tax + nonres_project)
        escrow_release = float(fr.get("escrow_release", 0.0) or 0.0)
        cash_revenue_to_equity = 0.0 if month < op["rve"] else revenue_m + escrow_release
        # Кэш-свип уходит банку с поступлений этой очереди: её долг он не
        # гасит (линия закрыта), поэтому в pf_repay его нет, а из кассы он
        # выбывает. Без этого вычета деньги посчитались бы дважды — здесь как
        # оставшиеся застройщику, и у следующей очереди как погашение.
        equity_cf.append(
            cash_revenue_to_equity - capex_m - opex_m - int_pay - fees - tax
            + bridge_draw + pf_draw - bridge_repay - pf_repay
            - float(fr.get("bank_sweep_out", 0.0) or 0.0)
            + float(fr.get("bank_sweep_returned", 0.0) or 0.0)
            + float(fr.get("nonres_cash_to_equity", 0.0) or 0.0)
        )

    if project_cf:
        project_cf[0] -= fin["bridge_fee"]
    if equity_cf:
        equity_cf[0] -= fin["bridge_fee"]
    permit_idx = months_between(op["project_start"], op["permit"])
    if 0 <= permit_idx < len(project_cf):
        project_cf[permit_idx] -= fin["pf_reservation_fee"]
        equity_cf[permit_idx] -= fin["pf_reservation_fee"]

    discount_rate = n(x, "discount_rate_pct", 20) / 100
    project_npv = _monthly_npv(project_cf, discount_rate)
    # Поток проекта гостиницы — FCFF её расчёта, без процентов кредита (как в
    # модели Отеля 1): NPV проекта — её, а не ряды выше, они после процентов.
    _hotel = fin.get("hotel") or {}
    if _hotel.get("computed"):
        project_npv = float(_hotel["kpi"]["npv_project"])
    equity_npv = _equity_npv(equity_cf, discount_rate)
    irr_equity = _monthly_irr(equity_cf)

    # Product economics / sales KPIs.
    product_specs = {
        "apartments": {
            "label": "Квартиры", "quantity": n(t.get("apartments", {}), "saleable"),
            "unit": "м²", "start_price": n(x, "apartment_price_th"), "share": n(x, "share_before_rve_pct", 85)/100,
            "start": op["sales_start"], "end_ref": op["rve"], "residual": int(n(x, "residual_sales_months", 6))
        },
        "ground_commercial": {
            "label": "Коммерция 1 этажа", "quantity": n(t.get("ground_commercial", {}), "saleable"),
            "unit": "м²", "start_price": n(x, "commercial_price_th"), "share": n(x, "share_before_rve_pct", 85)/100,
            "start": op["sales_start"], "end_ref": op["rve"], "residual": int(n(x, "residual_sales_months", 6))
        },
        "underground_parking": {
            # Продаётся не весь паркинг: гостевые места остаются общими.
            "label": "Подземный паркинг",
            "quantity": underground_saleable_spaces(t.get("underground_parking", {})),
            "unit": "шт.", "start_price": n(x, "parking_price_th"), "share": n(x, "share_before_rve_pct", 85)/100,
            "start": op["sales_start"], "end_ref": op["rve"], "residual": int(n(x, "residual_sales_months", 6))
        },
        "storage": {
            "label": "Кладовые", "quantity": n(t.get("storage", {}), "units"),
            "unit": "шт.", "start_price": n(x, "storage_price_th"), "share": n(x, "share_before_rve_pct", 85)/100,
            "start": op["sales_start"], "end_ref": op["rve"], "residual": int(n(x, "residual_sales_months", 6))
        },
    }
    # Отдельно стоящие объекты — обходом реестра: поля у них одни и те же со
    # своей приставкой, и перечисленные руками они не знали второго офисника.
    # Переданный городу объект продаваемой площади не имеет: метры строятся,
    # но не продаются — как у соцобъекта.
    for _obj in standalone_objects_report_order():
        _pre = _obj.prefix
        _volume = f"{_pre}_spaces" if _obj.measure == "spaces" else f"{_pre}_saleable_sqm"
        product_specs[_obj.key] = {
            "label": _PRODUCT_SPEC_LABELS.get(_obj.key) or _obj.tep_label or _obj.label,
            # Метры — после пятна мест первых этажей (`standalone_object_saleable`),
            # места — как есть.
            "quantity": ((n(x, _volume) if _obj.measure == "spaces"
                          else standalone_object_saleable(x, t, _obj.key))
                         if b(x, _obj.enabled_key) and object_is_sold(x, _obj) else 0),
            "unit": "шт." if _obj.measure == "spaces" else "м²",
            # Цена места стоит в млн ₽, таблица — в тыс. ₽ за штуку.
            "start_price": n(x, _obj.rate_price) * (1000 if _obj.measure == "spaces" else 1),
            "share": n(x, f"{_pre}_share_before_rve_pct", 85)/100,
            "start": d(x[f"{_pre}_sales_start"]),
            "end_ref": add_months(d(x[f"{_pre}_start"]),
                                  int(n(x, f"{_pre}_months", _obj.default_months))),
            "residual": int(n(x, f"{_pre}_residual_months", 6)),
        }

    # Паркинг каждого объекта — своя строка продукта сразу за своим объектом:
    # места, цена и календарь СВОЕГО объекта (владелец, 27.09.2026). Состав —
    # из реестра, поэтому новый объект получает строку сам. Строка заводится
    # у включённого объекта с местами; у ТЦ и ФОКа места строятся и не
    # продаются — продаётся 0, построено — их число.
    _plans = {item["key"]: item for item in (op.get("object_parking_plan") or [])}
    _specs: dict[str, dict[str, Any]] = {}
    for _key, _spec in product_specs.items():
        _specs[_key] = _spec
        _obj = next((o for o in standalone_objects() if o.key == _key), None)
        if _obj is None or not _obj.garage or not b(x, _obj.enabled_key):
            continue
        _row = t.get(_key) or {}
        _built = n(_row, "parking_units")
        if _built <= 0:
            continue
        _sold = (n(_row, "parking_saleable_units")
                 if object_is_sold(x, _obj) else 0.0)
        _specs[OBJECT_PARKING_PRODUCT_KEYS[_key]] = {
            "label": NON_TEP_PRODUCT_LABELS[OBJECT_PARKING_PRODUCT_KEYS[_key]],
            "quantity": _sold, "built_units": _built,
            "object": _key, "unit": "шт.",
            **_object_parking_spec([_plans[_key]] if _key in _plans else [], {
                "start_price": 0.0, "share": _spec["share"],
                "start": _spec["start"], "end_ref": _spec["end_ref"],
                "residual": _spec["residual"]}),
        }
    product_specs = _specs

    products_report = []
    # Тот же признак, что в налоговой базе: переданный ФОК своего пула
    # расходов не имеет — признавать его нечем, выручки у него нет.
    report_krt_costs = {
        _obj.key: float(op["capex_amounts"].get(_obj.key, 0.0) or 0.0)
        for _obj in STANDALONE_OBJECTS
        if not _obj.sale_gate or (b(x, _obj.enabled_key) and object_is_sold(x, _obj))
    }
    # Паркинг объекта несёт долю статьи СВОЕГО объекта (`object_parking_costs`),
    # а не долю стройки дома. Сумма по объекту та же, что в налоговой базе.
    _parking_costs = {key: value for key, value in object_parking_costs(op).items()
                      if key in report_krt_costs}
    for _key, _value in _parking_costs.items():
        report_krt_costs[_key] -= _value
        report_krt_costs[OBJECT_PARKING_PRODUCT_KEYS[_key]] = _value
    # Паркинг объекта без своей доли (места не продаются) расхода не несёт:
    # его гараж стоит в статье объекта. В пул дома он не идёт никогда.
    for _key in product_specs:
        if _key in OBJECT_PARKING_PRODUCT_KEYS.values():
            report_krt_costs.setdefault(_key, 0.0)
    # Тот же пул, что у налоговой базы, и объявлен он там же: две копии одного
    # списка разошлись бы молча — доли расходов перестали бы давать единицу.
    report_core_keys = COST_POOL_PRODUCTS
    report_core_quantity = sum(float(product_specs[key]["quantity"] or 0.0)
                               for key in report_core_keys)
    report_core_cost = max(total_capex - sum(report_krt_costs.values()), 0.0)
    for key, spec in product_specs.items():
        quantity = float(spec["quantity"] or 0)
        revenue_value = op["revenue_by_product"].get(key, 0.0)
        tep_row = t.get(key) or {}
        if key in report_krt_costs:
            product_cost = report_krt_costs[key]
        else:
            product_cost = (report_core_cost * quantity / report_core_quantity
                            if report_core_quantity else 0.0)
        schedule = op["revenue_product_schedules"].get(key, {})
        months_pre = max(1, months_between(spec["start"], spec["end_ref"]))
        pace = quantity * spec["share"] / months_pre if quantity else 0.0
        avg_price = revenue_value / quantity / 1000 if quantity else 0.0
        start_date = min(schedule.keys()).isoformat() if schedule else None
        end_date = max(schedule.keys()).isoformat() if schedule else None
        products_report.append({
            "key": key,
            "label": spec["label"],
            "unit": spec["unit"],
            # Продукт продаж: у него есть цена и график. Признак стоит у
            # ОБЕИХ половин списка — «нет ключа» читалось бы как «не знаем».
            "sellable": True,
            "quantity": quantity,
            "gns": float(tep_row.get("gns", 0.0) or 0.0),
            "saleable": (object_sold_saleable(x, t, key) if key in _BY_KEY
                         else float(tep_row.get("saleable", 0.0) or 0.0)),
            "revenue": revenue_value,
            "cost": product_cost,
            "margin": ((revenue_value - product_cost) / revenue_value
                       if revenue_value else None),
            "start_price_th": spec["start_price"],
            "avg_price_th": avg_price,
            "pace_pre": pace,
            "share_before_rve": spec["share"],
            # Паркинг объекта: сколько мест построено и чей это объект —
            # у ТЦ и ФОКа построено есть, а продаётся ноль.
            **({"built_units": float(spec["built_units"]), "object": spec["object"]}
               if "built_units" in spec else {}),
            "sales_start": start_date,
            "sales_end": end_date,
            # Профиль продаж и лестница цены объекта — с тем, что применилось и
            # что не разобралось: экран и PDF печатают их рядом с продуктом.
            **_product_schedule_fields(op.get("object_schedule_notes", {}), key),
        })

    # Остаточные строки ТЭП — продукт, заведённый позже и не попавший в список
    # продаваемых. Он обязан остаться видимым, а не исчезнуть молча, но
    # ПРОДУКТОМ ПРОДАЖ он от этого не становится.
    #
    # Единица здесь стояла литералом «м²», а количество бралось из штук: у
    # ДОО выходило «350 м²», у СОШ «1 000 м²», у поликлиники «79 м²» — это
    # места, места и посещения в смену, подписанные метрами, в таблице
    # продаж, с выручкой ноль. «Почему школа, поликлиника и СОШ в метрах
    # квадратных стоят» (владелец, 27.09.2026). Единица клетки — единица
    # ЭТОГО числа, а не соседнего, и берётся она у объявленной меры счёта.
    reported = {item["key"] for item in products_report}
    for key, tep_row in t.items():
        if key in reported or not any(float(tep_row.get(field, 0.0) or 0.0)
                                      for field in ("gns", "total_area", "units")):
            continue
        measure = tep_count_measure(key)
        metres = float(tep_row.get("saleable", 0.0) or 0.0)
        products_report.append({
            "key": key, "label": tep_row.get("label") or key,
            "unit": measure or "м²",
            "quantity": (float(tep_row.get("units", 0.0) or 0.0) if measure else metres),
            "gns": float(tep_row.get("gns", 0.0) or tep_row.get("total_area", 0.0) or 0.0),
            "saleable": metres,
            "revenue": 0.0, "cost": 0.0, "margin": None,
            "start_price_th": 0.0, "avg_price_th": 0.0, "pace_pre": 0.0,
            "share_before_rve": 0.0, "sales_start": None, "sales_end": None,
            # Признак объявлен, а не выводится из нулевой выручки: продукт,
            # который в этом расчёте ничего не продал, — не то же самое, что
            # продукт, который не продаётся по построению.
            "sellable": False,
        })

    # Продукт объекта вне состава проекта — той же меркой, что строка ТЭП.
    for item in products_report:
        item["excluded"] = row_outside_project(x, item["key"], item)

    # Calendar / Gantt, mirroring the conceptual structure of the Excel Calendar sheet.
    calendar_events = []
    def add_event(label: str, start: date, end: date | None = None, group: str = "Проект", kind: str = "bar"):
        calendar_events.append({
            "label": label, "start": _iso(start), "end": _iso(end or start),
            "group": group, "kind": kind
        })

    add_event("Сделка / начало проекта", op["project_start"], group="Ключевые вехи", kind="milestone")
    add_event("ИРД и согласования", op["project_start"], op["permit"], group="Подготовка")
    design_start = add_months(op["permit"],
                              -min(6, max(IRD_MONTHS_MIN, int(n(x, "ird_months", 18)))))
    add_event("Проектирование П и РД", design_start, op["permit"], group="Подготовка")
    bridge_end = add_months(op["permit"], int(n(x, "bridge_repay_lag_months", 0)))
    # Полоса финансирования — того долга, что у проекта есть. БРИДЖ рисуется,
    # когда он выбирался; у нежилого проекта его нет, а есть кредит каждого
    # объекта вне ДДУ — от первой выдачи до полного погашения
    # (`object_financing`). Прежде БРИДЖ стоял в календаре любого проекта.
    _nonres_objects = (fin.get("nonres") or {}).get("objects") or []
    if float(fin.get("peak_bridge") or 0.0) > 0.5 or not _nonres_objects:
        add_event("БРИДЖ", op["project_start"], bridge_end, group="Финансирование")
    for _item in _nonres_objects:
        _rows = [r for r in _item.get("rows") or [] if float(r.get("nonres_loan_draw") or 0) > 0]
        _repaid = (_item.get("financing") or {}).get("repaid_month") or _item.get("horizon_end")
        if _rows and _repaid:
            add_event(f"Кредит объекта — {_item.get('title')}", d(_rows[0]["month"]), d(_repaid),
                      group="Финансирование")
    add_event("РнС", op["permit"], group="Ключевые вехи", kind="milestone")
    add_event("Старт продаж", op["sales_start"], group="Ключевые вехи", kind="milestone")
    if not is_nonresidential(x):
        add_event("Строительство ЖК", op["permit"], op["rve"], group="Строительство")
    if any(v > 0 for v in (op["capex_amounts"].get("utilities", 0), op["capex_amounts"].get("landscaping", 0))):
        add_event("Сети и благоустройство", op["permit"], op["rve"], group="Строительство")

    if str(x.get("social_mode")) == "Денежная компенсация":
        add_event("Социальный платёж", d(x["social_comp_date"]), group="Социальная нагрузка", kind="milestone")
    else:
        if n(x, "kindergarten_places"):
            add_event("ДОО", d(x["kindergarten_start"]), add_months(d(x["kindergarten_start"]), int(n(x, "kindergarten_months", 24))), group="Социальная нагрузка")
        if n(x, "school_places"):
            add_event("СОШ", d(x["school_start"]), add_months(d(x["school_start"]), int(n(x, "school_months", 30))), group="Социальная нагрузка")
        if n(x, "clinic_capacity"):
            add_event("Поликлиника", d(x["clinic_start"]), add_months(d(x["clinic_start"]), int(n(x, "clinic_months", 24))), group="Социальная нагрузка")

    # Календарь показывает стройку, а не продажу: переданный городу объект
    # строится ровно так же, и его срок в проекте виден.
    for _obj in standalone_objects_report_order():
        if not b(x, _obj.enabled_key):
            continue
        _start = d(x[f"{_obj.prefix}_start"])
        _name = (_CALENDAR_OBJECT_LABELS.get(_obj.key)
                 or _PRODUCT_SPEC_LABELS.get(_obj.key) or _obj.tep_label or _obj.label)
        if _obj.sale_gate and not object_is_sold(x, _obj):
            _name += " (передаётся городу)"
        add_event(_name, _start,
                  add_months(_start, int(n(x, f"{_obj.prefix}_months", _obj.default_months))),
                  group="Отдельные объекты")

    sales_months = [month for sched in op["revenue_product_schedules"].values() for month in sched]
    sales_end = max(sales_months) if sales_months else add_months(op["rve"], int(n(x, "residual_sales_months", 6)))
    add_event("Продажи", op["sales_start"], sales_end, group="Продажи")
    add_event("РВЭ / РНВ", op["rve"], group="Ключевые вехи", kind="milestone")
    add_event("Окончание продаж", sales_end, group="Ключевые вехи", kind="milestone")

    pf_active_months = [d(row["month"]) for row in fin["rows"] if (row.get("pf_balance", 0) or row.get("pf_draw", 0) or row.get("pf_repayment", 0))]
    if pf_active_months:
        add_event("Проектное финансирование", min(pf_active_months), max(pf_active_months), group="Финансирование")

    calendar_start = min(d(e["start"]) for e in calendar_events)
    calendar_end = max(d(e["end"]) for e in calendar_events)

    # Фактический пик БРИДЖа расшифровывается по статьям: расчётный лимит имеет
    # разбивку по целям, а пик — не имел, и разница между ними («остальное
    # вашими») читалась только глазами по структуре расходов.
    monthly_detail = _monthly_detail(op, timeline, row_by_month)
    bridge_peak_month = _bridge_peak_month(fin["rows"])

    return {
        "dates": {
            "project_start": op["project_start"].isoformat(),
            "permit": op["permit"].isoformat(),
            "sales_start": op["sales_start"].isoformat(),
            "rve": op["rve"].isoformat(),
            # Дата платежа компенсации — не всегда та, что введена: банк держит
            # её в лимите БРИДЖа, поэтому платёж не выходит за бридж-период.
            # Без этой строки перенос было бы видно только по пику долга.
            "social_cash": op["social_cash_date"].isoformat(),
        },
        "tep": {
            "rows": tep_rows,
            "total": tep_total,
            "core_above_gns": op["core_above_gns"],
            "core_under_gns": op["core_under_gns"],
            "project_articles_sqm": op["project_articles_sqm"],
            "project_articles_area": op["project_articles_area"],
        },
        "revenue": {"total": total_revenue, **op["revenue_by_product"]},
        "revenue_structure": revenue_structure({"total": total_revenue, **op["revenue_by_product"]},
                                               monetizable_saleable_sqm),
        # land_rights_gross и land_rights_relief — справочные величины платы
        # до льготы: в total их нет, а таблица расходов на странице рисует все
        # ключи подряд — и показывала их сырыми именами. Валовая плата и льгота
        # уходят наружу полем vri.totals, не статьями CAPEX.
        "capex": {"total": total_capex,
                  **{key: value for key, value in op["capex_amounts"].items()
                     if key not in ("land_rights_gross", "land_rights_relief")}},
        # Удельные статей CAPEX — каждая на свою базу (решение 4 ревизии):
        # страница их печатает, а не делит сама.
        "capex_units": capex_unit_rows(
            {"total": total_capex,
             **{key: value for key, value in op["capex_amounts"].items()
                if key not in ("land_rights_gross", "land_rights_relief")}}, bases),
        "vri": {**op["vri"], "benefits": vri_benefits_for(x, t)},
        # Смета каждого объекта вне ДДУ — его статья и начисленные от неё
        # генподряд, техзаказчик и резерв (`object_cost_parts`).
        "object_costs": op.get("object_cost_parts") or {},
        # Нормативная потребность нежилых объектов в машино-местах. Считается
        # всегда: офисник или ТЦ без парковки — это не «ноль мест», а не
        # заданный вопрос (владелец, 24.08.2026). Норма приходит готовой из
        # `parking_norms` вместе со своим основанием; второй экономики тут нет.
        "parking": object_parking,
        # Отчёт о наложении факта. Пустой словарь на обычном расчёте, а на
        # действующем проекте — что подменено, чем и с какими оговорками.
        # Наружу он идёт потому, что наложение меняет числа: приближение,
        # видное только в коде, неотличимо от точного расчёта.
        "actuals": actuals_report,
        "commercial_costs": fin["commercial_costs"],
        "finance": fin,
        # Стоимость сделки двумя строками и итогом: цена участка/права и
        # выкуп ЗУ/ОКС у третьих лиц. Одна разбивка на все поверхности; своим
        # ключом, а не в сводке, — числа сводки держит сторож эталонов.
        "deal": {
            "price_mln": n(x, "purchase_price_mln"),
            "buyout_mln": n(x, "land_buyout_mln"),
            "total_mln": n(x, "purchase_price_mln") + n(x, "land_buyout_mln"),
        },
        "summary": {
            "revenue": total_revenue,
            "capex": total_capex,
            "commercial_costs": fin["commercial_costs"],
            "ebitda": ebitda,
            "financing_cost": fin["financing_cost"],
            "profit_before_tax": after_finance_pre_tax,
            "profit_tax": fin["profit_tax"],
            # Ставка едет в сводке рядом с налогом: свод очередей считает
            # налог заново как один налогоплательщик и берёт ставку отсюда,
            # а не вторую копию из мастер-вводных.
            "profit_tax_rate": fin.get("profit_tax_rate", 0.0),
            # НДС живёт в summary рядом с налогом на прибыль, а не только в
            # finance: поверхности читают сводку, и без этого ключа налог,
            # уменьшающий чистую прибыль на миллиард, нигде не показывался.
            "vat": fin.get("vat", 0.0),
            "net_profit": net_profit,
            "margin": net_profit / total_revenue if total_revenue else 0.0,
            "llcr": fin["llcr"],
            "ending_pf": fin.get("ending_pf", 0.0),
            "rve_pf_shortfall": fin.get("rve_pf_shortfall", 0.0),
            # Непокрытая потребность в ПФ: одобренного лимита не хватило.
            # Движок считал её с самого начала и никуда не отдавал — она жила
            # в `finance`, а свод и отчёт читают отсюда, и вердикт вместе с
            # ними. Проект с дырой в треть нужных денег выглядел целым.
            "pf_shortfall": fin.get("pf_shortfall", 0.0),
            "pf_shortfall_month": fin.get("pf_shortfall_month", ""),
            "scenario_revenue_multiplier": n(x, "scenario_revenue_multiplier", 1.0),
            "scenario_cost_multiplier": n(x, "scenario_cost_multiplier", 1.0),
            # Что за проект считали — и что от жилья в нём осталось. Второе
            # пусто у жилого проекта по построению и у нежилого, собранного
            # страницей: она обнуляет и называет убранное. Непусто — значит
            # проект пришёл файлом, ссылкой или мостом КРТ, и во вводных лежат
            # жилые метры, которые расчёт не считает (`residential_excluded`).
            "project_kind": project_kind(x),
            "project_kind_leftovers": kind_leftovers,
            # Состав объектов, которым считал расчёт, и непринятое из
            # присланного — с причиной, а не молчаливым пропуском.
            "object_instances": list(project_object_instances(x)),
            "object_instance_notes": instance_notes,
            "npv": project_npv,
            "npv_equity": equity_npv,
            "irr_equity": irr_equity,
            "full_project_cost": full_project_cost,
            "monetizable_saleable_sqm": monetizable_saleable_sqm,
            "apartment_saleable_sqm": apartment_saleable_sqm,
            "average_apartment_price_th": avg_apartment_price,
            # Каждый удельный — на свою базу (решение 4 ревизии книги):
            # расходы — на суммарную площадь в ГНС и для сравнения с ценой на
            # продаваемую; EBITDA и прибыль — на продаваемую.
            "full_cost_per_saleable_th": full_cost_per_saleable,
            "full_cost_per_total_area_th": per_sqm_th(full_project_cost, construction_volume_sqm),
            "capex_per_total_area_th": per_sqm_th(total_capex, construction_volume_sqm),
            "construction_cost_per_gns_th": construction_cost_per_gns,
            "construction_cost_per_saleable_th": per_sqm_th(
                construction_capex, monetizable_saleable_sqm),
            "ebitda_per_saleable_th": ebitda_per_saleable,
            "net_profit_per_saleable_th": net_profit_per_saleable,
            "unit_bases": bases,
            "project_gns_sqm": project_gns_sqm,
            # Обе половины базы — рядом с ней: удельный показатель без второй
            # базы читается как другой показатель.
            "underground_gns_sqm": underground_gns_sqm,
            "construction_volume_sqm": construction_volume_sqm,
            # Благоустройство меряется своей площадью, а не строительным
            # объёмом: число без основания читается как другой показатель, и
            # основание едет рядом.
            "landscaping_area_sqm": op.get("landscaping_area_sqm", 0.0),
            "landscaping_basis": op.get("landscaping_basis", ""),
            "landscaping_money_basis": op.get("landscaping_money_basis", ""),
            # Пустая статья называется вслух: нулевая строка в структуру
            # расходов не попадает, и её отсутствие неотличимо от ответа
            # методики «благоустройства здесь не нужно».
            "landscaping_gap": landscaping_gap(
                op["capex_amounts"].get("landscaping", 0.0),
                op.get("landscaping_basis", ""), project_gns_sqm),
            "landscaping_by_class_th": per_sqm_th(
                op.get("landscaping_by_class", 0.0), project_gns_sqm),
            "landscaping_by_rate": bool(op.get("landscaping_by_rate")),
            # Статья считается на своей физической базе — дворе, — а сравнивают
            # её с чужой сметой и со сводом «Статистики», которые меряют метр
            # ГНС. Производная считается ЗДЕСЬ и один раз: посчитанная на
            # экране, она была бы вторым счётом той же величины. Пара
            # обязательна — одинокое «на метр» читается как другой показатель.
            "landscaping_per_gns_th": per_sqm_th(
                op["capex_amounts"].get("landscaping", 0.0), project_gns_sqm),
            "landscaping_per_saleable_th": per_sqm_th(
                op["capex_amounts"].get("landscaping", 0.0),
                monetizable_saleable_sqm),
            # Третьего «на метр» у этой статьи больше нет. Оно было, пока поле
            # ставки умножалось на метры ДОМА, а строка выше делила те же
            # деньги на ГНС ПРОЕКТА: два числа под одним словом «ГНС»,
            # различающиеся на соцобъекты и ОСЗ. Базы сведены — показатель поля
            # и есть `landscaping_per_gns_th`, считать его вторым способом
            # незачем.
            "total_expenses": total_expenses,
            "social_payment": op["capex_amounts"].get("social", 0.0),
            "social_payment_mode": str(x.get("social_mode", "")),
            # Режимов три, а проверка знала два: при «строительстве и
            # компенсации» в CAPEX лежит и стройка, и денежная часть, а
            # ожидание считалось по одной стройке — самопроверка всегда
            # падала, и отчёт 2.0 писал «социалка расходится с режимом» на
            # исправном расчёте (замечание владельца, 19.08.2026).
            "social_in_capex_check": abs(
                op["capex_amounts"].get("social", 0.0)
                - (
                    sum(op.get("social_construction_breakdown", {}).values())
                    + (op.get("imported_social_compensation", 0.0)
                       if str(x.get("social_mode", "")) == SOCIAL_MODE_BOTH else 0.0)
                    if str(x.get("social_mode", "")) in ("Строительство", SOCIAL_MODE_BOTH)
                    else op.get("imported_social_compensation", 0.0)
                )
            ) < 1.0,
            "social_program": op.get("social_program", {}),
            # Что строит проект — выше; здесь то, за что он платит. При
            # денежной компенсации первое пустое, и без второго в отчёте не
            # остаётся ни одного числа о социалке, кроме суммы.
            "social_required": social_required_program(
                x, t, built=op.get("social_program") or {}),
            "social_payment_breakdown": {
                "construction": {
                    "kindergarten_mln": op.get("social_construction_breakdown", {}).get("kindergarten", 0.0) / 1_000_000,
                    "school_mln": op.get("social_construction_breakdown", {}).get("school", 0.0) / 1_000_000,
                    "clinic_mln": op.get("social_construction_breakdown", {}).get("clinic", 0.0) / 1_000_000,
                },
                "compensation": {
                    "kindergarten_mln": n((x.get("_glavapu_import") or {}).get("normalized", {}), "social_compensation_kindergarten_mln"),
                    "school_mln": n((x.get("_glavapu_import") or {}).get("normalized", {}), "social_compensation_school_mln"),
                    "clinic_mln": n((x.get("_glavapu_import") or {}).get("normalized", {}), "social_compensation_clinic_mln"),
                },
            },
        },
        "report": {
            "project_class": project_class_view(x),
            "nonres_strategy": nonres_report(fin.get("nonres")),
            "hotel": hotel_report(fin.get("hotel")),
            "nonres_financing": nonres_financing_report(fin.get("nonres")),
            "nonres_costs_label": nonres_costs_label(x),
            "equity_participation": equity_participation_report(
                timeline, equity_cf, fin, discount_rate=discount_rate, irr=irr_equity),
            "layout": report_layout(x, fin, equity_cf),
            "products": products_report,
            # График платежей за покупку — как посчитано: даты, суммы, доли и
            # оговорки разбора. Одна строка в дату сделки — прежнее поведение.
            "purchase": op.get("purchase_schedule") or {},
            "unit_economics": unit_economics,
            "construction_costs": construction_costs,
            "apartment_sales": apartment_sales,
            "expense_structure": expense_structure,
            "calendar": {
                "start": calendar_start.isoformat(),
                "end": calendar_end.isoformat(),
                "events": calendar_events,
            },
            "financing": {
                "calculated_bridge": fin["calculated_bridge_limit"],
                "calculated_bridge_parts": fin.get("calculated_bridge_parts") or {},
                "actual_bridge": fin["peak_bridge"],
                "actual_bridge_month": bridge_peak_month,
                "own_funds": fin.get("own_funds_used", 0.0),
                "own_funds_available": fin.get("own_funds_available", 0.0),
                "project_cash": fin.get("project_cash_used", 0.0),
                "actual_bridge_structure": _bridge_actual_structure(
                    [monthly_detail], bridge_peak_month, fin["peak_bridge"],
                    _own_funds_by(fin["rows"], bridge_peak_month),
                    _project_cash_by(fin["rows"], bridge_peak_month)),
                "pf_peak": fin["peak_pf"],
                "pf_uncovered_peak": fin.get("peak_uncovered_pf", 0.0),
                "rve_pf_before_repayment": fin.get("rve_pf_before_repayment", 0.0),
                "rve_escrow_release": fin.get("rve_escrow_release", 0.0),
                # Раскрытое и погашенное — разные величины: эскроу гасит СВОЙ
                # ПФ, излишек уходит в кассу. Ключ считался, суммировался по
                # очередям и до экрана не доезжал — строка «Из него на
                # погашение ПФ» показывала ноль на любом проекте.
                "rve_pf_repayment": fin.get("rve_pf_repayment", 0.0),
                "rve_pf_shortfall": fin.get("rve_pf_shortfall", 0.0),
                "pf_limit_required": fin.get("pf_limit_required", 0.0),
                "pf_limit_approved": fin.get("pf_limit_approved", 0.0),
                "pf_shortfall": fin.get("pf_shortfall", 0.0),
                # Та же величина в миллионах: адаптер `/v2` считать не вправе
                # (в нём запрещена всякая арифметика, и это проверяется), а
                # оговорка вердикта величину ПЕЧАТАЕТ — значит единица часть
                # числа, и делить её должен тот, кто её посчитал.
                "pf_shortfall_mln": float(fin.get("pf_shortfall", 0.0) or 0.0) / 1_000_000,
                "pf_shortfall_month": fin.get("pf_shortfall_month", ""),
                # Чем эскроу перекрывает обязательство — считается один раз в
                # движке. Ключ, добавленный только в `finance`, до поверхностей
                # не доезжает: у отчёта свой экземпляр.
                "escrow_cover": fin.get("escrow_cover") or {},
                "pf_limit": fin["pf_limit"],
                "avg_bridge_rate": fin["avg_bridge_rate"],
                "avg_bridge_key_rate": fin.get("avg_bridge_key_rate", 0.0),
                "current_key_rate": fin.get("current_key_rate", 0.0),
                "bridge_spread": fin.get("bridge_spread", 0.0),
                "current_bridge_rate": fin.get("current_bridge_rate", 0.0),
                "bridge_rate_at_project_start": fin.get("bridge_rate_at_project_start", 0.0),
                "avg_pf_rate": fin["avg_pf_rate"],
                "avg_pf_effective_rate": fin["avg_pf_effective_rate"],
                "avg_pf_base_rate": fin["avg_pf_base_rate"],
                "avg_pf_key_rate": fin["avg_pf_key_rate"],
                "pf_special_rate": fin["pf_special_rate"],
                # Ступени и сколько месяцев отработала каждая: средняя ставка
                # без этого — число, которое банку нечем объяснить.
                "pf_special_steps": fin.get("pf_special_steps") or [],
                "interest_and_fees": fin["financing_cost"],
                "ending_pf": fin.get("ending_pf", 0.0),
                # Принятый долг предыдущей очереди — не «новые деньги»: лимита
                # он не выбирает, но проценты несёт и стоит в знаменателе LLCR.
                # Без своей строки он растворяется в остатке ПФ, и очередь
                # выглядит взявшей больше, чем брала.
                "carried_debt_in": fin.get("carried_debt_in", 0.0),
                "debt_carried_out": fin.get("debt_carried_out", 0.0),
                # Сколько не покрыл раскрытый эскроу и когда банк зафиксировал
                # дефолт. У отчёта свой экземпляр финансирования, и ключ,
                # добавленный только в `finance`, до поверхностей не доезжает.
                "rve_unpaid": fin.get("rve_unpaid", 0.0),
                "default_date": fin.get("default_date"),
                # Пик тела и пик с капитализированными процентами — разные
                # показатели: книга ведёт остаток сразу с капитализацией, и
                # одинаковое слово «пик» читалось как расхождение моделей.
                "bridge_peak_capitalized": fin["peak_bridge"]
                + fin.get("transferred_bridge_interest", 0.0),
            }
        },
        "cashflow": {
            "months": [month.isoformat() for month in timeline],
            "project": project_cf,
            "equity": equity_cf,
            "profit_tax": [
                float(row_by_month.get(month, {}).get("profit_tax", 0.0) or 0.0)
                for month in timeline
            ],
        },
        # Помесячная детализация финмодели: статьи расходов, продукты продаж и
        # физические объёмы по месяцам. Суммы сходятся с итогами выше.
        "monthly": monthly_detail,
        "excel_control": EXCEL_CONTROL,
        "notes": {
            "llcr": "LLCR рассчитан по структуре действующего листа LLCR: поступления минус операционные/инвестиционные расходы плюс ПФ, делённые на ПФ и стоимость долга.",
            "finance": "Помесячная логика БРИДЖ/ПФ/эскроу перенесена в код. До окончательной замены Excel требуется контрольная сверка нескольких сценариев по месяцам.",
            "tax": "Налог на прибыль начисляется накопительно не ранее РВЭ: маржа реализованных основных продуктов и отдельных объектов КРТ минус выплаченные проценты и комиссии.",
        },
    }


_OBJECT_SCHEDULE_PREFIX = {
    **{obj.key: obj.prefix for obj in standalone_objects()},
    # Основные продукты — одна лестница на четверых.
    "apartments": "core", "ground_commercial": "core",
    "underground_parking": "core", "storage": "core",
}


def _product_schedule_fields(notes: dict[str, dict[str, Any]], key: str) -> dict[str, Any]:
    prefix = _OBJECT_SCHEDULE_PREFIX.get(key)
    item = (notes or {}).get(prefix or "") or {}
    return {
        "sales_profile": item.get("sales_profile", ""),
        "price_ladder": item.get("price_ladder", ""),
        "price_stages": list(item.get("price_stages") or []),
        "schedule_applied": bool(item.get("profile_applied") or item.get("steps_applied")),
        "schedule_warnings": list(item.get("warnings") or []),
    }


_MONTHLY_CAPEX_LABELS: dict[str, str] = {
    "purchase": "Покупка / цена входа",
    "land_rights": "Земельные правоотношения / смена ВРИ",
    "vri_security": "Обеспечение обязательства по ВРИ",
    "vri_interest": "Проценты по рассрочке ВРИ",
    "ird": "ИРД и согласования",
    "design_p": "Проектирование, стадия П",
    "design_rd": "Проектирование, стадия РД",
    "demolition": "Снос и демонтаж",
    "resettlement": "Расселение",
    "preparation": "Подготовительные работы",
    "main_above": "Основное строительство, наземная часть",
    "main_under": "Основное строительство, подземная часть",
    "utilities": "Наружные инженерные сети",
    "site_maintenance": "Содержание стройплощадки",
    "author_supervision": "Авторский надзор",
    "technical_supervision": "Технический заказчик / стройконтроль",
    "project_management": "Управление проектом",
    "landscaping": "Благоустройство",
    "commissioning": "Сдача и ввод",
    "social": "Социальная нагрузка",
    "offices": "МФОЦ / офисы",
    "standalone_retail": "ТЦ / коммерция ОСЗ",
    "above_parking": "Наземный паркинг",
    "sports": "ФОК / медцентр",
    "hotel": "Гостиница — здание",
    "hotel_ffe": "Гостиница — мебель и оборудование (FF&E)",
    "gc_fee": "Вознаграждение генподрядчика",
    "reserve": "Резерв",
}
# Второй объект — строкой за своим продуктом, как в `_MODEL_CAPEX_LABELS`.
_MONTHLY_CAPEX_LABELS = dict(_after_their_product(
    list(_MONTHLY_CAPEX_LABELS.items()), lambda obj: obj.group_label or obj.label))


def _monthly_series(schedule: dict[date, float], timeline: list[date]) -> list[float]:
    return [float(schedule.get(month, 0.0) or 0.0) for month in timeline]


def _monthly_detail(
    op: dict[str, Any], timeline: list[date], row_by_month: dict[date, dict[str, Any]]
) -> dict[str, Any]:
    """Помесячная детализация: расходы по статьям, продажи по продуктам, объёмы."""
    capex_by_article = op.get("capex_by_article") or {}
    revenue_schedules = op.get("revenue_product_schedules") or {}
    quantity_schedules = op.get("quantity_product_schedules") or {}

    def product_label(key: str) -> str:
        return str((TEP_DEFAULT.get(key) or {}).get("label") or key)

    def order(key: str) -> int:
        keys = list(_MONTHLY_CAPEX_LABELS)
        return keys.index(key) if key in keys else len(keys)

    costs = [
        {
            "key": key,
            "label": _MONTHLY_CAPEX_LABELS.get(key, key),
            "total": round(sum(schedule.values()), 2),
            "values": [round(value, 2) for value in _monthly_series(schedule, timeline)],
        }
        for key, schedule in capex_by_article.items()
        if abs(sum(schedule.values())) > 1e-9
    ]
    costs.sort(key=lambda item: order(item["key"]))
    revenue = [
        {
            "key": key,
            "label": product_label(key),
            "total": round(sum(schedule.values()), 2),
            "values": [round(value, 2) for value in _monthly_series(schedule, timeline)],
        }
        for key, schedule in revenue_schedules.items()
        if abs(sum(schedule.values())) > 1e-9
    ]
    quantity = [
        {
            "key": key,
            "label": product_label(key),
            "total": round(sum(schedule.values()), 4),
            "values": [round(value, 4) for value in _monthly_series(schedule, timeline)],
        }
        for key, schedule in quantity_schedules.items()
        if abs(sum(schedule.values())) > 1e-9
    ]
    return {
        "months": [month.isoformat() for month in timeline],
        "costs": costs,
        "revenue": revenue,
        "quantity": quantity,
        "commercial_costs": [round(value, 2) for value in _monthly_series(op.get("operating") or {}, timeline)],
        "capex_total": [round(value, 2) for value in _monthly_series(op.get("capex") or {}, timeline)],
        "profit_tax": [
            round(float((row_by_month.get(month) or {}).get("profit_tax", 0.0) or 0.0), 2)
            for month in timeline
        ],
    }


def _bridge_peak_month(rows: list[dict[str, Any]]) -> str:
    peak = max(rows, key=lambda row: float(row.get("bridge_balance") or 0.0), default=None)
    if not peak or float(peak.get("bridge_balance") or 0.0) <= 0:
        return ""
    month = peak.get("month")
    return month.isoformat() if hasattr(month, "isoformat") else str(month)


def _bridge_balance_at(rows: list[dict[str, Any]], month: str) -> float:
    """Остаток БРИДЖа этой линии в названный месяц; нет строки — линии нет."""
    for row in rows:
        row_month = row.get("month")
        row_month = row_month.isoformat() if hasattr(row_month, "isoformat") else str(row_month)
        if row_month == month:
            return float(row.get("bridge_balance") or 0.0)
    return 0.0


def _queues_on_bridge(phase_items: list[dict[str, Any]], month: str) -> dict[str, list[str]]:
    """Чей БРИДЖ открыт в месяц пика свода — и чей уже закрыт или ещё не начат.

    У каждой очереди своя линия до открытия её ПФ. Пик свода приходится на
    месяц, когда открыты линии не всех очередей: расшифровка, сложившая
    оплаченное ВСЕМИ очередями, показывала 148% по одной статье и 2,5 млрд ₽
    проектирования трёх очередей, из которых на БРИДЖе стояла одна.
    """
    on_bridge: list[str] = []
    refinanced: list[str] = []
    not_started: list[str] = []
    for item in phase_items:
        name = str(item.get("name") or "")
        rows = ((item.get("result") or {}).get("finance") or {}).get("rows") or []
        if _bridge_balance_at(rows, month) > 0:
            on_bridge.append(name)
            continue
        opened = [
            (r.get("month").isoformat() if hasattr(r.get("month"), "isoformat") else str(r.get("month")))
            for r in rows if float(r.get("bridge_balance") or 0.0) > 0
        ]
        if opened and max(opened) < month:
            refinanced.append(name)
        else:
            not_started.append(name)
    return {"on_bridge": on_bridge, "refinanced": refinanced, "not_started": not_started}


def _own_funds_by(rows: list[dict[str, Any]], month: str) -> float:
    """Сколько собственных средств вложено к этому месяцу включительно."""
    if not month:
        return 0.0
    total = 0.0
    for row in rows:
        row_month = row.get("month")
        iso = row_month.isoformat() if hasattr(row_month, "isoformat") else str(row_month)
        if iso <= month:
            total += float(row.get("own_funds_draw") or 0.0)
    return total


def _project_cash_by(rows: list[dict[str, Any]], month: str) -> float:
    """Сколько свободного cash проекта направлено в очередь к месяцу."""
    if not month:
        return 0.0
    total = 0.0
    for row in rows:
        row_month = row.get("month")
        iso = row_month.isoformat() if hasattr(row_month, "isoformat") else str(row_month)
        if iso <= month:
            total += float(row.get("project_cash_draw") or 0.0)
    return total


def _bridge_actual_structure(monthlies: list[dict[str, Any]], peak_month: str,
                             peak_value: float, own_funds: float = 0.0,
                             project_cash: float = 0.0) -> list[dict[str, Any]]:
    """Что оплачено к месяцу пика БРИДЖа — по статьям.

    Расчётный лимит расшифрован по четырём целям методики, а фактический пик —
    ничем; разница между ними разбиралась перепиской, хотя это и есть то, что
    банк называет «остальное вашими». До открытия ПФ у проекта нет ни выручки,
    ни ПФ, поэтому остаток БРИДЖа в месяц пика равен всему, что к этому месяцу
    оплачено. Если сходится не до конца — расхождение показывается строкой, а не
    прячется в округление.
    """
    if not peak_month:
        return []
    totals: dict[str, float] = defaultdict(float)
    for monthly in monthlies:
        months = [str(month) for month in (monthly.get("months") or [])]
        upto = [index for index, month in enumerate(months) if month <= peak_month]
        for cost in monthly.get("costs") or []:
            values = cost.get("values") or []
            totals[str(cost.get("label") or "—")] += sum(
                float(values[index] or 0.0) for index in upto if index < len(values))
    rows = [{"label": label, "value": value}
            for label, value in totals.items() if value > 1_000_000]
    rows.sort(key=lambda item: -item["value"])
    # Часть оплаченного закрыта не банком: собственные средства уменьшают долг,
    # а не расходы, поэтому они стоят отдельной строкой со знаком минус — иначе
    # сумма статей перестала бы сходиться с пиком.
    if own_funds > 1_000_000:
        rows.append({"label": "Оплачено собственными средствами", "value": -own_funds})
    if project_cash > 1_000_000:
        rows.append({"label": "Оплачено свободным cash проекта", "value": -project_cash})
    paid = sum(item["value"] for item in rows)
    residual = float(peak_value or 0.0) - paid
    if abs(residual) > max(float(peak_value or 0.0) * 0.01, 1_000_000):
        rows.append({
            "label": "Покрыто выручкой и ПФ" if residual < 0 else "Проценты и капитализация",
            "value": residual,
        })
    base = float(peak_value or 0.0) or paid
    for item in rows:
        item["share"] = item["value"] / base if base else 0.0
    return rows


@app.get("/health")
def health() -> dict:
    # Выкатка сверяет ответ с тем коммитом, который выпускала: без этого
    # «поднялось» означает лишь «что-то поднялось». Данные тоже проверяются —
    # каталог примонтирован томом, и потерять его молча дороже всего.
    data_dir = Path(os.getenv("DEVELOPAID_DATA_DIR") or "data")
    # Свободное место — не украшение ответа: 18.08.2026 диск кончился молча,
    # выкатка упала на распаковке образа, а вход через бота стал отвечать
    # ошибкой без объяснения, потому что коды входа пишутся файлами. Заполненный
    # диск виден в /health раньше, чем в поведении.
    free_mb: float | None = None
    try:
        usage = shutil.disk_usage(data_dir if data_dir.exists() else Path("."))
        free_mb = round(usage.free / (1024 * 1024))
    except Exception:
        free_mb = None
    return {
        "status": "ok",
        "version": VERSION,
        "commit": COMMIT,
        "data_dir": str(data_dir),
        "data_writable": os.access(data_dir, os.W_OK) if data_dir.exists() else False,
        "disk_free_mb": free_mb,
        # Порог не абстрактный: образ выкатки весит два-три гигабайта, и ниже
        # этого следующая выкатка не пройдёт.
        "disk_low": (free_mb is not None and free_mb < 3072),
        # Браузер в образе — не подробность сборки. Его отсутствие выходит
        # наружу как «ТЭП посчитан формулами» и «PDF прежнего вида»: две разные
        # на вид поломки с одной причиной, и обе выглядят как штатная работа.
        # Здесь она названа до того, как о ней спросят.
        "browsers": browser_launch.diagnostics(),
    }


@app.get("/defaults")
def defaults() -> dict:
    return {
        "inputs": DEFAULT_INPUTS,
        "tep": TEP_DEFAULT,
        "rates": RATE_CURVE,
        "scenarios": SCENARIOS,
        "excel_control": EXCEL_CONTROL,
    }


def _normalized_phase_weights(values: Any, count: int, fallback: list[float] | None = None) -> list[float]:
    vals: list[float] = []
    if isinstance(values, list):
        for i in range(count):
            try:
                vals.append(max(0.0, float(values[i])))
            except Exception:
                vals.append(0.0)
    else:
        vals = [0.0] * count
    total = sum(vals)
    if total <= 0:
        base = fallback or [100.0 / count] * count
        vals = [float(base[i]) if i < len(base) else 0.0 for i in range(count)]
        total = sum(vals)
    return [v * 100.0 / total for v in vals]


def _default_phase_weights(count: int) -> list[float]:
    presets = {
        1: [100.0],
        2: [55.0, 45.0],
        3: [40.0, 32.0, 28.0],
        4: [32.0, 26.0, 22.0, 20.0],
        5: [28.0, 22.0, 19.0, 16.0, 15.0],
    }
    return presets.get(count, [100.0 / count] * count)


def _scale_tep_row(row: dict[str, Any], share_pct: float) -> dict[str, Any]:
    result = copy.deepcopy(row)
    factor = share_pct / 100.0
    # Гостевые и переданные места делятся вместе со своими: поле, которого нет
    # в этом списке, молча остаётся числом ПРОЕКТА в каждой очереди — у
    # выгрузки ГлавАПУ это девяносто гостевых мест, вычтенных из каждой
    # четверти паркинга вместо своей доли.
    for key in ("gns", "total_area", "useful", "saleable", "transfer", "units",
                "guest_units", "transfer_units", "under_gns", "parking_units",
                "parking_saleable_units"):
        if key in ("guest_units", "transfer_units",
                   "under_gns", "parking_units",
                   "parking_saleable_units") and key not in row:
            continue
        result[key] = n(result, key) * factor
    return result


def _integer_phase_allocations(total_units: float, weights: list[float]) -> list[int]:
    """Split indivisible units across phases while preserving the exact rounded total."""
    total = max(0, int(round(float(total_units or 0.0))))
    if not weights:
        return [total]
    norm = _normalized_phase_weights(weights, len(weights))
    raw = [total * w / 100.0 for w in norm]
    floors = [int(math.floor(v)) for v in raw]
    remainder = total - sum(floors)
    order = sorted(range(len(raw)), key=lambda i: (raw[i] - floors[i], norm[i]), reverse=True)
    for i in order[:remainder]:
        floors[i] += 1
    return floors


def _scale_tep_row_by_units(
    row: dict[str, Any],
    allocations: list[int],
    phase_index: int,
) -> dict[str, Any]:
    result = copy.deepcopy(row)
    total_units = float(n(row, "units"))
    allocated = int(allocations[phase_index]) if phase_index < len(allocations) else 0
    factor = (allocated / total_units) if total_units > 0 else 0.0
    for key in ("gns", "total_area", "useful", "saleable", "transfer"):
        result[key] = n(result, key) * factor
    for key in ("under_gns", "parking_units", "parking_saleable_units"):
        if key in row:
            result[key] = n(result, key) * factor
    result["units"] = float(allocated)
    # Место неделимо и в гостевых, и в переданных: доля очереди округляется,
    # но не может превысить её же мест — иначе очередь «продаёт» меньше нуля.
    for key in ("guest_units", "transfer_units"):
        if key not in row:
            continue
        result[key] = float(min(allocated, int(round(n(row, key) * factor))))
    return result


_PHASE_MASS_PRODUCTS = ("apartments", "ground_commercial", "underground_parking", "storage")

# Absolute queue TEP is the authoritative layer above legacy percentage weights.
# The aliases keep the atomic engine unchanged: several KRT products are read
# from inputs, while the rest are read directly from TEP rows.
# Отдельно стоящие объекты приходят из реестра: их приставки и меры там уже
# объявлены (`aliases`), и перечисление руками отставало бы на следующем
# объекте — ровно так пресет молча терял ФОК. Остальные строки своей вводной
# пары в реестре не имеют, и стоят здесь.
_PHASE_PRODUCT_INPUT_ALIASES = {
    **{obj.key: obj.aliases for obj in STANDALONE_OBJECTS},
    "underground_parking": {
        "gns": "underground_manual_gns_sqm", "units": "underground_manual_spaces",
    },
    "kindergarten": {"units": "kindergarten_places"},
    "school": {"units": "school_places"},
    "clinic": {"units": "clinic_capacity"},
}


def _explicit_phase_products(cfg: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Return sanitized absolute product TEP stored on a queue."""
    products = cfg.get("products") or {}
    if not isinstance(products, dict):
        return {}
    return {str(key): copy.deepcopy(value) for key, value in products.items()
            if key in TEP_DEFAULT and isinstance(value, dict)}


def _apply_explicit_phase_products(
    p_tep: dict[str, dict[str, Any]],
    p_inputs: dict[str, Any],
    cfg: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    """Overlay manually edited queue TEP and synchronize atomic input aliases."""
    explicit = _explicit_phase_products(cfg)
    # Соцобъект очереди меряется МЕСТАМИ, а не вписанными метрами: сколько его
    # в этой очереди, говорит таблица соцобъектов (`social_objects`), а метры
    # считает `social_tep_row` от мест. Наложить сюда вписанное значит
    # собрать строку из двух источников: редактор очереди правит ГНС,
    # продаваемую и штуки, а общую площадь оставляет от норматива — на 250
    # местах проекта это ГНС 9 999 при общей 4 500 и 111 местах, и ни одно из
    # трёх чисел не отвечает двум другим. Метры при этом уходят в строительный
    # объём, то есть в знаменатель всех удельных.
    explicit = {key: value for key, value in explicit.items()
                if key not in SOCIAL_TEP_FIELDS}
    # Переданные штуки правятся в очереди наравне с остальными полями:
    # приоритет у очереди, проектная строка — их сумма (владелец, 04.09.2026).
    numeric_fields = ("gns", "total_area", "useful", "saleable", "transfer", "units",
                      "transfer_units")
    for key, override in explicit.items():
        row = copy.deepcopy(p_tep.get(key) or TEP_DEFAULT[key])
        for field in numeric_fields:
            if field in override:
                row[field] = max(0.0, float(override.get(field) or 0.0))
        # Очередь объявила передаваемую и не объявила продаваемую — значит
        # вычесть переданное обязан движок. Правило «переданные метры строятся,
        # но не продаются» было закрыто на СТРАНИЦЕ и только там: проект,
        # приехавший пресетом КРТ, файлом или ссылкой, продавал метры, отданные
        # городу, — 5 000 м² квартир это 2 163,7 млн ₽ выручки, которой нет.
        # Объявлены оба числа — приоритет у них: продаваемая очереди уже нетто,
        # и второе вычитание отняло бы переданное дважды.
        if "transfer" in override and "saleable" not in override:
            gross = max(n(row, "useful"), n(row, "saleable"))
            row["useful"] = gross
            row["saleable"], _excess = saleable_after_transfer(gross, row.get("transfer"))
        if override.get("generates_revenue") is False:
            row["saleable"] = 0.0
        # Объявленная очередью строка не пересчитывается по нормативу: у
        # соцобъекта это требование договора, а не наша оценка.
        row[TEP_ROW_DECLARED] = True
        p_tep[key] = row
        for field, input_key in _PHASE_PRODUCT_INPUT_ALIASES.get(key, {}).items():
            p_inputs[input_key] = float(row.get(field) or 0.0)
        obj = _BY_KEY.get(key)
        if obj is not None:
            p_inputs[obj.enabled_key] = _object_row_is_built(obj, row)
    return explicit


def _object_row_is_built(obj: StandaloneObject, row: dict[str, Any]) -> bool:
    """Есть ли объект в строке ТЭП очереди — по его мере, а не по имени.

    Цепочка «если офисы, иначе ТЦ, иначе паркинг» молча не знала бы второго
    офисника. Объект, который может уйти городу, стоит и при одних переданных
    метрах: он строится в любом случае.
    """
    if obj.measure == "spaces":
        return bool(row.get("gns") or row.get("units"))
    return bool(row.get("gns") or row.get("saleable")
                or (obj.sale_gate and row.get("transfer")))


def _phase_tep_product_rows(
    t_master: dict[str, dict[str, Any]],
    phasing: dict[str, Any],
    count: int,
) -> tuple[list[dict[str, dict[str, Any]]], dict[str, list[float]]]:
    """Каноническое деление массовых продуктов по очередям.

    Единственное место, где ТЭП режется на очереди: движок собирает из этих
    строк вводные каждой фазы, а книга получает готовые числа. Раньше книга
    нормировала доли сама — с собственным запасным раскладом «поровну» против
    движкового пресета 40/32/28 — и умножала итог на дробную долю даже для
    паркинга, который движок раздаёт целыми местами: очереди расходились на
    ±1 машино-место и десятки метров ГНС. Дробные метры делятся долями как
    есть, штучные продукты — целыми с сохранением итога. Одна очередь —
    не деление: движок без очередей считает атомарно по сырому ТЭП с дробными
    местами, и округлять их здесь значило бы разойтись с ним на полместа.
    """
    products_cfg = (phasing or {}).get("products") or {}
    # Most projects keep offices, standalone retail and an above-ground garage
    # as one discrete object. A KRT project may contain several real office
    # objects in different queues, though. If the preset/user explicitly
    # supplies percentage weights for such a product, it becomes share-based
    # without changing the default behaviour of existing projects.
    split_products = list(_PHASE_MASS_PRODUCTS)
    split_products.extend(
        key for key in products_cfg
        if key in TEP_DEFAULT and key not in split_products
    )
    if count <= 1:
        return ([{key: copy.deepcopy(t_master[key])
                  for key in split_products if key in t_master}],
                {key: [100.0] for key in split_products})
    default_weights = _default_phase_weights(count)
    product_weights = {
        key: _normalized_phase_weights(products_cfg.get(key), count, default_weights)
        for key in split_products
    }
    indivisible = {
        key: _integer_phase_allocations(n(t_master.get(key, {}), "units"), product_weights[key])
        for key in ("underground_parking", "storage")
        if key in t_master
    }
    rows: list[dict[str, dict[str, Any]]] = []
    for idx in range(count):
        per: dict[str, dict[str, Any]] = {}
        for key in split_products:
            if key not in t_master:
                continue
            if key in indivisible:
                per[key] = _scale_tep_row_by_units(t_master[key], indivisible[key], idx)
            else:
                per[key] = _scale_tep_row(t_master[key], product_weights[key][idx])
        rows.append(per)
    return rows, product_weights


_PHASE_INFLATABLE_INPUTS = (
    "ird_th_per_sqm",
    "design_p_th_per_sqm",
    "design_rd_th_per_sqm",
    "preparation_th_per_sqm",
    "main_above_th_per_sqm",
    "main_under_th_per_sqm",
    "utilities_th_per_sqm",
    "landscaping_th_per_sqm",
    "commissioning_th_per_sqm",
    "site_maintenance_th_per_sqm",
)


def _phase_cost_inflation_factor(phasing: dict[str, Any], offset_months: int) -> float:
    annual = float(phasing.get("cost_inflation_pct", 8.0) or 0.0) / 100.0
    return (1.0 + annual) ** (max(0, int(offset_months)) / 12.0)


def _phase_sales_price_inflation_factor(phasing: dict[str, Any], offset_months: int) -> float:
    """Annual market-price inflation between queue launches.
    Monthly price growth after each queue's own sales start stays in atomic calculate().
    """
    annual = float(phasing.get("sales_price_inflation_pct", 8.0) or 0.0) / 100.0
    return (1.0 + annual) ** (max(0, int(offset_months)) / 12.0)


def _zero_tep_row(row: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(row)
    for key in ("gns", "total_area", "useful", "saleable", "transfer", "units",
                "guest_units", "transfer_units",
                "under_gns", "parking_units", "parking_saleable_units"):
        if key not in row and key in ("guest_units", "transfer_units",
                                      "under_gns", "parking_units",
                                      "parking_saleable_units"):
            continue
        result[key] = 0.0
    return result


def _phase_object_share(master_row: Any, phase_row: Any) -> float:
    """Какая доля объекта досталась этой очереди — по его же метрам.

    Второго правила размещения тут нет: у объекта, посаженного в очередь
    целиком, доля равна единице в своей очереди и нулю в остальных; у
    разложенного долями — его доле; у объявленного метрами очереди — доле
    объявленного. Мера берётся та, что у объекта есть: ГНС, иначе продаваемая,
    иначе штуки — у наземного паркинга метров нет вовсе.
    """
    master = master_row or {}
    phase = phase_row or {}
    for key in ("gns", "saleable", "units"):
        base = n(master, key)
        if base > 0:
            return max(0.0, n(phase, key) / base)
    # Метров в строке проекта нет вовсе — объект задан одними вводными (так
    # приезжает проект файлом, ботом, API: строку ТЭП синхронизирует только
    # страница). Делить тогда нечем, и объект, включённый в этой очереди,
    # посажен в неё целиком: вызывающий гасит долю там, где объект выключен.
    # Прежний ноль терял гараж объекта во всех очередях, а книга его строила.
    return 1.0


def _phase_place_allocation(
    state: dict[str, tuple[float, int]],
    key: str,
    total: float,
    share: float,
) -> int:
    """Целые места по нарастающей доле — сумма по очередям равна проектной.

    Место неделимо, а доли очередей округляются каждая сама по себе: три
    очереди по трети от ста мест дали бы 33+33+33 и потеряли бы место.
    Считается нарастающим итогом, поэтому лишнее и недостающее забирает
    следующая очередь, а последняя закрывает остаток.
    """
    total_places = max(0, int(round(float(total or 0.0))))
    seen_share, given = state.get(key, (0.0, 0))
    seen_share = min(1.0, seen_share + max(0.0, share))
    target = int(round(total_places * seen_share))
    allocated = max(0, target - given)
    state[key] = (seen_share, given + allocated)
    return allocated


def _shift_iso(value: Any, months: int) -> Any:
    if not value:
        return value
    try:
        return add_months(d(value), months).isoformat()
    except Exception:
        return value


def _merged_nonres_reconciliation(fs: list[dict[str, Any]]) -> dict[str, Any]:
    """Сверка итогов объектов с проектом на своде очередей: суммы — суммой,
    «сошлось» — только если сошлось в каждой очереди."""
    recs = [(f.get("nonres") or {}).get("reconciliation") for f in fs]
    recs = [rec for rec in recs if rec]
    if not recs:
        return {}
    return {"reconciliation": {
        **_sum_dicts([{k: v for k, v in rec.items() if k != "ok"} for rec in recs]),
        "ok": all(rec.get("ok") for rec in recs)}}


def _sum_dicts(items: list[dict[str, Any]]) -> dict[str, float]:
    # Порядок ключей — порядок первой встречи, а не множества: порядок `set`
    # зависит от сида хеша процесса, и статьи расходов вставали на экране
    # вразнобой, от перезапуска к перезапуску по-разному.
    keys: dict[str, None] = {}
    for item in items:
        keys.update(dict.fromkeys(item.keys()))
    out: dict[str, float] = {}
    for key in keys:
        if key == "total":
            continue
        total = 0.0
        for item in items:
            try:
                total += float(item.get(key, 0.0) or 0.0)
            except Exception:
                pass
        out[key] = total
    out["total"] = sum(float(item.get("total", 0.0) or 0.0) for item in items)
    return out


def _combine_cashflows(results: list[dict[str, Any]], master_start: date) -> tuple[list[date], list[float], list[float]]:
    project_by_month: dict[date, float] = defaultdict(float)
    equity_by_month: dict[date, float] = defaultdict(float)
    for result in results:
        cf = result.get("cashflow") or {}
        months = cf.get("months") or []
        project = cf.get("project") or []
        equity = cf.get("equity") or []
        for i, month_text in enumerate(months):
            month = d(month_text)
            if i < len(project):
                project_by_month[month] += float(project[i] or 0.0)
            if i < len(equity):
                equity_by_month[month] += float(equity[i] or 0.0)
    if not project_by_month and not equity_by_month:
        return [], [], []
    end = max(list(project_by_month.keys()) + list(equity_by_month.keys()))
    months = month_range(master_start, end)
    return (
        months,
        [project_by_month.get(m, 0.0) for m in months],
        [equity_by_month.get(m, 0.0) for m in months],
    )


def _sweep_project_cash_enabled(phasing: dict[str, Any]) -> bool:
    """Кэш-свип включён, если его явно не выключили.

    Правило то же, что у платы за ВРИ: отсутствующий ключ — «не задано», а не
    «снято». Проект, сохранённый до появления признака, приедет без него, и
    прочитать это как выключенный значит молча посчитать его по прежней
    методике — той, где деньги от продаж передавшей очереди лежат у
    застройщика, пока банку не заплачено.
    """
    value = (phasing or {}).get("sweep_project_cash")
    return True if value is None else bool(value)


def _phase_financing_strategy(phasing: dict[str, Any]) -> str:
    """Normalize the public strategy; independent financing is the default."""
    raw = str(phasing.get("financing_strategy") or "").strip().lower()
    if raw in {"unified_project_cash", "unified", "project_cash"}:
        return "unified_project_cash"
    if raw == "independent":
        return "independent"
    return "independent"


def _phase_free_cash_schedule(result: dict[str, Any]) -> list[tuple[date, float]]:
    """Cash actually released to the sponsor after phase debt service.

    Atomic equity cash flow keeps pre-RVE revenue at zero (escrow), offsets
    bridge/PF draws against funded costs, and deducts repayments, interest and
    taxes.  Its positive dated values are therefore the conservative pool that
    may be used by a later queue without transferring a bank facility.
    """
    cashflow = result.get("cashflow") or {}
    return [
        (d(month_text), float(raw_value or 0.0))
        for month_text, raw_value in zip(
            cashflow.get("months") or [], cashflow.get("equity") or [])
        if float(raw_value or 0.0) > 1e-6
    ]


def _available_project_cash_schedule(
    sources: list[dict[str, Any]],
) -> dict[str, float]:
    schedule: dict[str, float] = defaultdict(float)
    for source in sources:
        remaining = float(source.get("remaining", 0.0) or 0.0)
        if remaining > 1e-6:
            schedule[str(source["month"])] += remaining
    return dict(schedule)


def _consume_project_cash_sources(
    sources: list[dict[str, Any]], result: dict[str, Any], target_phase: int,
) -> list[dict[str, Any]]:
    """Attribute actual dated project-cash draws to earlier queues FIFO."""
    transfers: list[dict[str, Any]] = []
    ordered = sorted(sources, key=lambda item: (str(item["month"]), int(item["phase"])))
    for row in (result.get("finance") or {}).get("rows") or []:
        # Только финансирование расходов: кэш-свип берётся не из общего пула
        # свободной кассы, а прямо с поступлений передавшей очереди, и из её
        # потока на капитал уже вычтен. Списать его отсюда значит вычесть одни
        # деньги дважды — пул опустеет там, где он полон.
        remaining_draw = float(row.get("project_cash_draw", 0.0) or 0.0)
        if remaining_draw <= 1e-6:
            continue
        draw_month = str(row.get("month") or "")
        for source in ordered:
            if int(source["phase"]) >= target_phase or str(source["month"]) > draw_month:
                continue
            available = float(source.get("remaining", 0.0) or 0.0)
            used = min(available, remaining_draw)
            if used <= 1e-6:
                continue
            source["remaining"] = available - used
            remaining_draw -= used
            transfers.append({
                "month": draw_month,
                "cash_month": str(source["month"]),
                "from_phase": int(source["phase"]),
                "to_phase": target_phase,
                "amount": used,
            })
            if remaining_draw <= 1e-6:
                break
        if remaining_draw > 1.0:
            raise RuntimeError("Project-cash draw exceeds available earlier-phase cash")
    return transfers


def _phase_financing_summary(
    phase_items: list[dict[str, Any]], strategy: str,
    transfers: list[dict[str, Any]],
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for index, item in enumerate(phase_items, start=1):
        result = item.get("result") or {}
        finance = result.get("finance") or {}
        permit = d((result.get("dates") or {}).get("permit"))
        before_rns = sum(
            max(0.0, float(row.get("project_costs", 0.0) or 0.0))
            for row in finance.get("rows") or []
            if d(row.get("month")) < permit
        )
        project_cash = float(finance.get("project_cash_used", 0.0) or 0.0)
        own_funds = float(finance.get("own_funds_used", 0.0) or 0.0)
        new_bridge = float(finance.get("bridge_draw_total", 0.0) or 0.0)
        rows.append({
            "phase": index,
            "name": str(item.get("name") or f"О{index}"),
            "pre_rns_costs": before_rns,
            "project_cash_used": project_cash,
            "own_funds": own_funds,
            "new_bridge": new_bridge,
            "peak_pf": float(finance.get("peak_pf", 0.0) or 0.0),
            "free_cash_generated": sum(value for _, value in _phase_free_cash_schedule(result)),
        })
    return {
        "strategy": strategy,
        "enabled": strategy == "unified_project_cash",
        "rows": rows,
        "transfers": transfers,
        "totals": {
            key: sum(float(row.get(key, 0.0) or 0.0) for row in rows)
            for key in ("pre_rns_costs", "project_cash_used", "own_funds", "new_bridge")
        },
        "excluded_sources": ["escrow", "bridge_limit", "pf_limit", "bank_debt", "future_profit"],
        "rule": (
            "Only dated positive cash released after debt service by an earlier queue "
            "may replace pre-RNS bridge/equity of a later queue."
        ),
    }


def _phase_tax_rate(results: list[dict[str, Any]]) -> float:
    """Ставка налога, по которой посчитаны очереди.

    Берётся из самих результатов, а не из вводных мастера: свод обязан
    пересчитывать налог по той же ставке, что уже применена к очередям.
    Вторая копия «двадцать пять процентов» рядом со сводом однажды
    разъехалась бы с расчётом, и обе выглядели бы верными.

    Очереди с разными ставками — не наш случай и молчать о нём нельзя:
    ноль отключает пересчёт, и свод остаётся суммой очередей.
    """
    rates = {round(float((r.get("summary") or {}).get("profit_tax_rate") or 0.0), 6)
             for r in results}
    rates.discard(0.0)
    return rates.pop() if len(rates) == 1 else 0.0


def _pf_obligation(row: dict[str, Any]) -> float:
    """Обязательство перед банком в этом месяце: тело плюс начисленное.

    Складывать их можно ровно здесь. С ЛИМИТОМ это число не сравнивают —
    капитализированные проценты лимит не выбирают (решение владельца,
    04.08.2026), и внешние сверки, прибавляющие payable к телу, находят
    «превышение», которого нет. С ЭСКРОУ сравнивают: эскроу и есть то, чем
    долг закрывают, и вопрос «сходятся они или нет» — про полное
    обязательство, а не про его тело.
    """
    if row.get("pf_obligation") is not None:
        return float(row.get("pf_obligation") or 0.0)
    return (float(row.get("pf_balance", 0.0) or 0.0)
            + float(row.get("pf_payable", 0.0) or 0.0))


def _mln_ru(value: float) -> str:
    return f"{value / 1e6:,.0f}".replace(",", " ") + " млн ₽"


def _month_ru(value: Any) -> str:
    parts = str(value or "")[:7].split("-")
    return f"{parts[1]}.{parts[0]}" if len(parts) == 2 else str(value or "")[:7]


def _escrow_cover(rows: list[dict[str, Any]], rve: Any = None) -> dict[str, Any]:
    """Чем эскроу перекрывает обязательство по ПФ — и где не перекрывает.

    График «Долг и эскроу» сравнивал счёт с ТЕЛОМ долга. Банку в дату
    раскрытия причитается и начисленное: проценты и комиссии копятся вне
    лимита и платятся кассой проекта. Пока их не видно, «эскроу выше долга»
    читается как «рассчитались» — хотя сверх эскроу проект платит деньгами, и
    в дефолтном случае разрыв ещё и больше показанного.

    Числа считаются здесь один раз: вкладка, PDF и очереди берут готовые.
    """
    gaps = [(_pf_obligation(row) - float(row.get("escrow", 0.0) or 0.0),
             str(row.get("month") or "")) for row in rows]
    peak_gap, peak_month = max(gaps, default=(0.0, ""))
    out: dict[str, Any] = {
        "peak_gap": max(peak_gap, 0.0),
        "peak_gap_month": peak_month if peak_gap > 0 else "",
        "peak_obligation": max((_pf_obligation(row) for row in rows), default=0.0),
        "peak_escrow": max((float(row.get("escrow", 0.0) or 0.0) for row in rows), default=0.0),
        "lines": [],
    }
    row = {}
    if rve is not None:
        row = next((item for item in rows
                    if str(item.get("month") or "") == rve.isoformat()), {})
    if row:
        repaid = float(row.get("pf_repayment", 0.0) or 0.0)
        unpaid = float(row.get("pf_balance", 0.0) or 0.0)
        released = float(row.get("escrow_release", 0.0) or 0.0)
        interest = float(row.get("interest_payment", 0.0) or 0.0)
        out.update({
            "rve": rve.isoformat(),
            "escrow_released": released,
            "pf_body": repaid + unpaid,
            "pf_body_repaid": repaid,
            "pf_body_unpaid": unpaid,
            "interest_due": interest,
            "obligation": repaid + unpaid + interest,
            "covered": unpaid <= 0,
        })
        if unpaid > 0:
            out["lines"].append(
                f"На раскрытии эскроу {_month_ru(out['rve'])} счёт даёт "
                f"{_mln_ru(released)} против тела ПФ {_mln_ru(out['pf_body'])} — "
                f"не хватает {_mln_ru(unpaid)}. Это дефолт по линии очереди, пока "
                f"банк не переоформит долг или не реструктурирует его.")
        else:
            out["lines"].append(
                f"На раскрытии эскроу {_month_ru(out['rve'])} счёт даёт "
                f"{_mln_ru(released)} и закрывает тело ПФ {_mln_ru(out['pf_body'])} "
                f"целиком.")
        if interest > 0:
            out["lines"].append(
                "Начисленные проценты и комиссии "
                f"{_mln_ru(interest)} эскроу не покрывает: они копятся вне лимита "
                "и платятся кассой проекта в ту же дату.")
    if rows:
        last = rows[-1]
        ending = float(last.get("pf_balance", 0.0) or 0.0)
        out["ending_month"] = str(last.get("month") or "")
        out["ending_unpaid"] = ending
        out["residual_sales"] = float(last.get("sales_after_rve_cumulative", 0.0) or 0.0)
        if ending > 1_000_000:
            out["lines"].append(
                f"На конец горизонта {_month_ru(out['ending_month'])} не погашено "
                f"{_mln_ru(ending)}: остаточных продаж после раскрытия хватило на "
                f"{_mln_ru(out['residual_sales'])}, и это всё, что модель считает "
                "источником — условий реструктуризации она не знает.")
        elif out.get("pf_body_unpaid", 0.0) > 0:
            out["lines"].append(
                f"Остаток закрыт продажами после раскрытия — {_mln_ru(out['residual_sales'])} "
                f"к {_month_ru(out['ending_month'])}. Банк ждал их в дату раскрытия, "
                "а не через месяцы: допущение модели, а не согласие банка.")
    if out["peak_gap"] > 0 and out["peak_gap_month"]:
        out["lines"].append(
            f"Наибольший разрыв между обязательством и эскроу — "
            f"{_mln_ru(out['peak_gap'])} в {_month_ru(out['peak_gap_month'])}: до "
            "раскрытия счёт только копится, а долг растёт вместе с процентами.")
    return out


def _escrow_phase_lines(results: list[dict[str, Any]], names: list[str],
                        rows: list[dict[str, Any]]) -> list[str]:
    """Чьё эскроу стоит на сводной линии, когда очередь начинает выбирать ПФ.

    Свод складывает счета очередей, и это верная сумма. Но даты раскрытия у
    них разные, и в месяц первой выборки ПФ второй очереди на линии стоит
    почти только эскроу ПЕРВОЙ: покрытие свода 0,58 против 0,22 у самой
    очереди. Читается это как «выборка второй очереди сразу покрыта»
    (владелец, 04.09.2026: «Это деньги первой очереди или что?»).

    Считается здесь один раз: экран рисует и печатает готовое.
    """
    by_month = {str(row.get("month") or ""): row for row in rows}
    lines: list[str] = []
    for index, result in enumerate(results):
        own = (result.get("finance") or {}).get("rows") or []
        start = next((str(row.get("month") or "") for row in own
                      if float(row.get("pf_draw", 0.0) or 0.0) > 0), "")
        if not start:
            continue
        total = by_month.get(start) or {}
        mine = next((row for row in own if str(row.get("month") or "") == start), {})
        escrow_all = float(total.get("escrow", 0.0) or 0.0)
        escrow_mine = float(mine.get("escrow", 0.0) or 0.0)
        others = escrow_all - escrow_mine
        if others <= 1e6:
            continue
        name = names[index] if index < len(names) else f"Очередь {index + 1}"
        # Полное объяснение — один раз. Три одинаковых хвоста подряд перестают
        # читаться, и это правило у нас уже записано на оговорке о дефолте.
        #
        # И само утверждение другое, чем стояло. Мерили мы вот что: в месяц
        # первой выборки на сводной линии столько-то, своих у очереди столько.
        # Прежний вывод «их деньги её выборку не покрывают» звучит как «не
        # хватило» — то есть обещает сравнение с выборкой, которой в строке
        # даже нет. Правда жёстче и проще: чужие счета её долг не гасят
        # ВООБЩЕ, сколько бы на них ни стояло.
        tail = ("Остальное — счета других очередей, и её долг они не гасят: "
                "у каждой очереди свой счёт и своя дата раскрытия."
                if not lines else "")
        lines.append(
            f"{name} открывает ПФ в {_month_ru(start)}: на сводной линии эскроу "
            f"{_mln_ru(escrow_all)}, из них своих {_mln_ru(escrow_mine)}."
            + (" " + tail if tail else ""))
    return lines


def _escrow_cover_with_phases(rows: list[dict[str, Any]], results: list[dict[str, Any]],
                              names: list[str]) -> dict[str, Any]:
    """Свод эскроу плюс оговорка о том, чьи это деньги."""
    out = _escrow_cover(rows)
    if len(results) > 1:
        out["phase_lines"] = _escrow_phase_lines(results, names, rows)
        # Порядок строк — это рассказ: сперва события по датам, потом выводы.
        # Прежде «наибольший разрыв в 06.2030» стоял ПЕРВЫМ, а под ним шли
        # 07.2029, 07.2030, 07.2031 — даты прыгали, и неверный порядок
        # читается как ошибка счёта.
        out["lines"] = out["phase_lines"] + list(out.get("lines") or [])
        # Имена очередей нужны рисунку: слои сложены снизу вверх в этом
        # порядке, и без имён подпись обещает то, чего не видно.
        out["phase_names"] = [str(name) for name in names]
    return out


def _aggregate_finance(results: list[dict[str, Any]],
                      names: list[str] | None = None,
                      pf_limit_general: float = 0.0) -> dict[str, Any]:
    month_map: dict[str, dict[str, float]] = {}
    # Поток и остаток складываются по-разному, и это не оттенок. Поток
    # (выборка, погашение, проценты, выручка) после конца горизонта очереди
    # равен нулю — её строк больше нет, и складывать нечего. А ОСТАТОК — долг,
    # счёт эскроу, начисленное к уплате — никуда не девается: очередь, чья
    # линия кончилась с непогашенным долгом, должна банку и дальше.
    #
    # Складывалось всё одинаково, и очередь после своего горизонта выпадала из
    # суммы месяца целиком. На пресете Нагатино О1 кончается 2033-01 с долгом
    # 3 193,61 млн, О2 — 2034-01 с 1 536,86: с этих месяцев сводный долг падал
    # ровно на них, и пик «одновременно открытых линий» выходил 94 250,21 млн
    # против 97 443,30 у книги. Движок при этом ЗНАЛ, что долг остался, — их
    # сумма 4 730,47 стоит у него в `ending_pf` свода до копейки, — но в
    # помесячный ряд она не попадала. Книга держала хвосты и была права.
    #
    # Где хвостов нет (все очереди рассчитались), последний остаток нулевой и
    # правка не двигает ничего: она бьёт ровно там, где очередь ушла в дефолт.
    flows = (
        "bridge_draw", "bridge_repayment", "bridge_interest", "bridge_capitalization",
        "project_cash_draw", "own_funds_draw",
        "pf_draw", "pf_repayment", "pf_interest",
        "pf_interest_capitalization",
        "sales_after_rve", "escrow_release", "limit_fee",
        "interest_payment", "profit_tax", "taxable_margin",
        "financing_tax_deduction", "taxable_profit_cumulative",
        "revenue", "capex", "operating",
        *NONRES_ROW_FLOWS,
    )
    stocks = ("bridge_balance", "pf_balance", "pf_payable", "escrow", *NONRES_ROW_STOCKS)
    # `pf_obligation` здесь не складывается: это тело плюс начисленное, и ниже
    # он считается из уже сложенных остатков. Сложенный третьим слагаемым, он
    # разошёлся бы с ними на первой же правке.
    additive = flows + stocks
    source_rows: dict[tuple[int, str], dict[str, Any]] = {}
    for ri, result in enumerate(results):
        for row in result["finance"]["rows"]:
            source_rows[(ri, row["month"])] = row
            month_map.setdefault(row["month"], {key: 0.0 for key in additive})
    # Потоки складываются только там, где строка есть; остатки — с переносом
    # последнего известного значения очереди на месяцы после её горизонта.
    # Обход идёт ПО МЕСЯЦАМ, а не по очередям: перенос обязан знать, какой
    # месяц последний у каждой, а это видно только в общем календаре.
    carried: dict[int, dict[str, float]] = {
        ri: {key: 0.0 for key in stocks} for ri in range(len(results))}
    escrow_by_phase_map: dict[str, list[float]] = {}
    for month in sorted(month_map):
        agg = month_map[month]
        for ri in range(len(results)):
            row = source_rows.get((ri, month))
            if row is not None:
                for key in flows:
                    agg[key] += float(row.get(key, 0.0) or 0.0)
                for key in stocks:
                    carried[ri][key] = float(row.get(key, 0.0) or 0.0)
            for key in stocks:
                agg[key] += carried[ri][key]
        escrow_by_phase_map[month] = [carried[ri]["escrow"]
                                      for ri in range(len(results))]

    # Накопленные ряды свода считаются заново по сложенному потоку. Сложить
    # два накопленных итога нельзя: горизонты очередей разной длины, и в
    # месяце, где строки одной кончились, сумма падает — линия «погашено
    # банку» уезжала с 41,8 до 19,7 млрд на ровном месте.
    running = {"escrow_and_sales_cumulative": 0.0, "sales_after_rve_cumulative": 0.0,
               "escrow_released_cumulative": 0.0}
    rows: list[dict[str, Any]] = []
    for month in sorted(month_map):
        agg = month_map[month]
        key_rate = 0.0
        # Средняя ставка взвешивается по ЖИВЫМ линиям: у очереди, чья линия
        # кончилась, ставки в этот месяц нет вовсе — договор закрыт, — и
        # приписать ей ноль значило бы занизить среднюю по остальным. Долг её
        # при этом в сумме остатков стоит: он не обслуживается, но и не исчез.
        bridge_num = bridge_den = pf_num = pf_den = 0.0
        for ri, result in enumerate(results):
            row = source_rows.get((ri, month))
            if not row:
                continue
            key_rate = float(row.get("key_rate", key_rate) or key_rate)
            bb = float(row.get("bridge_balance", 0.0) or 0.0)
            pb = float(row.get("pf_balance", 0.0) or 0.0)
            bridge_num += bb * float(row.get("bridge_rate", 0.0) or 0.0)
            bridge_den += bb
            pf_num += pb * float(row.get("pf_rate", 0.0) or 0.0)
            pf_den += pb
        out = dict(agg)
        out["month"] = month
        out["key_rate"] = key_rate
        out["bridge_rate"] = bridge_num / bridge_den if bridge_den else 0.0
        out["pf_rate"] = pf_num / pf_den if pf_den else 0.0
        out["coverage"] = out["escrow"] / out["pf_balance"] if out["pf_balance"] else 0.0
        out["pf_obligation"] = out["pf_balance"] + out["pf_payable"]
        running["escrow_and_sales_cumulative"] += out["escrow_release"] + out["sales_after_rve"]
        running["sales_after_rve_cumulative"] += out["sales_after_rve"]
        running["escrow_released_cumulative"] += out["escrow_release"]
        # Чьё это эскроу. Свод складывает счета очередей, а даты раскрытия у
        # них разные: в месяц первой выборки ПФ второй очереди на сводной
        # линии стоит 8,88 млрд, из которых 8,43 — деньги ПЕРВОЙ, и покрытие
        # свода 0,58 против 0,22 у самой очереди. Читается это как «выборка
        # второй очереди сразу покрыта» (владелец, 04.09.2026: «Это деньги
        # первой очереди или что?»). Сумма верна, неверно, что она отвечает
        # на вопрос про очередь, — поэтому доли едут вместе с ней.
        # Долю очереди берём из той же суммы, что и сам остаток: слой,
        # посчитанный по строке, исчезал бы в месяце, где строки уже нет, а
        # общая площадь оставалась — на рисунке это читается как «эскроу
        # ничьё».
        out["escrow_by_phase"] = list(escrow_by_phase_map.get(month) or [])
        out.update(running)
        rows.append(out)

    # Налог очередей считается ЗАНОВО и на своде, а не складывается из
    # очередей (решение владельца, 24.08.2026: «очереди это один проект»).
    # Складывать нельзя: у каждой очереди база обрезалась нулём отдельно, и
    # убыток убыточной очереди выбрасывался целиком. На Румянцеве первая
    # очередь давала −5 264,6 млн, и эти деньги просто пропадали — налог
    # выходил на 1 316 млн больше, чем платит один налогоплательщик.
    #
    # Ловилось это чудом: паритет сверяет только консолидацию, а сдвиг
    # расходов между очередями в ней гасится. Наружу он вылез единственным
    # путём — через налог, и только потому, что убыток обрезается нулём.
    tax_rate = _phase_tax_rate(results)
    consolidated_profit_tax: float | None = None
    # Гейт объявляется здесь и уезжает в свод: его читает раздача налога по
    # очередям. Второе объявление «с какого месяца облагается» разошлось бы с
    # первым молча — и очередь получила бы долю налога за годы, которые сама
    # эта отсрочка из счёта и убрала.
    first_taxable = min(
        (d(r["dates"]["rve"]) for r in results if (r.get("dates") or {}).get("rve")),
        default=None)
    if rows and tax_rate > 0:
        months = [d(row["month"]) for row in rows]
        margins = {d(row["month"]): float(row.get("taxable_margin", 0.0) or 0.0)
                   for row in rows}
        financings = {d(row["month"]): float(row.get("financing_tax_deduction", 0.0) or 0.0)
                      for row in rows}
        schedule, detail = _profit_tax_schedule(
            months, margins, financings, first_taxable, tax_rate)
        for row, line in zip(rows, detail):
            row["profit_tax"] = schedule.get(d(row["month"]), 0.0)
            row["taxable_profit_cumulative"] = line["taxable_base"]
            row["loss_carry_forward"] = line["loss_carry_forward"]
        consolidated_profit_tax = sum(schedule.values())

    fs = [r["finance"] for r in results]
    bridge_weight = sum(max(f["peak_bridge"], 0.0) for f in fs)
    pf_weight = sum(max(f["peak_pf"], 0.0) for f in fs)
    peak_bridge = max((r["bridge_balance"] for r in rows), default=0.0)
    peak_pf = max((r["pf_balance"] for r in rows), default=0.0)
    peak_uncovered_pf = max((max(r["pf_balance"] - r["escrow"], 0.0) for r in rows), default=0.0)
    peak_total_debt = max((r["bridge_balance"] + r["pf_balance"] + r.get("nonres_loan_balance", 0.0)
                           for r in rows), default=0.0)
    peak_escrow = max((r["escrow"] for r in rows), default=0.0)
    llcr_num = sum(f["llcr_numerator"] for f in fs)
    # Долг, принятый одной очередью от другой, стоит в знаменателе принявшей —
    # там он и должен стоять. Но на своде это те же деньги, что уже посчитаны
    # выборкой передавшей очереди, и без вычета они удваиваются: свод показал
    # бы покрытие хуже действительного ровно на сумму переноса. Тот же приём,
    # что и с перенесёнными процентами БРИДЖа.
    carried_total = sum(float(f.get("carried_debt_in") or 0.0) for f in fs)
    llcr_den = sum(f["llcr_denominator"] for f in fs) - carried_total

    financing_cost = sum(f["financing_cost"] for f in fs)
    return {
        "rows": rows,
        # Имена очередей в том же порядке, в каком в строке лежат доли эскроу:
        # без имён доля — безымянное число, а второй список порядка разошёлся
        # бы с первым молча.
        "phase_names": [str(name or f"Очередь {i + 1}")
                        for i, name in enumerate(names or [""] * len(results))],
        "escrow_cover": _escrow_cover_with_phases(rows, results, names or []),
        "calculated_bridge_limit": sum(f["calculated_bridge_limit"] for f in fs),
        # Состав лимита складывается по целям, а не пересобирается вычитанием.
        "calculated_bridge_parts": {
            key: sum(float((f.get("calculated_bridge_parts") or {}).get(key, 0.0)) for f in fs)
            for key in ("purchase", "social", "design_p", "design_rd")
        },
        "bridge_draw_total": sum(f["bridge_draw_total"] for f in fs),
        "project_cash_used": sum(f.get("project_cash_used", 0.0) for f in fs),
        "own_funds_used": sum(f.get("own_funds_used", 0.0) for f in fs),
        "own_funds_available": sum(f.get("own_funds_available", 0.0) for f in fs),
        "peak_bridge": peak_bridge,
        "avg_bridge_rate": (
            sum(f["avg_bridge_rate"] * max(f["peak_bridge"], 0.0) for f in fs) / bridge_weight
            if bridge_weight else 0.0
        ),
        "avg_bridge_key_rate": (
            sum(f.get("avg_bridge_key_rate", 0.0) * max(f["peak_bridge"], 0.0) for f in fs) / bridge_weight
            if bridge_weight else 0.0
        ),
        "current_key_rate": fs[0].get("current_key_rate", 0.0) if fs else 0.0,
        "bridge_spread": fs[0].get("bridge_spread", 0.0) if fs else 0.0,
        "current_bridge_rate": fs[0].get("current_bridge_rate", 0.0) if fs else 0.0,
        "bridge_rate_at_project_start": (
            sum(f.get("bridge_rate_at_project_start", 0.0) * max(f["peak_bridge"], 0.0) for f in fs) / bridge_weight
            if bridge_weight else 0.0
        ),
        "bridge_interest": sum(f["bridge_interest"] for f in fs),
        "bridge_capitalization": sum(f["bridge_capitalization"] for f in fs),
        "bridge_fee": sum(f["bridge_fee"] for f in fs),
        "transferred_bridge_interest": sum(f["transferred_bridge_interest"] for f in fs),
        # Лимит свода — сумма НКЛ очередей: свой лимит очереди или лимит по
        # методике (владелец, 20.09.2026: НКЛ каждой очереди считается заново
        # при её открытии, общий лимит — ожидание, а не потолок).
        "pf_limit": sum(f["pf_limit"] for f in fs),
        "pf_draw_total": sum(f["pf_draw_total"] for f in fs),
        "peak_pf": peak_pf,
        "peak_uncovered_pf": peak_uncovered_pf,
        "pf_repayment_total": sum(f["pf_repayment_total"] for f in fs),
        "ending_pf": sum(f["ending_pf"] for f in fs),
        "avg_pf_rate": (
            sum(f["avg_pf_rate"] * max(f["peak_pf"], 0.0) for f in fs) / pf_weight
            if pf_weight else 0.0
        ),
        "avg_pf_effective_rate": (
            sum(f["avg_pf_effective_rate"] * max(f["peak_pf"], 0.0) for f in fs) / pf_weight
            if pf_weight else 0.0
        ),
        "avg_pf_base_rate": (
            sum(f["avg_pf_base_rate"] * max(f["peak_pf"], 0.0) for f in fs) / pf_weight
            if pf_weight else 0.0
        ),
        "avg_pf_key_rate": (
            sum(f["avg_pf_key_rate"] * max(f["peak_pf"], 0.0) for f in fs) / pf_weight
            if pf_weight else 0.0
        ),
        "pf_special_rate": fs[0]["pf_special_rate"] if fs else 0.0,
        "pf_interest": sum(f["pf_interest"] for f in fs),
        "pf_interest_capitalization": sum(f["pf_interest_capitalization"] for f in fs),
        "pf_limit_fee": sum(f["pf_limit_fee"] for f in fs),
        "pf_reservation_fee": sum(f["pf_reservation_fee"] for f in fs),
        "financing_cost": financing_cost,
        "reported_interest_and_fees": financing_cost,
        "total_revenue": sum(f["total_revenue"] for f in fs),
        "total_capex": sum(f["total_capex"] for f in fs),
        "commercial_costs": sum(f["commercial_costs"] for f in fs),
        "nonres_costs": sum(f.get("nonres_costs", 0.0) for f in fs),
        "nonres": {
            "objects": [item for f in fs for item in (f.get("nonres") or {}).get("objects") or []],
            "totals": _sum_dicts([(f.get("nonres") or {}).get("totals") or {} for f in fs]),
            **_merged_nonres_reconciliation(fs),
        },
        # Гостиница — одна на проект: очередей у гостиничного проекта нет, и
        # свод берёт её итог как есть, а не складывает гостиницы очередей.
        "hotel": next((f.get("hotel") for f in fs if f.get("hotel")), None),
        # Налог свода — пересчитанный как у одного налогоплательщика, а не
        # сумма очередей. Оставить сумму значило бы посчитать заново и не
        # применить: строки показывали бы одно, итог другое.
        "profit_tax": (consolidated_profit_tax if consolidated_profit_tax is not None
                       else sum(f["profit_tax"] for f in fs)),
        # Первый облагаемый месяц свода — самый ранний РВЭ очередей. Всё, что
        # признано раньше, приходит в ГОД этого месяца, а не пропадает; раздача
        # налога по очередям обязана свернуть базы тем же правилом.
        "first_taxable_month": first_taxable,
        "vat": sum(f.get("vat", 0.0) for f in fs),
        "vat_charged": sum(f.get("vat_charged", 0.0) for f in fs),
        "vat_input_deductible": sum(f.get("vat_input_deductible", 0.0) for f in fs),
        "tax_margin_by_product": {
            key: sum(float((f.get("tax_margin_by_product") or {}).get(key, 0.0) or 0.0) for f in fs)
            for key in ("core",) + STANDALONE_PRODUCTS
        },
        "tax_cost_by_product": {
            key: sum(float((f.get("tax_cost_by_product") or {}).get(key, 0.0) or 0.0) for f in fs)
            for key in ("core",) + STANDALONE_PRODUCTS
        },
        "financing_tax_deductions": sum(float(f.get("financing_tax_deductions", 0.0) or 0.0) for f in fs),
        "profit_before_tax": sum(f["profit_before_tax"] for f in fs),
        "llcr_numerator": llcr_num,
        "llcr_denominator": llcr_den,
        "carried_debt_in": carried_total,
        "llcr": llcr_num / llcr_den if llcr_den else 0.0,
        "peak_total_debt": peak_total_debt,
        "peak_escrow": peak_escrow,
        # У многоочередного проекта своё РВЭ у каждой очереди. Свод показывает
        # сумму остатков, возникших в эти даты, а не сравнивает долг одной
        # очереди с эскроу другой.
        "rve_pf_before_repayment": sum(
            f.get("rve_pf_before_repayment", 0.0) for f in fs),
        "rve_escrow_release": sum(f.get("rve_escrow_release", 0.0) for f in fs),
        "rve_pf_shortfall": sum(f.get("rve_pf_shortfall", 0.0) for f in fs),
        # Нехватка лимита складывается: у каждой очереди свой договор и свой
        # потолок. А месяц — САМЫЙ РАННИЙ из названных: «когда открылась
        # дыра» у свода один ответ, и сумма дат его не даёт.
        "pf_limit_required": sum(f.get("pf_limit_required", 0.0) for f in fs),
        # Общий лимит по генеральным условиям — ожидание на все очереди, и
        # свод печатает его РЯДОМ с суммой НКЛ, а не вместо: потолком он не
        # служит. Одобрено проекту — сумма лимитов НКЛ, заданных очередям.
        "pf_limit_general": pf_limit_general,
        "pf_limit_approved": sum(f.get("pf_limit_approved", 0.0) for f in fs),
        "pf_shortfall": sum(f.get("pf_shortfall", 0.0) for f in fs),
        "pf_shortfall_month": min(
            (str(f.get("pf_shortfall_month") or "") for f in fs
             if str(f.get("pf_shortfall_month") or "")), default=""),
        "rve_pf_repayment": sum(f.get("rve_pf_repayment", 0.0) for f in fs),
        # Дефолт хотя бы одной очереди — свойство всего свода: прибыль после
        # него посчитана на допущении, что банк дал проекту продолжиться.
        # Без этих двух ключей свод их не знал вовсе, и вердикт с PDF
        # печатали прибыль голым числом там, где модель ушла в дефолт
        # (владелец, 30.08.2026: «значит нельзя писать и чистую прибыль»).
        "rve_unpaid": sum(f.get("rve_unpaid", 0.0) for f in fs),
        "default_date": min(
            (str(f.get("default_date")) for f in fs if f.get("default_date")),
            default=None),
    }


# Налог на прибыль с переносом убытка по ст. 283 НК —
# `developaid_finance_math.profit_tax_schedule` (здесь: `_profit_tax_schedule`);
# обоснование половинного ограничения — там же.


def _phase_tax_bases(
    results: list[dict[str, Any]],
    first_taxable_month: Any,
) -> list[dict[int, float]]:
    """База каждой очереди по НАЛОГОВЫМ годам свода.

    Год — единственная мера, которую задаёт НК: налоговый период по налогу на
    прибыль это календарный год (ст. 285), а база считается нарастающим итогом
    с начала периода (п. 7 ст. 274). Месяц объектом налогообложения не
    является вовсе — он отчётный период, и его база тоже с начала года.

    Свёртка до гейта повторяет `_profit_tax_schedule`: всё, что признано до
    первого облагаемого месяца, приходит в ГОД этого месяца. Без неё база
    очереди живёт в годах, в которых налога не было, и раздача приписывает ей
    долю за периоды, когда проект не был должен бюджету ничего.
    """
    gate = str(first_taxable_month) if first_taxable_month else None
    gate_year = int(gate[:4]) if gate else None
    bases: list[dict[int, float]] = []
    for result in results:
        years: dict[int, float] = {}
        for row in result["finance"]["rows"]:
            month = str(row["month"])
            year = gate_year if (gate and month < gate) else int(month[:4])
            years[year] = years.get(year, 0.0) + _phase_tax_base_of(row)
        bases.append(years)
    return bases


def _phase_tax_base_of(row: dict[str, Any]) -> float:
    """Облагаемая база месяца очереди — та же величина, что считает свод."""
    return (float(row.get("taxable_margin", 0.0) or 0.0)
            - float(row.get("financing_tax_deduction", 0.0) or 0.0))


def _reallocate_phase_tax(
    results: list[dict[str, Any]],
    comparison: list[dict[str, Any]],
    finance: dict[str, Any],
) -> None:
    """Сводный налог раздаётся очередям по их вкладу в облагаемую базу.

    Очередь без базы налога не платит — у убыточной он остаётся нулевым, и
    именно её убыток снизил налог остальным. Прибыль очереди правится на ту
    же величину, иначе сумма очередей разойдётся со сводом.

    Налог КАЖДОГО года раздаётся по вкладу очередей в базу ЭТОГО года. Прежде
    веса брались суммой прибыльных лет за весь горизонт и этим весом делился
    ВЕСЬ налог: очередь, прибыльная в 2033-м, получала долю налога 2038 года,
    которого она не создавала. На двух и трёх очередях это совпадало с верным
    ответом, поэтому и прожило; на четырёх с шагом 36 месяцев расхождение —
    1 156 млн ₽ на строке очереди при совпадающем итоге.

    У года бывает налог при отрицательной годовой базе: внутри года
    накопленным итогом была прибыль, налог начислен и обратно не возвращается
    (`tax_month = max(target - year_tax_paid, 0)`). Делить такой год по годовой
    базе нечем — он делится по МЕСЯЦАМ, в которых налог и начислен. Мера
    вынужденная и названа: год тут ответа не даёт, а терять налог нельзя —
    сумма очередей обязана сойтись со сводом.
    """
    consolidated_tax = float(finance.get("profit_tax", 0.0) or 0.0)
    bases = _phase_tax_bases(results, finance.get("first_taxable_month"))
    rows = list(finance.get("rows") or [])
    tax_by_year: dict[int, float] = {}
    taxed_months: dict[int, set[str]] = {}
    for row in rows:
        tax = float(row.get("profit_tax", 0.0) or 0.0)
        if tax:
            year = int(str(row["month"])[:4])
            tax_by_year[year] = tax_by_year.get(year, 0.0) + tax
            taxed_months.setdefault(year, set()).add(str(row["month"]))
    shares = [0.0] * len(results)
    for year, tax in tax_by_year.items():
        positive = [max(base.get(year, 0.0), 0.0) for base in bases]
        if sum(positive) <= 0:
            months = taxed_months.get(year) or set()
            positive = [
                sum(max(_phase_tax_base_of(row), 0.0)
                    for row in result["finance"]["rows"]
                    if str(row["month"]) in months)
                for result in results]
        total_year = sum(positive)
        if total_year <= 0:
            # Ни годовой базы, ни положительных месяцев — делить не по чему.
            # Поровну: налог в строках очередей обязан остаться, а выдумывать
            # за него основание нечем, и это сказано вслух здесь.
            positive = [1.0] * len(results)
            total_year = float(len(results)) or 1.0
        for index in range(len(results)):
            shares[index] += tax * positive[index] / total_year
    total = sum(shares)
    for index, result in enumerate(results):
        share = (shares[index] / total) if total else 0.0
        was = float((result.get("summary") or {}).get("profit_tax", 0.0) or 0.0)
        now = consolidated_tax * share
        result["summary"]["profit_tax"] = now
        result["summary"]["net_profit"] = (
            float(result["summary"].get("net_profit", 0.0) or 0.0) + was - now)
        if index < len(comparison):
            row = comparison[index]
            row["profit_tax"] = now
            row["net_profit"] = float(row.get("net_profit", 0.0) or 0.0) + was - now
        _restate_phase_tax_expense(result, now)


def _restate_phase_tax_expense(result: dict[str, Any], profit_tax: float) -> None:
    """Налог в структуре расходов очереди — тот же, что в её сводке.

    Свод складывает структуры очередей построчно, и налог в них оставался
    прежним, посчитанным очередью в одиночку. Итоговая строка при этом брала
    сводный налог: таблица переставала сходиться сама с собой, а обе половины
    выглядели достоверно. Ровно та беда, ради которой у этой таблицы и есть
    проверка на сходимость.
    """
    report = result.get("report") or {}
    rows = report.get("expense_structure") or []
    summary = result.get("summary") or {}
    bases = summary.get("unit_bases") or unit_bases(
        summary.get("construction_volume_sqm"), summary.get("monetizable_saleable_sqm"), 0.0, 0.0)
    target = None
    for row in rows:
        if str(row.get("label")) == "Налог на прибыль":
            target = row
            break
    if target is None:
        # Строки может не быть вовсе: в одиночку очередь налога не платила, и
        # нулевые строки в структуру не попадают. Сводный налог при этом есть —
        # он и берётся из зачёта между очередями. Без этой строки итог учитывал
        # налог, а таблица его не показывала: ровно на него и не сходилась.
        if profit_tax <= 0:
            return
        target = {"label": "Налог на прибыль"}
        rows.append(target)
        report["expense_structure"] = rows
    target["value"] = profit_tax
    target.update(unit_rates(profit_tax, UNIT_BASE_TOTAL, bases))
    base = sum(float(row.get("value") or 0.0) for row in rows)
    for row in rows:
        row["share"] = (float(row.get("value") or 0.0) / base) if base else 0.0


def _consolidate_phase_results(
    master_inputs: dict[str, Any],
    phase_items: list[dict[str, Any]],
    comparison: list[dict[str, Any]],
    phase_financing: dict[str, Any] | None = None,
) -> dict[str, Any]:
    results = [item["result"] for item in phase_items]
    pf_limit_general = max(0.0, n(master_inputs, "pf_limit_approved_mln")) * 1_000_000
    finance = _aggregate_finance(
        results, [str(item.get("name") or "") for item in phase_items],
        pf_limit_general=pf_limit_general)
    consolidated_bridge_month = _bridge_peak_month(finance["rows"])
    # Расшифровка пика свода — только по очередям, чья линия в этот месяц
    # открыта: закрытая линия ничего не должна, а её расходы уже на ПФ.
    bridge_queues = _queues_on_bridge(phase_items, consolidated_bridge_month)
    bridge_items = [item for item in phase_items
                    if str(item.get("name") or "") in bridge_queues["on_bridge"]]
    bridge_own_funds = sum(
        _own_funds_by((item["result"].get("finance") or {}).get("rows") or [], consolidated_bridge_month)
        for item in bridge_items)
    bridge_project_cash = sum(
        _project_cash_by((item["result"].get("finance") or {}).get("rows") or [], consolidated_bridge_month)
        for item in bridge_items)

    tep_map: dict[str, dict[str, Any]] = {}
    for result in results:
        for row in result["tep"]["rows"]:
            target = tep_map.setdefault(row["key"], {
                "key": row["key"], "label": row["label"],
                "gns": 0.0, "total_area": 0.0, "useful": 0.0,
                "saleable": 0.0, "transfer": 0.0, "units": 0.0,
                "guest_units": 0.0, "transfer_units": 0.0, "saleable_units": 0.0,
                "under_gns": 0.0, "parking_units": 0.0,
                "parking_saleable_units": 0.0,
                "parking_under_units": 0.0, "parking_over_units": 0.0,
                "parking_guest_units": 0.0,
                "excluded": True,
            })
            # Вне состава свода — только строка, которой нет ни в одной
            # очереди: объект второй очереди выключен в первой, и ответ
            # первой очереди не прячет его из свода.
            target["excluded"] = target["excluded"] and bool(row.get("excluded"))
            for field in ("gns", "total_area", "useful", "saleable", "transfer", "units",
                          "guest_units", "transfer_units", "saleable_units",
                          "under_gns", "parking_units",
                          "parking_saleable_units", "parking_under_units",
                          "parking_over_units", "parking_guest_units"):
                target[field] += float(row.get(field, 0.0) or 0.0)
    tep_rows = list(tep_map.values())
    # Признак свода — по своду, а не по первой очереди: объект второй очереди
    # выключен в первой и пуст в ней.
    for _row in tep_rows:
        _row["listed"] = row_listed(_row)
    # Тот же список полей, что у одиночного расчёта, и та же группировка
    # штук: две копии однажды разошлись бы, и своды очередного и одиночного
    # проектов считались бы по-разному.
    tep_total = {field: sum(row[field] for row in tep_rows) for field in TEP_SUMMABLE_FIELDS}
    tep_total["units_by_measure"] = tep_units_by_measure(tep_rows)
    tep_total["saleable_units_by_measure"] = tep_units_by_measure(
        tep_rows, "saleable_units", "parking_saleable_units")

    revenue = _sum_dicts([r["revenue"] for r in results])
    capex = _sum_dicts([r["capex"] for r in results])
    total_revenue = finance["total_revenue"]
    total_capex = finance["total_capex"]
    commercial_costs = finance["commercial_costs"]
    nonres_costs = float(finance.get("nonres_costs", 0.0) or 0.0)
    ebitda = total_revenue - total_capex - commercial_costs - nonres_costs
    net_profit = sum(r["summary"]["net_profit"] for r in results)
    # Налог пересчитан на своде как у одного налогоплательщика, а прибыль
    # очередей посчитана с их собственным налогом. Не развести — и таблица
    # очередей перестанет складываться в итог: два числа об одном и том же,
    # оба достоверные на вид. Разница раздаётся очередям по их вкладу в базу.
    phase_tax_delta = sum(
        float((r.get("summary") or {}).get("profit_tax", 0.0) or 0.0)
        for r in results) - finance["profit_tax"]
    if abs(phase_tax_delta) > 0.5:
        net_profit += phase_tax_delta
        _reallocate_phase_tax(results, comparison, finance)

    saleable = sum(r["summary"]["monetizable_saleable_sqm"] for r in results)
    apartment_saleable = sum(r["summary"]["apartment_saleable_sqm"] for r in results)
    project_gns = sum(r["summary"]["project_gns_sqm"] for r in results)
    underground_gns = sum(r["summary"].get("underground_gns_sqm", 0.0) for r in results)
    construction_volume = sum(r["summary"].get("construction_volume_sqm", 0.0) for r in results)
    # НДС — такой же денежный расход проекта, как налог на прибыль: без него
    # строки структуры расходов не сходятся с итоговой строкой, и обе
    # выглядят достоверно.
    full_cost = (total_capex + commercial_costs + nonres_costs + finance["financing_cost"]
                 + finance["profit_tax"] + finance.get("vat", 0.0))
    avg_apt_price = revenue.get("apartments", 0.0) / apartment_saleable / 1000 if apartment_saleable else 0.0

    construction_keys = (
        "ird", "design_p", "design_rd", "author_supervision", "preparation",
        "main_above", "main_under", "utilities", "landscaping",
        "commissioning", "site_maintenance", "gc_fee", "reserve",
    )
    construction_capex = sum(capex.get(k, 0.0) for k in construction_keys)
    core_gns = sum(r["tep"]["core_above_gns"] + r["tep"]["core_under_gns"] for r in results)

    master_start = d(master_inputs.get("project_start", results[0]["dates"]["project_start"]))
    cf_months, project_cf, equity_cf = _combine_cashflows(results, master_start)
    tax_by_month = {
        d(row["month"]): float(row.get("profit_tax", 0.0) or 0.0)
        for row in finance["rows"]
    }
    discount_rate = n(master_inputs, "discount_rate_pct", 20) / 100
    npv = _monthly_npv(project_cf, discount_rate) if project_cf else 0.0
    npv_equity = _equity_npv(equity_cf, discount_rate) if equity_cf else 0.0
    irr_equity = _monthly_irr(equity_cf) if equity_cf else None

    def per_th(value: float, area: float) -> float:
        return value / area / 1000 if area else 0.0

    # Те же строки и базы, что у очереди (`unit_economics_rows`), от сводных
    # площадей: удельные складывать нельзя.
    bases = unit_bases(construction_volume, saleable,
                       sum(r["tep"]["core_above_gns"] for r in results),
                       sum(r["tep"]["core_under_gns"] for r in results))
    unit_economics = unit_economics_rows({
        "revenue": total_revenue, "capex": total_capex,
        "commercial_costs": commercial_costs, "ebitda": ebitda,
        "financing_cost": finance["financing_cost"], "profit_tax": finance["profit_tax"],
        "vat": finance.get("vat", 0.0), "total_expenses": full_cost,
        "net_profit": net_profit}, bases)

    # Статьи стройки — из сводного CAPEX теми же строками, что у очереди.
    construction_costs = construction_cost_rows(capex, bases)

    # Темп продаж квартир в штуках складывается по месяцам всех очередей:
    # в один месяц могут продаваться квартиры двух очередей сразу, и отдел
    # продаж видит их одной цифрой, а не двумя.
    apartment_units_by_month: dict[str, float] = defaultdict(float)
    apartment_units_total = 0.0
    apartment_area_total = 0.0
    for result in results:
        phase_sales_apartments = (result["report"].get("apartment_sales") or {})
        apartment_units_total += float(phase_sales_apartments.get("units_total") or 0.0)
        apartment_area_total += (float(phase_sales_apartments.get("units_total") or 0.0)
                                 * float(phase_sales_apartments.get("avg_unit_sqm") or 0.0))
        for row in phase_sales_apartments.get("rows") or []:
            apartment_units_by_month[str(row["month"])] += float(row["units"] or 0.0)
    apartment_sales: dict[str, Any] = {}
    if apartment_units_by_month:
        monthly = sorted(apartment_units_by_month.items())
        last_rve = max(d(r["dates"]["rve"]) for r in results)
        before_rve = [units for month, units in monthly if d(month) <= last_rve]
        apartment_sales = {
            "units_total": apartment_units_total,
            "avg_unit_sqm": (apartment_area_total / apartment_units_total
                             if apartment_units_total else 0.0),
            "avg_unit_price_mln": (apartment_area_total / apartment_units_total
                                   * avg_apt_price / 1000 if apartment_units_total else 0.0),
            "pace_pre_rve_units": sum(before_rve) / len(before_rve) if before_rve else 0.0,
            "pace_units": sum(u for _, u in monthly) / len(monthly),
            "peak_units": max(u for _, u in monthly),
            "months": len(monthly),
            "rows": [{"month": month, "units": units} for month, units in monthly],
        }

    expense_map: dict[str, float] = defaultdict(float)
    # Подстроки объектов складываются по объекту, а не по проекту: у каждой
    # очереди свои офисы и свой паркинг, и на своде их надо сложить с их же
    # площадями — иначе «на свою ГНС» перестало бы быть своим.
    item_map: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    for result in results:
        for item in result["report"]["expense_structure"]:
            expense_map[item["label"]] += float(item["value"] or 0.0)
            for part in item.get("items") or []:
                kept = item_map[item["label"]].setdefault(
                    part["key"], {"key": part["key"], "label": part["label"],
                                  "basis": part["basis"]})
                # Здание и гараж складываются порознь: сложенные в одно число,
                # они давали на своде ставку «здания» 316 при вводной 200.
                for field in _STANDALONE_ITEM_SUMS:
                    if field in part:
                        kept[field] = kept.get(field, 0.0) + float(part.get(field) or 0.0)
    expense_base = sum(expense_map.values())
    expense_structure = [
        {
            "label": label,
            "value": value,
            "share": value / expense_base if expense_base else 0.0,
            # Удельные складывать нельзя — их пересчитывают от сводных площадей.
            # Пока их тут не было, свод по всему проекту показывал нули во всех
            # строках, а итоговая строка считалась отдельно и стояла живая:
            # таблица выглядела сломанной ровно там, где по ней и спорят.
            **unit_rates(value, UNIT_BASE_TOTAL, bases),
        }
        for label, value in expense_map.items() if value > 0
    ]
    for entry in expense_structure:
        parts = [standalone_expense_item_rates(part)
                 for part in (item_map.get(entry["label"]) or {}).values()]
        if not parts:
            continue
        entry["items"] = sorted(parts, key=lambda one: one["value"], reverse=True)
        entry["items_note"] = standalone_expense_note(entry["value"], construction_volume, saleable)
    expense_structure.sort(key=lambda x: x["value"], reverse=True)

    product_map: dict[str, dict[str, Any]] = {}
    for result in results:
        for item in result["report"]["products"]:
            p = product_map.setdefault(item["key"], {
                "key": item["key"], "label": item["label"], "unit": item["unit"],
                # Признак продаваемости переносится на свод как есть: без
                # него таблица очередей снова показала бы соцобъект строкой
                # продаж — она собирается из ЭТОГО списка, а не из
                # одноочередного.
                "sellable": bool(item.get("sellable", True)),
                "quantity": 0.0, "gns": 0.0, "saleable": 0.0,
                "revenue": 0.0, "cost": 0.0, "margin": None,
                "start_price_th": item["start_price_th"],
                "avg_price_th": 0.0, "pace_pre": None,
                "share_before_rve": item["share_before_rve"],
                "sales_start": None, "sales_end": None,
                "excluded": True,
            })
            # Вне состава свода — только продукт, которого нет ни в одной очереди.
            p["excluded"] = p["excluded"] and bool(item.get("excluded"))
            p["quantity"] += float(item["quantity"] or 0.0)
            p["gns"] += float(item.get("gns", 0.0) or 0.0)
            p["saleable"] += float(item.get("saleable", 0.0) or 0.0)
            p["revenue"] += float(item["revenue"] or 0.0)
            p["cost"] += float(item.get("cost", 0.0) or 0.0)
            if "built_units" in item:
                p["built_units"] = p.get("built_units", 0.0) + float(item["built_units"] or 0.0)
                p["object"] = item.get("object")
            if item.get("sales_start"):
                p["sales_start"] = item["sales_start"] if p["sales_start"] is None else min(p["sales_start"], item["sales_start"])
            if item.get("sales_end"):
                p["sales_end"] = item["sales_end"] if p["sales_end"] is None else max(p["sales_end"], item["sales_end"])
    for p in product_map.values():
        p["avg_price_th"] = p["revenue"] / p["quantity"] / 1000 if p["quantity"] else 0.0
        p["margin"] = ((p["revenue"] - p["cost"]) / p["revenue"]
                       if p["revenue"] else None)
    # Паркинг объекта стоит сразу за своим объектом — как в очереди. Первая
    # очередь без офиса иначе ставила его строку в конец списка.
    _parking_of = {pkey: okey for okey, pkey in OBJECT_PARKING_PRODUCT_KEYS.items()}
    _ordered: dict[str, dict[str, Any]] = {}
    for _key, _item in product_map.items():
        if _key in _parking_of and _parking_of[_key] in product_map:
            continue
        _ordered[_key] = _item
        _pkey = OBJECT_PARKING_PRODUCT_KEYS.get(_key)
        if _pkey in product_map:
            _ordered[_pkey] = product_map[_pkey]
    product_map = _ordered

    # Consolidated project has no single RVE. Keep phase-specific sales pace and dates.
    phase_sales = []
    for key, total_item in product_map.items():
        phases = []
        for phase_item in phase_items:
            item = next((p for p in phase_item["result"]["report"]["products"] if p["key"] == key), None)
            if not item:
                continue
            phases.append({
                "phase": phase_item["name"],
                "phase_index": phase_item["index"],
                "quantity": float(item.get("quantity", 0.0) or 0.0),
                "unit": item.get("unit"),
                "pace_pre": float(item.get("pace_pre", 0.0) or 0.0),
                "share_before_rve": float(item.get("share_before_rve", 0.0) or 0.0),
                "start_price_th": float(item.get("start_price_th", 0.0) or 0.0),
                "avg_price_th": float(item.get("avg_price_th", 0.0) or 0.0),
                "revenue": float(item.get("revenue", 0.0) or 0.0),
                "sales_start": item.get("sales_start"),
                "sales_end": item.get("sales_end"),
                "rve": phase_item["result"]["dates"]["rve"],
                "cost_inflation_factor": phase_item.get("cost_inflation_factor", 1.0),
                "sales_price_inflation_factor": phase_item.get("sales_price_inflation_factor", 1.0),
            })
        phase_sales.append({
            "key": key,
            "label": total_item["label"],
            "unit": total_item["unit"],
            "sellable": total_item["sellable"],
            "excluded": total_item["excluded"],
            "quantity": total_item["quantity"],
            "revenue": total_item["revenue"],
            "avg_price_th": total_item["avg_price_th"],
            "phases": phases,
        })

    events = []
    for phase_item in phase_items:
        for event in phase_item["result"]["report"]["calendar"]["events"]:
            e = copy.deepcopy(event)
            e["label"] = f"{phase_item['name']} · {e['label']}"
            e["group"] = f"{phase_item['name']} · {e['group']}"
            # Calendar-only metadata. It does not participate in any financial calculation.
            e["phase_index"] = phase_item["index"]
            e["phase_name"] = phase_item["name"]
            events.append(e)
    cal_start = min(d(e["start"]) for e in events)
    cal_end = max(d(e["end"]) for e in events)

    social_program = {
        "kindergarten_places": sum(r["summary"]["social_program"].get("kindergarten_places", 0.0) for r in results),
        "school_places": sum(r["summary"]["social_program"].get("school_places", 0.0) for r in results),
        "clinic_capacity": sum(r["summary"]["social_program"].get("clinic_capacity", 0.0) for r in results),
    }
    social_construction = {
        key: sum(r["summary"]["social_payment_breakdown"]["construction"].get(key, 0.0) for r in results)
        for key in ("kindergarten_mln", "school_mln", "clinic_mln")
    }
    social_compensation = {
        key: sum(r["summary"]["social_payment_breakdown"]["compensation"].get(key, 0.0) for r in results)
        for key in ("kindergarten_mln", "school_mln", "clinic_mln")
    }

    phase_financing = phase_financing or _phase_financing_summary(
        phase_items, "independent", [])
    return {
        "dates": {
            "project_start": min(r["dates"]["project_start"] for r in results),
            "permit": min(r["dates"]["permit"] for r in results),
            "sales_start": min(r["dates"]["sales_start"] for r in results),
            "rve": max(r["dates"]["rve"] for r in results),
        },
        "tep": {
            "rows": tep_rows, "total": tep_total,
            "core_above_gns": sum(r["tep"]["core_above_gns"] for r in results),
            "core_under_gns": sum(r["tep"]["core_under_gns"] for r in results),
            "project_articles_sqm": sum(float(r["tep"].get("project_articles_sqm") or 0.0)
                                        for r in results),
            # Вид проекта у очередей один — имя базы берётся у первой.
            "project_articles_area": next((r["tep"].get("project_articles_area")
                                           for r in results), CORE_TOTAL_AREA.key),
        },
        "revenue": revenue,
        "revenue_structure": revenue_structure({**revenue, "total": total_revenue}, saleable),
        "capex": capex,
        "object_costs": _sum_object_costs(results),
        "capex_units": capex_unit_rows(capex, bases),
        "commercial_costs": commercial_costs,
        "finance": finance,
        # Сделка проекта — сумма сделок очередей, строка к строке.
        "deal": {key: sum(float((r.get("deal") or {}).get(key) or 0.0) for r in results)
                 for key in ("price_mln", "buyout_mln", "total_mln")},
        "summary": {
            "revenue": total_revenue, "capex": total_capex,
            "commercial_costs": commercial_costs, "ebitda": ebitda,
            "financing_cost": finance["financing_cost"],
            "profit_before_tax": finance["profit_before_tax"],
            "profit_tax": finance["profit_tax"], "vat": finance.get("vat", 0.0),
            "net_profit": net_profit,
            "margin": net_profit / total_revenue if total_revenue else 0.0,
            "llcr": finance["llcr"],
            "ending_pf": finance.get("ending_pf", 0.0),
            "rve_pf_shortfall": finance.get("rve_pf_shortfall", 0.0),
            "pf_shortfall": finance.get("pf_shortfall", 0.0),
            "pf_shortfall_month": finance.get("pf_shortfall_month", ""),
            "min_phase_llcr": min((r["summary"]["llcr"] for r in results), default=0.0),
            "scenario_revenue_multiplier": n(master_inputs, "scenario_revenue_multiplier", 1.0),
            "scenario_cost_multiplier": n(master_inputs, "scenario_cost_multiplier", 1.0),
            "npv": npv, "npv_equity": npv_equity, "irr_equity": irr_equity,
            "full_project_cost": full_cost,
            "monetizable_saleable_sqm": saleable,
            "apartment_saleable_sqm": apartment_saleable,
            # Гараж отдельно стоящих объектов по всему проекту — сумма
            # очередей, посчитанная ЗДЕСЬ, а не складываемая на экране: у
            # свода и у таблицы очередей иначе вышло бы два ответа об одном
            # обязательстве, и оба выглядели бы верными.
            "object_parking_units": sum(
                float((r.get("parking") or {}).get("own_units") or 0.0) for r in results),
            "object_parking_saleable_units": sum(
                float((r.get("parking") or {}).get("own_saleable_units") or 0.0) for r in results),
            "object_parking_under_gns": sum(
                float((r.get("parking") or {}).get("own_under_gns") or 0.0) for r in results),
            "average_apartment_price_th": avg_apt_price,
            "full_cost_per_saleable_th": per_th(full_cost, saleable),
            "full_cost_per_total_area_th": per_th(full_cost, construction_volume),
            "capex_per_total_area_th": per_th(total_capex, construction_volume),
            "construction_cost_per_gns_th": per_th(construction_capex, core_gns),
            "construction_cost_per_saleable_th": per_th(construction_capex, saleable),
            "ebitda_per_saleable_th": per_th(ebitda, saleable),
            "net_profit_per_saleable_th": per_th(net_profit, saleable),
            "unit_bases": bases,
            "project_gns_sqm": project_gns, "total_expenses": full_cost,
            "underground_gns_sqm": underground_gns,
            "construction_volume_sqm": construction_volume,
            # Площадь благоустройства свода — сумма очередей: у каждой своё
            # население, и второй счёт по своду разошёлся бы с ними.
            "landscaping_area_sqm": sum(
                float(r["summary"].get("landscaping_area_sqm") or 0.0) for r in results),
            "landscaping_basis": "сумма площадей очередей — у каждой своё население",
            # Деньги у очередей считаются своими основаниями — у одной ставка,
            # у другой методика, — и взятое у первой говорило бы за остальные.
            "landscaping_money_basis": "сумма очередей — у каждой своё основание",
            # Показатель поля «Благоустройство, тыс. ₽/м² ГНС» — от денег и ГНС
            # свода, а не средним удельных. Без него страница читала пустоту
            # как «методика дала ноль» и писала «благоустройства в расчёте
            # нет» над 544 млн ₽ в CAPEX (Мытищи, владелец, 04.10.2026).
            "landscaping_per_gns_th": per_th(capex.get("landscaping", 0.0), project_gns),
            "landscaping_by_class_th": per_th(sum(
                float(r["summary"].get("landscaping_by_class_th") or 0.0)
                * float(r["summary"].get("project_gns_sqm") or 0.0) * 1000
                for r in results), project_gns),
            "landscaping_by_rate": any(
                bool(r["summary"].get("landscaping_by_rate")) for r in results),
            # Пустоту свод не выбирает у первой очереди: текстов у неё
            # столько же, сколько очередей, и любой выбранный говорил бы за
            # остальные. Свод называет счёт.
            "landscaping_gap": _phase_landscaping_gap(results),
            "social_payment": sum(r["summary"]["social_payment"] for r in results),
            "social_payment_mode": str(master_inputs.get("social_mode", "")),
            "social_in_capex_check": all(r["summary"].get("social_in_capex_check", True) for r in results),
            "social_program": social_program,
            "social_payment_breakdown": {
                "construction": social_construction,
                "compensation": social_compensation,
            },
            "phase_count": len(results),
            "peak_total_debt": finance["peak_total_debt"],
        },
        "report": {
            "project_class": project_class_view(master_inputs),
            "nonres_strategy": nonres_report(finance.get("nonres")),
            "hotel": hotel_report(finance.get("hotel")),
            "nonres_financing": nonres_financing_report(finance.get("nonres")),
            "nonres_costs_label": nonres_costs_label(master_inputs),
            "equity_participation": equity_participation_report(
                cf_months, equity_cf, finance, discount_rate=discount_rate, irr=irr_equity),
            "layout": report_layout(master_inputs, finance, equity_cf),
            "products": list(product_map.values()),
            "phase_products": phase_sales,
            "unit_economics": unit_economics,
            "construction_costs": construction_costs,
            "apartment_sales": apartment_sales,
            "expense_structure": expense_structure,
            "calendar": {"start": cal_start.isoformat(), "end": cal_end.isoformat(), "events": events},
            "financing": {
                "calculated_bridge": finance["calculated_bridge_limit"],
                "calculated_bridge_parts": finance.get("calculated_bridge_parts") or {},
                "actual_bridge": finance["peak_bridge"],
                # Пик свода — общий месяц, а не сумма пиков очередей, поэтому и
                # расшифровка собирается на этот общий месяц по всем очередям.
                "actual_bridge_month": consolidated_bridge_month,
                "own_funds": finance.get("own_funds_used", 0.0),
                "own_funds_available": finance.get("own_funds_available", 0.0),
                "project_cash": finance.get("project_cash_used", 0.0),
                "actual_bridge_structure": _bridge_actual_structure(
                    [item["result"].get("monthly") or {} for item in bridge_items],
                    consolidated_bridge_month, finance["peak_bridge"],
                    bridge_own_funds, bridge_project_cash),
                "actual_bridge_queues": bridge_queues,
                "pf_peak": finance["peak_pf"],
                "pf_uncovered_peak": finance["peak_uncovered_pf"],
                "rve_pf_before_repayment": finance.get("rve_pf_before_repayment", 0.0),
                "rve_escrow_release": finance.get("rve_escrow_release", 0.0),
                "rve_pf_repayment": finance.get("rve_pf_repayment", 0.0),
                "rve_pf_shortfall": finance.get("rve_pf_shortfall", 0.0),
                "pf_limit_required": finance.get("pf_limit_required", 0.0),
                "pf_limit_approved": finance.get("pf_limit_approved", 0.0),
                "pf_shortfall": finance.get("pf_shortfall", 0.0),
                "pf_shortfall_mln": float(finance.get("pf_shortfall", 0.0) or 0.0) / 1_000_000,
                "pf_shortfall_month": finance.get("pf_shortfall_month", ""),
                # На своде дата раскрытия у каждой очереди своя, поэтому здесь
                # свод разрыва по месяцам, а поимённые ответы — рядом списком.
                # Одна сумма на весь проект не отвечает, какой очереди не
                # хватило: то же правило, что у непогашенного долга.
                "escrow_cover": finance.get("escrow_cover") or {},
                "escrow_cover_phases": [
                    dict(item["result"]["finance"].get("escrow_cover") or {},
                         label=str(item.get("name") or f"Очередь {index + 1}"))
                    for index, item in enumerate(phase_items)
                ],
                "pf_limit": finance["pf_limit"],
                "avg_bridge_rate": finance["avg_bridge_rate"],
                "avg_bridge_key_rate": finance.get("avg_bridge_key_rate", 0.0),
                "current_key_rate": finance.get("current_key_rate", 0.0),
                "bridge_spread": finance.get("bridge_spread", 0.0),
                "current_bridge_rate": finance.get("current_bridge_rate", 0.0),
                "bridge_rate_at_project_start": finance.get("bridge_rate_at_project_start", 0.0),
                "avg_pf_rate": finance["avg_pf_rate"],
                "avg_pf_effective_rate": finance["avg_pf_effective_rate"],
                "avg_pf_base_rate": finance["avg_pf_base_rate"],
                "avg_pf_key_rate": finance["avg_pf_key_rate"],
                "pf_special_rate": finance["pf_special_rate"],
                "interest_and_fees": finance["financing_cost"],
                "ending_pf": finance.get("ending_pf", 0.0),
                "carried_debt_in": finance.get("carried_debt_in", 0.0),
                "rve_unpaid": finance.get("rve_unpaid", 0.0),
                "default_date": finance.get("default_date"),
                "bridge_peak_capitalized": finance["peak_bridge"]
                + finance.get("transferred_bridge_interest", 0.0),
                "peak_total_debt": finance["peak_total_debt"],
                "peak_escrow": finance["peak_escrow"],
                "phase_financing": phase_financing,
            },
        },
        "cashflow": {
            "months": [m.isoformat() for m in cf_months],
            "project": project_cf, "equity": equity_cf,
            "profit_tax": [tax_by_month.get(m, 0.0) for m in cf_months],
        },
        "comparison": comparison,
        "phase_financing": phase_financing,
        "excel_control": EXCEL_CONTROL,
        "notes": {
            "phasing": "Очередность — внешняя надстройка над единым одноочередным движком: отдельные ТЭП, сроки, инфляция затрат, инфляция стартовой цены продажи и дискретные объекты.",
            "sales": "У многоочередного проекта нет единого РВЭ: темп продаж показывается отдельно по каждой очереди.",
            "finance": "БРИДЖ и ПФ остаются отдельными банковскими линиями каждой очереди. В режиме единого денежного потока только уже высвобождённый cash более ранней очереди после обслуживания её долга уменьшает затраты до РНС следующей очереди; эскроу, будущая прибыль и банковские лимиты не переносятся.",
        },
    }


# Поздняя раскладка социальных объектов по очередям.
#
# Первая очередь несёт сети, подготовительный период и самый длинный срок, поэтому
# социальные объекты по умолчанию уезжают вправо: школа — в последнюю очередь,
# ДОУ — во вторую, поликлиника — ближе к концу. Поликлинике первая очередь
# разрешена, если её туда двигает обязательство; школе и ДОУ — нет.
_SOCIAL_LATE_POLICY: dict[str, dict[str, Any]] = {
    "kindergarten": {"label": "ДОО", "target": "second", "auto_earliest": 2},
    "clinic": {"label": "Поликлиника", "target": "second_last", "auto_earliest": 1},
    "school": {"label": "СОШ", "target": "last", "auto_earliest": 2},
}


def _social_target_phase(target: str, count: int) -> int:
    if count <= 1:
        return 1
    if target == "last":
        return count
    if target == "second":
        return min(2, count)
    if target == "second_last":
        return count - 1 if count >= 3 else count
    return count


def _phase_social_allocation(
    social_objects: list[dict[str, Any]], count: int
) -> list[dict[str, Any]]:
    """Расставляет объекты по очередям и объясняет, почему объект встал именно туда."""
    allocation: list[dict[str, Any]] = []
    for obj in social_objects:
        # JSON.stringify превращает пропуск в массиве в null, и весь расчёт
        # очередей падал на ровном месте: «'NoneType' object has no attribute get».
        if not isinstance(obj, dict):
            continue
        typ = str(obj.get("type") or "kindergarten")
        policy = _SOCIAL_LATE_POLICY.get(typ) or _SOCIAL_LATE_POLICY["kindergarten"]
        auto_phase = max(int(policy["auto_earliest"]), _social_target_phase(str(policy["target"]), count))
        auto_phase = min(auto_phase, count)
        limit = obj.get("not_later_than")
        limit_value = int(limit) if isinstance(limit, (int, float)) and int(limit) >= 1 else None
        manual = obj.get("phase")
        manual_value = int(manual) if isinstance(manual, (int, float)) and int(manual) >= 1 else None

        if manual_value and not obj.get("auto"):
            phase = min(max(manual_value, 1), count)
            reason = "вручную"
        elif limit_value and limit_value < auto_phase:
            phase = min(max(limit_value, 1), count)
            reason = f"обязательство: не позже очереди {limit_value}"
        else:
            phase = auto_phase
            reason = "поздняя раскладка: разгружаем первую очередь"

        obj["phase"] = phase
        allocation.append({
            "name": str(obj.get("name") or policy["label"]),
            "type": typ,
            "capacity": float(obj.get("capacity", 0.0) or 0.0),
            "phase": phase,
            "auto_phase": auto_phase,
            "not_later_than": limit_value,
            "reason": reason,
            "moved_earlier": bool(limit_value and phase < auto_phase),
        })
    return allocation


def _consolidate_vri(phase_items: list[dict[str, Any]]) -> dict[str, Any]:
    """Сводный график ВРИ: одно обязательство проекта, доли очередей на общих датах."""
    money = ("principal", "interest", "total", "bridge", "pf", "equity")
    merged: dict[str, dict[str, Any]] = {}
    totals = {
        key: 0.0 for key in
        ("amount", "principal", "interest", "security_cost", "before_pf", "after_pf",
         "bridge", "pf", "equity", "cash", "gross", "relief")
    }
    warnings: list[str] = []
    enabled = False
    region = payment_mode = ""
    for item in phase_items:
        block = item["result"].get("vri") or {}
        if not block.get("enabled"):
            continue
        enabled = True
        region = block.get("region") or region
        payment_mode = block.get("payment_mode") or payment_mode
        for key in totals:
            totals[key] += float(block["totals"].get(key, 0.0) or 0.0)
        for warning in block.get("warnings") or []:
            if warning not in warnings:
                warnings.append(warning)
        for row in block.get("rows") or []:
            slot = merged.setdefault(row["date"], {
                "date": row["date"], "before_pf": row["before_pf"], "by_phase": {},
                **{key: 0.0 for key in money},
            })
            for key in money:
                slot[key] += float(row.get(key, 0.0) or 0.0)
            slot["by_phase"][item["name"]] = slot["by_phase"].get(item["name"], 0.0) + float(row["total"])
            slot["before_pf"] = slot["before_pf"] or row["before_pf"]
    rows = []
    balance = totals["amount"]
    for date_key in sorted(merged):
        slot = merged[date_key]
        balance = max(0.0, balance - slot["principal"])
        rows.append({
            **{key: round(slot[key], 2) for key in money},
            "date": date_key, "period": len(rows) + 1,
            "before_pf": slot["before_pf"], "balance_after": round(balance, 2),
            "by_phase": {name: round(value, 2) for name, value in slot["by_phase"].items()},
        })
    return {
        "enabled": enabled,
        "region": region,
        "payment_mode": payment_mode,
        "rows": rows,
        "totals": {key: round(value, 2) for key, value in totals.items()},
        "warnings": warnings,
    }


def _calculate_phased_once(req: PhasedCalcRequest) -> dict[str, Any]:
    x_master = copy.deepcopy(req.inputs)
    t_master = copy.deepcopy(req.tep)
    rates = copy.deepcopy(req.rates)
    phasing = copy.deepcopy(req.phasing or {})
    phases_cfg = phasing.get("phases") or []
    count = max(1, min(5, int(phasing.get("phase_count") or len(phases_cfg) or 1)))

    if not phasing.get("enabled") or count <= 1:
        single = calculate(CalcRequest(inputs=x_master, tep=t_master, rates=rates))
        return {"mode": "single", "consolidated": single, "phases": [], "comparison": []}

    # Строка подземного паркинга выводится ДО деления: очередь получает долю
    # уже посчитанной проектной площади. Прежде деление шло по присланной
    # строке, а проект считался по выведенной — на 6 000 м² кладовых сумма
    # очередей выходила 41 965 м² против 35 965 у одиночного расчёта, то есть
    # этаж кладовых доставался очередям вторым экземпляром.
    apply_underground_tep_row(x_master, t_master)
    apply_storage_tep_row(x_master, t_master)
    # Тип проекта — тем же предикатом, что у одиночного расчёта, и в том же
    # месте: после строк МКД и до деления. Очередь иначе получила бы долю
    # паркинга дома и мест ДОО, которых нежилой проект не строит.
    kind_leftovers = nonresidential_leftovers(x_master, t_master)
    x_master, t_master = residential_excluded(x_master, t_master)
    instance_notes = object_instance_notes(x_master)
    x_master, t_master = object_instances_applied(x_master, t_master)

    while len(phases_cfg) < count:
        phases_cfg.append({
            "name": f"О{len(phases_cfg)+1}",
            "start_offset_months": len(phases_cfg) * int(phasing.get("phase_gap_months", 12)),
            "construction_months": int(n(x_master, "construction_months", 24)),
        })
    # Дополненную конфигурацию надо вернуть наружу. «phasing.get("phases") or []»
    # для пустого списка отдаёт новый объект, и достроенные очереди оставались
    # внутри функции: отчёт показывал сдвиг старта и сроки прочерками.
    phasing["phases"] = phases_cfg

    default_weights = _default_phase_weights(count)
    phase_product_rows, product_weights = _phase_tep_product_rows(t_master, phasing, count)

    shared_cash = phasing.get("shared_cash") or {}
    shared_alloc = phasing.get("shared_allocation") or {}
    cash_defaults = phase_cash_default_weights(count)
    cash_weights = {
        key: _normalized_phase_weights(shared_cash.get(key), count, cash_defaults[key])
        for key in cash_defaults
    }
    # Статья «по объёму» (`shared_cash[key] == "volume"`): очередь платит
    # проектирование, подготовку и сети по своему строительному объёму, и цена
    # метра у каждой равна вводной. Общая сумма, делённая долями, не
    # привязанными к объёму, давала первой очереди 25,9 тыс ₽/м² при вводной
    # 14,5, а офисной третьей — 6,3 (владелец, 04.09.2026: «а если ставить
    # 42, то и удельные вводные меняться должны»). Доля считается по ТЭП
    # очереди, когда он собран, — перед запуском её расчёта.
    volume_articles = {
        key for key in ("ird", "design", "preparation", "utilities")
        if isinstance(shared_cash.get(key), str) and shared_cash.get(key).strip().lower() == "volume"
    }
    # База этих статей в движке — ГНС МКД (квартиры, коммерция 1 этажа,
    # подземный паркинг, кладовые): у офисов, ТЦ и наземного паркинга своя
    # цена «всё включено». Доля «по объёму» берётся от той же базы — иначе
    # очередь с офисами платила бы за проектирование объекта, которое уже
    # сидит в его цене, а цена метра расходилась бы с вводной.
    _SHARED_BASE_KEYS = ("apartments", "ground_commercial", "underground_parking", "storage")
    def _shared_base_gns(rows: dict[str, Any]) -> float:
        return sum(float(((rows or {}).get(key) or {}).get("gns") or 0.0) for key in _SHARED_BASE_KEYS)
    # База очереди известна до расчёта — это её строки продуктов; доли
    # нормируются к сумме баз очередей, чтобы сходиться в 100% по построению.
    queue_base_gns = [
        sum(float(((phase_product_rows[i].get(key) if key in phase_product_rows[i] else (t_master.get(key) or {})) or {}).get("gns") or 0.0)
            for key in _SHARED_BASE_KEYS)
        for i in range(count)
    ]
    queue_base_total = sum(queue_base_gns)
    if volume_articles and queue_base_total > 0:
        for key in volume_articles:
            cash_weights[key] = [g / queue_base_total * 100.0 for g in queue_base_gns]
    # Снос и расселение — те же деньги до РнС, что и подготовка площадки, и
    # без своей доли они идут её долей (в том числе «по объёму»): в книге у них
    # та же колонка доли, второго ответа на «кто платит» быть не должно.
    for key in ("demolition", "resettlement"):
        if not shared_cash.get(key):
            cash_weights[key] = list(cash_weights["preparation"])
    allocation_weights = {
        key: _normalized_phase_weights(shared_alloc.get(key), count, default_weights)
        for key in (*cash_defaults.keys(), "social_construction")
    }

    x_base = copy.deepcopy(x_master)
    x_base["scenario_cost_multiplier"] = 1.0
    x_base["scenario_revenue_multiplier"] = 1.0
    base_op = build_operating_model(x_base, copy.deepcopy(t_master), rates)
    base_amounts = base_op["capex_amounts"]
    master_vri_obligation = _vri_settings(x_master, base_op["permit"])["obligation_date"]
    shared_base_mln = {
        "purchase": n(x_master, "purchase_price_mln"),
        "land_rights": base_amounts.get("land_rights", 0.0) / 1_000_000,
        "ird": base_amounts.get("ird", 0.0) / 1_000_000,
        "design": (base_amounts.get("design_p", 0.0)+base_amounts.get("design_rd", 0.0))/1_000_000,
        "preparation": base_amounts.get("preparation", 0.0) / 1_000_000,
        "utilities": base_amounts.get("utilities", 0.0) / 1_000_000,
        "demolition": base_amounts.get("demolition", 0.0) / 1_000_000,
        "resettlement": base_amounts.get("resettlement", 0.0) / 1_000_000,
        "social_compensation": n(x_master, "social_compensation_mln") if str(x_master.get("social_mode"))=="Денежная компенсация" else 0.0,
    }

    # Пропуск в массиве JSON.stringify отдаёт как null. Чистим один раз здесь:
    # список читают несколько мест, и каждое падало бы на своём .get.
    social_objects = [copy.deepcopy(obj) for obj in (phasing.get("social_objects") or [])
                      if isinstance(obj, dict)]
    # Совмещённый режим тоже строит: без него реестр объектов оставался пустым,
    # стройка школы и садика в очередях исчезала, и соцнагрузка выходила нулевой.
    if (str(x_master.get("social_mode")) in ("Строительство", SOCIAL_MODE_BOTH)
            and not social_objects):
        # Реестр объектов пуст — собираем его из вводных, чтобы нагрузка не потерялась.
        for typ, key in (("kindergarten", "kindergarten_places"), ("school", "school_places"),
                         ("clinic", "clinic_capacity")):
            capacity = n(x_master, key)
            if capacity > 0:
                social_objects.append({
                    "name": _SOCIAL_LATE_POLICY[typ]["label"], "type": typ,
                    "capacity": capacity, "auto": True,
                    "not_later_than": x_master.get(f"{typ}_not_later_than"),
                })
    social_allocation = _phase_social_allocation(social_objects, count) if social_objects else []

    discrete = phasing.get("discrete") or {}
    # Объект, который очередь объявила своими метрами, размещён явно — и
    # умолчание `discrete` сажает его второй раз. ТЦ, объявленный в четвёртой
    # очереди, по умолчанию движка попадал ещё и во вторую: 92 845 м² ГНС
    # строились и продавались дважды, а подпись «Очередь 4 · ТЦ» при этом
    # выглядела верной. Явное размещение сильнее умолчания.
    explicitly_placed = {key for cfg in phases_cfg for key in _explicit_phase_products(cfg)}
    master_import = (x_master.get("_glavapu_import") or {}).get("normalized", {})
    phase_items: list[dict[str, Any]] = []
    comparison: list[dict[str, Any]] = []
    financing_strategy = _phase_financing_strategy(phasing)
    phasing["financing_strategy"] = financing_strategy
    # Dated, already-earned cash from completed/working earlier queues.  Each
    # source is consumed once; unused balances remain available to the next
    # queue, never to an earlier one.
    project_cash_sources: list[dict[str, Any]] = []
    project_cash_transfers: list[dict[str, Any]] = []
    tax_rate = n(x_master, "profit_tax_pct", 25) / 100
    scenario_cost = n(x_master, "scenario_cost_multiplier", 1.0)

    # Total social construction cost for analytical allocation.
    total_social_construction = 0.0
    if str(x_master.get("social_mode")) in ("Строительство", SOCIAL_MODE_BOTH):
        for obj in social_objects:
            capacity = float(obj.get("capacity", 0.0) or 0.0)
            typ = str(obj.get("type"))
            unit_cost = (
                n(x_master, "kindergarten_cost_mln_per_place") if typ == "kindergarten"
                else n(x_master, "school_cost_mln_per_place") if typ == "school"
                else n(x_master, "clinic_cost_mln_per_unit")
            )
            total_social_construction += capacity * unit_cost * 1_000_000 * scenario_cost

    # Нарастающая раздача мест гаража объектов: сумма по очередям обязана
    # сойтись с проектной, а место неделимо.
    object_parking_split: dict[str, tuple[float, int]] = {}

    # Население очередей — делитель заданной руками площади двора: та же
    # норма региона, что у самого счёта двора (`project_population`).
    given_yard = float(x_master.get("landscaping_area_sqm") or 0.0)
    _yard_region = str(x_master.get("vri_region") or "msk")
    phase_populations = [
        project_population({"apartments": phase_product_rows[i].get("apartments")
                            or t_master.get("apartments") or {}}, _yard_region)[0]
        for i in range(count)]
    phase_populations_total = sum(phase_populations)

    for idx in range(count):
        cfg = phases_cfg[idx]
        name = str(cfg.get("name") or f"О{idx+1}")
        offset = int(cfg.get("start_offset_months", idx*int(phasing.get("phase_gap_months",12))))
        p_inputs = copy.deepcopy(x_master)
        p_tep = copy.deepcopy(t_master)
        p_inputs["project_start"] = add_months(d(x_master["project_start"]), offset).isoformat()
        p_inputs["construction_months"] = int(cfg.get("construction_months", n(x_master,"construction_months",24)))
        p_inputs.pop("_glavapu_import", None)
        # Заданная руками ПЛОЩАДЬ двора — величина проекта: оставленная
        # очереди целиком, она благоустроила бы один и тот же двор столько раз,
        # сколько очередей. Очередь получает долю площади по своему населению,
        # и сумма очередей равна заданному числу ровно. Прежде площадь
        # приводилась к мере на человека и умножалась на население очереди, а
        # население каждой очереди округляется вверх: в Мытищах 7 145 жителей
        # по очередям против 7 143 по проекту, и вписанные 78 595 м² в своде
        # становились 78 617 (владелец, 05.10.2026).
        if given_yard > 0 and phase_populations_total > 0:
            p_inputs["landscaping_area_sqm"] = (
                given_yard * phase_populations[idx] / phase_populations_total)
        elif given_yard > 0:
            p_inputs["landscaping_area_per_person_sqm"] = landscaping_area_per_person(
                x_master, t_master)[0]
            p_inputs["landscaping_area_sqm"] = 0.0

        # Mass products are split only in the phasing wrapper; the atomic single-phase engine is unchanged.
        for key, split_row in phase_product_rows[idx].items():
            if key in p_tep:
                p_tep[key] = copy.deepcopy(split_row)
                # Several products are read by the atomic engine from inputs,
                # not directly from the TEP table. Keep those aliases equal
                # to the queue row, otherwise a 50% office share is overwritten
                # by the full project office area during calculation.
                for field, input_key in _PHASE_PRODUCT_INPUT_ALIASES.get(key, {}).items():
                    p_inputs[input_key] = float(split_row.get(field) or 0.0)

        # Поделённую строку паркинга нельзя отдавать движку вместе с общим
        # решением по машино-местам: атомарный расчёт считает поле «решение
        # проекта» главнее ТЭП и в каждой очереди перетирал долю полным итогом.
        # На Мытищах 2 723 места превращались в 8 169 — ровно втрое, — и то же
        # самое происходило с подземной ГНС. Доля очереди объявляется здесь и
        # тем же полем, иначе движок посчитает по своему.
        if not b(p_inputs, "underground_parking_disabled"):
            parking_row = p_tep.get("underground_parking") or {}
            if n(x_master, "underground_manual_spaces") > 0 or n(x_master, "underground_manual_gns_sqm") > 0:
                p_inputs["underground_manual_spaces"] = n(parking_row, "units")
                p_inputs["underground_manual_gns_sqm"] = n(parking_row, "gns")
            # Доля очереди посчитана здесь — значит она объявлена, и движок её
            # не выводит заново. Иначе норматив пересчитал бы строку от квартир
            # ОЧЕРЕДИ и разбиение исчезло бы, а кладовые вычлись бы дважды:
            # площадь очереди — доля уже очищенной проектной.
            if isinstance(parking_row, dict):
                parking_row[TEP_ROW_DECLARED] = True

        # Cost inflation belongs to the queue wrapper, not to the atomic engine.
        cost_inflation_factor = _phase_cost_inflation_factor(phasing, offset)
        for cost_key in _PHASE_INFLATABLE_INPUTS:
            p_inputs[cost_key] = n(x_master, cost_key) * cost_inflation_factor

        # Queue launch price inflation is independent of monthly price growth during sales.
        # At 8% annual and offsets 0 / 12 / 24m => x1.000 / x1.080 / x1.1664.
        sales_price_inflation_factor = _phase_sales_price_inflation_factor(phasing, offset)
        p_inputs["apartment_price_th"] = n(x_master,"apartment_price_th")*sales_price_inflation_factor
        p_inputs["commercial_price_th"] = n(x_master,"commercial_price_th")*sales_price_inflation_factor
        p_inputs["parking_price_th"] = n(x_master,"parking_price_th")*sales_price_inflation_factor
        p_inputs["storage_price_th"] = n(x_master,"storage_price_th")*sales_price_inflation_factor

        p_inputs["purchase_price_mln"] = shared_base_mln["purchase"]*cash_weights["purchase"][idx]/100
        # Выкуп — часть сделки: той же долей, что цена участка.
        p_inputs["land_buyout_mln"] = n(x_master, "land_buyout_mln")*cash_weights["purchase"][idx]/100
        p_inputs["land_rights_cost_mln"] = shared_base_mln["land_rights"]*cash_weights["land_rights"][idx]/100
        # Свои средства — один котёл на проект: без деления каждая очередь
        # получила бы всю сумму, и проект «финансировал» бы себя вчетверо.
        p_inputs["pre_pf_own_funds_mln"] = (
            n(x_master, "pre_pf_own_funds_mln") * cash_weights["own_funds"][idx] / 100)
        # ВРИ — обязательство всего проекта, а не отдельной очереди. Рассрочка
        # (в Москве до шести лет) идёт по общему календарю: даты платежей у всех
        # очередей одни и те же, различается только доля. Поэтому дату
        # обязательства фиксируем абсолютной, иначе она уехала бы вместе со
        # стартом очереди и шестилетний график растянулся бы на срок проекта.
        p_inputs["vri_obligation_date"] = master_vri_obligation.isoformat()
        # Льгота уже срезана в базовом расчёте, из которого взята доля очереди:
        # применять её повторно к доле нельзя.
        p_inputs["vri_relief_mode"] = "none"

        if str(x_master.get("social_mode")) == "Денежная компенсация":
            p_inputs["social_mode"] = "Денежная компенсация"
            sw = cash_weights["social_compensation"][idx]/100
            p_inputs["social_compensation_mln"] = shared_base_mln["social_compensation"]*sw
            shifted_comp_date = d(_shift_iso(x_master.get("social_comp_date"), offset))
            phase_start_date = d(p_inputs["project_start"])
            p_inputs["social_comp_date"] = max(shifted_comp_date, phase_start_date).isoformat()
            p_inputs["kindergarten_places"] = p_inputs["school_places"] = p_inputs["clinic_capacity"] = 0
            # Места обнулялись, а строки ТЭП соцобъектов оставались в каждой
            # очереди целиком: свод показывал ДОУ и СОШ трижды, и ГНС проекта
            # росла на 29 тыс. м² из воздуха. Денег это не стоило — соцобъекты
            # в этом режиме не строятся, — но по ГНС считаются все удельные
            # показатели. Объект остаётся в первой очереди, чтобы свод сходился
            # с исходным ТЭП, как у офисов и наземного паркинга.
            if idx > 0:
                for social_key in ("kindergarten", "school", "clinic"):
                    if social_key in p_tep:
                        p_tep[social_key] = _zero_tep_row(p_tep[social_key])
            if master_import:
                p_inputs["_glavapu_import"] = {"normalized": {
                    "social_compensation_kindergarten_mln": n(master_import,"social_compensation_kindergarten_mln")*sw,
                    "social_compensation_school_mln": n(master_import,"social_compensation_school_mln")*sw,
                    "social_compensation_clinic_mln": n(master_import,"social_compensation_clinic_mln")*sw,
                }}
        else:
            p_inputs["social_mode"] = "Строительство"
            # Совмещённый режим: стройка расходится по очередям своими
            # объектами, а денежная часть — кассовыми долями, как обычная
            # компенсация. Без этого очередь получала только стройку, и 1,15
            # млрд по спортивному объекту исчезали из фазового расчёта.
            if str(x_master.get("social_mode")) == SOCIAL_MODE_BOTH:
                cash_share = cash_weights["social_compensation"][idx] / 100
                cash_part = n(x_master, "social_compensation_mln") * cash_share
                if cash_part > 0:
                    p_inputs["social_mode"] = SOCIAL_MODE_BOTH
                    p_inputs["social_compensation_mln"] = cash_part
                    shifted = d(_shift_iso(x_master.get("social_comp_date"), offset))
                    p_inputs["social_comp_date"] = max(
                        shifted, d(p_inputs["project_start"])).isoformat()
                else:
                    p_inputs["social_compensation_mln"] = 0.0
            p_inputs["kindergarten_cost_mln_per_place"] = n(x_master,"kindergarten_cost_mln_per_place")*cost_inflation_factor
            p_inputs["school_cost_mln_per_place"] = n(x_master,"school_cost_mln_per_place")*cost_inflation_factor
            p_inputs["clinic_cost_mln_per_unit"] = n(x_master,"clinic_cost_mln_per_unit")*cost_inflation_factor
            sums = {"kindergarten":0.0,"school":0.0,"clinic":0.0}
            starts = {"kindergarten":[],"school":[],"clinic":[]}
            for obj in social_objects:
                if int(obj.get("phase",1) or 1) != idx+1:
                    continue
                typ = str(obj.get("type","kindergarten"))
                if typ not in sums:
                    continue
                sums[typ] += float(obj.get("capacity",0.0) or 0.0)
                if obj.get("start_date"):
                    starts[typ].append(str(obj["start_date"]))
            p_inputs["kindergarten_places"] = sums["kindergarten"]
            p_inputs["school_places"] = sums["school"]
            p_inputs["clinic_capacity"] = sums["clinic"]
            phase_start_date = d(p_inputs["project_start"])
            # Стройка не начинается раньше РнС своей очереди: до РнС у очереди
            # нет ни разрешения, ни ПФ, и садик, стартовавший в день старта
            # очереди, целиком ложился на БРИДЖ (1,89 млрд ₽ у О2 «Нагатино»)
            # — «БРИДЖ не может финансировать стройку» (владелец, 04.09.2026).
            phase_permit_date = add_months(
                phase_start_date, int(max(float(IRD_MONTHS_MIN), n(p_inputs, "ird_months", 18.0))))
            def phase_social_start(values: list[str]) -> str:
                candidate = d(min(values)) if values else phase_start_date
                # A social object assigned to a queue cannot start before that queue itself.
                return max(candidate, phase_start_date, phase_permit_date).isoformat()
            p_inputs["kindergarten_start"] = phase_social_start(starts["kindergarten"])
            p_inputs["school_start"] = phase_social_start(starts["school"])
            p_inputs["clinic_start"] = phase_social_start(starts["clinic"])
            # Метры соцобъекта очереди считаются тем же ответом, что и метры
            # проекта (`social_area_per_place`), а не зашитым числом: 12 и 13
            # м²/место, стоявшие здесь, НИЖЕ городского минимума в любой
            # ёмкости — и очередь показывала садик меньше, чем тот же садик в
            # проекте. Бюджет объекта при этом по-прежнему идёт от МЕСТ
            # (решение владельца, 03.09.2026: «логику, что бюджет стройки
            # берётся от места, а не от ГНС, сохраняем; ГНС нам нужен для
            # контроля общей площади»), поэтому здесь считается только площадь.
            for typ, label, tep_key in (("kindergarten","ДОО","kindergarten"),
                                        ("school","СОШ","school"),
                                        ("clinic","Поликлиника","clinic")):
                # Строку считает тот же `social_tep_row`, что и одиночный
                # расчёт со страницей: своя арифметика здесь давала садику
                # разный ТЭП в зависимости от того, считают проект одной
                # очередью или несколькими.
                row = social_tep_row(x_master, typ, sums[typ])
                area = row["total_area"]
                master_places = n(x_master, SOCIAL_TEP_FIELDS[typ][0], 0.0)
                share_of_project = (sums[typ] / master_places) if master_places > 0 else 0.0
                p_tep[tep_key] = {**p_tep.get(tep_key,{"label":label}),
                    "gns": row["gns"], "total_area": area, "useful": 0.0,
                    "saleable": 0.0, "transfer": row["transfer"], "units": row["units"]}
                # Площадь очереди уходит и во вводные: книга и выгрузка читают
                # её оттуда, и оставленная от проекта она показала бы в каждой
                # очереди метры ВСЕХ садиков разом. Норматив — тоже: ступень
                # РНГП идёт от размера ЗДАНИЯ, а расчёт очереди пересчитал бы
                # её по ёмкости очереди и уменьшил объект вдвое на середине.
                p_inputs[SOCIAL_TEP_FIELDS[typ][1]] = area
                p_inputs[SOCIAL_TEP_FIELDS[typ][2]] = (
                    area / row["units"] if row["units"] > 0 else 0.0)
                # Выгрузка ГлавАПУ несёт СПП объекта ПРОЕКТА, и она сильнее
                # пропорции. Оставленная очереди целиком, она дала бы каждой
                # ГНС всего садика: доля очереди уменьшается вместе с
                # площадью, как и всё остальное.
                _scale_glavapu_social(p_inputs, typ, share_of_project)
                # Ёмкость здания — у проекта: без неё повторный расчёт по
                # вводным очереди берёт ступень РНГП по её доле мест.
                p_inputs.setdefault(SOCIAL_BUILDING_PLACES, {})[typ] = master_places

        # Дефолтные очереди объектов — те же, что на странице и в билдере
        # книги (офисы — 3, ТЦ и паркинг — 2): без discrete движок сажал
        # офисы в первую очередь, книга — в третью, и поверхности молча
        # расходились на весь объём объекта.
        # Признак включения и удельные вводные объекта объявлены рядом с ним, а
        # не цепочкой «если офисы, иначе если ТЦ, иначе паркинг»: четвёртый
        # объект в такой цепочке молча получил бы вводные третьего.
        # Состав — реестр: перечисленный здесь поимённо, он пропускал новый
        # объект мимо выбора очереди, и объект вне списка оставался включённым
        # в КАЖДОЙ очереди — его выручка считалась столько раз, сколько очередей.
        for _obj in STANDALONE_OBJECTS:
            prefix, tep_key, default_queue, enabled_key = (
                _obj.prefix, _obj.key, _obj.default_queue, _obj.enabled_key)
            rate_keys = (_obj.rate_cost, _obj.rate_price)
            if tep_key in explicitly_placed:
                declared = _explicit_phase_products(cfg).get(tep_key) or {}
                p_inputs[enabled_key] = bool(x_master.get(enabled_key)) and bool(
                    n(declared, "gns") or n(declared, "saleable") or n(declared, "units"))
            elif tep_key in product_weights:
                # Explicit percentages mean this is a set of queue objects,
                # not one discrete object assigned through the dropdown.
                row = p_tep.get(tep_key) or {}
                p_inputs[enabled_key] = bool(x_master.get(enabled_key)) and bool(
                    n(row, "gns") or n(row, "saleable") or n(row, "units"))
            else:
                assigned = int(discrete.get(tep_key, default_queue) or default_queue)
                # Очередь за пределами проекта уронила бы объект в никуда.
                assigned = max(1, min(count, assigned))
                p_inputs[enabled_key] = bool(x_master.get(enabled_key)) and assigned==idx+1
            # Объект не в этой очереди — значит и метров его здесь нет. Гасить
            # один выключатель мало: площадь объекта движок читает из вводных,
            # и оставленное «на всякий случай» число видно и в ТЭП очереди, и
            # в её выгрузке — там, где объекта нет вовсе.
            if not p_inputs[enabled_key]:
                if tep_key in p_tep:
                    p_tep[tep_key] = _zero_tep_row(p_tep[tep_key])
                for field, input_key in _PHASE_PRODUCT_INPUT_ALIASES.get(tep_key, {}).items():
                    p_inputs[input_key] = 0.0
            else:
                for suffix in ("start","sales_start"):
                    dk=f"{prefix}_{suffix}"
                    if dk in p_inputs:
                        p_inputs[dk]=_shift_iso(x_master.get(dk),offset)
                # Объект строится в своей очереди — и не раньше её РнС: офисы
                # третьей очереди стартовали за полгода до её РнС, и 7,3 млрд ₽
                # их стройки лежали на БРИДЖе. Продажи — не раньше стройки.
                build_key, sales_key = f"{prefix}_start", f"{prefix}_sales_start"
                permit_date = add_months(
                    d(p_inputs["project_start"]),
                    int(max(float(IRD_MONTHS_MIN), n(p_inputs, "ird_months", 18.0))))
                if p_inputs.get(build_key):
                    build_date = max(d(p_inputs[build_key]), permit_date)
                    p_inputs[build_key] = build_date.isoformat()
                    if p_inputs.get(sales_key):
                        p_inputs[sales_key] = max(d(p_inputs[sales_key]), build_date).isoformat()
                cost_key, price_key = rate_keys
                p_inputs[cost_key]=n(x_master,cost_key)*cost_inflation_factor
                p_inputs[price_key]=n(x_master,price_key)*sales_price_inflation_factor

        # Percentages above are only the initial allocation. Absolute queue TEP
        # is authoritative once a user edits it; consolidation remains bottom-up.
        explicit_products = _apply_explicit_phase_products(p_tep, p_inputs, cfg)

        # Места гаража объекта — вводная ПРОЕКТА, и в карте деления по очередям
        # её не было: у объекта, разложенного долями, КАЖДАЯ очередь строила и
        # продавала весь гараж. На офисе из 100 мест это 200 мест и 5 600 м²
        # подземной части вместо 100 и 2 800 — двойной CAPEX подземной части и
        # двойная выручка паркинга, при верном на вид ТЭП. Ровно так уже
        # терялись гостевые места и решение по подземному паркингу проекта.
        # Доля берётся у метров самого объекта, а не выводится вторым правилом
        # размещения, и стоит ПОСЛЕ явных метров очереди: до них у объявленного
        # метрами объекта в строке ещё проектное число.
        for tep_key, prefix, enabled_key, _sellable in OBJECT_PARKING_OBJECTS:
            share = _phase_object_share(t_master.get(tep_key), p_tep.get(tep_key))
            if not p_inputs.get(enabled_key):
                share = 0.0
            # Чьё число — решает тот же предикат, что у проекта: два правила
            # на один вопрос уже развели свод и очереди (Нагатино, 27.09.2026).
            by_hand = object_parking_by_hand(x_master, prefix)
            for suffix in ("under", "over"):
                field = f"{prefix}_parking_{suffix}_spaces"
                p_inputs[field] = float(_phase_place_allocation(
                    object_parking_split, field, n(x_master, field), share))
            if by_hand:
                p_inputs["_phase_parking_by_hand"] = sorted(
                    set(p_inputs.get("_phase_parking_by_hand") or ()) | {prefix})

        # Долг предыдущей очереди, принятый этой по генеральному соглашению.
        # Список кладёт обёртка calculate_phased после первого прохода: пока
        # очереди не посчитаны, переносить нечего.
        carried_list = phasing.get("_carried_debt_mln") or []
        if idx < len(carried_list):
            p_inputs["_phase_carried_debt_mln"] = float(carried_list[idx] or 0.0)
        # Месяц приёма — РВЭ передавшей очереди, а не открытие ПФ этой.
        carried_at = phasing.get("_carried_debt_month") or []
        if idx < len(carried_at) and carried_at[idx]:
            p_inputs["_phase_carried_debt_month"] = str(carried_at[idx])
        # Признак «долг уходит отсюда в РВЭ»: ставится передавшей очереди.
        leaves = phasing.get("_debt_leaves_at_rve") or []
        if idx < len(leaves) and leaves[idx]:
            p_inputs["_phase_debt_leaves_at_rve"] = True

        if idx > 0:
            p_inputs["_phase_project_cash_schedule"] = (
                _available_project_cash_schedule(project_cash_sources))
        if financing_strategy == "unified_project_cash":
            p_inputs["_phase_project_cash_funds_costs"] = True
        # Умолчание — включено (владелец, 31.08.2026: «в реальности иначе быть
        # не может»). Отсутствующий ключ — это «не задано», а не «снято»:
        # старые сохранённые проекты приезжают без него, и читать его как
        # выключенный значило бы молча считать их по прежней методике.
        # Снятая галочка приходит явным false — вот она и выключает.
        if _sweep_project_cash_enabled(phasing):
            p_inputs["_phase_sweep_project_cash"] = True
            p_inputs["_phase_cash_sweep_pct"] = float(
                phasing.get("cash_sweep_pct") or 80.0)
            # Что предыдущая очередь отдаёт банку помесячно — приходит сюда в
            # погашение принятого долга. Расписание собирается из уже
            # посчитанной очереди: своего баланса она не знает, а эта не знает
            # её продаж.
            if idx > 0 and phase_items:
                previous = (phase_items[-1].get("result") or {}).get("finance") or {}
                schedule = previous.get("bank_sweep_out_schedule") or {}
                if schedule:
                    p_inputs["_phase_bank_sweep_schedule"] = dict(schedule)

        # Общепроектные статьи — после того как ТЭП очереди собран целиком
        # (продукты, объекты, соцобъекты): доля «по объёму» считается от него.
        design_total = shared_base_mln["design"]
        design_p_total = base_amounts.get("design_p",0.0)/1_000_000
        p_ratio = design_p_total/design_total if design_total else .5
        p_inputs["_cost_override_mln"] = {
            "ird": shared_base_mln["ird"]*cash_weights["ird"][idx]/100*cost_inflation_factor,
            "design_p": design_total*p_ratio*cash_weights["design"][idx]/100*cost_inflation_factor,
            "design_rd": design_total*(1-p_ratio)*cash_weights["design"][idx]/100*cost_inflation_factor,
            "preparation": shared_base_mln["preparation"]*cash_weights["preparation"][idx]/100*cost_inflation_factor,
            "utilities": shared_base_mln["utilities"]*cash_weights["utilities"][idx]/100*cost_inflation_factor,
            "demolition": shared_base_mln["demolition"]*cash_weights["demolition"][idx]/100*cost_inflation_factor,
            "resettlement": shared_base_mln["resettlement"]*cash_weights["resettlement"][idx]/100*cost_inflation_factor,
        }

        # Одобренный лимит ПФ у очередей — два поля, и оба настоящие
        # (владелец, 19.09.2026: «как правило дают общий лимит на всё в
        # рамках генеральных условий, а разбивку на очереди — когда одобряют
        # индивидуальные условия НКЛ»). Что значит общий, уточнено
        # 20.09.2026: «это сумма всех очередей, но реальным он становится
        # только для первой очереди, когда подписывается соответствующая
        # НКЛ. Когда доходит до второй очереди, лимит считается заново на
        # реальных цифрах, а не ожиданиях двухлетней давности. И так с каждой
        # очередью. Невыбранные лимиты автоматом в следующую очередь не идут».
        # Поэтому потолок очереди — только её лимит НКЛ; общий лимит проекта
        # потолком не служит ни одной очереди и остаётся ожиданием, которое
        # свод печатает рядом с суммой НКЛ. Пул «общий на четыре очереди, и
        # не важно, какая что расходует» владелец назвал маргинальным
        # исключением — раздача остатком по порядку снята.
        _individual_cap = max(0.0, float(cfg.get("pf_limit_approved_mln") or 0.0))
        if _individual_cap > 0:
            p_inputs["_pf_limit_cap_mln"] = _individual_cap
            p_inputs["_pf_limit_cap_source"] = "individual"
        else:
            # Поле проекта в вводных очереди — копия общего лимита, и
            # `calculate` прочитал бы его потолком ЭТОЙ очереди: ровно та
            # ошибка, с которой всё началось (каждой очереди — весь лимит).
            p_inputs["pf_limit_approved_mln"] = 0.0
        p_inputs["pf_limit_individual_mln"] = _individual_cap

        result = calculate(CalcRequest(inputs=p_inputs, tep=p_tep, rates=rates))

        project_cash_transfers.extend(_consume_project_cash_sources(
            project_cash_sources, result, idx + 1))
        # Свободная касса очереди копится всегда: при единой стратегии ею
        # финансируются расходы следующей, при любой — банк заберёт её в РВЭ,
        # если эскроу не хватило.
        for cash_month, amount in _phase_free_cash_schedule(result):
            project_cash_sources.append({
                "phase": idx + 1,
                "month": cash_month.isoformat(),
                "amount": amount,
                "remaining": amount,
            })

        cash_shared = sum(shared_base_mln[k]*cash_weights[k][idx]/100*scenario_cost for k in shared_base_mln)*1_000_000
        allocated_shared = sum(shared_base_mln[k]*allocation_weights[k][idx]/100*scenario_cost for k in shared_base_mln)*1_000_000
        if str(x_master.get("social_mode"))=="Строительство":
            cash_shared += result["summary"]["social_payment"]
            allocated_shared += total_social_construction*allocation_weights["social_construction"][idx]/100

        allocated_profit = result["summary"]["net_profit"] + (cash_shared-allocated_shared)*(1-tax_rate)

        phase_items.append({
            "name":name,"index":idx+1,"result":result,
            # Вводные и ТЭП очереди нужны выгрузке в шаблон ПЛАТО: без них она
            # заполняет каждый файл очереди данными всего проекта, и три файла
            # выходят одинаковыми.
            "inputs":p_inputs,"tep":p_tep,"products":explicit_products,
            "cash_shared_cost":cash_shared,"allocated_shared_cost":allocated_shared,
            "allocated_net_profit":allocated_profit,
            "product_weights":{k:product_weights[k][idx] for k in product_weights},
            "cost_inflation_factor":cost_inflation_factor,
            "cost_inflation_pct":float(phasing.get("cost_inflation_pct",8.0) or 0.0),
            "sales_price_inflation_factor":sales_price_inflation_factor,
            "sales_price_inflation_pct":float(phasing.get("sales_price_inflation_pct",8.0) or 0.0),
            "start_offset_months":offset,
        })
        # Удельные показатели считаем от кассовых величин самой очереди: общие
        # расходы уже сидят в её денежном потоке по кассовым весам, поэтому
        # рубль на метр сопоставим с кассовыми строками таблицы.
        p_saleable = float(result["summary"].get("monetizable_saleable_sqm") or 0.0)
        p_gns = float(result["summary"].get("project_gns_sqm") or 0.0)
        p_expenses = float(result["summary"].get("total_expenses") or 0.0)

        def per_th(value: float, area: float) -> float:
            return value / area / 1000.0 if area else 0.0

        # Цена метра очереди по общепроектным статьям — то, что она платит на
        # свой строительный объём; рядом вводная проекта. При долях «по
        # объёму» они равны (с поправкой на инфляцию очереди), при заданных
        # руками — расходятся, и это видно числом, а не угадывается.
        override = p_inputs.get("_cost_override_mln") or {}
        p_core_gns = queue_base_gns[idx] if idx < len(queue_base_gns) else _shared_base_gns(p_tep)
        shared_rates_th = {
            "ird": per_th(float(override.get("ird") or 0.0) * 1_000_000, p_core_gns),
            "design": per_th((float(override.get("design_p") or 0.0) + float(override.get("design_rd") or 0.0)) * 1_000_000, p_core_gns),
            "preparation": per_th(float(override.get("preparation") or 0.0) * 1_000_000, p_core_gns),
            "utilities": per_th(float(override.get("utilities") or 0.0) * 1_000_000, p_core_gns),
        }
        shared_rate_inputs_th = {
            "ird": n(x_master, "ird_th_per_sqm"),
            "design": n(x_master, "design_p_th_per_sqm") + n(x_master, "design_rd_th_per_sqm"),
            "preparation": n(x_master, "preparation_th_per_sqm"),
            "utilities": n(x_master, "utilities_th_per_sqm"),
        }

        p_total_area = float(result["summary"].get("construction_volume_sqm") or 0.0)
        comparison.append({
            "name":name,"saleable_sqm":result["summary"]["monetizable_saleable_sqm"],
            "shared_rates_th":shared_rates_th,
            "shared_rate_inputs_th":shared_rate_inputs_th,
            "shared_rate_base_sqm":p_core_gns,
            "shared_cash_applied":{k:round(float(cash_weights[k][idx]),4) for k in cash_weights},
            # Чисто квартирная удельная цена: смешанные периметры («вся выручка
            # на м²» против «площадные продукты») не сверить глазами, а
            # квартиры на м² продаваемой — общий знаменатель отчёта и книги.
            "apartment_price_th":result["summary"].get("average_apartment_price_th", 0.0),
            "apartment_saleable_sqm":result["summary"].get("apartment_saleable_sqm", 0.0),
            # ГНС очереди — наземная; подземная и объём стоят рядом своими
            # полями: удельный показатель без второй базы читается как другой.
            "gns_sqm":p_gns,"total_expenses":p_expenses,
            "underground_gns_sqm":float(result["summary"].get("underground_gns_sqm") or 0.0),
            "construction_volume_sqm":float(result["summary"].get("construction_volume_sqm") or 0.0),
            # Гараж отдельно стоящих объектов очереди: построено, продаётся и
            # сколько это подземной площади. Считает движок очереди, экран
            # только печатает — второй счёт той же величины однажды разошёлся
            # бы с первым, и обе строки выглядели бы верными.
            "object_parking_units":float((result.get("parking") or {}).get("own_units") or 0.0),
            "object_parking_saleable_units":float(
                (result.get("parking") or {}).get("own_saleable_units") or 0.0),
            "object_parking_under_gns":float(
                (result.get("parking") or {}).get("own_under_gns") or 0.0),
            "revenue_per_saleable_th":per_th(result["summary"]["revenue"], p_saleable),
            # Базы — решение 4 ревизии книги: выручка и прибыль на
            # продаваемую, расходы на суммарную площадь в ГНС (и на
            # продаваемую для сравнения с ценой).
            "capex_per_total_area_th":per_th(result["summary"]["capex"], p_total_area),
            "capex_per_saleable_th":per_th(result["summary"]["capex"], p_saleable),
            "expenses_per_saleable_th":per_th(p_expenses, p_saleable),
            "expenses_per_total_area_th":per_th(p_expenses, p_total_area),
            "net_profit_per_saleable_th":per_th(result["summary"]["net_profit"], p_saleable),
            "revenue":result["summary"]["revenue"],"capex":result["summary"]["capex"],
            # Выручка очереди по продуктам. Одной строкой она не отвечает на
            # вопрос, чем очередь живёт: у одной весь объём в квартирах, у
            # другой треть в паркинге и ОСЗ, а маржа и риск у них разные.
            # Числа берутся из отчёта очереди, а не считаются здесь заново.
            "revenue_by_product":{
                str(item.get("key")): float(item.get("revenue") or 0.0)
                for item in (result.get("report") or {}).get("products") or []},
            "saleable_by_product":{
                str(item.get("key")): float(item.get("quantity") or 0.0)
                for item in (result.get("report") or {}).get("products") or []},
            # CAPEX объекта — его собственная статья очереди: стройка вместе
            # со своим гаражом (паркинг объекта своего расхода не имеет, он в
            # статье объекта — так и в книге, `'ОБЪЕКТЫ'!B28`). Число берётся
            # из расчёта очереди, а не делится на странице.
            "capex_by_object":{
                o.key: float((result.get("capex") or {}).get(o.key) or 0.0)
                for o in STANDALONE_OBJECTS
                if float((result.get("capex") or {}).get(o.key) or 0.0) > 0.5},
            "cash_shared_cost":cash_shared,"allocated_shared_cost":allocated_shared,
            "peak_bridge":result["finance"]["peak_bridge"],"peak_pf":result["finance"]["peak_pf"],
            # Раскрытие эскроу — событие очереди, а не проекта: у каждой своя
            # дата РВЭ, свой лимит и свой остаток. В своде эти строки
            # складывались под именами моментов и читались как одно событие
            # (владелец, 31.08.2026: «раскрытый эскроу в РВЭ — какое из них?»).
            # Место им — здесь, рядом с именем очереди.
            "rve": str((result.get("dates") or {}).get("rve") or ""),
            "pf_limit": result["finance"].get("pf_limit", 0.0),
            "rve_pf_before_repayment": result["finance"].get("rve_pf_before_repayment", 0.0),
            "rve_escrow_release": result["finance"].get("rve_escrow_release", 0.0),
            "rve_pf_repayment": result["finance"].get("rve_pf_repayment", 0.0),
            "rve_pf_shortfall": result["finance"].get("rve_pf_shortfall", 0.0),
            "pf_shortfall": result["finance"].get("pf_shortfall", 0.0),
            "pf_shortfall_month": result["finance"].get("pf_shortfall_month", ""),
            # Непогашенный долг очереди в таблице сравнения не выводился вовсе:
            # очередь, не рассчитавшаяся с банком, выглядела в ней так же, как
            # закрывшая долг, — разница пряталась в отдельной карточке отчёта
            # одной очереди. Дефолт старше бумажной прибыли, и стоять он обязан
            # там, где очереди сравнивают.
            "ending_pf":result["finance"].get("ending_pf", 0.0),
            # Принято от предыдущей очереди и передано следующей. Первое движок
            # знает сам, второе дописывает перенос: у передавшей очереди долг
            # обнуляется, и без этой строки он исчезал бы бесследно — читатель
            # увидел бы ноль и не понял, платит его теперь кто-то другой или
            # очередь рассчиталась сама.
            "carried_debt_in":result["finance"].get("carried_debt_in", 0.0),
            "debt_carried_out":result["finance"].get("debt_carried_out", 0.0),
            "llcr":result["summary"]["llcr"],"net_profit":result["summary"]["net_profit"],
            # Налог очереди в таблице был не выведен вовсе, хотя в книге он в
            # строке очереди стоит. Свод считает его как один налогоплательщик
            # и раздаёт обратно — без этого поля проверить, что очереди
            # складываются в итог, нечем.
            "profit_tax":result["summary"]["profit_tax"],
            "allocated_net_profit":allocated_profit,"margin":result["summary"]["margin"],
            "cost_inflation_factor":cost_inflation_factor,
            "sales_price_inflation_factor":sales_price_inflation_factor,
            "social_cost":sum(
                float(item.get("capacity", 0.0) or 0.0) * (
                    n(x_master, "kindergarten_cost_mln_per_place") if item["type"] == "kindergarten"
                    else n(x_master, "school_cost_mln_per_place") if item["type"] == "school"
                    else n(x_master, "clinic_cost_mln_per_unit")
                ) * 1_000_000 * cost_inflation_factor
                for item in social_allocation if item["phase"] == idx + 1
            ),
            "social_objects":[item["name"] for item in social_allocation if item["phase"] == idx + 1],
        })

    phase_financing = _phase_financing_summary(
        phase_items, financing_strategy, project_cash_transfers)
    for phase_item, comparison_row, financing_row in zip(
            phase_items, comparison, phase_financing["rows"]):
        phase_item["phase_financing"] = copy.deepcopy(financing_row)
        comparison_row.update({
            "pre_rns_costs": financing_row["pre_rns_costs"],
            "project_cash_used": financing_row["project_cash_used"],
            "own_funds": financing_row["own_funds"],
            "new_bridge": financing_row["new_bridge"],
        })
    consolidated = _consolidate_phase_results(
        x_master, phase_items, comparison, phase_financing)
    vri_summary = _consolidate_vri(phase_items)
    vri_summary["totals"]["gross"] = round(base_amounts.get("land_rights_gross", 0.0), 2)
    vri_summary["totals"]["relief"] = round(base_amounts.get("land_rights_relief", 0.0), 2)
    vri_summary["benefits"] = vri_benefits_for(x_master, t_master)
    consolidated["vri"] = vri_summary
    # Норматив приобъектной парковки — обязательство ОБЪЕКТА, то есть проекта:
    # офисник, разрезанный надвое, не становится двумя офисниками со своими
    # нормами (то же правило, что у ступени площади соцобъекта). У свода блока
    # не было вовсе, и подпись под полем уходила в холодное «Расчёт не
    # выполнен — норматив появится после пересчёта» ПРИ посчитанной модели,
    # да ещё и советовала проверить вход (экран владельца, 14.09.2026: «куда
    # пропала сверка с нормативом парковок???»). Ложная тревога такого рода
    # хуже молчания: человек ищет поломку там, где всё цело.
    #
    # Считается на КОПИЯХ: `apply_object_parking` не идемпотентна — метры
    # первых этажей вычитаются из продаваемой при каждом вызове, — и второй
    # проход по мастер-строке увёл бы продаваемую объекта вниз.
    consolidated["parking"] = apply_object_parking(
        copy.deepcopy(x_master), copy.deepcopy(t_master))
    # Тип проекта — свойство ПРОЕКТА, а не очереди, и в свод он попадает
    # отсюда: свод собирается заново, и поле, заведённое в одиночном расчёте,
    # до него само не доезжает. PDF читает именно свод — без этих двух ключей
    # у нежилого проекта с очередями не было бы ни строки «Тип проекта», ни
    # названного оставшегося жилья, и молчание читалось бы как жилой проект.
    summary_block = consolidated.get("summary")
    if isinstance(summary_block, dict):
        summary_block["project_kind"] = project_kind(x_master)
        summary_block["project_kind_leftovers"] = kind_leftovers
        summary_block["object_instances"] = list(project_object_instances(x_master))
        summary_block["object_instance_notes"] = instance_notes
    for item, row in zip(phase_items, comparison):
        row["vri_cash"] = item["result"].get("vri", {}).get("totals", {}).get("cash", 0.0)
    # Применённые кассовые доли — один ответ на движок и книгу: статья «по
    # объёму» в `shared_cash` стоит словом, а числа знает только этот расчёт.
    shared_cash_applied = {key: [round(float(w), 4) for w in ws] for key, ws in cash_weights.items()}
    phasing["shared_cash_applied"] = shared_cash_applied
    return {"mode":"phased","consolidated":consolidated,"phases":phase_items,"comparison":comparison,
            "shared_cash_applied":shared_cash_applied,
            "phasing":phasing,"social_allocation":social_allocation,"vri":vri_summary,
            "phase_financing":phase_financing}


# Порог, ниже которого банк долг не переносит. Перенос — не подарок: если
# проект в целом не обслуживает долг, перенос просто оттягивает дефолт, и
# банку это не нужно (решение владельца, 27.08.2026). Единица — минимальное
# осмысленное значение: дисконтированный поток покрывает долг ровно в ноль.
_PHASE_DEBT_CARRY_MIN_LLCR = 1.0
# Мельче этого «непогашенный долг» — след округления, а не обязательство.
_PHASE_DEBT_CARRY_MIN_RUB = 500_000.0


def product_groups(keys: Any) -> tuple[list[str], list[str]]:
    """Продукты по группам и в порядке чтения: МКД из `MKD_PRODUCTS`, затем
    отдельно стоящие объекты в порядке реестра `STANDALONE_OBJECTS`, и паркинг
    каждого объекта — сразу за своим объектом (`OBJECT_PARKING_PRODUCT_KEYS`),
    а не по имени. Продукт вне обоих списков идёт в ОСЗ следом, а не теряется.

    Один ответ для всех таблиц выручки: сравнения очередей и «Структуры
    выручки» — прежде вторая шла в порядке словаря движка, и паркинг ТЦ стоял
    перед квартирами, а офисы — посреди кладовых (владелец, 28.09.2026).
    """
    present = [str(k) for k in keys]
    have = set(present)
    mkd = [k for k in MKD_PRODUCTS if k in have]
    obj = [k for o in STANDALONE_OBJECTS
           for k in (o.key, OBJECT_PARKING_PRODUCT_KEYS.get(o.key, ""))
           if k and k in have]
    osz = obj + [k for k in present if k not in MKD_PRODUCTS and k not in obj]
    return mkd, osz


def revenue_structure(revenue: dict[str, Any], saleable: float = 0.0) -> dict[str, Any]:
    """«Структура выручки» — строки, которые печатает страница.

    Нулевой продукт — шум, а не полнота: семь строк «0 млрд ₽» между
    настоящими разрывали таблицу. Итог группы заводится, когда в ней больше
    одного продукта: «Итого МКД» под единственной строкой квартир — та же
    строка дважды. Последняя строка — «Итого» всей выручки.
    """
    labels = product_labels()
    values = {str(k): float(v or 0.0) for k, v in (revenue or {}).items() if k != "total"}
    mkd, osz = product_groups(values)
    rows: list[dict[str, Any]] = []
    for keys, label, group in ((mkd, "Итого МКД", "mkd"), (osz, "Итого ОСЗ", "osz")):
        mine = [k for k in keys if abs(values[k]) > 0.5]
        rows += [{"key": k, "label": labels.get(k, k), "value": values[k],
                  "role": "part", "group": group} for k in mine]
        if len(mine) > 1:
            rows.append({"label": label, "value": sum(values[k] for k in mine),
                         "role": "total", "group": group})
    total = float((revenue or {}).get("total") or sum(values.values()))
    rows.append({"label": "Итого", "value": total, "role": "total", "group": "all"})
    # Выручка — на продаваемую площадь проекта (решение 4 ревизии книги);
    # нулевая база — None, а не ноль.
    for item in rows:
        item["per_saleable_th"] = (item["value"] / saleable / 1000) if saleable else None
    return {"rows": rows, "base": UNIT_BASE_SALEABLE, "base_label": unit_label(UNIT_BASE_SALEABLE)}


def phase_comparison_table(consolidated: dict[str, Any]) -> dict[str, Any]:
    """Таблица «Сравнение очередей» — одна на страницу и PDF.

    Порядок строк жил на странице, а PDF печатал свой набор своими таблицами:
    две раскладки одного сравнения расходились бы молча (владелец, 27.09.2026:
    «PDF тоже надо сделать то же»). Здесь решается состав и порядок — блоки,
    строки, роль итога и слагаемого, сырые числа; поверхность только печатает
    число по его виду (`kind`): деньги, количество с единицей, тыс ₽/м²,
    процент, кратность, дата.

    Порядок — как в отчёте о прибылях: объёмы → выручка (и цена на м²) →
    затраты (ставки статей, CAPEX, полные расходы и их метр) →
    финансирование → результат, последней строкой — чистая прибыль на м².
    Делители метра — одна подпись таблицы (`divisors`), а не строки.
    """
    c = [item for item in (consolidated.get("comparison") or []) if isinstance(item, dict)]
    summary = consolidated.get("summary") or {}
    finance = consolidated.get("finance") or {}
    totals_fin = ((consolidated.get("phase_financing") or {}).get("totals") or {})
    products = [p for p in ((consolidated.get("report") or {}).get("products") or [])
                if isinstance(p, dict)]
    order = [str(p.get("key")) for p in products]
    by_key = {str(p.get("key")): p for p in products}

    def f(value: Any) -> float:
        try:
            return float(value or 0.0)
        except (TypeError, ValueError):
            return 0.0

    def rev(item: dict[str, Any], key: str) -> float:
        return f((item.get("revenue_by_product") or {}).get(key))

    def qty(item: dict[str, Any], key: str) -> float:
        return f((item.get("saleable_by_product") or {}).get(key))

    def row(label: str, kind: str, values: list[Any], total: Any, **extra: Any) -> dict[str, Any]:
        return {"label": label, "kind": kind, "values": values, "total": total, **extra}

    def per_th(value: float, area: float) -> float | None:
        return value / area / 1000.0 if area else None

    # Состав групп — из реестров движка: МКД из MKD_PRODUCTS, объекты из
    # STANDALONE_OBJECTS в его порядке, и паркинг каждого объекта — своей
    # строкой сразу за объектом (владелец, 27.09.2026): ключ продукта берётся
    # из реестра (`OBJECT_PARKING_PRODUCT_KEYS`), а не угадывается по имени.
    # Продукт вне обоих списков идёт в ОСЗ следом, а не теряется.
    mkd, osz = product_groups(order)
    obj_block = [k for k in osz if k in {o.key for o in STANDALONE_OBJECTS}
                 or k in OBJECT_PARKING_PRODUCT_KEYS.values()]

    # Объём к продаже — то количество, на которое движок продаёт; строка
    # заводится вместе с числом.
    def volume(keys: list[str], suffix: str = "") -> list[dict[str, Any]]:
        out = []
        for key in keys:
            if not any(qty(x, key) > 0 for x in c):
                continue
            p = by_key[key]
            out.append(row(str(p.get("label") or key) + suffix, "qty",
                           [qty(x, key) for x in c], f(p.get("quantity")),
                           unit=str(p.get("unit") or "")))
        return out

    # Выручка по продуктам: нулевые строки — шум, а не полнота. Итог группы
    # заводится, только когда продуктов в ней больше одного: «Итого МКД» под
    # единственной строкой квартир — та же строка дважды.
    def revenue_group(keys: list[str], label: str, group: str) -> list[dict[str, Any]]:
        mine = [k for k in keys if any(rev(x, k) > 0 for x in c)]
        out = [row(str(by_key[k].get("label") or k), "money", [rev(x, k) for x in c],
                   f(by_key[k].get("revenue")), role="part", group=group) for k in mine]
        if len(mine) > 1:
            out.append(row(label, "money", [sum(rev(x, k) for k in mine) for x in c],
                           sum(f(by_key[k].get("revenue")) for k in mine),
                           role="total", group=group))
        return out

    # Гараж объектов строится в СВОЕЙ очереди. Построено и продаётся — два
    # разных числа: у ТЦ и ФОКа места обеспечивают посетителей и не продаются,
    # у офисника продаются все, кроме гостевых. Оба считает движок очереди.
    park: list[dict[str, Any]] = []
    if any(f(x.get("object_parking_units")) > 0 for x in c):
        park = [
            row("Паркинг отдельно стоящих объектов — мест", "qty",
                [f(x.get("object_parking_units")) for x in c],
                f(summary.get("object_parking_units")), unit="шт."),
            row("из них продаётся", "qty",
                [f(x.get("object_parking_saleable_units")) for x in c],
                f(summary.get("object_parking_saleable_units")), unit="шт.", role="sub"),
            row("подземная часть под объектами", "qty",
                [f(x.get("object_parking_under_gns")) for x in c],
                f(summary.get("object_parking_under_gns")), unit="м²", role="sub"),
        ]

    # Долг, не погашенный очередью, и его перенос. Порядок — рассказ: сколько
    # пришло, сколько ушло, что осталось (владелец, 30.08.2026). Строки
    # заводятся вместе с числом.
    def any_debt(key: str) -> bool:
        return any(f(x.get(key)) > 0.5e6 for x in c)

    debt: list[dict[str, Any]] = []
    if any_debt("ending_pf") or any_debt("debt_carried_out") or any_debt("carried_debt_in"):
        if any_debt("carried_debt_in"):
            debt.append(row("Принято от предыдущей очереди", "money",
                            [f(x.get("carried_debt_in")) for x in c], None))
        if any_debt("debt_carried_out"):
            debt.append(row("Передано следующей очереди", "money",
                            [f(x.get("debt_carried_out")) for x in c], None))
        debt.append(row("Осталось непогашенным на очереди" if any_debt("debt_carried_out")
                        else "Непогашенный долг ПФ на конец очереди", "money",
                        [f(x.get("ending_pf")) for x in c], f(finance.get("ending_pf"))))

    sale, total_area = f(summary.get("monetizable_saleable_sqm")), f(summary.get("construction_volume_sqm"))
    rev_all = [f(x.get("revenue")) for x in c]
    # Ставки общепроектных статей — цена метра МКД очереди по статье, с
    # вводной рядом: заданная руками доля видна числом. Стоят ВИДИМЫМИ
    # строками в начале расходов, до CAPEX: это расходы, и после итоговой
    # прибыли им не место (владелец, 28.09.2026: «ничего не сворачивать»).
    inputs0 = (c[0].get("shared_rate_inputs_th") or {}) if c else {}
    rates = [row(label + " — цена м² МКД очереди", "th",
                 [(x.get("shared_rates_th") or {}).get(key) for x in c], None,
                 rate_input=inputs0.get(key))
             for key, label in (("ird", "ИРД и согласования"), ("design", "Проектирование П+РД"),
                                ("preparation", "Подготовительные работы"),
                                ("utilities", "Наружные сети"))]

    def money(label: str, key: str, total: Any) -> dict[str, Any]:
        return row(label, "money", [f(x.get(key)) for x in c], total)

    # CAPEX — зеркало «Выручки» (владелец, 29.09.2026): МКД → каждый объект
    # в порядке `product_groups`, паркинг объекта за объектом → Итого ОСЗ →
    # CAPEX всего. Порядок и состав — у того же владельца, что у выручки.
    # Объект — его собственная статья очереди; «МКД и общепроектные статьи»
    # — остаток CAPEX очереди: дома и всё, что движок не относит к объекту
    # (земля, ИРД, проектирование, надбавки, резерв), а не угаданная доля.
    def capex_obj(item: dict[str, Any], key: str) -> float:
        return f((item.get("capex_by_object") or {}).get(key))

    object_keys = {o.key for o in STANDALONE_OBJECTS}
    built = [k for k in (o.key for o in STANDALONE_OBJECTS)
             if any(capex_obj(x, k) > 0.5 for x in c)]
    capex_total = row("CAPEX всего", "money", [f(x.get("capex")) for x in c],
                      f(summary.get("capex")), role="total", group="capex_all")
    capex_rows: list[dict[str, Any]] = [capex_total]
    expense_note: list[dict[str, Any]] = []
    if built:
        cons_capex = consolidated.get("capex") or {}
        _, osz_order = product_groups(list(dict.fromkeys(order + built)))
        parking_of = {p: o for o, p in OBJECT_PARKING_PRODUCT_KEYS.items()}
        labels = product_labels()
        osz_rows: list[dict[str, Any]] = []
        for key in osz_order:
            if key in object_keys and key in built:
                osz_rows.append(row(labels.get(key, key), "money",
                                    [capex_obj(x, key) for x in c],
                                    f(cons_capex.get(key)) or sum(capex_obj(x, key) for x in c),
                                    role="part", group="capex_osz"))
            elif parking_of.get(key) in built and any(rev(x, key) > 0 for x in c):
                # Строка мест — зеркало выручки: заводится там же, где у
                # паркинга есть выручка, и говорит, где его расход.
                osz_rows.append(row(labels.get(key, key) + " — в CAPEX объекта", "note",
                                    [None for _ in c], None, role="sub"))
        mkd_values = [f(x.get("capex")) - sum(capex_obj(x, k) for k in built) for x in c]
        mkd_total = f(summary.get("capex")) - sum(r["total"] for r in osz_rows if r["role"] == "part")
        capex_rows = [row("МКД и общепроектные статьи", "money", mkd_values, mkd_total,
                          role="part", group="capex_mkd"), *osz_rows]
        parts = [r for r in osz_rows if r["role"] == "part"]
        if len(parts) > 1:
            capex_rows.append(row("Итого ОСЗ", "money",
                                  [sum(r["values"][i] for r in parts) for i in range(len(c))],
                                  sum(r["total"] for r in parts), role="total", group="capex_osz"))
        capex_rows.append(capex_total)
        # Полные расходы по объектам не делятся: финансирование, коммерческие
        # расходы и налог движок считает на очередь целиком, и пропорция
        # здесь была бы выдумкой (владелец: «не делить молча»).
        expense_note = [row("По объектам не делятся: финансирование, коммерческие "
                            "расходы и налог считаются на очередь целиком", "note",
                            [None for _ in c], None, role="sub")]

    def th(label: str, key: str, value: float, area: float) -> dict[str, Any]:
        return row(label, "th", [f(x.get(key)) for x in c], per_th(value, area))

    # Порядок — отчёт о прибылях (владелец, 28.09.2026): доходы → все
    # расходы подряд → финансирование → прибыль, и последней строкой таблицы
    # — чистая прибыль на м². Удельный стоит в разделе своей величины, рядом
    # с её деньгами, а не отдельным блоком, где цена, затраты и прибыль
    # шли вперемешку. Ни одна строка не свёрнута.
    blocks = [
        ("mkd", "Объём МКД — к продаже", volume(mkd)),
        ("osz", "Отдельно стоящие объекты",
         volume(obj_block, " — к продаже") + park),
        ("revenue", "Выручка",
         revenue_group(mkd, "Итого МКД", "mkd") + revenue_group(osz, "Итого ОСЗ", "osz")
         + [row("Выручка всего", "money", rev_all, f(summary.get("revenue")),
                role="total", group="all"),
            th("Цена реализации на м² продаваемой", "revenue_per_saleable_th",
               f(summary.get("revenue")), sale),
            # Чисто квартирная цена — общий знаменатель с Excel-книгой: в ней
            # та же строка, и числа обязаны совпадать один в один.
            row("в т.ч. квартиры — на м² их продаваемой", "th",
                [f(x.get("apartment_price_th")) for x in c],
                f(summary.get("average_apartment_price_th")) or None, role="sub"),
        ]),
        ("costs", "Затраты", [
            *rates,
            *capex_rows,
            th(f"CAPEX на м² {TOTAL_AREA.genitive}", "capex_per_total_area_th",
               f(summary.get("capex")), total_area),
            money("Полные расходы", "total_expenses", f(summary.get("total_expenses"))),
            *expense_note,
            th("Полные расходы на м² продаваемой", "expenses_per_saleable_th",
               f(summary.get("total_expenses")), sale),
            th(f"Полные расходы на м² {TOTAL_AREA.genitive}", "expenses_per_total_area_th",
               f(summary.get("total_expenses")), total_area)]),
        ("finance", "Финансирование", [
            money("Пиковый БРИДЖ", "peak_bridge", f(finance.get("peak_bridge"))),
            money("Затраты до РНС", "pre_rns_costs", f(totals_fin.get("pre_rns_costs"))),
            money("Свободный cash проекта", "project_cash_used",
                  f(totals_fin.get("project_cash_used"))),
            money("Собственные средства", "own_funds", f(totals_fin.get("own_funds"))),
            money("Новый БРИДЖ", "new_bridge", f(totals_fin.get("new_bridge"))),
            money("Пиковый остаток ПФ", "peak_pf", f(finance.get("peak_pf"))),
            # Раскрытие эскроу — событие очереди: у каждой своя дата РВЭ.
            money("Лимит ПФ", "pf_limit", f(finance.get("pf_limit"))),
            row("РВЭ очереди", "date", [str(x.get("rve") or "") for x in c], None),
            money("Долг ПФ перед раскрытием", "rve_pf_before_repayment",
                  f(finance.get("rve_pf_before_repayment"))),
            money("Раскрыто эскроу", "rve_escrow_release", f(finance.get("rve_escrow_release"))),
            money("Из него на погашение ПФ", "rve_pf_repayment", f(finance.get("rve_pf_repayment"))),
            money("Не покрыто эскроу при раскрытии", "rve_pf_shortfall",
                  f(finance.get("rve_pf_shortfall"))),
            *debt,
            row("LLCR", "mult", [f(x.get("llcr")) for x in c], f(summary.get("llcr")))]),
        # Аллокация общих расходов — аналитика рядом с прибылью, а сама
        # прибыль и её метр закрывают таблицу.
        ("result", "Результат", [
            money("Общепроектная нагрузка — cash", "cash_shared_cost", None),
            money("Аллоцированные общие расходы", "allocated_shared_cost", None),
            money("Аналитическая прибыль после аллокации", "allocated_net_profit", None),
            money("Чистая прибыль — cash", "net_profit", f(summary.get("net_profit"))),
            row("Маржинальность", "pct", [f(x.get("margin")) for x in c], f(summary.get("margin"))),
            th("Чистая прибыль на м² продаваемой", "net_profit_per_saleable_th",
               f(summary.get("net_profit")), sale)]),
    ]
    # Удельный подписан своим делителем: те же площади, на которые делит
    # движок (`monetizable_saleable_sqm`, `construction_volume_sqm`), а не угаданные
    # по заголовку. Это одна подпись таблицы мелким шрифтом, а не строки:
    # крупная «Делитель…» среди денег читалась как ещё одно число экономики
    # (владелец, 28.09.2026). Удельные стоят в нескольких разделах, делитель
    # у них общий. Итог удельного — отношение сумм, а не среднее.
    divisors = [
        {"label": "на м² продаваемой — продаваемая площадь", "unit": "м²",
         "values": [f(x.get("saleable_sqm")) for x in c], "total": sale},
        {"label": f"на м² {TOTAL_AREA.genitive} — {TOTAL_AREA.lower()} (наземная и подземная)",
         "unit": "м²",
         "values": [f(x.get("construction_volume_sqm")) for x in c], "total": total_area}]
    return {"columns": [str(x.get("name") or "") for x in c],
            "has_debt": bool(debt),
            "divisors": divisors,
            "blocks": [{"key": k, "title": t, "rows": r} for k, t, r in blocks if r]}


def calculate_phased(req: PhasedCalcRequest) -> dict[str, Any]:
    """Очереди и свод; решение о доходности капитала — по итоговому долгу.

    Свод решается после переноса долга между очередями: до него остаток
    свода ещё не приведён к очередям (см. `_calculate_phased_with_carry`).
    Очереди решены своим `calculate`.
    """
    bundle = _calculate_phased_with_table(req)
    if isinstance(bundle, dict):
        _finalize_result(bundle.get("consolidated"))
        for item in bundle.get("phases") or []:
            _finalize_result((item or {}).get("result"))
    return bundle


def _calculate_phased_with_table(req: PhasedCalcRequest) -> dict[str, Any]:
    """Очереди с переносом долга и таблицей сравнения.

    Таблица строится ПОСЛЕ переноса: перенос дописывает строкам сравнения
    принятый и переданный долг, и собранная раньше таблица их бы не знала.
    """
    bundle = _calculate_phased_with_carry(req)
    consolidated = bundle.get("consolidated")
    if bundle.get("mode") == "phased" and isinstance(consolidated, dict):
        consolidated["comparison_table"] = phase_comparison_table(consolidated)
    return bundle


def _calculate_phased_with_carry(req: PhasedCalcRequest) -> dict[str, Any]:
    """Очереди с переносом непогашенного долга вперёд.

    По генеральному соглашению долг, который очередь не погасила, переходит в
    ПФ следующей — лимита её он не выбирает, но проценты несёт и в знаменателе
    её LLCR стоит (ответы владельца, 27.08.2026). Условие одно и жёсткое:
    **общий LLCR проекта должен выдерживаться**. Не выдерживается — переноса
    нет, дефолт остаётся на своей очереди и называется вслух: банк не станет
    переносить обязательство ради того, чтобы отодвинуть тот же дефолт на год.

    Проходов несколько по необходимости: приняв долг, очередь может сама не
    погасить его до конца, и тогда остаток идёт дальше. Цепочка считается от
    первой очереди к последней, по проходу на стык.
    """
    bundle = _calculate_phased_once(req)
    if bundle.get("mode") != "phased":
        return bundle
    # Признак, а не умолчание: книга о переносе пока не знает, и включённый по
    # умолчанию перенос развёл бы движок с выгрузкой молча — оба документа
    # выглядели бы достоверными на одних вводных. Включается явно, и до тех
    # пор, пока лист CF книги не научится принимать долг предыдущей очереди,
    # включать его стоит только для расчёта на экране.
    if not bool((req.phasing or {}).get("carry_debt_forward")):
        return bundle
    phases = bundle.get("phases") or []
    if len(phases) < 2:
        return bundle

    def unpaid(item: dict[str, Any]) -> float:
        """Чего не хватило раскрытого эскроу — вот что переезжает.

        Владелец (29.08.2026): «долг переходит в тот момент, когда средства с
        эскроу после РВЭ предыдущей очереди раскрылись и их не хватило на
        погашение. При этом деньги от последующих продаж остаются у
        застройщика». Прежде бралось `ending_pf` — остаток на КОНЕЦ горизонта,
        то есть уже после того, как остаточные продажи год гасили долг на
        закрытой линии. На контрольном проекте это 4 229 млн вместо 7 816.
        """
        return float(((item.get("result") or {}).get("finance") or {}).get(
            "rve_pf_shortfall") or 0.0)

    def rve_month(item: dict[str, Any]) -> str:
        return str(((item.get("result") or {}).get("dates") or {}).get("rve") or "")

    # Переносить нечего, если долг остаётся только у последней очереди: дальше
    # него нет никого, и «перенос» был бы фикцией.
    if not any(unpaid(item) > _PHASE_DEBT_CARRY_MIN_RUB for item in phases[:-1]):
        return bundle

    consolidated_llcr = float(
        ((bundle.get("consolidated") or {}).get("summary") or {}).get("llcr") or 0.0)
    if consolidated_llcr < _PHASE_DEBT_CARRY_MIN_LLCR:
        # Молчать нельзя: без этой строки читатель увидит дефолтную очередь и
        # не поймёт, почему перенос, о котором сказано в методике, не сработал.
        refusal = {
            "applied": False,
            "project_llcr": round(consolidated_llcr, 4),
            "min_llcr": _PHASE_DEBT_CARRY_MIN_LLCR,
            "note": (
                f"Перенос долга между очередями не применён: общий LLCR проекта "
                f"{consolidated_llcr:.2f}x ниже {_PHASE_DEBT_CARRY_MIN_LLCR:.2f}x. "
                "Банк переносит обязательство только если проект в целом его "
                "обслуживает; иначе перенос лишь отодвигает дефолт."),
        }
        bundle["debt_carry"] = refusal
        if isinstance(bundle.get("consolidated"), dict):
            bundle["consolidated"]["debt_carry"] = copy.deepcopy(refusal)
        return bundle

    carried = [0.0] * len(phases)
    at: list[str] = [""] * len(phases)
    leaves: list[bool] = [False] * len(phases)
    applied: list[dict[str, Any]] = []
    current = bundle
    for idx in range(len(phases) - 1):
        left = unpaid((current.get("phases") or [])[idx])
        if left <= _PHASE_DEBT_CARRY_MIN_RUB:
            continue
        carried[idx + 1] = carried[idx + 1] + left
        at[idx + 1] = rve_month((current.get("phases") or [])[idx])
        leaves[idx] = True
        request = PhasedCalcRequest(
            inputs=copy.deepcopy(req.inputs), tep=copy.deepcopy(req.tep),
            rates=copy.deepcopy(req.rates),
            phasing={**copy.deepcopy(req.phasing or {}),
                     "_carried_debt_mln": [value / 1_000_000 for value in carried],
                     "_carried_debt_month": list(at),
                     "_debt_leaves_at_rve": list(leaves)})
        current = _calculate_phased_once(request)
        # Дописывать сверху здесь больше нечего: движок сам снимает долг с
        # передавшей очереди в её РВЭ и сам называет переданную сумму, а все
        # поверхности читают её у него. Пока это делалось правкой результата,
        # экземпляров было три — `finance`, строка сравнения и `report.
        # financing`, — и любой забытый показывал долг там, где его уже нет.
        applied.append({
            "from": idx + 1, "to": idx + 2,
            "amount": round(left, 2),
            "amount_mln": round(left / 1_000_000, 3),
            "at": at[idx + 1],
        })

    if not applied:
        return bundle
    # Свод собран внутри прохода — до того, как передавшей очереди списали
    # долг. Приводим его к очередям, иначе итог покажет непогашенным то, что
    # уже платит следующая, и вердикт снова назовёт проект дефолтным.
    ending_total = sum(
        float(((item.get("result") or {}).get("finance") or {}).get("ending_pf") or 0.0)
        for item in (current.get("phases") or []))
    consolidated = current.get("consolidated") or {}
    for section in ("finance", "summary"):
        block = consolidated.get(section)
        if isinstance(block, dict) and "ending_pf" in block:
            block["ending_pf"] = ending_total
    summary_block = consolidated.get("summary")
    if isinstance(summary_block, dict) and "ending_pf_mln" in summary_block:
        summary_block["ending_pf_mln"] = ending_total / 1_000_000
    carry_block = {
        "applied": True,
        "project_llcr": round(consolidated_llcr, 4),
        "min_llcr": _PHASE_DEBT_CARRY_MIN_LLCR,
        "transfers": applied,
        # Дата и сумма в самой фразе: «принят следующей очередью» без месяца
        # не отличает переезд в раскрытие эскроу от переезда на два года
        # раньше, а разница между ними — сотни миллионов процентов.
        "note": (
            "Долг, не погашенный раскрытым эскроу, принят ПФ следующей очереди "
            "по генеральному соглашению: "
            + "; ".join(
                f"О{item['from']} → О{item['to']} "
                f"{item['amount_mln']:,.0f} млн ₽ в {item['at'][:7]}".replace(",", " ")
                for item in applied)
            + ". Переезд — в месяц раскрытия эскроу передавшей очереди: её линия "
              "закрыта, и остаточные продажи остаются застройщику. Лимита долг не "
              "выбирает, но проценты несёт и стоит в знаменателе LLCR принявшей. "
            f"Общий LLCR проекта {consolidated_llcr:.2f}x — перенос допустим."),
    }
    current["debt_carry"] = carry_block
    # PDF собирается из свода, а не из связки: без этой строки отчёт печатал бы
    # обнулённый долг первой очереди и повышенный долг второй, ничего не сказав
    # о переносе, — то самое «снижение без объяснения».
    if isinstance(current.get("consolidated"), dict):
        current["consolidated"]["debt_carry"] = copy.deepcopy(carry_block)
    return current


@app.post("/calculate-phased")
def calculate_phased_api(req: PhasedCalcRequest) -> dict[str, Any]:
    # Очерёдность — тот же расчёт экономики, и та же граница входа.
    _require_web_access(req.session, req.access_key, "Расчёт экономики")
    return calculate_phased(req)


@app.post("/analysis/sensitivity")
def sensitivity_api(req: SensitivityRequest) -> dict[str, Any]:
    return run_sensitivity(
        req.inputs, req.tep, req.rates, req.phasing,
        metric=req.metric, scope=req.scope, selected_view=req.selected_view,
        parameters=list(req.parameters), change_pct=req.change_pct,
        duration_change_months=req.duration_change_months,
    )


@app.get("/analysis/sensitivity/options")
def sensitivity_options() -> dict[str, Any]:
    """Показатели и параметры для формы: справочник один, дублировать его нельзя."""
    meta = _field_meta()
    return {
        "metrics": [
            {"key": key, "label": info["label"], "unit": info["unit"], "better": info["better"]}
            for key, info in _SENSITIVITY_METRICS.items()
        ],
        "parameters": [
            {
                "key": spec["key"],
                "label": _sensitivity_label(spec, meta)[0],
                "unit": _sensitivity_label(spec, meta)[1],
                "group": spec["group"],
                "kind": spec["kind"],
            }
            for spec in _SENSITIVITY_PARAMETERS
        ],
    }


# Агент Платон Сергеевич — инструменты, цикл агента, маршрут к модели,
# ход и кэш ответов — вынесен в engine/agent.py и выполняется здесь же,
# в пространстве имён движка: порядок объявлений и подмены core.<имя>
# остаются прежними.
_engine_part("agent")


# --- Кто пользуется и о чём спрашивает --------------------------------------
# Пользователей считали по ощущениям, а вопросы читали через плечо. Ни того, ни
# другого не хватает, чтобы решать, что делать дальше: непонятно, растёт ли
# аудитория, и непонятно, о чём её спрашивают чаще всего.
#
# Журнал — построчный файл на день. Строка пишется одним `write` в режиме
# добавления: воркеров два, и перезаписывать общий файл им нельзя. Хранится
# полгода, чистится при записи. Выключается переменной, потому что журнал
# пользовательских текстов — это данные людей, и решение хранить их принимает
# владелец, а не код.

_USAGE_DIR = Path(_env_str("DEVELOPAID_USAGE_DIR", "").strip()
                  or (Path(__file__).resolve().parent / "data" / "usage"))
_USAGE_KEEP_DAYS = max(1, int(_env_float("DEVELOPAID_USAGE_KEEP_DAYS", 180.0)))
_USAGE_TEXT_LIMIT = 500
_USAGE_LOCK = threading.Lock()
_USAGE_SWEPT: dict[str, str] = {}


def _usage_enabled() -> bool:
    return _env_str("DEVELOPAID_USAGE_JOURNAL", "on").strip().lower() not in {
        "off", "0", "no", "false", "выкл"}


def _usage_day(at: float) -> str:
    return datetime.fromtimestamp(at, tz=timezone.utc).strftime("%Y-%m-%d")


def _usage_path(day: str) -> Path:
    return _USAGE_DIR / f"events-{day}.jsonl"


def _usage_sweep(today: str) -> None:
    """Старое удаляется раз в день, а не на каждой записи."""
    if _USAGE_SWEPT.get("day") == today:
        return
    _USAGE_SWEPT["day"] = today
    try:
        cutoff = (datetime.now(tz=timezone.utc)
                  - timedelta(days=_USAGE_KEEP_DAYS)).strftime("%Y-%m-%d")
        for path in _USAGE_DIR.glob("events-*.jsonl"):
            if path.stem[len("events-"):] < cutoff:
                path.unlink(missing_ok=True)
    except OSError:
        pass


def usage_track(kind: str, *, surface: str = "bot", chat_id: int = 0, user_id: int = 0,
                name: str = "", text: str = "", **extra: Any) -> None:
    """Одно событие в журнал. Молча — учёт не имеет права ронять ответ."""
    if not _usage_enabled():
        return
    at = time.time()
    record = {
        "at": round(at, 3),
        "surface": surface,
        "kind": kind,
        "chat": int(chat_id or 0),
        "user": int(user_id or 0),
        "name": str(name or "")[:80],
        "text": str(text or "").strip()[:_USAGE_TEXT_LIMIT],
    }
    record.update({key: value for key, value in extra.items() if value not in (None, "")})
    day = _usage_day(at)
    try:
        with _USAGE_LOCK:
            _USAGE_DIR.mkdir(parents=True, exist_ok=True)
            _usage_sweep(day)
            with _usage_path(day).open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    except (OSError, TypeError, ValueError):
        pass
    # Человек и его анкета живут дольше журнала: журнал подметается через
    # полгода и умирает вместе с контейнером Render, а на вопросы «сколько у
    # нас пользователей» и «что нам написали» отвечать надо всегда.
    users_touch(record["chat"], surface=record["surface"], kind=kind,
                name=record["name"])
    if kind == "survey":
        survey_store(record)


def usage_events(days: int = 30) -> list[dict[str, Any]]:
    """События за последние N суток, по возрастанию времени."""
    events: list[dict[str, Any]] = []
    now = datetime.now(tz=timezone.utc)
    for back in range(max(1, int(days))):
        path = _usage_path((now - timedelta(days=back)).strftime("%Y-%m-%d"))
        if not path.is_file():
            continue
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except ValueError:
                    continue  # оборванная строка не отменяет остальной день
                if isinstance(record, dict):
                    events.append(record)
        except OSError:
            continue
    events.sort(key=lambda item: float(item.get("at") or 0))
    return events


def usage_summary(days: int = 30) -> dict[str, Any]:
    """Свод: сколько людей, сколько новых, что нажимают, о чём спрашивают.

    Читается весь журнал, а не окно свода: «новый» — это тот, кого раньше не
    было вообще, а не тот, кого не было последний месяц. По окну в тридцать дней
    вернувшийся через полгода человек считался новым. Команда ручная, файлов за
    полгода меньше двух сотен — цена чтения того стоит.
    """
    events = usage_events(max(days, _USAGE_KEEP_DAYS))
    now = time.time()

    def users_since(seconds: float) -> set[int]:
        return {int(e.get("user") or 0) for e in events
                if e.get("surface") == "bot" and float(e.get("at") or 0) >= now - seconds
                and int(e.get("user") or 0)}

    window = [e for e in events if float(e.get("at") or 0) >= now - days * 86400]
    seen_before: dict[int, float] = {}
    for event in events:
        user = int(event.get("user") or 0)
        if user and user not in seen_before:
            seen_before[user] = float(event.get("at") or 0)

    commands: dict[str, int] = {}
    buttons: dict[str, int] = {}
    questions: list[dict[str, Any]] = []
    for event in window:
        kind = str(event.get("kind") or "")
        text = str(event.get("text") or "")
        if kind == "command":
            key = text.split(maxsplit=1)[0].split("@", 1)[0].lower()
            commands[key] = commands.get(key, 0) + 1
        elif kind == "button":
            buttons[text] = buttons.get(text, 0) + 1
        elif kind == "question":
            questions.append(event)

    return {
        "days": int(days),
        "users_today": len(users_since(86400)),
        "users_7d": len(users_since(7 * 86400)),
        "users_30d": len(users_since(30 * 86400)),
        "users_window": len({int(e.get("user") or 0) for e in window
                             if e.get("surface") == "bot" and int(e.get("user") or 0)}),
        "new_users_window": len([user for user, first in seen_before.items()
                                 if first >= now - days * 86400]),
        "events_window": len(window),
        "questions_bot": len([q for q in questions if q.get("surface") == "bot"]),
        "questions_site": len([q for q in questions if q.get("surface") == "site"]),
        "top_commands": sorted(commands.items(), key=lambda kv: -kv[1])[:8],
        "top_buttons": sorted(buttons.items(), key=lambda kv: -kv[1])[:8],
        "last_questions": questions[-15:],
        "enabled": _usage_enabled(),
        "keep_days": _USAGE_KEEP_DAYS,
        "dir": str(_USAGE_DIR),
    }


def survey_summary(days: int = 30) -> dict[str, Any]:
    """Свод теста: откуда пришли, докуда дошли, как оценили, что написали.

    Воронка считается по людям, а не по событиям: один человек, посчитавший
    десять проектов, — это один дошедший, а не десять. Средние оценки —
    по подпунктам и по разделам, и рядом всегда число ответов: среднее по
    двум ответам выглядит так же солидно, как по двадцати, и вводит в
    заблуждение сильнее всего.

    Свободные тексты не сворачиваются ни во что: их читают целиком. Ради них
    анкета и затевалась.
    """
    events = usage_events(max(days, _USAGE_KEEP_DAYS))
    now = time.time()
    window = [e for e in events if float(e.get("at") or 0) >= now - days * 86400]

    # Метка источника приезжает один раз, при нажатии Start. Дальше события
    # приходят без неё, поэтому источник восстанавливается по chat_id.
    source_by_chat: dict[int, str] = {}
    for event in events:
        if str(event.get("kind")) == "invite":
            chat = int(event.get("chat") or 0)
            if chat:
                source_by_chat[chat] = str(event.get("source") or "")

    def people(kind: str) -> set[int]:
        return {int(e.get("chat") or 0) for e in window
                if str(e.get("kind")) == kind and int(e.get("chat") or 0)}

    invited = people("invite")
    funnel = {
        "перешли по ссылке": len(invited),
        "искали участок": len(people("land")),
        "посчитали": len(people("calc")),
        "выгрузили PDF": len(people("pdf")),
        "ответили на анкету": len(people("survey")),
    }
    by_source: dict[str, int] = {}
    for chat in invited:
        key = source_by_chat.get(chat) or "без метки"
        by_source[key] = by_source.get(key, 0) + 1

    # Анкеты берутся из хранилища, а не только из журнала: журнал подметается,
    # а анкета должна лежать вечно. Журнальные оставлены для тех, что записаны
    # до появления хранилища; дубли снимаются по времени и чату.
    surveys = [e for e in window if str(e.get("kind")) == "survey"]
    seen_surveys = {(round(float(e.get("at") or 0), 3), int(e.get("chat") or 0))
                    for e in surveys}
    for stored in survey_records():
        at = float(stored.get("at") or 0)
        if at < now - days * 86400:
            continue
        if (round(at, 3), int(stored.get("chat") or 0)) in seen_surveys:
            continue
        surveys.append(stored)
    surveys.sort(key=lambda item: float(item.get("at") or 0))
    scores: dict[str, list[int]] = {}
    for survey in surveys:
        for key, value in (survey.get("ratings") or {}).items():
            if key in FEEDBACK_ITEMS:
                scores.setdefault(key, []).append(int(value))

    def average(values: list[int]) -> float:
        return round(sum(values) / len(values), 2) if values else 0.0

    items = [{"key": key, "label": FEEDBACK_ITEMS[key],
              "avg": average(values), "count": len(values)}
             for key, values in scores.items()]
    items.sort(key=lambda row: (row["avg"], -row["count"]))

    groups = []
    for group_key, title, members in FEEDBACK_GROUPS:
        collected = [score for item in members for score in scores.get(item[0], [])]
        groups.append({"key": group_key, "label": title,
                       "avg": average(collected), "count": len(collected)})

    # Кто ответил. Анкета не анонимная — она привязана к chat_id, — но по одному
    # номеру ничего не понять, и владелец видел «— : не верю числам» без всякого
    # автора. Имя берётся тремя источниками по убыванию надёжности: знакомство
    # (имя и компания, их человек написал сам), имя из Telegram в журнале,
    # номер чата. Профиль лежит на ядре, поэтому на Render остаются два
    # последних — там и живут ответы из бота.
    def who(chat: int) -> str:
        chat = int(chat or 0)
        if not chat:
            return "аноним"
        profile = {}
        try:
            profile = profile_read(chat) or {}
        except Exception:
            profile = {}
        name = str(profile.get("name") or "").strip() or name_by_chat.get(chat, "")
        company = str(profile.get("company") or "").strip()
        if name and company:
            return f"{name} ({company})"
        return name or f"chat {chat}"

    name_by_chat: dict[int, str] = {}
    for event in events:
        chat = int(event.get("chat") or 0)
        name = str(event.get("name") or "").strip()
        if chat and name:
            name_by_chat[chat] = name

    notes: list[dict[str, Any]] = []
    for survey in surveys:
        for group_key, text in (survey.get("problems") or {}).items():
            title = next((g[1] for g in FEEDBACK_GROUPS if g[0] == group_key), group_key)
            notes.append({"at": survey.get("at"), "chat": survey.get("chat"),
                          "who": who(survey.get("chat")),
                          "role": survey.get("role", ""), "group": title, "text": text})
        # Свободные поля — тоже комментарий, и раньше они не доходили никуда:
        # свод читал только привязанные к разделу. В боте комментарий один и
        # приходит именно так, то есть пропала бы вся его половина.
        for field, title in (("impression", "Общее впечатление"),
                             ("mistakes", "Что пошло не так")):
            text = str(survey.get(field) or "").strip()
            if text:
                notes.append({"at": survey.get("at"), "chat": survey.get("chat"),
                              "who": who(survey.get("chat")),
                              "role": survey.get("role", ""), "group": title,
                              "text": text})

    # Ответы поимённо. Средние показывают состояние сервиса, а этот список —
    # разговор с конкретным человеком: что он поставил и что написал. Анкета
    # приходит двумя записями (оценки и комментарий), поэтому они складываются
    # по chat_id, а не показываются двумя строками.
    people: dict[int, dict[str, Any]] = {}
    for survey in sorted(surveys, key=lambda s: float(s.get("at") or 0)):
        chat = int(survey.get("chat") or 0)
        person = people.setdefault(chat, {
            "chat": chat, "who": who(chat), "at": survey.get("at"),
            "surface": survey.get("surface", ""), "role": survey.get("role", ""),
            "scores": {}, "texts": [],
        })
        person["at"] = survey.get("at") or person["at"]
        if survey.get("role"):
            person["role"] = survey.get("role")
        for key, value in (survey.get("ratings") or {}).items():
            if key in FEEDBACK_ITEMS:
                person["scores"][key] = int(value)
        for text in list((survey.get("problems") or {}).values()) + [
                survey.get("impression"), survey.get("mistakes")]:
            text = str(text or "").strip()
            if text:
                person["texts"].append(text)
    respondents = []
    for person in people.values():
        scores = list(person["scores"].values())
        respondents.append({
            "chat": person["chat"], "who": person["who"], "at": person["at"],
            "surface": person["surface"], "role": person["role"],
            "rated": len(scores), "avg": average(scores),
            "texts": person["texts"],
            "lowest": sorted(
                ({"label": FEEDBACK_ITEMS[key], "score": score}
                 for key, score in person["scores"].items()),
                key=lambda row: row["score"])[:3],
        })
    respondents.sort(key=lambda row: float(row["at"] or 0), reverse=True)

    return {
        "days": int(days),
        "funnel": funnel,
        "by_source": sorted(by_source.items(), key=lambda kv: -kv[1]),
        "answers": len(surveys),
        "roles": sorted({str(s.get("role") or "—") for s in surveys}),
        # Слабейшие подпункты идут первыми: свод читают, чтобы понять, что чинить.
        "weakest": items[:8],
        "strongest": list(reversed(items[-5:])),
        "groups": groups,
        "notes": notes,
        "respondents": respondents,
    }


def usage_csv(days: int = 30, events: list[dict[str, Any]] | None = None) -> bytes:
    """Выгрузка для разбора вопросов не глазами.

    Точка с запятой и BOM — чтобы Excel открыл кириллицу и не склеил колонки.

    События можно передать снаружи: журнал пишется там, где обслужен запрос,
    и выгрузка бота без событий ядра — половина картины. Пустая таблица при
    этом читается как «людей не было», хотя это «диск Render пережил выкатку
    и не пережил».
    """
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=";")
    writer.writerow(["время (UTC)", "поверхность", "событие", "chat_id", "user_id",
                     "кто", "текст"])
    rows = usage_events(days) if events is None else sorted(
        events, key=lambda event: float(event.get("at") or 0))
    for event in rows:
        writer.writerow([
            datetime.fromtimestamp(float(event.get("at") or 0),
                                   tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
            event.get("surface", ""), event.get("kind", ""),
            event.get("chat", ""), event.get("user", ""),
            event.get("name", ""), str(event.get("text") or "").replace("\n", " "),
        ])
    return ("﻿" + buffer.getvalue()).encode("utf-8")


def profile_registry_summary(days: int = 30) -> dict[str, Any]:
    """Сколько людей заполнило знакомство и кто это.

    Знакомство — единственная запись, которая переживает выкатку: журнал
    обращений живёт на том хосте, который обслужил запрос, а на Render его диск
    кончается вместе с контейнером. Профили лежат на ядре файлами, поэтому
    «сколько зарегистрировалось» считается по ним, а не по журналу.

    Слова человека остаются словами человека: телеграм подтверждает аккаунт,
    имя и компанию подтвердить нечем — так и записано в самой анкете.
    """
    directory = _PROJECTS_DIR.parent / "profiles"
    people: list[dict[str, Any]] = []
    try:
        paths = sorted(directory.glob("*.json"))
    except OSError:
        paths = []
    for path in paths:
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(record, dict):
            continue
        people.append(record)

    def moment(record: dict[str, Any]) -> float:
        raw = str(record.get("created") or record.get("updated") or "")
        try:
            return datetime.fromisoformat(raw).timestamp()
        except ValueError:
            return 0.0

    people.sort(key=moment, reverse=True)
    edge = time.time() - max(1, int(days)) * 86400
    fresh = [record for record in people if moment(record) >= edge]

    sources: dict[str, int] = {}
    for record in people:
        key = str(record.get("source") or "").strip() or "не сказали"
        sources[key] = sources.get(key, 0) + 1

    return {
        "days": int(days),
        "total": len(people),
        "window": len(fresh),
        "complete": len([r for r in people if profile_complete(r)]),
        "by_source": sorted(sources.items(), key=lambda kv: -kv[1])[:8],
        "recent": [{
            "chat": int(record.get("chat_id") or 0),
            "name": str(record.get("name") or ""),
            "company": str(record.get("company") or ""),
            "role": str(record.get("role") or ""),
            "source": str(record.get("source") or ""),
            "contact": str(record.get("contact") or ""),
            "created": str(record.get("created") or ""),
        } for record in people[:15]],
        "dir": str(directory),
    }


# Пользователи бота — анкеты, хранилище проектов, передача, знакомство,
# рассылки и вход через бота — вынесены в engine/bot_users.py и
# выполняются здесь же, в пространстве имён движка: порядок объявлений
# и подмены core.<имя> остаются прежними.
_engine_part("bot_users")


# Локальные сценарии кнопок Платона и маршруты /agent/* вынесены
# в engine/agent_routes.py и выполняются здесь же, в пространстве имён
# движка: порядок объявлений и подмены core.<имя> остаются прежними.
_engine_part("agent_routes")


@app.get("/current-key-rate")
def current_key_rate() -> dict[str, Any]:
    return fetch_current_cbr_key_rate()


@app.post("/calculate")
def calculate_api(req: CalcRequest) -> dict:
    # Экономика — за входом через бота: участок, ТЭП и ограничения открыты и
    # показывают, что мы умеем, а вывод о деньгах уже принадлежит конкретному
    # человеку (решение владельца, 18.08.2026). Без токена бота гейт честно
    # выключен — проверять подпись нечем.
    _require_web_access(req.session, req.access_key, "Расчёт экономики")
    # Учёт шагов с сайта: без него от публикации на пятьсот человек остаётся
    # число заходов, а где люди останавливаются — неизвестно. Пишем на сервере,
    # а не на странице: браузер закрывают на полуслове, и событие теряется.
    usage_track("calc", surface="site",
                chat_id=_web_identity_chat_id(str(getattr(req, "session", "") or "")))
    return calculate(req)


# Страница приложения PAGE — разметка, стили и скрипт — вынесена
# в engine/page.py и выполняется здесь же, в пространстве имён движка:
# порядок объявлений и подмены core.<имя> остаются прежними.
_engine_part("page")


# Сборка страницы — подстановка данных движка в плейсхолдеры PAGE,
# страница монитора и маршрут GET / — вынесена в engine/page_build.py
# и выполняется здесь же, в пространстве имён движка: порядок
# объявлений и подмены core.<имя> остаются прежними.
_engine_part("page_build")

# _DEVELOPAID_EDIT_MODE_FIX_V01217

# _DEVELOPAID_EDIT_ROUNDTRIP_V01218
