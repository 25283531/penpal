"""Penpal tests — email-is-the-only-identity + virtual-world name +
anonymous read-only.

Covers the three decisions that replaced the old "anonymous can write"
setup (2026-11-21):

1. Register/login migrate the anonymous trial data into the email
   account (deduped, idempotent) and retire the anonymous device.
2. Registration requires a virtual-world name (display_name, 1-20
   chars, Chinese / letters / digits); pen pals address the user by
   it in replies; anonymous users are addressed as "你" with no
   invented name. GET/PATCH /auth/me + /auth/display-name serve the
   我的 page.
3. Anonymous devices are read-only: POST /letters -> 403
   anonymous_letter_forbidden, and anonymous browsing earns no points.
   Registered-but-unverified accounts CAN send.

Run with: python -m pytest tests/ -q
"""
import os
import tempfile
from datetime import date
from unittest.mock import patch

os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="penpal-linking-test-")
os.environ["JWT_SECRET"] = "test-secret"
for k in ("DASHSCOPE_API_KEY", "HUNYUAN_API_KEY", "SILICONFLOW_API_KEY",
          "ZHIPU_API_KEY", "GENERIC_LLM_API_KEY"):
    os.environ.pop(k, None)

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import database, email_auth  # noqa: E402
from app.context import build_reply_context  # noqa: E402
from app.main import app  # noqa: E402

database.init_db()  # TestClient without a context manager skips lifespan
client = TestClient(app)


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _captcha():
    token, code, _png = email_auth.create_captcha()
    return token, code


def _anon(device_id: str, age: int = 30) -> str:
    r = client.post("/api/v1/auth/device", json={"device_id": device_id, "age": age})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def _register(email: str, display_name: str = "阿辉", device_id: str | None = None,
              password: str = "password123"):
    token, code = _captcha()
    body: dict = {
        "email": email, "password": password, "age": 30,
        "display_name": display_name,
        "captcha_token": token, "captcha_text": code,
    }
    if device_id:
        body["device_id"] = device_id
    return client.post("/api/v1/auth/register", json=body)


def _seed_legacy_anon(device_id: str) -> dict:
    """Anonymous data as the OLD version produced it (writing was
    allowed then): one letter + its write point + a login point + an
    active relationship. Seeded at the DB layer because the API no
    longer lets anonymous devices write."""
    database.get_or_create_device(device_id, age=30)
    database.start_relationship(device_id, "P01", max_active=1)
    letter = database.create_user_letter(
        device_id, "P01", "你好，我是老版本的匿名笔友。", date.today().isoformat(), True,
    )
    database.award_point(device_id, "write", ref_id=str(letter["id"]))
    database.award_point(device_id, "login")
    assert database.points_balance(device_id) == 2
    return letter


def _send(token: str, character_id: str = "P01", text: str = "你好，我是新来的笔友。"):
    return client.post(
        "/api/v1/letters",
        json={"character_id": character_id, "text": text},
        headers=_auth(token),
    )


# ---------- 1. register migrates + retires the anonymous device ----------

def test_register_migrates_legacy_anon_data_and_retires_device():
    anon_id = "legacy-anon-001"
    anon_tok = _anon(anon_id)
    legacy = _seed_legacy_anon(anon_id)

    r = _register("migrate@example.com", display_name="云游者", device_id=anon_id)
    assert r.status_code == 200, r.text
    reg = r.json()
    assert reg["device_id"].startswith("email-")
    assert reg["display_name"] == "云游者"
    assert reg["linked_anonymous_device"] is True
    assert reg["migrated"]["merged"] is True
    assert reg["migrated"]["letters_moved"] == 1
    assert reg["migrated"]["points_moved"] == 2  # login + write
    assert reg["migrated"]["points_dropped_duplicate"] == 0
    assert reg["migrated"]["relationships_moved"] == 1

    tok = reg["token"]
    # letters carried over, visible on the home list (in_transit included)
    r = client.get("/api/v1/letters", headers=_auth(tok))
    assert r.status_code == 200
    assert [l["id"] for l in r.json()] == [legacy["id"]]
    assert r.json()[0]["status"] == "in_transit"
    # points carried over, no double-count: login moved, then register's
    # own login award is a no-op for today (2, not 3)
    r = client.get("/api/v1/points", headers=_auth(tok))
    assert r.json()["points"] == 2
    # the anonymous device is retired: its old token is dead
    assert database.device_exists(anon_id) is False
    r = client.get("/api/v1/characters", headers=_auth(anon_tok))
    assert r.status_code == 401
    assert r.json()["code"] == "unknown_device"


def test_register_without_anon_device_still_mints_email_device():
    r = _register("fresh@example.com", display_name="夜行人")
    assert r.status_code == 200, r.text
    assert r.json()["device_id"].startswith("email-")
    assert r.json()["linked_anonymous_device"] is False
    assert r.json()["migrated"]["merged"] is False
    # registration itself awards the day's login point
    assert client.get("/api/v1/points",
                      headers=_auth(r.json()["token"])).json()["points"] == 1


