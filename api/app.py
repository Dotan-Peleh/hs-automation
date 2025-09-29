import os, hmac, hashlib, threading, time
from fastapi import FastAPI, Request, HTTPException, Query, Response
from fastapi.responses import RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
import helpscout, slack
from engine import classify, fingerprint, anomaly, severity
from engine import embeddings
from engine import pine as pinevec
from engine import llm
from models import Base, get_session, upsert_incident, record_ticket_event, load_active_ruleset, upsert_hs_conversation, Incident, HsConversation

DB_URL = os.getenv("DATABASE_URL")
if not DB_URL:
    pg_user = os.getenv("POSTGRES_USER")
    pg_password = os.getenv("POSTGRES_PASSWORD")
    pg_host = os.getenv("POSTGRES_HOST")
    pg_port = os.getenv("POSTGRES_PORT")
    pg_db = os.getenv("POSTGRES_DB")
    if os.getenv("USE_SQLITE", "1") == "1" or not all([pg_user, pg_password, pg_host, pg_port, pg_db]):
        DB_URL = "sqlite:///dev.db"
    else:
        DB_URL = f"postgresql+psycopg2://{pg_user}:{pg_password}@{pg_host}:{pg_port}/{pg_db}"

engine = create_engine(DB_URL, pool_pre_ping=True, connect_args={"check_same_thread": False} if DB_URL.startswith("sqlite") else {})
Session = sessionmaker(bind=engine)

app = FastAPI(title="HS Trends")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_headers=["*"], allow_methods=["*"])

@app.get("/healthz")
def healthz():
    return {"status": "ok"}

# --- Vector auto-index helpers ---
def _vector_auto_enabled() -> bool:
    if os.getenv("VECTOR_AUTO", "1") != "1":
        return False
    return pinevec.is_enabled() and embeddings.is_enabled()

def _vector_upsert_one(conv_id: int, number: int | None, subject: str | None, text: str | None, updated_at_iso: str | None = None) -> bool:
    if not _vector_auto_enabled():
        return False
    raw = ((subject or "") + "\n" + (text or "")).strip()
    if not raw:
        return False
    try:
        vec = embeddings.embed_text(raw)
        if not vec:
            return False
        pinevec.upsert_vectors([
            {
                "id": str(conv_id),
                "values": vec,
                "metadata": {
                    "number": number,
                    "subject": subject or "",
                    "updated_at": updated_at_iso,
                },
            }
        ])
        return True
    except Exception:
        return False

