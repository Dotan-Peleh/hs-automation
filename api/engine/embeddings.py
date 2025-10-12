import os, json, requests

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
OPENAI_EMBED_MODEL = os.getenv("OPENAI_EMBED_MODEL", "text-embedding-3-small").strip()
OPENAI_EMBED_URL = os.getenv("OPENAI_EMBED_URL", "https://api.openai.com/v1/embeddings").strip()

HEADERS = {
    "Authorization": f"Bearer {OPENAI_API_KEY}",
    "Content-Type": "application/json"
}

def is_enabled() -> bool:
    return bool(OPENAI_API_KEY)


def embed_text(text: str) -> list | None:
    """Return embedding vector for text using OpenAI embeddings API. None if disabled or error."""
    if not is_enabled() or not (text or "").strip():
        return None
    # Truncate to a safe length for embeddings API
    payload = {"model": OPENAI_EMBED_MODEL, "input": (text or "")[:6000]}
    try:
        r = requests.post(OPENAI_EMBED_URL, headers=HEADERS, data=json.dumps(payload), timeout=20)
        r.raise_for_status()
        j = r.json()
        data = j.get("data") or []
        if data and isinstance(data, list) and data[0].get("embedding"):
            return data[0]["embedding"]
    except Exception:
        return None
    return None
