-- Add table for tracking ticket feedback and user actions
CREATE TABLE IF NOT EXISTS ticket_feedback (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id INTEGER NOT NULL,
    ticket_number INTEGER,
    action_type TEXT NOT NULL, -- 'seen', 'dismissed', 'tag_correction'
    feedback_data TEXT, -- JSON string with details
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(conversation_id, action_type)
);

CREATE INDEX IF NOT EXISTS idx_ticket_feedback_conv_id ON ticket_feedback(conversation_id);
CREATE INDEX IF NOT EXISTS idx_ticket_feedback_action ON ticket_feedback(action_type);
CREATE INDEX IF NOT EXISTS idx_ticket_feedback_created ON ticket_feedback(created_at);

