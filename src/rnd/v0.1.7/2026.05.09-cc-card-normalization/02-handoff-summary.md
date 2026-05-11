# Handoff Summary — Claude Code UI Card + Endpoint Normalization

**For**: Lupin mobile team + multiplexer R&D team (Phase 6b in flight).
**Authored**: 2026-05-10 (parent Lupin session).
**Read time**: ≤ 5 minutes.
**Full design**: [`01-design.md`](01-design.md). **Execution log**: [`90-execution-log.md`](90-execution-log.md).

---

## TL;DR

The Claude Code submit endpoint is renamed: **new canonical `POST /api/claude-code/submit`**, old URL `POST /api/claude-code/queue/submit` kept as a deprecated alias for **one release cycle** then removed. The notifications-page CC card is pruned of dispatch-retirement gravestones (yellow banner, disabled inject/interrupt/end-session buttons, response panel, session-info row, execution-mode select) so it now matches sibling cards (Research, Podcast, Presentation, SWE, BFE, Test Suite). Backend factory chain unchanged — same `agentic_job_factory.create_agentic_job()` path, same CJ Flow lifecycle, same `cc-{uuid8}` job_id convention.

---

## What changed

### URL contract

| Surface | Before | After |
|---------|--------|-------|
| Canonical CC submit | `POST /api/claude-code/queue/submit` | **`POST /api/claude-code/submit`** |
| Backward-compat alias | (none — only `/queue/submit` existed) | `POST /api/claude-code/queue/submit` (deprecated, one release cycle) |
| Request body shape | `ClaudeCodeQueueRequest` Pydantic | UNCHANGED — same schema |
| Response shape | `ClaudeCodeQueueResponse` Pydantic | UNCHANGED — same schema |
| Backend factory | `agentic_job_factory.create_agentic_job()` | UNCHANGED — same factory |
| Job ID convention | `cc-{uuid8}` | UNCHANGED |
| Multiplexer Jobs pane surfacing | via `job_state_transition` events | UNCHANGED — agent-agnostic renderer |

**Q8 fallback contingency**: If FastAPI rejects the stacked-decorator alias pattern at verification, the alias is COMMENTED OUT (not deleted) in the source as a code-level breadcrumb. In that case **there is no working alias** and consumers must migrate to `/api/claude-code/submit` immediately. The execution log will document which path was taken.

### Notifications page UI (`/app/notifications` Submit Claude Code Task card)

| Element | Before | After |
|---------|--------|-------|
| Card header | `🤖 Claude Code Dispatcher` | `🤖 Submit Claude Code Task` (verb-first, matches siblings) |
| Project select | present | UNCHANGED |
| Prompt textarea + STT mic | present | UNCHANGED |
| Task-type select | BOUNDED only; INTERACTIVE in HTML comment | BOUNDED + **disabled** INTERACTIVE option (visual breadcrumb that it returns later) |
| Dry-run / schedule / monopolize / submit button | present | UNCHANGED |
| Status feedback | wrote to `<pre id="cc-response">` (yellow retirement banner) | New `<div id="cc-submit-status">` matching sibling pattern (neutral / green-success / red-error) |
| `#cc-execution-mode` select (disabled, single-option) | present | **DELETED** |
| `<pre id="cc-response">` per-turn streaming panel | present (yellow retirement notice) | **DELETED** |
| `#cc-option-b-controls` retired banner + 4 disabled inject/interrupt/end buttons | present | **DELETED** |
| `#cc-session-info` (hidden by default) | present | **DELETED** (redundant with multiplexer Jobs pane) |

---

## Why

