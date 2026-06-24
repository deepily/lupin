# Voice-Input-Row Rebuild — Fresh-Review CR Handoff (re-spin memento)

**Reviewer**: Cheech 🌿 (session `a85be662`, spawned by Mr Radio 🦉) · **Date**: 2026-06-23
**Lane**: `voice-input-row-rebuild` @ `01d2960f` (base `45e7a024`, merges clean onto `wip-v0.1.9-2026.06.21-bug-fix-implementation` HEAD `2e6cbf35`)
**Verdict**: **CHANGES-REQUESTED** — one blocker (coverage-integrity, not a functional bug).
**Routing (Mr Radio)**: Rachel makes the CR fix · Tiffany runs the deferred oracle 10/10 + 6 E2E, then re-reviews.

This memento carries the review through-line so the re-review inherits it without re-deriving.

---

## What reproduced GREEN (so the re-review need not redo)

Verified in a throwaway `/tmp` worktree at `01d2960f` (the registered `wt2` was pruned/swept; created fresh + symlinked root `node_modules`; cleaned up after):

| Check | Result | How |
|---|---|---|
| **Tier-3 carve genuinely lifted** | ✅ | `test_tier2_tier3.py` loop is now a plain 4-axis absolute `dx/dy/w/h` compare incl. `h`, **no anchor / no height-exclusion**; helpers `_sid_of` + `_dates_anchor` **deleted**; "anchor" survives only in the HISTORY comment. |
| **CSS byte-faithful** | ✅ | vs legacy `notifications.css:5297-5360` — block `padding 8px 12px / border-bottom 1px dashed #dee2e6 / background #f0f7ff` exact; mic/conv/send `height 34px · min-width 40px · padding · font-size · flex-shrink 0` exact. |
| **Markup byte-faithful** | ✅ | vs legacy `notifications.js:13504-13521` (mux idiom: delegated clicks, pre-composed ids). |
| **Geometry soundness** | ✅ | `* { box-sizing: border-box }` is universal (`lupin-base.css:14`) → the lane's added self-containment borders are **geometry-neutral**; byte-faithful props ⇒ Tier-3 parity well-founded. Corroborates the lane's "empirically green" carve-lift claim. |
| **tsc** | ✅ exit 0 | `tsc --noEmit -p tsconfig.json` |
| **Changed-file unit tests** | ✅ 47/47 | `tsx --test` on the two changed test files |
| **c8 100/100/100/100** | ✅ exit 0 | `c8 --all --100 --include <the two changed .ts>` directory-include |
| parity-harness.html | ✅ | only the `sender-card-recorder.css` `<link>` added; shared hash-guarded sheet untouched → golden stays valid |

**Deferred (NOT run by me — `:8000` / golden-gated)**: full parity-oracle 10/10 and the 6 E2E (`src/tests/e2e_ui/test_multiplexer_stt_insert_at_cursor.py` — 6 test fns confirmed by count). **→ Tiffany's task.** Geometry is well-corroborated above, so green is expected; still run for the record.

---

## THE BLOCKER (Rachel's fix)

**File**: `src/lupin_app/static/js/multiplexer/render/SenderCardRecorderRenderer.ts`

Two **whole-method** `c8 ignore start/stop` blocks mask reachable, stubbable, **partly-already-tested** logic. This violates the 100% mandate ("`c8 ignore` ONLY for genuinely-unreachable defensive branches"; "exercised at smoke tier" is exactly the deferral the mandate forbids). c8 reports 100% only because the ignore hides the untested branches.

### Span 1 — `handleSendClick`, lines **281–329**
- `/* c8 ignore start */` at **281** swallows the two validation early-returns:
  - **line 290** `if (!senderId.includes("#"))` → "Malformed sender_id; cannot send."
  - **line 297** `if (message === "")` → "Message is empty."
- **These are ALREADY exercised** by this file's own unit tests **#16** ("send with a malformed sender_id … renders an error") and **#17** ("send with an empty message …") — i.e. tested-but-uncounted.
- Still masked (genuinely untested, but **stubbable** not unreachable): the `message===""` **false** arm (flows to fetch), the `fetch` success path, the `!resp.ok` branch, the `catch`, and the `token !== null` header branch.

### Span 2 — `handleConvModeClick`, lines **335–366**
- `/* c8 ignore start */` at **335** swallows: the `sessionHash === ""` guard, the `active = button.classList.contains("is-active")` derivation, the `token !== null` branch, and the `fetch` success / `!resp.ok` / `catch` paths.
- Only test #18 ("conv-mode click is routed to the handler") covers the **delegation** in `onClick` (lines 188–191) — **not** anything inside the method.

### The fix (bounded, low-risk, peer-pattern-aligned)
1. **Stub `global.fetch`** in `src/tests/unit/multiplexer/render/sender_card_recorder_renderer.test.ts` — the established peer pattern (`auth_manager.test.ts`, `api_client.test.ts` already do this; 7 usages in `src/tests/unit/multiplexer/`).
2. Add unit cases covering:
   - **send**: success (2xx → input cleared + state reset), `!resp.ok` (error stripe), `catch`/network throw, message-non-empty path, token present/absent.
   - **conv-mode**: `sessionHash===""` guard, `active` true→`{on:false}` / false→`{on:true}` body, token present/absent, success, `!resp.ok`, `catch`.
3. **Narrow** both `c8 ignore` blocks to ONLY the genuine defensive guards (the `voiceInput === null` / attribute-empty null-returns already carry their own narrow `/* c8 ignore next */`). Once narrowed, tests #16/#17 cover the two validation early-returns and the new fetch-stub cases cover the rest — **c8 stays 100%**.

### Peer-pattern reference (the standard to meet)
`src/lupin_app/static/js/multiplexer/render/JobsPaneRenderer.ts` `handleDeleteClick` injects `this.api` and leaves the success / 404 / 5xx-rollback / `finally` branches **all counted + unit-tested**, reserving narrow `/* c8 ignore next */` for true defensive guards only. This lane's direct `fetch()` + whole-method ignore is the outlier. Either inject an api client (JobsPane style) **or** stub `fetch` (ApiClient/AuthManager style) — the latter is the smaller diff.

---

## Why CR not APPROVE-with-note
Per the manager's criterion: APPROVE-with-note only if the masked branches are proven genuinely unreachable. I proved the **opposite** — they're reachable (tests #16/#17 reach them) and the network paths are stubbable per peer convention. Everything else about the lane is excellent; this is a gate-integrity narrowing, then a clean merge.

## Pointers
- Verdict DM thread to Mr Radio: thread `ad9520d2-b1b2-4e32-9c97-33ba2d1ee515`.
- Lane build plan (lane-branch only): `git show voice-input-row-rebuild:src/rnd/v0.1.9/2026.06.22-multiplexer-full-parity-build/03-voice-input-row-rebuild-lane.md`.
