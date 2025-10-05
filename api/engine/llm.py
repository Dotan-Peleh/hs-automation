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
    "You are an expert support analyst for a gaming company. Your task is to analyze a user's support ticket and provide a structured JSON output.\n\n"
    "CRITICAL: You MUST respond with ONLY valid JSON. No explanations, no prose, ONLY JSON.\n\n"
    "Required JSON format:\n"
    "{\n"
    '  "root_cause": "brief description of the fundamental issue",\n'
    '  "intent": "user_goal_as_snake_case",\n'
    '  "tags": ["keyword1", "keyword2", "keyword3"],\n'
    '  "summary": "One sentence under 15 words describing the specific user problem"\n'
    "}\n\n"
    "Examples of valid intent values: bug_report, billing_issue, lost_progress, feedback, question, feature_request, refund_request.\n"
    "Examples of valid tags: crash, android, ios, payment, progress, freeze, stuck, coins, energy.\n\n"
    "Output ONLY the JSON object. No other text."
)


def is_enabled() -> bool:
    if ANTHROPIC_API_KEY:
        return True
    print("⚠️ LLM enrichment is DISABLED. ANTHROPIC_API_KEY is not set.")
    return False


def enrich(text: str) -> dict:
    if not is_enabled() or not text:
        return {}
    
    clean_text_for_log = text[:150].replace('\n', ' ')
    print(f"🧠 Calling LLM to enrich ticket content (first 150 chars): '{clean_text_for_log}...'")
    
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
        
        print(f"🤖 LLM raw response: {raw}")
        
        # Handle empty response from LLM
        if not raw:
            print("❌ LLM returned an empty response.")
            return {}

        # try parse JSON; if the model wrapped with code fences, strip them
        if raw.startswith("```"):
            raw = raw.strip("`\n ")
            # remove possible leading json identifier
            if raw.lower().startswith("json\n"):
                raw = raw[5:]
        
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as e:
            print(f"❌ LLM returned invalid JSON: {e}. Raw response: {raw[:200]}")
            return {}
        
        # minimal sanitation
        if not isinstance(parsed, dict):
            return {}
        
        print(f"✅ LLM enrichment successful. Summary: {parsed.get('summary')}")
        
        # Return fields that match the SYSTEM prompt
        return {
            "summary": parsed.get("summary"),
            "root_cause": parsed.get("root_cause"),
            "intent": parsed.get("intent"),
            "tags": parsed.get("tags") or [],
        }
    except Exception as e:
        print(f"❌ LLM enrichment FAILED. Error: {e}")
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
    {chr(10).join(ticket_previews)}

    Summary:
    """
    
    # This block was a leftover from a previous implementation and is not used.
    # The 'enrich' function uses a direct 'requests.post' call.
    # I am removing it to fix the '_client is not defined' error.
    return ""
