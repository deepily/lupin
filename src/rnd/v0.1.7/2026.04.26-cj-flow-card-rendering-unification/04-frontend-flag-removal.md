# 04 — Frontend Flag Removal (B, Lupin)

**Phase**: 2
**Files**:
- `src/fastapi_app/static/js/notifications.js`
- `src/fastapi_app/templates/notifications.html` (cache-bust bump)

---

## 1. Goal

Remove `_isHistory` from the rendering pipeline. Replace its two consumers (DOM-id namespacing and delete-handler routing) with queue-name-driven dispatch through a lookup table. After this phase, `renderJobCard()` does not branch on a "history flag" — it branches only on `queueName`, the same way it already branches on `queueName === 'todo'`, `queueName === 'run'`, etc.

---

## 2. Current state (per forensic investigation)

`_isHistory` has 3 occurrences in `notifications.js`:

| Line | Code | Role |
|---|---|---|
| 6065 | `_isHistory : true` | Set by `renderHistoryCard()` |
| 6850 | `const idKey = job._isHistory ? \`history-${jobId}\` : jobId;` | DOM-id namespacing in `renderJobCard()` |
| 6976 | `const deleteAction = job._isHistory ? \`...deleteHistoryJob(...)\` : \`...deleteQueueJob(...)\`;` | Delete-action routing in `renderJobCard()` |

Plus one related defect: `notifications.js:6054` hardcodes `has_interactions: false` on history cards.

---

## 3. Target state

- `_isHistory` is deleted from the codebase. Zero matches.
- `renderJobCard()` reads `queueName` (already a parameter) for both DOM-id namespacing and delete-handler routing.
- Delete-handler routing goes through a `DELETE_HANDLERS` lookup table — single chokepoint, easy to extend, no string-template branching in the renderer.
- `renderHistoryCard()` no longer sets `_isHistory` and no longer hardcodes `has_interactions`. Reads the new top-level `has_interactions` field returned by the backend (post-Phase-1).

---

## 4. Concrete changes

### 4.1 Add `DELETE_HANDLERS` lookup near top of file

Location: near the existing module-level constants (`notifications.js`, top of class definition).

```javascript
const DELETE_HANDLERS = {
    todo    : ( jobId, queueName ) => window.notificationsUI.deleteQueueJob( jobId, queueName ),
    run     : ( jobId, queueName ) => window.notificationsUI.deleteQueueJob( jobId, queueName ),
    done    : ( jobId, queueName ) => window.notificationsUI.deleteQueueJob( jobId, queueName ),
    dead    : ( jobId, queueName ) => window.notificationsUI.deleteQueueJob( jobId, queueName ),
    history : ( jobId )            => window.notificationsUI.deleteHistoryJob( jobId )
};
```

### 4.2 Add a single dispatcher method

```javascript
_dispatchDelete( jobId, queueName ) {
    const handler = DELETE_HANDLERS[ queueName ];
    if ( !handler ) {
        console.error( `[Notifications ERROR] No delete handler for queueName=${queueName}` );
        return;
    }
    handler( jobId, queueName );
}
```

### 4.3 Replace `notifications.js:6850` (DOM-id namespacing)

**Before**:
```javascript
const idKey = job._isHistory ? `history-${jobId}` : jobId;
```

**After**:
```javascript
const idKey = `${queueName}-${jobId}`;
```

This namespaces every queue's DOM ids by queue name (not just history). Slight side effect: `done-${jobId}` is now used everywhere instead of bare `${jobId}`. **CSS selectors and `getElementById` calls that target bare `${jobId}` ids must be updated** — included in the audit checklist below.

### 4.4 Replace `notifications.js:6976` (delete routing)

**Before**:
```javascript
const deleteAction = job._isHistory
    ? `window.notificationsUI.deleteHistoryJob('${jobId}')`
    : `window.notificationsUI.deleteQueueJob('${jobId}', '${queueName}')`;
```

