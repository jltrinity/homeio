#!/bin/sh
# Import the current MariaDB backup using Homeio's validated importer.
set -eu

PROJECT_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
SQL_FILE="$PROJECT_ROOT/mgtv3_backup_20261121_225003.sql"
MODE=docker
DRY_RUN=false

usage() {
    cat <<'HELP'
Usage: scripts/import_sql.sh [--docker | --local] [--dry-run] [--file PATH]

Import the current SQL backup into Homeio's SQLite tables.

  --docker       Use the shared database through Docker (default).
  --local        Use HOMEIO_DATABASE from the project .env.
  --dry-run      Validate the import and roll back all inserted data.
  --file PATH    Import a different SQL backup.
  --help         Show this help.

Run make docker-up first for Docker, or make setup for local use.
Local Python defaults to .venv/bin/python; override with HOMEIO_PYTHON.
The destination ledger must be empty. Existing data is never overwritten,
users are preserved, and duplicate imports are rejected.
HELP
}

while [ "$#" -gt 0 ]; do
    case "$1" in
        --docker) MODE=docker ;;
        --local) MODE=local ;;
        --dry-run) DRY_RUN=true ;;
        --file)
            if [ "$#" -lt 2 ] || [ -z "$2" ]; then
                echo 'Error: --file requires a path.' >&2
                exit 2
            fi
            SQL_FILE=$2
            shift
            ;;
        --help|-h) usage; exit 0 ;;
        *) echo "Error: unknown argument: $1" >&2; usage >&2; exit 2 ;;
    esac
    shift
done

# Resolve relative input paths before moving to the project directory.
case "$SQL_FILE" in
    /*) ;;
    *) SQL_FILE="$(pwd)/$SQL_FILE" ;;
esac
if [ ! -f "$SQL_FILE" ] || [ ! -r "$SQL_FILE" ]; then
    echo "Error: SQL file is missing or unreadable: $SQL_FILE" >&2
    exit 1
fi

cd "$PROJECT_ROOT"
if [ "$MODE" = docker ]; then
    TARGET=docker-import
    if [ "$DRY_RUN" = true ]; then TARGET=docker-import-check; fi
    exec make "$TARGET" "SQL=$SQL_FILE"
fi

LOCAL_PYTHON=${HOMEIO_PYTHON:-"$PROJECT_ROOT/.venv/bin/python"}
# Initialization is idempotent and does not delete existing users or movements.
"$LOCAL_PYTHON" -m homeio.cli init
if [ "$DRY_RUN" = true ]; then
    exec "$LOCAL_PYTHON" -m homeio.cli import-sql "$SQL_FILE" --dry-run
fi
exec "$LOCAL_PYTHON" -m homeio.cli import-sql "$SQL_FILE"