@app.post("/helpscout/webhook")
async def hs_webhook(req: Request):
    body = await req.body()
    secret = os.getenv("HS_WEBHOOK_SECRET")
    if secret:
        sig = req.headers.get("X-HelpScout-Signature")
        mac = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig or "", mac):
            raise HTTPException(status_code=401, detail="Invalid HS signature")

    payload = await req.json()
    conv_id = helpscout.extract_conversation_id(payload)
    if not conv_id:
        raise HTTPException(status_code=400, detail="Missing conversation id")

    try:
        conv = helpscout.fetch_conversation(conv_id)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"HS fetch failed: {e}")
    text = helpscout.extract_text(conv)
    first, last = helpscout.extract_customer_name(conv)
    subj = conv.get("subject") or ""
    combined = (subj + "\n" + text).strip()

    entities = classify.extract_entities(combined)
    cats, rule_score = classify.categorize(combined)

    # optional LLM enrichment
    extra = llm.enrich(combined) if llm.is_enabled() else {}
    if extra.get("summary"):
        entities = {**entities}
        if extra.get("platform"): entities["platform"] = extra["platform"]
        if extra.get("app_version"): entities["app_version"] = extra["app_version"]
        if extra.get("level") is not None: entities["level"] = extra["level"]
        cats = sorted(set((cats or []) + (extra.get("categories") or [])))

    cluster = fingerprint.cluster_key(combined, entities)
    sev_score = severity.compute(combined, entities, rule_score)
    z, cus = anomaly.update_and_score(cluster)
    bucket = severity.bucketize(sev_score, z, cus) or "low"

    try:
        helpscout.ensure_tags(conv_id, cats, sev_score, entities)
    except Exception as e:
        # don’t fail the webhook on tag write issues
        pass

    try:
        with get_session() as s:
            # Persist/update conversation so dashboard queries include this ticket (delta upsert)
            raw_tags = conv.get("tags") or []
            tag_names = [t.get("tag") if isinstance(t, dict) else str(t) for t in raw_tags]
            tags_str = ",".join([t for t in tag_names if t])
            updated_at_dt = None
            try:
                updated_iso = conv.get("updatedAt") or conv.get("createdAt")
                if updated_iso:
                    from datetime import datetime
                    updated_at_dt = datetime.fromisoformat(updated_iso.replace("Z","+00:00")).replace(tzinfo=None)
            except Exception:
                pass
            upsert_hs_conversation(s, conv_id, conv.get("number"), subj, text, tags_str, updated_at_dt)
            # derive suggested tags and one-liner using same helpers as insights
            extra = llm.enrich(combined) if llm.is_enabled() else {}
            from datetime import datetime, timedelta
            from math import floor
            # day window from 10:00 UTC to next 10:00 UTC
            now = datetime.utcnow()
            day_start = now.replace(hour=10, minute=0, second=0, microsecond=0)
            if now < day_start:
                day_start = day_start - timedelta(days=1)
            # reuse derive_custom_tags and build_one_liner from insights scope by defining minimal shims
            def _derive(text, entities, cats, extra):
                t = (text or '').lower()
                tags = []
                if any(k in t for k in ("refund","chargeback","charged twice","double charge","money back","unauthorized charge","billing issue","payment issue","invoice","receipt")):
                    tags.append("intent:refund_request")
                if any(k in t for k in ("cancel subscription","unsubscribe","cancel my subscription","stop charging","turn off auto-renew","disable auto renew","cancel renewal")):
                    tags.append("intent:cancel_subscription")
                if any(k in t for k in ("can't log in","cant log in","cannot log in","login problem","log in problem","password reset","forgot password","2fa","two factor","verification code","verification email")):
                    tags.append("intent:account_access")
                if any(k in t for k in ("delete my account","delete account","remove my data","erase my data","gdpr","ccpa")):
                    tags.append("intent:account_deletion")
                if any(k in t for k in ("progress lost","lost progress","save lost","reset progress","rollback")):
                    tags.append("intent:recover_progress")
                if any(k in t for k in ("crash","crashing","force close","exception","stuck on","freeze","freezing","bug")):
                    tags.append("intent:bug_report")
                if any(k in t for k in ("slow","lag","stutter","fps","performance")):
                    tags.append("intent:performance_issue")
                if any(k in t for k in ("feature request","please add","could you add","it would be great if")):
                    tags.append("intent:feature_request")
                if any(k in t for k in ("how do i","how to","where is","can you explain","how can i")):
                    tags.append("intent:how_to")
                if any(k in t for k in ("new phone","new device","switch device","migrate","transfer progress","restore purchase")):
                    tags.append("intent:device_migration")
                platform = (entities or {}).get("platform") or (extra or {}).get("platform")
                if isinstance(platform, str) and platform:
                    tags.append(f"platform:{platform}")
                appv = (entities or {}).get("app_version") or (extra or {}).get("app_version")
                if isinstance(appv, str) and appv:
                    tags.append(f"version:{appv}")
                return tags
            def _one_liner(text, entities, cats, extra, bucket, suggested):
                try:
                    platform = (entities or {}).get('platform') or (extra or {}).get('platform')
                    appv = (entities or {}).get('app_version') or (extra or {}).get('app_version')
                    lvl = (entities or {}).get('level')
                    intent = ''
                    for t in (suggested or []):
                        if isinstance(t, str) and t.startswith('intent:'): intent = t.split(':',1)[1]; break
                    intent_map = { 'refund_request':'refund request','cancel_subscription':'subscription cancellation','account_access':'account access issue','account_deletion':'account deletion request','recover_progress':'recover lost progress','bug_report':'bug/crash report','performance_issue':'performance issue','feature_request':'feature request','how_to':'how-to question','device_migration':'device migration/restore' }
                    primary_cat = None
                    for ccat in (cats or []):
                        if ccat not in ('uncategorized','device'): primary_cat = ccat.replace('_',' '); break
                    label = intent_map.get(intent, primary_cat or 'support request')
                    parts = [str(bucket).lower(), label]
                    if platform: parts.append(f"on {platform}")
                    if appv: parts.append(f"v{appv}")
                    if isinstance(lvl, int): parts.append(f"lvl {lvl}")
                    return ' '.join([p for p in parts if p])[:180]
                except Exception:
                    return 'support request'
            custom = _derive(combined, entities, cats, extra)
            cats = [c for c in (cats or []) if c not in ("uncategorized","device")]
            suggested = [f"sev:{bucket}"] + [f"cat:{x}" for x in (cats or [])] + custom
            one = _one_liner(combined, entities, cats, extra, bucket, suggested)
            # persist ticket event with normalized day_start
            # attach user context to tags string for now (non-breaking)
            extra_tags = [t for t in suggested]
            if first or last:
                extra_tags.append(f"user:{(first or '').strip()} {(last or '').strip()}".strip())
            record_ticket_event(s, conv_id, conv.get('number'), subj, combined, entities, cats, bucket, sev_score, cluster, z, cus, None, next((t.split(':',1)[1] for t in suggested if t.startswith('intent:')), None), ','.join(extra_tags), one, extra.get('summary'), day_start)
            incident = upsert_incident(s, cluster, bucket, sev_score)
            if not incident.slack_thread_ts:
                summary = extra.get("summary") if 'extra' in locals() else None
                ts, ch = slack.post_parent(incident, cats, entities, z, cus, summary)
                incident.slack_thread_ts = ts
                incident.slack_channel_id = ch
                s.commit()
            else:
                slack.post_update(incident, cats, entities, z, cus)
    except Exception as e:
        # don’t fail the webhook on persistence issues
        return {"ok": True, "stored": False}
    # auto-upsert vector for this conversation (best-effort)
    try:
        updated_iso = None
        _vector_upsert_one(conv_id, conv.get("number"), subj, text, updated_iso)
    except Exception:
        pass
    return {"ok": True}

@app.get("/admin/preview")
def admin_preview(text: str = Query("", description="text to classify")):
    combined = text.strip()
    entities = classify.extract_entities(combined)
    cats, rule_score = classify.categorize(combined)

    # optional LLM enrichment
    extra = llm.enrich(combined) if llm.is_enabled() else {}
    if extra.get("summary"):
        entities = {**entities}
        if extra.get("platform"): entities["platform"] = extra["platform"]
        if extra.get("app_version"): entities["app_version"] = extra["app_version"]
        if extra.get("level") is not None: entities["level"] = extra["level"]
        cats = sorted(set((cats or []) + (extra.get("categories") or [])))

    cluster = fingerprint.cluster_key(combined, entities)
    z, cus = anomaly.update_and_score(cluster)
    sev_score = severity.compute(combined, entities, rule_score)
    bucket = severity.bucketize(sev_score, z, cus)
    return {
        "entities": entities,
        "categories": cats,
        "rule_score": rule_score,
        "severity_score": sev_score,
        "bucket": bucket,
        "z": z,
        "cusum": cus,
        "cluster_key": cluster,
        "llm": extra
    }

@app.post("/slack/interact")
async def slack_interact(req: Request):
    payload = await slack.verify_and_parse_interaction(req)
    action = payload["actions"][0]["action_id"]
    thread_ts = payload["message"]["ts"]
    with get_session() as s:
        incident = slack.find_incident_by_ts(s, thread_ts)
        if not incident:
            return {"ok": True}
        if action == "ack":
            slack.acknowledge(incident); s.commit()
        elif action == "mute_24h":
            slack.mute(incident, hours=24); s.commit()
        elif action == "resolve":
            slack.resolve(incident); s.commit()
    return {"ok": True}

@app.get("/admin/config")
def get_config():
    with get_session() as s:
        return load_active_ruleset(s)

