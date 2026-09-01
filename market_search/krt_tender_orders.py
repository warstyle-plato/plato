"""Распоряжение о торгах по КРТ: распознать скан и понять, о какой площадке речь.

Владелец: «мы сами ищем с твоей помощью, а не знаем это» — то есть привязку
распоряжения к площадке должна делать программа, а не человек (31.08.2026).
Прежняя ручная отметка была перекладыванием работы обратно на него.

Машине это казалось невозможным: распоряжение ДГП не называет адреса ни в
заголовке, ни в карточке документа mos.ru, текстовые поля записи поиска пустые,
вложение одно, а PDF — скан (семь страниц, 199 картинок на первой, текста
только регистрационный штамп). Оказалось, невозможно было только без
распознавания: в тексте страницы есть и адрес, и короткое имя КРТ, и начальная
цена аукциона, и шаг, и задаток.

Цифры из распознавания проверяются словами. В документе сумма написана дважды —
цифрами и прописью, — и это единственная защита от съеденного пробела:
«2403 657 113» читается как 2,4 млрд, а могло быть 240 млрд. Не сошлось —
величина не показывается вовсе, а не показывается «примерно».
"""

from __future__ import annotations

import re
import shutil
import subprocess
from typing import Any

_SPACE = re.compile(r"\s+")

# Адрес: «...расположенных по адресам: г. Москва, ... » — до закрывающей кавычки
# или до слова «(далее».
_ADDRESS = re.compile(
    r"(?iu)расположенн\w*\s+по\s+адрес\w*:?\s*(?P<value>.{10,240}?)\s*(?:»|\(далее|$)")
# Короткое имя КРТ в кавычках: «КРТ «Куркинское ш., ул. Героев Панфиловцев»».
_KRT_NAME = re.compile(r"(?iu)КРТ\s*«(?P<value>[^»]{4,90})»")
_START_PRICE = re.compile(
    r"(?iu)начальная\s+цена\s+предмета\s+аукциона\s+в\s+размере\s*(?P<digits>[\d  ]{4,20})"
    r"\s*\((?P<words>[^)]{10,220})\)")
_STEP = re.compile(
    r"(?iu)«?шаг\s+аукциона»?\)?\s*в\s+размере\s*(?P<digits>[\d  ]{4,20})\s*\((?P<words>[^)]{10,220})\)")
_DEPOSIT = re.compile(
    r"(?iu)сумма\s+задатка[^0-9]{0,80}?(?P<digits>[\d  ]{4,20})\s*\((?P<words>[^)]{10,220})\)")

# Пропись проверяет не только порядок, но и старшие разряды: «два миллиарда»
# означает, что перед «миллиард» стоит именно 2, а не 24. Порядка мало —
# лишняя цифра его не меняет.
_MAGNITUDE = (
    ("миллиард", 1_000_000_000),
    ("миллион", 1_000_000),
    ("тысяч", 1_000),
)
# Числительные до 999: столько и нужно, чтобы прочитать «сто десять» перед
# словом «миллионов». Полного разбора не пишем — дальше старшего разряда
# проверять нечего.
_UNITS = {
    "один": 1, "одна": 1, "два": 2, "две": 2, "три": 3, "четыре": 4, "пять": 5,
    "шесть": 6, "семь": 7, "восемь": 8, "девять": 9, "десять": 10,
    "одиннадцать": 11, "двенадцать": 12, "тринадцать": 13, "четырнадцать": 14,
    "пятнадцать": 15, "шестнадцать": 16, "семнадцать": 17, "восемнадцать": 18,
    "девятнадцать": 19, "двадцать": 20, "тридцать": 30, "сорок": 40,
    "пятьдесят": 50, "шестьдесят": 60, "семьдесят": 70, "восемьдесят": 80,
    "девяносто": 90, "сто": 100, "двести": 200, "триста": 300, "четыреста": 400,
    "пятьсот": 500, "шестьсот": 600, "семьсот": 700, "восемьсот": 800,
    "девятьсот": 900,
}


class OcrUnavailable(RuntimeError):
    """Распознавания нет — это отказ, а не пустой ответ."""


def ocr_available() -> bool:
    return bool(shutil.which("tesseract"))


