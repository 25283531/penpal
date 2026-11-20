"""Penpal M0 tests — run with: python -m pytest tests/ -q

Covers the M0 backend rules end to end against a TestClient with an
isolated temp DATA_DIR. No paid API is called: no LLM provider key is
set, so reply generation without a mock stays queued (never a fake
reply). LLM generation is tested with generate_reply_text mocked.
"""
import json
import os
import sqlite3
import stat
import tempfile
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="penpal-test-")
os.environ["JWT_SECRET"] = "test-secret"
for k in ("DASHSCOPE_API_KEY", "HUNYUAN_API_KEY", "SILICONFLOW_API_KEY",
          "ZHIPU_API_KEY", "GENERIC_LLM_API_KEY"):
    os.environ.pop(k, None)

from app.main import app  # noqa: E402
from app import database  # noqa: E402
from app.characters import BY_ID  # noqa: E402

database.init_db()  # TestClient without a context manager skips lifespan
client = TestClient(app)


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _new_device(device_id: str, age: int = 30) -> str:
    r = client.post("/api/v1/auth/device", json={"device_id": device_id, "age": age})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def _send(token: str, character_id: str, text: str = "你好，我是新来的笔友。"):
    return client.post(
        "/api/v1/letters",
        json={"character_id": character_id, "text": text},
        headers=_auth(token),
    )


# ---------- health / config ----------

