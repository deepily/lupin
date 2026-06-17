#!/usr/bin/env python3
"""
Unit + integration tests for the Stop-hook Heartbeat Branch-C adapter (v2).

Layers:
  1. _run_heartbeat — the side-effecting adapter shell, driven against the REAL
     pure leaves (heartbeat_hold + heartbeat_work_owed + heartbeat_decision) so
     the v2 seam composition is validated, not mocked away. The Task*-replay
     SOURCE is injected via patched fetch_task_work_owed / is_task_set_empty
     (the reader itself is unit-tested in test_heartbeat_task_state.py).
  2. _emit_genuine_idle — the §6.2 genuine-idle declaration beacon (edge-trigger
     gate delegated to heartbeat_events.is_idle_transition).
  3. _notify_cap_reached — log-only cap FYI.
  4. main() — the Branch-C wiring (poke owns stop vs fall-through-to-idle), now
     threading transcript_path.

v2 scope (§0.3): work-owed source = the session's own Task* state replayed from
its transcript. v1 behavior preserved (fresh hold honored; hold-declared owed
still wins). FM-19 catch added: no hold + owed Task* → poke.

Venue: :7999-eligible / local — fully mocked I/O, no server, sub-second.
"""
import datetime
import os
import sys

import pytest
from unittest.mock import patch, MagicMock

# Bootstrap
_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

from lupin_cli.claude_code.hooks.stop import (
    main, _run_heartbeat, _emit_genuine_idle, _notify_cap_reached,
    _poke_sentence, _announce_poke, _has_pending_voice,
    _compose_poke_abstract, _build_poke_abstract_safe, _format_inbound, _receipt_lines,
    _owed_count_from_store, _synthesize_owed_items, STORE_OWED_STATUSES,
)
from lupin_cli.claude_code.hooks.lib.heartbeat_work_owed import TODO_IN_PROGRESS
from lupin_cli.claude_code.hooks.lib.heartbeat_decision import (
    DECLARED_OWED_REASON, OUTCOME_POKE, OUTCOME_NOT_OWED,
)
from lupin_cli.notifications.notification_models import NotificationPriority

UTC = datetime.timezone.utc


def _now():
    return datetime.datetime.now( UTC )


def _fresh_reasoned_hold():
    return {
        "session_id"  : "s", "persona": "María 🌸", "held_at": _now().isoformat(),
        "ttl_seconds" : 900, "work_owed": True, "reason": "holding on the gate",
        "awaiting"    : "peer:Rachel",
    }


def _stale_owed_hold():
    stale = ( _now() - datetime.timedelta( seconds=10_000 ) ).isoformat()
    return {
        "session_id"  : "s", "persona": "Tiffany 💍", "held_at": stale,
        "ttl_seconds" : 900, "work_owed": True, "reason": "was holding", "awaiting": "none",
    }


# v2.1: stop.py replays the transcript ONCE → these are replay_task_state outputs
# (the derive helpers owed_items_from_state / is_empty_state run real on them).
_OWED_STATE  = { "1": "in_progress" }    # FM-19 owed Task* state
_EMPTY_STATE = { }                        # no tasks → genuinely idle (empty set)
_DONE_STATE  = { "1": "completed" }       # not owed, but task set NON-empty


# ═════════════════════════════════════════════════════════════════════════════
# _run_heartbeat — v2 adapter shell over the REAL leaves
# ═════════════════════════════════════════════════════════════════════════════

