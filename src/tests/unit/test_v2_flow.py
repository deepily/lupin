#!/usr/bin/env python3
"""
Unit tests for CJ Flow v2's branch logic (unit D) — src/cosa/rest/v2/flow.py.

Hermetic: every collaborator (cache, router, expeditor, executor, pending,
notifier) is a fake, and `resolve` / `JOB_ARG_CONTRACTS` are patched at the flow
module boundary, so the four branches + every degradation are exercised with NO
live Postgres, NO model server, and NO TTS network call. :7999-eligible.

Coverage target is the Lupin-wide hard gate: 100% lines AND branches on flow.py.
Each guard is proven able to fail — the receptionist degradations, the write-back
kill-switch seam, the fail-loud construction guard, and the speak/compose forks
all have a test that would go red if the branch flipped.
"""

import types

import pytest

from cosa.rest.v2 import flow as flow_mod
from cosa.rest.v2.flow import AskFlow
from cosa.rest.v2.pending import PendingRequests


# ────────────────────────────────────────────────────────────── fakes

class FakeAgent:
    """Constructible on the shared 11-kwarg signature; never actually run (the
    executor is faked, so do_all() is never reached from the flow's view)."""

    def __init__( self, **kwargs ):
        self.kwargs = kwargs

    def do_all( self ):                       # pragma: no cover - executor is faked
        return "unused"


class FakeReceptionist( FakeAgent ):
    pass


class FakeSpec:
    """Stand-in for registry.AgentSpec: the three attrs the flow reads."""

    def __init__( self, required_args=(), factory=FakeAgent, snapshotable=True ):
        self.required_args = required_args
        self.factory       = factory
        self.snapshotable  = snapshotable


def _lookup( is_replay_hit=False, snapshot=None, tier=1, similarity=0.0, best_score=0.0,
             best_candidate=None, embed_cached=False, question_normalized="q",
             t_exact_ms=0.1, t_embed_ms=0.2, t_ann_ms=0.3 ):
    return types.SimpleNamespace(
        is_replay_hit=is_replay_hit, snapshot=snapshot, tier=tier, similarity=similarity,
        best_score=best_score, best_candidate=best_candidate, embed_cached=embed_cached,
        question_normalized=question_normalized, t_exact_ms=t_exact_ms,
        t_embed_ms=t_embed_ms, t_ann_ms=t_ann_ms,
    )


def _outcome( status="done", answer="the answer", answer_raw="raw", job_id=None, error=None ):
    return types.SimpleNamespace( status=status, answer=answer, answer_raw=answer_raw,
                                  job_id=job_id, error=error )


def _extraction( final_args=None, missing=(), fallback_questions=None ):
    return types.SimpleNamespace(
        final_args=final_args if final_args is not None else {},
        missing=list( missing ),
        fallback_questions=fallback_questions if fallback_questions is not None else {},
        fallback_defaults={}, special_handlers={},
    )


class FakeCache:
    def __init__( self, lookup_result=None, write_back_id="snap-123" ):
        self._lookup       = lookup_result if lookup_result is not None else _lookup()
        self._write_back_id = write_back_id
        self.snapshot_calls = []
        self.write_back_calls = []

    def lookup( self, question ):
        return self._lookup

    def snapshot_from_result( self, **kwargs ):
        self.snapshot_calls.append( kwargs )
        return types.SimpleNamespace( tag="snap-object" )

    def write_back( self, snapshot, writeback_enabled=True ):
        self.write_back_calls.append( ( snapshot, writeback_enabled ) )
        return self._write_back_id


class CacheNoWriteBack:
    """A cache missing the write-back methods — trips the fail-loud guard."""

    def lookup( self, question ):
        return _lookup()


class FakeRouter:
    def __init__( self, command="agent router go to math", raw_args="" ):
        self._command  = command
        self._raw_args = raw_args

    def route( self, question ):
        return ( self._command, self._raw_args )


class FakeExpeditor:
    def __init__( self, extraction=None, raise_exc=None ):
        self._extraction = extraction if extraction is not None else _extraction()
        self._raise_exc  = raise_exc
        self.calls       = []

    def extract( self, command, raw_args, question, spec ):
        self.calls.append( ( command, raw_args, question, spec ) )
        if self._raise_exc is not None:
            raise self._raise_exc
        return self._extraction


