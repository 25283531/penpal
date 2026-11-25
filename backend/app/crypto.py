"""Field-level encryption for user content at rest (Fernet).

Everything a user writes and everything the AI writes back is encrypted
before it reaches SQLite and decrypted only in memory, only for two
purposes: (a) returning content to its own owner's app, (b) assembling
that user's LLM context. The admin APIs never see decrypted content.

Key management:
- The key lives in a standalone file DATA_DIR/.encryption.key (mode 0600),
  separate from the database. It never enters the DB, never appears in
  logs, and never travels over any API.
- First boot generates a fresh random key; later boots load the file.
- If the key file is lost, the encrypted data is PERMANENTLY unrecoverable
  — back the key file up separately from the database.

Only these fields are encrypted: letters.text, memories.text,
persona.summary, devices.emergency_contact. Operational metadata
stays plaintext (category, dates, counts, device_id, violation flags,
memory emotion/recall counts, relationship stage, traits) because the
admin aggregate statistics are computed from it.
"""
import hashlib
import hmac
import os
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

from .config import settings

KEY_FILENAME = ".encryption.key"

_fernet: Fernet | None = None


def key_path() -> Path:
    return settings.DATA_DIR / KEY_FILENAME


def load_or_create_key() -> bytes:
    """Load the key file, or generate + store one (mode 0600) on first boot."""
    path = key_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        key = path.read_bytes().strip()
        if key:
            return key
    key = Fernet.generate_key()
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(fd, key)
    finally:
        os.close(fd)
    os.chmod(path, 0o600)
    return key


def get_fernet() -> Fernet:
    global _fernet
    if _fernet is None:
        _fernet = Fernet(load_or_create_key())
    return _fernet


def encrypt_text(plaintext: str) -> str:
    """Encrypt to a URL-safe base64 token string (stored as TEXT)."""
    return get_fernet().encrypt(plaintext.encode("utf-8")).decode("ascii")


def fingerprint_for_key(key: bytes | str) -> str:
    """SHA256 fingerprint (first 12 hex chars) of one key value.

    Only the fingerprint is ever exposed or compared; the key value
    itself never leaves the caller. Leading/trailing whitespace is
    stripped so a pasted key with a stray newline still matches."""
    raw = key.encode("utf-8") if isinstance(key, str) else key
    return hashlib.sha256(raw.strip()).hexdigest()[:12]


def key_fingerprint() -> str | None:
    """SHA256 fingerprint (first 12 hex chars) of the key file, or None
    when the file does not exist. This deliberately does NOT create the
    key (unlike load_or_create_key) — a status check must never mint a
    new key. Only the fingerprint is ever exposed; the key value itself
    never leaves this module."""
    path = key_path()
    if not path.exists():
        return None
    return fingerprint_for_key(path.read_bytes())


def presented_key_matches(presented: str | None) -> bool:
    """Constant-time check: does the key an admin just presented match
    the stored key file? Compares SHA256 fingerprints with
    hmac.compare_digest — the presented value is never logged and
    never compared byte-for-byte against the stored value."""
    if not presented or not presented.strip():
        return False
    stored = key_fingerprint()
    if stored is None:
        return False
    try:
        return hmac.compare_digest(fingerprint_for_key(presented), stored)
    except (ValueError, TypeError):
        return False


def decrypt_text_with_key(token: str, key: bytes | str) -> str:
    """Decrypt a token with an explicitly supplied key (the one the
    admin presented for this one view), NOT the stored key file.
    Raises InvalidToken for a token this key cannot open, and
    ValueError for a malformed key. Callers must drop the key from
    memory as soon as this returns."""
    raw = key.encode("utf-8") if isinstance(key, str) else key
    return Fernet(raw.strip()).decrypt(token.encode("ascii")).decode("utf-8")


def key_status() -> dict:
    """Key-file status for the /admin status page: whether the file
    exists, its path, and its fingerprint (never the key value)."""
    path = key_path()
    return {
        "exists": path.exists(),
        "path": str(path),
        "fingerprint_sha256_12": key_fingerprint(),
        "backup_reminder": (
            "密钥丢了，信件数据永久无法恢复。请把密钥文件单独备份，"
            "不要和数据库放在同一处。"
        ),
    }


def decrypt_text(token: str) -> str:
    """Decrypt a token. Raises InvalidToken for anything that is not a
    valid token produced by this key."""
    return get_fernet().decrypt(token.encode("ascii")).decode("utf-8")


def is_encrypted(value: str) -> bool:
    """True if `value` decrypts cleanly with the current key. Used by the
    startup migration to tell already-encrypted rows from legacy plaintext."""
    if not value:
        return False
    try:
        decrypt_text(value)
        return True
    except (InvalidToken, ValueError):
        return False


def decrypt_or_keep(value: str) -> str:
    """Decrypt when possible; return legacy plaintext unchanged otherwise.
    Read paths use this so rows missed by the migration still work."""
    if not value:
        return value
    try:
        return decrypt_text(value)
    except (InvalidToken, ValueError):
        return value
