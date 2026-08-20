"""Сколько людей зарегистрировалось на портале — и почему не по журналу.

Вопрос владельца (20.08.2026): «а как узнать, сколько зарегилось на портале»,
сразу после того как `/stats csv` пришёл пустым. Обе половины одной причины:
журнал пишется на том хосте, который обслужил запрос, а диск бота на Render
живёт до следующей выкатки. Знакомство лежит файлом на ядре и переживает и
выкатку, и пересоздание контейнера, поэтому «сколько зарегистрировалось»
считается по профилям, а выгрузка собирается из обеих половин.

Запуск: python3 -m pytest tests/test_who_registered.py -q
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import main as wrapper  # noqa: E402

core = wrapper.core


def _profiles(tmp_path: Path, people: list[tuple[str, str, str, int]]) -> Path:
    """Кладёт знакомства на диск так, как их пишет сам движок."""
    directory = tmp_path / "profiles"
    directory.mkdir(parents=True, exist_ok=True)
    for index, (name, company, source, days_ago) in enumerate(people):
        created = (datetime.now() - timedelta(days=days_ago)).isoformat(timespec="seconds")
        (directory / f"{100 + index}.json").write_text(json.dumps({
            "chat_id": 100 + index, "name": name, "company": company,
            "role": "Девелопер", "source": source, "consent": True,
            "created": created, "updated": created,
        }, ensure_ascii=False), encoding="utf-8")
    return tmp_path / "projects"


def test_the_registry_counts_people_not_events(monkeypatch, tmp_path):
    """Считаем по знакомствам: журнал бота обнуляется, профили — нет."""
    monkeypatch.setattr(core, "_PROJECTS_DIR", _profiles(tmp_path, [
        ("Владислав", "ПЛАТО", "Телеграм", 1),
        ("Пётр", "Самолёт", "От коллеги", 3),
        ("Анна", "ПИК", "Телеграм", 100),
    ]))
    registry = core.profile_registry_summary(30)
    assert registry["total"] == 3
    # За окно — только те, кто в него попал; остальные из «всего» не исчезают.
    assert registry["window"] == 2
    assert registry["complete"] == 3
    assert registry["by_source"][0] == ("Телеграм", 2)
    # Свежие сверху: список читают, чтобы увидеть, кто пришёл вчера.
    assert [person["name"] for person in registry["recent"]][:2] == ["Владислав", "Пётр"]
    assert registry["recent"][0]["chat"] == 100


def test_a_broken_profile_does_not_take_the_whole_list_down(monkeypatch, tmp_path):
    """Один битый файл — минус один человек, а не минус реестр."""
    monkeypatch.setattr(core, "_PROJECTS_DIR", _profiles(tmp_path, [
        ("Владислав", "ПЛАТО", "Телеграм", 1)]))
    (tmp_path / "profiles" / "999.json").write_text("{не json", encoding="utf-8")
    assert core.profile_registry_summary(30)["total"] == 1


def test_the_stats_answer_names_who_registered(monkeypatch, tmp_path):
    """`/stats` отвечает на вопрос «сколько зарегистрировалось» словами и людьми."""
    monkeypatch.setattr(core, "_PROJECTS_DIR", _profiles(tmp_path, [
        ("Владислав", "ПЛАТО", "Телеграм", 1)]))
    sent: list[str] = []
    monkeypatch.setattr(wrapper, "_send_message",
                        lambda chat_id, text, **kw: sent.append(text))
    monkeypatch.setattr(wrapper, "_remote_summaries", lambda days: None)
    monkeypatch.setattr(core, "usage_admin_ids", lambda: {9})
    monkeypatch.setattr(core, "usage_events", lambda days=30: [])
    wrapper._stats_message(9, 9, "")
    text = sent[-1]
    assert "Зарегистрировано: 1" in text
    assert "Владислав" in text and "ПЛАТО" in text
    # Слова человека остаются словами человека.
    assert "указывают сами" in text
    # И причина пустого журнала названа там же, где журнал.
    assert "обнуляется при выкатке" in text


def test_the_registry_comes_from_the_core_when_there_is_one(monkeypatch):
    """Профили лежат на ядре: у бота своих нет, и выдумывать их нельзя."""
    sent: list[str] = []
    monkeypatch.setattr(wrapper, "_send_message",
                        lambda chat_id, text, **kw: sent.append(text))
    monkeypatch.setattr(wrapper, "_remote_summaries", lambda days: {"registry": {
        "total": 42, "window": 7, "by_source": [("Телеграм", 40)],
        "recent": [{"chat": 5, "name": "Анна", "company": "ПИК",
                    "created": "2026-08-19T10:00:00"}]}})
    monkeypatch.setattr(core, "usage_admin_ids", lambda: {9})
    monkeypatch.setattr(core, "usage_events", lambda days=30: [])
    monkeypatch.setattr(core, "profile_registry_summary",
                        lambda days=30: (_ for _ in ()).throw(
                            AssertionError("реестр берётся с ядра, а не свой")))
    wrapper._stats_message(9, 9, "")
    text = sent[-1]
    assert "Зарегистрировано: 42" in text
    assert "Анна" in text and "19.08.2026" in text


def test_the_export_carries_both_journals(monkeypatch):
    """Выгрузка приходила пустой: у бота свой журнал, и он живёт до выкатки."""
    documents: list[tuple] = []
    monkeypatch.setattr(wrapper, "_send_message", lambda chat_id, text, **kw: None)
    monkeypatch.setattr(core, "_telegram_send_document_bytes",
                        lambda chat_id, data, name, caption="", content_type="":
                        documents.append((name, caption, data.decode("utf-8"))))
    monkeypatch.setattr(core, "usage_admin_ids", lambda: {9})
    monkeypatch.setattr(core, "usage_events", lambda days=30: [
        {"at": 1_800_000_000.0, "surface": "bot", "kind": "message", "chat": 1,
         "user": 1, "name": "Пётр", "text": "77:01:0001001:1"}])
    monkeypatch.setattr(wrapper, "_remote_summaries", lambda days: {"events": [
        {"at": 1_800_000_050.0, "surface": "site", "kind": "land", "chat": 2,
         "text": "Мишина 46"}]})
    wrapper._stats_message(9, 9, "csv")
    _name, caption, body = documents[-1]
    assert "Бот: 1" in caption and "ядро (сайт): 1" in caption
    assert "77:01:0001001:1" in body and "Мишина 46" in body
    # По времени, а не по хостам: две половины одного журнала читаются подряд.
    assert body.index("77:01:0001001:1") < body.index("Мишина 46")


def test_a_silent_core_is_said_out_loud(monkeypatch):
    """Половина вместо целого — с оговоркой, иначе выгрузка врёт полнотой."""
    documents: list[tuple] = []
    monkeypatch.setattr(wrapper, "_send_message", lambda chat_id, text, **kw: None)
    monkeypatch.setattr(core, "_telegram_send_document_bytes",
                        lambda chat_id, data, name, caption="", content_type="":
                        documents.append((name, caption, data)))
    monkeypatch.setattr(core, "usage_admin_ids", lambda: {9})
    monkeypatch.setattr(core, "usage_events", lambda days=30: [])
    monkeypatch.setattr(wrapper, "_remote_summaries", lambda days: None)
    monkeypatch.setattr(core, "_projects_remote_url",
                        lambda path: "https://core.example/internal/usage/summary")
    wrapper._stats_message(9, 9, "csv")
    assert "Ядро не ответило" in documents[-1][1]


def test_the_core_hands_over_the_registry_and_the_events(monkeypatch):
    """Свод для бота несёт и знакомства, и события — за одной подписью."""
    from fastapi.testclient import TestClient
    # Подпись считается токеном бота — без него ходить незачем и нечем.
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123456:registry-test-token")
    monkeypatch.setattr(core, "usage_events", lambda days=30: [{"at": 1.0}])
    monkeypatch.setattr(core, "profile_registry_summary",
                        lambda days=30: {"total": 3, "recent": []})
    client = TestClient(core.app)
    days = 30
    body = {"days": days, "sign": core._web_login_sign("usage-summary", days)}
    answer = client.post("/internal/usage/summary", json=body)
    assert answer.status_code == 200, answer.text
    data = answer.json()
    assert data["registry"]["total"] == 3
    assert data["events"] == [{"at": 1.0}]
    # Без подписи — никому: реестр несёт имена и компании живых людей.
    assert client.post("/internal/usage/summary",
                       json={"days": days, "sign": "нет"}).status_code == 403
