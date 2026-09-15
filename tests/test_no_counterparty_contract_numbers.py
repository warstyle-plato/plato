"""Реквизиты чужих договоров в публичный репозиторий не едут.

Репозиторий открыт по решению владельца 07.09.2026. Номер кредитного договора
ничего не отпирает сам по себе, но он — реквизит договора третьего лица, и
опубликованный однажды он остаётся читаемым навсегда. Методику это не
обедняет: провенанс держится на контрагенте и дате сверки, а номера — у
владельца.

Сторож ищет ФОРМУ номера НКЛ (`400` + буквенно-цифровой хвост), а не
конкретные пять: следующий договор пришёл бы с другим номером и прошёл бы
мимо списка. Проверка сама себя не ловит — образец собран из кусков, а
исключением объявлено единственное место, ей же и принадлежащее.

Запуск: python3 -m pytest tests/test_no_counterparty_contract_numbers.py -q
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# «400» и дальше буквы с цифрами вперемешку — так выглядят номера НКЛ Сбера.
# Просто «400» + цифры не годится: это любое число, от площади до суммы.
_NUMBER = re.compile("40" + r"0(?=[0-9A-Z]*[A-Z])[0-9A-Z]{6,}")

# Запрещаем место, а не слово: этот файл несёт сам образец.
_ALLOWED = {"tests/test_no_counterparty_contract_numbers.py"}

_TEXT = {".py", ".md", ".json", ".js", ".css", ".html", ".txt", ".yml", ".yaml", ".sh"}


def _tracked() -> list[str]:
    out = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True,
                         text=True, check=True).stdout
    return [line for line in out.splitlines() if line]


def test_the_guard_has_files_to_read():
    """Иначе «нарушений нет» значит, что git не ответил."""
    files = [name for name in _tracked() if Path(name).suffix in _TEXT]
    assert len(files) > 100, f"прочитано подозрительно мало файлов: {len(files)}"


def test_the_guard_recognises_such_a_number():
    """Проверка, которая не падает на поломке, — не проверка."""
    assert _NUMBER.search("НКЛ Сбербанка " + "400" + "F00BVX003 от 04.08.2026")
    assert not _NUMBER.search("площадь 4000 м², цена 400 тыс ₽")


def test_no_tracked_file_names_a_counterparty_contract():
    found: list[str] = []
    for name in _tracked():
        if name in _ALLOWED or Path(name).suffix not in _TEXT:
            continue
        path = ROOT / name
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for match in _NUMBER.finditer(text):
            line = text.count("\n", 0, match.start()) + 1
            found.append(f"{name}:{line} → {match.group()}")
    assert not found, "реквизиты чужих договоров в репозитории:\n" + "\n".join(found)
