# PostgreSQL security maintenance — 2026-11-05

The remaining published compatible container fix is deployed and verified.
Debian APT and `libapt-pkg7.0` were upgraded from **3.0.3 to 3.0.4**, addressing
[CVE-2026-109518](https://security-tracker.debian.org/tracker/CVE-2026-109518).
PostgreSQL remains **17.11**. No other installed binary package version changed.

## Reproducible patch

The [Dockerfile](../infra/postgres/Dockerfile) derives from the previous immutable
official image, selects ARM64 or AMD64, and downloads the two exact Debian security
packages over HTTPS with enforced SHA-256 checksums. Signed release metadata was
verified using the Debian archive keyring in that base; package indexes and all
four architecture-specific package files matched their signed hashes. Metadata
was within its validity window. [Package provenance](../infra/postgres/apt-patch.json)
and [maintenance instructions](../infra/postgres/README.md) record the inputs.
The build does not use the vulnerable package manager to fetch updates.

## Verification

Tested implementation: `a7faafbcc2ceb6654ea3ca0489dcba6384c172bf`.

- **599 tests passed:** 466 backend, 66 workload, 13 Airflow and 54 frontend.
- Fresh isolated delivery passed migrations, constrained runtime permissions,
  real failed/successful attempts, incident resolution with retained failure,
  14 quality checks, complete reported lineage, HTTP body limits/deadlines,
  database-access outage/restoration, production dashboard startup and cleanup.
- Both jobs passed in [manual hosted CI](https://github.com/RJ1899157/PipeGuard/actions/runs/41967389480).
  This also exercised the AMD64 image build; local checks exercised ARM64.
  Automatic CI triggers remain disabled.
- Fresh consistent backups of all three databases restored with matching table
  and schema hashes on a disposable patched container **before** replacement.
  All three restore drills passed again after replacement. No live database was
  replaced by a backup; temporary restore databases and the trial container were removed.
- All **10,807** captured immutable rows across **15 tables** retain their IDs and
  content hashes. The named data volume and previous image remain retained.
- Source inventory remains **8 runs / 14 attempts**. Public investigation history
  remains **16 requests / 16 outcomes**. All 16 isolated AI evaluations replayed
  unchanged with **zero new provider calls**. Recovery history remains one action,
  one approval, one dispatch and two observations.
- API liveness/readiness and dashboard return 200, the stored API contract matches,
  and database/API/dashboard/Airflow listeners remain on loopback. Airflow and the
  monitor were gracefully restarted; the independent watcher reports healthy API
  and database with a fresh monitor heartbeat. Recovery flags remain **0/0** and
  the daily DAG remains **paused**.

## Remaining limits

The new [installed inventory](audit/postgres-maintenance-packages.tsv) has 95
source/version pairs. The [rescan](audit/postgres-maintenance-advisories.json)
returns **130 advisory matches**, down from 131; the fixed APT advisory is absent.
No remaining matched record has a published nonzero compatible trixie fixed
version in this snapshot. One existing GnuTLS bulk-feed discrepancy remains
explicit. These findings do not prove the remaining packages safe or unreachable.
Historical [Stage 14 evidence](stage14-audit.md) retains its original 131-match
checkpoint; this maintenance report supersedes that pending APT fix.

Same-host monitoring/backups, broader AI accuracy, public multi-user access,
distributed execution and atomic warehouse publication retain their documented
[scope limits](next-session.md#explicit-remaining-limits). No mandatory owned-code
fix remains from the final audit; future upstream security releases still require
review and verification.

Structured evidence: [maintenance verification](audit/container-maintenance-verification.json).
