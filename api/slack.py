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

def send_ticket_alert(ticket_number, subject, severity, intent, root_cause, summary, tags, hs_link, 
                      customer_name=None, game_user_id=None, platform=None, device=None, created_at=None):
    """Send Slack notification for support tickets"""
    if not BOT or not DEFAULT_CH:
        print("⚠️ Slack not configured")
        return False
    
    # Build message
    severity_emoji = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🟢"}.get(severity.lower(), "⚪")
    
    intent_labels = {
        "crash_report": "🔥 App Crash",
        "bug_report": "🐛 Bug",
        "billing_issue": "💳 Billing",
        "delete_account": "🚨 DELETE ACCOUNT",
        "lost_progress": "💾 Progress Lost",
        "incomplete_ticket": "📭 Empty",
        "feedback": "💬 Feedback",
        "unreadable": "❓ Unreadable"
    }
    intent_label = intent_labels.get(intent, intent or "Support Ticket")
    
    title = f"{intent_label}: #{ticket_number}"
    
    header_fields = [
        {"type": "mrkdwn", "text": f"*Severity:*\n{severity_emoji} {severity.upper()}"},
        {"type": "mrkdwn", "text": f"*Subject:*\n{subject[:100]}"},
    ]

    if created_at:
        try:
            from datetime import datetime
            dt_obj = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
            ts = int(dt_obj.timestamp())
            header_fields.append({"type": "mrkdwn", "text": f"*Time:*\n<!date^{ts}^{date_short} at {time}|{created_at}>"})
        except Exception:
            header_fields.append({"type": "mrkdwn", "text": f"*Time:*\n{created_at}"})


    blocks = [
        {"type": "header", "text": {"type": "plain_text", "text": title}},
        {"type": "section", "fields": header_fields},
        {"type": "section", "text": {"type": "mrkdwn", "text": f"*Summary:* {summary[:200]}"}}
    ]
    
    context_fields = []
    if platform:
        context_fields.append({"type": "mrkdwn", "text": f"📱 *Platform:* {platform}"})
    if device:
        context_fields.append({"type": "mrkdwn", "text": f"💻 *Device:* {device}"})

    if customer_name or game_user_id:
        if customer_name:
            context_fields.append({"type": "mrkdwn", "text": f"👤 *Customer:* {customer_name}"})
        if game_user_id:
            context_fields.append({"type": "mrkdwn", "text": f"🆔 *UserID:* `{game_user_id}`"})
    
    if context_fields:
        blocks.append({"type": "context", "elements": context_fields})

    if tags:
        blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": f"🏷️ {', '.join(tags[:8])}"}]})
    
    blocks.append({"type": "actions", "elements": [
        {"type": "button", "text": {"type": "plain_text", "text": "Open in Help Scout"}, "url": hs_link, "style": "primary"}
    ]})
    
    try:
        resp = requests.post("https://slack.com/api/chat.postMessage", headers=_headers(),
            data=json.dumps({"channel": DEFAULT_CH, "text": f"{intent_label}: #{ticket_number} - {subject}", "blocks": blocks}), timeout=10)
        data = resp.json()
        if data.get("ok"):
            print(f"✅ Sent Slack alert for #{ticket_number}")
            return True
        else:
            print(f"❌ Slack error: {data}")
            return False
    except Exception as e:
        print(f"❌ Slack failed: {e}")
        return False

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
