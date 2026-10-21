
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
from terms_glossary import (CORE_ABOVE_AREA, CORE_TOTAL_AREA, CORE_UNDER_AREA, OBJECTS_TOTAL_AREA,
                            ROW_AREA_HEADER, ROW_AREA_HEADER_FULL, SALEABLE_AREA, area_total_label,
                            TERMS, TOTAL_AREA, capex_unit_base, page_terms, unit_label)
import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape as xml_escape

# Запуск Chromium — общий: его заводят и ГлавАПУ, и печать отчёта, и ломается
# он у обоих сразу, а наружу выходит по-разному.
import browser_launch
import glavapu_scenario
import site_position
# Регион проекта: Москва, область или другой — один предикат на все модули.
import project_regions
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
    profit_tax_payment_month as _profit_tax_payment_month,
    profit_tax_payments as _profit_tax_payments,
    profit_tax_schedule as _profit_tax_schedule,
    unused_tax_loss as _unused_tax_loss,
)
import developaid_monitor
import developaid_monitor_daily
import developaid_monitor_scenarios
from developaid_monitor_page import MONITOR_PAGE as _MONITOR_PAGE_RAW
from developaid_report_page import REPORT_PAGE as _REPORT_PAGE_RAW

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
VERSION = "0.26.78"
# Коммит, из которого собран образ. Версия отвечает на «что выпущено», коммит —
# на «что сейчас крутится»: одна версия живёт много правок, и по ней не отличить
# выкаченный образ от собранного часом раньше. Значение запекается сборкой
# (ARG APP_COMMIT), запуску его задавать неоткуда — вне контейнера пусто.
COMMIT = (os.getenv("APP_COMMIT") or "").strip()[:40]
USER_AGENT = f"DevelopAid-Development-Model/{VERSION}"

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


# Плейсхолдеры страницы и состав анкеты обратной связи вынесены в
# engine/page_placeholders.py
# и выполняются здесь же, в пространстве имён движка: порядок
# объявлений и подмены core.<имя> остаются прежними.
_engine_part("page_placeholders")


app = FastAPI(title="DevelopAid Development Investment Model", version=VERSION)

# Меню бота Telegram — команды меню, команды вне меню и якорь
# расширений — вынесено в engine/telegram_menu.py
# и выполняются здесь же, в пространстве имён движка: порядок
# объявлений и подмены core.<имя> остаются прежними.
_engine_part("telegram_menu")

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
# и маршрут /report/workbook — вынесена в engine/xlsx_book_v4*.py по листам
# и помощникам. Куски выполняются здесь же, подряд и в этом порядке, в
# пространстве имён движка: порядок объявлений и подмены core.<имя>
# остаются прежними.
_engine_part("xlsx_book_v4")
_engine_part("xlsx_book_v4_xml")
_engine_part("xlsx_book_v4_products")
_engine_part("xlsx_book_v4_capex")
_engine_part("xlsx_book_v4_debt_carry")
_engine_part("xlsx_book_v4_objects")
_engine_part("xlsx_book_v4_finance")
_engine_part("xlsx_book_v4_presentation")
_engine_part("xlsx_book_v4_sheets")
_engine_part("xlsx_book_v4_social")
_engine_part("xlsx_book_v4_registry")
_engine_part("xlsx_book_v4_build")


# Общие списки книги и движка (варианты полей, прогноз ставки, статьи без
# резерва) — engine/book_constants.py, на месте удалённой выгрузки в шаблон
# ПЛАТО: порядок объявлений и подмены core.<имя> остаются прежними.
_engine_part("book_constants")


# Маршрут /report/pdf и тизер — фоновая сборка, опрос по билету,
# build_teaser_pdf, участок и карта — вынесены в engine/report_teaser.py
# и выполняются здесь же, в пространстве имён движка: порядок объявлений
# и подмены core.<имя> остаются прежними.
_engine_part("report_teaser")


# Результат расчёта для Telegram — плитки, паритет, вложения — и серверные
# предустановки вынесены в engine/telegram_result.py
# и выполняются здесь же, в пространстве имён движка: порядок
# объявлений и подмены core.<имя> остаются прежними.
_engine_part("telegram_result")



# Даты, ставки и графики — кривая ставки, ключевая ставка ЦБ, графики
# продаж и оплат, соцпрограмма — вынесены в engine/schedules.py
# и выполняются здесь же, в пространстве имён движка: порядок
# объявлений и подмены core.<имя> остаются прежними.
_engine_part("schedules")


