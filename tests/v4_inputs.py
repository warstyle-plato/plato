"""Где на самом деле лежит вводная книги v4.

Ввод переехал на свой лист: «Вводные» — то, что правит человек, «Параметры
модели» — формулы шаблона, которые его читают. Координата вводной по-прежнему
объявлена один раз (`_V4_INPUT_CELLS`) и указывает на лист параметров; там
теперь стоит ссылка вида `='Вводные'!B34`.

Проверке нужно ЗНАЧЕНИЕ, а не то, на каком листе оно лежит. Поэтому она берёт
лист отсюда и читает по прежним координатам: ссылка раскрывается на месте.
Копировать сюда карту координат нельзя — она объявлена в движке, и второй
список разошёлся бы с первым молча.

Лист ПЛАТО и книга v2 держат свои «Вводные» и этого разделения не знают — их
проверки сюда не ходят.
"""

from __future__ import annotations

import re
from typing import Any

ENTRY = "Вводные"
PARAMS = "Параметры модели"

# Ссылка на лист ввода и ничего кроме неё: составная формула — это уже расчёт,
# и подставлять вместо неё чужое значение значит отвечать не на тот вопрос.
_LINK = re.compile(r"^=\s*'?([^'!]+)'?!\$?([A-Z]{1,3})\$?(\d+)\s*$")


class _Cell:
    """Ячейка листа параметров, читаемая насквозь через ссылку на ввод."""

    def __init__(self, book: Any, cell: Any) -> None:
        self._book = book
        self._cell = cell

    @property
    def value(self) -> Any:
        raw = self._cell.value
        if isinstance(raw, str):
            link = _LINK.match(raw)
            if link:
                sheet, column, row = link.groups()
                return self._book[sheet][f"{column}{row}"].value
        return raw

    @property
    def source(self) -> Any:
        """Сама ячейка листа параметров — со ссылкой, стилем и координатой."""
        return self._cell

    def __getattr__(self, name: str) -> Any:
        return getattr(self._cell, name)


class Inputs:
    """Лист параметров, читаемый как прежде: ссылки раскрываются."""

    def __init__(self, book: Any) -> None:
        self.book = book
        self.sheet = book[PARAMS]
        self.entry = book[ENTRY]

    @property
    def title(self) -> str:
        return self.sheet.title

    def __getitem__(self, coord: str) -> _Cell:
        return _Cell(self.book, self.sheet[coord])

    def __setitem__(self, coord: str, value: Any) -> None:
        """Записать вводную туда, где она живёт, — на лист ввода.

        Записанная поверх ссылки, она стёрла бы саму ссылку: лист параметров
        перестал бы читать ввод, и книга считала бы по числу, оставшемуся от
        проверки. Правка в Excel идёт на лист ввода — и здесь тоже.
        """
        raw = self.sheet[coord].value
        link = _LINK.match(raw) if isinstance(raw, str) else None
        if link:
            sheet, column, row = link.groups()
            self.book[sheet][f"{column}{row}"] = value
        else:
            self.sheet[coord] = value

    def cell(self, row: int | None = None, column: int | None = None, **kw: Any) -> _Cell:
        return _Cell(self.book, self.sheet.cell(row=row, column=column, **kw))

    def iter_rows(self, *a: Any, **kw: Any):
        for row in self.sheet.iter_rows(*a, **kw):
            yield tuple(_Cell(self.book, cell) for cell in row)

    def __getattr__(self, name: str) -> Any:
        return getattr(self.sheet, name)


def inputs(book: Any) -> Inputs:
    """Лист вводных книги v4 — с раскрытием ссылок на лист ввода."""
    return Inputs(book)


def value(book: Any, coord: str) -> Any:
    """Значение вводной по её координате на листе параметров."""
    return Inputs(book)[coord].value
