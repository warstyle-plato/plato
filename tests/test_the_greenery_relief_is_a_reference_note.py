"""Нормы озеленения города — справка в «Настройках класса», а не в расчёте.

2260-ПП от 18.08.2026 разрешает не добирать норму озеленения метрами, а
платить деньгами в бюджет — по решению ГЗК через инфраструктурный договор:
−15% при ОТОП ≥5 га / ООПТ / ООЗТ в радиусе 500 м, а внутри Садового кольца
вплоть до нуля. Считать это модель НЕ должна (решение владельца, 13.09.2026:
«это зависит от решения мэрии, так что мы же можем просто указать на такую
возможность справочно»): решение принимает город по конкретной площадке, а
порядок расчёта самой компенсации определит акт ДГП, которого нет.

Отсюда две половины, и одна без другой врёт. Расчёт платит полную ставку —
это проверяется числом, а не обещанием. А возможность названа справкой, и
живёт она РЯДОМ С НОРМАТИВОМ, который объясняет, то есть в окне «Настройки
класса» (владелец, 16.09.2026: «нормы логично вставить в настройки класса»).
Во «Вводных» её больше нет вовсе: там считают деньги, и справка о норме
города читалась там как часть расчёта.

Проверяется отрисовкой: искомый текст присутствует в исходнике и у страницы,
которая его не показывает. Рядом предохранитель — справка обязана исчезать в
Подмосковье: 2152-ПП другим регионам не писан, и там она была бы неправдой.

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

PORT = 18957

PROBE = """()=>{
  const read=(region)=>{
    inputs.vri_region=region;
    renderInputs();
    renderClassDialog();
    const body=document.getElementById('classDialogBody');
    const folds=body?[...body.querySelectorAll('details')]:[];
    const form=document.getElementById('inputs');
    return {
      inClass: folds.map(one=>one.textContent).join(' '),
      folds: folds.length,
      summary: folds.length?folds[0].querySelector('summary').textContent:'',
      inForm: (form?form.textContent:'').includes('2152-ПП'),
    };
  };
  openTab('inputs');
  const msk=read('msk'), mo=read('mo');
  read('msk');
  return {msk, mo};
}"""


@pytest.fixture(scope="module")
def seen():
    chrome = browser.chromium_or_skip()
    from playwright.sync_api import sync_playwright

    import main as wrapper

    with browser.serve(wrapper.app, PORT) as root:
        with sync_playwright() as pw:
            chromium = pw.chromium.launch(executable_path=str(chrome))
            page = chromium.new_page()
            errors: list[str] = []
            page.on("pageerror", lambda exc: errors.append(str(exc)))
            page.goto(root, wait_until="networkidle")
            out = page.evaluate(PROBE)
            out["errors"] = errors
            chromium.close()
    return out


def test_the_page_draws_without_errors(seen):
    assert not seen["errors"], seen["errors"]


def test_the_note_lives_in_the_class_settings(seen):
    """Справка стоит там, где правят норматив, который она объясняет."""
    assert seen["msk"]["folds"] >= 1, "в окне классов нет ни одной складки"
    assert "Нормы озеленения города" in seen["msk"]["summary"], seen["msk"]["summary"]
    assert "2152-ПП" in seen["msk"]["inClass"]


def test_the_note_left_the_inputs(seen):
    """Во «Вводных» её нет: там считают деньги, а не читают нормы города."""
    assert seen["msk"]["inForm"] is False


def test_the_note_names_the_relief_and_says_the_model_ignores_it(seen):
    """Названа и возможность, и то, что модель её не считает."""
    text = seen["msk"]["inClass"]
    assert "2260-ПП" in text
    assert "ГЗК" in text
    assert "полную ставку" in text and "не считает" in text


def test_the_note_says_whose_number_the_norm_is(seen):
    """Первой строкой — чьё число: наша ставка площади, а не норма города."""
    assert "НАША ставка площади" in seen["msk"]["inClass"], seen["msk"]["inClass"][:200]


def test_the_note_is_gone_outside_moscow(seen):
    """Предохранитель: 2152-ПП Подмосковью не писан."""
    assert seen["mo"]["folds"] == 0, seen["mo"]["summary"]


def test_the_model_still_pays_the_full_rate():
    """Вторая половина: расчёт платит полную ставку — это число, а не обещание."""
    inputs = dict(core.DEFAULT_INPUTS)
    inputs["landscaping_gns_th_per_sqm"] = 0
    money, basis = core.landscaping_cost(inputs, core.TEP_DEFAULT,
                                         core.project_above_gns(core.TEP_DEFAULT))
    area, _ = core.landscaping_area(inputs, core.TEP_DEFAULT)
    rate = float(inputs["landscaping_th_per_sqm"])
    assert money == pytest.approx(area * rate * 1000, rel=1e-9), basis
