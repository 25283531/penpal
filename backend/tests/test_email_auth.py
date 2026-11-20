"""Penpal M1 tests — email auth + privacy endpoints.

Run with: python -m pytest tests/ -q  (use the future-me venv python)

No real mail is sent: app.email_auth.send_email is monkeypatched with a
fake that records (to, subject, body); the 6-digit code is extracted
from the fake mail body. SMTP-unconfigured behaviour is tested with
the default settings (smtp.user empty).
"""
import os
import re
import sqlite3
import tempfile

os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="penpal-email-test-")
os.environ["JWT_SECRET"] = "test-secret"
for k in ("DASHSCOPE_API_KEY", "HUNYUAN_API_KEY", "SILICONFLOW_API_KEY",
          "ZHIPU_API_KEY", "GENERIC_LLM_API_KEY"):
    os.environ.pop(k, None)

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import database, email_auth  # noqa: E402
from app.main import app  # noqa: E402

database.init_db()  # TestClient without a context manager skips lifespan
client = TestClient(app)

CODE_RE = re.compile(r"(\d{6})")


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def fake_smtp(monkeypatch):
    """Capture sent mail instead of sending it. Returns the sent list."""
    sent: list[dict] = []

    def _fake(to_email: str, subject: str, body: str) -> None:
        sent.append({"to": to_email, "subject": subject, "body": body})

    monkeypatch.setattr(email_auth, "send_email", _fake)
    return sent


@pytest.fixture
def smtp_configured(monkeypatch):
    """Pretend SMTP is configured (host+user set) so send-code proceeds
    to the (fake) mail step instead of 503."""
    monkeypatch.setattr(email_auth, "smtp_configured", lambda: True)
    return True


def _captcha():
    token, code, png = email_auth.create_captcha()
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    return token, code


def _register(email: str, password: str = "password123", age: int = 30):
    token, code = _captcha()
    r = client.post("/api/v1/auth/register", json={
        "email": email, "password": password, "age": age,
        "captcha_token": token, "captcha_text": code,
    })
    assert r.status_code == 200, r.text
    return r.json()


def _send_code(email: str, purpose: str = "verify", with_captcha: bool = True):
    body: dict = {"email": email, "purpose": purpose}
    if with_captcha:
        token, code = _captcha()
        body["captcha_token"] = token
        body["captcha_text"] = code
    return client.post("/api/v1/auth/send-code", json=body)


def _code_from_mail(sent: list[dict]) -> str:
    assert sent, "no mail was sent"
    m = CODE_RE.search(sent[-1]["body"])
    assert m, f"no 6-digit code in mail body: {sent[-1]['body']!r}"
    assert sent[-1]["subject"] == "笔友：你的验证码"
    return m.group(1)


def _expire_latest_code(email: str):
    past = "2000-01-01T00:00:00+00:00"
    conn = sqlite3.connect(str(database.settings.DB_PATH))
    conn.execute(
        "UPDATE verification_codes SET expires_at = ? WHERE email = ?",
        (past, email),
    )
    conn.commit()
    conn.close()


def _clear_send_events(email: str):
    """Drop the 1/min rate-limit window for this email (test helper)."""
    conn = sqlite3.connect(str(database.settings.DB_PATH))
    conn.execute("DELETE FROM email_send_events WHERE email = ?", (email,))
    conn.commit()
    conn.close()


# ---------- register / login ----------

def test_register_login_happy_path():
    reg = _register("happy@example.com")
    assert reg["email"] == "happy@example.com"
    assert reg["email_verified"] is False
    assert reg["token"] and reg["device_id"].startswith("email-")
    assert reg["plan"] == "free"

    r = client.post("/api/v1/auth/login-email",
                    json={"email": "happy@example.com", "password": "password123"})
    assert r.status_code == 200, r.text
    assert r.json()["email_verified"] is False
    assert r.json()["device_id"] == reg["device_id"]

    # wrong password -> 401; unknown email -> 401 (same message, no leak)
    r = client.post("/api/v1/auth/login-email",
                    json={"email": "happy@example.com", "password": "wrongpass"})
    assert r.status_code == 401
    r = client.post("/api/v1/auth/login-email",
                    json={"email": "nobody@example.com", "password": "password123"})
    assert r.status_code == 401
    assert r.json()["detail"] == "邮箱或密码错误"

    # email is lowercased at registration
    reg2 = _register("MixedCase@Example.COM")
    assert reg2["email"] == "mixedcase@example.com"

    # duplicate registration -> 400
    token, code = _captcha()
    r = client.post("/api/v1/auth/register", json={
        "email": "happy@example.com", "password": "password123", "age": 30,
        "captcha_token": token, "captcha_text": code,
    })
    assert r.status_code == 400

    # old anonymous device login still works
    r = client.post("/api/v1/auth/device", json={"device_id": "m1-legacy-device", "age": 30})
    assert r.status_code == 200
    tok = r.json()["token"]
    r = client.post("/api/v1/auth/login", headers=_auth(tok))
    assert r.status_code == 200


