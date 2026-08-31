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


def _function(name: str) -> str:
    """Исходник функции страницы — по её объявлению, а не по соседней строке.

    Прежде кусок вырезался «от `function salesDigest(` до комментария
    „// Сказанное Платоном“». Комментарий — не контракт: его переписали
    вместе с соседним блоком, и десять проверок разом упали с
    `ValueError: substring not found`, ни слова не сказав о том, что
    сломалось на самом деле (ничего). Функция — контракт: она либо есть, либо
    её нет, и второе — настоящая поломка. Границу считаем скобками.
    """
    start = PAGE.index(f"function {name}(")
    depth, index = 0, PAGE.index("{", start)
    while index < len(PAGE):
        if PAGE[index] == "{":
            depth += 1
        elif PAGE[index] == "}":
            depth -= 1
            if depth == 0:
                return PAGE[start:index + 1]
        index += 1
    raise AssertionError(f"функция {name} на странице не закрыта")


def _question(summary: dict, ask: str | None = None) -> str:
    """Собираем вопрос настоящим кодом страницы, а не его пересказом."""
    digest = _function("salesDigest")
    asks = PAGE[PAGE.index("const SALES_ASKS=["):]
    asks = asks[:asks.index("\n];") + 3]
    body = PAGE[PAGE.index("async function askPlatoSales(){"):]
    body = body[:body.index("\n}\n")]
    tail = body[body.index("const tail='") + len("const tail="):]
    tail = tail[:tail.index(";\n")]
    preamble = body[body.index("const preamble='") + len("const preamble="):]
    preamble = preamble[:preamble.index(";\n")]
    limit_line = PAGE[PAGE.index("const SALES_ASK_LIMIT="):]
    limit_line = limit_line[:limit_line.index(";") + 1]

    # Укладка объявлена один раз (`plato_question`) и подставляется на
    # страницы плейсхолдером — берём её оттуда, а не выкусываем со страницы
    # куском по соседству со сводом.
    import plato_question

    script = (
        "const num=(v,d=0)=>v===null||v===undefined?'—':"
        "Number(v).toLocaleString('ru-RU',"
        "{minimumFractionDigits:d,maximumFractionDigits:d});\n"
        + plato_question.SCRIPT + "\n"
        + limit_line + "\n" + asks + "\n" + digest + "\n"
        + "const salesData=" + json.dumps(summary, ensure_ascii=False) + ";\n"
        + "const ask=" + json.dumps(ask, ensure_ascii=False) + "||SALES_ASKS[0].text;\n"
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
    body = _function("salesDigest")
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
    body = _function("salesDigest")
    assert "const ORDER=[" in body
    order = body[body.index("const ORDER=["):body.index("groups.sort(")]
    for name in ("выводы", "не прочитано", "оплата", "каналы"):
        assert f"'{name}'" in order, name


def test_a_long_question_of_your_own_still_fits():
    """Вопрос пишет человек, и длина его заранее не известна. Бюджет свода
    считается от настоящей длины вопроса, а не назначается на глазок."""
    message = _question(_fat_summary(), "Почему " + "очень " * 120 + "медленно?")
    assert len(message) <= LIMIT


def test_the_dialogue_has_preset_questions_and_one_of_them_stands_in_the_field():
    """Кнопка задавала один вопрос и на этом кончалась: не понравился ответ —
    переспросить негде."""
    assert "const SALES_ASKS=[" in PAGE
    body = PAGE[PAGE.index("const SALES_ASKS=["):]
    body = body[:body.index("\n];")]
    assert body.count("chip:") >= 4, "подсказок меньше четырёх — это не диалог"

    card = PAGE[PAGE.index("Спросить Платона Сергеевича о продажах"):]
    card = card[:card.index("box.innerHTML=html")]
    assert "id=\"salesq\"" in card, "поле для своего вопроса"
    assert "SALES_ASKS[0].text" in card, "разбор стоит в поле сразу"
    assert "saleschips" in card, "подсказки нажимаются"


def test_the_answers_do_not_erase_each_other():
    """Ответы копятся, новый стоит сверху — и это проверяется отрисовкой.

    Прежде проверялись имена из реализации (`salesSaid`, `insertBefore`).
    Порядок реплик от них не зависит: стопку ответов заменил разговор, имена
    сменились, поведение осталось — и проверка упала, ничего про поведение не
    сказав. Теперь гоняется сама отрисовка: новая реплика обязана стоять выше
    прежней, потому что на телефоне дописанный снизу ответ оказывается за
    краем экрана.
    """
    import plato_question

    body = PAGE[PAGE.index("async function askPlatoSales(){"):]
    body = body[:body.index("\n}\n")]
    assert ".said(" in body, "сказанное никуда не записывается"
    assert "renderTalk(" in body, "разговор не рисуется"

    script = (
        plato_question.SCRIPT + "\n"
        + "const esc=s=>String(s);\n"
        + _function("renderTalk") + "\n"
        + "const box={innerHTML:''};\n"
          "const talk=platoThread();\n"
          "talk.said('первый вопрос','первый ответ');\n"
          "talk.said('второй вопрос','второй ответ');\n"
          "renderTalk(box, talk, '');\n"
          "process.stdout.write(box.innerHTML);\n"
    )
    done = subprocess.run(["node", "-e", script], capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    shown = done.stdout
    assert "первый ответ" in shown, "прежний ответ затёрт новым"
    assert shown.index("второй ответ") < shown.index("первый ответ"), (
        "новый ответ встал под старым — на телефоне его не видно")


def test_the_sources_line_carries_no_file_names():
    """Вид источника и дата отвечают на «то ли это, что я грузил». Имя файла
    занимало по три строки на источник."""
    line = PAGE[PAGE.index("Источники: "):]
    line = line[:line.index("</div>")]
    assert "s.file" not in line, "имя файла со строки источников убрано"
    assert "s.at" in line and "s.name" in line


def test_the_report_is_open_on_its_own_page():
    """Свод продаж занимает свою страницу целиком, и складки у него нет.

    Свёрнут он был 27.08.2026, когда жил на общей странице кабинета рядом с
    отчётом о рынке. С 30.08.2026 кабинет разнесён на три страницы, причина
    исчезла, а складка осталась: на `/cabinet/sales` человек видел плитки и одну
    серую строку «▸ Отчёт о продажах ПЛАТО» — «там нет ничего на вкладке»
    (владелец, 31.08.2026). Складки внутри разделов при этом остаются: они
    прячут числа под уже показанной картинкой, а не отчёт под его именем.
    """
    body = PAGE[PAGE.index("function renderSales(d){"):]
    body = body[:body.index("\nfunction tile(")]
    assert '<details class="salesreport" id="sales">' not in body, \
        "отчёт снова свёрнут — страница показывает одну строку вместо свода"
    assert '<div class="card" id="salesreport">' in body
    assert "Продажи проекта" in body, "у отчёта пропало имя вместе со складкой"
    # Разделы никуда не делись — свёрнут был показ, а не разбор.
    assert "salesSection('sb-dyn'" in body and "salesSection('sb-plan'" in body


def test_only_one_upload_button_is_left():
    """Две загрузки рядом означали два файла разных дат, поданных как один
    проект, — ровно то, ради чего заведён общий склад источников."""
    assert PAGE.count("class=\"upload\"") == 1
    assert "Загрузить файл проекта" in PAGE
    assert "loadPlan(" not in PAGE, "своего маршрута загрузки у плана больше нет"
    assert "takePlan(" in PAGE, "план приезжает вместе со сводом"


def test_the_plan_is_read_by_one_parser_for_both_paths():
    """Два разбора одной книги однажды разойдутся, и обе картинки будут
    выглядеть верными."""
    api = (ROOT / "market_search" / "api.py").read_text(encoding="utf-8")
    assert "def _plan_payload(" in api
    assert api.count("parse_plan(data)") == 1, "разбор книги объявлен один раз"
    assert 'parts["plan"] = _plan_payload(data)' in api
    from market_search import sales_store
    assert "plan" in sales_store.KINDS


def test_the_wait_shows_the_stage_and_the_timeout_names_it():
    """Ожидание без признака работы читается как внезапность: пять минут
    «Платон думает…», потом «ответ пустой» — а работа могла и не начинаться."""
    body = PAGE[PAGE.index("async function platoAnswer(message"):]
    body = body[:body.index("\n}\n")]
    assert "/agent/trace/" in body, "стадию сервер пишет — её надо показать"
    assert "не ответил за" in body
    assert "работа не начиналась" in body, "«нет стадии» и «стадия застряла» — разные ответы"
    # Комментарии из проверки исключены: в них прежний неверный диагноз назван
    # по имени, чтобы следующий читатель не завёл его обратно. Запрещаем место,
    # а не слово.
    code = "\n".join(line for line in body.split("\n") if not line.strip().startswith("//"))
    assert "Ответ пустой" not in code, "неверный диагноз: работа могла идти и не кончиться"
