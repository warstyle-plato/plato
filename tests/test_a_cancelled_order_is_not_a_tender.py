"""Ось «Торги»: идёт аукцион и «объявлялись когда-то» — разные ответы.

«Почему тут в списке якобы 28 торгов хотя на вкладке торги у нас их 7»
(владелец, 14.09.2026). Замер прода настоящими функциями страницы: по фильтру
28 площадок = 11 с живым лотом + 17 только по РАСПОРЯЖЕНИЮ города, причём
привязанные распоряжения идут с 2022 года (2022 — 1, 2023 — 8, 2024 — 6,
2025 — 3, 2026 — 7). Тушино и Малино объявлены 28.11.2023, Дегунино-Лихоборы
20.01.2023 — аукционы прошли, у восьми площадок статус уже «В реализации».

И одно из этих распоряжений — № 56209 от 09.08.2023 «Об ОТМЕНЕ проведения
торгов… Волгоградский проспект, вл. 32». Оно стояло за объявленные торги, его
начальная цена годилась бы модели за цену входа, а шаг воронки говорил
«объявлено о торгах»: слово источника прочитано наоборот, и в трёх местах
сразу. Поэтому «действующее распоряжение» — один ответ на всех читателей.

Запуск: python3 -m pytest tests/test_a_cancelled_order_is_not_a_tender.py -q
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import page_blocks  # noqa: E402
from auction_search import ui  # noqa: E402
from market_search import krt_decisions, krt_registry  # noqa: E402

PAGE = ui.auctions_page(None)
AHEAD = "2031-10-09T15:00:00+03:00"
PAST = "2023-11-28T15:00:00+03:00"
HOLD = ("Распоряжение Департамента градостроительной политики города Москвы "
        "от 20 мая 2026 года № ДГП-Р-54/26 «О проведении торгов в форме аукциона "
        "на право заключения договора о комплексном развитии территории»")
CANCEL = ("Распоряжение Департамента городского имущества города Москвы "
          "от 09 августа 2023 года № 56209 «Об отмене проведения торгов в форме "
          "аукциона на право заключения договора о комплексном развитии "
          "территории нежилой застройки города Москвы № 2135, расположенной по "
          "адресу: г. Москва, Волгоградский проспект, вл. 32»")


def _answers(sites: dict[str, dict], orders: dict[str, dict]) -> dict:
    """Ответы страницы по каждой площадке — настоящими её функциями.

    Зависимости добирает общий разрешитель: перечисленные руками, они отстают
    от страницы, и падение выходит про стенд, а не про ось отбора.
    """
    # Состояние берётся у самой страницы: перечисленное руками, оно отстаёт —
    # а отстающий ключ падает как «Cannot read properties of undefined», то
    # есть про стенд, а не про ось.
    prelude = (page_blocks.page_const("state", PAGE)
               + f"\nstate.krtOrderBySite={json.dumps(orders, ensure_ascii=False)};")
    # Ось берётся СО СТРАНИЦЫ (`KRT_FILTERS`), а не пересказывается здесь:
    # пересказанная, она зеленеет на сломанном отборе — диверсия «ось снова
    # складывает два ответа» прошла мимо первой версии этой проверки.
    tail = f"""
