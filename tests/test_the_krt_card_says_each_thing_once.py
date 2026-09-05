"""Правая карточка КРТ говорит каждую вещь один раз и своим именем.

«Правый блок когда будет пересмотрен? там хаос конечно сейчас» и следом «И что
с правым полем?» (владелец, 05.09.2026). Замер настоящей карточки на настоящих
строках прода — 580 площадок, снимок 05.09 — показал четыре разных беспорядка,
и ни один из них не про вкус.

**Балл подписан чужим именем.** «Оценка Платона: 4/100» — а Платон в нём не
участвует вовсе: балл собирает арифметика (`krtScore`) по каталожным ТЭП и
названным снижениям. В той же карточке ниже стоит НАСТОЯЩАЯ «Рекомендация
Платона» — кнопка и его ответ. Два разных смысла под одним именем; правило то
же, по которому с фильтра каталога снята подпись «Платон: жильё и быстрый
старт».

**Снижения печатались дважды подряд.** Плашка перечисляла их прозой, а
раскрытие сразу под ней — списком: на площадке с четырьмя снижениями это 350
одних и тех же знаков, сказанных два раза, — восьмая часть карточки.

**Раскрытие внутри раскрытия.** «Пропорции ТЭП» лежали складкой внутри складки
«Остальные ТЭП каталога и пропорции», «Чьё это КРТ» — внутри «Что про площадку
известно». Девять раскрытий на карточку.

**Две кнопки на одно действие.** «Пересчитать» в блоке пропорций звала ровно
тот же `loadKrtMarket`, что и «Пересчитать сейчас» выше. А сама «Пересчитать
сейчас» после первого нажатия переименовывала себя в «Обновить маркетинг и
модель» — подпись спорила сама с собой через одно нажатие, ровно как у кнопки
«Оценить все КРТ моделью» до неё.

**Источник назывался чужим именем.** 298 строк каталога из 580 — площадки,
которых на krt.mos.ru нет вовсе: они приезжают проектом решения с mos.ru.
Подзаголовок карточки, кнопка «Открыть krt.mos.ru» и список ссылок говорили им
«krt.mos.ru» — три утверждения об источнике, неверных больше чем на половине
списка. Там же карточка печатала «Жильё —» и «Нежилое по каталогу —» при
названных в самом документе числах: площадь квартир известна у 44 площадок,
нежилая наземная — у 91.

**Длинные списки лежали открытыми.** «Всё должно быть последовательно и
логично, длинные списки с возможностью свернуть» (владелец, 05.09.2026).
Требования КРТ рисовали восемь списков подряд без единой складки: на Мира,
вл. 122 это 102 строки, из них 19 объектов сноса и 43 кадастровых номера. А
там, где списки пусты, восемь плашек «не найдено» подряд давали ту же стену из
молчания. Теперь правило одно и порог назван один раз (`KRT_LIST_OPEN_LIMIT`):
пусто — ничего или названная причина; коротко — открытым; длинно — складкой с
числом. Ненайденное собирается в одну строку и по-прежнему говорит «не
опубликовано», а не «нет».

**Порядок был обратный самому решению.** «Срочно надо разумный блок карточки
КРТ делать справа. Без хаоса» (владелец, 05.09.2026, третий раз про это поле).
Балл со списком снижений стоял ВЫШЕ экономики, из которой он свёрнут, и одни и
те же LLCR с маржой рассказывались трижды подряд: плашкой балла, списком
снижений и таблицей модели. А четвёртым блоком сверху стояла «Проверка данных»
— утверждение про НАШЕ чтение, и на живом каталоге она говорит «сверять не с
чем» у 501 строки из 580, то есть была постоянной припиской, которую перестают
читать. Теперь карточка отвечает на четыре вопроса подряд, и у каждого есть имя
на экране: можно ли войти → что за площадка → что это даёт → насколько верим,
дальше действие и приложения.

Запуск: python3 -m pytest tests/test_the_krt_card_says_each_thing_once.py -q
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from auction_search.ui import auctions_page  # noqa: E402


def _fn(page: str, name: str) -> str:
    """Кусок страницы по границам функции, а не по соседней строке."""
    start = page.index(f"function {name}(")
    depth, seen, i = 0, False, page.index("{", start)
    while i < len(page):
        if page[i] == "{":
            depth, seen = depth + 1, True
        elif page[i] == "}":
            depth -= 1
            if seen and depth == 0:
                return page[start:i + 1]
        i += 1
    raise AssertionError(f"на странице нет функции {name}")


def test_the_score_is_not_signed_with_platons_name():
    """Балл — наша арифметика, и подписан он ею; Платон остаётся у своей кнопки."""
    page = auctions_page()

    box = _fn(page, "krtScoreBoxHtml")
    assert "Балл площадки" in box, box
    assert "Оценка Платона" not in box, "балл снова подписан именем, которое его не считает"

    card = _fn(page, "selectKrt")
    # Настоящий Платон в карточке остаётся — кнопкой и своим ответом. Именно
    # поэтому балл нельзя звать его именем: иначе в одной карточке два «Платона».
    assert "Рекомендация Платона" in card, card

    # Колонка таблицы называет то же, что карточка: два имени у одного числа
    # читаются как два разных числа.
    head = page[page.index('data-sort="score"'):]
    head = head[:head.index("</th>")]
    assert "Балл площадки" in head, head


def test_the_cuts_are_printed_once():
    """Перечень снижений живёт в раскрытии, а плашка называет только итог."""
    page = auctions_page()
    box = _fn(page, "krtScoreBoxHtml")
    assert "Расчёт снял ${sc.cut}%" in box, box
    assert "sc.cuts.map" not in box, "снижения снова перечислены и в плашке, и списком под ней"

    card = _fn(page, "selectKrt")
    assert "sc.cuts.map" in card, "перечень снижений исчез вовсе — снижение без объяснения это другое число"


def test_no_fold_hides_inside_another_fold():
    """Складка внутри складки читается как ещё один экран за нажатием."""
    page = auctions_page()
    for name in ("krtRatioBlock", "krtIntentBlock"):
        body = _fn(page, name)
        assert "<details" not in body, f"{name} снова рисует раскрытие внутри раскрытия"
        assert '<h3>' in body, f"{name} потерял свой заголовок"


def test_one_action_has_one_button_and_one_name():
    """Пересчёт зовётся одной кнопкой, и она не переименовывает себя нажатием."""
    page = auctions_page()

    ratios = _fn(page, "krtRatioBlock")
    assert "krtRatioApply" not in ratios, "вторая кнопка на то же самое действие вернулась"
    assert "Пересчитать сейчас" in ratios, "не сказано, чем применяются доли"

    market = _fn(page, "loadKrtMarket")
    # Подпись после нажатия — та же, что стоит в разметке карточки.
    assert "b.textContent='Пересчитать сейчас'" in market, market
    card = _fn(page, "selectKrt")
    assert 'id="krtMarket">Пересчитать сейчас<' in card, card

    # Поле долей всё ещё применяется — Enter'ом, и связывает его одно место.
    assert "function krtRatioBind(" in page
    assert card.count("krtRatioBind(x)") == 1, card


def test_a_list_folds_when_it_is_long_and_stays_open_when_short():
    """Одно правило на все списки карточки, и порог назван один раз.

    Гоняется настоящая функция страницы: строковая проверка увидела бы её имя
    и в сломанном виде.
    """
    node = subprocess.run(["which", "node"], capture_output=True, text=True)
    if node.returncode:
        pytest.skip("node недоступен")

    page = auctions_page()
    program = "\n".join([
        # `esc` объявлена стрелкой — берём её строкой объявления, а не по границам функции.
        next(one for one in page.splitlines() if one.startswith("const esc=")),
        next(one for one in page.splitlines() if one.startswith("const KRT_LIST_OPEN_LIMIT=")),
        _fn(page, "krtList"),
        "const many=Array.from({length:19},(_,i)=>'объект '+(i+1));",
        "console.log(JSON.stringify({",
        "  empty: krtList('Что пока не учтено',[],{word:'пункт(ов)'}),",
        "  named: krtList('Что снести',[],{missing:'в решении не найдено'}),",
        "  short: krtList('Что пока не учтено',['снос','расселение'],{word:'пункт(ов)'}),",
        "  long: krtList('Что снести или реконструировать',many),",
        "}));",
    ])
    done = subprocess.run([node.stdout.strip(), "-e", program],
                          capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr
    import json
    got = json.loads(done.stdout)

    # Пусто и без названной причины — блока нет вовсе: «— 0» это экран за нажатием.
    assert got["empty"] == "", got["empty"]
    # Пусто с названной причиной — причина, а не молчание.
    assert "в решении не найдено" in got["named"], got["named"]
    # Коротко — открытым: складка ради двух строк заставляет нажимать впустую.
    assert "<details" not in got["short"], got["short"]
    assert "— 2 пункт(ов)" in got["short"] and "расселение" in got["short"], got["short"]
    # Длинно — складкой, и число стоит в заголовке.
    assert "<details" in got["long"], got["long"][:200]
    assert "— 19" in got["long"], got["long"][:200]
    assert "объект 19" in got["long"], "список за складкой опустел"


def test_the_requirements_do_not_stack_eight_open_lists():
    """Найденное — списками по общему правилу, ненайденное — одной строкой."""
    page = auctions_page()
    block = _fn(page, "renderKrtRequirements")
    assert "krtList(" in block, block[:300]
    assert "krtRequirementList" not in page, "старый рисовальщик списков вернулся"
    # Ненайденное собрано в одну строку и названо «не опубликовано», а не «нет».
    assert "Не опубликовано в материалах города" in block, block[:400]
    assert "а не «нет»" in block, block[:400]


# --- источник ----------------------------------------------------------------

DECISION = {"slug": "decision:349135220", "name": "ул. Архитектора Власова, влд. 59",
            "okrug": "ЮЗАО", "no_card": True, "status_kind": "draft",
            "url": "https://www.mos.ru/dgp/documents/view/349135220/",
            "draft_decision_url": "https://www.mos.ru/dgp/documents/view/349135220/",
            "area_ha": 3.66, "total_gfa_sqm": 27915.0,
            "flats_sqm": 15681.0, "nonresidential_ground_sqm": 3410.0}
CARD = {"slug": "no7", "name": "№7 Октябрьское поле", "okrug": "СЗАО",
        "district": "Щукино", "status": "В реализации",
        "url": "https://krt.mos.ru/projects/no7", "area_ha": 5.92,
        "total_gfa_sqm": 184930.0, "housing_gfa_sqm": 161680.0,
        "nonresidential_gfa_sqm": 10550.0, "business_gfa_sqm": 12700.0, "jobs": 1490}


def _piece(page: str, name: str) -> str:
    """Объявление по имени: функция — скобками, константа — до следующего объявления."""
    if f"function {name}(" in page:
        return _fn(page, name)
    at = page.index(f"const {name}=")
    tail = page[at:]
    stop = re.search(r"\n(?=(?:const|function|let|var|//) )", tail)
    return tail[:stop.start()] if stop else tail.split("\n")[0]


def _render(name: str, project: dict) -> str:
    """Гоняем настоящую функцию страницы на настоящей форме строки.

    Что ей нужно рядом, спрашиваем у самого node: он называет недостающее имя,
    и объявление добавляется. Перечень «зависимостей» руками устарел бы на
    первой же правке карточки и упал бы не о том.
    """
    node = subprocess.run(["which", "node"], capture_output=True, text=True)
    if node.returncode:
        pytest.skip("node недоступен")
    page = auctions_page()
    needed = [name]
    for _ in range(30):
        parts = [_piece(page, one) for one in reversed(needed)]
        parts.append(f"console.log({name}({json.dumps(project, ensure_ascii=False)}))")
        done = subprocess.run([node.stdout.strip(), "-e", "\n".join(parts)],
                              capture_output=True, text=True, timeout=60)
        if done.returncode == 0:
            return done.stdout
        missing = re.search(r"ReferenceError: (\w+) is not defined", done.stderr)
        assert missing, done.stderr
        needed.append(missing.group(1))
    raise AssertionError("не удалось собрать окружение карточки за 30 шагов")


def test_a_decision_site_names_its_own_source():
    """У площадки без карточки источник — проект решения, и так он и назван."""
    html = _render("krtPassport", DECISION)
    assert "карточка krt.mos.ru" not in html, html
    assert "проект решения на mos.ru" in html, html

    # А у каталожной — по-прежнему карточка каталога.
    card = _render("krtPassport", CARD)
    assert "карточка krt.mos.ru" in card, card


def test_the_decision_numbers_are_shown_under_their_own_names():
    """Числа документа стоят в паспорте — своими именами, а не вместо жилья."""
    # Intl ставит неразрывный пробел — сравниваем по обычному.
    html = _render("krtPassport", DECISION).replace("\u00a0", " ")
    assert "Квартиры по решению" in html and "15 681" in html, html
    assert "Нежилая наземная" in html and "3 410" in html, html
    # Площадь квартир — не жилая СПП, и подменять ею строку «Жильё» нельзя:
    # в одном документе это 30 304 против 50 400 м².
    housing = html[html.index("<div>Жильё</div>"):]
    assert housing[:housing.index("</div>", 20)].count("15 681") == 0, housing[:200]

    # У каталожной строки решения не появляются: их там нет.
    card = _render("krtPassport", CARD)
    assert "по решению" not in card, card


# --- порядок карточки --------------------------------------------------------

def test_the_card_answers_in_the_order_of_the_decision():
    """Сначала можно ли войти, потом что за площадка, потом что это даёт."""
    page = auctions_page()
    card = _fn(page, "selectKrt")
    order = [
        ("можно ли войти", "krtEntryHead(x)"),
        ("что за площадка", "<h3>Что за площадка</h3>"),
        ("что это даёт", 'id="krtMarketResult"'),
        ("насколько верим", "<h3>Насколько этому верить</h3>"),
        ("что делать", 'id="krtHandoff"'),
        ("приложения", "<summary>Карта и границы</summary>"),
    ]
    seen = []
    for name, mark in order:
        assert mark in card, f"в карточке нет блока «{name}»: {mark}"
        seen.append((card.index(mark), name))
    assert seen == sorted(seen), [name for _, name in seen]

    # Балл — свёртка экономики, и стоит он ПОД ней, а не над.
    assert card.index('id="krtMarketResult"') < card.index('id="krtScoreBox"'), card[:200]


def test_a_silent_data_check_does_not_stand_above_the_verdict():
    """«Сверять не с чем» — про наше чтение, и её место в «чего не хватает».

    Громкое («сошлось», «расходится») остаётся выше вердикта: ради этого
    правка и делалась, и её держит
    tests/test_the_card_checks_the_data_before_the_verdict.py.
    """
    page = auctions_page()
    card = _fn(page, "selectKrt")
    assert "krtDataCheckSpeaks(x)" in card, card
    # Громкая — до балла, тихая — после него, и обе из одной функции.
    loud = card.index("(speaks?krtDataCheck(x):'')")
    quiet = card.index("(speaks?'':krtDataCheck(x))")
    assert loud < card.index('id="krtScoreBox"') < quiet, (loud, quiet)

    speaks = _fn(page, "krtDataCheckSpeaks")
    assert "no_card" in speaks and "compared" in speaks, speaks


def test_an_unnamed_value_says_who_did_not_name_it():
    """Прочерк остаётся ответом, но называет, чьё это молчание."""
    node = subprocess.run(["which", "node"], capture_output=True, text=True)
    if node.returncode:
        pytest.skip("node недоступен")
    html = _render("krtPassport", DECISION).replace("\u00a0", " ")
    assert "решение не называет" in html, html
    # У каталожной площадки молчит каталог, а не решение.
    card = _render("krtPassport", dict(CARD, housing_gfa_sqm=None))
    assert "каталог не называет" in card, card
    # Названное число прочерком не подменяется.
    assert "161 680" in _render("krtPassport", CARD).replace("\u00a0", " ")
