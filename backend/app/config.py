"""Configuration — env vars only for NON-SECRET server settings.

All API keys and admin-editable config live in the SQLite `settings`
table and are edited in the web admin console (/admin). Nothing secret
is read from env — except JWT_SECRET, which is kept only as a legacy
override (new installs auto-generate the signing secret into the
settings table; see database.get_or_create_jwt_secret).

Penpal is an independent service: port 7000, its own SQLite file
(`penpal.db`) and its own Fernet key. It shares nothing at runtime
with the future-me service on port 6999.
"""
import os
from pathlib import Path


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


class Settings:
    HOST: str = _env("HOST", "0.0.0.0")
    PORT: int = int(_env("PORT", "7000"))
    DATA_DIR: Path = Path(_env("DATA_DIR", str(Path(__file__).resolve().parent.parent / "data")))
    DB_PATH: Path = DATA_DIR / "penpal.db"


settings = Settings()
