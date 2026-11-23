"""Environment configuration shared by the CLI and web adapter."""

import os
from dataclasses import dataclass
from pathlib import Path
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Settings:
    database: Path
    secret: str
    allowed_hosts: tuple[str, ...] = ("localhost", "127.0.0.1")
    cookie_secure: bool = False
    https: bool = False
    session_hours: int = 8
    version: str = "dev"
    backup: Path = ROOT / "data/backups"

    @classmethod
    def load(cls) -> "Settings":
        load_dotenv(ROOT / ".env")
        secret = os.getenv("HOMEIO_SECRET_KEY", "")
        if len(secret) < 32 or secret.startswith("replace-"):
            raise ValueError("Run make env first and configure HOMEIO_SECRET_KEY.")
        path = Path(os.getenv("HOMEIO_DATABASE", "data/homeio.sqlite3"))
        backup = Path(os.getenv("HOMEIO_BACKUP", "data/backups"))
        https = os.getenv("HOMEIO_HTTPS", "false").lower() == "true"
        secure = os.getenv("HOMEIO_COOKIE_SECURE", "false").lower() == "true"
        if https and not secure:
            raise ValueError("HTTPS requires HOMEIO_COOKIE_SECURE=true.")
        hours = int(os.getenv("HOMEIO_SESSION_HOURS", "8"))
        if not 1 <= hours <= 24:
            raise ValueError("Session lifetime must be between 1 and 24 hours.")
        hosts = tuple(
            h.strip()
            for h in os.getenv("HOMEIO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")
            if h.strip()
        )
        if not hosts or "*" in hosts:
            raise ValueError("Explicit allowed hosts are required.")
        version = os.getenv("HOMEIO_VERSION", "dev").strip() or "dev"
        return cls(
            path if path.is_absolute() else ROOT / path,
            secret,
            hosts,
            secure,
            https,
            hours,
            version,
            backup if backup.is_absolute() else ROOT / backup,
        )
