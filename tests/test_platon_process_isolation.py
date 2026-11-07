"""Synthetic checks of Platon state shared by independent Python processes."""
from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import subprocess
import sys

import agent_access
import site_chat_access


ROOT = Path(__file__).resolve().parents[1]
TRACE = "0123456789abcdef" * 2
KEY = "synthetic-process-owner-key"
GROUP = -10012345
PROJECT = "Synthetic Process Project"


def _child(code, directory):
    return subprocess.run(
        [sys.executable, "-c", code, str(directory)], cwd=ROOT,
        env={**os.environ, "PYTHONPATH": str(ROOT)}, capture_output=True,
        text=True, check=True, timeout=30,
    ).stdout.strip()


def test_signing_key_is_atomic_and_shared_by_independent_processes(tmp_path):
    code = """
from pathlib import Path
import sys
import agent_access
print(agent_access.digest(Path(sys.argv[1]), 'synthetic-process-owner'))
"""
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: _child(code, tmp_path), range(8)))
    assert len(set(results)) == 1
    assert results[0] == agent_access.digest(tmp_path, "synthetic-process-owner")
    key = tmp_path / ".owner-signing-key"
    assert len(key.read_bytes()) == 32
    assert key.stat().st_mode & 0o777 == 0o600


def test_only_one_process_can_claim_the_same_run(tmp_path):
    code = """
from pathlib import Path
import sys
from fastapi import HTTPException
import agent_access
try:
    agent_access.claim(Path(sys.argv[1]), '0123456789abcdef' * 2,
                       agent_access.Actor('synthetic-owner', 'web', False, 'public'))
    print('claimed')
except HTTPException as error:
    assert error.status_code == 409
    print('conflict')
"""
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: _child(code, tmp_path), range(8)))
    assert results.count("claimed") == 1
    assert results.count("conflict") == 7
    metadata = agent_access.load(tmp_path, TRACE)
    assert metadata == agent_access.Actor("synthetic-owner", "web", False, "public").metadata()
    assert (tmp_path / ("access_" + TRACE + ".json")).stat().st_mode & 0o777 == 0o600


def _read_grant(directory, key=KEY):
    code = f"""
from pathlib import Path
import sys
import site_chat_access
try:
    with site_chat_access.access(Path(sys.argv[1]) / 'grants.json', {key!r},
                                {GROUP}, 'sales:reply', {PROJECT!r}) as project:
        print(project)
except site_chat_access.AccessDenied:
    print('denied')
"""
    return _child(code, directory)


def test_another_process_observes_group_revocation(tmp_path):
    path = tmp_path / "grants.json"
    site_chat_access.authorize(path, KEY, GROUP, PROJECT)
    assert _read_grant(tmp_path) == PROJECT
    site_chat_access.revoke(path, GROUP, PROJECT)
    assert _read_grant(tmp_path) == "denied"
    assert KEY.encode() not in path.read_bytes()


def test_rotation_observed_by_another_process_retires_old_grants(tmp_path):
    path = tmp_path / "grants.json"
    site_chat_access.authorize(path, KEY, GROUP, PROJECT)
    assert _read_grant(tmp_path) == PROJECT
    assert _read_grant(tmp_path, "synthetic-rotated-process-key") == "denied"
    assert _read_grant(tmp_path) == "denied"
    assert KEY.encode() not in path.read_bytes()
