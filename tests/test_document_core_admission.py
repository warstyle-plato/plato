"""Synthetic owner configuration, without sources, providers or rollout claims."""
import email.message
import errno
import fcntl
import hashlib
import json
import os
from pathlib import Path
import stat

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

import document_core_admission as config
import document_intake_protocol as protocol

TARGET = "https://developaid.ru"
COMMIT = "c" * 40
VERSION = "0.0.synthetic"


def raw_config(flag=True, **changes):
    value = {"schema": 1, "origin": TARGET, "protocol": protocol.PROTOCOL,
             "core_commit": "a" * 40, "completed_rollout": flag}
    value.update(changes)
    return json.dumps(value).encode()


def headers(*, digest=None, length=None):
    result = [(b"host", b"developaid.ru"), (b"x-developaid-admin-key", b"synthetic-owner"),
        (b"content-type", b"application/json"), (b"x-developaid-expected-commit", COMMIT.encode()),
        (b"x-developaid-expected-version", VERSION.encode())]
    result.append((b"if-none-match", b"*") if digest is None else
                  (b"if-match", ('"' + digest + '"').encode()))
    if length is not None:
        result.append((b"content-length", str(length).encode()))
    return result


def owner(key):
    if key != "synthetic-owner":
        raise HTTPException(403, "owner required")


def prepare(**changes):
    values = dict(raw_headers=headers(), require_admin=owner, environ={}, scheme="https", query="",
                  local_mode="", local_commit=COMMIT, local_version=VERSION)
    values.update(changes)
    return config.preflight(**values)


@pytest.fixture
def root(tmp_path):
    value = tmp_path / "data"
    value.mkdir(mode=0o700)
    return value


def store(root, flag=True, digest=None):
    return config.store(prepare(raw_headers=headers(digest=digest)), raw_config(flag),
                        root=root, target=TARGET, environ={})


def test_false_is_durable_HOLD_and_valid_CAS_state_for_explicit_reenable(root):
    first = store(root, False)
    raw = (root / config.FILENAME).read_bytes()
    assert json.loads(raw)["completed_rollout"] is False
    assert first == {"schema": 1, "stored": True, "sha256": hashlib.sha256(raw).hexdigest()}
    for _ in range(2):
        original = config.admission_raw({}, root, TARGET)
        assert original.encode() == raw
        with pytest.raises(protocol.ProtocolHold):
            protocol.admitted_origin(original, TARGET)
    second = store(root, True, first["sha256"])
    positive = config.admission_raw({}, root, TARGET)
    assert protocol.admitted_origin(positive, TARGET) == TARGET
    assert json.loads(positive)["core_commit"] == "a" * 40  # no current-release equality
    assert second["sha256"] != first["sha256"]
    info = (root / config.FILENAME).stat()
    assert stat.S_IMODE(info.st_mode) == 0o600 and info.st_nlink == 1


@pytest.mark.parametrize("flag", [True, False])
@pytest.mark.parametrize("changes", [
    {"schema": True}, {"schema": 1.0}, {"schema": "1"}, {"protocol": "old"},
    {"core_commit": "A" * 40}, {"core_commit": None}, {"origin": TARGET + "/"},
    {"origin": "https://plato-development-investment-model.onrender.com"},
    {"completed_rollout": 0}, {"completed_rollout": 1}, {"completed_rollout": None},
    {"completed_rollout": "false"}, {"extra": False}])
def test_positive_and_negative_config_reject_type_or_scope_substitutions(flag, changes):
    with pytest.raises(config.ConfigHold):
        config.validate(raw_config(flag, **changes), TARGET)


@pytest.mark.parametrize("raw", [b"", b"[]", b"\xff", b"x" * 4097,
    raw_config().replace(b'"schema": 1', b'"schema": 1,"schema": 1'),
    raw_config().replace(b'"schema": 1', b'"schema": NaN')])
