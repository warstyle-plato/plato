"""Проверка прода запускается сама после каждой сборки main.

Сборку диспатчит release-merge токеном GITHUB_TOKEN, а прогон, порождённый
этим токеном, `workflow_run` не будит: prod-smoke висел на `workflow_run` и не
запустился ни разу сам. Теперь его диспатчит последнее задание сборки.

Запуск: python3 -m pytest tests/test_prod_smoke_starts_after_the_build.py -q
"""
from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
FLOWS = ROOT / ".github" / "workflows"
BUILD = FLOWS / "build-yandex.yml"
SMOKE = FLOWS / "prod-smoke.yml"


def _load(path: Path) -> dict:
    flow = yaml.safe_load(path.read_text(encoding="utf-8"))
    # YAML 1.1 читает ключ `on` как True.
    flow["on"] = flow.pop(True, flow.get("on"))
    return flow


def _smoke_job() -> dict:
    jobs = _load(BUILD)["jobs"]
    found = [job for job in jobs.values()
             if "prod-smoke.yml" in " ".join(str(s.get("run", "")) for s in job.get("steps", []))]
    assert len(found) == 1, "сборка должна запускать prod-smoke.yml ровно одним заданием"
    return found[0]


def test_the_build_dispatches_the_smoke_after_publishing():
    job = _smoke_job()
    needs = job.get("needs")
    needs = [needs] if isinstance(needs, str) else list(needs or [])
    assert "build" in needs, "проверка прода — после публикации образа, а не до"
    assert job.get("permissions", {}).get("actions") == "write"
    assert "refs/heads/main" in str(job.get("if", "")), "только сборка main выкатывается"
    run = " ".join(str(s.get("run", "")) for s in job["steps"])
    assert "gh workflow run prod-smoke.yml" in run
    assert "--ref main" in run, "код проверки — с main, не из ожидаемого коммита"
    assert 'expect_commit="$GITHUB_SHA"' in run, "ждать в /health надо именно этот коммит"


def test_the_smoke_is_not_also_waiting_on_workflow_run():
    """Второй триггер дал бы двойной прогон одного выпуска, а при
    cancel-in-progress — снятый нужный прогон."""
    triggers = _load(SMOKE)["on"]
    assert "workflow_run" not in triggers
    assert set(triggers) == {"workflow_dispatch"}
    inputs = triggers["workflow_dispatch"]["inputs"]
    assert "expect_commit" in inputs


def test_the_smoke_reads_the_expected_commit_from_the_dispatch():
    job = _load(SMOKE)["jobs"]["smoke"]
    assert job["env"]["EXPECT_COMMIT"] == "${{ github.event.inputs.expect_commit }}"
    assert "workflow_run" not in SMOKE.read_text(encoding="utf-8").split("\njobs:", 1)[1]
