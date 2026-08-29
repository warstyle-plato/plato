"""Бот спрашивает то, чего нельзя ни прочитать, ни посчитать.

Разбор тизера по Тимирязевской, 17 (владелец, 29.08.2026: «вот такие идиотские
вопросы задавал бот… это он должен спрашивать или считать?») выдал десять
вопросов, и семь из них — про то, что город считает сам по кадастровому номеру:
плата за смену ВРИ, места ДОО и СОШ, мощность поликлиники, машино-места. Номер
участка при этом стоял первой строкой разбора.

Вопрос, на который у нас есть источник, — это не вежливость, а работа,
возвращённая человеку, и второй ответ на один вопрос: его догадка и расчёт
калькулятора разошлись бы, и оба выглядели бы верными.

Рядом — вторая находка того же разбора: «Стоимость 1 650 000 000 ₽» ложилась в
поле, которое меряет МИЛЛИОНАМИ рублей. Единица — часть числа, и без неё это
другое число.

Запуск: python3 -m pytest tests/test_the_intake_asks_only_what_it_cannot_count.py -q
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import document_intake as di  # noqa: E402


# Ровно то, что бот прислал владельцу: четыре прочитанных поля и десять
# вопросов. Пример живой — на выдуманном эта правка выглядела бы верной и в
# сломанном виде.
TIMIRYAZEVSKAYA = {
    "fields": [
        {"key": "cadastral_numbers", "value": ["77:09:0003021:158"],
         "unit": "", "quote": "КН 77:09:0003021:158"},
        {"key": "site_area_ha", "value": "0,88", "unit": "Га",
         "quote": "Площадь 0,88 Га"},
        {"key": "purchase_price_mln", "value": "1 650 000 000", "unit": "₽",
         "quote": "Стоимость 1 650 000 000 ₽"},
        {"key": "apartments_gns_sqm", "value": "31 000", "unit": "м²",
         "quote": "СПП в ГНС (предварительно) 31 000 м²"},
    ],
    "questions": [
        {"key": "", "question": "Как учитывать обязательство «Передача 1500 м²»: "
                                "в цене сделки или в социальной нагрузке?",
         "options": ["Включить в цену сделки", "Включить в социальную нагрузку"]},
        {"key": "land_rights_cost_mln",
         "question": "Каков размер платы за смену ВРИ? В документе сумма не указана."},
        {"key": "resettlement_cost_mln",
         "question": "Есть ли обязательства по расселению и какова их стоимость?"},
        {"key": "demolition_area_sqm",
         "question": "Есть ли сносимые объекты и какова их площадь?"},
        {"key": "offices_gba_sqm", "question": "Какова общая площадь офисов?"},
        {"key": "retail_gba_sqm", "question": "Какова общая площадь ТЦ / ОСЗ?"},
        {"key": "underground_manual_spaces",
         "question": "Сколько предусмотрено подземных машино-мест?"},
        {"key": "kindergarten_places", "question": "Сколько мест предусмотрено в ДОО?"},
        {"key": "school_places", "question": "Сколько мест предусмотрено в СОШ?"},
        {"key": "clinic_capacity",
         "question": "Какова мощность поликлиники в посещениях за смену?"},
    ],
    "notes": ["Структура сделки: «Продажа долей ЮЛ»"],
}


def parsed() -> dict:
    return di.parse_intake(json.dumps(TIMIRYAZEVSKAYA, ensure_ascii=False))


def test_the_city_is_not_asked_what_the_city_computes() -> None:
    got = parsed()
    asked = [item["question"] for item in got["questions"]]
    assert len(asked) == 3, f"вопросов должно остаться три, а не {len(asked)}: {asked}"
    assert any("Передача 1500" in text for text in asked), \
        "куда отнести обязательство — настоящий вопрос, его снимать нельзя"
    assert any("расселени" in text.lower() for text in asked)
    assert any("сносим" in text.lower() for text in asked)


def test_the_removed_questions_are_named_not_dropped() -> None:
    """Молча снятый вопрос читается как «об этом не подумали»."""
    got = parsed()
    removed = {item["key"]: item for item in got["not_asked"]}
    for key in ("land_rights_cost_mln", "kindergarten_places", "school_places",
                "clinic_capacity", "underground_manual_spaces"):
        assert key in removed, f"вопрос про {key} исчез бесследно"
        assert "калькулятор" in removed[key]["why"]
    for key in ("offices_gba_sqm", "retail_gba_sqm"):
        assert removed[key]["origin"] == "project"
        assert "нулём" in removed[key]["why"], "умолчание называется предпосылкой"


def test_a_question_without_a_key_is_recognised_by_its_words() -> None:
    """Модель ставит `key` пустым чаще, чем хотелось бы."""
    got = di.parse_intake(json.dumps({"fields": [], "questions": [
        {"key": "", "question": "Каков размер платы за смену ВРИ?"},
        {"key": "", "question": "Сколько мест предусмотрено в СОШ?"},
        {"key": "", "question": "Какова цена входа в проект?"},
    ]}, ensure_ascii=False))
    assert len(got["questions"]) == 1
    assert "цена входа" in got["questions"][0]["question"]
    assert len(got["not_asked"]) == 2


def test_the_prompt_forbids_asking_what_we_count() -> None:
    text = di.intake_prompt({"filename": "тизер.pdf", "pages": 3, "text": "…"})
    assert "НЕ ЗАДАВАЙ вопросов" in text
    for label in ("Плата за смену ВРИ", "ДОО — мест", "Машино-места подземные"):
        assert label in text
    # А то, что спрашивать НАДО, в запрет не попало.
    forbidden = text[text.index("НЕ ЗАДАВАЙ вопросов"):]
    assert "Расселение" not in forbidden.split("Спросить о них")[0]


def test_the_unit_is_part_of_the_number() -> None:
    """«1 650 000 000 ₽» в поле «млн ₽» — это 1650, а не 1,65 квадриллиона."""
    got = parsed()
    applied = di.apply_intake(got, {}, {"apartments": {"gns": 0.0}},
                              accept=["purchase_price_mln", "site_area_ha",
                                      "apartments_gns_sqm"])
    assert applied["inputs"]["purchase_price_mln"] == 1650.0
    assert applied["inputs"]["site_area_ha"] == 0.88
    assert applied["tep"]["apartments"]["gns"] == 31000.0
    # На экране видно, как было написано и во что превратилось: молчаливый
    # перевод единиц неотличим от ошибки переписывания.
    price = next(row for row in applied["applied"] if row["key"] == "purchase_price_mln")
    assert price["as_written"] == "1 650 000 000 ₽"
    assert price["label"] == "Цена сделки / цена входа"


def test_money_without_a_unit_is_refused_with_a_reason() -> None:
    """Разница между «1650 ₽» и «1650 млн ₽» — миллион раз, и угадывать её нельзя."""
    got = di.parse_intake(json.dumps({"fields": [
        {"key": "purchase_price_mln", "value": "1650", "unit": "",
         "quote": "Стоимость 1650"}]}, ensure_ascii=False))
    applied = di.apply_intake(got, {}, {}, accept=["purchase_price_mln"])
    assert not applied["applied"]
    assert "purchase_price_mln" not in applied["inputs"]
    assert "единица не названа" in applied["refused"][0]["reason"]


def test_the_bot_hands_the_parcel_to_the_calculator() -> None:
    """Номер участка из документа уходит туда же, куда присланный сообщением."""
    import main_legacy as core

    assert core._intake_cadastral_numbers(parsed()) == ["77:09:0003021:158"]
    body = (ROOT / "main_legacy.py").read_text(encoding="utf-8")
    start = body.index("def _telegram_handle_intake_document(")
    intake = body[start:body.index("\ndef _intake_cadastral_numbers(")]
    assert "_telegram_handle_cadastral_numbers(chat_id, numbers)" in intake, \
        "участок прочитан и брошен: считать его никто не пошёл"
    # И имя поля на экране, а не ключ латиницей.
    assert "document_intake.INTAKE_LABELS" in intake
    assert 'html.escape(item["key"])' not in intake
