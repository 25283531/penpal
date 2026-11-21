"""SQLite storage for Penpal (stdlib sqlite3, no ORM).

Forked from future-me's storage design, rewritten for penpal — there
are NO wishes / check-ins / daily sentences / TTS tables here. Every
memory, persona and letter is scoped to one (device_id, character_id)
pair, so character A can never recall character B's letters.

Tables:
- devices: device_id + age (age gate) + minor_mode + plan (free/member/
  premium) + emergency_contact (encrypted).
- characters: seeded P01–P05 from app/characters.py (fixed text).
- relationships: one row per (device, character); status active/ended;
  ended_at + reconnect_until (+30 days). Ended rows stay user-visible
  for 30 days, then user-invisible — but letters/memories are NEVER
  hard-deleted (soft delete only, encrypted retention for legal/audit).
- letters: user letters (direction=user, status in_transit/replied)
  and AI replies (direction=ai, status delivered, ai_generated=1).
  Text is Fernet-encrypted at rest.
- memories / persona / consolidation_runs: per (device, character),
  same evolution semantics as future-me (recall +0.05, fading, daily
  consolidation, at most one insight per run).
- point_events / unlocks / referrals: points (+1 write / +1 read /
  +1 login once a day) and unlock counters.
- settings / admin_sessions / admin_messages / admin_activities:
  admin console config and fetch-on-open content.
- violation_stats: TYPE + COUNT per day only. Never text, never device.
"""
import json
import secrets
import sqlite3
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from .characters import BY_ID, CHARACTERS, UNLOCK_ORDER, placeholder_photos
from .config import settings
from .crypto import decrypt_or_keep, encrypt_text, is_encrypted

