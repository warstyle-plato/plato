"""Решает, падать ли проверке зависимостей по отчёту pip-audit.

Падать есть смысл только там, где есть что делать: у уязвимости есть
исправленная версия, и её можно поставить. Уязвимость без исправления (чужой
пакет, автор ещё не выпустил версию) называется в отчёте, но сборку не роняет:
красный main из-за того, что от нас не зависит, учит не смотреть на красное.

    pip-audit -r requirements-dev.txt --format json -o audit.json
    python3 scripts/pip_audit_gate.py audit.json

Код выхода: 0 — исправимых нет; 1 — есть исправимые; 2 — отчёт не прочитан
(битый или пустой отчёт — не «уязвимостей нет»).
"""

from __future__ import annotations

import json
import sys


def classify(report: dict) -> tuple[list[dict], list[dict]]:
    """Делит находки на исправимые и без исправления."""
    fixable: list[dict] = []
    unfixed: list[dict] = []
    seen: set[tuple] = set()
    deps = report.get("dependencies")
    if not isinstance(deps, list):
        raise ValueError("в отчёте pip-audit нет списка dependencies")
    for dep in deps:
        for vuln in dep.get("vulns") or []:
            # pip-audit повторяет одну находку, если её отдают две базы.
            key = (dep.get("name"), dep.get("version"), vuln.get("id"))
            if key in seen:
                continue
            seen.add(key)
            row = {
                "name": dep.get("name"),
                "version": dep.get("version"),
                "id": vuln.get("id"),
                "aliases": vuln.get("aliases") or [],
                "fix_versions": vuln.get("fix_versions") or [],
            }
            (fixable if row["fix_versions"] else unfixed).append(row)
    return fixable, unfixed


def _line(row: dict) -> str:
    ids = ", ".join([row["id"], *row["aliases"]])
    fix = ", ".join(row["fix_versions"]) or "исправления нет"
    return f"{row['name']} {row['version']}: {ids} → {fix}"


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("использование: pip_audit_gate.py audit.json", file=sys.stderr)
        return 2
    try:
        with open(argv[1], encoding="utf-8") as fh:
            fixable, unfixed = classify(json.load(fh))
    except (OSError, ValueError) as exc:
        print(f"Отчёт pip-audit не прочитан ({argv[1]}): {exc}", file=sys.stderr)
        return 2
    for row in unfixed:
        # Аннотация в GitHub Actions: видна в сводке прогона, но не роняет его.
        print(f"::warning title=Уязвимость без исправления::{_line(row)}")
    for row in fixable:
        print(f"::error title=Уязвимость с исправлением::{_line(row)}")
    print(
        f"pip-audit: исправимых {len(fixable)}, без исправления {len(unfixed)}."
    )
    return 1 if fixable else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
