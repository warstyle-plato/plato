"""Плашка о непогашенном ПФ говорит по очередям, а не общей кучей.

Владелец, 30.08.2026: «текст невнятный. Что куда и когда гасится? Может
русским языком написать: что после первой очереди не погашено столько-то и
оно уходит во 2. По итогам всех очередей будет то-то».

Прежняя плашка складывала все очереди в одну сумму — «в даты РВЭ очередей:
долг перед раскрытием столько-то» — и из неё нельзя было понять ни какая
очередь не рассчиталась, ни куда ушёл её долг. А с включённым переносом
фраза «остаток гасится продажами после ввода» стала прямо неверной: остаток
уходит на линию следующей очереди, а продажи остаются застройщику.

Запуск: python3 -m pytest tests/test_the_rve_plate_speaks_by_queue.py -q
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import main as _wrapper  # noqa: E402

core = _wrapper.core
PAGE = core.PAGE


def _function(name: str) -> str:
    """Тело функции страницы — из самой PAGE, а не пересказом."""
    start = PAGE.index(f"function {name}(")
    depth, index = 0, PAGE.index("{", start)
    for position in range(index, len(PAGE)):
        if PAGE[position] == "{":
            depth += 1
        elif PAGE[position] == "}":
            depth -= 1
            if depth == 0:
                return PAGE[start:position + 1]
    raise AssertionError(f"функция {name} не закрыта")


def test_the_plate_names_the_queue_and_where_the_debt_went():
    body = _function("pfRveWarningHtml")
    assert "принял ПФ" in body, "не сказано, кто принял долг"
    assert "ruMonth" in body, "не сказано, когда долг перешёл"
    assert "По итогу всех очередей" in body, "нет итога по проекту"
    # Общая куча «в даты РВЭ очередей» больше не собирается.
    assert "В даты РВЭ очередей" not in PAGE


def test_the_plate_says_why_the_transfer_did_not_happen():
    """Отказ и выключенный признак — разные ответы, и оба названы.

    Иначе читатель видит дефолтную очередь и не знает, почему методика, о
    которой сказано рядом, не сработала.
    """
    body = _function("pfRveWarningHtml")
    assert "carry.applied===false" in body.replace(" ", "")
    assert "признак на вкладке «Очерёдность»" in body


def test_the_month_is_written_in_russian():
    body = _function("ruMonth")
    assert "RU_MONTHS_IN" in body
    # Предложный падеж объявлен списком, а не выведен заменой окончаний:
    # правило «я→е, а→е» однажды даст «в феврале» из чего угодно.
    assert "replace(/я$/" not in PAGE
    for month in ("январе", "феврале", "марте", "мае", "июле", "декабре"):
        assert f"'{month}'" in PAGE, month


def test_node_renders_the_plate_by_queue():
    """Проверяется настоящий код страницы через node, а не его пересказ."""
    if not _node():
        pytest.skip("node недоступен")
    script = (
        _preamble()
        + _function("ruMonth") + "\n"
        + _function("pfRveWarningHtml") + "\n"
        + """
        phaseBundle = {
          mode: 'phased',
          comparison: [
            {name: 'О1', debt_carried_out: 6.93e9, ending_pf: 0, carried_debt_in: 0},
            {name: 'О2', debt_carried_out: 0, ending_pf: 0, carried_debt_in: 6.93e9},
          ],
          phases: [
            {result: {report: {financing: {rve_pf_shortfall: 0}}}},
            {result: {report: {financing: {rve_pf_shortfall: 0}}}},
          ],
          consolidated: {finance: {ending_pf: 0}},
          debt_carry: {applied: true, transfers: [{from: 1, to: 2, at: '2030-01-01'}]},
        };
        const html = pfRveWarningHtml({report: {financing: {}}, summary: {}});
        console.log(html.replace(/<[^>]+>/g, ' ').replace(/\\s+/g, ' ').trim());
        """
    )
    out = subprocess.run([_node(), "-e", script], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    text = out.stdout.strip()
    assert "О1" in text and "принял ПФ О2" in text, text
    assert "в январе 2030" in text, text
    assert "По итогу всех очередей долг погашен полностью" in text, text
    # Не должно быть и следа старой фразы: с переносом она неверна.
    assert "гасится её собственными продажами" not in text, text


def test_node_renders_the_plate_without_the_transfer():
    if not _node():
        pytest.skip("node недоступен")
    script = (
        _preamble()
        + _function("ruMonth") + "\n"
        + _function("pfRveWarningHtml") + "\n"
        + """
        phaseBundle = {
          mode: 'phased',
          comparison: [
            {name: 'О1', debt_carried_out: 0, ending_pf: 8.93e9, carried_debt_in: 0},
            {name: 'О2', debt_carried_out: 0, ending_pf: 0, carried_debt_in: 0},
          ],
          phases: [
            {result: {report: {financing: {rve_pf_shortfall: 8.93e9}}}},
            {result: {report: {financing: {rve_pf_shortfall: 0}}}},
          ],
          consolidated: {finance: {ending_pf: 6.63e9}},
        };
        const html = pfRveWarningHtml({report: {financing: {}}, summary: {}});
        console.log(html.replace(/<[^>]+>/g, ' ').replace(/\\s+/g, ' ').trim());
        """
    )
    out = subprocess.run([_node(), "-e", script], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    text = out.stdout.strip()
    assert "гасится её собственными продажами" in text, text
    assert "модель считает это дефолтом" in text, text
    assert "признак на вкладке «Очерёдность»" in text, text


def _node() -> str | None:
    from shutil import which
    return which("node")


def _months_declaration() -> str:
    """Список месяцев берётся из самой PAGE, а не переписывается в тест.

    Копия здесь была бы вторым объявлением того же списка — ровно та ошибка,
    которую этот набор ловит в движке и в книге."""
    match = re.search(r"const RU_MONTHS_IN=\[[^\]]+\];", PAGE)
    assert match, "объявление RU_MONTHS_IN не найдено в PAGE"
    return match.group(0)


def _preamble() -> str:
    """Зависимости плашки — теми же именами, что на странице."""
    return _months_declaration() + """
    let phaseBundle = null;
    const escapeHtml = s => String(s);
    const money = v => (Number(v) / 1e9).toFixed(2).replace('.', ',') + ' млрд ₽';
    """
