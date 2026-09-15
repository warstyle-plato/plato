"""Тело, которое не разобралось, — это отказ с причиной, а не пятисотка.

Замер прода 15.09.2026 на 0.23.73: `POST /auctions/krt/tenders` отвечал **500**
с телом `Internal Server Error` на пустое тело, на «не json», на оборванное
`{"lots":` и на валидный список `[1,2]`; `POST /auctions/krt/{slug}/tender-order`
— так же. Причина осмысленная («прислали не объект»), а на экране это
`Unexpected token` в разборе ответа: человек видит поломку разбора вместо
причины отказа. Правило записано на `/market/price-hint` 04.09.2026 и соседние
маршруты не защитило — сторожей у тела не было нигде, и таких дверей семь.

Сторож один на сервис (`request_body.json_object`): два ответа на «что делать с
негодным телом» однажды разошлись бы, и один маршрут отвечал бы 422, а соседний
500 на том же теле.

Ответов ТРИ, и слить их нельзя: тело пустое, тело не разобрано, тело не объект.
«Ничего не прислали» и «прислали не то» чинятся по-разному.

Содержимое тела в отказ НЕ идёт: в нём бывают имена людей, номер чата и текст
вопроса Платону, а отказ уезжает в журнал.

Строковым тестом это не ловится — `await request.json()` и `await
json_object(request)` в исходнике выглядят одинаково осмысленно. Ловит запуск
маршрута и разбор: запуск стережёт семь известных дверей, а завтра появится
восьмая.

Запуск: python3 -m pytest tests/test_a_bad_body_is_a_named_refusal.py -q
"""

from __future__ import annotations

import ast
import hashlib
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

CABINET_KEY = "probe-cabinet-key"
BOT_TOKEN = "probe-bot-token"

# Негодные тела: у каждого свой ответ, и ни один из них не 500.
BAD_BODIES = (
    ("пустое", b"", "пуст"),
    ("не json", "секретное слово".encode("utf-8"), "не разобрано"),
    ("оборванный объект", b'{"lots":', "не разобрано"),
    ("список вместо объекта", b"[1,2]", "объект JSON"),
    ("строка вместо объекта", '"секретное слово"'.encode("utf-8"), "объект JSON"),
)

# Семь дверей, в которые приходит тело запроса. Гейты доступа у них разные и
# стоят в разных местах: кабинет проверяет ключ ДО разбора, вебхук — подпись,
# у остальных гейта нет вовсе.
ROUTES = (
    "/auctions/krt/tenders",
    "/auctions/krt/probe-slug/tender-order",
    "/report/pdf",
    "/cabinet/ask",
    "/cabinet/report.pdf",
    "/cabinet/sales.pptx",
    "/telegram/webhook",
)


@pytest.fixture(scope="module")
def client() -> TestClient:
    """Клиент с ключом кабинета и токеном бота — и оба УБИРАЮТСЯ за собой.

    Первая версия писала прямо в `os.environ` и роняла четырёх соседей по
    прогону: с заданным `TELEGRAM_BOT_TOKEN` мягкий гейт `/report/pdf`
    взводится, и отчёт начинает отвечать 401 всем. Падало при этом не здесь, а
    у них — то есть выглядело поломкой их кода. Состояние прогона обязано быть
    в самом прогоне.
    """
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("MARKET_CABINET_KEY", CABINET_KEY)
        patch.setenv("TELEGRAM_BOT_TOKEN", BOT_TOKEN)
        import main_registry

        yield TestClient(main_registry.app)


def _headers() -> dict[str, str]:
    secret = hashlib.sha256(("plato-webhook:" + BOT_TOKEN).encode("utf-8")).hexdigest()
    return {
        "X-Market-Key": CABINET_KEY,
        "X-Telegram-Bot-Api-Secret-Token": secret,
    }


@pytest.mark.parametrize("path", ROUTES)
@pytest.mark.parametrize("name,body,expected", BAD_BODIES,
                         ids=[item[0] for item in BAD_BODIES])
def test_a_bad_body_is_refused_by_name(client: TestClient, path: str,
                                       name: str, body: bytes,
                                       expected: str) -> None:
    """422 с названной причиной — не 500 и не текстовая страница."""
    answer = client.post(path, content=body, headers=_headers())
    assert answer.status_code == 422, (
        f"{path} на теле «{name}» ответил {answer.status_code}: {answer.text[:200]}"
    )
    # Читатель разбирает ответ как JSON; текстовая страница даёт ему
    # «Unexpected token» вместо причины.
    assert answer.headers.get("content-type", "").startswith("application/json"), (
        f"{path}: отказ пришёл не JSON — {answer.headers.get('content-type')}"
    )
    detail = answer.json().get("detail")
    assert isinstance(detail, str) and expected in detail, (
        f"{path} на теле «{name}» не назвал причину: {detail!r}"
    )


