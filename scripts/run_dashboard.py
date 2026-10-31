"""Launch the local read-only dashboard with only its required secret."""
import os
from pathlib import Path
import shutil
import subprocess
import sys

if __name__ == "__main__":
    root = Path(__file__).resolve().parents[1]
    token = os.environ.get("PIPEGUARD_ADMIN_TOKEN")
    if not token:
        raise SystemExit("Load the private root .env before launching the dashboard")
    node = shutil.which("node")
    if not node or subprocess.check_output([node, "-p", "process.versions.node.split('.')[0]"], text=True).strip() != "22":
        raise SystemExit("Use Node.js 22 for the dashboard")
    web = root / "apps/pipeguard/web"
    next_cli = web / "node_modules/next/dist/bin/next"
    if not next_cli.is_file():
        raise SystemExit("Install the web dependencies with pnpm before launching the dashboard")
    # No database URLs, Airflow credentials or producer tokens reach Next.js.
    environment = {key: value for key, value in os.environ.items()
                   if key in {"PATH", "HOME", "TMPDIR", "LANG", "LC_ALL", "SHELL"}}
    environment.update(PIPEGUARD_ADMIN_TOKEN=token, NEXT_TELEMETRY_DISABLED="1")
    command = "dev" if "--dev" in sys.argv else "start"
    # Replace the launcher so signals and exit status belong to the web process.
    os.chdir(web)
    os.execve(node, [node, str(next_cli), command, "--hostname", "127.0.0.1", "--port", "3000"], environment)
