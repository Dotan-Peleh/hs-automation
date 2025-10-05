-- Migration: Add customer info fields to hs_conversation table
-- Date: 2025-10-05
-- Purpose: Add customer_name, first_name, last_name, game_user_id columns

-- Add customer_name column (full name from Help Scout)
ALTER TABLE hs_conversation
ADD COLUMN IF NOT EXISTS customer_name TEXT;

-- Add first_name column
ALTER TABLE hs_conversation
ADD COLUMN IF NOT EXISTS first_name VARCHAR(128);

-- Add last_name column
ALTER TABLE hs_conversation
ADD COLUMN IF NOT EXISTS last_name VARCHAR(128);

-- Add game_user_id column (extracted from message text)
ALTER TABLE hs_conversation
ADD COLUMN IF NOT EXISTS game_user_id VARCHAR(64);

-- Create indexes for better query performance
CREATE INDEX IF NOT EXISTS idx_hs_conversation_customer_name ON hs_conversation(customer_name);
CREATE INDEX IF NOT EXISTS idx_hs_conversation_game_user_id ON hs_conversation(game_user_id);

