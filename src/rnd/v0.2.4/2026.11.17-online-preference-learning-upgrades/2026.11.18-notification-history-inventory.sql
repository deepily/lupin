-- authorized_by: task:94a8f561-ac7b-4de4-847b-7f37d0114da7
-- author: Rick's resident expert (outside reviewer)
-- added_by: Mr. Radio, at Rick's request (decision 6, 2026-11-18); uploaded by Rick 2026-11-18 10:39 EST; body unchanged
--
-- Run with psql against a snapshot or read-only connection to the Lupin database.
-- Example: psql -X -v ON_ERROR_STOP=1 -v recipient_id=<Rick's UUID> -f notification-history-inventory.sql
-- Use the installed schema matching the reviewed checkout. All outputs are aggregates.
-- First table is database-wide. Remaining tables are scoped to the supplied recipient.
BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY;

SELECT count(*) AS notification_rows,
       count(*) FILTER (WHERE response_requested IS TRUE) AS response_required_rows,
       count(*) FILTER (WHERE response_requested IS TRUE AND recipient_id = :'recipient_id'::uuid) AS recipient_asks
FROM notifications;

-- Start with notifications, retaining requests that never produced a prediction or case.
-- Pre-aggregate attempts so a repeated log write cannot add a second question.
WITH asks AS (
    SELECT * FROM notifications WHERE response_requested IS TRUE AND recipient_id = :'recipient_id'::uuid
), logs AS (
    SELECT p.notification_id, count(*) AS attempts,
           bool_or(p.predicted_value IS NOT NULL) AS has_candidate,
           bool_or(p.accuracy_match IS NOT NULL) AS has_score
    FROM prediction_log p JOIN asks n ON n.id = p.notification_id GROUP BY p.notification_id
)
SELECT n.response_type, n.state, count(*) AS asks,
       count(*) FILTER (WHERE n.responded_at IS NOT NULL) AS with_response_time,
       count(*) FILTER (WHERE n.response_value IS NOT NULL AND n.response_value <> 'null'::jsonb) AS with_payload,
       count(l.notification_id) AS logged_asks,
       count(*) FILTER (WHERE l.attempts > 1) AS duplicate_log_ids,
       count(*) FILTER (WHERE l.has_candidate) AS with_stored_prediction,
       count(*) FILTER (WHERE l.has_score) AS with_stored_score,
       count(c.id) AS with_answer_case
FROM asks n LEFT JOIN logs l ON l.notification_id = n.id
LEFT JOIN prediction_decisions c ON c.id = n.id::text
GROUP BY n.response_type, n.state ORDER BY 1, 2;

-- Inventory attribution and shape. A known account or a populated answer alone
-- does not establish a usable label. Keep unknown and default buckets visible.
SELECT n.response_type, n.state, coalesce(n.response_value->>'source', '(missing)') AS source,
       coalesce(n.response_value #>> '{answered_by,method}', '(missing)') AS auth_method,
       CASE WHEN n.response_value #>> '{answered_by,user_id}' IS NULL THEN 'unknown'
            WHEN n.response_value #>> '{answered_by,user_id}' = n.recipient_id::text THEN 'recipient'
            ELSE 'different account' END AS attribution,
       CASE WHEN n.response_value IS NULL THEN 'no payload'
            WHEN n.response_value ? 'answers' THEN 'answers key'
            WHEN n.response_value ? 'value' THEN 'value key / ' || jsonb_typeof(n.response_value->'value')
            ELSE jsonb_typeof(n.response_value) END AS stored_shape,
       count(*) AS asks
FROM notifications n WHERE n.response_requested IS TRUE AND n.recipient_id = :'recipient_id'::uuid
GROUP BY 1, 2, 3, 4, 5, 6 ORDER BY 1, 2, 7 DESC;

-- Presence is the first pass. Later inspect whether the contents are meaningful
-- and whether response_options.questions describes every header and offered option.
SELECT date_trunc('month', created_at AT TIME ZONE 'UTC')::date AS month_utc, response_type,
       count(*) AS asks,
       count(*) FILTER (WHERE nullif(btrim(message), '') IS NOT NULL) AS with_prompt,
       count(*) FILTER (WHERE nullif(btrim(abstract), '') IS NOT NULL) AS with_abstract,
       count(*) FILTER (WHERE nullif(btrim(title), '') IS NOT NULL) AS with_title,
       count(*) FILTER (WHERE title = left(btrim(message), 50)) AS title_equals_prompt_prefix,
       count(*) FILTER (WHERE jsonb_typeof(response_options->'questions') = 'array'
                        AND response_options->'questions' <> '[]'::jsonb) AS with_questions,
       count(*) FILTER (WHERE nullif(split_part(sender_id, '#', 2), '') IS NOT NULL) AS with_session_suffix,
       count(job_id) AS with_job, count(thread_id) AS with_thread, count(reply_to) AS with_parent,
       count(response_default) AS with_default, count(timeout_seconds) AS with_timeout
FROM notifications WHERE response_requested IS TRUE AND recipient_id = :'recipient_id'::uuid
GROUP BY 1, 2 ORDER BY 1, 2;

-- Sketch the tri-state label distribution on the common string envelope. Other
-- encodings stay visible for inspection. Restrict to attributable submissions;
-- reconcile provenance and parse the original payloads before using as labels.
WITH labeled AS (
    SELECT response_value->>'value' AS raw_value
    FROM notifications
    WHERE response_requested IS TRUE AND recipient_id = :'recipient_id'::uuid
      AND response_type = 'yes_no' AND responded_at IS NOT NULL
      AND response_value #>> '{answered_by,user_id}' = recipient_id::text
      AND coalesce(response_value->>'source', '') <> 'timeout_default'
)
SELECT coalesce(lower(substring(btrim(raw_value) from '(?i)^(yes|no|neither)(?:[[:space:]]|$)')), '(inspect)') AS stance,
       coalesce(position('[comment:' in lower(raw_value)) > 0, false) AS has_comment_marker,
       count(*) AS submissions
FROM labeled GROUP BY 1, 2 ORDER BY 1, 2;

ROLLBACK;
