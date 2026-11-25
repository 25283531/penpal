"""Error-code tests — run with: python -m pytest tests/ -q

Every error response keeps its existing ``detail`` value and HTTP
status code, and gains a stable top-level ``code`` field that the
Android app maps to localised text (see app/errors.py). These tests
pin both halves: the old detail text and the new code.
"""
import os
import tempfile

os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="penpal-test-errcodes-")
os.environ["JWT_SECRET"] = "test-secret"

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app import database  # noqa: E402
from app.errors import code_for_exception  # noqa: E402
from fastapi import HTTPException  # noqa: E402

database.init_db()  # TestClient without a context manager skips lifespan
client = TestClient(app)


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _new_device(device_id: str, age: int = 30) -> str:
    r = client.post("/api/v1/auth/device", json={"device_id": device_id, "age": age})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def _registered(email: str) -> tuple[str, str]:
    """Register an email account (unverified) and return (token, device_id).

    Sending letters needs a registered account — anonymous devices are
    read-only (403 anonymous_letter_forbidden) — so every test that
    sends a letter uses this helper instead of _new_device.
    """
    from app import email_auth

    token, code, _png = email_auth.create_captcha()
    r = client.post("/api/v1/auth/register", json={
        "email": email, "password": "password123", "age": 30,
        # Registration requires a birth date (18+ gate).
        "birth_date": "1996-06-15",
        "display_name": "阿辉",
        "captcha_token": token, "captcha_text": code,
    })
    assert r.status_code == 200, r.text
    body = r.json()
    return body["token"], body["device_id"]


def _send(token: str, character_id: str, text: str = "你好，我是新来的笔友。"):
    return client.post(
        "/api/v1/letters",
        json={"character_id": character_id, "text": text},
        headers=_auth(token),
    )


# ---------- letters: the two live-verified scenarios ----------

def test_duplicate_letter_409_has_code_unanswered_letter():
    tok, _device_id = _registered("errcodes-dup@example.com")
    r = _send(tok, "P01", "你好，林澈。")
    assert r.status_code == 201, r.text
    r = _send(tok, "P01", "再写一封。")
    assert r.status_code == 409, r.text
    body = r.json()
    assert body["code"] == "unanswered_letter"
    assert body["detail"] == (
        "this character has an unanswered letter; wait for the reply before writing again"
    )


def test_daily_cap_429_has_code_daily_send_limit():
    tok, _device_id = _registered("errcodes-cap@example.com")
    r = _send(tok, "P01", "你好，林澈。")
    assert r.status_code == 201, r.text
    r = _send(tok, "P02", "你好，沈知遥。")
    assert r.status_code == 429, r.text
    body = r.json()
    assert body["code"] == "daily_send_limit"
    assert "daily send limit reached" in body["detail"]


def test_active_character_limit_409_has_code():
    # Free tier: 1 active slot. Occupy it via the DB (no letter sent,
    # so the daily cap does not fire first), then a send to a second
    # character must hit the slot rule with its own code.
    tok, device_id = _registered("errcodes-slot@example.com")
    database.start_relationship(device_id, "P01", max_active=1)
    r = _send(tok, "P02", "你好，沈知遥。")
    assert r.status_code == 409, r.text
    body = r.json()
    assert body["code"] == "active_character_limit"
    assert body["detail"] == (
        "active character limit reached (1); end a relationship or upgrade first"
    )


def test_letter_validation_codes():
    tok, _device_id = _registered("errcodes-letter@example.com")
    r = _send(tok, "P01", "   ")
    assert r.status_code == 400, r.text
    assert r.json()["code"] == "letter_empty"
    assert r.json()["detail"] == "letter is empty"
    r = _send(tok, "P01", "字" * 2001)
    assert r.status_code == 400, r.text
    assert r.json()["code"] == "letter_too_long"
    assert "must be at most 2000" in r.json()["detail"]


def test_not_found_codes():
    tok = _new_device("err-nf-001")
    r = client.get("/api/v1/characters/P99", headers=_auth(tok))
    assert r.status_code == 404 and r.json()["code"] == "character_not_found"
    assert r.json()["detail"] == "character not found"
    r = client.get("/api/v1/letters/999999", headers=_auth(tok))
    assert r.status_code == 404 and r.json()["code"] == "letter_not_found"
    r = client.get("/static/photos/P99/avatar.jpg")
    assert r.status_code == 404 and r.json()["code"] == "photo_not_found"


