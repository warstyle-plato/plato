"""Связь вопросов продаж с ответами Telegram. Вызывается под sales_questions.lock.

Журнал отдельно от заменяемых выгрузок. Ответ — пояснение менеджера, а не
подтверждённый платёж и не закрытие всех пунктов многочастного вопроса.
"""
from __future__ import annotations

import html
import contextlib
import fcntl
import json
import uuid
from pathlib import Path
from typing import Any

from market_search import sales_questions, sales_store


@contextlib.contextmanager
def origin_lock(data_dir: Path):
    """Порядок блокировок: общий журнал происхождения, затем проект.

    Создание pending, delivery-ack и поиск/запись ответа сериализуются также
    между проектами: перепривязка чата не создаёт гонку при поиске по тексту.
    """
    place = Path(data_dir) / "cabinet" / "dialogues" / ".origin.lock"
    place.parent.mkdir(parents=True, exist_ok=True)
    with place.open("w", encoding="utf-8") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def _path(data_dir: Path, project: str) -> Path:
    return Path(data_dir) / "cabinet" / "dialogues" / f"{sales_store.slug(project)}.json"


def load(data_dir: Path, project: str) -> dict[str, Any]:
    place = _path(data_dir, project)
    if not place.exists():
        return {"project": project, "batches": {}}
    try:
        data = json.loads(place.read_text(encoding="utf-8"))
        if not isinstance(data["batches"], dict):
            raise ValueError("batches")
        return data
    except Exception as exc:
        raise RuntimeError("не читается журнал ответов продаж") from exc


def _save(data_dir: Path, project: str, data: dict[str, Any]) -> None:
    place = _path(data_dir, project)
    place.parent.mkdir(parents=True, exist_ok=True)
    spare = place.with_suffix(".tmp")
    spare.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    spare.replace(place)


def prepare(data_dir: Path, project: str, chat_id: int, items: list[dict[str, Any]],
            today: str) -> str:
    data = load(data_dir, project)
    batch_id = uuid.uuid4().hex
    items = items[:sales_questions.MAX_QUESTIONS]
    data["batches"][batch_id] = {
        "chat_id": chat_id, "asked_at": today, "message_id": 0,
        "text": html.unescape(sales_questions.message(items)),
        "questions": [{"key": item["key"], "kind": item["kind"], "text": item["text"]}
                      for item in items], "replies": [],
    }
    _save(data_dir, project, data)
    return batch_id


def asked_keys(data_dir: Path, project: str) -> set[str]:
    """Журнал тоже свидетельствует об отправлявшихся вопросах."""
    return {q["key"] for batch in load(data_dir, project)["batches"].values()
            for q in batch["questions"]}


def reply_project(data_dir: Path, chat_id: int, reply_to_id: int, quoted: str) -> str:
    """Исходный проект сообщения, независимо от текущей привязки /site.

    Неизвестное сообщение — не основание выбрать нынешний проект. Ошибка
    чтения любого журнала/неоднозначность — отказ, а не догадка.
    """
    known, pending = set(), set()
    for place in (Path(data_dir) / "cabinet" / "dialogues").glob("*.json"):
        data = json.loads(place.read_text(encoding="utf-8"))
        for batch in data["batches"].values():
            if batch["chat_id"] != chat_id:
                continue
            if batch["message_id"] == reply_to_id:
                known.add(data["project"])
            elif not batch["message_id"] and batch["text"] == quoted:
                pending.add(data["project"])
    candidates = known or pending
    if len(candidates) > 1:
        raise RuntimeError("неоднозначный исходный проект вопроса продаж")
    return next(iter(candidates), "")


def delivered(data_dir: Path, project: str, chat_id: int, batch_id: str,
              message_id: int) -> bool:
    data = load(data_dir, project)
    batch = data["batches"].get(batch_id)
    if not batch or batch["chat_id"] != chat_id or message_id <= 0:
        return False
    if batch["message_id"] not in (0, message_id):
        return False
    batch["message_id"] = message_id
    _save(data_dir, project, data)
    return True


def is_question(text: str) -> bool:
    return text.startswith((sales_questions.GREETING + ". ",
                            sales_questions.GREETING_MANY + ":\n"))


def reply(data_dir: Path, project: str, *, chat_id: int, message_id: int,
          reply_to_id: int, quoted: str, text: str, author: str, author_id: int,
          telegram_date: int, allow_legacy: bool = False) -> bool:
    """Только ответ на наше сообщение, проверенное транспортом по ID бота.

    Старые сообщения тоже принимаются: Telegram несёт оригинал в reply_to_message.
    Если delivery-ack потерян, оригинал сверяется с сохранённым текстом целиком.
    """
    if min(message_id, reply_to_id) <= 0 or not text.strip() or not is_question(quoted):
        return False
    data = load(data_dir, project)
    batch = next((b for b in data["batches"].values()
                  if b["chat_id"] == chat_id and b["message_id"] == reply_to_id), None)
    if batch and batch["text"] != quoted:
        return False
    if not batch:
        # Только ещё не подтверждённая отправка с точно таким же текстом.
        candidates = [b for b in data["batches"].values()
                      if b["chat_id"] == chat_id and not b["message_id"]
                      and b["text"] == quoted]
        batch = candidates[0] if len(candidates) == 1 else None
    if not batch:
        if not allow_legacy:
            return False
        # До введения журнала хранились лишь ключи .asked.json. Не приписываем
        # ответ всем старым ключам: сохраняем исходный вопрос и ответ как есть.
        batch_id = f"legacy:{chat_id}:{reply_to_id}"
        batch = data["batches"].setdefault(batch_id, {
            "chat_id": chat_id, "message_id": reply_to_id, "text": quoted,
            "questions": [], "replies": [], "legacy": True,
        })
        if batch["text"] != quoted:
            return False
    batch["message_id"] = reply_to_id
    replies = batch["replies"]
    if not any(r["message_id"] == message_id for r in replies):
        replies.append({"message_id": message_id, "text": text, "author": author,
                        "author_id": author_id, "telegram_date": telegram_date})
        _save(data_dir, project, data)
    return True
