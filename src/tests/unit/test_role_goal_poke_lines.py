#!/usr/bin/env python3
"""
Unit tests — role-goal poke echoes (role-goals Phase 2-3).

Covers the role-selected north-star goal line APPENDED to each of the four
heartbeat poke sites, plus the injected-string plumbing through the pure modules:

    1. Pure core  — heartbeat_work_owed.build_poke_reason / heartbeat_decision
                    .decide_heartbeat append an INJECTED goal_line (empty ⇒
                    byte-identical to the pre-role-goals output).
    2. Stop hook  — stop._select_goal_role 3-way (bridge role → worker/manager;
                    fleet-roster persona → manager; else agnostic) +
                    _GOAL_LINE_KEYS → the configuration_manager keys.
    3. Arbiter    — _format_poke (role-selected via view["role"]) +
                    _format_manager_stale_poke (always Manager) + inert-when-"".
    4. Cascade    — fire_heartbeat appends the Manager line (manager-only) +
                    inert-when-"".

Canonical goal text: planning-is-prompting -> workflow/role-goals.md.
"""
import datetime
import importlib.util
import os

import pytest

from lupin_cli.claude_code.hooks.lib.heartbeat_work_owed import (
    evaluate_work_owed, build_poke_reason, TODO_IN_PROGRESS,
)
from lupin_cli.claude_code.hooks.lib.heartbeat_decision import (
    decide_heartbeat, DECLARED_OWED_REASON, OUTCOME_POKE,
)


_GOAL = "Your goal: TESTLINE."


class _FakeConfigMgr:
    """
    A stand-in ConfigurationManager: get(key) → a key-derived SENTINEL string.

    Lets a test prove the goal-line WIRING (which INI key each role reads, that the
    key's value flows through) WITHOUT coupling to the live goal-line wording — so
    Rick retuning a goal-line string in lupin-app.ini (the frictionless no-code
    case D1+D4 were ratified to protect) never breaks these tests.
    """
    def __init__( self, *args, **kwargs ):
        pass

    def get( self, key, default=None, silent=False, **kwargs ):
        return "SENTINEL::" + key


# ── 1. Pure core — injected goal_line append ─────────────────────────────────

class TestPureCoreGoalLine:

    def _owed_verdict( self ):
        return evaluate_work_owed( todo_items=[ { "status": TODO_IN_PROGRESS, "owned_by_me": True } ] )

    def test_build_poke_reason_empty_is_identical( self ):
        v = self._owed_verdict()
        assert build_poke_reason( v ) == build_poke_reason( v, goal_line="" )

    def test_build_poke_reason_appends_trailing_block( self ):
        v = self._owed_verdict()
        assert build_poke_reason( v, goal_line=_GOAL ).endswith( "\n\n" + _GOAL )

    def test_decide_oracle_owed_appends_goal( self ):
        v = self._owed_verdict()
        r = decide_heartbeat( None, v, 0, 3, goal_line=_GOAL )
        assert r[ "outcome" ] == OUTCOME_POKE
        assert r[ "hook_output" ][ "reason" ].endswith( "\n\n" + _GOAL )

    def test_decide_self_declared_appends_goal( self ):
        now      = datetime.datetime( 2026, 6, 4, 12, 0, 0, tzinfo=datetime.timezone.utc )
        empty_v  = evaluate_work_owed()
        hold     = { "held_at": now.isoformat(), "ttl_seconds": 0, "reason": "x", "work_owed": True }
        r        = decide_heartbeat( hold, empty_v, 0, 3, now=now, goal_line=_GOAL )
        assert r[ "outcome" ] == OUTCOME_POKE
        reason = r[ "hook_output" ][ "reason" ]
        assert reason.startswith( DECLARED_OWED_REASON )
        assert reason.endswith( "\n\n" + _GOAL )

    def test_decide_empty_goal_unchanged( self ):
        v = self._owed_verdict()
        r = decide_heartbeat( None, v, 0, 3, goal_line="" )
        assert "\n\nYour goal" not in r[ "hook_output" ][ "reason" ]


# ── 2. Stop hook — 3-way role selector + config keys ─────────────────────────