@app.get("/admin/incidents")
def list_incidents(limit: int = 50):
    with get_session() as s:
        q = s.query(Incident).order_by(Incident.last_update.desc()).limit(max(1, min(limit, 200)))
        rows = []
        for i in q.all():
            rows.append({
                "id": i.id,
                "signature": i.signature,
                "status": i.status,
                "bucket": i.severity_bucket,
                "score": i.severity_score,
                "cluster_key": i.cluster_key,
                "slack_channel_id": i.slack_channel_id,
                "slack_thread_ts": i.slack_thread_ts,
                "last_update": i.last_update.isoformat() if i.last_update else None,
            })
        return {"incidents": rows}

@app.get("/admin/stats")
def stats():
    with get_session() as s:
        total = s.query(Incident).count()
        by_status = {}
        for st in ("open","ack","muted","resolved"):
            by_status[st] = s.query(Incident).filter(Incident.status==st).count()
        by_bucket = {}
        for b in ("critical","high","medium","low"):
            by_bucket[b] = s.query(Incident).filter(Incident.severity_bucket==b).count()
        return {"total": total, "by_status": by_status, "by_bucket": by_bucket}

from datetime import datetime, timedelta

@app.get("/admin/conversations")
def list_conversations(hours: int = 24, limit: int = 200):
    cutoff = datetime.utcnow() - timedelta(hours=max(1, hours))
    with get_session() as s:
        q = s.query(HsConversation).filter(HsConversation.updated_at >= cutoff).order_by(HsConversation.updated_at.desc()).limit(max(1, min(limit, 2000)))
        rows = []
        for c in q.all():
            rows.append({
                "id": c.id,
                "number": c.number,
                "subject": c.subject,
                "last_text": c.last_text,
                "tags": (c.tags or "").split(",") if c.tags else [],
                "updated_at": c.updated_at.isoformat() if c.updated_at else None,
            })
        return {"conversations": rows}

@app.get("/admin/volume")
def volume(hours: int = 24, compare: int = 24):
    now = datetime.utcnow()
    win_start = now - timedelta(hours=max(1, hours))
    prev_start = win_start - timedelta(hours=max(1, compare))
    with get_session() as s:
        cur = s.query(HsConversation).filter(HsConversation.updated_at >= win_start).count()
        prev = s.query(HsConversation).filter(HsConversation.updated_at >= prev_start, HsConversation.updated_at < win_start).count()
    delta = cur - prev
    pct = (delta / prev * 100.0) if prev > 0 else None
    return {"current": cur, "previous": prev, "delta": delta, "delta_pct": pct}