class FakeExecutor:
    def __init__( self, outcome=None ):
        self._outcome = outcome if outcome is not None else _outcome()
        self.works    = []

    def submit( self, work, trace ):
        self.works.append( work )
        return self._outcome


class FakePending:
    def __init__( self ):
        self.put_calls = []

    def put( self, **kwargs ):
        self.put_calls.append( kwargs )
        return "pend-1"

    def get( self, pending_id ):                 # pragma: no cover - unused by flow
        return None

    def set_status( self, pending_id, status ):  # pragma: no cover - unused by flow
        return None


class FakeNotifier:
    def __init__( self ):
        self.requests = []

    def __call__( self, request ):
        self.requests.append( request )


# ────────────────────────────────────────────────────────────── fixtures

@pytest.fixture
def notifier():
    return FakeNotifier()


def _make_flow( tmp_path, cache, router, expeditor, executor, pending, notifier,
                *, writeback_enabled=False, similarity_floor=100.0 ):
    return AskFlow(
        cache, router, expeditor, executor, pending,
        similarity_floor=similarity_floor, writeback_enabled=writeback_enabled,
        receptionist_factory=FakeReceptionist, notifier=notifier,
        trace_dir=str( tmp_path ),
    )


_CTX = dict( user_id="u1", user_email="u@x.com", session_id="s1", websocket_id="ws1" )


# ────────────────────────────────────────────────────────────── construction guard

def test_construction_raises_when_writeback_on_but_cache_lacks_methods( tmp_path, notifier ):
    with pytest.raises( ValueError, match="writeback enabled" ):
        AskFlow( CacheNoWriteBack(), FakeRouter(), FakeExpeditor(), FakeExecutor(),
                 FakePending(), writeback_enabled=True, notifier=notifier,
                 trace_dir=str( tmp_path ) )


def test_construction_ok_when_writeback_on_and_cache_has_methods( tmp_path, notifier ):
    f = AskFlow( FakeCache(), FakeRouter(), FakeExpeditor(), FakeExecutor(), FakePending(),
                 writeback_enabled=True, notifier=notifier, trace_dir=str( tmp_path ) )
    assert f.writeback_enabled is True


def test_construction_ok_when_writeback_off_even_without_methods( tmp_path, notifier ):
    f = AskFlow( CacheNoWriteBack(), FakeRouter(), FakeExpeditor(), FakeExecutor(),
                 FakePending(), writeback_enabled=False, notifier=notifier,
                 trace_dir=str( tmp_path ) )
    assert f.writeback_enabled is False


# ────────────────────────────────────────────────────────────── branch 1 — replay

def test_replay_hit_done_returns_replay_result( tmp_path, notifier ):
    snap  = types.SimpleNamespace( routing_command="agent router go to math" )
    cache = FakeCache( lookup_result=_lookup( is_replay_hit=True, snapshot=snap ) )
    exe   = FakeExecutor( _outcome( status="done", answer="4", answer_raw="4" ) )
    f     = _make_flow( tmp_path, cache, FakeRouter(), FakeExpeditor(), exe, FakePending(), notifier )
    r = f.run( "what is 2+2", **_CTX, speak=True, interactive=True )
    assert r[ "path" ] == "replay"
    assert r[ "route_reason" ] == "exact_hit"
    assert r[ "cache_hit" ] is True
    assert r[ "command" ] == "agent router go to math"
    assert exe.works[ 0 ].kind == "replay"
    assert exe.works[ 0 ].snapshotable is False


def test_replay_hit_failed_degrades_to_receptionist( tmp_path, notifier ):
    snap  = types.SimpleNamespace( routing_command="agent router go to math" )
    cache = FakeCache( lookup_result=_lookup( is_replay_hit=True, snapshot=snap ) )
    # first submit (replay) fails; the receptionist submit then succeeds.
    outcomes = [ _outcome( status="failed", answer=None, error="boom" ), _outcome( status="done" ) ]

    class _SeqExecutor( FakeExecutor ):
        def submit( self, work, trace ):
            self.works.append( work )
            return outcomes.pop( 0 )

    exe = _SeqExecutor()
    f   = _make_flow( tmp_path, cache, FakeRouter(), FakeExpeditor(), exe, FakePending(), notifier )
    r = f.run( "what is 2+2", **_CTX )
    assert r[ "path" ] == "receptionist"
    assert r[ "route_reason" ] == "replay_error"


