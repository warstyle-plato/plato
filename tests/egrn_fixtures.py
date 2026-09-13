"""Печатная форма выписки ЕГРН для проверок: текст живого документа и PDF из него.

Снимок текстового слоя — `fixtures/egrn_print_form_*`, выписка из ПУБЛИЧНОЙ
документации лота 21000005000000033444 (Задонский пр-д, влд. 1А). Нарисовать
форму самим было бы проверкой наших же подписей: у своей подделки подписи ровно
те, под которые написан разбор.

Ответ на «где взять форму для проверки» один на все файлы: две копии разошлись
бы молча — так же, как расходятся две копии любого другого правила.

Имя кадастрового инженера в снимке УБРАНО: репозиторий публичный, а имя
физического лица — персональные данные, и в разборе оно не участвует ни одним
полем. Дата кадастровых работ оставлена: она про объект, а не про человека.
"""

from __future__ import annotations

import pathlib

import pytest

FIXTURE = (pathlib.Path(__file__).parent / "fixtures"
           / "egrn_print_form_77_05_0012007_2054.txt")
LIVE = FIXTURE.read_text(encoding="utf-8")

# Фраза, которой форма ОБЪЯВЛЯЕТ раздел прав отсутствующим. Взята дословно у
# тринадцати выписок того же архива; подставляется в текст четырнадцатой, потому
# что снимок нужен один, а ответов у формы два.
ABSENT_NOTE = (
    "Сведения, необходимые для заполнения разделов: 2 - Сведения о "
    "зарегистрированных правах; 6 - Сведения о частях объекта недвижимости, "
    "отсутствуют."
)

# Шрифт с кириллицей: базовые четырнадцать шрифтов PDF её не несут вовсе, и
# нарисованная ими страница приходит пустой — то есть проверка PDF-пути была бы
# зелёной на любом коде. Путь спрашивается у образа, а не помнится числом:
# зашитый путь к браузеру уже стоил нам двенадцати молча пропущенных проверок.
FONTS = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
)


def without_rights(text: str = "") -> str:
    """Тот же документ, но раздел прав объявлен отсутствующим."""
    text = text or LIVE
    text = text.replace("Собственность", "данные отсутствуют")
    return text.replace("Особые отметки:\n", "Особые отметки:\n" + ABSENT_NOTE + "\n", 1)


def print_form_pdf(text: str = "") -> bytes:
    """Печатная форма в PDF с текстовым слоем — из текста живого документа."""
    pymupdf = pytest.importorskip("pymupdf")
    font = next((path for path in FONTS if pathlib.Path(path).exists()), "")
    if not font:
        pytest.skip("в образе нет шрифта с кириллицей: " + ", ".join(FONTS)
                    + " — рисовать страницу нечем")
    text = text or LIVE[:6600]
    document = pymupdf.open()
    for start in range(0, len(text), 3200):
        page = document.new_page()
        page.insert_font(fontname="cyr", fontfile=font)
        page.insert_textbox(pymupdf.Rect(15, 15, 585, 820), text[start:start + 3200],
                            fontsize=4.5, fontname="cyr")
    return document.tobytes()
