"""Вопрос Платону по продажам укладывается в предел, а имя файла читается.

На полностью загруженном проекте кнопка «Комментарий Платона по продажам»
отвечала «Вопрос слишком длинный»: предел у Платона 4000 знаков, свод считал
бюджет только для середины, а наши выводы и список непрочитанного стояли вне
счёта. Выводов стало одиннадцать — и вопрос перевалил предел ещё до первого
раздела.

Рядом вторая половина того же экрана: имя файла ехало заголовком, где проценты
заменялись подчёркиванием «чтобы не мешали», и раскодировать его было уже
нечем. «Продажи Кутузов Сити.xlsx» показывалось как «_D0_9F_D1_80_D0_BE…» —
двести знаков нечитаемой строки на экране и в вопросе.

Запуск: python3 -m pytest tests/test_the_question_fits_the_limit.py -q
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CABINET = ROOT / "market_search" / "cabinet.py"
PAGE = CABINET.read_text(encoding="utf-8")

LIMIT = 4000


def _fat_summary() -> dict:
    """Свод, который заведомо не влезает: всё заполнено и всего много."""
    months = [f"2025-{m:02d}" for m in range(1, 13)] + [f"2026-{m:02d}" for m in range(1, 9)]
    return {
        "project": "Кутузов Сити (жилой комплекс на Можайском валу)",
        "total": {"contracts": 76, "area": 4321.5, "amount": 2_345_300_000,
                  "price_per_sqm": 542_700, "escrow": 1_988_000_000, "escrow_share": 0.848},
        "conclusions": {
            key: (
                "Длинная фраза вывода, которую считает сервер рядом с числами: "
                f"раздел «{key}» отвечает на свой вопрос и приводит доли и суммы."
            )
            for key in ("pool", "dynamics", "bands", "products", "payment",
                        "channels", "fm", "bank", "escrow", "demand", "funnel")
        },
        "pool": {
            "total": {"amount_share": 0.179, "sold_amount": 2_345_300_000,
                      "pool_amount": 13_100_000_000},
            "products": [{"product": p, "sold_units": 56, "pool_units": 220,
                          "units_share": 0.255, "area_share": 0.241}
                         for p in ("Квартира", "Машиноместо", "Кладовая", "ПСН")],
            "bands": [{"band": b, "pool_units": 51, "pool_share": 0.232,
                       "sold_units": 26, "sold_share": 0.464,
                       "left_units": 25, "left_share": 0.152}
                      for b in ("28,3–40", "40–55", "55–85", "85–120", "120–168,6")],
        },
        "demand": {"funnel": {
            "quality": {"calls": 518, "target": 449, "booked_target": 0.031, "blank": 231},
            "by_source": [{"name": f"Источник {i}", "deals": 40, "booked": 4, "share": 0.1}
                          for i in range(6)],
            "by_manager": [{"name": f"Менеджер {i}", "deals": 60, "booked": 3, "share": 0.05}
                           for i in range(6)],
        }},
        "by_channel": [{"channel": f"Брокер номер {i}", "own": False, "contracts": 12,
                        "amount": 300_000_000, "broker_fee": 12_000_000,
                        "sales_bonus": 1_540_000, "cost_of_sales": 0.0343,
                        "fee_of_escrow": 0.0412, "fee_unknown": False}
                       for i in range(6)],
        "by_payment": [{"variant": f"Условие оплаты {i}", "count": 12,
                        "amount": 300_000_000, "escrow": 250_000_000, "filled": 0.83}
                       for i in range(5)],
        "dynamics": [{"month": m, "units": 4, "area": 220.4, "amount": 120_000_000,
                      "price_per_sqm": 544_000} for m in months],
        "by_quarter": [{"quarter": f"2026 Q{i}", "amount": 400_000_000} for i in (1, 2)],
        "by_size": [{"band": b, "contracts": 12, "area": 500.5, "amount": 300_000_000}
                    for b in ("28,3–40", "40–55", "55–85", "85–120", "120–168,6")],
        "by_product": [{"product": p, "contracts": 20, "amount": 500_000_000}
                       for p in ("Квартира", "Машиноместо", "Кладовая", "ПСН")],
        "terminated": [{"escrow_returned": 5_000_000}, {"escrow_returned": 3_000_000}],
        "missing": [
            "источник «сделки CRM» не загружен",
            "пул «Машиноместо»: план финмодели 75 лотов, книга 73 — доли посчитаны по плану",
            "план банка — 2026-08-26 (Продажи Кутузов Сити на 26 августа 2026 года.xlsx)",
        ],
    }


def _question(summary: dict) -> str:
    """Собираем вопрос настоящим кодом страницы, а не его пересказом."""
    digest = PAGE[PAGE.index("function salesDigest("):PAGE.index("async function askPlatoSales(")]
    ask = PAGE[PAGE.index("async function askPlatoSales("):]
    ask = ask[:ask.index("\n}\n")]
    preamble = ask[ask.index("const preamble='") + len("const preamble="):]
    preamble = preamble[:preamble.index(";\n")]
    tail = ask[ask.index("const tail='") + len("const tail="):]
    tail = tail[:tail.index(";\n")]
    limit_line = PAGE[PAGE.index("const SALES_ASK_LIMIT="):]
    limit_line = limit_line[:limit_line.index(";") + 1]

    script = (
        "const num=(v,d=0)=>v===null||v===undefined?'—':"
        "Number(v).toLocaleString('ru-RU',"
        "{minimumFractionDigits:d,maximumFractionDigits:d});\n"
        + limit_line + "\n" + digest + "\n"
        + "const salesData=" + json.dumps(summary, ensure_ascii=False) + ";\n"
        + "const tail=" + tail + ";\n"
        + "const preamble=" + preamble + ";\n"
        + "const message=preamble"
          "+salesDigest(salesData, SALES_ASK_LIMIT-preamble.length-tail.length-20)"
          "+tail;\n"
        + "process.stdout.write(message);\n"
    )
    done = subprocess.run(["node", "-e", script], capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    return done.stdout


def test_the_question_fits_even_when_everything_is_loaded():
    """Полный проект — самый частый случай, а не крайний."""
    message = _question(_fat_summary())
    assert len(message) <= LIMIT, f"вопрос {len(message)} знаков при пределе {LIMIT}"


def test_what_did_not_fit_is_named():
    """Молча выброшенный раздел читается как отсутствие данных."""
    message = _question(_fat_summary())
    assert "НЕ ПОМЕСТИЛОСЬ В ВОПРОС" in message
    assert "не считай это отсутствием данных" in message


def test_the_head_is_only_the_project_and_the_totals():
    """Выводы и «не прочитано» стояли вне бюджета — с них и переполнялось."""
    message = _question(_fat_summary())
    assert message.count("ПРОЕКТ:") == 1
    body = PAGE[PAGE.index("function salesDigest("):PAGE.index("async function askPlatoSales(")]
    head = body[body.index("const head=["):body.index("const add=")]
    assert "ВЫВОД" not in head, "вывод — раздел с бюджетом, а не обязательная шапка"
    assert "НЕ ПРОЧИТАНО" not in head


def test_the_conclusions_are_the_first_section():
    """Они отвечают ровно на то, о чём мы спрашиваем."""
    message = _question(_fat_summary())
    assert "ВЫВОД:" in message, "выводы обязаны влезать первыми"
    assert message.index("ВЫВОД:") < message.index("ПУЛ:")


def test_a_small_project_keeps_everything():
    """Обрезка — не поведение по умолчанию."""
    message = _question({
        "project": "Малый проект",
        "total": {"contracts": 3, "area": 120, "amount": 40_000_000,
                  "price_per_sqm": 333_000, "escrow": 30_000_000, "escrow_share": 0.75},
        "conclusions": {"pool": "Продано три лота."},
        "dynamics": [{"month": "2026-08", "units": 3, "area": 120, "amount": 40_000_000}],
    })
    assert "НЕ ПОМЕСТИЛОСЬ В ВОПРОС" not in message
    assert len(message) <= LIMIT


def test_the_file_name_is_sent_decodable():
    """Заголовок обязан быть ASCII, но проценты в нём законны — а подчёркивание
    раскодировать нечем."""
    call = PAGE[PAGE.index("async function loadContracting("):]
    call = call[:call.index("\n}\n")]
    assert "encodeURIComponent(file.name)" in call
    assert "replace(/%/g" not in call, "проценты заменяли подчёркиванием — имя становилось нечитаемым"


def test_the_server_decodes_the_file_name():
    from urllib.parse import quote

    from market_search import api

    name = "Продажи Кутузов Сити на 26 августа.xlsx"
    assert api._uploaded_file_name(quote(name)) == name


def test_a_name_that_is_not_encoded_survives_as_it_came():
    """Битую кодировку не угадываем — иначе имя чинится в мусор молча."""
    from market_search import api

    assert api._uploaded_file_name("Продажи.xlsx") == "Продажи.xlsx"
    assert api._uploaded_file_name(None) == ""
    long = "и" * 300
    assert len(api._uploaded_file_name(long)) == 120

def test_every_theme_of_the_question_reaches_the_answer():
    """Вопрос спрашивает про рассрочку, вознаграждение, свой отдел и структуру.
    Пока разделы входили целиком или никак, «каналы» из шести строк выпадали, а
    стоящая ниже «размерность» из пяти влезала — две темы из четырёх пропадали.
    """
    message = _question(_fat_summary())
    assert "ОПЛАТА " in message, "рассрочка — первая тема вопроса"
    assert "КАНАЛ " in message, "вознаграждение и свой отдел — вторая и третья"
    assert "(вошло " in message, "часть раздела входит с числом вошедших строк"


def test_the_unread_sources_are_never_the_first_to_go():
    """Отсутствие источника, выброшенное молча, читается как ноль."""
    message = _question(_fat_summary())
    assert "НЕ ПРОЧИТАНО:" in message
    assert message.index("НЕ ПРОЧИТАНО:") < message.index("ОПЛАТА ")


def test_the_order_is_declared_not_inherited_from_the_maths():
    """Порядок разделов задаётся при сборке, а не порядком вычислений."""
    body = PAGE[PAGE.index("function salesDigest("):PAGE.index("async function askPlatoSales(")]
    assert "const ORDER=[" in body
    order = body[body.index("const ORDER=["):body.index("groups.sort(")]
    for name in ("выводы", "не прочитано", "оплата", "каналы"):
        assert f"'{name}'" in order, name
