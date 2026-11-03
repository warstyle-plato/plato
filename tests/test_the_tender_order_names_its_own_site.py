"""Распоряжение о торгах само называет свою площадку — после распознавания.

«Мы сами ищем с твоей помощью, а не знаем это» (владелец, 31.08.2026): привязку
распоряжения к площадке должна делать программа. Ручная отметка была
перекладыванием работы обратно на него.

Казалось, что нечем: распоряжение ДГП не называет адреса ни в заголовке, ни в
карточке документа mos.ru, текстовые поля записи поиска пустые, вложение одно, а
PDF — скан (семь страниц, 199 картинок на первой, текста только регистрационный
штамп). Оказалось, нечем было только без распознавания: в тексте страницы есть
адрес, короткое имя КРТ, начальная цена аукциона, шаг и задаток.

Текст ниже — настоящий, из распознанного распоряжения ДГП-Р-28/26 от 13.05.2026.

Главная защита — цифры проверяются прописью. В документе сумма написана дважды,
и это единственный способ поймать съеденный распознаванием пробел: «2403 657
113» читается как 2,4 млрд, а могло быть 240 млрд. Не сошлось — величина не
показывается вовсе, а не показывается «примерно».

Запуск: python3 -m pytest tests/test_the_tender_order_names_its_own_site.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from market_search.krt_tender_orders import (  # noqa: E402
    checked_amount, match_site, parse_order,
)

LIVE = """
ПРАВИТЕЛЬСТВО МОСКВЫ
ДЕПАРТАМЕНТ ГРАДОСТРОИТЕЛЬНОЙ ПОЛИТИКИ ГОРОДА МОСКВЫ
О проведении торгов в форме аукциона на право заключения договора о
комплексном развитии территорий нежилой застройки города Москвы
В соответствии с Градостроительным кодексом Российской Федерации,
постановлениями Правительства Москвы от 16 января 2024 г. № 36-ПП
«О комплексном развитии территорий нежилой застройки города Москвы,
расположенных по адресам: г. Москва, Куркинское ш., вл. 27-39, Куркинское
ш., вл. 21, ул. Героев Панфиловцев, вл. 20, корп. 1» (далее — решение о КРТ
«Куркинское ш., ул. Героев Панфиловцев»)
2. Утвердить следующие условия проведения аукциона:
2.1. Начальная цена предмета аукциона в размере 110 760 951 (сто
десять миллионов семьсот шестьдесят тысяч девятьсот пятьдесят один)
рубль 18 копеек с учетом НДС.
2.2. Величина повышения начальной цены предмета аукциона
(«шаг аукциона») в размере 2 215 219 (два миллиона двести пятнадцать
тысяч двести девятнадцать) рублей 02 копейки, что составляет 2 %.
2.3. Сумма задатка за участие в аукционе в размере 22 152 190
(двадцать два миллиона сто пятьдесят две тысячи сто девяносто) рублей.
"""

SITES = [
    {"slug": "kurkinskoe", "name": "Куркинское ш., вл. 27-39, Куркинское ш., вл. 21, "
                                   "Героев Панфиловцев ул., вл. 20, корп. 1", "okrug": "СЗАО"},
    {"slug": "other", "name": "Светлый проезд, вл. 4", "okrug": "САО"},
]


def test_the_address_and_the_money_come_out_of_the_scan() -> None:
    got = parse_order(LIVE)
    assert "Куркинское" in got["address"] and "Героев Панфиловцев" in got["address"]
    assert got["krt_name"] == "Куркинское ш., ул. Героев Панфиловцев"
    assert got["start_price_rub"] == 110_760_951
    assert got["step_rub"] == 2_215_219
    assert got["deposit_rub"] == 22_152_190
    assert got["notes"] == []


def test_the_order_finds_its_site_by_street_and_holding() -> None:
    site = match_site(parse_order(LIVE), SITES)
    assert site and site["slug"] == "kurkinskoe"


def test_a_wrong_site_is_not_taken() -> None:
    """Ложная привязка объявила бы площадку выставленной на торги."""
    assert match_site(parse_order(LIVE), [SITES[1]]) is None
    assert match_site({"address": "", "krt_name": ""}, SITES) is None


def test_the_digits_are_confirmed_by_the_words() -> None:
    value, why = checked_amount("2403 657 113", "два миллиарда четыреста три миллиона")
    assert value == 2_403_657_113 and not why
    lost, why = checked_amount("240 365", "два миллиарда четыреста три миллиона")
    assert lost is None and "расходятся" in why
    extra, why = checked_amount("24036571130", "два миллиарда четыреста три миллиона")
    assert extra is None, "лишняя цифра тоже обязана ловиться"


def test_an_unreadable_amount_is_dropped_not_guessed() -> None:
    broken = LIVE.replace("110 760 951 (сто\nдесять миллионов", "11 (сто\nдесять миллионов")
    got = parse_order(broken)
    assert "start_price_rub" not in got, "величина, не сошедшаяся с прописью, не показывается"
    assert any("start_price_rub" in note for note in got["notes"]), "и причина названа"


def test_a_text_without_a_site_says_so() -> None:
    got = parse_order("О проведении торгов в форме аукциона. Прочее.")
    assert not got["address"] and not got["krt_name"]
    assert any("ни адреса, ни имени" in note for note in got["notes"])


def test_the_image_carries_the_recogniser() -> None:
    """Без tesseract в образе распознавать нечем, и на проде это молчало бы."""
    docker = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "tesseract-ocr" in docker and "tesseract-ocr-rus" in docker
    assert "скан" in docker, "причина названа там же, где строка установки"


def test_a_missing_recogniser_is_a_refusal_not_an_empty_answer(monkeypatch) -> None:
    """Проверяется отказ, а не строка в исходнике.

    Прежняя версия искала «class OcrUnavailable» в файле — то есть держала
    СПОСОБ, которым исполнено утверждение. Распознавание объявлено один раз и
    переехало в `pdf_ocr`, имена здесь стали ссылками на него, и проверка
    упала бы на верном поведении.
    """
    import pdf_ocr
    from market_search import krt_tender_orders as orders

    monkeypatch.setattr(pdf_ocr.shutil, "which", lambda name: None)
    assert orders.ocr_available() is False
    try:
        orders.ocr(b"%PDF-1.4")
    except orders.OcrUnavailable as exc:
        assert "tesseract" in str(exc)
    else:  # pragma: no cover - отказ обязателен
        raise AssertionError("пустой ответ вместо отказа")
    assert orders.ocr.__doc__ and "приложения" in orders.ocr.__doc__
