-- Migration: Add is_hidden column to notifications table
-- Date: 2025-01-01
-- Purpose: Enable soft delete/archive functionality for date-based notification management
--
-- This migration adds:
-- 1. is_hidden BOOLEAN column (default FALSE) for soft delete capability
-- 2. Index on is_hidden for efficient filtering
-- 3. Composite partial index for efficient visible-only queries by sender/date

-- Add the is_hidden column
ALTER TABLE public.notifications
ADD COLUMN IF NOT EXISTS is_hidden BOOLEAN DEFAULT FALSE NOT NULL;

-- Add index for filtering by hidden status
CREATE INDEX IF NOT EXISTS idx_notifications_is_hidden
ON public.notifications( is_hidden );

-- Composite partial index for efficient visible-only queries
-- This index is used when fetching notifications grouped by sender and date
CREATE INDEX IF NOT EXISTS idx_notifications_visible_by_sender_date
ON public.notifications( sender_id, recipient_id, created_at DESC )
WHERE is_hidden = FALSE;

-- Verify the migration
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public'
        AND table_name = 'notifications'
        AND column_name = 'is_hidden'
    ) THEN
        RAISE NOTICE 'Migration successful: is_hidden column added to notifications table';
    ELSE
        RAISE EXCEPTION 'Migration failed: is_hidden column not found';
    END IF;
END $$;
