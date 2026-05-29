# TTS Interaction Mode — Open Questions

**Status**: Open. Decisions parked for future resolution.
**Companion**: [`00-index.md`](00-index.md), [`90-decisions-log.md`](90-decisions-log.md), [`2026.05.12-tts-interaction-mode-solo-chorus.md`](2026.05.12-tts-interaction-mode-solo-chorus.md)

**How to use this doc**: Append new questions at the bottom with the next `Q<N>` number. When a question is resolved, **don't delete** the entry — leave a one-line tombstone pointing to the relevant `90-decisions-log.md` entry, and update the Status field. This preserves the audit trail of what was considered.

---

## Q1 — Chorus-mode green-pin reservation

**Question**: Today the persona color pool excludes green because green-on-success is reserved for the conversation-mode mic-monopoly pin (per [[feedback_no_green_in_persona_pool]]). Under chorus mode, there is no monopoly to signal. What should green become in chorus?

**Options** (from May 12 plan):

| Option | Meaning | Tradeoff |
|---|---|---|
| (a) Green = speaker-on | Most cards green (default state in chorus) | Default-green dilution; signal weak |
| (b) Green = phone-mode | Phone-mode card highlighted as the deliberate exception | Inverts intuition (green ≠ "on") |
| (c) Drop green reservation in chorus; toggle uses icon shape only | Phone glyph vs speaker glyph; color free for personas | Frees the color pool; cleanest |

**May 12 plan recommends**: (c), but defers the decision.

**Owner**: Rick.

**Decision criteria**: Gate this on whether chorus mode lands. Solo-mode reservation is untouched regardless.

**Status**: Deferred to Phase 8.

---

## Q2 — Persona color pool expansion under chorus

**Question**: If Q1 resolves to (c), the green slot opens up in chorus mode. Should we expand the persona color pool to include green-spectrum colors, refresh existing personas, or leave the slot dormant?

**Owner**: Rick.

**Decision criteria**: Depends on Q1 outcome plus the long-term sizing of the persona pool.

**Status**: Open. Cannot be resolved before Q1.

---

## Q3 — Future small-group semantics (duet / trio / quartet)

**Question**: The `solo | chorus` value pair leaves room for `duet`, `trio`, `quartet` as future values. Should any of these be specified now, or wait until a concrete use-case surfaces?

**Considerations**:
- Specifying now risks designing in the dark — what would "duet" even mean? Pair-routing? Two-mic shared session? Lead/echo?
- Waiting risks the chorus rider/UI baking in `chorus = unlimited N` semantics that don't generalize cleanly to bounded-N modes.
- **Compromise**: Add a single `Future expansion` note to the May 12 plan stating chorus is "currently unbounded N; bounded-N modes (duet/trio/quartet) are reserved for future definition." No design work now; just don't bake in N-bound assumptions.

**Owner**: Rick.

**Status**: Open. Plan does not currently bake in N-bound assumptions, so deferral is low-risk.

---

## Q4 — Other behaviors coupled to TTS interaction mode ✅ Resolved 2026-05-12

**Resolution**: Audit complete — see [`04-mode-coupling-audit.md`](04-mode-coupling-audit.md).

**Headline finding**: All implementation-affecting couplings are already covered by Phases 1–7 design docs OR are explicitly out-of-scope per the May 12 plan. **Phase 1 can proceed.**

**One new finding folded into Phase 4 design doc**: the MCP `instructions=` block (`cosa_voice_mcp.py:598-603`) and the `enable_speakerphone` tool docstring (line 1436 area) have hard-coded mutual-exclusion language that needs to become mode-aware. Trivial text-only update, ~20 lines across two locations. Added to Phase 4 scope; not a new phase.

