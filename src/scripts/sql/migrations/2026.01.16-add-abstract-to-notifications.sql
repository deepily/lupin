-- Migration: Add abstract column to notifications table
-- Date: 2026-01-16
-- Purpose: Add supplementary context field for notifications (plan details, URLs, markdown)
--
-- This allows blocking tools (ask_yes_no, converse, etc.) to include
-- additional context that explains WHAT the user is being asked to approve.

-- Add abstract column to notifications table
ALTER TABLE notifications ADD COLUMN IF NOT EXISTS abstract TEXT;

-- Optional: Add partial index for filtering/search on non-null abstracts
CREATE INDEX IF NOT EXISTS idx_notifications_abstract ON notifications (abstract) WHERE abstract IS NOT NULL;

-- Comment for documentation
COMMENT ON COLUMN notifications.abstract IS 'Supplementary context for notification (plan details, URLs, markdown)';
