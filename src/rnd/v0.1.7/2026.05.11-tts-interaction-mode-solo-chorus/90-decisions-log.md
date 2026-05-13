# TTS Interaction Mode — Decisions Log

**Format**: Append-only ledger. Newest entries at top. **Never delete or rewrite past entries** — append a follow-up entry instead if a decision is revisited. This preserves the audit trail of how the design evolved.

Each entry: date, decision, context, alternatives considered, why this choice was made.

**Companion**: [`00-index.md`](00-index.md), [`03-open-questions.md`](03-open-questions.md), [`2026.05.12-tts-interaction-mode-solo-chorus.md`](2026.05.12-tts-interaction-mode-solo-chorus.md)

---

## 2026-05-12 — Default flipped: `solo` → `chorus` (at Phase 1 execution kickoff)

**Decision**: Default value for `tts interaction mode` flipped from `solo` to `chorus`. Helper fail-closed behavior (absent key / invalid value / config exception) all return `chorus` for consistency with the new default.

**Context**: At Phase 1 execution kickoff (2026-05-12, Rio persona resumption after Rick's walk), Rick noticed the design doc said `default = solo` and corrected it: "I thought we were starting in chorus mode, not solo mode." The framing flips: today's monopoly behavior was treated as the "safe deploy default" in the 2026-05-12 AM Rio session, but on reflection the experiment IS the work — defaulting to chorus and requiring an explicit `= solo` flip to invoke the monopoly fallback is the more consistent stance.

**Supersedes**: 2026-05-12 entry "INI value pair: `solo | chorus`" below — value pair unchanged, only the default changes. Reversibility intact: flipping the INI to `solo` re-engages monopoly behavior via the parallel-preserved plumbing.

**Alternatives considered at flip-time**:
- (a) Keep `default = solo`, force explicit `= chorus` opt-in for the experiment — rejected: makes the experiment harder to invoke on first deploy and requires every dev environment to remember to flip
- (b) Flip absent-key default to `chorus` but keep fail-closed fallbacks (invalid value, config exception) at `solo` — rejected for inconsistency; typo on `= chorus` would silently land in `solo` which surprises operators
- (c) Flip absent-key default AND all fail-closed fallbacks to `chorus` — **chosen** for consistency

**Why**: per Rick's clarification — "the experiment IS the work" — `chorus` is the new operational default. Fail-closed-to-default semantics keep typos / broken configs in the operator's expected state. Solo remains first-class permanent per `feedback_feature_flag_preserves_old_path`; nothing about reversibility changes.

**Downstream impact**:
- `10-phase1-ini-plumbing-design.md` updated throughout (helper return values, INI value, splainer rationale, test table)
- `2026.05.12-tts-interaction-mode-solo-chorus.md` §TL;DR / §The switch / §Phased landing references updated
- `00-index.md` status snapshot line 65 updated

---

## 2026-05-12 — Execution-time correction: `ConfigurationManager.get_config_value` does not exist; method is `.get`

**Decision**: The helper API call corrected from `ConfigurationManager().get_config_value( "tts interaction mode", default="..." )` to `ConfigurationManager().get( "tts interaction mode", default="...", return_type="string" )`. Additionally, the helper instantiates with `env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS"` to satisfy the singleton's first-call init contract per the CoSA CLAUDE.md memory.

**Context**: At Phase 1 execution-time audit, the design doc's assumed `.get_config_value()` API was checked against the actual `ConfigurationManager` source at `src/cosa/config/configuration_manager.py:745`. Method is `.get( key, default="@@@_None_@@@", silent=False, return_type="string" )`. Risk #1 in the Phase 1 design doc explicitly anticipated this exact divergence ("ConfigurationManager API differs from assumption (e.g., no `default=` kwarg)") — the audit found the divergence and the mitigation specified is exactly the fix.

**Why this matters**: doc-time speculation about API names is a known failure mode; the audit-at-execute-time mandate (`feedback_audit_plans_at_execute_time`) is what surfaced this before any code was written.

---

## 2026-05-12 — Q4 mode-coupling audit complete

**Decision**: Phase 1 implementation is unblocked. The audit found zero new implementation-blocking couplings; all mode-affecting behaviors are already covered by Phases 1–7 design docs or are explicitly out-of-scope per the May 12 plan.

**Context**: Q4 in `03-open-questions.md` asked whether other behaviors might be coupled to TTS interaction mode beyond the eight already gated in the plan. Audit ran 2026-05-12, scope: parent Lupin + CoSA `rest/`, excluded mobile + Firefox plugin.

**Findings summary** (full detail in [`04-mode-coupling-audit.md`](04-mode-coupling-audit.md)):

- **14 mode-independent couplings** confirmed (rename only; covered by Phase 2 / 5): stop-hook auto-narrate gating, idle-waiter exit, all three `conv_mode_wrap` callsites, `_notify_impl` on-branch, `get_session_info`, bridge helpers, TTS queue, `set_session_topic`, `voice_persona` field, `last_autonarrated_turn_id`.
- **1 new finding** requiring Phase 4 design update: MCP `instructions=` block + `enable_speakerphone` tool docstring have hard-coded mutual-exclusion language. Updated `13-phase4-mcp-tool-rename-design.md` §2 + new §3.6 to fold this into Phase 4 scope (Option B: single mode-aware paragraph).
- **3 confirmed out-of-scope** items: inbound mic-routing semantics (parked), persona pool sizing (borrow fallback handles N > 6), MCP HTTP-fallback bypass (existing Risk #7).
- **1 false-positive grep hit**: CJ Flow `monopolize: bool` field is an unrelated job-scheduling concept; documented to prevent future confusion.

**Why this matters**: per the user's directive "resolve Q4 first," the audit is the gate between drafted plan and Phase 1 implementation kickoff.

---

## 2026-05-12 — Subdirectory created: `2026.05.11-tts-interaction-mode-solo-chorus/`

**Decision**: Both speakerphone-mode docs moved into a new subdirectory using the May 11 origin date + the new canonical title slug. The subdir will hold all future documentation for this thought exercise.

**Context**: Rick anticipated that documentation will grow before any implementation begins (predecessor synthesis, open questions, decisions log, per-phase design docs, etc.). A flat directory with two related docs would get harder to navigate as more docs land.

**Alternatives considered**:

- (a) Keep flat with all docs at `src/rnd/v0.1.7/` root — rejected: doesn't scale as docs grow.
- (b) Use 2026-05-12 origin date for the subdir name — rejected: work started 2026-05-11, not 2026-05-12; subdir date should track origin.
- (c) Use the 2026-05-11 origin date + new canonical title slug — **chosen**.

**Why**: matches existing project convention (e.g., `2026.04.28-per-session-voice-personas/`, `2026.05.02-notifications-ui-js-refactor/`). Date reflects work-start, slug reflects current canonical direction.

---

## 2026-05-12 — INI value pair: `solo | chorus`

**Decision**: The runtime flag value pair is `solo | chorus`. The INI key is `tts interaction mode`. Default is `solo`.

**Context**: Voice-driven design conversation with Rick (Rio persona). The May 11 thought exercise used `cosa-voice speakerphone mode = per-session | monopoly`. Rewriting the plan around parallel preservation prompted a value-name review.

**Alternatives considered**:

| Pair | Verdict | Why rejected |
|---|---|---|
| `solo` / `chorus` | **Chosen** | Vivid, TTS-native metaphor (literally about voices); short; leaves room for `duet`/`trio`/`quartet` later |
| `monopoly` / `concurrent` | Rejected | Honest but dry; "monopoly" carries pejorative connotation |
| `exclusive` / `shared` | Rejected | Resource-lock framing reads as filesystem-y, not voice-y |
| `town-crier` / `party-line` | Rejected | Telephony metaphor is cute but obscure; ages out |
| `per-session` / `monopoly` (May 11 original) | Rejected | Asymmetric — one value names the new behavior, the other names the implementation mechanism. Hard to extend. |

**Why solo/chorus**: pairs naturally with a TTS context (literally about voices); maps "one voice at a time" vs "many voices together" intuitively; extensible to bounded-N modes (`duet`, `trio`, `quartet`) later without forcing redesign.

---

## 2026-05-12 — Parallel preservation as lead narrative (not hard-cut)

**Decision**: The May 12 canonical plan reframes the proposal around preserving both modes as first-class permanent paths. The May 11 hard-cut framing ("replace monopoly with per-session speakerphone, delete the plumbing") is rejected.

**Context**: Rick clarified on 2026-05-11 immediately after the original serialization that the monopoly plumbing must not be deleted — there must be a way to revert if the chorus experiment doesn't pan out. The May 11 doc captured this as a "post-serialization addendum" that overrode the body. By 2026-05-12 it was clear the addendum *was* the plan and the body's framing was stale.

**Alternatives considered**:

- (a) Leave the May 11 doc as-is, treat the addendum as authoritative — rejected: confusing for future readers, easy to miss the addendum.
- (b) Edit the May 11 doc in place to flip the framing — rejected: loses the historical record of how the design evolved.
- (c) Create a new May 12 doc with the rewritten framing, restore the May 11 doc to its original content with a "Superseded by" banner — **chosen**.

**Why**: preserves audit trail; future readers see one canonical plan (May 12) with a clear pointer back to the original thought exercise (May 11) for context.

---

## 2026-05-11 — Defer chorus-mode green-pin / color-pool UX question

**Decision**: The persona color pool's green-reservation question (what happens to green when monopoly is gone in chorus mode) is **deferred** to a Phase 8 follow-up. It does not block Phases 1–7.

**Context**: Today green is reserved for the mic-monopoly pin per [[feedback_no_green_in_persona_pool]]. Under chorus mode, that reservation has no use-case. Three options were sketched (see [Q1 in open-questions](03-open-questions.md#q1--chorus-mode-green-pin-reservation)).

**Why defer**: backend mode-switch + UI plumbing can land first; the color/glyph treatment is a single AC follow-up PR. Doesn't block Phases 1–7.

---

## 2026-05-11 — Mid-serialization addendum: preserve monopoly plumbing

**Decision**: The monopoly enforcement plumbing (asyncio.Lock, displacement scan, `find_active_conversation_sessions` helper, green mic-monopoly pin) must be **preserved**, not deleted.

**Context**: Original May 11 plan called for hard-cut removal. Rick clarified immediately after serialization that he wanted reversibility — a way to revert to monopoly if the chorus experiment didn't pan out:

> "I don't know as of yet if I want to throw away all of the plumbing used to create monopoly mode. We might want to think of having a separate parallel implementation that allows us to restore monopoly mode in case this experiment does not turn out the way I imagined it."

**Why**: per [[feedback_feature_flag_preserves_old_path]], feature-flagged forks preserve both paths permanently. Reversibility was the user's explicit ask. Both modes maintain forever-maintenance cost in exchange for the ability to revert.

**Downstream impact**: This decision is what drove the 2026-05-12 reframe to parallel-preservation as the lead narrative.

---

## 2026-05-11 — Original framing: hard-cut replacement (later superseded)

**Decision**: The original May 11 plan proposed a hard-cut replacement of monopoly mode with per-session speakerphone mode, with no migration code and no preserved fallback.

**Context**: Origin think-out-loud voice session 77e1bb27 (Mr. Radio persona). Framed as exploring "subtle changes I'm contemplating," explicitly NOT a commitment to build. Serialized as a thought exercise.

**Why this is logged despite being superseded**: the design evolved from this starting point. Future readers should see where the thinking began and how it shifted.

**Superseded by**: 2026-05-11 mid-serialization addendum (preserve monopoly plumbing) and 2026-05-12 parallel-preservation reframe (entries above).

---