# ────────────────────────────────────────────────────────────── branch 2 — router

def test_router_unknown_degrades_to_receptionist( tmp_path, notifier ):
    router = FakeRouter( command="unknown", raw_args="" )
    f = _make_flow( tmp_path, FakeCache(), router, FakeExpeditor(), FakeExecutor(),
                    FakePending(), notifier )
    r = f.run( "gibberish", **_CTX )
    assert r[ "path" ] == "receptionist"
    assert r[ "route_reason" ] == "router_error"


def test_resolve_none_degrades_to_receptionist( tmp_path, notifier, monkeypatch ):
    monkeypatch.setattr( flow_mod, "resolve", lambda command: None )
    router = FakeRouter( command="agent router go to deep research" )
    f = _make_flow( tmp_path, FakeCache(), router, FakeExpeditor(), FakeExecutor(),
                    FakePending(), notifier )
    r = f.run( "do deep research", **_CTX )
    assert r[ "path" ] == "receptionist"
    assert r[ "route_reason" ] == "unknown_command"


# ────────────────────────────────────────────────────────────── branch — args_none

def test_args_none_runs_agent_directly( tmp_path, notifier, monkeypatch ):
    monkeypatch.setattr( flow_mod, "resolve",
                         lambda command: FakeSpec( required_args=(), snapshotable=True ) )
    exe = FakeExecutor( _outcome( status="done", answer="42", answer_raw="42" ) )
    f = _make_flow( tmp_path, FakeCache(), FakeRouter(), FakeExpeditor(), exe,
                    FakePending(), notifier )
    r = f.run( "what time is it", **_CTX )
    assert r[ "path" ] == "agent"
    assert r[ "route_reason" ] == "args_none"
    assert exe.works[ 0 ].kind == "agent"


# ────────────────────────────────────────────────────────────── branch — extract fails

def test_extract_exception_degrades_to_receptionist( tmp_path, notifier, monkeypatch ):
    monkeypatch.setattr( flow_mod, "resolve",
                         lambda command: FakeSpec( required_args=( "location", ) ) )
    router    = FakeRouter( command="agent router go to weather" )
    expeditor = FakeExpeditor( raise_exc=RuntimeError( "extractor blew up" ) )
    f = _make_flow( tmp_path, FakeCache(), router, expeditor, FakeExecutor(),
                    FakePending(), notifier )
    r = f.run( "weather", **_CTX )
    assert r[ "path" ] == "receptionist"
    assert r[ "route_reason" ] == "extract_error"


# ────────────────────────────────────────────────────────────── branch 3 — needs_input

def test_needs_input_interactive_parks_and_returns_first_question( tmp_path, notifier, monkeypatch ):
    monkeypatch.setattr( flow_mod, "resolve",
                         lambda command: FakeSpec( required_args=( "location", ) ) )
    router    = FakeRouter( command="agent router go to weather" )
    extraction = _extraction( final_args={}, missing=[ "location" ],
                              fallback_questions={ "location": "Which city?" } )
    expeditor = FakeExpeditor( extraction=extraction )
    pending   = FakePending()
    f = _make_flow( tmp_path, FakeCache(), router, expeditor, FakeExecutor(), pending, notifier )
    r = f.run( "what's the weather", **_CTX, interactive=True )
    assert r[ "path" ] == "needs_input"
    assert r[ "status" ] == "parked"
    assert r[ "answer" ] == "Which city?"
    assert r[ "pending_id" ] == "pend-1"
    assert r[ "args_missing" ] == [ "location" ]
    assert len( pending.put_calls ) == 1