@app.get("/admin/insights")
def insights(
    hours: int = 24,
    limit: int = 100,
    use_llm: int = 1,
    all: int = 0,
    # incremental fetch controls
    page: int = 1,
    page_size: int = 0,
    min_number: int | None = None,
):
    """
    Read recent conversations and return recommended tags, summaries, and patterns.
    Does NOT write back to Help Scout; read-only analysis.
    """
    now = datetime.utcnow()
    with get_session() as s:
        if all:
            q = s.query(HsConversation)
        else:
            cutoff = now - timedelta(hours=max(1, hours))
            q = s.query(HsConversation).filter(HsConversation.updated_at >= cutoff)
        if min_number is not None:
            try:
                q = q.filter(HsConversation.number > int(min_number))
            except Exception:
                pass
        q = q.order_by(HsConversation.updated_at.desc())
        # total matching count before paging
        try:
            total = q.count()
        except Exception:
            total = 0
        # apply paging
        _ps = page_size if page_size and page_size > 0 else limit
        _ps = max(1, min(int(_ps), 1000))
        _off = max(0, (int(page) - 1) * _ps)
        rows = q.offset(_off).limit(_ps).all()

    recs = []
    cat_totals = {}
    word_counts = {}
    cluster_counts = {}
    cluster_meta = {}
    tag_counts = {}
    stop = set("""
        the a an and or for from with into on at to in of is are was were be been have has had i you we they he she it this that those these not can't cannot don't do does did as by if then so but our your their my me us them when where which who whom why how what
    """.split())

    # Remove markup/boilerplate tokens from keyword list
    BAN_TOKENS = set([
        'div','span','table','tbody','thead','tr','td','th','style','class','width','height','align','center',
        'https','http','com','google','userid','user','id','color','border','cellpadding','cellspacing',
        'href','padding','background-color','left','right','top','bottom','solid','dir','ltr','rtl','font','px','pt','em','rem',
        'ex-mj-column-per-100','ex-mj-outlook-group-fix','mj-column','mj-text','mj-section','outlook','mso','nbsp',
        # more non-user semantic tokens frequently observed
        'support','request','device','play','console','game','android','iphoneplayer','get','beta','app','new','none','ddd','fff','strong','text-decoration','font-weight','bold'
    ])

    def add_words(text: str):
        import re
        for w in re.findall(r"[a-zA-Z][a-zA-Z0-9_\-]{2,}", (text or '').lower()):
            if w in stop: continue
            if w in BAN_TOKENS: continue
            if re.match(r"^[a-z]{1,2}$", w):
                continue
            if any(ch.isdigit() for ch in w):
                # keep version-like tokens
                pass
            word_counts[w] = word_counts.get(w, 0) + 1

    import re

    def derive_custom_tags(text: str, entities: dict, cats: list[str] | None, extra: dict | None) -> list[str]:
        t = (text or '').lower()
        tags: list[str] = []
        # Intent detection (high-level user intent)
        # Refund / billing
        if any(k in t for k in ("refund", "chargeback", "charged twice", "double charge", "money back", "unauthorized charge", "billing issue", "payment issue", "invoice", "receipt")):
            tags.append("intent:refund_request")
        if any(k in t for k in ("cancel subscription", "unsubscribe", "cancel my subscription", "stop charging", "turn off auto-renew", "disable auto renew", "cancel renewal")):
            tags.append("intent:cancel_subscription")
        # Account access / credentials
        if any(k in t for k in ("can't log in", "cant log in", "cannot log in", "login problem", "log in problem", "password reset", "forgot password", "2fa", "two factor", "verification code", "verification email")):
            tags.append("intent:account_access")
        if any(k in t for k in ("delete my account", "delete account", "remove my data", "erase my data", "gdpr", "ccpa")):
            tags.append("intent:account_deletion")
        # Lost progress / restore
        if any(k in t for k in ("progress lost", "lost progress", "save lost", "reset progress", "rollback", "losing progress", "not saving", "progress not saving", "went back to", "back to level", "rollback to level")):
            tags.append("intent:recover_progress")
        # Crash / bug report
        if any(k in t for k in ("crash", "crashing", "force close", "exception", "stuck on", "freeze", "freezing", "bug")):
            tags.append("intent:bug_report")
        # Performance
        if any(k in t for k in ("slow", "lag", "stutter", "fps", "performance")):
            tags.append("intent:performance_issue")
        # Feature request / how-to
        if any(k in t for k in ("feature request", "please add", "could you add", "it would be great if")):
            tags.append("intent:feature_request")
        if any(k in t for k in ("how do i", "how to", "where is", "can you explain", "how can i")):
            tags.append("intent:how_to")
        # Device migration
        if any(k in t for k in ("new phone", "new device", "switch device", "migrate", "transfer progress", "restore purchase")):
            tags.append("intent:device_migration")
        # Store reviews
        if any(k in t for k in ("review", "rate", "rating")) and any(k in t for k in ("play store", "google play", "app store", "store")):
            tags.append("review:store")
        # UX issues
        if any(k in t for k in ("ux", "ui", "button", "menu", "layout", "confus", "hard to", "can't find", "cannot find")):
            tags.append("tag:ux_issue")
        # Purchase/payment signals (generic)
        if any(k in t for k in ("purchase", "payment", "charged", "iap", "in-app", "subscription", "renewal")):
            tags.append("tag:purchase_issue")
        # Domain-specific keyword: flowers
        if "flowers" in t or "flower" in t:
            tags.append("flowers")
        # Item disappeared / progress lost / restart prompts
        if any(k in t for k in ("item disappeared", "item gone", "lost item", "missing item", "inventory missing")):
            tags.append("tag:item_disappeared")
        if any(k in t for k in ("progress lost", "lost progress", "save lost", "progress reset", "account reset", "losing progress", "not saving", "progress not saving", "went back to", "back to level", "rollback to level")):
            tags.append("tag:progress_lost")
        if any(k in t for k in ("restart the game", "restart app", "reinstall", "re-install")):
            tags.append("tag:restart_prompt")
        # Platform tags from entities or LLM
        platform = (entities or {}).get("platform") or (extra or {}).get("platform")
        if isinstance(platform, str) and platform:
            tags.append(f"platform:{platform}")
        # App version
        appv = (entities or {}).get("app_version") or (extra or {}).get("app_version")
        if isinstance(appv, str) and appv:
            tags.append(f"version:{appv}")
        return tags

    def interpret_hs_tags(tag_list) -> tuple[str | None, list[str]]:
        names = [str(t or '').lower().strip() for t in (tag_list or [])]
        extra: list[str] = []
        mapped_intent: str | None = None
        def has(*keys: str) -> bool:
            return any(any(k in n for k in keys) for n in names)
        if has('progress_lost','progress lost','progress','save lost','rollback','not saving','lost progress'):
            extra.append('tag:progress_lost'); mapped_intent = mapped_intent or 'recover_progress'
        if has('crash','bug','exception','stuck','freeze','freezing'):
            mapped_intent = mapped_intent or 'bug_report'
        if has('refund','billing','payment','purchase','iap','charged'):
            extra.append('tag:purchase_issue'); mapped_intent = mapped_intent or 'refund_request'
        if has('how_to','how-to','how to','question','help','where is'):
            mapped_intent = mapped_intent or 'how_to'
        if has('device','migration','transfer','restore purchase','new phone','new device'):
            mapped_intent = mapped_intent or 'device_migration'
        if has('restart'):
            extra.append('tag:restart_prompt')
        if has('missing_item','item missing','lost item','inventory'):
            extra.append('tag:item_disappeared')
        if has('flowers','flower'):
            extra.append('flowers')
        return mapped_intent, extra

    def build_one_liner(text: str, entities: dict, cats: list[str] | None, extra: dict | None, bucket: str | None, suggested: list[str]) -> str:
        try:
            t = (text or '').strip()
            platform = (entities or {}).get('platform') or (extra or {}).get('platform')
            appv = (entities or {}).get('app_version') or (extra or {}).get('app_version')
            lvl = (entities or {}).get('level')
            intent = ''
            for tag in (suggested or []):
                if isinstance(tag, str) and tag.startswith('intent:'):
                    intent = tag.split(':', 1)[1]
                    break
            intent_map = {
                'refund_request': 'refund request',
                'cancel_subscription': 'subscription cancellation',
                'account_access': 'account access issue',
                'account_deletion': 'account deletion request',
                'recover_progress': 'recover lost progress',
                'bug_report': 'bug/crash report',
                'performance_issue': 'performance issue',
                'feature_request': 'feature request',
                'how_to': 'how-to question',
                'device_migration': 'device migration/restore',
            }
            primary_cat = None
            for ccat in (cats or []):
                if ccat not in ('uncategorized','device'):
                    primary_cat = ccat.replace('_',' ')
                    break
            label = intent_map.get(intent, primary_cat or 'support request')
            parts = []
            # Only surface severity for high/critical to avoid redundancy with tag chips
            if bucket and str(bucket).lower() in ("high","critical"):
                parts.append(str(bucket).lower())
            parts.append(label)
            if platform:
                parts.append(f"on {platform}")
            if appv:
                parts.append(f"v{appv}")
            if isinstance(lvl, int):
                parts.append(f"lvl {lvl}")
            # quick context phrase
            low = t.lower()
            if 'after update' in low or 'after updating' in low:
                parts.append('after update')
            elif 'on launch' in low or 'at startup' in low or 'start the app' in low:
                parts.append('on launch')
            elif 'payment' in low or 'purchase' in low or 'charged' in low:
                parts.append('payment issue')
            elif 'login' in low or 'log in' in low:
                parts.append('login problem')
            s = ' '.join(parts)
            return s[:180]
        except Exception:
            return 'support request'

    for c in rows:
        raw = ((c.subject or "") + "\n" + (c.last_text or "")).strip()
        # Only count keywords from the user's message body, not subjects/headers
        add_words(c.last_text or '')
        entities = classify.extract_entities(raw)
        cats, rule_score = classify.categorize(raw)
        extra = llm.enrich(raw) if (use_llm and llm.is_enabled()) else {}
        if extra.get("categories"):
            cats = sorted(set((cats or []) + (extra.get("categories") or [])))
        # Filter out weak categories
        cats = [c for c in (cats or []) if c not in ("uncategorized", "device")]
        for cat in (cats or []):
            cat_totals[cat] = cat_totals.get(cat, 0) + 1
        # existing HS tags
        existing_tags = []
        try:
            existing_tags = ((c.tags or '').split(",")) if getattr(c, 'tags', None) else []
            for t in existing_tags:
                t2 = (t or '').strip()
                if t2:
                    tag_counts[t2] = tag_counts.get(t2, 0) + 1
        except Exception:
            pass
        sev_score = severity.compute(raw, entities, rule_score)
        bucket = severity.bucketize(sev_score, 0, 0)
        if not bucket:
            if sev_score >= 50:
                bucket = "high"
            elif sev_score >= 30:
                bucket = "medium"
            else:
                bucket = "low"
        ck = fingerprint.cluster_key(raw, entities)
        cluster_counts[ck] = cluster_counts.get(ck, 0) + 1
        custom = derive_custom_tags(raw, entities, cats, extra)
        # augment using Help Scout tags if available
        hs_intent, hs_extra = interpret_hs_tags(existing_tags)
        # separate out intent from custom tags
        intent_tag = next((t for t in custom if isinstance(t, str) and t.startswith('intent:')), None)
        intent_val = intent_tag.split(':',1)[1] if intent_tag else None
        if not intent_val and hs_intent:
            intent_val = hs_intent
        custom_wo_intent = [t for t in custom if not (isinstance(t, str) and t.startswith('intent:'))]
        for t in (hs_extra or []):
            if t not in custom_wo_intent:
                custom_wo_intent.append(t)

        # refine categories: replace generic 'bug' with more specific ones based on tags/intent
        tag_set = set(custom_wo_intent)
        cats = list(cats or [])
        if 'bug' in cats:
            def has(name: str) -> bool:
                return (name in tag_set) or (f'tag:{name}' in tag_set)
            new_cat = None
            if has('progress_lost') or (intent_val == 'recover_progress'):
                new_cat = 'progress_lost'
            elif has('purchase_issue') or (intent_val in ('refund_request',)):
                new_cat = 'purchase'
            elif any(k in (c.last_text or '').lower() for k in ('crash','exception','stuck','freeze')) or (intent_val == 'bug_report'):
                new_cat = 'crash'
            if new_cat:
                cats = [new_cat] + [c for c in cats if c != 'bug']
        # Build suggested tags without intent; include sev and cats
        suggested_tags = [f"sev:{bucket}"] + [f"cat:{x}" for x in (cats or [])] + custom_wo_intent
        # pass intent back into one-liner context (not as a tag to UI)
        intent_injected = suggested_tags + ([f"intent:{intent_val}"] if intent_val else [])
        one_liner = build_one_liner(raw, entities, cats, extra, bucket, intent_injected)
        # best-effort: fetch customer name for display
        customer_name = None
        try:
            conv_full = helpscout.fetch_conversation(c.id)
            f,l = helpscout.extract_customer_name(conv_full)
            if (f or l):
                customer_name = (f or '') + (' ' if (f and l) else '') + (l or '')
        except Exception:
            pass

        # track meta for priority selection
        if ck not in cluster_meta:
            cluster_meta[ck] = {
                "title": (c.subject or (raw[:60] + "...")),
                "category": (cats or ["other"])[0].replace("_", " ").title(),
                "severity": {"critical": "Critical", "high": "High", "medium": "Medium", "low": "Low"}.get(bucket, "Medium"),
                "last_seen": c.updated_at.isoformat() if c.updated_at else None,
            }
        else:
            try:
                prev = cluster_meta[ck].get("last_seen")
                cur = c.updated_at.isoformat() if c.updated_at else None
                if cur and (not prev or cur > prev):
                    cluster_meta[ck]["last_seen"] = cur
            except Exception:
                pass
        recs.append({
            "id": c.id,
            "number": c.number,
            "subject": c.subject,
            "updated_at": c.updated_at.isoformat() if c.updated_at else None,
            "summary": extra.get("summary") if extra else None,
            "one_liner": one_liner,
            "intent": intent_val,
            "customer_name": customer_name,
            "categories": cats,
            "entities": entities,
            "severity_bucket": bucket,
            "severity_score": sev_score,
            "suggested_tags": suggested_tags,
            "existing_tags": existing_tags,
            "cluster_key": ck,
            # convenient links
            "hs_link": f"https://secure.helpscout.net/conversation/{c.id}",
            "api_link": f"https://api.helpscout.net/v2/conversations/{c.id}",
        })

    # Post-process: adjust severity by repetition and categories
    for r in recs:
        ck = r.get("cluster_key")
        if ck:
            similar = cluster_counts.get(ck, 1)
            # expose similar count to clients
            r["similar_count"] = similar
            if similar >= 5 and r["severity_bucket"] != "critical":
                r["severity_bucket"] = "high"
        cats_l = set((r.get("categories") or []))
        if "crash" in cats_l:
            r["severity_bucket"] = "high"
        if "payment" in cats_l and r["severity_bucket"] == "low":
            r["severity_bucket"] = "medium"
        if "progress_lost" in cats_l and r["severity_bucket"] == "low":
            r["severity_bucket"] = "high"

    top_categories = sorted(cat_totals.items(), key=lambda x: x[1], reverse=True)[:10]
    top_keywords = sorted(word_counts.items(), key=lambda x: x[1], reverse=True)[:20]
    top_clusters = sorted(cluster_counts.items(), key=lambda x: x[1], reverse=True)[:5]
    # Sort by highest ticket number first (assumes higher number == newer)
    recs.sort(key=lambda r: (r.get("number") or 0), reverse=True)

    # compute priority issue (severity-weighted count)
    weights = {"Critical": 8, "High": 4, "Medium": 2, "Low": 1}
    best_id = None
    best_score = -1
    for ck, cnt in cluster_counts.items():
        meta = cluster_meta.get(ck, {})
        sev_label = (meta.get("severity") or "Medium")
        # boost clusters with very recent activity
        recent_boost = 1
        try:
            last_seen = meta.get("last_seen")
            if last_seen:
                dt = datetime.fromisoformat(last_seen)
                if (datetime.utcnow() - dt) <= timedelta(hours=6):
                    recent_boost = 1.5
        except Exception:
            pass
        score = cnt * weights.get(sev_label, 2) * recent_boost
        if score > best_score:
            best_score = score
            best_id = ck
    priority_issue = None
    if best_id:
        meta = cluster_meta.get(best_id, {})
        priority_issue = {
            "id": best_id,
            "title": meta.get("title") or best_id,
            "category": meta.get("category") or "Other",
            "severity": meta.get("severity") or "Medium",
            "occurrences": cluster_counts.get(best_id, 0),
            "last_seen": meta.get("last_seen"),
        }

    return {
        "count": len(recs),
        "total": total,
        "page": int(page),
        "page_size": int(_ps),
        "top_categories": [{"name": k, "count": v} for k, v in top_categories],
        "top_keywords": [{"word": k, "count": v} for k, v in top_keywords],
        "top_clusters": [{"cluster_key": k, "count": v} for k, v in top_clusters],
        "tag_stats": sorted([{"tag": k, "count": v} for k, v in tag_counts.items()], key=lambda x: x["count"], reverse=True)[:100],
        "recommendations": recs,
        "priorityIssue": priority_issue,
    }


