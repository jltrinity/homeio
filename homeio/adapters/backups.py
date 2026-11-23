"""Consistent SQLite snapshots and validated full-database restores."""

import argparse
from contextlib import closing
from datetime import datetime, timezone
import os
from pathlib import Path
import secrets
import shutil
import sqlite3
import sys
import tempfile


def open_readonly(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=15)


def validate(db: sqlite3.Connection) -> None:
    """Accept only the current application's schema, without extra executable objects."""
    query = "SELECT type,name,tbl_name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name"
    with closing(sqlite3.connect(":memory:")) as reference:
        reference.executescript(Path(__file__).with_name("schema.sql").read_text())
        if db.execute(query).fetchall() != reference.execute(query).fetchall():
            raise ValueError("El archivo no tiene el esquema compatible de Homeio.")
    if db.execute("SELECT version FROM schema_version").fetchall() != [(1,)]:
        raise ValueError("Versión de base de datos incompatible.")
    if db.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
        raise ValueError("El archivo SQLite está dañado.")
    if db.execute("PRAGMA foreign_key_check").fetchall():
        raise ValueError("La base de datos contiene relaciones inválidas.")


def export_database(database: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        raise FileExistsError("El archivo de exportación ya existe; utiliza otro nombre.")
    descriptor, name = tempfile.mkstemp(prefix=".homeio-export-", dir=destination.parent)
    os.close(descriptor)
    temporary = Path(name)
    try:
        with (
            closing(open_readonly(database)) as source,
            closing(sqlite3.connect(temporary)) as target,
        ):
            source.backup(target)
            validate(target)
        # Publish exclusively, without replacing an existing backup even in a race.
        os.link(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def export_sql(database: Path, destination: Path) -> None:
    """Dump a consistent snapshot as SQLite schema and INSERT statements."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        raise FileExistsError("El archivo de exportación ya existe; utiliza otro nombre.")
    with tempfile.TemporaryDirectory(prefix=".homeio-sql-", dir=destination.parent) as directory:
        snapshot = Path(directory) / "snapshot.sqlite3"
        export_database(database, snapshot)
        temporary = Path(directory) / "dump.sql"
        descriptor = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            with closing(open_readonly(snapshot)) as source:
                for statement in source.iterdump():
                    output.write(statement + "\n")
        # Publish only a complete dump, preserving any concurrently created destination.
        os.link(temporary, destination)


def restore_database(
    database: Path, source_path: Path, backup_directory: Path | None = None
) -> Path | None:
    if database.resolve() == source_path.resolve():
        raise ValueError("El origen y el destino deben ser distintos.")
    database.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="homeio-restore-") as directory:
        staged = Path(directory) / "restore.sqlite3"
        with (
            closing(open_readonly(source_path)) as source,
            closing(sqlite3.connect(staged)) as snapshot,
        ):
            source.backup(snapshot)
            validate(snapshot)
            # Restoring credentials must not resurrect old authenticated sessions.
            with snapshot:
                snapshot.execute("DELETE FROM session")
                snapshot.execute("DELETE FROM login_attempt")
            safety_copy = None
            if database.exists():
                stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
                safety_copy = (backup_directory or database.parent) / (
                    f"{database.stem}.before-import-{stamp}-{secrets.token_hex(4)}.sqlite3"
                )
                export_database(database, safety_copy)
            else:
                descriptor = os.open(database, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                os.close(descriptor)
            # SQLite's backup API replaces the destination in a single transaction.
            with closing(sqlite3.connect(database, timeout=15)) as target:
                snapshot.backup(target)
        return safety_copy


def main() -> int:
    """Stream snapshots through Docker without changing host-file ownership."""
    parser = argparse.ArgumentParser()
    parser.add_argument("operation", choices=("export", "import"))
    parser.add_argument("database", type=Path, nargs="?")
    parser.add_argument("--backup-directory", type=Path)
    args = parser.parse_args()
    try:
        if args.database is None:
            from homeio.config import Settings

            settings = Settings.load()
            args.database = settings.database
            args.backup_directory = args.backup_directory or settings.backup
        with tempfile.TemporaryDirectory(prefix="homeio-transfer-") as directory:
            snapshot = Path(directory) / "snapshot.sqlite3"
            if args.operation == "export":
                export_database(args.database, snapshot)
                with snapshot.open("rb") as stream:
                    shutil.copyfileobj(stream, sys.stdout.buffer)
            else:
                with snapshot.open("xb") as stream:
                    shutil.copyfileobj(sys.stdin.buffer, stream)
                backup = restore_database(args.database, snapshot, args.backup_directory)
                print(f"Importación completada. Copia previa: {backup or 'base nueva'}")
    except (OSError, ValueError, sqlite3.Error) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
