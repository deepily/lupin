#!/usr/bin/env python3
"""
Heartbeat Hook v2 — WHOLE-CHAIN integration suite (real leaves, real files).

**Author:** Mr. Radio 🦉 (integration tester, idx 3) — independent, adversarial
whole-system perspective. Manager: Tiberius 👑. Implementers: Rachel 🕊️ (adapter
+ transcript-reader + Task* oracle wiring), Tiffany 💍 (pure leaves). Design:
María 🌸 (`src/rnd/v0.1.8/2026.06.04-heartbeat-hook/03-arbiter-design.md` + canonical
PIP §0/§0.2/§0.3).

## Why this suite exists (the gap)

Every other heartbeat test is either PURE-UNIT (one leaf module in isolation) or
ADAPTER-UNIT (`test_stop_hook_heartbeat.py` — drives `_run_heartbeat`/`main` with
the I/O leaves MOCKED: `load_heartbeat_settings`, `read_hold`, `get_poke_count`,
`increment_poke_count`, `fetch_task_work_owed`, `is_task_set_empty`,
`heartbeat_events` all patched). `test_heartbeat_v1_composition.py` is the closest
to integration but predates v2 — no transcript, no Task* replay, no event emit, no
idle beacon.

**NOTHING drives the full v2 chain through REAL leaves + REAL on-disk files.** This
suite does: a synthetic transcript JSONL on disk →
`transcript_reader.iter_tool_uses` → `heartbeat_task_state` Task* replay →
`heartbeat_work_owed.evaluate_work_owed` → `heartbeat_decision.decide_heartbeat` →
real `.heartbeat-hold-<sid>.json` (project-root leaf) + real `/tmp` poke-cap
counter + real `~/.claude/heartbeat-events/<sid>.jsonl` event log. The ONLY things
neutralized are TRUE externalities: the voice-bridge persona resolver
(`get_voice_persona`) and — per test choice — the settings loader (so the live
`settings.json` flag can't make the suite non-deterministic). The decision logic
under test is never mocked.

## Hermetic mandate (the heartbeat system is :7999-free by design)

Real `settings.json` has `heartbeat.enabled=true` RIGHT NOW and a real v2 arbiter
consumes `~/.claude/heartbeat-events/*.jsonl`. Synthetic test exhaust MUST NOT leak
into the live fleet dir. Isolation (Tiffany 💍 + Rachel 🕊️ traps):
  - `heartbeat_events.FLEET_EVENTS_DIR` → tmp  (the autouse `conftest.py` fixture)
  - `heartbeat_poke_cap.COUNTER_DIR`    → tmp  (the `roots` fixture below)
  - `heartbeat_hold` project-root default (`cu.get_project_root`) → tmp  (ditto)
So NO real `~/.claude` / repo file is ever touched; plain pytest, :7999-eligible
per the venue rubric (no persistent state, sub-second, no server monopoly).

## Coverage map (the seam matrix — Tiberius-approved 2026-06-04)

  A  whole-chain producer (transcript → decision → on-disk event)
  B  poke-cap exhaustion + re-engagement reset (real counter trajectory)
  C  hold ↔ oracle precedence (fresh / stale / reasonless / declared-done)
  D  idle beacon edge-trigger (sticky / de-dup / supersede)
  E  fire-and-forget degradation (emit raises / dir unwritable / bad transcript
     → Stop NEVER breaks — §0 #2 invariant)
  F  main() precedence seams (speakerphone / loop-guard / voice **vs** heartbeat —
     Rachel's crown jewels: heartbeat must LOSE to all three even with owed Task*)
  G  arbiter EXHAUST CONTRACT (producer-side; consumer deferred until arbiter
     built — §4/§0.2 record conformance the arbiter will glob+consume)
  S  settings loader seam (REAL load_heartbeat_settings via HOME→tmp file)

Venue: :7999-eligible / local — hermetic, no server, sub-second.
"""
import datetime
import json
import os
import sys

import pytest

# Bootstrap (mirrors the hook + sibling tests)
_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:   # pragma: no cover - src is always already on sys.path under pytest collection
    sys.path.insert( 0, _src_path )

import lupin_cli.claude_code.hooks.stop as stop
from lupin_cli.claude_code.hooks.lib import heartbeat_events, heartbeat_poke_cap, heartbeat_hold
from lupin_cli.claude_code.hooks.lib.heartbeat_decision import (
    DECLARED_OWED_REASON, OUTCOME_POKE, OUTCOME_HONORED,
    OUTCOME_NOT_OWED, OUTCOME_CAP_REACHED,
)
from lupin_cli.claude_code.hooks.lib.heartbeat_events import EVENT_IDLE

UTC = datetime.timezone.utc

# Canonical §0.2 record field set (every emitted line) — reason rides ONLY the poke.
_BASE_FIELDS = {
    "schema_version", "session_id", "persona", "ts",
    "outcome", "poke_count", "cap", "work_owed", "awaiting",
}


# ═════════════════════════════════════════════════════════════════════════════
# Synthetic-fixture builders (transcript JSONL + Task* event specs)
# ═════════════════════════════════════════════════════════════════════════════

def _assistant_tool_use( name, inp, tu_id ):
    """An `assistant` transcript line carrying a single tool_use block."""
    return { "type": "assistant", "message": { "role": "assistant", "content": [
        { "type": "tool_use", "name": name, "input": inp, "id": tu_id },
    ] } }


def _write_transcript( path, calls ):
    """
    Write a transcript JSONL of assistant tool_use lines.

    Requires:
        - path is a Path
        - calls is a list of ( name, input_dict, tool_use_id )

    Ensures:
        - Writes one assistant line per call, in order (trailing newline when
          non-empty; an empty call list yields an empty file)
        - Returns the path as a string (the Stop-payload transcript_path shape)
    """
    lines = [ json.dumps( _assistant_tool_use( n, i, tid ) ) for ( n, i, tid ) in calls ]
    text  = "\n".join( lines )
    if lines:
        text += "\n"
    path.write_text( text )
    return str( path )