def test_closed_parser_rejects_ambiguous_or_unbounded_bytes(raw):
    with pytest.raises(config.ConfigHold):
        config.validate(raw, TARGET)


@pytest.mark.parametrize("target", ["https://internal.invalid", "http://developaid.ru",
    "https://127.0.0.1", "https://developaid.ru:444", "https://user@developaid.ru",
    TARGET + "?x=1", TARGET + "#x"])
def test_stored_origin_never_replaces_an_unknown_or_incompatible_loaded_base(target):
    with pytest.raises(config.ConfigHold):
        config.validate(raw_config(False), target)


@pytest.mark.parametrize("value", ["", "{}", raw_config().decode(), raw_config(False).decode()])
def test_env_presence_never_reads_or_overrides_file(root, monkeypatch, value):
    env = {protocol.ADMISSION_ENV: value}
    monkeypatch.setattr(config, "_open_root", lambda *a: pytest.fail("env must precede file IO"))
    assert config.admission_raw(env, root, TARGET) == value
    with pytest.raises(config.ConfigHold, match="Настройка") as error:
        config.store(prepare(), raw_config(False), root=root, target=TARGET, environ=env)
    assert error.value.code == "environment_has_priority"
    with pytest.raises(config.ConfigHold) as error:
        prepare(environ=env)
    assert error.value.code == "environment_has_priority"


def test_env_disappearing_after_presence_check_is_HOLD_without_file_fallback(root, monkeypatch):
    class Changed(dict):
        def __contains__(self, key):
            return True
        def __getitem__(self, key):
            raise KeyError(key)
    monkeypatch.setattr(config, "_open_root", lambda *a: pytest.fail("no fallback after env drift"))
    with pytest.raises(protocol.ProtocolHold):
        config.admission_raw(Changed(), root, TARGET)


@pytest.mark.parametrize("kind", ["symlink", "fifo", "hardlink", "permissions", "oversize", "malformed", "other_origin"])
def test_unsafe_or_invalid_existing_state_is_never_repaired_or_replaced(root, kind):
    path = root / config.FILENAME
    if kind == "fifo":
        os.mkfifo(path, 0o600)
    elif kind == "symlink":
        target = root / "private-target"
        target.write_bytes(raw_config())
        target.chmod(0o600)
        path.symlink_to(target)
    else:
        path.write_bytes(b"x" * 4097 if kind == "oversize" else b"{}" if kind == "malformed" else
            raw_config(origin="https://plato-development-investment-model.onrender.com") if kind == "other_origin"
            else raw_config())
        path.chmod(0o644 if kind == "permissions" else 0o600)
        if kind == "hardlink":
            os.link(path, root / "other-link")
    before = path.lstat()
    with pytest.raises(protocol.ProtocolHold):
        config.admission_raw({}, root, TARGET)
    with pytest.raises(config.ConfigHold):
        store(root, False, "0" * 64)
    after = path.lstat()
    assert (after.st_ino, after.st_mode, after.st_nlink, after.st_size) == (
        before.st_ino, before.st_mode, before.st_nlink, before.st_size)


def test_unsafe_root_symlink_or_shared_mode_stays_HOLD_without_repair(root):
    root.chmod(0o777)
    with pytest.raises(config.ConfigHold):
        store(root)
    assert stat.S_IMODE(root.stat().st_mode) == 0o777 and not list(root.iterdir())
    root.chmod(0o700)
    link = root.parent / "data-link"
    link.symlink_to(root, target_is_directory=True)
    with pytest.raises(config.ConfigHold):
        store(link)
    assert not list(root.iterdir())


def test_changed_named_file_during_read_is_HOLD(root, monkeypatch):
    store(root)
    read = config.os.read
    replaced = False
    def change(fd, count):
        nonlocal replaced
        result = read(fd, count)
        if not replaced:
            replaced = True
            replacement = root / "replacement"
            replacement.write_bytes(raw_config(False)); replacement.chmod(0o600)
            replacement.replace(root / config.FILENAME)
        return result
    monkeypatch.setattr(config.os, "read", change)
    with pytest.raises(protocol.ProtocolHold):
        config.admission_raw({}, root, TARGET)


