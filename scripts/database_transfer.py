"""Export or restore the local or Docker database through the import directory."""

import argparse
from contextlib import closing
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import sqlite3

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def main() -> int:
    from homeio.adapters.backups import export_database, open_readonly, restore_database, validate

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("export", "import"))
    parser.add_argument("--local", action="store_true")
    parser.add_argument("--file", default="homeio.sqlite3", help="Filename inside import/")
    args = parser.parse_args()
    folder = ROOT / "import"
    path = (folder / args.file).resolve()
    if path.parent != folder.resolve():
        parser.error("--file must be a filename inside import/, without subdirectories.")
    compose = [
        "docker",
        "compose",
        "--env-file",
        str(ROOT / ".env"),
        "-f",
        str(ROOT / "compose.yaml"),
    ]
    try:
        if args.operation == "import":
            # Validate before stopping the service or touching its current database.
            with closing(open_readonly(path)) as source:
                validate(source)
        if args.local:
            from homeio.config import Settings

            database = Settings.load().database
            if args.operation == "export":
                export_database(database, path)
            else:
                backup = restore_database(database, path)
                print(f"Copia previa: {backup or 'base nueva'}")
        else:
            command = compose + [
                "run",
                "--rm",
                "-T",
                "--no-deps",
                "--entrypoint",
                "python",
                "-v",
                f"{ROOT / 'homeio/adapters'}:/transfer:ro",
                "app",
                "/transfer/backups.py",
                args.operation,
                "/data/homeio.sqlite3",
            ]
            if args.operation == "export":
                folder.mkdir(exist_ok=True)
                if path.exists():
                    raise FileExistsError("La exportación ya existe; utiliza otro FILE.")
                descriptor, name = tempfile.mkstemp(prefix=".export-", dir=folder)
                temporary = Path(name)
                try:
                    with os.fdopen(descriptor, "wb") as stream:
                        subprocess.run(command, stdout=stream, check=True)
                    with closing(open_readonly(temporary)) as exported:
                        validate(exported)
                    os.link(temporary, path)
                finally:
                    temporary.unlink(missing_ok=True)
            else:
                running = (
                    "app"
                    in subprocess.check_output(
                        compose + ["ps", "--status", "running", "--services"], text=True
                    ).splitlines()
                )
                if running:
                    subprocess.run(compose + ["stop", "app"], check=True)
                try:
                    with path.open("rb") as stream:
                        subprocess.run(command, stdin=stream, check=True)
                finally:
                    if running:
                        subprocess.run(compose + ["start", "app"], check=True)
        print(
            f"{'Exportación' if args.operation == 'export' else 'Importación'} completada: {path}"
        )
    except (OSError, ValueError, sqlite3.Error, subprocess.CalledProcessError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