def _task_transcript( path, events ):
    """
    Build a Task*-replay transcript from a compact event spec.

    Requires:
        - path is a Path
        - events is a list of either:
              ( "create", )                 → a TaskCreate (ordinal id assigned)
              ( "update", task_id, status ) → a TaskUpdate for that ordinal id

    Ensures:
        - TaskCreate calls get sequential tool_use ids c1, c2, … (the REAL
          ordinal taskId is assigned by replay, not by the transcript — exactly
          the seam under test)
        - Returns the transcript path (string)
    """
    calls    = [ ]
    n_create = 0
    for e in events:
        if e[ 0 ] == "create":
            n_create += 1
            calls.append( ( "TaskCreate", { "subject": f"task-{n_create}" }, f"c{n_create}" ) )
        else:
            _, task_id, status = e
            calls.append( ( "TaskUpdate", { "taskId": str( task_id ), "status": status }, f"u{task_id}-{status}" ) )
    return _write_transcript( path, calls )


def _iso( dt ):
    return dt.isoformat()


# ═════════════════════════════════════════════════════════════════════════════
# The hermetic chain harness — real leaves, every real-file root → tmp
# ═════════════════════════════════════════════════════════════════════════════

class _Chain:
    """Handle exposing the isolated dirs + assertion helpers over REAL leaves."""

    def __init__( self, tmp_path, monkeypatch ):
        self._tmp        = tmp_path
        self._mp         = monkeypatch
        self.hold_dir    = tmp_path / "proj"
        self.counter_dir = tmp_path / "counter"
        # FLEET_EVENTS_DIR is redirected by the autouse conftest fixture to
        # tmp_path / "heartbeat-events" — read it back from the live module.
        self.hold_dir.mkdir( exist_ok=True )
        self.counter_dir.mkdir( exist_ok=True )
        self.transcripts = tmp_path / "transcripts"
        self.transcripts.mkdir( exist_ok=True )
        self._t_seq      = 0

    # ── leaf-state seeding (REAL writes through the leaf modules) ──

    def task_transcript( self, events ):
        """Write a Task* transcript to a fresh path; return its path string."""
        self._t_seq += 1
        return _task_transcript( self.transcripts / f"t{self._t_seq}.jsonl", events )

    def raw_transcript( self, text ):
        """Write a RAW transcript body (for malformed / truncated-line cases)."""
        self._t_seq += 1
        path = self.transcripts / f"t{self._t_seq}.jsonl"
        path.write_text( text )
        return str( path )

    def append_update( self, transcript_path, task_id, status ):
        """Append one TaskUpdate line to an existing transcript (a later turn)."""
        line = json.dumps( _assistant_tool_use(
            "TaskUpdate", { "taskId": str( task_id ), "status": status }, f"u{task_id}-{status}-x"
        ) )
        with open( transcript_path, "a" ) as f:
            f.write( line + "\n" )

    def seed_hold( self, session_id, *, reason, work_owed, fresh=True,
                   awaiting="none", ttl_seconds=900 ):
        """Write a REAL .heartbeat-hold-<sid>.json into the isolated project root."""
        if fresh:
            held_at = _iso( datetime.datetime.now( UTC ) )
        else:
            held_at = _iso( datetime.datetime.now( UTC ) - datetime.timedelta( seconds=10_000 ) )
        return heartbeat_hold.write_hold(
            session_id, "María 🌸", reason, work_owed=work_owed,
            ttl_seconds=ttl_seconds, awaiting=awaiting, held_at=held_at,
            base_dir=self.hold_dir,
        )

    # ── settings control ──

    def enable( self, enabled=True, cap=3 ):
        """Patch the settings loader (the live flag must not bleed in)."""
        self._mp.setattr( stop, "load_heartbeat_settings",
                          lambda: { "enabled": enabled, "poke_cap": cap } )

    def persona( self, value ):
        """Override the (external) voice-bridge persona resolver."""
        self._mp.setattr( stop, "get_voice_persona", lambda _sid: value )

    # ── real read-back assertion surface ──

    def events( self, session_id ):
        """REAL events JSONL read-back (the arbiter's glob input)."""
        return heartbeat_events.read_events( session_id )

    def poke_count( self, session_id ):
        """REAL poke-cap counter file read-back."""
        return heartbeat_poke_cap.get_poke_count( session_id )

    def reset_via_user_prompt( self, session_id ):
        """
        Drive the REAL re-engagement reset the UserPromptSubmit hook performs
        (`heartbeat_poke_cap.reset_poke_count`) — the same function user_prompt_submit
        calls, reading the same isolated COUNTER_DIR.
        """
        heartbeat_poke_cap.reset_poke_count( session_id )

    def fleet_glob( self ):
        """All per-session event files in the fleet dir (arbiter glob seam)."""
        return sorted( heartbeat_events.FLEET_EVENTS_DIR.glob( "*.jsonl" ) )


@pytest.fixture
def roots( tmp_path, monkeypatch ):
    """
    Isolate every REAL-file root the heartbeat chain touches to tmp, leaving the
    decision logic fully real. Default persona is a fixed bridge value so persona
    propagation into the event record is assertable.
    """
    chain = _Chain( tmp_path, monkeypatch )
    # poke-cap counter → tmp (adapter calls get/incr/reset with no base_dir)
    monkeypatch.setattr( heartbeat_poke_cap, "COUNTER_DIR", chain.counter_dir )
    # hold default base_dir resolves via cu.get_project_root() → tmp
    import cosa.utils.util as cu
    monkeypatch.setattr( cu, "get_project_root", lambda: str( chain.hold_dir ) )
    # external voice-bridge persona (metadata, not decision logic)
    monkeypatch.setattr( stop, "get_voice_persona", lambda _sid: { "name": "Mr. Radio 🦉" } )
    return chain


