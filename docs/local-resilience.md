# Local resilience and recovery checks

This operating guide covers the local development deployment. It does not expose services beyond loopback or authorize automatic business recovery.

## Independent service watcher

From the project root, after database/API provisioning:

```sh
uv run --env-file .env python scripts/configure_watchdog.py
uv run python scripts/manage_watchdog.py install
uv run python scripts/manage_watchdog.py status
```

On macOS, installation creates only the current user's `com.rj1899157.pipeguard.watchdog` launch agent. It starts at login and restarts the watcher if that process exits, independently of Codex. It does not start Docker, Airflow or business jobs. To remove this checkout's owned agent:

```sh
uv run python scripts/manage_watchdog.py uninstall
```

For a foreground check without an installed/running agent:

```sh
uv run --env-file .env.watchdog python scripts/run_watchdog.py --once
```

A process lock prevents duplicate watchers. The separate `.env.watchdog` contains only the dedicated database credential. `pipeguard_watchdog` can connect only to PipeGuard and read `jobs`, `monitor_policies` and `monitor_heartbeats`; it cannot read evidence, mutate tables or create schema objects. Provisioning also restricts PUBLIC access to this dedicated PostgreSQL server's system databases; the database administrator and explicit application grants remain usable.

The watcher checks API liveness, database reachability and global/per-job detector heartbeats every 15 seconds. Source health and business failures remain the detector/incident system's responsibility. Its owner-private state and bounded, rotating change journal live in ignored `data/local/watchdog/`. The dashboard Overview reads an allowlisted status projection independently of the monitoring API and refreshes that sample every 15 seconds. Old samples and clock inconsistencies mean unknown health.

Normal installation does not submit OS notifications. The foreground `--notify` option can submit change-only macOS notifications; `submitted` means only that the OS accepted the request, never confirmed delivery. Logs and state never contain credentials or arbitrary exception text.

The watcher requires this Mac to be running and the user session to be available. There is no second device configured; host power loss and off-host alert delivery are not covered. Stopping services intentionally may produce outage/recovery entries. Database restarts can stop Airflow components; after database recovery, restart the Airflow launcher and verify source coverage rather than assuming it recovered.

## Private logical backups

With the existing PostgreSQL container running:

```sh
uv run --env-file .env python scripts/backup_local.py create --database pipeguard
uv run --env-file .env python scripts/backup_local.py create --database airflow
uv run --env-file .env python scripts/backup_local.py create --database sample_warehouse
uv run --env-file .env python scripts/backup_local.py verify --backup-id BACKUP_UUID
uv run --env-file .env python scripts/backup_local.py inspect
```

Each create operation prints its backup UUID. Archives, manifests and verification records remain private under ignored `data/local/backups/<UUID>/`. A backup uses one exported consistent database snapshot. A verification restores only into a newly generated, restricted disposable database and compares table row counts/content fingerprints plus schema definitions, constraints, indexes, triggers and functions before dropping that disposable database. It never replaces a live database.

Inspect reports leftover restore-check databases. To recover a marked interrupted verification associated with a known private backup:

```sh
uv run --env-file .env python scripts/backup_local.py cleanup --backup-id BACKUP_UUID
```

Recovery requires the private attempt record, exact generated name, PostgreSQL ownership marker and an unlocked verification record. Active restores and unmarked databases are refused. A SIGKILL exactly between database creation and marker publication may leave an unmarked scratch database; inspect reports it for manual ownership review. The tool does not guess which database is safe to delete.

Backups include the selected schemas, not PostgreSQL roles, private environment files, uploaded files, outboxes or an entire machine. They contain potentially sensitive metadata and must stay private. A real disaster restore needs separately protected credentials/configuration and reviewed grants. Same-disk backups do not survive disk loss or host destruction. They are manual; no off-host copy or backup schedule is configured.

## Consistent dashboard pages

The dashboard captures each list separately. Page membership and values stay fixed across concurrent inserts, retries and incident transitions. The capture time is visible; Refresh starts again from page one and includes newer changes. Quality-conflict summaries include every report in the selected execution/attempt scope, including reports outside the visible page.

Snapshots are process-local and expire after five minutes. They are bounded to 5,000 rows and 8 MiB serialized content each, with 128 entries/64 MiB aggregate content and two simultaneous captures. These are response-content bounds, not exact process-RSS limits. Expiry or API restart produces 410; capacity produces 413; a busy capture service produces 503. The UI asks for Refresh or a narrower selection and never silently falls back to inconsistent live pages. Legacy API requests without a snapshot remain live offset reads.

## Browser boundary

Production script permission uses a fresh cryptographic nonce for each document, including error pages. Dynamic graph/chart inline styles remain necessary. Host checks, fixed read destinations, frame restrictions and same-origin metadata checks remain enforced. A top-level GET navigation to the local app shell may originate from another page; that exception does not permit embedded navigation, cross-origin fetches, metadata routes or mutations. Public multi-user deployment still requires a separate identity and network design.