class TestRunHeartbeat:
    """Real decide_heartbeat + evaluate_work_owed; Task* source + emit injected."""

    @pytest.fixture( autouse=True )
    def _isolate( self ):
        """
        Isolate side effects for ALL tests: patch the emit module (no real
        ~/.claude writes), stub persona resolution, default the Task* source
        to 'no owed work / empty set', and intercept the §4 breadcrumb's
        async notify (no network). Tests override as needed.
        """
        with patch( "lupin_cli.claude_code.hooks.stop.heartbeat_events" ) as ev, \
             patch( "lupin_cli.claude_code.hooks.stop.get_voice_persona", return_value=None ) as vp, \
             patch( "lupin_cli.claude_code.hooks.stop.replay_task_state", return_value={ } ) as rt, \
             patch( "lupin_cli.claude_code.hooks.stop.notify_user_async" ) as na, \
             patch( "lupin_cli.claude_code.hooks.stop._gather_outstanding_delegations",
                    return_value=[ ] ) as gd, \
             patch( "lupin_cli.claude_code.hooks.stop._gather_unanswered_inbound_questions",
                    return_value={ "owed": [ ], "stale": [ ] } ) as gq, \
             patch( "lupin_cli.claude_code.hooks.stop.inject_qualifier_via_tmux" ) as inj, \
             patch( "lupin_cli.claude_code.hooks.stop.build_sender_id_for_cc",
                    return_value="claude.code@lupin.deepily.ai#sid" ):
            # owed_items_from_state + is_empty_state run REAL on the replayed
            # state (single-replay v2.1 path) — tests drive scenarios by setting
            # self.mock_replay.return_value to a { taskId: status } dict.
            # _announce_poke runs REAL (its AsyncNotificationRequest is
            # asserted via self.mock_notify) — only the network call is cut.
            ev.EVENT_IDLE = "idle"
            ev.is_idle_transition.return_value = True
            self.mock_events      = ev
            self.mock_persona     = vp
            self.mock_replay      = rt
            self.mock_notify      = na
            self.mock_delegations = gd
            self.mock_inbound     = gq
            self.mock_inject      = inj
            yield

    # ── gate / fail-safe ──

    @patch( "lupin_cli.claude_code.hooks.stop.read_hold" )
    @patch( "lupin_cli.claude_code.hooks.stop.load_heartbeat_settings",
            return_value={ "enabled": False, "poke_cap": 3 } )
    def test_disabled_returns_none_no_reads( self, mock_load, mock_read ):
        assert _run_heartbeat( "sid", "/t.jsonl" ) is None
        mock_read.assert_not_called()
        self.mock_replay.assert_not_called()
        self.mock_events.emit_outcome.assert_not_called()

    @patch( "lupin_cli.claude_code.hooks.stop.log_to_stream" )
    @patch( "lupin_cli.claude_code.hooks.stop.read_hold" )
    @patch( "lupin_cli.claude_code.hooks.stop.load_heartbeat_settings",
            side_effect=ValueError( "bad poke_cap" ) )
    def test_malformed_config_fails_safe( self, mock_load, mock_read, mock_log ):
        assert _run_heartbeat( "sid", "/t.jsonl" ) is None
        mock_read.assert_not_called()
        self.mock_events.emit_outcome.assert_not_called()
        assert "heartbeat_settings_invalid" in [ c.kwargs[ "extra" ][ "phase" ] for c in mock_log.call_args_list ]

    # ── poke paths ──

    @patch( "lupin_cli.claude_code.hooks.stop.increment_poke_count" )
    @patch( "lupin_cli.claude_code.hooks.stop.get_poke_count", return_value=0 )
    @patch( "lupin_cli.claude_code.hooks.stop.read_hold", return_value=None )
    @patch( "lupin_cli.claude_code.hooks.stop.load_heartbeat_settings",
            return_value={ "enabled": True, "poke_cap": 3, "owed_source_from_store": False } )
    def test_v2_fm19_catch_no_hold_owed_task_pokes( self, mock_load, mock_read, mock_count, mock_incr ):
        """FM-19: no hold + owed Task* (in_progress) → poke (the v2 headline catch)."""
        self.mock_replay.return_value = _OWED_STATE
        out = _run_heartbeat( "sid", "/t.jsonl" )
        assert out[ "decision" ] == "block"
        assert out[ "reason" ]                                    # oracle-owed reason (quotes specifics)
        mock_incr.assert_called_once_with( "sid" )
        # emit carries the REAL work_owed=True
        _, kwargs = self.mock_events.emit_outcome.call_args
        assert kwargs[ "work_owed" ] is True
        # §4 breadcrumb rides the poke: ONE low-pri card notify with specifics
        self.mock_notify.assert_called_once()
        crumb = self.mock_notify.call_args[ 0 ][ 0 ]
        assert crumb.message  == "A worker stopped — 1 owed item, poked."
        assert crumb.priority == NotificationPriority.LOW

    @patch( "lupin_cli.claude_code.hooks.stop.increment_poke_count" )
    @patch( "lupin_cli.claude_code.hooks.stop.get_poke_count", return_value=0 )
    @patch( "lupin_cli.claude_code.hooks.stop.read_hold" )
    @patch( "lupin_cli.claude_code.hooks.stop.load_heartbeat_settings",
            return_value={ "enabled": True, "poke_cap": 3, "owed_source_from_store": False } )
    def test_v1_preserved_stale_declared_hold_pokes( self, mock_load, mock_read, mock_count, mock_incr ):
        """v1 preserved: stale self-declared-owed hold pokes even with no owed Task*."""
        mock_read.return_value       = _stale_owed_hold()
        self.mock_replay.return_value = _EMPTY_STATE
        out = _run_heartbeat( "sid", "/t.jsonl" )
        assert out == { "decision": "block", "reason": DECLARED_OWED_REASON }
        mock_incr.assert_called_once_with( "sid" )
        # §4 breadcrumb: declared-owed poke has no Task* count → self-declared text
        self.mock_notify.assert_called_once()
        crumb = self.mock_notify.call_args[ 0 ][ 0 ]
        assert crumb.message == "A worker stopped — work owed (self-declared), poked."

    # ── non-poke paths ──

    @patch( "lupin_cli.claude_code.hooks.stop.increment_poke_count" )
    @patch( "lupin_cli.claude_code.hooks.stop.get_poke_count", return_value=0 )
    @patch( "lupin_cli.claude_code.hooks.stop.read_hold" )
    @patch( "lupin_cli.claude_code.hooks.stop.load_heartbeat_settings",
            return_value={ "enabled": True, "poke_cap": 3, "owed_source_from_store": False } )
    def test_fresh_hold_honored( self, mock_load, mock_read, mock_count, mock_incr ):
        mock_read.return_value = _fresh_reasoned_hold()
        assert _run_heartbeat( "sid", "/t.jsonl" ) is None
        mock_incr.assert_not_called()
        self.mock_notify.assert_not_called()    # §4 breadcrumb rides ONLY the poke

    @patch( "lupin_cli.claude_code.hooks.stop.get_poke_count", return_value=0 )
    @patch( "lupin_cli.claude_code.hooks.stop.read_hold", return_value=None )
    @patch( "lupin_cli.claude_code.hooks.stop.load_heartbeat_settings",
            return_value={ "enabled": True, "poke_cap": 3, "owed_source_from_store": False } )
    def test_not_owed_empty_taskset_emits_idle( self, mock_load, mock_read, mock_count ):
        """not_owed + empty Task* set → genuine-idle beacon (transition)."""
        self.mock_replay.return_value = _EMPTY_STATE
        assert _run_heartbeat( "sid", "/t.jsonl" ) is None
        # idle beacon emitted (is_idle_transition True by fixture)
        self.mock_events.is_idle_transition.assert_called_once_with( "sid" )
        idle_calls = [ c for c in self.mock_events.emit_outcome.call_args_list
                       if c.args[ 2 ] == "idle" ]
        assert len( idle_calls ) == 1
        assert idle_calls[ 0 ].kwargs[ "work_owed" ] is False

    @patch( "lupin_cli.claude_code.hooks.stop.get_poke_count", return_value=0 )
    @patch( "lupin_cli.claude_code.hooks.stop.read_hold", return_value=None )
    @patch( "lupin_cli.claude_code.hooks.stop.load_heartbeat_settings",
            return_value={ "enabled": True, "poke_cap": 3, "owed_source_from_store": False } )
    def test_not_owed_nonempty_taskset_no_idle( self, mock_load, mock_read, mock_count ):
        """not_owed but tasks exist (all completed) → NOT genuine-idle → no beacon."""
        self.mock_replay.return_value = _DONE_STATE        # nothing owed, but task set NON-empty
        assert _run_heartbeat( "sid", "/t.jsonl" ) is None
        self.mock_events.is_idle_transition.assert_not_called()

    @patch( "lupin_cli.claude_code.hooks.stop._notify_cap_reached" )
    @patch( "lupin_cli.claude_code.hooks.stop.increment_poke_count" )
    @patch( "lupin_cli.claude_code.hooks.stop.get_poke_count", return_value=3 )
    @patch( "lupin_cli.claude_code.hooks.stop.read_hold", return_value=None )
    @patch( "lupin_cli.claude_code.hooks.stop.load_heartbeat_settings",
            return_value={ "enabled": True, "poke_cap": 3, "owed_source_from_store": False } )
    def test_cap_reached_notifies_no_increment( self, mock_load, mock_read, mock_count,
                                                 mock_incr, mock_notify ):
        """Owed Task* but at cap → no poke, cap FYI, no increment."""
        self.mock_replay.return_value = _OWED_STATE
        assert _run_heartbeat( "sid", "/t.jsonl" ) is None
        mock_notify.assert_called_once_with( "sid" )
        mock_incr.assert_not_called()

    # ── emit details ──

    @patch( "lupin_cli.claude_code.hooks.stop.increment_poke_count" )
    @patch( "lupin_cli.claude_code.hooks.stop.get_poke_count", return_value=1 )
    @patch( "lupin_cli.claude_code.hooks.stop.read_hold" )
    @patch( "lupin_cli.claude_code.hooks.stop.load_heartbeat_settings",
            return_value={ "enabled": True, "poke_cap": 3, "owed_source_from_store": False } )
    def test_emit_persona_and_awaiting_from_hold( self, mock_load, mock_read, mock_count, mock_incr ):
        self.mock_persona.return_value = { "name": "Rachel" }
        mock_read.return_value         = _stale_owed_hold()      # awaiting="none"
        _run_heartbeat( "sid", "/t.jsonl" )
        poke_emits = [ c for c in self.mock_events.emit_outcome.call_args_list
                       if c.args[ 2 ] == OUTCOME_POKE ]
        assert len( poke_emits ) == 1
        assert poke_emits[ 0 ].args[ 1 ] == "Rachel"            # persona resolved
        assert poke_emits[ 0 ].kwargs[ "awaiting" ] == "none"

    @patch( "lupin_cli.claude_code.hooks.stop.log_to_stream" )
    @patch( "lupin_cli.claude_code.hooks.stop.increment_poke_count" )
    @patch( "lupin_cli.claude_code.hooks.stop.get_poke_count", return_value=0 )
    @patch( "lupin_cli.claude_code.hooks.stop.read_hold", return_value=None )
    @patch( "lupin_cli.claude_code.hooks.stop.load_heartbeat_settings",
            return_value={ "enabled": True, "poke_cap": 3, "owed_source_from_store": False } )
    def test_emit_failure_never_breaks_poke( self, mock_load, mock_read, mock_count, mock_incr, mock_log ):
        """§0 #2: emission failure must NOT break the poke."""
        self.mock_replay.return_value = _OWED_STATE
        self.mock_events.emit_outcome.side_effect = RuntimeError( "disk full" )
        out = _run_heartbeat( "sid", "/t.jsonl" )
        assert out[ "decision" ] == "block"
        assert "heartbeat_emit_error" in [ c.kwargs[ "extra" ][ "phase" ] for c in mock_log.call_args_list ]

    # ── v3 live signals (Rick 2026-06-09): manager delegations + worker inbound ──

    @patch( "lupin_cli.claude_code.hooks.stop.increment_poke_count" )
    @patch( "lupin_cli.claude_code.hooks.stop.get_poke_count", return_value=0 )
    @patch( "lupin_cli.claude_code.hooks.stop.read_hold", return_value=None )
    @patch( "lupin_cli.claude_code.hooks.stop.load_heartbeat_settings",
            return_value={ "enabled": True, "poke_cap": 3, "owed_source_from_store": False } )
    def test_manager_with_alive_worker_pokes( self, mock_load, mock_read, mock_count, mock_incr ):
        """The manager bug fix: zero Task* items, one live spawned worker → poke."""
        self.mock_delegations.return_value = [ { "session_name": "cc-reviewer-x-1", "session_id": "c1" } ]
        out = _run_heartbeat( "sid", "/t.jsonl" )
        assert out[ "decision" ] == "block"
        assert "1 live worker(s) still out" in out[ "reason" ]
        _, kwargs = self.mock_events.emit_outcome.call_args
        assert kwargs[ "work_owed" ] is True

    @patch( "lupin_cli.claude_code.hooks.stop.get_poke_count", return_value=0 )
    @patch( "lupin_cli.claude_code.hooks.stop.read_hold", return_value=None )
    @patch( "lupin_cli.claude_code.hooks.stop.load_heartbeat_settings",
            return_value={ "enabled": True, "poke_cap": 3, "owed_source_from_store": False } )
    def test_manager_all_workers_reaped_idles( self, mock_load, mock_read, mock_count ):
        """All children reaped (gatherer returns []) → no delegation signal → idle path."""
        self.mock_delegations.return_value = [ ]
        assert _run_heartbeat( "sid", "/t.jsonl" ) is None

    @patch( "lupin_cli.claude_code.hooks.stop.increment_poke_count" )
    @patch( "lupin_cli.claude_code.hooks.stop.get_poke_count", return_value=0 )
    @patch( "lupin_cli.claude_code.hooks.stop.read_hold", return_value=None )
    @patch( "lupin_cli.claude_code.hooks.stop.load_heartbeat_settings",
            return_value={ "enabled": True, "poke_cap": 3, "count_inbound_questions_as_owed": True, "owed_source_from_store": False } )
    def test_worker_with_open_inbound_dm_pokes( self, mock_load, mock_read, mock_count, mock_incr ):
        """The worker fix, OPT-IN (Thread B): with count_inbound_questions_as_owed
        True, an unhandled inbound assignment DM → poke to resume/finish (the v3
        behavior, now behind the gate)."""
        self.mock_inbound.return_value = { "owed": [ { "question_id": "q1", "ts": "2026-06-10T01:00:00+00:00" } ], "stale": [ ] }
        out = _run_heartbeat( "sid", "/t.jsonl" )
        assert out[ "decision" ] == "block"
        assert "unanswered inbound question" in out[ "reason" ]
        _, kwargs = self.mock_events.emit_outcome.call_args
        assert kwargs[ "work_owed" ] is True

    @patch( "lupin_cli.claude_code.hooks.stop.increment_poke_count" )
    @patch( "lupin_cli.claude_code.hooks.stop.get_poke_count", return_value=0 )
    @patch( "lupin_cli.claude_code.hooks.stop.read_hold", return_value=None )
    @patch( "lupin_cli.claude_code.hooks.stop.load_heartbeat_settings",
            return_value={ "enabled": True, "poke_cap": 3, "count_inbound_questions_as_owed": False, "owed_source_from_store": False } )
    def test_worker_open_inbound_default_off_no_poke( self, mock_load, mock_read, mock_count, mock_incr ):
        """Thread B DEFAULT-OFF (the Rick-visible fix): the SAME unhandled inbound
        DM, with the gate key False, is gated OUT of the owed feed → NOT owed → no
        poke, no increment, no tmux injection. The arbiter's own manager-stale
        poke-DMs stop self-inflating the owed count."""
        self.mock_inbound.return_value = { "owed": [ { "question_id": "q1", "ts": "2026-06-10T01:00:00+00:00" } ], "stale": [ ] }
        assert _run_heartbeat( "sid", "/t.jsonl" ) is None
        mock_incr.assert_not_called()
        self.mock_inject.assert_not_called()

    @patch( "lupin_cli.claude_code.hooks.stop.log_to_stream" )
    @patch( "lupin_cli.claude_code.hooks.stop.get_poke_count", return_value=0 )
    @patch( "lupin_cli.claude_code.hooks.stop.read_hold", return_value=None )
    @patch( "lupin_cli.claude_code.hooks.stop.load_heartbeat_settings",
            return_value={ "enabled": True, "poke_cap": 3, "owed_source_from_store": False } )
    def test_oracle_log_carries_live_signal_counts( self, mock_load, mock_read, mock_count, mock_log ):
        """Observability: the heartbeat_oracle log line carries both new counts."""
        self.mock_delegations.return_value = [ ]
        self.mock_inbound.return_value     = { "owed": [ ], "stale": [ ] }
        _run_heartbeat( "sid", "/t.jsonl" )
        oracle = [ c.kwargs[ "extra" ] for c in mock_log.call_args_list
                   if c.kwargs[ "extra" ].get( "phase" ) == "heartbeat_oracle" ]
        assert oracle and oracle[ 0 ][ "delegations" ] == 0 and oracle[ 0 ][ "open_inbound" ] == 0

    # ── f0d79d71: tmux pairing on the poke path (exactly-one-continuation) ──────

    @patch( "lupin_cli.claude_code.hooks.stop.increment_poke_count" )
    @patch( "lupin_cli.claude_code.hooks.stop.get_poke_count", return_value=0 )
    @patch( "lupin_cli.claude_code.hooks.stop.read_hold", return_value=None )
    @patch( "lupin_cli.claude_code.hooks.stop.load_heartbeat_settings",
            return_value={ "enabled": True, "poke_cap": 3, "count_inbound_questions_as_owed": False, "owed_source_from_store": False } )
    def test_poke_pairs_block_with_single_tmux_inject( self, mock_load, mock_read, mock_count, mock_incr ):
        """f0d79d71 EXACTLY-ONE-CONTINUATION: a poke returns the decision:block
        dict (the continue receipt the caller emits ONCE) AND injects the poke
        reason VERBATIM (wrap=False) into tmux EXACTLY once. Block + one keystroke
        nudge = one continuation — never a block+tmux double-submit."""
        self.mock_replay.return_value = _OWED_STATE
        out = _run_heartbeat( "sid", "/t.jsonl" )
        assert out[ "decision" ] == "block"
        self.mock_inject.assert_called_once_with( "sid", out[ "reason" ], wrap=False )

    @patch( "lupin_cli.claude_code.hooks.stop.increment_poke_count" )
    @patch( "lupin_cli.claude_code.hooks.stop.get_poke_count", return_value=0 )
    @patch( "lupin_cli.claude_code.hooks.stop.read_hold" )
    @patch( "lupin_cli.claude_code.hooks.stop.load_heartbeat_settings",
            return_value={ "enabled": True, "poke_cap": 3, "count_inbound_questions_as_owed": False, "owed_source_from_store": False } )
    def test_no_poke_does_not_inject( self, mock_load, mock_read, mock_count, mock_incr ):
        """A fresh reasoned hold is honored → no poke → NO tmux injection."""
        mock_read.return_value = _fresh_reasoned_hold()
        assert _run_heartbeat( "sid", "/t.jsonl" ) is None
        self.mock_inject.assert_not_called()

    @patch( "lupin_cli.claude_code.hooks.stop._notify_cap_reached" )
    @patch( "lupin_cli.claude_code.hooks.stop.increment_poke_count" )
    @patch( "lupin_cli.claude_code.hooks.stop.get_poke_count", return_value=3 )
    @patch( "lupin_cli.claude_code.hooks.stop.read_hold", return_value=None )
    @patch( "lupin_cli.claude_code.hooks.stop.load_heartbeat_settings",
            return_value={ "enabled": True, "poke_cap": 3, "count_inbound_questions_as_owed": False, "owed_source_from_store": False } )
    def test_cap_reached_does_not_inject( self, mock_load, mock_read, mock_count, mock_incr, mock_cap ):
        """Re-entry bound: owed Task* but poke_cap reached → no poke → NO injection.
        The cap is the guard that stops a re-fire from double-injecting."""
        self.mock_replay.return_value = _OWED_STATE
        assert _run_heartbeat( "sid", "/t.jsonl" ) is None
        self.mock_inject.assert_not_called()

    @patch( "lupin_cli.claude_code.hooks.stop.decide_heartbeat" )
    @patch( "lupin_cli.claude_code.hooks.stop.increment_poke_count" )
    @patch( "lupin_cli.claude_code.hooks.stop.get_poke_count", return_value=0 )
    @patch( "lupin_cli.claude_code.hooks.stop.read_hold", return_value=None )
    @patch( "lupin_cli.claude_code.hooks.stop.load_heartbeat_settings",
            return_value={ "enabled": True, "poke_cap": 3, "count_inbound_questions_as_owed": False, "owed_source_from_store": False } )
    def test_poke_empty_reason_skips_inject( self, mock_load, mock_read, mock_count, mock_incr, mock_decide ):
        """Defensive `if poke_reason` False arm: a poke whose hook_output carries an
        empty reason does NOT inject (inject requires non-empty text), yet still
        returns the block. Reason is contract-guaranteed non-empty in production —
        this exercises the guard's false branch explicitly (no pragma needed)."""
        mock_decide.return_value = {
            "outcome": OUTCOME_POKE, "should_increment": True, "should_notify_cap": False,
            "hook_output": { "decision": "block", "reason": "" },
        }
        self.mock_replay.return_value = _OWED_STATE
        out = _run_heartbeat( "sid", "/t.jsonl" )
        assert out == { "decision": "block", "reason": "" }
        self.mock_inject.assert_not_called()


