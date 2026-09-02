"""Правила проверки владельца — мерка для нашего разбора публикаций.

Владелец прислал проверку 55 площадок КРТ с методикой (02.09.2026,
`docs/reference/krt_operator_check_20260902.xlsx`). На пятидесяти пяти
площадках у него: оператор установлен у ТРЁХ, реновация подтверждена у
пятнадцати, торги найдены у девяти, статус не установлен у сорока одной. Наш
разбор утверждал заметно больше — и в этом вся разница.

Из методики дословно:

* **оператор КРТ** — только лицо, прямо названное оператором либо стороной
  заключённого адресного договора; бренд ЖК сам по себе оператором не
  считается;
* **застройщик / правообладатель** вынесен отдельно: застройщик здания,
  правообладатель земли и оператор КРТ могут быть разными лицами;
* **торги** — только на право заключения договора КРТ; закупка подрядчика
  действующим оператором площадку доступной не делает;
* **реновация** — «да» только при адресном упоминании; новость о районе
  целиком на проект не переносится;
* **Фонд реновации** — роль записана буквально; упоминание Фонда не означает,
  что он оператор;
* **«не найдено»** — отсутствие подтверждения в доступной выдаче на дату, а не
  доказательство отсутствия факта;
* **надёжность** — высокая (адресный первичный или официальный источник),
  средняя (отраслевой или реестровый), ограниченная (только карточка).

Запуск: python3 -m pytest tests/test_the_owner_check_is_the_yardstick.py -q
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from market_search import krt_open_sources as sources  # noqa: E402

CHECK = json.loads((ROOT / "tests" / "fixtures" / "krt_owner_check_20260902.json")
                   .read_text(encoding="utf-8"))


def doc(title: str, snippet: str, domain: str = "example.ru") -> SimpleNamespace:
    return SimpleNamespace(title=title, snippet=snippet,
                           url=f"https://{domain}/a", domain=domain)


def test_the_yardstick_is_in_the_repository() -> None:
    """Файл лежит рядом, а не в переписке: ссылки протухают, файл — нет."""
    assert (ROOT / "docs" / "reference" / "krt_operator_check_20260902.xlsx").exists()
    assert len(CHECK["rows"]) == 55
    named = [row for row in CHECK["rows"]
             if "Не найдено" not in row["operator"] and "Не определ" not in row["operator"]]
    assert len(named) == 5, "эталон изменился — проверьте, что мерка та же"


def test_a_developer_is_not_an_operator() -> None:
    """«Бренд ЖК сам по себе оператором не считается» — методика владельца."""
    found = sources.read_findings(
        [doc("ЖК на Шипиловском проезде, вл. 55",
             "Застройщиком жилого комплекса на Шипиловском проезде, вл. 55 выступает ПАО «ПИК».")],
        "Шипиловский пр-д, вл. 55")
    assert found["operator_named"] == [], "застройщик записан оператором КРТ"
    assert found["developer_named"], "застройщик потерян — он нужен отдельной строкой"
    assert found["taken"] is False, "застройщик здания вход на площадку не закрывает"


def test_the_operator_is_the_one_named_so() -> None:
    found = sources.read_findings(
        [doc("КРТ на Магистральных улицах",
             "Оператором комплексного развития территории «Магистральные улицы тер. 4, 5, 6» "
             "выступает ООО «КРТ «Магистральные улицы».")],
        "Магистральные улицы тер. 4, 5, 6")
    assert found["operator_named"], "оператор, названный прямо, не прочитан"


def test_a_contractor_tender_does_not_open_the_site() -> None:
    """«Закупка подрядчика действующим оператором площадку не открывает»."""
    found = sources.read_findings(
        [doc("Торги по Пудовкина, вл. 7А",
             "На улице Пудовкина, вл. 7А объявлены торги на поиск генерального подрядчика.")],
        "Улица Пудовкина, вл. 7А")
    assert found["contract_tender"] == [], "закупка подрядчика принята за торги на право КРТ"


def test_a_fund_mention_does_not_make_it_the_operator() -> None:
    """«Упоминание Фонда не означает, что он оператор КРТ»."""
    mention = sources.read_findings(
        [doc("Котляковская ул., вл. 8",
             "Проект решения предусматривает соглашение с Московским фондом реновации "
             "жилой застройки по адресу Котляковская ул., вл. 8.")],
        "Котляковская ул., вл. 8")
    assert mention["operator_named"] == [], "соглашение с Фондом записано оператором"
    assert mention["fund_role"], "роль Фонда не записана вовсе"


def test_confidence_follows_the_source() -> None:
    """Надёжность — три уровня, и она идёт от источника, а не от нашей уверенности."""
    official = sources.read_findings(
        [doc("Оператор КРТ на Котляковской, вл. 8",
             "Оператором КРТ на Котляковской ул., вл. 8 выступает Московский фонд реновации.",
             domain="mos.ru")],
        "Котляковская ул., вл. 8")
    trade = sources.read_findings(
        [doc("Оператор КРТ на Котляковской, вл. 8",
             "Оператором КРТ на Котляковской ул., вл. 8 выступает Московский фонд реновации.",
             domain="erzrf.ru")],
        "Котляковская ул., вл. 8")
    assert official["confidence"] == "высокая", official["confidence"]
    assert trade["confidence"] == "средняя", trade["confidence"]
    empty = sources.read_findings([], "Котляковская ул., вл. 8")
    assert empty["confidence"] == "ограниченная"


def test_nothing_found_is_not_proof_of_absence() -> None:
    empty = sources.read_findings([], "Шипиловский пр-д, вл. 55")
    assert empty["taken"] is False
    assert empty["not_found_note"], "«не найдено» не объяснено — читается как «нет»"
