1. **Authentication Success Rate**
   ```sql
   SELECT
       COUNT(CASE WHEN event_type = 'login_success' THEN 1 END) as successes,
       COUNT(CASE WHEN event_type = 'login_failure' THEN 1 END) as failures,
       ROUND(100.0 * COUNT(CASE WHEN event_type = 'login_success' THEN 1 END) /
             COUNT(*), 2) as success_rate
   FROM auth_audit_log
   WHERE event_type IN ('login_success', 'login_failure')
     AND created_at > datetime('now', '-1 hour');
   ```

