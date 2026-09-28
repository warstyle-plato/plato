"""Отчёт о пересчёте говорит о ПОЛЯХ, а не о намерении.

«Поменял в ТЭП пропорцию офисника с 50 % от общей до 60 % и высветилась эта
куча изменений, которые по идее не произошли, так как ВРИ вообще сведён к 0,
так как это КРТ; с чего вдруг поменялось население, тоже не ясно» (владелец,
26.09.2026).

На экране под заголовком «Подставлено:» стояло «Плата за ВРИ: было 18 265,9 →
стало 10 166,6», а ниже — «Не тронуто — вписано требованием КРТ: … плата за
ВРИ». Обе строки про одно поле, и они противоречат друг другу: список строился
ДО подстановки, а подстановка запертое требованием КРТ не трогала.

Второе: «было» означало ВЫГРУЗКУ ГлавАПУ, а не состояние до правки. Доля
офисов население не двигает вовсе — оно считается от площади квартир, — но
строка со стрелкой читалась как следствие правки.

Проверка гоняет НАСТОЯЩИЙ `recalcFromTep` со страницы через node и читает то,
что окажется в плашке. Заглушками стоит только то, к содержанию отчёта
отношения не имеющее: сеть, отрисовка, расчёт. Структурная сверка порядка
строк («список ниже подстановки») такого не доказывает: переставить литерал
можно, не меняя того, что человек прочитает.

Запуск: python3 -m pytest tests/test_the_recalc_report_speaks_about_the_fields.py -q
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import main_legacy as core  # noqa: E402
import page_blocks  # noqa: E402

NUM = "const num=v=>Number(v||0).toLocaleString('ru-RU',{maximumFractionDigits:1});"

# Поле заперто требованием КРТ, ВРИ сведена к нулю, места вбиты руками — то
# самое состояние, на котором снят экран владельца.
KRT = {"social_area_source": "manual", "land_rights_cost_mln": 0,
       "kindergarten_places": 350, "school_places": 1000, "clinic_capacity": 120,
       "social_compensation_mln": 900, "underground_manual_spaces": 1210,
       "_glavapu_import": {"normalized": {"change_vri_mln": 18265.9}}}

ANSWER = {"vri_total_mln": 10166.6, "compensation_mln": 1500.2,
          "land_right_factor": 1,
          "places": {"kindergarten": 412, "school": 1120, "clinic": 130},
          "parking": {"total": 1310, "permanent": 1100, "guest": 110,
                      "attached": 100},
          "population": 4137,
          "baseline": {"parking_total": 1310, "population": 4137,
                       "vri_mln": 18265.9, "compensation_mln": 1500.2},
          "warnings": [], "self_check": {"matches_baseline": True}}

TEP = {"apartments": {"saleable": 80000, "gns": 130716, "units": 1800},
       "ground_commercial": {"gns": 1000, "total_area": 1200},
       "offices": {"gns": 5000, "total_area": 6000},
       "standalone_retail": {"gns": 0, "total_area": 0},
       "underground_parking": {"units": 1210}}


def _stand() -> str:
    """Настоящие куски страницы плюс заглушки того, что к отчёту не относится."""
    return "\n".join([
        NUM,
        page_blocks.function("escapeHtml"),
        "let inputs={}, tep={}, cadastralAnalysis={};",
        "let noteHtml='';",
        "const document={getElementById:()=>({style:{},"
        "set innerHTML(v){noteHtml=v},get innerHTML(){return noteHtml}})};",
        # Отрисовка, пересчёт и штамп основания к содержанию плашки отношения
        # не имеют; сеть подменяется в самой проверке — её ответ и есть вход.
        "function stampSocialBasis(){}",
        # Настоящий `syncTep` пересобирает весь ТЭП и к отчёту отношения не
        # имеет; из него нужен один перенос — вводные машино-места в строку
        # гаража. Без него строка «машино-места в ТЭП» не двигалась бы никогда,
        # и проверка «изменилось → сказано» проходила бы на заглушке.
        "function syncTep(){tep.underground_parking.units="
        "Number(inputs.underground_manual_spaces||0)}",
        "function renderInputs(){}",
        "function renderTep(){}",
        "function calculate(){}",
        "async function rescaleSocialFromTep(){return false}",
        "async function recalcFromTepByNorms(){}",
        "function nonresidentialAboveSqm(){return 0}",
        # Суммы «офисы и ТЦ» читают реестр: второй офисник той же семьи.
        page_blocks.object_roster(),
        page_blocks.function("standaloneProductSum"),
        page_blocks.krt_lock(),
        page_blocks.function("recalcFromTep"),
    ])


def _run(inputs: dict, answer: dict, tep: dict | None = None) -> dict:
    script = _stand() + f"""
