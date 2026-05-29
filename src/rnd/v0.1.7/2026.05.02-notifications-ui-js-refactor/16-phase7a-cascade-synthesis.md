# Phase 7a Telemetry — Cascade Synthesis & Implementer Handoff (Run 4)

**Status**: 🟢 CASCADE-COMPLETE 2026-05-20 — pending Step 9 light-review by Krishna 🦚
**Manager**: Tiberius 🌑 (Run 4)
**Author**: Mr Radio 🦉 (Stage 0)
**Reviewers**: Rachel 🕊️ (Stage 1 Usability/Reuse), Krishna 🦚 (Stage 2 Risk/Anti-pattern), Rio ⚡ (Stage 3 Ownership/Convention)
**Observer**: María 🌸 (doctrine consultant, telemetry capture)

---

## TL;DR

Phase 7a Telemetry design surface is **implementer-ready** following Run 4 of the cascaded plan-review workflow. Three reviewer stages executed cleanly; 14 active findings + 1 cosmetic + 2 withdrawn closed across cap-disciplined revision cycles. Five v1.1 doctrine candidates surfaced and empirically validated during the run. Implementation handoff doc is `15-phase7a-telemetry-design.md`; this synthesis captures the cascade execution itself + doctrine telemetry.

## §1. Cross-references

| Artifact | Path | Role |
|---|---|---|
| **Canonical design doc** | `src/rnd/v0.1.7/2026.05.02-notifications-ui-js-refactor/15-phase7a-telemetry-design.md` | Implementer reference; cascade-ratified content |
| Pre-cascade recon | `src/rnd/v0.1.7/2026.05.02-notifications-ui-js-refactor/14-phase7a-telemetry-pre-cascade-recon.md` | 6 browser-API archaeology items resolved upstream |
| Slicing manifest | `src/rnd/v0.1.7/2026.05.02-notifications-ui-js-refactor/13-phase7-slicing-manifest.md` | Phase 7 → 7a/7b/7c/7d boundaries |
| Step 0 doctrine | PIP commit `bbb3e47` | Cascade preparation v1 live-test (validated this run) |
| Step 9 doctrine | PIP commits `6a8084c`, `0ae9aba`, `bbb3e47` | Synthesis + handoff v1 live-test (this doc) |
| Run 3 Section B precedent | `src/rnd/v0.1.7/2026.05.02-notifications-ui-js-refactor/10-phase6c-persona-focus-recorder-design.md` | Doctrine-candidate ancestor for multi-surface sweep gap |

## §2. Cascade execution timeline

| Beat | Wall-clock UTC | Notes |
|---|---|---|
| Step 0 prep complete | ~02:00 (estimated) | Mr Radio drafted slicing manifest + recon + Stage 0 design |
| Step 0 light-review by María | 02:02:41 | 👍 6 of 6 rubric criteria pass; 2 minor v2 candidates |
| Stage 1 dispatch to Rachel | 02:09:41 | First reviewer dispatch |
| Stage 1 review (Rachel) | 02:14:30 | 1F + 2P + 5 reuse confirms |
| Stage 1 cap-2 revision (Mr Radio) | 02:18:57 | Single turn closed all 3 findings |
| Stage 1 cap-3 dispatch | 02:22:27 | Manager re-dispatch |
| Stage 1 cap-3 close (Rachel) | 02:24:30 | 🟢 closed-clean |
| Stage 2 dispatch to Krishna | 02:28:11 | Risk/Anti-pattern lens |
| Stage 2 review (Krishna) | 02:33:39 | 1F + 4inc + 3P + 1cosm |
| Manager-side phantom-lag | 02:33-02:46 | Heartbeat-injection density obscured peer-DM; María observer probe cleared |
| Stage 2 cap-2 dispatch | 02:47:19 | All Manager pins articulated (Path A R-3, Option A + sub-revise R-5) |
| Stage 2 cap-2 revision (Mr Radio) | 02:50:52 | Single turn covered 9 findings + 1 cosmetic |
| Stage 2 cap-3 dispatch | 02:51:34 | Manager re-dispatch |
| Stage 2 cap-3 close (Krishna) | 02:54:24 | 🟡 close-with-quibbles (4 doctrine-sweep drift items) |
| Stage 2 tiny cleanup dispatch | 02:57:54 | T1 line edits, not cap-2 turn 2 |
| Stage 2 cleanup applied (Mr Radio) | 02:58:40 | First-pass; Tiffany-rename-pass had silently reverted edits |
| Stage 3 dispatch to Rio | 02:59:44 | Ownership/Convention lens |
| Cleanup re-apply (Mr Radio) | 03:00:30 | Caught Tiffany-rename-pass revert on grep-sweep |
| State-update DM to Rio | 03:01:41 | Manager + Rio re-grep verifies canonical state |
| Stage 3 corrected review (Rio) | 03:07:29 | 3 inconsistency + 1 cosmetic + 1 withdrawn (F-Rio-7a-2 stale-state false positive) |
| Stage 3 cap-2 dispatch | 03:10:22 | 5-pattern grep-sweep mandate explicit |
| Stage 3 cap-2 revision (Mr Radio) | 03:13:44 | Caught 3rd silent Tiffany revert (OSQ-T-5/T-6/T-7) during grep-sweep |
| Stage 3 cap-3 dispatch | 03:14:31 | Manager re-dispatch |
| Stage 3 cap-3 close (Rio) | 03:16:28 | 🟢 closed-clean — all 6 verification points pass |
| **Manager synthesis pass starts** | ~03:17 | THIS DOC |
| Step 9 light-review (Krishna) | TBD | Pending this doc dispatch |

