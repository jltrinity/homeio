from contextlib import closing
from pathlib import Path
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest

from homeio.adapters.backups import export_database, export_sql, restore_database, validate
from homeio.adapters.sqlite import connect, initialize


class BackupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.database = self.root / "live.sqlite3"
        self.export = self.root / "import" / "snapshot.sqlite3"
        initialize(self.database)
        with connect(self.database) as db:
            db.execute("INSERT INTO category (id,name,movement_type) VALUES (1,'Food',0)")
            db.execute("INSERT INTO app_user VALUES (1,'alice','test-hash',1)")
            db.execute("INSERT INTO session VALUES ('token',1,'csrf',9999999999)")

    def test_sql_export_round_trip_preserves_schema_and_data(self):
        description = "Compra de café 'especial'\nsegunda línea; --"
        with connect(self.database) as db:
            db.execute(
                "INSERT INTO movement (description, valid_date, amount_cents, movement_type, "
                "category_id) VALUES (?, '2026-11-23', 123456789, 0, 1)",
                (description,),
            )
        destination = self.root / "exports" / "dump.sql"
        export_sql(self.database, destination)
        sql = destination.read_text(encoding="utf-8")
        self.assertIn("CREATE TABLE", sql)
        self.assertIn("INSERT INTO", sql)
        self.assertEqual(destination.stat().st_mode & 0o777, 0o600)
        with closing(sqlite3.connect(":memory:")) as restored:
            # Execute only the dump generated from this test's synthetic fixture.
            restored.executescript(sql)
            validate(restored)
            with closing(sqlite3.connect(self.database)) as original:
                tables = original.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
                for (table,) in tables:
                    with self.subTest(table=table):
                        self.assertEqual(
                            original.execute(f'SELECT * FROM "{table}" ORDER BY rowid').fetchall(),
                            restored.execute(f'SELECT * FROM "{table}" ORDER BY rowid').fetchall(),
                        )

    def test_sql_export_preserves_existing_destination(self):
        destination = self.root / "dump.sql"
        destination.write_text("existing export")
        with self.assertRaises(FileExistsError):
            export_sql(self.database, destination)
        self.assertEqual(destination.read_text(), "existing export")

    def test_sql_export_failure_leaves_no_dump_or_empty_database(self):
        for database in (self.root / "missing.sqlite3", self.root / "invalid.sqlite3"):
            with self.subTest(database=database.name):
                if database.name == "invalid.sqlite3":
                    database.write_bytes(b"invalid database")
                destination = self.root / "exports" / "dump.sql"
                with self.assertRaises(sqlite3.Error):
                    export_sql(database, destination)
                self.assertFalse(destination.exists())
                self.assertEqual(list(destination.parent.iterdir()), [])
        self.assertFalse((self.root / "missing.sqlite3").exists())

    def test_round_trip_preserves_users_and_saves_current_data(self):
        export_database(self.database, self.export)
        with connect(self.database) as db:
            db.execute("UPDATE category SET name='Changed'")
        backup = restore_database(self.database, self.export)
        with connect(self.database) as db:
            self.assertEqual(db.execute("SELECT name FROM category").fetchone()[0], "Food")
            self.assertEqual(db.execute("SELECT username FROM app_user").fetchone()[0], "alice")
            self.assertEqual(db.execute("SELECT count(*) FROM session").fetchone()[0], 0)
        with connect(backup) as db:
            self.assertEqual(db.execute("SELECT name FROM category").fetchone()[0], "Changed")
        self.assertEqual(self.export.stat().st_mode & 0o777, 0o600)

    def test_existing_export_is_not_overwritten(self):
        export_database(self.database, self.export)
        contents = self.export.read_bytes()
        with self.assertRaises(FileExistsError):
            export_database(self.database, self.export)
        self.assertEqual(self.export.read_bytes(), contents)

    def test_invalid_database_does_not_change_live_data(self):
        invalid = self.root / "invalid.sqlite3"
        invalid.write_bytes(b"not a sqlite database")
        with self.assertRaises(sqlite3.DatabaseError):
            restore_database(self.database, invalid)
        with connect(self.database) as db:
            self.assertEqual(db.execute("SELECT name FROM category").fetchone()[0], "Food")
        self.assertEqual(list(self.root.glob("*.before-import-*")), [])

    def test_extra_trigger_is_rejected(self):
        export_database(self.database, self.export)
        with closing(sqlite3.connect(self.export)) as db:
            db.execute(
                "CREATE TRIGGER unexpected AFTER DELETE ON session BEGIN DELETE FROM app_user; END"
            )
            db.commit()
        with self.assertRaises(ValueError):
            restore_database(self.database, self.export)

    def test_missing_source_does_not_create_empty_database(self):
        missing = self.root / "missing.sqlite3"
        with self.assertRaises(sqlite3.OperationalError):
            export_database(missing, self.export)
        self.assertFalse(missing.exists())
        self.assertFalse(self.export.exists())

    def test_stream_transport_round_trip_to_new_database(self):
        module = Path("homeio/adapters/backups.py").resolve()
        exported = subprocess.run(
            [sys.executable, str(module), "export", str(self.database)],
            capture_output=True,
            check=True,
        )
        self.assertTrue(exported.stdout.startswith(b"SQLite format 3"))
        target = self.root / "new.sqlite3"
        subprocess.run(
            [sys.executable, str(module), "import", str(target)],
            input=exported.stdout,
            capture_output=True,
            check=True,
        )
        with connect(target) as db:
            self.assertEqual(db.execute("SELECT name FROM category").fetchone()[0], "Food")
            self.assertEqual(db.execute("SELECT count(*) FROM session").fetchone()[0], 0)

    def test_cli_uses_configured_persistent_paths(self):
        backup_directory = self.root / "persistent" / "backups"
        environment = {
            **os.environ,
            "HOMEIO_DATABASE": str(self.database),
            "HOMEIO_BACKUP": str(backup_directory),
            "HOMEIO_SECRET_KEY": "a" * 48,
            "HOMEIO_HTTPS": "false",
            "HOMEIO_ALLOWED_HOSTS": "localhost",
            "HOMEIO_SESSION_HOURS": "8",
        }
        for _ in range(2):
            subprocess.run(
                [sys.executable, "-m", "homeio.cli", "backup"],
                env=environment,
                capture_output=True,
                check=True,
            )
        for _ in range(2):
            subprocess.run(
                [sys.executable, "-m", "homeio.cli", "export-sql"],
                env=environment,
                capture_output=True,
                check=True,
            )
        sql_exports = list(backup_directory.glob("*.sql"))
        self.assertEqual(len(sql_exports), 2)
        self.assertIn("INSERT INTO", sql_exports[0].read_text())
        snapshots = list(backup_directory.glob("*.sqlite3"))
        self.assertEqual(len(snapshots), 2)
        with connect(snapshots[0]) as db:
            self.assertEqual(db.execute("SELECT name FROM category").fetchone()[0], "Food")
        with connect(self.database) as db:
            db.execute("UPDATE category SET name='Changed'")
        subprocess.run(
            [sys.executable, "-m", "homeio.adapters.backups", "import"],
            env=environment,
            input=snapshots[0].read_bytes(),
            capture_output=True,
            check=True,
        )
        safety_copies = list(backup_directory.glob("*.before-import-*.sqlite3"))
        self.assertEqual(len(safety_copies), 1)
        with connect(safety_copies[0]) as db:
            self.assertEqual(db.execute("SELECT name FROM category").fetchone()[0], "Changed")
        with connect(self.database) as db:
            self.assertEqual(db.execute("SELECT name FROM category").fetchone()[0], "Food")

    def test_failed_safety_backup_preserves_live_database(self):
        export_database(self.database, self.export)
        with connect(self.database) as db:
            db.execute("UPDATE category SET name='Changed'")
        blocked_directory = self.root / "not-a-directory"
        blocked_directory.write_text("occupied")
        with self.assertRaises(OSError):
            restore_database(self.database, self.export, blocked_directory)
        with connect(self.database) as db:
            self.assertEqual(db.execute("SELECT name FROM category").fetchone()[0], "Changed")

    def test_foreign_key_violation_is_rejected(self):
        export_database(self.database, self.export)
        with closing(sqlite3.connect(self.export)) as db:
            db.execute(
                "INSERT INTO movement (description,valid_date,amount_cents,movement_type,category_id) VALUES ('Bad','2026-11-01',100,0,999)"
            )
            db.commit()
        with self.assertRaises(ValueError):
            restore_database(self.database, self.export)
