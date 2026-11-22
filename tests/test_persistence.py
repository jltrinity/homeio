import sqlite3
import tempfile
import unittest
from pathlib import Path
from homeio.adapters.sqlite import SQLiteLedger, connect, initialize
from homeio.adapters.legacy_import import import_dump, read_dump
from homeio.application.accounting import Accounting
from homeio.domain.accounting import Movement, ValidationError

DUMP = r"""
-- Export fixture
CREATE TABLE `ignored` (`id` int);
INSERT INTO `category` VALUES (7,'Food',0,NULL,NULL,1),(8,'Salary',1,NULL,NULL,1);
INSERT INTO `movement` VALUES
(50,'Shop; O\'Brien','2026-11-01',12.34,NULL,NULL,0,1,9,7),
(51,'Salary','2026-11-02',2000,NULL,NULL,1,1,NULL,8),
(52,'Archived','2026-10-01',30,NULL,NULL,0,0,NULL,7),
(53,'Zero','2026-11-03',0,NULL,NULL,0,1,NULL,NULL);
INSERT INTO `site` VALUES (9,'Corner shop',0,NULL,NULL,1);
INSERT INTO `doctrine_migration_versions` VALUES ('ignored',NULL,0);
"""


class DatabaseCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "test.sqlite3"
        initialize(self.path)
        self.ledger = SQLiteLedger(self.path)

    def dump(self, content=DUMP):
        path = Path(self.temp.name) / "dump.sql"
        path.write_text(content)
        return path


class ImportTests(DatabaseCase):
    def test_import_preserves_relations_dates_ids_and_amounts(self):
        result = import_dump(self.path, self.dump())
        self.assertEqual(result["movement"], 4)
        self.assertEqual(self.ledger.movement(50)["amount_cents"], 1234)
        self.assertEqual(self.ledger.movement(50)["description"], "Shop; O'Brien")
        self.assertEqual(self.ledger.movement(50)["site_id"], 9)
        self.assertEqual(self.ledger.movement(53)["amount_cents"], 0)
        self.assertIsNone(self.ledger.movement(52))
        self.assertEqual(self.ledger.dashboard("2026-11")["balance"], 198766)

    def test_dry_run_has_no_side_effects(self):
        import_dump(self.path, self.dump(), dry_run=True)
        with connect(self.path) as db:
            for table in ("movement", "category", "site", "import_history"):
                self.assertEqual(db.execute(f"SELECT count(*) FROM {table}").fetchone()[0], 0)

    def test_import_is_atomic_when_foreign_key_is_missing(self):
        with self.assertRaises(sqlite3.IntegrityError):
            import_dump(self.path, self.dump(DUMP.replace("1,9,7)", "1,999,7)")))
        self.assertEqual(self.ledger.catalogs("category"), [])

    def test_refuse_duplicate_import(self):
        path = self.dump()
        import_dump(self.path, path)
        with self.assertRaises(ValidationError):
            import_dump(self.path, path)

    def test_refuse_nonempty_ledger(self):
        self.ledger.save_catalog("category", "Existing", 0)
        with self.assertRaises(ValidationError):
            import_dump(self.path, self.dump())
        self.assertEqual(len(self.ledger.catalogs("category")), 1)

    def test_never_execute_sql_in_dump(self):
        path = self.dump(DUMP + "\nDROP TABLE app_user; DELETE FROM movement;")
        import_dump(self.path, path)
        with connect(self.path) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM movement").fetchone()[0], 4)
            self.assertEqual(db.execute("SELECT count(*) FROM app_user").fetchone()[0], 0)

    def test_reject_expression_in_values(self):
        path = self.dump(DUMP.replace("12.34", "load_extension(1)"))
        with self.assertRaises(ValidationError):
            read_dump(path)

    def test_quote_escapes_and_comments(self):
        path = self.dump(
            "/* comment */ INSERT INTO `category` VALUES (1,'O''Brien -- \\n;',0,NULL,NULL,1);"
        )
        data = read_dump(path)
        self.assertEqual(data["category"][0]["name"], "O'Brien -- \n;")

    def test_round_legacy_float_artifacts_and_report(self):
        result = import_dump(self.path, self.dump(DUMP.replace("12.34", "12.34000000001")))
        self.assertEqual(result["rounded_amounts"], 1)
        self.assertEqual(self.ledger.movement(50)["amount_cents"], 1234)

    def test_reject_bad_date_without_partial_import(self):
        with self.assertRaises(ValidationError):
            import_dump(self.path, self.dump(DUMP.replace("2026-11-01", "invalid")))
        self.assertEqual(self.ledger.catalogs("category"), [])


