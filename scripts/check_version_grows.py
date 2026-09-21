#!/usr/bin/env python3
"""Версия на main обязана строго расти.

Две параллельные сессии взяли номер от одного и того же main и обе объявили
0.18.45 — разные правки под одним номером. Общей памяти у сессий нет, общий у
них репозиторий, поэтому проверяет он: если движок изменился, а `VERSION` не
выросла, сборка красная.

Второй случай той же болезни (19.08.2026): ветка взяла 0.18.77, пока соседняя
сессия довела main до 0.18.81. Проверка на main это ловит — но уже после
слияния, красной сборкой и без образа. Поэтому та же проверка идёт на ветке
против базы (`--base origin/main`), а номер не выбирается на глаз: `--next`
печатает первый свободный над базой, с переходом через сотню (x.y.99 → x.(y+1).1).

Третий случай (21.09.2026) вылечил сам подход. Номер брали В ВЕТКЕ заранее, а
сверяли с main — и две сессии взяли 0.24.16 одновременно, каждая законно:
до слияния первой расхождения не видно ниоткуда. Номер отвечает на «что
выпущено», а выпуск случается на main, поэтому и выдаёт его слияние
(`.github/workflows/release-merge.yml`), а не ветка. Отсюда `--on-branch`:
равный базе номер — это «ещё не выдан», а не нарушение; ниже базы — регресс;
выше базы и занят соседом — то самое столкновение, названное ДО слияния.

Запуск:
    python3 scripts/check_version_grows.py [предыдущий_коммит]
    python3 scripts/check_version_grows.py --base origin/main
    python3 scripts/check_version_grows.py --next --base origin/main
    python3 scripts/check_version_grows.py --on-branch --base origin/main
"""

from __future__ import annotations

import os
import re
import subprocess
import sys

ENGINE = "main_legacy.py"
_VERSION = re.compile(r'^VERSION = "([^"]+)"', re.M)


def _version(text: str) -> tuple[int, ...]:
    found = _VERSION.search(text)
    if not found:
        raise SystemExit(f"В {ENGINE} не нашлась строка VERSION = \"…\"")
    parts = found.group(1).split(".")
    try:
        return tuple(int(part) for part in parts)
    except ValueError:
        raise SystemExit(f"Версия не разбирается на числа: {found.group(1)}")


def _show(ref: str) -> str:
    data = subprocess.run(
        ["git", "show", f"{ref}:{ENGINE}"],
        capture_output=True,
        check=True,
    ).stdout
    # A release guard must still be able to reject or recover from a damaged
    # previous revision. VERSION is ASCII; replacement keeps that line readable
    # without treating invalid source bytes as valid application code.
    return data.decode("utf-8", errors="replace")


def _remote_versions() -> tuple[dict[str, tuple[int, ...]], list[str]]:
    """Версия у каждой ветки origin и список тех, кого прочитать не вышло.

    Номер сверяют СО ВСЕМИ ветками, а не только с базой: пока ветка живёт,
    соседняя сессия успевает выпустить пять номеров, и в main их не видно,
    пока она не слита. Правило было записано 31.08.2026 и держалось на памяти
    — 02.09.2026 соседняя ветка стояла на 0.21.55 при main 0.21.62 и моей
    0.21.65, и `--next` напечатал бы ей занятый номер.

    Непрочитанная ветка НАЗЫВАЕТСЯ: в чистой сборке CI ссылок соседей нет
    вовсе, и молча посчитать по одной базе значило бы вернуть ту же ошибку с
    уверенным видом.
    """
    try:
        listed = subprocess.run(
            ["git", "ls-remote", "--heads", "origin"],
            capture_output=True, check=True, text=True).stdout
    except (subprocess.CalledProcessError, OSError) as exc:
        return {}, [f"git ls-remote не ответил ({exc}) — ветки не сверены"]
    seen: dict[str, tuple[int, ...]] = {}
    unread: list[str] = []
    for line in listed.splitlines():
        parts = line.split("\t")
        if len(parts) != 2 or not parts[1].startswith("refs/heads/"):
            continue
        branch = parts[1][len("refs/heads/"):]
        try:
            seen[branch] = _version(_show(f"origin/{branch}"))
        except (subprocess.CalledProcessError, SystemExit):
            unread.append(branch)
    return seen, unread


