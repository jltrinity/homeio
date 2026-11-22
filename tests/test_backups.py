from contextlib import closing
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest

from homeio.adapters.backups import export_database, restore_database
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

    def test_foreign_key_violation_is_rejected(self):
        export_database(self.database, self.export)
        with closing(sqlite3.connect(self.export)) as db:
            db.execute(
                "INSERT INTO movement (description,valid_date,amount_cents,movement_type,category_id) VALUES ('Bad','2026-11-01',100,0,999)"
            )
            db.commit()
        with self.assertRaises(ValueError):
            restore_database(self.database, self.export)