def test_legacy_email_login_migrates_once_and_is_idempotent():
    # Old user: registered before the merge existed (no anon device).
    r = _register("legacy-login@example.com", display_name="老笔友")
    assert r.status_code == 200, r.text
    email_tok = r.json()["token"]

    # ...meanwhile the same person kept using an anonymous device
    # (old version) and built up data there.
    anon_id = "legacy-anon-002"
    legacy = _seed_legacy_anon(anon_id)

    r = client.post("/api/v1/auth/login-email", json={
        "email": "legacy-login@example.com", "password": "password123",
        "device_id": anon_id,
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["display_name"] == "老笔友"
    # email device already had today's login point from registration,
    # so the anon login point is dropped as a duplicate; the write
    # point moves. Total: register login 1 + write 1 = 2.
    assert body["migrated"]["letters_moved"] == 1
    assert body["migrated"]["points_moved"] == 1
    assert body["migrated"]["points_dropped_duplicate"] == 1
    tok = body["token"]
    assert client.get("/api/v1/points", headers=_auth(tok)).json()["points"] == 2
    letters = client.get("/api/v1/letters", headers=_auth(tok)).json()
    assert [l["id"] for l in letters] == [legacy["id"]]
    assert database.device_exists(anon_id) is False

    # second login with the same anon id: nothing left to move, no
    # double-count, data intact.
    r = client.post("/api/v1/auth/login-email", json={
        "email": "legacy-login@example.com", "password": "password123",
        "device_id": anon_id,
    })
    assert r.status_code == 200, r.text
    assert r.json()["migrated"]["letters_moved"] == 0
    assert r.json()["migrated"]["points_moved"] == 0
    assert client.get("/api/v1/points", headers=_auth(tok)).json()["points"] == 2
    assert len(client.get("/api/v1/letters", headers=_auth(tok)).json()) == 1


def test_migration_refuses_device_bound_to_another_email():
    _register("owner@example.com", display_name="主人")
    # a device already bound to owner@example.com cannot be claimed by
    # a second registration...
    owner_device = database.get_user_by_email("owner@example.com")["device_id"]
    r = _register("thief@example.com", display_name="小偷", device_id=owner_device)
    assert r.status_code == 409, r.text
    assert r.json()["code"] == "device_already_bound"
    # ...nor by a login under another email
    r = _register("victim@example.com", display_name="受害者")
    assert r.status_code == 200
    r = client.post("/api/v1/auth/login-email", json={
        "email": "victim@example.com", "password": "password123",
        "device_id": owner_device,
    })
    assert r.status_code == 409, r.text
    assert r.json()["code"] == "device_already_bound"


# ---------- 2. virtual-world name: required, validated, used ----------

def test_display_name_required_and_validated():
    # missing -> 422 (required field)
    token, code = _captcha()
    r = client.post("/api/v1/auth/register", json={
        "email": "noname@example.com", "password": "password123", "age": 30,
        "captcha_token": token, "captcha_text": code,
    })
    assert r.status_code == 422, r.text
    # too long (21 chars) -> 400 invalid_display_name
    r = _register("longname@example.com", display_name="阿" * 21)
    assert r.status_code == 400, r.text
    assert r.json()["code"] == "invalid_display_name"
    # punctuation / spaces not allowed
    r = _register("punct@example.com", display_name="阿辉!")
    assert r.status_code == 400
    assert r.json()["code"] == "invalid_display_name"
    r = _register("space@example.com", display_name="阿 辉")
    assert r.status_code == 400
    assert r.json()["code"] == "invalid_display_name"
    # empty after strip -> 400
    r = _register("blank@example.com", display_name="   ")
    assert r.status_code == 400
    # 20 chars is fine; Chinese / letters / digits all fine
    r = _register("edge@example.com", display_name="阿" * 20)
    assert r.status_code == 200, r.text
    r = _register("mixed@example.com", display_name="A辉2026")
    assert r.status_code == 200, r.text


def test_profile_view_and_rename_take_effect_immediately():
    r = _register("profile@example.com", display_name="初名")
    assert r.status_code == 200, r.text
    tok = r.json()["token"]
    email_device = r.json()["device_id"]

    r = client.get("/api/v1/auth/me", headers=_auth(tok))
    assert r.status_code == 200
    assert r.json()["email"] == "profile@example.com"
    assert r.json()["display_name"] == "初名"
    assert r.json()["email_verified"] is False

    # rename: takes effect immediately, visible in profile AND in the
    # next reply's context (the name is read live from the users row)
    r = client.patch("/api/v1/auth/display-name",
                     json={"display_name": "新名字"}, headers=_auth(tok))
    assert r.status_code == 200, r.text
    assert r.json()["display_name"] == "新名字"
    assert "新名字" in build_reply_context(email_device, "P01")
    assert "初名" not in build_reply_context(email_device, "P01")

    # invalid rename rejected, old name kept
    r = client.patch("/api/v1/auth/display-name",
                     json={"display_name": "bad name!"}, headers=_auth(tok))
    assert r.status_code == 400
    assert r.json()["code"] == "invalid_display_name"
    assert client.get("/api/v1/auth/me", headers=_auth(tok)).json()["display_name"] == "新名字"

    # anonymous devices have no name to rename...
    anon_tok = _anon("profile-anon-001")
    r = client.patch("/api/v1/auth/display-name",
                     json={"display_name": "谁"}, headers=_auth(anon_tok))
    assert r.status_code == 400
    assert r.json()["code"] == "account_email_not_bound"
    # ...but they can still view their (empty) profile
    r = client.get("/api/v1/auth/me", headers=_auth(anon_tok))
    assert r.status_code == 200
    assert r.json()["email"] is None and r.json()["display_name"] is None


def test_reply_context_uses_display_name_or_falls_back_to_you():
    r = _register("ctx@example.com", display_name="云游者")
    device_id = r.json()["device_id"]
    ctx = build_reply_context(device_id, "P01")
    assert "云游者" in ctx
    assert "不用每句都喊" in ctx

    anon_id = "ctx-anon-001"
    _anon(anon_id)
    ctx = build_reply_context(anon_id, "P01")
    assert "用“你”称呼" in ctx
    assert "不要编造名字" in ctx

    # end to end: the captured generation context carries the name,
    # and the stored reply (mocked LLM) contains it.
    _seed_legacy_anon("ctx-anon-002")  # legacy data only; reply needs a send
    tok, reg_device = _registered_via_migration("ctx2@example.com", "星野", "ctx-anon-002")
    assert _send(tok, "P01", "你好，我最近在想要不要换工作。").status_code == 409  # legacy letter outstanding
    captured: dict = {}

    def _fake_generate(char, user_letter, context=None, **_kw):
        captured["context"] = context or ""
        return "星野，你好。我是林澈，谢谢你的来信。"

    with patch("app.replies.generate_reply_text", side_effect=_fake_generate):
        r = client.post("/api/v1/letters/process-due", json={}, headers=_auth(tok))
    assert r.status_code == 200 and r.json()["replied"] == 1, r.text
    assert "星野" in captured["context"]
    thread = client.get("/api/v1/letters?character_id=P01", headers=_auth(tok)).json()
    assert thread[1]["direction"] == "ai" and "星野" in thread[1]["text"]


def _registered_via_migration(email: str, display_name: str, anon_id: str):
    r = _register(email, display_name=display_name, device_id=anon_id)
    assert r.status_code == 200, r.text
    return r.json()["token"], r.json()["device_id"]


# ---------- 3. anonymous is read-only ----------

def test_anonymous_cannot_send_letters_but_can_browse():
    anon_tok = _anon("readonly-anon-001")
    # browse works
    r = client.get("/api/v1/characters", headers=_auth(anon_tok))
    assert r.status_code == 200
    r = client.get("/api/v1/letters", headers=_auth(anon_tok))
    assert r.status_code == 200 and r.json() == []
    # ...but sending is forbidden with a stable code for the app to map
    r = _send(anon_tok, "P01", "你好，我想写信。")
    assert r.status_code == 403, r.text
    assert r.json()["code"] == "anonymous_letter_forbidden"
    # and browsing earns no points and builds no relationships
    r = client.post("/api/v1/auth/login", headers=_auth(anon_tok))
    assert r.status_code == 200
    assert r.json()["points_awarded"] == 0
    assert r.json()["points"] == 0
    assert database.list_relationships("readonly-anon-001") == []


def test_registered_but_unverified_can_send():
    r = _register("unverified-send@example.com", display_name="未验证")
    assert r.status_code == 200, r.text
    assert r.json()["email_verified"] is False
    r = _send(r.json()["token"], "P01", "你好，我还没验证邮箱，但能写信。")
    assert r.status_code == 201, r.text
    assert r.json()["status"] == "in_transit"


def test_anonymous_login_point_not_awarded():
    # a fresh anonymous registration earns no login point anymore
    _anon("nopoints-anon-001")
    assert database.points_balance("nopoints-anon-001") == 0


# ---------- task 2 (from the earlier round): list returns in-transit ----------

def test_list_letters_returns_in_transit_and_matches_409():
    r = _register("in-transit@example.com", display_name="在途")
    tok = r.json()["token"]
    r = _send(tok, "P01", "你好，第一封。")
    assert r.status_code == 201, r.text
    letter_id = r.json()["id"]
    # the 409 (outstanding letter) and the list agree under one token:
    # the same letter the 409 complains about IS in GET /letters.
    r = _send(tok, "P01", "再写一封。")
    assert r.status_code == 409
    assert r.json()["code"] == "unanswered_letter"
    letters = client.get("/api/v1/letters", headers=_auth(tok)).json()
    assert [l["id"] for l in letters] == [letter_id]
    assert letters[0]["status"] == "in_transit"