class LedgerTests(DatabaseCase):
    def test_movement_type_filter_keeps_counts_and_pagination_consistent(self):
        for index in range(31):
            self.ledger.save_movement(Movement(f"Match expense {index}", "2026-11-01", 100, 0))
        self.ledger.save_movement(Movement("Match income", "2026-11-01", 200, 1))
        archived = self.ledger.save_movement(Movement("Match archived", "2026-11-01", 100, 0))
        self.ledger.archive_movement(archived)
        self.ledger.save_movement(Movement("Match other month", "2026-10-01", 100, 0))
        self.ledger.save_movement(Movement("Unrelated", "2026-11-01", 100, 0))
        rows, count = self.ledger.movements("2026-11", "Match", movement_type=0)
        self.assertEqual((len(rows), count), (30, 31))
        self.assertTrue(all(row["movement_type"] == 0 for row in rows))
        rows, count = self.ledger.movements("2026-11", "Match", 2, movement_type=0)
        self.assertEqual((len(rows), count), (1, 31))
        rows, count = self.ledger.movements("2026-11", "Match", movement_type=1)
        self.assertEqual((len(rows), count), (1, 1))
        self.assertEqual(rows[0]["description"], "Match income")
        self.assertEqual(self.ledger.movements("2026-11", "Match")[1], 32)
        self.assertEqual(self.ledger.movements("2026-12", movement_type=1), ([], 0))
        with self.assertRaises(ValueError):
            self.ledger.movements("2026-11", movement_type=2)

    def test_create_edit_and_archive(self):
        service = Accounting(self.ledger)
        item = Movement("Groceries", "2026-11-01", 1234, 0)
        item_id = service.record(item)
        service.record(Movement("Updated", "2026-11-02", 5678, 0), item_id)
        self.assertEqual(self.ledger.dashboard("2026-11")["expense"], 5678)
        service.archive(item_id)
        self.assertEqual(self.ledger.dashboard("2026-11")["expense"], 0)
        with connect(self.path) as db:
            self.assertEqual(db.execute("SELECT active FROM movement").fetchone()[0], 0)

    def test_invalid_references_and_type_mismatch(self):
        self.ledger.save_catalog("category", "Salary", 1)
        for category in (1, 999):
            with self.assertRaises(ValidationError):
                self.ledger.save_movement(Movement("Expense", "2026-11-01", 100, 0, category))

    def test_catalog_type_cannot_change_when_referenced(self):
        self.ledger.save_catalog("category", "Food", 0)
        self.ledger.save_movement(Movement("Groceries", "2026-11-01", 100, 0, 1))
        with self.assertRaises(ValidationError):
            self.ledger.save_catalog("category", "Food", 1, 1)
        self.ledger.save_catalog("category", "Food", 0, 1, 0)
        self.assertEqual(self.ledger.catalogs("category", active_only=True), [])

    def test_sql_injection_is_plain_data(self):
        self.ledger.save_movement(Movement("'; DROP TABLE movement; --", "2026-11-01", 100, 0))
        rows, total = self.ledger.movements("2026-11", "'; DROP TABLE movement; --")
        self.assertEqual(total, 1)
        self.assertEqual(rows[0]["amount_cents"], 100)

    def test_edit_preserves_inactive_historical_reference(self):
        self.ledger.save_catalog("site", "Old shop", 0)
        item_id = self.ledger.save_movement(Movement("Before", "2026-11-01", 100, 0, site_id=1))
        self.ledger.save_catalog("site", "Old shop", 0, 1, 0)
        self.ledger.save_movement(Movement("After", "2026-11-01", 200, 0, site_id=1), item_id)
        self.assertEqual(self.ledger.movement(item_id)["site_id"], 1)
        with self.assertRaises(ValidationError):
            self.ledger.save_movement(Movement("New", "2026-11-01", 100, 0, site_id=1))