# ═════════════════════════════════════════════════════════════════════════════
# _gather_outstanding_delegations — manager-side live IO shell (v3)
# ═════════════════════════════════════════════════════════════════════════════

class TestGatherOutstandingDelegations:

    def _bridge_file( self, tmp_path, name, tmux ):
        p = tmp_path / name
        p.write_text( __import__( "json" ).dumps( { "tmux_session": tmux } ) )
        return p

    @patch( "lupin_cli.claude_code.hooks.stop.find_active_voice_persona_sessions" )
    @patch( "lupin_mcp.session_spawner._read_manifest" )
    def test_alive_child_returned( self, mock_manifest, mock_disc, tmp_path ):
        from lupin_cli.claude_code.hooks.stop import _gather_outstanding_delegations
        mock_manifest.return_value = [ { "session_name": "cc-reviewer-x-1" } ]
        mock_disc.return_value     = [ ( self._bridge_file( tmp_path, "b1.json", "cc-reviewer-x-1" ), "c1", { } ) ]
        out = _gather_outstanding_delegations( "mgr-sid" )
        assert out == [ { "session_name": "cc-reviewer-x-1", "session_id": "c1" } ]

    @patch( "lupin_cli.claude_code.hooks.stop.find_active_voice_persona_sessions" )
    @patch( "lupin_mcp.session_spawner._read_manifest", return_value=[ ] )
    def test_no_manifest_skips_bridge_scan( self, mock_manifest, mock_disc ):
        """Workers (no manifest) pay one manifest read per Stop — no bridge scan."""
        from lupin_cli.claude_code.hooks.stop import _gather_outstanding_delegations
        assert _gather_outstanding_delegations( "worker-sid" ) == [ ]
        mock_disc.assert_not_called()

    @patch( "lupin_cli.claude_code.hooks.stop.find_active_voice_persona_sessions" )
    @patch( "lupin_mcp.session_spawner._read_manifest" )
    def test_dead_child_excluded( self, mock_manifest, mock_disc, tmp_path ):
        """A manifest child with no live bridge (reaped/crashed) is NOT outstanding."""
        from lupin_cli.claude_code.hooks.stop import _gather_outstanding_delegations
        mock_manifest.return_value = [ { "session_name": "cc-reviewer-x-1" } ]
        mock_disc.return_value     = [ ( self._bridge_file( tmp_path, "b1.json", "cc-OTHER-9" ), "z9", { } ) ]
        assert _gather_outstanding_delegations( "mgr-sid" ) == [ ]

    @patch( "lupin_cli.claude_code.hooks.stop.find_active_voice_persona_sessions" )
    @patch( "lupin_mcp.session_spawner._read_manifest" )
    def test_unreadable_or_non_dict_bridge_skipped( self, mock_manifest, mock_disc, tmp_path ):
        from lupin_cli.claude_code.hooks.stop import _gather_outstanding_delegations
        mock_manifest.return_value = [ { "session_name": "cc-reviewer-x-1" }, "not-a-dict", { } ]
        listfile = tmp_path / "list.json"
        listfile.write_text( "[]" )                              # parses, but not a dict
        mock_disc.return_value = [
            ( tmp_path / "absent.json", "a1", { } ),             # open fails → skipped
            ( listfile, "a2", { } ),                             # non-dict → tmux None
        ]
        assert _gather_outstanding_delegations( "mgr-sid" ) == [ ]

    @patch( "lupin_cli.claude_code.hooks.stop.find_active_voice_persona_sessions",
            side_effect=RuntimeError( "discovery exploded" ) )
    @patch( "lupin_mcp.session_spawner._read_manifest" )
    def test_degrade_safe_on_any_error( self, mock_manifest, mock_disc ):
        from lupin_cli.claude_code.hooks.stop import _gather_outstanding_delegations
        mock_manifest.return_value = [ { "session_name": "cc-reviewer-x-1" } ]
        assert _gather_outstanding_delegations( "mgr-sid" ) == [ ]


# ═════════════════════════════════════════════════════════════════════════════
# _gather_unanswered_inbound_questions — worker-side live IO shell (v3)
# ═════════════════════════════════════════════════════════════════════════════

MY_SID = "6acfa341-1dcd-4240-96d5-9bc39ae58861"

# Pinned "now" for the gatherer's age-out partition (spec (e)). Fixed 30 min
# after the default _dm ts so date-pinned fixtures stay FRESH regardless of when
# the suite runs (the gatherer's time.time() is mocked to this in _run/_run_full).
_NOW_EPOCH = datetime.datetime( 2026, 6, 10, 2, 0, 0, tzinfo=UTC ).timestamp()


def _dm( qid, sender="7b76ad86", ts="2026-06-10T01:30:00+00:00", in_reply_to=None, with_md=True ):
    md = { }
    if qid:
        md[ "question_id" ] = qid
    if in_reply_to:
        md[ "in_reply_to" ] = in_reply_to
    return { "sender_session_id": sender, "ts": ts, "body": "x",
             "metadata": ( md if with_md else None ) }