def test_needs_input_non_interactive_does_not_park( tmp_path, notifier, monkeypatch ):
    monkeypatch.setattr( flow_mod, "resolve",
                         lambda command: FakeSpec( required_args=( "location", ) ) )
    router     = FakeRouter( command="agent router go to weather" )
    extraction = _extraction( final_args={}, missing=[ "location" ], fallback_questions={} )
    expeditor  = FakeExpeditor( extraction=extraction )
    pending    = FakePending()
    f = _make_flow( tmp_path, FakeCache(), router, expeditor, FakeExecutor(), pending, notifier )
    r = f.run( "what's the weather", **_CTX, interactive=False )
    assert r[ "path" ] == "needs_input"
    assert r[ "status" ] == "needs_input"
    assert r[ "pending_id" ] is None
    # fallback_questions empty → the synthesized default question is used.
    assert r[ "answer" ] == "What location would you like?"
    assert pending.put_calls == []


def test_non_interactive_spawns_no_background_thread( tmp_path, notifier, monkeypatch ):
    """
    The OTHER half of the never-blocks guarantee (plan DoD 3).

    Its sibling above pins "PendingRequests stays empty". The plan asks for two
    things, and this is the second: "and no background thread spawns". They are
    different failures — a flow that parks anyway returns a clean-looking 200
    while LEAKING a thread, which the eval cannot see because the response body
    looks identical.

    Today this passes because nothing in v2 spawns a thread at all. That is
    exactly why it is worth writing now rather than later: the resume path is
    still unbuilt, so the moment it lands this assertion is already standing
    guard. A guarantee nobody pinned while it was free stops holding silently.
    """
    import threading

    monkeypatch.setattr( flow_mod, "resolve",
                         lambda command: FakeSpec( required_args=( "location", ) ) )
    router     = FakeRouter( command="agent router go to weather" )
    extraction = _extraction( final_args={}, missing=[ "location" ], fallback_questions={} )
    expeditor  = FakeExpeditor( extraction=extraction )
    pending    = FakePending()
    f = _make_flow( tmp_path, FakeCache(), router, expeditor, FakeExecutor(), pending, notifier )

    before = { t.ident for t in threading.enumerate() }
    r      = f.run( "what's the weather", **_CTX, interactive=False )
    after  = { t.ident for t in threading.enumerate() }

    assert r[ "status" ] == "needs_input"
    assert after == before, (
        "non-interactive run spawned a background thread — the never-blocks "
        f"guarantee is broken. new thread ids: {after - before}"
    )


# ────────────────────────────────────────────────────────────── branch — args_complete

def test_args_complete_runs_agent_and_writes_back( tmp_path, notifier, monkeypatch ):
    monkeypatch.setattr( flow_mod, "resolve",
                         lambda command: FakeSpec( required_args=( "location", ), snapshotable=True ) )
    router     = FakeRouter( command="agent router go to weather" )
    extraction = _extraction( final_args={ "location": "Boston" }, missing=[] )
    expeditor  = FakeExpeditor( extraction=extraction )
    cache      = FakeCache( write_back_id="snap-999" )
    exe        = FakeExecutor( _outcome( status="done", answer="sunny", answer_raw="sunny raw" ) )
    f = _make_flow( tmp_path, cache, router, expeditor, exe, FakePending(), notifier,
                    writeback_enabled=True )
    r = f.run( "weather in Chicago", **_CTX )
    assert r[ "path" ] == "agent"
    assert r[ "route_reason" ] == "args_complete"
    assert r[ "snapshot_id" ] == "snap-999"
    assert r[ "wrote_snapshot" ] is True
    assert len( cache.snapshot_calls ) == 1
    assert cache.write_back_calls[ 0 ][ 1 ] is True   # writeback_enabled forwarded


def test_agent_failure_degrades_to_receptionist( tmp_path, notifier, monkeypatch ):
    monkeypatch.setattr( flow_mod, "resolve",
                         lambda command: FakeSpec( required_args=(), snapshotable=True ) )
    outcomes = [ _outcome( status="failed", error="agent boom" ), _outcome( status="done" ) ]

    class _SeqExecutor( FakeExecutor ):
        def submit( self, work, trace ):
            self.works.append( work )
            return outcomes.pop( 0 )

    exe = _SeqExecutor()
    f = _make_flow( tmp_path, FakeCache(), FakeRouter(), FakeExpeditor(), exe,
                    FakePending(), notifier )
    r = f.run( "do a thing", **_CTX )
    assert r[ "path" ] == "receptionist"
    assert r[ "route_reason" ] == "agent_error"


# ────────────────────────────────────────────────────────────── write-back seam

