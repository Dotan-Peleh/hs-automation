import os, hmac, hashlib, json, requests
from fastapi import Request, HTTPException
from sqlalchemy.orm import Session

BOT = os.getenv("SLACK_BOT_TOKEN")
SIGNING_SECRET = os.getenv("SLACK_SIGNING_SECRET")
DEFAULT_CH = os.getenv("SLACK_DEFAULT_CHANNEL_ID")

def _headers():
    return {"Authorization": f"Bearer {BOT}", "Content-Type":"application/json; charset=utf-8"}

def post_parent(incident, cats, entities, z, cus, summary: str | None = None):
    if not BOT or not (DEFAULT_CH):
        return "", (DEFAULT_CH or "")
    title = f"{incident.severity_bucket.upper()} · {incident.signature}"
    sect_fields = [
        {"type":"mrkdwn","text":f"*Severity:* {incident.severity_bucket} ({incident.severity_score})"},
        {"type":"mrkdwn","text":f"*Z:* {z:.2f}  ·  *CUSUM:* {cus:.2f}"},
        {"type":"mrkdwn","text":f"*Cats:* {', '.join(cats)}"},
        {"type":"mrkdwn","text":f"*Ctx:* lv={entities.get('level')} plat={entities.get('platform')} app={entities.get('app_version')}"}
    ]
    blocks = [
        {"type":"header","text":{"type":"plain_text","text":title}},
        {"type":"section","fields": sect_fields}
    ]
    if summary:
        blocks.append({"type":"section","text":{"type":"mrkdwn","text":f"*LLM summary:* {summary}"}})
    blocks.append({"type":"actions","elements":[
        {"type":"button","text":{"type":"plain_text","text":"Acknowledge"},"action_id":"ack"},
        {"type":"button","text":{"type":"plain_text","text":"Mute 24h"},"style":"danger","action_id":"mute_24h"},
        {"type":"button","text":{"type":"plain_text","text":"Resolve"},"style":"primary","action_id":"resolve"}
    ]})
    resp = requests.post("https://slack.com/api/chat.postMessage", headers=_headers(),
                         data=json.dumps({"channel": DEFAULT_CH, "text": title, "blocks": blocks}))
    data = resp.json()
    if not data.get("ok"): raise HTTPException(status_code=502, detail=f"Slack error: {data}")
    return data["ts"], (data.get("channel") or DEFAULT_CH)

def post_update(incident, cats, entities, z, cus):
    if not BOT:
        return
    txt = f"Update · sev={incident.severity_bucket}({incident.severity_score}) · z={z:.2f} cusum={cus:.2f}"
    requests.post("https://slack.com/api/chat.postMessage", headers=_headers(),
                  data=json.dumps({"channel": incident.slack_channel_id or DEFAULT_CH, "thread_ts": incident.slack_thread_ts, "text": txt}))

async def verify_and_parse_interaction(req: Request):
    if not SIGNING_SECRET:
        raise HTTPException(status_code=501, detail="Slack interactivity not configured")
    ts = req.headers.get("X-Slack-Request-Timestamp")
    sig = req.headers.get("X-Slack-Signature")
    body = await req.body()
    basestring = b"v0:" + ts.encode() + b":" + body
    my_sig = "v0=" + hmac.new(SIGNING_SECRET.encode(), basestring, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig or "", my_sig):
        raise HTTPException(status_code=401, detail="Invalid Slack signature")
    payload = dict([part.split("=") for part in body.decode().split("&")]).get("payload")
    return json.loads(requests.utils.unquote(payload))

# ORM helpers (lookups + state changes)
from models import Incident

def find_incident_by_ts(s: Session, thread_ts: str):
    return s.query(Incident).filter(Incident.slack_thread_ts == thread_ts).first()

def acknowledge(incident: Incident):
    incident.status = "ack"

def mute(incident: Incident, hours: int = 24):
    incident.status = "muted"

def resolve(incident: Incident):
    incident.status = "resolved"