**Confirmed mode-independent** (just need the rename Phase 5 already covers):
- Stop hook auto-narrate + idle-prompt skip (`stop.py:671`, `idle_waiter.py:251`).
- TTS queue at the listener's ear (single global FIFO, handles chorus N voices).
- `set_session_topic` "Continue Session?" notification.
- Bridge `voice_persona` field + `last_autonarrated_turn_id` (clear-preserve, mode-independent).
- Persona pool sizing (6 personas + deterministic borrow fallback handles N > 6 gracefully).

**Confirmed out-of-scope** (per May 12 plan):
- Inbound mic-routing semantics (who hears voice input in chorus). Parked as separate axis.
- Persona pool expansion under chorus (covered by deterministic borrow; INI pool can grow if needed later).
- MCP HTTP-fallback mutex bypass (existing Risk #7 from three-layer enforcement; affects solo only).

**Confirmed unrelated** (false positive in grep):
- CJ Flow `monopolize: bool` field on agentic job routers — orthogonal concept (job-scheduling on `:8000` test server), not TTS interaction mode.

For the full audit trail, raw grep results, and per-coupling cross-references, read [`04-mode-coupling-audit.md`](04-mode-coupling-audit.md).

---

## Q5 — Solo retirement

**Question**: Under what conditions, if any, should solo mode be retired?

**Plan's current position**: **NEVER.** Both modes are permanent per [[feedback_feature_flag_preserves_old_path]]. Rick explicitly accepted the forever-maintenance cost in exchange for reversibility.

**Why this is parked here despite being "decided"**: future readers will ask this question. Document the answer once so they don't have to re-derive it.

**Status**: Decided (no retirement planned). Logged here for visibility, with cross-link to [`90-decisions-log.md`](90-decisions-log.md#2026-05-11--mid-serialization-addendum-preserve-monopoly-plumbing).

---

## Q6 — Predecessor doc integration treatment

**Question**: The two predecessor docs (`../2026.04.27-conversation-mode-design.md` and `../2026.04.30-conv-mode-three-layer-enforcement/`) describe today's behavior. Should they be:

- (a) Left untouched, with the new subdir's `02-background-synthesis.md` distilling their relevant bits.
- (b) Updated with "Superseded by" pointers to this subdir.
- (c) Moved into this subdir alongside the new docs.

**Recommendation**: (a). The predecessors describe today's behavior, which solo mode preserves exactly. They are **not superseded** — they describe the still-current solo branch. The synthesis doc bridges them to the new plan without disturbing them.

**Owner**: Rick.

**Status**: Open. Pending Rick's call after he reads the May 12 plan and the synthesis doc.

---

## Q7 — Plan file in `~/.claude/plans/` — what happens to it?

**Question**: The original plan file lives at `~/.claude/plans/polished-tickling-sunbeam.md`. The May 11 doc references it as "Plan file (live)". Now that the design has evolved and lives in R&D docs, what's the status of that plan file?

**Options**:

- (a) Leave it alone — it's historical, the R&D docs are authoritative.
- (b) Update it with a pointer to this subdir.
- (c) Delete it (the design is now in R&D docs, the plan-mode artifact is redundant).

**Recommendation**: (b). Plans in `~/.claude/plans/` are auto-generated by Claude Code's plan-mode; leaving stale plan files can mislead future sessions that grep for "speakerphone" or "conversation mode." A one-line pointer is cheapest.

**Owner**: Rick.

**Status**: Open. Cosmetic; doesn't block implementation work.

---

## Q8 — Migration of in-flight conversation-mode skills

**Question**: Existing skills `conversation-mode-on`, `conversation-mode-off`, `conversation-mode-guardrails` are scheduled for retire/rename in the May 12 plan (Phase 6). But these skills may be referenced by other auto-memory entries, by user habit (slash command invocation), or by other workflows we haven't enumerated.

**Audit needed**:
- Grep `~/.claude/` for references to the old skill names.
- Grep auto-memory directory for references.
- Check CLAUDE.md files in any project.

**Owner**: Claude (mechanical sweep).

**Status**: Open. Resolve as part of Phase 6 prep.
