"""Получателя переданных метров модель не знает — и не называет.

Механизм зачёта писался под Подмосковье, где метры уходят муниципалитету; по
КРТ их забирает оператор или Фонд реновации; по сделке метрами платят продавцу
участка или соинвестору — «Передано городу или продавцу / инвестору»
(владелец, 13.09.2026). Поля под получателя нет и быть не может: это условие
соглашения, а не расчёт. Названный город там, где его нет, читается как факт
сделки, а не как наше умолчание.

Исключение названо здесь же и проверяется отдельно: соцобъект и переданный ФОК
уходят ГОРОДУ по решению владельца (05.09.2026) — там получатель известен, и
нейтральная подпись была бы потерей, а не честностью. Запрещается МЕСТО, а не
слово: проверка перечисляет разрешённые места прямо в себе, иначе её чинят
обходом, а обход выглядит правкой.
"""

from __future__ import annotations

import copy
import io
import pathlib
import re

import pytest

import main_legacy as core
import developaid_v2_form as v2form

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _page_text() -> str:
    return core.PAGE


def test_the_word_is_declared_once_in_the_engine():
    """Слово одно, и живёт оно в движке — копию негде обновлять."""
    assert core.TRANSFER_WORD == "Передаётся"
    assert core.TRANSFER_NOTE_WORD == "передано"
    for word in (core.TRANSFER_WORD, core.TRANSFER_NOTE_WORD):
        assert "город" not in word.lower(), f"подпись называет получателя: {word}"
    # Возможные получатели названы там, где человек вписывает число, — и город
    # среди них, а не вместо них.
    note = core.TRANSFER_RECIPIENT_NOTE.lower()
    for who in ("город", "муниципалитет", "продавец участка", "соинвестор"):
        assert who in note, f"в перечне получателей нет «{who}»: {note}"


def test_the_page_carries_the_word_from_the_engine():
    """На странице копии слова нет: она получает его плейсхолдером."""
    page = _page_text()
    assert core.TRANSFER_LABELS_PLACEHOLDER not in page, "плейсхолдер не подставлен"
    assert f'"word": "{core.TRANSFER_WORD}"' in page or \
           f'"word":"{core.TRANSFER_WORD}"' in page, "слово не доехало на страницу"


def test_the_v2_form_takes_the_label_from_the_engine():
    """Форма /v2 своей подписи не держит — третья копия разошлась бы молча."""
    form = v2form.form_description(core)
    tep = [block for block in form["blocks"] if block.get("kind") == "tep"]
    assert tep, "блока ТЭП в форме нет"
    seen = 0
    for row in tep[0]["rows"]:
        for field in row["fields"]:
            if field["key"] != "transfer":
                continue
            seen += 1
            assert field["label"] == core.TRANSFER_WORD, field["label"]
            assert "город" not in field["label"].lower()
    assert seen, "поля передаваемой площади в форме нет"


def _transfer_tep() -> dict:
    tep = copy.deepcopy(core.TEP_DEFAULT)
    tep["apartments"]["transfer"] = 5000.0
    return tep


def test_the_report_table_names_the_metres_without_a_recipient():
    """Отчёт печатает «передано N м²» и молчит о том, кому: мы не знаем."""
    pytest.importorskip("reportlab", reason="reportlab нужен только для PDF")
    from market_search.krt_requirements import pdf_text

    inputs = dict(core.DEFAULT_INPUTS)
    tep = _transfer_tep()
    bundle = core._run_authoritative_model(inputs, tep, [], {})
    data = core._build_developaid_pdf({
        "result": bundle["consolidated"], "project_name": "Передача",
        "inputs": inputs, "tep": tep,
    })
    text = pdf_text(data)
    assert f"{core.TRANSFER_WORD}, м²" in text, "колонка переданного не напечатана"
    # Отчёт носят в банк: «городу» там — утверждение о сделке.
    assert "городу" not in text, "отчёт назвал получателя, которого мы не знаем"
    assert "продавец участка или соинвестор" in text, (
        "перечень получателей не напечатан — молчание читается как «городу»")


# Места, где получатель ИЗВЕСТЕН и потому назван. Список здесь, а не в коде:
# запрещают место, а не слово, и исключение обязано стоять в самой проверке.
_ALLOWED = (
    # ФОК уходит городу или продаётся — признак объекта, решение владельца
    # 05.09.2026. Слово стоит и в книге (`_V4_SPORTS_TRANSFER_WORD`), и
    # вариантом выпадающего списка в `FIELD_GROUPS`.
    "_V4_SPORTS_TRANSFER_WORD",
    '["transfer", "Передаётся городу"]',
    "'transfer', 'Передаётся городу'",
)


def test_only_the_known_recipient_is_named_in_the_engine():
    """«Передаётся городу» осталось ровно там, где получатель известен."""
    source = io.open(ROOT / "main_legacy.py", encoding="utf-8").read()
    hits = []
    for match in re.finditer(r"Передаётся городу", source):
        line_start = source.rfind("\n", 0, match.start()) + 1
        line_end = source.find("\n", match.end())
        line = source[line_start:line_end if line_end > 0 else len(source)]
        if any(mark in line for mark in _ALLOWED):
            continue
        hits.append(source.count("\n", 0, match.start()) + 1)
    assert not hits, (
        "получатель назван там, где модель его не знает; строки: "
        + ", ".join(str(n) for n in hits))


def test_the_guard_falls_on_a_saboteur():
    """Проверка, не падающая на поломке, — не проверка.

    Диверсант: колонка отчёта снова называет город. Перечень разрешённых мест
    его не покрывает, значит сторож обязан покраснеть.
    """
    source = 'tep_rows=[["Продукт","Передаётся городу, м²"]]\n'
    hits = [1 for match in re.finditer(r"Передаётся городу", source)
            if not any(mark in source for mark in _ALLOWED)]
    assert hits, "сторож не увидел бы возвращённого получателя"


def test_the_money_does_not_move_with_the_wording():
    """Правка — про подпись. Зачёт перед получателем остаётся своим полем.

    Сумму зачёта мы не считаем по цене продажи: получатель засчитывает по
    своей оценке, она из соглашения (правило 19.08.2026).
    """
    assert "vri_transfer_offset_mln" in core.DEFAULT_INPUTS
    inputs = dict(core.DEFAULT_INPUTS)
    tep = _transfer_tep()
    plain = core._run_authoritative_model(inputs, tep, [], {})["consolidated"]
    with_offset = core._run_authoritative_model(
        {**inputs, "vri_transfer_offset_mln": 500.0}, tep, [], {})["consolidated"]
    assert plain["summary"]["revenue"] == with_offset["summary"]["revenue"], (
        "зачёт двинул выручку — он должен уменьшать плату за ВРИ, а не продажи")
