"""Operational boundary checks use synthetic configuration and temporary files."""
from datetime import datetime, timedelta, timezone
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest


@pytest.fixture
def operations(monkeypatch):
    directory = Path(__file__).resolve().parents[3] / "scripts"
    monkeypatch.syspath_prepend(str(directory))
    def load(name):
        spec = importlib.util.spec_from_file_location(name, directory / (name + ".py"))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    return SimpleNamespace(watchdog=load("run_watchdog"), backup=load("backup_local"))


def test_watchdog_only_notifies_changes_and_initial_failure(tmp_path, operations):
    watchdog = operations.watchdog
    notifications = []
    def notify(status):
        notifications.append(status)
        return "submitted"
    healthy = {"api": "healthy", "database": "healthy", "monitor": "fresh"}
    assert not watchdog.record_check(tmp_path, healthy, notify=True, notification=notify)[0]
    assert not watchdog.record_check(tmp_path, healthy, notify=True, notification=notify)[0]
    failed = healthy | {"monitor": "stale"}
    assert watchdog.record_check(tmp_path, failed, notify=True, notification=notify)[0]
    assert not watchdog.record_check(tmp_path, failed, notify=True, notification=notify)[0]
    assert watchdog.record_check(tmp_path, healthy, notify=True, notification=notify)[0]
    assert notifications == [failed, healthy]
    assert len((tmp_path / "changes.jsonl").read_text().splitlines()) == 2
    assert (tmp_path / "state.json").stat().st_mode & 0o777 == 0o600


def test_watchdog_restart_retains_failure_without_duplicate_notification(tmp_path, operations):
    failed = {"api": "unreachable", "database": "unreachable", "monitor": "unknown"}
    calls = []
    notify = lambda status: calls.append(status) or "failed"
    assert operations.watchdog.record_check(tmp_path, failed, notify=True, notification=notify)[0]
    assert not operations.watchdog.record_check(tmp_path, failed, notify=True, notification=notify)[0]
    assert len(calls) == 1
    assert json.loads((tmp_path / "state.json").read_text())["notification"] == "failed"


@pytest.mark.parametrize("url", [
    "postgresql+psycopg://postgres:synthetic@127.0.0.1:55432/pipeguard",
    "postgresql+psycopg://pipeguard_watchdog:synthetic@example.com:55432/pipeguard",
    "postgresql+psycopg://pipeguard_watchdog:synthetic@127.0.0.1:55432/airflow",
    "postgresql+psycopg://pipeguard_watchdog:synthetic@127.0.0.1:55432/pipeguard?sslmode=disable",
    "postgresql+psycopg://pipeguard_api:synthetic@127.0.0.1:55432/pipeguard",
])
def test_watchdog_rejects_wrong_database_or_privileged_connection(operations, url):
    with pytest.raises(ValueError):
        operations.watchdog.database_parameters(url)


@pytest.mark.parametrize("age,unmonitored,stale,expected", [
    (0, 0, 0, "fresh"), (89, 0, 0, "fresh"), (90, 0, 0, "stale"),
    (-1, 0, 0, "stale"), (0, 1, 0, "unmonitored"), (0, 0, 1, "stale"),
])
def test_watchdog_checks_global_and_individual_heartbeats(operations, monkeypatch, age, unmonitored, stale, expected):
    now = datetime.now(timezone.utc)
    class Connection:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def execute(self, *args): return self
        def fetchone(self): return now, now-timedelta(seconds=age), unmonitored, stale
    monkeypatch.setattr(operations.watchdog.psycopg, "connect", lambda **kwargs: Connection())
    assert operations.watchdog.database_status({}) == {"database": "healthy", "monitor": expected}


def test_watchdog_db_failure_does_not_claim_monitor_fresh(operations, monkeypatch):
    def unavailable(**kwargs): raise RuntimeError("SYNTHETIC_PRIVATE_CREDENTIAL")
    monkeypatch.setattr(operations.watchdog.psycopg, "connect", unavailable)
    assert operations.watchdog.database_status({}) == {"database": "unreachable", "monitor": "unknown"}


