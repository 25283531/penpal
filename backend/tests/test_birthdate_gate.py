"""Birth-date 18+ gate tests (registration).

Run with: /tmp/penpal-venv/bin/python -m pytest backend/tests/ -q

Covers the switch from the legacy age-number gate to a birth-date
gate for NEW email registrations:
- under-18 (by birth date) refused with stable code age_under_18;
- boundary: 18th birthday itself passes, one day before it refuses;
- future dates and malformed dates refused;
- a missing birth date is refused outright (birth_date_required) —
  an `age` number alone never registers;
- birth date encrypted at rest (never plaintext) and never returned
  by any API (at most the `is_adult` flag);
- anonymous device auth keeps NO age gate at all: any age or birth
  date (including under-18) is stored, never refused;
- already-registered accounts are never re-gated;
- old databases (no birth_date column) gain the nullable column via
  migration, with legacy rows left NULL.
"""
import os
import sqlite3
import tempfile
from datetime import date, timedelta

os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="penpal-birthdate-test-")
os.environ["JWT_SECRET"] = "test-secret"
for k in ("DASHSCOPE_API_KEY", "HUNYUAN_API_KEY", "SILICONFLOW_API_KEY",
          "ZHIPU_API_KEY", "GENERIC_LLM_API_KEY"):
    os.environ.pop(k, None)

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import database, email_auth  # noqa: E402
from app.config import settings  # noqa: E402
from app.crypto import decrypt_or_keep  # noqa: E402
from app.main import app  # noqa: E402

database.init_db()  # TestClient without a context manager skips lifespan
client = TestClient(app)

UNDER_18_DETAIL = "不符合使用条件，必须年满 18 周岁才能使用本软件"


def _years_ago_iso(n: int, days_offset: int = 0) -> str:
    """ISO date exactly n years ago today, shifted by days_offset."""
    today = date.today()
    try:
        d = today.replace(year=today.year - n)
    except ValueError:  # Feb 29 -> Feb 28
        d = today.replace(year=today.year - n, day=28)
    return (d + timedelta(days=days_offset)).isoformat()


def _captcha():
    token, code, _png = email_auth.create_captcha()
    return token, code


def _register(email: str, birth_date: str | None = None,
              age: int | None = None, display_name: str = "阿辉"):
    token, code = _captcha()
    body: dict = {
        "email": email, "password": "password123",
        "display_name": display_name,
        "captcha_token": token, "captcha_text": code,
    }
    if birth_date is not None:
        body["birth_date"] = birth_date
    if age is not None:
        body["age"] = age
    return client.post("/api/v1/auth/register", json=body)


def _raw_birth_date(table: str, where_col: str, where_val: str) -> str | None:
    conn = sqlite3.connect(str(settings.DB_PATH))
    try:
        row = conn.execute(
            f"SELECT birth_date FROM {table} WHERE {where_col} = ?",
            (where_val,),
        ).fetchone()
    finally:
        conn.close()
    assert row is not None, f"no row in {table} for {where_val}"
    return row[0]


# ---------- 18+ gate ----------

def test_register_under_18_refused():
    born = _years_ago_iso(17)
    r = _register("bd-under18@example.com", birth_date=born)
    assert r.status_code == 400, r.text
    assert r.json()["code"] == "age_under_18"
    assert r.json()["detail"] == UNDER_18_DETAIL
    assert database.get_user_by_email("bd-under18@example.com") is None


def test_register_exactly_18th_birthday_passes():
    born = _years_ago_iso(18)
    r = _register("bd-turns18@example.com", birth_date=born)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["age"] == 18
    assert body["minor_mode"] is False
    assert body["is_adult"] is True
    assert body["age_source"] == "birth_date"
    assert born not in r.text
    assert "birth_date" not in body


