"""Explicit database configuration; never log connection credentials."""
import os

from sqlalchemy.engine import URL, make_url


def database_url() -> URL:
    value = os.environ.get("PIPEGUARD_DATABASE_URL")
    if not value:
        raise RuntimeError("Set PIPEGUARD_DATABASE_URL before running database commands")
    url = make_url(value)
    if url.drivername != "postgresql+psycopg":
        raise ValueError("PIPEGUARD_DATABASE_URL must use postgresql+psycopg")
    return url
