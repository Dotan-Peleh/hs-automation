import os, hmac, hashlib, threading, time, re as _re
from fastapi import FastAPI, Request, HTTPException, Query, Response, BackgroundTasks
from fastapi.responses import RedirectResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
import helpscout, slack
from engine import classify, fingerprint, anomaly, severity
from engine import embeddings
from engine import pine as pinevec
from engine import llm
from engine import auto_learn
from models import Base, get_session, upsert_incident, record_ticket_event, load_active_ruleset, upsert_hs_conversation, Incident, HsConversation, HsEnrichment, TicketFeedback

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

# Auto-create all tables on startup (safe - won't drop existing data)
try:
    Base.metadata.create_all(engine)
    print("✅ Database tables created/verified")
    
    # Run migrations to add new columns
    from sqlalchemy import text
    with engine.connect() as conn:
        # Add customer info columns if they don't exist (PostgreSQL syntax)
        try:
            conn.execute(text("ALTER TABLE hs_conversation ADD COLUMN IF NOT EXISTS customer_name TEXT"))
            conn.execute(text("ALTER TABLE hs_conversation ADD COLUMN IF NOT EXISTS first_name VARCHAR(128)"))
            conn.execute(text("ALTER TABLE hs_conversation ADD COLUMN IF NOT EXISTS last_name VARCHAR(128)"))
            conn.execute(text("ALTER TABLE hs_conversation ADD COLUMN IF NOT EXISTS game_user_id VARCHAR(64)"))
            conn.commit()
            print("✅ Database migrations applied successfully")
        except Exception as migration_error:
            # Ignore errors if columns already exist or using SQLite
            print(f"ℹ️  Migration info: {migration_error}")
except Exception as e:
    print(f"⚠️  Database table creation warning: {e}")

app = FastAPI(title="HS Trends", version="3.0")  # Clean rebuild with working enrichment

# CRITICAL: CORS must be configured FIRST before any other middleware
# Allow requests from Vercel deployments and localhost
allowed_origins = [
    "http://localhost:3000",
    "http://localhost:3001", 
    "https://*.vercel.app",
    "https://hs-automation-9fw30d31m-dotan-s-projects.vercel.app",
]

# Also allow all origins with wildcard for maximum compatibility
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow all origins
    allow_credentials=False,  # Must be False when allow_origins is "*"
    allow_methods=["*"],  # Allow all HTTP methods
    allow_headers=["*"],  # Allow all headers
    expose_headers=["*"],  # Expose all headers in response
)

# Add exception handler to ensure CORS headers on errors
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request, exc):
    from fastapi.responses import JSONResponse
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": str(exc.detail)},
        headers={
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "*",
            "Access-Control-Allow-Headers": "*",
        }
    )

@app.exception_handler(Exception)
async def general_exception_handler(request, exc):
    from fastapi.responses import JSONResponse
    import traceback
    print(f"❌ Unhandled exception: {exc}")
    traceback.print_exc()
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error", "error": str(exc)},
        headers={
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "*",
            "Access-Control-Allow-Headers": "*",
        }
    )

# --- Very lightweight in‑process pubsub for real‑time notifications (dev only) ---
import asyncio
_subscribers: list[asyncio.Queue] = []

def _publish_event(ev: dict):
    """Publish event to all SSE subscribers"""
    try:
        import json
        event_data = json.dumps(ev)
        for q in list(_subscribers):
            try:
                q.put_nowait(event_data)
            except Exception:
                # Remove dead subscribers
                try:
                    _subscribers.remove(q)
                except Exception:
                    pass
    except Exception as e:
        print(f"ERROR: Failed to publish event: {e}")

@app.get("/admin/events")
async def events_stream():
    """Server-Sent Events endpoint for real-time dashboard updates"""
    from fastapi.responses import StreamingResponse
    
    async def event_gen():
        q: asyncio.Queue = asyncio.Queue(maxsize=100)
        _subscribers.append(q)
        print(f"🔌 New SSE subscriber connected. Total: {len(_subscribers)}")
        
        try:
            # Send initial connection event
            import json
            yield f"data: {json.dumps({'type': 'connected', 'timestamp': time.time()})}\n\n"
            
            while True:
                try:
                    ev = await asyncio.wait_for(q.get(), timeout=30.0)
                    yield f"data: {ev}\n\n"
                except asyncio.TimeoutError:
                    # Send keepalive every 30 seconds
                    yield f"data: {json.dumps({'type': 'keepalive', 'timestamp': time.time()})}\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            try:
                _subscribers.remove(q)
                print(f"🔌 SSE subscriber disconnected. Total: {len(_subscribers)}")
            except:
                pass
    
    return StreamingResponse(event_gen(), media_type="text/event-stream")

@app.get("/admin/poll")
def poll_for_updates(since: int = 0):
    """Polling fallback for new tickets since timestamp"""
    try:
        with get_session() as s:
            # Get recent conversations updated since 'since' timestamp
            from datetime import datetime
            since_dt = datetime.fromtimestamp(since) if since > 0 else datetime.utcnow().replace(hour=0, minute=0, second=0)
            
            recent = s.query(HsConversation).filter(
                HsConversation.updated_at >= since_dt
            ).order_by(HsConversation.updated_at.desc()).limit(10).all()
            
            updates = []
            for conv in recent:
                updates.append({
                    'type': 'ticket_update',
                    'conv_id': conv.id,
                    'number': conv.number,
                    'subject': conv.subject,
                    'updated_at': conv.updated_at.timestamp() if conv.updated_at else 0
                })
            
            return {
                'ok': True,
                'updates': updates,
                'timestamp': time.time()
            }
    except Exception as e:
        print(f"ERROR: Polling failed: {e}")
        return {'ok': False, 'error': str(e), 'updates': [], 'timestamp': time.time()}

# Reply to Help Scout conversation with a templated or custom message
@app.post("/admin/reply")
def reply(conv_id: int, text: str):
    try:
        import requests
        HS = os.getenv("HS_BASE_URL", "https://api.helpscout.net/v2")
        hdrs = {"Accept":"application/json","User-Agent":"hs-trends/0.1"}
        # borrow existing auth header logic
        hdrs.update(helpscout._bearer_header())
        body = {"text": text}
        r = requests.post(f"{HS}/conversations/{conv_id}/notes", headers={**hdrs, "Content-Type":"application/json"}, json=body, timeout=10)
        r.raise_for_status()
        return {"ok": True}
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Reply failed: {e}")

@app.get("/healthz")
def healthz():
    return {"status": "ok"}

@app.get("/admin/system-status")
async def system_status():
    """Comprehensive system status check"""
    with get_session() as s:
        total_tickets = s.query(HsConversation).count()
        enriched_tickets = s.query(HsEnrichment).count()
        recent_tickets = s.query(HsConversation).filter(
            HsConversation.updated_at >= datetime.utcnow() - timedelta(hours=24)
        ).count()
        
    return {
        "version": "3.0",
        "slack_configured": bool(slack.BOT and slack.DEFAULT_CH),
        "llm_configured": llm.is_enabled(),
        "database": {
            "total_tickets": total_tickets,
            "enriched_tickets": enriched_tickets,
            "enrichment_rate": f"{(enriched_tickets/total_tickets*100):.1f}%" if total_tickets > 0 else "0%",
            "recent_24h": recent_tickets
        },
        "status": "operational"
    }

@app.delete("/admin/clear-ticket-cache")
async def clear_ticket_cache(ticket_number: int):
    """Clear enrichment cache for a specific ticket"""
    with get_session() as s:
        # Find ticket by number
        conv = s.query(HsConversation).filter(HsConversation.number == ticket_number).first()
        if not conv:
            return {"ok": False, "error": f"Ticket #{ticket_number} not found"}
        
        # Delete cached enrichment
        cached = s.query(HsEnrichment).filter(HsEnrichment.conv_id == conv.id).first()
        if cached:
            s.delete(cached)
            s.commit()
            return {"ok": True, "message": f"✅ Cleared cache for ticket #{ticket_number}. Run enrich-from-db to re-analyze."}
        else:
            return {"ok": False, "message": f"Ticket #{ticket_number} has no cache to clear"}

