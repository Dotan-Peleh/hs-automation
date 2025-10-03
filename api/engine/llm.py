import os, json, requests

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "").strip()
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-3-haiku-20240307")

API_URL = "https://api.anthropic.com/v1/messages"
HEADERS = {
    "x-api-key": ANTHROPIC_API_KEY,
    "anthropic-version": "2023-06-01",
    "content-type": "application/json"
}

SYSTEM = (
    "You are a support incident enricher. Read the latest customer message and summarize the core issue in one short sentence. "
    "Then suggest up to 2 short categories (lowercase, snake_case), and extract lightweight fields if present: platform (android/ios/web/desktop), app_version, level (integer). "
    "If a user identifier is present (e.g., 'user:abc123', 'distinct_id abc123', 'id abc123'), extract it as distinct_id (string). "
    "Output STRICT JSON only with keys: summary (string), categories (array of strings), platform (string|null), app_version (string|null), level (integer|null), distinct_id (string|null). No prose."
)


def is_enabled() -> bool:
    return bool(ANTHROPIC_API_KEY)


def enrich(text: str) -> dict:
    if not is_enabled() or not text:
        return {}
    try:
        payload = {
            "model": ANTHROPIC_MODEL,
            "max_tokens": 400,
            "system": SYSTEM,
            "messages": [{"role": "user", "content": text[:6000]}]
        }
        r = requests.post(API_URL, headers=HEADERS, data=json.dumps(payload), timeout=20)
        r.raise_for_status()
        data = r.json()
        # Anthropic returns a list of content blocks; first block should be text
        content_blocks = data.get("content") or []
        raw = "".join([b.get("text", "") for b in content_blocks if isinstance(b, dict)])
        raw = raw.strip()
        # try parse JSON; if the model wrapped with code fences, strip them
        if raw.startswith("```"):
            raw = raw.strip("`\n ")
            # remove possible leading json identifier
            if raw.lower().startswith("json\n"):
                raw = raw[5:]
        parsed = json.loads(raw)
        # minimal sanitation
        if not isinstance(parsed, dict):
            return {}
        return {
            "summary": parsed.get("summary"),
            "categories": parsed.get("categories") or [],
            "platform": parsed.get("platform"),
            "app_version": parsed.get("app_version"),
            "level": parsed.get("level"),
            "distinct_id": (parsed.get("distinct_id") or _extract_id_like(parsed.get("summary") or "") ),
        }
    except Exception:
        return {}


def _extract_id_like(text: str) -> str | None:
    try:
        import re
        t = text or ""
        m = re.search(r"(?i)user\s*id\s*[=:]\s*([A-Za-z0-9\-]{6,})", t)
        if not m:
            m = re.search(r"(?i)userid\s*[=:]\s*([A-Za-z0-9\-]{6,})", t)
        if not m:
            m = re.search(r"(?i)distinct[_\s-]*id\s*[=:]\s*([A-Za-z0-9\-]{6,})", t)
        return m.group(1) if m else None
    except Exception:
        return None


def get_global_summary(tickets: list[dict]) -> str:
    """Generate a high-level summary of the current situation from a list of tickets."""
    if not is_enabled() or not tickets:
        return ""
    
    # Create a concise summary of the tickets
    ticket_previews = []
    for t in tickets[:20]: # Use top 20 most recent/relevant for summary
        preview = f"- Ticket #{t.get('number')}: {t.get('one_liner')} (Severity: {t.get('severity_bucket')})"
        ticket_previews.append(preview)
    
    prompt = f"""
    You are an expert game support analyst. Based on the following recent tickets, provide a 2-3 sentence summary of the current situation for a support manager.
    Highlight any widespread issues (look for high 'similar_count'), critical bugs, or emerging patterns. Be concise and action-oriented.

    Recent Tickets:
    { "
".join(ticket_previews) }

    Summary:
    """
    
    try:
        completion = _client.completions.create(
            model="claude-2.1",
            max_tokens_to_sample=200,
            prompt=f"\n\nHuman: {prompt}\n\nAssistant:",
        )
        return completion.completion.strip()
    except Exception as e:
        print(f"ERROR: LLM global summary failed: {e}")
        return ""
