"""Install, inspect or remove only this checkout's macOS user watchdog agent."""
import argparse
import json
import os
from pathlib import Path
import plistlib
import re
import shutil
import subprocess
import sys
import time

from local_files import read_private, write_private

ROOT = Path(__file__).resolve().parents[1]
LABEL = "com.rj1899157.pipeguard.watchdog"


def agent_definition(root, uv):
    return {"Label": LABEL, "WorkingDirectory": str(root), "RunAtLoad": True, "KeepAlive": True,
            "ThrottleInterval": 15, "ProcessType": "Background",
            "ProgramArguments": [str(uv), "run", "--project", str(root), "--locked", "--no-sync",
                                 "--env-file", str(root / ".env.watchdog"),
                                 str(root / ".venv/bin/python"), str(root / "scripts/run_watchdog.py"), "--quiet"],
            # The watchdog owns a bounded change journal. Discard launcher output
            # rather than creating unbounded logs or exporting the environment.
            "StandardOutPath": "/dev/null", "StandardErrorPath": "/dev/null"}


def own_definition(definition, root):
    arguments = definition.get("ProgramArguments")
    return (isinstance(arguments, list) and bool(arguments) and definition.get("Label") == LABEL
            and definition.get("WorkingDirectory") == str(root)
            and arguments == agent_definition(root, arguments[0])["ProgramArguments"])


def query():
    target = f"gui/{os.getuid()}/{LABEL}"
    result = subprocess.run(["launchctl", "print", target], capture_output=True, text=True, timeout=10)
    if result.returncode:
        return {"installed": False, "running": False}
    pid = re.search(r"\bpid = ([0-9]+)", result.stdout)
    exit_code = re.search(r"last exit code = (-?[0-9]+)", result.stdout)
    return {"installed": True, "running": pid is not None,
            "owned": str(ROOT / "scripts/run_watchdog.py") in result.stdout,
            "pid": int(pid[1]) if pid else None,
            "last_exit_code": int(exit_code[1]) if exit_code else None}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=["install", "status", "uninstall"])
    args = parser.parse_args()
    if sys.platform != "darwin" or os.getuid() == 0:
        raise RuntimeError("A non-root macOS user session is required")
    plist = Path.home() / "Library/LaunchAgents" / (LABEL + ".plist")
    if plist.is_symlink():
        raise RuntimeError("User agent must be a regular file")
    if plist.exists() and not own_definition(plistlib.loads(read_private(plist, 65536)), ROOT):
        raise RuntimeError("Existing user agent belongs to a different checkout/configuration")
    target = f"gui/{os.getuid()}/{LABEL}"
    if args.operation == "install":
        uv = shutil.which("uv")
        configuration = ROOT / ".env.watchdog"
        if (not uv or not (ROOT / ".venv/bin/python").is_file() or not configuration.is_file()
                or configuration.is_symlink() or configuration.stat().st_mode & 0o077):
            raise RuntimeError("Verified local runtime and private watchdog configuration required")
        read_private(configuration, 65536)
        status = query()
        if status["installed"] and (not plist.exists() or not status.get("owned")):
            raise RuntimeError("Existing launchd service is not owned by this checkout")
        plist.parent.mkdir(parents=True, exist_ok=True)
        write_private(plist, plistlib.dumps(agent_definition(ROOT, Path(uv).resolve())).decode())
        if query()["installed"]:
            subprocess.run(["launchctl", "bootout", target], check=True, capture_output=True, timeout=15)
        # launchd can acknowledge bootout before releasing the old service.
        for attempt in range(4):
            result = subprocess.run(["launchctl", "bootstrap", f"gui/{os.getuid()}", str(plist)],
                                    capture_output=True, timeout=15)
            if result.returncode == 0:
                break
            if attempt == 3:
                raise RuntimeError("User agent bootstrap failed")
            time.sleep(0.5)
    elif args.operation == "uninstall":
        if not plist.exists():
            raise RuntimeError("No owned user-agent definition to remove")
        status = query()
        if status["installed"] and not status.get("owned"):
            raise RuntimeError("Registered service is not owned by this checkout")
        if status["installed"]:
            subprocess.run(["launchctl", "bootout", target], check=True, capture_output=True, timeout=15)
        plist.unlink()
    print(json.dumps(query(), sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        raise SystemExit("Watchdog user-agent operation failed (private details withheld)")
