# 05 — Adapter Collapse: `renderHistoryCard()`

**Phase**: 3
**Files**: `src/fastapi_app/static/js/notifications.js`

---

## 1. Goal

After Phase 1 (backend flat shape) and Phase 2 (frontend `_isHistory` removal), the only remaining job of `renderHistoryCard()` (`notifications.js:6026-6086`) is to:

1. Call `renderJobCard(job, 'history')`
2. Append history-specific action buttons (delete + conditional retry) via string splice

Phase 3 collapses this. There are two options.

---

## 2. Option A — Keep as ≤5-line wrapper

```javascript
renderHistoryCard( job ) {
    let html = this.renderJobCard( job, 'history' );
    return this._injectHistoryActions( html, job );
}
```

**Pros**: minimal diff, history-specific actions still in their own helper.
**Cons**: still has a per-bucket renderer in name. The "single source of truth" claim isn't quite literal.

---

## 3. Option B — Move history actions into `renderJobCard()` directly (recommended)

Inside `renderJobCard()`, the action-button block already has queueName-driven branches (cancel for `run`, pause for `todo`, etc.). Add a `queueName === 'history'` branch that emits the retry button when applicable:

```javascript
// Inside renderJobCard's action-button section
${ queueName === 'history' && shouldOfferRetry( job ) ? `
    <button class="history-action-btn"
            onclick="window.notificationsUI.retryFromHistory('${jobId}')">
        🔁 Retry
    </button>` : '' }
```

The delete button is already routed through `_dispatchDelete( jobId, queueName )` from Phase 2 — it picks `deleteHistoryJob` automatically when `queueName === 'history'`. So the history-specific delete is already handled.

After this:
- `renderHistoryCard()` is **deleted entirely**
- `loadJobHistory()` calls `renderJobCard(normalizedJob, 'history')` directly for each row
- The mapping of `metadata_json` → flat shape (which Phase 1 made unnecessary at the API layer) is gone from the frontend

**Pros**: literal single source of truth, deletes ~60 lines of adapter code.
**Cons**: slightly larger diff in `renderJobCard()` (one extra branch, copy-paste pattern to existing branches).

---

## 4. Recommendation: Option B

It's the literal single source of truth the prior fix attempts have been chasing. The "extra branch" cost in `renderJobCard()` is ~5 lines and parallels existing per-queueName branches. The deletion of `renderHistoryCard()` is what makes the cleanup permanent — every future contributor sees one renderer, not two.

---

## 5. Concrete diff sketch (Option B)

### 5.1 Delete `renderHistoryCard()` entirely

Lines 6026-6086 (the function and its inline `_normalizeHistoryJob` adapter logic).

### 5.2 Inline normalization at the call site, OR rely on Phase 1 to make it unnecessary

After Phase 1, the backend returns flat fields. The only missing piece in older rows that don't have new fields would be the transition-window fallback. **Phase 3 happens AFTER backend rollout has stabilized**, so we drop the fallback and trust the new shape.

`loadJobHistory()` change:

```javascript
// BEFORE (Phase 2)
data.jobs.forEach( job => {
    const html = this.renderHistoryCard( job );
    container.insertAdjacentHTML( 'beforeend', html );
} );

// AFTER (Phase 3)
data.jobs.forEach( job => {
    const html = this.renderJobCard( job, 'history' );
    container.insertAdjacentHTML( 'beforeend', html );
} );
```

If the API returns `id_hash` instead of `job_id` (legacy column-name mismatch), normalize at the call site with a one-liner:
```javascript
job.job_id = job.job_id || job.id_hash;
```
**Or** — better — make Phase 1 emit `job_id` consistently from `query_job_history()`. Adding this to the Phase 1 unpacker is simpler than carrying a frontend rename.

### 5.3 Add history retry into `renderJobCard()`

```javascript
// In the per-card action-button section, alongside cancel/pause/delete:
${ this._shouldOfferHistoryRetry( job, queueName ) ? `
    <button class="history-action-btn job-action-btn"
            title="Retry this job"
            onclick="window.notificationsUI.retryFromHistory('${jobId}')">
        🔁
    </button>` : '' }
```

Helper:
```javascript
_shouldOfferHistoryRetry( job, queueName ) {
    if ( queueName !== 'history' ) return false;
    // Same eligibility logic that was in renderHistoryActions before
    return job.status === 'failed' || job.status === 'dead';
}
```

---

## 6. Final grep audit (Phase 3 gates)

```bash
# All MUST return zero matches:
grep -n '_isHistory'         src/fastapi_app/static/js/notifications.js
grep -n 'renderHistoryCard'  src/fastapi_app/static/js/notifications.js

# This MAY have matches (if any code reads metadata_json for fields the API now flattens):
grep -nE 'metadata_json\\.|metadata\\.(response_text|abstract|report_link|cost_summary)' \
    src/fastapi_app/static/js/notifications.js

# Should return zero hardcoded falses:
grep -nE 'has_interactions\\s*:\\s*false' src/fastapi_app/static/js/notifications.js
```

If `metadata_json.*` reads remain after Phase 3, that's a sign the frontend is still doing the unpacking the backend now does — remove and re-test.

---

## 7. Risk

The only Phase-3 risk is that a stale call site for `renderHistoryCard()` exists somewhere we haven't found. Mitigation: the grep audit above will catch it (zero matches required). If the grep returns matches, fix and re-run before declaring Phase 3 complete.