@app.post("/admin/enrich-from-db")
async def enrich_from_database(limit: int = 20, debug: bool = False):
    """Enrich tickets directly from database (no Help Scout fetch needed)"""
    import hashlib
    with get_session() as s:
        # Get tickets without enrichment or with empty/incomplete enrichment
        # Check ALL recent tickets, not just first N
        all_tickets = s.query(HsConversation).order_by(HsConversation.number.desc()).limit(100).all()
        unenriched = []
        
        print(f"🔍 Scanning {len(all_tickets)} recent tickets for missing enrichment...")
        
        for t in all_tickets:
            cached = s.query(HsEnrichment).filter(HsEnrichment.conv_id == t.id).first()
            
            # Get actual values
            intent = getattr(cached, 'intent', None) if cached else None
            summary = getattr(cached, 'summary', None) if cached else None
            root_cause = getattr(cached, 'root_cause', None) if cached else None
            
            # DEBUG: Print first 10 to see what's in DB
            if debug and len(unenriched) < 10:
                print(f"DEBUG #{t.number}: cached={bool(cached)}, intent={repr(intent)}, summary={repr(summary)[:50]}")
            
            # Ticket needs enrichment if ANY of these are true:
            needs_enrichment = (
                not cached or  # No cache at all
                not intent or  # intent is None/null
                str(intent).strip() == '' or  # Empty string
                str(intent).lower() == 'none' or  # String "none" or "None"
                not summary or  # summary is None/null
                str(summary).strip() == '' or  # Empty string
                str(summary).lower() == 'none' or  # String "none"
                summary == 'Support Request' or  # Default fallback
                summary == 'No description available' or  # Another fallback
                len(str(summary).strip()) < 10  # Too short
            )
            
            if needs_enrichment:
                unenriched.append(t)
                if len(unenriched) <= 5:  # Log first 5
                    print(f"🔍 Needs enrichment: #{t.number} - intent={repr(intent)}, summary={repr(summary)[:50]}")
                if len(unenriched) >= limit:
                    break
        
        enriched_count = 0
        for conv in unenriched:
            raw = ((conv.subject or "") + "\n" + (conv.last_text or "")).strip()
            if not raw or len(raw) < 20:
                continue
            
            # Get user corrections
            corrections = s.query(TicketFeedback).filter(
                TicketFeedback.action_type == 'tag_correction'
            ).order_by(TicketFeedback.created_at.desc()).limit(5).all()
            
            user_corrections = []
            for corr in corrections:
                try:
                    import json
                    feedback = json.loads(corr.feedback_data or '{}')
                    orig = s.query(HsConversation).get(corr.conversation_id)
                    if orig and feedback.get('correct_intent'):
                        user_corrections.append({
                            "text": ((orig.subject or "") + "\n" + (orig.last_text or "")).strip(),
                            "correct_intent": feedback.get('correct_intent'),
                            "correct_severity": feedback.get('correct_severity'),
                            "notes": feedback.get('notes')
                        })
                except:
                    pass
            
            # Enrich
            extra = llm.enrich(raw, user_corrections=user_corrections) if llm.is_enabled() else {}
            if not extra or not extra.get('intent'):
                continue
            
            # Compute severity
            entities = classify.extract_entities(raw)
            cats, rule_score = classify.categorize(raw)
            sev_score = severity.compute(raw, entities, rule_score)
            bucket = severity.bucketize(sev_score, 0, 0)
            if not bucket:
                bucket = "high" if sev_score >= 50 else ("medium" if sev_score >= 30 else "low")
            if extra.get("intent") == "incomplete_ticket":
                bucket = "low"
            if extra.get("intent") == "unreadable":
                bucket = "low"
            
            # Save (UPDATE existing or INSERT new)
            try:
                cached = s.query(HsEnrichment).filter(HsEnrichment.conv_id == conv.id).first()
                if not cached:
                    cached = HsEnrichment(conv_id=conv.id)
                    s.add(cached)
                
                cached.content_hash = hashlib.sha256(raw.encode('utf-8')).hexdigest()
                cached.summary = extra.get('summary')
                cached.tags = ','.join(extra.get('tags', []))
                cached.intent = extra.get('intent')
                cached.root_cause = extra.get('root_cause')
                cached.severity_bucket = bucket
                cached.last_enriched_at = datetime.utcnow()
                s.commit()
                enriched_count += 1
                print(f"✅ Enriched #{conv.number}: {extra.get('intent')} - {extra.get('summary')}")
            except Exception as e:
                s.rollback()
                print(f"❌ Failed #{conv.number}: {e}")
        
        return {
            "ok": True,
            "enriched": enriched_count,
            "total_unenriched": len(unenriched),
            "message": f"Enriched {enriched_count}/{len(unenriched)} tickets from database"
        }

@app.get("/admin/test-slack")
async def test_slack():
    """Test Slack connection"""
    if not slack.BOT or not slack.DEFAULT_CH:
        return {"ok": False, "error": "Slack not configured", "bot": bool(slack.BOT), "channel": bool(slack.DEFAULT_CH)}
    
    try:
        from datetime import datetime
        result = slack.send_ticket_alert(
            ticket_number=9999,
            subject="🧪 TEST ALERT - Slack Integration Working!",
            severity="medium",
            intent="test",
            root_cause="This is a test message to verify Slack integration",
            summary="Testing Slack notifications for Help Scout alerts",
            tags=["test", "slack", "integration"],
            hs_link="https://secure.helpscout.net/",
            customer_name="Test User",
            game_user_id="test123456789",
            platform="iOS",
            device="iPhone 14 Pro",
            created_at=datetime.utcnow().isoformat() + "Z"
        )
        
        return {
            "ok": result,
            "message": "✅ Test message sent! Check your Slack channel." if result else "❌ Failed to send. Check Render logs.",
            "channel": slack.DEFAULT_CH
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}

# Mark ticket as seen/dismissed
@app.post("/admin/ticket/mark_seen")
def mark_ticket_seen(conv_id: int, action: str = 'dismissed'):
    """Mark a ticket as seen or dismissed by the user."""
    if not conv_id:
        raise HTTPException(status_code=400, detail="conv_id required")
        
    with get_session() as s:
        # Upsert feedback
        existing = s.query(TicketFeedback).filter_by(conversation_id=conv_id, action_type=action).first()
        if existing:
            existing.created_at = datetime.utcnow()
        else:
            fb = TicketFeedback(conversation_id=conv_id, action_type=action)
            s.add(fb)
        s.commit()
    return {"ok": True}

# Provide tag/intent correction feedback
@app.post("/admin/ticket/feedback")
def provide_feedback(conv_id: int, correct_intent: str = None, correct_severity: str = None, notes: str = None):
    """User provides feedback on incorrect tagging AND immediately update the ticket."""
    import json
    updated_ticket = None  # Initialize to None

    with get_session() as s:
        try:
            enrichment = s.query(HsEnrichment).filter(HsEnrichment.conv_id == conv_id).first()
            if enrichment:
                if correct_intent:
                    enrichment.intent = correct_intent
                if correct_severity:
                    enrichment.severity_bucket = correct_severity
                enrichment.last_enriched_at = datetime.utcnow()
                s.commit()
                s.refresh(enrichment) # Refresh to get the latest state from the DB
                updated_ticket = {
                    "conv_id": enrichment.conv_id,
                    "intent": enrichment.intent,
                    "severity_bucket": enrichment.severity_bucket,
                }
            
            # Save feedback for future learning
            feedback_data = {"correct_intent": correct_intent, "correct_severity": correct_severity, "notes": notes}
            
            ticket_num = 0
            if enrichment:
                conv_for_num = s.query(HsConversation).filter(HsConversation.id == enrichment.conv_id).first()
                if conv_for_num:
                    ticket_num = conv_for_num.number

            new_feedback = TicketFeedback(
                conversation_id=conv_id,
                ticket_number=ticket_num,
                action_type='tag_correction',
                feedback_data=json.dumps(feedback_data)
            )
            s.add(new_feedback)
            s.commit()
        except Exception as e:
            s.rollback()
            print(f"❌ Failed to save feedback: {e}")
            raise HTTPException(status_code=500, detail="Failed to save feedback")

    return {"ok": True, "message": "Feedback saved and ticket updated.", "updated_ticket": updated_ticket}

# Unmark ticket (remove from dismissed)
@app.post("/admin/ticket/unmark")
def unmark_ticket(conv_id: int):
    """Remove a ticket from the dismissed/seen list."""
    with get_session() as s:
        s.query(TicketFeedback).filter_by(conversation_id=conv_id, action_type='dismissed').delete()
        s.query(TicketFeedback).filter_by(conversation_id=conv_id, action_type='seen').delete()
        s.commit()
    return {"ok": True}

# Get seen/dismissed ticket IDs
@app.get("/admin/ticket/dismissed")
def get_dismissed_tickets():
    """Get list of conversation IDs that have been marked as seen or dismissed."""
    with get_session() as s:
        rows = s.query(TicketFeedback).filter(TicketFeedback.action_type.in_(['seen', 'dismissed'])).all()
    return {"dismissed": [r.conversation_id for r in rows]}

# Get all tag corrections to analyze and improve the model
@app.get("/admin/feedback/summary")
def feedback_summary():
    """Analyze all tag corrections to identify patterns and improve detection."""
    import json
    with get_session() as s:
        corrections = s.query(TicketFeedback).filter_by(action_type='tag_correction').all()
    
    intent_corrections = {}
    severity_corrections = {}
    all_feedback = []
    
    for fb in corrections:
        try:
            data = json.loads(fb.feedback_data or '{}')
            if data.get('correct_intent'):
                intent_corrections[data['correct_intent']] = intent_corrections.get(data['correct_intent'], 0) + 1
            if data.get('correct_severity'):
                severity_corrections[data['correct_severity']] = severity_corrections.get(data['correct_severity'], 0) + 1
            
            # Get the original ticket to compare
            with get_session() as s2:
                conv = s2.query(HsConversation).filter_by(id=fb.conversation_id).first()
                if conv:
                    all_feedback.append({
                        'ticket_number': conv.number,
                        'subject': conv.subject,
                        'text_preview': (conv.last_text or '')[:200],
                        'correct_intent': data.get('correct_intent'),
                        'correct_severity': data.get('correct_severity'),
                        'notes': data.get('notes'),
                        'created_at': fb.created_at.isoformat() if fb.created_at else None
                    })
        except Exception:
            pass
    
    return {
        'total_corrections': len(corrections),
        'intent_distribution': intent_corrections,
        'severity_distribution': severity_corrections,
        'all_feedback': all_feedback,
        'insights': {
            'most_corrected_intent': max(intent_corrections.items(), key=lambda x: x[1])[0] if intent_corrections else None,
            'most_corrected_severity': max(severity_corrections.items(), key=lambda x: x[1])[0] if severity_corrections else None
        }
    }

# Get auto-learning statistics
@app.get("/admin/learning/stats")
def learning_stats():
    """Get statistics about the automatic learning system."""
    stats = auto_learn.get_feedback_stats()
    stats['status'] = 'active' if stats['total_learned_intents'] > 0 else 'waiting_for_feedback'
    stats['message'] = (
        f"Learning from {stats['total_learned_intents']} intent patterns and "
        f"{stats['total_exact_matches']} exact matches. "
        "Corrections are applied automatically to all new tickets!"
    ) if stats['total_learned_intents'] > 0 else "No feedback collected yet. Start correcting tags to teach the AI!"
    return stats

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

