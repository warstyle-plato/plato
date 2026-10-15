"""Платон применяет 331-ПП (КРТ нежилой застройки) — с пунктом и цитатой.

Решение владельца: «иметь в виду его и применять в рассуждениях, в том числе
Платона». Положения записаны один раз — в реестре нормативов
(`key_provisions` строки moscow-331-pp-krt), сверены по тексту редакции от
09.09.2025. Платон и поиск по записям читают их оттуда. В расчёт и денежный
поток они не входят: это нормы торгов и документации, а не множители.

Запуск: python3 -m pytest tests/test_plato_applies_331pp.py -q
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import project_knowledge as knowledge  # noqa: E402
import main as wrapper  # noqa: E402

core = wrapper.core
ACT = "moscow-331-pp-krt"

# Пункт → то, что в нём сказано числом. Номера пунктов — из текста акта.
EXPECTED = {
    "deposit": ("п. 3 приложения 2 к Порядку", "20 процентов"),
    "auction_step": ("п. 2 приложения 2 к Порядку", "двух процентов"),
    "bidder_revenue": ("пп. 5.1, 6, 7 приложения 2 к Порядку", "не менее 10 процентов"),
    "tender_changes": ("п. 9 приложения 2 к Порядку", "не менее 20 дней"),
    "nonres_phase_deviation": ("пп. 2–4 приложения 1 к Порядку", "не более чем 15 процентов"),
    "residential_share_30": ("п. 7.1 приложения 1 к Порядку", "менее 30 процентов"),
    "city_operator": ("пп. 3.1–3.2 Порядка", "аренду без торгов"),
}


def _row() -> dict:
    rows = json.loads((ROOT / "data" / "normatives" / "registry.json").read_text(encoding="utf-8"))
    return next(r for r in rows if r["id"] == ACT)


def _krt_rule() -> str:
    answer = core._execute_agent_tool("get_methodology", {"topic": "krt"}, None, {})
    rules = [r for r in answer["rules"] if r["id"] == "KRT_NONRES_331PP"]
    assert rules, "правила 331-ПП в методике Платона нет"
    return rules[0]["rule"]


def test_the_registry_holds_the_provisions_with_points():
    row = _row()
    provisions = {p["id"]: p for p in row["key_provisions"]}
    for key, (point, quoted) in EXPECTED.items():
        assert provisions[key]["point"] == point, key
        assert quoted in provisions[key]["quote"], key
        assert provisions[key]["kind"], key
    assert "2207-ПП" in row["latest_amendment"]
    assert [s["number"] for s in row["amendment_chain"]][-1] == "2207-ПП"
    assert len(row["amendment_chain"]) == 11


def test_the_thirty_percent_is_a_threshold_not_a_cap():
    """п. 7.1 снимает требование очередности, а не ограничивает долю жилья."""
    item = next(p for p in _row()["key_provisions"] if p["id"] == "residential_share_30")
    assert "не потолок" in item["kind"]


def test_the_ten_percent_is_revenue_not_equity():
    item = next(p for p in _row()["key_provisions"] if p["id"] == "bidder_revenue")
    assert "выручки" in item["quote"]
    assert "не собственные средства" in item["text"]


def test_plato_gets_the_provisions_with_their_points():
    rule = _krt_rule()
    for point, quoted in EXPECTED.values():
        assert point in rule, point
        assert quoted in rule, quoted
    assert "331-ПП" in rule
    assert "не входят" in rule, "оговорки «не в расчёт» нет"


def test_the_instructions_send_krt_questions_to_the_provisions():
    text = core._AGENT_INSTRUCTIONS
    assert "get_methodology(topic=krt)" in text
    tool = next(t for t in core._AGENT_TOOLS if t.get("name") == "get_methodology")
    assert "krt" in tool["parameters"]["properties"]["topic"]["enum"]


def test_a_removed_fact_disappears_from_plato(tmp_path, monkeypatch):
    """Контрпример: факт убран из реестра — Платон его больше не знает."""
    rows = json.loads((ROOT / "data" / "normatives" / "registry.json").read_text(encoding="utf-8"))
    for row in rows:
        if row["id"] == ACT:
            row["key_provisions"] = [p for p in row["key_provisions"] if p["id"] != "deposit"]
    forged = tmp_path / "registry.json"
    forged.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(knowledge, "REGISTRY_RELATIVE", forged)
    rule = _krt_rule()
    assert EXPECTED["deposit"][0] not in rule
    with pytest.raises(AssertionError):
        test_plato_gets_the_provisions_with_their_points()


def test_the_search_finds_the_deposit_with_its_point():
    answer = core._execute_agent_tool(
        "search_project_knowledge",
        {"query": "задаток торги КРТ нежилой застройки 331-ПП", "source": "normative"}, None, {})
    assert answer["available"] is True
    text = " ".join(e["title"] + e["text"] for e in answer["entries"])
    assert "п. 3 приложения 2 к Порядку" in text


def test_the_calculation_does_not_read_the_provisions():
    """Решение владельца: положения не становятся множителями расчёта."""
    # Платон (agent.py) положения читает — в рассуждение, а не в расчёт.
    readers = [p.name for p in (ROOT / "engine").glob("*.py")
               if p.name != "agent.py" and "key_provisions" in p.read_text(encoding="utf-8")]
    assert readers == [], readers
    assert "key_provisions" not in (ROOT / "main_legacy.py").read_text(encoding="utf-8")
