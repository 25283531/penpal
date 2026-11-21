#!/usr/bin/env python3
"""End-to-end scenario for the 2026-11-21 Penpal round (app + backend contract).

Reproduces the user's exact journey at the API level, the way the Android
app drives it (see PenpalRepository):

  1. Anonymous device browses; POST /letters as anonymous -> 403
     anonymous_letter_forbidden (the app maps it to err_email_required:
     "注册邮箱后才能给笔友写信").
  2. Legacy anonymous data (a letter + points, from before anonymous
     writing was disabled) migrates into the new email account on
     register with device_id + device_token + display_name.
  3. GET /letters under the email token shows the in-transit letter with
     delivery_stage_text + expected_reply_at; GET /points is not 0.
  4. The old anonymous token 401s (device retired) — the app must never
     fall back to it.
  5. A second send to the same character -> 409 unanswered_letter, and
     the same letter IS in GET /letters (the original "home shows no
     letters while a letter is unanswered" contradiction, now closed).
  6. GET /auth/me echoes the display name; PATCH /auth/display-name
     renames it immediately.
  7. Login-email with device_id + device_token migrates a legacy
     anonymous device for an already-registered account.

Run:  cd backend && /tmp/penpal-venv/bin/python ../app/e2e_scenario.py
Exit code 0 = all steps pass.
"""
import os
import sys
import tempfile
from datetime import date

os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="penpal-e2e-")
os.environ["JWT_SECRET"] = "test-secret"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)) + "/../backend")

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app import database, email_auth  # noqa: E402

database.init_db()
client = TestClient(app)

failures = []


def check(cond, msg):
    print(("PASS " if cond else "FAIL ") + msg)
    if not cond:
        failures.append(msg)


def auth(token):
    return {"Authorization": f"Bearer {token}"}


def captcha():
    token, code, _png = email_auth.create_captcha()
    return token, code


# ---- 1. Anonymous browsing: read OK, write forbidden ----
r = client.post("/api/v1/auth/device", json={"device_id": "anon-device-1", "age": 30})
assert r.status_code == 200, r.text
anon_token = r.json()["token"]
anon_id = r.json()["device_id"]
r = client.get("/api/v1/characters", headers=auth(anon_token))
check(r.status_code == 200 and len(r.json()) >= 1, "anonymous can browse characters")
r = client.post(
    "/api/v1/letters",
    json={"character_id": "P01", "text": "你好"},
    headers=auth(anon_token),
)
check(r.status_code == 403, "anonymous POST /letters -> 403")
check(r.json().get("code") == "anonymous_letter_forbidden",
      "anonymous 403 carries code anonymous_letter_forbidden")
check("发信需要注册邮箱账号" in r.json().get("detail", ""),
      "anonymous 403 detail is the Chinese prompt")

# ---- 2. Seed legacy anonymous data (pre-rule era: anonymous could write) ----
database.start_relationship(anon_id, "P01", max_active=1)
letter = database.create_user_letter(
    anon_id, "P01", "你好，我是老版本的匿名笔友。", date.today().isoformat(), True,
)
database.award_point(anon_id, "write", ref_id=str(letter["id"]))
database.award_point(anon_id, "login")
check(database.points_balance(anon_id) == 2, "legacy anonymous device has 2 points")

# ---- 3. Register with display name + anonymous link (what the app sends) ----
tok, code = captcha()
r = client.post("/api/v1/auth/register", json={
    "email": "e2e@example.com", "password": "password123", "age": 30,
    "display_name": "阿辉", "captcha_token": tok, "captcha_text": code,
    "device_id": anon_id, "device_token": anon_token,
})
check(r.status_code == 200, "register with link -> 200")
body = r.json()
check(body.get("display_name") == "阿辉", "register echoes display_name")
check(body.get("linked_anonymous_device") is True, "register linked the anonymous device")
mig = body.get("migrated") or {}
check(mig.get("letters_moved") == 1, f"migration moved the letter ({mig})")
check(mig.get("points_moved") == 2, f"migration moved the points ({mig})")
email_token = body["token"]

# ---- 4. Home timeline + points under the email account ----
letters = client.get("/api/v1/letters", headers=auth(email_token)).json()
check(len(letters) == 1 and letters[0]["id"] == letter["id"],
      "GET /letters under the email account shows the migrated letter")
check(letters[0].get("status") == "in_transit", "migrated letter is in_transit")
check(bool(letters[0].get("delivery_stage_text")),
      "in-transit letter has delivery_stage_text")
check(bool(letters[0].get("expected_reply_at")),
      "in-transit letter has expected_reply_at")
pts = client.get("/api/v1/points", headers=auth(email_token)).json()
check(pts.get("points", 0) >= 2, f"points under email account are not 0 ({pts.get('points')})")

# ---- 5. Old anonymous token is dead (retired) ----
r = client.get("/api/v1/letters", headers=auth(anon_token))
check(r.status_code == 401, "retired anonymous token -> 401 (app must not reuse it)")

# ---- 6. The 409 and the list agree ----
r = client.post("/api/v1/letters", json={"character_id": "P01", "text": "再写一封"},
                headers=auth(email_token))
check(r.status_code == 409 and r.json().get("code") == "unanswered_letter",
      "second send to P01 -> 409 unanswered_letter")
letters = client.get("/api/v1/letters", headers=auth(email_token)).json()
check([x["id"] for x in letters] == [letter["id"]],
      "the letter the 409 complains about IS in GET /letters")

# ---- 7. Profile + rename ----
me = client.get("/api/v1/auth/me", headers=auth(email_token)).json()
check(me.get("display_name") == "阿辉" and me.get("email") == "e2e@example.com",
      "GET /auth/me returns display_name + email")
r = client.patch("/api/v1/auth/display-name", json={"display_name": "小辉"},
                 headers=auth(email_token))
check(r.status_code == 200 and r.json().get("display_name") == "小辉",
      "PATCH /auth/display-name renames immediately")
r = client.patch("/api/v1/auth/display-name", json={"display_name": "x"},
                 headers=auth(anon_token))
check(r.status_code == 401, "rename with the retired token -> 401, not a silent no-op")

# ---- 8. Login-email migrates a legacy anonymous device (old account) ----
tok, code = captcha()
r = client.post("/api/v1/auth/register", json={
    "email": "old@example.com", "password": "password123", "age": 30,
    "display_name": "老用户", "captcha_token": tok, "captcha_text": code,
})
assert r.status_code == 200, r.text
r = client.post("/api/v1/auth/device", json={"device_id": "anon-device-2", "age": 30})
anon2_token = r.json()["token"]
anon2_id = r.json()["device_id"]
database.start_relationship(anon2_id, "P01", max_active=1)
letter2 = database.create_user_letter(
    anon2_id, "P01", "老账号的匿名期来信。", date.today().isoformat(), True,
)
database.award_point(anon2_id, "write", ref_id=str(letter2["id"]))
r = client.post("/api/v1/auth/login-email", json={
    "email": "old@example.com", "password": "password123",
    "device_id": anon2_id, "device_token": anon2_token,
})
check(r.status_code == 200, "login-email with link -> 200")
mig = r.json().get("migrated") or {}
check(mig.get("letters_moved") == 1, f"login migration moved the letter ({mig})")
tok2 = r.json()["token"]
letters = client.get("/api/v1/letters", headers=auth(tok2)).json()
check(any(x["id"] == letter2["id"] for x in letters),
      "old account sees the migrated letter after login")

print()
if failures:
    print(f"{len(failures)} FAILURES")
    sys.exit(1)
print("ALL E2E STEPS PASSED")