**Total cascade wall-clock**: ~1h 30min (Step 0 light-review through Stage 3 close).
**Stages breakdown**: Stage 1 ~38 min; Stage 2 ~25 min effective (excluding 13 min Manager phantom-lag) + 7 min cleanup; Stage 3 ~17 min effective.

## §3. Findings catalog

### Stage 1 — Usability/Reuse (Rachel 🕊️)

| ID | Class | Closure | Disposition |
|---|---|---|---|
| F-1 | Foundational | ✅ Q-T1 emission site re-pointed from `forceRenderForTesting()` to production-path `renderSenderSection()` with `#firstRenderEmitted` flag | Single-revision-turn close |
| P-1 | Polish | ✅ Q-T7 `handlers.telemetry` pinned to literal `"initialized"`; AC-7a-9 grep gate updated | Single-revision-turn close |
| P-2 | Polish | ✅ Step T5 INI config TBD resolved via `boot.ts:148-160` trace; `/api/multiplexer/config` Pydantic extension named with 2 fields | Single-revision-turn close |
| Reuse-hunt confirmations (×5) | Positive | ✅ Factory pattern, handshake convention, type extension, `AbortSignal.any`, User Timing/Long Tasks/OTel genuinely-new | No revision needed |

### Stage 2 — Risk/Anti-pattern (Krishna 🦚)

| ID | Class | Risk axis | Closure | Manager tier |
|---|---|---|---|---|
| R-1 | Inconsistency | Cardinality + PII | ✅ Q-T2 Long Task event schema enumerated `{duration, name, startTime}`; per-span 50-event cap; `longtask_overflow_count` overflow attribute; AC-7a-LT extended | T2 |
| R-2 | Polish (v2-defer) | Sampling | ✅ Q-T6 v2-defer note + OSQ-T-5 filed for ParentBasedSampler vs collector tail-based | T1 |
| **R-3** | **Foundational** | **PII** | ✅ **PATH A executed** — `crash` removed from ReportingObserver registered types; `['deprecation', 'intervention']` retained; OSQ-T-6 filed for v2 sanitizer-design | **T2 boundary, Path A pin** |
| R-4 | Polish (v2-defer) | Memory | ✅ Q-T1 mark accumulation v2-defer note + empirical 4-hour-session bound (~95 marks); OSQ-T-7 filed | T1 |
| R-5 | Inconsistency | Race/failure-cascade | ✅ Footer 2 sub-revised — Option A + 500ms `Promise.race` bounded timeout + safe defaults; handshake fires regardless; AC-7a-9 extended | T2 |
| R-6 | Polish | Bundle delta | ✅ AC-7a-10b updated with implementer-resolves-at-code-write + ~50KB suggested upper bound | T1 |
| R-7 | Inconsistency | Performance gate | ✅ AC-7a-8b rewritten with `p99 < 200ms` SLO assumption + warm-up smoke-ping + re-baseline policy; paired with R-5 → ~750ms worst-case | T1 |
| R-8 | Inconsistency | Documentation | ✅ Stage 2 = Risk/Anti-pattern (Krishna); Stage 3 = Ownership/Convention (Rio); Step 9 = Manager-Synthesis; feedback_pass2 self-audit row corrected | T1 |
| C-1 | Cosmetic | Tracking-doc hygiene | ✅ Recon-T-5 row removed; OSQ-T-1 retained as canonical bundle-delta tracking | T1 |

