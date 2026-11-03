"""Колонки таблицы торгов — одно описание для книги Excel и страницы.

«Почему комментарии Платона в Excel мы вставляем, а в окне веб их нет?»
(владелец, 04.10.2026). Список колонок жил в `_xlsx`, а страница держала свой
набор заголовков в разметке: колонка, добавленная в книгу, на экран не
приезжала. Теперь список один — здесь. Книга берёт из него заголовки, ширину и
числовой формат; страница получает его маршрутом `/auctions/table` вместе со
строками, подготовленными тем же кодом, что строки книги, и своей копии
заголовков не держит.

`kind` — как значение показывать: число, деньги, площадь, дата, дни до срока,
длинный текст. Excel-формат выводится из него же, чтобы «деньги» в книге и на
экране не разошлись.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Column:
    key: str
    title: str
    width: int
    kind: str = "text"


# Числовые виды и их формат в книге. Ключ — `Column.kind`.
XLSX_FORMATS = {
    "area": '#,##0.00',
    "ha": '0.00',
    "gfa": '#,##0',
    "money": '#,##0" ₽"',
    "score": '0',
    "days": '0',
}
NUMERIC_KINDS = frozenset(XLSX_FORMATS)

AUCTION_COLUMNS: tuple[Column, ...] = (
    Column("section", "Раздел", 11),
    Column("name", "Название", 48, "long"),
    Column("okrug", "Округ", 10),
    Column("district", "Район", 18),
    Column("address", "Адрес", 34),
    Column("cadastre", "Кадастровые номера", 28),
    # Ссылка на участок — по координатам, полученным фоном у НСПД
    # (`lot_notes.points`); без точки клетка называет причину. Общая
    # карта без точки ссылкой «на участок» не считается.
    Column("nspd_map", "Участок на карте НСПД", 30),
    Column("type", "Тип", 18),
    Column("land_area_sqm", "Площадь участка, м²", 20, "area"),
    Column("building_area_sqm", "Площадь здания/ОКС, м²", 23, "area"),
    Column("krt_area_ha", "Площадь КРТ, га", 18, "ha"),
    Column("total_gfa_sqm", "Общий объём, м²", 18, "gfa"),
    Column("housing_gfa_sqm", "Жильё, м²", 16, "gfa"),
    Column("price", "Цена, ₽", 18, "money"),
    Column("score", "Балл лота", 17, "score"),
    Column("application_start", "Начало приёма заявок", 21, "date"),
    Column("application_deadline", "Окончание приёма заявок", 21, "date"),
    Column("days_to_deadline", "Дней до окончания заявок", 21, "days"),
    Column("auction_date", "Дата торгов", 18, "date"),
    Column("status", "Статус", 22),
    # Комментарий Платона — из фонового разбора лота; выгрузка и страница его
    # только читают (`lot_notes`). Пустой клетки нет: у отсутствия — причина.
    Column("plato_comment", "Комментарий Платона: чем интересен, чем опасен, что пишут", 70, "comment"),
    Column("url", "Источник", 42, "link"),
)

# Статусы, которые говорят «торги идут». У лота с прошедшим сроком приёма
# заявок они ложны: площадка не всегда успевает сменить статус, а «лот
# существует» и «идут торги» — разные состояния.
_LIVE_STATUSES = frozenset({"", "опубликован", "приём заявок", "прием заявок"})
CLOSED_STATUS = "Приём заявок закончился"


def status_for(status: str, days_to_deadline: int | None) -> str:
    """Статус строки с учётом срока: просроченный лот не выдаётся за идущие торги."""
    if days_to_deadline is not None and days_to_deadline < 0 \
            and str(status or "").strip().lower() in _LIVE_STATUSES:
        return CLOSED_STATUS
    return status


def days_text(days: int | None) -> str:
    """Клетка «Дней до окончания» на странице. Число то же, что в книге."""
    if days is None:
        return "Срок не понят: площадка не дала дату окончания приёма"
    if days < 0:
        return f"Приём заявок закончился ({-days} дн. назад)"
    if days == 0:
        return "Сегодня последний день"
    return str(days)


def _group(value: float, digits: int) -> str:
    text = f"{value:,.{digits}f}".replace(",", " ").replace(".", ",")
    return text


def cell_text(column: Column, value: Any) -> str:
    """Как клетка выглядит на странице. Пусто — тире: значения нет, а не ноль."""
    if column.kind == "days":
        return days_text(value if isinstance(value, int) else None)
    if value in (None, ""):
        return "—"
    if column.kind in NUMERIC_KINDS:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return str(value)
        if column.kind == "area":
            return _group(number, 0 if number.is_integer() else 2) + " м²"
        if column.kind == "ha":
            return _group(number, 2) + " га"
        if column.kind == "gfa":
            return _group(number, 0) + " м²"
        if column.kind == "money":
            return _group(number, 0) + " ₽"
        return _group(number, 0)
    return str(value)


def public_columns(columns: tuple[Column, ...] = AUCTION_COLUMNS) -> list[dict[str, Any]]:
    return [{"key": c.key, "title": c.title, "kind": c.kind, "width": c.width} for c in columns]