async def process_webhook_event(conv_id: int):
    """(Async) Fetch full conversation, enrich, and store. This is slow."""
    with get_session() as s:
        try:
            conv = helpscout.fetch_conversation(conv_id)
            if not conv: return
            
            # Extract fields from conversation object
            number = conv.get('number')
            subject = conv.get('subject')
            last_text = helpscout.extract_text(conv)
            raw_tags = conv.get('tags') or []
            tag_names = [t.get('tag') if isinstance(t, dict) else str(t) for t in raw_tags]
            
            # Extract customer info (name and game UserID)
            first_name, last_name = helpscout.extract_customer_name(conv)
            customer_name = f"{first_name or ''} {last_name or ''}".strip() or None
            
            # Extract UserID from message text (format: "UserId = XXXX" or "userid: XXXX")
            user_id = None
            try:
                import re
                match = re.search(r'(?i)user\s*id\s*[=:]\s*([a-f0-9]{24})', last_text or '')
                if match:
                    user_id = match.group(1)
            except Exception:
                pass
            
            # Check if agent has replied (look at threads)
            threads = conv.get('_embedded', {}).get('threads', []) if '_embedded' in conv else []
            agent_replied = False
            for thread in threads:
                created_by = thread.get('createdBy', {})
                if created_by.get('type') == 'user' and created_by.get('email'):
                    # This is a staff reply (not customer)
                    agent_replied = True
                    break
            
            # Add agent:replied tag if agent responded
            if agent_replied and 'agent:replied' not in tag_names:
                tag_names.append('agent:replied')
            
            tags_str = ','.join([t for t in tag_names if t])
            print(f"📋 Ticket #{number}: Customer={customer_name}, UserID={user_id}, Tags={tags_str}, Agent replied={agent_replied}")
            
            # Parse timestamp
            updated_at_dt = None
            try:
                updated_iso = conv.get('updatedAt') or conv.get('createdAt')
                if updated_iso:
                    from datetime import datetime as dt
                    updated_at_dt = dt.fromisoformat(updated_iso.replace('Z', '+00:00')).replace(tzinfo=None)
            except Exception:
                pass
            
            # Upsert with correct arguments (including customer info)
            upsert_hs_conversation(s, conv_id, number, subject, last_text, tags_str, updated_at_dt, customer_name, first_name, last_name, user_id)
            
            # ENRICH NEW TICKETS (with learning from your corrections!)
            raw = ((subject or "") + "\n" + (last_text or "")).strip()
            content_hash = None
            try:
                import hashlib
                content_hash = hashlib.sha256(raw.encode('utf-8')).hexdigest()
            except Exception:
                pass
            
            # Check if already enriched
            cached = s.query(HsEnrichment).filter(HsEnrichment.conv_id == conv_id).first()
            
            should_enrich = False
            if not cached:
                should_enrich = True
                print(f"🆕 NEW TICKET #{number} - MUST enrich (no cache)")
            elif not getattr(cached, 'intent', None):
                should_enrich = True
                print(f"🔄 INCOMPLETE CACHE for #{number} - MUST enrich (missing intent)")
            elif content_hash and getattr(cached, 'content_hash', None) != content_hash:
                should_enrich = True
                print(f"🔄 Content changed for #{number} - will re-enrich")
            else:
                print(f"✅ Already enriched #{number} - using cache")
            
            if should_enrich:
                # Fetch YOUR recent corrections (few-shot learning!)
                user_corrections = []
                try:
                    corrections = s.query(TicketFeedback).filter(
                        TicketFeedback.action_type == 'tag_correction'
                    ).order_by(TicketFeedback.created_at.desc()).limit(5).all()
                    
                    for corr in corrections:
                        try:
                            import json
                            feedback = json.loads(corr.feedback_data) if corr.feedback_data else {}
                            orig_conv = s.query(HsConversation).get(corr.conversation_id)
                            if orig_conv and feedback.get('correct_intent'):
                                user_corrections.append({
                                    "text": ((orig_conv.subject or "") + "\n" + (orig_conv.last_text or "")).strip(),
                                    "correct_intent": feedback.get('correct_intent'),
                                    "correct_severity": feedback.get('correct_severity'),
                                    "notes": feedback.get('notes')
                                })
                        except:
                            continue
                except Exception:
                    pass
                
                # Call LLM with your corrections as examples!
                extra = llm.enrich(raw, user_corrections=user_corrections) if llm.is_enabled() and raw else {}
                
                # If enrichment fails, don't use high-score keywords. Default to a safe level.
                if not extra.get("intent"):
                    print("⚠️ LLM enrichment failed or returned no intent. Defaulting severity to MEDIUM.")
                    bucket = "medium"
                    sev_score = 30  # Default score for medium
                    entities = {}
                else:
                    # Compute severity ONLY if enrichment was successful
                    entities = classify.extract_entities(raw)
                    cats, rule_score = classify.categorize(raw)
                    sev_score = severity.compute(raw, entities, rule_score)
                    bucket = severity.bucketize(sev_score, 0, 0)
                    if not bucket:
                        # Fallback to score-based bucketing if anomaly detection doesn't trigger
                        if sev_score >= 50:
                            bucket = "high"
                        elif sev_score >= 30:
                            bucket = "medium"
                        else:
                            bucket = "low"
                
                # NEW: Granular severity overrides based on intent and root cause
                intent = extra.get("intent")
                root_cause = extra.get("root_cause", "").lower()
                new_bucket = None

                if intent == 'crash_report':
                    new_bucket = 'high'
                elif intent == 'billing_issue' or intent == 'missing_purchase_reward':
                    if any(k in raw.lower() for k in ["charge twice", "double charge"]):
                        new_bucket = 'high'
                    elif 'refund' in root_cause:
                        new_bucket = 'medium'
                    else:
                        new_bucket = 'high'  # Default for billing issues
                elif intent == 'lost_progress':
                    new_bucket = 'high'
                elif 'app freezing/stuck' in root_cause:
                    new_bucket = 'medium'
                elif intent == 'bug_report' and 'gameplay' in root_cause:
                    # Low by default, but check for recent volume
                    try:
                        from datetime import datetime, timedelta
                        two_days_ago = datetime.utcnow() - timedelta(days=2)
                        recent_complaints = s.query(HsEnrichment).filter(
                            HsEnrichment.intent == 'bug_report',
                            HsEnrichment.last_enriched_at >= two_days_ago
                        ).count()
                        
                        if recent_complaints >= 5: # If 5 or more in 48h
                            new_bucket = 'high'
                        elif recent_complaints >= 3: # If 3 or more in 48h
                            new_bucket = 'medium'
                        else:
                            new_bucket = 'low'
                    except Exception as e:
                        print(f"⚠️ Failed to check recent complaint volume: {e}")
                        new_bucket = 'low'
                elif intent == 'delete_account':
                    new_bucket = 'low'
                elif intent == 'question' or intent == 'feedback':
                    new_bucket = 'low'
                elif intent == 'offerwall_issue':
                    new_bucket = 'low'

                # Keyword-based overrides for critical issues
                if any(k in raw.lower() for k in ["can't play", "unable to play"]):
                    new_bucket = 'high'
                
                if new_bucket:
                    print(f"🧠 Overriding severity for intent '{intent}'/'{root_cause}' to '{new_bucket}' (was '{bucket}')")
                    bucket = new_bucket
                
                # Force empty tickets to LOW (FINAL OVERRIDE)
                if extra.get("intent") == "incomplete_ticket":
                    bucket = "low"
                
                # Force unreadable/incomprehensible tickets to LOW
                if extra.get("intent") == "unreadable":
                    bucket = "low"
                
                # Save to cache (UPSERT - update if exists, insert if new)
                try:
                    from datetime import datetime
                    if not cached:
                        cached = HsEnrichment(conv_id=conv_id)
                        s.add(cached)
                    
                    cached.content_hash = content_hash
                    cached.summary = extra.get('summary')
                    cached.tags = ','.join(extra.get('tags', []))
                    cached.intent = extra.get('intent')
                    cached.root_cause = extra.get('root_cause')
                    cached.severity_bucket = bucket
                    cached.last_enriched_at = datetime.utcnow()
                    s.commit()
                    print(f"💾 Saved enrichment for #{number}")

                    # Publish event for real-time dashboard updates ONLY after successful save
                    print(f"📡 Publishing SSE event for conv_id {conv_id}, number {number}")
                    _publish_event({
                        'type': 'new_message',
                        'conv_id': conv_id,
                        'number': number,
                        'subject': subject
                    })
                    print(f"✅ SSE event published successfully")

                except Exception as e:
                    print(f"❌ Failed to save: {e}")
                    s.rollback()
                
                # Send Slack alert for ALL tickets (including empty ones!)
                # But SKIP if agent already replied (no spam for handled tickets)
                if extra.get("intent") and not agent_replied:
                    intent_val = extra.get("intent", "").lower()
                    
                    # Special message for empty tickets
                    if intent_val == "incomplete_ticket":
                        print(f"📢 Sending Slack alert for EMPTY ticket #{number} - severity: LOW")
                    else:
                        print(f"📢 Sending Slack alert for #{number}: {bucket} severity")
                    
                    slack_tags = extra.get("tags", []).copy() if extra.get("tags") else []
                    if intent_val == "delete_account":
                        slack_tags.append("🚨 DELETE_REQUEST")
                    elif intent_val == "incomplete_ticket":
                        slack_tags.append("📭 EMPTY_TICKET")
                    elif intent_val == "unreadable":
                        slack_tags.append("❓ UNREADABLE")
                    elif intent_val == "offerwall_issue":
                        slack_tags.append("🎁 OfferWall")
                    
                    # Extract platform and device from entities
                    platform_val = entities.get("platform")
                    device_val = entities.get("device")
                    
                    # Get created_at timestamp from conversation
                    created_at_str = conv.get('createdAt') or conv.get('updatedAt')
                    
                    slack.send_ticket_alert(
                        ticket_number=number,
                        subject=subject or "No subject",
                        severity=bucket or "low",
                        intent=extra.get("intent", "unknown"),
                        root_cause=extra.get("root_cause", ""),
                        summary=extra.get("summary", "No summary"),
                        tags=slack_tags,
                        hs_link=f"https://secure.helpscout.net/conversation/{conv_id}",
                        customer_name=customer_name,
                        game_user_id=user_id,
                        platform=platform_val,
                        device=device_val,
                        created_at=created_at_str
                    )
                elif agent_replied:
                    print(f"⏭️ Skip Slack alert for #{number} - agent already replied")
            
        except Exception as e:
            print(f"❌ ERROR: Webhook processing failed for conv_id {conv_id}: {e}")
            import traceback
            traceback.print_exc()

