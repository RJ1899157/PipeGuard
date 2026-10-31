from dataclasses import replace
from uuid import uuid4
import pytest
from psycopg import sql
from orders_pipeline.loader import Warehouse


@pytest.fixture
def warehouse():
    settings = replace(Warehouse.from_environment(), prefix="test_" + uuid4().hex + "_")
    with settings.connect() as connection:
        try:
            yield settings, connection
        finally:
            for suffix in ("analytics", "staging", "raw"):
                connection.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(settings.prefix + suffix)))
