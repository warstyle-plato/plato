#!/usr/bin/env python3
"""Доехала ли работа ветки до main — по СОДЕРЖИМОМУ, а не по номеру PR.

«Слит ли PR» и «доехала ли работа» — разные вопросы, и первый на второй не
отвечает. При squash номер `(#N)` в сообщении коммита может стоять, а может и
нет; ветку можно закрыть, переоткрыть, переписать заново другой веткой. По
номеру всё это выглядит одинаково, а по содержимому — нет.

21.09.2026 пятнадцать закрытых PR пришлось разбирать руками: ровно один
(`#440`) не доехал, и найден он был поиском функции в main, а не по номеру.
Здесь тот же поиск, но написанный: берутся строки, которые ветка ДОБАВИЛА
поверх точки расхождения, и проверяется, есть ли они в main.

Доля не равна вердикту. Строку могли переписать в main своими словами —
тогда она числится ненайденной, хотя работа доехала. Поэтому скрипт не
голосует «да/нет» молча: он НАЗЫВАЕТ, чего не нашёл, и решение остаётся за
тем, кто это читает. Ненайденных ноль — ответ однозначен; ненайденные есть —
их надо прочитать глазами, и они напечатаны.

Запуск:
    python3 scripts/did_it_land.py origin/claude/ветка
    python3 scripts/did_it_land.py origin/ветка --base origin/main
    python3 scripts/did_it_land.py origin/ветка --brief      # строка таблицы
    python3 scripts/did_it_land.py origin/a origin/b ...     # сразу несколько
"""

from __future__ import annotations

import subprocess
import sys

# Строка короче этого ничего не доказывает: `)`, `else:`, `"""` встречаются в
# любом файле, и «нашлась в main» у них случайно. Они не выбрасываются молча —
# их число печатается, иначе доля считалась бы от невидимого знаменателя.
MEANINGFUL = 12
# Сколько ненайденных строк показать. Показать все — это утопить находку в
# простыне; не показать ни одной — это вердикт без доказательства.
SHOWN = 5


def _git(*args: str) -> str:
    done = subprocess.run(["git", *args], capture_output=True, check=True)
    return done.stdout.decode("utf-8", errors="replace")


def _meaningful(line: str) -> bool:
    body = line.strip()
    if len(body) < MEANINGFUL:
        return False
    # Строка из одних скобок и знаков — это форма, а не работа.
    return any(char.isalnum() for char in body)


def _added_lines(base_commit: str, ref: str, path: str) -> list[str]:
    """Строки, добавленные веткой в этот файл поверх точки расхождения."""
    diff = _git("diff", "--unified=0", base_commit, ref, "--", path)
    return [line[1:] for line in diff.splitlines()
            if line.startswith("+") and not line.startswith("+++")]


def _file_in(ref: str, path: str) -> str | None:
    try:
        return _git("show", f"{ref}:{path}")
    except subprocess.CalledProcessError:
        return None


class Unreadable(Exception):
    """Сверку сделать не из чего — и причина у этого СВОЯ.

    «Ссылки нет локально» и «общего предка нет» лечатся разным: первое —
    `git fetch`, второе не лечится вовсе, потому что ветка выросла из другой
    истории и сравнивать её с базой построчно нечем. Один текст на оба случая
    отправил бы за `fetch` того, кому он не поможет.
    """


def _point_of_divergence(base: str, ref: str) -> str:
    for name in (base, ref):
        try:
            _git("rev-parse", "--verify", f"{name}^{{commit}}")
        except subprocess.CalledProcessError:
            raise Unreadable(f"ссылки {name} нет локально — "
                             f"`git fetch origin {name.removeprefix('origin/')}`")
    try:
        found = _git("merge-base", base, ref).strip()
    except subprocess.CalledProcessError:
        found = ""
    if not found:
        raise Unreadable(f"у {ref} и {base} нет общего предка — ветка выросла "
                         "из другой истории, и построчно сверять её не с чем")
    return found


def check(ref: str, base: str = "origin/main") -> dict:
    """Что из работы ветки есть в базе, а чего нет."""
    base_commit = _point_of_divergence(base, ref)
    status = _git("diff", "--name-status", base_commit, ref).splitlines()
    report = {"ref": ref, "base": base, "files": 0, "added": 0, "found": 0,
              "skipped": 0, "missing_files": [], "kept_deletions": [],
              "missing_lines": []}
    for row in status:
        parts = row.split("\t")
        if len(parts) < 2:
            continue
        mark, path = parts[0], parts[-1]
        report["files"] += 1
        in_base = _file_in(base, path)
        if mark.startswith("D"):
            # Ветка файл удалила. Удаление доехало, если в базе файла нет.
            if in_base is not None:
                report["kept_deletions"].append(path)
            continue
        if in_base is None:
            report["missing_files"].append(path)
            continue
        haystack = {line.strip() for line in in_base.splitlines()}
        for line in _added_lines(base_commit, ref, path):
            if not _meaningful(line):
                report["skipped"] += 1
                continue
            report["added"] += 1
            if line.strip() in haystack:
                report["found"] += 1
            else:
                report["missing_lines"].append(f"{path}: {line.strip()}")
    return report


def verdict(report: dict) -> str:
    """Вердикт называет состояние, а не долю.

    Доля отвечает на «сколько совпало», а спрашивают «доехало ли». Файла нет
    в базе вовсе — работа не доехала, какой бы ни была доля по остальным.
    """
    if report["missing_files"] or report["kept_deletions"]:
        return "НЕ ДОЕХАЛО"
    if not report["added"]:
        return "НЕЧЕГО СВЕРЯТЬ"
    if not report["missing_lines"]:
        return "ДОЕХАЛО"
    if report["found"] == 0:
        return "НЕ ДОЕХАЛО"
    return "ЧАСТИЧНО"


def _print(report: dict, brief: bool) -> None:
    answer = verdict(report)
    share = (f"{report['found']}/{report['added']}" if report["added"] else "—")
    if brief:
        print(f"{answer}\t{share}\t{report['ref']}")
        return
    print(f"{report['ref']} против {report['base']}: {answer}")
    print(f"  файлов затронуто {report['files']}, значимых добавленных строк "
          f"{report['added']}, из них в базе {report['found']}; "
          f"коротких строк пропущено {report['skipped']}")
    for path in report["missing_files"]:
        print(f"  файла нет в базе: {path}")
    for path in report["kept_deletions"]:
        print(f"  ветка удалила, а в базе файл остался: {path}")
    for line in report["missing_lines"][:SHOWN]:
        print(f"  не найдено — {line[:160]}")
    if len(report["missing_lines"]) > SHOWN:
        print(f"  …и ещё {len(report['missing_lines']) - SHOWN} строк")


def main() -> int:
    argv = sys.argv[1:]
    brief = "--brief" in argv
    argv = [arg for arg in argv if arg != "--brief"]
    base = "origin/main"
    if "--base" in argv:
        index = argv.index("--base")
        try:
            base = argv[index + 1]
        except IndexError:
            raise SystemExit("--base без ссылки.")
        argv = argv[:index] + argv[index + 2:]
    if not argv:
        raise SystemExit(__doc__)
    worst = 0
    for ref in argv:
        try:
            report = check(ref, base)
        except Unreadable as why:
            print(f"{ref}: не сверить — {why}.", file=sys.stderr)
            worst = 2
            continue
        _print(report, brief)
        if verdict(report) in ("НЕ ДОЕХАЛО", "ЧАСТИЧНО"):
            worst = max(worst, 1)
    return worst


if __name__ == "__main__":
    raise SystemExit(main())
