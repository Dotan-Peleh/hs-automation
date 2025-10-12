import os
from contextlib import contextmanager
from datetime import datetime
from sqlalchemy import create_engine, Column, Integer, BigInteger, String, Text, DateTime, Float
from sqlalchemy.orm import declarative_base, sessionmaker

# Database configuration with sensible dev fallback
# Prefer explicit DATABASE_URL. Otherwise use Postgres if all env vars are present.
# If not, default to local SQLite so the API can run without Docker.
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

engine = create_engine(
    DB_URL,
    pool_pre_ping=True,
    pool_size=10,  # Balanced for Render free tier (was 20)
    max_overflow=20,  # Total 30 connections (was 50)
    pool_recycle=3600,  # Recycle connections after 1 hour
    pool_timeout=60,  # Wait up to 60 seconds for a connection
    connect_args={"check_same_thread": False} if DB_URL.startswith("sqlite") else {}
)
SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()

class Incident(Base):
    __tablename__ = 'incident'
    id = Column(Integer, primary_key=True)
    signature = Column(Text, nullable=False, default='')
    status = Column(String(16), nullable=False, default='open')
    severity_bucket = Column(String(16), nullable=False, default='medium')
    severity_score = Column(Integer, nullable=False, default=0)
    cluster_key = Column(Text, nullable=False, default='')
    slack_channel_id = Column(Text, nullable=True)
    slack_thread_ts = Column(Text, nullable=True)
    first_seen = Column(DateTime, default=datetime.utcnow)
    last_update = Column(DateTime, default=datetime.utcnow)

class HsOAuthToken(Base):
    __tablename__ = 'hs_oauth_token'
    id = Column(Integer, primary_key=True)
    access_token = Column(Text, nullable=True)
    refresh_token = Column(Text, nullable=True)
    expires_at = Column(DateTime, nullable=True)

class HsConversation(Base):
    __tablename__ = 'hs_conversation'
    id = Column(BigInteger, primary_key=True)  # Help Scout conversation id
    number = Column(Integer, nullable=True)
    subject = Column(Text, nullable=True)
    last_text = Column(Text, nullable=True)
    tags = Column(Text, nullable=True)
    customer_name = Column(Text, nullable=True)  # Full name from Help Scout
    first_name = Column(String(128), nullable=True)  # Customer first name
    last_name = Column(String(128), nullable=True)  # Customer last name
    game_user_id = Column(String(64), nullable=True)  # Game UserID extracted from message
    updated_at = Column(DateTime, default=datetime.utcnow)

class HsEnrichment(Base):
    __tablename__ = 'hs_enrichment'
    conv_id = Column(BigInteger, primary_key=True)
    content_hash = Column(Text, nullable=True)
    summary = Column(Text, nullable=True)
    categories = Column(Text, nullable=True)  # comma-separated
    platform = Column(String(32), nullable=True)
    app_version = Column(String(64), nullable=True)
    level = Column(Integer, nullable=True)
    intent = Column(String(64), nullable=True)
    one_liner = Column(Text, nullable=True)
    severity_bucket = Column(String(16), nullable=True)
    severity_score = Column(Integer, nullable=True)
    last_enriched_at = Column(DateTime, default=datetime.utcnow)

class TicketFeedback(Base):
    __tablename__ = 'ticket_feedback'
    id = Column(Integer, primary_key=True)
    conversation_id = Column(BigInteger, nullable=False)
    ticket_number = Column(BigInteger, nullable=True)
    action_type = Column(Text, nullable=False)  # 'seen', 'dismissed', 'tag_correction'
    feedback_data = Column(Text, nullable=True)  # JSON string with details
    created_at = Column(DateTime, default=datetime.utcnow)