def test_no_write_back_when_agent_not_snapshotable( tmp_path, notifier, monkeypatch ):
    monkeypatch.setattr( flow_mod, "resolve",
                         lambda command: FakeSpec( required_args=(), snapshotable=False ) )
    cache = FakeCache()
    f = _make_flow( tmp_path, cache, FakeRouter(), FakeExpeditor(), FakeExecutor(),
                    FakePending(), notifier, writeback_enabled=True )
    r = f.run( "do a thing", **_CTX )
    assert r[ "path" ] == "agent"
    assert r[ "snapshot_id" ] is None
    assert r[ "wrote_snapshot" ] is False
    assert cache.snapshot_calls == []


def test_write_back_returning_none_marks_no_snapshot( tmp_path, notifier, monkeypatch ):
    # snapshotable+done, but write_back returns None (flag off inside the cache) →
    # snapshot_from_result IS called, but no t_writeback mark and wrote_snapshot False.
    monkeypatch.setattr( flow_mod, "resolve",
                         lambda command: FakeSpec( required_args=(), snapshotable=True ) )
    cache = FakeCache( write_back_id=None )
    f = _make_flow( tmp_path, cache, FakeRouter(), FakeExpeditor(), FakeExecutor(),
                    FakePending(), notifier, writeback_enabled=True )
    r = f.run( "do a thing", **_CTX )
    assert r[ "snapshot_id" ] is None
    assert r[ "wrote_snapshot" ] is False
    assert len( cache.snapshot_calls ) == 1


# ────────────────────────────────────────────────────────────── _speak forks

def test_speak_off_dispatches_no_notification( tmp_path, notifier, monkeypatch ):
    monkeypatch.setattr( flow_mod, "resolve",
                         lambda command: FakeSpec( required_args=() ) )
    f = _make_flow( tmp_path, FakeCache(), FakeRouter(), FakeExpeditor(), FakeExecutor(),
                    FakePending(), notifier )
    r = f.run( "do a thing", **_CTX, speak=False )
    assert notifier.requests == []
    assert r[ "spoke" ] is False


def test_speak_on_with_answer_dispatches_notification( tmp_path, notifier, monkeypatch ):
    monkeypatch.setattr( flow_mod, "resolve",
                         lambda command: FakeSpec( required_args=() ) )
    exe = FakeExecutor( _outcome( status="done", answer="hello", answer_raw="hello" ) )
    f = _make_flow( tmp_path, FakeCache(), FakeRouter(), FakeExpeditor(), exe,
                    FakePending(), notifier )
    r = f.run( "do a thing", **_CTX, speak=True )
    assert len( notifier.requests ) == 1
    assert r[ "spoke" ] is True


def test_speak_on_but_empty_message_dispatches_nothing( tmp_path, notifier, monkeypatch ):
    monkeypatch.setattr( flow_mod, "resolve",
                         lambda command: FakeSpec( required_args=() ) )
    exe = FakeExecutor( _outcome( status="done", answer=None, answer_raw=None ) )
    f = _make_flow( tmp_path, FakeCache(), FakeRouter(), FakeExpeditor(), exe,
                    FakePending(), notifier )
    r = f.run( "do a thing", **_CTX, speak=True )
    assert notifier.requests == []
    assert r[ "spoke" ] is False


# ────────────────────────────────────────────────────────────── _compose_question forks

def test_compose_question_appends_missing_skips_present_and_empty( tmp_path, notifier, monkeypatch ):
    captured = {}

    def _spec_capturing( command ):
        return FakeSpec( required_args=( "a", ), snapshotable=False )

    monkeypatch.setattr( flow_mod, "resolve", _spec_capturing )
    router     = FakeRouter( command="agent router go to weather" )
    extraction = _extraction( final_args={ "empty": "", "present": "already", "new": "Boston" }, missing=[] )
    expeditor  = FakeExpeditor( extraction=extraction )

    class _CapturingAgent( FakeAgent ):
        def __init__( self, **kwargs ):
            super().__init__( **kwargs )
            captured[ "question" ] = kwargs[ "question" ]

    monkeypatch.setattr( flow_mod, "resolve",
                         lambda command: FakeSpec( required_args=( "a", ), factory=_CapturingAgent,
                                                   snapshotable=False ) )
    f = _make_flow( tmp_path, FakeCache(), router, expeditor, FakeExecutor(),
                    FakePending(), notifier )
    f.run( "weather in already", **_CTX )
    q = captured[ "question" ]
    assert "Boston" in q            # truthy + absent → appended
    assert q.lower().count( "already" ) == 1  # present already → not re-appended
    assert q.count( "" ) >= 0       # empty value → skipped (no crash)