**Stage 2 cap-3 quibbles** (closed via tiny T1 cleanup, not cap-2 turn 2):
- Q-1 §Cluster T summary `'crash'` removal propagation
- Q-2 Self-audit row 6 `Recon-T-5 → OSQ-T-1` citation update
- Q-3 Self-audit row 9 `OSQ-T-1..T-4 → T-1..T-7` count update
- Q-4 §Next-steps §7 "Stage 4 → Stage 3 close + cap-lock" wording

### Stage 3 — Ownership/Convention (Rio ⚡)

| ID | Class | Closure |
|---|---|---|
| F-Rio-7a-1 | Inconsistency | ✅ §OSQ table populated with T-5/T-6/T-7 rows (caught 3rd silent Tiffany-rename-pass revert) |
| F-Rio-7a-2 | Withdrawn | Stale-state false positive (pre-re-apply read) — re-apply corrected before withdrawal |
| F-Rio-7a-3 | Cosmetic | ✅ Documented-not-revised — Files-EDITED CoSA row notes implementer-files-handoff-at-code-write per [[cross-project-handoff-doc]] |
| F-Rio-7a-4 | Inconsistency | ✅ §Scope row 7a-T3 `'crash'` removed; PII-safety framing surfaced at §Scope level |
| F-Rio-7a-5 | Inconsistency | ✅ §Cluster T Bundle delta row cites OSQ-T-1 (Recon-T-5 consolidated historical) |

### Findings totals

| Class | Stage 1 | Stage 2 | Stage 3 | Total |
|---|---|---|---|---|
| Foundational | 1 | 1 | 0 | **2** |
| Inconsistency | — | 4 | 3 | **7** |
| Polish | 2 | 3 | — | **5** |
| Cosmetic | — | 1 | 1 | **2** |
| Withdrawn | — | — | 1 | **1** |
| Doctrine-sweep quibbles | — | 4 | — | **4** (treated separately) |
| **Active findings closed** | **3** | **9** | **4** | **16** |

## §4. Manager-ratifications (4 footers in design doc)

### Footer 1 — P-2 CoSA scope (Tier 1)

**Location**: §Step T5 in design doc
**Pin**: P-2 CoSA config-plumbing extension lives within Phase 7a scope. Config plumbing (2 fields on existing `/api/multiplexer/config` Pydantic response model) ≠ server-side instrumentation per §Out-of-scope semantics. Implementer commits Lupin-side in working tree; CoSA-side router edit committed in CoSA-context session per [[lupin-only-never-cosa]].

### Footer 2 — Step T5 ordering Option A (Tier 2)

**Location**: §Step T5 in design doc
**Pin**: Option A (block-on-config-fetch) over Option B (non-blocking + replay). Rationale: +1 RTT acceptable on boot path already awaiting auth + multiplexer config; non-blocking + replay adds buffer/ordering defect surface for marginal ~50ms latency gain. Symmetric reversibility.

### Footer 2 sub-revision — Bounded timeout + safe defaults (Tier 2)

**Location**: §Step T5 in design doc (extension of Footer 2)
**Pin**: Option A structurally preserved + 500ms `Promise.race` bounded timeout + safe-defaults fallback (`endpoint=""` no-op exporter; `samplingRate=1.0`). Failure-mode cascade bounded at 500ms worst-case; pairs with R-7 SLO assumption for ~750ms worst-case boot inside 1500ms budget.

