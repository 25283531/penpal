"""Personified, self-evolving memory for each pen-pal character.

Ported from future-me's evolution.py, scoped per (device_id,
character_id) pair: every character remembers the user separately —
character A can never recall character B's letters.

- **Relationship stages** (by user letters sent, not days):
  初识 (1–2) → 熟悉 (3–6) → 默契 (7–14) → 知己 (15+).
- **Recall strengthens memory**: every time a memory is included in an
  assembled LLM context, recall_count +1, importance +0.05 (cap 1.0).
- **Fading / forgetting**: memories left unrecalled for 30+ days lose
  0.02 importance/day (floor 0.1); below 0.15 and older than 60 days
  they are marked faded — soft fade, data never deleted.
- **Consolidation**: at most once per (device, character) per day,
  recent letters are turned into durable memories (dedupe, trivia
  dropped, at most one insight). The persona summary is rewritten in
  the character's own first-person voice. Without an LLM key the
  rule-based pass still runs — consolidation never fails a request.

No open-source memory project, no embeddings, no vector DB: plain
SQLite + rule-based decay + at most one LLM call per pair per day.
"""
import json
from datetime import date, datetime, timedelta, timezone

from . import database
from .content_filter import BANNED_WORDS
from .llm import LLMError, LLMNotConfigured, chat_complete

# Relationship stages: (minimum user letters sent, stage name).
STAGE_THRESHOLDS = [(15, "知己"), (7, "默契"), (3, "熟悉"), (1, "初识")]

FADE_IDLE_DAYS = 30
FADE_DECAY_PER_DAY = 0.02
FADE_THRESHOLD = 0.15
FADE_MIN_AGE_DAYS = 60
IMPORTANCE_FLOOR = 0.1
IMPORTANCE_MAX = 1.0
RECALL_BUMP = 0.05

LOW_EMOTIONS = {"低落", "焦虑", "难过", "沮丧"}

CONSOLIDATION_SYSTEM = """你是一位虚拟笔友，正在整理自己对这位笔友的记忆。你的任务是把最近的
信件往来提炼成值得长期记住的记忆，并更新你对自己的介绍。

硬性规则：
1. 用第一人称“我”的口吻写，就像在回忆和这个人一起写信的日子。
2. 每条记忆不超过 60 个字，只记 durable 的东西：对方的目标、习惯、感受、转折点；
   丢掉琐事（某一天写了信、某天说了什么例行的话）。
3. 绝对禁止出现：玄学、塔罗、占星、星座、显化、改运、转运、宇宙能量、注定、
   必成、财运、发财、包过、保过、算命、风水；不承诺任何结果，不写医疗/理财建议。
4. 绝对禁止任何恋人/伴侣/配偶的表述：你们是知己，不是恋人。
5. 最多写 5 条记忆；其中最多 1 条 kind 为 insight（你从这些记忆里看出的关于
   对方的规律，例如“我发现你每次遇到困难都会先给自己打气”）。
6. persona_summary 是你对自己的简短介绍（100 字以内，第一人称），要提到你记得
   的事和你们现在的关系，温暖、具体。

只返回 JSON，不要任何其他文字：
{"memories": [{"kind": "milestone|progress|note|emotion|insight", "text": "...", "emotion": "开心|低落|坚定|焦虑|自豪", "importance": 0.7}], "persona_summary": "..."}
kind 为 insight 的那条不要填 emotion；其他 kind 的 emotion 可空。
"""


def stage_for(letter_count: int) -> str:
    """Relationship stage for a user-letter count."""
    for threshold, stage in STAGE_THRESHOLDS:
        if letter_count >= threshold:
            return stage
    return "初识"


def _today() -> date:
    return date.today()