SCHEMA = """
CREATE TABLE IF NOT EXISTS devices (
    device_id TEXT PRIMARY KEY,
    age INTEGER,
    minor_mode INTEGER NOT NULL DEFAULT 0,
    plan TEXT NOT NULL DEFAULT 'free',
    emergency_contact TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS characters (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    age INTEGER NOT NULL,
    gender TEXT NOT NULL,
    occupation TEXT NOT NULL,
    appearance TEXT NOT NULL,
    personality TEXT NOT NULL,
    hobbies TEXT NOT NULL,
    writing_style TEXT NOT NULL,
    topics TEXT NOT NULL,
    boundaries TEXT NOT NULL,
    life_history TEXT NOT NULL,
    photo_prompt TEXT NOT NULL,
    photo_url TEXT,
    photo_status TEXT NOT NULL DEFAULT 'pending',
    city TEXT,
    motto TEXT,
    photos TEXT,
    candid_photos TEXT,
    relationship TEXT NOT NULL DEFAULT '知己',
    unlocked_by_default INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS relationships (
    device_id TEXT NOT NULL,
    character_id TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    ended_at TEXT,
    reconnect_until TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (device_id, character_id)
);
CREATE TABLE IF NOT EXISTS letters (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id TEXT NOT NULL,
    character_id TEXT NOT NULL,
    direction TEXT NOT NULL,
    text TEXT NOT NULL,
    status TEXT NOT NULL,
    reply_due_at TEXT,
    is_first INTEGER NOT NULL DEFAULT 0,
    ai_generated INTEGER NOT NULL DEFAULT 0,
    read_at TEXT,
    user_read_at TEXT,
    character_read_at TEXT,
    created_at TEXT NOT NULL,
    replied_at TEXT
);
CREATE TABLE IF NOT EXISTS memories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id TEXT NOT NULL,
    character_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    text TEXT NOT NULL,
    importance REAL NOT NULL DEFAULT 0.5,
    emotion TEXT,
    recall_count INTEGER NOT NULL DEFAULT 0,
    last_recalled_at TEXT,
    faded INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS persona (
    device_id TEXT NOT NULL,
    character_id TEXT NOT NULL,
    relationship_stage TEXT NOT NULL DEFAULT '初识',
    summary TEXT NOT NULL DEFAULT '',
    traits TEXT NOT NULL DEFAULT '{"warmth": 0.5, "pride": 0.5}',
    interaction_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (device_id, character_id)
);
CREATE TABLE IF NOT EXISTS consolidation_runs (
    device_id TEXT NOT NULL,
    character_id TEXT NOT NULL,
    last_run_at TEXT NOT NULL,
    PRIMARY KEY (device_id, character_id)
);
CREATE TABLE IF NOT EXISTS point_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    points INTEGER NOT NULL,
    ref_id TEXT,
    date TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS unlocks (
    device_id TEXT NOT NULL,
    character_id TEXT NOT NULL,
    source TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (device_id, character_id)
);
CREATE TABLE IF NOT EXISTS referrals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    inviter_device_id TEXT NOT NULL,
    referred_device_id TEXT NOT NULL UNIQUE,
    successful INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS admin_sessions (
    token TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS admin_messages (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    body TEXT NOT NULL,
    audience TEXT NOT NULL DEFAULT 'all',
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS admin_activities (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    body TEXT NOT NULL,
    image_url TEXT,
    start_at TEXT,
    end_at TEXT,
    active INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS violation_stats (
    date TEXT NOT NULL,
    type TEXT NOT NULL,
    count INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (date, type)
);
-- M1: email accounts (one device_id bound per user, created at registration)
CREATE TABLE IF NOT EXISTS users (
    email TEXT PRIMARY KEY,
    password_hash TEXT NOT NULL,
    email_verified INTEGER NOT NULL DEFAULT 0,
    verified_at TEXT,
    age INTEGER,
    device_id TEXT UNIQUE NOT NULL,
    display_name TEXT,
    created_at TEXT NOT NULL
);
-- M1: email verification / reset codes (SHA256 of the code only, never the code)
CREATE TABLE IF NOT EXISTS verification_codes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT NOT NULL,
    purpose TEXT NOT NULL,
    code_hash TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    used INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
-- M1: one-time image captchas (SHA256 of the code, 5-min expiry, single use)
CREATE TABLE IF NOT EXISTS captchas (
    token TEXT PRIMARY KEY,
    code_hash TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    created_at TEXT NOT NULL
);
-- Anonymous -> email account merges (one row per merge; the move itself
-- is the idempotency guarantee — moved rows no longer live under the
-- source device, so a repeated merge finds nothing left to move).
CREATE TABLE IF NOT EXISTS device_merges (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_device_id TEXT NOT NULL,
    target_device_id TEXT NOT NULL,
    letters_moved INTEGER NOT NULL DEFAULT 0,
    points_moved INTEGER NOT NULL DEFAULT 0,
    points_dropped_duplicate INTEGER NOT NULL DEFAULT 0,
    relationships_moved INTEGER NOT NULL DEFAULT 0,
    memories_moved INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
-- M1: send-code events (rate limits) and failures (captcha gating)
CREATE TABLE IF NOT EXISTS email_send_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT NOT NULL,
    ip TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS email_send_failures (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT NOT NULL,
    ip TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""

DEFAULT_SETTINGS: dict[str, str] = {
    "llm.default_provider": "qwen",
    "llm.qwen.model": "qwen-plus",
    "llm.qwen.enabled": "1",
    "llm.hunyuan.model": "hunyuan-turbos-latest",
    "llm.hunyuan.enabled": "1",
    "llm.siliconflow.model": "Qwen/Qwen3-8B",
    "llm.siliconflow.enabled": "1",
    "llm.zhipu.model": "glm-4-flash",
    "llm.zhipu.enabled": "1",
    "dashscope.api_key": "",
    "hunyuan.api_key": "",
    "siliconflow.api_key": "",
    "zhipu.api_key": "",
    "membership.price_member_cny": "9.9",
    "membership.price_premium_cny": "19.9",
    "membership.paywalled": "0",
    "smtp.host": "smtp.qiye.aliyun.com",
    "smtp.port": "465",
    "smtp.ssl": "1",
    "smtp.user": "",
    "smtp.password": "",
    "memory.evolution_enabled": "1",
    "memory.reflection_enabled": "1",
    "memory.consolidation_interval_days": "1",
    "admin.password_hash": "",
}

SECRET_SETTINGS = {
    "dashscope.api_key",
    "hunyuan.api_key",
    "siliconflow.api_key",
    "zhipu.api_key",
    "smtp.password",
}

HIDDEN_SETTINGS = {"admin.password_hash", "auth.jwt_secret"}
SETTING_MASK = "********"


def connect() -> sqlite3.Connection:
    settings.DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(settings.DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db() -> None:
    with connect() as conn:
        conn.executescript(SCHEMA)
    _migrate_columns()
    _seed_characters()
    _migrate_encryption()
    _seed_content()


def _migrate_columns() -> None:
    """Add columns to a pre-existing DB (fresh DBs already get them from
    SCHEMA). Idempotent: only adds what PRAGMA says is missing, so old
    data is never lost and old rows simply read NULL for the new fields
    (e.g. user_read_at / character_read_at are NULL until the event
    actually happens)."""
    additions: dict[str, list[tuple[str, str]]] = {
        "letters": [
            ("user_read_at", "TEXT"),
            ("character_read_at", "TEXT"),
        ],
        "characters": [
            ("city", "TEXT"),
            ("motto", "TEXT"),
            ("photos", "TEXT"),
            ("candid_photos", "TEXT"),
        ],
        "users": [
            ("display_name", "TEXT"),
        ],
    }
    with connect() as conn:
        for table, cols in additions.items():
            existing = {r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}
            for name, coltype in cols:
                if name not in existing:
                    conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {coltype}")


def _seed_characters() -> None:
    """Seed P01–P05 from app/characters.py (fixed text). Idempotent:
    existing rows are left alone so a future edit of the seed does not
    silently rewrite a live character — except the profile/photo
    fields (city/motto/photos/candid_photos/photo_url/photo_status),
    which are backfilled where they are still NULL / "pending" /
    placeholders, because no live data ever lived in them. This is
    what heals an already-deployed DB whose rows were seeded when
    photos were still pending."""
    with connect() as conn:
        for c in CHARACTERS:
            conn.execute(
                "INSERT OR IGNORE INTO characters"
                " (id, name, age, gender, occupation, appearance, personality,"
                "  hobbies, writing_style, topics, boundaries, life_history,"
                "  photo_prompt, photo_url, photo_status, city, motto, photos,"
                "  candid_photos, relationship, unlocked_by_default)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    c["id"], c["name"], c["age"], c["gender"], c["occupation"],
                    c["appearance"], c["personality"],
                    json.dumps(c["hobbies"], ensure_ascii=False),
                    c["writing_style"],
                    json.dumps(c["topics"], ensure_ascii=False),
                    c["boundaries"], c["life_history"], c["photo_prompt"],
                    c["photo_url"], c["photo_status"],
                    c.get("city"),
                    c.get("motto"),
                    json.dumps(c.get("photos") or placeholder_photos(), ensure_ascii=False),
                    json.dumps(c.get("candid_photos") or [], ensure_ascii=False),
                    c["relationship"],
                    1 if c["unlocked_by_default"] else 0,
                ),
            )
            conn.execute(
                "UPDATE characters SET city = ?, motto = ?, photos = ?,"
                " candid_photos = ?, photo_url = ?, photo_status = ?"
                " WHERE id = ? AND (city IS NULL OR motto IS NULL OR photos IS NULL"
                " OR candid_photos IS NULL OR photo_url IS NULL"
                " OR photo_status = 'pending'"
                " OR photos LIKE '%\"is_placeholder\": true%')",
                (
                    c.get("city"),
                    c.get("motto"),
                    json.dumps(c.get("photos") or placeholder_photos(), ensure_ascii=False),
                    json.dumps(c.get("candid_photos") or [], ensure_ascii=False),
                    c["photo_url"],
                    c["photo_status"],
                    c["id"],
                ),
            )


def _migrate_encryption() -> None:
    specs = [
        ("letters", "id", "text"),
        ("memories", "id", "text"),
    ]
    with connect() as conn:
        for table, id_col, text_col in specs:
            rows = conn.execute(f"SELECT {id_col}, {text_col} FROM {table}").fetchall()
            for r in rows:
                val = r[text_col]
                if val and not is_encrypted(val):
                    conn.execute(
                        f"UPDATE {table} SET {text_col} = ? WHERE {id_col} = ?",
                        (encrypt_text(val), r[id_col]),
                    )
        for r in conn.execute(
            "SELECT device_id, character_id, summary FROM persona"
        ).fetchall():
            if r["summary"] and not is_encrypted(r["summary"]):
                conn.execute(
                    "UPDATE persona SET summary = ? WHERE device_id = ? AND character_id = ?",
                    (encrypt_text(r["summary"]), r["device_id"], r["character_id"]),
                )


def _decrypt_row(row: dict | None, field: str = "text") -> dict | None:
    if row is not None and row.get(field):
        row[field] = decrypt_or_keep(row[field])
    return row


def _decrypt_rows(rows: list[dict], field: str = "text") -> list[dict]:
    return [_decrypt_row(dict(r), field) for r in rows]


def _today() -> str:
    return date.today().isoformat()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---- settings ----

def get_setting(key: str, default: str = "") -> str:
    with connect() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    if row is not None:
        return row["value"]
    return DEFAULT_SETTINGS.get(key, default)


def get_all_settings() -> dict[str, str]:
    out = dict(DEFAULT_SETTINGS)
    with connect() as conn:
        rows = conn.execute("SELECT key, value FROM settings").fetchall()
    for r in rows:
        out[r["key"]] = r["value"]
    return out


def set_setting(key: str, value: str) -> None:
    with connect() as conn:
        conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?)"
            " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )


def set_settings(values: dict[str, str]) -> None:
    with connect() as conn:
        conn.executemany(
            "INSERT INTO settings (key, value) VALUES (?, ?)"
            " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            [(k, v) for k, v in values.items()],
        )


def get_or_create_jwt_secret() -> str:
    import os

    env_secret = os.environ.get("JWT_SECRET", "")
    if env_secret:
        return env_secret
    secret = get_setting("auth.jwt_secret", "")
    if not secret:
        secret = secrets.token_hex(32)
        set_setting("auth.jwt_secret", secret)
    return secret


# ---- admin sessions ----

SESSION_TTL_SECONDS = 7 * 24 * 3600


def create_admin_session() -> tuple[str, int]:
    token = secrets.token_urlsafe(32)
    now = datetime.now(timezone.utc)
    expires = now + timedelta(seconds=SESSION_TTL_SECONDS)
    with connect() as conn:
        conn.execute(
            "INSERT INTO admin_sessions (token, created_at, expires_at) VALUES (?, ?, ?)",
            (token, now.isoformat(), expires.isoformat()),
        )
    return token, SESSION_TTL_SECONDS


def admin_session_valid(token: str) -> bool:
    with connect() as conn:
        row = conn.execute(
            "SELECT expires_at FROM admin_sessions WHERE token = ?", (token,)
        ).fetchone()
    if not row:
        return False
    try:
        expires = datetime.fromisoformat(row["expires_at"])
    except ValueError:
        return False
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) < expires


def delete_admin_session(token: str) -> None:
    with connect() as conn:
        conn.execute("DELETE FROM admin_sessions WHERE token = ?", (token,))


# ---- seed messages / activities ----

def _seed_content() -> None:
    with connect() as conn:
        msg_count = conn.execute("SELECT COUNT(*) FROM admin_messages").fetchone()[0]
        act_count = conn.execute("SELECT COUNT(*) FROM admin_activities").fetchone()[0]
        if msg_count == 0:
            for m in _load_seed_json("messages.json"):
                conn.execute(
                    "INSERT OR IGNORE INTO admin_messages"
                    " (id, title, body, audience, active, created_at)"
                    " VALUES (?, ?, ?, ?, ?, ?)",
                    (str(m.get("id", "")), m.get("title", ""), m.get("body", ""),
                     m.get("audience", "all"), 1 if m.get("active", True) else 0,
                     m.get("created_at", _today())),
                )
        if act_count == 0:
            for a in _load_seed_json("activities.json"):
                conn.execute(
                    "INSERT OR IGNORE INTO admin_activities"
                    " (id, title, body, image_url, start_at, end_at, active)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (str(a.get("id", "")), a.get("title", ""), a.get("body", ""),
                     a.get("image_url"), a.get("start_at"), a.get("end_at"),
                     1 if a.get("active", True) else 0),
                )


def _load_seed_json(name: str) -> list[dict]:
    path = settings.DATA_DIR / name
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (ValueError, OSError):
        return []


def list_messages(include_inactive: bool = False) -> list[dict]:
    with connect() as conn:
        q = "SELECT id, title, body, audience, active, created_at FROM admin_messages"
        if not include_inactive:
            q += " WHERE active = 1"
        q += " ORDER BY created_at DESC, id DESC"
        return [dict(r) for r in conn.execute(q).fetchall()]


def create_message(title: str, body: str, audience: str = "all") -> dict:
    msg_id = f"msg-{secrets.token_hex(4)}"
    now = datetime.now(timezone.utc).isoformat()
    with connect() as conn:
        conn.execute(
            "INSERT INTO admin_messages (id, title, body, audience, active, created_at)"
            " VALUES (?, ?, ?, ?, 1, ?)",
            (msg_id, title, body, audience, now),
        )
    return get_message(msg_id)


def get_message(msg_id: str) -> dict | None:
    with connect() as conn:
        row = conn.execute(
            "SELECT id, title, body, audience, active, created_at FROM admin_messages WHERE id = ?",
            (msg_id,),
        ).fetchone()
    return dict(row) if row else None


def update_message(msg_id: str, fields: dict) -> dict | None:
    allowed = {"title", "body", "audience", "active"}
    sets = {k: v for k, v in fields.items() if k in allowed}
    if not sets:
        return get_message(msg_id)
    sql = "UPDATE admin_messages SET " + ", ".join(f"{k} = ?" for k in sets) + " WHERE id = ?"
    with connect() as conn:
        conn.execute(sql, (*sets.values(), msg_id))
    return get_message(msg_id)


def delete_message(msg_id: str) -> bool:
    with connect() as conn:
        cur = conn.execute("DELETE FROM admin_messages WHERE id = ?", (msg_id,))
        return cur.rowcount > 0


def list_activities(include_inactive: bool = False) -> list[dict]:
    with connect() as conn:
        q = "SELECT id, title, body, image_url, start_at, end_at, active FROM admin_activities"
        if not include_inactive:
            q += " WHERE active = 1"
        q += " ORDER BY id"
        return [dict(r) for r in conn.execute(q).fetchall()]


def create_activity(fields: dict) -> dict:
    act_id = fields.get("id") or f"act-{secrets.token_hex(4)}"
    with connect() as conn:
        conn.execute(
            "INSERT INTO admin_activities (id, title, body, image_url, start_at, end_at, active)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (act_id, fields.get("title", ""), fields.get("body", ""),
             fields.get("image_url"), fields.get("start_at"), fields.get("end_at"),
             1 if fields.get("active", True) else 0),
        )
    return get_activity(act_id)


def get_activity(act_id: str) -> dict | None:
    with connect() as conn:
        row = conn.execute(
            "SELECT id, title, body, image_url, start_at, end_at, active FROM admin_activities WHERE id = ?",
            (act_id,),
        ).fetchone()
    return dict(row) if row else None


def update_activity(act_id: str, fields: dict) -> dict | None:
    allowed = {"title", "body", "image_url", "start_at", "end_at", "active"}
    sets = {k: v for k, v in fields.items() if k in allowed}
    if not sets:
        return get_activity(act_id)
    sql = "UPDATE admin_activities SET " + ", ".join(f"{k} = ?" for k in sets) + " WHERE id = ?"
    with connect() as conn:
        conn.execute(sql, (*sets.values(), act_id))
    return get_activity(act_id)


def delete_activity(act_id: str) -> bool:
    with connect() as conn:
        cur = conn.execute("DELETE FROM admin_activities WHERE id = ?", (act_id,))
        return cur.rowcount > 0


# ---- devices (age gate) ----
# Age is collected at registration. Under-14s are refused (guardian
# consent + full minor mode are M2); 14–17s are flagged minor_mode=1.
# The gate lives here so no device row can exist without an age check.

MIN_AGE = 14


def device_exists(device_id: str) -> bool:
    with connect() as conn:
        row = conn.execute(
            "SELECT 1 FROM devices WHERE device_id = ?", (device_id,)
        ).fetchone()
        return row is not None


def get_device(device_id: str) -> dict | None:
    with connect() as conn:
        row = conn.execute(
            "SELECT device_id, age, minor_mode, plan, emergency_contact, created_at"
            " FROM devices WHERE device_id = ?",
            (device_id,),
        ).fetchone()
    if not row:
        return None
    d = dict(row)
    if d.get("emergency_contact"):
        d["emergency_contact"] = decrypt_or_keep(d["emergency_contact"])
    return d


def get_or_create_device(
    device_id: str, age: int | None = None, emergency_contact: str | None = None,
) -> dict:
    """Create a device row. `age` is required on first registration
    (the age gate); later calls without age return the existing row."""
    existing = get_device(device_id)
    if existing:
        return existing
    if age is None:
        raise ValueError("age is required at registration (age gate)")
    if not isinstance(age, int) or not 1 <= age <= 120:
        raise ValueError("age must be an integer between 1 and 120")
    if age < MIN_AGE:
        raise ValueError(
            "users under 14 need a guardian's consent (minor mode is M2); registration refused"
        )
    minor_mode = 1 if age < 18 else 0
    with connect() as conn:
        conn.execute(
            "INSERT INTO devices (device_id, age, minor_mode, plan, emergency_contact, created_at)"
            " VALUES (?, ?, ?, 'free', ?, ?)",
            (
                device_id, age, minor_mode,
                encrypt_text(emergency_contact) if emergency_contact else None,
                _today(),
            ),
        )
    return get_device(device_id)


def set_device_plan(device_id: str, plan: str) -> dict:
    if plan not in ("free", "member", "premium"):
        raise ValueError(f"unknown plan: {plan}")
    with connect() as conn:
        conn.execute("UPDATE devices SET plan = ? WHERE device_id = ?", (plan, device_id))
    return get_device(device_id)


# ---- characters ----

def _decode_character(row: dict) -> dict:
    row["hobbies"] = json.loads(row.get("hobbies") or "[]")
    row["topics"] = json.loads(row.get("topics") or "[]")
    try:
        photos = json.loads(row.get("photos") or "")
    except (ValueError, TypeError):
        photos = None
    if not isinstance(photos, list) or not photos:
        photos = placeholder_photos()
    try:
        candid = json.loads(row.get("candid_photos") or "")
    except (ValueError, TypeError):
        candid = None
    if not isinstance(candid, list):
        candid = []
    seed = BY_ID.get(row.get("id") or "")
    if seed:
        # Rows seeded before the photos went live still carry
        # placeholders (photo_url NULL / status "pending"): prefer the
        # seed's real photos so an already-deployed DB heals on read,
        # even if the backfill in _seed_characters was skipped.
        if all(
            isinstance(p, dict) and p.get("is_placeholder")
            for p in photos
        ):
            photos = seed.get("photos") or photos
            row["photo_url"] = seed.get("photo_url") or row.get("photo_url")
            row["photo_status"] = seed.get("photo_status") or row.get("photo_status")
        if not candid:
            candid = seed.get("candid_photos") or []
    row["photos"] = photos
    row["candid_photos"] = candid
    row["unlocked_by_default"] = bool(row.get("unlocked_by_default"))
    row["is_ai"] = True
    row["ai_label"] = "AI 生成 · 虚拟人物"
    row["relationship"] = row.get("relationship") or "知己"
    return row


def list_characters() -> list[dict]:
    with connect() as conn:
        rows = conn.execute("SELECT * FROM characters ORDER BY id").fetchall()
    return [_decode_character(dict(r)) for r in rows]


def get_character(character_id: str) -> dict | None:
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM characters WHERE id = ?", (character_id,)
        ).fetchone()
    return _decode_character(dict(row)) if row else None


def character_for_llm(character_id: str, device_id: str) -> dict | None:
    """Character dict as the LLM prompt needs it, plus the live persona
    stage / interaction count for this (device, character) pair."""
    c = get_character(character_id)
    if not c:
        return None
    persona = get_persona(device_id, character_id)
    c["_stage"] = persona["relationship_stage"]
    c["_interaction_count"] = persona["interaction_count"]
    return c


# ---- relationships ----

def get_relationship(device_id: str, character_id: str) -> dict | None:
    with connect() as conn:
        row = conn.execute(
            "SELECT device_id, character_id, status, ended_at, reconnect_until,"
            " created_at, updated_at FROM relationships"
            " WHERE device_id = ? AND character_id = ?",
            (device_id, character_id),
        ).fetchone()
    return dict(row) if row else None


def active_relationship_count(device_id: str) -> int:
    with connect() as conn:
        row = conn.execute(
            "SELECT COUNT(*) FROM relationships WHERE device_id = ? AND status = 'active'",
            (device_id,),
        ).fetchone()
    return row[0]


def list_relationships(device_id: str, include_expired_ended: bool = False) -> list[dict]:
    """User-visible relationships: active ones, plus ended ones still
    inside their 30-day reconnect window. Ended rows past the window
    are invisible to the user (data stays encrypted on the server)."""
    with connect() as conn:
        rows = conn.execute(
            "SELECT device_id, character_id, status, ended_at, reconnect_until,"
            " created_at, updated_at FROM relationships WHERE device_id = ? ORDER BY created_at",
            (device_id,),
        ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        if d["status"] == "active":
            out.append(d)
        elif include_expired_ended:
            out.append(d)
        elif d.get("reconnect_until") and d["reconnect_until"] >= _today():
            out.append(d)
    return out


def start_relationship(device_id: str, character_id: str, max_active: int) -> dict:
    """Start (or resume) a relationship. Raises ValueError when the
    tier's active-slot limit is reached."""
    rel = get_relationship(device_id, character_id)
    now = _now_iso()
    if rel and rel["status"] == "active":
        return rel
    if rel and rel["status"] == "ended":
        return reconnect_relationship(device_id, character_id, max_active)
    if active_relationship_count(device_id) >= max_active:
        raise ValueError(
            f"active character limit reached ({max_active}); end a relationship or upgrade first"
        )
    with connect() as conn:
        conn.execute(
            "INSERT INTO relationships (device_id, character_id, status, ended_at,"
            " reconnect_until, created_at, updated_at) VALUES (?, ?, 'active', NULL, NULL, ?, ?)",
            (device_id, character_id, now, now),
        )
    return get_relationship(device_id, character_id)


