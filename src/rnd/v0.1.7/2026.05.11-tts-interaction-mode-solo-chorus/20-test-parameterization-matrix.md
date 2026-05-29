# Test Parameterization Matrix — Solo & Chorus

**Date**: 2026.05.12
**Status**: 📝 Plan reference — to be expanded with concrete test names as each phase lands
**Owner**: [LUPIN]
**Companion docs**: [`00-index.md`](00-index.md), all per-phase design docs (`10`–`17`)

---

## 1. Purpose

The May 12 plan mandates that **every test parameterizes over `tts interaction mode = solo | chorus` unless mode-independent by construction.** This doc enumerates the test surfaces and which tests need parameterization, so we don't ship implementation without symmetric coverage.

**Hard rule**: at end of Phases 1–7, every behavior-affecting test runs once per mode. Tests that are mode-independent by construction (e.g., `get_tts_interaction_mode()` itself, `sanitize_for_wrap`) need no parameterization.

---

## 2. Mode-independence audit per phase

| Phase | Test category | Mode-dependent? | Notes |
|---|---|---|---|
| 1 (INI) | `test_tts_interaction_mode_helper` | No | Tests the helper itself; mode IS the parameter |
| 2 (bridge) | `test_session_bridge_speakerphone` | **Yes** for defaults; No for round-trip | New-bridge defaults differ per mode (solo=false, chorus=true) |
| 3 (router) | `test_speakerphone_router` | **Yes** for activate path | Solo: displaces; chorus: doesn't. Deactivate path is mode-independent. |
| 4 (MCP) | `test_notify_impl_mode_conditional` | **Yes** for cross-talk cue | Cue fires in solo; not in chorus |
| 4 (MCP) | `test_get_session_info` | Partial | Field shape mode-independent; `tts_interaction_mode` value differs |
| 5 (hooks) | `test_speakerphone_rider` | **Yes** for rider content | 4-variant matrix |
| 6 (CLAUDE.md/skills) | Static checks | No | File ops, no runtime |
| 7 (UI) | `SpeakerphoneToggle`, `SenderCard`, etc. | **Yes** for affordance rendering | Solo: pin + glow; chorus: neither |

---

## 3. Parameterization patterns

### Python (pytest)

```python
import pytest
from unittest.mock import patch

@pytest.mark.parametrize( "mode", [ "solo", "chorus" ] )
def test_activate_path_mode_aware( mode, mock_bridge ):
    with patch( "cosa.utils.util.get_tts_interaction_mode", return_value=mode ):
        result = activate_speakerphone( sid="A" )
        if mode == "solo":
            assert result["displaced_sessions"] == []  # No others to displace in this fixture
            # Lock was acquired
        else:  # chorus
            assert result["displaced_sessions"] == []  # Always empty
            # No Lock attempted
```

### TypeScript (Jest / Vitest)

```typescript
describe.each( [ [ "solo" ], [ "chorus" ] ] )( "SpeakerphoneToggle in %s mode", ( mode ) => {
    it( "renders the correct icon", () => {
        // ...
    } );
} );
```

---

## 4. Mode-affecting test inventory (target counts)

Filled in as phases land. Initial estimates:

| Phase | Mode-parameterized tests | Mode-independent tests | Total new tests |
|---|---|---|---|
| 1 | 0 | 7 | 7 |
| 2 | 4 | 7 | 11 |
| 3 | 8 | 3 | 11 |
| 4 | 8 | 5 | 13 |
| 5 | 8 | 5 | 13 |
| 6 | 0 (static) | 0 (manual) | 0 |
| 7 | ~20 (UI components × 2 modes) | ~10 | ~30 |
| **Total** | **~48** | **~37** | **~85** |

Plus regression assertions on the existing three-layer enforcement test suite, which today is mode-independent but must still pass after the rename.

---

## 5. Live verification matrix (manual `:7999`)

After Phases 1–7 land, the following live-flip exercises verify both modes work end-to-end:

| Scenario | Mode | Setup | Expected |
|---|---|---|---|
| **Solo regression — single session** | solo | Default config | Session A activates speakerphone → bridge=true, pin appears, green glow, bell→phone toggle |
| **Solo regression — displacement** | solo | A active | B activates → A's bridge=false, A's pin removed, B's pin appears, A's listener gets `disable_speakerphone` action |
| **Chorus simultaneous** | chorus (INI flip + server restart) | Two CC sessions | Both activate independently → both have `speakerphone_on=true`, neither has pin, both have phone↔speaker toggle |
| **Mode round-trip** | both | Toggle INI from solo→chorus→solo | Behavior matches expected per mode in each state |
| **Cross-talk leak cue (solo)** | solo | A is the holder, B's Claude has stale `speakerphone_on=true` belief and calls `notify(suppress_ding=True)` | User hears a ding (cue fired); audible signal that B leaked |
| **No cue (chorus)** | chorus | Same as above | User does NOT hear inverted ding (chorus doesn't cue; quiet notify is legitimate) |
| **Rider content — solo + speakerphone-on** | solo | Inject voice msg to A | A's rider has monopoly notice; brevity rules; routing reminder |
| **Rider content — chorus + speakerphone-on** | chorus | Inject voice msg to A; B also speakerphone-on | A's rider has multi-voice notice; NO monopoly notice |
| **`/clear` persistence (both modes)** | both | Toggle speakerphone, `/clear`, send a prompt | State preserved (solo: bridge=true persists; chorus: bridge=true persists) |
| **CLAUDE.md sweep** | n/a | After Phase 6 | `grep conversation_mode ~/.claude/CLAUDE.md` returns zero hits |
| **Skill sweep** | n/a | After Phase 6 | `ls ~/.claude/skills/conversation-mode-*` returns nothing |

---

## 6. Coverage gates

| Surface | Tool | Gate |
|---|---|---|
| Python unit tests | pytest | All pass; mode parameterization explicit per §4 |
| Python smoke tests | inline `quick_smoke_test()` | All pass on `:7999` |
| Python integration tests | `:8000` schedule via `/api/test-suite/submit` | After Phases 1–7 PR lands |
| TypeScript multiplexer | c8 | **`--100` hard gate** per [[feedback_100pct_coverage_multiplexer]] |
| WebSocket smoke | `run-websocket-smoke-tests.sh` | All pass; rename to `speakerphone_changed` event |
| E2E UI (Playwright) | `:8000` scheduled | After core PR lands; full sweep over both modes |
| Visual regression | Playwright snapshots | Snapshot baselines updated for both modes |

---

## 7. Pre-merge checklist (per [[feedback_e2e_two_phase_gate]])

**Phase A — Code-writing (Phases 1–7 PR)**:

- [ ] All unit tests pass in both modes.
- [ ] All smoke tests pass.
- [ ] WebSocket smoke tests pass.
- [ ] Multiplexer c8 coverage at `--100`.
- [ ] Sweep audit: zero `conversation_mode` / `enter_conversation_mode` / `exit_conversation_mode` hits across parent + nested repos.
- [ ] Memory and docs updated per the touchpoints table in each phase doc.

**Phase B — Live verification gate**:

- [ ] User confirms `:8000` slot availability.
- [ ] Integration tests scheduled via `/api/test-suite/submit` with non-overlapping `scheduled_at`.
- [ ] E2E UI tests scheduled separately.
- [ ] Both schedules confirmed clean by user.

**Phase C — Merge**:

- [ ] All scheduled tests pass.
- [ ] No regressions in baseline test counts.
- [ ] Decisions log updated with final landing date + commit hash.
- [ ] Open questions either resolved (move to decisions log) or explicitly deferred (status updated).