def test_CAS_and_busy_lock_preserve_current_config(root):
    first = store(root)
    original = (root / config.FILENAME).read_bytes()
    with pytest.raises(config.ConfigHold) as error:
        store(root, False)
    assert error.value.code == "configuration_conflict"
    fd = os.open(root / config.LOCKNAME, os.O_RDWR)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(config.ConfigHold) as error:
            store(root, False, first["sha256"])
        assert error.value.code == "configuration_busy"
    finally:
        os.close(fd)
    assert (root / config.FILENAME).read_bytes() == original


def test_EXCL_temp_collision_cannot_delete_an_existing_file(root, monkeypatch):
    monkeypatch.setattr(config.secrets, "token_hex", lambda _: "0" * 32)
    path = root / (".document_core_admission." + "0" * 32 + ".tmp")
    path.write_bytes(b"synthetic-existing-private-control")
    path.chmod(0o600)
    before = path.stat()
    with pytest.raises(config.ConfigHold):
        store(root)
    assert path.stat().st_ino == before.st_ino
    assert path.read_bytes() == b"synthetic-existing-private-control"
    assert not (root / config.FILENAME).exists()


def test_after_publication_sync_failure_is_unknown_without_rollback_or_retry(root, monkeypatch):
    sync = config.os.fsync
    def fail_directory(fd):
        if stat.S_ISDIR(os.fstat(fd).st_mode):
            raise OSError("synthetic directory sync failure")
        return sync(fd)
    monkeypatch.setattr(config.os, "fsync", fail_directory)
    with pytest.raises(config.ConfigHold) as error:
        store(root, False)
    assert error.value.code == "publication_unknown"
    assert json.loads((root / config.FILENAME).read_bytes())["completed_rollout"] is False
    with pytest.raises(protocol.ProtocolHold):
        protocol.admitted_origin(config.admission_raw({}, root, TARGET), TARGET)


@pytest.mark.parametrize("initial", [True, False])
@pytest.mark.parametrize("committed", [True, False])
def test_namespace_error_is_unknown_without_retry_or_cleanup(root, monkeypatch, initial, committed):
    receipt = None if initial else store(root, False)
    before = None if initial else (root / config.FILENAME).read_bytes()
    operation = config.os.link if initial else config.os.replace
    attempts, cleanup = [], []
    unlink = config.os.unlink
    def ambiguous(*args, **kwargs):
        attempts.append("one namespace attempt")
        if committed:
            operation(*args, **kwargs)
        raise OSError(errno.EIO, "synthetic ambiguous namespace error")
    def watched_unlink(*args, **kwargs):
        cleanup.append("unlink")
        return unlink(*args, **kwargs)
    monkeypatch.setattr(config.os, "link" if initial else "replace", ambiguous)
    monkeypatch.setattr(config.os, "unlink", watched_unlink)
    with pytest.raises(config.ConfigHold) as error:
        store(root, True, None if initial else receipt["sha256"])
    assert error.value.code == "publication_unknown"
    assert "Не повторяйте запись" in str(error.value)
    assert "не применена" not in str(error.value)
    assert attempts == ["one namespace attempt"] and cleanup == []
    if committed:
        assert json.loads((root / config.FILENAME).read_bytes())["completed_rollout"] is True
    elif before is None:
        assert not (root / config.FILENAME).exists()
    else:
        assert (root / config.FILENAME).read_bytes() == before
    if initial or not committed:
        assert len(list(root.glob(".document_core_admission.*.tmp"))) == 1


