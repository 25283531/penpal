"""Membership tiers + reply scheduling (pure rules, no payment in M0).

Phase 1 is FREE: every device is on the free tier and no payment is
taken. The tier checks still exist and are enforced, so turning on
paid tiers later is a settings change, not a rewrite.

Tiers (from workspace/penpal-app/PLAN.md):
  free    ¥0     1 active character, 1 letter/day, reply every 3 days
  member  ¥9.9   1 active character, 1 letter/day, reply daily
  premium ¥19.9  5 active characters, 5 letters/day, reply daily

Reply schedule: each character's FIRST letter replies SAME DAY;
afterwards free every 3 days, member/premium daily.
"""
from datetime import date, datetime, timedelta, timezone

# Delivery stages for a user's in-transit letter, derived from real
# state only (sent time, due date, whether a reply was generated, now)
# — never a fake animation. `delivered` is the terminal stage once a
# reply has actually been generated and stored.
DELIVERY_STAGES = (
    "posted", "collected", "in_transit", "out_for_delivery", "replying", "delivered",
)

TIERS: dict[str, dict] = {
    "free": {
        "max_active_characters": 1,
        "daily_send_cap": 1,
        "reply_interval_days": 3,
        "price_monthly_cny": 0,
    },
    "member": {
        "max_active_characters": 1,
        "daily_send_cap": 1,
        "reply_interval_days": 1,
        "price_monthly_cny": 9.9,
    },
    "premium": {
        "max_active_characters": 5,
        "daily_send_cap": 5,
        "reply_interval_days": 1,
        "price_monthly_cny": 19.9,
    },
}

PHASE1_FREE = True  # phase 1: no payment, everyone is free


def tier_for(plan: str) -> dict:
    return TIERS.get(plan, TIERS["free"])


def reply_due_date(sent: date, plan: str, is_first: bool) -> date:
    """When a reply is due. First letter to a character: same day.
    Afterwards: free +3 days, member/premium +1 day."""
    if is_first:
        return sent
    return sent + timedelta(days=tier_for(plan)["reply_interval_days"])


def expected_reply_at(sent: date, plan: str, is_first: bool) -> date:
    """Expected reply date for a user letter — the same rule as
    reply_due_date, reused here so the API never invents a second
    schedule. Callers render it as an ISO 8601 date (YYYY-MM-DD)."""
    return reply_due_date(sent, plan, is_first)


def _parse_dt(value) -> datetime | None:
    """Parse a stored timestamp (SQLite 'YYYY-MM-DD HH:MM:SS', ISO with
    'T', or a plain date) into an aware UTC datetime. Naive values are
    treated as UTC, matching SQLite datetime('now')."""
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, date):
        dt = datetime(value.year, value.month, value.day)
    elif isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
        if isinstance(dt, date) and not isinstance(dt, datetime):
            dt = datetime(dt.year, dt.month, dt.day)
    else:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _parse_date(value) -> date | None:
    dt = _parse_dt(value)
    return dt.date() if dt else None


def delivery_stage(sent_at, due_at, replied: bool, *, city: str = "",
                   name: str = "", now: datetime | None = None) -> tuple[str, str]:
    """Derive (stage, poetic Chinese text) for a user's sent letter.

    - replied: the reply was actually generated -> "delivered".
    - same-day due (first letter): stages advance by hours since sent
      (<1h posted, <4h collected, <8h in transit, <16h out for
      delivery, then replying).
    - multi-day due: stages advance by elapsed fraction of the
      sent -> due interval (<0.20 posted, <0.40 collected, <0.65 in
      transit, <0.90 out for delivery, then replying). Overdue and
      still unreplied stays at "replying" — the character is writing.
    `city` is the character's city (for the in-transit line) and `name`
    the character's name (for the replying line).
    """
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    if replied:
        return "delivered", "回信已送达，正在等你拆开，慢慢读。"
    sent_dt = _parse_dt(sent_at)
    due_date = _parse_date(due_at)
    if sent_dt is None or due_date is None:
        return "posted", "你的信已投进邮箱，信封还带着你的温度，正在等邮差来取。"
    sent_date = sent_dt.date()
    total_days = (due_date - sent_date).days
    if total_days <= 0:
        hours = max(0.0, (now - sent_dt).total_seconds() / 3600.0)
        if hours < 1:
            stage = "posted"
        elif hours < 4:
            stage = "collected"
        elif hours < 8:
            stage = "in_transit"
        elif hours < 16:
            stage = "out_for_delivery"
        else:
            stage = "replying"
    else:
        # Multi-day due: elapsed fraction of the sent -> due interval,
        # measured in hours (date-only progress would jump 0 -> 1/3 ->
        # 2/3 and skip the in-transit stage entirely on a 3-day cycle).
        total_seconds = total_days * 86400.0
        elapsed = max(0.0, (now - sent_dt).total_seconds())
        progress = elapsed / total_seconds
        if progress < 0.20:
            stage = "posted"
        elif progress < 0.40:
            stage = "collected"
        elif progress < 0.65:
            stage = "in_transit"
        elif progress < 0.90:
            stage = "out_for_delivery"
        else:
            stage = "replying"
    if stage == "posted":
        text = "你的信已投进邮箱，信封还带着你的温度，正在等邮差来取。"
    elif stage == "collected":
        text = "邮差已经收走了你的信，它正揣着你的心事，离开这条街。"
    elif stage == "in_transit":
        dest = f"赶往{city}" if city else "在路上"
        who = f"，去见{name}" if name else ""
        text = f"你的信正{dest}，穿过山川与灯火{who}。"
    elif stage == "out_for_delivery":
        who = f"{name}的" if name else ""
        text = f"你的信快到了，{who}信箱就在眼前，只差最后一段路。"
    else:  # replying
        who = name or "他"
        text = f"{who}已经读完了你的信，正在灯下，一字一句给你回信。"
    return stage, text
