"""Дата торгов: читается там, где площадка её отдаёт, и названа отсутствующей там, где нет.

Поле `auction_date` у лота было, но ни один адаптер его не заполнял: реестр
ЭТП РФ отдаёт колонку «Дата начала торгов», а разбор её пропускал. Пустое поле
на экране читалось как «даты нет вовсе». Теперь пустота называет причину —
«дата торгов не получена от источника», — а просроченный лот в карточке КРТ
говорит, что приём заявок закончился, а не «живой лот не найден».
"""

from __future__ import annotations

from auction_search import krt_tenders
from auction_search.adapters.etp_rf import ETPRFAdapter
from auction_search.krt_investment_card import krt_investment_card_page
import page_blocks  # noqa: E402 — стенд страницы, лежит рядом с тестами

_HEADER = """<table><thead><tr>
  <th>Номер</th><th>Номер извещения</th><th>Предмет извещения</th>
  <th>Начальная цена</th><th>Организатор</th><th>Дата публикации</th>
  <th>Дата начала приема заявок</th><th>Дата завершения приема заявок</th>
  <th>Дата начала торгов</th><th>Статус извещения</th>
  <th>Статус торгов</th><th>Тип извещения</th>
</tr></thead><tbody>"""
_ROW = """<tr>
  <td><a href="/Notification/id/20019">20019</a></td><td>BNKOA00014936</td>
  <td>Продажа земельного участка, г. Москва, площадь 57 367 кв. м,
      кадастровый номер 77:02:0002002:19</td>
  <td>277 000 000 руб.</td><td>Конкурсный управляющий</td><td>28.08.2026 10:00</td>
  <td>28.08.2026 12:00</td><td>01.09.2099 12:00</td><td>05.09.2099 12:00</td>
  <td>Опубликовано</td><td>Ожидает подачи заявок</td>
  <td>Продажа имущества должника (банкротство)</td>
</tr>"""


def _lot(html: str):
    rows = ETPRFAdapter._rows(html)
    return ETPRFAdapter._to_lot(rows[0], "2026-09-28T00:00:00+00:00")


def test_etp_rf_keeps_the_auction_date_it_is_given() -> None:
    lot = _lot(_HEADER + _ROW + "</tbody></table>")
    assert lot is not None
    assert lot.auction_date == "2099-09-05T12:00:00+03:00"
    assert lot.application_start == "2026-08-28T12:00:00+03:00"
    assert lot.application_deadline == "2099-09-01T12:00:00+03:00"
    assert lot.provenance["auction_date"].raw_value == lot.auction_date


def test_without_a_header_the_dates_are_not_guessed_by_position() -> None:
    """Без заголовка колонку даты торгов не отличить от соседней — не берём."""
    lot = _lot("<table><tbody>" + _ROW + "</tbody></table>")
    assert lot is not None
    assert lot.auction_date is None and lot.application_start is None
    assert "auction_date" not in lot.provenance


def test_a_missing_auction_date_names_the_source() -> None:
    sites = [{"slug": "s", "name": "", "okrug": "", "cadastral_numbers": ["77:01:0001001:1"]}]
    lot = {"title": "Аукцион на право заключения договора о КРТ",
           "cadastral_numbers": ["77:01:0001001:1"], "lot_kind": "krt",
           "application_deadline": "2099-10-01T18:00:00+03:00",
           "source": {"catalogue": "ГИС Торги", "lot_url": "https://torgi.gov.ru/1"}}
    linked = krt_tenders.match([lot], sites)
    [summary] = linked["by_site"].get("s") or linked["unmatched"]
    assert summary["auction_date_label"] == ""
    assert summary["auction_date_note"] == "дата торгов не получена от источника (ГИС Торги)"

    dated = krt_tenders.auction_date_fields({"auction_date": "2099-09-05T12:00:00+03:00"})
    assert dated == {"auction_date_label": "05.09.2099, 12:00 МСК", "auction_date_note": ""}


def test_a_stored_link_gets_the_note_on_read() -> None:
    """Связка прежних выпусков подписи не несёт — считается на чтении."""
    [old] = krt_tenders.with_moment([{"deadline": "01.10.2099", "source": "РАД"}])
    assert old["auction_date_note"] == "дата торгов не получена от источника (РАД)"
    assert old["deadline_iso"]


# Окружение карточки, а не её логика: DOM и «сейчас». Функции страницы стенд
# добирает сам (`page_blocks.run`).
_DOM = ("Date.now=()=>1790000000000;let html='';"
        "const document={getElementById:()=>({set innerHTML(v){html=v}})};")
_EXPIRED = "{deadline:'01.09.2026',deadline_iso:'2026-09-01T18:00:00+03:00'}"
_FUTURE = "{deadline:'01.10.2026',deadline_iso:'2026-10-01T18:00:00+03:00'"


def _entries(prelude: str, *rows: str) -> list[str]:
    tail = ("const out=[];"
            + "".join(f"renderEntry({row},{{}});out.push(html);" for row in rows)
            + "console.log(JSON.stringify(out));")
    return page_blocks.run_json(_DOM + prelude, tail, page=krt_investment_card_page("x"))


def test_the_card_says_when_applications_closed_and_names_the_auction_date() -> None:
    expired, undated, dated = _entries(
        "",
        "{tender_lots:[" + _EXPIRED + "]}",
        "{tender_lots:[" + _FUTURE + ",auction_date_note:'дата торгов не получена от источника (ГИС Торги)'}]}",
        "{tender_lots:[" + _FUTURE + ",auction_date_label:'05.10.2026, 12:00 МСК'}]}",
    )
    assert "Идёт аукцион" not in expired
    assert "приём заявок закончился 01.09.2026" in expired
    assert "Идёт аукцион" in undated
    assert "дата торгов не получена от источника (ГИС Торги)" in undated
    assert "Торги 05.10.2026, 12:00 МСК" in dated


def test_a_lot_rejected_for_another_reason_is_not_called_closed() -> None:
    """«Закончился» — только по прошедшему сроку, а не по отказу activeTender.

    Правило живого лота может отбросить лот и по другой причине (снят,
    отменён). Срок у такого лота впереди, и «приём заявок закончился» было бы
    неправдой про него.
    """
    [entry] = _entries("function activeTender(){return null}",
                       "{tender_lots:[" + _FUTURE + "}]}")
    assert "закончился" not in entry