@app.post("/helpscout/webhook")
async def hs_webhook(req: Request, background_tasks: BackgroundTasks):
    body = await req.body()
    secret = os.getenv("HS_WEBHOOK_SECRET", "").strip()
    
    # Validate signature if secret is configured
    if secret:
        sig = req.headers.get("X-HelpScout-Signature", "")
        mac = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, mac):
            print("WARNING: Signature mismatch but allowing request for debugging")
            # In production, you would uncomment this:
            # raise HTTPException(status_code=401, detail="Invalid HS signature")

    # Parse webhook payload
    try:
        payload = await req.json()
    except Exception:
        return {"ok": True}  # Ignore malformed JSON

    conv_id = helpscout.extract_conversation_id(payload)
    if not conv_id:
        return {"ok": True}  # Nothing to do
    
    # Process in background to avoid timeouts
    background_tasks.add_task(process_webhook_event, conv_id)
    
    return {"ok": True}

@app.post("/admin/test-webhook")
async def test_webhook(conv_id: int, background_tasks: BackgroundTasks):
    """Test endpoint to manually trigger webhook processing"""
    print(f"🧪 Testing webhook processing for conv_id {conv_id}")
    background_tasks.add_task(process_webhook_event, conv_id)
    return {"ok": True, "message": f"Webhook processing triggered for conv_id {conv_id}"}

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
    # Align to 24h window from 10:00 UTC to next 10:00 UTC when hours==24
    if int(hours) == 24:
        win_start = now.replace(hour=10, minute=0, second=0, microsecond=0)
        if now < win_start:
            win_start = win_start - timedelta(days=1)
    else:
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
            # Align to 24h window from 10:00 UTC to next 10:00 UTC
            if int(hours) == 24:
                day_start = now.replace(hour=10, minute=0, second=0, microsecond=0)
                if now < day_start:
                    day_start = day_start - timedelta(days=1)
                q = s.query(HsConversation).filter(HsConversation.updated_at >= day_start)
            else:
                cutoff = now - timedelta(hours=max(1, hours))
                q = s.query(HsConversation).filter(HsConversation.updated_at >= cutoff)
        if min_number is not None:
            try:
                q = q.filter(HsConversation.number > int(min_number))
            except Exception:
                pass
        q = q.order_by(HsConversation.updated_at.desc())
        # Get dismissed ticket IDs but DON'T filter them out - just mark them as done
        dismissed = s.query(TicketFeedback).filter(
            TicketFeedback.action_type.in_(['seen', 'dismissed', 'done'])
        ).all()
        dismissed_ids = [fb.conversation_id for fb in dismissed]
        
        # DON'T FILTER - we'll show them but mark as done in the response
            
        # total matching count before paging
        try:
            total = q.count()
        except Exception:
            total = 0
        # For page 1, get ALL rows for category/keyword/cluster counts, then paginate
        # For subsequent pages, only get the page slice
        if int(page) == 1:
            all_rows = q.all()
        else:
            all_rows = []
        # apply paging
        _ps = page_size if page_size and page_size > 0 else limit
        _ps = max(1, min(int(_ps), 1000))
        _off = max(0, (int(page) - 1) * _ps)
        rows = q.offset(_off).limit(_ps).all()

    # Get dismissed ticket IDs but DON'T filter - just mark them visually
    dismissed_ids = set()
    with get_session() as s2:
        dismissed = s2.query(TicketFeedback).filter(
            TicketFeedback.action_type.in_(['seen', 'dismissed', 'done'])
        ).all()
        dismissed_ids = set(fb.conversation_id for fb in dismissed)

    recs = []
    cat_totals = {}
    word_counts = {}
    cluster_counts = {}
    cluster_meta = {}
    tag_counts = {}
    stop = set("""
        the a an and or for from with into on at to in of is are was were be been have has had i you we they he she it this that those these not can't cannot don't do does did as by if then so but our your their my me us them when where which who whom why how what
    """.split())
    
    # First pass: lightweight category/keyword/cluster counting on ALL messages (page 1 only)
    if all_rows:
        for c in all_rows:
            raw = ((c.subject or "") + "\n" + (c.last_text or "")).strip()
            entities = classify.extract_entities(raw)
            cats, rule_score = classify.categorize(raw)
            cats = [c for c in (cats or []) if c not in ("uncategorized", "device")]
            for cat in (cats or []):
                cat_totals[cat] = cat_totals.get(cat, 0) + 1
            ck = fingerprint.cluster_key(raw, entities)
            cluster_counts[ck] = cluster_counts.get(ck, 0) + 1
            # Track basic cluster metadata
            if ck not in cluster_meta:
                sev_score = severity.compute(raw, entities, rule_score)
                bucket = severity.bucketize(sev_score, 0, 0)
                if not bucket:
                    if sev_score >= 50:
                        bucket = "high"
                    elif sev_score >= 30:
                        bucket = "medium"
                    else:
                        bucket = "low"
                cluster_meta[ck] = {
                    "title": (c.subject or (raw[:60] + "...")),
                    "category": (cats or ["other"])[0].replace("_", " ").title(),
                    "severity": {"critical": "Critical", "high": "High", "medium": "Medium", "low": "Low"}.get(bucket, "Medium"),
                    "last_seen": c.updated_at.isoformat() if c.updated_at else None,
                }
            else:
                # Update last_seen
                try:
                    prev = cluster_meta[ck].get("last_seen")
                    cur = c.updated_at.isoformat() if c.updated_at else None
                    if cur and (not prev or cur > prev):
                        cluster_meta[ck]["last_seen"] = cur
                except Exception:
                    pass
            
            # This is where we determine if an agent has replied
            agent_replied = False
            try:
                # A simple check for now: if there's more than one thread, assume an agent replied.
                # This is a proxy and can be improved with more detailed thread analysis.
                if c.threads and len(c.threads) > 1:
                    agent_replied = True
            except:
                pass
            
            # Store this status to be used in the final recs object
            c.agent_replied_status = agent_replied

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

    def add_keywords_smart(text: str):
        # gensim_keywords is not available, skip this feature
                return

    import re

    def detect_sentiment(text: str) -> str:
        """Detect if feedback is positive (compliment) or negative (issue/problem)"""
        t = text.lower()
        
        # Strong issue indicators - these override any positives
        strong_issues = [
            'accidentally', 'accident', 'refund', 'help me', 'can you help', 'please help',
            'i\'m sorry', 'need help', 'mistake', 'wrong', 'error', 'problem', 'issue'
        ]
        
        # If it's clearly asking for help or reporting a problem, it's NOT a compliment
        if any(phrase in t for phrase in strong_issues):
            return 'neutral'  # Don't tag support requests as compliments
        
        # True compliment indicators (must be clear praise without issues)
        compliments = [
            'love this', 'love the', 'great game', 'awesome', 'amazing game', 
            'fantastic', 'excellent', 'perfect', 'best game', 'favorite game',
            'really enjoy', 'enjoying', 'so much fun', 'addicted', 'can\'t stop playing'
        ]
        # Issue/negative indicators  
        issues = [
            'however', 'but', 'unfortunately', 'problem', 'issue', 'bug', 'broken',
            'irritating', 'annoying', 'frustrating', 'ridiculous', 'terrible', 'bad',
            'worst', 'hate', 'disappointed', 'crash', 'freeze', 'stuck', 'won\'t work',
            'can\'t', 'cannot', 'doesn\'t work', 'not working', 'too many', 'too much'
        ]
        
        has_compliment = any(phrase in t for phrase in compliments)
        has_issue = any(word in t for word in issues)
        
        # If message has both compliment and issue, it's mixed feedback
        if has_compliment and has_issue:
            return 'mixed'
        elif has_compliment:
            return 'positive'
        elif has_issue:
            return 'negative'
        return 'neutral'

    def derive_custom_tags(text: str, entities: dict, cats: list[str] | None, extra: dict | None) -> list[str]:
        t = (text or '').lower()
        tags: list[str] = []
        # Intent detection (high-level user intent)
        
        # Sentiment tagging for feedback
        sentiment = detect_sentiment(text)
        if sentiment == 'positive':
            tags.append('sentiment:compliment')
        elif sentiment == 'negative':
            tags.append('sentiment:issue')
        elif sentiment == 'mixed':
            tags.append('sentiment:mixed')
        
        # Offerwall / rewards for tasks
        if any(k in t for k in ("offerwall", "tapjoy", "ironsource", "offer", "reward", "task", "gem", "coin", "credit")) and any(k in t for k in ("not received", "didn't get", "missing", "did not receive", "no reward")):
            # EXCLUSION: Do not tag as offerwall if it's about in-game features
            if not any(k in t for k in ("blossom bounty", "flower")):
                tags.append("intent:offerwall_issue")
                tags.append("tag:offerwall")
        
        # PRIORITY 1: Beta feedback / reviews / opinions (CHECK FIRST!)
        # These should ALWAYS be LOW priority, even if they mention bugs/crashes
        if any(k in t for k in ("beta feedback", "written new beta feedback", "new beta feedback", "feedback for", "my feedback", "review:", "opinion", "suggestion", "has written new beta")):
            tags.append("intent:beta_feedback")
            return tags  # Return early - don't check other intents
        
        # PRIORITY 2: Refund / billing
        if any(k in t for k in ("refund", "chargeback", "charged twice", "double charge", "money back", "unauthorized charge", "billing issue", "payment issue", "invoice", "receipt")):
            tags.append("intent:refund_request")
        if any(k in t for k in ("cancel subscription", "unsubscribe", "cancel my subscription", "stop charging", "turn off auto-renew", "disable auto renew", "cancel renewal")):
            tags.append("intent:cancel_subscription")
        # Monetization/Gameplay complaints (negative feedback about game mechanics)
        elif any(k in t for k in ("out of energy", "no energy", "energy system", "too expensive", "pay to win", "paywall", "spend money", "watch ads", "watching ads", "not worth", "greedy", "cash grab")):
            tags.append("intent:monetization_complaint")
        # Gameplay balance/mechanics complaints
        elif any(k in t for k in ("too hard", "too difficult", "impossible", "unfair", "bad design", "poor design", "frustrating", "annoying")):
            tags.append("intent:gameplay_feedback")
        # Account access / credentials (VERY common) - BUT check context
        # Only tag as account_access if there's ACTUAL login problem keywords
        elif any(k in t for k in ("can't log in", "cant log in", "cannot log in", "login problem", "log in problem", "password reset", "forgot password", "2fa", "two factor", "verification code", "verification email")):
            # Make sure it's not just mentioning login in passing
            if not any(phrase in t for phrase in ("i log in and", "when i log in", "after i log in", "logged in and")):
                tags.append("intent:account_access")
        if any(k in t for k in ("delete my account", "delete account", "remove my data", "erase my data", "gdpr", "ccpa")):
            tags.append("intent:account_deletion")
        # Store login issues (specific pattern from Google Play Console / App Store)
        if any(k in t for k in ("store", "google play", "play store", "app store")) and any(k in t for k in ("login", "sign in", "log in", "problem", "issue", "error")):
            tags.append("intent:account_access")
            tags.append("tag:store_issue")
        # Lost progress / restore
        if any(k in t for k in ("progress lost", "lost progress", "save lost", "reset progress", "rollback")):
            tags.append("intent:recover_progress")
        # Critical issues - app/game completely broken
        if any(k in t for k in ("app crash", "game crash", "crashing", "force close", "won't start", "can't start", "won't open", "can't open")):
            tags.append("intent:bug_report")
            tags.append("tag:critical_crash")
        # Item issues - HIGH priority (affects user progress/purchases)
        elif any(k in t for k in ("item stuck", "stuck item", "item disappeared", "item gone", "item missing", "stuck on board", "can't remove", "cannot remove")):
            tags.append("intent:bug_report")
            tags.append("tag:item_stuck")
        # App freeze/stuck (not crash but serious)
        elif any(k in t for k in ("stuck on", "freeze", "freezing", "frozen", "not responding", "stuck at")):
            tags.append("intent:bug_report")
            tags.append("tag:app_freeze")
        # Generic bug/feedback (lower priority)
        elif any(k in t for k in ("bug", "glitch", "issue", "problem")):
            tags.append("intent:bug_report")
        # Performance
        if any(k in t for k in ("slow", "lag", "stutter", "fps", "performance")):
            tags.append("intent:performance_issue")
        # Feature request / how-to
        if any(k in t for k in ("feature request", "please add", "could you add", "it would be great if")):
            tags.append("intent:feature_request")
        if any(k in t for k in ("how do i", "how to", "where is", "can you explain", "how can i")):
            tags.append("intent:how_to")
            tags.append("tag:how_to")  # Also add as visible tag
        # Device migration
        if any(k in t for k in ("new phone", "new device", "switch device", "migrate", "transfer progress", "restore purchase")):
            tags.append("intent:device_migration")
        # Store reviews
        if any(k in t for k in ("review", "rate", "rating")) and any(k in t for k in ("play store", "google play", "app store", "store")):
            tags.append("review:store")
        # UX issues
        if any(k in t for k in ("ux", "ui", "button", "menu", "layout", "confus", "hard to", "can't find", "cannot find")):
            tags.append("tag:ux_issue")
        # Credits not received (NOT purchase - earned credits missing)
        if any(k in t for k in ("didn't get credits", "not getting credits", "credits missing", "credits disappeared", "no credits", "credits not received", "earned credits", "task credits")):
            tags.append("tag:credits_missing")
            tags.append("intent:bug_report")  # This is a bug, not purchase
        # Actual purchase/payment issues (spent money)
        elif any(k in t for k in ("purchase", "payment", "charged", "iap", "in-app", "subscription", "renewal", "bought", "paid for")):
            tags.append("tag:purchase_issue")
        # Domain-specific keyword: flowers
        if "flowers" in t or "flower" in t:
            tags.append("flowers")
        # Content/features disappeared (NOT purchase - could be tasks, levels, items)
        if any(k in t for k in ("daily tasks disappeared", "tasks disappeared", "disappeared", "things disappeared", "features disappeared", "content disappeared")):
            tags.append("tag:content_missing")
            if "intent:bug_report" not in tags: tags.append("intent:bug_report")
        # Item disappeared / progress lost / restart prompts
        if any(k in t for k in ("item disappeared", "item gone", "lost item", "missing item", "inventory missing")):
            tags.append("tag:item_disappeared")
            if "intent:bug_report" not in tags: tags.append("intent:bug_report") # Also a bug
        if any(k in t for k in ("progress lost", "lost progress", "save lost", "progress reset", "account reset", "losing progress", "not saving", "progress not saving", "went back to", "back to level", "rollback to level")):
            tags.append("tag:progress_lost")
            tags.append("intent:bug_report") # Also a bug
        # Platform tags from entities or LLM
        platform = (entities or {}).get("platform")
        if isinstance(platform, str) and platform:
            tags.append(f"platform:{platform}")
        # App version
        appv = (entities or {}).get("app_version")
        if isinstance(appv, str) and appv:
            tags.append(f"version:{appv}")
        return tags

    def interpret_hs_tags(tag_list) -> tuple[str | None, list[str]]:
        """Learn from existing Help Scout tags to determine intent and extract additional context."""
        names = [str(t or '').lower().strip() for t in (tag_list or [])]
        extra: list[str] = []
        mapped_intent: str | None = None
        def has(*keys: str) -> bool:
            return any(any(k in n for k in keys) for n in names)
        
        # PRIORITY 1: Beta feedback / opinions (CHECK FIRST - always LOW priority)
        if has('beta','feedback','review','opinion','suggestion'):
            return 'beta_feedback', []  # Return early to prevent other patterns
        
        # Store-related (high priority for store issues)
        if has('store','google play','play store','app store','ios','review:store'):
            extra.append('tag:store_issue'); 
            if has('login','sign in','log in','can\'t login','cannot login'):
                mapped_intent = mapped_intent or 'account_access'
            elif has('problem','issue','error','not working'):
                mapped_intent = mapped_intent or 'bug_report'
        
        # Monetization/Energy complaints
        elif has('energy','monetization','pay to win','paywall','expensive','greedy','cash grab','ads'):
            mapped_intent = mapped_intent or 'monetization_complaint'
        
        # Gameplay feedback/balance
        elif has('too hard','difficult','impossible','unfair','frustrating','bad design'):
            mapped_intent = mapped_intent or 'gameplay_feedback'
        
        # Login/Account access (very common) - be careful not to over-match
        if has('login problem','login failed','login error','locked out','can\'t access account','password reset'):
            mapped_intent = mapped_intent or 'account_access'
        
        # Progress/Save issues (critical for games)
        if has('progress_lost','progress lost','progress','save lost','rollback','not saving','lost progress','reset','went back','losing progress'):
            extra.append('tag:progress_lost'); mapped_intent = mapped_intent or 'recover_progress'
        
        # Critical crashes (app completely broken)
        if has('crash','crashing','force close','not responding','won\'t start','won\'t open'):
            extra.append('tag:critical_crash'); mapped_intent = mapped_intent or 'bug_report'
        # Item stuck/disappeared (high priority)
        elif has('item stuck','stuck item','item disappeared','stuck on board','item missing'):
            extra.append('tag:item_stuck'); mapped_intent = mapped_intent or 'bug_report'
        # App freeze (serious but not crash)
        elif has('stuck','freeze','freezing','frozen','stuck at'):
            extra.append('tag:app_freeze'); mapped_intent = mapped_intent or 'bug_report'
        # Generic bugs (lower priority)
        elif has('bug','exception','glitch'):
            mapped_intent = mapped_intent or 'bug_report'
        
        # Payment/Billing (high priority)
        if has('purchase', 'payment', 'billing', 'charged', 'refund', 'iap', 'subscription'):
            extra.append('tag:purchase_issue')
            if has('cancel','stop','unsubscribe'):
                mapped_intent = mapped_intent or 'delete_account'
            else:
                mapped_intent = mapped_intent or 'refund_request'
        
        # How-to questions (low severity but common)
        if has('how_to','how-to','how to','question','help','where is','how do i','how can i','explain'):
            mapped_intent = mapped_intent or 'how_to'
        
        # Device migration/transfer
        if has('device','migration','transfer','restore purchase','new phone','new device','switch device'):
            mapped_intent = mapped_intent or 'device_migration'
        
        # Missing items/inventory
        if has('missing_item','item missing','lost item','inventory','item disappeared','disappeared'):
            extra.append('tag:item_disappeared')
        
        # Performance issues
        if has('slow','lag','laggy','stutter','fps','performance','freezing'):
            mapped_intent = mapped_intent or 'performance_issue'
        
        # Account deletion (GDPR/privacy)
        if has('delete account','remove account','delete my data','gdpr','ccpa'):
            mapped_intent = mapped_intent or 'account_deletion'
        
        # Restart/reinstall suggestions
        if has('restart','reinstall','re-install'):
            extra.append('tag:restart_prompt')
        
        # Game-specific tags
        if has('flowers','flower'):
            extra.append('flowers')
        if has('level','lvl'):
            extra.append('tag:level_related')
        
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
                'monetization_complaint': 'monetization feedback',
                'gameplay_feedback': 'gameplay feedback',
                'beta_feedback': 'beta feedback',
            }
            primary_cat = None
            for ccat in (cats or []):
                if ccat not in ('uncategorized','device'):
                    primary_cat = ccat.replace('_',' ')
                    break
            # Build more descriptive label from actual ticket content
            # Extract the first meaningful sentence or phrase
            first_sentence = ''
            try:
                # Try multiple extraction methods
                text_clean = t.replace('\n', ' ').strip()
                
                # Method 1: Look for complete sentences
                sentences = text_clean.split('.')
                for sent in sentences[:5]:
                    sent = sent.strip()
                    if len(sent) > 25 and len(sent) < 200:
                        # Skip boilerplate
                        if not any(skip in sent.lower() for skip in ['help scout', 'merge cube', 'merge cruise', 'google play console', 'userid', 'device =', 'os =']):
                            first_sentence = sent
                            break
                
                # Method 2: If no good sentence, extract key phrases
                if not first_sentence and len(text_clean) > 10:
                    # Look for problem descriptions
                    problem_words = ['disappeared', 'missing', 'not working', 'crash', 'freeze', 'stuck', 'problem', 'issue', 'bug', 'error']
                    lines = text_clean.split('\n')
                    for line in lines[:3]:
                        line = line.strip()
                        if len(line) > 15 and len(line) < 150:
                            if any(word in line.lower() for word in problem_words):
                                first_sentence = line
                                break
                
                # Method 3: Fallback to first substantial line
                if not first_sentence:
                    lines = text_clean.split('\n')
                    for line in lines[:3]:
                        line = line.strip()
                        if len(line) > 10 and len(line) < 100:
                            if not any(skip in line.lower() for skip in ['userid', 'device', 'os =', 'much regards']):
                                first_sentence = line
                                break
            except:
                pass
            
            # If we have a good sentence, use it; otherwise fall back to intent
            if first_sentence and len(first_sentence) > 30:
                label = first_sentence[:100]  # Cap at 100 chars
            else:
                label = intent_map.get(intent, primary_cat or 'support request')
            
            parts = []
            # Only add severity prefix for high/critical
            if bucket and str(bucket).lower() in ("high","critical"):
                parts.append(str(bucket).lower())
            if not first_sentence or len(first_sentence) < 30:
                parts.append(label)
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
        # Only count keywords from the user's message body; augment with gensim if available
        msg = c.last_text or ''
        add_words(msg)
        add_keywords_smart(msg)
        entities = classify.extract_entities(raw)
        cats, rule_score = classify.categorize(raw)
        # Delta-aware enrichment: reuse cached enrichment when content unchanged
        extra = {}
        content_hash = None
        try:
            content_hash = hashlib.sha256(raw.encode('utf-8')).hexdigest()
        except Exception:
            pass

        # ALWAYS read from cache if exists (trust the cache!)
        cached = None
        try:
            cached = s.query(HsEnrichment).filter(HsEnrichment.conv_id == c.id).first()
        except Exception:
            pass
        
        if cached:
            # Use cached data regardless of content_hash
            extra = {
                "summary": getattr(cached, 'summary', None),
                "intent": getattr(cached, 'intent', None),
                "root_cause": getattr(cached, 'root_cause', None),
                "tags": (getattr(cached, 'tags', '') or '').split(',') if getattr(cached, 'tags', '') else [],
            }
            # Use cached severity
            cached_sev = getattr(cached, 'severity_bucket', None)
            if cached_sev and str(cached_sev) not in ('None', 'none', ''):
                bucket = cached_sev
        else:
            # No cache
            extra = {}
        
        # --- Build final ticket object ---
        
        one_liner = extra.get("summary")
        # Fallback if LLM failed
        if not one_liner:
            one_liner = c.subject or "No description available"
        
        # Check if agent has replied
        agent_replied = False
        try:
            # Check Help Scout tags for agent:replied indicator
            if c.tags and 'agent:replied' in c.tags.lower():
                agent_replied = True
            # Also check if there are multiple threads (fallback)
            elif c.threads and len(c.threads) > 1:
                agent_replied = True
        except:
            pass
        
        # Combine tags from various sources
        llm_tags = extra.get("tags", [])
        
        # Add intent tag
        if extra.get("intent"):
            llm_tags.append(f"intent:{extra['intent']}")
        
        # Add root cause as a tag
        if extra.get("root_cause"):
            rc = extra['root_cause'].lower()
            llm_tags.append(f"cause:{extra['root_cause']}")
            
            # Add specific issue type tags based on root cause
            if any(word in rc for word in ["crash", "crashing", "force close"]):
                llm_tags.append("issue:crash")
            elif any(word in rc for word in ["freeze", "freezing", "frozen", "stuck", "not responding"]):
                llm_tags.append("issue:freeze")
            elif any(word in rc for word in ["bug", "glitch", "error", "broken"]):
                llm_tags.append("issue:bug")
        
        # NOTE: agent:replied is added to existing_tags below, not here
            
        final_tags = list(set(llm_tags)) # Simplified, as other sources were removed
        
        # Compute severity
        sev_score = severity.compute(raw, entities, rule_score)
        bucket = severity.bucketize(sev_score, 0, 0)
        if not bucket:
            if sev_score >= 50:
                bucket = "high"
            elif sev_score >= 30:
                bucket = "medium"
            else:
                bucket = "low"
        
        suggested_tags = [f"sev:{bucket}"] + final_tags
        
        # Get Help Scout tags
        existing_tags = []
        if c.tags:
            existing_tags = [t.strip() for t in c.tags.split(',') if t.strip()]
        
        # Add agent:replied to existing tags (it's a behavioral tag, not LLM-generated)
        if agent_replied and 'agent:replied' not in existing_tags:
            existing_tags.append('agent:replied')
        
        # Compute cluster key
        cluster_key = fingerprint.cluster_key(raw, entities)
        
        # Check if dismissed
        is_dismissed = c.id in dismissed_ids
        
        # Extract game UserID from message text
        game_user_id = getattr(c, 'game_user_id', None)
        if not game_user_id and c.last_text:
            try:
                import re
                match = re.search(r'(?i)user\s*id\s*[=:]\s*([a-f0-9]{24})', c.last_text)
                if match:
                    game_user_id = match.group(1)
            except Exception:
                pass

        # Build recommendation object
        rec = {
            "conv_id": c.id,
            "number": c.number,
            "subject": c.subject,
            "one_liner": one_liner,
            "text": c.last_text or "",
            "categories": cats or [],
            "entities": entities,
            "severity_score": sev_score,
            "severity_bucket": bucket,
            "cluster_key": cluster_key,
            "suggested_tags": suggested_tags,
            "existing_tags": existing_tags,
            "intent": extra.get("intent"),
            "root_cause": extra.get("root_cause"),
            "customer_name": getattr(c, 'customer_name', None),
            "first_name": getattr(c, 'first_name', None),
            "last_name": getattr(c, 'last_name', None),
            "game_user_id": game_user_id,
            "updated_at": c.updated_at.isoformat() if c.updated_at else None,
            "hs_link": f"https://secure.helpscout.net/conversation/{c.id}",
            "is_dismissed": is_dismissed,
            "agent_replied_status": agent_replied,
        }
        recs.append(rec)

    # Post-process: adjust severity by repetition and categories
    for r in recs:
        ck = r.get("cluster_key")
        if ck:
            similar = cluster_counts.get(ck, 1)
            # expose similar count to clients
            r["similar_count"] = similar
            # Escalate to CRITICAL if many users affected (10+)
            if similar >= 10:
                r["severity_bucket"] = "critical"
                r["escalation_reason"] = f"🔥 CRITICAL: {similar} users affected by same issue"
            # Escalate to HIGH if multiple users affected (5+)
            elif similar >= 5 and r["severity_bucket"] not in ("critical", "high"):
                r["severity_bucket"] = "high"
                r["escalation_reason"] = f"⚠️ Escalated to HIGH: {similar} similar reports"
        cats_l = set((r.get("categories") or []))
        tags_l = set((r.get("suggested_tags") or []))
        
        # Severity escalation based on category and tags
        # Critical issues - app completely broken or severe item issues
        if "tag:critical_crash" in tags_l or "tag:item_stuck" in tags_l:
            r["severity_bucket"] = "high"
        elif "tag:app_freeze" in tags_l:
            # Freeze is always HIGH - blocks gameplay completely
            r["severity_bucket"] = "high"
        elif "crash" in cats_l:
            r["severity_bucket"] = "high"
        # Check for crash/freeze/stuck in LLM tags (simple keywords)
        # Be specific - only escalate TRUE crashes/freezes, not gameplay issues
        crash_keywords = {"crash", "crashing", "freeze", "freezing", "frozen", "force-close", "not-responding"}
        stuck_keywords = {"stuck", "loading", "infinite-loop"}
        
        # Check for critical crash indicators
        if any(keyword in tags_l for keyword in crash_keywords):
            r["severity_bucket"] = "high"
            r["escalation_reason"] = "⚠️ Escalated to HIGH: App crash/freeze detected"
        # "stuck" only escalates if combined with UI/loading context (not gameplay)
        elif any(keyword in tags_l for keyword in stuck_keywords):
            # Only escalate if it's a UI/loading issue, not a gameplay mechanic issue
            root_cause = r.get("root_cause", "").lower()
            if any(term in root_cause for term in ["app", "game", "loading", "screen", "launch"]):
                r["severity_bucket"] = "high"
                r["escalation_reason"] = "⚠️ Escalated to HIGH: App stuck/loading issue"
        # Item disappeared/missing items (affects user purchases/progress)
        if "tag:item_disappeared" in tags_l and r["severity_bucket"] in ("low", "medium"):
            r["severity_bucket"] = "high"
        # Payment issues are important (revenue)
        payment_keywords = {"payment", "purchase", "charged", "refund", "billing", "subscription", "iap", "in-app-purchase"}
        if "payment" in cats_l or any(keyword in tags_l for keyword in payment_keywords):
            if r["severity_bucket"] == "low":
                r["severity_bucket"] = "medium"
        # Progress lost is at least medium
        progress_keywords = {"progress", "save", "lost", "reset", "rollback", "disappeared", "missing"}
        if "progress_lost" in cats_l or any(keyword in tags_l for keyword in progress_keywords):
            if r["severity_bucket"] == "low":
                r["severity_bucket"] = "medium"
        # Store issues should be at least medium (affects revenue)
        if "tag:store_issue" in tags_l and r["severity_bucket"] == "low":
            r["severity_bucket"] = "medium"
        # Login/account access issues should be medium (critical UX)
        if "intent:account_access" in tags_l and r["severity_bucket"] == "low":
            r["severity_bucket"] = "medium"
        # Beta feedback, monetization complaints, and gameplay feedback stay LOW (just feedback, not bugs)
        if "intent:beta_feedback" in tags_l or "intent:monetization_complaint" in tags_l or "intent:gameplay_feedback" in tags_l:
            r["severity_bucket"] = "low"  # Force to low regardless of initial scoring
        # Generic bug reports without critical keywords stay lower priority
        # (e.g., "I found a bug" feedback vs "app crashes every time")

    # Count replied vs unreplied tickets
    replied_count = 0
    unreplied_count = 0
    for r in recs:
        # Check the status we determined earlier
        if r.get("agent_replied_status"):
            replied_count += 1
        else:
            unreplied_count += 1

    top_categories = sorted(cat_totals.items(), key=lambda x: x[1], reverse=True)[:10]
    top_keywords = sorted(word_counts.items(), key=lambda x: x[1], reverse=True)[:20]
    top_clusters = sorted(cluster_counts.items(), key=lambda x: x[1], reverse=True)[:5]
    # Build structured issue analysis summary for UI
    intents_count = {}
    tag_focus_count = {}
    platform_count = {}
    severity_count = {"critical":0, "high":0, "medium":0, "low":0}
    for r in recs:
        if r.get("intent"):
            intents_count[r["intent"]] = intents_count.get(r["intent"], 0) + 1
        for t in (r.get("suggested_tags") or []):
            t = str(t or "")
            if t.startswith("tag:") or t == "flowers":
                tag_focus_count[t] = tag_focus_count.get(t, 0) + 1
            if t.startswith("platform:"):
                p = t.split(":",1)[1]
                platform_count[p] = platform_count.get(p, 0) + 1
        p2 = (r.get("entities") or {}).get("platform")
        if isinstance(p2, str) and p2:
            platform_count[p2] = platform_count.get(p2, 0) + 1
        b = r.get("severity_bucket")
        if b in severity_count:
            severity_count[b] += 1
    issue_analysis = {
        "categories": [{"name": k, "count": v} for k,v in sorted(cat_totals.items(), key=lambda x: x[1], reverse=True)],
        "intents": [{"name": k, "count": v} for k,v in sorted(intents_count.items(), key=lambda x: x[1], reverse=True)],
        "tags": [{"tag": k, "count": v} for k,v in sorted(tag_focus_count.items(), key=lambda x: x[1], reverse=True)],
        "platforms": [{"name": k, "count": v} for k,v in sorted(platform_count.items(), key=lambda x: x[1], reverse=True)],
        "severities": [{"bucket": bk.title(), "count": severity_count[bk]} for bk in ["critical","high","medium","low"]],
        "clusters": [{"id": k, "count": v} for k,v in top_clusters],
    }
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

    # Generate global summary (page 1 only) - REAL insights, not generic stats
    global_summary = ""
    if int(page) == 1 and recs:
        try:
            total_tickets = len(recs)
            high_critical = len([r for r in recs if r.get('severity_bucket') in ['high', 'critical']])
            
            # Collect root causes (actual problems, not intents)
            root_causes = {}
            platforms = {}
            for r in recs:
                rc = r.get('root_cause', '')
                if rc and len(rc) > 5:  # Real causes, not empty strings
                    root_causes[rc] = root_causes.get(rc, 0) + 1
                
                # Extract platform from tags
                for tag in r.get('suggested_tags', []):
                    if tag in ['android', 'ios', 'ipad', 'mobile']:
                        platforms[tag] = platforms.get(tag, 0) + 1
            
            # Find the most common specific problem
            top_problem = None
            if root_causes:
                top_problem = max(root_causes.items(), key=lambda x: x[1])
            
            # Build insightful summary
            parts = []
            
            if high_critical > 0:
                parts.append(f"⚠️ {high_critical} critical issues")
            
            if top_problem and top_problem[1] >= 3:
                parts.append(f"trending issue: '{top_problem[0]}' ({top_problem[1]} reports)")
            elif top_problem:
                parts.append(f"top issue: '{top_problem[0]}'")
            
            if platforms:
                top_platform = max(platforms.items(), key=lambda x: x[1])
                if top_platform[1] >= 5:
                    parts.append(f"mainly {top_platform[0]} users ({top_platform[1]} tickets)")
            
            if parts:
                global_summary = " | ".join(parts) + f" | {total_tickets} total"
            else:
                global_summary = f"✅ {total_tickets} tickets, no major patterns detected"
                
        except Exception as e:
            global_summary = f"Analysis error: {e}"  # Debug what's wrong

    return {
        "count": len(recs),
        "total": total,
        "page": int(page),
        "page_size": int(_ps),
        "replied_count": replied_count,
        "unreplied_count": unreplied_count,
        "global_summary": global_summary,
        "top_categories": [{"name": k, "count": v} for k, v in top_categories],
        "top_keywords": [{"word": k, "count": v} for k, v in top_keywords],
        "top_clusters": [{"cluster_key": k, "count": v} for k, v in top_clusters],
        "tag_stats": sorted([{"tag": k, "count": v} for k, v in tag_counts.items()], key=lambda x: x["count"], reverse=True)[:100],
        "recommendations": recs,
        "priorityIssue": priority_issue,
        "issue_analysis": issue_analysis,
        "responseStatus": {
            "replied": replied_count,
            "total": len(rows)
        },
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


@app.get("/admin/dashboard")
def dashboard(hours: int = 24):
    now = datetime.utcnow()
    # Initialize hourly buckets (last 24h) aligned to exact hour starts (UTC)
    hourly = []
    series_start = (now - timedelta(hours=23)).replace(minute=0, second=0, microsecond=0)
    # Only consider conversations within the last 24h window to match buckets
    win_start = series_start
    for i in range(0, 24):
        bucket_start = series_start + timedelta(hours=i)
        hourly.append({
            "ts": (bucket_start.isoformat() + "Z"),  # used by frontend for x-axis
            "date": bucket_start.strftime("%I%p").lstrip('0').lower(),  # backward-compat label
            "bugs": 0, "crashes": 0, "uxIssues": 0, "performance": 0, "technical": 0, "questions": 0, "features": 0, "payments": 0, "offerwalls": 0, "total": 0
        })

    cat_counts = {"bug": 0, "crash": 0, "ux": 0, "performance": 0, "technical": 0, "question": 0, "feature_request": 0, "payment": 0, "offerwall": 0}
    platform_counts = {}
    severity_counts = {"critical": 0, "high": 0, "medium": 0, "low": 0}
    cluster_counts = {}
    cluster_meta = {}
    replied_count = 0

    with get_session() as s:
        rows = s.query(HsConversation).filter(HsConversation.updated_at >= win_start).all()
        
    for c in rows:
        if c.tags and 'agent:replied' in c.tags:
            replied_count += 1
        raw = ((c.subject or "") + "\n" + (c.last_text or "")).strip()
        if not raw:
            continue
        entities = classify.extract_entities(raw)
        
        # Use cached LLM enrichment instead of calling LLM again
        extra = {}
        try:
            cached = s.query(HsEnrichment).filter(HsEnrichment.conv_id == c.id).first()
            if cached and getattr(cached, 'intent', None):
                extra = {
                    "intent": getattr(cached, 'intent', None),
                    "root_cause": getattr(cached, 'root_cause', None),
                }
        except:
            pass
        
        # Map LLM intent to chart categories - keep bugs and crashes SEPARATE
        cats = []
        intent = extra.get("intent", "")
        root_cause = (extra.get("root_cause", "") or "").lower()
        
        if intent:
            # CRASHES are distinct from bugs - check root_cause for crash indicators
            if any(word in root_cause for word in ["crash", "crashing", "freeze", "freezing", "frozen", "force close", "not responding"]):
                cats.append("crash")
            # Bugs that aren't crashes
            elif "bug" in intent:
                cats.append("bug")
            
            # Other categories
            if "performance" in intent:
                cats.append("performance")
            if "billing" in intent or "payment" in intent or "refund" in intent:
                cats.append("payment")
            if "question" in intent or "how_to" in intent:
                cats.append("question")
            if "feature" in intent:
                cats.append("feature_request")
        
        # Fallback to basic categorization if no intent
        if not cats:
            cats, rule_score = classify.categorize(raw.lower())
        else:
            rule_score = 0
        sev_score = severity.compute(raw, entities, rule_score)
        bucket = severity.bucketize(sev_score, 0, 0)
        if not bucket:
            if sev_score >= 50:
                bucket = "high"
            elif sev_score >= 30:
                bucket = "medium"
            else:
                bucket = "low"
        # Escalate severity from existing Help Scout tags if present (take highest across cluster)
        try:
            hs_tags = set([(t or '').strip().lower() for t in (c.tags or '').split(',') if t])
            if 'sev:critical' in hs_tags:
                bucket = 'critical'
            elif 'sev:high' in hs_tags and bucket in ('low','medium'):
                bucket = 'high'
            elif 'sev:medium' in hs_tags and bucket == 'low':
                bucket = 'medium'
        except Exception:
            pass
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
            try:
                idx = int((ct - series_start).total_seconds() // 3600)
            except Exception:
                idx = 23
            # Clamp into the visible window instead of dropping
            if idx < 0:
                idx = 0
            if idx > 23:
                idx = 23
        else:
            idx = 23
        # Increment hourly counts by mapped categories; if none matched, count under questions
        map_keys = {
            "bug": "bugs",
            "crash": "crashes",
            "ux": "uxIssues",
            "performance": "performance",
            "technical": "technical",
            "question": "questions",
            "feature_request": "features",
            "payment": "payments",
            "offerwall": "offerwalls",
        }
        matched_any = False
        for cat in (cats or []):
            if cat in cat_counts:
                cat_counts[cat] += 1
            key = map_keys.get(cat)
            if key:
                hourly[idx][key] = hourly[idx].get(key, 0) + 1
                matched_any = True
        # Ensure we count the message in totals even if no mapped category matched
        if not matched_any:
            hourly[idx]["questions"] = hourly[idx].get("questions", 0) + 1

        ck = fingerprint.cluster_key(raw, entities)
        cluster_counts[ck] = cluster_counts.get(ck, 0) + 1
        # Keep highest severity seen for the cluster (Critical > High > Medium > Low)
        sev_title = {"critical": "Critical", "high": "High", "medium": "Medium", "low": "Low"}.get(bucket, "Medium")
        if ck not in cluster_meta:
            cluster_meta[ck] = {
                "title": (c.subject or (raw[:60] + "...")),
                "category": (cats or ["other"])[0].replace("_", " ").title(),
                "severity": sev_title,
                "last_seen": c.updated_at.isoformat() if c.updated_at else None,
                "cid": c.id,
            }
        else:
            try:
                prev = cluster_meta[ck].get("last_seen")
                cur = c.updated_at.isoformat() if c.updated_at else None
                if cur and (not prev or cur > prev):
                    cluster_meta[ck]["last_seen"] = cur
                # escalate stored severity if current ticket is higher
                order = {"Low": 0, "Medium": 1, "High": 2, "Critical": 3}
                if order.get(sev_title, 1) > order.get(cluster_meta[ck].get("severity") or "Medium", 1):
                    cluster_meta[ck]["severity"] = sev_title
            except Exception:
                pass

    for r in hourly:
        r["total"] = (r.get("bugs",0) + r.get("crashes",0) + r.get("uxIssues",0) + r.get("performance",0) + r.get("technical",0) + r.get("questions",0) + r.get("features",0) + r.get("payments",0) + r.get("offerwalls", 0))

    # Build category pie
    def pretty(name: str) -> str:
        mapping = {
            "bug": "Bug", "crash": "Crash", "ux": "UX Issue", "performance": "Performance",
            "technical": "Technical", "question": "Question", "feature_request": "Feature Request", "payment": "Payments", "offerwall": "OfferWall"
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

    # Compute single highest priority issue using severity-weighted scoring
    weights = {"Critical": 8, "High": 4, "Medium": 2, "Low": 1}
    best_ck = None
    best_score = -1
    for ck, cnt in cluster_counts.items():
        meta = cluster_meta.get(ck, {})
        sev = meta.get("severity") or "Medium"
        # small recency boost based on last_seen
        recent_boost = 1.0
        try:
            ls = meta.get("last_seen")
            if ls:
                dt = datetime.fromisoformat(ls)
                hrs = max(0, (datetime.utcnow() - dt).total_seconds() / 3600.0)
                if hrs <= 6:
                    recent_boost = 1.5
        except Exception:
            pass
        score = cnt * weights.get(sev, 2) * recent_boost
        if score > best_score:
            best_score = score
            best_ck = ck
    priorityIssue = None
    if best_ck:
        m = cluster_meta.get(best_ck, {})
        priorityIssue = {
            "id": best_ck,
            "title": m.get("title") or best_ck,
            "category": m.get("category") or "Other",
            "severity": m.get("severity") or "Medium",
            "occurrences": cluster_counts.get(best_ck, 0),
            "last_seen": m.get("last_seen"),
            "hs_link": (f"https://secure.helpscout.net/conversation/{m.get('cid')}" if m.get('cid') else None),
        }

    # Top 5 priority issues
    scored = []
    for ck, cnt in cluster_counts.items():
        m = cluster_meta.get(ck, {})
        sev = m.get("severity") or "Medium"
        recent_boost = 1.0
        try:
            ls = m.get("last_seen")
            if ls:
                dt = datetime.fromisoformat(ls)
                if (datetime.utcnow() - dt).total_seconds() <= 6*3600:
                    recent_boost = 1.5
        except Exception:
            pass
        scored.append((ck, cnt * weights.get(sev, 2) * recent_boost))
    scored.sort(key=lambda x: x[1], reverse=True)
    priorityIssues = []
    for ck, _sc in scored[:5]:
        m = cluster_meta.get(ck, {})
        priorityIssues.append({
            "id": ck,
            "title": m.get("title") or ck,
            "category": m.get("category") or "Other",
            "severity": m.get("severity") or "Medium",
            "occurrences": cluster_counts.get(ck, 0),
            "last_seen": m.get("last_seen"),
        })

    return {
        "dailyData": hourly,
        "categoryData": categoryData,
        "platformData": platformData,
        "severityData": severityData,
        "responseTimeData": [],
        "topIssues": topIssues,
        "priorityIssue": priorityIssue,
        "priorityIssues": priorityIssues,
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
        extra = {}  # Cache only - no LLM
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
        extra = {}  # Cache only - no LLM
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
                    # Only upsert when new or updated (delta) to avoid expensive re-enrichment
                    existing = s.query(HsConversation).get(conv_id)
                    if not existing or (updated_at_dt and (existing.updated_at or datetime.min) < updated_at_dt):
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
@app.get("/admin/cluster_conversations")
def cluster_conversations(cluster_key: str, hours: int = 48):
    """
    Return all conversations that belong to a specific cluster/priority issue.
    Each conversation includes links to Help Scout.
    """
    cutoff = datetime.utcnow() - timedelta(hours=max(1, hours))
    with get_session() as s:
        rows = s.query(HsConversation).filter(HsConversation.updated_at >= cutoff).all()
    
    matching = []
    HS_DOMAIN = os.getenv("HS_SUBDOMAIN", "mergecube")
    for c in rows:
        raw = ((c.subject or "") + "\n" + (c.last_text or "")).strip()
        entities = classify.extract_entities(raw)
        
        # Compute cluster key using the same fingerprint function
        ck = fingerprint.cluster_key(raw, entities)
        
        if ck == cluster_key:
            # Build Help Scout link
            hs_link = f"https://secure.helpscout.net/conversation/{c.id}"
            matching.append({
                "id": c.id,
                "number": c.number,
                "subject": c.subject,
                "customer_name": c.customer_name,
                "updated_at": c.updated_at.isoformat() if c.updated_at else None,
                "hs_link": hs_link,
                "text_preview": (c.last_text or "")[:200],
            })
    
    # Sort by number descending (newest first)
    matching.sort(key=lambda x: x.get("number") or 0, reverse=True)
    
    return {
        "cluster_key": cluster_key,
        "count": len(matching),
        "conversations": matching,
    }

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

@app.get("/admin/hs_tags")
def hs_tags(conv_id: int | None = None, url: str | None = None):
    """Fetch Help Scout tags for a given conversation id or a HS URL."""
    if not conv_id and url:
        try:
            m = _re.search(r"/conversation/(\d+)", url)
            if m:
                conv_id = int(m.group(1))
        except Exception:
            pass
    if not conv_id:
        raise HTTPException(status_code=400, detail="Provide conv_id or url")
    try:
        conv = helpscout.fetch_conversation(conv_id)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Help Scout fetch failed: {e}")
    raw_tags = conv.get("tags") or []
    tags = [t.get('tag') if isinstance(t, dict) else str(t) for t in raw_tags]
    return {"conv_id": conv_id, "tags": tags, "count": len(tags)}

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
        f"?response_type=code&client_id={cid}&state=csrf&redirect_uri={redirect_uri}"
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
        f"?response_type=code&client_id={cid}&state=csrf&redirect_uri={redirect_uri}"
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
    # Help Scout expects client authentication via HTTP Basic auth.
    # Provide client_id/client_secret via auth header rather than form body.
    data = {"grant_type":"authorization_code","code":code, "redirect_uri": redirect_uri}
    r = requests.post(token_url, data=data, auth=(cid, csec), headers={"Accept":"application/json"}, timeout=10)
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

@app.get("/admin/db_stats")
def db_stats():
    """Get database statistics"""
    with get_session() as s:
        total_tickets = s.query(HsConversation).count()
        total_feedback = s.query(TicketFeedback).filter_by(action_type='tag_correction').count()
        
        # Get date range
        oldest = s.query(HsConversation).order_by(HsConversation.updated_at.asc()).first()
        newest = s.query(HsConversation).order_by(HsConversation.updated_at.desc()).first()
        
        return {
            "total_tickets": total_tickets,
            "total_corrections": total_feedback,
            "oldest_ticket": oldest.updated_at.isoformat() if oldest and oldest.updated_at else None,
            "newest_ticket": newest.updated_at.isoformat() if newest and newest.updated_at else None,
            "oldest_number": oldest.number if oldest else None,
            "newest_number": newest.number if newest else None,
        }