def test_register_one_day_before_18th_birthday_refused():
    # Born tomorrow, 18 years ago: still 17 today.
    born = _years_ago_iso(18, days_offset=1)
    r = _register("bd-almost18@example.com", birth_date=born)
    assert r.status_code == 400, r.text
    assert r.json()["code"] == "age_under_18"
    assert r.json()["detail"] == UNDER_18_DETAIL


def test_age_from_birth_date_counts_birthday_passed():
    # Not a plain year subtraction: the birthday must have passed.
    born = date(2008, 11, 23)
    assert database.age_from_birth_date(born, on=date(2026, 11, 22)) == 17
    assert database.age_from_birth_date(born, on=date(2026, 11, 23)) == 18


def test_register_future_birth_date_refused():
    born = (date.today() + timedelta(days=1)).isoformat()
    r = _register("bd-future@example.com", birth_date=born)
    assert r.status_code == 400, r.text
    assert r.json()["code"] == "birth_date_in_future"


@pytest.mark.parametrize("bad", [
    "2008/11/22", "2008-11-22x", "2008-02-30", "2008-13-01", "2008-1-1",
])
def test_register_bad_birth_date_format_refused(bad):
    r = _register(f"bd-bad-{bad[:4]}-{len(bad)}@example.com", birth_date=bad)
    assert r.status_code == 400, r.text
    assert r.json()["code"] == "invalid_birth_date"


# ---------- encrypted storage, never leaked ----------

def test_birth_date_encrypted_at_rest_and_never_returned():
    born = _years_ago_iso(30)
    r = _register("bd-encrypted@example.com", birth_date=born)
    assert r.status_code == 200, r.text
    body = r.json()
    assert born not in r.text
    assert "birth_date" not in body
    # Stored value is ciphertext, not the plaintext date.
    raw_device = _raw_birth_date("devices", "device_id", body["device_id"])
    raw_user = _raw_birth_date("users", "email", "bd-encrypted@example.com")
    assert raw_device and raw_device != born
    assert raw_user and raw_user != born
    assert decrypt_or_keep(raw_device) == born
    assert decrypt_or_keep(raw_user) == born
    # Read paths never expose the raw date either.
    device = database.get_device(body["device_id"])
    assert "birth_date" not in device
    assert device["has_birth_date"] is True
    assert device["is_adult"] is True
    user = database.get_user_by_email("bd-encrypted@example.com")
    assert "birth_date" not in user
    assert user["has_birth_date"] is True
    assert user["is_adult"] is True
    # /auth/me does not leak it either.
    me = client.get("/api/v1/auth/me",
                    headers={"Authorization": f"Bearer {body['token']}"})
    assert me.status_code == 200, me.text
    assert born not in me.text
    assert "birth_date" not in me.json()


def test_birth_date_wins_over_age():
    born = _years_ago_iso(30)
    r = _register("bd-wins@example.com", birth_date=born, age=16)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["age"] == 30  # derived from birth_date, not the age number
    assert body["minor_mode"] is False
    assert body["age_source"] == "birth_date"
    user = database.get_user_by_email("bd-wins@example.com")
    assert user["age"] == 30


# ---------- registration requires a birth date (no legacy path) ----------

def test_register_without_birth_date_refused():
    # An age number alone never registers — not 30, not 16, not 13.
    for email, age in (("bd-nobd30@example.com", 30),
                       ("bd-nobd16@example.com", 16),
                       ("bd-nobd13@example.com", 13)):
        r = _register(email, age=age)
        assert r.status_code == 400, r.text
        assert r.json()["code"] == "birth_date_required"
        assert database.get_user_by_email(email) is None
    r = _register("bd-nobd-none@example.com")
    assert r.status_code == 400, r.text
    assert r.json()["code"] == "birth_date_required"
    assert database.get_user_by_email("bd-nobd-none@example.com") is None


