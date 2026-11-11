from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool, text

import app.models  # Register all models.
from app.core.config import get_settings
from app.db.base import Base


config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def include_name(name, type_, parent_names):
    if type_ == "schema":
        return name == "proofvault"

    return True


def include_object(obj, name, type_, reflected, compare_to):
    if type_ == "table":
        return (
            obj.schema == "proofvault"
            and not obj.info.get("externally_managed", False)
        )

    return True


def run_migrations_online():
    settings = get_settings()

    connectable = create_engine(
        settings.database_url.get_secret_value(),
        poolclass=pool.NullPool,
        connect_args={"connect_timeout": 10},
        hide_parameters=True,
    )

    try:
        with connectable.connect() as connection:
            with connection.begin():
                server_version = int(
                    connection.execute(
                        text("SHOW server_version_num")
                    ).scalar_one()
                )

                if server_version < 150000:
                    raise RuntimeError(
                        "This schema requires PostgreSQL 15 or newer."
                    )

                # Bootstrap the namespace before Alembic creates
                # proofvault.alembic_version.
                connection.execute(
                    text("CREATE SCHEMA IF NOT EXISTS proofvault")
                )

                # Make extension types available without changing
                # the default application schema to proofvault.
                connection.execute(
                    text("SET LOCAL search_path TO public, extensions")
                )

                context.configure(
                    connection=connection,
                    target_metadata=target_metadata,
                    include_schemas=True,
                    include_name=include_name,
                    include_object=include_object,
                    version_table_schema="proofvault",
                    compare_type=True,
                )

                with context.begin_transaction():
                    context.run_migrations()
    finally:
        connectable.dispose()


if context.is_offline_mode():
    raise RuntimeError(
        "Offline migrations are not configured. "
        "Run Alembic with a database connection."
    )
else:
    run_migrations_online()