def end_relationship(device_id: str, character_id: str) -> dict | None:
    """End a relationship. The 30-day reconnect window starts now.
    Letters/memories are NOT deleted — soft delete only (see module doc)."""
    rel = get_relationship(device_id, character_id)
    if not rel or rel["status"] != "active":
        return rel
    ended = _now_iso()
    reconnect_until = (date.today() + timedelta(days=30)).isoformat()
    with connect() as conn:
        conn.execute(
            "UPDATE relationships SET status = 'ended', ended_at = ?,"
            " reconnect_until = ?, updated_at = ?"
            " WHERE device_id = ? AND character_id = ?",
            (ended, reconnect_until, ended, device_id, character_id),
        )
    return get_relationship(device_id, character_id)


def reconnect_relationship(device_id: str, character_id: str, max_active: int) -> dict:
    """Reconnect inside the 30-day window (letters + memories intact).
    Past the window the relationship is user-side gone (410 in the API);
    the encrypted server data is retained for legal/audit only."""
    rel = get_relationship(device_id, character_id)
    if not rel:
        raise ValueError("relationship not found")
    if rel["status"] == "active":
        return rel
    if not rel.get("reconnect_until") or rel["reconnect_until"] < _today():
        raise ValueError("reconnect window (30 days) has passed; this relationship is closed to the user")
    if active_relationship_count(device_id) >= max_active:
        raise ValueError(
            f"active character limit reached ({max_active}); end a relationship or upgrade first"
        )
    now = _now_iso()
    with connect() as conn:
        conn.execute(
            "UPDATE relationships SET status = 'active', ended_at = NULL,"
            " reconnect_until = NULL, updated_at = ?"
            " WHERE device_id = ? AND character_id = ?",
            (now, device_id, character_id),
        )
    return get_relationship(device_id, character_id)


