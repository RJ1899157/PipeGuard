"""Resolve reviewed security constraints without bypassing dependency requirements."""
from pathlib import Path
import re
import subprocess
import tempfile


def main():
    root = Path(__file__).resolve().parents[1]
    directory = root / "infra/airflow"
    security = (directory / "security-constraints.txt").read_text()
    selected = {line.split("==", 1)[0].lower() for line in security.splitlines()
                if line and not line.startswith("#")}
    upstream = (directory / "constraints-3.12.txt").read_text()
    lines = [line for line in upstream.splitlines()
             if re.split(r"[=<>!~ ]", line, maxsplit=1)[0].lower() not in selected]
    with tempfile.TemporaryDirectory(prefix="pipeguard-airflow-constraints-") as temporary:
        constraints = Path(temporary) / "constraints.txt"
        constraints.write_text("\n".join(lines) + "\n" + security)
        result = subprocess.call([
            "uv", "pip", "compile", "infra/airflow/requirements.in",
            "--constraint", str(constraints), "--python-version", "3.12",
            "--generate-hashes", "--output-file", "infra/airflow/requirements.lock",
            "--custom-compile-command", "uv run python scripts/compile_airflow_requirements.py",
        ], cwd=root, stdout=subprocess.DEVNULL)
        if result == 0:
            lock = directory / "requirements.lock"
            # Temporary filesystem paths are not reproducible provenance.
            lock.write_text(lock.read_text().replace(str(constraints),
                "infra/airflow/constraints-3.12.txt + infra/airflow/security-constraints.txt"))
        return result


if __name__ == "__main__":
    raise SystemExit(main())
