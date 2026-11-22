# Homeio

Household accounting in Python 3.12+, SQLite, and a small custom WSGI framework.
HTML is rendered with Jinja, styled with Bootstrap in a light theme, and enhanced
with Chart.js. There is no Flask or Django dependency.

## Features

- Private login for console-provisioned users; one shared household ledger.
- Monthly income, expenses, balance, annual evolution, and expense categories.
- Searchable, paginated movements; create, edit, and archive income and expenses.
- Manage categories and establishments, including inactive entries.
- Import the supplied MariaDB backup into SQLite with validation and a dry run.
- Configuration in `.env`, Makefile commands, and Docker Compose with persistent data.

All amounts are stored as integer euro cents. Archived movements remain in SQLite
but do not contribute to summaries. This is a household income/expense ledger,
not a double-entry accounting or bank-reconciliation system. Every provisioned
user has access to the same household; separate households require separate instances.

## Start with Docker

Docker configuration lives in `docker/`: `Dockerfile`, `compose.yaml`,
`entrypoint.sh`, and `.dockerignore`. The root `.dockerignore` is a symlink to
`docker/.dockerignore` so both modern and classic builders apply the same context
exclusions. The build context and `.env` remain at the project root. Compose uses
the explicit project name `homeio` for its containers.

Requires Docker Engine and the Compose plugin. Image builds use Buildx when
available, with a fallback to the classic builder for Docker installations that
still support it.

```bash
make docker-up
make docker-user
# Optional: import the supplied backup before entering any household data.
make docker-import-check SQL=mgtv3_backup_20261121_225003.sql
make docker-import SQL=mgtv3_backup_20261121_225003.sql
```

Open **http://localhost:8000** and sign in with the username and password entered
at the `docker-user` prompt. There is no default account or password.
`docker-up` creates `.env` with a random secret if absent and initializes the schema.
Imports use a temporary read-only bind mount; the SQL file is never copied into the
image. Docker bind-mounts the project directory `./data` at `/data`, so both
local commands and Docker use the same `data/homeio.sqlite3` file. Keep
`HOMEIO_DATABASE=data/homeio.sqlite3` in `.env` for local commands; Docker uses
`/data/homeio.sqlite3`. A user created with `make user` is also available in Docker,
and an SQL import from either environment is immediately visible in both.

`make env` creates `data/` and records `HOMEIO_UID`/`HOMEIO_GID` for the host user.
Docker runs with those IDs to read and write the private SQLite files without root.
When moving the checkout to another machine, set these values to `id -u` and `id -g`.
Use a local filesystem for the shared SQLite directory.

```bash
make docker-logs
make docker-down
# Reset a password and revoke that user's sessions:
docker compose --env-file .env -f docker/compose.yaml exec app python -m homeio.cli user --reset-password
# Export a consistent backup; choose a new filename each time:
docker compose --env-file .env -f docker/compose.yaml exec app python -m homeio.cli backup /data/backup.sqlite3
docker compose --env-file .env -f docker/compose.yaml cp app:/data/backup.sqlite3 ./backup.sqlite3
```

`docker-down` preserves the database in `./data`. The container runs as an
unprivileged user with a read-only root filesystem and a writable data directory.

## Deploy with Coolify

Use `docker/compose-coolify.yaml` for production. The local `docker/compose.yaml`
continues to share `./data` with local commands. The Coolify configuration instead
mounts a persistent named volume at `/data`, uses the image's non-root user
`10001:10001`, and receives configuration from Coolify without a local `.env`.
A new volume inherits the image's `/data` ownership; an existing volume must
already allow UID/GID `10001:10001` to read and write its directory and files.

Create a Git-based application with these settings:

| Setting | Value |
| --- | --- |
| Build strategy | Docker Compose |
| Base Directory | `/` |
| Docker Compose Location | `/docker/compose-coolify.yaml` |
| Public service | `app` |
| Domain | `https://homeio.example.com:8000` (replace the hostname) |

The build context is the repository root (`.`), with Dockerfile
`docker/Dockerfile`. Keep Base Directory at `/`; do not switch it to `/docker`.
For local configuration validation, explicitly use the same project directory:

```bash
docker compose --project-directory . --env-file .env -f docker/compose-coolify.yaml config --quiet
```

The domain's port selects the internal container port; public access uses HTTPS
on port 443. No application port is published directly on the server. Configure
DNS for the hostname and enable HTTPS through Coolify's proxy.

