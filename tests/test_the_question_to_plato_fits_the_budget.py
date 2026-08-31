"""Вопрос Платону укладывается в бюджет — и счёт объявлен один раз.

Предел у Платона 4000 знаков (`main_legacy.py`), и превышение — это отказ
«вопрос слишком длинный» ровно там, где данных больше всего. Свод продаж это
уже проходил. В торгах повторилось своим путём: списки резались по двенадцать
строк, а общего счёта не было вовсе — и один выбранный лот, у которого в
названии весь перечень ЗОУИТ, выносил вопрос за предел (экран владельца,
30.08.2026).
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import plato_question  # noqa: E402

LONG_TITLE = (
    "Земельный участок общей площадью 173 494 кв. м, адрес: г. Москва, вн.тер.г. "
    "муниципальный округ Коммунарка, квартал 101, земельный участок 2, кадастровый "
    "номер 50:21:0120316:1221, земли населенных пунктов — многофункциональные "
    "общественные центры, ограничения и обременения: ограничения прав на земельный "
    "участок, предусмотренные ст. 56 Земельного Кодекса РФ, ЗОУИТ 77:06.2.2 Охранная "
    "зона ЛЭП 110 кВ Битца — Ясенево — на 30 389 м2, ЗОУИТ 77:00-6.122 Охранная зона "
    "ВЛ 220 кВ Бутово"
)


def run(js: str) -> dict:
    if not shutil_which("node"):
        pytest.skip("node недоступен")
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False,
                                     encoding="utf-8") as handle:
        handle.write(plato_question.SCRIPT + js)
        name = handle.name
    done = subprocess.run(["node", name], capture_output=True, text=True, timeout=60)
    Path(name).unlink(missing_ok=True)
    assert done.returncode == 0, done.stderr[:600]
    return json.loads(done.stdout.strip().splitlines()[-1])


def shutil_which(name: str):
    import shutil

    return shutil.which(name)


def test_a_long_lot_no_longer_blows_the_limit() -> None:
    got = run("""
    const rows=[]; for(let i=0;i<12;i++) rows.push('— %s : балл 70');
    const packed=platoPack(['ОТОБРАНО ЛОТОВ: 17 из 240'],
      [{name:'выбранное', lines:['ВЫБРАН: %s.', 'Почему в выборке: %s']},
       {name:'список', lines:rows}],
      {limit:3200, order:['выбранное','список'], lineLimit:240});
    console.log(JSON.stringify({len:packed.length, text:packed,
      longest:Math.max(...packed.split('\\n').map(l=>l.length))}));
    """ % (LONG_TITLE, LONG_TITLE, LONG_TITLE))
    assert got["len"] <= 3200, "вопрос всё ещё вылезает за бюджет"
    # Длинная строка обрезается, а не выбрасывает раздел целиком.
    assert got["longest"] <= 240
    # Выбранное важнее списка: спрашивают обычно про него.
    text = got["text"]
    assert text.index("ВЫБРАН") < text.index("— "), "список вытеснил выбранное"
    # Что не поместилось — сказано, и это не «данных нет».
    assert "НЕ ПОМЕСТИЛОСЬ В ВОПРОС" in text
    assert "не считай это отсутствием данных" in text


def test_the_warning_survives_even_when_everything_is_huge() -> None:
    """Место под строку «не поместилось» держится с начала: приписанная сверх
    бюджета, она обрезалась бы первой — пропадало бы ровно то предупреждение,
    ради которого она написана."""
    got = run("""
    const rows=[]; for(let i=0;i<40;i++) rows.push('строка '+i+' '.repeat(1)+'%s');
    const packed=platoPack(['ШАПКА'], [{name:'список', lines:rows}], {limit:900});
    console.log(JSON.stringify({len:packed.length, text:packed}));
    """ % LONG_TITLE)
    assert got["len"] <= 900
    assert "НЕ ПОМЕСТИЛОСЬ В ВОПРОС" in got["text"]


def test_the_count_is_declared_once_and_both_pages_use_it() -> None:
    """Второй счёт того же однажды разойдётся с первым, и одна поверхность
    будет отвечать «слишком длинный» там, где другая уложилась."""
    from auction_search.ui import auctions_page
    from market_search.cabinet import cabinet_page

    for page in (auctions_page(None), cabinet_page("sales")):
        assert "function platoPack(" in page, "помощник не подставился"
        assert page.count("function platoPack(") == 1
        assert plato_question.PLACEHOLDER not in page

    # И ни одна страница не считает бюджет своими руками.
    for path in (ROOT / "auction_search" / "ui.py",
                 ROOT / "market_search" / "cabinet.py"):
        body = path.read_text(encoding="utf-8")
        assert "НЕ ПОМЕСТИЛОСЬ В ВОПРОС" not in body, f"{path.name}: вторая укладка"


def test_the_auctions_page_counts_the_whole_message() -> None:
    """Бюджет считается на всё сообщение, а не на его середину: преамбула и
    вопрос человека вычитаются до укладки."""
    body = (ROOT / "auction_search" / "ui.py").read_text(encoding="utf-8")
    place = body.index("function askMessage(")
    chunk = body[place: body.index("\nfunction renderAskContext(", place)]
    assert "preamble.length" in chunk and "tail.length" in chunk
    assert re.search(r"platoPack\(parts\.head,\s*parts\.groups", chunk)
    # Сообщение собирается одной функцией, и её же зовёт кнопка.
    assert "const message=askMessage(question);" in body