# ────────────────────────────────────────────────────────────── _arg_spec_for forks

def test_arg_spec_for_synthesizes_weather_when_not_in_table( tmp_path, notifier, monkeypatch ):
    # weather is NOT in JOB_ARG_CONTRACTS → the call-site ArgSpec is synthesized (R-B3).
    monkeypatch.setattr( flow_mod, "resolve",
                         lambda command: FakeSpec( required_args=( "location", ) ) )
    router  = FakeRouter( command="agent router go to weather" )
    spec = AskFlow( FakeCache(), router, FakeExpeditor(), FakeExecutor(), FakePending(),
                    notifier=notifier, trace_dir=str( tmp_path ) )._arg_spec_for(
                        "agent router go to weather", ( "location", ) )
    assert spec.required_user_args == [ "location" ]
    assert spec.cli_module is None
    assert "location" in spec.fallback_questions


def test_arg_spec_for_uses_table_entry_when_present( tmp_path, notifier, monkeypatch ):
    entry = {
        "arg_mapping"        : {},
        "system_provided"    : [],
        "required_user_args" : [ "foo" ],
        "fallback_questions" : { "foo": "Which foo?" },
    }
    monkeypatch.setattr( flow_mod, "JOB_ARG_CONTRACTS", { "agent router go to foo": entry } )
    f = AskFlow( FakeCache(), FakeRouter(), FakeExpeditor(), FakeExecutor(), FakePending(),
                 notifier=notifier, trace_dir=str( tmp_path ) )
    spec = f._arg_spec_for( "agent router go to foo", ( "foo", ) )
    assert spec.required_user_args == [ "foo" ]
    assert spec.fallback_questions == { "foo": "Which foo?" }


# ────────────────────────────────────────────────────────────── the second turn — resume (DoD 4)
#
# These use the REAL PendingRequests, not a fake, on purpose: the plan's finding
# (§ reachability) was that the parked-request lifecycle was 100% covered and 0%
# reachable — put/get/set_status had no caller outside their own tests. Driving
# resume through the real store is the reachability assertion: it proves the flow
# is the caller that closes the loop. Still hermetic (in-process dict), :7999-safe.

def _park( pending, *, command="agent router go to weather", question="what's the weather",
           final_args=None, missing=( "location", ), fallback_questions=None ):
    """Park a real entry and return (pending_id, extraction) (mirrors flow.py:210's put)."""
    extraction = _extraction(
        final_args=final_args if final_args is not None else {},
        missing=missing,
        fallback_questions=fallback_questions if fallback_questions is not None else { "location": "Which city?" },
    )
    pid = pending.put( extraction=extraction, user_email="u@x.com", session_id="s1",
                       user_id="u1", command=command, question=question )
    return pid, extraction


def test_resume_completes_when_answer_fills_last_arg( tmp_path, notifier, monkeypatch ):
    monkeypatch.setattr( flow_mod, "resolve",
                         lambda command: FakeSpec( required_args=( "location", ), snapshotable=False ) )
    pending      = PendingRequests()
    pid, _       = _park( pending )
    exe          = FakeExecutor( _outcome( status="done", answer="sunny", answer_raw="sunny raw" ) )
    f            = _make_flow( tmp_path, FakeCache(), FakeRouter(), FakeExpeditor(), exe, pending, notifier )
    r = f.resume( pending_id=pid, answer="Boston", websocket_id="ws1" )
    assert r[ "path" ] == "agent"
    assert r[ "route_reason" ] == "resumed"
    assert r[ "status" ] == "done"
    assert r[ "answer" ] == "sunny"
    # the executor saw the resumed arg folded into the composed question (R-B4)
    assert "Boston" in exe.works[ 0 ].job.kwargs[ "question" ]
    # the AI-observable seam advanced the real entry pending -> running -> done
    assert pending.get( pid ).status == "done"
    assert pending.get( pid ).answer == "sunny"