@pytest.mark.parametrize("initial", [True, False])
def test_known_file_sync_failure_is_prepublication_and_preserves_config(root, monkeypatch, initial):
    receipt = None if initial else store(root, False)
    before = None if initial else (root / config.FILENAME).read_bytes()
    def no_namespace(*args, **kwargs):
        pytest.fail("known file-sync failure must precede namespace publication")
    def fail_file_sync(fd):
        assert stat.S_ISREG(os.fstat(fd).st_mode)
        raise OSError(errno.EIO, "synthetic file-sync failure")
    monkeypatch.setattr(config.os, "fsync", fail_file_sync)
    monkeypatch.setattr(config.os, "link", no_namespace)
    monkeypatch.setattr(config.os, "replace", no_namespace)
    with pytest.raises(config.ConfigHold) as error:
        store(root, True, None if initial else receipt["sha256"])
    assert error.value.code == "configuration_hold" and "не применена" in str(error.value)
    assert not list(root.glob(".document_core_admission.*.tmp"))
    if before is None:
        assert not (root / config.FILENAME).exists()
    else:
        assert (root / config.FILENAME).read_bytes() == before


def test_direct_store_without_native_preflight_has_no_IO(root, monkeypatch):
    monkeypatch.setattr(config, "_open_root", lambda *a: pytest.fail("unauthorized IO"))
    with pytest.raises(config.ConfigHold) as error:
        config.store(None, raw_config(), root=root, target=TARGET, environ={})
    assert error.value.status == 403


@pytest.fixture
def native(root, monkeypatch):
    import main
    core = main.core
    monkeypatch.setenv("DEVELOPAID_ADMIN_KEY", "synthetic-owner")
    monkeypatch.delenv(protocol.ADMISSION_ENV, raising=False)
    monkeypatch.setattr(core, "_DOCUMENT_CORE_ADMISSION_ROOT", root)
    monkeypatch.setattr(core, "_TELEGRAM_WEB_APP_BASE_URL", TARGET)
    monkeypatch.setattr(core, "_MO_CALC_API_URL", "")
    monkeypatch.setattr(core, "COMMIT", COMMIT)
    monkeypatch.setattr(core, "VERSION", VERSION)
    def forbidden(*a, **k):
        pytest.fail("config route must not enter owner salt, queue, session or provider IO")
    monkeypatch.setattr(core._agent_access, "browser_owner", forbidden)
    monkeypatch.setattr(core, "_telegram_session", forbidden)
    monkeypatch.setattr(core, "_intake_queue_directory", forbidden)
    client = TestClient(main.app, base_url=TARGET)
    return core, client, root


def http_headers(**changes):
    value = {key.decode(): val.decode() for key, val in headers()}
    value.update(changes)
    return value


def test_native_owner_POST_stores_only_closed_config_before_owner_middleware(native):
    _, client, root = native
    reply = client.post(config.PATH, headers=http_headers(), content=raw_config(False))
    assert reply.status_code == 200
    assert set(reply.json()) == {"schema", "stored", "sha256"}
    assert reply.headers["cache-control"] == "private, no-store"
    assert "set-cookie" not in reply.headers
    assert json.loads((root / config.FILENAME).read_bytes())["completed_rollout"] is False
    assert sorted(p.name for p in root.iterdir()) == [config.LOCKNAME, config.FILENAME]


@pytest.mark.parametrize("change", ["wrong", "missing", "unconfigured"])
def test_native_owner_key_is_required_even_without_bot_configuration(native, monkeypatch, change):
    _, client, root = native
    values = http_headers()
    if change == "missing":
        del values["x-developaid-admin-key"]
    else:
        values["x-developaid-admin-key"] = "wrong" if change == "wrong" else "synthetic-owner"
    if change == "unconfigured":
        monkeypatch.delenv("DEVELOPAID_ADMIN_KEY")
    reply = client.post(config.PATH, headers=values, content=raw_config(),
                        cookies={"plato_owner": "synthetic-cookie"})
    assert reply.status_code == 403 and not list(root.iterdir())
    assert "set-cookie" not in reply.headers


