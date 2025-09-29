-- Initial schema (simplified for scaffold)
CREATE TABLE IF NOT EXISTS incident (
  id SERIAL PRIMARY KEY,
  signature TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'open',
  severity_bucket TEXT NOT NULL,
  severity_score INT NOT NULL,
  cluster_key TEXT NOT NULL,
  slack_channel_id TEXT,
  slack_thread_ts TEXT,
  first_seen TIMESTAMPTZ DEFAULT now(),
  last_update TIMESTAMPTZ DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_incident_cluster ON incident(cluster_key) WHERE status IN ('open','ack','muted');
