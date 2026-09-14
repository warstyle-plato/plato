"""Платон знает то, что у нас записано, — и не пересказывает лишнего.

Решение владельца 14.09.2026: «инструкцию надо полностью пересмотреть, чтобы
AI-агент знал всё, что есть у нас в логах» — в наших записях, CLAUDE.md и
бэклоге.

Замер, с которого всё началось: база методики агента знала 26 правил и НЕ знала
девяти крупных кусков последних недель (благоустройство на метр двора, ГНС
только наземная, дефолт в РВЭ, налог с убытком по ст. 283, передаваемые метры,
паркинг объектов, кэш-свип, график платежей, ступени ставки ПФ), зато держала
правило про preset «Мытищи», которого в репозитории нет ни в одном файле.
Мёртвое знание опаснее отсутствующего: оно выглядит проверенным.

Копией в промпт записи не влезают (597 000 знаков), а выжимка была бы второй
копией — её негде обновлять. Поэтому источник один, читается лениво, а агент
получает куски по запросу. Наружу они выходят обезличенными: Платон отвечает
пользователям.

Запуск: python3 -m pytest tests/test_plato_knows_what_we_wrote_down.py -q
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import project_knowledge as knowledge  # noqa: E402
import main as wrapper  # noqa: E402

core = wrapper.core


def test_the_notes_are_cut_into_rules_not_lines():
    """Запись — это правило целиком: половина правила выглядит целой."""
    found = knowledge.entries()
    assert len(found) > 300, "записей подозрительно мало — разбор не нашёл правила"
    for entry in found[:50]:
        assert entry["text"].startswith(("- **", "## ", "# ")), entry["title"][:60]


def test_a_question_finds_the_rule_that_answers_it():
    """Спрашивают словами вопроса, а правило написано словами автора.

    «благоустройство» из вопроса и «благоустраивают» из правила — разные
    строки, как «двора» и «двор»; без приведения к основе поиск отвечал мимо.
    """
    answer = knowledge.search("почему благоустройство считается от двора")
    assert answer["available"] is True
    assert "двор" in answer["entries"][0]["title"].lower()


def test_an_abbreviation_is_a_word_too():
    """ГНС, ВРИ, СПП — предмет вопроса, а не служебные слова."""
    answer = knowledge.search("подземный паркинг входит в ГНС?")
    assert "ГНС" in answer["entries"][0]["title"]


def test_the_answer_is_redacted_for_the_person_asking():
    """Номера договоров, кадастры и адреса собственных проектов наружу не идут.

    Правило то же, что у свода «Статистики» (решение владельца 26.08.2026):
    сырые файлы не трогаются, чистится точка выдачи.
    """
    answer = knowledge.search("методика финансирования сверена с НКЛ Сбера договоры")
    printed = " ".join(item["text"] for item in answer["entries"])
    assert not re.search(r"\b400[A-Z0-9]{6,}\b", printed), "номер договора вышел наружу"
    assert not re.search(r"\b\d{2}:\d{2}:\d{6,7}:\d+", printed), "кадастр вышел наружу"
    for name in ("Кутузов Сити", "Гродненская", "Саввинская"):
        assert name not in printed, name


def test_the_redaction_is_proven_on_a_note_that_has_something_to_hide():
    """Предохранитель: чистить было что, иначе проверка выше ничего не значит."""
    raw = " ".join(entry["text"] for entry in knowledge.entries("rules"))
    assert re.search(r"\b400[A-Z0-9]{6,}\b", raw), "в записях нет номеров договоров"
    assert re.search(r"\b\d{2}:\d{2}:\d{6,7}:\d+", raw), "в записях нет кадастров"
    assert "‹номер договора скрыт›" in knowledge.redact("договор 400F00BVX003 подписан")


def test_the_cut_is_named_not_silent():
    """Показано меньше найденного — это говорится числом."""
    answer = knowledge.search("очередь")
    assert answer["found"] > answer["shown"]
    assert answer["shown"] >= 1


def test_nothing_found_is_an_answer_with_a_reason():
    answer = knowledge.search("квантовая хромодинамика")
    assert answer["available"] is False
    assert "квантовая хромодинамика" in answer["reason"]


def test_the_agent_reaches_the_notes_through_its_own_door():
    """Проверять надо ту дверь, в которую ходит Платон."""
    answer = core._execute_agent_tool(
        "search_project_knowledge",
        {"query": "гостевые машино-места продаются", "source": "all"}, None, {})
    assert answer["available"] is True
    assert "остев" in answer["entries"][0]["title"]
    names = {tool.get("name") for tool in core._AGENT_TOOLS}
    assert "search_project_knowledge" in names


def test_the_instructions_send_the_agent_to_the_notes():
    text = core._AGENT_INSTRUCTIONS
    assert "search_project_knowledge" in text
    # И называют границу: записи внутренние, пересказывать их наружу нельзя.
    assert "не пересказывай" in text
    assert "Записанное решение владельца сильнее твоего рассуждения" in text


def test_every_tool_named_in_the_instructions_exists():
    """Инструкция звала к рычагу, которого инструмент не принимал, — уже было.

    Имя инструмента, написанное в инструкции и не заведённое в наборе, — это
    приказ вызвать несуществующее: модель попробует и промолчит об этом.
    """
    names = {tool.get("name") for tool in core._AGENT_TOOLS}
    text = core._AGENT_INSTRUCTIONS
    # Инструмент назначают стрелкой: «вопрос → имя_инструмента». Имена
    # параметров (target_metric, scope) в этой позиции не стоят, и ловить их
    # по хвосту слова значило бы краснеть на верном тексте.
    called = set()
    for tail in re.findall(r"→\s*([a-z_]+(?:\s+(?:и|или|затем)\s+[a-z_]+)*)", text):
        called.update(re.findall(r"[a-z_]{4,}", tail))
    called -= {"и", "или", "затем"}
    unknown = sorted(called - names)
    assert unknown == [], f"инструкция зовёт несуществующие инструменты: {unknown}"


def test_the_methodology_does_not_describe_a_preset_that_is_gone():
    """Правило про preset «Мытищи» описывало проект, которого нет нигде.

    Сторож общий: правило методики, называющее пресет, обязано называть
    существующий — иначе агент считает мёртвые числа действующими.
    """
    presets = {path.stem.lower() for path in (Path(__file__).resolve().parent.parent
                                              / "presets").glob("*.json")}
    rules = " ".join(rule["rule"] for rule in core._DevelopAid_METHODOLOGY)
    for named in re.findall(r"preset[а-я]*\s+«?([A-ZА-ЯЁ][\w-]+)»?", rules):
        assert any(named.lower() in stem for stem in presets), (
            f"методика описывает preset «{named}», которого нет в presets/")


def test_the_methodology_points_at_the_notes_for_the_rest():
    """Список в промпте короткий, и он обязан сказать, где лежит остальное."""
    rules = {rule["id"]: rule["rule"] for rule in core._DevelopAid_METHODOLOGY}
    assert "PROJECT_NOTES" in rules
    assert "search_project_knowledge" in rules["PROJECT_NOTES"]
    assert "MYTISHCHI_MFC" not in rules
