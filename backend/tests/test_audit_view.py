"""Penpal audit-view tests — privacy text, audited letter view, audit log, CLI.

Run with: python -m pytest tests/ -q
"""
import hashlib
import json
import os
import sqlite3
import tempfile
from pathlib import Path

os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="penpal-audit-test-")
os.environ["JWT_SECRET"] = "test-secret"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import admin, audit_view, crypto, database, email_auth  # noqa: E402
from app.main import app  # noqa: E402

database.init_db()
client = TestClient(app)

ADMIN_PASSWORD = "audit-admin-pass-9"

MARKER = "AUDIT-LETTER-77cc-信件原文"


@pytest.fixture(autouse=True)
def _admin_password():
    """Set the admin password for each test, then clear it again.

    All test modules in this run share one test database (DATA_DIR is
    fixed by the first imported module), so a password left behind here
    would break test_penpal's expectation of a fresh admin setup.
    """
    database.set_setting("admin.password_hash", admin.hash_password(ADMIN_PASSWORD))
    yield
    database.set_setting("admin.password_hash", "")
    with database.connect() as conn:
        conn.execute("DELETE FROM admin_sessions")


def _login() -> TestClient:
    c = TestClient(app)
    r = c.post("/api/v1/admin/login", json={"password": ADMIN_PASSWORD})
    assert r.status_code == 200, r.text
    return c


def _seed_letter(text: str = MARKER, character_id: str = "P01") -> dict:
    return database.create_user_letter(
        "dev-audit-001", character_id, text, "2026-11-22", False,
    )


def _audit_rows() -> list[dict]:
    return database.list_audit_logs(limit=500)


def _test_key() -> str:
    """The test database's decryption key value (read from the key
    file). Tests may use it because it is a throwaway test key; the
    value is never asserted into any response or audit row."""
    return crypto.key_path().read_text(encoding="utf-8").strip()


def _wrong_key() -> str:
    from cryptography.fernet import Fernet
    return Fernet.generate_key().decode("ascii")


# ---------- privacy text ----------

def test_privacy_text_covers_audit_points():
    text = email_auth.PRIVACY_TEXT
    assert email_auth.PRIVACY_UPDATED_AT == "2026-11-22"
    assert len(text) <= 600, f"privacy text too long: {len(text)} chars"
    # purpose of collecting letter content
    assert "慢信服务" in text
    assert "公检法" in text and "依法" in text
    # admin cannot see content day-to-day; views need the key file + audit
    assert "管理员日常看不到任何信件内容" in text
    assert "只能看到汇总数字" in text
    assert "解密密钥" in text
    assert "审计日志" in text
    assert "无法跳过" in text
    assert "审计日志本身不记录信件内容" in text
    # retained clauses
    assert "服务端仍加密留存，仅依法留存" in text
    assert "彻底删除" not in text
    assert "未成年人" in text and "2 小时" in text
    # date of birth: collected only to check 18+, no real-name verification
    assert "出生日期" in text and "年满 18 周岁" in text
    assert "实名认证" in text
    assert "出生日期加密保存，不会在任何界面原样展示" in text
    assert "虚假年龄" in text and "承担法律责任" in text
    assert "AI 生成" in text and "2000" in text
    # App offline fallback text is the same text as the backend
    app_path = (
        Path(__file__).resolve().parent.parent.parent
        / "app" / "app" / "src" / "main" / "res" / "raw" / "privacy_policy.txt"
    )
    assert app_path.read_text(encoding="utf-8").strip() == text.strip()


# ---------- auth gating ----------

def test_audit_endpoints_require_admin_login():
    anon = TestClient(app)
    assert anon.get("/api/v1/admin/letters").status_code == 401
    assert anon.get("/api/v1/admin/letters/1").status_code == 401
    assert anon.post("/api/v1/admin/letters/1/view",
                     json={"reason": "执法检查"}).status_code == 401
    assert anon.get("/api/v1/admin/audit-log").status_code == 401
    assert anon.get("/api/v1/admin/key-status").status_code == 401


# ---------- letter list never shows content ----------