@pytest.mark.parametrize("path", ROUTES)
def test_the_refusal_does_not_echo_the_body(client: TestClient, path: str) -> None:
    """В теле бывают имена людей и текст вопроса — в отказ они не идут."""
    answer = client.post(path, content='"секретное слово"'.encode("utf-8"),
                         headers=_headers())
    assert "секретное слово" not in answer.text, (
        f"{path}: отказ пересказал тело запроса — {answer.text[:200]}"
    )


# --- разбор: следующая дверь попадает в проверку тем, что она появилась ---

# Место, а не слово: `request_body.py` и ЕСТЬ сторож — он обязан читать тело
# сам и разбирать его сам. Запрет по строке чинился бы обходом, а обход
# выглядит правкой.
GUARD_MODULE = "request_body.py"

SCANNED = ("main_legacy.py", "auction_search/api.py", "market_search/api.py",
           "mpt_extension.py", "request_body.py")


def _request_argument_names(node: ast.AST) -> set[str]:
    names: set[str] = set()
    args = getattr(node, "args", None)
    if args is None:
        return names
    for arg in [*args.args, *args.posonlyargs, *args.kwonlyargs]:
        annotation = arg.annotation
        if isinstance(annotation, ast.Name) and annotation.id == "Request":
            names.add(arg.arg)
        elif isinstance(annotation, ast.Attribute) and annotation.attr == "Request":
            names.add(arg.arg)
    return names


def _unguarded_body_reads(source: str, *, is_guard: bool) -> list[str]:
    """Обработчики, читающие тело мимо общего сторожа.

    Два вида находок, и оба про непойманный отказ. `request.json()` бросает
    `JSONDecodeError` — пятисотка без причины. `json.loads` над сырыми байтами
    тела — то же самое своими руками.
    """
    tree = ast.parse(source)
    found: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        requests = _request_argument_names(node)
        if not requests:
            continue
        raw_names: set[str] = set()
        for inner in ast.walk(node):
            # `ast.walk` доходит до самого Call, поэтому Await разворачивать не
            # надо: развёрнутый, он давал бы ту же находку дважды.
            if (isinstance(inner, ast.Call)
                    and isinstance(inner.func, ast.Attribute)
                    and isinstance(inner.func.value, ast.Name)
                    and inner.func.value.id in requests
                    and inner.func.attr == "json"):
                found.append(f"{node.name}: {inner.func.value.id}.json()")
            if isinstance(inner, ast.Assign) and isinstance(inner.value, ast.Await):
                call = inner.value.value
                if (isinstance(call, ast.Call)
                        and isinstance(call.func, ast.Attribute)
                        and call.func.attr == "body"
                        and isinstance(call.func.value, ast.Name)
                        and call.func.value.id in requests):
                    for target in inner.targets:
                        if isinstance(target, ast.Name):
                            raw_names.add(target.id)
        if is_guard:
            continue
        for inner in ast.walk(node):
            if (isinstance(inner, ast.Call)
                    and isinstance(inner.func, ast.Attribute)
                    and inner.func.attr == "loads"
                    and inner.args):
                argument = inner.args[0]
                base = argument
                while isinstance(base, ast.Call) and isinstance(base.func, ast.Attribute):
                    base = base.func.value
                if isinstance(base, ast.Name) and base.id in raw_names:
                    found.append(f"{node.name}: json.loads над телом запроса")
    return found


def test_no_route_reads_the_body_without_the_guard() -> None:
    complaints: list[str] = []
    for name in SCANNED:
        path = ROOT / name
        for item in _unguarded_body_reads(path.read_text(encoding="utf-8"),
                                          is_guard=name == GUARD_MODULE):
            complaints.append(f"{name}: {item}")
    assert not complaints, (
        "тело читается мимо общего сторожа — непонятое тело даст 500 без "
        f"причины: {complaints}"
    )


def test_the_guard_bites() -> None:
    """Сторож, не падающий на поломке, — не сторож."""
    broken = (
        "async def handler(request: Request) -> dict:\n"
        "    payload = await request.json()\n"
        "    return payload\n"
    )
    assert _unguarded_body_reads(broken, is_guard=False) == [
        "handler: request.json()"]

    by_hand = (
        "async def handler(request: Request) -> dict:\n"
        "    raw = await request.body()\n"
        "    return json.loads(raw)\n"
    )
    assert _unguarded_body_reads(by_hand, is_guard=False) == [
        "handler: json.loads над телом запроса"]

    # Сырые байты файла телом-объектом не притворяются: загрузка книги читает
    # тело и не разбирает его как JSON — такую дверь запрещать нечего.
    upload = (
        "async def handler(request: Request) -> dict:\n"
        "    data = await request.body()\n"
        "    return {'size': len(data)}\n"
    )
    assert _unguarded_body_reads(upload, is_guard=False) == []