**After**:
```javascript
const deleteAction = `window.notificationsUI._dispatchDelete( '${jobId}', '${queueName}' )`;
```

### 4.5 Update `renderHistoryCard()` (`notifications.js:6026-6086`)

Three changes inside the function:
1. **Drop** `_isHistory: true` from the normalized object
2. **Drop hardcoded** `has_interactions: false` — read from `job.has_interactions` directly (now flat from backend)
3. **Pass `queueName: 'history'`** explicitly to `renderJobCard()` instead of mapping by status

After Phase 2, `renderHistoryCard()` is still alive — it's an adapter that:
- Pulls remaining nested fields from `metadata_json` IF present (transition-window fallback)
- Calls `renderJobCard(normalized, 'history')`
- Appends history-specific action buttons (delete + retry) via string splice

Phase 3 collapses this further (see `05-adapter-collapse.md`).

### 4.6 Cache-bust

In `src/fastapi_app/templates/notifications.html`, find the `<script src="...notifications.js?v=...">` tag and bump the `v=` query param to `20260426a` (or current date).

---

## 5. Audit checklist (post-edit)

Run these before declaring Phase 2 complete:

```bash
# Zero matches expected:
grep -n '_isHistory' src/fastapi_app/static/js/notifications.js

# Verify _dispatchDelete is only the new method:
grep -n '_dispatchDelete' src/fastapi_app/static/js/notifications.js

# Find any bare-jobId getElementById calls that need to migrate to namespaced ids:
grep -nE "getElementById\\(\\s*['\"]?\\\$?\\{?jobId" src/fastapi_app/static/js/notifications.js
grep -nE "getElementById\\(\\s*['\"]\\\$?\\{?[a-z]+-\\\$?\\{?jobId" src/fastapi_app/static/js/notifications.js  # already-namespaced

# Hardcoded has_interactions:
grep -n 'has_interactions.*false' src/fastapi_app/static/js/notifications.js
```

The `getElementById` audit is the riskiest part of this phase — if any bare-jobId selector slips through, the now-namespaced cards become unreachable. Read every match individually; do not assume.

---

## 6. Transition-window fallback

During the brief window where Phase 2 frontend is deployed but Phase 1 backend may not be (e.g., older container, partial rollout):

```javascript
// In renderHistoryCard() — read top-level field with fallback during transition
has_interactions: job.has_interactions ?? Boolean( job.session_id )
```

This `??` chain accepts the new top-level field if present, otherwise falls back to the proxy. Removed in Phase 3 audit.

---

## 7. Why a dispatcher method, not a `<button onclick="DELETE_HANDLERS[queueName]( ...)">` direct call?

The card HTML is built as a template string (not React/Vue). The `onclick=` attribute requires a string that resolves to a callable expression. Embedding a lookup-table call inline:
```html
onclick="DELETE_HANDLERS['${queueName}']('${jobId}', '${queueName}')"
```
...works but creates two problems:
1. `DELETE_HANDLERS` would have to be on `window` (`window.DELETE_HANDLERS`)
2. Hard to add logging/instrumentation later without changing every template

The dispatcher method `_dispatchDelete()` keeps the lookup private to the class, makes it trivial to add logging, and the inline `onclick` stays readable.

---

## 8. Test scope (Phase 2)

See `06-testing-strategy.md` §Phase 2 for full breakdown. Key cases this doc drives:

- E2E: history card renders 💬 indicator when notifications exist (was always missing)
- E2E: clicking 💬 on history card fires `/api/get-job-interactions/{job_id}` and renders the transcript
- E2E: clicking delete on history card fires `DELETE /api/job-history/{id}` (not `/api/queue/history/{id}`)
- E2E: clicking delete on done card fires `DELETE /api/queue/done/{id}` (parity)
- E2E: DOM-id namespacing prevents collision when the same job_id appears in both done (live) and history (after refresh)
- Visual regression: done card and history card render side-by-side near-identically for the same terminal job