def _utcnow_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _parse_day(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


_TRAIT_NUDGES = {
    "letter": {"warmth": 0.02, "pride": 0.01},
    "reply": {"warmth": 0.01},
    "read": {"warmth": 0.01},
}


def record_interaction(
    device_id: str, character_id: str, event: str | None = None,
) -> dict:
    """Count one user letter (interaction_count = user letters sent),
    advance the relationship stage, nudge traits."""
    persona = database.get_persona(device_id, character_id)
    count = persona["interaction_count"] + 1
    traits = dict(persona["traits"])
    if event in _TRAIT_NUDGES:
        for trait, delta in _TRAIT_NUDGES[event].items():
            traits[trait] = max(0.0, min(1.0, traits.get(trait, 0.5) + delta))
    return database.update_persona(
        device_id,
        character_id,
        {
            "interaction_count": count,
            "relationship_stage": stage_for(count),
            "traits": traits,
        },
    )


def register_recall(device_id: str, character_id: str, memory_ids: list[int]) -> None:
    database.touch_memories(device_id, character_id, memory_ids)


def apply_fading(device_id: str, character_id: str, today: date | None = None) -> dict:
    today = today or _today()
    decayed = 0
    faded = 0
    for m in database.list_memories(device_id, character_id):
        ref = _parse_day(m.get("last_recalled_at")) or _parse_day(m["created_at"])
        created = _parse_day(m["created_at"])
        if ref is None:
            continue
        idle = (today - ref).days
        new_importance = m["importance"]
        if idle > FADE_IDLE_DAYS:
            new_importance = max(
                IMPORTANCE_FLOOR,
                m["importance"] - FADE_DECAY_PER_DAY * (idle - FADE_IDLE_DAYS),
            )
        updates: dict = {}
        if new_importance != m["importance"]:
            updates["importance"] = new_importance
            decayed += 1
        age = (today - created).days if created else 0
        if new_importance < FADE_THRESHOLD and age > FADE_MIN_AGE_DAYS:
            updates["faded"] = 1
            faded += 1
        if updates:
            database.update_memory(m["id"], updates)
    return {"decayed": decayed, "faded": faded}


def _evolution_enabled() -> bool:
    return database.get_setting("memory.evolution_enabled", "1") == "1"


def _reflection_enabled() -> bool:
    return database.get_setting("memory.reflection_enabled", "1") == "1"


def _consolidation_interval_days() -> int:
    try:
        n = int(database.get_setting("memory.consolidation_interval_days", "1"))
    except ValueError:
        n = 1
    return max(1, min(7, n))


def consolidation_due(device_id: str, character_id: str) -> bool:
    if not _evolution_enabled():
        return False
    last = database.get_consolidation_last_run(device_id, character_id)
    if last is None:
        return True
    last_day = _parse_day(last)
    if last_day is None:
        return True
    return (_today() - last_day).days >= _consolidation_interval_days()


def _dedupe_memories(device_id: str, character_id: str) -> int:
    seen: dict[tuple[str, str], dict] = {}
    removed = 0
    for m in database.list_memories(device_id, character_id, include_faded=True):
        key = (m["kind"], m["text"])
        if key in seen:
            keep = seen[key]
            if m["importance"] > keep["importance"]:
                database.delete_memory(keep["id"])
                seen[key] = m
            else:
                database.delete_memory(m["id"])
            removed += 1
        else:
            seen[key] = m
    return removed


def _rule_based_summary(device_id: str, character_id: str) -> str:
    char = database.get_character(character_id) or {}
    persona = database.get_persona(device_id, character_id)
    letters = database.count_user_letters(device_id, character_id)
    top = database.list_memories(device_id, character_id)
    text = (
        f"我是{char.get('name', '你的笔友')}，{char.get('occupation', '')}。"
        f"我们已经通过 {letters} 封信认识了，现在是{persona['relationship_stage']}的关系。"
    )
    if top:
        text += f"我记得你{top[0]['text'][:30]}。"
    text += "我会一直记得这些，慢慢回你的每一封信。"
    return text


def _clean_llm_output(raw: str) -> dict | None:
    try:
        start = raw.index("{")
        end = raw.rindex("}") + 1
        data = json.loads(raw[start:end])
    except (ValueError, IndexError):
        return None
    if not isinstance(data, dict):
        return None
    return data


def _banned(text: str) -> bool:
    clean = text.replace(" ", "").replace("\n", "")
    return any(w in clean for w in BANNED_WORDS)


def _apply_llm_consolidation(device_id: str, character_id: str, data: dict) -> dict:
    added = 0
    insight_written = False
    reflection = _reflection_enabled()
    existing = {(m["kind"], m["text"]) for m in database.list_memories(device_id, character_id, include_faded=True)}
    for item in (data.get("memories") or [])[:5]:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or "").strip()
        if not text or len(text) > 200 or _banned(text):
            continue
        kind = str(item.get("kind") or "note")
        if kind not in database.MEMORY_KINDS:
            kind = "note"
        if kind == "insight":
            if not reflection or insight_written:
                continue
            insight_written = True
        if (kind, text) in existing:
            continue
        try:
            importance = float(item.get("importance") or 0.6)
        except (TypeError, ValueError):
            importance = 0.6
        emotion = item.get("emotion") if kind != "insight" else None
        if emotion is not None:
            emotion = str(emotion)[:10] or None
        database.create_memory(
            device_id, character_id, kind, text,
            importance=database.normalize_importance(importance),
            emotion=emotion,
        )
        existing.add((kind, text))
        added += 1
    persona_updated = False
    summary = str(data.get("persona_summary") or "").strip()
    if summary and len(summary) <= 200 and not _banned(summary):
        database.update_persona(device_id, character_id, {"summary": summary})
        persona_updated = True
    return {"added": added, "insight": insight_written, "persona_updated": persona_updated}