@pytest.mark.parametrize("name", sorted(config._SECURITY_HEADERS))
def test_raw_duplicate_security_headers_never_reach_file_or_owner_IO(native, name):
    _, client, root = native
    values = list(http_headers().items())
    sample = dict(values).get(name, "synthetic")
    if name not in dict(values):
        values.append((name, sample))
    values.append((name, sample))
    reply = client.post(config.PATH, headers=values, content=raw_config())
    assert reply.status_code in {400, 403} and not list(root.iterdir())


@pytest.mark.parametrize("changes,status", [
    ({"origin": "null"}, 403), ({"origin": "https://other.invalid"}, 403),
    ({"sec-fetch-site": "cross-site"}, 403), ({"sec-fetch-site": "same-site"}, 403),
    ({"host": "plato-development-investment-model.onrender.com", "x-forwarded-host": "developaid.ru"}, 409),
    ({"x-developaid-expected-commit": "d" * 40}, 409),
    ({"x-developaid-expected-version": "0.0.other"}, 409),
    ({"content-type": "text/plain"}, 415), ({"content-encoding": "gzip"}, 415),
    ({"if-match": '"' + "0" * 64 + '"'}, 428)])
def test_native_closed_realm_runtime_and_request_preconditions_hold_before_IO(native, changes, status):
    _, client, root = native
    reply = client.post(config.PATH, headers=http_headers(**changes), content=raw_config())
    assert reply.status_code == status and not list(root.iterdir())


def test_native_http_transport_retains_explicit_owner_authority_and_query_HOLD(native):
    _, client, root = native
    reply = client.post("http://developaid.ru" + config.PATH,
        headers=http_headers(**{"x-forwarded-proto": "https", "x-forwarded-for": "203.0.113.7:1234"}),
        content=raw_config(False))
    assert reply.status_code == 200 and reply.json()["stored"] is True
    before = (root / config.FILENAME).read_bytes()
    assert json.loads(before)["completed_rollout"] is False
    reply = client.post(config.PATH + "?path=elsewhere", headers=http_headers(), content=raw_config())
    assert reply.status_code == 409 and (root / config.FILENAME).read_bytes() == before


@pytest.mark.parametrize("scheme", [None, "", "ftp", "ws", "wss", "HTTPS", 1, True, [], {}])
def test_malformed_or_other_backend_transport_remains_HOLD(scheme):
    with pytest.raises(config.ConfigHold) as error:
        prepare(scheme=scheme)
    assert error.value.code == "core_realm"


@pytest.mark.parametrize("change", ["missing", "wrong", "unconfigured"])
def test_native_http_and_forwarded_claims_never_replace_owner_key(native, monkeypatch, change):
    _, client, root = native
    values = http_headers(**{"x-forwarded-proto": "https", "x-forwarded-for": "127.0.0.1:1234"})
    if change == "missing":
        del values["x-developaid-admin-key"]
    elif change == "wrong":
        values["x-developaid-admin-key"] = "wrong"
    else:
        monkeypatch.delenv("DEVELOPAID_ADMIN_KEY")
    reply = client.post("http://developaid.ru" + config.PATH, headers=values, content=raw_config())
    assert reply.status_code == 403 and not list(root.iterdir())


@pytest.mark.parametrize("changes,status", [
    ({"host": "other.invalid", "x-forwarded-host": "developaid.ru"}, 409),
    ({"origin": "https://other.invalid"}, 403), ({"sec-fetch-site": "cross-site"}, 403),
    ({"x-developaid-expected-commit": "d" * 40}, 409),
    ({"x-developaid-expected-version": "other"}, 409),
    ({"content-type": "text/plain"}, 415), ({"if-match": '"' + "0" * 64 + '"'}, 428)])
def test_native_http_keeps_target_CSRF_runtime_body_and_CAS_preconditions(native, changes, status):
    _, client, root = native
    reply = client.post("http://developaid.ru" + config.PATH,
                        headers=http_headers(**changes), content=raw_config())
    assert reply.status_code == status and not list(root.iterdir())


