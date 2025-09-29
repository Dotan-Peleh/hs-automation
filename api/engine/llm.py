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
    "You are a support incident enricher. Read the latest customer message and summarize the core issue in one sentence. "
    "Then suggest up to 2 short categories (lowercase, snake_case), and extract lightweight fields if present: platform (android/ios/web/desktop), app_version, level (integer). "
    "Output STRICT JSON only with keys: summary (string), categories (array of strings), platform (string|null), app_version (string|null), level (integer|null). No prose."
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
        }
    except Exception:
        return {}
