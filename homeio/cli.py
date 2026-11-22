"""Administrative operations are intentionally available only from the console."""

import argparse
import getpass
import json
import os
import sqlite3
import sys
from pathlib import Path
from wsgiref.simple_server import make_server
from homeio.adapters.auth import Authentication
from homeio.adapters.legacy_import import import_dump
from homeio.adapters.sqlite import initialize
from homeio.config import Settings
from homeio.domain.accounting import ValidationError


def main() -> int:
    parser = argparse.ArgumentParser(description="Homeio household accounting")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("init", help="Initialize the database without deleting existing data")
    commands.add_parser("serve", help="Start the local development WSGI server")
    user = commands.add_parser("user", help="Create a household user or reset a password")
    user.add_argument("--username")
    user.add_argument("--reset-password", action="store_true")
    importer = commands.add_parser(
        "import-sql", help="Import a supported MariaDB backup into an empty ledger"
    )
    importer.add_argument("file", type=Path)
    importer.add_argument("--dry-run", action="store_true")
    backup = commands.add_parser("backup", help="Create a consistent SQLite backup")
    backup.add_argument("destination", type=Path)
    args = parser.parse_args()
    try:
        settings = Settings.load()
        if args.command == "init":
            initialize(settings.database)
            print("Database initialized.")
        elif args.command == "user":
            username = args.username or input("Username: ")
            password = getpass.getpass("Password (at least 12 characters): ")
            if password != getpass.getpass("Repeat password: "):
                raise ValidationError("Las contraseñas no coinciden.")
            Authentication(settings.database, settings.secret).create_user(
                username, password, reset=args.reset_password
            )
            print("User updated." if args.reset_password else "User created.")
        elif args.command == "import-sql":
            result = import_dump(settings.database, args.file, dry_run=args.dry_run)
            print(
                (
                    "Validation completed; no changes saved. "
                    if args.dry_run
                    else "Import completed. "
                )
                + json.dumps(result)
            )
        elif args.command == "backup":
            # Exclusive creation prevents accidental overwrites of an existing backup.
            with args.destination.open("xb"):
                args.destination.chmod(0o600)
            with (
                sqlite3.connect(settings.database) as source,
                sqlite3.connect(args.destination) as target,
            ):
                source.backup(target)
            print("Backup completed.")
        elif args.command == "serve":
            from homeio.web.app import App

            host = os.getenv("HOMEIO_HOST", "127.0.0.1")
            port = int(os.getenv("HOMEIO_PORT", "8000"))
            with make_server(host, port, App(settings)) as server:
                print(f"Homeio: http://{host}:{port} (development only)", flush=True)
                server.serve_forever()
    except (ValueError, OSError, sqlite3.Error) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