def _next_version(base: tuple[int, ...]) -> str:
    """Первый свободный номер над базой.

    Патч за сотню не уходит — после x.y.99 растёт средний разряд. Правило было
    в знании о проекте и держалось на памяти: утро 16.08.2026 успело выпустить
    0.17.100–105.
    """
    parts = list(base) or [0, 0, 0]
    parts[-1] += 1
    if parts[-1] > 99 and len(parts) > 1:
        parts[-1] = 1
        parts[-2] += 1
    return ".".join(str(part) for part in parts)


def _on_branch(base_ref: str) -> int:
    """Сторож на ветке: номер не ниже базы и не занят соседом.

    Роста здесь НЕ требуется. Пока требовался, ветка обязана была взять номер
    заранее — то есть угадать его за час-два до слияния, — и угадывали двое
    разом. Равенство базе значит «номер ещё не выдан»: его выдаст слияние.
    """
    try:
        base = _version(_show(base_ref))
    except subprocess.CalledProcessError:
        print(f"Базы нет ({base_ref}) — сравнение пропущено.")
        return 0
    head = _version(_show("HEAD"))
    shown_base, shown_head = ".".join(map(str, base)), ".".join(map(str, head))
    if head < base:
        print(f"Номер ниже базы: в ветке {shown_head}, в {base_ref} {shown_base}.",
              file=sys.stderr)
        print("Выпуск назад — это откат прода на прошлый образ. Влейте базу: "
              "номер выдаёт слияние, и трогать его в ветке не нужно.",
              file=sys.stderr)
        return 1
    if head == base:
        print(f"Номер не выдан ({shown_head} — как в {base_ref}); выдаст слияние.")
        return 0
    # Номер в ветке всё-таки взят. Это больше не нужно, но и не запрещено —
    # запрещено взять ЗАНЯТЫЙ, и вот это здесь и проверяется. Своя ветка из
    # сверки исключена: сравнивать номер с самим собой нечего.
    taken, unread = _remote_versions()
    mine = _current_branch()
    holders = sorted(branch for branch, version in taken.items()
                     if version == head and branch != mine)
    if holders:
        print(f"Номер {shown_head} уже держат: {', '.join(holders)}.", file=sys.stderr)
        print("Двое под одним номером — разные правки одного выпуска. Не "
              "поднимайте номер в ветке: его выдаёт слияние, и до него ветка "
              "стоит на номере базы.", file=sys.stderr)
        return 1
    print(f"Номер {shown_head} выше базы {shown_base} и свободен.")
    if unread:
        shown = ", ".join(sorted(unread)[:3])
        print(f"Не прочитано веток: {len(unread)} — ссылок нет локально "
              f"({shown}{' и другие' if len(unread) > 3 else ''}). "
              "В сверку они не вошли.", file=sys.stderr)
    return 0


def _current_branch() -> str:
    """Имя своей ветки — чтобы не счесть собственный номер занятым."""
    for command in (["git", "symbolic-ref", "--quiet", "--short", "HEAD"],
                    ["git", "rev-parse", "--abbrev-ref", "HEAD"]):
        try:
            name = subprocess.run(command, capture_output=True, text=True,
                                  check=True).stdout.strip()
        except (subprocess.CalledProcessError, OSError):
            continue
        if name and name != "HEAD":
            return name
    # В CI ветка приезжает отцепленной головой, и своего имени у неё нет.
    # Имя есть у события: без него сторож счёл бы своим номером чужой.
    return os.environ.get("GITHUB_HEAD_REF", "") or os.environ.get("GITHUB_REF_NAME", "")