# A would-poke Task* set: one in_progress task (owned_by_me True by construction).
_OWED   = [ ( "create", ), ( "update", 1, "in_progress" ) ]
# A genuinely-done Task* set: created then completed (non-empty, not owed).
_DONE   = [ ( "create", ), ( "update", 1, "completed" ) ]
# Empty Task* set (genuine idle): no Task* calls at all.
_EMPTY  = [ ]


# ═════════════════════════════════════════════════════════════════════════════
# GROUP A — whole-chain producer (transcript → decision → on-disk event)
# ═════════════════════════════════════════════════════════════════════════════

class TestGroupAWholeChainProducer:
    """Real transcript_reader → task_state → work_owed → decision → events file."""

    def test_a1_fm19_no_hold_owed_task_pokes_and_emits( self, roots ):
        """FM-19 headline: no hold + owed Task* (in_progress) → block dict + real poke event + counter==1."""
        roots.enable( cap=3 )
        tp  = roots.task_transcript( _OWED )
        out = stop._run_heartbeat( "sidA1", tp )

        assert out[ "decision" ] == "block"
        assert "in-progress" in out[ "reason" ]                # oracle specifics quoted
        assert roots.poke_count( "sidA1" ) == 1                # REAL counter incremented

        ev = roots.events( "sidA1" )
        assert len( ev ) == 1
        rec = ev[ 0 ]
        assert rec[ "outcome" ]    == OUTCOME_POKE
        assert rec[ "work_owed" ]  is True                     # v2 REAL bool (was null in v1)
        assert rec[ "poke_count" ] == 1
        assert rec[ "cap" ]        == 3
        assert rec[ "persona" ]    == "Mr. Radio 🦉"           # bridge metadata propagated
        assert rec[ "reason" ]     == out[ "reason" ]          # poke text rides the record

    def test_a2_done_taskset_nonempty_no_poke_no_event_no_idle( self, roots ):
        """create→completed: not owed, task set NON-empty → no poke, no event line, NO idle."""
        roots.enable()
        tp  = roots.task_transcript( _DONE )
        out = stop._run_heartbeat( "sidA2", tp )

        assert out is None                                     # not_owed → no block
        assert roots.events( "sidA2" ) == [ ]                  # not_owed skipped; non-empty set → no idle
        assert roots.poke_count( "sidA2" ) == 0

    def test_a3_poke_then_completed_next_turn_stops( self, roots ):
        """in_progress → poke; append completed (next turn) → not owed, non-empty set → no poke, no idle."""
        roots.enable()
        tp = roots.task_transcript( _OWED )
        assert stop._run_heartbeat( "sidA3", tp )[ "decision" ] == "block"

        roots.append_update( tp, 1, "completed" )              # the work got finished
        out2 = stop._run_heartbeat( "sidA3", tp )
        assert out2 is None
        ev = roots.events( "sidA3" )
        assert [ r[ "outcome" ] for r in ev ] == [ OUTCOME_POKE ]   # only the first poke; no new line

    def test_a4_empty_transcript_no_hold_emits_idle( self, roots ):
        """Empty Task* set + no hold → not_owed AND empty set → exactly ONE idle beacon."""
        roots.enable()
        tp  = roots.task_transcript( _EMPTY )
        out = stop._run_heartbeat( "sidA4", tp )

        assert out is None
        ev = roots.events( "sidA4" )
        assert len( ev ) == 1
        assert ev[ 0 ][ "outcome" ]   == EVENT_IDLE
        assert ev[ 0 ][ "work_owed" ] is False
        assert ev[ 0 ][ "awaiting" ]  is None
        assert "reason" not in ev[ 0 ]

    def test_a5_last_write_wins_same_taskid( self, roots ):
        """Multiple updates to the same taskId → final status drives owed/not (last-write-wins)."""
        roots.enable()
        # task 1: pending → in_progress → completed  ⇒ final completed ⇒ NOT owed
        tp1 = roots.task_transcript( [ ( "create", ), ( "update", 1, "in_progress" ), ( "update", 1, "completed" ) ] )
        assert stop._run_heartbeat( "sidA5a", tp1 ) is None

        # task 1: pending → completed → in_progress  ⇒ final in_progress ⇒ OWED
        tp2 = roots.task_transcript( [ ( "create", ), ( "update", 1, "completed" ), ( "update", 1, "in_progress" ) ] )
        assert stop._run_heartbeat( "sidA5b", tp2 )[ "decision" ] == "block"

    def test_a6_ordinal_taskid_mapping( self, roots ):
        """Sequential ordinal ids: create×2 then update BOTH to completed → not owed (proves Nth-create→str(N))."""
        roots.enable()
        tp = roots.task_transcript( [
            ( "create", ), ( "create", ),
            ( "update", 1, "completed" ), ( "update", 2, "completed" ),
        ] )
        # If ordinal mapping were wrong, an update could miss a created task → a
        # phantom pending task → false poke. Correct mapping ⇒ both terminal ⇒ no poke.
        assert stop._run_heartbeat( "sidA6", tp ) is None

    def test_a7_many_events_replay_correct( self, roots ):
        """Scale/correctness (Tiberius): 30 creates, most completed, a few left in_progress → owed poke."""
        roots.enable()
        events = [ ( "create", ) for _ in range( 30 ) ]
        for i in range( 1, 29 ):                               # complete tasks 1..28
            events.append( ( "update", i, "completed" ) )
        events.append( ( "update", 29, "in_progress" ) )       # 29 still working
        # task 30 left at created/pending
        tp  = roots.task_transcript( events )
        out = stop._run_heartbeat( "sidA7", tp )
        assert out[ "decision" ] == "block"                    # 29 in_progress + 30 pending ⇒ owed
        # the real oracle saw exactly the two owed tasks
        from lupin_cli.claude_code.hooks.lib.heartbeat_task_state import fetch_task_work_owed
        owed = fetch_task_work_owed( tp )
        assert sorted( i[ "status" ] for i in owed ) == [ "in_progress", "pending" ]