@pytest.mark.parametrize("mode,commit", [(None, COMMIT), ("https://core.invalid/mo/calculate", COMMIT), ("", "")])
def test_unknown_or_remote_local_mode_and_unknown_commit_hold(native, monkeypatch, mode, commit):
    core, client, root = native
    monkeypatch.setattr(core, "_MO_CALC_API_URL", mode)
    monkeypatch.setattr(core, "COMMIT", commit)
    reply = client.post(config.PATH, headers=http_headers(), content=raw_config())
    assert reply.status_code == 409 and not list(root.iterdir())


@pytest.mark.parametrize("body,status", [(b"\xff", 422), (b"{}", 422),
    (raw_config().replace(b'"schema": 1', b'"schema": 1,"schema": 1'), 422),
    (raw_config().replace(b'"schema": 1', b'"schema": NaN'), 422), (b"x" * 4097, 413)])
def test_native_body_refusals_are_bounded_named_and_leave_no_files(native, body, status):
    _, client, root = native
    reply = client.post(config.PATH, headers=http_headers(), content=body)
    assert reply.status_code == status and not list(root.iterdir())
    assert set(reply.json()["detail"]) == {"code", "message"}
    assert "NaN" not in reply.text and "synthetic-owner" not in reply.text


def test_false_file_qualified_emitter_holds_before_capability_or_signing(native, monkeypatch):
    core, _, root = native
    store(root, False)
    monkeypatch.setattr(core.urllib.request, "build_opener", lambda *a: pytest.fail("false is HOLD before network"))
    with pytest.raises(protocol.ProtocolHold):
        core._telegram_web_app_url(17, [], calc_overrides={"_intake_qualification": {}})


def test_native_file_and_env_emitters_keep_current_capability_and_stable_initial_evidence(native, monkeypatch):
    import io
    core, _, root = native
    receipt = store(root)
    calls = []
    class Reply(io.BytesIO):
        status = 200
        def __init__(self, url):
            super().__init__(json.dumps(protocol.capability()).encode())
            self.url = url
            self.headers = email.message.Message()
            self.headers["Content-Type"] = "application/json"
        def geturl(self):
            return self.url
    def open_(request, timeout):
        assert timeout == 5 and request.data is None
        assert not any(k.lower() in {"authorization", "cookie"} for k in request.headers)
        calls.append(request.full_url)
        return Reply(request.full_url)
    monkeypatch.setattr(core.urllib.request, "build_opener", lambda *a:
        type("MemoryOpener", (), {"open": staticmethod(open_), "close": lambda self: None})())
    assert core._telegram_document_target() == TARGET
    monkeypatch.setattr(core, "COMMIT", "d" * 40)  # unrelated later compatible release
    assert core._telegram_document_target() == TARGET
    store(root, False, receipt["sha256"])
    monkeypatch.setenv(protocol.ADMISSION_ENV, raw_config().decode())
    assert core._telegram_document_target() == TARGET  # ENV priority over false file
    monkeypatch.setenv(protocol.ADMISSION_ENV, "")
    with pytest.raises(protocol.ProtocolHold):
        core._telegram_document_target()  # empty ENV never falls back
    assert calls == [TARGET + protocol.CAPABILITY_PATH] * 3


def test_data_root_matches_health_rule_without_using_market_DATA_DIR(tmp_path):
    assert config.data_root({"DEVELOPAID_DATA_DIR": str(tmp_path), "DATA_DIR": "/ignored"}) == tmp_path
    assert config.data_root({"DATA_DIR": "/ignored"}) == Path.cwd() / "data"


@pytest.mark.parametrize("value", ["../outside", "/synthetic/\x00invalid"])
def test_data_root_alias_or_malformed_path_is_HOLD_without_normalizing_it(value):
    root = config.data_root({"DEVELOPAID_DATA_DIR": value})
    with pytest.raises(config.ConfigHold):
        config._open_root(root)
