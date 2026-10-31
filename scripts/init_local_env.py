"""Create local development credentials once without printing them."""
import os
from pathlib import Path
import secrets

root = Path(__file__).resolve().parents[1]
owner_password = secrets.token_hex(32)
content = (
    f"POSTGRES_PASSWORD={secrets.token_hex(32)}\n"
    f"PIPEGUARD_OWNER_PASSWORD={owner_password}\n"
    "PIPEGUARD_POSTGRES_PORT=55432\n"
    f"PIPEGUARD_DATABASE_URL=postgresql+psycopg://pipeguard_owner:{owner_password}@127.0.0.1:55432/pipeguard\n"
)
try:
    descriptor = os.open(root / ".env", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
except FileExistsError:
    raise SystemExit(".env already exists; left unchanged")
with os.fdopen(descriptor, "w") as stream:
    stream.write(content)
print("Created .env with local development credentials (not displayed)")