Set `HOMEIO_SECRET_KEY` to a random secret of at least 32 characters and
`HOMEIO_ALLOWED_HOSTS` to your hostname without scheme, path, or port. Optional
`HOMEIO_SESSION_HOURS` defaults to 8. Generate a secret locally with:

```bash
python3 -c 'import secrets; print(secrets.token_urlsafe(48))'
```

The Compose file fixes `HOMEIO_DATABASE=/data/homeio.sqlite3`, secure cookies,
and HTTPS headers. It includes a Python health check, so curl is not required.
Deploy and check the logs and health status. For a fresh database, create a user
in the `app` container terminal with `python -m homeio.cli user`.

To keep existing users and movements, export a consistent local snapshot using
`make db-export-local FILE=homeio-coolify.sqlite3`. Transfer that snapshot privately
to the server, stop the application, and restore it into its persistent volume
as `homeio.sqlite3` with owner `10001:10001` and permissions `600` before restarting.
Back up any existing destination database first. Storage on the deployment server
does not synchronize with your workstation's `data/` directory.

For daily backups, add a Scheduled Task targeting `app`, enable Run in a shell,
and use frequency `0 3 * * *` with this command:

```sh
mkdir -p /data/backups && python -m homeio.cli backup "/data/backups/homeio-$(date -u +%Y%m%dT%H%M%S)-$$.sqlite3"
```

The schedule follows the deployment server's timezone. Execute it manually once
and verify the output. These snapshots persist in the volume; configure separate
off-server copies and retention. The task only runs while the container is running.