# ---- letters ----

LETTER_COLUMNS = (
    "id, device_id, character_id, direction, text, status, reply_due_at,"
    " is_first, ai_generated, read_at, user_read_at, character_read_at,"
    " created_at, replied_at"
)


def create_user_letter(
    device_id: str, character_id: str, text: str, reply_due_at: str, is_first: bool,
) -> dict:
    with connect() as conn:
        cur = conn.execute(
            "INSERT INTO letters (device_id, character_id, direction, text, status,"
            " reply_due_at, is_first, ai_generated, created_at)"
            " VALUES (?, ?, 'user', ?, 'in_transit', ?, ?, 0, datetime('now'))",
            (device_id, character_id, encrypt_text(text), reply_due_at, 1 if is_first else 0),
        )
        letter_id = cur.lastrowid
    return get_letter(device_id, letter_id)


def create_reply_letter(device_id: str, character_id: str, text: str) -> dict:
    with connect() as conn:
        cur = conn.execute(
            "INSERT INTO letters (device_id, character_id, direction, text, status,"
            " reply_due_at, is_first, ai_generated, created_at)"
            " VALUES (?, ?, 'ai', ?, 'delivered', NULL, 0, 1, datetime('now'))",
            (device_id, character_id, encrypt_text(text)),
        )
        letter_id = cur.lastrowid
    return get_letter(device_id, letter_id)


def get_letter(device_id: str, letter_id: int) -> dict | None:
    with connect() as conn:
        row = conn.execute(
            f"SELECT {LETTER_COLUMNS} FROM letters WHERE device_id = ? AND id = ?",
            (device_id, letter_id),
        ).fetchone()
    return _decrypt_row(dict(row)) if row else None


def list_thread(device_id: str, character_id: str) -> list[dict]:
    """Whole thread for one character, oldest first (decrypted in memory)."""
    with connect() as conn:
        rows = conn.execute(
            f"SELECT {LETTER_COLUMNS} FROM letters"
            " WHERE device_id = ? AND character_id = ? ORDER BY id ASC",
            (device_id, character_id),
        ).fetchall()
    return _decrypt_rows([dict(r) for r in rows])


def list_all_letters(device_id: str) -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            f"SELECT {LETTER_COLUMNS} FROM letters WHERE device_id = ? ORDER BY id DESC",
            (device_id,),
        ).fetchall()
    return _decrypt_rows([dict(r) for r in rows])


def outstanding_letter(device_id: str, character_id: str) -> dict | None:
    """The user's in-transit letter for this character, if any
    (turn-taking: one outstanding letter per character)."""
    with connect() as conn:
        row = conn.execute(
            f"SELECT {LETTER_COLUMNS} FROM letters"
            " WHERE device_id = ? AND character_id = ? AND direction = 'user'"
            " AND status = 'in_transit' ORDER BY id DESC LIMIT 1",
            (device_id, character_id),
        ).fetchone()
    return _decrypt_row(dict(row)) if row else None


def count_user_letters(device_id: str, character_id: str) -> int:
    with connect() as conn:
        row = conn.execute(
            "SELECT COUNT(*) FROM letters WHERE device_id = ? AND character_id = ?"
            " AND direction = 'user'",
            (device_id, character_id),
        ).fetchone()
    return row[0]


def count_today_sends(device_id: str, day: str | None = None) -> int:
    """User letters sent today (per-user daily cap — not per character)."""
    day = day or _today()
    with connect() as conn:
        row = conn.execute(
            "SELECT COUNT(*) FROM letters WHERE device_id = ? AND direction = 'user'"
            " AND substr(created_at, 1, 10) = ?",
            (device_id, day),
        ).fetchone()
    return row[0]


def due_user_letters(device_id: str, day: str) -> list[dict]:
    """In-transit user letters whose reply is due on or before `day`."""
    with connect() as conn:
        rows = conn.execute(
            f"SELECT {LETTER_COLUMNS} FROM letters"
            " WHERE device_id = ? AND direction = 'user' AND status = 'in_transit'"
            " AND reply_due_at IS NOT NULL AND reply_due_at <= ? ORDER BY id ASC",
            (device_id, day),
        ).fetchall()
    return _decrypt_rows([dict(r) for r in rows])