# ═════════════════════════════════════════════════════════════════════════════
# GROUP B — poke-cap exhaustion + re-engagement reset (real counter trajectory)
# ═════════════════════════════════════════════════════════════════════════════

class TestGroupBPokeCapAndReset:

    def test_b1_poke_to_cap_then_cap_reached( self, roots ):
        """Owed, cap=3: poke/poke/poke (counts 1,2,3); 4th → cap_reached, no increment, work_owed=True."""
        roots.enable( cap=3 )
        sid = "sidB1"
        tp  = roots.task_transcript( _OWED )

        for expected in ( 1, 2, 3 ):
            out = stop._run_heartbeat( sid, tp )
            assert out[ "decision" ] == "block"
            assert roots.poke_count( sid ) == expected

        out4 = stop._run_heartbeat( sid, tp )                  # at cap
        assert out4 is None                                    # cap_reached → no block
        assert roots.poke_count( sid ) == 3                    # NOT incremented past cap

        outcomes = [ r[ "outcome" ] for r in roots.events( sid ) ]
        assert outcomes == [ OUTCOME_POKE, OUTCOME_POKE, OUTCOME_POKE, OUTCOME_CAP_REACHED ]
        cap_rec = roots.events( sid )[ -1 ]
        assert cap_rec[ "work_owed" ] is True                  # the §4 "stuck" signal
        assert "reason" not in cap_rec

    def test_b2_reengagement_reset_reopens_budget( self, roots ):
        """After cap, the REAL UserPromptSubmit reset reopens the budget → next owed stop pokes from 1."""
        roots.enable( cap=2 )
        sid = "sidB2"
        tp  = roots.task_transcript( _OWED )

        stop._run_heartbeat( sid, tp )
        stop._run_heartbeat( sid, tp )                         # count now 2 == cap
        assert stop._run_heartbeat( sid, tp ) is None          # cap_reached
        assert roots.poke_count( sid ) == 2

        roots.reset_via_user_prompt( sid )                     # genuine user re-engagement
        assert roots.poke_count( sid ) == 0
        out = stop._run_heartbeat( sid, tp )                   # budget reopened
        assert out[ "decision" ] == "block"
        assert roots.poke_count( sid ) == 1

    def test_b3_cap_one_boundary( self, roots ):
        """cap=1: first owed stop pokes (count 1); second immediately cap_reached."""
        roots.enable( cap=1 )
        sid = "sidB3"
        tp  = roots.task_transcript( _OWED )
        assert stop._run_heartbeat( sid, tp )[ "decision" ] == "block"
        assert roots.poke_count( sid ) == 1
        assert stop._run_heartbeat( sid, tp ) is None
        assert roots.events( sid )[ -1 ][ "outcome" ] == OUTCOME_CAP_REACHED


# ═════════════════════════════════════════════════════════════════════════════
# GROUP C — hold ↔ oracle precedence (real hold file ↔ decision ↔ events)
# ═════════════════════════════════════════════════════════════════════════════

class TestGroupCHoldOraclePrecedence:

    def test_c1_fresh_reasoned_hold_honored_no_poke( self, roots ):
        """Fresh reasoned hold + owed transcript → HONORED (no poke), counter untouched, awaiting propagated."""
        roots.enable()
        sid = "sidC1"
        roots.seed_hold( sid, reason="holding on Rachel", work_owed=True, fresh=True, awaiting="peer:Rachel" )
        tp  = roots.task_transcript( _OWED )                   # oracle WOULD owe

        assert stop._run_heartbeat( sid, tp ) is None          # honored wins over oracle
        assert roots.poke_count( sid ) == 0
        rec = roots.events( sid )[ -1 ]
        assert rec[ "outcome" ]  == OUTCOME_HONORED
        assert rec[ "awaiting" ] == "peer:Rachel"              # dependency-graph edge in the exhaust

    def test_c2_stale_declared_owed_empty_oracle_pokes_declared_reason( self, roots ):
        """Stale hold work_owed=True + EMPTY oracle → declared-owed drives poke with DECLARED_OWED_REASON."""
        roots.enable()
        sid = "sidC2"
        roots.seed_hold( sid, reason="was holding", work_owed=True, fresh=False, awaiting="none" )
        tp  = roots.task_transcript( _EMPTY )                  # oracle NOT owed

        out = stop._run_heartbeat( sid, tp )
        assert out[ "decision" ] == "block"
        assert out[ "reason" ]   == DECLARED_OWED_REASON       # declared (not oracle) reason text
        assert roots.events( sid )[ -1 ][ "work_owed" ] is False   # oracle verdict is the emitted bool

    def test_c2b_stale_declared_owed_with_oracle_uses_oracle_reason( self, roots ):
        """Stale hold work_owed=True + OWED oracle → poke, but reason quotes the ORACLE specifics."""
        roots.enable()
        sid = "sidC2b"
        roots.seed_hold( sid, reason="was holding", work_owed=True, fresh=False )
        tp  = roots.task_transcript( _OWED )

        out = stop._run_heartbeat( sid, tp )
        assert out[ "decision" ] == "block"
        assert "in-progress" in out[ "reason" ]                # oracle specifics win the reason text
        assert roots.events( sid )[ -1 ][ "work_owed" ] is True

    def test_c3_fresh_reasonless_hold_not_honored( self, roots ):
        """Fresh but REASONLESS hold → not honored → falls to work-owed (declared True → poke)."""
        roots.enable()
        sid = "sidC3"
        roots.seed_hold( sid, reason="", work_owed=True, fresh=True )
        tp  = roots.task_transcript( _EMPTY )

        out = stop._run_heartbeat( sid, tp )
        assert out is not None and out[ "decision" ] == "block"   # reasonless ⇒ not a defended quiescence
        assert roots.events( sid )[ -1 ][ "outcome" ] == OUTCOME_POKE

    def test_c4_stale_declared_done_beats_oracle_owed( self, roots ):
        """Stale hold work_owed=False + owed transcript → declared-done wins → NOT_OWED, no poke."""
        roots.enable()
        sid = "sidC4"
        roots.seed_hold( sid, reason="all finished", work_owed=False, fresh=False )
        tp  = roots.task_transcript( _OWED )                   # oracle WOULD owe

        assert stop._run_heartbeat( sid, tp ) is None          # declared done short-circuits
        assert roots.poke_count( sid ) == 0
        # not_owed with a NON-empty task set ⇒ no idle, no event line at all
        assert roots.events( sid ) == [ ]

    def test_c5_fresh_reasoned_hold_wins_over_oracle_owed( self, roots ):
        """Fresh reasoned hold (work_owed True) + oracle owed → honored wins; no poke despite oracle."""
        roots.enable()
        sid = "sidC5"
        roots.seed_hold( sid, reason="mid long run", work_owed=True, fresh=True, awaiting="commons:coordination" )
        tp  = roots.task_transcript( _OWED )
        assert stop._run_heartbeat( sid, tp ) is None
        assert roots.events( sid )[ -1 ][ "outcome" ] == OUTCOME_HONORED

    def test_c6_fresh_reasoned_hold_empty_taskset_honored_not_idle( self, roots ):
        """Precedence (Tiberius): fresh reasoned hold + EMPTY task set → HONORED, NOT idle (hold beats idle path)."""
        roots.enable()
        sid = "sidC6"
        roots.seed_hold( sid, reason="paused deliberately", work_owed=True, fresh=True )
        tp  = roots.task_transcript( _EMPTY )                  # would otherwise emit an idle beacon

        assert stop._run_heartbeat( sid, tp ) is None
        outcomes = [ r[ "outcome" ] for r in roots.events( sid ) ]
        assert outcomes == [ OUTCOME_HONORED ]                 # honored, NOT idle
        assert EVENT_IDLE not in outcomes

    def test_c6b_declared_owed_empty_taskset_pokes( self, roots ):
        """Rachel #5: hold work_owed=True + EMPTY oracle (stale/reasonless) → poke even with empty Task* set."""
        roots.enable()
        sid = "sidC6b"
        roots.seed_hold( sid, reason="", work_owed=True, fresh=True )   # reasonless ⇒ not honored
        tp  = roots.task_transcript( _EMPTY )
        out = stop._run_heartbeat( sid, tp )
        assert out[ "decision" ] == "block"
        assert out[ "reason" ]   == DECLARED_OWED_REASON


