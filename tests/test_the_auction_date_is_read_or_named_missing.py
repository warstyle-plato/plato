"""Дата торгов: читается там, где площадка её отдаёт, и названа отсутствующей там, где нет.

Поле `auction_date` у лота было, но ни один адаптер его не заполнял: реестр
ЭТП РФ отдаёт колонку «Дата начала торгов», а разбор её пропускал. Пустое поле
на экране читалось как «даты нет вовсе». Теперь пустота называет причину —
«дата торгов не получена от источника», — а просроченный лот в карточке КРТ
говорит, что приём заявок закончился, а не «живой лот не найден».
"""

from __future__ import annotations

import json
import shutil
import subprocess

import pytest

from auction_search import krt_tenders
from auction_search.adapters.etp_rf import ETPRFAdapter
from auction_search.krt_investment_card import krt_investment_card_page

NODE = shutil.which("node")

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


@pytest.mark.parametrize("with_header", [True, False])
def test_etp_rf_keeps_the_auction_date_it_is_given(with_header: bool) -> None:
    html = (_HEADER if with_header else "<table><tbody>") + _ROW + "</tbody></table>"
    rows = ETPRFAdapter._rows(html)
    lot = ETPRFAdapter._to_lot(rows[0], "2026-09-28T00:00:00+00:00")
    assert lot is not None
    assert lot.auction_date == "2099-09-05T12:00:00+03:00"
    assert lot.application_start == "2026-08-28T12:00:00+03:00"
    assert lot.application_deadline == "2099-09-01T12:00:00+03:00"
    assert lot.provenance["auction_date"].raw_value == lot.auction_date


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


def _function(page: str, name: str) -> str:
    start = page.index(f"function {name}(")
    depth = 0
    for index in range(page.index("{", start), len(page)):
        depth += {"{": 1, "}": -1}.get(page[index], 0)
        if depth == 0:
            return page[start:index + 1]
    raise AssertionError(name)


@pytest.mark.skipif(NODE is None, reason="node не установлен")
def test_the_card_says_when_applications_closed_and_names_the_auction_date() -> None:
    card = krt_investment_card_page("x")
    code = (
        "Date.now=()=>1790000000000;"
        "const esc=s=>String(s??''),fmt=v=>String(v),num=v=>v==null?null:Number(v),"
        "safeUrl=u=>u;let html='';const $=()=>({set innerHTML(v){html=v}});"
        + "".join(_function(card, n) for n in
                  ("liveTenderLot", "activeTender", "operatorInfo", "renderEntry"))
        + "const out=[];"
        "renderEntry({tender_lots:[{deadline:'01.09.2026',deadline_iso:'2026-09-01T18:00:00+03:00'}]},{});out.push(html);"
        "renderEntry({tender_lots:[{deadline:'01.10.2026',deadline_iso:'2026-10-01T18:00:00+03:00',"
        "auction_date_note:'дата торгов не получена от источника (ГИС Торги)'}]},{});out.push(html);"
        "renderEntry({tender_lots:[{deadline:'01.10.2026',deadline_iso:'2026-10-01T18:00:00+03:00',"
        "auction_date_label:'05.10.2026, 12:00 МСК'}]},{});out.push(html);"
        "console.log(JSON.stringify(out));"
    )
    run = subprocess.run([NODE, "-e", code], capture_output=True, text=True, timeout=30)
    assert run.returncode == 0, run.stderr
    expired, undated, dated = json.loads(run.stdout)
    assert "Идёт аукцион" not in expired
    assert "приём заявок закончился 01.09.2026" in expired
    assert "Идёт аукцион" in undated
    assert "дата торгов не получена от источника (ГИС Торги)" in undated
    assert "Торги 05.10.2026, 12:00 МСК" in dated