def test_letter_list_metadata_only():
    letter = _seed_letter()
    r = _login().get("/api/v1/admin/letters")
    assert r.status_code == 200, r.text
    blob = json.dumps(r.json(), ensure_ascii=False)
    assert MARKER not in blob
    row = [x for x in r.json() if x["id"] == letter["id"]]
    assert len(row) == 1
    assert "text" not in row[0] and "device_id" not in row[0]
    assert row[0]["device_digest"] and len(row[0]["device_digest"]) == 12
    # filter by character
    r = _login().get("/api/v1/admin/letters", params={"character_id": "P02"})
    assert all(x["character_id"] == "P02" for x in r.json())
    assert not any(x["id"] == letter["id"] for x in r.json())


# ---------- view: reason required ----------

def test_view_without_reason_is_refused_and_not_audited():
    letter = _seed_letter()
    before = len(_audit_rows())
    r = _login().post(f"/api/v1/admin/letters/{letter['id']}/view", json={})
    assert r.status_code == 422  # missing required field
    r = _login().post(f"/api/v1/admin/letters/{letter['id']}/view",
                          json={"reason": "随便看看"})
    assert r.status_code == 400, r.text
    assert r.json()["detail"] == "audit_reason_required" or "原因" in str(r.json())
    assert MARKER not in r.text
    assert len(_audit_rows()) == before  # refused views write no audit row


# ---------- view: success writes audit ----------

def test_view_success_writes_audit_log_without_content():
    letter = _seed_letter()
    r = _login().post(
        f"/api/v1/admin/letters/{letter['id']}/view",
        json={"reason": "执法检查", "note": "配合检查",
              "decryption_key": _test_key()},
    )
    assert r.status_code == 200, r.text
    assert r.json()["text"] == MARKER
    assert r.json()["audit_id"]
    # the key itself is never echoed back in the response
    assert _test_key() not in json.dumps(r.json(), ensure_ascii=False)
    rows = database.list_audit_logs(letter_id=letter["id"])
    assert len(rows) == 1
    row = rows[0]
    assert row["action"] == "letter_view"
    assert row["reason"] == "执法检查"
    assert row["result"] == "ok"
    assert row["operator"].startswith("admin:")
    assert row["letter_id"] == letter["id"]
    # the audit log itself never contains letter content or the key
    blob = json.dumps(rows, ensure_ascii=False)
    assert MARKER not in blob
    assert _test_key() not in blob
    # filter by letter id on the API too
    r = _login().get("/api/v1/admin/audit-log",
                         params={"letter_id": letter["id"]})
    assert r.status_code == 200
    assert len(r.json()) == 1
    assert MARKER not in json.dumps(r.json(), ensure_ascii=False)


# ---------- view: key is required, and must match ----------

def test_view_without_key_is_refused_and_audited_key_missing():
    letter = _seed_letter()
    before = len(_audit_rows())
    r = _login().post(
        f"/api/v1/admin/letters/{letter['id']}/view",
        json={"reason": "执法检查"},
    )
    assert r.status_code == 400, r.text
    assert r.json()["code"] == "decryption_key_required"
    assert MARKER not in r.text
    assert _test_key() not in r.text
    rows = database.list_audit_logs(letter_id=letter["id"])
    assert len(rows) == 1
    assert rows[0]["action"] == "letter_view_failed"
    assert rows[0]["result"] == "key_missing"
    assert MARKER not in json.dumps(rows, ensure_ascii=False)
    assert _test_key() not in json.dumps(rows, ensure_ascii=False)
    assert len(_audit_rows()) == before + 1


def test_view_wrong_key_is_refused_and_audited_key_mismatch():
    letter = _seed_letter()
    r = _login().post(
        f"/api/v1/admin/letters/{letter['id']}/view",
        json={"reason": "故障排查", "decryption_key": _wrong_key()},
    )
    assert r.status_code == 403, r.text
    assert r.json()["code"] == "decryption_key_mismatch"
    assert MARKER not in r.text
    rows = database.list_audit_logs(letter_id=letter["id"])
    assert len(rows) == 1
    assert rows[0]["action"] == "letter_view_failed"
    assert rows[0]["result"] == "key_mismatch"
    assert MARKER not in json.dumps(rows, ensure_ascii=False)
    assert _wrong_key() not in json.dumps(rows, ensure_ascii=False)