def test_backup_rejects_tampered_archive_before_creating_database(tmp_path, operations, monkeypatch):
    backup = operations.backup
    monkeypatch.setattr(backup, "ROOT", tmp_path)
    identity = str(uuid4())
    directory = tmp_path / "data/local/backups" / identity
    directory.mkdir(parents=True)
    (directory / "database.dump").write_bytes(b"original")
    (directory / "database.dump").chmod(0o600)
    manifest = {"version": 1, "backup_id": identity, "database": "pipeguard", "schemas": ["public"],
                "archive_sha256": backup.file_hash(directory / "database.dump"), "tables": []}
    (directory / "manifest.json").write_text(json.dumps(manifest))
    (directory / "manifest.json").chmod(0o600)
    (directory / "database.dump").write_bytes(b"modified")
    monkeypatch.setattr(backup.psycopg, "connect", lambda **kwargs: pytest.fail("must reject before connecting"))
    with pytest.raises(ValueError, match="checksum"):
        backup.verify(identity)


def test_backup_rejects_non_uuid_or_outside_backup_identity(operations):
    for identity in ("pipeguard", "../pipeguard", "postgres", "--clean"):
        with pytest.raises(ValueError):
            operations.backup.load_manifest(identity)


def test_watchdog_rejects_public_journal(tmp_path, operations):
    journal = tmp_path / 'changes.jsonl'
    journal.write_text('private history\n')
    journal.chmod(0o644)
    with pytest.raises(ValueError, match='owner-private'):
        operations.watchdog.record_check(tmp_path, {'api': 'unreachable'})
    assert journal.read_text() == 'private history\n'


def test_watchdog_rejects_symlink_journal(tmp_path, operations):
    destination = tmp_path / 'elsewhere'
    destination.write_text('unchanged')
    (tmp_path / 'changes.jsonl').symlink_to(destination)
    with pytest.raises(OSError):
        operations.watchdog.record_check(tmp_path, {'api': 'unreachable'})
    assert destination.read_text() == 'unchanged'


def test_watchdog_rotates_bounded_journal(tmp_path, operations):
    journal = tmp_path / 'changes.jsonl'
    journal.write_bytes(b'x' * (1024 * 1024))
    journal.chmod(0o600)
    operations.watchdog.record_check(tmp_path, {'api': 'unreachable'})
    assert (tmp_path / 'changes.previous.jsonl').stat().st_size == 1024 * 1024
    assert journal.stat().st_size < 4096
    assert journal.stat().st_mode & 0o777 == 0o600


def test_restore_attempt_cannot_race_active_check(tmp_path, operations, monkeypatch):
    import fcntl
    backup = operations.backup
    monkeypatch.setattr(backup, 'load_manifest', lambda identity: (tmp_path, None, {}))
    lock = tmp_path / 'restore.lock'
    lock.touch(mode=0o600)
    with lock.open('r+') as held:
        fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(BlockingIOError):
            backup.cleanup(str(uuid4()))
    assert lock.exists()


def test_restore_cleanup_refuses_unmarked_database(operations):
    class Administrator:
        def execute(self, query, parameters=None):
            assert parameters == ('pipeguard_restore_check_' + 'a' * 32,)
            return self
        def fetchone(self):
            return ('postgres', None)
    with pytest.raises(RuntimeError, match='marker'):
        operations.backup.drop_owned_check(Administrator(), 'pipeguard_restore_check_' + 'a' * 32,
                                          'pipeguard_restore_check:v1:' + str(uuid4()) + ':' + 'b' * 32)


def test_restore_cleanup_uses_shared_database_comment_catalog(operations):
    name = 'pipeguard_restore_check_' + 'a' * 32
    marker = 'pipeguard_restore_check:v1:' + str(uuid4()) + ':' + 'b' * 32
    calls = []
    class Administrator:
        def execute(self, query, parameters=None):
            calls.append(query)
            if parameters:
                assert 'shobj_description' in query
                assert parameters == (name,)
            return self
        def fetchone(self):
            return ('postgres', marker)
    assert operations.backup.drop_owned_check(Administrator(), name, marker)
    assert len(calls) == 2