def _consolidation_prompt(events: dict, memories: list[dict]) -> tuple[str, str]:
    lines: list[str] = []
    if events["letters"]:
        lines.append("最近的信件往来（节选）：")
        for lt in events["letters"]:
            who = "对方" if lt["direction"] == "user" else "我"
            lines.append(f"- {who}：{lt['text']}")
    if memories:
        lines.append("已有的记忆：")
        for m in memories[:10]:
            lines.append(f"- [{m['kind']}] {m['text']}")
    user = (
        "最近发生的事情如下（没有新事情就只整理已有的记忆）：\n"
        + ("\n".join(lines) if lines else "（无新事情）")
        + "\n\n请按规则输出 JSON。"
    )
    return CONSOLIDATION_SYSTEM, user


def run_consolidation(device_id: str, character_id: str, force: bool = False) -> dict:
    """One consolidation run for a (device, character) pair. Never raises."""
    if not _evolution_enabled():
        return {"status": "disabled"}
    if not force and not consolidation_due(device_id, character_id):
        return {"status": "skipped"}
    try:
        last_run = database.get_consolidation_last_run(device_id, character_id)
        events = database.events_since(device_id, character_id, last_run)
        deduped = _dedupe_memories(device_id, character_id)
        fade = apply_fading(device_id, character_id)
        has_events = bool(events["letters"])
        persona_updated = False
        added = 0
        insight = False
        if has_events:
            try:
                memories = database.list_memories(device_id, character_id)[:10]
                system, user = _consolidation_prompt(events, memories)
                raw = chat_complete(system, user, max_tokens=800, temperature=0.7)
                data = _clean_llm_output(raw)
                if data:
                    out = _apply_llm_consolidation(device_id, character_id, data)
                    added = out["added"]
                    insight = out["insight"]
                    persona_updated = out["persona_updated"]
            except (LLMNotConfigured, LLMError):
                pass
        if not persona_updated:
            database.update_persona(
                device_id, character_id, {"summary": _rule_based_summary(device_id, character_id)}
            )
            persona_updated = True
        recent_low = [
            m for m in database.list_memories(device_id, character_id)
            if m.get("emotion") in LOW_EMOTIONS
            and (_parse_day(m["created_at"]) or _today()) >= _today() - timedelta(days=7)
        ]
        if recent_low:
            persona = database.get_persona(device_id, character_id)
            traits = dict(persona["traits"])
            traits["warmth"] = max(0.0, min(1.0, traits.get("warmth", 0.5) + 0.05))
            database.update_persona(device_id, character_id, {"traits": traits})
        database.set_consolidation_last_run(device_id, character_id, _utcnow_str())
        return {
            "status": "done",
            "deduped": deduped,
            "decayed": fade["decayed"],
            "faded": fade["faded"],
            "memories_added": added,
            "insight": insight,
            "persona_updated": persona_updated,
        }
    except Exception:
        return {"status": "error"}


def after_interaction(
    device_id: str, character_id: str, event: str | None = None,
    used_memory_ids: list[int] | None = None,
) -> None:
    """Wire evolution into a user flow: count the letter, strengthen the
    memories this call used, and run a lazy consolidation when due.
    Never fails the request."""
    record_interaction(device_id, character_id, event=event)
    if used_memory_ids:
        register_recall(device_id, character_id, used_memory_ids)
    try:
        if consolidation_due(device_id, character_id):
            run_consolidation(device_id, character_id)
    except Exception:
        pass
