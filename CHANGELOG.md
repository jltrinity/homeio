# Changelog

Notable changes to Homeio are recorded in this file.

Record new changes under `Unreleased`, grouped as `Added`, `Changed`, `Deprecated`,
`Removed`, `Fixed`, or `Security` as appropriate. When publishing a release, move
its entries into a versioned section with the release date (`YYYY-MM-DD`).

## [Unreleased]

### Fixed

- Renamed the Coolify definition to `compose-coolify.yaml` and resolved
  its build context from the repository root; updated deployment settings.

### Added

- Configurable `HOMEIO_VERSION` label next to the header logo, available locally
  and in Coolify, with `dev` as the default.

- Quick expense/income filters on the movements page, defaulting to expenses
  and preserving the selection in search and pagination.

- Dedicated Coolify Compose configuration with persistent SQLite storage,
  required deployment variables, HTTPS settings, and a Python health check.
  Documented deployment, data migration, and daily backup scheduling.

- Makefile commands to export and restore complete SQLite snapshots through
  `import/`, for Docker and local databases, with validation, automatic safety
  backups, session revocation, and Docker service stop/start during restoration.
- Executable `scripts/import_sql.sh` to load the current SQL backup into Docker
  or local SQLite, with a dry run and an optional source path.
- Initial project README, license, and Git ignore rules.
- Python agent guidelines for Domain-Driven Design, hexagonal architecture,
  security, testing, and English code comments and docstrings.
- Project changelog.
- Household accounting application with a custom WSGI framework, Jinja HTML
  templates, light Bootstrap layouts, and JavaScript charts using Chart.js.
- Monthly summaries, searchable paginated movements, movement creation/editing/
  archiving, and editable category and establishment catalogs.
- SQLite persistence with integer-cent amounts and domain/application/adapter
  boundaries.
- Validated MariaDB dump import preserving identifiers, relationships, dates, and
  activity flags, with dry runs, atomic writes, and duplicate-import protection.
- Console user management, session-revoking password resets, and SQLite backups.
- Environment configuration, Makefile workflows, pinned runtime dependencies,
  requirement compilation, Docker Compose, and a persistent database volume.
- Automated domain, importer, persistence, authentication, and HTTP tests.

### Security

- Salted scrypt password hashes, opaque server-side sessions, CSRF protection,
  persistent login throttling, host validation, HTML escaping, and security headers.
- No public registration or SQL uploads; administrative operations require console
  access. All provisioned users share one household ledger.
- Private configuration and household data excluded from Git and Docker builds.

### Changed

- Describe every public Makefile command in Spanish with an icon in `make help`,
  including parameters and shared-database restore precautions. Each command is
  written explicitly in the help recipe, without AWK or comment parsing.

- Share `data/homeio.sqlite3` between local commands and Docker using a bind mount
  and the host user/group IDs, preserving private SQLite file permissions.
  Environment setup creates the host directory before Docker starts.

- Renamed Spendio to Homeio across the Python package, UI, environment variables,
  session cookie, scripts, Makefile, Docker configuration, and documentation.
  Existing installations must update environment keys and migrate Docker data
  as described in the README; SQLite schemas remain unchanged.

- Moved all Docker configuration and the entrypoint to the repository root;
  replaced the `.dockerignore` symlink with a regular file and updated Compose
  paths, Makefile commands, transfer scripts, documentation, and agent guidelines.
  The local project identity and shared data directory remain unchanged.