# ---------- auth ----------

def test_auth_codes():
    r = client.get("/api/v1/characters")
    assert r.status_code == 401, r.text
    assert r.json()["code"] == "missing_token"
    assert r.json()["detail"] == "missing bearer token"
    r = client.get("/api/v1/characters", headers=_auth("bogus.token.here"))
    assert r.status_code == 401, r.text
    assert r.json()["code"] == "invalid_token"
    # Anonymous device auth has no age gate: no age at all, or an
    # under-14 age, both succeed with 200 and no age error code.
    r = client.post("/api/v1/auth/device", json={"device_id": "err-age-001"})
    assert r.status_code == 200, r.text
    assert r.json()["age"] is None
    r = client.post("/api/v1/auth/device", json={"device_id": "err-age-002", "age": 13})
    assert r.status_code == 200, r.text
    assert r.json()["minor_mode"] is True


def test_email_auth_codes():
    r = client.post("/api/v1/auth/login-email",
                    json={"email": "errcodes-nobody@example.com", "password": "wrongpass"})
    assert r.status_code == 401, r.text
    assert r.json()["code"] == "invalid_credentials"
    assert r.json()["detail"] == "邮箱或密码错误"
    r = client.post("/api/v1/auth/register",
                    json={"email": "errcodes-not-an-email", "password": "longenoughpassword",
                          "display_name": "阿辉"})
    assert r.status_code == 400 and r.json()["code"] == "invalid_email"
    r = client.post("/api/v1/auth/register",
                    json={"email": "errcodes-a@example.com", "password": "short",
                          "display_name": "阿辉"})
    assert r.status_code == 400 and r.json()["code"] == "password_too_short"
    # Wrong verification code: deterministic regardless of test order.
    r = client.post("/api/v1/auth/verify",
                    json={"email": "errcodes-a@example.com", "code": "000000"})
    assert r.status_code == 400, r.text
    assert r.json()["code"] == "verification_code_invalid"
    assert r.json()["detail"] == "验证码错误或已过期"
    # No SMTP configured in tests: the shared send-code flow raises
    # ApiError(503, "email_not_configured", ...). Called directly with
    # a fresh email + fresh IP so the captcha gate (which counts prior
    # failed sends per email/IP across the whole suite) cannot fire.
    from app.main import _request_code  # noqa: E402
    from app.errors import ApiError  # noqa: E402
    import pytest  # noqa: E402
    with pytest.raises(ApiError) as excinfo:
        _request_code("errcodes-fresh@example.com", "verify", "10.9.9.9", None, None)
    assert excinfo.value.status_code == 503
    assert excinfo.value.code == "email_not_configured"
    assert excinfo.value.detail == "email not configured"
    assert code_for_exception(excinfo.value) == "email_not_configured"


def test_validation_error_422_has_code():
    # LetterIn.text has min_length=1: an empty string is a 422, and
    # its detail list is unchanged, only `code` is added.
    tok = _new_device("err-422-001")
    r = client.post("/api/v1/letters",
                    json={"character_id": "P01", "text": ""},
                    headers=_auth(tok))
    assert r.status_code == 422, r.text
    assert r.json()["code"] == "validation_error"
    assert isinstance(r.json()["detail"], list)


# ---------- LLM / reply generation ----------

def test_process_due_no_llm_carries_code():
    tok, _device_id = _registered("errcodes-llm@example.com")
    r = _send(tok, "P01", "你好，这是我的第一封信。")
    assert r.status_code == 201, r.text
    r = client.post("/api/v1/letters/process-due", json={}, headers=_auth(tok))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["llm_unavailable"] is True
    assert body["details"][0]["status"] == "queued_no_llm"
    assert body["details"][0]["code"] == "llm_not_configured"


# ---------- inference safety net (unreachable-via-API codes) ----------

def test_code_inference_covers_plain_http_exceptions():
    # character_locked is not reachable through the API today (P01-P05
    # are all unlocked by default), but the code must resolve if the
    # detail ever surfaces from an unconverted raise site.
    assert code_for_exception(
        HTTPException(status_code=403, detail="character is locked; unlock it first")
    ) == "character_locked"
    assert code_for_exception(
        HTTPException(status_code=409, detail="active character limit reached (1); end a relationship or upgrade first")
    ) == "active_character_limit"
    assert code_for_exception(
        HTTPException(status_code=400, detail="something entirely new")
    ) == "bad_request"
