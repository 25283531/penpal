"""Penpal tests — read times, expected reply + delivery stage,
unread count, and extended character profile fields.

Run with: python -m pytest tests/ -q
"""
import os
import sqlite3
import tempfile
from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch

os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="penpal-read-delivery-test-")
os.environ["JWT_SECRET"] = "test-secret"
for k in ("DASHSCOPE_API_KEY", "HUNYUAN_API_KEY", "SILICONFLOW_API_KEY",
          "ZHIPU_API_KEY", "GENERIC_LLM_API_KEY"):
    os.environ.pop(k, None)

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import database  # noqa: E402
from app.main import app  # noqa: E402
from app.membership import delivery_stage  # noqa: E402

database.init_db()  # TestClient without a context manager skips lifespan
client = TestClient(app)

FAKE_REPLY = "我是林澈，谢谢你的来信。你说的事，我想先陪你把这件事拆开看看。"


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


def _reply_via_process_due(token: str, day: str | None = None):
    body: dict = {}
    if day:
        body["date"] = day
    with patch("app.replies.generate_reply_text", return_value=FAKE_REPLY):
        r = client.post("/api/v1/letters/process-due", json=body, headers=_auth(token))
    assert r.status_code == 200, r.text
    assert r.json()["replied"] == 1, r.json()
    return r.json()


def _thread(token: str, character_id: str = "P01"):
    r = client.get(f"/api/v1/letters?character_id={character_id}", headers=_auth(token))
    assert r.status_code == 200, r.text
    return r.json()


def _shift_user_letter_created(device_id: str, days_back: int):
    """Move the latest user letter's created_at back N days (test helper
    for the +3-day / delivery-stage checks)."""
    conn = sqlite3.connect(str(database.settings.DB_PATH))
    when = (datetime.now(timezone.utc) - timedelta(days=days_back)).strftime(
        "%Y-%m-%d %H:%M:%S"
    )
    conn.execute(
        "UPDATE letters SET created_at = ? WHERE device_id = ? AND direction = 'user'"
        " AND id = (SELECT MAX(id) FROM letters WHERE device_id = ? AND direction = 'user')",
        (when, device_id, device_id),
    )
    conn.commit()
    conn.close()


# ---------- character profile fields ----------

def test_character_detail_fields_complete():
    tok = _new_device("prof-device-001")
    r = client.get("/api/v1/characters", headers=_auth(tok))
    assert r.status_code == 200
    chars = {c["id"]: c for c in r.json()}
    assert set(chars) == {"P01", "P02", "P03", "P04", "P05"}
    expected = {
        "P01": ("男", "male", 26, "上海"),
        "P02": ("女", "female", 29, "北京"),
        "P03": ("男", "male", 34, "潍坊"),
        "P04": ("女", "female", 27, "杭州"),
        "P05": ("男", "male", 31, "武汉"),
    }
    for cid, (_zh, gender, age, city) in expected.items():
        c = chars[cid]
        assert c["gender"] == gender, cid
        assert c["age"] == age, cid
        assert c["city"] == city, cid
        assert isinstance(c["hobbies"], list) and len(c["hobbies"]) >= 3, cid
        assert isinstance(c["motto"], str) and len(c["motto"]) >= 10, cid
        # 3 life photos, real URLs shipped in the image (never placeholders)
        assert isinstance(c["photos"], list) and len(c["photos"]) == 3, cid
        for p in c["photos"]:
            assert isinstance(p["photo_url"], str) and p["photo_url"].startswith(
                f"/static/photos/{cid}/life"
            ), cid
            assert p["is_placeholder"] is False, cid
            assert p["label"] == "AI 生成 · 虚拟人物", cid
        assert c["photo_url"] == f"/static/photos/{cid}/avatar.jpg", cid
        assert c["photo_status"] == "ready", cid
        # 2 candid shots, reserved for future reply attachments
        assert isinstance(c["candid_photos"], list) and len(c["candid_photos"]) == 2, cid
        for p in c["candid_photos"]:
            assert isinstance(p["photo_url"], str) and p["photo_url"].startswith(
                f"/static/photos/{cid}/candid"
            ), cid
            assert p["is_placeholder"] is False, cid
            assert p["label"] == "AI 生成 · 虚拟人物", cid
    # detail endpoint returns the same fields
    r = client.get("/api/v1/characters/P01", headers=_auth(tok))
    assert r.status_code == 200
    p01 = r.json()
    assert p01["motto"] == chars["P01"]["motto"]
    assert p01["city"] == "上海"
    assert len(p01["photos"]) == 3
    # DB seed carries the same values (backfilled on old DBs too)
    db_char = database.get_character("P04")
    assert db_char["city"] == "杭州"
    assert db_char["motto"] == chars["P04"]["motto"]
    assert len(db_char["photos"]) == 3