def _character_read_at(created_at: str | None, replied_at: str) -> str | None:
    """When the character 'read' the user's letter, as recorded when the
    reply is generated. This is NOT a precise timestamp anyone observed:
    it is derived as replied_at minus the smaller of 3 hours and half
    the sent -> replied interval, truncated to the minute, and clamped
    inside [sent, replied] — so it never claims second-level precision
    and never lands in the future or before the letter was sent.
    (Comparisons are minute-granularity by design: when sent and
    replied fall in the same minute, the truncated value is that minute,
    which can read up to 59s before the sent second — it still denotes
    the same minute, not an earlier moment.)"""
    try:
        sent = datetime.fromisoformat((created_at or "").replace("Z", "+00:00"))
    except ValueError:
        return None
    try:
        replied = datetime.fromisoformat(replied_at.replace("Z", "+00:00"))
    except ValueError:
        return None
    if sent.tzinfo is None:
        sent = sent.replace(tzinfo=timezone.utc)
    if replied.tzinfo is None:
        replied = replied.replace(tzinfo=timezone.utc)
    interval = (replied - sent).total_seconds()
    if interval <= 0:
        return sent.replace(second=0, microsecond=0).strftime("%Y-%m-%d %H:%M:%S")
    read_at = replied - timedelta(seconds=min(3 * 3600, interval / 2))
    read_at = max(sent, min(read_at, replied))
    return read_at.replace(second=0, microsecond=0).strftime("%Y-%m-%d %H:%M:%S")


def mark_letter_replied(device_id: str, letter_id: int) -> dict | None:
    letter = get_letter(device_id, letter_id)
    if not letter:
        return None
    replied_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    char_read_at = _character_read_at(letter.get("created_at"), replied_at)
    with connect() as conn:
        conn.execute(
            "UPDATE letters SET status = 'replied', replied_at = ?,"
            " character_read_at = ? WHERE id = ? AND device_id = ?",
            (replied_at, char_read_at, letter_id, device_id),
        )
    return get_letter(device_id, letter_id)


def mark_letter_read(device_id: str, letter_id: int) -> dict | None:
    """Mark an AI reply as read. First call only: user_read_at (and the
    legacy read_at, kept for backward compatibility) are set once and
    never overwritten. Returns the letter; the +1 read point is awarded
    once only (see main.read_letter)."""
    letter = get_letter(device_id, letter_id)
    if not letter or letter["direction"] != "ai":
        return letter
    if not letter.get("user_read_at") and not letter.get("read_at"):
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        with connect() as conn:
            conn.execute(
                "UPDATE letters SET read_at = ?, user_read_at = ?"
                " WHERE id = ? AND device_id = ?",
                (now, now, letter_id, device_id),
            )
    return get_letter(device_id, letter_id)


def count_unread_replies(device_id: str) -> int:
    """Delivered AI replies the user has not opened yet. Unread is
    judged by user_read_at (falling back to the legacy read_at, so
    replies marked read before this change still count as read)."""
    with connect() as conn:
        row = conn.execute(
            "SELECT COUNT(*) FROM letters WHERE device_id = ? AND direction = 'ai'"
            " AND status = 'delivered' AND user_read_at IS NULL AND read_at IS NULL",
            (device_id,),
        ).fetchone()
    return row[0]


# ---- memories (per device x character) ----

MEMORY_KINDS = {
    "profile", "preference", "milestone", "progress", "note",
    "emotion", "insight",
}

MEMORY_COLUMNS = (
    "id, device_id, character_id, kind, text, importance, emotion, recall_count,"
    " last_recalled_at, faded, created_at, updated_at"
)


def normalize_importance(value) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return 0.5
    if isinstance(value, int) and not isinstance(value, bool):
        return 0.9 if v >= 3 else (0.7 if v == 2 else 0.5)
    return max(0.1, min(1.0, v))


def list_memories(device_id: str, character_id: str, include_faded: bool = False) -> list[dict]:
    q = f"SELECT {MEMORY_COLUMNS} FROM memories WHERE device_id = ? AND character_id = ?"
    if not include_faded:
        q += " AND faded = 0"
    q += " ORDER BY importance DESC, created_at DESC"
    with connect() as conn:
        rows = conn.execute(q, (device_id, character_id)).fetchall()
    return _decrypt_rows([dict(r) for r in rows])


def create_memory(
    device_id: str, character_id: str, kind: str, text: str, importance: float = 0.5,
    emotion: str | None = None,
) -> dict:
    if kind not in MEMORY_KINDS:
        raise ValueError(f"unknown memory kind: {kind}")
    now = _now_iso()
    with connect() as conn:
        cur = conn.execute(
            "INSERT INTO memories (device_id, character_id, kind, text, importance,"
            " emotion, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (device_id, character_id, kind, encrypt_text(text),
             normalize_importance(importance), emotion, now, now),
        )
        row_id = cur.lastrowid
    return get_memory(row_id)


def get_memory(row_id: int) -> dict | None:
    with connect() as conn:
        row = conn.execute(
            f"SELECT {MEMORY_COLUMNS} FROM memories WHERE id = ?", (row_id,)
        ).fetchone()
    return _decrypt_row(dict(row)) if row else None


def update_memory(row_id: int, fields: dict) -> dict | None:
    allowed = {"kind", "text", "importance", "emotion", "recall_count",
               "last_recalled_at", "faded"}
    sets = {k: v for k, v in fields.items() if k in allowed}
    if "kind" in sets and sets["kind"] not in MEMORY_KINDS:
        raise ValueError(f"unknown memory kind: {sets['kind']}")
    if not sets:
        return get_memory(row_id)
    if "text" in sets:
        sets["text"] = encrypt_text(sets["text"])
    if "importance" in sets:
        sets["importance"] = normalize_importance(sets["importance"])
    sets["updated_at"] = _now_iso()
    sql = "UPDATE memories SET " + ", ".join(f"{k} = ?" for k in sets) + " WHERE id = ?"
    with connect() as conn:
        conn.execute(sql, (*sets.values(), row_id))
    return get_memory(row_id)


def touch_memories(device_id: str, character_id: str, memory_ids: list[int]) -> None:
    if not memory_ids:
        return
    now = _now_iso()
    with connect() as conn:
        for mid in memory_ids:
            conn.execute(
                "UPDATE memories SET recall_count = recall_count + 1,"
                " last_recalled_at = ?, importance = MIN(1.0, importance + 0.05),"
                " updated_at = ? WHERE id = ? AND device_id = ? AND character_id = ?",
                (now, now, mid, device_id, character_id),
            )


def delete_memory(row_id: int) -> bool:
    """Used only by consolidation dedupe (exact duplicates). This is
    dedupe of a duplicate memory row, NOT deletion of user data on
    relationship end — letters/memories are never deleted there."""
    with connect() as conn:
        cur = conn.execute("DELETE FROM memories WHERE id = ?", (row_id,))
        return cur.rowcount > 0


def _memory_exists(device_id: str, character_id: str, kind: str, text: str) -> bool:
    with connect() as conn:
        row = conn.execute(
            "SELECT 1 FROM memories WHERE device_id = ? AND character_id = ? AND kind = ? AND text = ?",
            (device_id, character_id, kind, text),
        ).fetchone()
    return row is not None


# ---- persona (per device x character) ----

DEFAULT_TRAITS: dict[str, float] = {"warmth": 0.5, "pride": 0.5}


def _decode_persona(row: dict) -> dict:
    row["summary"] = decrypt_or_keep(row.get("summary") or "")
    try:
        traits = json.loads(row.get("traits") or "{}")
        if not isinstance(traits, dict):
            traits = {}
    except ValueError:
        traits = {}
    merged = dict(DEFAULT_TRAITS)
    for k, v in traits.items():
        try:
            merged[k] = max(0.0, min(1.0, float(v)))
        except (TypeError, ValueError):
            continue
    row["traits"] = merged
    return row


def get_persona(device_id: str, character_id: str) -> dict:
    now = _now_iso()
    with connect() as conn:
        row = conn.execute(
            "SELECT device_id, character_id, relationship_stage, summary, traits,"
            " interaction_count, created_at, updated_at FROM persona"
            " WHERE device_id = ? AND character_id = ?",
            (device_id, character_id),
        ).fetchone()
        if row is None:
            conn.execute(
                "INSERT INTO persona (device_id, character_id, relationship_stage, summary,"
                " traits, interaction_count, created_at, updated_at)"
                " VALUES (?, ?, '初识', '', ?, 0, ?, ?)",
                (device_id, character_id, json.dumps(DEFAULT_TRAITS, ensure_ascii=False), now, now),
            )
            row = conn.execute(
                "SELECT device_id, character_id, relationship_stage, summary, traits,"
                " interaction_count, created_at, updated_at FROM persona"
                " WHERE device_id = ? AND character_id = ?",
                (device_id, character_id),
            ).fetchone()
    return _decode_persona(dict(row))


