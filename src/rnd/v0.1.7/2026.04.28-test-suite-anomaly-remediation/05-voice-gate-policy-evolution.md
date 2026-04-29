# 05 — Voice-gate Policy Evolution: Forward-compat Breadcrumbs

**Status**: Forward-compat design notes only — NO IMPLEMENTATION YET.
**Created**: 2026-04-28 (post WG-9, post `c4e5d4f`)
**Trigger**: WG-9 shipped a TFE-only voice-gate timeout policy (`stall|top_1|top_n|none`) using a confidence-sort heuristic. UPE's online-learning roadmap is ~2 dev branches out. This doc anchors what `voice gate timeout policy = delegate` will mean when UPE is ready, so today's WG-9 code stays forward-compatible without committing us to design choices.

## Summary

Today's WG-9 implementation is **TFE-specific** and uses **generator-supplied confidence** for sorting. That's fine as a first cut — the 22:35 incident exposed exactly the failure mode that `top_1` would have prevented. But the same problem exists for every blocking voice gate (BFE, Deep Research, Podcast, Presentation), and the eventual right answer is **delegate to UPE** with online-learned operator priors, not confidence-sort.

This doc captures what we'll need when we get there, plus the small WG-9-era hooks we're leaving in `c4e5d4f`'s successor commit so the future migration is mechanical, not a rewrite.

## The bigger problem TFE is a special case of

Every blocking voice gate has the same operator-away failure mode:

| Agent | Gate | Discard cost on timeout |
|-------|------|------------------------|
| TFE | "Pick fixes from N proposals" | All proposals lost |
| BFE | "Apply this fix?" | Single fix lost |
| Deep Research | "Clarify topic boundaries" | Run aborts mid-research |
| Podcast / Presentation | "Pick voice / template / language" | Generation stalls |

WG-9 currently lives only on TFE. The next stall (BFE, Deep Research, Podcast) will need the same shape.

## Layered policy architecture (target)

A four-layer fallback chain — each layer has an INI knob, each layer is independent:

```ini
# ─────────────────────────────────────────────────────────────────────────
# Layer 0 — System-wide voice-gate default. Applies to any agent that
# doesn't override at Layer 1. NEW section in lupin-app.ini under
# [Lupin: Baseline].
# ─────────────────────────────────────────────────────────────────────────
voice gate timeout policy default        = stall          # legacy default
voice gate timeout policy when away      = delegate       # operator-away override
voice gate min delegate confidence       = 0.75           # abstention threshold
voice gate delegate to                   = upe            # who decides
voice gate fallback policy               = stall          # if delegate also abstains

# ─────────────────────────────────────────────────────────────────────────
# Layer 1 — Per-agent override. Each agent inherits Layer 0 unless
# explicitly set. The keyword `inherit` resolves to Layer 0 at runtime.
# ─────────────────────────────────────────────────────────────────────────
test fix expediter voice gate timeout policy            = inherit
test fix expediter voice gate auto ratify top n         = 1
test fix expediter voice gate min delegate confidence   = inherit

bug fix expediter voice gate timeout policy             = inherit
bug fix expediter voice gate auto ratify top n          = 1

deep research voice gate timeout policy                 = inherit
podcast voice gate timeout policy                       = inherit
presentation voice gate timeout policy                  = inherit
```

**Backward-compat with WG-9**: today's `test fix expediter voice gate timeout policy = stall` keeps working — it's still a valid Layer 1 explicit override. The only new vocabulary is `inherit` (looks up Layer 0) and `delegate` (calls UPE).

## Where UPE plugs in — the `delegate` mode

When an agent's resolved policy is `delegate`, the orchestrator calls UPE with a structured request and falls through to the configured fallback if UPE abstains.

### Delegate request contract (proposed)

```python
{
    "agent_type"          : "test_fix_expediter",
    "gate_type"           : "multiple_choice_proposals",  # or "yes_no", "open_ended", etc.
    "context"             : {
        "proposals"        : [...],     # full proposal list w/ metadata
        "cluster_summary"  : {...},     # cluster info from Phase 0
        "prior_diagnoses"  : {...},     # diagnose-phase output
    },
    "operator_user_id"    : "...",
    "min_confidence"      : 0.75,
    "request_id"          : "tfe-d9786eea-gate-1",  # for feedback tracking
}
```

### Delegate response contract (proposed)

```python
{
    "answer"              : { "selected": [proposal_id_1, proposal_id_3] },  # or None
    "confidence"          : 0.82,
    "abstained"           : false,
    "reasoning"           : "Operator picked similar 'add pytest.skip guard' proposals 7/8 times in last 30d",
    "training_signal_id"  : "ts-xyz",  # so the agent can post operator approval back
}
```

