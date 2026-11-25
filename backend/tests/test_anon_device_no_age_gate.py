"""Anonymous device auth has no age gate; the 18+ gate lives only on
email registration.

Run with: /tmp/penpal-venv/bin/python -m pytest backend/tests/ -q

Regression for the fresh-device first-launch failure: the app only
sends a deviceId to POST /api/v1/auth/device, and the old code
refused that with 400 age_required, so a brand-new install could
not get a token at all and the characters page loaded nothing.

Covers:
- a brand-new anonymous device (no age, no birth_date) gets 200
  with age NULL / minor_mode off / is_adult NULL, and can then
  browse the character list;
- anonymous auth NEVER returns an age error code, whatever age or
  birth date a (legacy) client sends — missing, 13, 16, under-18
  birth date, malformed or future birth date;
- re-authenticating an existing device without age still works
  (old accounts are never re-gated);
- [RED LINE] email registration still requires a birth date
  (missing -> 400 birth_date_required, even with an age number)
  and still refuses under-18s (400 age_under_18).
"""
import os
import tempfile
from datetime import date, timedelta

os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="penpal-anon-age-test-")
os.environ["JWT_SECRET"] = "test-secret"
for k in ("DASHSCOPE_API_KEY", "HUNYUAN_API_KEY", "SILICONFLOW_API_KEY",
          "ZHIPU_API_KEY", "GENERIC_LLM_API_KEY"):
    os.environ.pop(k, None)

from fastapi.testclient import TestClient  # noqa: E402

from app import database, email_auth  # noqa: E402
from app.main import app  # noqa: E402

database.init_db()  # TestClient without a context manager skips lifespan
client = TestClient(app)

# Age-class codes that anonymous auth must never return.
AGE_CODES = {"age_required", "age_invalid", "underage_refused", "age_under_18",
             "invalid_birth_date", "birth_date_in_future", "birth_date_required"}


def _years_ago_iso(n: int, days_offset: int = 0) -> str:
    today = date.today()
    try:
        d = today.replace(year=today.year - n)
    except ValueError:  # Feb 29 -> Feb 28
        d = today.replace(year=today.year - n, day=28)
    return (d + timedelta(days=days_offset)).isoformat()


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def test_fresh_anonymous_device_gets_token_without_age():
    r = client.post("/api/v1/auth/device", json={"device_id": "anon-fresh-001"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["token"]
    assert body["age"] is None
    assert body["minor_mode"] is False
    assert body["is_adult"] is None
    # Stored row really has NULL age (devices.age is nullable).
    assert database.get_device("anon-fresh-001")["age"] is None
    # ... and the fresh install can immediately browse characters.
    chars = client.get("/api/v1/characters", headers=_auth(body["token"]))
    assert chars.status_code == 200, chars.text
    assert len(chars.json()) >= 1


def test_anonymous_auth_never_returns_age_error_code():
    bodies = [
        {"device_id": "anon-nogate-missing"},
        {"device_id": "anon-nogate-13", "age": 13},
        {"device_id": "anon-nogate-16", "age": 16},
        {"device_id": "anon-nogate-30", "age": 30},
        {"device_id": "anon-nogate-u18", "birth_date": _years_ago_iso(17)},
        {"device_id": "anon-nogate-u10", "birth_date": _years_ago_iso(10)},
        {"device_id": "anon-nogate-badbd", "birth_date": "2008/11/22"},
        {"device_id": "anon-nogate-futurebd",
         "birth_date": (date.today() + timedelta(days=1)).isoformat()},
    ]
    for body in bodies:
        r = client.post("/api/v1/auth/device", json=body)
        assert r.status_code == 200, f"{body}: {r.text}"
        assert r.json().get("code") not in AGE_CODES
    # Under-18 values are stored (minor mode on), not refused.
    assert database.get_device("anon-nogate-13")["minor_mode"] == 1
    assert database.get_device("anon-nogate-u18")["minor_mode"] == 1
    assert database.get_device("anon-nogate-u18")["age"] == 17
    # Unusable birth dates are ignored, never stored.
    assert database.get_device("anon-nogate-badbd")["age"] is None
    assert database.get_device("anon-nogate-futurebd")["age"] is None


def test_existing_device_reauth_without_age_still_works():
    r = client.post("/api/v1/auth/device",
                    json={"device_id": "anon-reauth-001", "age": 30})
    assert r.status_code == 200, r.text
    r = client.post("/api/v1/auth/device", json={"device_id": "anon-reauth-001"})
    assert r.status_code == 200, r.text
    assert r.json()["age"] == 30
    assert r.json()["minor_mode"] is False


def _register(email: str, birth_date: str | None = None,
              age: int | None = None):
    token, code, _png = email_auth.create_captcha()
    body: dict = {
        "email": email, "password": "password123",
        "display_name": "阿辉",
        "captcha_token": token, "captcha_text": code,
    }
    if birth_date is not None:
        body["birth_date"] = birth_date
    if age is not None:
        body["age"] = age
    return client.post("/api/v1/auth/register", json=body)


def test_register_without_birth_date_refused_even_with_age():
    # An age number alone never satisfies registration.
    r = _register("anon-gate-age30@example.com", age=30)
    assert r.status_code == 400, r.text
    assert r.json()["code"] == "birth_date_required"
    assert database.get_user_by_email("anon-gate-age30@example.com") is None
    r = _register("anon-gate-noage@example.com")
    assert r.status_code == 400, r.text
    assert r.json()["code"] == "birth_date_required"
    assert database.get_user_by_email("anon-gate-noage@example.com") is None


def test_register_under_18_still_refused():
    r = _register("anon-gate-u18@example.com",
                  birth_date=_years_ago_iso(17))
    assert r.status_code == 400, r.text
    assert r.json()["code"] == "age_under_18"
    assert database.get_user_by_email("anon-gate-u18@example.com") is None