def update_persona(device_id: str, character_id: str, fields: dict) -> dict:
    get_persona(device_id, character_id)
    allowed = {"relationship_stage", "summary", "traits", "interaction_count"}
    sets = {k: v for k, v in fields.items() if k in allowed}
    if not sets:
        return get_persona(device_id, character_id)
    if "summary" in sets:
        sets["summary"] = encrypt_text(sets["summary"] or "")
    if "traits" in sets:
        traits = dict(DEFAULT_TRAITS)
        traits.update(sets["traits"] or {})
        sets["traits"] = json.dumps(
            {k: max(0.0, min(1.0, float(v))) for k, v in traits.items()},
            ensure_ascii=False,
        )
    sets["updated_at"] = _now_iso()
    sql = (
        "UPDATE persona SET " + ", ".join(f"{k} = ?" for k in sets)
        + " WHERE device_id = ? AND character_id = ?"
    )
    with connect() as conn:
        conn.execute(sql, (*sets.values(), device_id, character_id))
    return get_persona(device_id, character_id)


# ---- consolidation runs ----

def get_consolidation_last_run(device_id: str, character_id: str) -> str | None:
    with connect() as conn:
        row = conn.execute(
            "SELECT last_run_at FROM consolidation_runs WHERE device_id = ? AND character_id = ?",
            (device_id, character_id),
        ).fetchone()
    return row["last_run_at"] if row else None


def set_consolidation_last_run(device_id: str, character_id: str, when: str) -> None:
    with connect() as conn:
        conn.execute(
            "INSERT INTO consolidation_runs (device_id, character_id, last_run_at) VALUES (?, ?, ?)"
            " ON CONFLICT(device_id, character_id) DO UPDATE SET last_run_at = excluded.last_run_at",
            (device_id, character_id, when),
        )


def events_since(device_id: str, character_id: str, since: str | None) -> dict:
    """Recent letters for consolidation (decrypted in memory only,
    first 120 chars each). Never returned by any API."""
    since = since or "0000-00-00 00:00:00"
    with connect() as conn:
        letters = [
            dict(r) for r in conn.execute(
                "SELECT id, direction, text, created_at FROM letters"
                " WHERE device_id = ? AND character_id = ? AND created_at >= ? ORDER BY id",
                (device_id, character_id, since),
            ).fetchall()
        ]
    letters = _decrypt_rows(letters)
    for r in letters:
        r["text"] = (r["text"] or "")[:120]
    return {"letters": letters}


# ---- points / unlocks / referrals ----

POINT_RULES = {"write": 1, "read": 1, "login": 1}
POINTS_UNLOCK_THRESHOLDS = (100, 300)  # 100 -> 1 character, 300 -> another 1
REFERRAL_MILESTONES = ((1, 1), (10, 2), (30, 3), (40, 4), (50, 5))  # (referrals, cumulative unlocks)


def referral_unlocks(referral_count: int) -> int:
    """Cumulative referral unlocks, capped at 5."""
    unlocked = 0
    for needed, count in REFERRAL_MILESTONES:
        if referral_count >= needed:
            unlocked = count
    return unlocked


def points_unlocks(points: int) -> int:
    """Points unlocks: 100 points -> 1, 300 points -> another 1 (max 2)."""
    return sum(1 for t in POINTS_UNLOCK_THRESHOLDS if points >= t)


def points_balance(device_id: str) -> int:
    with connect() as conn:
        row = conn.execute(
            "SELECT COALESCE(SUM(points), 0) FROM point_events WHERE device_id = ?",
            (device_id,),
        ).fetchone()
    return row[0]


def list_point_events(device_id: str, limit: int = 50) -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT id, device_id, kind, points, ref_id, date, created_at"
            " FROM point_events WHERE device_id = ? ORDER BY id DESC LIMIT ?",
            (device_id, limit),
        ).fetchall()
    return [dict(r) for r in rows]


def award_point(device_id: str, kind: str, ref_id: str | None = None) -> int:
    """Award +1 point for a kind. Login is once per day; write/read are
    once per ref (letter id) — repeat calls are no-ops. Returns the
    points awarded (0 or 1)."""
    if kind not in POINT_RULES:
        raise ValueError(f"unknown point kind: {kind}")
    today = _today()
    with connect() as conn:
        if kind == "login":
            row = conn.execute(
                "SELECT 1 FROM point_events WHERE device_id = ? AND kind = 'login' AND date = ?",
                (device_id, today),
            ).fetchone()
            if row:
                return 0
        elif ref_id is not None:
            row = conn.execute(
                "SELECT 1 FROM point_events WHERE device_id = ? AND kind = ? AND ref_id = ?",
                (device_id, kind, ref_id),
            ).fetchone()
            if row:
                return 0
        conn.execute(
            "INSERT INTO point_events (device_id, kind, points, ref_id, date, created_at)"
            " VALUES (?, ?, 1, ?, ?, datetime('now'))",
            (device_id, kind, ref_id, today),
        )
    evaluate_unlocks(device_id)
    return 1


def referral_count(device_id: str) -> int:
    with connect() as conn:
        row = conn.execute(
            "SELECT COUNT(*) FROM referrals WHERE inviter_device_id = ? AND successful = 1",
            (device_id,),
        ).fetchone()
    return row[0]


def record_referral(inviter_device_id: str, referred_device_id: str) -> dict:
    """Record a referral (inviter claims a referred device). Success
    flips when the referred device writes its first letter (see
    mark_referral_successful). No referral UI in M0 — counters only."""
    if inviter_device_id == referred_device_id:
        raise ValueError("cannot refer yourself")
    now = _now_iso()
    with connect() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO referrals (inviter_device_id, referred_device_id, successful, created_at)"
            " VALUES (?, ?, 0, ?)",
            (inviter_device_id, referred_device_id, now),
        )
        row = conn.execute(
            "SELECT id, inviter_device_id, referred_device_id, successful, created_at"
            " FROM referrals WHERE referred_device_id = ?",
            (referred_device_id,),
        ).fetchone()
    return dict(row)


def mark_referral_successful(referred_device_id: str) -> None:
    """A referral succeeds when the referred device writes its first
    letter. Called from the send-letter flow."""
    with connect() as conn:
        cur = conn.execute(
            "UPDATE referrals SET successful = 1 WHERE referred_device_id = ? AND successful = 0",
            (referred_device_id,),
        )
        if cur.rowcount:
            row = conn.execute(
                "SELECT inviter_device_id FROM referrals WHERE referred_device_id = ?",
                (referred_device_id,),
            ).fetchone()
    if cur.rowcount and row:
        evaluate_unlocks(row["inviter_device_id"])


def evaluate_unlocks(device_id: str) -> list[str]:
    """Grant unlock rows for newly entitled characters (in UNLOCK_ORDER).
    Entitlement = points unlocks + referral unlocks. M0 only seeds
    P01–P05, so no new rows can be granted yet — the function returns
    the entitled character ids (including unseeded P06+) so the logic
    is testable, and grants rows for any that are seeded."""
    entitled_n = points_unlocks(points_balance(device_id)) + referral_unlocks(referral_count(device_id))
    entitled = UNLOCK_ORDER[:entitled_n]
    now = _now_iso()
    granted: list[str] = []
    with connect() as conn:
        for cid in entitled:
            if get_character(cid) is None:
                continue
            conn.execute(
                "INSERT OR IGNORE INTO unlocks (device_id, character_id, source, created_at)"
                " VALUES (?, ?, 'points_or_referral', ?)",
                (device_id, cid, now),
            )
            granted.append(cid)
    return entitled


def unlocked_character_ids(device_id: str) -> list[str]:
    """Characters this device may choose: default P01–P05 + granted unlocks."""
    ids = [c["id"] for c in CHARACTERS]
    with connect() as conn:
        rows = conn.execute(
            "SELECT character_id FROM unlocks WHERE device_id = ? ORDER BY character_id",
            (device_id,),
        ).fetchall()
    for r in rows:
        if r["character_id"] not in ids:
            ids.append(r["character_id"])
    return ids


# ---- dashboard: AGGREGATES ONLY (privacy red line) ----

def record_violation(vtype: str, day: str | None = None) -> None:
    day = day or _today()
    with connect() as conn:
        conn.execute(
            "INSERT INTO violation_stats (date, type, count) VALUES (?, ?, 1)"
            " ON CONFLICT(date, type) DO UPDATE SET count = count + 1",
            (day, vtype),
        )