# ---------- delivery stage derivation (unit) ----------

def test_delivery_stage_thresholds():
    base = datetime(2026, 11, 20, 10, 0, tzinfo=timezone.utc)
    # same-day due: by hours since sent
    assert delivery_stage(base, "2026-11-20", False, city="上海", name="林澈",
                          now=base + timedelta(minutes=30))[0] == "posted"
    assert delivery_stage(base, "2026-11-20", False, city="上海", name="林澈",
                          now=base + timedelta(hours=2))[0] == "collected"
    stage, text = delivery_stage(base, "2026-11-20", False, city="上海", name="林澈",
                                 now=base + timedelta(hours=5))
    assert stage == "in_transit" and "上海" in text and "林澈" in text
    assert delivery_stage(base, "2026-11-20", False, city="上海", name="林澈",
                          now=base + timedelta(hours=10))[0] == "out_for_delivery"
    stage, text = delivery_stage(base, "2026-11-20", False, city="上海", name="林澈",
                                 now=base + timedelta(hours=20))
    assert stage == "replying" and "林澈" in text
    # multi-day due: by elapsed fraction of sent -> due
    sent = datetime(2026, 11, 20, 10, 0, tzinfo=timezone.utc)
    assert delivery_stage(sent, "2026-11-23", False, city="上海", name="林澈",
                          now=sent)[0] == "posted"
    assert delivery_stage(sent, "2026-11-23", False, city="上海", name="林澈",
                          now=sent + timedelta(days=1))[0] == "collected"
    stage, text = delivery_stage(sent, "2026-11-23", False, city="上海", name="林澈",
                                 now=sent + timedelta(days=1, hours=12))
    assert stage == "in_transit" and "上海" in text
    assert delivery_stage(sent, "2026-11-23", False, city="上海", name="林澈",
                          now=sent + timedelta(days=2, hours=12))[0] == "out_for_delivery"
    assert delivery_stage(sent, "2026-11-23", False, city="上海", name="林澈",
                          now=sent + timedelta(days=3))[0] == "replying"
    # overdue and still unreplied stays at replying; replied -> delivered
    assert delivery_stage(sent, "2026-11-23", False, city="上海", name="林澈",
                          now=sent + timedelta(days=9))[0] == "replying"
    stage, text = delivery_stage(sent, "2026-11-23", True, city="上海", name="林澈",
                                 now=sent + timedelta(days=3))
    assert stage == "delivered" and "已送达" in text


# ---------- expected reply + stage via the API ----------