def test_view_malformed_key_is_refused_as_mismatch():
    letter = _seed_letter()
    r = _login().post(
        f"/api/v1/admin/letters/{letter['id']}/view",
        json={"reason": "故障排查", "decryption_key": "not-a-fernet-key"},
    )
    assert r.status_code == 403, r.text
    assert MARKER not in r.text
    rows = database.list_audit_logs(letter_id=letter["id"])
    assert len(rows) == 1 and rows[0]["result"] == "key_mismatch"


# ---------- view: reason "其他" requires a note ----------

def test_view_other_reason_without_note_is_refused_400_no_audit():
    letter = _seed_letter()
    before = len(_audit_rows())
    for note in (None, "", "   "):
        body = {"reason": "其他", "decryption_key": _test_key()}
        if note is not None:
            body["note"] = note
        r = _login().post(f"/api/v1/admin/letters/{letter['id']}/view",
                          json=body)
        assert r.status_code == 400, r.text
        assert r.json()["code"] == "audit_note_required_for_other"
        assert MARKER not in r.text
    assert len(_audit_rows()) == before  # refused views write no audit row


def test_view_other_reason_with_note_and_key_succeeds():
    letter = _seed_letter()
    r = _login().post(
        f"/api/v1/admin/letters/{letter['id']}/view",
        json={"reason": "其他", "note": "用户电话里要求核查",
              "decryption_key": _test_key()},
    )
    assert r.status_code == 200, r.text
    assert r.json()["text"] == MARKER
    rows = database.list_audit_logs(letter_id=letter["id"])
    assert len(rows) == 1 and rows[0]["result"] == "ok"
    assert rows[0]["note"] == "用户电话里要求核查"


# ---------- view: missing letter + decrypt failure are audited ----------

def test_view_missing_letter_is_404_and_audited():
    r = _login().post("/api/v1/admin/letters/999999/view",
                          json={"reason": "故障排查"})
    assert r.status_code == 404
    rows = database.list_audit_logs(letter_id=999999)
    assert len(rows) == 1 and rows[0]["result"] == "not_found"


def test_view_decrypt_failure_is_audited_and_returns_no_content():
    letter = _seed_letter("AUDIT-CORRUPT-11aa-原文")
    conn = sqlite3.connect(str(database.settings.DB_PATH))
    conn.execute("UPDATE letters SET text = 'not-a-fernet-token' WHERE id = ?",
                 (letter["id"],))
    conn.commit()
    conn.close()
    r = _login().post(
        f"/api/v1/admin/letters/{letter['id']}/view",
        json={"reason": "故障排查", "decryption_key": _test_key()},
    )
    assert r.status_code == 502, r.text
    assert "AUDIT-CORRUPT" not in r.text
    rows = database.list_audit_logs(letter_id=letter["id"])
    assert len(rows) == 1
    assert rows[0]["action"] == "letter_view_failed"
    assert rows[0]["result"] == "decrypt_failed"
    assert "AUDIT-CORRUPT" not in json.dumps(rows, ensure_ascii=False)


# ---------- audit log: append-only ----------

def test_audit_log_has_no_delete():
    assert not hasattr(database, "delete_audit_log")
    r = _login().delete("/api/v1/admin/audit-log")
    assert r.status_code in (404, 405)


# ---------- key status ----------

def test_key_status_shows_fingerprint_not_key():
    r = _login().get("/api/v1/admin/key-status")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["exists"] is True
    assert str(body["path"]).endswith(".encryption.key")
    key_bytes = crypto.key_path().read_bytes()
    assert body["fingerprint_sha256_12"] == hashlib.sha256(key_bytes).hexdigest()[:12]
    assert len(body["fingerprint_sha256_12"]) == 12
    assert "单独备份" in body["backup_reminder"]
    blob = json.dumps(body, ensure_ascii=False)
    assert key_bytes.decode("ascii") not in blob


# ---------- CLI ----------