# ═════════════════════════════════════════════════════════════════════════════
# GROUP D — idle beacon edge-trigger (sticky / de-dup / supersede)
# ═════════════════════════════════════════════════════════════════════════════

class TestGroupDIdleEdgeTrigger:

    def test_d1_idle_streak_emits_one_beacon( self, roots ):
        """not_owed + empty ×3 Stops → exactly ONE idle event (sticky-until-superseded de-dup)."""
        roots.enable()
        sid = "sidD1"
        tp  = roots.task_transcript( _EMPTY )
        for _ in range( 3 ):
            assert stop._run_heartbeat( sid, tp ) is None
        outcomes = [ r[ "outcome" ] for r in roots.events( sid ) ]
        assert outcomes == [ EVENT_IDLE ]                      # de-duped: one beacon, not three

    def test_d2_supersede_reopens_idle_edge( self, roots ):
        """idle → owed(poke) → idle: the poke supersedes, re-arming a fresh idle transition."""
        roots.enable()
        sid     = "sidD2"
        tp_idle = roots.task_transcript( _EMPTY )
        tp_owed = roots.task_transcript( _OWED )

        stop._run_heartbeat( sid, tp_idle )                    # idle #1
        stop._run_heartbeat( sid, tp_owed )                    # poke (supersedes)
        stop._run_heartbeat( sid, tp_idle )                    # idle #2 (fresh transition)

        outcomes = [ r[ "outcome" ] for r in roots.events( sid ) ]
        assert outcomes == [ EVENT_IDLE, OUTCOME_POKE, EVENT_IDLE ]

    def test_d3_idle_is_sticky_standing_state( self, roots ):
        """After a quiet streak the LAST emitted outcome stays 'idle' — the standing state an arbiter reads
        from offset 0 (the inference-backstop the arbiter relies on is consumer-side → deferred)."""
        roots.enable()
        sid = "sidD3"
        tp  = roots.task_transcript( _EMPTY )
        for _ in range( 4 ):
            stop._run_heartbeat( sid, tp )
        assert heartbeat_events.last_emitted_outcome( sid ) == EVENT_IDLE


# ═════════════════════════════════════════════════════════════════════════════
# GROUP E — fire-and-forget degradation (§0 #2: emit NEVER breaks the Stop)
# ═════════════════════════════════════════════════════════════════════════════