def test_restore_inspection_does_not_claim_orphan_is_active(operations, monkeypatch):
    class Administrator:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def execute(self, *args): return self
        def fetchall(self): return [('pipeguard_restore_check_' + 'a' * 32, 'postgres', None)]
    monkeypatch.setattr(operations.backup, 'parameters', lambda database: {})
    monkeypatch.setattr(operations.backup.psycopg, 'connect', lambda **kwargs: Administrator())
    record = operations.backup.inspect_checks()[0]
    assert record['requires_review'] and not record['tool_owned']
    assert 'active_check' not in record


@pytest.mark.parametrize('increment,last,called,bound,safe', [
    (1, 10, True, 10, True), (1, 10, False, 10, False),
    (1, 9, True, 10, False), (-1, -10, True, -10, True),
    (-1, -9, True, -10, False), (1, 1, False, None, True),
])
def test_restored_sequence_must_advance_beyond_restored_rows(operations, increment, last, called, bound, safe):
    sequence = ('public', 'items_id_seq', increment, -100, 100, False,
                'public', 'items', 'id', 'integer', '', "nextval('items_id_seq'::regclass)", True)
    class Connection:
        def __init__(self): self.values = iter([(last, called), (bound,)])
        def execute(self, *args): return self
        def fetchall(self): return [sequence]
        def fetchone(self): return next(self.values)
    if safe:
        result = operations.backup.sequence_safety(Connection(), ['public'])
        assert result['checked'] == 1 and not result['unsupported']
        assert not result['source_sequence_position_compared']
    else:
        with pytest.raises(RuntimeError, match='collide'):
            operations.backup.sequence_safety(Connection(), ['public'])


@pytest.mark.parametrize('change,reason', [
    ({5: True}, 'cycling_sequence'), ({6: None, 7: None, 8: None}, 'unowned_sequence'),
    ({9: 'numeric'}, 'non_integer_owner_column'), ({12: False}, 'custom_owner_default'),
    ({6: 'outside'}, 'owner_outside_backup_scope'),
])
def test_uncertain_sequence_shapes_are_reported_as_unsupported(operations, change, reason):
    sequence = ['public', 'items_id_seq', 1, 1, 100, False,
                'public', 'items', 'id', 'integer', '', "nextval('items_id_seq'::regclass)", True]
    for position, value in change.items(): sequence[position] = value
    class Connection:
        def execute(self, *args): return self
        def fetchall(self): return [sequence]
        def fetchone(self): pytest.fail('unsupported sequence must not be claimed checked')
    result = operations.backup.sequence_safety(Connection(), ['public'])
    assert result['checked'] == 0 and result['unsupported'][0]['reason'] == reason


def test_exhausted_restored_sequence_is_reported_without_claiming_checked(operations):
    sequence = ('public', 'items_id_seq', 1, 1, 100, False,
                'public', 'items', 'id', 'integer', 'a', None, False)
    class Connection:
        def execute(self, *args): return self
        def fetchall(self): return [sequence]
        def fetchone(self): return (100, True)
    result = operations.backup.sequence_safety(Connection(), ['public'])
    assert result['checked'] == 0
    assert result['unsupported'][0]['reason'] == 'exhausted_sequence'


def test_identity_sequence_is_supported_without_serial_default(operations):
    sequence = ('public', 'items_id_seq', 1, 1, 100, False,
                'public', 'items', 'id', 'bigint', 'a', None, False)
    class Connection:
        def __init__(self): self.values = iter([(10, True), (10,)])
        def execute(self, *args): return self
        def fetchall(self): return [sequence]
        def fetchone(self): return next(self.values)
    result = operations.backup.sequence_safety(Connection(), ['public'])
    assert result['checked'] == 1 and not result['unsupported']
