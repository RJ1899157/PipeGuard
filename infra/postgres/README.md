# PostgreSQL security overlay

Compose builds a local image from the existing immutable PostgreSQL 17.11 base.
The overlay installs only Debian trixie-security `apt` and `libapt-pkg7.0` 3.0.4,
fixing [CVE-2026-109518](https://security-tracker.debian.org/tracker/CVE-2026-109518).
PostgreSQL, libc, entrypoint, credentials and persistent data layout stay unchanged.

The Dockerfile supports Linux ARM64 and AMD64. BuildKit downloads each package over
HTTPS and enforces its SHA-256 before installation; `dpkg` must satisfy dependencies
without forced installation. No repository refresh runs through the vulnerable APT.
The exact URLs and hashes in [apt-patch.json](apt-patch.json) were authenticated
against Debian's signed InRelease using the archive keyring in the pinned base,
then checked against its SHA-256 package indexes and downloaded package bytes.
Unsupported architectures fail to select a build stage.

`docker compose build postgres` prepares the image without replacing the running
database. Compose's `pull_policy: build` also ensures ordinary startup builds the
reviewed local definition rather than looking for this local tag on Docker Hub.
The build context contains only this directory, excluding project secrets.

Before replacing a retained container, take consistent backups of all three
databases and verify restores against a disposable patched database. Retain the
previous image and named volume. Then run `docker compose up --detach --no-deps
--wait postgres`, verify health and retained evidence, and repeat restore checks.
Never remove the volume. This overlay does not claim to resolve unrelated Debian
advisories; see [container security](../../docs/container-security.md).

Future maintenance requires reviewing signed metadata and updating the package
hashes and manifest together. Missing packages or checksum mismatches fail the
build; do not bypass validation or substitute unreviewed repositories.