1. **Consumer split** between endpoints: per-agent `/api/<agent>/submit` paths serve **human UI** (typed Pydantic 422s, friendly per-field error messages); `/api/push-agentic` serves **agent-to-agent** (opaque args, agent constructor validates). CC was a URL outlier from the dispatch-retirement era — `/queue/submit` was originally a contrast marker against `/dispatch`, but with dispatch retired (2026-05-05, commit `73bee1b`), the infix is a dangling fossil. Rename brings it in line with siblings.
2. **The dead UI was visual gravestones** for the retired inject/interrupt/end-session controls. Sibling cards have NONE of these — they're a form + submit button + small status div, period. Pruning brings the CC card down to that shape.
3. **No architectural shift**: the backend factory chain is unchanged. Submit → `agentic_job_factory.create_agentic_job()` → CJ Flow → multiplexer Jobs pane works identically to before.

---

## Per-sub-project action required

### 📱 Lupin Mobile (`src/lupin-mobile/`)

**Action items**:
1. **Update `claude_code_repository.dart:87`** — change the `queueSubmit()` POST URL from `/api/claude-code/queue/submit` to `/api/claude-code/submit`. The old URL still works as an alias for one release cycle (or, if Q8 fallback was taken, breaks immediately — check the execution log to find out which).
2. **Update unit + bloc tests** (`test/unit/claude_code/claude_code_repository_test.dart`, `claude_code_bloc_test.dart`) to match the new URL constant.
3. **Plan for INTERACTIVE controls return**: when `ClaudeCodeJob.inject/interrupt/end_session` ship (separate epic, see `src/rnd/v0.1.7/2026.05.07-claude-code-bounded-redesign/`), co-design new mobile controls with the new endpoints — do NOT revive the retired dispatch-cluster shape.
4. **Continue migrating off the retired dispatch cluster**: `dispatch()`, `getStatus()`, `inject()`, `interrupt()`, `endSession()` methods at `claude_code_repository.dart:15-78` all target `/api/claude-code/dispatch` (retired 2026-05-05) and are already broken. Existing TODO entries cover this work; this URL rename is one piece of the larger mobile migration story.

**Where mobile's TODO lives**: `src/lupin-mobile/TODO.md` — a new entry pointing back to this handoff doc has been seeded by the parent Lupin session that produced this change. **Expected entry shape** (look for this line under the Pending section):

```
- [ ] [LUPIN-CC-SUBMIT-RENAME] Update Claude Code submit endpoint from /api/claude-code/queue/submit to /api/claude-code/submit. Alias active for one release cycle from <commit-date>. See parent Lupin src/rnd/v0.1.7/2026.05.09-cc-card-normalization/02-handoff-summary.md for full context. [Q8 verdict: PRIMARY|FALLBACK]
```

The `[Q8 verdict]` field will be filled at Phase 6 — PRIMARY means alias works (full release-cycle window), FALLBACK means alias was rejected by FastAPI and you must migrate immediately on next deploy.

**Important — placeholder vs literal**: the `[Q8 verdict: PRIMARY|FALLBACK]` text shown above is a PLACEHOLDER. The parent Lupin session populates it at Phase 6.8 commit time with either the literal word `PRIMARY` or the literal word `FALLBACK` — NEVER the pipe characters or both words. Mobile should only ever see the populated form (e.g. `[Q8 verdict: PRIMARY]`). If you see the literal `PRIMARY|FALLBACK`, the parent session forgot to fill it — flag back to the parent before acting on the TODO.

### 🧩 Multiplexer R&D (`src/rnd/v0.1.7/2026.05.02-notifications-ui-js-refactor/`, Phase 6b in flight)

**Action items**:
1. **No code changes today** — `JobsPaneRenderer.ts` is agent-agnostic; CC jobs already render uniformly via `metadata.agent_type` (`stores/JobStore.ts:215`). The URL change is server-side only.
2. **Visual baseline awareness**: the CC card in `notifications.html` no longer carries cosmetic gravestones. If Phase 6b touches CC card screenshots (e.g. as part of any Jobs-pane visual regression suite), expect to regenerate the baseline. The parent Lupin session has scheduled Phase 5.9 to regen baselines as part of the change; if your in-flight work has its own baselines for the CC card, regen those too.
3. **Future INTERACTIVE controls**: when `ClaudeCodeJob.inject/interrupt/end_session` ship, the new controls may need a Jobs-pane interactive widget surface (Phase 6b territory per the multiplexer slicing manifest). Confirm with the bounded-redesign R&D doc (`src/rnd/v0.1.7/2026.05.07-claude-code-bounded-redesign/`) before designing the widget — the canonical shape is still in flight, so don't lock the multiplexer-side widget contract until that lands.

