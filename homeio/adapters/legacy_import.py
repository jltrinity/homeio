"""Read the supported MariaDB dump as data; never execute source SQL."""

import hashlib
import json
import re
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from homeio.adapters.sqlite import connect, now
from homeio.domain.accounting import ValidationError, money_to_cents

COLUMNS = {
    "category": ["id", "name", "movement_type", "date_created", "date_updated", "active"],
    "site": ["id", "name", "movement_type", "date_created", "date_updated", "active"],
    "movement": [
        "id",
        "description",
        "valid_date",
        "amount",
        "date_created",
        "date_updated",
        "movement_type",
        "active",
        "site_id",
        "category_id",
    ],
}


def statements(source: str):
    """Split statements while respecting quoted strings and SQL comments."""
    buffer = []
    index = 0
    quoted = False
    while index < len(source):
        char = source[index]
        if quoted:
            buffer.append(char)
            if char == "\\" and index + 1 < len(source):
                index += 1
                buffer.append(source[index])
            elif char == "'":
                if index + 1 < len(source) and source[index + 1] == "'":
                    index += 1
                    buffer.append("'")
                else:
                    quoted = False
        elif source.startswith("--", index) or char == "#":
            end = source.find("\n", index)
            index = len(source) if end < 0 else end
            buffer.append(" ")
            continue
        elif source.startswith("/*", index):
            end = source.find("*/", index + 2)
            if end < 0:
                raise ValidationError("Comentario SQL sin cerrar.")
            index = end + 2
            buffer.append(" ")
            continue
        elif char == "'":
            quoted = True
            buffer.append(char)
        elif char == ";":
            yield "".join(buffer).strip()
            buffer = []
        else:
            buffer.append(char)
        index += 1
    if quoted:
        raise ValidationError("Cadena SQL sin cerrar.")
    if "".join(buffer).strip():
        raise ValidationError("Sentencia SQL incompleta.")


def value_rows(source: str):
    index = 0
    length = len(source)
    escapes = {"n": "\n", "r": "\r", "t": "\t", "0": "\0", "b": "\b", "Z": "\x1a"}

    def whitespace():
        nonlocal index
        while index < length and source[index].isspace():
            index += 1

    while index < length:
        whitespace()
        if index >= length or source[index] != "(":
            raise ValidationError("Se esperaba una fila SQL.")
        index += 1
        row = []
        while True:
            whitespace()
            if index >= length:
                raise ValidationError("Fila SQL incompleta.")
            if source[index] == "'":
                index += 1
                value = []
                while index < length:
                    char = source[index]
                    index += 1
                    if char == "\\":
                        if index >= length:
                            raise ValidationError("Escape SQL incompleto.")
                        value.append(escapes.get(source[index], source[index]))
                        index += 1
                    elif char == "'":
                        if index < length and source[index] == "'":
                            value.append("'")
                            index += 1
                        else:
                            break
                    else:
                        value.append(char)
                else:
                    raise ValidationError("Cadena SQL incompleta.")
                row.append("".join(value))
            else:
                start = index
                while index < length and source[index] not in ",)":
                    index += 1
                token = source[start:index].strip()
                if token.upper() == "NULL":
                    row.append(None)
                elif re.fullmatch(r"[-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?", token):
                    row.append(token)
                else:
                    raise ValidationError("Valor SQL no permitido.")
            whitespace()
            if index >= length or source[index] not in ",)":
                raise ValidationError("Separador SQL inválido.")
            char = source[index]
            index += 1
            if char == ")":
                break
        yield row
        whitespace()
        if index == length:
            break
        if source[index] != ",":
            raise ValidationError("Separador de filas inválido.")
        index += 1
        whitespace()
        if index == length:
            raise ValidationError("Fila SQL ausente.")


def read_dump(path: Path) -> dict[str, list[dict]]:
    if path.stat().st_size > 50 * 1024 * 1024:
        raise ValidationError("El archivo supera el límite de 50 MiB.")
    data = {table: [] for table in COLUMNS}
    for statement in statements(path.read_text(encoding="utf-8-sig")):
        if not re.match(r"INSERT\b", statement, re.I):
            continue
        match = re.fullmatch(
            r"INSERT INTO `([a-z_]+)`(?:\s*\(([^)]+)\))?\s+VALUES\s+(.*)", statement, re.S | re.I
        )
        if not match:
            raise ValidationError("Formato INSERT no compatible.")
        table, columns, values = match.groups()
        if table == "doctrine_migration_versions":
            continue
        if table not in COLUMNS:
            raise ValidationError("El archivo contiene una tabla no compatible.")
        names = (
            [col.strip().strip("`") for col in columns.split(",")] if columns else COLUMNS[table]
        )
        if len(names) != len(COLUMNS[table]) or set(names) != set(COLUMNS[table]):
            raise ValidationError(f"Columnas inesperadas en {table}.")
        for row in value_rows(values):
            if len(row) != len(names):
                raise ValidationError(f"Número de columnas inválido en {table}.")
            data[table].append(dict(zip(names, row)))
    if not any(data.values()):
        raise ValidationError("No hay datos compatibles en el archivo.")
    return data


def normalize_date(value: str) -> str:
    for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%d/%m/%Y", "%Y/%m/%d", "%d-%m-%Y"):
        try:
            return datetime.strptime(value, fmt).date().isoformat()
        except ValueError:
            pass
    raise ValidationError("Fecha de movimiento no compatible.")


def import_dump(database: Path, source: Path, *, dry_run: bool = False) -> dict:
    data = read_dump(source)
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    counts = {table: len(rows) for table, rows in data.items()}
    rounded = 0
    with connect(database) as db:
        db.execute("BEGIN IMMEDIATE")
        if db.execute("SELECT 1 FROM import_history WHERE digest=?", (digest,)).fetchone():
            raise ValidationError("Este archivo ya se ha importado.")
        if any(db.execute(f"SELECT 1 FROM {table} LIMIT 1").fetchone() for table in COLUMNS):
            raise ValidationError(
                "La importación inicial requiere un libro vacío; no se sobrescriben datos."
            )
        for table in ("category", "site", "movement"):
            for row in data[table]:
                try:
                    if int(row["id"]) <= 0:
                        raise ValueError
                    if table == "movement":
                        row["valid_date"] = normalize_date(row["valid_date"])
                        original = Decimal(row.pop("amount"))
                        # The legacy DOUBLE field may contain binary floating-point artifacts.
                        normalized = original.quantize(Decimal(".01"), rounding=ROUND_HALF_UP)
                        rounded += int(original != normalized)
                        row["amount_cents"] = money_to_cents(str(normalized), allow_negative=True)
                    columns = list(row)
                    db.execute(
                        f"INSERT INTO {table} ({','.join(columns)}) "
                        f"VALUES ({','.join('?' for _ in columns)})",
                        tuple(row[column] for column in columns),
                    )
                except (ValueError, ArithmeticError) as exc:
                    raise ValidationError(
                        f"Datos inválidos en {table}, id {row.get('id', '?')}."
                    ) from exc
        result = dict(counts, rounded_amounts=rounded)
        db.execute("INSERT INTO import_history VALUES (?,?,?)", (digest, now(), json.dumps(result)))
        if dry_run:
            db.rollback()
        return result
