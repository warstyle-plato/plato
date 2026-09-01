"""«Планируемая» в каталоге — это «стройка не начата», а не «свободна».

Владелец (01.09.2026): «первичный парсинг источников нужен, чтобы избегать
таких классификаций как планируемая, когда она давно уже отдана другим».

На Маршала Воробьева, вл. 12 договор о КРТ заключён с правообладателями —
город подписал его с тремя застройщиками, торгов по площадке не будет вовсе.
В каталоге krt.mos.ru она при этом стоит «Планируемая», потому что статус там
отвечает на другой вопрос: начата ли стройка. Экран читал статус как ответ на
свой — рисовал зелёную метку с подсказкой «Войти ещё можно», то есть
утверждал то, чего каталог не говорил.

Отсюда два правила, и второе важнее первого. Занятость решается уликами —
названным застройщиком карточки, названным оператором публикации, заключённым
договором, — а не полем статуса. И **неизвестная занятость называется
неизвестной**: молчание источника не «свободно», ровно как пустой ответ НСПД
не «чисто».

Заключённый договор при этом не разновидность стадии: стадия отвечает на «как
далеко зашло», а он — на «можно ли ещё войти». Пока он лежал в общем списке
стадий, на балл и на фильтр он не влиял никак.

Запуск: python3 -m pytest tests/test_a_planned_site_is_not_a_free_one.py -q
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from auction_search import ui  # noqa: E402
from market_search import krt_open_sources  # noqa: E402

NAME = "Маршала Воробьева ул., вл. 12"


@dataclass
class Doc:
    title: str
    url: str
    domain: str
    snippet: str
    rank: int = 1


def _read(snippet: str) -> dict:
    return krt_open_sources.read_findings(
        [Doc(title="Новости", url="https://stroygaz.ru/1", domain="stroygaz.ru",
             snippet=snippet)], NAME)


def test_a_signed_agreement_takes_the_site():
    found = _read("Город и правообладатели трёх участков в районе Строгино заключили "
                  "договор о комплексном развитии территории на Маршала Воробьева, вл. 12.")
    assert found["agreement"], "заключённый договор не прочитан"
    assert found["taken"] is True, "площадка с заключённым договором считается свободной"
    assert not found["free"]


def test_an_owner_initiative_takes_the_site_too():
    found = _read("КРТ по адресу Маршала Воробьева, вл. 12 реализуется "
                  "по инициативе правообладателей земельных участков.")
    assert found["agreement"], "инициатива правообладателей не прочитана"
    assert found["taken"] is True


def test_the_agreement_is_not_filed_as_a_stage():
    """Стадия отвечает на «как далеко зашло», договор — на «можно ли войти»."""
    found = _read("Город и правообладатели заключили договор о комплексном развитии "
                  "территории на Маршала Воробьева, вл. 12.")
    assert not found["stage"], "договор снова уехал в общий список стадий"


def test_a_site_nobody_wrote_about_stays_free():
    found = _read("На Маршала Воробьева, вл. 12 представлена концепция застройки.")
    assert not found["agreement"]
    assert found["taken"] is False
    assert found["stage"], "стадия перестала читаться вовсе"


def test_the_status_cell_no_longer_promises_that_the_site_is_free():
    page = ui.auctions_page(None)
    assert "function krtStatusCell(" in page, \
        "ответ о занятости снова считается прямо в разметке строки"
    assert "Войти ещё можно" not in page, \
        "статус каталога опять обещает то, чего каталог не говорит"
    assert "занятость не проверена" in page, \
        "непроверенная занятость выдаётся за свободную площадку"


def test_the_taken_site_is_cut_by_a_named_reason():
    page = ui.auctions_page(None)
    body = page[page.index("function krtScore("):]
    body = body[:body.index("\nfunction ")]
    assert "договор о КРТ уже заключён" in body, \
        "снижение за заключённый договор не названо — снижение без причины это просто другое число"


def test_the_screen_shows_the_agreement_it_found():
    page = ui.auctions_page(None)
    assert re.search(r"krtPressLines\(d\.agreement,", page), \
        "найденный договор нигде не показывается — находка есть и не видна"