const rows={json.dumps(sites, ensure_ascii=False)};
const stage=KRT_FILTERS.find(a=>a.key==='stage').options;
const pick=name=>{{
  const one=stage.find(o=>o.name===name);
  if(!one)throw new Error('нет варианта оси: '+name);
  return one.test;
}};
const live=pick('Идёт аукцион'), announced=pick('Торги объявлялись');
const out={{}};
for(const [slug,row] of Object.entries(rows)){{
  const x={{slug, ...row}};
  out[slug]={{
    live:!!live(x), announced:!!announced(x), on_tender:krtOnTender(x),
    order:!!krtCityOrder(x), stage:(krtStage(x)||{{}}).key,
    price:(krtAskingPrice(x)||{{}}).from||'',
  }};
}}
console.log(JSON.stringify(out));
"""
    return page_blocks.run_json(prelude, tail, page=PAGE)


def test_a_live_auction_and_an_old_announcement_are_different_answers():
    said = _answers(
        {
            "live": {"tender_lots": [{"deadline": "09.10.31 15:00",
                                      "deadline_iso": AHEAD, "price_rub": 2_403_700_000}]},
            "held": {"tender_lots": [{"deadline": "28.11.23 15:00", "deadline_iso": PAST}]},
            "announced": {},
        },
        {"announced": {"number": "ДГП-Р-54/26", "title": HOLD,
                       "action": "hold", "published_at": 1786914000,
                       "start_price_rub": 110_760_951}},
    )
    assert said["live"]["live"] and not said["live"]["announced"]
    assert said["held"]["announced"] and not said["held"]["live"]
    assert said["announced"]["announced"] and not said["announced"]["live"]
    # Обе оси вместе дают прежний союз — площадка не выпадает из отбора.
    for slug in ("live", "held", "announced"):
        assert said[slug]["on_tender"], slug


def test_a_cancelled_order_is_not_a_tender_anywhere():
    """Отмена читалась как объявление в трёх местах: ось, шаг, цена входа."""
    said = _answers(
        {"volgogradskiy": {}},
        {"volgogradskiy": {"number": "56209", "title": CANCEL, "action": "cancel",
                           "published_at": 1691653557, "start_price_rub": 1_000_000_000}},
    )
    row = said["volgogradskiy"]
    assert not row["live"] and not row["announced"], "отмена — не объявленные торги"
    assert not row["order"], "действующего распоряжения у площадки нет"
    assert not row["on_tender"]
    assert row["stage"] != "upcoming", "шаг воронки не говорит «объявлено о торгах»"
    assert not row["price"], "начальная цена отменённого аукциона в модель не идёт"


def test_the_city_document_says_what_it_does():
    assert krt_decisions.order_action(CANCEL) == "cancel"
    assert krt_decisions.order_action(HOLD) == "hold"
    # «Не поняли, что это за документ» — не «назначены торги».
    assert krt_decisions.order_action("Распоряжение об аукционе") == ""
    assert krt_decisions.parse_tender_order(
        {"id": "1", "title": CANCEL, "url": "u", "date": 1})["action"] == "cancel"


def test_the_action_is_derived_when_the_snapshot_is_read():
    """Снимок живёт сутками, а правило может измениться: вид считается при чтении.

    Заодно снимок, снятый до этой правки, получает вид документа без единого
    запроса к городу — иначе «объявлены торги» стояло бы по прежнему правилу.
    """
    old = {"orders": [{"id": "290538220", "number": "56209", "title": CANCEL},
                      {"id": "2", "number": "ДГП-Р-54/26", "title": HOLD}]}
    fresh = krt_registry.KrtRegistry._with_order_actions(old)
    assert [one["action"] for one in fresh["orders"]] == ["cancel", "hold"]
    # Исходный снимок не правится: его пишет обход, а не читатель.
    assert "action" not in old["orders"][0]


# Заголовки прода 15.09.2026, снятые с `POST /auctions/krt/tenders`: у обоих
# распоряжений номер стоит в заголовке через ПРОБЕЛ, а в записи снимка он пуст.
SPACED_HOLD = (
    "Распоряжение Департамента градостроительной политики города Москвы по "
    "основной деятельности № ДГП-Р 58/26 от 03.09.2026 О проведении торгов в "
    "форме аукциона на право заключения договора о комплексном развитии "
    "территорий нежилой застройки")


def test_the_number_is_derived_when_the_snapshot_is_read():
    """Номер — производная того же заголовка, и живёт он там же, где вид.

    0.23.76 научил читать «№ ДГП-Р 58/26» через пробел, а на проде у обоих
    таких распоряжений номер остался ПУСТЫМ: он лежал в записи снимка, а снимок
    живёт сутками. Вид пересчитывался при чтении с 14.09.2026, номер нет —
    правило, закрытое у одного поля, соседнее не защищает.
    """
    old = {"orders": [{"id": "349133220", "number": "", "title": SPACED_HOLD}]}
    fresh = krt_registry.KrtRegistry._with_order_actions(old)
    assert fresh["orders"][0]["number"] == "ДГП-Р 58/26"
    assert fresh["orders"][0]["action"] == "hold"
    # Исходный снимок не правится: его пишет обход, а не читатель.
    assert old["orders"][0]["number"] == ""


def test_a_record_without_a_title_keeps_what_was_read():
    """Пересчитывать не из чего — стирать прочитанное было бы потерей.

    «Нечем прочитать» и «прочитали и не нашли» — разные ответы, и второй
    приходит только от заголовка.
    """
    old = {"orders": [{"id": "1", "number": "ДГП-Р-54/26", "title": ""}]}
    fresh = krt_registry.KrtRegistry._with_order_actions(old)
    assert fresh["orders"][0]["number"] == "ДГП-Р-54/26"