def violation_summary(days: int = 30) -> list[dict]:
    since = (date.today() - timedelta(days=days - 1)).isoformat()
    with connect() as conn:
        rows = conn.execute(
            "SELECT type, SUM(count) AS count FROM violation_stats"
            " WHERE date >= ? GROUP BY type ORDER BY count DESC",
            (since,),
        ).fetchall()
    return [{"type": r["type"], "count": r["count"]} for r in rows]


def letters_by_character() -> list[dict]:
    """Letters per character (counts only — no text, no device)."""
    with connect() as conn:
        rows = conn.execute(
            "SELECT character_id, COUNT(*) AS letters,"
            " COUNT(DISTINCT device_id) AS devices FROM letters"
            " GROUP BY character_id ORDER BY letters DESC"
        ).fetchall()
    return [dict(r) for r in rows]


def dashboard_stats() -> dict:
    today = _today()
    with connect() as conn:
        devices = conn.execute("SELECT COUNT(*) FROM devices").fetchone()[0]
        letters = conn.execute("SELECT COUNT(*) FROM letters").fetchone()[0]
        user_letters = conn.execute(
            "SELECT COUNT(*) FROM letters WHERE direction = 'user'"
        ).fetchone()[0]
        replies = conn.execute(
            "SELECT COUNT(*) FROM letters WHERE direction = 'ai'"
        ).fetchone()[0]
        active_rels = conn.execute(
            "SELECT COUNT(*) FROM relationships WHERE status = 'active'"
        ).fetchone()[0]
        dau = conn.execute(
            "SELECT COUNT(DISTINCT device_id) FROM letters WHERE substr(created_at, 1, 10) = ?",
            (today,),
        ).fetchone()[0]
    return {
        "devices": devices,
        "letters": letters,
        "user_letters": user_letters,
        "replies": replies,
        "active_relationships": active_rels,
        "dau_today": dau,
        "characters": letters_by_character(),
        "violations": violation_summary(),
    }

# ---- M1: email users / verification codes / captchas / rate limits ----

def create_user(email: str, password_hash: str, age: int | None, device_id: str,
                display_name: str | None = None) -> dict:
    with connect() as conn:
        conn.execute(
            "INSERT INTO users (email, password_hash, email_verified, verified_at,"
            " age, device_id, display_name, created_at) VALUES (?, ?, 0, NULL, ?, ?, ?, ?)",
            (email, password_hash, age, device_id, display_name, _now_iso()),
        )
    return get_user_by_email(email)


def get_user_by_email(email: str) -> dict | None:
    with connect() as conn:
        row = conn.execute(
            "SELECT email, password_hash, email_verified, verified_at, age,"
            " device_id, display_name, created_at FROM users WHERE email = ?",
            (email,),
        ).fetchone()
    return dict(row) if row else None


def get_user_by_device(device_id: str) -> dict | None:
    with connect() as conn:
        row = conn.execute(
            "SELECT email, password_hash, email_verified, verified_at, age,"
            " device_id, display_name, created_at FROM users WHERE device_id = ?",
            (device_id,),
        ).fetchone()
    return dict(row) if row else None


def update_user_display_name(email: str, display_name: str) -> dict | None:
    """Rename the user's virtual-world name. Takes effect immediately:
    the next reply generation reads it live from the users row."""
    with connect() as conn:
        conn.execute(
            "UPDATE users SET display_name = ? WHERE email = ?",
            (display_name, email),
        )
    return get_user_by_email(email)


def set_user_verified(email: str) -> dict | None:
    with connect() as conn:
        conn.execute(
            "UPDATE users SET email_verified = 1, verified_at = ? WHERE email = ?",
            (_now_iso(), email),
        )
    return get_user_by_email(email)


def update_user_password(email: str, password_hash: str) -> dict | None:
    with connect() as conn:
        conn.execute(
            "UPDATE users SET password_hash = ? WHERE email = ?",
            (password_hash, email),
        )
    return get_user_by_email(email)


ZERO_MERGE = {
    "merged": False,
    "letters_moved": 0,
    "points_moved": 0,
    "points_dropped_duplicate": 0,
    "relationships_moved": 0,
    "memories_moved": 0,
}


