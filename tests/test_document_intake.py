"""Разбор присланного документа: читает и цитирует, а не вспоминает.

Половина работы аналитика — переписать в модель числа с чужого листа: тизер
несёт кадастры и площадь, справка по участку — СПП и обязательства, решение ГЗК
приходит сканом. Ошибка переписывания на экране неотличима от расчёта.

Проверяется главное: значение без цитаты не применяется, модель не считает,
скан не выдаётся за пустой документ, а обязательство не раскладывается за
человека — «400 млн, не оплачен» это либо цена сделки, либо соцнагрузка
(владелец, 24.08.2026), и из документа выбор не следует.

Запуск: python3 -m pytest tests/test_document_intake.py -q
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import document_intake as di  # noqa: E402


def _answer(fields=(), questions=(), notes=()) -> str:
    return json.dumps({"fields": list(fields), "questions": list(questions),
                       "notes": list(notes)}, ensure_ascii=False)


# --- чтение документа -------------------------------------------------------

def test_a_scan_is_not_an_empty_document() -> None:
    """Молчаливая пустая строка выдала бы «не смогли» за «там ничего нет»."""
    import io
    from pypdf import PdfWriter
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    buffer = io.BytesIO()
    writer.write(buffer)
    # Распознавание выключено намеренно: здесь проверяется ОТКАЗ, а он
    # обязан остаться честным там, где распознавать нечем (бот живёт на
    # Render, и наш Dockerfile там не собирается). Что делает распознавание,
    # когда оно есть, держит `test_a_scan_is_read_by_recognition.py`.
    got = di.extract_text(buffer.getvalue(), "скан.pdf", recognize=False)
    assert got["scanned"] is True
    assert got["recognized"] is False
    assert "скан" in got["reason"]


def test_a_broken_file_says_why() -> None:
    got = di.extract_text(b"not a pdf at all", "мусор.pdf")
    assert got["text"] == ""
    assert got["reason"]


def test_an_empty_file_is_refused() -> None:
    assert di.extract_text(b"", "пусто.pdf")["reason"] == "пустой файл"


# --- числа так, как их пишет документ ---------------------------------------

def test_numbers_are_read_the_way_documents_write_them() -> None:
    assert di.to_number("11 385,6") == 11385.6
    assert di.to_number("400 млн. руб.") == 400.0
    assert di.to_number("0,2423 Га") == 0.2423
    assert di.to_number("14 87 Га") is not None
    assert di.to_number("не указано") is None


# --- разбор ответа модели ---------------------------------------------------

def test_a_value_without_a_quote_is_not_applied() -> None:
    """Модель, которой нечего процитировать, вспоминает, а не читает."""
    got = di.parse_intake(_answer([
        {"key": "purchase_price_mln", "value": 400, "unit": "млн ₽", "quote": ""},
    ]))
    assert got["fields"] == []
    assert any("нет цитаты" in line for line in got["dropped"])


def test_a_field_the_model_does_not_have_is_dropped_and_named() -> None:
    got = di.parse_intake(_answer([
        {"key": "infrastructure_contract_mln", "value": 400, "quote": "договор 400 млн"},
    ]))
    assert got["fields"] == []
    assert any("infrastructure_contract_mln" in line for line in got["dropped"])


def test_a_quoted_known_field_survives() -> None:
    got = di.parse_intake(_answer([
        {"key": "apartments_gns_sqm", "value": "11 385,6", "unit": "м²",
         "quote": "СПП ГНС, кв. м. – 11 385,6"},
    ]))
    assert len(got["fields"]) == 1
    assert got["fields"][0]["quote"].startswith("СПП ГНС")


def test_a_non_json_answer_is_a_refusal_not_an_empty_result() -> None:
    got = di.parse_intake("Конечно! Я посмотрел документ и вот что нашёл: …")
    assert got["fields"] == []
    assert got["reason"]


def test_silence_is_a_refusal_too() -> None:
    assert di.parse_intake("")["reason"]


def test_questions_survive_the_parse() -> None:
    got = di.parse_intake(_answer(questions=[
        {"key": "purchase_price_mln", "question": "Инфраструктурный договор 400 млн — куда?",
         "options": ["в цену сделки", "в соцнагрузку"]},
    ]))
    assert len(got["questions"]) == 1
    assert len(got["questions"][0]["options"]) == 2


# --- применение -------------------------------------------------------------

def test_nothing_is_applied_without_confirmation() -> None:
    """Разбор показывает таблицу; применение — отдельное действие."""
    extraction = di.parse_intake(_answer([
        {"key": "purchase_price_mln", "value": "400 млн", "quote": "договор 400 млн"},
    ]))
    got = di.apply_intake(extraction, {"purchase_price_mln": 0.0}, {})
    assert got["applied"] == []
    assert got["inputs"]["purchase_price_mln"] == 0.0


def test_a_confirmed_field_lands_and_says_what_changed() -> None:
    extraction = di.parse_intake(_answer([
        {"key": "purchase_price_mln", "value": "400 млн. руб.", "quote": "договор — 400 млн"},
    ]))
    got = di.apply_intake(extraction, {"purchase_price_mln": 0.0}, {},
                          accept=["purchase_price_mln"])
    assert got["inputs"]["purchase_price_mln"] == 400.0
    assert got["applied"][0]["was"] == 0.0 and got["applied"][0]["now"] == 400.0


def test_the_housing_area_lands_in_the_tep_not_in_the_inputs() -> None:
    extraction = di.parse_intake(_answer([
        {"key": "apartments_gns_sqm", "value": "11 385,6", "quote": "СПП ГНС – 11 385,6"},
    ]))
    got = di.apply_intake(extraction, {}, {"apartments": {"gns": 0.0}},
                          accept=["apartments_gns_sqm"])
    assert got["tep"]["apartments"]["gns"] == 11385.6
    assert "apartments_gns_sqm" not in got["inputs"]


def test_an_unreadable_number_is_refused_out_loud() -> None:
    extraction = di.parse_intake(_answer([
        {"key": "purchase_price_mln", "value": "по договорённости", "quote": "цена по договорённости"},
    ]))
    got = di.apply_intake(extraction, {}, {}, accept=["purchase_price_mln"])
    assert got["applied"] == []
    assert got["refused"][0]["reason"]


# --- обязательства ----------------------------------------------------------

def test_an_obligation_has_two_legal_homes_and_no_field_of_its_own() -> None:
    """Решение владельца: либо цена сделки, либо соцнагрузка. Своего поля нет."""
    keys = {row["key"] for row in di.OBLIGATION_TARGETS}
    assert keys == {"purchase_price_mln", "social_compensation_mln"}
    assert not any("infrastructure" in key for key in di.INTAKE_KEYS)


def test_the_prompt_forbids_arithmetic_and_demands_quotes() -> None:
    text = di.intake_prompt({"filename": "тизер.pdf", "pages": 3, "text": "…"})
    assert "Считать нельзя" in text
    assert "quote" in text
    assert "не угадывай" in text


def test_the_prompt_offers_both_homes_for_an_obligation() -> None:
    text = di.intake_prompt({"filename": "справка.pdf", "pages": 2, "text": "…"})
    assert "цену сделки" in text and "социальную нагрузку" in text


def test_the_field_catalogue_matches_the_engine() -> None:
    """Поле, которого нет в движке, применилось бы в пустоту."""
    import main_legacy as core
    known = set(core.DEFAULT_INPUTS) | {
        "cadastral_numbers", "site_area_ha", "apartments_gns_sqm"}
    for row in di.INTAKE_FIELDS:
        assert row["key"] in known, row["key"]


# --- поверхности: окно на сайте и бот делят один разбор -----------------------

def test_the_site_window_takes_a_document() -> None:
    """Скрепка стоит в окне Платона, а не отдельной страницей."""
    import main_legacy as core
    assert 'id="aiFile"' in core.PAGE
    assert "sendAgentDocument" in core.PAGE
    assert "/agent/document" in core.PAGE


def test_the_site_shows_the_quote_next_to_the_value() -> None:
    """Значение без источника на экране неотличимо от посчитанного."""
    import main_legacy as core
    assert "Откуда взято" in core.PAGE
    assert "Применить отмеченное" in core.PAGE


def test_the_bot_accepts_a_pdf_now() -> None:
    import main_legacy as core
    assert ".pdf" in core._TELEGRAM_DOCUMENT_EXTENSIONS
    assert hasattr(core, "_telegram_handle_intake_document")


def test_both_surfaces_use_the_same_parser() -> None:
    """Второй разбор на ту же задачу однажды разошёлся бы с первым."""
    import inspect
    import main_legacy as core
    site = inspect.getsource(core.agent_document)
    bot = inspect.getsource(core._telegram_handle_intake_document)
    for source in (site, bot):
        assert "document_intake.extract_text" in source
        assert "document_intake.parse_intake" in source
        assert "document_intake.intake_prompt" in source


def test_a_scan_is_named_a_scan_on_both_surfaces() -> None:
    """Причина доносится до человека, а признак скана гейтом не служит.

    Прежняя версия искала слово «scanned» в исходнике обеих поверхностей — то
    есть держала СПОСОБ. Способ был неверен: скан остаётся сканом и после
    распознавания, и гейт по этому признаку отказывал бы ровно там, где
    распознавание сработало. Утверждение не изменилось: скан — не пустой
    документ, и причина называется вслух.
    """
    import inspect
    import main_legacy as core
    for source in (inspect.getsource(core.agent_document),
                   inspect.getsource(core._telegram_handle_intake_document)):
        assert 'document.get("reason")' in source, "причина не доходит до человека"
        assert 'document.get("scanned")' not in source, \
            "признак скана снова служит гейтом — распознанное будет отказано"
