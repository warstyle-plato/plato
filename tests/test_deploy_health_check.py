"""Проверка живости читает настоящий ответ, а не пустой стандартный ввод.

Проверка была написана так:

    echo "$body" | python3 - "$expect" <<'PY'
    data = json.load(sys.stdin)

Heredoc забирает стандартный ввод себе — из него python читает саму программу.
Труба от `echo` до него не доходит, и `json.load(sys.stdin)` получает EOF.
Итог: при живом приложении и честном 200 OK проба объявлялась проваленной,
пробный контейнер гасился, а рабочий не менялся никогда. Выкатка выглядела
осторожной, а была неработающей.

Питоновскую часть я тогда проверил отдельно, скормив ей JSON через stdin, —
и она прошла. Проверять надо было трубу, а не то, что в неё кладут: ошибка
жила ровно в стыке между оболочкой и программой.

Поэтому здесь поднимается настоящий сервер и запускается настоящий скрипт.

Запуск: python3 -m pytest tests -q
"""

from __future__ import annotations

import json
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import main as wrapper  # noqa: E402

core = wrapper.core
ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "deploy-developaid.sh"


def serve(payload: object, *, status: int = 200):
    """Настоящий сокет: curl из скрипта ходит по сети, а не по подмене."""
    body = (payload if isinstance(payload, (bytes, str))
            else json.dumps(payload)).encode() if not isinstance(payload, bytes) \
        else payload

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            if self.path != "/health":
                self.send_error(404)
                return
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def check(payload, expect: str = "", *, status: int = 200):
    server = serve(payload, status=status)
    try:
        return subprocess.run(
            ["sh", str(SCRIPT), "--check", str(server.server_port), expect],
            cwd=ROOT, capture_output=True, text=True, timeout=60)
    finally:
        server.shutdown()


@pytest.fixture(autouse=True)
def _env_file():
    """Скрипт требует .env — на машине он есть, в репозитории его нет."""
    env = ROOT / ".env"
    created = not env.exists()
    if created:
        env.write_text("APP_PORT=8080\n", encoding="utf-8")
    yield
    if created:
        env.unlink()


def healthy(**overrides) -> dict:
    """Ровно то, что отдаёт приложение, а не выдумка о нём."""
    body = dict(core.health())
    body.setdefault("commit", "")
    body["data_writable"] = True
    body.update(overrides)
    return body


def test_a_live_answer_passes():
    """Тот самый случай, на котором проверка ломалась: честный 200 OK."""
    result = check(healthy())
    assert result.returncode == 0, result.stderr
    assert core.VERSION in result.stdout


def test_the_real_health_payload_is_what_the_app_returns():
    """Предохранитель: если /health перестанет отдавать эти поля, проверка
    выше станет проверкой выдумки."""
    body = core.health()
    assert {"status", "version", "commit", "data_dir", "data_writable"} <= set(body)


def test_the_expected_commit_must_match():
    """«Поднялось» — это не «отвечает на порт»: прежний образ отвечает так же."""
    result = check(healthy(commit="deadbee"), "ae3bb26")
    assert result.returncode == 1
    assert "ожидался" in result.stderr


def test_the_same_commit_passes():
    result = check(healthy(commit="ae3bb26"), "ae3bb26")
    assert result.returncode == 0, result.stderr


def test_a_moving_tag_is_not_compared_by_commit():
    """У `prod` коммита нет — сравнивать его с ответом бессмысленно."""
    result = check(healthy(commit="ae3bb26"), "prod")
    assert result.returncode == 0, result.stderr


def test_data_that_did_not_mount_is_a_failure():
    """Контейнер без тома отвечает так же бодро, а данные уходят в слой
    образа и исчезают со следующей выкаткой."""
    result = check(healthy(data_writable=False))
    assert result.returncode == 1
    assert "каталог данных" in result.stderr


def test_an_image_older_than_the_check_is_not_a_failure():
    """На ядре крутился 0.17.58 — образ без поля `data_writable`. Пропуск
    читался как «ложь», и проверка объявляла провал на здоровом контейнере.
    Отсутствие ответа — не отрицательный ответ."""
    result = check({"status": "ok", "version": "0.17.58"})
    assert result.returncode == 0, result.stderr
    assert "собран до этой проверки" in result.stdout


def test_the_rollback_to_an_old_image_still_works():
    """Худшее следствие: откат на образ старше проверки проваливался бы
    всегда, и скрипт писал бы «ОТКАТ НЕ УДАЛСЯ — нужен человек» там, где всё
    в порядке. Откат зовёт проверку без ожидаемого коммита."""
    result = check({"status": "ok", "version": "0.17.58"}, "")
    assert result.returncode == 0, result.stderr


def test_data_reported_as_broken_is_still_a_failure():
    """Пропуск и явное «нет» — разные вещи: второе по-прежнему провал."""
    result = check({"status": "ok", "version": "0.17.62", "data_writable": False,
                    "data_dir": "data"})
    assert result.returncode == 1
    assert "каталог данных" in result.stderr


def test_a_broken_status_is_a_failure():
    result = check(healthy(status="degraded"))
    assert result.returncode == 1
    assert "status=" in result.stderr


def test_garbage_instead_of_json_is_named_not_swallowed():
    """Ошибка, ушедшая только в код возврата, — ошибка, которой нет."""
    result = check(b"<html>502 Bad Gateway</html>")
    assert result.returncode == 1
    assert "JSON" in result.stderr


def test_the_heredoc_no_longer_eats_the_answer():
    """Прямой запрет на возвращение той же конструкции."""
    script = SCRIPT.read_text(encoding="utf-8")
    # Комментарии не в счёт — они как раз объясняют, почему так больше нельзя.
    code = "\n".join(line for line in script.splitlines()
                     if not line.lstrip().startswith("#"))
    assert 'echo "$body" | python3 -' not in code
    assert "json.load(sys.stdin)" not in code.split("health_check()")[1]