def main() -> int:
    argv = [arg for arg in sys.argv[1:]]
    show_next = "--next" in argv
    on_branch = "--on-branch" in argv
    argv = [arg for arg in argv if arg not in ("--next", "--on-branch")]
    base_ref = ""
    if "--base" in argv:
        index = argv.index("--base")
        try:
            base_ref = argv[index + 1]
        except IndexError:
            raise SystemExit("--base без ссылки: укажите ветку или коммит.")
        argv = argv[:index] + argv[index + 2:]
    if on_branch:
        return _on_branch(base_ref or "origin/main")
    if show_next:
        reference = base_ref or "origin/main"
        try:
            highest = _version(_show(reference))
        except subprocess.CalledProcessError:
            raise SystemExit(f"Не удалось прочитать {ENGINE} в {reference}.")
        taken, unread = _remote_versions()
        for version in taken.values():
            if version > highest:
                highest = version
        # Держателей у максимума бывает НЕСКОЛЬКО, и назвать одного значит
        # спрятать столкновение: 12.09.2026 соседняя ветка взяла 0.23.15
        # одновременно с этой, строка назвала только эту — и свой номер выглядел
        # свободным, хотя его уже держал сосед. Это тот же выпуск назад, из-за
        # которого 23.08 прод откатился, только увиденный до слияния.
        holders = sorted(branch for branch, version in taken.items()
                         if version == highest)
        if not holders:
            holders = [reference]
        print(_next_version(highest))
        # Чем посчитано — часть ответа: «свободный номер» без списка веток
        # неотличим от номера, посчитанного по одной базе.
        word = "держат" if len(holders) > 1 else "держит"
        print(f"Взято выше {'.'.join(map(str, highest))} — максимума по "
              f"{len(taken) or 1} веткам ({word} {', '.join(holders)}).",
              file=sys.stderr)
        if len(holders) > 1:
            print("Максимум держат несколько веток разом — значит этот номер "
                  "уже занят соседом, а не только вами.", file=sys.stderr)
        if unread:
            # Одной строкой: в репозитории живут десятки давно брошенных
            # веток, и строка на каждую утопила бы саму находку — список всех
            # непрочитанных это шум, в котором теряется ответ.
            shown = ", ".join(sorted(unread)[:3])
            print(f"Не прочитано веток: {len(unread)} — ссылок нет локально "
                  f"({shown}{' и другие' if len(unread) > 3 else ''}). "
                  "В сверку они не вошли; `git fetch origin --prune` их "
                  "подтянет.", file=sys.stderr)
        return 0
    previous_ref = base_ref or (argv[0] if argv else "HEAD~1")
    try:
        before_text = _show(previous_ref)
    except subprocess.CalledProcessError:
        # Первый коммит или мелкая история: сравнивать не с чем — это не повод
        # ронять сборку.
        print(f"Предыдущей версии нет ({previous_ref}) — сравнение пропущено.")
        return 0
    after_text = _show("HEAD")
    if before_text == after_text:
        print("Движок не менялся — версия может остаться прежней.")
        return 0
    if ("\x00" in before_text or "\ufffd" in before_text) and not (
        "\x00" in after_text or "\ufffd" in after_text
    ):
        print("Повреждённое ядро восстановлено — сравнение версии пропущено.")
        return 0
    before, after = _version(before_text), _version(after_text)
    if after > before:
        print(f"Версия выросла: {'.'.join(map(str, before))} → {'.'.join(map(str, after))}")
        return 0
    print(f"Версия не выросла: было {'.'.join(map(str, before))}, "
          f"стало {'.'.join(map(str, after))}.", file=sys.stderr)
    print("Движок изменился, значит выпуск другой. Поднимите VERSION в "
          f"{ENGINE} — она объявляется там один раз.", file=sys.stderr)
    taken, _unread = _remote_versions()
    highest = before
    for version in taken.values():
        highest = max(highest, version)
    print(f"Свободный номер выше максимума по всем веткам: "
          f"{_next_version(highest)}. Его же печатает "
          "`python3 scripts/check_version_grows.py --next --base origin/main` "
          "— он сверяет ветки, а не только базу.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