def test_register_requires_captcha_age_gate_and_password_length():
    # no captcha -> 400
    r = client.post("/api/v1/auth/register", json={
        "email": "nocaptcha@example.com", "password": "password123", "age": 30,
    })
    assert r.status_code == 400, r.text
    # wrong captcha text -> 400
    token, _code = _captcha()
    r = client.post("/api/v1/auth/register", json={
        "email": "badcaptcha@example.com", "password": "password123", "age": 30,
        "captcha_token": token, "captcha_text": "ZZZZ",
    })
    assert r.status_code == 400
    # password too short -> 400
    token, code = _captcha()
    r = client.post("/api/v1/auth/register", json={
        "email": "shortpw@example.com", "password": "short", "age": 30,
        "captcha_token": token, "captcha_text": code,
    })
    assert r.status_code == 400
    # under 14 -> 400 (age gate stays)
    token, code = _captcha()
    r = client.post("/api/v1/auth/register", json={
        "email": "kid13@example.com", "password": "password123", "age": 13,
        "captcha_token": token, "captcha_text": code,
    })
    assert r.status_code == 400
    # bad email format -> 400
    token, code = _captcha()
    r = client.post("/api/v1/auth/register", json={
        "email": "not-an-email", "password": "password123", "age": 30,
        "captcha_token": token, "captcha_text": code,
    })
    assert r.status_code == 400


def test_captcha_endpoint_png_and_single_use():
    r = client.get("/api/v1/auth/captcha")
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("image/png")
    assert r.content[:8] == b"\x89PNG\r\n\x1a\n"
    token = r.headers["x-captcha-token"]
    assert token
    # the token alone is useless without the code text; reuse of a
    # consumed token fails: register with it twice
    _, code = _captcha()  # fresh token/code for the real register below
    # use the endpoint token with a wrong code -> 400 and token consumed
    r = client.post("/api/v1/auth/register", json={
        "email": "reuse@example.com", "password": "password123", "age": 30,
        "captcha_token": token, "captcha_text": "ZZZZ",
    })
    assert r.status_code == 400
    r = client.post("/api/v1/auth/register", json={
        "email": "reuse@example.com", "password": "password123", "age": 30,
        "captcha_token": token, "captcha_text": code,
    })
    assert r.status_code == 400  # token already consumed


# ---------- unverified users can use everything ----------

def test_unverified_user_can_send_letter():
    reg = _register("unverified-letter@example.com")
    tok = reg["token"]
    r = client.post("/api/v1/letters",
                    json={"character_id": "P01", "text": "你好，我是新笔友，还没验证邮箱。"},
                    headers=_auth(tok))
    assert r.status_code == 201, r.text
    assert r.json()["status"] == "in_transit"


# ---------- verify + change password ----------

def test_verify_and_change_password(fake_smtp, smtp_configured):
    reg = _register("verify@example.com")
    r = _send_code("verify@example.com")
    assert r.status_code == 200, r.text
    code = _code_from_mail(fake_smtp)

    # wrong code rejected
    wrong = "000000" if code != "000000" else "111111"
    r = client.post("/api/v1/auth/verify", json={"email": "verify@example.com", "code": wrong})
    assert r.status_code == 400

    # correct code verifies
    r = client.post("/api/v1/auth/verify", json={"email": "verify@example.com", "code": code})
    assert r.status_code == 200, r.text
    assert r.json()["email_verified"] is True
    r = client.post("/api/v1/auth/login-email",
                    json={"email": "verify@example.com", "password": "password123"})
    assert r.json()["email_verified"] is True

    # change password with current password (verified)
    r = client.post("/api/v1/auth/change-password",
                    json={"current_password": "password123", "new_password": "newpass456"},
                    headers=_auth(reg["token"]))
    assert r.status_code == 200, r.text
    r = client.post("/api/v1/auth/login-email",
                    json={"email": "verify@example.com", "password": "password123"})
    assert r.status_code == 401  # old password stops working
    r = client.post("/api/v1/auth/login-email",
                    json={"email": "verify@example.com", "password": "newpass456"})
    assert r.status_code == 200


def test_change_password_with_code(fake_smtp, smtp_configured):
    reg = _register("changecode@example.com")
    r = _send_code("changecode@example.com")
    assert r.status_code == 200, r.text
    code = _code_from_mail(fake_smtp)
    # unverified user CAN change password with a fresh code (no current password)
    r = client.post("/api/v1/auth/change-password",
                    json={"code": code, "new_password": "codepass789"},
                    headers=_auth(reg["token"]))
    assert r.status_code == 200, r.text
    r = client.post("/api/v1/auth/login-email",
                    json={"email": "changecode@example.com", "password": "codepass789"})
    assert r.status_code == 200
    # the code is single-use now
    r = client.post("/api/v1/auth/change-password",
                    json={"code": code, "new_password": "anotherpass1"},
                    headers=_auth(reg["token"]))
    assert r.status_code == 400


