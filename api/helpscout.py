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
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
        }
        r = requests.post(OAUTH_TOKEN_URL, data=data, timeout=10)
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
    # Prefer OAuth token if present; fallback to PAT if provided
    with get_session() as s:
        row = get_hs_tokens(s)
        if row and row.access_token and (not row.expires_at or row.expires_at > datetime.utcnow()):
            return {"Authorization": f"Bearer {row.access_token}"}
    if _pat:
        return {"Authorization": f"Bearer {_pat}"}
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
        # fallback to threads endpoint if needed
        threads = []
    bodies = []
    for t in threads:
        if not isinstance(t, dict):
            continue
        bodies += [t.get("text"), t.get("body"), _strip_html(t.get("html"))]
    bodies = [b for b in bodies if b]
    return (subj + "\n" + (bodies[-1] if bodies else "")).strip()

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
