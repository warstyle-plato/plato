"""Маршрут, объявленный выше своей модели, читает тело как строку запроса.

`main_legacy.py` стоит на `from __future__ import annotations`: аннотация
параметра — строка, и FastAPI разбирает её в момент навешивания декоратора.
Пока `WebLoginConfirmRequest` лежала НИЖЕ маршрутов `/internal/*/announcements`,
имени в этот момент не существовало, тип не опознавался, и `req` уезжал в
параметры строки запроса. Всякий POST с телом получал 422 «loc: query.req».

Молчали разом все три канала уведомлений: новые площадки КРТ, новые
регистрации и нормативы. Замер прода 09.09.2026: в очереди ядра 168 новостей,
самая свежая семнадцатичасовой давности, а бот каждые 15 минут получал отказ и
честно писал его у себя (`/krt/delivery`: «очередь у ядра не забрана»).

Строковым тестом это не ловится: имя модели в файле есть, аннотация написана
верно, и сломанный файл выглядит как исправный. Ловит только запуск — и разбор,
потому что запуск проверяет три известных маршрута, а завтра появится
четвёртый.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
ENGINE = ROOT / "main_legacy.py"

# Каналы уведомлений: ядро копит, хост с вебхуком забирает по общей подписи.
ANNOUNCEMENT_ROUTES = (
    "/internal/krt/announcements",
    "/internal/profile/announcements",
    "/internal/normatives/announcements",
)


def _query_complaint(payload: object) -> str:
    """Жалоба FastAPI на недостающий параметр СТРОКИ ЗАПРОСА — или пусто."""
    if not isinstance(payload, dict):
        return ""
    detail = payload.get("detail")
    if not isinstance(detail, list):
        return ""
    for item in detail:
        loc = item.get("loc") if isinstance(item, dict) else None
        if isinstance(loc, list) and loc and loc[0] == "query":
            return str(loc)
    return ""


@pytest.mark.parametrize("path", ANNOUNCEMENT_ROUTES)
def test_an_announcement_route_reads_the_body(path: str) -> None:
    """Тело доезжает до обработчика.

    Утверждение здесь одно и оно узкое: запрос НЕ отвергнут как «нет параметра
    строки запроса». Чем именно ответит обработчик дальше — 403 на подписи,
    503 без токена бота — зависит от настроек машины и к этой поломке
    отношения не имеет.
    """
    import main_legacy as core

    client = TestClient(core.app)
    response = client.post(path, json={"chat_id": 0, "sign": "не та подпись"})
    complaint = _query_complaint(response.json())
    assert not complaint, (
        f"{path}: тело ушло в строку запроса ({complaint}) — модель объявлена "
        "ниже маршрута, и FastAPI не опознал тип"
    )


def _routes_above_their_model(source: str) -> list[tuple[str, str]]:
    """Маршруты, чья модель тела объявлена ниже них самих.

    Запрещаем МЕСТО, а не слово: имя модели в файле есть у любого кода, и
    сломанного от исправного строкой не отличить.
    """
    tree = ast.parse(source)
    models = {
        node.name: node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.ClassDef)
        and any(isinstance(base, ast.Name) and base.id == "BaseModel"
                for base in node.bases)
    }
    late: list[tuple[str, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        takes_body = any(
            isinstance(deco, ast.Call)
            and isinstance(deco.func, ast.Attribute)
            and deco.func.attr in {"post", "put", "patch"}
            for deco in node.decorator_list
        )
        if not takes_body:
            continue
        for arg in node.args.args:
            name = arg.annotation.id if isinstance(arg.annotation, ast.Name) else None
            if name in models and models[name] > node.lineno:
                late.append((node.name, name))
    return late


def test_no_route_is_declared_above_its_model() -> None:
    late = _routes_above_their_model(ENGINE.read_text(encoding="utf-8"))
    assert not late, (
        "модель тела объявлена ниже маршрута — FastAPI прочитает её как "
        f"параметр строки запроса: {late}"
    )


def test_the_guard_bites() -> None:
    """Сторож, не падающий на поломке, — не сторож."""
    broken = (
        "from __future__ import annotations\n"
        "@app.post('/x')\n"
        "def handler(req: LateModel) -> dict:\n"
        "    return {}\n"
        "class LateModel(BaseModel):\n"
        "    a: int = 0\n"
    )
    assert _routes_above_their_model(broken) == [("handler", "LateModel")]
