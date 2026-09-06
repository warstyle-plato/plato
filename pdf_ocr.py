"""Распознавание PDF-скана: одна реализация на весь сервис.

Скан без текстового слоя — это не пустой документ, и молча вернуть пустую
строку значит выдать «не смогли прочитать» за «в документе ничего нет». Пока
распознавание жило внутри читателя распоряжений о торгах, оно отвечало на один
вопрос — где адрес площадки; тизер и справка по участку упирались в тот же скан
и получали отказ, хотя средство лежало в двух модулях от них.

Две половины, и обе обязаны быть на месте. Растеризует страницу `pymupdf`,
читает буквы `tesseract` с русским словарём; в образе стоит и то и другое.
Проверять только одну половину нельзя: `tesseract` в образе есть с 31.08.2026,
а `pymupdf` не был объявлен нигде — и `ocr_available()` отвечало «да» ровно до
`import pymupdf`, после которого распознавание распоряжений умирало
`ModuleNotFoundError`. Тот же класс, что «файл лежит и корень принят — разные
вещи»: проверка половины says «умеем» о том, чего нет.
"""

from __future__ import annotations

import shutil
import subprocess

# Плотность растра. Двести точек — то, на чём распознавание распоряжений о
# торгах сошлось с прописью; ниже начинают путаться цифры, выше растёт время
# на страницу, а платим мы им.
DEFAULT_DPI = 200
# Сколько ждём распознавание ОДНОЙ страницы. Человек ждёт ответа в окне, и
# зависшая страница не имеет права держать его до конца бесконечности.
PAGE_TIMEOUT_SECONDS = 60


class Unavailable(RuntimeError):
    """Распознавания нет — это отказ, а не пустой ответ."""


def available() -> bool:
    """Есть ли обе половины. Половина — это «нет»."""
    return bool(shutil.which("tesseract")) and _rasterizer_ready()


def unavailable_reason() -> str:
    """Чего именно не хватает. Пусто — всё на месте."""
    missing = []
    if not shutil.which("tesseract"):
        missing.append("tesseract")
    if not _rasterizer_ready():
        missing.append("pymupdf")
    return ("в образе нет " + " и ".join(missing)) if missing else ""


def _rasterizer_ready() -> bool:
    try:
        import pymupdf  # noqa: F401
    except Exception:  # noqa: BLE001
        return False
    return True


def text(pdf: bytes, pages: int = 3, dpi: int = DEFAULT_DPI) -> str:
    """Распознать первые страницы документа.

    Сколько страниц — решает вызывающий: у распоряжения о торгах адрес, цена и
    задаток стоят в начале, у тизера числа рассыпаны по всему листу. Общего
    правильного числа тут нет, поэтому умолчание маленькое, а не щедрое.
    """
    reason = unavailable_reason()
    if reason:
        raise Unavailable(
            f"Распознавание недоступно: {reason}. Документ — скан, и без "
            "распознавания текста из него не достать.")
    import pymupdf

    document = pymupdf.open(stream=pdf, filetype="pdf")
    out: list[str] = []
    for index in range(min(max(0, int(pages)), document.page_count)):
        png = document[index].get_pixmap(dpi=dpi).tobytes("png")
        done = subprocess.run(
            ["tesseract", "stdin", "stdout", "-l", "rus", "--psm", "6"],
            input=png, capture_output=True, timeout=PAGE_TIMEOUT_SECONDS)
        out.append(done.stdout.decode("utf-8", errors="replace"))
    return "\n".join(out)