class TestGroupEFireAndForgetDegradation:

    def test_e1_emit_raises_poke_still_proceeds( self, roots, monkeypatch ):
        """emit_outcome raises → _run_heartbeat STILL returns the poke block; error logged, poke proceeds."""
        roots.enable()
        logged = [ ]
        monkeypatch.setattr( stop, "log_to_stream",
                             lambda *a, **k: logged.append( k.get( "extra", {} ).get( "phase" ) ) )
        monkeypatch.setattr( stop.heartbeat_events, "emit_outcome",
                             lambda *a, **k: ( _ for _ in () ).throw( RuntimeError( "disk gone" ) ) )
        tp  = roots.task_transcript( _OWED )
        out = stop._run_heartbeat( "sidE1", tp )
        assert out[ "decision" ] == "block"                    # the §0 #2 invariant
        assert "heartbeat_emit_error" in logged

    def test_e2_idle_emit_raises_swallowed( self, roots, monkeypatch ):
        """Idle-beacon emit raises → _emit_genuine_idle swallows + logs; _run_heartbeat returns None (stop allowed)."""
        roots.enable()
        logged = [ ]
        monkeypatch.setattr( stop, "log_to_stream",
                             lambda *a, **k: logged.append( k.get( "extra", {} ).get( "phase" ) ) )

        # First emit (the not_owed self-filter) is a harmless no-op; the idle path
        # is where is_idle_transition → emit fires. Make is_idle_transition raise.
        monkeypatch.setattr( stop.heartbeat_events, "is_idle_transition",
                             lambda *a, **k: ( _ for _ in () ).throw( RuntimeError( "boom" ) ) )
        tp = roots.task_transcript( _EMPTY )
        assert stop._run_heartbeat( "sidE2", tp ) is None      # stop still allowed
        assert "heartbeat_idle_emit_error" in logged

    def test_e3_events_dir_unwritable_returns_false_poke_proceeds( self, roots, monkeypatch ):
        """REAL OSError: point the fleet dir at an unwritable location → emit returns False (no raise) → poke proceeds."""
        roots.enable()
        # A path whose parent is a FILE → mkdir(parents=True) raises OSError inside
        # emit_outcome's try/except → returns False, never raises.
        blocker = roots._tmp / "blocker"
        blocker.write_text( "i am a file, not a dir" )
        monkeypatch.setattr( heartbeat_events, "FLEET_EVENTS_DIR", blocker / "events" )
        tp  = roots.task_transcript( _OWED )
        out = stop._run_heartbeat( "sidE3", tp )
        assert out[ "decision" ] == "block"                    # poke unaffected by the write failure
        assert heartbeat_events.emit_outcome( "sidE3", "p", OUTCOME_POKE, 1, 3, base_dir=blocker / "events" ) is False

    def test_e4_corrupt_existing_events_file_resilient( self, roots ):
        """A partially-corrupt fleet file → read_events skips bad lines → is_idle_transition still correct."""
        roots.enable()
        sid  = "sidE4"
        path = heartbeat_events.events_path( sid )             # fleet dir (tmp)
        path.parent.mkdir( parents=True, exist_ok=True )
        path.write_text(
            '{ "outcome": "honored" }\n'                       # valid prior event
            "{ not json at all\n"                              # malformed → skipped
            "\n"                                               # blank → skipped
            '"a-bare-string"\n'                                # non-object → skipped
        )
        # last VALID outcome is "honored" ⇒ a fresh empty stop is a real idle transition
        tp = roots.task_transcript( _EMPTY )
        assert stop._run_heartbeat( sid, tp ) is None
        assert [ r[ "outcome" ] for r in roots.events( sid ) ] == [ "honored", EVENT_IDLE ]

    # ── conservative degradation: a sick transcript NEVER false-pokes / crashes (Rachel #9) ──

    def test_e5_none_transcript_path_no_poke_no_crash( self, roots ):
        """transcript_path=None → reader empty → not_owed (+empty set ⇒ idle beacon) → no poke, no crash."""
        roots.enable()
        assert stop._run_heartbeat( "sidE5", None ) is None
        assert roots.poke_count( "sidE5" ) == 0
        assert [ r[ "outcome" ] for r in roots.events( "sidE5" ) ] == [ EVENT_IDLE ]

    def test_e6_nonexistent_transcript_no_poke_no_crash( self, roots ):
        """A transcript_path that does not exist → reader empty → no poke, no crash."""
        roots.enable()
        ghost = str( roots.transcripts / "does-not-exist.jsonl" )
        assert stop._run_heartbeat( "sidE6", ghost ) is None
        assert roots.poke_count( "sidE6" ) == 0

    def test_e7_partial_truncated_last_line_uses_valid_prefix( self, roots ):
        """A mid-write truncated last line → reader skips the bad line → decides on the valid prefix, no crash."""
        roots.enable()
        valid  = json.dumps( _assistant_tool_use( "TaskCreate", { "subject": "real" }, "c1" ) )
        # second line is a half-flushed JSON object (no closing) AND no trailing newline
        broken = '{ "type": "assistant", "message": { "role": "assistant", "content": [ { "type": "tool_us'
        tp     = roots.raw_transcript( valid + "\n" + broken )
        out    = stop._run_heartbeat( "sidE7", tp )
        # the one valid TaskCreate ⇒ a pending (owed) task ⇒ poke; the broken line is simply skipped
        assert out[ "decision" ] == "block"


# ═════════════════════════════════════════════════════════════════════════════
# GROUP F — main() precedence seams (heartbeat must LOSE to A/B/voice — Rachel)
# ═════════════════════════════════════════════════════════════════════════════

def _drive_main( roots, monkeypatch, *, payload, speakerphone=False, voice_ctx="" ):
    """
    Drive the REAL stop.main() routing with the heartbeat chain LEFT REAL; patch
    ONLY the genuine entry externalities (stdin / stdout / bridge / voice-drain /
    idle-waiter). Returns the dict captured from emit_json + spy flags.
    """
    captured = { "emitted": [ ], "armed_idle": False, "asked": False, "voice_block": False }

    monkeypatch.setattr( stop, "read_hook_input", lambda: payload )
    monkeypatch.setattr( stop, "emit_json", lambda d: captured[ "emitted" ].append( d ) )
    monkeypatch.setattr( stop, "log_payload", lambda *a, **k: None )
    monkeypatch.setattr( stop, "log_to_stream", lambda *a, **k: None )
    monkeypatch.setattr( stop, "resolve_stable_session_id", lambda s: s )
    monkeypatch.setattr( stop, "get_claude_session_id", lambda: payload.get( "session_id", "" ) )
    monkeypatch.setattr( stop, "get_speakerphone", lambda _sid: speakerphone )
    monkeypatch.setattr( stop, "_try_auto_narrate", lambda *a, **k: None )
    monkeypatch.setattr( stop, "drain_and_acknowledge", lambda _sid: [ ] )
    monkeypatch.setattr( stop, "format_voice_context", lambda _m: voice_ctx )
    # voice-branch externalities
    monkeypatch.setattr( stop, "get_stop_block_count", lambda _sid: 0 )
    monkeypatch.setattr( stop, "increment_stop_block_count", lambda _sid: None )
    monkeypatch.setattr( stop, "reset_stop_block_count", lambda _sid: None )
    monkeypatch.setattr( stop, "enrich_voice_context", lambda c: c )
    monkeypatch.setattr( stop, "build_stop_block",
                         lambda r: captured.__setitem__( "voice_block", True ) or { "decision": "block", "reason": r } )
    monkeypatch.setattr( stop, "send_tts", lambda *a, **k: None )
    # idle-path spies
    monkeypatch.setattr( stop, "load_idle_settings", lambda: { "enabled": True, "backoff_minutes": [ 1 ] } )
    monkeypatch.setattr( stop, "_arm_idle_waiter",
                         lambda *a, **k: captured.__setitem__( "armed_idle", True ) )
    monkeypatch.setattr( stop, "_ask_anything_else",
                         lambda *a, **k: captured.__setitem__( "asked", True ) or { } )

    try:
        stop.main()
    except SystemExit:
        pass
    return captured


