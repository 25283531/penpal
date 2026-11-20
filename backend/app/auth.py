"""Anonymous device auth.

Token format: base64url(device_id) + "." + random_hex + "." + hmac_sha256(secret, device_id + "." + random_hex)
No password, no personal data. The token is verified by recomputing the HMAC
and checking the device exists in the DB.

The signing secret lives in the settings table (auto-generated on first
boot); a JWT_SECRET env var, when set, overrides it for backwards
compatibility with existing deployments.
"""
import base64
import hashlib
import hmac
import secrets

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from . import database

_bearer = HTTPBearer(auto_error=False)


def _secret() -> str:
    return database.get_or_create_jwt_secret()


def _b64e(s: str) -> str:
    return base64.urlsafe_b64encode(s.encode()).decode().rstrip("=")


def _b64d(s: str) -> str:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4)).decode()


def issue_token(device_id: str) -> str:
    nonce = secrets.token_hex(16)
    payload = f"{device_id}.{nonce}"
    sig = hmac.new(
        _secret().encode(), payload.encode(), hashlib.sha256
    ).hexdigest()
    return f"{_b64e(device_id)}.{nonce}.{sig}"


def verify_token(token: str) -> str:
    """Return the device_id if the token is valid, else raise 401."""
    try:
        b64_id, nonce, sig = token.split(".")
        device_id = _b64d(b64_id)
    except (ValueError, Exception):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid token")
    payload = f"{device_id}.{nonce}"
    expected = hmac.new(
        _secret().encode(), payload.encode(), hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(expected, sig):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid token")
    if not database.device_exists(device_id):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="unknown device")
    return device_id


def get_current_device(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> str:
    if creds is None or creds.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing bearer token",
        )
    return verify_token(creds.credentials)
