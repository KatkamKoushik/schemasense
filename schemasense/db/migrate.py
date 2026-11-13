"""Explicit Alembic Database Migration Management CLI for SchemaSense 2.0.

Fulfills Master Architecture Requirement Item 1:
- Never executes automatic migrations on FastAPI application startup.
- Exposes explicit, auditable CLI commands for upgrades, downgrades, and checks.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

from alembic.config import Config
from alembic.util.exc import CommandError

from alembic import command
from schemasense.config import get_platform_config

logger = logging.getLogger("schemasense.db.migrate")


def get_alembic_config(
    db_url: str | None = None, config_path: str | None = None
) -> Config:
    """Constructs an Alembic Config object pointed to the platform database."""
    base_dir = Path(__file__).resolve().parent.parent.parent
    ini_file = config_path or str(base_dir / "alembic.ini")

    if not os.path.exists(ini_file):
        raise FileNotFoundError(f"Alembic configuration file not found at: {ini_file}")

    alembic_cfg = Config(ini_file)

    target_url = db_url or get_platform_config().platform_db_url
    if target_url:
        alembic_cfg.set_main_option("sqlalchemy.url", target_url)

    return alembic_cfg


def upgrade(revision: str = "head", db_url: str | None = None) -> None:
    """Executes version-controlled database schema upgrade."""
    cfg = get_alembic_config(db_url)
    print(f"[*] Upgrading platform database to revision: '{revision}'...")
    command.upgrade(cfg, revision)
    print("[+] Database upgrade complete.")


def downgrade(revision: str = "-1", db_url: str | None = None) -> None:
    """Executes version-controlled database schema downgrade."""
    cfg = get_alembic_config(db_url)
    print(f"[*] Downgrading platform database to revision: '{revision}'...")
    command.downgrade(cfg, revision)
    print("[+] Database downgrade complete.")


def check_status(db_url: str | None = None) -> bool:
    """Non-destructively checks whether the database is synchronized with the migration head."""
    cfg = get_alembic_config(db_url)
    print("[*] Checking database migration alignment...")
    try:
        command.check(cfg)
        print("[+] Database schema is synchronized with migration head.")
        return True
    except (CommandError, RuntimeError, ValueError) as e:
        print(
            f"[!] Database schema out of sync or pending migrations: {e}",
            file=sys.stderr,
        )
        return False


def main() -> int:
    """CLI entry point for `python -m schemasense.db.migrate`."""
    parser = argparse.ArgumentParser(
        description="SchemaSense 2.0 Platform Database Migration Tool"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # Upgrade
    upgrade_parser = subparsers.add_parser(
        "upgrade", help="Apply pending database migrations"
    )
    upgrade_parser.add_argument(
        "revision", nargs="?", default="head", help="Target revision (default: head)"
    )
    upgrade_parser.add_argument(
        "--db-url", default=None, help="Override target database connection URI"
    )

    # Downgrade
    downgrade_parser = subparsers.add_parser(
        "downgrade", help="Revert database migrations"
    )
    downgrade_parser.add_argument(
        "revision", nargs="?", default="-1", help="Target revision (default: -1)"
    )
    downgrade_parser.add_argument(
        "--db-url", default=None, help="Override target database connection URI"
    )

    # Check
    check_parser = subparsers.add_parser(
        "check", help="Verify if database schema matches migration head"
    )
    check_parser.add_argument(
        "--db-url", default=None, help="Override target database connection URI"
    )

    args = parser.parse_args()

    try:
        if args.command == "upgrade":
            upgrade(revision=args.revision, db_url=args.db_url)
        elif args.command == "downgrade":
            downgrade(revision=args.revision, db_url=args.db_url)
        elif args.command == "check":
            is_synced = check_status(db_url=args.db_url)
            return 0 if is_synced else 1
        return 0
    except (CommandError, RuntimeError, ValueError, OSError) as err:
        print(f"[!] Migration command failed: {err}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