def test_device_auth_with_birth_date():
    # Anonymous auth has NO age gate: an under-18 birth date is
    # stored (minor mode on), never refused.
    r = client.post("/api/v1/auth/device", json={
        "device_id": "bd-device-under18", "birth_date": _years_ago_iso(17),
    })
    assert r.status_code == 200, r.text
    assert r.json()["is_adult"] is False
    assert r.json()["minor_mode"] is True
    assert r.json()["age"] == 17
    assert r.json()["age_source"] == "birth_date"
    born = _years_ago_iso(25)
    r = client.post("/api/v1/auth/device", json={
        "device_id": "bd-device-adult", "birth_date": born,
    })
    assert r.status_code == 200, r.text
    assert r.json()["is_adult"] is True
    assert r.json()["age_source"] == "birth_date"
    raw = _raw_birth_date("devices", "device_id", "bd-device-adult")
    assert raw and raw != born and decrypt_or_keep(raw) == born


# ---------- old accounts are never re-gated ----------

def test_old_account_unaffected_by_new_gate():
    # An adult registered with a birth date can still log in.
    reg = _register("bd-old30@example.com", birth_date=_years_ago_iso(30))
    assert reg.status_code == 200, reg.text
    login = client.post("/api/v1/auth/login-email", json={
        "email": "bd-old30@example.com", "password": "password123",
    })
    assert login.status_code == 200, login.text
    me = client.get("/api/v1/auth/me",
                    headers={"Authorization": f"Bearer {login.json()['token']}"})
    assert me.status_code == 200, me.text
    # The old anonymous device also still authenticates as before.
    r = client.post("/api/v1/auth/device", json={
        "device_id": "bd-old-anon-16", "age": 16,
    })
    assert r.status_code == 200, r.text
    assert r.json()["minor_mode"] is True
    r = client.post("/api/v1/auth/device", json={
        "device_id": "bd-old-anon-16",
    })
    assert r.status_code == 200, r.text
    assert r.json()["minor_mode"] is True


# ---------- old-DB migration ----------

def test_old_db_migration_adds_birth_date_column(monkeypatch, tmp_path):
    """A DB created before birth_date existed gains the nullable
    column on init_db, with legacy rows left NULL."""
    old_schema = "\n".join(
        line for line in database.SCHEMA.splitlines()
        if "birth_date" not in line
    )
    tmp_data = tmp_path / "data"
    tmp_data.mkdir()
    db_path = tmp_data / "penpal.db"
    conn = sqlite3.connect(str(db_path))
    conn.executescript(old_schema)
    conn.execute(
        "INSERT INTO devices (device_id, age, minor_mode, plan,"
        " emergency_contact, created_at) VALUES (?, ?, ?, 'free', NULL, ?)",
        ("legacy-dev-1", 30, 0, "2026-01-01"),
    )
    conn.execute(
        "INSERT INTO users (email, password_hash, email_verified,"
        " verified_at, age, device_id, display_name, created_at)"
        " VALUES (?, ?, 0, NULL, ?, ?, ?, ?)",
        ("legacy@example.com", "x", 30, "legacy-dev-1", "阿辉",
         "2026-01-01T00:00:00"),
    )
    conn.commit()
    conn.close()
    monkeypatch.setattr(database.settings, "DATA_DIR", tmp_data)
    monkeypatch.setattr(database.settings, "DB_PATH", db_path)
    database.init_db()
    conn = sqlite3.connect(str(db_path))
    try:
        dev_cols = {row[1] for row in conn.execute("PRAGMA table_info(devices)")}
        user_cols = {row[1] for row in conn.execute("PRAGMA table_info(users)")}
        assert "birth_date" in dev_cols
        assert "birth_date" in user_cols
        row = conn.execute(
            "SELECT birth_date FROM devices WHERE device_id = 'legacy-dev-1'"
        ).fetchone()
        assert row[0] is None
        row = conn.execute(
            "SELECT birth_date FROM users WHERE email = 'legacy@example.com'"
        ).fetchone()
        assert row[0] is None
    finally:
        conn.close()
