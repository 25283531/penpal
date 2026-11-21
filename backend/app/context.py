"""Per-(user, character) context for reply generation.

Assembles everything the AI needs to reply as this character:
the fixed character setting + verbatim life history, the persona
(stage + summary + traits), live memories (top 20 by evolved
importance, faded excluded), and summaries of the last 3 letters —
NOT full history, so the cost stays flat as the thread grows.

Building the context also registers the recall: every memory
included here gets recall_count + 1 and a small importance bump.
"""
from . import database
from . import evolution


def build_reply_context(device_id: str, character_id: str) -> str:
    parts: list[str] = []
    char = database.get_character(character_id)
    if not char:
        return ""
    parts.append(
        f"【人物设定】{char['name']}，{char['age']} 岁，{char['occupation']}。"
        f"性格：{char['personality']}爱好：{'、'.join(char['hobbies'])}。"
        f"写信风格：{char['writing_style']}"
    )
    parts.append(f"【人生经历（定稿）】{char['life_history']}")

    # How to address the user: registered users chose a virtual-world
    # name — use it naturally, not every sentence. Anonymous users have
    # no name: address them as "你" and never invent one.
    user = database.get_user_by_device(device_id)
    display_name = (user or {}).get("display_name") or ""
    if display_name:
        parts.append(
            f"【对方在这个虚拟世界的名字】对方叫“{display_name}”。"
            "写信时可以自然地用这个名字称呼对方，不用每句都喊，顺其自然就好。"
        )
    else:
        parts.append(
            "【称呼】对方还没有起虚拟世界姓名，写信时用“你”称呼，不要编造名字。"
        )

    persona = database.get_persona(device_id, character_id)
    summary = persona["summary"] or (
        f"我是{char['name']}，我们才刚刚认识，我正在慢慢了解你。"
    )
    traits = persona["traits"]
    parts.append(
        f"【我现在的状态】{summary}\n"
        f"我们现在的关系：{persona['relationship_stage']}（已经通过"
        f" {persona['interaction_count']} 封信交流）。"
        f"我的状态：温暖 {traits.get('warmth', 0.5):.1f}，"
        f"自豪 {traits.get('pride', 0.5):.1f}。"
        "请以这个身份和你对对方的了解写信。"
    )

    # Recent letters, summaries only (first 120 chars each).
    thread = database.list_thread(device_id, character_id)
    recent = thread[-6:]
    if recent:
        lines = []
        for lt in recent:
            who = "对方" if lt["direction"] == "user" else "我"
            lines.append(f"- {who}：{lt['text'][:120]}")
        parts.append("最近的信件（节选）：\n" + "\n".join(lines))

    memories = database.list_memories(device_id, character_id)[:20]
    if memories:
        lines = []
        for m in memories:
            extra = f"（{m['emotion']}）" if m.get("emotion") else ""
            lines.append(f"- [{m['kind']}]{extra} {m['text']}")
        parts.append("关于这位笔友的记忆：\n" + "\n".join(lines))
        evolution.register_recall(device_id, character_id, [m["id"] for m in memories])

    insights = [m for m in memories if m["kind"] == "insight"]
    if insights:
        parts.append(f"【我对对方的最新感悟】{insights[0]['text']}")

    return "\n\n".join(parts)


def build_reply_context_dict(device_id: str, character_id: str) -> dict:
    """Structured version of the same context (for tests / debugging)."""
    persona = database.get_persona(device_id, character_id)
    memories = database.list_memories(device_id, character_id)[:20]
    return {
        "character_id": character_id,
        "persona": {
            "stage": persona["relationship_stage"],
            "summary": persona["summary"],
            "traits": persona["traits"],
            "interaction_count": persona["interaction_count"],
        },
        "recent_letters": database.list_thread(device_id, character_id)[-3:],
        "memories": memories,
        "insight": next((m for m in memories if m["kind"] == "insight"), None),
    }