class TicketEvent(Base):
    __tablename__ = 'ticket_event'
    id = Column(Integer, primary_key=True)
    conv_id = Column(BigInteger, nullable=False)
    number = Column(Integer, nullable=True)
    subject = Column(Text, nullable=True)
    cluster_key = Column(Text, nullable=False)
    severity_bucket = Column(String(16), nullable=False, default='low')
    severity_score = Column(Integer, nullable=False, default=0)
    z_score = Column(Float, nullable=True)
    cusum = Column(Float, nullable=True)
    impact = Column(String(16), nullable=True)
    intent = Column(String(64), nullable=True)
    categories = Column(Text, nullable=True)
    tags = Column(Text, nullable=True)
    platform = Column(String(32), nullable=True)
    app_version = Column(String(64), nullable=True)
    level = Column(Integer, nullable=True)
    one_liner = Column(Text, nullable=True)
    summary = Column(Text, nullable=True)
    day_start = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

@contextmanager
def get_session():
    s = SessionLocal()
    try:
        yield s
    finally:
        s.close()

# simple upsert by cluster_key
OPENISH = ('open','ack','muted')

def upsert_incident(s, cluster_key: str, bucket: str, sev_score: int) -> Incident:
    inc = s.query(Incident).filter(Incident.cluster_key == cluster_key, Incident.status.in_(OPENISH)).first()
    if inc is None:
        inc = Incident(cluster_key=cluster_key, signature=cluster_key, status='open', severity_bucket=bucket, severity_score=sev_score)
        s.add(inc)
        s.commit()
        s.refresh(inc)
    else:
        inc.severity_bucket = bucket
        inc.severity_score = sev_score
        inc.last_update = datetime.utcnow()
        s.commit()
    return inc

# no-op stubs for now

def record_ticket_event(
    s,
    conv_id: int,
    number: int | None,
    subject: str | None,
    combined: str,
    entities: dict,
    cats,
    sev_bucket: str,
    sev_score: int,
    cluster_key: str,
    z: float | None = None,
    cus: float | None = None,
    impact: str | None = None,
    intent: str | None = None,
    tags_str: str | None = None,
    one_liner: str | None = None,
    summary: str | None = None,
    day_start = None,
):
    from sqlalchemy import func
    row = TicketEvent(
        conv_id=conv_id,
        number=number,
        subject=subject,
        cluster_key=cluster_key,
        severity_bucket=sev_bucket,
        severity_score=sev_score,
        z_score=float(z) if z is not None else None,
        cusum=float(cus) if cus is not None else None,
        impact=impact,
        intent=intent,
        categories=','.join(cats or []) if cats else None,
        tags=tags_str,
        platform=(entities or {}).get('platform'),
        app_version=(entities or {}).get('app_version'),
        level=(entities or {}).get('level'),
        one_liner=one_liner,
        summary=summary,
        day_start=day_start,
    )
    s.add(row)
    s.commit()
    return row

# helpers to persist HS oauth tokens

def save_hs_tokens(s, access_token: str, refresh_token: str, expires_at: datetime | None):
    row = s.query(HsOAuthToken).get(1)
    if not row:
        row = HsOAuthToken(id=1)
        s.add(row)
    row.access_token = access_token
    row.refresh_token = refresh_token
    row.expires_at = expires_at
    s.commit()
    return row

def get_hs_tokens(s):
    return s.query(HsOAuthToken).get(1)

# read-only backfill upsert

def upsert_hs_conversation(s, conv_id: int, number: int | None, subject: str | None, last_text: str | None, tags_str: str | None, updated_at_dt: datetime | None = None, customer_name: str | None = None, first_name: str | None = None, last_name: str | None = None, game_user_id: str | None = None):
    row = s.query(HsConversation).get(conv_id)
    if not row:
        row = HsConversation(id=conv_id)
        s.add(row)
    row.number = number
    row.subject = subject
    row.last_text = last_text
    row.tags = tags_str
    row.customer_name = customer_name
    row.first_name = first_name
    row.last_name = last_name
    row.game_user_id = game_user_id
    if updated_at_dt:
        row.updated_at = updated_at_dt
    else:
        row.updated_at = datetime.utcnow()
    s.commit()
    return row

def load_active_ruleset(s):
    return {"rules": [], "thresholds": {}}

# create tables if not exist (dev convenience)
Base.metadata.create_all(engine)