**Where multiplexer's open follow-ups live**: `src/rnd/v0.1.7/2026.05.02-notifications-ui-js-refactor/00-synthesis-and-roadmap.md` Open follow-ups section — a new entry pointing back to this handoff doc has been seeded.

---

## Migration timeline

| Date | Event |
|------|-------|
| 2026-05-10 | Phase 0 docs serialized (this folder); `/plan-review` REUSE → Pass 1 → Pass 2 sequential review begins |
| TBD (post-plan-review) | Phases 1-4 implementation lands in parent Lupin + CoSA submodule |
| TBD (post-implementation) | Phase 5 verification (`:7999` smoke + `:8000` scheduled E2E + visual baseline regen) |
| TBD (post-verification) | Phase 6 wrap (TODO updates, history.md, commits) — alias goes live |
| **TBD + 1 release cycle** | **Alias `/api/claude-code/queue/submit` REMOVED.** Mobile must have migrated by this date. |

**"One release cycle" — concrete trigger**: the alias `/api/claude-code/queue/submit` is REMOVED when the NEXT stable release of Lupin (`v0.1.8` or later) is cut and deployed to production. The next development cycle after that release tag will land the alias-removal commit. **Mobile MUST migrate during the window between the parent Lupin commit landing (Phase 6.8 of the parent's serialization) and the next stable release being cut.** Phase 6.2 of the parent plan will pin the target release tag once the parent commit hash is known.

If Q8 FALLBACK path was taken (no working alias because FastAPI rejected stacked decorators), the timeline collapses: mobile must migrate **before the parent Lupin commit lands**, otherwise mobile breaks immediately on next deploy. The Q8 verdict is recorded in the parent plan's `90-execution-log.md` Phase 4 evidence section.

---

## Where to ask

| Source | Path |
|--------|------|
| Full design (Q-decisions, ACs, risks) | `src/rnd/v0.1.7/2026.05.09-cc-card-normalization/01-design.md` |
| Execution log (per-phase evidence + Q8 fallback verdict) | `src/rnd/v0.1.7/2026.05.09-cc-card-normalization/90-execution-log.md` |
| Master nav (REUSE table, prior art) | `src/rnd/v0.1.7/2026.05.09-cc-card-normalization/00-index.md` |
| Origin plan file (pre-merge reference) | `~/.claude/plans/ok-so-far-so-swirling-pearl.md` |
| Predecessor R&D — dispatch retirement | `src/rnd/v0.1.7/2026.05.05-claude-code-dispatch-retirement/01-plan.md` |
| Predecessor R&D — bounded redesign (in flight) | `src/rnd/v0.1.7/2026.05.07-claude-code-bounded-redesign/00-index.md` |
| Sibling-card R&D — multiplexer notifications refactor | `src/rnd/v0.1.7/2026.05.02-notifications-ui-js-refactor/00-synthesis-and-roadmap.md` |
| Parent Lupin TODO with mobile follow-ups | `TODO.md` (root) — `🪦 CC DISPATCH RETIREMENT — Follow-ups` section |
| Mobile TODO | `src/lupin-mobile/TODO.md` |

**Need a human?** If you need immediate clarification on this handoff:

1. **Primary contact**: the parent Lupin session author recorded in the commit hash at Phase 6.8. Extract via `git show <hash> --format='%an <%ae>'` from a parent-Lupin checkout.
2. **Fallback**: flag in `bug-fix-queue.md` (root of parent Lupin) under the "🔥 Top of Queue — IMMEDIATE" section with a pointer to this file and your specific blocker. Async — may take a session cycle to be seen.
3. **Last resort**: open an issue against the parent Lupin repo with a `cc-handoff-blocker` label so the next active Lupin session picks it up.
