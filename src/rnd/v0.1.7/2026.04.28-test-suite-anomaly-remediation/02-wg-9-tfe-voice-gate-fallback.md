# WG-9 — TFE voice-gate auto-fallback policy

## Root cause

`TestFixExpediter.orchestrator` (`src/cosa/agents/test_fix_expediter/orchestrator.py:1061-1073`) fires `ask_multiple_choice(multiSelect=True, timeout=feedback_timeout_seconds)` (default 300s). On timeout it raises `VoiceGateTimeoutError` → `StalledException` → job goes to `STALLED` state with the 23 already-generated proposals discarded.

Only `dry_run=True` mode skips the gate (auto-selects all). There is no production fallback for "user didn't answer in 5 minutes" — which is exactly what happened with the 22:35 run that scheduled itself after-hours.

## Approach

Add an explicit voice-gate-timeout policy with four modes:

| Mode | Behavior on timeout |
|------|---------------------|
| `stall` | (default, current) Stall with `voice_gate_timeout` reason — no behavior change. |
| `top_1` | Auto-select highest-confidence proposal, proceed to repair. |
| `top_n` | Auto-select top N proposals (N from sibling INI key). |
| `none` | Auto-select nothing, exit cleanly with `no_fixes_selected` instead of stalling. |

## Steps

1. INI keys in `src/conf/lupin-app.ini` `[Lupin: Baseline]`:
   ```
   test fix expediter voice gate timeout policy = stall
   test fix expediter voice gate auto ratify top n = 1
   ```
2. Splainer entries in `lupin-app-splainer.ini`.
3. Config plumbing in `src/cosa/agents/test_fix_expediter/config.py` — read both keys.
4. Orchestrator branch in `orchestrator.py:1061-1073`:
   ```python
   try:
       result = await cosa_interface.present_choices( ... )
   except VoiceGateTimeoutError:
       policy = self.config.voice_gate_timeout_policy
       if policy == "stall":
           raise
       elif policy == "top_1":
           selected = self._top_n_proposals( proposals, 1 )
       elif policy == "top_n":
           selected = self._top_n_proposals( proposals, self.config.voice_gate_auto_ratify_top_n )
       elif policy == "none":
           selected = []
       # log + continue with `selected`
   ```
5. Unit test `src/tests/unit/test_tfe_voice_gate_fallback.py` covering all four modes.

## Acceptance

- All four modes verified by unit test.
- Default behavior (`stall`) unchanged from current production.
- After-hours runs can be configured to `top_1` to make autonomous progress.

## Files

- `src/cosa/agents/test_fix_expediter/orchestrator.py` (~30 lines)
- `src/cosa/agents/test_fix_expediter/config.py` (~10 lines)
- `src/conf/lupin-app.ini` + `splainer.ini` (2 INI keys + splainer)
- `src/tests/unit/test_tfe_voice_gate_fallback.py` (NEW)

## Status

- [ ] INI keys + splainer
- [ ] Config plumbing
- [ ] Orchestrator branch
- [ ] Unit test (4 modes)
- [ ] py_compile
