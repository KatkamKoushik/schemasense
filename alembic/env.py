"""Alembic Environment Script for SchemaSense 2.0 Platform Migrations."""

from __future__ import annotations

import logging
from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

# Ensure all models are registered in Base.metadata
import schemasense.db.models  # noqa: F401
from alembic import context
from schemasense.config import get_platform_config
from schemasense.db.base import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

logger = logging.getLogger("alembic.env")
target_metadata = Base.metadata


def get_target_url() -> str:
    """Retrieves target database connection URL from runtime configuration or ini file."""
    cfg = get_platform_config()
    if cfg.platform_db_url:
        return cfg.platform_db_url
    return config.get_main_option(
        "sqlalchemy.url", "sqlite:///./schemasense_platform.db"
    )


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    url = get_target_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = get_target_url()

    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
