"""Кнопка бота по Москве спрашивает штатный калькулятор, а не формулы рядом.

Путь к калькулятору был и работал — `/cadastral/tep-server` пересылает запрос
на ядро, там headless-Chromium, — а кнопка звала `vri_tep_quick("msk", …)`
напрямую. На Render браузера нет, значит других чисел, кроме формульных, у бота
не бывало вовсе: сайт и бот отвечали по одному участку разное, и оба выглядели
верными.
"""

import main_legacy as core


def _calculator_rows(**over: str) -> list[list[str]]:
    """Таблица в том виде, в каком её отдаёт `import_cadastral_tep`."""
    values = {
        "1": "0,6510", "4": "377", "5": "163",
        "6": "22,785", "7.1": "21,418", "7.2": "1,367",
        "9.1.1": "19,276", "9.1.2": "1,230", "10": "13,920", "11": "1,230",
        "30": "17", "31": "34", "32": "5", "33": "5", "34": "3",
        "42.1": "161", "42.2": "17", "42.3": "4",
        "44": "1267,500", "54": "180,100", "55": "160,200", "56": "40,300",
    }
    values.update(over)
    return [[code, f"строка {code}", "ед.", value] for code, value in values.items()]


def _served(rows: list[list[str]] | None, calculator: bool = True) -> dict:
    return {
        "source": {"format": "Штатный калькулятор ГлавАПУ — серверный запуск"},
        "glavapu": ({"rows": rows, "calculator": calculator,
                     "parameters": [["Район", "Хамовники"]]}
                    if rows is not None else {}),
    }


def test_the_calculator_table_travels_with_its_result(monkeypatch):
    # Таблицу строит только калькулятор: не поедет с ответом — тому, кто соберёт
    # по нему карточку, придётся считать рядом свои числа.
    rows = [{"code": code, "name": name, "unit": "ед.", "value": value}
            for code, name, value in [
                ("1", "Площадь территории", "0,6510"),
                ("4", "Численность населения", "377"),
                ("10", "Площадь квартир", "13,920"),
            ]]
    captured: dict = {}

    def fake_missing(items):
        captured["asked"] = items
        return []

    monkeypatch.setattr(core, "_glavapu_missing_controls", fake_missing)
    monkeypatch.setattr(core, "_glavapu_drift_in_background", lambda *a, **k: None)
    result = core.import_cadastral_tep(core.CadastralTepRequest(
        rows=rows * 12, cadastral_analysis={"recognized": ["77:01:0004023:1000"]}))
    carried = result["glavapu"]
    assert carried["calculator"] is True
    assert carried["rows"], "таблица калькулятора должна ехать вместе с ТЭП"
    assert ["1", "Площадь территории", "ед.", "0,6510"] in carried["rows"]


def test_the_moscow_button_asks_the_server(monkeypatch):
    asked: dict = {}

    def fake_server(req):
        asked["numbers"] = req.cadastral_numbers
        return _served(_calculator_rows())

    monkeypatch.setattr(core, "cadastral_tep_server", fake_server)
    monkeypatch.setattr(core, "vri_tep_quick", lambda *a, **k: (_ for _ in ()).throw(
        AssertionError("формулы не должны звучать, пока калькулятор ответил")))
    payload = core.vri_tep_moscow("77:01:0004023:1000")
    assert asked["numbers"] == "77:01:0004023:1000"
    assert payload["file"] and payload["filename"].endswith(".xlsx")


def test_the_card_reads_the_calculator_numbers(monkeypatch):
    # Карточка читает ту же таблицу, а не считает рядом: два счёта одной
    # величины однажды разойдутся, и обе строки будут выглядеть верными.
    monkeypatch.setattr(core, "cadastral_tep_server",
                        lambda req: _served(_calculator_rows()))
    card = core.vri_tep_moscow("77:01:0004023:1000")["card"]
    assert "1 267,5 млн ₽" in card, card          # строка 44 калькулятора
    assert "380,6 млн ₽" in card, card            # 54+55+56
    assert "постоянные 161" in card and "гостевые 17" in card, card
    assert "377 чел." in card and "квартир — 163" in card, card
    assert "Хамовники" in card, card