class TestGatherUnansweredInbound:

    def _run( self, entries, persona=None, monkeypatch=None ):
        from lupin_cli.claude_code.hooks.stop import _gather_unanswered_inbound_questions
        persona = persona if persona is not None else { "name": "mr radio" }
        store   = MagicMock()
        store.read.return_value = entries
        with patch( "lupin_cli.claude_code.hooks.stop.get_voice_persona", return_value=persona ), \
             patch( "lupin_cli.claude_code.hooks.stop.time.time", return_value=_NOW_EPOCH ), \
             patch( "lupin_mcp.commons_store.CommonsStore", return_value=store ) as cs:
            out = _gather_unanswered_inbound_questions( MY_SID )
        if entries is not None and persona and persona.get( "name" ):
            cs.assert_called_once()
            assert store.read.call_args[ 0 ][ 0 ] == "dm-mr_radio"
        return out[ "owed" ]

    def _run_full( self, entries, persona=None, acked=None ):
        """Like _run but returns the whole { owed, stale } dict (age/ledger tests)."""
        from lupin_cli.claude_code.hooks.stop import _gather_unanswered_inbound_questions
        persona = persona if persona is not None else { "name": "mr radio" }
        store   = MagicMock()
        store.read.return_value = entries
        with patch( "lupin_cli.claude_code.hooks.stop.get_voice_persona", return_value=persona ), \
             patch( "lupin_cli.claude_code.hooks.stop.time.time", return_value=_NOW_EPOCH ), \
             patch( "lupin_cli.claude_code.hooks.stop.read_acked_qids", return_value=set( acked or [ ] ) ), \
             patch( "lupin_mcp.commons_store.CommonsStore", return_value=store ):
            return _gather_unanswered_inbound_questions( MY_SID )

    def test_open_inbound_dm_is_owed( self ):
        out = self._run( [ _dm( "q1" ) ] )
        assert out == [ { "question_id": "q1", "ts": "2026-06-10T01:30:00+00:00", "sender": "7b76ad86" } ]

    def test_broadened_rule_no_kind_required( self ):
        """Rick's broadening: ANY inbound DM counts — no kind=question filter."""
        entry = _dm( "q1" )
        entry[ "metadata" ][ "kind" ] = "arbiter-ping"           # not a question
        assert len( self._run( [ entry ] ) ) == 1

    def test_handled_by_my_threaded_reply_not_owed( self ):
        entries = [
            _dm( "q1" ),
            _dm( None, sender=MY_SID[ :8 ], in_reply_to="q1" ),  # my short-id reply
        ]
        assert self._run( entries ) == [ ]

    def test_peer_reply_does_not_count_as_mine( self ):
        """Handled = a threaded reply from THIS session — a third party's doesn't clear it."""
        entries = [ _dm( "q1" ), _dm( None, sender="42954f0b", in_reply_to="q1" ) ]
        assert len( self._run( entries ) ) == 1

    def test_my_own_posts_are_not_inbound( self ):
        assert self._run( [ _dm( "q9", sender=MY_SID[ :8 ] ) ] ) == [ ]

    def test_qid_less_and_md_less_entries_untrackable( self ):
        assert self._run( [ _dm( None ), _dm( None, with_md=False ), "not-a-dict" ] ) == [ ]

    def test_tenure_floor_excludes_prior_holder_debt( self ):
        """A prior persona-holder's unanswered brief must not poke this session."""
        persona = { "name": "mr radio", "assigned_at": "2026-06-10T00:17:34+00:00" }
        entries = [ _dm( "old", ts="2026-06-09T23:51:13+00:00" ),    # prior tenure
                    _dm( "new", ts="2026-06-10T01:29:26+00:00" ) ]   # mine
        out = self._run( entries, persona=persona )
        assert [ e[ "question_id" ] for e in out ] == [ "new" ]

    def test_missing_assigned_at_disables_floor( self ):
        # No assigned_at ⇒ the tenure floor is OFF, so the ancient DM is still
        # CONSIDERED (not floor-dropped). Being ancient it ages out to `stale`
        # (review, not owed) rather than vanishing — that surfacing is the proof
        # the floor was disabled (a floor would have excluded it entirely).
        full = self._run_full( [ _dm( "old", ts="2020-01-01T00:00:00+00:00" ) ] )
        assert full[ "owed" ] == [ ]
        assert [ e[ "question_id" ] for e in full[ "stale" ] ] == [ "old" ]

    # ── acked-inbound ledger spec parts (Rick 2026-06-10) ──────────────────────

    def test_expect_reply_false_never_owed( self ):
        """(a) fire-and-forget acks/verdicts (expect_reply=False) are NOT owed."""
        e = _dm( "q1" )
        e[ "metadata" ][ "expect_reply" ] = False
        full = self._run_full( [ e ] )
        assert full[ "owed" ] == [ ] and full[ "stale" ] == [ ]

    def test_expect_reply_true_is_owed( self ):
        """(a) an explicit expect_reply=True genuine question stays owed."""
        e = _dm( "q1" )
        e[ "metadata" ][ "expect_reply" ] = True
        assert [ q[ "question_id" ] for q in self._run( [ e ] ) ] == [ "q1" ]

    def test_expect_reply_missing_stays_owed( self ):
        """(a) a MISSING expect_reply (older-format DM) is owed — bias-to-poke."""
        assert [ q[ "question_id" ] for q in self._run( [ _dm( "q1" ) ] ) ] == [ "q1" ]

    def test_acked_qid_subtracted( self ):
        """(c) a qid in the looked-at ledger is cleared from owed."""
        full = self._run_full( [ _dm( "q1" ), _dm( "q2" ) ], acked=[ "q1" ] )
        assert [ q[ "question_id" ] for q in full[ "owed" ] ] == [ "q2" ]

    def test_aged_out_inbound_is_stale_not_owed( self ):
        """(e) an un-handled DM older than the threshold surfaces as stale."""
        full = self._run_full( [ _dm( "fresh", ts="2026-06-10T01:45:00+00:00" ),
                                 _dm( "old",   ts="2026-06-08T00:00:00+00:00" ) ] )
        assert [ q[ "question_id" ] for q in full[ "owed" ] ]  == [ "fresh" ]
        assert [ q[ "question_id" ] for q in full[ "stale" ] ] == [ "old" ]

    def test_acceptance_backlog_collapses_to_genuinely_owed( self ):
        """ACCEPTANCE (Rick 2026-06-10): a manager inbox of mostly serviced
        acks/verdicts + old/looked-at items collapses to ONLY the genuinely
        -awaiting few (~0-3), not the raw inbound count (the 46 → ~0-3 fix).

        12 inbound DMs:
          - 6 fire-and-forget acks/verdicts (expect_reply=False)   → (a) dropped
          - 2 genuine questions already answered by my threaded reply → (b) cleared
          - 1 genuine question the manager bulk-marked looked-at      → (c) acked
          - 2 genuine questions older than the age threshold          → (e) stale
          - 1 genuine, fresh, reply-expected question                 → OWED
        Net: owed == 1 (was 12 under the old count-every-qid rule).
        """
        def _ack( i ):
            e = _dm( f"ack{i}", ts="2026-06-10T01:50:00+00:00" )
            e[ "metadata" ][ "expect_reply" ] = False
            return e
        entries = [ _ack( i ) for i in range( 6 ) ] + [
            _dm( "answered1", ts="2026-06-10T01:50:00+00:00" ),
            _dm( "answered2", ts="2026-06-10T01:50:00+00:00" ),
            _dm( None, sender=MY_SID[ :8 ], in_reply_to="answered1" ),   # my reply (b)
            _dm( None, sender=MY_SID[ :8 ], in_reply_to="answered2" ),   # my reply (b)
            _dm( "lookedat", ts="2026-06-10T01:50:00+00:00" ),           # (c)
            _dm( "stale1", ts="2026-06-07T00:00:00+00:00" ),             # (e)
            _dm( "stale2", ts="2026-06-06T00:00:00+00:00" ),             # (e)
            _dm( "OWED",   ts="2026-06-10T01:55:00+00:00" ),             # genuinely owed
        ]
        full = self._run_full( entries, acked=[ "lookedat" ] )
        assert [ q[ "question_id" ] for q in full[ "owed" ] ] == [ "OWED" ]
        assert sorted( q[ "question_id" ] for q in full[ "stale" ] ) == [ "stale1", "stale2" ]

    def test_no_persona_returns_empty( self ):
        assert self._run( [ _dm( "q1" ) ], persona={ } ) == [ ]

    def test_no_lupin_root_returns_empty( self, monkeypatch ):
        from lupin_cli.claude_code.hooks.stop import _gather_unanswered_inbound_questions
        monkeypatch.delenv( "LUPIN_ROOT", raising=False )
        with patch( "lupin_cli.claude_code.hooks.stop.get_voice_persona",
                    return_value={ "name": "mr radio" } ):
            assert _gather_unanswered_inbound_questions( MY_SID ) == { "owed": [ ], "stale": [ ] }

    def test_degrade_safe_on_store_error( self ):
        from lupin_cli.claude_code.hooks.stop import _gather_unanswered_inbound_questions
        with patch( "lupin_cli.claude_code.hooks.stop.get_voice_persona",
                    return_value={ "name": "mr radio" } ), \
             patch( "lupin_mcp.commons_store.CommonsStore",
                    side_effect=RuntimeError( "store exploded" ) ):
            assert _gather_unanswered_inbound_questions( MY_SID ) == { "owed": [ ], "stale": [ ] }


class TestDmTopicFor:

    def test_space_collapses_to_underscore( self ):
        from lupin_cli.claude_code.hooks.stop import _dm_topic_for
        assert _dm_topic_for( "mr radio" ) == "dm-mr_radio"

    def test_lowercases_and_strips( self ):
        from lupin_cli.claude_code.hooks.stop import _dm_topic_for
        assert _dm_topic_for( " Tiberius " ) == "dm-tiberius"

    def test_unicode_persona_survives( self ):
        from lupin_cli.claude_code.hooks.stop import _dm_topic_for
        assert _dm_topic_for( "María" ) == "dm-maría"


class TestIsSameSession:

    def test_prefix_tolerant_both_directions_and_falsy( self ):
        from lupin_cli.claude_code.hooks.stop import _is_same_session
        assert _is_same_session( MY_SID[ :8 ], MY_SID ) is True
        assert _is_same_session( MY_SID, MY_SID[ :8 ] ) is True
        assert _is_same_session( MY_SID, MY_SID ) is True
        assert _is_same_session( "7b76ad86", MY_SID ) is False
        assert _is_same_session( None, MY_SID ) is False
        assert _is_same_session( MY_SID, "" ) is False


# ═════════════════════════════════════════════════════════════════════════════
# _emit_genuine_idle — the §6.2 beacon (edge-trigger gate delegated)
# ═════════════════════════════════════════════════════════════════════════════