### Footer 3 — Q-T3 R-3 Path A (Tier 2 boundary)

**Location**: §Q-T3 in design doc
**Pin**: Path A (drop `crash` from registered ReportingObserver types) over Path B (sanitizer-based inclusion). Rationale: sanitizer false-negative risk too high (the absence of a token in stack traces is unverifiable; one missed pattern leaks indefinitely); exported telemetry to a collector cannot be remediated post-hoc; minimum-blast-radius wins. v2 OSQ-T-6 captures sanitizer-design follow-on.

### Closure-context references ruling (Manager-disposition)

**Mr Radio raised**: 6 `crash` + 4 `Recon-T-5` references survive in closure-context audit trail post-revisions.

**Manager ratification**: KEEP. The grep-sweep mandate is about surface-of-record violations (active claims contradicting canonical change), not historical scrubbing. Closure-context documents WHAT WAS CHANGED — essential for future readers tracing design evolution. Rio cap-3 verified all closure-context references read unambiguously.

## §5. v1.1 doctrine candidates surfaced this run

### Candidate #1 — Heartbeat-daemon kickoff codification

**Empirical basis**: Both Manager (Tiberius PID 504677) and Observer (María) launched independent daemons this run via `bash $LUPIN_ROOT/src/scripts/start-cascade-heartbeat.sh <persona>`. Per-session ownership pattern worked cleanly across the cascade lifecycle.

**Proposed fold target**: `plan-review-cascaded-common.md` §Heartbeat protocol.

**Codification text**:
> Each Manager and Observer launches own daemon via `bash $LUPIN_ROOT/src/scripts/start-cascade-heartbeat.sh <session_persona>`. Independent daemons per session; no shared daemon. Daemons exit cleanly on `cascade-complete` signal. User authorization implicit at cascade-start time.

### Candidate #2 — 4-tier clarification doctrine for autonomous-cascade decision points

**Empirical basis**: Demonstrated live across Stages 2+3 with Mr Radio's residual questions. T1 (tactical) + T2 (substantive reversible) resolved silently Manager-unilateral; no T3/T4 escalation needed.

**Proposed fold target**: New `plan-review-cascaded-common.md` §X clarification-needs tiering subsection.

**Codification text**:
> **T1 tactical/mechanical** (file paths, naming, code conventions): Manager-unilateral decision + document in design doc. Cascade rolls forward. Zero impact.
>
> **T2 substantive reversible** (Option A vs B both sound, INI key naming, sampling default): Manager-unilateral with documented rationale. Cascade rolls forward. Zero impact.
>
> **T3 substantive load-bearing** (architectural commitment hard to reverse, scope expansion candidate): Park as OSQ in design doc with PROPOSED stance + queue `ask_multiple_choice` with default-on-timeout = defer-to-v2 for user's morning. Cascade continues with PROPOSED stance.
>
> **T4 genuinely blocking** (does the slice exist? does the architecture make sense?): Halt that slice only + post to user wakeup queue via `priority=urgent` notify. One slice halts; non-overlapping slices continue.

### Candidate #3 — Heartbeat-tick-vs-peer-DM injection-density mitigation

**Empirical basis**: Stage 2 Manager-side 13-minute phantom lag at 02:33-02:46 UTC. Cascade-scheduler heartbeat ticks 11-14 obscured Krishna's Stage 2 peer-DM injection in Manager perceptual surface. María's observer probe at 02:43:47 cleared the phantom.

