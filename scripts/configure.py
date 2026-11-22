"""Generate a private local environment file without replacing existing settings."""

import os
from pathlib import Path
import secrets

root = Path(__file__).resolve().parent.parent
path = root / ".env"
if path.exists():
    print(".env already exists; preserved.")
else:
    contents = (
        (root / ".env.example")
        .read_text()
        .replace("replace-with-a-random-secret-at-least-32-characters", secrets.token_urlsafe(48))
        .replace("HOMEIO_UID=1000", f"HOMEIO_UID={os.getuid()}")
        .replace("HOMEIO_GID=1000", f"HOMEIO_GID={os.getgid()}")
    )
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w") as output:
        output.write(contents)
    print(".env created with a random secret.")

# Bind mounts must exist before Docker starts, owned by the local user.
(root / "data").mkdir(mode=0o700, exist_ok=True)
with path.open("a") as output:
    existing_keys = {line.split("=", 1)[0] for line in path.read_text().splitlines()}
    for key, value in (("HOMEIO_UID", os.getuid()), ("HOMEIO_GID", os.getgid())):
        if key not in existing_keys:
            output.write(f"\n{key}={value}\n")