class TestEmitGenuineIdle:

    @patch( "lupin_cli.claude_code.hooks.stop.get_poke_count", return_value=0 )
    @patch( "lupin_cli.claude_code.hooks.stop.heartbeat_events" )
    def test_emits_on_transition( self, mock_ev, mock_count ):
        mock_ev.EVENT_IDLE = "idle"
        mock_ev.is_idle_transition.return_value = True
        _emit_genuine_idle( "sid", "Rachel", 3 )
        mock_ev.emit_outcome.assert_called_once()
        args, kwargs = mock_ev.emit_outcome.call_args
        assert args[ 0 ] == "sid" and args[ 1 ] == "Rachel" and args[ 2 ] == "idle"
        assert kwargs[ "work_owed" ] is False and kwargs[ "awaiting" ] is None

    @patch( "lupin_cli.claude_code.hooks.stop.get_poke_count", return_value=0 )
    @patch( "lupin_cli.claude_code.hooks.stop.heartbeat_events" )
    def test_skips_when_already_idle( self, mock_ev, mock_count ):
        mock_ev.is_idle_transition.return_value = False
        _emit_genuine_idle( "sid", "Rachel", 3 )
        mock_ev.emit_outcome.assert_not_called()

    @patch( "lupin_cli.claude_code.hooks.stop.log_to_stream" )
    @patch( "lupin_cli.claude_code.hooks.stop.get_poke_count", return_value=0 )
    @patch( "lupin_cli.claude_code.hooks.stop.heartbeat_events" )
    def test_failure_never_raises( self, mock_ev, mock_count, mock_log ):
        mock_ev.is_idle_transition.side_effect = RuntimeError( "events unreadable" )
        _emit_genuine_idle( "sid", "Rachel", 3 )   # must not raise
        assert "heartbeat_idle_emit_error" in [ c.kwargs[ "extra" ][ "phase" ] for c in mock_log.call_args_list ]


# ═════════════════════════════════════════════════════════════════════════════
# _notify_cap_reached — log-only FYI
# ═════════════════════════════════════════════════════════════════════════════

class TestNotifyCapReached:

    @patch( "lupin_cli.claude_code.hooks.stop.get_poke_count", return_value=3 )
    @patch( "lupin_cli.claude_code.hooks.stop.log_to_stream" )
    def test_logs_session_and_count( self, mock_log, mock_count ):
        _notify_cap_reached( "sid42" )
        assert mock_log.call_count == 1
        extra = mock_log.call_args.kwargs[ "extra" ]
        assert extra[ "phase" ] == "heartbeat_cap_reached"
        assert extra[ "session_id" ] == "sid42"
        assert extra[ "poke_count" ] == 3


# ═════════════════════════════════════════════════════════════════════════════
# main() — Branch-C wiring (threads transcript_path)
# ═════════════════════════════════════════════════════════════════════════════

class TestMainBranchCWiring:

    @patch( "lupin_cli.claude_code.hooks.stop.load_idle_settings" )
    @patch( "lupin_cli.claude_code.hooks.stop._run_heartbeat",
            return_value={ "decision": "block", "reason": "poke!" } )
    @patch( "lupin_cli.claude_code.hooks.stop.reset_stop_block_count" )
    @patch( "lupin_cli.claude_code.hooks.stop.emit_json" )
    @patch( "lupin_cli.claude_code.hooks.stop.drain_and_acknowledge", return_value=[] )
    @patch( "lupin_cli.claude_code.hooks.stop.get_speakerphone", return_value=False )
    @patch( "lupin_cli.claude_code.hooks.stop.resolve_stable_session_id", side_effect=lambda x: x )
    @patch( "lupin_cli.claude_code.hooks.stop.log_payload" )
    @patch( "lupin_cli.claude_code.hooks.stop.read_hook_input" )
    def test_poke_emits_block_skips_idle_passes_transcript( self, mock_read, mock_log, mock_resolve,
                                                            mock_sp, mock_drain, mock_emit,
                                                            mock_reset, mock_hb, mock_idle ):
        mock_read.return_value = {
            "stop_hook_active": False, "session_id": "abc12345",
            "transcript_path": "/home/u/.claude/projects/p/abc.jsonl",
        }
        main()
        mock_emit.assert_called_once_with( { "decision": "block", "reason": "poke!" } )
        mock_hb.assert_called_once_with( "abc12345", "/home/u/.claude/projects/p/abc.jsonl" )
        mock_idle.assert_not_called()

    @patch( "lupin_cli.claude_code.hooks.stop._stop_hook_idle_behavior", return_value="ask" )
    @patch( "lupin_cli.claude_code.hooks.stop._arm_idle_waiter" )
    @patch( "lupin_cli.claude_code.hooks.stop.load_idle_settings",
            return_value={ "enabled": True, "backoff_minutes": [ 5 ] } )
    @patch( "lupin_cli.claude_code.hooks.stop._run_heartbeat", return_value=None )
    @patch( "lupin_cli.claude_code.hooks.stop.reset_stop_block_count" )
    @patch( "lupin_cli.claude_code.hooks.stop.emit_json" )
    @patch( "lupin_cli.claude_code.hooks.stop.drain_and_acknowledge", return_value=[] )
    @patch( "lupin_cli.claude_code.hooks.stop.get_speakerphone", return_value=False )
    @patch( "lupin_cli.claude_code.hooks.stop.resolve_stable_session_id", side_effect=lambda x: x )
    @patch( "lupin_cli.claude_code.hooks.stop.log_payload" )
    @patch( "lupin_cli.claude_code.hooks.stop.read_hook_input" )
    def test_no_poke_falls_through_to_idle( self, mock_read, mock_log, mock_resolve,
                                            mock_sp, mock_drain, mock_emit, mock_reset,
                                            mock_hb, mock_idle, mock_arm, mock_behavior ):
        """Idle behavior 'ask' + no poke + idle enabled → arm the deferred waiter, allow stop."""
        mock_read.return_value = { "stop_hook_active": False, "session_id": "abc12345" }   # no transcript_path key
        main()
        mock_hb.assert_called_once_with( "abc12345", None )   # missing key → None threaded
        mock_arm.assert_called_once()
        mock_emit.assert_called_once_with( {} )


# ═════════════════════════════════════════════════════════════════════════════
# main() — §3 speakerphone poke matrix (the :990 split, 2026-06-09)
#
# Regression-guards the order-of-operations bug where the all-or-nothing
# speakerphone early-exit bailed 75 lines upstream of _run_heartbeat, so NO
# speakerphone session (i.e. every manager) was ever poked. Post-split:
# speakerphone suppresses ONLY the blocking "Anything else?" ask — the poke
# and the breadcrumb run; the loop guard + voice-wins invariants hold.
# ═════════════════════════════════════════════════════════════════════════════