def test_expected_reply_first_same_day_then_free_plus_3():
    tok, _device_id = _registered("exp@example.com")
    r = _send(tok, "P01", "第一封。")
    assert r.status_code == 201, r.text
    letter = r.json()
    today = date.today().isoformat()
    assert letter["expected_reply_at"] == today
    assert letter["reply_due_at"] == today
    assert letter["delivery_stage"] == "posted"  # just sent, same-day <1h
    assert "邮箱" in letter["delivery_stage_text"]
    assert letter["user_read_at"] is None and letter["character_read_at"] is None

    _reply_via_process_due(tok)
    thread = _thread(tok)
    user_letter, reply = thread[0], thread[1]
    # reply generated: user letter is delivered-stage, character_read_at set
    assert user_letter["delivery_stage"] == "delivered"
    assert "已送达" in user_letter["delivery_stage_text"]
    assert user_letter["character_read_at"] is not None
    # minute-granularity comparison (character_read_at is truncated to
    # the minute by design — see database._character_read_at)
    assert user_letter["created_at"][:16] <= user_letter["character_read_at"][:16] <= user_letter["replied_at"][:16]
    # minute precision only: no faked exact seconds
    assert user_letter["character_read_at"].endswith(":00")
    # AI reply itself carries no expected-reply / delivery stage
    assert reply["direction"] == "ai"
    assert reply["expected_reply_at"] is None
    assert reply["delivery_stage"] is None
    assert reply["delivery_stage_text"] is None
    assert reply["user_read_at"] is None

    # second letter: free tier -> +3 days, stage still derived from real state
    tok2, device_id2 = _registered("exp2@example.com")
    r = _send(tok2, "P01", "第一封。")
    assert r.status_code == 201
    _reply_via_process_due(tok2)
    _shift_user_letter_created(device_id2, days_back=1)
    r = _send(tok2, "P01", "第二封，想继续聊。")
    assert r.status_code == 201, r.text
    letter2 = r.json()
    assert letter2["is_first"] is False
    assert letter2["expected_reply_at"] == (date.today() + timedelta(days=3)).isoformat()
    assert letter2["delivery_stage"] in {
        "posted", "collected", "in_transit", "out_for_delivery", "replying", "delivered",
    }
    assert letter2["delivery_stage_text"]


# ---------- read: idempotent, +1 once, unread-count moves ----------

def test_read_idempotent_and_unread_count():
    tok, _device_id = _registered("read@example.com")
    r = client.get("/api/v1/letters/unread-count", headers=_auth(tok))
    assert r.status_code == 200 and r.json()["unread_count"] == 0

    r = _send(tok, "P01", "你好，想聊聊。")
    assert r.status_code == 201
    # no reply yet: nothing unread (a user letter is not an unread reply)
    r = client.get("/api/v1/letters/unread-count", headers=_auth(tok))
    assert r.json()["unread_count"] == 0

    _reply_via_process_due(tok)
    r = client.get("/api/v1/letters/unread-count", headers=_auth(tok))
    assert r.json()["unread_count"] == 1

    reply = _thread(tok)[1]
    assert reply["direction"] == "ai"
    r = client.post(f"/api/v1/letters/{reply['id']}/read", headers=_auth(tok))
    assert r.status_code == 200, r.text
    assert r.json()["points_awarded"] == 1
    first_read_at = r.json()["user_read_at"]
    assert first_read_at is not None
    assert r.json()["read_at"] == first_read_at  # legacy alias kept in sync

    r = client.get("/api/v1/letters/unread-count", headers=_auth(tok))
    assert r.json()["unread_count"] == 0

    # repeat read: same timestamp (never overwritten), no more points
    r = client.post(f"/api/v1/letters/{reply['id']}/read", headers=_auth(tok))
    assert r.status_code == 200
    assert r.json()["points_awarded"] == 0
    assert r.json()["user_read_at"] == first_read_at
    r = client.get("/api/v1/letters/unread-count", headers=_auth(tok))
    assert r.json()["unread_count"] == 0

    # reading a user letter is rejected
    user_letter = _thread(tok)[0]
    r = client.post(f"/api/v1/letters/{user_letter['id']}/read", headers=_auth(tok))
    assert r.status_code == 400


def test_character_read_at_never_future_or_before_sent():
    tok, _device_id = _registered("charread@example.com")
    r = _send(tok, "P01", "第一封。")
    assert r.status_code == 201
    _reply_via_process_due(tok)
    user_letter = _thread(tok)[0]
    char_read = user_letter["character_read_at"]
    assert char_read is not None
    sent = datetime.fromisoformat(user_letter["created_at"])
    read = datetime.fromisoformat(char_read)
    replied = datetime.fromisoformat(user_letter["replied_at"])
    # minute-granularity: character_read_at is truncated to the minute
    assert sent.replace(second=0, microsecond=0) <= read <= replied
    assert read <= datetime.now(timezone.utc).replace(tzinfo=None)