def test_health_port_7000():
    from app.config import settings

    assert settings.PORT == 7000
    assert str(settings.DB_PATH).endswith("penpal.db")
    r = client.get("/api/v1/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["port"] == 7000
    assert body["phase1_free"] is True
    assert body["providers_configured"] == []


def test_llm_providers_four_only_no_doubao():
    tok = _new_device("prov-device-001")
    r = client.get("/api/v1/llm/providers", headers=_auth(tok))
    assert r.status_code == 200
    assert {p["id"] for p in r.json()} == {"qwen", "hunyuan", "siliconflow", "zhipu"}
    assert all(p["configured"] is False for p in r.json())
    from app.llm import _provider_config, LLMProviderError

    with pytest.raises(LLMProviderError):
        _provider_config("doubao")


# ---------- auth / age gate ----------

def test_auth_age_gate():
    # age is required at registration
    r = client.post("/api/v1/auth/device", json={"device_id": "age-missing-001"})
    assert r.status_code == 400, r.text
    # under 14 refused
    r = client.post("/api/v1/auth/device", json={"device_id": "age-13-001", "age": 13})
    assert r.status_code == 400, r.text
    assert "14" in r.json()["detail"]
    # 14-17: minor mode on
    r = client.post("/api/v1/auth/device", json={"device_id": "age-16-001", "age": 16})
    assert r.status_code == 200, r.text
    assert r.json()["minor_mode"] is True
    assert r.json()["plan"] == "free"
    # adult: minor mode off
    r = client.post("/api/v1/auth/device", json={"device_id": "age-30-001", "age": 30})
    assert r.status_code == 200
    assert r.json()["minor_mode"] is False

    r = client.get("/api/v1/characters")
    assert r.status_code == 401  # auth required


def test_membership_status_phase1_free():
    tok = _new_device("member-device-001")
    r = client.get("/api/v1/membership/status", headers=_auth(tok))
    assert r.status_code == 200
    body = r.json()
    assert body["plan"] == "free"
    assert body["phase1_free"] is True
    assert body["paywalled"] is False
    assert body["max_active_characters"] == 1
    assert body["daily_send_cap"] == 1
    assert body["reply_interval_days"] == 3
    assert body["price_member_cny"] == 9.9
    assert body["price_premium_cny"] == 19.9


# ---------- characters ----------

def test_characters_seed_p01_p05_only():
    tok = _new_device("char-device-001")
    r = client.get("/api/v1/characters", headers=_auth(tok))
    assert r.status_code == 200
    chars = r.json()
    assert [c["id"] for c in chars] == ["P01", "P02", "P03", "P04", "P05"]
    p01 = chars[0]
    assert p01["name"] == "林澈" and p01["age"] == 26
    assert p01["occupation"] == "助理建筑师"
    assert p01["relationship"] == "知己"
    assert p01["is_ai"] is True
    assert p01["ai_label"] == "AI 生成 · 虚拟人物"
    # Photo: pending asset only — no URL, never claimed generated.
    assert p01["photo_url"] is None
    assert p01["photo_status"] == "pending"
    assert all(c["unlocked"] is True for c in chars)

    # P06 is not seeded in M0
    r = client.get("/api/v1/characters/P06", headers=_auth(tok))
    assert r.status_code == 404

    # Life history is verbatim in the DB seed and in the LLM context,
    # not invented on the fly.
    db_char = database.get_character("P01")
    assert db_char["life_history"] == BY_ID["P01"]["life_history"]
    assert "河南洛阳" in db_char["life_history"]
    assert "25 岁那年父亲生了一场病" in db_char["life_history"]
    from app.context import build_reply_context

    ctx = build_reply_context("char-device-001", "P01")
    assert "河南洛阳" in ctx
    assert "25 岁那年父亲生了一场病" in ctx


# ---------- letters: send, turn-taking, daily cap, 2000-char limit ----------

def test_send_letter_first_letter_same_day():
    tok = _new_device("send-device-001")
    r = _send(tok, "P01", "你好，林澈，我最近在想要不要换工作。")
    assert r.status_code == 201, r.text
    letter = r.json()
    assert letter["direction"] == "user"
    assert letter["status"] == "in_transit"
    assert letter["is_first"] is True
    assert letter["reply_due_at"] == date.today().isoformat()  # first letter: same day
    assert letter["ai_generated"] is False

    # points: login +1 (registration) + write +1
    r = client.get("/api/v1/points", headers=_auth(tok))
    assert r.json()["points"] == 2

    # turn-taking: a second letter to P01 while one is outstanding -> 409
    r = _send(tok, "P01", "再写一封。")
    assert r.status_code == 409, r.text

    # daily cap: even to a DIFFERENT character, after 1 send today -> 429
    r = _send(tok, "P02", "你好，沈知遥。")
    assert r.status_code == 429, r.text


def test_letter_2000_char_limit():
    tok = _new_device("limit-device-001")
    r = _send(tok, "P01", "字" * 2001)
    assert r.status_code == 400, r.text
    r = _send(tok, "P01", "字" * 2000)
    assert r.status_code == 201, r.text
    assert len(r.json()["text"]) == 2000


def test_premium_can_send_to_more_characters_same_day():
    tok = _new_device("premium-device-001")
    database.set_device_plan("premium-device-001", "premium")
    for cid in ("P01", "P02"):
        r = _send(tok, cid, f"你好，{cid}，我是新笔友。")
        assert r.status_code == 201, r.text
    # free tier would have been capped at 1; premium cap is 5
    r = client.get("/api/v1/membership/status", headers=_auth(tok))
    assert r.json()["daily_send_cap"] == 5
    assert r.json()["max_active_characters"] == 5


def test_second_character_blocked_while_one_active_free():
    tok = _new_device("slot-device-001")
    r = _send(tok, "P01", "你好。")
    assert r.status_code == 201
    # The daily cap (1) already blocks a second send today; to test the
    # slot rule itself, end P01 and try P02 tomorrow's cap via DB date
    # manipulation is covered by the cap test — here check the slot
    # error path directly at the database layer:
    with pytest.raises(ValueError):
        database.start_relationship("slot-device-001", "P02", max_active=1)


# ---------- reply scheduling: first same day, then free 3 days ----------

def test_reply_schedule_first_same_day_then_free_3_days():
    tok = _new_device("sched-device-001")
    r = _send(tok, "P01", "你好，这是我的第一封信。")
    first_id = r.json()["id"]

    fake_reply = "我是林澈，谢谢你的来信。你说的换工作，我想先陪你把这件事拆开看看。"
    with patch("app.replies.generate_reply_text", return_value=fake_reply):
        r = client.post("/api/v1/letters/process-due", json={}, headers=_auth(tok))
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["replied"] == 1
        assert body["details"][0]["status"] == "replied"

    # the reply is stored, labelled AI, and the user letter is replied
    r = client.get("/api/v1/letters?character_id=P01", headers=_auth(tok))
    thread = r.json()
    assert len(thread) == 2
    reply = thread[1]
    assert reply["direction"] == "ai"
    assert reply["text"] == fake_reply
    assert reply["ai_generated"] is True
    assert reply["ai_label"] == "AI 生成"
    assert thread[0]["status"] == "replied"

    # read the reply: +1 point, once only
    r = client.post(f"/api/v1/letters/{reply['id']}/read", headers=_auth(tok))
    assert r.status_code == 200 and r.json()["points_awarded"] == 1
    r = client.post(f"/api/v1/letters/{reply['id']}/read", headers=_auth(tok))
    assert r.json()["points_awarded"] == 0

    # second letter: NOT due the same day (free = +3 days).
    # Use a fresh device for the 3-day check to avoid the daily cap:
    tok2 = _new_device("sched-device-002")
    r = _send(tok2, "P01", "第一封。")
    assert r.status_code == 201
    with patch("app.replies.generate_reply_text", return_value=fake_reply):
        r = client.post("/api/v1/letters/process-due", json={}, headers=_auth(tok2))
        assert r.json()["replied"] == 1
    # second user letter needs a new day: shift its created date back 1 day in DB
    conn = sqlite3.connect(str(database.settings.DB_PATH))
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    conn.execute(
        "UPDATE letters SET created_at = ? WHERE device_id = ? AND direction = 'user'"
        " AND id = (SELECT MAX(id) FROM letters WHERE device_id = ? AND direction = 'user')",
        (yesterday + "T00:00:00", "sched-device-002", "sched-device-002"),
    )
    conn.commit()
    conn.close()
    r = _send(tok2, "P01", "第二封，想继续聊。")
    assert r.status_code == 201, r.text
    assert r.json()["is_first"] is False
    assert r.json()["reply_due_at"] == (date.today() + timedelta(days=3)).isoformat()
    with patch("app.replies.generate_reply_text", return_value=fake_reply):
        r = client.post("/api/v1/letters/process-due", json={}, headers=_auth(tok2))
        assert r.json()["replied"] == 0  # not due yet
        r = client.post(
            "/api/v1/letters/process-due",
            json={"date": (date.today() + timedelta(days=3)).isoformat()},
            headers=_auth(tok2),
        )
        assert r.json()["replied"] == 1  # due on day +3


def test_process_due_without_llm_queues_never_fakes():
    tok = _new_device("nollm-device-001")
    r = _send(tok, "P01", "你好，没有 LLM 的时候会怎样？")
    assert r.status_code == 201
    r = client.post("/api/v1/letters/process-due", json={}, headers=_auth(tok))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["replied"] == 0
    assert body["llm_unavailable"] is True
    assert body["details"][0]["status"] == "queued_no_llm"
    # letter is still in transit — no fake reply was stored
    r = client.get("/api/v1/letters?character_id=P01", headers=_auth(tok))
    assert len(r.json()) == 1
    assert r.json()[0]["status"] == "in_transit"


def test_member_reply_interval_is_1_day():
    from app.membership import reply_due_date

    today = date.today()
    assert reply_due_date(today, "free", True) == today
    assert reply_due_date(today, "free", False) == today + timedelta(days=3)
    assert reply_due_date(today, "member", False) == today + timedelta(days=1)
    assert reply_due_date(today, "premium", False) == today + timedelta(days=1)


# ---------- memory isolation per character ----------

def test_memory_isolation_between_characters():
    device_id = "isolation-device-001"
    _new_device(device_id)
    database.create_memory(device_id, "P01", "note", "ISOLATION-A-7f1c-只属于林澈的记忆", importance=0.9)
    database.create_memory(device_id, "P02", "note", "ISOLATION-B-3d8a-只属于沈知遥的记忆", importance=0.9)
    from app.context import build_reply_context

    ctx1 = build_reply_context(device_id, "P01")
    assert "ISOLATION-A-7f1c" in ctx1
    assert "ISOLATION-B-3d8a" not in ctx1
    ctx2 = build_reply_context(device_id, "P02")
    assert "ISOLATION-B-3d8a" in ctx2
    assert "ISOLATION-A-7f1c" not in ctx2


def test_persona_stages_by_letter_count():
    from app import evolution

    assert evolution.stage_for(0) == "初识"
    assert evolution.stage_for(1) == "初识"
    assert evolution.stage_for(2) == "初识"
    assert evolution.stage_for(3) == "熟悉"
    assert evolution.stage_for(6) == "熟悉"
    assert evolution.stage_for(7) == "默契"
    assert evolution.stage_for(14) == "默契"
    assert evolution.stage_for(15) == "知己"
    assert evolution.stage_for(100) == "知己"

    device_id = "stage-device-001"
    database.get_or_create_device(device_id, age=30)
    p = database.get_persona(device_id, "P01")
    assert p["relationship_stage"] == "初识" and p["interaction_count"] == 0
    for _ in range(3):
        evolution.record_interaction(device_id, "P01", event="letter")
    p = database.get_persona(device_id, "P01")
    assert p["interaction_count"] == 3 and p["relationship_stage"] == "熟悉"


def test_fading_marks_old_unrecalled_memory_faded():
    from app import evolution
    from app.crypto import encrypt_text

    device_id = "fade-device-001"
    database.get_or_create_device(device_id, age=30)
    old = (date.today() - timedelta(days=70)).isoformat()
    conn = sqlite3.connect(str(database.settings.DB_PATH))
    conn.execute(
        "INSERT INTO memories (device_id, character_id, kind, text, importance, emotion,"
        " recall_count, last_recalled_at, faded, created_at, updated_at)"
        " VALUES (?, 'P01', 'note', ?, 0.12, NULL, 0, NULL, 0, ?, ?)",
        (device_id, encrypt_text("FADE-MARKER-4c1d-旧记忆"),
         old + "T00:00:00+00:00", old + "T00:00:00+00:00"),
    )
    conn.commit()
    conn.close()
    result = evolution.apply_fading(device_id, "P01")
    assert result["faded"] == 1
    assert not any("FADE-MARKER-4c1d" in m["text"]
                   for m in database.list_memories(device_id, "P01"))
    assert any("FADE-MARKER-4c1d" in m["text"]
               for m in database.list_memories(device_id, "P01", include_faded=True))


# ---------- points / unlocks / referrals ----------

def test_points_login_once_per_day_and_thresholds():
    tok = _new_device("points-device-001")
    assert database.points_balance("points-device-001") == 1  # login on registration
    r = client.post("/api/v1/auth/login", headers=_auth(tok))
    assert r.json()["points_awarded"] == 0  # already logged in today
    assert database.points_unlocks(0) == 0
    assert database.points_unlocks(99) == 0
    assert database.points_unlocks(100) == 1
    assert database.points_unlocks(299) == 1
    assert database.points_unlocks(300) == 2
    assert database.referral_unlocks(0) == 0
    assert database.referral_unlocks(1) == 1
    assert database.referral_unlocks(9) == 1
    assert database.referral_unlocks(10) == 2
    assert database.referral_unlocks(29) == 2
    assert database.referral_unlocks(30) == 3
    assert database.referral_unlocks(40) == 4
    assert database.referral_unlocks(50) == 5
    assert database.referral_unlocks(999) == 5  # capped at 5


def test_referral_counter_and_success_on_first_letter():
    inviter = _new_device("referrer-device-001")
    referred = _new_device("referred-device-001")
    r = client.post("/api/v1/referrals",
                    json={"referred_device_id": "referred-device-001"},
                    headers=_auth(inviter))
    assert r.status_code == 201, r.text
    assert database.referral_count("referrer-device-001") == 0  # not yet successful
    r = _send(referred, "P01", "我是被邀请来的。")
    assert r.status_code == 201
    assert database.referral_count("referrer-device-001") == 1
    with pytest.raises(ValueError):
        database.record_referral("referrer-device-001", "referrer-device-001")


def test_unlocks_entitlement_counts():
    device_id = "unlock-device-001"
    _new_device(device_id)
    # 100 points -> entitled to P06 (first in UNLOCK_ORDER); P06 is not
    # seeded in M0, so no row is granted yet — but the entitlement is computed.
    for i in range(100):
        database.award_point(device_id, "write", ref_id=f"w{i}")
    assert database.points_balance(device_id) >= 100
    entitled = database.evaluate_unlocks(device_id)
    assert entitled == ["P06"]
    r = client.get("/api/v1/unlocks", headers=_auth(_new_device("unlock-device-002")))
    assert r.json()["thresholds"] == {"points": [100, 300], "referrals": [1, 10, 30, 40, 50]}


# ---------- ending / reconnect / retention ----------

def test_end_reconnect_and_30_day_window():
    tok = _new_device("end-device-001")
    r = _send(tok, "P01", "你好。")
    assert r.status_code == 201
    r = client.post("/api/v1/relationships/P01/end", headers=_auth(tok))
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "ended"
    assert r.json()["reconnect_until"] == (date.today() + timedelta(days=30)).isoformat()
    # still listed inside the window
    r = client.get("/api/v1/relationships", headers=_auth(tok))
    assert any(x["character_id"] == "P01" and x["status"] == "ended" for x in r.json())
    # reconnect works inside the window, letters intact
    r = client.post("/api/v1/relationships/P01/reconnect", headers=_auth(tok))
    assert r.status_code == 200 and r.json()["status"] == "active"
    r = client.get("/api/v1/letters?character_id=P01", headers=_auth(tok))
    assert len(r.json()) == 1

    # simulate the window passing: relationship list hides it, thread is 410,
    # but the encrypted server data is RETAINED (soft delete only).
    database.end_relationship("end-device-001", "P01")
    conn = sqlite3.connect(str(database.settings.DB_PATH))
    past = (date.today() - timedelta(days=1)).isoformat()
    conn.execute(
        "UPDATE relationships SET reconnect_until = ? WHERE device_id = ? AND character_id = 'P01'",
        (past, "end-device-001"),
    )
    conn.commit()
    conn.close()
    r = client.get("/api/v1/relationships", headers=_auth(tok))
    assert not any(x["character_id"] == "P01" for x in r.json())
    r = client.get("/api/v1/letters?character_id=P01", headers=_auth(tok))
    assert r.status_code == 410
    r = client.post("/api/v1/relationships/P01/reconnect", headers=_auth(tok))
    assert r.status_code == 410
    # server-side retention: the letter row is still in the DB
    assert len(database.list_thread("end-device-001", "P01")) == 1


# ---------- encryption + admin privacy ----------

def test_encryption_at_rest():
    tok = _new_device("encrypt-device-001")
    marker = "ENCRYPT-MARKER-5b7e-信件内容"
    r = _send(tok, "P01", marker)
    assert r.status_code == 201
    conn = sqlite3.connect(str(database.settings.DB_PATH))
    rows = conn.execute("SELECT text FROM letters").fetchall()
    for (raw,) in rows:
        assert "ENCRYPT-MARKER" not in raw, "plaintext leaked in letters"
    conn.close()
    r = client.get("/api/v1/letters", headers=_auth(tok))
    assert marker in r.json()[0]["text"]
    key_path = Path(database.settings.DATA_DIR) / ".encryption.key"
    assert key_path.exists()
    assert stat.S_IMODE(key_path.stat().st_mode) == 0o600


ADMIN_PASSWORD = "test-admin-123"


def test_admin_auth_and_never_returns_user_text():
    c = TestClient(app)
    r = c.get("/api/v1/admin/status")
    assert r.status_code == 200
    assert r.json()["password_set"] is False
    r = c.get("/api/v1/admin/dashboard")
    assert r.status_code == 401
    r = c.post("/api/v1/admin/setup", json={"password": ADMIN_PASSWORD})
    assert r.status_code == 200, r.text
    r = c.post("/api/v1/admin/setup", json={"password": "another-one"})
    assert r.status_code == 400
    r = c.get("/api/v1/admin/dashboard")
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"devices", "letters", "user_letters", "replies",
                         "active_relationships", "dau_today", "characters", "violations"}
    # user text never leaks through any admin endpoint
    tok = _new_device("privacy-device-001")
    marker = "PRIVACY-LETTER-88bb-信件原文"
    _send(tok, "P01", marker)
    for path in ("/api/v1/admin/dashboard", "/api/v1/admin/settings",
                 "/api/v1/admin/messages", "/api/v1/admin/activities"):
        r = c.get(path)
        assert r.status_code == 200, path
        blob = json.dumps(r.json(), ensure_ascii=False)
        assert marker not in blob, f"user text leaked in {path}"
    # settings: LLM provider validation, secrets masked
    r = c.post("/api/v1/admin/settings", json={"settings": {"llm.default_provider": "doubao"}})
    assert r.status_code == 400
    r = c.post("/api/v1/admin/settings", json={"settings": {"dashscope.api_key": "sk-test-123"}})
    assert r.status_code == 200 and r.json()["dashscope.api_key"] == "********"
    assert database.get_setting("dashscope.api_key") == "sk-test-123"
    r = c.post("/api/v1/admin/settings", json={"settings": {"dashscope.api_key": ""}})
    assert database.get_setting("dashscope.api_key") == ""
    # logout clears the session
    r = c.post("/api/v1/admin/logout")
    assert r.status_code == 200
    assert c.get("/api/v1/admin/dashboard").status_code == 401


def test_content_filter_blocks_partner_framing():
    from app.content_filter import validate_reply

    ok, problems = validate_reply("我是林澈，你好。最近工作还顺利吗？我想听听你的事。")
    assert ok, problems
    ok, problems = validate_reply("我是你的恋人，做我女朋友吧，我会一直陪着你。")
    assert not ok
    assert any("恋人" in p or "伴侣" in p or "romantic" in p for p in problems)
    ok, problems = validate_reply("字" * 2001)
    assert not ok
