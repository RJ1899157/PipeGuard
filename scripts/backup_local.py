"""Private consistent backups and restore drills into new disposable databases only."""
import argparse
from functools import wraps
import fcntl
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import stat
import subprocess
from uuid import UUID, uuid4

import psycopg
from psycopg import sql
from sqlalchemy.engine import make_url

from local_files import ensure_private_directory, read_private, write_private

ROOT = Path(__file__).resolve().parents[1]
SCHEMAS = {"pipeguard": ["public"], "airflow": ["public"],
           "sample_warehouse": ["raw", "staging", "analytics"]}


def exclusive_attempt(operation):
    """Serialize verification/recovery so a cleanup cannot drop an active drill."""
    @wraps(operation)
    def locked(identity):
        directory, _, _ = load_manifest(identity)
        descriptor = os.open(directory / "restore.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        try:
            information = os.fstat(descriptor)
            if (not stat.S_ISREG(information.st_mode) or information.st_uid != os.getuid()
                    or information.st_mode & 0o077 or information.st_nlink != 1):
                raise ValueError("Restore lock must be owner-private and regular")
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return operation(identity)
        finally:
            os.close(descriptor)
    return locked


def parameters(database):
    url = make_url(os.environ["PIPEGUARD_DATABASE_URL"])
    if (url.drivername != "postgresql+psycopg" or url.host not in {"localhost", "127.0.0.1"}
            or url.database != "pipeguard" or url.query):
        raise ValueError("Local database configuration required")
    return dict(host=url.host, port=url.port or 5432, dbname=database, user="postgres",
                password=os.environ["POSTGRES_PASSWORD"], connect_timeout=5,
                options="-cstatement_timeout=60000 -clock_timeout=5000")


def command(arguments, *, source=None, destination=None):
    result = subprocess.run(["docker", "compose", "exec", "-T", "postgres", *arguments],
                            cwd=ROOT, stdin=source, stdout=destination or subprocess.DEVNULL,
                            stderr=subprocess.PIPE, timeout=180, check=False)
    if result.returncode:
        raise RuntimeError("local_backup_command_failed")


def fingerprints(connection, schemas):
    connection.execute("SET LOCAL timezone='UTC'")
    tables = connection.execute("""SELECT n.nspname,c.relname FROM pg_class c
        JOIN pg_namespace n ON n.oid=c.relnamespace
        WHERE n.nspname=ANY(%s) AND c.relkind IN ('r','p') ORDER BY 1,2""", (schemas,)).fetchall()
    result = []
    for schema, name in tables:
        digest, rows = sha256(), 0
        query = sql.SQL("COPY (SELECT to_jsonb(t)::text FROM {} t ORDER BY to_jsonb(t)::text) TO STDOUT").format(
            sql.Identifier(schema, name))
        with connection.cursor() as cursor, cursor.copy(query) as stream:
            for block in stream:
                content = bytes(block)
                digest.update(content)
                rows += content.count(b"\n")
        result.append({"schema": schema, "table": name, "rows": rows, "sha256": digest.hexdigest()})
    return result


def schema_definitions(connection, schemas):
    return connection.execute("""
        SELECT 'constraint',n.nspname,c.relname,k.conname,pg_get_constraintdef(k.oid,true)
          FROM pg_constraint k JOIN pg_class c ON c.oid=k.conrelid
          JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname=ANY(%s)
        UNION ALL SELECT 'trigger',n.nspname,c.relname,t.tgname,pg_get_triggerdef(t.oid,true)
          FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid
          JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname=ANY(%s) AND NOT t.tgisinternal
        UNION ALL SELECT 'view',n.nspname,c.relname,'',pg_get_viewdef(c.oid,true)
          FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
          WHERE n.nspname=ANY(%s) AND c.relkind IN ('v','m')
        UNION ALL SELECT 'function',n.nspname,p.proname,pg_get_function_identity_arguments(p.oid),pg_get_functiondef(p.oid)
          FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
          WHERE n.nspname=ANY(%s) AND p.prokind IN ('f','p')
        UNION ALL SELECT 'index',schemaname,tablename,indexname,indexdef
          FROM pg_indexes WHERE schemaname=ANY(%s)
        UNION ALL SELECT 'column',n.nspname,c.relname,a.attname,
          json_build_array(format_type(a.atttypid,a.atttypmod),a.attnotnull,a.attidentity,a.attgenerated,
                           pg_get_expr(d.adbin,d.adrelid,true))::text
          FROM pg_attribute a JOIN pg_class c ON c.oid=a.attrelid
          JOIN pg_namespace n ON n.oid=c.relnamespace
          LEFT JOIN pg_attrdef d ON d.adrelid=c.oid AND d.adnum=a.attnum
          WHERE n.nspname=ANY(%s) AND c.relkind IN ('r','p','v','m') AND a.attnum>0 AND NOT a.attisdropped
        ORDER BY 1,2,3,4,5
    """, (schemas, schemas, schemas, schemas, schemas, schemas)).fetchall()


def canonical_definition(row):
    # PostgreSQL distributes varchar-array -> text-array casts during restore.
    # Normalize only this exact enum-check shape; other DDL differences fail.
    if row[0] == "constraint":
        literal = r"'(?:''|[^'])*'::character varying(?:::text)?"
        match = re.fullmatch(r"CHECK \(([a-z_][a-z0-9_]*)::text = ANY \(ARRAY\[("
                             + literal + r"(?:, " + literal + r")*)\](?:::text\[\])?\)\)", row[4])
        if match:
            values = re.findall(r"'((?:''|[^'])*)'::character varying(?:::text)?", match[2])
            return (*row[:4], json.dumps({"check": "varchar_text_enum", "column": match[1], "values": values}))
    return row


def schema_hash(connection, schemas):
    definitions = [canonical_definition(row) for row in schema_definitions(connection, schemas)]
    return sha256(json.dumps(definitions, separators=(",", ":")).encode()).hexdigest()


def sequence_safety(connection, schemas):
    """Check restored counters against restored rows, without advancing a sequence.

    Sequence positions are not MVCC snapshots. This deliberately does not compare
    a live source counter with the exported snapshot or change the manifest hash.
    """
    sequences = connection.execute("""
        SELECT sn.nspname,s.relname,q.seqincrement,q.seqmin,q.seqmax,q.seqcycle,
               tn.nspname,t.relname,a.attname,a.atttypid::regtype::text,
               a.attidentity,pg_get_expr(ad.adbin,ad.adrelid),
               EXISTS (SELECT 1 FROM pg_depend x WHERE x.classid='pg_attrdef'::regclass
                       AND x.objid=ad.oid AND x.refclassid='pg_class'::regclass AND x.refobjid=s.oid)
          FROM pg_class s JOIN pg_namespace sn ON sn.oid=s.relnamespace
          JOIN pg_sequence q ON q.seqrelid=s.oid
          LEFT JOIN pg_depend d ON d.classid='pg_class'::regclass AND d.objid=s.oid
               AND d.refclassid='pg_class'::regclass AND d.deptype IN ('a','i')
          LEFT JOIN pg_class t ON t.oid=d.refobjid
          LEFT JOIN pg_namespace tn ON tn.oid=t.relnamespace
          LEFT JOIN pg_attribute a ON a.attrelid=t.oid AND a.attnum=d.refobjsubid
          LEFT JOIN pg_attrdef ad ON ad.adrelid=t.oid AND ad.adnum=a.attnum
         WHERE s.relkind='S' AND sn.nspname=ANY(%s)
         ORDER BY sn.nspname,s.relname
    """, (schemas,)).fetchall()
    checked, unsupported = 0, []
    for schema, name, increment, minimum, maximum, cycling, table_schema, table, column, datatype, identity, default, default_uses_sequence in sequences:
        reason = None
        if not table or not column:
            reason = "unowned_sequence"
        elif table_schema not in schemas:
            reason = "owner_outside_backup_scope"
        elif cycling:
            reason = "cycling_sequence"
        elif datatype not in {"smallint", "integer", "bigint"}:
            reason = "non_integer_owner_column"
        elif not identity and (not default_uses_sequence or not default or not re.fullmatch(r"nextval\('[^']+'::regclass\)", default)):
            reason = "custom_owner_default"
        if reason is None:
            last, called = connection.execute(sql.SQL("SELECT last_value,is_called FROM {}").format(
                sql.Identifier(schema, name))).fetchone()
            following = last + increment if called else last
            if not minimum <= following <= maximum:
                reason = "exhausted_sequence"
            else:
                edge = "max" if increment > 0 else "min"
                bound = connection.execute(sql.SQL("SELECT {}({}) FROM {}").format(
                    sql.SQL(edge), sql.Identifier(column), sql.Identifier(table_schema, table))).fetchone()[0]
                if bound is not None and (following <= bound if increment > 0 else following >= bound):
                    raise RuntimeError("restored_sequence_may_collide_with_restored_rows")
                checked += 1
        if reason:
            unsupported.append({"schema": schema, "sequence": name, "reason": reason})
    return {"checked": checked, "unsupported": unsupported,
            "scope": "restored_owned_integer_nocycle_counters_beyond_restored_row_bounds",
            "source_sequence_position_compared": False}


def create(database):
    if database not in SCHEMAS:
        raise ValueError("Unsupported backup database")
    identity = str(uuid4())
    directory = ROOT / "data/local/backups" / identity
    ensure_private_directory(directory.parent)
    ensure_private_directory(directory)
    archive = directory / "database.dump"
    with psycopg.connect(**parameters(database)) as connection:
        connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        snapshot = connection.execute("SELECT pg_export_snapshot()").fetchone()[0]
        descriptor = os.open(archive, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        arguments = ["pg_dump", "--username", "postgres", "--dbname", database,
                     "--format", "custom", "--no-owner", "--no-privileges", "--snapshot", snapshot,
                     "--lock-wait-timeout=5000"]
        for schema in SCHEMAS[database]:
            arguments.extend(["--schema", schema])
        with os.fdopen(descriptor, "wb") as output:
            command(arguments, destination=output)
            output.flush()
            os.fsync(output.fileno())
        manifest = {"version": 1, "backup_id": identity, "database": database,
                    "created_at": datetime.now(timezone.utc).isoformat(), "schemas": SCHEMAS[database],
                    "archive_sha256": file_hash(archive), "tables": fingerprints(connection, SCHEMAS[database]),
                    "schema_sha256": schema_hash(connection, SCHEMAS[database]),
                    "scope": "logical_selected_schemas_no_roles_or_private_configuration"}
    write_private(directory / "manifest.json", json.dumps(manifest, sort_keys=True, indent=2) + "\n")
    return manifest


def file_hash(path):
    digest = sha256()
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(descriptor, "rb") as stream:
        information = os.fstat(descriptor)
        if (not stat.S_ISREG(information.st_mode) or information.st_uid != os.getuid()
                or information.st_mode & 0o077):
            raise ValueError("Archive must be owner-private and regular")
        while block := stream.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def load_manifest(identity):
    identity = str(UUID(identity))
    directory = ROOT / "data/local/backups" / identity
    if directory.is_symlink() or directory.resolve().parent != (ROOT / "data/local/backups").resolve():
        raise ValueError("Private local backup required")
    manifest_path, archive = directory / "manifest.json", directory / "database.dump"
    if manifest_path.is_symlink() or archive.is_symlink() or manifest_path.stat().st_size > 1024 * 1024:
        raise ValueError("Invalid backup files")
    manifest = json.loads(read_private(manifest_path, 1024 * 1024))
    if (manifest.get("version") != 1 or manifest.get("backup_id") != identity
            or manifest.get("database") not in SCHEMAS
            or manifest.get("schemas") != SCHEMAS[manifest["database"]]
            or file_hash(archive) != manifest.get("archive_sha256")):
        raise ValueError("Backup manifest or archive checksum mismatch")
    return directory, archive, manifest


def drop_owned_check(administrator, disposable, marker):
    if not re.fullmatch(r"pipeguard_restore_check_[0-9a-f]{32}", disposable):
        raise RuntimeError("Unsafe restore cleanup target")
    record = administrator.execute("""SELECT pg_get_userbyid(datdba),
        shobj_description(oid,'pg_database') FROM pg_database WHERE datname=%s""", (disposable,)).fetchone()
    if record is None:
        return False
    if record != ("postgres", marker):
        raise RuntimeError("Restore database ownership marker does not match")
    administrator.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(disposable)))
    return True


