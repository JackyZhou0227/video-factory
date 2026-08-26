"""Copy the six application tables from SQLite into an Alembic-managed database.

The destination must already have the schema (run ``alembic upgrade head`` first).
This is intentionally a one-shot, conservative data copy: IDs, timestamps and JSON
strings are copied as-is, while PostgreSQL identity sequences are advanced afterward.
"""

from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

from sqlalchemy import MetaData, create_engine, inspect, text

TABLES = (
    "users",
    "settings",
    "sessions",
    "subtitle_replacements",
    "bgm_tracks",
    "generation_tasks",
)


def sqlite_columns(connection: sqlite3.Connection, table: str) -> list[str]:
    return [row[1] for row in connection.execute(f'PRAGMA table_info("{table}")')]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sqlite", required=True, help="Source SQLite database path")
    parser.add_argument("--postgres-url", required=True, help="SQLAlchemy PostgreSQL URL")
    parser.add_argument("--replace", action="store_true", help="Delete destination rows before copying")
    args = parser.parse_args()

    sqlite_path = Path(args.sqlite).resolve()
    if not sqlite_path.is_file():
        raise SystemExit(f"SQLite database not found: {sqlite_path}")

    source = sqlite3.connect(str(sqlite_path))
    source.row_factory = sqlite3.Row
    destination = create_engine(args.postgres_url)
    metadata = MetaData()
    metadata.reflect(bind=destination, only=list(TABLES))
    destination_tables = inspect(destination).get_table_names()
    missing = [table for table in TABLES if table not in destination_tables]
    if missing:
        raise SystemExit(f"Destination schema is missing tables: {', '.join(missing)}")

    with destination.begin() as connection:
        if args.replace:
            for table in reversed(TABLES):
                connection.execute(text(f'DELETE FROM "{table}"'))
        else:
            existing = {
                table: connection.execute(text(f'SELECT count(*) FROM "{table}"')).scalar_one()
                for table in TABLES
            }
            occupied = {table: count for table, count in existing.items() if count}
            if occupied:
                raise SystemExit(f"Destination is not empty; use --replace explicitly: {occupied}")

        copied: dict[str, int] = {}
        for table_name in TABLES:
            target = metadata.tables[table_name]
            target_columns = {column.name for column in target.columns}
            source_names = sqlite_columns(source, table_name)
            columns = [name for name in source_names if name in target_columns]
            rows = [dict(row) for row in source.execute(f'SELECT * FROM "{table_name}"')]
            if rows:
                connection.execute(target.insert(), [{name: row[name] for name in columns} for row in rows])
            copied[table_name] = len(rows)

        for table_name in ("settings", "subtitle_replacements"):
            target = metadata.tables[table_name]
            if "id" not in target.columns:
                continue
            connection.execute(
                text(
                    f"SELECT setval(pg_get_serial_sequence('{table_name}', 'id'), "
                    f"COALESCE((SELECT MAX(id) FROM \"{table_name}\"), 1), "
                    f"(SELECT COUNT(*) > 0 FROM \"{table_name}\"))"
                )
            )

    print("Copied rows:", copied)


if __name__ == "__main__":
    main()
