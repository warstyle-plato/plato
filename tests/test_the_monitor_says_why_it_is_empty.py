"""«Нет данных» и «остаток бюджета» значили не то, что показывали.

Владелец, 29.08.2026: «почти все статьи — на что влияет и кто влияет — пишут
нет данных, это непоказательно тогда»; «он некорректно назван остаток бюджета,
это остаток потребности по утверждённому бюджету».

Первое — тот же корень, что у пустого ответа НСПД: отсутствие ответа источника
нельзя показывать как его отрицательный ответ. Под связями «нет данных» значит
четыре разные вещи: сеть не загружена, сеть загружена без связей, это группа, и
у этой работы связей действительно нет. На экране они выглядели одинаково.

Второе — имя. `утверждённый − оплачено` это остаток ПОТРЕБНОСТИ: денег на эту
сумму может и не быть, а название обещает обратное.

Запуск: python3 -m pytest tests/test_the_monitor_says_why_it_is_empty.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

PAGE = (ROOT / "developaid_monitor_page.py").read_text(encoding="utf-8")
GRAPH = (ROOT / "developaid_monitor_schedule_graph.py").read_text(encoding="utf-8")


def test_the_remainder_is_called_what_it_is() -> None:
    assert "Остаток потребности по утверждённому бюджету" in PAGE
    assert "kpi('Остаток бюджета'" not in PAGE, "прежнее имя вернулось"
    assert "bar('Остаток бюджета'" not in PAGE
    # И объяснение говорит, чем это НЕ является: имя обещало деньги.
    assert "а не остаток денег" in PAGE


def test_the_empty_links_name_their_reason() -> None:
    assert "function linkNote(" in PAGE
    body = PAGE[PAGE.index("function linkNote("):]
    body = body[: body.index("\n}")]
    assert "не загружена" in body, "сеть без файла и работа без связей — разное"
    assert "связей в ней нет ни у одной работы" in body
    assert "связи заданы по работам" in body, "у группы связей не бывает — это не пробел"
    assert "из ${all}" in body, "«у этой работы нет» держится на том, что у других есть"
    # Прежнего безымянного ответа не осталось ни под одним блоком.
    detail = PAGE[PAGE.index("function renderDetail("):PAGE.index("\n// «Нет данных» под связями")]
    assert "нет данных" not in detail, "безымянный ответ остался под блоком связей"


def test_the_graph_counts_how_many_tasks_have_links() -> None:
    """Иначе «связей нет ни у кого» и «нет у этой» нечем различить."""
    assert '"linked_tasks": linked' in GRAPH
    assert 'task.get("predecessors") or task.get("successors")' in GRAPH


def test_the_page_script_still_parses() -> None:
    import re
    import shutil
    import subprocess
    import tempfile

    import pytest

    import developaid_monitor_page as page

    node = shutil.which("node")
    if not node:
        pytest.skip("node недоступен")
    source = max(re.findall(r"<script[^>]*>(.*?)</script>", page.MONITOR_PAGE, re.S), key=len)
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as handle:
        handle.write(source)
        path = handle.name
    done = subprocess.run([node, "--check", path], capture_output=True, text=True)
    assert done.returncode == 0, done.stderr[:400]