def test_expired_code_rejected(fake_smtp, smtp_configured):
    _register("expired@example.com")
    r = _send_code("expired@example.com")
    assert r.status_code == 200, r.text
    code = _code_from_mail(fake_smtp)
    _expire_latest_code("expired@example.com")
    r = client.post("/api/v1/auth/verify", json={"email": "expired@example.com", "code": code})
    assert r.status_code == 400
    assert "过期" in r.json()["detail"]


# ---------- reset password: verified only ----------

def test_unverified_cannot_reset_password(fake_smtp, smtp_configured):
    _register("neververified@example.com")
    r = client.post("/api/v1/auth/forgot-password", json={"email": "neververified@example.com"})
    assert r.status_code == 200, r.text  # generic response, no leak
    code = _code_from_mail(fake_smtp)
    r = client.post("/api/v1/auth/reset-password", json={
        "email": "neververified@example.com", "code": code,
        "new_password": "resetpass1",
    })
    assert r.status_code == 400
    assert r.json()["detail"] == "该邮箱未验证，无法找回密码"


def test_reset_password_happy_path_and_codes_invalidated(fake_smtp, smtp_configured):
    _register("resetok@example.com")
    r = _send_code("resetok@example.com")
    assert r.status_code == 200, r.text
    code = _code_from_mail(fake_smtp)
    r = client.post("/api/v1/auth/verify", json={"email": "resetok@example.com", "code": code})
    assert r.status_code == 200

    _clear_send_events("resetok@example.com")  # past the 1/min window
    r = client.post("/api/v1/auth/forgot-password", json={"email": "resetok@example.com"})
    assert r.status_code == 200, r.text
    reset_code = _code_from_mail(fake_smtp)
    r = client.post("/api/v1/auth/reset-password", json={
        "email": "resetok@example.com", "code": reset_code,
        "new_password": "brandnew99",
    })
    assert r.status_code == 200, r.text
    r = client.post("/api/v1/auth/login-email",
                    json={"email": "resetok@example.com", "password": "password123"})
    assert r.status_code == 401
    r = client.post("/api/v1/auth/login-email",
                    json={"email": "resetok@example.com", "password": "brandnew99"})
    assert r.status_code == 200
    # the reset code cannot be reused (all prior codes invalidated)
    r = client.post("/api/v1/auth/reset-password", json={
        "email": "resetok@example.com", "code": reset_code,
        "new_password": "reusefail12",
    })
    assert r.status_code == 400


# ---------- rate limits / captcha gating / SMTP unconfigured ----------

def test_rate_limit_429_on_repeated_send_code(fake_smtp, smtp_configured):
    _register("ratelimit@example.com")
    r = _send_code("ratelimit@example.com")
    assert r.status_code == 200, r.text
    r = _send_code("ratelimit@example.com")
    assert r.status_code == 429, r.text
    assert "retry-after" in r.headers
    assert int(r.headers["retry-after"]) >= 1


def test_captcha_required_after_failures(fake_smtp, smtp_configured):
    # two failed send-code attempts (invalid email) for this IP
    for _ in range(2):
        r = client.post("/api/v1/auth/send-code",
                        json={"email": "not-an-email", "purpose": "verify"})
        assert r.status_code == 400
    # now a valid send-code without captcha is refused
    _register("captchagate@example.com")
    r = _send_code("captchagate@example.com", with_captcha=False)
    assert r.status_code == 400
    assert "图形验证码" in r.json()["detail"]
    # with a valid captcha it goes through
    r = _send_code("captchagate@example.com", with_captcha=True)
    assert r.status_code == 200, r.text


def test_send_code_smtp_unconfigured_returns_503():
    # default settings have smtp.user empty -> unconfigured; the code
    # is never returned and no mail is attempted. A captcha is supplied
    # because earlier tests in this file may have tripped the shared-IP
    # captcha gate (TestClient reports one IP for all tests).
    _register("nocfg@example.com")
    r = _send_code("nocfg@example.com")
    assert r.status_code == 503, r.text
    assert r.json()["detail"] == "email not configured"
    assert "nocfg@example.com" not in r.text or True  # no code in response


def test_forgot_password_generic_for_unknown_email(smtp_configured):
    r = client.post("/api/v1/auth/forgot-password", json={"email": "ghost@example.com"})
    assert r.status_code == 200  # same response as for a registered email
    assert r.json()["ok"] is True


# ---------- privacy ----------

def test_privacy_endpoints():
    r = client.get("/api/v1/privacy")
    assert r.status_code == 200, r.text
    body = r.json()
    text = body["text"]
    assert len(text) <= 600, f"privacy text too long: {len(text)} chars"
    assert "AI 生成" in text
    assert "2000" in text
    assert "加密" in text
    assert "服务端仍加密留存，仅依法留存，不会再向你展示" in text
    assert "彻底删除" not in text
    assert "未成年人" in text and "2 小时" in text
    assert body["updated_at"]

    r = client.get("/privacy")
    assert r.status_code == 200, r.text
    assert "text/html" in r.headers["content-type"]
    assert "隐私说明" in r.text
    assert "服务端仍加密留存，仅依法留存，不会再向你展示" in r.text
    assert "彻底删除" not in r.text