def test_cli_view_writes_same_audit_log(monkeypatch, capsys):
    letter = _seed_letter("AUDIT-CLI-55dd-原文")
    monkeypatch.setenv("PENPAL_ADMIN_PASSWORD", ADMIN_PASSWORD)
    rc = audit_view.main(["--letter-id", str(letter["id"]),
                          "--reason", "用户申诉", "--operator", "tester",
                          "--decryption-key", _test_key()])
    assert rc == 0
    out = capsys.readouterr().out
    assert "AUDIT-CLI-55dd-原文" in out
    assert _test_key() not in out
    rows = database.list_audit_logs(letter_id=letter["id"])
    assert len(rows) == 1
    assert rows[0]["action"] == "letter_view"
    assert rows[0]["operator"] == "cli:tester"
    assert rows[0]["reason"] == "用户申诉"
    assert _test_key() not in json.dumps(rows, ensure_ascii=False)


def test_cli_key_file_view_succeeds(monkeypatch, capsys):
    letter = _seed_letter("AUDIT-CLI-FILE-77aa-原文")
    monkeypatch.setenv("PENPAL_ADMIN_PASSWORD", ADMIN_PASSWORD)
    rc = audit_view.main(["--letter-id", str(letter["id"]),
                          "--reason", "执法检查",
                          "--key-file", str(crypto.key_path())])
    assert rc == 0
    assert "AUDIT-CLI-FILE-77aa-原文" in capsys.readouterr().out
    rows = database.list_audit_logs(letter_id=letter["id"])
    assert len(rows) == 1 and rows[0]["result"] == "ok"


def test_cli_missing_key_refused_and_audited(monkeypatch, capsys):
    letter = _seed_letter("AUDIT-CLI-88bb-原文")
    monkeypatch.setenv("PENPAL_ADMIN_PASSWORD", ADMIN_PASSWORD)
    # No key arg: getpass prompt hits EOF in tests -> treated as missing.
    rc = audit_view.main(["--letter-id", str(letter["id"]),
                          "--reason", "执法检查"])
    assert rc == 2
    out = capsys.readouterr().out
    assert "AUDIT-CLI-88bb-原文" not in out
    rows = database.list_audit_logs(letter_id=letter["id"])
    assert len(rows) == 1
    assert rows[0]["action"] == "letter_view_failed"
    assert rows[0]["result"] == "key_missing"


def test_cli_wrong_key_refused_and_audited(monkeypatch, capsys):
    letter = _seed_letter("AUDIT-CLI-99cc-原文")
    monkeypatch.setenv("PENPAL_ADMIN_PASSWORD", ADMIN_PASSWORD)
    rc = audit_view.main(["--letter-id", str(letter["id"]),
                          "--reason", "执法检查",
                          "--decryption-key", _wrong_key()])
    assert rc == 2
    out = capsys.readouterr().out
    assert "AUDIT-CLI-99cc-原文" not in out
    rows = database.list_audit_logs(letter_id=letter["id"])
    assert len(rows) == 1 and rows[0]["result"] == "key_mismatch"


def test_cli_other_reason_without_note_refused_no_audit(monkeypatch, capsys):
    letter = _seed_letter()
    before = len(database.list_audit_logs(letter_id=letter["id"]))
    monkeypatch.setenv("PENPAL_ADMIN_PASSWORD", ADMIN_PASSWORD)
    rc = audit_view.main(["--letter-id", str(letter["id"]),
                          "--reason", "其他",
                          "--decryption-key", _test_key()])
    assert rc == 2
    assert len(database.list_audit_logs(letter_id=letter["id"])) == before


def test_cli_wrong_password_views_nothing(monkeypatch, capsys):
    letter = _seed_letter("AUDIT-CLI-66ee-原文")
    before = len(database.list_audit_logs(letter_id=letter["id"]))
    monkeypatch.setenv("PENPAL_ADMIN_PASSWORD", "wrong-password")
    rc = audit_view.main(["--letter-id", str(letter["id"]),
                          "--reason", "执法检查"])
    assert rc == 2
    out = capsys.readouterr().out
    assert "AUDIT-CLI-66ee-原文" not in out
    assert len(database.list_audit_logs(letter_id=letter["id"])) == before


def test_cli_invalid_reason_refused(monkeypatch, capsys):
    letter = _seed_letter()
    monkeypatch.setenv("PENPAL_ADMIN_PASSWORD", ADMIN_PASSWORD)
    rc = audit_view.main(["--letter-id", str(letter["id"]),
                          "--reason", "好奇看看"])
    assert rc == 2