class TestMainSpeakerphonePokeMatrix:

    def _patches( self, *, payload, pending_voice=False, heartbeat_output=None,
                  idle_behavior="idle_announce", persona=None ):
        """One ExitStack-style patch bundle for the speakerphone matrix."""
        from contextlib import ExitStack
        stack = ExitStack()
        p     = lambda target, **kw: stack.enter_context(
                    patch( f"lupin_cli.claude_code.hooks.stop.{target}", **kw ) )
        mocks = {
            "read"          : p( "read_hook_input", return_value=payload ),
            "log_payload"   : p( "log_payload" ),
            "log_stream"    : p( "log_to_stream" ),
            "resolve"       : p( "resolve_stable_session_id", side_effect=lambda x: x ),
            "speakerphone"  : p( "get_speakerphone", return_value=True ),
            "auto_narrate"  : p( "_try_auto_narrate" ),
            "voice_peek"    : p( "_has_pending_voice", return_value=pending_voice ),
            "heartbeat"     : p( "_run_heartbeat", return_value=heartbeat_output ),
            "idle_behavior" : p( "_stop_hook_idle_behavior", return_value=idle_behavior ),
            "persona"       : p( "get_voice_persona", return_value=persona ),
            "announce_idle" : p( "_announce_idle" ),
            "emit"          : p( "emit_json" ),
            "drain"         : p( "drain_and_acknowledge" ),
            "deliver_dms"   : p( "deliver_pending_peer_dms", return_value=[] ),
            "ask"           : p( "_ask_anything_else" ),
            "arm_waiter"    : p( "_arm_idle_waiter" ),
            "notify_sync"   : p( "notify_user_sync" ),
        }
        return stack, mocks

    _POKE = { "decision": "block", "reason": "Do not stop yet — owed Task work." }

    def test_speakerphone_owed_pokes( self ):
        """REGRESSION GUARD (brief §2): speakerphone ON + stopped-with-owed →
        the POKE FIRES — emit the block dict, return (heartbeat owns the stop),
        skip the idle announce. Pre-split this was unreachable."""
        payload = { "stop_hook_active": False, "session_id": "abc12345",
                    "transcript_path": "/t.jsonl" }
        stack, m = self._patches( payload=payload, heartbeat_output=dict( self._POKE ) )
        with stack:
            main()   # returns (no sys.exit) — the poke path mirrors Branch C
            m[ "heartbeat" ].assert_called_once_with( "abc12345", "/t.jsonl" )
            m[ "emit" ].assert_called_once_with( self._POKE )
            m[ "announce_idle" ].assert_not_called()
            # the split is observable in the log stream
            phases = [ c.kwargs[ "extra" ][ "phase" ] for c in m[ "log_stream" ].call_args_list ]
            assert "speakerphone_poke" in phases
            assert "speakerphone_skip" not in phases
            # interactive surfaces stay suppressed
            m[ "drain" ].assert_not_called()
            m[ "notify_sync" ].assert_not_called()
            m[ "ask" ].assert_not_called()

    def test_speakerphone_not_owed_no_poke_idle_announces( self ):
        """speakerphone ON + nothing owed → NO poke; the silent idle announce
        (2026-06-08 behavior) still fires; stop allowed."""
        payload  = { "stop_hook_active": False, "session_id": "abc12345" }
        stack, m = self._patches( payload=payload, heartbeat_output=None,
                                  persona={ "name": "Rachel" } )
        with stack:
            with pytest.raises( SystemExit ):
                main()
            m[ "heartbeat" ].assert_called_once_with( "abc12345", None )
            m[ "announce_idle" ].assert_called_once_with( "abc12345", "Rachel" )
            m[ "emit" ].assert_called_once_with( {} )

    def test_speakerphone_blocking_ask_still_suppressed( self ):
        """speakerphone ON + idle behavior 'ask' → the blocking 'Anything
        else?' path stays FULLY suppressed (the preserved half of the :990
        intent): no waiter, no ask, no sync notify."""
        payload  = { "stop_hook_active": False, "session_id": "abc12345" }
        stack, m = self._patches( payload=payload, heartbeat_output=None,
                                  idle_behavior="ask" )
        with stack:
            with pytest.raises( SystemExit ):
                main()
            m[ "arm_waiter" ].assert_not_called()
            m[ "ask" ].assert_not_called()
            m[ "notify_sync" ].assert_not_called()
            m[ "announce_idle" ].assert_not_called()   # gated to idle_announce only
            m[ "emit" ].assert_called_once_with( {} )

    def test_speakerphone_refire_never_pokes( self ):
        """Loop-guard invariant: stop_hook_active=True (re-fire after a block)
        → NEVER poke, exit silently BEFORE the heartbeat; auto-narrate (own
        per-turn dedup) still ran upstream."""
        payload  = { "stop_hook_active": True, "session_id": "abc12345" }
        stack, m = self._patches( payload=payload, heartbeat_output=dict( self._POKE ) )
        with stack:
            with pytest.raises( SystemExit ):
                main()
            m[ "heartbeat" ].assert_not_called()
            m[ "auto_narrate" ].assert_called_once_with( "abc12345", payload )
            m[ "announce_idle" ].assert_not_called()
            m[ "emit" ].assert_called_once_with( {} )

    def test_speakerphone_pending_voice_suppresses_poke( self ):
        """§6a: a pending buffered peer DM → NO poke; the DM is DELIVERED via
        deliver_pending_peer_dms (drain + tmux-wake, no voice rider), then the
        stop is allowed. (Pre-§6a the speakerphone branch peeked-and-left,
        losing the DM until idle_prompt — every manager runs speakerphone.)"""
        payload  = { "stop_hook_active": False, "session_id": "abc12345" }
        stack, m = self._patches( payload=payload, pending_voice=True,
                                  heartbeat_output=dict( self._POKE ) )
        with stack:
            main()   # returns (no sys.exit) — mirrors the poke early-exit
            m[ "heartbeat" ].assert_not_called()                       # pending ⇒ poke suppressed
            m[ "deliver_dms" ].assert_called_once_with( "abc12345" )   # the DM is delivered
            m[ "announce_idle" ].assert_not_called()                   # delivery path, not idle path
            m[ "emit" ].assert_called_once_with( {} )
            phases = [ c.kwargs[ "extra" ][ "phase" ] for c in m[ "log_stream" ].call_args_list ]
            assert "speakerphone_peer_dm_deliver" in phases

    def test_speakerphone_auto_narrate_error_never_blocks_poke( self ):
        """A raising auto-narrate is swallowed (logged) and the poke still
        fires — the safety net is never a dependency of the heartbeat."""
        payload  = { "stop_hook_active": False, "session_id": "abc12345",
                     "transcript_path": "/t.jsonl" }
        stack, m = self._patches( payload=payload, heartbeat_output=dict( self._POKE ) )
        with stack:
            m[ "auto_narrate" ].side_effect = RuntimeError( "transcript unreadable" )
            main()
            phases = [ c.kwargs[ "extra" ][ "phase" ] for c in m[ "log_stream" ].call_args_list ]
            assert "auto_narrate_error" in phases
            m[ "emit" ].assert_called_once_with( self._POKE )

    def test_speakerphone_poke_composition_breadcrumb_fires( self ):
        """§3+§4 composition over the REAL adapter: speakerphone main() with
        the real _run_heartbeat (leaves stubbed to owed-under-cap) emits the
        block AND fires the §4 breadcrumb — poke + breadcrumb in speakerphone,
        end to end."""
        payload = { "stop_hook_active": False, "session_id": "abc12345",
                    "transcript_path": "/t.jsonl" }
        with patch( "lupin_cli.claude_code.hooks.stop.read_hook_input", return_value=payload ), \
             patch( "lupin_cli.claude_code.hooks.stop.log_payload" ), \
             patch( "lupin_cli.claude_code.hooks.stop.log_to_stream" ), \
             patch( "lupin_cli.claude_code.hooks.stop.resolve_stable_session_id", side_effect=lambda x: x ), \
             patch( "lupin_cli.claude_code.hooks.stop.get_speakerphone", return_value=True ), \
             patch( "lupin_cli.claude_code.hooks.stop._try_auto_narrate" ), \
             patch( "lupin_cli.claude_code.hooks.stop._has_pending_voice", return_value=False ), \
             patch( "lupin_cli.claude_code.hooks.stop.load_heartbeat_settings",
                    return_value={ "enabled": True, "poke_cap": 3, "owed_source_from_store": False } ), \
             patch( "lupin_cli.claude_code.hooks.stop.read_hold", return_value=None ), \
             patch( "lupin_cli.claude_code.hooks.stop.get_poke_count", return_value=0 ), \
             patch( "lupin_cli.claude_code.hooks.stop.increment_poke_count" ), \
             patch( "lupin_cli.claude_code.hooks.stop.replay_task_state",
                    return_value={ "1": "in_progress", "2": "pending" } ), \
             patch( "lupin_cli.claude_code.hooks.stop.heartbeat_events" ), \
             patch( "lupin_cli.claude_code.hooks.stop.get_voice_persona",
                    return_value={ "name": "Tiberius" } ), \
             patch( "lupin_cli.claude_code.hooks.stop._gather_outstanding_delegations",
                    return_value=[] ), \
             patch( "lupin_cli.claude_code.hooks.stop._gather_unanswered_inbound_questions",
                    return_value={ "owed": [ ], "stale": [ ] } ), \
             patch( "lupin_cli.claude_code.hooks.stop.build_sender_id_for_cc",
                    return_value="claude.code@lupin.deepily.ai#abc12345" ), \
             patch( "lupin_cli.claude_code.hooks.stop.inject_qualifier_via_tmux" ) as mock_inject, \
             patch( "lupin_cli.claude_code.hooks.stop.notify_user_async" ) as mock_async, \
             patch( "lupin_cli.claude_code.hooks.stop.emit_json" ) as mock_emit:
            main()
            emitted = mock_emit.call_args[ 0 ][ 0 ]
            assert emitted[ "decision" ] == "block"             # the poke owns the stop
            mock_async.assert_called_once()                     # the breadcrumb fired
            crumb = mock_async.call_args[ 0 ][ 0 ]
            assert crumb.message  == "Tiberius stopped — 2 owed items, poked."
            assert crumb.priority == NotificationPriority.LOW   # silent card bubble — no double-speak
            # f0d79d71 end-to-end in speakerphone: the block is paired with EXACTLY
            # ONE verbatim tmux nudge (wrap=False) — the continuation actually fires.
            mock_inject.assert_called_once_with( "abc12345", emitted[ "reason" ], wrap=False )


# ═════════════════════════════════════════════════════════════════════════════
# _poke_sentence / _announce_poke — the §4 breadcrumb leaf + shell
# ═════════════════════════════════════════════════════════════════════════════

class TestPokeSentence:

    def test_singular_count( self ):
        assert _poke_sentence( "Krishna", 1 ) == "Krishna stopped — 1 owed item, poked."

    def test_plural_count( self ):
        assert _poke_sentence( "Krishna", 2 ) == "Krishna stopped — 2 owed items, poked."

    def test_zero_count_self_declared( self ):
        """A hold-declared poke has no oracle specifics to count."""
        assert _poke_sentence( "Krishna", 0 ) == "Krishna stopped — work owed (self-declared), poked."

    def test_missing_persona( self ):
        assert _poke_sentence( None, 3 ) == "A worker stopped — 3 owed items, poked."


class TestAnnouncePoke:

    @patch( "lupin_cli.claude_code.hooks.stop.build_sender_id_for_cc",
            return_value="claude.code@lupin.deepily.ai#abc12345" )
    @patch( "lupin_cli.claude_code.hooks.stop.notify_user_async" )
    def test_posts_low_priority_persona_notify( self, mock_notify, mock_sender ):
        _announce_poke( "abc12345", "Rio", 2 )
        mock_notify.assert_called_once()
        request = mock_notify.call_args[ 0 ][ 0 ]
        assert request.message   == "Rio stopped — 2 owed items, poked."
        assert request.priority  == NotificationPriority.LOW
        assert request.sender_id == "claude.code@lupin.deepily.ai#abc12345"

    @patch( "lupin_cli.claude_code.hooks.stop.log_to_stream" )
    @patch( "lupin_cli.claude_code.hooks.stop.build_sender_id_for_cc", return_value="x" )
    @patch( "lupin_cli.claude_code.hooks.stop.notify_user_async",
            side_effect=RuntimeError( "server down" ) )
    def test_failsafe_swallows_errors( self, mock_notify, mock_sender, mock_log ):
        # Must NOT raise — the breadcrumb can never block (or break) the poke.
        _announce_poke( "abc12345", "Rio", 2 )
        mock_log.assert_called_once()
        assert mock_log.call_args[ 1 ][ "extra" ][ "phase" ] == "poke_announce_error"

    @patch( "lupin_cli.claude_code.hooks.stop.build_sender_id_for_cc",
            return_value="claude.code@lupin.deepily.ai#abc12345" )
    @patch( "lupin_cli.claude_code.hooks.stop.notify_user_async" )
    def test_uses_provided_receipts_abstract( self, mock_notify, mock_sender ):
        _announce_poke( "abc12345", "Rio", 2, abstract="RECEIPTS HERE" )
        assert mock_notify.call_args[ 0 ][ 0 ].abstract == "RECEIPTS HERE"

    @patch( "lupin_cli.claude_code.hooks.stop.build_sender_id_for_cc",
            return_value="claude.code@lupin.deepily.ai#abc12345" )
    @patch( "lupin_cli.claude_code.hooks.stop.notify_user_async" )
    def test_none_abstract_falls_back_to_generic( self, mock_notify, mock_sender ):
        _announce_poke( "abc12345", "Rio", 2 )
        assert mock_notify.call_args[ 0 ][ 0 ].abstract == "Heartbeat: stopped with work owed — self-poke fired."


# ═════════════════════════════════════════════════════════════════════════════
# §4 poke-abstract receipts (Rick 2026-06-10) — compose / format / builder
# ═════════════════════════════════════════════════════════════════════════════

class TestComposePokeAbstract:

    def test_full_receipts_all_sections( self ):
        out = _compose_poke_abstract(
            { "signals": [ "todo_in_progress", "outstanding_delegation", "unanswered_inbound_question" ] },
            [ "Subj A", "Subj B" ],
            [ { "session_name": "wise-penguin" } ],
            [ { "sender": "7b76ad86", "question_id": "q1234567" } ],
            [ { "sender": "old-peer", "question_id": "stale123" } ],
            "Do not stop yet.",
        )
        assert out.startswith( "Heartbeat: stopped with work owed — self-poke fired." )
        assert "Signals (strongest first): todo_in_progress, outstanding_delegation, unanswered_inbound_question" in out
        assert "• Subj A" in out and "• Subj B" in out
        assert "• wise-penguin" in out
        assert "from 7b76ad86 (qid q1234567)" in out
        assert "Stale inbound (review, not owed):" in out
        assert "from old-peer (qid stale123)" in out
        assert "Poke text injected into the worker:" in out
        assert "Do not stop yet." in out

    def test_none_verdict_no_referents_just_header( self ):
        out = _compose_poke_abstract( None, [ ], [ ], [ ], [ ], None )
        assert out == "Heartbeat: stopped with work owed — self-poke fired."

    def test_delegation_name_falls_back_session_id_then_placeholder( self ):
        out = _compose_poke_abstract( { "signals": [ ] }, [ ],
                                      [ { "session_id": "sid-1" }, { } ], [ ], [ ], None )
        assert "• sid-1" in out      # session_name absent → session_id
        assert "• ?" in out          # both absent → placeholder

    def test_list_truncation_plus_n_more( self ):
        out = _compose_poke_abstract( { "signals": [ ] }, [ f"t{i}" for i in range( 12 ) ], [ ], [ ], [ ], None )
        assert "…+4 more" in out     # 12 − 8 shown
        assert "• t0" in out
        assert "• t8" not in out     # beyond the 8-item cap

    def test_abstract_capped_at_ceiling( self ):
        out = _compose_poke_abstract( { "signals": [ ] }, [ ], [ ], [ ], [ ], "x" * 9000 )
        assert len( out ) <= 4000
        assert out.endswith( "…" )


