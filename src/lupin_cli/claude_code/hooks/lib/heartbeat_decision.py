#!/usr/bin/env python3
"""
Heartbeat Hook — pure decision composition (`decide_heartbeat`).

Implements the §0 5-step `Stop`-hook decision logic as a PURE function over
already-fetched leaf state. Composes the three leaf modules:
    - heartbeat_hold      → is_honored, declared_work_owed   (over the hold dict)
    - heartbeat_work_owed → build_poke_reason                (over the verdict)
    - heartbeat_poke_cap  → the poke_count / cap VALUES are passed in

**Why this module exists (María, 2026-06-04):** push ALL decision logic into
pure, exhaustively-tested modules so the Rachel-gated `stop.py` Branch-C
surface shrinks to a *thin adapter*: read session_id → fetch live TODO/commons
state + hold file + poke_count → call `decide_heartbeat` → act on the result.
This module touches NOTHING in `stop.py`.

§0 decision logic (local):
    1. (caller reads the hold file)
    2. Hold present + fresh + reason non-empty → HONOR → {"continue": true}.
    3. Else determine work-owed (hold's declared work_owed first, else the
       oracle verdict). None owed → {"continue": true} (genuinely done).
    4. Work owed + poke_count < cap → {"decision":"block","reason": …}; the
       caller then INCREMENTS the counter.
    5. poke_count >= cap → {"continue": true}; the caller fires a "max
       auto-nudges reached" notify().

**Purity contract:** this function performs NO I/O and NO side effects. The
counter increment (step 4) and the cap notify (step 5) are SIDE EFFECTS owned
by the adapter — `decide_heartbeat` only *signals* them via `should_increment`
/ `should_notify_cap` so the adapter stays trivial and this core stays pure.

**`reason` channel:** the poke rides the top-level Stop-hook `reason` field —
NEVER `systemMessage` (CC silently ignores it; see 01-…-seam-analysis §ERRATA).

Design authority (LOCKED): planning-is-prompting →
    src/rnd/2026.06.02-stop-hook-natural-heartbeat-poker.md §0.
"""
from lupin_cli.claude_code.hooks.lib.heartbeat_hold import is_honored, declared_work_owed
from lupin_cli.claude_code.hooks.lib.heartbeat_work_owed import build_poke_reason


# Outcome vocabulary (the adapter routes side effects off this)
OUTCOME_HONORED     = "honored"       # fresh declared hold → don't poke
OUTCOME_NOT_OWED    = "not_owed"      # nothing owed → genuinely done
OUTCOME_POKE        = "poke"          # owed + under cap → self-poke
OUTCOME_CAP_REACHED = "cap_reached"   # owed + at/over cap → stop nudging

# Reason used when work is owed via the hold's self-declared work_owed=True
# but the oracle verdict has no specifics to quote.
DECLARED_OWED_REASON = (
    "Do not stop yet — you stopped with work owed and no fresh hold. "
    "Pick one and act before you stop:\n"
    "1. Owe work? Resume and finish it now.\n"
    '2. Blocked on someone? DM them for status ("where are we on X?"), then declare a fresh hold — '
    "write .heartbeat-hold-<session_id>.json with a reason and awaiting: peer:<name>.\n"
    "3. Truly nothing to do? Declare it — write a hold with work_owed: false."
)


def _result( outcome, hook_output, should_increment=False, should_notify_cap=False ):
    """
    Build the structured decision result.

    Ensures:
        - Returns a dict with:
            outcome           : one of the OUTCOME_* constants
            hook_output       : the EXACT dict the adapter should emit to CC
                                ({"continue": True} or {"decision":"block","reason":…})
            should_increment  : True only for a poke (adapter bumps the counter)
            should_notify_cap : True only at cap (adapter fires the notify)
    """
    return {
        "outcome"           : outcome,
        "hook_output"       : hook_output,
        "should_increment"  : should_increment,
        "should_notify_cap" : should_notify_cap,
    }


