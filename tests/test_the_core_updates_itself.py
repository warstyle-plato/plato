"""Ядро обновляет себя само, а выкатку больше не запускают руками.

Между сборкой образа и продом лежала ночь: выкатку делал владелец, а я до
машины не дотягиваюсь — ни ключа, ни адреса. Решение не в доступе, а в том,
чтобы ядро смотрело реестр по расписанию (владелец, 26.08.2026).

Дёшево это ровно потому, что сравниваются ОБРАЗЫ, а не версии: `docker pull`
на неизменившемся образе тянет манифест в несколько килобайт. Спрашивать
версию у контейнера здесь нельзя — она известна лишь после того, как образ уже
скачан, а качать два гигабайта каждые десять минут значит добить диск, об
который мы уже спотыкались (18.08.2026).
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "deploy-developaid.sh"


def test_the_script_still_parses() -> None:
    done = subprocess.run(["sh", "-n", str(SCRIPT)], capture_output=True, text=True)
    assert done.returncode == 0, done.stderr


def test_the_watcher_compares_images_not_versions() -> None:
    """Версия известна только после скачивания — сравнивать по ней значит качать."""
    body = SCRIPT.read_text()
    block = body[body.index("watch_once() {"):body.index("install_watch() {")]
    assert "docker pull -q" in block
    assert "{{.Image}}" in block, "сравнивается образ работающего контейнера"
    assert "running_version" not in block, "версия здесь стоила бы двух гигабайт за тик"


def test_a_tick_that_found_nothing_is_quiet_but_not_silent() -> None:
    """Cron не должен слать письмо каждые десять минут.

    Но «сторож ничего не делал» и «сторож не запускался» обязаны различаться,
    иначе молчащая проверка неотличима от отсутствующей.
    """
    body = SCRIPT.read_text()
    block = body[body.index("watch_once() {"):body.index("install_watch() {")]
    assert 'сторож: новее нет' in block
    assert '>> "$LOG"' in block, "строка уходит в журнал, а не в терминал"


def test_the_lock_keeps_two_deploys_apart() -> None:
    """Выкатка идёт минутами: без замка следующий тик встанет поверх неоконченной."""
    body = SCRIPT.read_text()
    assert "take_lock() {" in body
    lock = body[body.index("take_lock() {"):body.index("watch_once() {")]
    assert 'mkdir "$LOCK"' in lock
    # Брошенный замок не запирает навсегда: машина могла перезагрузиться.
    assert "-mmin +60" in lock and "старше часа" in lock


def test_the_installer_replaces_its_line_instead_of_adding_one(tmp_path: Path) -> None:
    """Повторная установка не должна плодить строки в расписании."""
    root = tmp_path / "root"
    (root / "data").mkdir(parents=True)
    (root / ".env").write_text("APP_PORT=8080\nYC_REGISTRY_ID=stub\n")
    (root / "deploy-developaid.sh").write_text(SCRIPT.read_text())
    binary = tmp_path / "bin"
    binary.mkdir()
    table = tmp_path / "table"
    (binary / "crontab").write_text(
        "#!/bin/sh\n"
        f'STORE="{table}"\n'
        'if [ "${1:-}" = "-l" ]; then [ -f "$STORE" ] && cat "$STORE"; exit 0; fi\n'
        'cat > "$STORE"\n')
    (binary / "crontab").chmod(0o755)
    env = {"PATH": f"{binary}:/usr/bin:/bin", "HOME": str(tmp_path)}
    for minutes in ("10", "5"):
        done = subprocess.run(
            ["sh", str(root / "deploy-developaid.sh"), "--install-watch", minutes],
            capture_output=True, text=True, env=env)
        assert done.returncode == 0, done.stderr
    written = table.read_text()
    assert written.count("deploy-developaid.sh --watch") == 1
    assert written.startswith("*/5 "), "последняя установка задаёт частоту"


def test_the_installer_refuses_a_non_number(tmp_path: Path) -> None:
    root = tmp_path / "root"
    (root / "data").mkdir(parents=True)
    (root / ".env").write_text("APP_PORT=8080\n")
    (root / "deploy-developaid.sh").write_text(SCRIPT.read_text())
    done = subprocess.run(
        ["sh", str(root / "deploy-developaid.sh"), "--install-watch", "часто"],
        capture_output=True, text=True)
    assert done.returncode != 0
    assert "числом" in done.stderr


def test_the_downgrade_guard_is_still_there() -> None:
    """Автомат без этого однажды тихо увёз бы прод на выпуск назад."""
    body = SCRIPT.read_text()
    assert "ALLOW_DOWNGRADE" in body
    assert "ОТКАТ НАЗАД" in body