def test_the_card_names_who_counted(monkeypatch):
    # «Методика: Формулы калькулятора ГлавАПУ» стояла у любого файла бота и
    # значила не «сорвалось», а «иначе тут не бывает».
    monkeypatch.setattr(core, "cadastral_tep_server",
                        lambda req: _served(_calculator_rows()))
    payload = core.vri_tep_moscow("77:01:0004023:1000")
    assert "Штатный калькулятор ГлавАПУ" in payload["card"]
    sheet = core._xlsx_read_tables(payload["file"])["Параметры территории"]
    method = [row for row in sheet if row and str(row[0]).strip() == "Методика"]
    assert method and "Штатный калькулятор" in str(method[0][1]), sheet


def test_formulas_stay_the_fallback(monkeypatch):
    for served in (_served(None), _served(_calculator_rows(), calculator=False)):
        monkeypatch.setattr(core, "cadastral_tep_server", lambda req, s=served: s)
        monkeypatch.setattr(core, "vri_tep_quick",
                            lambda *a, **k: {"card": "формулы", "file": b"",
                                             "filename": "f.xlsx"})
        assert core.vri_tep_moscow("77:01:0004023:1000")["card"] == "формулы"


def test_a_refusing_server_does_not_lose_the_answer(monkeypatch):
    # Ядро не ответило — человек получает прежний ответ, а не отказ кнопки.
    def boom(req):
        raise RuntimeError("ядро молчит")

    monkeypatch.setattr(core, "cadastral_tep_server", boom)
    monkeypatch.setattr(core, "vri_tep_quick",
                        lambda *a, **k: {"card": "формулы", "file": b"",
                                         "filename": "f.xlsx"})
    assert core.vri_tep_moscow("77:01:0004023:1000")["card"] == "формулы"


def test_a_non_cadastral_query_goes_straight_to_formulas(monkeypatch):
    # Спрашивать калькулятор нечем: он ходит по кадастровым номерам.
    monkeypatch.setattr(core, "cadastral_tep_server", lambda req: (
        _ for _ in ()).throw(AssertionError("калькулятор спрашивать нечем")))
    monkeypatch.setattr(core, "vri_tep_quick",
                        lambda *a, **k: {"card": "формулы", "file": b"",
                                         "filename": "f.xlsx"})
    assert core.vri_tep_moscow("Хамовники")["card"] == "формулы"


def test_the_button_itself_takes_the_served_path(monkeypatch, tmp_path):
    # Проверяется нажатие, а не строка в исходнике: строка совпадает и у
    # сломанного кода. Кнопка обязана прийти в `vri_tep_moscow` — вернётся к
    # прямым формулам, и тест это скажет.
    import main as wrapper

    monkeypatch.setattr(wrapper, "_STATE_DIR", tmp_path)
    sent: list[str] = []
    monkeypatch.setattr(wrapper, "_send_message",
                        lambda chat_id, text, *a, **k: sent.append(text))
    monkeypatch.setattr(wrapper.core, "_telegram_send_document_bytes",
                        lambda *a, **k: None)
    monkeypatch.setattr(wrapper.core, "vri_tep_quick", lambda *a, **k: (
        _ for _ in ()).throw(AssertionError("московская кнопка идёт мимо сервиса")))
    monkeypatch.setattr(wrapper.core, "vri_tep_moscow",
                        lambda query: {"card": "через сервис", "file": b"x",
                                       "filename": "f.xlsx"})
    wrapper._state_write("chat:1", {"vritep": "msk"})

    assert wrapper._vritep_handle_text(1, "77:01:0004023:1000") is True
    assert "через сервис" in sent


def test_the_region_outside_moscow_keeps_its_own_path(monkeypatch, tmp_path):
    # Подмосковья правка не касается: `mo_calculate` на ядро пересылает сам.
    import main as wrapper

    monkeypatch.setattr(wrapper, "_STATE_DIR", tmp_path)
    sent: list[str] = []
    monkeypatch.setattr(wrapper, "_send_message",
                        lambda chat_id, text, *a, **k: sent.append(text))
    monkeypatch.setattr(wrapper.core, "_telegram_send_document_bytes",
                        lambda *a, **k: None)
    monkeypatch.setattr(wrapper.core, "vri_tep_moscow", lambda query: (
        _ for _ in ()).throw(AssertionError("это не московская ветка")))
    monkeypatch.setattr(wrapper.core, "vri_tep_quick",
                        lambda *a, **k: {"card": "подмосковье", "file": b"x",
                                         "filename": "f.xlsx"})
    wrapper._state_write("chat:2", {"vritep": "mo"})

    assert wrapper._vritep_handle_text(2, "50:21:0120316:1221") is True
    assert "подмосковье" in sent
