-- # Missing vectors, step 0: why 2,306 scored asks have no case row
--
-- Row 0831171d. Measured by Clayton, read-only on `lupin_db_dev`, 2026-11-19 about 14:50 UTC. Queries: `this file (run it with `docker exec -i lupin-postgres psql -U lupin_dev -d lupin_db_dev < missing-vectors-step0.sql`). It issues no write; it opens `BEGIN READ ONLY` and ends in `ROLLBACK`. The cohort is the one in the plan: yes/no and multiple choice, scored, not a test override (3,610 asks; 2,306 without a row; 1,304 with).
--
-- ## Verdict
--
-- | Group | Asks | Cause |
-- |---|---|---|
-- | Asked 5 May to 25 Sep | 2,297 | **Named gap.** No row exists, and nothing in the table, the backup or any other database shows one ever did. Never written versus lost cannot be told from the data. |
-- | Asked 18 Nov 15:19Z to 18:20Z | 9 | **Consistent with written, then deleted** in the 18 Nov cleanup. Not proven: statement logging started at 23:55Z, after the deletion, and the deleted rows were vacuumed. |
--
-- ## The facts
--
-- - Earliest `prediction_decisions.created_at`: **2026-09-25T22:28:59Z**. The restored backup has the same earliest value. The earliest cohort ask with a row was asked 2026-09-26 15:54Z; the 3 rows of 25 Sep belong to asks outside the cohort.
-- - Every ask asked from 26 Sep to 18 Nov has a row, except the 9. Asked May 175, Jun 380, Jul 408, Aug 659, Sep 675 (of 847; 172 have rows) have none, so **0 of 2,297 early asks has a row**.
-- - Row `created_at` falls within 0.63 seconds after the notification's `responded_at` (minimum 0.20 seconds) on all 1,547 rows whose notification has an answer time (query 5). So the rows were written when the answer arrived, not in a later bulk load.
-- - The 9 are the only cohort asks answered between the backup (18 Nov 03:56:16Z) and the cleanup (19:05:17Z), so 9 of 9 in that window lack a row, against 0 of every other ask from 26 Sep on. The 9 are yes/no, from the lupin and plan seats. A restore of some other backup over the table is an alternative cause that I did not test.
-- - Run by hand, no query in this file: the table's heap file was born 2026-08-17 (row 69cc0bb6). `lupin_db_v1baseline` holds 3 rows, all 2026-08-17 01:43Z. `lupin_db_test` holds 12 rows, all 18 Nov. Neither holds an earlier case. `prediction_log` has rows from 5 Apr; none of the 877 + 520 + 463 + 837 logged May to Aug has a row, and none of Sep 25 and before.
-- - Run by hand, no query in this file: the table's stats counters read 5,357 inserts and 3,567 deletes; their difference (1,790) is not the live count (1,553). I do not know what period the counters cover, so I draw nothing from them.
-- - Run by hand, no query in this file (a read of the migration folder and the code): migration history. `f1c9a4d27b36` (owner and answer source) is the only migration naming the table in `src/migrations/versions`; its downgrade deletes no rows. The table itself is not created by a migration in that folder. `alembic_version` reads `c9e3a7b1d542` (query 8). The only code that deletes the table's rows is `PredictionDecisionRepository.delete_all`, per row 69cc0bb6.
-- - Run by hand (the server log, not the database): since logging went on, the server has logged no DELETE on this table (the only DELETE statements are 149 on `failed_login_attempts`).
--
-- ## Not found (named gaps)
--
-- - Why no row was written, or kept, before 25 Sep. The write code (`_store_decision`) is in the tree from 19 Jun and the repository from 3 Aug, but the history is squashed pull requests, so the dates do not say when the live path first ran on this database. A rebuild of the dev database around 17 Aug would remove earlier rows without any DELETE; nothing here shows or rules that out.
-- - Who deleted the 1,559 rows on 18 Nov (row 69cc0bb6 still has no name).
--
-- ## Can anything tell a human answer from a proxy or timeout answer, for the 2,306?
--
-- **Partly. Nothing positively marks a human; only the absence of a proxy or timeout marker points that way.**
--
-- | Evidence on the 2,306 | Result |
-- |---|---|
-- | `notifications.response_value.source` | `ui` on 2,304; missing on 2. Never `timeout_default` (no timeout answer is in the cohort at all, in any month) |
-- | A `proxy_decisions` row (ratification state) joined on `notification_id` | **none for any of the 2,306** |
-- | `response_value.answered_by.user_id` (the owner) | present on 302; absent on 2,004 |
-- | `prediction_log.forecast_source`, `display_decision` | null on all of them |
-- | `notifications.recipient_id` | 5 distinct recipients, a usable owner for every ask |
--
-- Only 302 of the 2,306 asks name an owner in the answer itself.
--
-- - The migration's own rule (`derive_answer_source`) needs a ratification state to call an answer human. No such state exists for these asks, so that rule would answer `unknown` for all 2,306, not `human`.
-- - On the 1,304 asks that do have a row, the stored answer is `human` on all, and every one has `source = ui` and an owner. So `source = ui` agrees with human on that population; it cannot prove it on the early one, because no proxy log exists to rule a proxy out.
-- - Rick decides: label the 2,304 `ui` asks `human` by that agreement (and the 2 without a source `unknown`), or leave them `unknown` and so unreplayable. An owner for each would come from `recipient_id`, not from `answered_by`.
--
-- ============ QUERIES ============
-- Missing vectors, step 0 (row 0831171d): why do 2,306 scored asks have no prediction_decisions row?
-- READ ONLY. Run: docker exec -i lupin-postgres psql -U lupin_dev -d lupin_db_dev < this file
-- The cohort is cohorts.counted_scored_filter() compiled to SQL, yes_no and multiple_choice only.
BEGIN READ ONLY;
-- A read-only transaction refuses even a temp view, so the cohort is a psql variable pasted in as a subquery.
\set coh '( SELECT l.notification_id, l.response_type, l.predicted_at, l.asked_at, l.responded_at AS log_responded_at, n.created_at AS n_created, n.responded_at AS n_responded, n.sender_id, d.id IS NOT NULL AS has_row, d.question_embedding IS NOT NULL AS has_vec, d.created_at AS d_created FROM prediction_log l JOIN notifications n ON n.id = l.notification_id LEFT JOIN prediction_decisions d ON d.id = l.notification_id::text WHERE l.response_type IN (''yes_no'',''multiple_choice'') AND coalesce(l.forecast_source,'''') != ''test_override'' AND NOT coalesce(CAST((l.accuracy_detail ->> ''similarity'') AS FLOAT) > 1.0 OR CAST((l.accuracy_detail ->> ''avg_similarity'') AS FLOAT) > 1.0, false) AND l.prediction_confidence <= 1.0 AND l.accuracy_match IS NOT NULL )'

\echo '== 1 cohort census'
SELECT count(*) total, count(*) FILTER (WHERE NOT has_row) no_row, count(*) FILTER (WHERE has_vec) has_vec FROM :coh c;

\echo '== 2 prediction_decisions: size, earliest and latest created_at (text column)'
SELECT count(*) n, min(created_at) earliest, max(created_at) latest FROM prediction_decisions;

\echo '== 3 earliest ask with a row vs latest ask without a row (asked_at, UTC)'
SELECT (SELECT min(coalesce(asked_at,n_created)) FROM :coh c WHERE has_row) first_with_row,
       (SELECT max(coalesce(asked_at,n_created)) FROM :coh c WHERE NOT has_row) last_without_row,
       (SELECT count(*) FROM :coh c WHERE has_row AND coalesce(asked_at,n_created) < '2026-09-26') rows_for_asks_before_26sep;

\echo '== 4 by month and row state'
SELECT to_char(coalesce(asked_at,n_created) AT TIME ZONE 'UTC','YYYY-MM') mon, count(*) asks,
       count(*) FILTER (WHERE has_row) with_row, count(*) FILTER (WHERE NOT has_row) without_row FROM :coh c GROUP BY 1 ORDER BY 1;

\echo '== 5 the lag between an answer and its row, in seconds (row created_at minus notification responded_at), every row with an answer time'
SELECT count(*) n, round(min(extract(epoch from (d.created_at::timestamptz - n.responded_at)))::numeric,2) min_s,
       round(max(extract(epoch from (d.created_at::timestamptz - n.responded_at)))::numeric,2) max_s
FROM prediction_decisions d JOIN notifications n ON n.id::text = d.id WHERE n.responded_at IS NOT NULL;

\echo '== 6 rows whose created_at is not the ask day: rows created the same day as the migration-style backfill?'
SELECT substr(d_created,1,10) dy, count(*) rows_created FROM :coh c WHERE has_row GROUP BY 1 ORDER BY 2 DESC LIMIT 8;

\echo '== 7 the 9 asks of November with no row'
SELECT notification_id, response_type, coalesce(asked_at,n_created) asked, n_responded, sender_id FROM :coh c WHERE NOT has_row AND coalesce(asked_at,n_created) >= '2026-11-01' ORDER BY 3;

\echo '== 8 alembic head and table history'
SELECT version_num FROM alembic_version;

\echo '== 9 can anything tell a human answer from a proxy or timeout answer, for the asks with no row?'
\echo '-- 9a notifications.response_value.source and answered_by on the 2306'
SELECT n.response_value->>'source' src, (n.response_value ? 'answered_by') has_answered_by,
       (n.response_value->'answered_by'->>'user_id') IS NOT NULL has_owner, count(*)
FROM :coh c JOIN notifications n ON n.id = c.notification_id WHERE NOT c.has_row GROUP BY 1,2,3 ORDER BY 4 DESC;
\echo '-- 9b a proxy_decisions row (ratification state) joined on notification_id, for the 2306'
SELECT pd.ratification_state, pd.action, count(*) FROM :coh c LEFT JOIN proxy_decisions pd ON pd.notification_id = c.notification_id::text
WHERE NOT c.has_row GROUP BY 1,2 ORDER BY 3 DESC;
\echo '-- 9c the same two facts on the 1304 asks that DO have a row, against the stored answer_source'
SELECT d.answer_source, n.response_value->>'source' src, (n.response_value->'answered_by'->>'user_id') IS NOT NULL has_owner, count(*)
FROM :coh c JOIN notifications n ON n.id = c.notification_id JOIN prediction_decisions d ON d.id = c.notification_id::text
WHERE c.has_row GROUP BY 1,2,3 ORDER BY 4 DESC;
\echo '-- 9d recipient of the 2306 (the owner the live path would not have had to guess)'
SELECT count(DISTINCT n.recipient_id) recipients FROM :coh c JOIN notifications n ON n.id = c.notification_id WHERE NOT c.has_row;
-- 10 other databases (run by hand, same query shape): lupin_db_v1baseline holds 3 rows, 2026-08-17 01:43; lupin_db_test holds 12 rows, 2026-11-18 20:44 to 22:43; neither holds an earlier case.

\echo '== 11 the 9 against the loss window: cohort asks answered between the backup (18 Nov 03:56:16Z) and the cleanup (19:05:17Z), by row state'
SELECT count(*) asks, count(*) FILTER (WHERE c.has_row) with_row FROM :coh c WHERE c.n_responded >= '2026-11-18 03:56:16+00' AND c.n_responded < '2026-11-18 19:06:00+00';
\echo '-- cohort asks answered outside that window in Oct-Nov with no row (expect 0)'
SELECT count(*) FROM :coh c WHERE NOT c.has_row AND c.n_responded >= '2026-09-26' AND NOT (c.n_responded >= '2026-11-18 03:56:16+00' AND c.n_responded < '2026-11-18 19:06:00+00');
\echo '-- delete statements the server has logged since statement logging went on (23:55Z 18 Nov): see docker logs; this file cannot read them'
ROLLBACK;
