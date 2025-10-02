def _try_refresh():
    if not (CLIENT_ID and CLIENT_SECRET):
        return
    with get_session() as s:
        row = get_hs_tokens(s)
        if not row or not row.refresh_token:
            return
        data = {
            "grant_type": "refresh_token",
            "refresh_token": row.refresh_token,
        }
        # Help Scout prefers client auth via HTTP Basic
        r = requests.post(OAUTH_TOKEN_URL, data=data, auth=(CLIENT_ID, CLIENT_SECRET), headers={"Accept":"application/json"}, timeout=10)
        if r.status_code >= 300:
            return
        j = r.json()
        expires_at = datetime.utcnow() + timedelta(seconds=int(j.get("expires_in", 3600)))
        save_hs_tokens(s, j.get("access_token"), j.get("refresh_token") or row.refresh_token, expires_at)
import os, requests, base64, time
from datetime import datetime, timedelta
from bs4 import BeautifulSoup
from models import get_session, get_hs_tokens, save_hs_tokens

HS = os.getenv("HS_BASE_URL", "https://api.helpscout.net/v2")
OAUTH_TOKEN_URL = f"{HS}/oauth2/token"
CLIENT_ID = os.getenv("HS_CLIENT_ID", "").strip()
CLIENT_SECRET = os.getenv("HS_CLIENT_SECRET", "").strip()

_pat = (os.getenv('HS_API_TOKEN') or '').strip()


def _bearer_header():
    """Return Authorization header.

    Behavior:
    - Prefer OAuth access_token if present. If token is close to expiry,
      proactively refresh using the stored refresh_token.
    - Fallback to API key (PAT) via HTTP Basic auth.
    """
    with get_session() as s:
        row = get_hs_tokens(s)
        if row and row.access_token:
            # Proactively refresh if within N minutes of expiry
            try:
                if row.expires_at is not None:
                    threshold_min = int(os.getenv("HS_REFRESH_THRESHOLD_MIN", "5") or "5")
                    if (row.expires_at - datetime.utcnow()).total_seconds() <= threshold_min * 60:
                        _try_refresh()
                        row = get_hs_tokens(s)
                return {"Authorization": f"Bearer {row.access_token}"}
            except Exception:
                # On any error, fall through to PAT/basic if present
                pass
    if _pat:
        # Help Scout API key uses HTTP Basic auth (api_key as username, blank password)
        try:
            b64 = base64.b64encode(f"{_pat}:".encode("utf-8")).decode("utf-8")
            return {"Authorization": f"Basic {b64}"}
        except Exception:
            pass
    return {}

HDRS_BASE = {"Accept":"application/json","User-Agent":"hs-trends/0.1"}


def extract_conversation_id(payload: dict):
    c = payload.get("id") or payload.get("conversationId") or payload.get("conversation_id")
    if not c and isinstance(payload.get("event"), dict):
        c = payload["event"].get("id")
    return c

def fetch_conversation(conv_id: int) -> dict:
    hdrs = {**HDRS_BASE, **_bearer_header()}
    url = f"{HS}/conversations/{conv_id}?embed=threads"
    r = requests.get(url, headers=hdrs, timeout=10)
    if r.status_code == 401 and CLIENT_ID and CLIENT_SECRET:
        # try refresh
        _try_refresh()
        hdrs = {**HDRS_BASE, **_bearer_header()}
        r = requests.get(url, headers=hdrs, timeout=10)
    r.raise_for_status()
    return r.json()

def _strip_html(s: str) -> str:
    return BeautifulSoup(s or "", "html.parser").get_text(separator=" ", strip=True)

def extract_text(conv: dict) -> str:
    subj = conv.get("subject") or ""
    threads = conv.get("_embedded", {}).get("threads")
    if not isinstance(threads, list):
        # fallback if threads not embedded
        threads = []
    # Concatenate entire thread (user + agent) to give full context to enrichment/tagging
    parts = []
    for t in threads:
        if not isinstance(t, dict):
            continue
        # Prefer plain text, then body, then HTML stripped
        for k in ("text", "body", "html"):
            v = t.get(k)
            if v:
                parts.append(_strip_html(v) if k == "html" else str(v))
                break
    # Deduplicate adjacent empties and trim
    parts = [p.strip() for p in parts if isinstance(p, str) and p.strip()]
    full = (subj + "\n" + ("\n---\n".join(parts) if parts else "")).strip()
    # Cap extremely long conversations to a reasonable size to avoid over-enrichment cost
    if len(full) > 20000:
        full = full[:20000]
    return full

def extract_customer_name(conv: dict):
    try:
        cust = (
            conv.get("primaryCustomer")
            or conv.get("customer")
            or conv.get("_embedded", {}).get("customer")
            or {}
        )
        first = cust.get("firstName") or cust.get("first") or cust.get("first_name")
        last = cust.get("lastName") or cust.get("last") or cust.get("last_name")
        return (first, last)
    except Exception:
        return (None, None)

def list_conversations(page: int = 1) -> dict:
    hdrs = {**HDRS_BASE, **_bearer_header()}
    url = f"{HS}/conversations?page={page}&embed=threads"
    r = requests.get(url, headers=hdrs, timeout=10)
    if r.status_code == 401 and CLIENT_ID and CLIENT_SECRET:
        _try_refresh(); hdrs = {**HDRS_BASE, **_bearer_header()}
        r = requests.get(url, headers=hdrs, timeout=10)
    r.raise_for_status(); return r.json()


def ensure_tags(conv_id: int, cats, sev_score: int, entities: dict):
    tags = set()
    bucket = "critical" if sev_score>=70 else "high" if sev_score>=40 else "medium" if sev_score>=20 else "low"
    tags.add(f"sev:{bucket}")
    for c in (cats or []):
        if c in ("uncategorized", "device"):
            continue
        tags.add(f"cat:{c}")
    # Domain-specific tag 'flowers' if present in text is added upstream during processing
    if entities.get("level"): tags.add(f"lvl:{entities['level']}")
    if entities.get("platform"): tags.add(f"platform:{entities['platform']}")
    if entities.get("app_version"): tags.add(f"app:{entities['app_version']}")

    hdrs = {**HDRS_BASE, **_bearer_header()}
    r = requests.get(f"{HS}/conversations/{conv_id}", headers=hdrs, timeout=8)
    if r.status_code == 401 and CLIENT_ID and CLIENT_SECRET:
        _try_refresh(); hdrs = {**HDRS_BASE, **_bearer_header()}
        r = requests.get(f"{HS}/conversations/{conv_id}", headers=hdrs, timeout=8)
    r.raise_for_status()
    payload = r.json()
    current_raw = payload.get("tags") or []
    current = set([t.get('tag') if isinstance(t, dict) else str(t) for t in current_raw])
    merged = list(current.union(tags))

    hdrs_json = {**hdrs, "Content-Type":"application/json"}
    r2 = requests.put(f"{HS}/conversations/{conv_id}", headers=hdrs_json, json={"tags": merged}, timeout=8)
    if r2.status_code < 300: return
    requests.post(f"{HS}/conversations/{conv_id}/tags", headers=hdrs_json, json={"tags": list(tags), "operation": "add"}, timeout=8).raise_for_status()