**New failure-mode class** (María §10.14 fold this morning identified 5 distinct modes; this is #6): **signal-density-obscures-needle**. Distinct from rate-limit, read-side truncation, turn-based-CC, write-side truncation, Anthropic rate-limit.

**Proposed mitigation surfaces** (3 options, can stack):
1. **Distinguishable system-reminder prefix** — system-layer change (cosa-voice MCP); different prefix/sub-type marker for heartbeat vs peer-DM
2. **Phantom-detection threshold tightening** — `plan-review-cascaded-common.md` §6.4 update (10 min → 5 min)
3. **Manager proactive `commons_read` every N ticks** — purely Manager-behavior doctrine; no system change; cheapest fix

**Recommended primary fix**: option 3 (Manager-behavior doctrine, no cross-repo coordination). Demonstrated effective in second half of run (Rio cap-3 + Stage 3 cap-2 surfaced cleanly via proactive reads).

### Candidate #4 — Author-side grep-sweep checklist (Krishna)

**Empirical basis**: Stage 2 cap-3 4 quibbles (Q-1 through Q-4) all same pattern: targeted edits applied per finding but doctrine-sweep didn't propagate into summary/audit tables. Krishna identified as Persona 2.A point 14 doctrine-sweep sub-pattern (Run-3 AC-table-doctrine-lag anchor).

**Mr Radio adopted into rolling self-review checklist mid-cascade**, then candidate #4 + #5 caught 3 silent linter reverts.

**Proposed fold target**: `plan-review-cascaded-common.md` §Author-side discipline OR Persona 2.A point 14 expansion. María + Manager to decide surface ownership.

**Codification text**:
> After applying per-finding revisions in cap-2 turn, grep-sweep summary/audit tables for any references to the original (now-changed) values. Trigger before marking ready for re-read.

### Candidate #5 — Multi-surface footer-ratification close protocol (Rio + Mr Radio refinement)

**Empirical basis**: Stage 3 3 inconsistencies (F-Rio-7a-1, F-4, F-5) all same anti-pattern as Stage 2 quibbles but more sophisticated — surface-of-record-vs-body lag when a footer ratification changes a multi-surface claim.

**6 in-doc instances within Phase 7a alone + Run 3 Section B precedent = 7 cross-cascade instances. Pattern is generalizing.**

**Empirical refinement (Mr Radio)**: Tiffany-rename-pass reverted 3 separate **non-adjacent** edit regions in one operation. The mitigation must include non-adjacent canonical surfaces, not just "the area I just touched."

**Proposed fold target**: §10.14 doctrine-sweep section.

**Codification text**:
> When a footer ratification changes a multi-surface claim (e.g., R-3 `crash` removal, R-8 role label, C-1 Recon→OSQ consolidation, v2-defer OSQ filings), close gate requires explicit sweep checklist run BY THE AUTHOR against ALL 6 canonical surfaces independently:
> 1. §Scope summary
> 2. §Cluster/Section summary tables
> 3. §OSQ table
> 4. §Self-audit table
> 5. §Next-steps
> 6. §Files-EDITED
>
> Each surface must be grep-verified independently — do not assume adjacency. Manager confirms sweep ran before Stage close.

## §6. §10.14 / §10.18 telemetry contributions

### Cycle-time metrics

| Stage | Review | Revision | Re-read | Total | Findings |
|---|---|---|---|---|---|
| Stage 1 (Rachel) | ~20 min | ~5 min | ~6 min | ~38 min | 3 active + 5 reuse |
| Stage 2 (Krishna) | ~25 min | ~3 min | ~5 min | ~33 min (+ 13 min Manager phantom-lag) | 9 active + 1 cosmetic + 4 quibbles |
| Stage 3 (Rio) | ~10 min + ~3 min correction | ~3 min | ~5 min | ~21 min | 3 active + 1 cosmetic + 1 withdrawn |

### Findings closure efficiency

- **Cap-2 author revision utilization**: 1/2 per stage uniformly — 50% headroom preserved
- **Single-revision-turn close rate**: 100% per stage (no cap-2 turn 2 needed)
- **Manager-unilateral resolution rate**: 100% — zero T3 escalations, zero T4 wake-ups, Rick stayed asleep

### Step 0 doctrine validation signals

Per Krishna's Stage 2 assessment: ✅ STRONG.
- Pre-cascade recon eliminated 6 browser-API archaeology items upstream
- OTel package selection alone would have spawned multi-turn Stage 1+2 cycle without recon
- Q→F→S→D recon shape empirically clean
- AC2e + AC-conditional-executability markers caught right things at draft time
- 21-memory self-audit table = actual instantiation of §6.1 standing-memories checklist

Per Rachel's Stage 1 assessment: ✅ STRONG.
- Recon's "Question → Finding → Source → Decision" shape works
- Worth deferring "Persona conventions sub-section" formalization to v2 (current cast seasoned)

Per Rio's Stage 3 assessment: ✅ STRONG.
- Author rides upstream recon verbatim
- Recon-T-1..T-4 stayed open for code-write-time resolution (correct doctrine fit)
- Step 0 doctrine wouldn't have caught Q-1-style summary staleness — different doctrine anchor

### Step 9 doctrine validation signals (this doc + Krishna's light-review)

⏳ Pending Krishna's light-review gate.

### New failure-mode #6 (signal-density-obscures-needle)

Captured for §10.14 cosa-voice failure-mode catalog (already had 5 modes; this is #6).

### Cumulative-learning-dividend signal

Run 4 Stage 3 surfaced 3 inconsistencies that are SAME-PATTERN-FAMILY as Run 3 Section B doctrine candidate #1. The pattern is generalizing across runs — strong evidence the cascade-learning-loop is a first-order workflow asset.

## §7. Implementation handoff

### Files NEW (Mr Radio enumerated in design doc §Files)

| Path | Purpose |
|---|---|
| `src/fastapi_app/static/js/multiplexer/observability/timing.ts` | User Timing + Long Tasks observer factories |
| `src/fastapi_app/static/js/multiplexer/observability/otel.ts` | OTel SDK init + exporter + tracer factory |
| `src/tests/unit/multiplexer/observability/timing.test.ts` | Unit tests for timing module |
| `src/tests/unit/multiplexer/observability/otel.test.ts` | Unit tests for otel module |
| `src/tests/smoke/test_multiplexer_phase7a_smoke.py` | Functional smoke + perf gate (8 cases per design doc §Step T7) |

### Files EDITED (Mr Radio enumerated in design doc §Files)

| Path | Edits |
|---|---|
| `src/fastapi_app/static/js/multiplexer/boot.ts` | `:148-160` config-fetch extension + `:155+` createOtelTracer wire + `:311 + :367-374` handshake registration |
| `src/fastapi_app/static/js/multiplexer/render/NotificationsListRenderer.ts` | `#firstRenderEmitted` flag + first-render mark emission in `renderSenderSection()` |
| `src/fastapi_app/static/js/multiplexer/stores/AudioStore.ts` | TTS-playback-start mark emission |
| `src/fastapi_app/static/js/multiplexer/transport/ws-channel.ts` | WS reconnect mark emission |
| `src/fastapi_app/static/js/multiplexer/auth/AuthManager.ts` | Auth-refresh mark emission |
| `src/fastapi_app/static/js/multiplexer/shared/types.ts` | `BootCompletePayload.handlers.telemetry?: "initialized"` field |
| `src/conf/lupin-app.ini` | `multiplexer otel collector endpoint` + `multiplexer otel sampling rate` keys |
| `src/conf/lupin-app-splainer.ini` | Splainer entries for above |
| `src/cosa/rest/routers/multiplexer.py` (or equivalent) | `/api/multiplexer/config` response model extends with `otel_collector_endpoint: str` + `otel_sampling_rate: float`. **Committed in CoSA-context session per [[lupin-only-never-cosa]].** |
| `package.json` | OTel SDK dependencies pinned at versions resolved in Recon-T-3 |

### Acceptance Criteria summary (14 ACs + sub-ACs)

Refer to design doc §Acceptance Criteria for full text. Convention 3 EXECUTOR tags on all ACs; Convention 4 TBD markers on AC-7a-8b + AC-7a-10b (both Conditional-on OSQ-T-1).

### OSQ inventory (7 OSQs)

| OSQ | Topic | Disposition |
|---|---|---|
| OSQ-T-1 | Bundle-delta literal | TBD at code-write per `npm install` + esbuild measurement; ~50KB suggested upper bound |
| OSQ-T-2 | `service.name` hardcode (`lupin-multiplexer`) | Accept hardcode v1; file follow-on if multi-tenant deployment lands |
| OSQ-T-3 | `trace_id` propagation to server | Defer — server-side OTel is its own initiative |
| OSQ-T-4 | WS message-level instrumentation | Skip v1; per-message IS the cardinality explosion concern; revisit if WS becomes diagnostic gap |
| OSQ-T-5 | Error-span preservation under reduced sampling | Defer v2 — `ParentBasedSampler` client-side vs collector tail-based |
| OSQ-T-6 | Crash-report ingestion via sanitizer module | Defer v2 with explicit false-negative test design |
| OSQ-T-7 | `performance.clearMarks()` policy | Defer v2 — clear-after-export hook once telemetry collector lands |

### TBD-at-code-write items

- **AC-7a-8b**: `/api/multiplexer/config` p99 < 200ms SLO assumption — verify in production telemetry post-deployment; re-baseline if exceeded
- **AC-7a-10b**: Bundle-delta literal — pin once `npm install` + esbuild measurement complete

### Cross-project handoff (CoSA)

**Implementer must file at code-write time per [[cross-project-handoff-doc]]**:
1. Handoff doc in CoSA repo summarizing the `/api/multiplexer/config` extension
2. Seed TODO entry in CoSA `TODO.md` pointing to the handoff doc

The Lupin-side edits and CoSA-side router edit must be committed in **separate sessions** (CoSA-context session for the router edit) per [[lupin-only-never-cosa]].

## §8. Open standing questions (7 OSQs)

See §7 OSQ inventory for full list. All 7 OSQs accepted-as-PROPOSED through 3 reviewer stages. None block Phase 7a implementation.

## §9. Cross-component shared-state interaction matrix

**N/A for Phase 7a** — single-cluster (Cluster T Telemetry). No cross-section watch-pairs because Phase 7a is a self-contained observability layer addition.

**Note for future cascades**: when a cascade has cross-section dependencies (e.g., Run 3 Section B's persona-focus recorder cross-renderer state), the synthesis pass must include an explicit cross-component shared-state matrix per Step 9 doctrine §6.7. Krishna's Step 9 light-review criterion 6 covers this when applicable.

## §10. Step 9 light-review readiness

**Reviewer**: Krishna 🦚 (accepted per cascade common.md §Step 9 reviewer selection: fresh-cascade-context ✅; Persona 4 lens maps to "is this design cascade-ready" ✅; non-Manager ✅).

**Rubric**: 5-criterion focused pass (criterion 6 cross-component shared-state interaction N/A for Phase 7a single-cluster) + Manager-self-administered cold-context test.

**Cap**: 1 revision turn on the gate.

### Manager-self-administered cold-context test

**Test**: If a cold reader picked up `15-phase7a-telemetry-design.md` + this synthesis doc with no other context from this conversation, could they execute Phase 7a implementation?

**Verdict (Manager self-assessment)**: ✅ PASS.
- Design doc has explicit Step T1-T7 execution sequence
- 14 ACs with EXECUTOR tags
- 7 OSQs with PROPOSED stances + dispositions
- 5 NEW files + 9 EDITED files enumerated
- Manager footers document non-obvious decisions with rationale
- This synthesis doc captures cascade execution + doctrine context for future-reader continuity
- TBD-at-code-write items both cite their conditional dependency (OSQ-T-1)
- Cross-project handoff explicitly named for CoSA

**Possible cold-context friction points** (Krishna to verify):
- Telemetry init ordering under bounded-timeout + safe-defaults — Step T5 + Footer 2 sub-revise both describe this, but reader must hold both in mind
- `BootCompletePayload.handlers.telemetry === "initialized"` literal semantic — pinned in Q-T7 + AC-7a-9 grep gate, but reader must understand semantic carve-out vs renderer `"mounted"`
- Long Task event attribute schema enumeration — Q-T2 explicit but reader must understand WHY `attribution[*]` excluded (PII)

### Pending Krishna's verdict

Dispatch follows this doc's commit.

---

**Signed**: Tiberius 🌑 — Run 4 Manager, Phase 7a cascade synthesis pass.
**Date**: 2026-05-20
**Status**: 🟢 PHASE 7A CASCADE-COMPLETE pending Step 9 light-review.
