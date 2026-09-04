"""Воронка КРТ: ГИС Торги — самый поздний источник, а не единственный.

«Если брать только ГИС Торги, мы узнаём об участке слишком поздно. mos.ru и
krt.mos.ru дают потенциальные КРТ за недели или месяцы до появления лота»
(владелец, 31.08.2026). Шаги: решение о КРТ на mos.ru → объявлено о торгах →
лот опубликован (ИнвестМосква, ГИС Торги) → идёт аукцион (Росэлторг) →
инвестор определён.

Шаг считается ОДИН раз и носит своё основание. «Не знаем» — такой же ответ, как
остальные, и выглядит он иначе, чем «шага не было»: площадка, у которой ничего
не прочитано, не должна выглядеть как площадка без событий.

Запуск: python3 -m pytest tests/test_the_krt_funnel_sees_the_early_signal.py -q
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from auction_search import ui  # noqa: E402

PAGE = ui.AUCTIONS_PAGE


def _function(name: str) -> str:
    start = PAGE.index(f"function {name}(")
    depth, index, seen = 0, PAGE.index("{", start), False
    while index < len(PAGE):
        if PAGE[index] == "{":
            depth, seen = depth + 1, True
        elif PAGE[index] == "}":
            depth -= 1
            if seen and depth == 0:
                return PAGE[start:index + 1]
        index += 1
    raise AssertionError(f"не нашёл конец функции {name}")


def _stages_const() -> str:
    start = PAGE.index("const KRT_STAGES=")
    return PAGE[start:PAGE.index("];", start) + 2]


def stage(site: dict, *, lots=None, press=None, intent=None, mark=None, order=None) -> dict:
    node = shutil.which("node")
    if not node:
        pytest.skip("node недоступен")
    slug = site.get("slug", "x")
    program = (
        f"const state={{krtTenders:{json.dumps({slug: lots or []})},"
        f"krtPress:{json.dumps({slug: press} if press else {})},"
        f"krtRank:{{}},krtTenderLinks:{json.dumps(mark or {})},"
        f"krtOrderBySite:{json.dumps(order or {})},"
        f"krtRequirements:{json.dumps({slug: {'intent': intent}} if intent else {})}}};\n"
        "const esc=s=>String(s);\n"
        "function krtWhen(t){return t?'дата':''}\n"
        # Лоты площадки — один ответ на всю страницу (`krtLots`): связку
        # считает сервер и он же её помнит, а не память вкладки.
        + _stages_const() + "\n" + _function("krtIntent") + "\n"
        + _function("krtLots") + "\n" + _function("krtLiveLot") + "\n"
        + _function("krtStage") + "\n"
        + f"console.log(JSON.stringify(krtStage({json.dumps(site)})));"
    )
    done = subprocess.run([node, "-e", program], capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr[:800]
    return json.loads(done.stdout)


def test_a_published_decision_is_already_a_step() -> None:
    """Самый ранний сигнал: решение есть, лота нет и не будет ещё месяцами."""
    got = stage({"slug": "a", "status": "Планируемый"},
                intent={"decision_read": True, "taken": False, "city_needs": [], "operator": []})
    assert got["key"] == "decision"
    assert "решени" in got["why"][0]


def test_an_announcement_comes_before_the_lot() -> None:
    got = stage({"slug": "b", "status": "Планируемый"},
                press={"available": True, "operator_pending": [{"quote": "выставят на торги"}],
                       "operator_named": [], "operator_appointed": [], "city_needs": []})
    assert got["key"] == "upcoming"


def test_the_catalogue_status_about_tenders_counts_too() -> None:
    """У портала есть раздел «Проекты на торгах» — статус оттуда это тот же шаг."""
    got = stage({"slug": "c", "status": "На торгах"})
    assert got["key"] == "upcoming"


def test_a_published_lot_moves_the_site_further() -> None:
    got = stage({"slug": "d", "status": "Планируемый"}, lots=[{"title": "лот"}])
    assert got["key"] == "auction"


def test_an_open_application_window_is_bidding() -> None:
    got = stage({"slug": "e", "status": "Планируемый"},
                lots=[{"title": "лот", "deadline": "2026-09-30"}])
    assert got["key"] == "bidding"
    assert "2026-09-30" in got["why"][0]


def test_a_named_operator_ends_the_funnel() -> None:
    got = stage({"slug": "f", "status": "Планируемый"},
                intent={"decision_read": True, "taken": True, "operator": ["оператор назван"],
                        "city_needs": []})
    assert got["key"] == "taken"
    got = stage({"slug": "g", "status": "В реализации"})
    assert got["key"] == "taken"


def test_nothing_read_is_not_nothing_happening() -> None:
    got = stage({"slug": "h", "status": "Планируемый"})
    assert got["key"] == "unknown"
    assert "не знаем" in " ".join(got["why"])


def test_the_stage_sorts_by_time_not_by_alphabet() -> None:
    body = _function("krtValue")
    assert "case 'stage'" in body and "KRT_STAGES.findIndex" in body
    assert "'unknown'?null" in body.replace(" ", ""), "«не знаем» не сортируется как шаг"


def test_the_probe_shows_the_answer_and_parses_nothing() -> None:
    """Имена полей из «уверенности модели» уже приезжали на прод гаражами."""
    from auction_search import krt_api_probe

    source = (ROOT / "auction_search" / "krt_api_probe.py").read_text(encoding="utf-8")
    assert "api.krt.mos.ru" in krt_api_probe.API_BASE
    assert len(krt_api_probe.CANDIDATES) >= 5
    for name in ("status", "название", "площадь"):
        assert f'"{name}"' not in source, "проба не должна знать имён полей заранее"
    import re as _re
    flat = _re.sub(r"\s+", " ", source)
    assert "сначала ответ источника" in flat, "правило должно быть названо в самом модуле"


def test_the_investmoscow_probe_names_where_the_chain_breaks() -> None:
    """«Investmoscow у нас нету» (владелец, 31.08.2026).

    Адаптер есть и стоит в наборе «все источники», но лот у него рождается
    цепочкой: каталог → карточки города → ссылка на официальную ЭТП → лот. Ноль
    лотов при живом каталоге значит обрыв на одном из шагов, а не отсутствие
    лотов. Проба называет шаг: сколько байт, похоже ли на оболочку SPA, сколько
    карточек нашлось.
    """
    source = (ROOT / "auction_search" / "api.py").read_text(encoding="utf-8")
    block = source[source.index('"/auctions/investmoscow/probe"'):]
    block = block[:block.index('@app.get("/auctions/krt/api-probe")')]
    for name in ("city_cards", "looks_html", "bytes"):
        assert name in block, f"проба не показывает {name}"
    assert "run_in_threadpool" in block, "чтение сети не должно держать цикл событий"
    assert "InvestMoscowDiscoveryAdapter" in block, "проба обязана идти тем же путём, что адаптер"


def test_investmoscow_is_part_of_all_sources() -> None:
    """Источник, которого нет в наборе «все», не появится никогда."""
    source = (ROOT / "auction_search" / "api.py").read_text(encoding="utf-8")
    block = source[source.index("def _discovery_adapters("):]
    block = block[:block.index("\ndef ", 1)]
    assert "InvestMoscowDiscoveryAdapter()" in block
    assert block.count("InvestMoscowDiscoveryAdapter()") >= 2, \
        "и отдельным выбором, и в наборе «все»"


def test_a_hand_made_mark_moves_the_site_to_upcoming() -> None:
    """Машине привязать распоряжение нечем — отметку ставит человек."""
    got = stage({"slug": "m", "status": "Планируемый"},
                mark={"m": {"number": "ДГП-Р-28/26", "published_at": 1778619600}})
    assert got["key"] == "upcoming"
    assert "отмечено вручную" in " ".join(got["why"])


def test_the_order_binds_itself_when_the_scan_is_read() -> None:
    """Привязку делает программа: адрес берётся из распознанного распоряжения."""
    got = stage({"slug": "o", "status": "Планируемый"},
                order={"o": {"number": "ДГП-Р-28/26", "published_at": 1778619600,
                             "address": "Куркинское ш., вл. 27-39"}})
    assert got["key"] == "upcoming"
    assert "распознан" in " ".join(got["why"]), "основание названо"


def test_a_live_lot_beats_an_operator_from_the_press() -> None:
    """«Почему занята? Там торги идут, ты сам нашёл их» (владелец, 02.09.2026).

    Право на договор о КРТ на торгах — значит оператора у площадки нет: город
    торгует тем, чего никому не отдал. Публикация с именем проигрывает лоту,
    а противоречие названо в основании шага.
    """
    got = stage({"slug": "g", "status": "Планируемый"},
                lots=[{"title": "лот", "deadline": "2026-09-21"}],
                intent={"decision_read": True, "taken": True,
                        "operator": ["публикация: оператор Х"], "operator_name": "Х",
                        "city_needs": []})
    assert got["key"] == "bidding"
    assert any("торги сильнее" in line for line in got["why"])
    # Слово города «В реализации» лот не отменяет: противоречие названо.
    still = stage({"slug": "h", "status": "В реализации"},
                  lots=[{"title": "лот", "deadline": "2026-09-21"}])
    assert still["key"] == "taken"
    assert any("противоречат" in line for line in still["why"])


def test_a_draft_decision_can_be_chosen_by_status() -> None:
    """«В фильтре КРТ реализуемые и планируемые, а проекты» (владелец, 02.09.2026).

    У проекта решения статуса каталога нет вовсе — карточки ещё не существует.
    Пока выбор в списке был из двух городских слов, такие площадки выпадали из
    любого отбора по статусу молча: `x.status !== status` истинно для пустого
    статуса при любом выборе.
    """
    page = (Path(__file__).resolve().parent.parent / "auction_search" / "ui.py").read_text("utf-8")
    assert "{value:'draft',    name:'Проект решения'," in page, \
        "проект решения нельзя выбрать в отборе по стадии"
    assert "function krtFilterPass(x){" in page, \
        "отбор по осям снова считается в каждой строке своим условием"
    # Вид статуса — один ответ, приходящий с сервера. Пока его выводил экран,
    # а сервер писал в строку слово, выбор давал ноль строк из 298 (владелец,
    # 04.09.2026). Отбор нажатием проверяет test_the_krt_filters_actually_filter.
    assert "function krtStatusKind(x){" in page
    assert "if(x.status_kind)return x.status_kind;" in page
    # Прочерк на месте статуса читался как пробел в данных, а это ответ.
    assert "kind==='draft'?'Проект решения'" in page
