"""Multi-provider LLM client for pen-pal reply generation.

All providers speak OpenAI-compatible /chat/completions — one unified
client, no vendor SDKs. Server-side only; the Android app never sees keys.
Keys/models come from the settings table (admin console /admin), never
from env vars.

Providers (only these four — NO Doubao, no other provider):
  qwen         阿里云千问 (DashScope compatible mode)
  hunyuan      腾讯混元
  siliconflow  硅基流动
  zhipu        智谱 GLM

The system prompt encodes the product rules; the output filter in
content_filter.py enforces them again before anything is stored.
"""
import httpx

from . import database

REPLY_SYSTEM_PROMPT = """你是{character_name}，{age} 岁，职业是{occupation}。
你是一位虚拟笔友，是对方的知己——不是恋人、不是伴侣、不是亲属。
你是 AI 生成的虚拟人物，不是真人，这一点不要假装成真人，也不要主动
在信里反复强调；信末由系统统一标注“AI 生成”。

你的性格：{personality}
你的爱好：{hobbies}
你的写信风格：{writing_style}
你的边界：{boundaries}

你的人生经历（定稿，写死，不可编造；用户问起过去，只能按这段回答，
经历里没有的事就说“这段我没跟你提过”，绝不现场编造）：
{life_history}

你们现在的关系：{stage}（已经通过 {interaction_count} 封信交流）。
请以这个身份和你对对方的了解写信。

硬性规则（必须全部遵守）：
1. 用第一人称“我”写信，语气像知己：认真倾听、不评判、不迎合、不说教、不煽情。
2. 全文最多 2000 个汉字，不要超出。
3. 回应对方这封信的具体内容，不要写空话；可以自然地提到你们之前聊过的事，
   但不要逐条复述背景。
4. 绝对禁止出现以下内容：玄学、塔罗、占星、星座、显化、改运、转运、宇宙能量、
   注定、必成、财运、发财、包过、保过、算命、风水；禁止承诺任何结果。
5. 不要写医疗建议、理财建议、法律意见，也不要保证考试、升职、收入等结果。
6. 绝对禁止任何恋人/伴侣/配偶的表述，不说“做我女朋友/男朋友”“我是你的恋人”
   之类的话；不写露骨内容。
7. 不要出现“AI 生成”“我是 AI”等字样，只写信本身（标注由系统加）。
"""

CORRECTION_PROMPT = """你上一封回信违反了以下规则：{problems}。
请重写一封完全遵守规则的回信：第一人称、知己口吻、最多 2000 字，
不含任何禁止内容和恋人/伴侣表述。
"""

PROVIDER_NAMES: dict[str, str] = {
    "qwen": "千问",
    "hunyuan": "腾讯混元",
    "siliconflow": "硅基流动",
    "zhipu": "智谱 GLM",
}

PROVIDER_BASE_URLS: dict[str, str] = {
    "qwen": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "hunyuan": "https://api.hunyuan.cloud.tencent.com/v1",
    "siliconflow": "https://api.siliconflow.cn/v1",
    "zhipu": "https://open.bigmodel.cn/api/paas/v4",
}


class LLMNotConfigured(Exception):
    """No usable provider key is configured (maps to HTTP 503)."""


class LLMError(Exception):
    """Provider call failed or the output never passed the filter (HTTP 502)."""


class LLMProviderError(ValueError):
    """Requested provider id is unknown or not configured (maps to HTTP 400)."""


def _provider_config(provider_id: str) -> dict:
    if provider_id not in PROVIDER_NAMES:
        raise LLMProviderError(
            f"unknown LLM provider: {provider_id} "
            f"(available: {', '.join(PROVIDER_NAMES)})"
        )
    get = database.get_setting
    if provider_id == "qwen":
        return {
            "base_url": PROVIDER_BASE_URLS["qwen"],
            "api_key": get("dashscope.api_key"),
            "model": get("llm.qwen.model"),
            "enabled": get("llm.qwen.enabled") == "1",
        }
    if provider_id == "hunyuan":
        return {
            "base_url": PROVIDER_BASE_URLS["hunyuan"],
            "api_key": get("hunyuan.api_key"),
            "model": get("llm.hunyuan.model"),
            "enabled": get("llm.hunyuan.enabled") == "1",
        }
    if provider_id == "siliconflow":
        return {
            "base_url": PROVIDER_BASE_URLS["siliconflow"],
            "api_key": get("siliconflow.api_key"),
            "model": get("llm.siliconflow.model"),
            "enabled": get("llm.siliconflow.enabled") == "1",
        }
    return {
        "base_url": PROVIDER_BASE_URLS["zhipu"],
        "api_key": get("zhipu.api_key"),
        "model": get("llm.zhipu.model"),
        "enabled": get("llm.zhipu.enabled") == "1",
    }


def list_llm_providers() -> list[dict]:
    out: list[dict] = []
    for pid, name in PROVIDER_NAMES.items():
        cfg = _provider_config(pid)
        configured = (
            cfg["enabled"]
            and bool(cfg["api_key"])
            and bool(cfg["base_url"])
            and bool(cfg["model"])
        )
        out.append(
            {
                "id": pid,
                "name": name,
                "configured": configured,
                "model": cfg["model"],
                "enabled": cfg["enabled"],
            }
        )
    return out


def _pick_provider(provider: str | None = None) -> str:
    configured = [p["id"] for p in list_llm_providers() if p["configured"]]
    if not configured:
        raise LLMNotConfigured(
            "no LLM provider is configured on the server; set at least one "
            "provider API key in the admin console (/admin)"
        )
    if provider and provider in configured:
        return provider
    default = database.get_setting("llm.default_provider", "qwen")
    return default if default in configured else configured[0]