def test_resume_reasks_when_more_args_remain( tmp_path, notifier, monkeypatch ):
    monkeypatch.setattr( flow_mod, "resolve",
                         lambda command: FakeSpec( required_args=( "location", "date" ) ) )
    pending  = PendingRequests()
    pid, _   = _park( pending, missing=[ "location", "date" ],
                      fallback_questions={ "location": "Which city?", "date": "Which day?" } )
    f = _make_flow( tmp_path, FakeCache(), FakeRouter(), FakeExpeditor(), FakeExecutor(), pending, notifier )
    r = f.resume( pending_id=pid, answer="Boston", websocket_id="ws1" )
    assert r[ "path" ] == "needs_input"
    assert r[ "status" ] == "parked"
    assert r[ "answer" ] == "Which day?"          # the NEXT question
    assert r[ "pending_id" ] == pid               # same id — the interview continues
    assert r[ "args_missing" ] == [ "date" ]
    # still parked, still pending — not advanced to running
    assert pending.get( pid ).status == "pending"


def test_resume_missing_pending_id_refuses_loudly( tmp_path, notifier ):
    pending = PendingRequests()
    f = _make_flow( tmp_path, FakeCache(), FakeRouter(), FakeExpeditor(), FakeExecutor(), pending, notifier )
    r = f.resume( pending_id="does-not-exist", answer="Boston", websocket_id="ws1" )
    assert r[ "status" ] == "expired"
    assert r[ "route_reason" ] == "pending_expired"
    assert r[ "path" ] == "needs_input"
    assert r[ "answer" ] is None                  # nothing rebuilt — a refusal, not a 500


def test_resume_expired_entry_refuses( tmp_path, notifier ):
    # a zero-TTL store expires the entry the instant it is read back.
    clock   = [ 0 ]
    pending = PendingRequests( ttl_seconds=0.0, clock=lambda: clock[ 0 ] )
    pid, _  = _park( pending )
    clock[ 0 ] = 1                                # advance past the (zero) TTL
    f = _make_flow( tmp_path, FakeCache(), FakeRouter(), FakeExpeditor(), FakeExecutor(), pending, notifier )
    r = f.resume( pending_id=pid, answer="Boston", websocket_id="ws1" )
    assert r[ "status" ] == "expired"
    assert r[ "route_reason" ] == "pending_expired"


def test_resume_unknown_command_degrades_and_marks_failed( tmp_path, notifier, monkeypatch ):
    monkeypatch.setattr( flow_mod, "resolve", lambda command: None )   # command no longer resolvable
    pending = PendingRequests()
    pid, _  = _park( pending, command="agent router go to ghost" )
    f = _make_flow( tmp_path, FakeCache(), FakeRouter(), FakeExpeditor(), FakeExecutor(), pending, notifier )
    r = f.resume( pending_id=pid, answer="Boston", websocket_id="ws1" )
    assert r[ "path" ] == "receptionist"
    assert r[ "route_reason" ] == "unknown_command"
    assert pending.get( pid ).status == "failed"


def test_resume_spawns_no_background_thread( tmp_path, notifier, monkeypatch ):
    """With resume synchronous, 'no background thread spawns' is a PERMANENT design
    invariant — the sibling guard on run() pins the park side; this pins the resume
    side, so the guarantee holds across the whole two-turn mechanism."""
    import threading

    monkeypatch.setattr( flow_mod, "resolve",
                         lambda command: FakeSpec( required_args=( "location", ), snapshotable=False ) )
    pending = PendingRequests()
    pid, _  = _park( pending )
    f = _make_flow( tmp_path, FakeCache(), FakeRouter(), FakeExpeditor(), FakeExecutor(), pending, notifier )

    before = { t.ident for t in threading.enumerate() }
    f.resume( pending_id=pid, answer="Boston", websocket_id="ws1" )
    after  = { t.ident for t in threading.enumerate() }
    assert after == before, f"resume spawned a background thread: {after - before}"


