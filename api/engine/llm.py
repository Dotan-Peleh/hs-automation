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
    "SUMMARY RULES - USE USER'S ACTUAL WORDS:\n"
    "1. Extract what the user ACTUALLY wrote, not the subject line\n"
    "2. Beta feedback emails: Ignore subject, extract the real feedback message\n"
    "3. Example: Subject 'A user has written new beta feedback...' + Body 'good game' → summary: 'good game'\n"
    "4. Quote user's exact words when short and clear\n"
    "5. For complaints/issues: Extract the specific problem they describe\n\n"
    "IMPORTANT DISTINCTIONS:\n"
    '- Use root_cause "game crashing on launch" for app crashes (app closes/stops working)\n'
    '- Use root_cause "gameplay bug/glitch" for bugs that don\'t crash the app (items missing, wrong behavior, etc.)\n'
    '- Use root_cause "app freezing/stuck" for UI freezes (app doesn\'t crash but stops responding)\n'
    '- If a ticket contains ONLY structured data (like UserID, OS, Device) and NO actual message from the user, use intent "incomplete_ticket". DO NOT invent a problem.\n\n'
    "Valid intent values:\n"
    "- bug_report: for bugs/glitches that don't crash the app\n"
    "- crash_report: for app crashes/force closes\n"
    "- billing_issue: payment/purchase/refund problems\n"
    "- delete_account: for requests to delete an account or cancel a subscription\n"
    "- lost_progress: save data lost\n"
    "- feedback: general feedback/compliments\n"
    "- question: how-to questions\n"
    "- incomplete_ticket: for empty messages or tickets with only structured data (UserID, OS, etc.)\n"
    "- unreadable: for messages that are incomprehensible, gibberish, or cannot be understood\n\n"
    "Output ONLY the JSON object. No other text."
)


def is_enabled() -> bool:
    if ANTHROPIC_API_KEY:
        return True
    print("⚠️ LLM enrichment is DISABLED. ANTHROPIC_API_KEY is not set.")
    return False


def enrich(text: str, user_corrections: list = None) -> dict:
    """
    Enrich ticket with LLM, using user corrections as few-shot examples.
    
    Args:
        text: Ticket text to analyze
        user_corrections: Recent user corrections to guide the LLM
    """
    if not is_enabled() or not text:
        return {}
    
    # PRE-CHECK: AGGRESSIVE empty ticket detection to prevent hallucinations!
    import re
    original_len = len(text)
    cleaned = text
    
    # Remove template patterns line-by-line
    cleaned = re.sub(r'(?im)^user\s*id\s*[=:]\s*.*$', '', cleaned)
    cleaned = re.sub(r'(?im)^os\s*[=:]\s*.*$', '', cleaned)
    cleaned = re.sub(r'(?im)^device\s*[=:]\s*.*$', '', cleaned)
    cleaned = re.sub(r'(?im)^platform\s*[=:]\s*.*$', '', cleaned)
    
    # General cleanup
    cleaned = re.sub(r'<[^>]+>', '', cleaned)  # Remove ALL HTML
    cleaned = re.sub(r'Support Request', '', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'\[PeerPlay Games\]', '', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'---+', '', cleaned)
    cleaned = re.sub(r'=+', '', cleaned)
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    
    # STRICT: If less than 40 chars of real content, it's EMPTY
    if len(cleaned) < 40:
        print(f"🚫 EMPTY TICKET BLOCKED - Only {len(cleaned)} chars after removing template (original: {original_len})")
        print(f"   Cleaned text: '{cleaned[:100]}'")
        return {
            "summary": "Empty ticket - no user message provided",
            "root_cause": "no user message provided",
            "intent": "incomplete_ticket",
            "tags": ["empty", "no_message"],
        }
    
    # Build enhanced system prompt with user corrections (few-shot learning)
    enhanced_system = SYSTEM
    if user_corrections and len(user_corrections) > 0:
        examples = "\n\n🎓 LEARN FROM THESE USER CORRECTIONS:\n"
        for i, corr in enumerate(user_corrections[:3], 1):  # Use 3 most recent
            examples += f"\nExample {i} - User's Correction:\n"
            examples += f"Ticket text: {corr.get('text', '')[:150]}...\n"
            examples += f"✓ Correct intent: {corr.get('correct_intent')}\n"
            examples += f"✓ Correct severity: {corr.get('correct_severity')}\n"
            if corr.get('notes'):
                examples += f"Why: {corr.get('notes')}\n"
        enhanced_system = SYSTEM + examples
        print(f"📚 Using {len(user_corrections)} user corrections as learning examples")
    
    clean_text_for_log = text[:150].replace('\n', ' ')
    print(f"🧠 Calling LLM with user guidance (first 150 chars): '{clean_text_for_log}...'")
    
    try:
        payload = {
            "model": ANTHROPIC_MODEL,
            "max_tokens": 400,
            "system": enhanced_system,  # Enhanced with your corrections!
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
    if not tickets:
        return "No recent tickets to analyze."

    from collections import Counter

    intent_counts = Counter(t.get('intent') for t in tickets if t.get('intent'))
    
    tag_counts = Counter()
    for t in tickets:
        tags = t.get('tags', [])
        if isinstance(tags, str):
            tags = tags.split(',')
        tag_counts.update(tag for tag in tags if tag)

    # Get the top 3 most common intents and tags
    top_intents = intent_counts.most_common(3)
    top_tags = tag_counts.most_common(3)

    summary = "Recent trends: "
    
    if top_intents:
        summary += "Top intents are "
        summary += ", ".join([f"**{intent}** ({count})" for intent, count in top_intents])
        summary += ". "

    if top_tags:
        summary += "Most common tags are "
        summary += ", ".join([f"`{tag}` ({count})" for tag, count in top_tags])
        summary += "."

    if not top_intents and not top_tags:
        return f"Analyzed {len(tickets)} recent tickets. No significant trends detected."

    return summary