def ocr(pdf: bytes, pages: int = 3, dpi: int = 200) -> str:
    """Распознать первые страницы распоряжения.

    Дальше третьей не идём: адрес, цена, шаг и задаток стоят в начале, а
    приложения — это таблицы участков на десяток страниц, и распознавать их
    ради привязки незачем.
    """
    if not ocr_available():
        raise OcrUnavailable(
            "Распознавание недоступно: в образе нет tesseract. "
            "Распоряжение о торгах — скан, и без него адрес из него не достать.")
    import pymupdf

    document = pymupdf.open(stream=pdf, filetype="pdf")
    out: list[str] = []
    for index in range(min(pages, document.page_count)):
        png = document[index].get_pixmap(dpi=dpi).tobytes("png")
        done = subprocess.run(["tesseract", "stdin", "stdout", "-l", "rus", "--psm", "6"],
                              input=png, capture_output=True, timeout=180)
        out.append(done.stdout.decode("utf-8", errors="replace"))
    return "\n".join(out)


def _digits(raw: str) -> int | None:
    clean = re.sub(r"[^\d]", "", raw or "")
    return int(clean) if clean else None


def _expected_magnitude(words: str) -> tuple[int, int | None]:
    """Порядок величины и старший разряд прописью: (1e9, 2) для «два миллиарда»."""
    low = _SPACE.sub(" ", (words or "").casefold())
    for word, value in _MAGNITUDE:
        at = low.find(word)
        if at < 0:
            continue
        lead = 0
        for token in low[:at].replace("-", " ").split():
            lead += _UNITS.get(token.strip(",."), 0)
        return value, (lead or None)
    return 1, None


def checked_amount(digits: str, words: str) -> tuple[int | None, str]:
    """Число цифрами, подтверждённое числом прописью.

    Возвращает значение и причину отказа. Не сошлось — величины нет: показать
    «примерно» значит показать цифру, за которую никто не отвечает.
    """
    value = _digits(digits)
    if value is None:
        return None, "цифры не распознаны"
    magnitude, lead = _expected_magnitude(words)
    said = f"цифры и пропись расходятся: {value} против «{_SPACE.sub(' ', words).strip()[:60]}»"
    if not (magnitude <= value < magnitude * 1000):
        return None, said
    # Старший разряд: «два миллиарда» — это 2, а не 24. Порядок лишнюю цифру
    # не ловит, а старший разряд ловит.
    if lead is not None and value // magnitude != lead:
        return None, said
    return value, ""


def parse_order(text: str) -> dict[str, Any]:
    """Разобрать распознанный текст распоряжения."""
    flat = _SPACE.sub(" ", text or "")
    out: dict[str, Any] = {"address": "", "krt_name": "", "notes": []}
    found = _ADDRESS.search(flat)
    if found:
        out["address"] = found.group("value").strip(" ,;")
    name = _KRT_NAME.search(flat)
    if name:
        out["krt_name"] = name.group("value").strip()
    for key, pattern in (("start_price_rub", _START_PRICE), ("step_rub", _STEP),
                         ("deposit_rub", _DEPOSIT)):
        hit = pattern.search(flat)
        if not hit:
            continue
        value, why = checked_amount(hit.group("digits"), hit.group("words"))
        if value is None:
            out["notes"].append(f"{key}: {why}")
            continue
        out[key] = value
    if not out["address"] and not out["krt_name"]:
        out["notes"].append("ни адреса, ни имени КРТ в распознанном тексте не нашлось")
    return out


def match_site(order: dict[str, Any], sites: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Найти площадку каталога по адресу распоряжения или по имени КРТ.

    Правило совпадения одно на модуль — то же, что у решений и у лотов: улица
    держится за своим владением. Ложная привязка объявила бы площадку
    выставленной на торги.
    """
    from .krt_decisions import same_place

    address = str(order.get("address") or "")
    name = str(order.get("krt_name") or "")
    for site in sites or []:
        title = str(site.get("name") or "")
        if not title:
            continue
        if address and same_place(address, title):
            return site
        # Имя КРТ короче адреса и владения не несёт: сверяем его только целиком
        # по значащим словам, и только когда адреса нет вовсе.
        if not address and name and same_place(name, title):
            return site
    return None
