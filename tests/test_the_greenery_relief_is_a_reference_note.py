"""Смягчение озеленения — справка у числа, а не множитель в расчёте.

2260-ПП от 18.08.2026 разрешает не добирать норму озеленения метрами, а
платить деньгами в бюджет — по решению ГЗК через инфраструктурный договор:
−15% при ОТОП ≥5 га / ООПТ / ООЗТ в радиусе 500 м, а внутри Садового кольца
вплоть до нуля. Считать это модель НЕ должна (решение владельца, 13.09.2026:
«это зависит от решения мэрии, так что мы же можем просто указать на такую
возможность справочно»): решение принимает город по конкретной площадке, а
порядок расчёта самой компенсации определит акт ДГП, которого нет.

Отсюда две половины, и одна без другой врёт. Расчёт платит полную ставку —
это проверяется числом, а не обещанием. А возможность названа справкой, и
стоит она у ПЛОЩАДИ двора: норматив м²/чел. с 14.09.2026 правится в
«Настройках класса» (решение владельца), и площадь осталась единственным
полем «Вводных», куда согласованное снижение вносят. Переехать справка была
обязана вместе с ним: оставшись у скрытого поля, она не нарисовалась бы
вовсе — молча, потому что в исходнике она при этом на месте. Первой строкой
справка говорит, ЧЬЁ число считает двор: наши 11/15/20 м²/чел. — стоимость
двора по классу (решение владельца, 12.09.2026), а не норма города, и одно
под другим читалось бы как ссылка на акт там, где стоит экспертная ставка.

Проверяется отрисовкой на настоящем адресе: искомый текст присутствует в
исходнике и у страницы, которая его не показывает. Рядом стоят предохранители
— справка обязана исчезать в Подмосковье (2152-ПП другим регионам не писан) и
обязана стоять НИЖЕ поля: подпись над вводом приклеивается к подписи поля, и
это уже стоило захода 13.09.2026 на нормативе паркинга.

Запуск: python3 -m pytest tests/test_the_greenery_relief_is_a_reference_note.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import browser  # noqa: E402
import main_legacy as core  # noqa: E402

FIELD = "f_landscaping_area_sqm"

PROBE = """(field)=>{
  const read=(region)=>{
    inputs.vri_region=region;
    renderInputs();
    const el=document.getElementById(field);
    if(!el)return {field:false};
    const wrap=el.closest('.field');
    const note=wrap?wrap.querySelector('.note'):null;
    if(!note)return {field:true, note:false};
    const a=el.getBoundingClientRect(), b=note.getBoundingClientRect();
    return {field:true, note:true, text:note.textContent,
            fieldBottom:a.bottom, noteTop:b.top};
  };
  openTab('inputs');
  const msk=read('msk');
  const mo=read('mo');
  read('msk');
  return {msk, mo};
}"""


@pytest.fixture(scope="module")
def seen():
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright

    path = browser.chromium_or_skip()
    with browser.serve(core.app, 18102) as base, sync_playwright() as pw:
        with pw.chromium.launch(executable_path=str(path)) as engine:
            page = engine.new_page(viewport={"width": 1440, "height": 900})
            page.goto(base, wait_until="domcontentloaded")
            page.wait_for_timeout(1200)
            got = page.evaluate(PROBE, FIELD)
            page.close()
    return got


def test_the_note_reaches_the_screen(seen):
    assert seen["msk"]["field"], "поля площади двора на странице нет"
    assert seen["msk"]["note"], "справки о смягчении у поля нет — она есть только в исходнике"


def test_the_note_says_whose_number_stands_in_the_field(seen):
    """Наша ставка — не норма города, и это первое, что должна сказать справка."""
    text = seen["msk"]["text"]
    assert "не норма города" in text, \
        f"справка не отделяет нашу ставку от городской нормы: {text[:200]}"
    assert "2152-ПП" in text and "2260-ПП" in text, \
        "справка не называет акты, на которые ссылается"


def test_the_note_says_where_the_norm_is_edited(seen):
    """Норматив уехал в настройки класса — справка обязана сказать куда.

    Утверждение «поле выше — наша ставка» после переезда указывало бы на
    пустое место: поля норматива во «Вводных» больше нет. Отказ, не
    сказавший «а где», отвечает половину — это уже стоило захода на сроке
    строительства при очередности (владелец, 07.09.2026).
    """
    text = seen["msk"]["text"]
    assert "Настройках класса" in text, \
        f"справка не говорит, где правится норматив двора: {text[:200]}"


def test_the_note_names_the_relief_and_says_the_model_ignores_it(seen):
    text = seen["msk"]["text"]
    for word in ("−15%", "Садового кольца", "ГЗК"):
        assert word in text, f"справка не называет «{word}»: {text[:300]}"
    assert "полную ставку" in text, \
        "справка не говорит, что модель платит полную ставку, — читается как учтённое"


def test_the_note_stands_under_the_field(seen):
    """Подпись над вводом читается как утверждение о подписи поля."""
    got = seen["msk"]
    assert got["noteTop"] >= got["fieldBottom"] - 1, (
        f"справка стоит выше поля: верх справки {got['noteTop']:.0f}, "
        f"низ поля {got['fieldBottom']:.0f}")


def test_the_note_is_gone_outside_moscow(seen):
    """Предохранитель: 2152-ПП Подмосковью не писан, и справка там неверна."""
    assert seen["mo"]["field"], "в Подмосковье поля площади двора нет вовсе — меряем не то"
    assert not seen["mo"]["note"], \
        "справка о московском акте показана в Подмосковье"


def test_the_model_still_pays_the_full_rate():
    """Справка справкой, а расчёт смягчения не применяет — это меряется числом."""
    tep = {"apartments": {"saleable": 30_000.0}}
    inputs = {"vri_region": "msk", "landscaping_area_per_person_sqm": 5}
    population, _ = core.project_population(tep, "msk")
    assert population > 0, "населения нет — смягчать нечего, проверка пуста"
    area, basis = core.landscaping_area(inputs, tep)
    assert area == pytest.approx(5 * population), (
        f"площадь двора {area:g} м² не равна полной норме {5 * population:g} — "
        f"где-то применено смягчение: {basis}")