def decide_heartbeat( hold, oracle_verdict, poke_count, cap, now=None ):
    """
    Pure §0 decision over fetched leaf state.

    Requires:
        - hold is the hold dict (heartbeat_hold.read_hold) or None
        - oracle_verdict is the heartbeat_work_owed.evaluate_work_owed dict
          or None
        - poke_count is the current heartbeat poke count (int >= 0)
        - cap is the per-session poke cap (int > 0)
        - now is an aware datetime or None (forwarded to freshness check)

    Ensures:
        - Returns the _result(...) structure; NO I/O, NO side effects
        - Honored fresh hold        → OUTCOME_HONORED,    {"continue": True}
        - Hold self-declares done   → OUTCOME_NOT_OWED,   {"continue": True}
        - Nothing owed (no hold + oracle empty) → OUTCOME_NOT_OWED
        - Owed + poke_count >= cap  → OUTCOME_CAP_REACHED, {"continue": True},
                                      should_notify_cap=True
        - Owed + poke_count <  cap  → OUTCOME_POKE,
                                      {"decision":"block","reason": …},
                                      should_increment=True
        - The poke reason quotes the oracle specifics when work is oracle-owed,
          else uses DECLARED_OWED_REASON (self-declared via the hold)
    """
    # Step 2 — honored declared hold defends its quiescence → never poke
    if is_honored( hold, now=now ):
        return _result( OUTCOME_HONORED, { "continue": True } )

    # Step 3 — work-owed: the hold's self-declared work_owed wins; else oracle
    declared = declared_work_owed( hold )
    if declared is False:
        return _result( OUTCOME_NOT_OWED, { "continue": True } )

    oracle_owed = bool( oracle_verdict and oracle_verdict.get( "work_owed" ) )
    owed        = True if declared is True else oracle_owed
    if not owed:
        return _result( OUTCOME_NOT_OWED, { "continue": True } )

    # Steps 4 / 5 — owed: poke under cap, else stop nudging
    if poke_count >= cap:
        return _result( OUTCOME_CAP_REACHED, { "continue": True }, should_notify_cap=True )

    reason = build_poke_reason( oracle_verdict ) if oracle_owed else DECLARED_OWED_REASON
    return _result( OUTCOME_POKE, { "decision": "block", "reason": reason }, should_increment=True )


def quick_smoke_test():
    """
    Self-contained smoke test over the four outcome paths.

    Ensures:
        - Returns True if honor / not-owed / poke / cap-reached resolve as
          designed; raises AssertionError otherwise.
    """
    import datetime
    from lupin_cli.claude_code.hooks.lib import heartbeat_work_owed as owed_mod

    now      = datetime.datetime( 2026, 6, 4, 12, 0, 0, tzinfo=datetime.timezone.utc )
    fresh_at = now.isoformat()

    # Honored fresh declared hold → no poke
    honored_hold = { "held_at": fresh_at, "ttl_seconds": 900, "reason": "holding on Rachel", "work_owed": True }
    r = decide_heartbeat( honored_hold, None, 0, 3, now=now )
    assert r[ "outcome" ] == OUTCOME_HONORED
    assert r[ "hook_output" ] == { "continue": True }

    # No hold, oracle says owed, under cap → poke
    verdict = owed_mod.evaluate_work_owed( todo_items=[ { "status": owed_mod.TODO_IN_PROGRESS, "owned_by_me": True } ] )
    r = decide_heartbeat( None, verdict, 0, 3, now=now )
    assert r[ "outcome" ] == OUTCOME_POKE
    assert r[ "hook_output" ][ "decision" ] == "block"
    assert "reason" in r[ "hook_output" ]
    assert r[ "should_increment" ] is True

    # Owed but at cap → stop nudging + notify signal
    r = decide_heartbeat( None, verdict, 3, 3, now=now )
    assert r[ "outcome" ] == OUTCOME_CAP_REACHED
    assert r[ "should_notify_cap" ] is True

    # Nothing owed → done
    empty = owed_mod.evaluate_work_owed()
    r = decide_heartbeat( None, empty, 0, 3, now=now )
    assert r[ "outcome" ] == OUTCOME_NOT_OWED

    return True


if __name__ == "__main__":   # pragma: no cover - manual smoke entrypoint
    ok = quick_smoke_test()
    print( f"heartbeat_decision smoke: {'PASS' if ok else 'FAIL'}" )
