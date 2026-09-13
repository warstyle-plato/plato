"""Передача знания собирается из живых источников и ничего не теряет молча.

Владелец 08.09.2026 попросил копию знания о проекте — на случай, которым мы
занимались весь день: поставщика отключили, и работу может подхватить кто-то
другой. Копия здесь запрещена тем же правилом, что копия `VERSION`: переписанная
руками выжимка разойдётся с `CLAUDE.md` на первой же правке, и обе будут
выглядеть верными.

Поэтому сборщик, и проверяется у него ровно два утверждения:

* он ничего не помнит сам — своего знания о проекте в нём нет;
* он ничего не теряет — правил в сборке столько же, сколько в источнике.

Второе не мелочь: первая версия разбора требовала закрывающих звёздочек в той
же строке и молча теряла 76 правил из 415. Счёт при этом выглядел посчитанным —
ровно то, как выглядит потеря в этом проекте.

Запуск: python3 -m pytest tests/test_the_handover_is_assembled_not_copied.py -q
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import handover  # noqa: E402

KNOWLEDGE = (ROOT / "CLAUDE.md").read_text(encoding="utf-8")
SOURCE = (ROOT / "scripts" / "handover.py").read_text(encoding="utf-8")


def test_every_rule_reaches_the_index() -> None:
    """Правил в сборке столько же, сколько их в источнике.

    Считается по началу правила (`- **`), а не по разбору — иначе проверка
    сверяла бы разбор с самим собой.
    """
    starts = len(re.findall(r"^\s*- \*\*", KNOWLEDGE, flags=re.MULTILINE))
    indexed = handover._rule_index(KNOWLEDGE)
    assert starts > 300, f"источник прочитан не весь: {starts}"
    assert len(indexed) == starts, (
        f"в указатель попало {len(indexed)} правил из {starts} — потерянное "
        "правило читается как его отсутствие")


def test_a_wrapped_headline_is_not_lost() -> None:
    """Заголовок, перенесённый на вторую строку, — та самая потеря."""
    sample = "- **Зелёный набор тестов не значит, что ветка кода верна —\n  до неё не доходят.**\n"
    found = handover._rule_index(sample)
    assert len(found) == 1, found
    assert "Зелёный набор" in found[0][1] and "не доходят" in found[0][1], found


def test_the_index_points_at_the_real_line() -> None:
    """Номер строки ведёт к правилу, а не куда-нибудь.

    Указатель ценен ровно тем, что по нему идут в оригинал; сбитый номер делает
    его хуже отсутствующего.
    """
    lines = KNOWLEDGE.splitlines()
    for number, headline in handover._rule_index(KNOWLEDGE)[:40]:
        assert lines[number - 1].lstrip().startswith("- **"), (number, headline)


def test_the_assembler_holds_no_knowledge_of_its_own() -> None:
    """Своего знания о проекте у сборщика нет — оно всё в источниках.

    Признак простой: заголовок правила, встреченный в коде сборщика, значит, что
    знание переписали, а переписанное негде обновлять.
    """
    headlines = [h for _n, h in handover._rule_index(KNOWLEDGE)]
    body = SOURCE.split('"""', 2)[-1]        # без объяснения в шапке модуля
    copied = [h for h in headlines if len(h) > 25 and h[:25] in body]
    assert not copied, f"знание переписано в сборщик: {copied[:3]}"


def test_the_assembly_names_its_source_and_its_moment() -> None:
    """Сборка говорит, чем собрана и когда, и кто прав при расхождении."""
    text = handover.build(count_tests=False)
    assert "scripts/handover.py" in text, "не сказано, чем собрано"
    assert "верен `CLAUDE.md`" in text, "не сказано, кто прав при расхождении"
    assert re.search(r"Собрано \d{4}-\d{2}-\d{2}T", text), "нет отметки времени"
    assert "выпуск" in text and handover._version() in text, "нет выпуска"


def test_the_assembly_carries_the_open_questions() -> None:
    """Открытые вопросы едут вместе со знанием: без них оно читается законченным."""
    text = handover.build(count_tests=False)
    assert "## Открытые вопросы" in text
    assert len(handover._backlog_open((ROOT / "docs" / "questions_backlog.md")
                                      .read_text(encoding="utf-8"))) > 10
