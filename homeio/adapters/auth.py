"""Password hashing, opaque server-side sessions, and persistent login throttling."""

import hashlib
import hmac
import re
import secrets
import time
from pathlib import Path
from homeio.adapters.sqlite import connect
from homeio.domain.accounting import ValidationError


def password_hash(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=16384, r=8, p=1, dklen=32)
    return f"scrypt${salt.hex()}${digest.hex()}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, salt, expected = encoded.split("$")
        if algorithm != "scrypt" or len(password) > 1024:
            return False
        digest = hashlib.scrypt(
            password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1, dklen=32
        )
        return hmac.compare_digest(digest.hex(), expected)
    except (ValueError, TypeError):
        return False


class Authentication:
    def __init__(self, database: Path, secret: str, session_hours: int = 8):
        self.database = database
        self.secret = secret.encode()
        self.lifetime = session_hours * 3600
        self.dummy_hash = password_hash(secrets.token_urlsafe(24))

    def create_user(self, username: str, password: str, *, reset: bool = False) -> None:
        username = username.strip().lower()
        if not re.fullmatch(r"[a-z0-9_.@-]{3,80}", username):
            raise ValidationError("Usuario: 3–80 letras, números o caracteres _.@-")
        if not 12 <= len(password) <= 128 or password.lower() == username:
            raise ValidationError("La contraseña debe tener entre 12 y 128 caracteres.")
        encoded = password_hash(password)
        with connect(self.database) as db:
            user = db.execute("SELECT id FROM app_user WHERE username=?", (username,)).fetchone()
            if reset:
                if not user:
                    raise ValidationError("El usuario no existe.")
                db.execute("UPDATE app_user SET password_hash=? WHERE id=?", (encoded, user["id"]))
                db.execute("DELETE FROM session WHERE user_id=?", (user["id"],))
            else:
                if user:
                    raise ValidationError("El usuario ya existe.")
                db.execute(
                    "INSERT INTO app_user (username,password_hash) VALUES (?,?)",
                    (username, encoded),
                )

    def login(self, username: str, password: str, ip: str) -> int | None:
        username = username.strip().lower()
        clock = int(time.time())
        buckets = [(self._bucket("user:" + username), 5), (self._bucket("ip:" + ip), 30)]
        with connect(self.database) as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("DELETE FROM login_attempt WHERE expires_at<=?", (clock,))
            for key, limit in buckets:
                row = db.execute(
                    "SELECT attempts FROM login_attempt WHERE bucket=?", (key,)
                ).fetchone()
                if row and row["attempts"] >= limit:
                    raise ValidationError("Demasiados intentos. Vuelve a intentarlo en 15 minutos.")
            for key, _ in buckets:
                db.execute(
                    """INSERT INTO login_attempt VALUES (?,1,?) ON CONFLICT(bucket)
                    DO UPDATE SET attempts=attempts+1""",
                    (key, clock + 900),
                )
            user = db.execute(
                "SELECT * FROM app_user WHERE username=? AND active=1", (username,)
            ).fetchone()
        valid = verify_password(password, user["password_hash"] if user else self.dummy_hash)
        if user and valid:
            with connect(self.database) as db:
                db.execute("DELETE FROM login_attempt WHERE bucket=?", (buckets[0][0],))
            return user["id"]
        return None

    def _bucket(self, value: str) -> str:
        return hmac.new(self.secret, value.encode(), hashlib.sha256).hexdigest()

    @staticmethod
    def digest(token: str) -> str:
        return hashlib.sha256(token.encode()).hexdigest()

    def session(self, token: str) -> dict | None:
        if not re.fullmatch(r"[A-Za-z0-9_-]{43}", token):
            return None
        with connect(self.database) as db:
            row = db.execute(
                """SELECT s.*,u.username,u.active FROM session s
                LEFT JOIN app_user u ON s.user_id=u.id WHERE token_hash=? AND expires_at>?""",
                (self.digest(token), int(time.time())),
            ).fetchone()
        if not row or (row["user_id"] and not row["active"]):
            return None
        return dict(row)

    def start_session(self, user_id: int | None = None, old_token: str = "") -> tuple[str, dict]:
        token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        clock = int(time.time())
        expires = clock + (self.lifetime if user_id else 900)
        with connect(self.database) as db:
            db.execute(
                "DELETE FROM session WHERE expires_at<=? OR token_hash=?",
                (clock, self.digest(old_token)),
            )
            db.execute(
                "INSERT INTO session VALUES (?,?,?,?)", (self.digest(token), user_id, csrf, expires)
            )
        return token, self.session(token)

    def logout(self, token: str) -> None:
        with connect(self.database) as db:
            db.execute("DELETE FROM session WHERE token_hash=?", (self.digest(token),))
