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
from datetime import date, timedelta

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
