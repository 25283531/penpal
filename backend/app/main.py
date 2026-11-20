"""笔友 (Penpal) backend — FastAPI + SQLite. M0, backend only.

Slow letters with virtual pen pals (知己 confidants, never lovers):
a user writes a text-only letter (max 2000 chars) to one of P01–P05;
the character replies once, on a schedule — first letter same day,
then free every 3 days / member+premium daily. One outstanding letter
per character (turn-taking); daily send cap per user per day (free/
member 1, premium 5) — reaching the cap blocks further sends that day
even to a different character.

Anonymous device auth with an age gate (age is required at
registration; under-14s are refused, 14–17s get minor_mode=1; full
minor mode is M2). Phase 1 is FREE: everyone is on the free tier, no
payment is taken; tier checks are enforced anyway.

All API keys live in the SQLite settings table (admin console /admin).
User content (letters / memories / persona summaries) is encrypted at
rest (see crypto.py); the admin console only ever sees aggregate
numbers, never user text. A reply is only 'replied' when the LLM
actually generated and stored it — without an LLM key, letters stay
queued (never a fake reply).
"""
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse
from pydantic import BaseModel, Field

from . import admin, database, evolution
from .auth import get_current_device, issue_token
from .characters import BY_ID, public_character
from .content_filter import validate_user_letter
from .llm import list_llm_providers
from .membership import PHASE1_FREE, reply_due_date, tier_for
from .replies import process_due_replies


@asynccontextmanager
async def lifespan(_app: FastAPI):
    database.init_db()
    yield