class TestGroupFMainPrecedence:

    def test_f1_poke_emits_block_skips_idle_path( self, roots, monkeypatch ):
        """Owed + enabled + no voice + not speakerphone → main emits the block JSON and SKIPS the idle path."""
        roots.enable()
        tp  = roots.task_transcript( _OWED )
        cap = _drive_main( roots, monkeypatch,
                           payload={ "session_id": "sidF1", "transcript_path": tp, "stop_hook_active": False } )
        assert cap[ "emitted" ] and cap[ "emitted" ][ -1 ][ "decision" ] == "block"
        assert cap[ "armed_idle" ] is False and cap[ "asked" ] is False   # heartbeat owned the stop
        assert roots.events( "sidF1" )[ -1 ][ "outcome" ] == OUTCOME_POKE

    def test_f2_not_owed_falls_through_to_idle_path( self, roots, monkeypatch ):
        """Empty Task* set → heartbeat returns None → main falls through to the idle waiter; idle beacon emitted."""
        # Thread A flipped the Stop-hook default idle behavior ask→idle_announce,
        # so not-owed now ANNOUNCES rather than arming the waiter. This test asserts
        # the legacy idle-WAITER fall-through, so force the "ask" behavior (mirrors
        # test_stop_hook.py::_force_immediate_ask_path).
        monkeypatch.setattr( stop, "_stop_hook_idle_behavior", lambda: "ask" )
        roots.enable()
        tp  = roots.task_transcript( _EMPTY )
        cap = _drive_main( roots, monkeypatch,
                           payload={ "session_id": "sidF2", "transcript_path": tp, "stop_hook_active": False } )
        assert cap[ "armed_idle" ] is True                     # fell through to idle path
        assert cap[ "emitted" ][ -1 ] == { }                   # allow-stop
        assert roots.events( "sidF2" )[ -1 ][ "outcome" ] == EVENT_IDLE

    def test_f3_speakerphone_early_exit_no_heartbeat( self, roots, monkeypatch ):
        """Speakerphone ON → Branch A early-exit BEFORE heartbeat → NO poke even with owed Task* (crown jewel)."""
        roots.enable()
        tp  = roots.task_transcript( _OWED )                   # WOULD poke
        cap = _drive_main( roots, monkeypatch, speakerphone=True,
                           payload={ "session_id": "sidF3", "transcript_path": tp, "stop_hook_active": False } )
        assert cap[ "emitted" ][ -1 ] == { }                   # speakerphone allow-stop
        assert roots.events( "sidF3" ) == [ ]                  # heartbeat never ran → no exhaust
        assert roots.poke_count( "sidF3" ) == 0

    def test_f4_loop_guard_no_heartbeat_on_refire( self, roots, monkeypatch ):
        """stop_hook_active=True (re-fire) → loop guard allows stop BEFORE Branch C → NO poke even with owed Task*."""
        roots.enable()
        tp  = roots.task_transcript( _OWED )
        cap = _drive_main( roots, monkeypatch,
                           payload={ "session_id": "sidF4", "transcript_path": tp, "stop_hook_active": True } )
        assert cap[ "emitted" ][ -1 ] == { }                   # loop-guard allow-stop
        assert roots.events( "sidF4" ) == [ ]                  # heartbeat never reached
        assert roots.poke_count( "sidF4" ) == 0

    def test_f5_voice_block_wins_no_heartbeat( self, roots, monkeypatch ):
        """voice_ctx present → Branch B voice block wins → heartbeat never reached (voice always wins)."""
        roots.enable()
        tp  = roots.task_transcript( _OWED )
        cap = _drive_main( roots, monkeypatch, voice_ctx="user said keep going",
                           payload={ "session_id": "sidF5", "transcript_path": tp, "stop_hook_active": False } )
        assert cap[ "voice_block" ] is True
        assert roots.events( "sidF5" ) == [ ]                  # heartbeat never ran


# ═════════════════════════════════════════════════════════════════════════════
# GROUP G — arbiter EXHAUST CONTRACT (producer-side; consumer DEFERRED)
#
# The v2 arbiter (glob+tail / fleet data model §4 / dependency graph / idle-roster /
# auto-ping throttle — María's 03-arbiter-design.md) is NOT BUILT. heartbeat_poker_job
# does not yet consume ~/.claude/heartbeat-events/. These tests validate the PRODUCER
# half of that unbuilt seam: the emitted records carry EXACTLY the §0.2/§4 contract the
# arbiter will glob+consume. Arbiter BEHAVIOR (cycle detection, roster assembly, ping
# backoff) is integration-tested when it lands.
# ═════════════════════════════════════════════════════════════════════════════

