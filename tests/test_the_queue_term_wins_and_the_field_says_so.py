"""Срок строительства при очередности задаёт очередь, и поле проекта это говорит.

Владелец 07.09.2026: «у нас есть срок строительства в Вводных и в очередности —
какой будет срок, если эти сроки противоречат друг другу? может если включат
очередность эти поля становятся не активными?»

Замер ответил так. Противоречия в СЧЁТЕ нет: обёртка очередей пишет
`p_inputs["construction_months"] = cfg.get("construction_months", проектный)`,
то есть срок очереди сильнее, а проектный читается ТОЛЬКО когда очередь своего
не назвала. Но страница называет его всегда — и до этой правки заводила очередь
УМОЛЧАНИЕМ движка (24), а не тем, что человек вписал: вписал 36, включил
очерёдность, и все очереди строились 24, при том что «36» осталось на экране и
выглядело посчитанным. Это ровно «умолчание, которое можно переписать, — уже не
умолчание», только с другой стороны: переписать было нельзя, а выглядело можно.

Отсюда два утверждения и две проверки к ним. Очередь заводится вписанным
сроком — гоняется настоящий `makeDefaultPhasing` из `PAGE` через node. И поле
проекта при очередности гасится, называя сроки очередей: гашение без ответа
«а где тогда» отвечает только половину. Механизм для этого уже был — так при
очередности гасятся даты соцобъектов, — и срок в него просто не входил.

Остальные вводные при очередности НЕ мертвы, и это тоже измерено: обёртка
переписывает 38 полей, но все прочие читаются базой — цены и ставки
себестоимости множатся на инфляцию очереди, покупка, ВРИ, свои средства и
соцкомпенсация делятся долями, `project_start` служит началом первой очереди и
точкой отсчёта остальных, места ДОО и СОШ доезжают в свою очередь целиком.
Гасить их значило бы спрятать работающую вводную.

Запуск: python3 -m pytest tests/test_the_queue_term_wins_and_the_field_says_so.py -q
"""

from __future__ import annotations

import copy
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import main_legacy as core  # noqa: E402

from test_inputs_open_on_the_first_group import page_const, page_function, render  # noqa: E402


def _phase_terms(project_months: float, phases: list[dict]) -> list:
    """Что движок реально посчитал каждой очереди — через перехват вводных."""
    seen: list[dict] = []
    original = core.calculate

    def spy(request):
        seen.append(copy.deepcopy(request.inputs))
        return original(request)

    inputs = copy.deepcopy(core.DEFAULT_INPUTS)
    inputs["construction_months"] = project_months
    phasing = {"enabled": True, "phase_count": len(phases),
               "phase_gap_months": 12, "phases": copy.deepcopy(phases)}
    core.calculate = spy
    try:
        core._calculate_phased_once(core.PhasedCalcRequest(
            inputs=inputs, tep=copy.deepcopy(core.TEP_DEFAULT), rates=[], phasing=phasing))
    finally:
        core.calculate = original
    return [item.get("construction_months") for item in seen]


def test_the_queue_term_beats_the_project_one() -> None:
    """Назвала свой — считается её, и проектное число в счёт не идёт."""
    got = _phase_terms(24, [{"name": "О1", "start_offset_months": 0, "construction_months": 36},
                            {"name": "О2", "start_offset_months": 12, "construction_months": 18}])
    assert got == [36, 18], got


def test_the_project_term_is_only_a_fallback() -> None:
    """Не назвала — берётся проектный: это его единственная работа при очередности."""
    got = _phase_terms(30, [{"name": "О1", "start_offset_months": 0},
                            {"name": "О2", "start_offset_months": 12}])
    assert got == [30, 30], got


def _seeded(entered) -> list:
    """Настоящий `makeDefaultPhasing` из `PAGE`, а не его пересказ."""
    node = shutil.which("node")
    if not node:  # pragma: no cover - в песочнице без node
        pytest.skip("node недоступен")
    inputs = {} if entered is None else {"construction_months": entered}
    script = "\n".join([
        page_const("INPUT_DEFAULT"),
        "function phaseWeightPreset(n){return Array.from({length:n},()=>100/n)}",
        "function frontLoadedPreset(n,k){return Array.from({length:n},()=>100/n)}",
        page_function("defaultConstructionMonths"),
        page_function("makeDefaultPhasing"),
        f"const inputs=Object.assign(structuredClone(INPUT_DEFAULT),{json.dumps(inputs)});",
        "if(%s)delete inputs.construction_months;" % ("true" if entered is None else "false"),
        "console.log(JSON.stringify(makeDefaultPhasing(3).phases.map(p=>p.construction_months)));",
    ])
    done = subprocess.run([node, "-e", script], capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def test_a_new_queue_takes_the_term_the_person_entered() -> None:
    """Вписал 36 — очереди строятся 36, а не умолчанием движка."""
    assert _seeded(36) == [36, 36, 36], _seeded(36)


def test_an_empty_field_falls_back_to_the_default() -> None:
    """Пустое поле — это «не задано», и тогда работает умолчание."""
    fallback = float(core.DEFAULT_INPUTS.get("construction_months") or 24)
    assert _seeded(None) == [fallback] * 3, _seeded(None)


# «Срок строительства» на странице не один: свой есть у офисов, ТЦ, ФОКа и
# наземного паркинга. Ищется тот, что в группе «Сделка и сроки», — иначе
# проверка молча смотрела бы на чужое поле.
_FIELD_IN_DEAL_GROUP = """
function fieldsOf(node,out){
 for(const child of node.children){
  if(child.className==='field')out.push(child);
  fieldsOf(child,out);
 }
 return out;
}
const deal=created.filter(n=>n.tagName==='details'&&n.dataset.group==='Сделка и сроки')[0];
if(!deal)throw new Error('на странице нет группы «Сделка и сроки»');
const found=fieldsOf(deal,[]).filter(n=>/Срок строительства/.test(n.innerHTML))
  .map(n=>n.innerHTML+(n.children.map(c=>c.id||'').join('')));
console.log(JSON.stringify(found));
"""


def _term_field_html(phasing: dict | None) -> str:
    found = render({"construction_months": 36}, tail=_FIELD_IN_DEAL_GROUP, phasing=phasing)
    assert len(found) == 1, f"поля срока строительства в «Сделке и сроках» не одно: {len(found)}"
    return found[0]


def test_the_project_field_is_live_without_phasing() -> None:
    """Без очередности поле обычное: гасить нечего, читает его движок."""
    html = _term_field_html(None)
    assert "f_construction_months" in html, html
    assert "Очередность" not in html


def test_the_project_field_goes_quiet_under_phasing_and_says_where() -> None:
    """При очередности — не поле, а ответ: где задаётся и сколько там сейчас."""
    phasing = {"enabled": True, "phase_count": 2, "phases": [
        {"name": "О1", "construction_months": 36},
        {"name": "О2", "construction_months": 18}]}
    html = _term_field_html(phasing)
    assert "f_construction_months" not in html, "поле осталось правимым при очередности: " + html
    assert "Очередность" in html, html
    for expected in ("О1 — 36", "О2 — 18"):
        assert expected in html, f"срок очереди не назван ({expected}): {html}"


def test_one_queue_leaves_the_project_field_alone() -> None:
    """Очередь одна — движок считает как обычный проект и читает это поле."""
    html = _term_field_html({"enabled": True, "phase_count": 1,
                             "phases": [{"name": "О1", "construction_months": 36}]})
    assert "f_construction_months" in html, html
