"""Строка знает, какой ЭКОНОМИКОЙ посчитана, — и это измерено, а не объявлено.

«Везде написано что модель не считалась, потолок нигде не определен. Раньше
хотя бы у варшавского шоссе и Нагатино был нормальный расчет, около 1.5 млрд
на вход. В чем проблема» (владелец, 16.09.2026).

Замер прода в тот час: каталог судил выпуском 0.23.22 (521 строка из 579) при
работающем 0.23.96 — семьдесят четыре выпуска. У Варшавского ш., вл. 37 отказ
потолка был честным («LLCR не ниже 1,20x не достигается даже при нулевой цене —
выходит 1,18x»), а ТЕ ЖЕ вводные нынешним движком давали 1,228x и потолок
2 142 млн ₽. Правка экономики — двор в м²/чел, кладовые в подземной площади,
база НДС, инфляция объектов от старта очереди — прошла молча: `computed_at`
отвечает «когда», `rules_version` — «какой методикой скрининга», а
`engine_version` писался рядом со строкой и не читался НИКЕМ.

Сравнивать выпуски нельзя — их бывает пять в день. Объявлять номер методики
движка отдельным числом мало: правка делается в движке, а поднимать пришлось бы
число в скрининге — ровно так семьдесят четыре выпуска и прошли. Поэтому
отпечаток ИЗМЕРЯЕТСЯ: движок считает один и тот же маленький проект, и ответ
меняется тогда и только тогда, когда меняются числа.

Запуск: python3 -m pytest tests/test_a_row_knows_which_engine_counted_it.py -q
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from auction_search import krt_ranking  # noqa: E402

_PROBE = (
    "import sys; sys.path.insert(0, %r);"
    "from auction_search import krt_ranking;"
    "print(krt_ranking.model_fingerprint())" % str(ROOT)
)


def _in_a_fresh_process(seed: str) -> str:
    done = subprocess.run([sys.executable, "-c", _PROBE], capture_output=True,
                          text=True, timeout=300,
                          env={**__import__("os").environ, "PYTHONHASHSEED": seed})
    assert done.returncode == 0, done.stderr[-2000:]
    return done.stdout.strip()


def test_the_fingerprint_answers_the_same_in_any_process():
    """Иначе он объявит устаревшим весь каталог на ровном месте.

    Внутри одного процесса семя одно, порядок множеств один и тот же, и
    непостоянство невидимо — проверка, зовущая функцию дважды, зелена на
    сломанном коде. Поэтому процессы разные и с разными семенами.
    """
    got = {_in_a_fresh_process(seed) for seed in ("0", "1", "12345")}
    assert len(got) == 1, f"отпечаток пляшет от процесса к процессу: {got}"
    only = got.pop()
    assert only and only != "—", "отпечаток не снялся вовсе"
    assert only == krt_ranking.model_fingerprint()


def test_the_fingerprint_follows_the_numbers_not_the_release():
    """Выпуск методику не двигает, а методика двигает отпечаток.

    Обе половины нужны порознь. Если бы отпечаток шёл за выпуском, каталог
    устаревал бы по пять раз в день — ровно то, из-за чего у `rules_version`
    и написано, что версией приложения это делать нельзя. А если бы он не
    шёл за числами, он не заметил бы ни одной правки экономики.
    """
    core = krt_ranking._engine()
    assert core is not None, "движка нет — мерить нечем"
    base = krt_ranking._measure_model_fingerprint()
    assert base

    was_version = core.VERSION
    try:
        core.VERSION = "99.99.99"
        assert krt_ranking._measure_model_fingerprint() == base, (
            "отпечаток пошёл за номером выпуска — каталог устареет пять раз в день")
    finally:
        core.VERSION = was_version

    # Настоящая правка методики: норматив площади соцобъекта на место (РНГП,
    # таблицы 1.4.1 и 1.4.2). Он двигает площадь объекта, а с ней строительный
    # объём — то есть знаменатель всех удельных.
    was_norm = core.MOSCOW_SOCIAL_AREA_PER_PLACE
    try:
        core.MOSCOW_SOCIAL_AREA_PER_PLACE = {
            "kindergarten": ((125.0, 40.0), (250.0, 30.0), (float("inf"), 25.0)),
            "school": ((550.0, 30.0), (1000.0, 25.0), (float("inf"), 20.0)),
        }
        moved = krt_ranking._measure_model_fingerprint()
    finally:
        core.MOSCOW_SOCIAL_AREA_PER_PLACE = was_norm
    assert moved and moved != base, "правка методики отпечаток не сдвинула"
    assert krt_ranking._measure_model_fingerprint() == base, "отпечаток не вернулся"


def test_a_broken_fingerprint_does_not_declare_the_whole_catalogue_stale(monkeypatch):
    """Свой сбой — это «не знаем», а не «всё устарело».

    Объявить устаревшим весь каталог из-за собственной поломки хуже молчания:
    человек нажмёт «пересчитать только их» и заплатит за весь рынок.
    """
    monkeypatch.setattr(krt_ranking, "_MODEL_FINGERPRINT", "", raising=False)
    monkeypatch.setattr(krt_ranking, "model_fingerprint", lambda: "", raising=True)
    from auction_search import krt_screening

    assert krt_ranking.model_is_current(
        {"rules_version": krt_screening.SCREENING_RULES_VERSION}) is True


def test_the_row_carries_the_fingerprint():
    row = krt_ranking.score_row(
        {"slug": "site", "name": "Площадка"},
        {"available": True, "market": {}, "metrics": {}, "phasing": {}})
    assert row["model_fingerprint"] == krt_ranking.model_fingerprint()
    assert row["engine_version"] == krt_ranking._engine_version()


def test_the_screen_names_which_release_counted_the_stale_rows():
    """Проверяется то, что человек ПРОЧИТАЕТ, а не то, что лежит в исходнике.

    Строка «Посчитаны выпусками» есть в файле и у сломанной страницы: своей
    копии `VERSION` у неё нет, и `esc(VERSION)` уронил бы весь скрипт молча —
    ни одной функции, ни кабинета, ни расчёта.
    """
    import page_blocks
    from auction_search.ui import auctions_page

    prelude = (
        "const box={innerHTML:'',style:{}};"
        "const state={krtStaleModel:2,krtStaleEngines:[{engine:'0.23.22',rows:2}],"
        "krtEngine:'0.23.97'};"
        "function $(id){return id==='krtRankStatus'?box:null}\n")
    got = page_blocks.run_json(
        prelude, "renderKrtStaleModelNote();console.log(JSON.stringify({html:box.innerHTML}));",
        page=auctions_page())
    said = got["html"]
    assert "Посчитано прежней методикой: 2 площадок" in said
    assert "0.23.22 — 2" in said, said
    assert "сейчас 0.23.97" in said, said
    assert "Пересчитать только их" in said

    # Выпусков не назвали — строка остаётся без них, а не пишет «сейчас».
    silent = page_blocks.run_json(
        prelude.replace("[{engine:'0.23.22',rows:2}]", "[]"),
        "renderKrtStaleModelNote();console.log(JSON.stringify({html:box.innerHTML}));",
        page=auctions_page())["html"]
    assert "Посчитаны выпусками" not in silent, silent
    assert "Посчитано прежней методикой" in silent
