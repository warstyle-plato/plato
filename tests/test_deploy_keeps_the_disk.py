"""Выкатка не оставляет за собой гору образов и бесконечный журнал.

18.08.2026 диск ядра забился под ноль: пять сборок за день, каждая тянет образ
на два-три гигабайта, прежние остаются навсегда, журнал контейнера ничем не
ограничен. Выкатка упала на «no space left on device», прод остался на
позавчерашней версии, а вход через бота начал отвечать ошибкой без объяснения —
коды входа пишутся файлами, а писать было некуда.

Здесь закреплено устройство скрипта: журнал ограничен, старые образы убираются
после успеха, текущий и предыдущий остаются, а перед скачиванием место
проверяется.

Запуск: python3 -m pytest tests/test_deploy_keeps_the_disk.py -q
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "deploy-developaid.sh"
TEXT = SCRIPT.read_text(encoding="utf-8")


def test_the_script_is_valid_shell():
    done = subprocess.run(["sh", "-n", str(SCRIPT)], capture_output=True, text=True)
    assert done.returncode == 0, done.stderr


def test_the_container_log_has_a_ceiling():
    """Docker пишет журнал контейнера и сам его не чистит."""
    run = TEXT[TEXT.index("docker run -d --name"):]
    run = run[:run.index(">/dev/null")]
    assert "--log-opt max-size=10m" in run
    assert "--log-opt max-file=3" in run


def test_old_images_are_trimmed_after_success_not_before():
    """Пока новый образ не доказал, что работает, старый — единственный путь
    назад."""
    body = TEXT[TEXT.index('say "готово: ${verdict}"'):]
    body = body[:body.index("# --- откат")]
    assert "trim_images" in body

    trim = TEXT[TEXT.index("trim_images() {"):]
    trim = trim[:trim.index("\n}\n")]
    assert "keep_now" in trim and "keep_before" in trim, "текущий и предыдущий остаются"
    assert "PREVIOUS" in trim, "предыдущий берётся из файла отката"
    assert "docker rmi" in trim


def test_the_space_is_checked_before_pulling():
    body = TEXT[TEXT.index("registry_login\n"):TEXT.index('say "скачивание ${IMAGE}"')]
    assert "free_mb" in body and "NEED_MB" in body, "мало места — прибираем до скачивания"


def test_the_disk_is_said_out_loud_even_when_there_is_room():
    """Проверка молчала, пока не считала нужным прибираться, и молчала же,
    когда прибирать было нечего: со стороны выкатка выглядела так, будто диск
    никто не смотрел, — а потом упиралась в него (владелец, 20.08.2026)."""
    body = TEXT[TEXT.index("registry_login\n"):TEXT.index('say "скачивание ${IMAGE}"')]
    announce = body[:body.index("if [")]
    assert "free_mb" in announce and "total_mb" in announce, announce
    assert "say" in announce, "остаток печатается всегда, а не только при уборке"


def test_a_full_disk_is_refused_before_the_pull():
    """`docker pull` на забитом диске падает на середине распаковки: сообщение
    приходит от докера, звучит как сетевое, и оставляет мусор."""
    body = TEXT[TEXT.index("registry_login\n"):TEXT.index('say "скачивание ${IMAGE}"')]
    assert "FLOOR_MB" in body and "ОТКАЗ" in body, body
    assert "disk_report" in body, "отказ показывает, чем занят диск"
    assert "exit 1" in body


def test_the_cleanup_lives_in_one_place():
    """Уборка — у сторожа диска. Вторая с другими правилами разойдётся молча."""
    clean = TEXT[TEXT.index("deep_clean() {"):]
    clean = clean[:clean.index("\n}\n")]
    assert "plato-disk-guard.sh" in clean and "--force" in clean
    # Сторожа может не быть рядом — тогда убираем хотя бы своё, а не молчим.
    assert "trim_images" in clean


def test_the_deploy_notices_the_guard_is_not_in_cron():
    """Уборка при выкатке закрывает дыру наполовину: без выкаток убирать
    некому. Поставить cron за человека нельзя, сказать — обязательно."""
    body = TEXT[TEXT.index('say "готово: ${verdict}"'):TEXT.index("# --- откат")]
    assert "crontab -l" in body and "--install" in body


def test_the_space_can_be_seen_without_deploying():
    assert "--space)" in TEXT
    report = TEXT[TEXT.index("disk_report() {"):]
    report = report[:report.index("\n}\n")]
    assert "docker system df" in report
    assert "docker images" in report, "видно, какой образ занимает место"


def test_a_failed_pull_says_how_much_room_is_left():
    """«Образ не скачался» без цифры отправляет искать причину в сеть, а она
    была на диске."""
    body = TEXT[TEXT.index('docker pull "$IMAGE"'):]
    body = body[:body.index("# --- проверка на закрытом порту")]
    assert "свободно $(free_mb) МБ" in body


def test_the_data_directory_is_never_touched():
    """В data лежат проекты людей, анкеты и коды входа: уборка их не касается."""
    trim = TEXT[TEXT.index("trim_images() {"):]
    trim = trim[:trim.index("\n}\n")]
    assert "data" not in trim
    assert not re.search(r"\brm\s+-rf\b", TEXT), "в выкатке нет места рекурсивному удалению"


# --- уборка сама, без выкатки ----------------------------------------------------

GUARD = ROOT / "scripts" / "plato-disk-guard.sh"
GUARD_TEXT = GUARD.read_text(encoding="utf-8")


def test_the_guard_is_valid_shell():
    done = subprocess.run(["sh", "-n", str(GUARD)], capture_output=True, text=True)
    assert done.returncode == 0, done.stderr


def test_the_guard_installs_itself_into_cron_once():
    """Уборка при выкатке закрывает дыру наполовину: когда выкаток нет, убирать
    тоже некому."""
    assert "--install" in GUARD_TEXT and "crontab" in GUARD_TEXT
    body = GUARD_TEXT[GUARD_TEXT.index("install_cron() {"):]
    body = body[:body.index("\n}\n")]
    assert "plato-disk-guard.sh*" in body, "второй раз в cron не добавляется"


def test_the_guard_keeps_the_running_and_the_previous_image():
    assert "keep_now" in GUARD_TEXT and "keep_before" in GUARD_TEXT
    assert "deploy-previous" in GUARD_TEXT, "предыдущий образ нужен откату"


def test_the_guard_never_touches_the_data():
    """В data лежат проекты людей, анкеты и коды входа."""
    assert "rm -rf" not in GUARD_TEXT
    assert "docker stop" not in GUARD_TEXT and "docker rm " not in GUARD_TEXT
    # Каталог упоминается только как место журнала и файла отката.
    for line in GUARD_TEXT.splitlines():
        if "data" in line and "prune" in line:
            raise AssertionError(f"уборка не должна касаться data: {line}")


def test_the_guard_is_silent_when_there_is_room():
    """Ежедневная строка «всё хорошо» быстро перестаёт читаться, а вместе с ней
    перестают читаться и плохие."""
    marker = 'if [ "$FORCE" -eq 0 ]'
    body = GUARD_TEXT[GUARD_TEXT.index(marker):]
    assert "exit 0" in body[:300]
    assert "THRESHOLD_MB" in body[:120], "порог тишины — тот же, что у выкатки"


def test_the_health_shows_the_free_space():
    """Заполненный диск должен быть виден раньше, чем в поведении: выкатка
    падает на распаковке, а вход через бота — на записи кода."""
    import sys
    sys.path.insert(0, str(ROOT))
    import main as wrapper

    answer = wrapper.core.health()
    assert "disk_free_mb" in answer and "disk_low" in answer
    assert answer["disk_free_mb"] is None or answer["disk_free_mb"] > 0
    assert answer["disk_low"] is (answer["disk_free_mb"] is not None
                                  and answer["disk_free_mb"] < 3072)



def test_the_guard_cleans_earlier_than_the_deploy_needs():
    """Порог уборки не может быть ниже того, что нужно выкатке: иначе сторож
    считает, что всё в порядке, ровно до момента, когда выкатка не проходит."""
    guard = (ROOT / "scripts" / "plato-disk-guard.sh").read_text(encoding="utf-8")
    threshold = int(re.search(r"^THRESHOLD_MB=(\d+)", guard, re.M).group(1))
    need = int(re.search(r"^NEED_MB=(\d+)", TEXT, re.M).group(1))
    assert threshold >= need, (threshold, need)


def test_the_bot_shows_the_room_left_on_the_core():
    """Диск кончается на ядре, а спрашивают бота: цифра должна попадаться на
    глаза сама, а не лежать в /health, куда никто не ходит."""
    import sys

    sys.path.insert(0, str(ROOT))
    import main as wrapper

    core = wrapper.core
    saved = core._projects_remote_url, core.health
    try:
        core._projects_remote_url = lambda path: ""
        core.health = lambda: {"disk_free_mb": 1200, "disk_low": True}
        low = wrapper._core_disk_line()
        assert "1200" in low and "мало для выкатки" in low
        assert "plato-disk-guard.sh" in low, "сказано, чем убирать"

        core.health = lambda: {"disk_free_mb": 15000, "disk_low": False}
        assert "15000" in wrapper._core_disk_line()

        # Ядро молчит — строки нет вовсе: выдуманный остаток хуже отсутствия.
        core.health = lambda: (_ for _ in ()).throw(RuntimeError("нет связи"))
        assert wrapper._core_disk_line() == ""
    finally:
        core._projects_remote_url, core.health = saved


def test_the_status_carries_that_line():
    source = (ROOT / "main.py").read_text(encoding="utf-8")
    status = source[source.index("def _status_message("):]
    status = status[:status.index("@app.post(\"/telegram/context\")")]
    assert "_core_disk_line()" in status
