"""Create local development credentials once without printing them."""
from pathlib import Path
import secrets
from local_files import write_private

root = Path(__file__).resolve().parents[1]
owner_password = secrets.token_hex(32)
content = (
    f"POSTGRES_PASSWORD={secrets.token_hex(32)}\n"
    f"PIPEGUARD_OWNER_PASSWORD={owner_password}\n"
    "PIPEGUARD_POSTGRES_PORT=55432\n"
    f"PIPEGUARD_DATABASE_URL=postgresql+psycopg://pipeguard_owner:{owner_password}@127.0.0.1:55432/pipeguard\n"
)
try:
    write_private(root / ".env", content, exclusive=True)
except FileExistsError:
    raise SystemExit(".env already exists; left unchanged")
print("Created .env with local development credentials (not displayed)")
