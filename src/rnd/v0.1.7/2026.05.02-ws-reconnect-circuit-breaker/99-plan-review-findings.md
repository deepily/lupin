# Plan-Review Findings — Pre-Implementation

This file embeds REUSE pre-pass + Pass 1 (adversarial) + Pass 2
(fitness) findings against this doc set, run before any code is
written. Anchors per `planning-is-prompting/workflow/plan-review.md`:

- **Layer 1 (global)**: `~/.claude/CLAUDE.md` TEST OWNERSHIP MANDATE +
  DOCUMENTATION-FIRST PROTOCOL
- **Layer 2 (project)**: `00-working-contract.md`
- **Layer 3 (milestone)**: `01-design-review.md` Q1–Q12 FROZEN

---

## 1. REUSE Pre-Pass Findings

| New thing the plan proposes | Existing prior art (file:line) | Verdict |
|----------------------------|-------------------------------|---------|
| `WSChannel` factory in `ws-channel.js` | None — `grep -rn "WSChannel\|wsChannel\|ws-channel" src/fastapi_app/ src/cosa/` returns nothing | genuinely-new |
| Per-channel state machine for browser WS | None in `src/fastapi_app/static/js/` | genuinely-new |
| `fullJitterDelay()` helper | None — `notifications.js:5645` has the existing no-jitter exponential to be replaced; no jitter helper anywhere | genuinely-new |
| `#ws-circuit-banner` UI element | None in templates | genuinely-new |
| `.ws-circuit-retry-btn` CSS class | `.history-action-btn.retry-btn` exists in `notifications.css:4070` for a DIFFERENT button (job history retry). Class names are namespaced (`.ws-circuit-retry-btn` ≠ `.retry-btn`); no collision | genuinely-new (intentional namespacing — see Pass 2 RISK row #2) |
| Server-side close codes 4001/4002/4003 | None — `grep -rn "close.*code=4" src/cosa/rest/` returns nothing. Full `src/` re-grep scheduled at Phase 5 entry | genuinely-new (subject to pre-impl confirmation) |
| Page Lifecycle event listeners (visibilitychange/pageshow/pagehide/online/offline/freeze/resume) | None — `grep -rn "visibilitychange\|pageshow\|pagehide" src/fastapi_app/static/js/notifications.js` returns nothing | genuinely-new |
| `circuit_breaker` terminology | `src/fastapi_app/static/html/auth/admin/js/proxy-dashboard.js:251` already uses `circuit_breaker_state` for the **proxy-trust circuit breaker** (a different domain — backend service-trust scoring, not WS reconnect). Disambiguated by name: WSChannel uses `circuitOpen` (boolean) and `OPEN_CIRCUIT` (state); proxy uses `circuit_breaker_state.status` (object) | NOT reuse — different concern, different name. Add disambiguation note in 01-design-review.md |
| `MockWebSocket` test harness | None — no JS unit-test infrastructure exists in the codebase | genuinely-new (lives inline in `page.evaluate()`, not a standalone module) |

**REUSE verdict**: All new components are justified-new. The one
near-collision (proxy-dashboard's `circuit_breaker_state`) is in a
different domain and the names don't collide; recommend adding a single
disambiguation sentence to `01-design-review.md` so a future reader
doesn't conflate them. (Applied — see post-review fix #3 below.)

---

## 2. Pass 1 Findings — Adversarial Review (Ownership Language)

### Grep outputs (raw, for falsifiability)

```
$ grep -rnE "(^|[^a-zA-Z])[Mm]anual[ ]" src/rnd/v0.1.7/2026.05.02-ws-reconnect-circuit-breaker/*.md
02-phase-1-ws-channel-module.md:89:AND the new file passes a manual structural review against §2 of
02-phase-1-ws-channel-module.md:91:readyState guard). Manual structural review is performed by the AI
01-design-review.md:49:| Circuit shape | Two-state ... Manual "Retry now" button ...
01-design-review.md:143:| ... | Manual retry resets attempts to 0 ...
00-working-contract.md:58:- "Manual E2E" in any doc in this set means "not yet automated by me"
[+ historical mentions in expert-brief.md and solution-*.md, ignored]

$ grep -rn "EXECUTOR: HUMAN" src/rnd/v0.1.7/2026.05.02-ws-reconnect-circuit-breaker/*.md
00-working-contract.md:61:  carries `EXECUTOR: HUMAN <specific reason>` per Convention 3.
[Only 1 hit — the rule definition itself, not a tagged step]

$ grep -rnE "^\- \[ \] [^E]" src/rnd/v0.1.7/2026.05.02-ws-reconnect-circuit-breaker/*.md
[ZERO hits — all verification uses the EXECUTOR-tagged table format, not bare checkboxes]
```

### Findings table

| File | Line | Problem | Layer | Proposed fix |
|------|------|---------|-------|--------------|
| `02-phase-1-ws-channel-module.md` | 89–91 | "Manual structural review" wording is technically correct (next sentence clarifies "performed by the AI") but a hostile skim could mis-read "manual" as a human task. | Layer 1 | Replace "Manual structural review is performed by the AI" with "AI structural review (EXECUTOR: AI)" — eliminates the ambiguity entirely |
| `01-design-review.md` | 49 | "Manual 'Retry now' button" — describes the UI affordance (user-initiated click), NOT a test step. Different sense of "manual." | Layer 1 | OK as-is; semantic is clear from "user-driven half-open probe" same line |
| `01-design-review.md` | 143 | "Manual retry resets attempts to 0" — refers to the `manualRetry()` API method, NOT a test step. | Layer 1 | OK as-is; API name is `manualRetry()` and the row is in a Risk-Mitigation table, not a verification step |
| `00-working-contract.md` | 58 | "Manual E2E" appears explicitly to define what "Manual E2E" means — this IS the canonical definition mandated by Convention 5 in the plan-review doc. | Layer 2 | OK as-is — required by Convention 5 |
| All 5 phase docs (02–06) | every "Verification" table | Every row carries an explicit `EXECUTOR: AI` tag. Zero rows tagged `EXECUTOR: HUMAN`. | Layer 1 ✓ | OK as-is |

### Design concerns from Pass 1

None. Layer 3 (Q1–Q12 FROZEN) has not been challenged by Pass 1's
ownership review.

---

## 3. Pass 2 Findings — Fitness-to-Implement Review (Design Completeness)

### Grep outputs (raw)

```
$ grep -rnE "TBD|tbd|confirm during impl|decide at impl time" src/rnd/v0.1.7/2026.05.02-ws-reconnect-circuit-breaker/*.md
[ZERO hits]

$ grep -rn "Open sub-question" src/rnd/v0.1.7/2026.05.02-ws-reconnect-circuit-breaker/*.md
[ZERO hits]
```

### Findings table

| File | Section | Deficiency type | What's missing / ambiguous | Proposed fix |
|------|---------|-----------------|----------------------------|--------------|
| `03-phase-2-notifications-integration.md` | Diff Map row for `checkWebSocketHealth` | COMPLETENESS | The off-hours gate (8 AM–Midnight) is mentioned in Risks but the Diff Map says "becomes a watchdog" without spelling out that the off-hours gate is removed | Add explicit row: "off-hours gate REMOVED; watchdog runs always; circuit breaker bounds the cost" |
| `04-phase-3-circuit-banner-and-retry.md` | Banner Markup | COMPLETENESS | Doesn't specify WHERE in `notifications.html` the banner is inserted (parent container, sibling element) | Re-read `notifications.html` at Phase 3 entry and write the exact insertion sentinel (e.g., "after `<header id='top-bar'>` closing tag, before `<main>`"). Defer specifics to phase start, not pre-plan |
| `06-phase-5-server-side-hardening.md` | Existing routers/websocket.py Auth-Failure Sites | COMPLETENESS / TESTABILITY | Mentions "Re-check at impl time" for re-classifying the protocol-violation branch | Re-read `routers/websocket.py:374-462` at Phase 5 entry, write exact line numbers + close-code-per-branch table. This IS the "open sub-question" pattern — mark it as such per Convention 4 |
| `07-test-strategy.md` | Layer 5 | EXTERNAL DEPENDENCIES | Layer 5 invokes `docker pause`/`docker unpause` from Pytest. The runner needs `docker` CLI access. Is this guaranteed in the test container? | Verify before implementation: read `test_container_preflight.py` (the precedent). If docker access isn't guaranteed in all test environments, add a `subprocess.run(["docker", "version"], check=False)` early-skip with a clear skip reason |
| `06-phase-5-server-side-hardening.md` | Risks "renumber if collision found" | RISK SURFACE / EXTERNAL DEPENDENCIES | The grep was scoped to `src/cosa/rest/`. Other src subtrees not swept | Add to Phase 5 Verification: row "0. `grep -rn 'close.*code=4\|close.*code = 4' src/` returns no existing collisions. If hits, renumber the Lupin auth block away from collision" |
| `01-design-review.md` | §3 Q12 | DECISION TRACEABILITY | Q12 cites `feedback_feature_flag_preserves_old_path` memory but doesn't quote it inline; reader without memory access can't independently verify the citation | Add brief inline quote: "memory rule: 'A runtime fork via INI flag means BOTH branches stay first-class and maintained forever — never plan A/B then retire the loser'" |
| `03-phase-2-notifications-integration.md` | Channel Construction | AMBIGUITY | The cache-bust query string `?v=<cache-bust>` is shown as a placeholder; what's the actual cache-bust strategy for this ES module load? | Re-read existing `notifications.html` at Phase 2 entry to see how other JS assets are cache-busted (likely a build-time hash or a static version constant). Match that pattern |
| `05-phase-4-page-lifecycle.md` | initialization order | ORDERING | The initialization-order list is correct but doesn't say WHERE in `notifications.js` `init()` the `_attachPageLifecycle()` call goes (which line / after which existing call) | Defer to Phase 4 entry; the answer is "after channel construction, before initial connect()" per the order list, but the exact line site is part of implementation, not design |

### Explicit answers to TBDs

There are no `TBD` markers in the doc set. The "Re-check at impl time" /
"Re-read at phase entry" deferrals listed above are intentional and
follow Convention 4 (resolve at the phase boundary that owns the
question, not pre-plan).

### Design concerns from Pass 2

None. Layer 3 (Q1–Q12) survives Pass 2 unchallenged.

---

## 4. Resolution Loop — Fixes Applied

The following fixes were applied immediately (small wording changes,
no design impact):

1. `02-phase-1-ws-channel-module.md` — "Manual structural review" → "AI structural review (EXECUTOR: AI)"
2. `01-design-review.md` — added one-sentence disambiguation between WS `OPEN_CIRCUIT` and the unrelated proxy-dashboard `circuit_breaker_state`
3. `01-design-review.md` Q12 — added inline quote of the feature-flag memory rule
4. `03-phase-2-notifications-integration.md` — added explicit Diff Map row for the off-hours gate removal
5. `06-phase-5-server-side-hardening.md` — added Verification row 0: codebase-wide close-code grep before picking 4001/4002/4003
6. `00-working-contract.md` — added a "Pre-Phase Audit" reminder (see post-review fix below)

The deferrals (re-read at phase entry) are intentional. Per plan-review
Convention 4 and the spirit of "design what's design-time, defer what's
phase-start-time," these are NOT loose ends — they are bounded items
the AI commits to resolving at a specific later moment.

---

## 5. Pre-Phase Audit (Convention 4 follow-on)

Per `feedback_audit_plans_at_execute_time` (memory):
> Re-audit serialized plan diffs against feedback memories before
> applying; same-pattern adjacent violations are part of the fix, not
> "out of scope."

At each Phase N entry, the AI must:

1. Re-read this `99-plan-review-findings.md` to recall any Phase-N
   deferrals (e.g., the Phase-5 close-code-collision grep, the Phase-2
   cache-bust pattern lookup).
2. Re-read the relevant feedback memories (the ones listed in §6 below).
3. Surface any newly-discovered violation BEFORE writing code, not
   during code review.

This is the "execute-time audit" referenced in
`feedback_audit_plans_at_execute_time`.

---

## 6. Feedback-Memory Audit (pre-ExitPlanMode)

The following feedback memories were checked against this doc set for
violations. ✓ = no violation; → = applied as a fix:

| Memory | Status | Where in doc set |
|--------|--------|------------------|
| `feedback_user_is_never_a_tester` | ✓ | `00-working-contract.md`; every Verification row tagged `EXECUTOR: AI` |
| `feedback_test_server_monopolize_mode` | ✓ | `07-test-strategy.md` Layer 4/5 explicitly schedule via `/api/test-suite/submit` with slot confirmation |
| `feedback_tests_parameterize_base_url` | ✓ | `07-test-strategy.md` Layer 2 reads `LUPIN_API_URL` |
| `feedback_mock_tokens_are_legacy` | ✓ | `07-test-strategy.md` Layer 2 uses POST `/auth/login` + JWT, not mock_token_email_* |
| `feedback_auth_contract_lookup` | ✓ | `07-test-strategy.md` Layer 2 cites memory rule |
| `feedback_lupin_only_never_cosa` | → | `06-phase-5` edits `src/cosa/rest/routers/websocket.py` (CoSA file). Per `feedback_cosa_edit_vs_manage_git`, editing CoSA files is allowed — only git ops (add/commit/push) on the CoSA submodule are forbidden. Added explicit note in `06-phase-5` |
| `feedback_skip_rnd_doc_for_trivial_fixes` | ✓ | This is non-trivial; full doc set is justified |
| `feedback_naming_underscore_not_abbreviations` | ✓ | JS uses PascalCase (`WSChannel`); JS files use dashes per project convention (`ws-channel.js`); state names are clear underscores (`OPEN_CIRCUIT`, `BACKOFF_BASE_MS`) |
| `feedback_feature_flag_preserves_old_path` | ✓ | Q12 explicitly rejects feature flag, citing this rule with inline quote |
| `feedback_phase0_serialization_prominence` | ✓ | `00-index.md` has an explicit "Phase 0" heading immediately under the status block |
| `feedback_comprehensive_automated_testing` | ✓ | Five-layer pyramid in `07-test-strategy.md` |
| `feedback_plans_include_tracking_docs` | ✓ | Phase docs 02–06 + execution-log placeholders 90–94 noted in 00-index (created at phase entry, NOT pre-plan, per Convention 4) |
| `feedback_plan_self_audit_against_memory` | ✓ | This §6 IS the self-audit |
| `feedback_no_green_in_persona_pool` | ✓ N/A | Banner is red (error semantic), not green |
| `feedback_sweep_for_pattern_offenders` | ✓ | `03-phase-2` Diff Map enumerates ALL 5 `scheduleReconnect` callers — verified by `grep -n "scheduleReconnect" src/fastapi_app/static/js/notifications.js` |
| `feedback_enumerate_all_activation_paths` | ✓ | Plan covers UI button, page lifecycle (visibility, pageshow, pagehide, freeze, resume), online/offline events, BFCache restore — all surfaces are listed in `05-phase-4` |
| `feedback_acknowledge_receipt_before_tool_work` | ✓ | (session-level — already honored in this turn's flow) |
| `feedback_no_duplicate_notify_in_conversation_mode` | ✓ | (session-level — single closing notify only) |
| `feedback_conversation_mode_user_only_initiation` | ✓ | (session-level — no enter/exit_conversation_mode calls) |
| `feedback_never_auto_commit_push` | ✓ | Implementation phases will pause for explicit commit/push approval; not a planning concern but flagged here |
| `feedback_audit_plans_at_execute_time` | → | §5 above adds the "Pre-Phase Audit" requirement |
| `feedback_fastapi_auto_reload` | ✓ N/A | No restart asks in this plan |
| `feedback_ad_hoc_runs_go_to_7999` | ✓ | Layers 1, 2, 3 routed to `:7999` (AI-discretionary) |
| `feedback_tests_call_server_api_not_instantiate` | ✓ | Layer 2 uses real :7999 server via `websockets` lib, no in-process instantiation |

---

## 7. Termination

Per plan-review §9, the loop terminates when **either** condition fires:
1. **Quality**: 0 new structural findings; only wording tweaks remain.
2. **Count**: 2 full rounds completed.

This is round 1. Quality terminates: zero new STRUCTURAL findings (zero
TBDs, zero design-concern challenges to Q1–Q12, zero EXECUTOR: HUMAN
without justification). Wording fixes (§4) applied. The doc set passes
the gate.

`last-reviewed-at`: 2026-05-02 (pre-implementation). Will be updated
on each plan-review re-invocation.
