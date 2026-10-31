"""Start the locally bound API without request URL/header logging."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps/pipeguard/src"))
import uvicorn

if __name__ == "__main__":
    uvicorn.run("pipeguard.api.app:create_app", factory=True, host="127.0.0.1", port=8000,
                proxy_headers=False, access_log=False)
