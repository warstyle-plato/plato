"""Доли ГНС → общая → продаваемая правятся руками, а не только смотрятся.

Наши доли — умолчание, восстановленное по выгрузкам ГлавАПУ и принятое
владельцем. Но у человека на руках бывает ГПЗУ или АГР со своими, и вписать их
должно быть можно (просьба владельца, 20.08.2026): прежде на месте правки
стояла кнопка «⟳ по пропорциям», считавшая строку нашими числами.

Правка живёт строкой во вводных — отдельного хранилища у неё нет, поэтому она
сохраняется, делится ссылкой и открывается вместе с проектом. Формат читают
двое: движок (`tep_ratios_applied`) и страница (`tepRatioOverrides`). Один
формат и два читателя — значит, они обязаны понимать его одинаково, и это
проверяется настоящим кодом страницы через node, а не его пересказом.

Запуск: python3 -m pytest tests/test_tep_ratios_can_be_edited.py -q
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import main as wrapper  # noqa: E402

core = wrapper.core


def page_reads(raw: str) -> dict:
    """Прогоняет настоящие функции разбора долей из PAGE через node."""
    node = shutil.which("node")
    if not node:
        pytest.skip("node недоступен")
    parts = []
    for name in ("tepRatioOverrides", "tepRatio", "tepRatioChain"):
        found = re.search(r"\nfunction " + name + r"\(.*?\n\}", core.PAGE, re.S)
        assert found, f"функция {name} на странице не найдена"
        parts.append(found.group(0))
    script = (
        "const TEP_RATIOS=" + json.dumps(core.TEP_RATIOS, ensure_ascii=False) + ";\n"
        "const inputs=" + json.dumps({core.TEP_RATIOS_INPUT: raw}) + ";\n"
        + "\n".join(parts) + "\n"
        "const out={};Object.keys(TEP_RATIOS).forEach(k=>{out[k]=tepRatio(k)});\n"
        "console.log(JSON.stringify(out));\n"
    )
    done = subprocess.run([node, "-e", script], capture_output=True, text=True, timeout=30)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def test_our_ratios_are_the_default():
    """Пустая строка — наши доли, без сюрпризов."""
    applied, warnings = core.tep_ratios_applied("")
    assert applied == core.TEP_RATIOS
    assert warnings == []
    assert core.tep_ratios_changed("") == []
    assert core.DEFAULT_INPUTS[core.TEP_RATIOS_INPUT] == ""


def test_the_chain_is_what_a_person_reads():
    """Хранится от ГНС, читается цепочкой: у квартир 65% ГНС — это 72,2% общей."""
    total, saleable_of_total = core.tep_ratio_chain(core.TEP_RATIOS["apartments"])
    assert total == pytest.approx(0.90)
    assert saleable_of_total == pytest.approx(0.65 / 0.90)


def test_a_hand_written_ratio_wins_over_ours():
    applied, warnings = core.tep_ratios_applied("apartments:94/70")
    assert warnings == []
    assert applied["apartments"]["total_of_gns"] == pytest.approx(0.94)
    assert applied["apartments"]["saleable_of_gns"] == pytest.approx(0.94 * 0.70)
    assert applied["apartments"]["source"] == "задано вручную"
    # Остальные продукты не трогаются: правка одной строки не переписывает таблицу.
    assert applied["offices"] == core.TEP_RATIOS["offices"]
    assert core.tep_ratios_changed("apartments:94/70") == ["apartments"]


def test_the_impossible_is_refused_not_applied():
    """Свободное поле доли — тот же класс ошибки, что дал 238 млрд ₽ платы за ВРИ.

    Общая больше ГНС и продаваемая больше общей не бывают. Такое значение не
    принимается вовсе: принятое с оговоркой уезжает в метры, а оговорку не
    читают.
    """
    for raw, word in (("apartments:140/70", "общая"),
                      ("apartments:90/130", "продаваемая"),
                      ("apartments:0/70", "общая"),
                      ("apartments:-5/70", "общая")):
        applied, warnings = core.tep_ratios_applied(raw)
        assert applied["apartments"] == core.TEP_RATIOS["apartments"], raw
        assert warnings and word in warnings[0].lower(), raw


def test_junk_is_named_not_swallowed():
    """Молчаливо пропущенная строка читается как принятая."""
    applied, warnings = core.tep_ratios_applied("нетакого:90/70;apartments:абв/70")
    assert applied == core.TEP_RATIOS
    assert len(warnings) == 2
    assert "такого продукта" in warnings[0]
    assert "не числа" in warnings[1]


@pytest.mark.parametrize("raw", [
    "",
    "apartments:94/70",
    "apartments:94/70;offices:90/55",
    "apartments:94,5/70,5",
    "apartments:140/70",          # отвергается — обеими сторонами одинаково
    "нетакого:90/70",
    "apartments:абв/70",
    "  apartments : 94 / 70  ",
])
def test_the_page_and_the_engine_read_one_string_alike(raw):
    """Один формат, два читателя. Разойдись они — строка значила бы разное.

    Проверяется настоящий код страницы через node: пересказ проверял бы себя.
    """
    engine, _ = core.tep_ratios_applied(raw)
    page = page_reads(raw)
    for key in core.TEP_RATIOS:
        assert page[key]["total_of_gns"] == pytest.approx(
            engine[key]["total_of_gns"], abs=1e-9), f"{raw} · {key}"
        assert page[key]["saleable_of_gns"] == pytest.approx(
            engine[key]["saleable_of_gns"], abs=1e-9), f"{raw} · {key}"


def test_the_button_is_gone_and_the_fields_are_there():
    """Кнопка «по пропорциям» заменена вводом, а не дополнена им."""
    page = core.PAGE
    assert 'onclick="refillTepRow(' not in page, (
        "кнопка пересчёта нашими долями убрана — доли пересчитывают строку сами")
    assert "tepRatioSet(" in page and "tepRatioReset(" in page
    assert "type=\"number\" step=\"0.1\" min=\"0\" max=\"100\"" in page, (
        "доли вводятся числом с потолком 100%")


def test_the_refusal_is_visible_without_opening_anything():
    """Отказ, которого не видно, читается как поломка.

    Раскрытия над таблицей больше нет — доли переехали под свои числа
    (владелец, 21.08.2026), — поэтому и прятать отказ стало негде. Проверка
    осталась той же по смыслу: он рисуется в подписи, а не молчит.
    """
    page = core.PAGE
    body = page[page.index("function renderTepRatioNote"):]
    body = body[:body.index("\nfunction tepRatioOverrides")]
    assert "<details" not in body, "доли и отказ больше ничем не накрыты"
    assert "tepRatioComplaint" in body
    assert "box.innerHTML=" in body and "+complaint" in body, (
        "отказ обязан попадать в подпись, а не теряться")


def test_the_ratios_survive_a_plot_import():
    """Доли — предпосылка аналитика, а не свойство участка.

    Импорт ГлавАПУ чистит поля, принадлежащие участку. Доля продукта к участку
    не относится: она про то, как этот девелопер строит, — и обнулять её вместе
    с ценой сделки было бы потерей.
    """
    page = core.PAGE
    listing = page[page.index("const TERRITORY_INPUT_KEYS=["):]
    listing = listing[:listing.index("];")]
    assert "purchase_price_mln" in listing, "список полей участка не найден"
    assert core.TEP_RATIOS_INPUT not in listing