def merge_device_data(source_device_id: str, target_device_id: str,
                      retire_source: bool = False) -> dict:
    """Move ALL of one device's data under another device (anonymous ->
    email-account merge). Used when an email registration or login binds
    the currently-anonymous device: letters, point events, relationships,
    memories, persona, consolidation runs, unlocks and referrals all move
    to the target device.

    With retire_source=True (the registered-account flow) the source
    device row itself is deleted last, so its old anonymous token stops
    working (401 unknown_device) and the anonymous identity can no
    longer produce new data — the email account is the only identity
    from then on. A later anonymous re-auth under the same client id
    would create a fresh, empty device row; it never resurrects the
    moved data.

    No double-counting: a point event is dropped instead of moved when
    the target already has the same event — same (kind, ref_id) for
    write/read, same (kind, date) for login (the same dedupe rule
    award_point enforces). Idempotent: moved rows no longer live under
    the source, so a repeated merge moves nothing; every run is recorded
    in device_merges for audit. One transaction: all-or-nothing.
    """
    if not source_device_id or source_device_id == target_device_id:
        return dict(ZERO_MERGE)
    now = _now_iso()
    counts = dict(ZERO_MERGE)
    counts["merged"] = True
    with connect() as conn:
        # Letters: ids are globally unique, so a plain reassign is safe.
        cur = conn.execute(
            "UPDATE letters SET device_id = ? WHERE device_id = ?",
            (target_device_id, source_device_id),
        )
        counts["letters_moved"] = cur.rowcount

        # Point events: move, unless the target already has that event.
        src_points = conn.execute(
            "SELECT id, kind, ref_id, date FROM point_events WHERE device_id = ? ORDER BY id",
            (source_device_id,),
        ).fetchall()
        for p in src_points:
            if p["kind"] == "login":
                dup = conn.execute(
                    "SELECT 1 FROM point_events WHERE device_id = ? AND kind = 'login' AND date = ?",
                    (target_device_id, p["date"]),
                ).fetchone()
            elif p["ref_id"] is not None:
                dup = conn.execute(
                    "SELECT 1 FROM point_events WHERE device_id = ? AND kind = ? AND ref_id = ?",
                    (target_device_id, p["kind"], p["ref_id"]),
                ).fetchone()
            else:
                dup = conn.execute(
                    "SELECT 1 FROM point_events WHERE device_id = ? AND kind = ? AND date = ?",
                    (target_device_id, p["kind"], p["date"]),
                ).fetchone()
            if dup:
                conn.execute("DELETE FROM point_events WHERE id = ?", (p["id"],))
                counts["points_dropped_duplicate"] += 1
            else:
                conn.execute(
                    "UPDATE point_events SET device_id = ? WHERE id = ?",
                    (target_device_id, p["id"]),
                )
                counts["points_moved"] += 1

        # Relationships: one row per (device, character). No conflict ->
        # move. Conflict -> the target row wins, except a live source
        # relationship revives an ended target one.
        src_rels = conn.execute(
            "SELECT character_id, status FROM relationships WHERE device_id = ?",
            (source_device_id,),
        ).fetchall()
        for r in src_rels:
            tgt = conn.execute(
                "SELECT status FROM relationships WHERE device_id = ? AND character_id = ?",
                (target_device_id, r["character_id"]),
            ).fetchone()
            if tgt is None:
                conn.execute(
                    "UPDATE relationships SET device_id = ?"
                    " WHERE device_id = ? AND character_id = ?",
                    (target_device_id, source_device_id, r["character_id"]),
                )
                counts["relationships_moved"] += 1
            else:
                if r["status"] == "active" and tgt["status"] == "ended":
                    conn.execute(
                        "UPDATE relationships SET status = 'active', ended_at = NULL,"
                        " reconnect_until = NULL, updated_at = ?"
                        " WHERE device_id = ? AND character_id = ?",
                        (now, target_device_id, r["character_id"]),
                    )
                    counts["relationships_moved"] += 1
                conn.execute(
                    "DELETE FROM relationships WHERE device_id = ? AND character_id = ?",
                    (source_device_id, r["character_id"]),
                )

        # Memories: no per-device unique key, plain reassign.
        cur = conn.execute(
            "UPDATE memories SET device_id = ? WHERE device_id = ?",
            (target_device_id, source_device_id),
        )
        counts["memories_moved"] = cur.rowcount

        # Persona: one row per (device, character). A target row that is
        # still a never-touched default (0 interactions, empty summary)
        # is replaced by the source's lived-in row; otherwise the target
        # row wins and the source row is dropped.
        src_personas = conn.execute(
            "SELECT character_id, relationship_stage, summary, traits,"
            " interaction_count FROM persona WHERE device_id = ?",
            (source_device_id,),
        ).fetchall()
        for p in src_personas:
            tgt = conn.execute(
                "SELECT interaction_count, summary FROM persona"
                " WHERE device_id = ? AND character_id = ?",
                (target_device_id, p["character_id"]),
            ).fetchone()
            if tgt is None:
                conn.execute(
                    "UPDATE persona SET device_id = ? WHERE device_id = ? AND character_id = ?",
                    (target_device_id, source_device_id, p["character_id"]),
                )
            elif (
                tgt["interaction_count"] == 0
                and decrypt_or_keep(tgt["summary"] or "") == ""
            ):
                conn.execute(
                    "DELETE FROM persona WHERE device_id = ? AND character_id = ?",
                    (target_device_id, p["character_id"]),
                )
                conn.execute(
                    "UPDATE persona SET device_id = ? WHERE device_id = ? AND character_id = ?",
                    (target_device_id, source_device_id, p["character_id"]),
                )
            else:
                conn.execute(
                    "DELETE FROM persona WHERE device_id = ? AND character_id = ?",
                    (source_device_id, p["character_id"]),
                )

        # Consolidation runs: one row per (device, character); keep the
        # target's when both exist (the later run is the fresher one).
        src_runs = conn.execute(
            "SELECT character_id FROM consolidation_runs WHERE device_id = ?",
            (source_device_id,),
        ).fetchall()
        for r in src_runs:
            tgt = conn.execute(
                "SELECT 1 FROM consolidation_runs WHERE device_id = ? AND character_id = ?",
                (target_device_id, r["character_id"]),
            ).fetchone()
            if tgt is None:
                conn.execute(
                    "UPDATE consolidation_runs SET device_id = ?"
                    " WHERE device_id = ? AND character_id = ?",
                    (target_device_id, source_device_id, r["character_id"]),
                )
            else:
                conn.execute(
                    "DELETE FROM consolidation_runs WHERE device_id = ? AND character_id = ?",
                    (source_device_id, r["character_id"]),
                )

        # Unlocks: INSERT OR IGNORE moves each grant once.
        cur = conn.execute(
            "INSERT OR IGNORE INTO unlocks (device_id, character_id, source, created_at)"
            " SELECT ?, character_id, source, created_at FROM unlocks WHERE device_id = ?",
            (target_device_id, source_device_id),
        )
        conn.execute("DELETE FROM unlocks WHERE device_id = ?", (source_device_id,))

        # Referrals: the source's invites now come from the target; a
        # referred device already recorded under the target keeps its row.
        conn.execute(
            "UPDATE referrals SET inviter_device_id = ? WHERE inviter_device_id = ?",
            (target_device_id, source_device_id),
        )
        src_refd = conn.execute(
            "SELECT id FROM referrals WHERE referred_device_id = ?",
            (source_device_id,),
        ).fetchall()
        for r in src_refd:
            tgt = conn.execute(
                "SELECT 1 FROM referrals WHERE referred_device_id = ?",
                (target_device_id,),
            ).fetchone()
            if tgt is None:
                conn.execute(
                    "UPDATE referrals SET referred_device_id = ? WHERE id = ?",
                    (target_device_id, r["id"]),
                )
            else:
                conn.execute("DELETE FROM referrals WHERE id = ?", (r["id"],))

        conn.execute(
            "INSERT INTO device_merges (source_device_id, target_device_id,"
            " letters_moved, points_moved, points_dropped_duplicate,"
            " relationships_moved, memories_moved, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                source_device_id, target_device_id,
                counts["letters_moved"], counts["points_moved"],
                counts["points_dropped_duplicate"],
                counts["relationships_moved"], counts["memories_moved"], now,
            ),
        )
        if retire_source:
            # Retire the anonymous identity: its token stops working and
            # it can no longer produce new data. All of its data already
            # lives under the target device (see above).
            conn.execute(
                "DELETE FROM devices WHERE device_id = ?", (source_device_id,)
            )
    return counts


def create_verification_code(email: str, purpose: str, code_hash: str, expires_at: str) -> int:
    with connect() as conn:
        cur = conn.execute(
            "INSERT INTO verification_codes (email, purpose, code_hash, expires_at,"
            " attempts, used, created_at) VALUES (?, ?, ?, ?, 0, 0, ?)",
            (email, purpose, code_hash, expires_at, _now_iso()),
        )
        return cur.lastrowid


def get_latest_unused_code(email: str) -> dict | None:
    """Latest unused code for this email, any purpose (verify/reset share
    the same 6-digit code channel)."""
    with connect() as conn:
        row = conn.execute(
            "SELECT id, email, purpose, code_hash, expires_at, attempts, used, created_at"
            " FROM verification_codes WHERE email = ? AND used = 0"
            " ORDER BY id DESC LIMIT 1",
            (email,),
        ).fetchone()
    return dict(row) if row else None


def increment_code_attempts(code_id: int) -> None:
    with connect() as conn:
        conn.execute(
            "UPDATE verification_codes SET attempts = attempts + 1 WHERE id = ?",
            (code_id,),
        )


def mark_code_used(code_id: int) -> None:
    with connect() as conn:
        conn.execute(
            "UPDATE verification_codes SET used = 1 WHERE id = ?", (code_id,)
        )


def invalidate_codes_for_email(email: str) -> None:
    """Mark every code for this email used (e.g. after a password reset)."""
    with connect() as conn:
        conn.execute(
            "UPDATE verification_codes SET used = 1 WHERE email = ?", (email,)
        )


def store_captcha(token: str, code_hash: str, expires_at: str) -> None:
    with connect() as conn:
        conn.execute(
            "INSERT INTO captchas (token, code_hash, expires_at, created_at)"
            " VALUES (?, ?, ?, ?)",
            (token, code_hash, expires_at, _now_iso()),
        )


def consume_captcha(token: str) -> dict | None:
    """Fetch + delete a captcha in one step: single use, success or fail."""
    with connect() as conn:
        row = conn.execute(
            "SELECT token, code_hash, expires_at, created_at FROM captchas WHERE token = ?",
            (token,),
        ).fetchone()
        if row:
            conn.execute("DELETE FROM captchas WHERE token = ?", (token,))
    return dict(row) if row else None


def record_send_event(email: str, ip: str) -> None:
    with connect() as conn:
        conn.execute(
            "INSERT INTO email_send_events (email, ip, created_at) VALUES (?, ?, ?)",
            (email, ip, _now_iso()),
        )


def count_send_events(email: str | None = None, ip: str | None = None, since: str = "") -> int:
    q = "SELECT COUNT(*) FROM email_send_events WHERE created_at >= ?"
    params: list = [since]
    if email is not None:
        q += " AND email = ?"
        params.append(email)
    if ip is not None:
        q += " AND ip = ?"
        params.append(ip)
    with connect() as conn:
        row = conn.execute(q, params).fetchone()
    return row[0]


def latest_send_event_at(email: str, since: str = "") -> str | None:
    with connect() as conn:
        row = conn.execute(
            "SELECT created_at FROM email_send_events WHERE email = ? AND created_at >= ?"
            " ORDER BY id DESC LIMIT 1",
            (email, since),
        ).fetchone()
    return row["created_at"] if row else None


def record_send_failure(email: str, ip: str) -> None:
    with connect() as conn:
        conn.execute(
            "INSERT INTO email_send_failures (email, ip, created_at) VALUES (?, ?, ?)",
            (email, ip, _now_iso()),
        )


def count_send_failures(email: str | None = None, ip: str | None = None, since: str = "") -> int:
    q = "SELECT COUNT(*) FROM email_send_failures WHERE created_at >= ?"
    params: list = [since]
    if email is not None:
        q += " AND email = ?"
        params.append(email)
    if ip is not None:
        q += " AND ip = ?"
        params.append(ip)
    with connect() as conn:
        row = conn.execute(q, params).fetchone()
    return row[0]
