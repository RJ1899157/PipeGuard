"""Launch the incident worker using only .env.monitoring credentials."""
import os
from pathlib import Path
import sys

os.umask(0o077)
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps/pipeguard/src"))
from pipeguard.detection.worker import main

if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(0)
    except Exception:
        raise SystemExit("Monitor startup failed (private details withheld)")