def inspect_checks():
    with psycopg.connect(**parameters("postgres")) as administrator:
        records = administrator.execute("""SELECT datname,pg_get_userbyid(datdba),
            shobj_description(oid,'pg_database') FROM pg_database
            WHERE datname LIKE 'pipeguard_restore_check_%%' ORDER BY datname""").fetchall()
    result = []
    for database, owner, marker in records:
        if not re.fullmatch(r"pipeguard_restore_check_[0-9a-f]{32}", database):
            continue
        match = re.fullmatch(r"pipeguard_restore_check:v1:([0-9a-f-]{36}):[0-9a-f]{32}", marker or "")
        result.append({"database": database, "backup_id": match[1] if match else None,
                       "tool_owned": bool(match) and owner == "postgres",
                       "requires_review": True, "cleanup_requires_owned_attempt_record": True})
    return result


@exclusive_attempt
def cleanup(identity):
    directory, _, manifest = load_manifest(identity)
    attempt = json.loads(read_private(directory / "restore-attempt.json", 4096))
    disposable, marker = attempt.get("database"), attempt.get("marker")
    expected_marker = "pipeguard_restore_check:v1:" + manifest["backup_id"] + ":"
    if (attempt.get("backup_id") != manifest["backup_id"] or not isinstance(marker, str)
            or not re.fullmatch(re.escape(expected_marker) + "[0-9a-f]{32}", marker)):
        raise ValueError("Invalid restore attempt record")
    with psycopg.connect(**parameters("postgres"), autocommit=True) as administrator:
        removed = drop_owned_check(administrator, disposable, marker)
    attempt["state"] = "cleaned"
    write_private(directory / "restore-attempt.json", json.dumps(attempt, sort_keys=True) + "\n")
    return {"backup_id": manifest["backup_id"], "database": manifest["database"], "removed_disposable": removed}


