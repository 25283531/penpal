"""Reply scheduler tests (Bug 1 fix) — run with: python -m pytest tests/ -q

Covers the automatic pass (replies.process_all_due_replies) and the
in-process thread driver (app.scheduler): every device's due letters,
backlog/overdue letters, no-LLM queueing (never a fake reply), LLM
failure retried on the next pass, per-device failures not blocking
other devices, aggregate stats recording, and the end-to-end proof
that a letter gets a reply with no manual process-due call once the
app lifespan starts the scheduler.
"""
import os
import sqlite3
import tempfile
import time
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="penpal-test-scheduler-")
os.environ["JWT_SECRET"] = "test-secret"
for k in ("DASHSCOPE_API_KEY", "HUNYUAN_API_KEY", "SILICONFLOW_API_KEY",
          "ZHIPU_API_KEY", "GENERIC_LLM_API_KEY"):
    os.environ.pop(k, None)

from app.main import app  # noqa: E402
from app import database, scheduler  # noqa: E402
from app.llm import LLMError  # noqa: E402
from app.replies import process_all_due_replies  # noqa: E402

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
        # Registration requires a birth date (18+ gate).
        "birth_date": "1996-06-15",
        "display_name": "阿辉",
        "captcha_token": token, "captcha_text": code,
    })
    assert r.status_code == 200, r.text
    body = r.json()
    return body["token"], body["device_id"]


def _send(token: str, character_id: str = "P01", text: str = "你好，我是新来的笔友。"):
    return client.post(
        "/api/v1/letters",
        json={"character_id": character_id, "text": text},
        headers=_auth(token),
    )


def _thread(token: str, character_id: str = "P01"):
    r = client.get(f"/api/v1/letters?character_id={character_id}", headers=_auth(token))
    assert r.status_code == 200, r.text
    return r.json()


def test_process_all_due_replies_two_devices():
    tok1, _d1 = _registered("sched-all-1@example.com")
    tok2, _d2 = _registered("sched-all-2@example.com")
    assert _send(tok1).status_code == 201
    assert _send(tok2).status_code == 201
    with patch("app.replies.generate_reply_text", return_value=FAKE_REPLY):
        result = process_all_due_replies()
    # NOTE: pytest runs all test files against one shared DB, so other
    # files may have left due letters behind — assert on my two devices
    # (per-device details) and lower bounds on the totals, not exact
    # totals.
    by_device = {d["device_id"]: d for d in result["details"]}
    assert by_device[_d1]["replied"] == 1
    assert by_device[_d2]["replied"] == 1
    assert result["devices"] >= 2
    assert result["processed"] >= 2
    assert result["replied"] >= 2
    assert result["queued"] == 0
    assert result["failed"] == 0
    assert result["error_counts"] == {}
    assert len(_thread(tok1)) == 2
    assert len(_thread(tok2)) == 2


def test_process_all_due_no_llm_queues_never_fakes_then_retries():
    tok, device_id = _registered("sched-nollm@example.com")
    assert _send(tok).status_code == 201
    # No LLM key in tests: the pass queues, never fakes a reply.
    # (Totals are lower bounds — other test files may share this DB
    # and leave due letters behind; assert on this device's detail.)
    result = process_all_due_replies()
    mine = {d["device_id"]: d for d in result["details"]}[device_id]
    assert mine["processed"] == 1
    assert mine["replied"] == 0
    assert mine["queued"] == 1
    assert result["replied"] == 0
    assert result["queued"] >= 1
    assert result["llm_unavailable"] is True
    assert result["error_counts"].get("llm_not_configured", 0) >= 1
    assert len(_thread(tok)) == 1
    assert _thread(tok)[0]["status"] == "in_transit"
    # Same letter, next pass, LLM now available: retried and replied.
    with patch("app.replies.generate_reply_text", return_value=FAKE_REPLY):
        result = process_all_due_replies()
    mine = {d["device_id"]: d for d in result["details"]}[device_id]
    assert mine["replied"] == 1
    assert _thread(tok)[1]["direction"] == "ai"
    assert _thread(tok)[1]["text"] == FAKE_REPLY


def test_process_all_due_llm_failure_retried_next_pass():
    tok, device_id = _registered("sched-fail@example.com")
    assert _send(tok).status_code == 201
    with patch("app.replies.generate_reply_text", side_effect=LLMError("boom")):
        result = process_all_due_replies()
    mine = {d["device_id"]: d for d in result["details"]}[device_id]
    assert mine["processed"] == 1
    assert mine["replied"] == 0
    assert mine["failed"] == 1
    assert result["error_counts"].get("reply_generation_failed", 0) >= 1
    assert _thread(tok)[0]["status"] == "in_transit"  # not dropped
    with patch("app.replies.generate_reply_text", return_value=FAKE_REPLY):
        result = process_all_due_replies()
    mine = {d["device_id"]: d for d in result["details"]}[device_id]
    assert mine["replied"] == 1
    assert len(_thread(tok)) == 2


