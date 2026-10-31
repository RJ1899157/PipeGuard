"""Migration entrypoint. Credentials come from the environment, never this file."""
from alembic import context
from sqlalchemy import create_engine, pool

from pipeguard.db.config import database_url
from pipeguard.db.models import Base

config = context.config
target_metadata = Base.metadata

if context.is_offline_mode():
    context.configure(url=database_url(), target_metadata=target_metadata,
                      literal_binds=True, dialect_opts={"paramstyle": "named"})
    with context.begin_transaction():
        context.run_migrations()
else:
    # Tests may supply a connection to an isolated schema.
    connection = config.attributes.get("connection")
    if connection is not None:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()
    else:
        engine = create_engine(database_url(), poolclass=pool.NullPool, hide_parameters=True)
        with engine.connect() as connection:
            context.configure(connection=connection, target_metadata=target_metadata)
            with context.begin_transaction():
                context.run_migrations()
        engine.dispose()