globalThis.fetch=async()=>({{ok:true,json:async()=>({json.dumps(answer)})}});
inputs={json.dumps(inputs)};
tep={json.dumps(tep or TEP)};
(async()=>{{ await recalcFromTep({{silent:true}});
 console.log(JSON.stringify({{note:noteHtml, fields:inputs}})); }})();
"""
    done = subprocess.run(["node", "-e", script], capture_output=True, text=True,
                          timeout=60)
    assert done.returncode == 0, done.stderr[-2000:]
    got = json.loads(done.stdout)
    # Плашка читается человеком, а не разметкой: сравнивать надо текст.
    text = re.sub(r"<[^>]+>", "\n", got["note"])
    got["text"] = text.replace(" ", " ")
    got["lines"] = [one.strip() for one in got["text"].split("\n") if one.strip()]
    return got


def _line(got: dict, head: str) -> str:
    """Строка плашки, начинающаяся с этого имени.

    Первая строка списка склеена с заголовком — он печатается перед ней без
    разрыва, — поэтому ищется вхождение, а отрезается от имени.
    """
    for one in got["lines"]:
        if head in one:
            return one[one.index(head):]
    raise AssertionError(f"строки «{head}» в плашке нет:\n" + "\n".join(got["lines"]))


def test_a_locked_field_is_never_reported_as_substituted():
    """Экран владельца: ВРИ заперта требованием КРТ и осталась нулём."""
    got = _run(KRT, ANSWER)
    assert got["fields"]["land_rights_cost_mln"] == 0, "запертое поле переписали"
    vri = _line(got, "Плата за ВРИ")
    assert vri == ("Плата за ВРИ, млн ₽: осталось 0 — поле заперто требованием "
                   "КРТ; метод дал бы 10 166,6"), vri


def test_one_field_is_not_described_twice_and_oppositely():
    """Строка о подстановке и приписка «не тронуто» были про одно поле.

    Утверждение шире одной приписки нарочно: проверяется, что НИ ОДНО поле не
    названо в плашке дважды — иначе второй ответ на тот же вопрос вернулся бы
    в другом виде.
    """
    got = _run(KRT, ANSWER)
    assert "Не тронуто" not in got["text"], got["text"]
    for name in ("Плата за ВРИ", "Соцкомпенсация", "Места ДОО", "Места СОШ",
                 "Мощность поликлиники"):
        said = [one for one in got["lines"] if name in one]
        assert len(said) == 1, f"поле «{name}» названо дважды: {said}"


def test_the_heading_does_not_claim_a_substitution_that_did_not_happen():
    """Заголовок отвечает за весь список: «Подставлено» над неподставленным —
    то же враньё, что и строка о подстановке, только крупнее."""
    got = _run(KRT, ANSWER)
    assert got["lines"][0].startswith("Подставлять нечего"), got["lines"][0]
    # И наоборот: когда подставлено — заголовок обязан это сказать.
    open_inputs = {**KRT, "social_area_source": "norm"}
    done = _run(open_inputs, ANSWER)
    assert done["lines"][0].startswith("Пересчитано под новый ТЭП"), done["lines"][0]


def test_an_open_field_is_substituted_and_the_line_shows_what_stands_in_it():
    """Без замка числа доезжают до полей, и строка печатает то, что в поле."""
    got = _run({**KRT, "social_area_source": "norm"}, ANSWER)
    assert got["fields"]["kindergarten_places"] == 412
    assert got["fields"]["land_rights_cost_mln"] == 10166.6
    assert _line(got, "Места ДОО") == "Места ДОО: 412"
    assert _line(got, "Плата за ВРИ") == "Плата за ВРИ, млн ₽: 10 166,6"


def test_a_field_the_method_did_not_offer_says_exactly_that():
    """«Заперто» и «метод числа не дал» лечатся разным.

    По расхождению чисел они неразличимы: поле в обоих случаях осталось
    прежним. Причину поэтому берут у правила, а не выводят из разницы.
    """
    answer = {**ANSWER, "vri_total_mln": 0}
    got = _run({**KRT, "social_area_source": "norm",
                "land_rights_cost_mln": 18265.9}, answer)
    vri = _line(got, "Плата за ВРИ")
    assert "метод числа не дал" in vri, vri
    assert "КРТ" not in vri, f"замок назван там, где его нет: {vri}"
    assert got["fields"]["land_rights_cost_mln"] == 18265.9


def test_an_unchanged_number_is_not_printed_as_a_change():
    """Население от доли офисов не зависит — и стрелкой печататься не должно."""
    got = _run(KRT, ANSWER)
    people = _line(got, "Население")
    assert "→" not in people, f"неизменившееся напечатано стрелкой: {people}"
    assert people == "Население, чел.: 4 137 — как в выгрузке ГлавАПУ", people


def test_the_base_of_the_comparison_is_named():
    """«Было» без имени читается как «до твоей правки», а это выгрузка."""
    moved = {**ANSWER, "population": 4600,
             "parking": {**ANSWER["parking"], "total": 1500}}
    got = _run(KRT, moved)
    people = _line(got, "Население")
    assert "в выгрузке ГлавАПУ 4 137 → на нынешнем ТЭП 4 600" in people, people
    assert "было" not in people.lower(), people


def test_the_parking_line_is_a_change_only_when_it_changed():
    """Машино-места в ТЭП — настоящая подстановка, и она названа как есть."""
    same = _run(KRT, ANSWER)
    assert _line(same, "Машино-места в ТЭП") == "Машино-места в ТЭП: 1210 — не изменились"
    moved = _run(KRT, {**ANSWER,
                       "parking": {**ANSWER["parking"], "permanent": 1400}})
    assert _line(moved, "Машино-места в ТЭП") == "Машино-места в ТЭП: было 1210, стало 1510"
    # Гараж поехал — значит подставлено, и заголовок обязан это признать.
    assert moved["lines"][0].startswith("Пересчитано под новый ТЭП"), moved["lines"][0]


def test_the_lock_rule_has_a_single_owner():
    """Писатель вводных и отчёт решают «заперто ли» одной функцией.

    Вторая копия условия разошлась бы молча: починенный писатель выглядел бы
    как починенный отчёт.
    """
    assert "function krtLocks(key)" in core.PAGE
    writer = page_blocks.function("applyDerivedInputs")
    assert "krtLocks(key)" in writer
    assert "KRT_REQUIREMENT_INPUTS.indexOf" not in writer, (
        "у писателя завелась своя копия правила замка")
    assert "krtLocks(" in page_blocks.function("recalcFromTep"), (
        "отчёт решает о замке сам")


def test_the_note_is_still_said_by_the_other_writers():
    """Приписку убрали у отчёта пересчёта, а не у всех: импорту ГлавАПУ и
    пересчёту по нормативам сказать о незатронутом больше нечем."""
    assert "Не тронуто — вписано требованием КРТ: " in core.PAGE
    for name in ("rescaleSocialFromTep", "recalcFromTepByNorms"):
        body = page_blocks.function(name)
        assert "applyDerivedInputs(" in body, name
        assert "skipped" in body, f"{name} молчит о незатронутом"
