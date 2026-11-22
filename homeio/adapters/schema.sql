PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS schema_version (version INTEGER PRIMARY KEY);
INSERT OR IGNORE INTO schema_version VALUES (1);
CREATE TABLE IF NOT EXISTS category (
 id INTEGER PRIMARY KEY, name TEXT NOT NULL CHECK(length(name) BETWEEN 1 AND 255),
 movement_type INTEGER NOT NULL CHECK(movement_type IN (0,1)),
 date_created TEXT, date_updated TEXT, active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1))
);
CREATE TABLE IF NOT EXISTS site (
 id INTEGER PRIMARY KEY, name TEXT NOT NULL CHECK(length(name) BETWEEN 1 AND 255),
 movement_type INTEGER NOT NULL CHECK(movement_type IN (0,1)),
 date_created TEXT, date_updated TEXT, active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1))
);
CREATE TABLE IF NOT EXISTS movement (
 id INTEGER PRIMARY KEY, description TEXT NOT NULL CHECK(length(description) BETWEEN 1 AND 255),
 valid_date TEXT NOT NULL, amount_cents INTEGER NOT NULL,
 date_created TEXT, date_updated TEXT,
 movement_type INTEGER NOT NULL CHECK(movement_type IN (0,1)),
 active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)),
 site_id INTEGER REFERENCES site(id), category_id INTEGER REFERENCES category(id)
);
CREATE INDEX IF NOT EXISTS movement_date ON movement(active, valid_date);
CREATE TABLE IF NOT EXISTS app_user (
 id INTEGER PRIMARY KEY, username TEXT NOT NULL UNIQUE, password_hash TEXT NOT NULL,
 active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1))
);
CREATE TABLE IF NOT EXISTS session (
 token_hash TEXT PRIMARY KEY, user_id INTEGER REFERENCES app_user(id) ON DELETE CASCADE,
 csrf TEXT NOT NULL, expires_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS session_expiry ON session(expires_at);
CREATE TABLE IF NOT EXISTS login_attempt (
 bucket TEXT PRIMARY KEY, attempts INTEGER NOT NULL, expires_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS import_history (
 digest TEXT PRIMARY KEY, imported_at TEXT NOT NULL, counts TEXT NOT NULL
);