# ────────────────────────────────────────────────────────────── t_complete span (row 76a3c32d)
#
# t_complete is the closing bookend of the completion-symmetric span (t_recv ->
# t_complete), mirroring v1's RUNNING->COMPLETED for the paired harness report
# note. It is stamped once at the _emit chokepoint, so EVERY terminal exit carries
# it. Each test below would go red if the mark were removed (KeyError → the `in`
# assertion fails) — RED-provable per the 100% mandate. perf_counter_ns is
# monotonic, so t_complete >= t_first_useful >= t_recv holds without an injected clock.

def test_agent_path_stamps_t_complete_after_first_useful( tmp_path, notifier, monkeypatch ):
    monkeypatch.setattr( flow_mod, "resolve",
                         lambda command: FakeSpec( required_args=(), snapshotable=True ) )
    exe = FakeExecutor( _outcome( status="done", answer="42", answer_raw="42" ) )
    f = _make_flow( tmp_path, FakeCache(), FakeRouter(), FakeExpeditor(), exe,
                    FakePending(), notifier )
    r = f.run( "what time is it", **_CTX )
    timings = r[ "timings_ms" ]
    assert "t_complete" in timings                              # the completion bookend exists
    assert timings[ "t_complete" ] >= timings[ "t_first_useful" ]  # after the useful answer
    assert timings[ "t_complete" ] >= timings[ "t_recv" ]         # after the anchor (0.0)


def test_replay_path_stamps_t_complete( tmp_path, notifier ):
    snap  = types.SimpleNamespace( routing_command="agent router go to math" )
    cache = FakeCache( lookup_result=_lookup( is_replay_hit=True, snapshot=snap ) )
    exe   = FakeExecutor( _outcome( status="done", answer="4", answer_raw="4" ) )
    f     = _make_flow( tmp_path, cache, FakeRouter(), FakeExpeditor(), exe, FakePending(), notifier )
    r = f.run( "what is 2+2", **_CTX )
    assert "t_complete" in r[ "timings_ms" ]
    assert r[ "timings_ms" ][ "t_complete" ] >= r[ "timings_ms" ][ "t_first_useful" ]


def test_needs_input_path_stamps_t_complete( tmp_path, notifier, monkeypatch ):
    monkeypatch.setattr( flow_mod, "resolve",
                         lambda command: FakeSpec( required_args=( "location", ) ) )
    router     = FakeRouter( command="agent router go to weather" )
    extraction = _extraction( final_args={}, missing=[ "location" ],
                              fallback_questions={ "location": "Which city?" } )
    expeditor  = FakeExpeditor( extraction=extraction )
    f = _make_flow( tmp_path, FakeCache(), router, expeditor, FakeExecutor(), FakePending(), notifier )
    r = f.run( "what's the weather", **_CTX, interactive=True )
    timings = r[ "timings_ms" ]
    assert r[ "path" ] == "needs_input"
    assert "t_complete" in timings                              # needs_input turn is bookended too
    assert timings[ "t_complete" ] >= timings[ "t_first_useful" ]


def test_resume_complete_stamps_t_complete( tmp_path, notifier, monkeypatch ):
    monkeypatch.setattr( flow_mod, "resolve",
                         lambda command: FakeSpec( required_args=( "location", ), snapshotable=False ) )
    pending = PendingRequests()
    pid, _  = _park( pending )
    exe     = FakeExecutor( _outcome( status="done", answer="sunny", answer_raw="sunny raw" ) )
    f       = _make_flow( tmp_path, FakeCache(), FakeRouter(), FakeExpeditor(), exe, pending, notifier )
    r = f.resume( pending_id=pid, answer="Boston", websocket_id="ws1" )
    assert r[ "status" ] == "done"
    assert "t_complete" in r[ "timings_ms" ]


def test_resume_expired_stamps_t_complete( tmp_path, notifier ):
    # even the refusal path is bookended: t_recv + t_complete, no t_first_useful.
    pending = PendingRequests()
    f = _make_flow( tmp_path, FakeCache(), FakeRouter(), FakeExpeditor(), FakeExecutor(), pending, notifier )
    r = f.resume( pending_id="does-not-exist", answer="Boston", websocket_id="ws1" )
    timings = r[ "timings_ms" ]
    assert r[ "status" ] == "expired"
    assert "t_complete" in timings
    assert timings[ "t_complete" ] >= timings[ "t_recv" ]
