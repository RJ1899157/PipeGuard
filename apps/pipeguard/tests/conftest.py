"""Integration tests migrate only a unique, disposable PostgreSQL schema."""
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from pipeguard.db.config import database_url


@pytest.fixture
def migrated_database():
    engine = create_engine(database_url(), hide_parameters=True)
    schema = "test_" + uuid4().hex
    try:
        with engine.connect() as connection:
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
            connection.execute(text(f'SET search_path TO "{schema}"'))
            connection.commit()
            config = Config("alembic.ini")
            config.attributes["connection"] = connection
            command.upgrade(config, "head")
            connection.commit()
            try:
                yield connection, config
            finally:
                connection.rollback()
                connection.execute(text('SET search_path TO public'))
                connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
                connection.commit()
    finally:
        engine.dispose()


@pytest.fixture
def db(migrated_database):
    connection, _ = migrated_database
    with Session(connection) as session:
        yield session
        session.rollback()