# Плата за изменение ВРИ — льготы, даты обязательства, рассрочка,
# build_vri_schedule — вынесена в engine/vri_payment.py
# и выполняются здесь же, в пространстве имён движка: порядок
# объявлений и подмены core.<имя> остаются прежними.
_engine_part("vri_payment")


# Операционная модель проекта (build_operating_model) вынесена в
# engine/operating_model.py
# и выполняются здесь же, в пространстве имён движка: порядок
# объявлений и подмены core.<имя> остаются прежними.
_engine_part("operating_model")


# Финансирование — ступенчатая ставка ПФ, объекты вне ДДУ, гостиница,
# simulate_financing — вынесено в engine/financing.py
# и выполняются здесь же, в пространстве имён движка: порядок
# объявлений и подмены core.<имя> остаются прежними.
_engine_part("financing")


# Отчёты по результату — раскладка, объекты, гостиница, метрики долга,
# участие капиталом — вынесены в engine/reports.py
# и выполняются здесь же, в пространстве имён движка: порядок
# объявлений и подмены core.<имя> остаются прежними.
_engine_part("reports")


# Экономика проекта — удельные показатели, calculate, _calculate_economics,
# детализация и БРИДЖ — вынесена в engine/economics.py
# и выполняются здесь же, в пространстве имён движка: порядок
# объявлений и подмены core.<имя> остаются прежними.
_engine_part("economics")


# Очереди — разбиение ТЭП, финансирование и налог по очередям, свод,
# сравнение и чувствительность — вынесены в engine/phases.py
# и выполняются здесь же, в пространстве имён движка: порядок
# объявлений и подмены core.<имя> остаются прежними.
_engine_part("phases")


# Агент Платон Сергеевич — инструменты, цикл агента, маршрут к модели,
# ход и кэш ответов — вынесен в engine/agent.py и выполняется здесь же,
# в пространстве имён движка: порядок объявлений и подмены core.<имя>
# остаются прежними.
_engine_part("agent")


# Учёт использования — журнал событий, свод, анкета, реестр профилей —
# вынесен в engine/usage.py
# и выполняются здесь же, в пространстве имён движка: порядок
# объявлений и подмены core.<имя> остаются прежними.
_engine_part("usage")


# Пользователи бота — анкеты, хранилище проектов, передача, знакомство,
# рассылки и вход через бота — вынесены в engine/bot_users.py и
# выполняются здесь же, в пространстве имён движка: порядок объявлений
# и подмены core.<имя> остаются прежними.
_engine_part("bot_users")


# Права на расчёт — бесплатный участок, оплаченные участки, подписка — и
# единое решение «можно ли считать этот участок» лежат в
# engine/access_rights.py и выполняются здесь же, в пространстве имён движка.
_engine_part("access_rights")


# Локальные сценарии кнопок Платона и маршруты /agent/* вынесены
# в engine/agent_routes.py и выполняются здесь же, в пространстве имён
# движка: порядок объявлений и подмены core.<имя> остаются прежними.
_engine_part("agent_routes")


# Маршруты /current-key-rate и /calculate вынесены в engine/calc_routes.py
# и выполняются здесь же, в пространстве имён движка: порядок
# объявлений и подмены core.<имя> остаются прежними.
_engine_part("calc_routes")


# Страница приложения PAGE — разметка, стили и скрипт — вынесена
# в engine/page_*.py по разделам и выполняется здесь же, в пространстве
# имён движка: первый кусок заводит PAGE, каждый следующий дописывает свой
# текст. Порядок строк ниже и есть порядок страницы — склейка байт в байт
# прежняя; другого списка кусков нет.
_engine_part("page_styles")
_engine_part("page_markup")
_engine_part("page_js_core")
_engine_part("page_js_plato")
_engine_part("page_js_phasing")
_engine_part("page_js_land")
_engine_part("page_js_mo_glavapu")
_engine_part("page_js_inputs")
_engine_part("page_js_tep")
_engine_part("page_js_calc")
_engine_part("page_js_results")
_engine_part("page_js_export_projects")
_engine_part("page_js_telegram")


# Сборка страницы — подстановка данных движка в плейсхолдеры PAGE,
# страница монитора и маршрут GET / — вынесена в engine/page_build.py
# и выполняется здесь же, в пространстве имён движка: порядок
# объявлений и подмены core.<имя> остаются прежними.
_engine_part("page_build")

# _DEVELOPAID_EDIT_MODE_FIX_V01217

# _DEVELOPAID_EDIT_ROUNDTRIP_V01218
