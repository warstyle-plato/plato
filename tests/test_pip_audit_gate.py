"""Проверка зависимостей падает на исправимой уязвимости и только на ней."""

import json
import subprocess
import sys
from pathlib import Path

GATE = Path(__file__).resolve().parents[1] / "scripts" / "pip_audit_gate.py"


def _run(tmp_path, report):
    path = tmp_path / "audit.json"
    path.write_text(report if isinstance(report, str) else json.dumps(report))
    return subprocess.run(
        [sys.executable, str(GATE), str(path)], capture_output=True, text=True
    )


def _dep(name, *vulns):
    return {
        "name": name,
        "version": "1.0",
        "vulns": [
            {"id": vid, "aliases": [], "fix_versions": fixes}
            for vid, fixes in vulns
        ],
    }


def test_fixable_vulnerability_fails(tmp_path):
    out = _run(tmp_path, {"dependencies": [_dep("pkg", ("PYSEC-1", ["1.1"]))]})
    assert out.returncode == 1
    assert "pkg 1.0: PYSEC-1 → 1.1" in out.stdout


def test_unfixed_vulnerability_is_named_but_does_not_fail(tmp_path):
    out = _run(tmp_path, {"dependencies": [_dep("pkg", ("PYSEC-2", []))]})
    assert out.returncode == 0
    assert "::warning" in out.stdout and "PYSEC-2" in out.stdout


def test_one_fixable_among_unfixed_still_fails(tmp_path):
    report = {
        "dependencies": [
            _dep("a", ("PYSEC-3", [])),
            _dep("b", ("PYSEC-4", ["2.0"])),
            _dep("c"),
        ]
    }
    assert _run(tmp_path, report).returncode == 1


def test_clean_report_passes(tmp_path):
    assert _run(tmp_path, {"dependencies": [_dep("a"), _dep("b")]}).returncode == 0


def test_broken_report_is_not_clean(tmp_path):
    # Пустой или битый отчёт — это «не проверили», а не «уязвимостей нет».
    assert _run(tmp_path, "").returncode == 2
    assert _run(tmp_path, {"oops": 1}).returncode == 2