class TestFormatInbound:

    def test_sender_and_qid_shortened( self ):
        assert _format_inbound( { "sender": "abcdef12-xyz", "question_id": "q1234567890" } ) \
            == "from abcdef12-xyz (qid q1234567)"

    def test_missing_sender_unknown( self ):
        assert _format_inbound( { "question_id": "q1" } ) == "from unknown (qid q1)"

    def test_missing_qid_placeholder( self ):
        assert _format_inbound( { "sender": "s" } ) == "from s (qid ?)"

    def test_non_str_qid_placeholder( self ):
        assert _format_inbound( { "sender": "s", "question_id": 12345 } ) == "from s (qid ?)"


class TestReceiptLines:

    def test_no_truncation_under_cap( self ):
        assert _receipt_lines( "L:", [ "a", "b" ] ) == [ "L:", "  • a", "  • b" ]

    def test_truncation_over_cap( self ):
        lines = _receipt_lines( "L:", [ str( i ) for i in range( 10 ) ] )
        assert lines[ 0 ] == "L:"
        assert lines[ -1 ] == "  • …+2 more"     # 10 − 8


class TestBuildPokeAbstractSafe:

    def test_success_owed_subjects_with_fallback( self ):
        task_state = { "1": "in_progress", "2": "completed", "3": "pending" }
        result     = { "hook_output": { "reason": "POKE TEXT" } }
        with patch( "lupin_cli.claude_code.hooks.stop.replay_task_subjects",
                    return_value={ "1": "First subj" } ):
            out = _build_poke_abstract_safe(
                { "signals": [ "todo_in_progress" ] }, task_state, "/t.jsonl", [ ], [ ],
                [ { "sender": "old", "question_id": "stale9" } ], result )
        assert "First subj" in out      # owed task 1 has a subject
        assert "task 3" in out           # owed task 3 subject missing → fallback
        assert "POKE TEXT" in out
        assert "completed" not in out    # task 2 is terminal → not owed → not listed
        assert "Stale inbound (review, not owed):" in out   # stale passed through the safe wrapper

    def test_owed_ids_empty_skips_subject_replay( self ):
        with patch( "lupin_cli.claude_code.hooks.stop.replay_task_subjects" ) as rps:
            out = _build_poke_abstract_safe(
                { "signals": [ "outstanding_delegation" ] }, { }, "/t.jsonl",
                [ { "session_name": "w1" } ], [ ], [ ], { "hook_output": { "reason": "r" } } )
        rps.assert_not_called()          # delegation-only poke → no transcript re-read
        assert "• w1" in out

    @patch( "lupin_cli.claude_code.hooks.stop.log_to_stream" )
    def test_compose_failure_returns_none_and_logs( self, mock_log ):
        with patch( "lupin_cli.claude_code.hooks.stop._compose_poke_abstract",
                    side_effect=RuntimeError( "boom" ) ):
            out = _build_poke_abstract_safe(
                { "signals": [ ] }, { "1": "in_progress" }, "/t.jsonl", [ ], [ ], [ ],
                { "hook_output": { "reason": "r" } } )
        assert out is None               # degrade-safe → caller falls back to generic
        assert mock_log.call_args[ 1 ][ "extra" ][ "phase" ] == "poke_abstract_error"


# ═════════════════════════════════════════════════════════════════════════════
# _has_pending_voice — the Branch-C voice-wins peek (non-destructive)
# ═════════════════════════════════════════════════════════════════════════════

class TestHasPendingVoice:

    def test_true_when_buffer_exists( self, tmp_path ):
        buf = tmp_path / "cc-buffer-abc12345.jsonl"
        buf.write_text( '{"message": "hold on"}\n' )
        with patch( "lupin_cli.claude_code.hooks.stop.get_buffer_path", return_value=buf ):
            assert _has_pending_voice( "abc12345" ) is True
        assert buf.exists(), "peek must NOT consume the buffer"

    def test_false_when_no_buffer( self, tmp_path ):
        with patch( "lupin_cli.claude_code.hooks.stop.get_buffer_path",
                    return_value=tmp_path / "absent.jsonl" ):
            assert _has_pending_voice( "abc12345" ) is False

    def test_false_on_error_never_raises( self ):
        with patch( "lupin_cli.claude_code.hooks.stop.get_buffer_path",
                    side_effect=RuntimeError( "bad session dir" ) ):
            assert _has_pending_voice( "abc12345" ) is False


# ═════════════════════════════════════════════════════════════════════════════
# Spine Step-2 store-count seam — _synthesize_owed_items (pure)
# ═════════════════════════════════════════════════════════════════════════════

class TestSynthesizeOwedItems:

    def test_zero_count_empty_list( self ):
        assert _synthesize_owed_items( 0 ) == [ ]

    def test_n_count_n_owed_items_in_oracle_shape( self ):
        items = _synthesize_owed_items( 3 )
        assert len( items ) == 3
        # SAME shape owed_items_from_state emits → drops straight into the oracle
        assert all( i == { "status": TODO_IN_PROGRESS, "owned_by_me": True } for i in items )


# ═════════════════════════════════════════════════════════════════════════════
# Spine Step-2 store-count seam — _owed_count_from_store (IO shell, 100% L/B/F)
# ═════════════════════════════════════════════════════════════════════════════

class TestOwedCountFromStore:
    """Scopes to the session's OWN owed work via the mirror's identity
    (owner_persona = lowercased persona, mirror's 'unknown' fallback; project =
    resolve_project_name). Degrade-safe: any failure ⇒ ( 0, False ) → no poke."""

    @pytest.fixture( autouse=True )
    def _isolate( self ):
        with patch( "lupin_cli.claude_code.hooks.stop.load_task_store_settings",
                    return_value={ "api_base_url": "http://t:7999" } ) as ts, \
             patch( "lupin_cli.claude_code.hooks.stop.read_api_key", return_value="k" ) as rk, \
             patch( "lupin_cli.claude_code.hooks.stop.resolve_project_name", return_value="lupin" ) as rp, \
             patch( "lupin_cli.claude_code.hooks.stop.get_voice_persona" ) as vp, \
             patch( "lupin_cli.claude_code.hooks.stop.query_owed" ) as qo:
            self.ts, self.rk, self.rp, self.vp, self.qo = ts, rk, rp, vp, qo
            yield

    def test_persona_dict_scopes_query_and_returns_count( self ):
        self.vp.return_value = { "name": "Krishna" }
        self.qo.return_value = ( True, 4 )
        assert _owed_count_from_store( "sid" ) == ( 4, True )
        # owner lowercased; owed statuses + project threaded through
        _args, kwargs = self.qo.call_args
        assert _args[ 2 ] == "krishna"
        assert _args[ 3 ] == STORE_OWED_STATUSES
        assert kwargs[ "project" ] == "lupin"

    def test_persona_name_none_falls_back_to_unknown( self ):
        self.vp.return_value = { "name": None }
        self.qo.return_value = ( True, 0 )
        _owed_count_from_store( "sid" )
        assert self.qo.call_args[ 0 ][ 2 ] == "unknown"

    def test_persona_not_dict_falls_back_to_unknown( self ):
        self.vp.return_value = None
        self.qo.return_value = ( True, 1 )
        _owed_count_from_store( "sid" )
        assert self.qo.call_args[ 0 ][ 2 ] == "unknown"

    def test_query_not_ok_returns_not_ok( self ):
        self.vp.return_value = { "name": "Krishna" }
        self.qo.return_value = ( False, 0 )
        assert _owed_count_from_store( "sid" ) == ( 0, False )

    def test_exception_is_degrade_safe( self ):
        # e.g. load_task_store_settings raises ValueError on malformed config
        self.ts.side_effect = ValueError( "bad task_store config" )
        assert _owed_count_from_store( "sid" ) == ( 0, False )


# ═════════════════════════════════════════════════════════════════════════════
# Spine Step-2 — _run_heartbeat flag-gated owed SOURCE (every branch)
# ═════════════════════════════════════════════════════════════════════════════