See [Coolify's Compose configuration](https://coolify.io/docs/applications/builds/docker-compose)
and [scheduled tasks](https://coolify.io/docs/applications/operations/scheduled-tasks).

## Upgrading from the previous name

Configuration keys now use `HOMEIO_` instead of `SPENDIO_`; rename the keys in
an existing `.env` while preserving secrets and other settings. Existing SQLite
files remain compatible. To share storage, back up the chosen database, restore
it as `data/homeio.sqlite3`, and set `HOMEIO_DATABASE=data/homeio.sqlite3`.
The Python package is now `homeio`, and the session cookie is `homeio_session`,
so users must sign in again.

Docker Compose uses project `homeio` and the shared host directory `./data`.
Existing `spendio` or `homeio-data` named volumes are not migrated automatically. Before switching,
export a database backup from the old deployment and stop its containers. Restore
the backup into the new deployment with `make db-import FILE=<backup.sqlite3>`
after placing it in `import/`. Keep the old volume until the restored data has
been verified.

## Start locally

Requires Python 3.12+ with `venv`, Make, and package-index access for installation.

```bash
make setup
make user
make import-check SQL=mgtv3_backup_20261121_225003.sql
make import-sql SQL=mgtv3_backup_20261121_225003.sql
make run
```

The local development server listens at **http://127.0.0.1:8000**. Use Gunicorn
(`make serve`) or Docker for deployment. Do not expose the development server.
`make init` is repeatable and preserves existing data.

## Development commands

Run `make help` to list all commands.

| Command | Purpose |
| --- | --- |
| `make venv` | Create `.venv` |
| `make env` | Create a private `.env` with a random secret; preserve an existing file |
| `make install` | Install pinned runtime dependencies from `requirements.txt` |
| `make install-dev` | Install runtime dependencies, Ruff, and pip-tools |
| `make compile` | Compile runtime and development requirements using pip-tools |
| `make setup` | Install runtime dependencies and initialize configuration/SQLite |
| `make init` | Initialize the database without deleting data |
| `make user` | Create a user interactively |
| `make reset-password` | Reset a password and invalidate all sessions for that user |
| `make run` | Run the local development WSGI server |
| `make serve` | Run Gunicorn on `127.0.0.1:8000` |
| `make test` | Run the standard-library unittest suite |
| `make check` | Run tests and Python compilation checks |
| `make lint` / `make format` | Check / format Python code with Ruff |
| `make import-check SQL=path.sql` | Validate import, then roll back all writes |
| `make import-sql SQL=path.sql` | Commit an initial import into an empty ledger |
| `make backup BACKUP=data/new-backup.sqlite3` | Create a consistent backup without overwriting |

Edit `requirements.in` or `requirements-dev.in`, run `make compile`, and review
and commit the generated requirements files. Both `requirements.txt` and
`requirements-dev.txt` are compiled with pip-tools, including transitive
dependencies. The compiler's pip and Click versions are pinned for compatibility.
`make install-dev` installs the compiled development requirements.

Tests use temporary databases and synthetic data. They cover business invariants,
exact monetary arithmetic, imports and rollback, CRUD, SQL injection attempts,
HTML escaping, CSRF, login throttling, cookie attributes, session expiry, and
revocation. They never modify the real household database.

## Importing the supplied SQL

### Export and restore a complete SQLite database

Export the Docker database and restore that same file using:

```bash
make db-export                       # Writes import/homeio.sqlite3
make db-import                       # Restores import/homeio.sqlite3
make db-export FILE=household.sqlite3 # Writes import/household.sqlite3
make db-import FILE=household.sqlite3 # Restores the same file
```

The `import/` folder is created as needed and its contents are excluded from Git
and Docker images. Exports are consistent SQLite snapshots, including household
data, users, password hashes, and import history. Existing export files are never
overwritten; choose another `FILE` to keep multiple snapshots. Only filenames
inside `import/` are accepted.

Restoration **replaces the entire destination database**. It validates the schema,
integrity, and foreign keys before any changes, and saves the current database next
to it as `homeio.before-import-<timestamp>-<id>.sqlite3`. Docker safety copies live
in `/data`, visible locally under `./data`. Active sessions and login counters are cleared
after restoration, so users must sign in again using the restored credentials.
The Docker command stops the app during restoration and starts it again if it was
running. Stop any local server as well and do not run other administrative writes
during a restore, since both environments share the same file.

For local SQLite, use `make db-export-local` and `make db-import-local` with the
same `FILE` option. Stop both the local server and Docker before a local restore,
and restart them afterwards.
These commands use `.env` and the local virtual environment. No real database is
restored automatically when these commands are added or tested.

These native SQLite snapshots are distinct from the MariaDB SQL migration below.

### Import a legacy MariaDB dump

Use the standalone script to load the current backup into the Docker SQLite
database (run `make docker-up` first):

```bash
./scripts/import_sql.sh --dry-run
./scripts/import_sql.sh
```

The default input is `mgtv3_backup_20261121_225003.sql` in the project root.
For the local SQLite database configured in `.env`, run `make setup` first and use:

```bash
./scripts/import_sql.sh --local --dry-run
./scripts/import_sql.sh --local
```

Use `--file /path/to/backup.sql` to choose another file. Relative paths are resolved
from the calling directory. `HOMEIO_PYTHON` optionally selects a local interpreter;
otherwise the script uses `.venv/bin/python`. Docker and local databases are
separate destinations. Repeated imports fail with an explanation and leave existing
data unchanged. The script reuses the validated importer described below.

The supported export contains `category`, `site`, and `movement` tables. The
importer parses allowlisted `INSERT ... VALUES` data; it never executes source SQL.
DDL, SQL settings, locks, comments, and Doctrine migration history are not applied.
Unknown insert tables, expressions, missing references, and invalid records cause
failure. The entire import is transactional.

| MariaDB source | SQLite destination |
| --- | --- |
| `category` | `category`, preserving IDs, names, types, activity, and timestamps |
| `site` | `site`, preserving IDs, names, types, activity, and timestamps |
| `movement.amount` (`DOUBLE`) | `movement.amount_cents` (`INTEGER`) |
| `movement.valid_date` | ISO calendar date (`YYYY-MM-DD`) |
| Other movement fields | Preserved, including IDs, references, and activity flags |
| Doctrine migration history | Ignored; unrelated to the new schema |

The supplied backup contains **6,125 movements, 33 categories, and 161
establishments**. Five legacy movements have a zero amount; imports preserve
these records, while newly entered movements require a positive amount. Legacy
negative amounts are also preserved if present. New movements represent income
or expenses with their type, not with a negative amount.

Amounts are parsed with `Decimal`. Legacy floating-point artifacts, if any, are
rounded to cents with `ROUND_HALF_UP`, and their count is reported. A dry run of
the supplied backup required **zero rounded amounts**. Date formats supported are
ISO dates, ISO timestamps without a zone, `DD/MM/YYYY`, `YYYY/MM/DD`, and `DD-MM-YYYY`.

Import is an initial migration into an empty household ledger. Existing users and
sessions are allowed, but categories, sites, and movements must be empty. Duplicate
imports and overwriting existing financial data are rejected. This avoids unsafe
ID remapping and accidental duplication. The source file is read-only and is
limited to 50 MiB. Import is console-only, not a public upload endpoint.

## Configuration and security

See [`.env.example`](.env.example). Existing environment variables take precedence
over `.env`.

| Setting | Purpose |
| --- | --- |
| `HOMEIO_SECRET_KEY` | Random secret, at least 32 characters; used for HMAC login-throttle keys |
| `HOMEIO_DATABASE` | Use `data/homeio.sqlite3` locally to share Docker’s `/data/homeio.sqlite3` |
| `HOMEIO_UID` / `HOMEIO_GID` | Host user/group IDs for Docker access to `./data`; set by `make env` |
| `HOMEIO_HOST` | Development-server bind address (default `127.0.0.1`) |
| `HOMEIO_PORT` | Development-server and Docker published port (default `8000`) |
| `HOMEIO_ALLOWED_HOSTS` | Comma-separated explicit hostnames, without scheme or port |
| `HOMEIO_COOKIE_SECURE` | Send session cookies only over HTTPS when `true` |
| `HOMEIO_HTTPS` | Enable HSTS; requires secure cookies and an HTTPS deployment |
| `HOMEIO_SESSION_HOURS` | Fixed authenticated session lifetime, 1–24 hours (default 8) |
| `HOMEIO_VERSION` | Version shown next to the Homeio logo (default `dev`), e.g. `1.2.0` |

Set `HOMEIO_VERSION` in `.env` locally or in Coolify's environment variables.
Restart the local server or recreate/redeploy the container after changing it.

Passwords use independently salted `hashlib.scrypt` hashes. Login rotates opaque
session tokens; only token hashes are stored in SQLite. Anonymous login sessions
last 15 minutes. Sessions are server-side and revocable. Forms, including login
and logout, require a session-bound CSRF token. Cookies are HttpOnly and SameSite=Lax.
Failed logins are limited by username and remote IP using SQLite-backed counters:
five attempts per username and thirty per IP in a 15-minute window. Successful
logins clear the username counter but still count toward the IP limit. The app
does not trust client-provided forwarding headers for login limits.

Templates autoescape HTML; database queries bind values; hostnames are checked;
request bodies are limited; CSP, clickjacking, referrer, and MIME-sniffing protections
are set. There is no public registration, password email reset, or default user.
Passwords are entered through an interactive prompt, not command-line arguments.

For an internet-facing deployment, place the application behind an HTTPS reverse
proxy, set the exact hostname in `HOMEIO_ALLOWED_HOSTS`, and enable both
`HOMEIO_HTTPS=true` and `HOMEIO_COOKIE_SECURE=true`. The proxy must terminate TLS,
redirect HTTP to HTTPS, and restrict direct backend access. Since the app uses the
actual peer IP, proxied requests may share the proxy's login limit; use proxy-side
rate limiting as well. Local HTTP deliberately leaves secure cookies disabled.

Bootstrap 5.3.3 CSS and Chart.js 4.4.8 load from versioned jsDelivr URLs; the browser
needs internet access for these assets. Bootstrap includes an integrity hash.
Tables and amounts remain server-rendered if charts cannot load. See the official
[Chart.js responsive charts guide](https://www.chartjs.org/docs/latest/configuration/responsive.html).
Before an offline deployment, vendor these dependencies and restrict CSP to self.

`.env`, SQLite files, and the supplied financial backup are excluded from Git and
Docker builds. Keep filesystem access limited to the household administrator and
store backups securely.

## Architecture

```text
homeio/
  domain/         Movement invariants and exact monetary values
  application/    Accounting use cases and the ledger persistence port
  adapters/       SQLite, legacy SQL reader, passwords and sessions
  web/            Custom WSGI router, HTTP adapter, Jinja templates, CSS and JS
  config.py       Environment-based composition settings
  cli.py          Initialization, users, import, backup, development server
```

The domain and application have no web-framework or database imports. The web
adapter composes the application and SQLite adapter; query methods return view
data without pushing rendering concerns into the domain. Database schema version
1 is initialized idempotently; future schema changes must introduce explicit,
versioned migrations instead of relying on `CREATE TABLE IF NOT EXISTS` alone.

See [CHANGELOG.md](CHANGELOG.md) for project history and [AGENTS.md](AGENTS.md) for
engineering and UI conventions.