class TestGroupGArbiterExhaustContract:

    def test_g1_fleet_glob_one_file_per_session_conformant_records( self, roots ):
        """N synthetic sessions → glob(*.jsonl)=N files; every record matches the §0.2 field contract."""
        roots.enable()
        sessions = [ "fleet-a1b2", "fleet-c3d4", "fleet-e5f6" ]
        for sid in sessions:
            stop._run_heartbeat( sid, roots.task_transcript( _OWED ) )   # each pokes once

        files = roots.fleet_glob()
        assert len( files ) == len( sessions )                 # one file per session (the glob seam)

        for sid in sessions:
            ev = roots.events( sid )
            assert len( ev ) == 1
            rec = ev[ 0 ]
            assert rec[ "schema_version" ] == 1
            assert _BASE_FIELDS.issubset( rec.keys() )
            assert set( rec.keys() ) == _BASE_FIELDS | { "reason" }      # poke ⇒ +reason exactly
            assert rec[ "outcome" ] in ( OUTCOME_POKE, OUTCOME_HONORED, OUTCOME_CAP_REACHED, EVENT_IDLE )
            assert isinstance( rec[ "ts" ], str ) and rec[ "ts" ]

    def test_g2_awaiting_peer_edge_present_verbatim( self, roots ):
        """A hold scenario emits awaiting='peer:<X>' verbatim — the dependency-graph / auto-ping input edge."""
        roots.enable()
        sid = "sidG2"
        roots.seed_hold( sid, reason="blocked on Rachel", work_owed=True, fresh=True, awaiting="peer:Rachel" )
        stop._run_heartbeat( sid, roots.task_transcript( _OWED ) )
        assert roots.events( sid )[ -1 ][ "awaiting" ] == "peer:Rachel"

    def test_g3_declared_idle_vs_quiet_inferred_distinguishable( self, roots ):
        """Trust-label raw input: a declared-idle session emits an idle record; a 'done-but-busy' session does not."""
        roots.enable()
        # declared-available: empty Task* set → idle beacon
        stop._run_heartbeat( "sidG3-declared", roots.task_transcript( _EMPTY ) )
        # not_owed but NON-empty (all completed) → NO beacon (arbiter would have to INFER quiet)
        stop._run_heartbeat( "sidG3-inferred", roots.task_transcript( _DONE ) )

        declared = roots.events( "sidG3-declared" )
        inferred = roots.events( "sidG3-inferred" )
        assert [ r[ "outcome" ] for r in declared ] == [ EVENT_IDLE ]
        assert declared[ -1 ][ "work_owed" ] is False
        assert inferred == [ ]                                  # nothing to upgrade on → inference-only

    def test_g4_cap_reached_with_work_owed_true_is_stuck_signal( self, roots ):
        """The §4 'stuck' signal: a work-owed-to-cap session's last record is cap_reached AND work_owed=True."""
        roots.enable( cap=2 )
        sid = "sidG4"
        tp  = roots.task_transcript( _OWED )
        stop._run_heartbeat( sid, tp )
        stop._run_heartbeat( sid, tp )
        stop._run_heartbeat( sid, tp )                         # at cap
        last = roots.events( sid )[ -1 ]
        assert last[ "outcome" ]   == OUTCOME_CAP_REACHED
        assert last[ "work_owed" ] is True                     # the stuck pair the arbiter keys on
        assert last[ "poke_count" ] == 2

    def test_g5_not_owed_never_emitted( self, roots ):
        """Contract (María): plain per-turn not_owed is NEVER an emitted line (only the idle beacon, on empty)."""
        roots.enable()
        sid = "sidG5"
        # not_owed + NON-empty task set (all completed) ⇒ neither a not_owed line NOR an idle beacon
        stop._run_heartbeat( sid, roots.task_transcript( _DONE ) )
        assert roots.events( sid ) == [ ]

    def test_g6_null_persona_propagates( self, roots ):
        """The arbiter's data model must tolerate a null persona: a failed bridge lookup → record persona=None."""
        roots.enable()
        roots.persona( None )                                  # voice bridge yielded nothing
        sid = "sidG6"
        stop._run_heartbeat( sid, roots.task_transcript( _OWED ) )
        assert roots.events( sid )[ -1 ][ "persona" ] is None


# ═════════════════════════════════════════════════════════════════════════════
# GROUP S — settings loader seam (REAL load_heartbeat_settings via HOME→tmp file)
# ═════════════════════════════════════════════════════════════════════════════

class TestGroupSSettingsLoaderSeam:
    """Exercise the REAL settings loader end-to-end (not the patched stub) so the
    enabled/disabled file seam is integration-validated, not just unit-validated."""

    def _write_settings( self, home, block ):
        cfg = home / ".claude"
        cfg.mkdir( parents=True, exist_ok=True )
        ( cfg / "settings.json" ).write_text( json.dumps( block ) )

    def test_s1_real_loader_enabled_file_pokes( self, roots, monkeypatch ):
        """A real settings.json with heartbeat.enabled=true (read by the REAL loader) → owed transcript pokes."""
        home = roots._tmp / "home_on"
        self._write_settings( home, { "heartbeat": { "enabled": True, "poke_cap": 3 } } )
        monkeypatch.setenv( "HOME", str( home ) )
        # NOTE: do NOT call roots.enable() — we want the REAL loader to run.
        tp = roots.task_transcript( _OWED )
        assert stop._run_heartbeat( "sidS1", tp )[ "decision" ] == "block"

    def test_s2_real_loader_missing_file_defaults_off_no_poke( self, roots, monkeypatch ):
        """No settings.json → REAL loader returns the conservative default (enabled=False) → NO poke even if owed."""
        home = roots._tmp / "home_off"
        home.mkdir()
        monkeypatch.setenv( "HOME", str( home ) )              # ~/.claude/settings.json absent
        tp = roots.task_transcript( _OWED )
        assert stop._run_heartbeat( "sidS2", tp ) is None      # dormant by default → no exhaust
        assert roots.events( "sidS2" ) == [ ]
