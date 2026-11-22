"""SQLite adapter. Each unit of work owns a short-lived connection."""

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from homeio.domain.accounting import Movement, ValidationError


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@contextmanager
def connect(path: Path):
    db = sqlite3.connect(path, timeout=15)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    try:
        with db:
            yield db
    finally:
        db.close()


def initialize(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with connect(path) as db:
        db.execute("PRAGMA journal_mode=WAL")
        db.executescript(Path(__file__).with_name("schema.sql").read_text())
    path.chmod(0o600)


class SQLiteLedger:
    def __init__(self, path: Path):
        self.path = path

    def save_movement(self, movement: Movement, movement_id: int | None = None) -> int:
        with connect(self.path) as db:
            existing = (
                db.execute(
                    "SELECT * FROM movement WHERE id=? AND active=1", (movement_id,)
                ).fetchone()
                if movement_id
                else None
            )
            for table, value in (("category", movement.category_id), ("site", movement.site_id)):
                if value is not None:
                    ref = db.execute(f"SELECT * FROM {table} WHERE id=?", (value,)).fetchone()
                    retained = existing and existing[table + "_id"] == value
                    if (
                        not ref
                        or (not ref["active"] and not retained)
                        or ref["movement_type"] != movement.movement_type
                    ):
                        raise ValidationError(
                            "La categoría o el establecimiento no corresponde al tipo."
                        )
            values = (
                movement.description.strip(),
                movement.valid_date,
                movement.amount_cents,
                movement.movement_type,
                movement.category_id,
                movement.site_id,
                now(),
            )
            if movement_id is None:
                result = db.execute(
                    """INSERT INTO movement
                    (description,valid_date,amount_cents,movement_type,category_id,site_id,date_created)
                    VALUES (?,?,?,?,?,?,?)""",
                    values,
                )
                return result.lastrowid
            result = db.execute(
                """UPDATE movement SET description=?,valid_date=?,amount_cents=?,
                movement_type=?,category_id=?,site_id=?,date_updated=? WHERE id=? AND active=1""",
                values + (movement_id,),
            )
            if not result.rowcount:
                raise ValidationError("El movimiento no existe o está archivado.")
            return movement_id

    def archive_movement(self, movement_id: int) -> None:
        with connect(self.path) as db:
            result = db.execute(
                "UPDATE movement SET active=0,date_updated=? WHERE id=? AND active=1",
                (now(), movement_id),
            )
            if not result.rowcount:
                raise ValidationError("El movimiento no existe o está archivado.")

    def catalogs(self, table: str, *, active_only: bool = False) -> list[dict]:
        if table not in ("category", "site"):
            raise ValueError("Unknown catalog")
        with connect(self.path) as db:
            where = " WHERE active=1" if active_only else ""
            return [dict(row) for row in db.execute(f"SELECT * FROM {table}{where} ORDER BY name")]

    def save_catalog(
        self, table: str, name: str, kind: int, item_id: int | None = None, active: int = 1
    ) -> None:
        if table not in ("category", "site"):
            raise ValueError("Unknown catalog")
        if not name.strip() or len(name) > 255 or kind not in (0, 1) or active not in (0, 1):
            raise ValidationError("Revisa el nombre, tipo y estado.")
        with connect(self.path) as db:
            if item_id:
                column = "category_id" if table == "category" else "site_id"
                old = db.execute(f"SELECT * FROM {table} WHERE id=?", (item_id,)).fetchone()
                if not old:
                    raise ValidationError("El elemento no existe.")
                if (
                    old["movement_type"] != kind
                    and db.execute(
                        f"SELECT 1 FROM movement WHERE {column}=? LIMIT 1", (item_id,)
                    ).fetchone()
                ):
                    raise ValidationError(
                        "No puedes cambiar el tipo de un elemento con movimientos."
                    )
                db.execute(
                    f"UPDATE {table} SET name=?,movement_type=?,active=?,date_updated=? WHERE id=?",
                    (name.strip(), kind, active, now(), item_id),
                )
            else:
                db.execute(
                    f"INSERT INTO {table} (name,movement_type,date_created) VALUES (?,?,?)",
                    (name.strip(), kind, now()),
                )

    def movement(self, item_id: int) -> dict | None:
        with connect(self.path) as db:
            row = db.execute(
                "SELECT * FROM movement WHERE id=? AND active=1", (item_id,)
            ).fetchone()
            return dict(row) if row else None

    def movements(
        self, month: str, query: str = "", page: int = 1, *, movement_type: int | None = None
    ) -> tuple[list[dict], int]:
        params: tuple[str | int, ...] = (month + "%", "%" + query + "%")
        where = " WHERE m.active=1 AND m.valid_date LIKE ? AND m.description LIKE ?"
        if movement_type is not None:
            if movement_type not in (0, 1):
                raise ValueError("Invalid movement type")
            where += " AND m.movement_type=?"
            params += (movement_type,)
        with connect(self.path) as db:
            count = db.execute("SELECT count(*) FROM movement m" + where, params).fetchone()[0]
            rows = db.execute(
                """SELECT m.*,c.name category_name,s.name site_name FROM movement m
                LEFT JOIN category c ON m.category_id=c.id LEFT JOIN site s ON m.site_id=s.id"""
                + where
                + " ORDER BY m.valid_date DESC,m.id DESC LIMIT 30 OFFSET ?",
                params + ((page - 1) * 30,),
            )
            return [dict(row) for row in rows], count

    def dashboard(self, month: str) -> dict:
        with connect(self.path) as db:
            totals = {
                row["movement_type"]: row["amount"]
                for row in db.execute(
                    """
                SELECT movement_type,sum(amount_cents) amount FROM movement
                WHERE active=1 AND valid_date LIKE ? GROUP BY movement_type""",
                    (month + "%",),
                )
            }
            monthly = [
                dict(row)
                for row in db.execute(
                    """SELECT substr(valid_date,1,7) month,
                sum(CASE WHEN movement_type=1 THEN amount_cents ELSE 0 END) income,
                sum(CASE WHEN movement_type=0 THEN amount_cents ELSE 0 END) expense
                FROM movement WHERE active=1 AND valid_date LIKE ? GROUP BY month ORDER BY month""",
                    (month[:4] + "%",),
                )
            ]
            categories = [
                dict(row)
                for row in db.execute(
                    """
                SELECT coalesce(c.name,'Sin categoría') name,sum(m.amount_cents) amount
                FROM movement m LEFT JOIN category c ON c.id=m.category_id
                WHERE m.active=1 AND m.movement_type=0 AND m.valid_date LIKE ?
                GROUP BY m.category_id ORDER BY amount DESC""",
                    (month + "%",),
                )
            ]
        return {
            "income": totals.get(1, 0),
            "expense": totals.get(0, 0),
            "balance": totals.get(1, 0) - totals.get(0, 0),
            "monthly": monthly,
            "categories": categories,
        }
