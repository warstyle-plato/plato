from __future__ import annotations

from pathlib import Path


def test_preview_deploy_isolated_from_production() -> None:
    script = Path("deploy-market-preview.sh").read_text(encoding="utf-8")
    assert "PORT=${MARKET_PREVIEW_PORT:-8081}" in script
    assert "developaid-market-preview" in script
    assert "--workers 1" in script
    assert "TELEGRAM_BOT_TOKEN=" in script
    assert "TELEGRAM_WEBHOOK_ENABLED=0" in script
    assert "docker build" not in script
    assert "PORT=${APP_PORT" not in script


def test_preview_health_json_is_passed_as_data_not_python_stdin() -> None:
    script = Path("deploy-market-preview.sh").read_text(encoding="utf-8")
    assert 'json.loads(sys.argv[2])' in script
    assert 'json.load(sys.stdin)' not in script.split("health_check()", 1)[1].split("route_check()", 1)[0]


def test_preview_workflow_builds_in_github_and_pushes_to_registry() -> None:
    workflow = Path(".github/workflows/market-preview.yml").read_text(encoding="utf-8")
    assert "python -m pip install -r requirements-dev.txt" in workflow
    assert "docker/build-push-action@v6" in workflow
    assert "cr.yandex/" in workflow
    assert "INSTALL_BROWSER=0" in workflow
    assert "deploy-market-preview.sh" in workflow