If `abstained=true` OR `confidence < min_confidence`, the agent falls through to `voice gate fallback policy` (default `stall`).

## Online-learning feedback loop

UPE only "learns" if feedback flows back. Two signals per delegate call:

| Signal | Source | When it fires | Strength |
|--------|--------|---------------|----------|
| **Direct correction** | Operator answers the voice gate manually before timeout | Fires unconditionally — "ground truth" of what operator wanted in that exact context | Strong |
| **Post-hoc approval** | After UPE-delegate auto-applies a fix, operator reviews PR and either merges (positive) or reverts (negative) | Fires after the fact — covers cases where UPE ran without operator input | Weaker, but covers most of the data |

Both must flow back to UPE keyed by `training_signal_id`. **Architectural implication**: training signals are *generated at delegate time* but *resolved later*. The agent must persist the signal id alongside the fix it applied so the post-hoc resolver can correlate.

## "Operator away" detection

Today: "away" is implicit in `feedback_timeout_seconds = 300` (5 min of silence). That's coarse — operator might be in the bathroom.

Better signals (already in the system, just need plumbing):

| Signal | Source | Cost to wire |
|--------|--------|--------------|
| Last keystroke from operator's terminal session | Claude Code SessionStart/Stop hooks | Existing infra; just plumb timestamp |
| Last UI interaction (WebSocket message from notification panel) | `websocket_manager` | Existing infra |
| Conversation-mode flag (session aabece5e work) | `~/.claude/sessions/cc-{PPID}.json` bridge | Existing |
| Calendar busy-state | Google Calendar MCP | Already wired (`mcp__claude_ai_Google_Calendar__*`) |

If we can detect "away" directly, we don't have to wait 5 min — we can fire `voice gate timeout policy when away` immediately. That's a UX win on top of the policy structure.

## What's in WG-9 today (the breadcrumb hooks)

To keep this future tractable, WG-9 leaves three hooks:

1. **Splainer comment** in `lupin-app-splainer.ini` for `test fix expediter voice gate timeout policy` notes that `delegate` is reserved for the UPE integration. One line, no behavior change.

2. **Stub method** `_delegate_to_predictor()` in `orchestrator.py` raises `NotImplementedError` for now. When UPE-online-learning is ready, the only code change is that method's body. Adds ~15 lines.

3. **This doc** — captures the architectural intent so we're not re-deriving it 3 months from now when UPE lands.

These three are intentionally **breadcrumb-grade**: zero new INI keys, zero new behavior. We're not pre-shaping infrastructure for an architecture we haven't validated yet.

## What we should NOT do today

- **Do NOT add Layer 0 system-wide keys yet.** The cost of premature abstraction across 5 agents is high; the cost of leaving TFE-specific keys is low. We can lift them when BFE / Deep Research stalls actually bite us.
- **Do NOT add `inherit` resolution logic.** It's two lines of code, but adding it without something to inherit from creates a fake-flexibility surface.
- **Do NOT pre-build the UPE delegate request/response contract.** It's premature — UPE's online-learning shape isn't locked yet.
- **Do NOT generalize the per-agent INI keys to BFE / Deep Research / Podcast.** Each agent will get a similar policy when its own stall incident actually happens.

## Migration order (when UPE is ready)

| Step | Change | Risk |
|------|--------|------|
| 1 | Add Layer 0 keys to `lupin-app.ini` + splainer | Cosmetic |
| 2 | Add `inherit` resolution helper at config-read time | Trivial |
| 3 | Implement `_delegate_to_predictor()` body in TFE orchestrator | Real risk — first agent on the new path |
| 4 | Validate with one TFE run + observe operator-feedback collection | Real risk |
| 5 | Migrate BFE: add `bug fix expediter voice gate timeout policy = inherit` | Trivial after step 3 |
| 6 | Migrate Deep Research / Podcast / Presentation similarly | Trivial |
| 7 | Add operator-away signal plumbing (skip 5-min wait when present) | Independent of policy work — could ship anytime |

Steps 1-2 are scaffolding (zero risk). Step 3 is the actual UPE integration. Steps 4-6 generalize. Step 7 is the cherry on top.

## References

- `02-wg-9-tfe-voice-gate-fallback.md` — the WG-9 design + acceptance
- `c4e5d4f` — WG-9 implementation (TFE-specific, confidence-sort)
- Future UPE online-learning design doc — TBD when that work picks up

## Owner

Claude session `ba7138c4` 2026-04-28 drafted this. Whoever picks up the UPE-delegate work owns it from then.
