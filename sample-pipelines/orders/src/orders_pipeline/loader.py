"""Validate a bounded CSV snapshot before replacing warehouse raw rows atomically."""
import csv
import io
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import os
from pathlib import Path
import re

import psycopg
from psycopg import sql

HEADERS = ["order_id", "customer_id", "ordered_at", "quantity", "unit_price", "status"]
MAX_BYTES = 5 * 1024 * 1024
MAX_ROWS = 10000


class InvalidSource(ValueError):
    """Safe structural error; never embed source cell values."""


@dataclass(frozen=True)
class Warehouse:
    host: str
    port: int
    database: str
    user: str
    password: str = field(repr=False)
    prefix: str = ""

    @classmethod
    def from_environment(cls):
        prefix = os.environ.get("ORDERS_SCHEMA_PREFIX", "")
        if not re.fullmatch(r"[a-z][a-z0-9_]{0,39}_|", prefix):
            raise ValueError("Invalid warehouse schema prefix")
        database = os.environ.get("ORDERS_DATABASE", "sample_warehouse")
        user = os.environ.get("ORDERS_USER", "sample_orders")
        host = os.environ.get("ORDERS_HOST", "127.0.0.1")
        if database != "sample_warehouse" or user != "sample_orders" or host not in ("127.0.0.1", "localhost"):
            raise ValueError("This workload targets only its independent local sample warehouse")
        return cls(host, int(os.environ.get("ORDERS_PORT", "55432")), database, user,
                   os.environ["DBT_ENV_SECRET_ORDERS_PASSWORD"], prefix)

    def connect(self):
        return psycopg.connect(host=self.host, port=self.port, dbname=self.database,
                               user=self.user, password=self.password, connect_timeout=5,
                               options="-cstatement_timeout=30000 -clock_timeout=5000", autocommit=True)


def parse_orders(path: Path):
    with path.open("rb") as stream:
        raw = stream.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise InvalidSource("source_too_large")
    try:
        content = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise InvalidSource("source_not_utf8") from None
    rows = []
    try:
        reader = csv.DictReader(io.StringIO(content, newline=""), strict=True)
        if reader.fieldnames != HEADERS:
            raise InvalidSource("unexpected_columns")
        for number, row in enumerate(reader, 2):
            if len(rows) >= MAX_ROWS:
                raise InvalidSource("too_many_rows")
            if None in row or any(value is None or value == "" for value in row.values()):
                raise InvalidSource(f"invalid_row_shape_at_line_{number}")
            try:
                if not re.fullmatch(r"[1-9][0-9]{0,9}", row["order_id"]):
                    raise ValueError
                if not re.fullmatch(r"C[0-9]{3,10}", row["customer_id"]):
                    raise ValueError
                if not re.fullmatch(r"[1-9][0-9]{0,6}", row["quantity"]):
                    raise ValueError
                if not re.fullmatch(r"[0-9]{1,10}(\.[0-9]{1,2})?", row["unit_price"]):
                    raise ValueError
                price = Decimal(row["unit_price"])
                timestamp = datetime.fromisoformat(row["ordered_at"].replace("Z", "+00:00"))
                if timestamp.tzinfo is None or timestamp.utcoffset() is None:
                    raise ValueError
                if row["status"] not in ("completed", "cancelled"):
                    raise ValueError
                rows.append((int(row["order_id"]), row["customer_id"], timestamp.astimezone(timezone.utc),
                             int(row["quantity"]), price, row["status"]))
            except (ValueError, OverflowError, InvalidOperation):
                raise InvalidSource(f"invalid_values_at_line_{number}") from None
    except csv.Error:
        raise InvalidSource("malformed_csv") from None
    if not rows:
        raise InvalidSource("empty_snapshot")
    return rows


# Shared by the runner and loader; one database-scoped key for full-snapshot replacement.
WAREHOUSE_LOCK = 735821904


def replace_orders(connection, rows, prefix=""):
    schema = sql.Identifier(prefix + "raw")
    table = sql.Identifier(prefix + "raw", "orders")
    with connection.transaction():
        connection.execute("SELECT pg_advisory_xact_lock(%s)", (WAREHOUSE_LOCK,))
        connection.execute(sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(schema))
        connection.execute(sql.SQL("""CREATE TABLE IF NOT EXISTS {} (
            order_id bigint NOT NULL, customer_id text NOT NULL, ordered_at timestamptz NOT NULL,
            quantity integer NOT NULL CHECK (quantity > 0), unit_price numeric(12,2) NOT NULL CHECK (unit_price >= 0),
            status text NOT NULL CHECK (status IN ('completed', 'cancelled'))
        )""").format(table))
        connection.execute(sql.SQL("DELETE FROM {}").format(table))
        with connection.cursor() as cursor:
            cursor.executemany(sql.SQL("INSERT INTO {} VALUES (%s,%s,%s,%s,%s,%s)").format(table), rows)