@app.get("/admin/dashboard")
def dashboard(hours: int = 24):
    now = datetime.utcnow()
    win_start = now - timedelta(hours=max(1, hours))
    # Initialize hourly buckets (last 24h) aligned to exact hour starts (UTC)
    hourly = []
    series_start = (now - timedelta(hours=23)).replace(minute=0, second=0, microsecond=0)
    for i in range(0, 24):
        bucket_start = series_start + timedelta(hours=i)
        hourly.append({
            "ts": (bucket_start.isoformat() + "Z"),  # used by frontend for x-axis
            "date": bucket_start.strftime("%I%p").lstrip('0').lower(),  # backward-compat label
            "bugs": 0, "crashes": 0, "uxIssues": 0, "performance": 0, "technical": 0, "questions": 0, "features": 0, "payments": 0, "total": 0
        })

    cat_counts = {"bug": 0, "crash": 0, "ux": 0, "performance": 0, "technical": 0, "question": 0, "feature_request": 0, "payment": 0}
    platform_counts = {}
    severity_counts = {"critical": 0, "high": 0, "medium": 0, "low": 0}
    cluster_counts = {}
    cluster_meta = {}

    with get_session() as s:
        rows = s.query(HsConversation).filter(HsConversation.updated_at >= win_start).all()

    for c in rows:
        raw = ((c.subject or "") + "\n" + (c.last_text or "")).strip()
        if not raw:
            continue
        entities = classify.extract_entities(raw)
        cats, rule_score = classify.categorize(raw.lower())
        extra = llm.enrich(raw) if llm.is_enabled() else {}
        if extra.get("categories"):
            cats = sorted(set((cats or []) + (extra.get("categories") or [])))
        sev_score = severity.compute(raw, entities, rule_score)
        bucket = severity.bucketize(sev_score, 0, 0) or "low"
        severity_counts[bucket] = severity_counts.get(bucket, 0) + 1
        if extra.get("platform"):
            p = (extra.get("platform") or "").strip().lower()
            if p:
                platform_counts[p] = platform_counts.get(p, 0) + 1
        # also derive platform from entities when LLM is disabled or missing
        if (entities or {}).get("platform"):
            p2 = str((entities or {}).get("platform") or "").strip().lower()
            if p2:
                platform_counts[p2] = platform_counts.get(p2, 0) + 1

        # Hour bin index using hour-floor alignment
        if c.updated_at:
            ct = c.updated_at.replace(minute=0, second=0, microsecond=0)
            idx = int((ct - series_start).total_seconds() // 3600)
            if idx < 0 or idx > 23:
                continue
        else:
            idx = 23
        # Increment hourly counts by mapped categories
        map_keys = {
            "bug": "bugs",
            "crash": "crashes",
            "ux": "uxIssues",
            "performance": "performance",
            "technical": "technical",
            "question": "questions",
            "feature_request": "features",
            "payment": "payments",
        }
        for cat in (cats or []):
            if cat in cat_counts:
                cat_counts[cat] += 1
            key = map_keys.get(cat)
            if key:
                hourly[idx][key] = hourly[idx].get(key, 0) + 1

        ck = fingerprint.cluster_key(raw, entities)
        cluster_counts[ck] = cluster_counts.get(ck, 0) + 1
        if ck not in cluster_meta:
            cluster_meta[ck] = {
                "title": (c.subject or (raw[:60] + "...")),
                "category": (cats or ["other"])[0].replace("_", " ").title(),
                "severity": {"critical": "Critical", "high": "High", "medium": "Medium", "low": "Low"}.get(bucket, "Medium"),
            }

    for r in hourly:
        r["total"] = (r.get("bugs",0) + r.get("crashes",0) + r.get("uxIssues",0) + r.get("performance",0) + r.get("technical",0) + r.get("questions",0) + r.get("features",0) + r.get("payments",0))

    # Build category pie
    def pretty(name: str) -> str:
        mapping = {
            "bug": "Bug", "crash": "Crash", "ux": "UX Issue", "performance": "Performance",
            "technical": "Technical", "question": "Question", "feature_request": "Feature Request", "payment": "Payments"
        }
        return mapping.get(name, name.title())
    categoryData = [{"name": pretty(k), "value": v, "percentage": 0} for k,v in cat_counts.items()]
    totalCat = sum([c["value"] for c in categoryData]) or 1
    for c in categoryData:
        c["percentage"] = f"{(c['value']/totalCat*100):.1f}"

    platformData = [{"platform": k.title(), "issues": v} for k,v in platform_counts.items()]
    severityData = [
        {"severity": "Critical", "count": severity_counts.get("critical", 0), "resolved": 0},
        {"severity": "High", "count": severity_counts.get("high", 0), "resolved": 0},
        {"severity": "Medium", "count": severity_counts.get("medium", 0), "resolved": 0},
        {"severity": "Low", "count": severity_counts.get("low", 0), "resolved": 0},
    ]

    # Top issues by cluster
    top = sorted(cluster_counts.items(), key=lambda x: x[1], reverse=True)[:5]
    topIssues = []
    for ck, cnt in top:
        meta = cluster_meta.get(ck, {})
        topIssues.append({
            "id": ck,
            "title": meta.get("title") or ck,
            "category": meta.get("category") or "Other",
            "count": cnt,
            "trend": "up",
            "severity": meta.get("severity") or "Medium",
        })

    return {
        "dailyData": hourly,
        "categoryData": categoryData,
        "platformData": platformData,
        "severityData": severityData,
        "responseTimeData": [],
        "topIssues": topIssues,
        # scatter series of ticket numbers (x) over time (y) for spike detection
        "ticketTimeline": [
            {
                "ts": (c.updated_at.isoformat() if c.updated_at else None),
                "number": c.number,
                "id": c.id,
            } for c in rows if c.number is not None
        ],
        "radarData": [],
    }

@app.get("/admin/aggregates")
def aggregates(hours: int = 24, limit: int = 50):
    cutoff = datetime.utcnow() - timedelta(hours=max(1, hours))
    with get_session() as s:
        rows = s.query(HsConversation).filter(HsConversation.updated_at >= cutoff).all()
    buckets = {}
    for c in rows:
        text = ((c.subject or "") + "\n" + (c.last_text or "")).strip()
        entities = classify.extract_entities(text)
        cats, _ = classify.categorize(text)
        # Optional Claude enrichment
        extra = llm.enrich(text) if llm.is_enabled() else {}
        if extra.get("categories"):
            cats = sorted(set((cats or []) + (extra.get("categories") or [])))
        key = fingerprint.cluster_key(text, entities)
        b = buckets.setdefault(key, {"count":0, "subjects":[], "ids":[], "categories":set(), "sample_text":""})
        b["count"] += 1
        if c.subject: b["subjects"].append(c.subject)
        b["ids"].append(c.id)
        for cat in (cats or []): b["categories"].add(cat)
        if not b["sample_text"] and c.last_text:
            b["sample_text"] = c.last_text[:400]
    # build response
    items = []
    for k,v in buckets.items():
        items.append({
            "cluster_key": k,
            "count": v["count"],
            "categories": sorted(list(v["categories"])),
            "top_subjects": v["subjects"][:5],
            "sample_text": v["sample_text"],
            "ids": v["ids"][:10],
        })
    items.sort(key=lambda x: x["count"], reverse=True)
    return {"aggregates": items[:max(1,min(limit,200))]}

@app.get("/admin/topic-stats")
def topic_stats(hours: int = 24):
    cutoff = datetime.utcnow() - timedelta(hours=max(1, hours))
    with get_session() as s:
        rows = s.query(HsConversation).filter(HsConversation.updated_at >= cutoff).all()
    counts = {"bug":0, "payment":0, "performance":0, "ux":0, "account":0, "store":0, "device":0}
    crash_count = 0
    for c in rows:
        raw = ((c.subject or "") + "\n" + (c.last_text or ""))
        text = raw.lower()
        cats, _ = classify.categorize(text)
        # Optional Claude enrichment
        extra = llm.enrich(raw) if llm.is_enabled() else {}
        if extra.get("categories"):
            cats = sorted(set((cats or []) + (extra.get("categories") or [])))
        for cat in (cats or []):
            if cat in counts: counts[cat]+=1
        if "crash" in text or "exception" in text or "stuck" in text:
            crash_count += 1
    return {"by_category": counts, "crash_count": crash_count, "total": len(rows)}

@app.post("/admin/backfill")
def backfill(limit_pages: int = 1):
    # Read-only: store conversation metadata and latest text
    saved = 0
    for p in range(1, max(1, limit_pages)+1):
        try:
            data = helpscout.list_conversations(page=p)
        except Exception as e:
            # Dev-friendly response when HS credentials are not configured
            return {"ok": False, "saved": saved, "error": f"Help Scout API error: {e}", "hint": "Set HS_API_TOKEN or complete OAuth install at /helpscout/oauth/install"}
        items = data.get("_embedded", {}).get("conversations", [])
        with get_session() as s:
            for c in items:
                conv_id = c.get("id")
                number = c.get("number")
                subject = c.get("subject")
                last_text = helpscout.extract_text(c)
                raw_tags = c.get("tags") or []
                tag_names = [t.get("tag") if isinstance(t, dict) else str(t) for t in raw_tags]
                tags_str = ",".join([t for t in tag_names if t])
                # HS timestamps if present
                updated_at_dt = None
                try:
                    updated_iso = c.get("updatedAt") or c.get("createdAt")
                    if updated_iso:
                        from datetime import datetime
                        updated_at_dt = datetime.fromisoformat(updated_iso.replace("Z","+00:00")).replace(tzinfo=None)
                except Exception:
                    pass
                if conv_id:
                    upsert_hs_conversation(s, conv_id, number, subject, last_text, tags_str, updated_at_dt)
                    saved += 1
                    # auto-upsert vector (best-effort)
                    try:
                        updated_at_iso = None
                        _vector_upsert_one(conv_id, number, subject, last_text, updated_at_iso)
                    except Exception:
                        pass
        if not data.get("_links", {}).get("next"):
            break
    return {"ok": True, "saved": saved}

# Convenience GET endpoint to trigger read-only backfill from a browser
@app.get("/admin/backfill")
def backfill_get(limit_pages: int = 1):
    return backfill(limit_pages=limit_pages)

# Backfill more pages quickly (all-time crawl via paginated calls)
@app.get("/admin/backfill_all")
def backfill_all(max_pages: int = 50):
    total = 0
    last_saved = 0
    for p in range(1, max(1, max_pages)+1):
        r = backfill(limit_pages=p)
        if not r.get("ok"):
            return {"ok": False, "saved": total, "error": r.get("error")}
        total = r.get("saved", total)
        # if no new items were saved for this page, stop early (delta complete)
        if total == last_saved:
            break
        last_saved = total
    return {"ok": True, "saved": total}


# Vector indexing
@app.post("/admin/reindex_vectors")
def reindex_vectors(limit: int = 2000):
    if not pinevec.is_enabled():
        return {"ok": False, "error": "Pinecone not configured"}
    if not embeddings.is_enabled():
        return {"ok": False, "error": "Embeddings model not configured"}
    with get_session() as s:
        rows = s.query(HsConversation).order_by(HsConversation.updated_at.desc()).limit(max(1, min(limit, 10000))).all()
    payload = []
    for c in rows:
        raw = ((c.subject or "") + "\n" + (c.last_text or "")).strip()
        vec = embeddings.embed_text(raw)
        if not vec:
            continue
        payload.append({
            "id": str(c.id),
            "values": vec,
            "metadata": {
                "number": c.number,
                "subject": c.subject or "",
                "updated_at": c.updated_at.isoformat() if c.updated_at else None,
            }
        })
    if not payload:
        return {"ok": False, "error": "no vectors to upsert"}
    res = pinevec.upsert_vectors(payload)
    return {"ok": True, "upserted": len(payload), "pinecone": res}

# Convenience GET alias
@app.get("/admin/reindex_vectors")
def reindex_vectors_get(limit: int = 2000):
    return reindex_vectors(limit=limit)


@app.post("/admin/reindex_recent")
def reindex_recent(hours: int = 24, limit: int = 5000):
    # No-op when vector infra is disabled; keep endpoint for compatibility
    if not pinevec.is_enabled() or not embeddings.is_enabled():
        return {"ok": True, "upserted": 0, "note": "vector indexing disabled"}
    cutoff = datetime.utcnow() - timedelta(hours=max(1, hours))
    with get_session() as s:
        rows = s.query(HsConversation).filter(HsConversation.updated_at >= cutoff).order_by(HsConversation.updated_at.desc()).limit(max(1, min(limit, 20000))).all()
    cnt = 0
    for c in rows:
        updated_iso = c.updated_at.isoformat() if c.updated_at else None
        if _vector_upsert_one(c.id, c.number, c.subject, c.last_text, updated_iso):
            cnt += 1
    return {"ok": True, "upserted": cnt}

# Convenience GET alias
@app.get("/admin/reindex_recent")
def reindex_recent_get(hours: int = 24, limit: int = 5000):
    return reindex_recent(hours=hours, limit=limit)


@app.get("/admin/vector_search")
def vector_search(q: str, top_k: int = 10):
        if not pinevec.is_enabled() or not embeddings.is_enabled():
            return {"matches": [], "note": "vector search disabled"}
        vec = embeddings.embed_text(q)
        if not vec:
            return {"matches": []}
        res = pinevec.search(vec, top_k=top_k)
        return res

# OAuth install and callback
@app.get("/helpscout/oauth/install")
def hs_install():
    cid = os.getenv("HS_CLIENT_ID", "").strip()
    redirect_uri = os.getenv("HS_REDIRECT_URL", "").strip()
    if not cid or not redirect_uri:
        raise HTTPException(status_code=400, detail="Missing HS_CLIENT_ID or HS_REDIRECT_URL")
    # per docs
    url = (
        "https://secure.helpscout.net/authentication/authorizeClientApplication"
        f"?client_id={cid}&state=csrf&redirect_uri={redirect_uri}"
    )
    return {"authorize_url": url, "redirect_uri": redirect_uri}

@app.get("/helpscout/oauth/start")
def hs_start():
    # Convenience redirect to the Help Scout consent screen
    cid = os.getenv("HS_CLIENT_ID", "").strip()
    redirect_uri = os.getenv("HS_REDIRECT_URL", "").strip()
    if not cid or not redirect_uri:
        raise HTTPException(status_code=400, detail="Missing HS_CLIENT_ID or HS_REDIRECT_URL")
    url = (
        "https://secure.helpscout.net/authentication/authorizeClientApplication"
        f"?client_id={cid}&state=csrf&redirect_uri={redirect_uri}"
    )
    return RedirectResponse(url=url, status_code=302)

@app.get("/helpscout/oauth/callback")
def hs_callback(code: str | None = None, state: str | None = None):
    cid = os.getenv("HS_CLIENT_ID", "").strip()
    csec = os.getenv("HS_CLIENT_SECRET", "").strip()
    redirect_uri = os.getenv("HS_REDIRECT_URL", "").strip()
    if not code or not cid or not csec or not redirect_uri:
        raise HTTPException(status_code=400, detail="Missing code or client credentials")
    # exchange code for tokens
    import requests
    from datetime import datetime, timedelta
    token_url = f"{os.getenv('HS_BASE_URL','https://api.helpscout.net/v2')}/oauth2/token"
    data = {"grant_type":"authorization_code","code":code,"client_id":cid,"client_secret":csec, "redirect_uri": redirect_uri}
    r = requests.post(token_url, data=data, timeout=10)
    if r.status_code >= 300:
        raise HTTPException(status_code=502, detail=f"Token exchange failed: {r.text}")
    j = r.json()
    from models import get_session, save_hs_tokens
    with get_session() as s:
        exp = datetime.utcnow() + timedelta(seconds=int(j.get("expires_in", 3600)))
        save_hs_tokens(s, j.get("access_token"), j.get("refresh_token"), exp)
    return {"ok": True}

@app.get("/helpscout/oauth/status")
def hs_status():
    from models import get_session, get_hs_tokens
    with get_session() as s:
        row = get_hs_tokens(s)
        if not row or not row.access_token:
            return {"connected": False}
        return {
            "connected": True,
            "expires_at": row.expires_at.isoformat() if row.expires_at else None
        }

# Optional background reindexer to keep vectors fresh
_bg_thread = None

def _bg_reindex_loop():
    # Reindex every N minutes if enabled
    interval_min = int(os.getenv("VECTOR_REINDEX_INTERVAL_MIN", "30") or "30")
    interval = max(5, interval_min) * 60
    while True:
        try:
            if _vector_auto_enabled():
                try:
                    reindex_recent(hours=int(os.getenv("VECTOR_REINDEX_HOURS", "24") or "24"))
                except Exception:
                    pass
        finally:
            time.sleep(interval)

@app.on_event("startup")
def _maybe_start_reindexer():
    global _bg_thread
    if os.getenv("VECTOR_BG_REINDEX", "1") == "1" and _bg_thread is None and _vector_auto_enabled():
        _bg_thread = threading.Thread(target=_bg_reindex_loop, name="vector-reindex", daemon=True)
        _bg_thread.start()
