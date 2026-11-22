"""Points consistency tests (Bug 2 investigation) — run with: python -m pytest tests/ -q

Bug 2 report: the App home page showed 4 points while the 我的 page
showed 0. Both pages read the backend, but through different
endpoints — home via POST /api/v1/auth/login (dailyLogin, field
`points`), 我的 via GET /api/v1/points (getPoints, field `points`).

Backend finding (locked in by these tests): the two endpoints cannot
diverge for the same identity. Both resolve the caller with the same
get_current_device (Bearer token -> device_id) and both return the
same single source, database.points_balance(device_id) — a SUM over
that device's point_events. There is no second counter, no cache, and
no per-endpoint adjustment. So for one token the two numbers are
identical by construction; a 4-vs-0 split means the two calls did NOT
use the same identity (different/stale token, e.g. the anonymous
device vs the email account), or one of the calls failed — the App's
我的 page renders a failed getPoints as 0 (`points?.points ?: 0` in
MeScreen.kt) while home keeps its last good value
(HomeScreen.kt only assigns _points on success).

These tests pin the backend side of that conclusion:
- same token -> login and getPoints always agree, after every award;
- a registered account can never read 0 (registration itself awards
  the +1 login point and points are never deducted), so a displayed 0
  cannot come from a successful backend read of that account;
- different identities really do hold different balances (anonymous 0
  vs registered N), which is the split the App must not create by
  mixing tokens.
"""
import os
import tempfile
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="penpal-test-points-")
os.environ["JWT_SECRET"] = "test-secret"
for k in ("DASHSCOPE_API_KEY", "HUNYUAN_API_KEY", "SILICONFLOW_API_KEY",
          "ZHIPU_API_KEY", "GENERIC_LLM_API_KEY"):
    os.environ.pop(k, None)

from app.main import app  # noqa: E402
from app import database  # noqa: E402

database.init_db()
client = TestClient(app)

FAKE_REPLY = "我是林澈，谢谢你的来信。你说的换工作，我想先陪你把这件事拆开看看。"


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _registered(email: str) -> tuple[str, str]:
    from app import email_auth

    token, code, _png = email_auth.create_captcha()
    r = client.post("/api/v1/auth/register", json={
        "email": email, "password": "password123", "age": 30,
        "display_name": "阿辉",
        "captcha_token": token, "captcha_text": code,
    })
    assert r.status_code == 200, r.text
    body = r.json()
    return body["token"], body["device_id"]


def _login_points(token: str) -> int:
    r = client.post("/api/v1/auth/login", headers=_auth(token))
    assert r.status_code == 200, r.text
    return r.json()["points"]


def _get_points(token: str) -> int:
    r = client.get("/api/v1/points", headers=_auth(token))
    assert r.status_code == 200, r.text
    return r.json()["points"]


def test_login_and_points_agree_for_same_identity():
    tok, device_id = _registered("pts-agree@example.com")
    # Registration awards the +1 login point: both endpoints read 1.
    assert _login_points(tok) == 1
    assert _get_points(tok) == 1
    assert database.points_balance(device_id) == 1
    # Write a letter (+1): both move to 2 together.
    r = client.post("/api/v1/letters", json={"character_id": "P01", "text": "你好，第一封信。"},
                    headers=_auth(tok))
    assert r.status_code == 201, r.text
    assert _login_points(tok) == 2
    assert _get_points(tok) == 2
    # Read the reply (+1): both move to 3 together.
    with patch("app.replies.generate_reply_text", return_value=FAKE_REPLY):
        r = client.post("/api/v1/letters/process-due", json={}, headers=_auth(tok))
        assert r.json()["replied"] == 1
    thread = client.get("/api/v1/letters?character_id=P01", headers=_auth(tok)).json()
    reply_id = thread[1]["id"]
    r = client.post(f"/api/v1/letters/{reply_id}/read", headers=_auth(tok))
    assert r.status_code == 200 and r.json()["points_awarded"] == 1
    assert _login_points(tok) == 3
    assert _get_points(tok) == 3


def test_registered_account_never_reads_zero_points():
    # Registration itself awards +1 and points are never deducted, so a
    # successful GET /points for a registered account is >= 1. A
    # displayed 0 therefore cannot be a successful read of that account.
    tok, _device_id = _registered("pts-never-zero@example.com")
    assert _get_points(tok) >= 1
    assert _login_points(tok) >= 1


def test_different_identities_hold_different_balances():
    # The only way two reads differ is two identities: the anonymous
    # device (0, anonymous browsing earns no points) vs the registered
    # account (its own balance). The endpoints do not create the split;
    # whichever token the App sends decides the number.
    r = client.post("/api/v1/auth/device", json={"device_id": "pts-anon-001", "age": 30})
    assert r.status_code == 200, r.text
    anon_tok = r.json()["token"]
    assert _get_points(anon_tok) == 0
    assert _login_points(anon_tok) == 0  # anonymous: awarded=0, balance still 0
    tok, _device_id = _registered("pts-split@example.com")
    client.post("/api/v1/letters", json={"character_id": "P01", "text": "你好。"},
                headers=_auth(tok))
    assert _get_points(tok) == 2
    assert _login_points(tok) == 2
    # And the anonymous identity is untouched by the registered one.
    assert _get_points(anon_tok) == 0


def test_points_with_unknown_token_is_401_not_zero():
    # A failed getPoints must not be silently rendered as a balance.
    # The backend answers 401 (unknown_device / invalid_token); if the
    # App shows 0 for this, the 0 is the App's failure fallback, not a
    # backend balance.
    r = client.get("/api/v1/points", headers={"Authorization": "Bearer bogus.token.here"})
    assert r.status_code == 401
    r = client.post("/api/v1/auth/login", headers={"Authorization": "Bearer bogus.token.here"})
    assert r.status_code == 401