class TestRunHeartbeatStoreSource:
    """The flag swaps ONLY the owed_items source. §B (delegations + inbound still
    feed the oracle) and §C (store-down → no poke) verified end-to-end on the
    REAL leaves; only the store read + emit are injected."""

    @pytest.fixture( autouse=True )
    def _isolate( self ):
        with patch( "lupin_cli.claude_code.hooks.stop.heartbeat_events" ) as ev, \
             patch( "lupin_cli.claude_code.hooks.stop.get_voice_persona", return_value=None ), \
             patch( "lupin_cli.claude_code.hooks.stop.replay_task_state", return_value={ } ) as rt, \
             patch( "lupin_cli.claude_code.hooks.stop.notify_user_async" ), \
             patch( "lupin_cli.claude_code.hooks.stop._gather_outstanding_delegations",
                    return_value=[ ] ) as gd, \
             patch( "lupin_cli.claude_code.hooks.stop._gather_unanswered_inbound_questions",
                    return_value={ "owed": [ ], "stale": [ ] } ) as gq, \
             patch( "lupin_cli.claude_code.hooks.stop.inject_qualifier_via_tmux" ), \
             patch( "lupin_cli.claude_code.hooks.stop.build_sender_id_for_cc",
                    return_value="claude.code@lupin.deepily.ai#sid" ):
            ev.EVENT_IDLE = "idle"
            ev.is_idle_transition.return_value = True
            self.mock_events      = ev
            self.mock_replay      = rt
            self.mock_delegations = gd
            self.mock_inbound     = gq
            yield

    _STORE_ON = { "enabled": True, "poke_cap": 3, "count_inbound_questions_as_owed": False,
                  "owed_source_from_store": True }

    @patch( "lupin_cli.claude_code.hooks.stop._owed_count_from_store", return_value=( 2, True ) )
    @patch( "lupin_cli.claude_code.hooks.stop.increment_poke_count" )
    @patch( "lupin_cli.claude_code.hooks.stop.get_poke_count", return_value=0 )
    @patch( "lupin_cli.claude_code.hooks.stop.read_hold", return_value=None )
    @patch( "lupin_cli.claude_code.hooks.stop.load_heartbeat_settings", return_value=_STORE_ON )
    def test_flag_on_store_owed_pokes( self, mock_load, mock_read, mock_count, mock_incr, mock_store ):
        """flag ON + store reports owed rows → poke, even with an EMPTY transcript
        (proves the owed source is the STORE, not replay)."""
        self.mock_replay.return_value = { }                  # empty transcript
        out = _run_heartbeat( "sid", "/t.jsonl" )
        assert out[ "decision" ] == "block"
        _, kwargs = self.mock_events.emit_outcome.call_args
        assert kwargs[ "work_owed" ] is True
        mock_store.assert_called_once_with( "sid" )
        # §B: task_state still replayed (for the genuine-idle beacon + abstract)
        self.mock_replay.assert_called_once()

    @patch( "lupin_cli.claude_code.hooks.stop._owed_count_from_store", return_value=( 0, True ) )
    @patch( "lupin_cli.claude_code.hooks.stop.get_poke_count", return_value=0 )
    @patch( "lupin_cli.claude_code.hooks.stop.read_hold", return_value=None )
    @patch( "lupin_cli.claude_code.hooks.stop.load_heartbeat_settings", return_value=_STORE_ON )
    def test_flag_on_store_zero_idles( self, mock_load, mock_read, mock_count, mock_store ):
        """flag ON + store reports zero owed → not owed; empty transcript → idle beacon."""
        assert _run_heartbeat( "sid", "/t.jsonl" ) is None
        idle = [ c for c in self.mock_events.emit_outcome.call_args_list if c.args[ 2 ] == "idle" ]
        assert len( idle ) == 1

    @patch( "lupin_cli.claude_code.hooks.stop.log_to_stream" )
    @patch( "lupin_cli.claude_code.hooks.stop._owed_count_from_store", return_value=( 0, False ) )
    @patch( "lupin_cli.claude_code.hooks.stop.increment_poke_count" )
    @patch( "lupin_cli.claude_code.hooks.stop.get_poke_count", return_value=0 )
    @patch( "lupin_cli.claude_code.hooks.stop.read_hold", return_value=None )
    @patch( "lupin_cli.claude_code.hooks.stop.load_heartbeat_settings", return_value=_STORE_ON )
    def test_flag_on_store_unreachable_no_local_signals_no_poke( self, mock_load, mock_read, mock_count,
                                                                 mock_incr, mock_store, mock_log ):
        """§C fail-safe: store unreachable/timeout/malformed AND no local signals
        → store-owed fails safe to 0, the verdict is not_owed, NO poke, distinct
        log phase, no increment (don't guess the STORE count when it's down).
        O1: this is NO LONGER an early return — the oracle still runs over the
        (empty) local signals, so emit_outcome fires the not_owed/idle beacon."""
        assert _run_heartbeat( "sid", "/t.jsonl" ) is None
        assert "heartbeat_store_unreachable" in [ c.kwargs[ "extra" ][ "phase" ]
                                                  for c in mock_log.call_args_list ]
        # The oracle now runs to completion (no early return): the outcome is
        # not_owed, never a poke, and the poke counter is never incremented.
        emitted_outcomes = [ c.args[ 2 ] for c in self.mock_events.emit_outcome.call_args_list ]
        assert OUTCOME_POKE not in emitted_outcomes
        mock_incr.assert_not_called()

    @patch( "lupin_cli.claude_code.hooks.stop.log_to_stream" )
    @patch( "lupin_cli.claude_code.hooks.stop._owed_count_from_store", return_value=( 0, False ) )
    @patch( "lupin_cli.claude_code.hooks.stop.increment_poke_count" )
    @patch( "lupin_cli.claude_code.hooks.stop.get_poke_count", return_value=0 )
    @patch( "lupin_cli.claude_code.hooks.stop.read_hold", return_value=None )
    @patch( "lupin_cli.claude_code.hooks.stop.load_heartbeat_settings", return_value=_STORE_ON )
    def test_O1_store_unreachable_with_delegation_STILL_pokes( self, mock_load, mock_read, mock_count,
                                                               mock_incr, mock_store, mock_log ):
        """O1 REGRESSION GUARD: with the flag ON and the store UNREACHABLE, a live
        un-reaped spawned worker MUST still poke. The local delegations signal is
        filesystem-derived (store-independent) — before O1 the store-down early
        return suppressed it, silencing the manager. Now the store-owed count
        fails safe to 0 but the delegation survives the outage → poke."""
        self.mock_delegations.return_value = [ { "session_name": "cc-reviewer-x-1", "session_id": "c1" } ]
        out = _run_heartbeat( "sid", "/t.jsonl" )
        assert out is not None and out[ "decision" ] == "block"
        assert "1 live worker(s) still out" in out[ "reason" ]
        # The store-unreachable log still fires (the count failed safe)...
        assert "heartbeat_store_unreachable" in [ c.kwargs[ "extra" ][ "phase" ]
                                                  for c in mock_log.call_args_list ]
        # ...but the local signal drove a real poke (the O1 fix).
        mock_incr.assert_called_once()

    @patch( "lupin_cli.claude_code.hooks.stop.log_to_stream" )
    @patch( "lupin_cli.claude_code.hooks.stop._owed_count_from_store", return_value=( 0, False ) )
    @patch( "lupin_cli.claude_code.hooks.stop.increment_poke_count" )
    @patch( "lupin_cli.claude_code.hooks.stop.get_poke_count", return_value=0 )
    @patch( "lupin_cli.claude_code.hooks.stop.read_hold", return_value=None )
    @patch( "lupin_cli.claude_code.hooks.stop.load_heartbeat_settings",
            return_value={ "enabled": True, "poke_cap": 3, "count_inbound_questions_as_owed": True,
                           "owed_source_from_store": True } )
    def test_O1_store_unreachable_with_inbound_STILL_pokes( self, mock_load, mock_read, mock_count,
                                                            mock_incr, mock_store, mock_log ):
        """O1 REGRESSION GUARD (worker side): store UNREACHABLE + an unanswered
        inbound DM (gate ON) → still pokes. Inbound is bridge-derived
        (store-independent) and must survive a store outage."""
        self.mock_inbound.return_value = { "owed": [ { "question_id": "q1", "ts": "2026-06-10T01:00:00+00:00" } ],
                                           "stale": [ ] }
        out = _run_heartbeat( "sid", "/t.jsonl" )
        assert out is not None and out[ "decision" ] == "block"
        assert "unanswered inbound question" in out[ "reason" ]
        mock_incr.assert_called_once()

    @patch( "lupin_cli.claude_code.hooks.stop._owed_count_from_store" )
    @patch( "lupin_cli.claude_code.hooks.stop.increment_poke_count" )
    @patch( "lupin_cli.claude_code.hooks.stop.get_poke_count", return_value=0 )
    @patch( "lupin_cli.claude_code.hooks.stop.read_hold", return_value=None )
    @patch( "lupin_cli.claude_code.hooks.stop.load_heartbeat_settings",
            return_value={ "enabled": True, "poke_cap": 3, "count_inbound_questions_as_owed": False,
                           "owed_source_from_store": False } )
    def test_flag_off_uses_transcript_not_store( self, mock_load, mock_read, mock_count,
                                                  mock_incr, mock_store ):
        """DEFAULT (flag OFF): owed source is the transcript replay; the store
        reader is NEVER consulted."""
        self.mock_replay.return_value = { "1": "in_progress" }     # owed via transcript
        out = _run_heartbeat( "sid", "/t.jsonl" )
        assert out[ "decision" ] == "block"
        mock_store.assert_not_called()

    @patch( "lupin_cli.claude_code.hooks.stop._owed_count_from_store", return_value=( 0, True ) )
    @patch( "lupin_cli.claude_code.hooks.stop.increment_poke_count" )
    @patch( "lupin_cli.claude_code.hooks.stop.get_poke_count", return_value=0 )
    @patch( "lupin_cli.claude_code.hooks.stop.read_hold", return_value=None )
    @patch( "lupin_cli.claude_code.hooks.stop.load_heartbeat_settings", return_value=_STORE_ON )
    def test_j2_delegations_still_feed_oracle_under_store_source( self, mock_load, mock_read,
                                                                  mock_count, mock_incr, mock_store ):
        """§B: with the store owed-count 0, a LIVE spawned worker still pokes —
        the manager delegations signal survives the source swap."""
        self.mock_delegations.return_value = [ { "session_name": "cc-reviewer-x-1", "session_id": "c1" } ]
        out = _run_heartbeat( "sid", "/t.jsonl" )
        assert out[ "decision" ] == "block"
        assert "1 live worker(s) still out" in out[ "reason" ]

    @patch( "lupin_cli.claude_code.hooks.stop._owed_count_from_store", return_value=( 0, True ) )
    @patch( "lupin_cli.claude_code.hooks.stop.increment_poke_count" )
    @patch( "lupin_cli.claude_code.hooks.stop.get_poke_count", return_value=0 )
    @patch( "lupin_cli.claude_code.hooks.stop.read_hold", return_value=None )
    @patch( "lupin_cli.claude_code.hooks.stop.load_heartbeat_settings",
            return_value={ "enabled": True, "poke_cap": 3, "count_inbound_questions_as_owed": True,
                           "owed_source_from_store": True } )
    def test_j2_inbound_still_feeds_oracle_under_store_source( self, mock_load, mock_read,
                                                               mock_count, mock_incr, mock_store ):
        """§B: with the store owed-count 0 and the inbound gate ON, an unanswered
        inbound DM still pokes — the worker-inbound signal survives the swap."""
        self.mock_inbound.return_value = { "owed": [ { "question_id": "q1", "ts": "2026-06-10T01:00:00+00:00" } ],
                                           "stale": [ ] }
        out = _run_heartbeat( "sid", "/t.jsonl" )
        assert out[ "decision" ] == "block"
        assert "unanswered inbound question" in out[ "reason" ]