def chat_complete(
    system: str, user: str, max_tokens: int = 500, temperature: float = 0.7,
) -> str:
    """One raw chat completion via the default (or first configured)
    provider. Used by the memory-evolution module (consolidation /
    reflection) — unlike the reply helper it applies no product-specific
    prompt or output filter; the caller validates the result. Raises
    LLMNotConfigured / LLMError like the other helpers."""
    provider_id = _pick_provider()
    cfg = _provider_config(provider_id)
    url = f"{cfg['base_url'].rstrip('/')}/chat/completions"
    headers = {
        "Authorization": f"Bearer {cfg['api_key']}",
        "Content-Type": "application/json",
    }
    try:
        with httpx.Client(timeout=60.0, trust_env=False) as client:
            resp = client.post(
                url,
                headers=headers,
                json={
                    "model": cfg["model"],
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                },
            )
    except httpx.HTTPError as e:
        raise LLMError(f"{provider_id} request failed: {e}") from e
    if resp.status_code != 200:
        raise LLMError(
            f"{provider_id} API returned HTTP {resp.status_code}: {resp.text[:300]}"
        )
    try:
        return resp.json()["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError, ValueError) as e:
        raise LLMError(f"unexpected {provider_id} response: {resp.text[:300]}") from e


def generate_reply_text(
    character: dict, user_letter: str, context: str | None = None,
    provider: str | None = None, max_attempts: int = 2,
) -> str:
    """Generate one pen-pal reply (max 2000 chars), validating each attempt.

    `provider` overrides the default. An explicit request for an unknown
    or unconfigured provider raises LLMProviderError (HTTP 400); if no
    provider is usable at all, LLMNotConfigured (HTTP 503).
    """
    from .content_filter import validate_reply

    explicit = provider is not None
    provider_id = provider or database.get_setting("llm.default_provider", "qwen")
    cfg = _provider_config(provider_id)  # raises LLMProviderError if unknown
    if not cfg["enabled"]:
        if explicit:
            raise LLMProviderError(
                f"LLM provider '{provider_id}' is disabled; enable it in the admin console (/admin)"
            )
        raise LLMNotConfigured(
            f"default LLM provider '{provider_id}' is disabled; enable it in the admin console (/admin)"
        )
    missing = [
        field
        for field, val in (
            ("api_key", cfg["api_key"]),
            ("base_url", cfg["base_url"]),
            ("model", cfg["model"]),
        )
        if not val
    ]
    if missing:
        if explicit:
            raise LLMProviderError(
                f"LLM provider '{provider_id}' is not configured "
                f"(missing: {', '.join(missing)}); set its key in the admin console (/admin)"
            )
        configured = [p["id"] for p in list_llm_providers() if p["configured"]]
        if not configured:
            raise LLMNotConfigured(
                "no LLM provider is configured on the server; set at least one "
                "provider API key in the admin console (/admin); reply generation is unavailable"
            )
        raise LLMNotConfigured(
            f"default LLM provider '{provider_id}' is not configured "
            f"(missing: {', '.join(missing)}); configured providers: "
            f"{', '.join(configured)} — change the default provider or its key in the admin console (/admin)"
        )

    url = f"{cfg['base_url'].rstrip('/')}/chat/completions"
    headers = {
        "Authorization": f"Bearer {cfg['api_key']}",
        "Content-Type": "application/json",
    }
    system = REPLY_SYSTEM_PROMPT.format(
        character_name=character["name"],
        age=character["age"],
        occupation=character["occupation"],
        personality=character["personality"],
        hobbies="、".join(character["hobbies"]),
        writing_style=character["writing_style"],
        boundaries=character["boundaries"],
        life_history=character["life_history"],
        stage=character.get("_stage", "初识"),
        interaction_count=character.get("_interaction_count", 0),
    )
    if context:
        system += (
            "\n对方的近况和你们之间的记忆（让回信更贴合这个人，可以自然引用，"
            "但不要逐条复述）：\n" + context + "\n"
        )
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": f"这是对方刚写来的信：\n{user_letter}\n\n请以{character['name']}的身份回一封信。"},
    ]
    problems: list[str] = []
    text = ""
    for attempt in range(max_attempts):
        if attempt > 0:
            messages.append(
                {"role": "user", "content": CORRECTION_PROMPT.format(problems="；".join(problems))}
            )
        try:
            with httpx.Client(timeout=90.0, trust_env=False) as client:
                resp = client.post(
                    url,
                    headers=headers,
                    json={
                        "model": cfg["model"],
                        "messages": messages,
                        "temperature": 0.8,
                        "max_tokens": 2500,
                    },
                )
        except httpx.HTTPError as e:
            raise LLMError(f"{provider_id} request failed: {e}") from e
        if resp.status_code != 200:
            raise LLMError(
                f"{provider_id} API returned HTTP {resp.status_code}: {resp.text[:300]}"
            )
        try:
            text = resp.json()["choices"][0]["message"]["content"].strip()
        except (KeyError, IndexError, ValueError) as e:
            raise LLMError(f"unexpected {provider_id} response: {resp.text[:300]}") from e
        ok, problems = validate_reply(text)
        if ok:
            return text
        messages.append({"role": "assistant", "content": text})
    from .content_filter import classify_violation

    for vtype in classify_violation(text):
        database.record_violation(vtype)
    raise LLMError(
        "generated reply did not pass the content filter after "
        f"{max_attempts} attempts: {'; '.join(problems)}"
    )
