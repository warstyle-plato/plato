from pathlib import Path

from telegram_user_registry import Registry


def test_registry_tracks_users(tmp_path: Path):
    registry = Registry(tmp_path / "users.sqlite3")
    registry.touch({"id": 1, "username": "alpha", "first_name": "A"}, 1, "message", command="/start")
    registry.touch({"id": 1}, 1, "callback", platon=1)
    registry.touch({"id": 2, "first_name": "B"}, 2, "message")

    assert len(registry.list()) == 2
    first = registry.get(1)
    assert first is not None
    assert first["messages"] == 1
    assert first["callbacks"] == 1
    assert first["platon_requests"] == 1
    assert registry.stats()[0] == 2
