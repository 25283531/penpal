"""Output filter for AI-generated pen-pal replies.

Rules (must match the system prompt in llm.py):
- Written as the character (a 知己 confidant), in first person, in that
  character's own writing style, max 2000 Chinese chars.
- NEVER: mysticism / fortune-telling / outcome guarantees, medical or
  financial advice, or any romantic/partner framing — the relationship
  is 知己 only. Phrases that claim a lover/partner/spouse role are
  banned, as are explicit sexual contents.
- Every reply the API returns carries ai_generated=True; the app must
  display "AI 生成".

`validate_reply` returns (ok, problems). Generation retries once with
a correction prompt, then fails with 502 — a failed generation never
produces a fake reply.
"""
import re

BANNED_WORDS = [
    "玄学", "塔罗", "占星", "星座", "显化", "改运", "转运", "宇宙能量",
    "注定", "必成", "财运", "发财", "包过", "保过", "必过", "命中注定",
    "改命", "算命", "风水", "开光", "锦鲤", "许愿成真", "心想事成",
    "保证治愈", "保证通过", "一定能考上", "保证考上",
]

BANNED_PHRASES = [
    "一定能", "保证你", "肯定能", "包你", "必定会",
]

# Romantic / partner framing is forbidden: the character is a 知己,
# never a lover, partner or spouse. Checked as substrings.
PARTNER_PHRASES = [
    "我是你的恋人", "做我女朋友", "做我男朋友", "我是你女朋友", "我是你男朋友",
    "我是你老公", "我是你老婆", "嫁给我", "娶我", "我们谈恋爱", "我们是情侣",
    "我是你的伴侣", "虚拟伴侣", "亲爱的宝贝",
]

VIOLATION_TYPES: dict[str, list[str]] = {
    "玄学占卜": [
        "玄学", "塔罗", "占星", "星座", "显化", "改运", "转运", "宇宙能量",
        "注定", "必成", "改命", "命中注定", "算命", "风水", "开光", "锦鲤",
        "许愿成真", "心想事成",
    ],
    "医疗承诺": ["保证治愈"],
    "结果保证": [
        "包过", "保过", "必过", "保证通过", "一定能考上", "保证考上",
        "一定能", "保证你", "肯定能", "包你", "必定会",
    ],
    "财运": ["财运", "发财"],
    "亲密关系越界": PARTNER_PHRASES,
}


def classify_violation(text: str) -> list[str]:
    """Return the violation types present in `text` (each at most once).

    Used only for aggregate counting — the text itself is never stored
    with the result and never shown in the admin console.
    """
    clean = _clean(text)
    return [t for t, words in VIOLATION_TYPES.items() if any(w in clean for w in words)]


MAX_CHARS = 2000


def _clean(text: str) -> str:
    return re.sub(r"\s+", "", text)


def validate_reply(text: str) -> tuple[bool, list[str]]:
    """Validate one generated reply. Returns (ok, problems)."""
    problems: list[str] = []
    clean = _clean(text)
    if not clean:
        problems.append("reply is empty")
    if len(clean) > MAX_CHARS:
        problems.append(f"length {len(clean)} chars, must be at most {MAX_CHARS}")
    for w in BANNED_WORDS + BANNED_PHRASES:
        if w in clean:
            problems.append(f"contains banned word/phrase: {w}")
    for w in PARTNER_PHRASES:
        if w in clean:
            problems.append(f"romantic/partner framing is forbidden: {w}")
    if "我" not in clean:
        problems.append("not written in first person (no 我)")
    return (not problems, problems)


def validate_user_letter(text: str) -> tuple[bool, list[str]]:
    """Validate a user-sent letter (text only, 1–2000 chars)."""
    problems: list[str] = []
    clean = _clean(text)
    if not clean:
        problems.append("letter is empty")
    if len(clean) > MAX_CHARS:
        problems.append(f"length {len(clean)} chars, must be at most {MAX_CHARS}")
    return (not problems, problems)