app = FastAPI(title="笔友 Penpal API", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(admin.router)


@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse("/admin", status_code=302)


@app.get("/admin", include_in_schema=False)
def admin_page():
    path = Path(__file__).resolve().parent / "admin.html"
    return FileResponse(path, media_type="text/html")


# ---------- schemas ----------

class DeviceAuthIn(BaseModel):
    device_id: str = Field(..., min_length=1, max_length=128)
    age: int | None = Field(None, ge=1, le=120)
    emergency_contact: str | None = Field(None, max_length=128)


class LetterIn(BaseModel):
    character_id: str
    # No max_length here: the 2000-char limit is enforced by
    # validate_user_letter so it returns 400 (not Pydantic's 422).
    text: str = Field(..., min_length=1)


class ProcessDueIn(BaseModel):
    date: str | None = None  # "YYYY-MM-DD"; test/simulation override, default today


class ReferralIn(BaseModel):
    referred_device_id: str = Field(..., min_length=1, max_length=128)


# ---------- helpers ----------

def _device_plan(device_id: str) -> tuple[dict, dict]:
    device = database.get_device(device_id)
    plan = device["plan"] if device else "free"
    return device, tier_for(plan)


def _public_letter(letter: dict) -> dict:
    return {
        "id": letter["id"],
        "character_id": letter["character_id"],
        "direction": letter["direction"],
        "text": letter["text"],
        "status": letter["status"],
        "reply_due_at": letter.get("reply_due_at"),
        "is_first": bool(letter.get("is_first")),
        "ai_generated": bool(letter.get("ai_generated")),
        "ai_label": "AI 生成" if letter.get("ai_generated") else None,
        "read_at": letter.get("read_at"),
        "created_at": letter["created_at"],
        "replied_at": letter.get("replied_at"),
    }


# ---------- health / auth ----------

@app.get("/api/v1/health")
def health():
    providers = [p["id"] for p in list_llm_providers() if p["configured"]]
    return {
        "status": "ok",
        "version": app.version,
        "port": 7000,
        "phase1_free": PHASE1_FREE,
        "providers_configured": providers,
    }


@app.post("/api/v1/auth/device")
def auth_device(body: DeviceAuthIn):
    device_id = body.device_id.strip()
    try:
        device = database.get_or_create_device(
            device_id, age=body.age, emergency_contact=body.emergency_contact,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    database.award_point(device_id, "login")
    return {
        "token": issue_token(device["device_id"]),
        "device_id": device["device_id"],
        "plan": device["plan"],
        "minor_mode": bool(device["minor_mode"]),
        "age": device["age"],
    }


@app.post("/api/v1/auth/login")
def auth_login(device_id: str = Depends(get_current_device)):
    awarded = database.award_point(device_id, "login")
    return {"device_id": device_id, "points_awarded": awarded, "points": database.points_balance(device_id)}


# ---------- characters ----------

@app.get("/api/v1/characters")
def list_characters(device_id: str = Depends(get_current_device)):
    unlocked = set(database.unlocked_character_ids(device_id))
    return [
        {**public_character(c), "unlocked": c["id"] in unlocked}
        for c in database.list_characters()
    ]


@app.get("/api/v1/characters/{character_id}")
def get_character(character_id: str, device_id: str = Depends(get_current_device)):
    char = database.get_character(character_id)
    if not char:
        raise HTTPException(status_code=404, detail="character not found")
    unlocked = character_id in database.unlocked_character_ids(device_id)
    return {**public_character(char), "unlocked": unlocked}


# ---------- letters ----------

@app.post("/api/v1/letters", status_code=status.HTTP_201_CREATED)
def send_letter(body: LetterIn, device_id: str = Depends(get_current_device)):
    ok, problems = validate_user_letter(body.text)
    if not ok:
        raise HTTPException(status_code=400, detail="; ".join(problems))
    character_id = body.character_id.strip()
    char = database.get_character(character_id)
    if not char:
        raise HTTPException(status_code=404, detail="character not found")
    if character_id not in database.unlocked_character_ids(device_id):
        raise HTTPException(status_code=403, detail="character is locked; unlock it first")
    device, tier = _device_plan(device_id)

    # 1. Turn-taking: one outstanding letter per character (checked
    # first so a double-send to the same character gets the specific
    # 409, not the generic daily-cap 429).
    if database.outstanding_letter(device_id, character_id):
        raise HTTPException(
            status_code=409,
            detail="this character has an unanswered letter; wait for the reply before writing again",
        )
    # 2. Daily send cap (per user per day, not per character).
    if database.count_today_sends(device_id) >= tier["daily_send_cap"]:
        raise HTTPException(
            status_code=429,
            detail=f"daily send limit reached ({tier['daily_send_cap']} letter(s) per day for the {device['plan']} plan)",
        )
    # 3. Relationship must be active (auto-start if a slot is free).
    rel = database.get_relationship(device_id, character_id)
    if not rel or rel["status"] != "active":
        try:
            database.start_relationship(device_id, character_id, tier["max_active_characters"])
        except ValueError as e:
            raise HTTPException(status_code=409, detail=str(e)) from e

    is_first = database.count_user_letters(device_id, character_id) == 0
    due = reply_due_date(date.today(), device["plan"], is_first)
    letter = database.create_user_letter(
        device_id, character_id, body.text.strip(), due.isoformat(), is_first,
    )
    database.award_point(device_id, "write", ref_id=str(letter["id"]))
    database.mark_referral_successful(device_id)
    evolution.after_interaction(device_id, character_id, event="letter")
    return _public_letter(letter)


def _thread_visible(device_id: str, character_id: str) -> None:
    """A thread is user-visible while the relationship is active or
    inside its 30-day reconnect window. Past the window the user sees
    nothing (410) — the encrypted server data is retained for
    legal/audit only."""
    rel = database.get_relationship(device_id, character_id)
    if rel and rel["status"] == "ended":
        if not rel.get("reconnect_until") or rel["reconnect_until"] < date.today().isoformat():
            raise HTTPException(
                status_code=410,
                detail="this relationship ended more than 30 days ago and is no longer visible to you",
            )


@app.get("/api/v1/letters")
def list_letters(character_id: str | None = None, device_id: str = Depends(get_current_device)):
    if character_id:
        if not database.get_character(character_id):
            raise HTTPException(status_code=404, detail="character not found")
        _thread_visible(device_id, character_id)
        return [_public_letter(l) for l in database.list_thread(device_id, character_id)]
    return [_public_letter(l) for l in database.list_all_letters(device_id)]


@app.get("/api/v1/letters/{letter_id}")
def get_letter(letter_id: int, device_id: str = Depends(get_current_device)):
    letter = database.get_letter(device_id, letter_id)
    if not letter:
        raise HTTPException(status_code=404, detail="letter not found")
    _thread_visible(device_id, letter["character_id"])
    return _public_letter(letter)


@app.post("/api/v1/letters/{letter_id}/read")
def read_letter(letter_id: int, device_id: str = Depends(get_current_device)):
    letter = database.get_letter(device_id, letter_id)
    if not letter:
        raise HTTPException(status_code=404, detail="letter not found")
    if letter["direction"] != "ai":
        raise HTTPException(status_code=400, detail="only AI replies can be marked read")
    was_unread = not letter.get("read_at")
    letter = database.mark_letter_read(device_id, letter_id)
    awarded = 0
    if was_unread:
        awarded = database.award_point(device_id, "read", ref_id=str(letter_id))
    return {**_public_letter(letter), "points_awarded": awarded}


@app.post("/api/v1/letters/process-due")
def process_due(body: ProcessDueIn | None = None, device_id: str = Depends(get_current_device)):
    day = (body.date if body else None) or date.today().isoformat()
    try:
        date.fromisoformat(day)
    except ValueError as e:
        raise HTTPException(status_code=400, detail="date must be YYYY-MM-DD") from e
    return process_due_replies(device_id, day)


# ---------- relationships ----------

@app.get("/api/v1/relationships")
def list_relationships(device_id: str = Depends(get_current_device)):
    return database.list_relationships(device_id)


@app.post("/api/v1/relationships/{character_id}/end")
def end_relationship(character_id: str, device_id: str = Depends(get_current_device)):
    rel = database.end_relationship(device_id, character_id)
    if not rel:
        raise HTTPException(status_code=404, detail="relationship not found")
    return {
        **rel,
        "note": "30 天内可以再次联系到原来的人物；超过 30 天后 App 里不再显示这段关系，"
                "服务端仍加密留存（依法留存），用户侧不可恢复。",
    }


@app.post("/api/v1/relationships/{character_id}/reconnect")
def reconnect_relationship(character_id: str, device_id: str = Depends(get_current_device)):
    device, tier = _device_plan(device_id)
    try:
        rel = database.reconnect_relationship(
            device_id, character_id, tier["max_active_characters"]
        )
    except ValueError as e:
        # Past the 30-day window: user-side gone (410).
        if "30 days" in str(e):
            raise HTTPException(status_code=410, detail=str(e)) from e
        raise HTTPException(status_code=409, detail=str(e)) from e
    return rel


# ---------- points / unlocks / referrals ----------

@app.get("/api/v1/points")
def get_points(device_id: str = Depends(get_current_device)):
    return {
        "points": database.points_balance(device_id),
        "events": database.list_point_events(device_id),
    }


@app.get("/api/v1/unlocks")
def get_unlocks(device_id: str = Depends(get_current_device)):
    points = database.points_balance(device_id)
    refs = database.referral_count(device_id)
    return {
        "points": points,
        "referral_count": refs,
        "points_unlocks": database.points_unlocks(points),
        "referral_unlocks": database.referral_unlocks(refs),
        "entitled_character_ids": database.evaluate_unlocks(device_id),
        "unlocked_character_ids": database.unlocked_character_ids(device_id),
        "thresholds": {"points": [100, 300], "referrals": [1, 10, 30, 40, 50]},
    }


@app.post("/api/v1/referrals", status_code=status.HTTP_201_CREATED)
def record_referral(body: ReferralIn, device_id: str = Depends(get_current_device)):
    try:
        return database.record_referral(device_id, body.referred_device_id.strip())
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


# ---------- LLM providers ----------

@app.get("/api/v1/llm/providers")
def list_providers(device_id: str = Depends(get_current_device)):
    return list_llm_providers()


# ---------- activities / messages (fetch-on-open) ----------

@app.get("/api/v1/activities")
def list_activities(device_id: str = Depends(get_current_device)):
    return [
        {
            "id": a["id"], "title": a["title"], "body": a["body"],
            "image_url": a["image_url"], "start_at": a["start_at"],
            "end_at": a["end_at"], "active": bool(a["active"]),
        }
        for a in database.list_activities()
    ]


@app.get("/api/v1/messages")
def list_messages(device_id: str = Depends(get_current_device)):
    return [
        {"id": m["id"], "title": m["title"], "body": m["body"], "created_at": m["created_at"]}
        for m in database.list_messages()
    ]


# ---------- membership (phase 1: free, no payment) ----------

@app.get("/api/v1/membership/status")
def membership_status(device_id: str = Depends(get_current_device)):
    device, tier = _device_plan(device_id)
    return {
        "plan": device["plan"],
        "phase1_free": PHASE1_FREE,
        "paywalled": False,
        "max_active_characters": tier["max_active_characters"],
        "daily_send_cap": tier["daily_send_cap"],
        "reply_interval_days": tier["reply_interval_days"],
        "price_member_cny": 9.9,
        "price_premium_cny": 19.9,
    }
