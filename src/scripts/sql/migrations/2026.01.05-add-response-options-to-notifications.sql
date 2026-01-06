-- Migration: Add response_options column to notifications table
-- Date: 2026-01-05
-- Purpose: Support multiple-choice question notifications
--
-- This migration adds a JSONB column to store options for multiple_choice response_type.
-- Structure: {"questions": [{"question": "...", "header": "...", "multi_select": bool, "options": [{"label": "...", "description": "..."}]}]}

-- Add response_options column
ALTER TABLE notifications
ADD COLUMN IF NOT EXISTS response_options JSONB;

-- Add comment for documentation
COMMENT ON COLUMN notifications.response_options IS 'JSON structure for multiple_choice questions: {questions: [{question, header, multi_select, options: [{label, description}]}]}';

-- Verify the column was added
SELECT column_name, data_type, is_nullable
FROM information_schema.columns
WHERE table_name = 'notifications'
AND column_name = 'response_options';