@exclusive_attempt
def verify(identity):
    directory, archive, manifest = load_manifest(identity)
    attempt_path = directory / "restore-attempt.json"
    if attempt_path.exists() and json.loads(read_private(attempt_path, 4096)).get("state") != "cleaned":
        raise RuntimeError("Inspect and clean the previous restore attempt before retrying")
    disposable = "pipeguard_restore_check_" + uuid4().hex
    marker = "pipeguard_restore_check:v1:" + manifest["backup_id"] + ":" + uuid4().hex
    attempt = {"version": 1, "backup_id": manifest["backup_id"], "database": disposable,
               "marker": marker, "state": "creating", "started_at": datetime.now(timezone.utc).isoformat()}
    write_private(directory / "restore-attempt.json", json.dumps(attempt, sort_keys=True) + "\n")
    with psycopg.connect(**parameters("postgres"), autocommit=True) as administrator:
        administrator.execute(sql.SQL("CREATE DATABASE {} TEMPLATE template0").format(sql.Identifier(disposable)))
        try:
            administrator.execute(sql.SQL("COMMENT ON DATABASE {} IS {}").format(
                sql.Identifier(disposable), sql.Literal(marker)))
            administrator.execute(sql.SQL("REVOKE ALL ON DATABASE {} FROM PUBLIC").format(sql.Identifier(disposable)))
            if "public" in manifest["schemas"]:
                # template0 already contains an empty public schema; the archive
                # must create its own schema, strictly inside this new database.
                with psycopg.connect(**parameters(disposable)) as empty:
                    empty.execute("DROP SCHEMA public")
            with archive.open("rb") as source:
                command(["pg_restore", "--username", "postgres", "--dbname", disposable,
                         "--no-owner", "--no-privileges", "--exit-on-error"], source=source)
            with psycopg.connect(**parameters(disposable)) as restored:
                restored.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
                actual = fingerprints(restored, manifest["schemas"])
                restored_schema = schema_hash(restored, manifest["schemas"])
                restored_sequences = sequence_safety(restored, manifest["schemas"])
            if actual != manifest["tables"]:
                raise RuntimeError("restored_rows_do_not_match_snapshot")
            if manifest.get("schema_sha256") and restored_schema != manifest["schema_sha256"]:
                raise RuntimeError("restored_schema_does_not_match_snapshot")
            result = {"version": 1, "backup_id": manifest["backup_id"], "database": manifest["database"],
                      "verified_at": datetime.now(timezone.utc).isoformat(), "result": "verified",
                      "table_count": len(actual), "archive_sha256": manifest["archive_sha256"],
                      "schema_verified": bool(manifest.get("schema_sha256")),
                      "sequence_safety": restored_sequences,
                      "restore_target": "new_disposable_database", "live_database_replaced": False}
        finally:
            # Only the exact generated name can be dropped. Never use --create,
            # --clean, a user-provided target or forced connection termination.
            drop_owned_check(administrator, disposable, marker)
            attempt["state"] = "cleaned"
            write_private(directory / "restore-attempt.json", json.dumps(attempt, sort_keys=True) + "\n")
    write_private(directory / "verification.json", json.dumps(result, sort_keys=True, indent=2) + "\n")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="operation", required=True)
    create_parser = commands.add_parser("create")
    create_parser.add_argument("--database", choices=SCHEMAS, default="pipeguard")
    verify_parser = commands.add_parser("verify")
    verify_parser.add_argument("--backup-id", required=True)
    cleanup_parser = commands.add_parser("cleanup")
    cleanup_parser.add_argument("--backup-id", required=True)
    commands.add_parser("inspect")
    args = parser.parse_args()
    os.umask(0o077)
    if args.operation == "inspect":
        print(json.dumps({"restore_checks": inspect_checks()}))
        return
    if args.operation == "create":
        result = create(args.database)
    elif args.operation == "verify":
        result = verify(args.backup_id)
    else:
        result = cleanup(args.backup_id)
    # Table contents and credentials are private; only safe operation metadata is printed.
    print(json.dumps({key: result[key] for key in ("backup_id", "database")} | {"operation": args.operation}))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        raise SystemExit("Local backup/restore drill failed (private details withheld)")