def test_process_all_due_backlog_overdue_letter():
    tok, device_id = _registered("sched-backlog@example.com")
    assert _send(tok).status_code == 201
    # Simulate a letter that has been waiting 3 days (backlog from
    # before the scheduler existed): push its due date into the past.
    past = (date.today() - timedelta(days=3)).isoformat()
    conn = sqlite3.connect(str(database.settings.DB_PATH))
    conn.execute(
        "UPDATE letters SET reply_due_at = ? WHERE device_id = ? AND direction = 'user'",
        (past, device_id),
    )
    conn.commit()
    conn.close()
    with patch("app.replies.generate_reply_text", return_value=FAKE_REPLY):
        result = process_all_due_replies()
    mine = {d["device_id"]: d for d in result["details"]}[device_id]
    assert mine["replied"] == 1
    assert len(_thread(tok)) == 2


def test_process_all_due_injectable_process_fn_and_device_failure_isolated():
    def fake_fn(device_id: str, day: str):
        if device_id == "bad-device":
            raise RuntimeError("device exploded")
        return {"processed": 1, "replied": 1, "queued": 0, "failed": 0,
                "llm_unavailable": False, "details": []}

    with patch("app.replies.database.devices_with_due_letters",
               return_value=["bad-device", "good-device"]):
        result = process_all_due_replies(process_fn=fake_fn)
    assert result["devices"] == 2
    assert result["replied"] == 1
    assert result["failed"] == 1
    assert result["error_counts"] == {"scheduler_device_failed": 1}
    assert result["details"][0]["code"] == "scheduler_device_failed"
    assert result["details"][1]["replied"] == 1


def test_run_scheduled_pass_records_aggregate_stats():
    tok, _device_id = _registered("sched-stats@example.com")
    assert _send(tok).status_code == 201
    before = database.scheduler_summary()["runs"]
    with patch("app.replies.generate_reply_text", return_value=FAKE_REPLY):
        result = scheduler.run_scheduled_pass()
    assert result["replied"] >= 1
    assert result["run_id"] > 0
    runs = database.list_scheduler_runs(limit=5)
    assert runs[0]["id"] == result["run_id"]
    assert runs[0]["replied"] >= 1
    assert runs[0]["processed"] >= 1
    # Aggregates only: a persisted run carries no device id / letter text.
    assert set(runs[0]) == {"id", "started_at", "finished_at", "day", "devices",
                            "processed", "replied", "queued", "failed",
                            "llm_unavailable", "error_counts", "error"}
    summary = database.scheduler_summary()
    assert summary["runs"] == before + 1
    assert summary["replied"] >= 1
    assert summary["last_run"]["id"] == result["run_id"]
    # Dashboard aggregates include the scheduler (no letter text, no device list).
    stats = database.dashboard_stats()
    assert stats["scheduler"]["runs"] == summary["runs"]
    assert stats["scheduler"]["replied"] == summary["replied"]


def test_scheduler_thread_auto_replies_without_manual_trigger(monkeypatch):
    """End-to-end Bug 1 proof: start the app (lifespan starts the
    scheduler), write a letter, never call process-due — the reply
    still arrives, generated by a scheduled pass."""
    monkeypatch.setenv("PENPAL_REPLY_INTERVAL_SECONDS", "1")
    try:
        with patch("app.replies.generate_reply_text", return_value=FAKE_REPLY):
            with TestClient(app) as live:
                assert scheduler._scheduler is not None
                assert scheduler._scheduler.running is True
                tok, _device_id = _registered("sched-thread@example.com")
                assert _send(tok).status_code == 201
                deadline = time.time() + 10
                thread = []
                while time.time() < deadline:
                    r = live.get("/api/v1/letters?character_id=P01", headers=_auth(tok))
                    thread = r.json()
                    if len(thread) == 2 and thread[1]["direction"] == "ai":
                        break
                    time.sleep(0.2)
                assert len(thread) == 2, thread
                assert thread[1]["text"] == FAKE_REPLY
                assert thread[0]["status"] == "replied"
                # Health reports the scheduler; at least one pass ran.
                health = live.get("/api/v1/health").json()
                assert health["reply_scheduler"]["running"] is True
                assert health["reply_scheduler"]["runs"] >= 1
    finally:
        scheduler.stop_scheduler()