class TestStopSelectGoalRole:

    def _clear_roster( self ):
        for k in list( os.environ ):
            if k.startswith( "COSA_VOICE_MANAGERS__" ):
                del os.environ[ k ]

    def test_keys_map_to_config_names( self ):
        from lupin_cli.claude_code.hooks import stop
        assert stop._GOAL_LINE_KEYS == {
            "manager"  : "heartbeat manager goal line",
            "worker"   : "heartbeat worker goal line",
            "agnostic" : "heartbeat role-agnostic goal line",
        }

    @pytest.mark.parametrize( "role", [ "author", "reviewer", "tester", "worker", "implementer" ] )
    def test_bridge_worker_roles_select_worker( self, role ):
        from lupin_cli.claude_code.hooks import stop
        assert stop._select_goal_role( "sid", role ) == "worker"

    def test_defensive_manager_role_selects_manager( self ):
        from lupin_cli.claude_code.hooks import stop
        assert stop._select_goal_role( "sid", "manager" )  == "manager"
        assert stop._select_goal_role( "sid", "MANAGER" )  == "manager"

    def test_absent_role_no_roster_is_agnostic( self ):
        self._clear_roster()
        from lupin_cli.claude_code.hooks import stop
        assert stop._select_goal_role( "sid", None )  == "agnostic"
        assert stop._select_goal_role( "sid", "" )    == "agnostic"
        assert stop._select_goal_role( "sid", "  " )  == "agnostic"

    def test_roster_persona_selects_manager( self, monkeypatch ):
        # a declared fleet-roster manager gets the Manager line at its OWN self-poke
        monkeypatch.setenv( "COSA_VOICE_MANAGERS__LUPIN", "Mr. Radio, Tiberius" )
        import lupin_cli.claude_code.hooks.lib.session_bridge as sb
        monkeypatch.setattr( sb, "get_voice_persona", lambda sid: { "name": "mr radio" } )  # accent/case variant
        from lupin_cli.claude_code.hooks import stop
        assert stop._select_goal_role( "sid", None ) == "manager"
        # a non-roster persona falls through to agnostic
        monkeypatch.setattr( sb, "get_voice_persona", lambda sid: { "name": "Rio" } )
        assert stop._select_goal_role( "sid", None ) == "agnostic"

    def test_heartbeat_goal_line_reads_selected_key( self, monkeypatch ):
        # D4 protection: prove the kind → _GOAL_LINE_KEYS[kind] → config-read WIRING
        # WITHOUT pinning the live wording (so Rick retuning a goal-line string never
        # breaks this test). The fake config echoes "SENTINEL::"+key, so the assert is
        # non-vacuous: the EXACT key for each role must have been read and flowed back.
        from lupin_cli.claude_code.hooks import stop
        monkeypatch.setattr( stop, "ConfigurationManager", _FakeConfigMgr )
        for kind in [ "worker", "manager", "agnostic" ]:
            monkeypatch.setattr( stop, "_select_goal_role", lambda sid, br, _k=kind: _k )
            got = stop._heartbeat_goal_line( "sid", None )
            assert got == "SENTINEL::" + stop._GOAL_LINE_KEYS[ kind ], ( kind, got )


# ── 3. Arbiter — role-selected poke formatters ───────────────────────────────

class TestArbiterPokeGoalLine:

    def _job( self, manager_line="GOAL-MANAGER.", worker_line="GOAL-WORKER." ):
        from cosa.agents.heartbeat_arbiter.arbiter_job import ArbiterConsumerJob
        j = ArbiterConsumerJob.__new__( ArbiterConsumerJob )   # skip heavy __init__
        j.manager_goal_line = manager_line
        j.worker_goal_line  = worker_line
        j.manager_stale_poke_threshold_seconds = 2700
        return j

    def test_stuck_poke_worker_role( self ):
        b = self._job()._format_poke( { "persona": "Rio", "role": "worker", "session_id": "s1" } )
        assert b.endswith( "\n\nGOAL-WORKER." )

    def test_stuck_poke_manager_role( self ):
        b = self._job()._format_poke( { "persona": "Mr. Radio", "role": "manager", "session_id": "s2" } )
        assert b.endswith( "\n\nGOAL-MANAGER." )

    def test_manager_stale_poke_always_manager( self ):
        b = self._job()._format_manager_stale_poke( { "persona": "Tiberius", "session_id": "s3" }, 3000 )
        assert b.endswith( "\n\nGOAL-MANAGER." )

    def test_inert_when_unconfigured( self ):
        j = self._job( manager_line="", worker_line="" )
        b = j._format_poke( { "persona": "Rio", "role": "worker", "session_id": "s1" } )
        assert "GOAL" not in b and b.rstrip().endswith( "nudge.)" )


# ── 4. Cascade scheduler — manager-only goal append ──────────────────────────

def _load_cascade_module():
    """Import the cascade scheduler script by path (it lives under src/scripts)."""
    import cosa.utils.util as cu
    path = cu.get_project_root() + "/src/scripts/cascade_heartbeat_scheduler.py"
    spec = importlib.util.spec_from_file_location( "cascade_hb_under_test", path )
    mod  = importlib.util.module_from_spec( spec )
    spec.loader.exec_module( mod )
    return mod


class _FakeStore:
    def __init__( self ):
        self.body = None
    def post( self, **kw ):
        self.body = kw[ "body" ]


class _FakeResp:
    status_code = 200
    text        = ""
    def json( self ):
        return { "dispatched": True }


class TestCascadeGoalLine:

    def test_fire_heartbeat_appends_manager_line( self, monkeypatch ):
        mod   = _load_cascade_module()
        store = _FakeStore()
        monkeypatch.setattr( mod.requests, "post", lambda *a, **k: _FakeResp() )
        mod.fire_heartbeat( "http://x", "k", "tiberius", store, 7, manager_goal_line="GOAL-MANAGER." )
        assert store.body.endswith( "\n\nGOAL-MANAGER." )

    def test_fire_heartbeat_inert_when_empty( self, monkeypatch ):
        mod   = _load_cascade_module()
        store = _FakeStore()
        monkeypatch.setattr( mod.requests, "post", lambda *a, **k: _FakeResp() )
        mod.fire_heartbeat( "http://x", "k", "tiberius", store, 8, manager_goal_line="" )
        assert "GOAL" not in store.body and store.body.rstrip().endswith( "pending stages" )

    def test_load_manager_goal_line_reads_manager_key( self, monkeypatch ):
        # D4 protection: prove load_manager_goal_line reads the `heartbeat manager
        # goal line` KEY (and its value flows back) WITHOUT pinning the live wording.
        # The function does a function-local `from ... import ConfigurationManager`,
        # so patching the attribute on the source module is picked up at call time.
        import cosa.config.configuration_manager as cm
        monkeypatch.setattr( cm, "ConfigurationManager", _FakeConfigMgr )
        mod = _load_cascade_module()
        assert mod.load_manager_goal_line() == "SENTINEL::heartbeat manager goal line"
