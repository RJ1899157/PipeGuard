# PostgreSQL container advisory triage

**Latest maintenance (2026-11-05):** APT 3.0.4 is now deployed in a verified,
checksum-pinned derived image. The rescan returns **130** matches; the APT advisory
is absent. PostgreSQL remains 17.11 and all retained data passed preservation and
restore checks. See [maintenance results](container-maintenance.md). The checkpoints
below retain their historical package versions and counts.

**Current Stage 14 refresh (2026-11-05):**131 matches across 95 installed source/version
pairs. One new APT advisory has a published trixie-security fix:3.0.4 versus installed
3.0.3 ([CVE-2026-109518](https://security-tracker.debian.org/tracker/CVE-2026-109518)).
The official ARM64 image is unchanged. Applying that fix requires reviewed image
maintenance; no container was modified in this audit. Other matched records have
no published compatible fixed version in this snapshot. See [Stage 14 results](stage14-audit.md).

**Stage 13 checkpoint (2026-11-04):** [Stage 13 verification](stage13-verification.md#current-dependency-findings) retains 130 matches without a published compatible fixed version. One GnuTLS record is absent from the bulk feed but remains vulnerable/unfixed on its individual tracker page; that discrepancy is explicit. The official ARM64 image is unchanged. The historical counts below describe the earlier checkpoint.

## Follow-up after hosted CI

On 2026-11-04, a fresh registry/OSV/Debian check verified all **95** source/version
pairs against the running container. **130** advisory matches remain, with no
published nonzero compatible fixed version in the matched trixie records. The
official PostgreSQL 17 index is `sha256:3b0cda93be7c8dba2ed484d19393d93845dc3dafb88973e248ba8e6d99d784e1`,
but its ARM64 child remains `sha256:ac359420747e1f5f8ac4d23f40d7ce022c0a39090ed6cdd8dde5f596affbe41d`,
identical to the pinned image's ARM64 child. Updating only the index pin would
not change this Mac's container contents or remediate these matches. The existing
bulk-feed gap remains recorded; lack of a fix does not establish safety.
No image, package, container or database was changed. Remediation remains blocked
on compatible upstream fixes or a separately reviewed base-image design.

Checkpoint: 2026-11-01. This is a time-specific installed-package comparison, not a reachability proof. The container remains bound to loopback, with separate administrator, application, Airflow, workload and minimal watcher roles.

The pinned official `postgres:17` image is already the current official PostgreSQL 17 image: registry index `sha256:31ba9c94a03ada9988f2bb493a22a75eef3a185884533e5cdbcd498ea835b08f`, PostgreSQL 17.11, Debian trixie slim, published October 28, 2026. A same-family image update is unavailable at this check. No image, container, package, or database was changed.

The 116 OSV advisory matches across 28 source packages were checked individually against Debian's trixie release records:

| Debian classification                                      | Matches |
| ---------------------------------------------------------- | ------: |
| Open, no published trixie fixed version                    |      62 |
| Open, Debian urgency unimportant                           |      48 |
| Open, Debian postponed                                     |       3 |
| Debian ignored                                             |       1 |
| Undetermined                                               |       1 |
| Not affected in trixie                                     |       1 |
| Known fixed-version upgrade candidates among these matches |       0 |

The not-affected match is SQLite CVE-2026-39113: Debian says the vulnerable code was never in a released Debian version. The ignored match is LLVM CVE-2024-7883: Debian says the default build flags are unaffected and no release-19 backport is planned. PAM CVE-2025-8941 remains undetermined. Open/unimportant/postponed/ignored records are not all equivalent to fixed or safe.

Residual exposure remains. Open records include libxml2 parsing and memory-safety issues and glibc library issues. Installed-source matches do not establish which vulnerable functions PostgreSQL or application queries can reach. All records have tracker scope metadata `local`, but some descriptions mention malicious remote input; that field is not evidence that remote input cannot exploit a vulnerable parser. This triage neither proves exploitability nor dismisses these records as harmless.

No package version in these 116 matches has a nonzero fixed version published for trixie. That finding is narrower than proving all packages are current. Mixing Debian unstable/testing packages, changing PostgreSQL major versions, or switching libc/base distribution would introduce compatibility changes and is not an established safe fix. Recheck the official PostgreSQL 17 image and Debian trixie tracker when an updated image or security fix is published. A rebuilt custom image or a different base would require a separate compatibility and restore drill before use.

Evidence: [advisory triage](audit/postgres-advisory-triage.json) records every matched CVE, installed source version, Debian release state, rationale, source URL and input checksums. The [source-package inventory](audit/postgres-packages.tsv) covers all 95 installed source/version pairs. Full primary-source and registry responses remain in the private local audit workspace. Docker Scout required an account login and was not completed; the recorded comparison used the OSV API and Debian release records. No external scanner was given database contents or credentials.

Sources: [Debian tracker JSON](https://security-tracker.debian.org/tracker/data/json), [official PostgreSQL image metadata](https://github.com/docker-library/official-images/blob/master/library/postgres), [SQLite not affected](https://security-tracker.debian.org/tracker/CVE-2026-39113), [LLVM ignored rationale](https://security-tracker.debian.org/tracker/CVE-2024-7883), [PAM undetermined](https://security-tracker.debian.org/tracker/CVE-2025-8941).
