"""Fail closed when private API configuration is absent."""
from dataclasses import dataclass, field
import os
import re
from sqlalchemy.engine import make_url


@dataclass(frozen=True)
class Settings:
    database_url: str = field(repr=False)
    admin_token: str = field(repr=False)

    def __post_init__(self):
        if make_url(self.database_url).drivername != "postgresql+psycopg":
            raise ValueError("API database must use postgresql+psycopg")
        if not re.fullmatch(r"[A-Za-z0-9_-]{32,128}", self.admin_token):
            raise ValueError("Configure a generated administrator token")

    @classmethod
    def from_environment(cls):
        try:
            return cls(os.environ["PIPEGUARD_API_DATABASE_URL"], os.environ["PIPEGUARD_ADMIN_TOKEN"])
        except KeyError:
            raise RuntimeError("Run local API provisioning before starting the API") from None
