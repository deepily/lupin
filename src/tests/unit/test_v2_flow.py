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
from cosa.rest.v2 import registry as registry_mod
from cosa.rest.v2.flow import AskFlow
from cosa.rest.v2.pending import PendingRequests
from cosa.rest.v2.executor import InlineExecutor


# ────────────────────────────────────────────────────────────── fakes

class FakeAgent:
    """Constructible on the shared 11-kwarg signature; never actually run (the
    executor is faked, so do_all() is never reached from the flow's view).

    Carries `routing_command` because the QueueableJob protocol requires it
    (queue_protocol.py:61) and `_submit_prebuilt` now READS it rather than
    getattr-ing past its absence. A fake that omits a required attribute is a
    fake that lets a protocol violation pass in production."""

    def __init__( self, **kwargs ):
        self.kwargs          = kwargs
        self.routing_command = kwargs.get( "routing_command", "agent router go to fake" )

    def do_all( self ):                       # pragma: no cover - executor is faked
        return "unused"


class FakeReceptionist( FakeAgent ):
    pass


class FakeSpec:
    """Stand-in for registry.AgentSpec: the attrs the flow reads.

    `crud_factory` is one of them since 6-pre — the flow reads it to decide whether
    to read the cache at all. It defaults to None (a non-CRUD command) because that
    is what every registry row but todo and calendar carries; a fake that omitted it
    would raise AttributeError on a path production never fails on, since the real
    AgentSpec always has the field.
    """

    def __init__( self, required_args=(), factory=FakeAgent, snapshotable=True, label="math",
                  crud_factory=None ):
        self.required_args = required_args
        self.factory       = factory
        self.snapshotable  = snapshotable
        self.label         = label
        self.crud_factory  = crud_factory


def _lookup( is_replay_hit=False, snapshot=None, tier=1, similarity=0.0, best_score=0.0,
             best_candidate=None, embed_cached=False, question_normalized="q",
             t_exact_ms=0.1, t_embed_ms=0.2, t_ann_ms=0.3 ):
    return types.SimpleNamespace(
        is_replay_hit=is_replay_hit, snapshot=snapshot, tier=tier, similarity=similarity,
        best_score=best_score, best_candidate=best_candidate, embed_cached=embed_cached,
        question_normalized=question_normalized, t_exact_ms=t_exact_ms,
        t_embed_ms=t_embed_ms, t_ann_ms=t_ann_ms,
    )


def _outcome( status="done", answer="the answer", answer_raw="raw", job_id=None, error=None,
              code=None, code_example="solution = do_something()", code_returns="string" ):
    """A stand-in Outcome.

    `code` defaults to a real one-line solution because that is what a done outcome
    from a code-generating agent carries — the executor now copies the agent's code out
    so the write-back can persist it. A default of None would make every write-back
    test in this file exercise the unreplayable-row path instead of the one it is
    about; the tests that DO want that path pass code=None explicitly.
    """
    return types.SimpleNamespace( status=status, answer=answer, answer_raw=answer_raw,
                                  job_id=job_id, error=error,
                                  code=[ "solution = 4" ] if code is None else code,
                                  code_example=code_example, code_returns=code_returns )


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
        self.gist_calls     = []

    def lookup( self, question ):
        return self._lookup

    def gist( self, question ):
        self.gist_calls.append( question )
        return f"gist:{question}"

    def normalize( self, question ):
        return question.lower()

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

    def gist( self, question ):
        return f"gist:{question}"

    def normalize( self, question ):
        return question.lower()


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
                *, writeback_enabled=False, similarity_floor=100.0, crud_enabled=False,
                agentic_factory=None ):
    return AskFlow(
        cache, router, expeditor, executor, pending,
        crud_enabled=crud_enabled,
        similarity_floor=similarity_floor, writeback_enabled=writeback_enabled,
        receptionist_factory=FakeReceptionist, notifier=notifier,
        agentic_factory=agentic_factory,
        trace_dir=str( tmp_path ),
    )


# A REAL scoped job id: register_scoped_job returns "{id_hash}::{user_id}", and
# AsyncNotificationRequest pattern-validates that shape (64-hex hash :: uuid).
# The gate tests above never hit the validator because a waiting outcome with no
# label speaks nothing, so nothing was built — these tests DO speak, and a
# made-up id fails at the model before it can reach the assertion.
_SCOPED_JOB_ID = "b" * 64 + "::11111111-2222-3333-4444-555555555555"


_CTX = dict( user_id="u1", user_email="u@x.com", session_id="s1", websocket_id="ws1" )


# ────────────────────────────────────────────────────────────── construction guard

def test_construction_raises_when_writeback_on_but_cache_lacks_methods( tmp_path, notifier ):
    with pytest.raises( ValueError, match="writeback enabled" ):
        AskFlow( CacheNoWriteBack(), FakeRouter(), FakeExpeditor(), FakeExecutor(),
                 FakePending(), crud_enabled=False, writeback_enabled=True, notifier=notifier,
                 trace_dir=str( tmp_path ) )


def test_construction_ok_when_writeback_on_and_cache_has_methods( tmp_path, notifier ):
    f = AskFlow( FakeCache(), FakeRouter(), FakeExpeditor(), FakeExecutor(), FakePending(),
                 crud_enabled=False, writeback_enabled=True, notifier=notifier, trace_dir=str( tmp_path ) )
    assert f.writeback_enabled is True


def test_construction_ok_when_writeback_off_even_without_methods( tmp_path, notifier ):
    f = AskFlow( CacheNoWriteBack(), FakeRouter(), FakeExpeditor(), FakeExecutor(),
                 FakePending(), crud_enabled=False, writeback_enabled=False, notifier=notifier,
                 trace_dir=str( tmp_path ) )
    assert f.writeback_enabled is False


# ────────────────────────────────────────────────────────────── branch 1 — replay

def test_replay_hit_done_returns_replay_result( tmp_path, notifier ):
    snap  = types.SimpleNamespace( routing_command="agent router go to math" )
    cache = FakeCache( lookup_result=_lookup( is_replay_hit=True, snapshot=snap ) )
    exe   = FakeExecutor( _outcome( status="done", answer="4", answer_raw="4" ) )
    f     = _make_flow( tmp_path, cache, FakeRouter(), FakeExpeditor(), exe, FakePending(), notifier )
    r = f.ask( "what is 2+2", **_CTX, speak=True, interactive=True )
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
    r = f.ask( "what is 2+2", **_CTX )
    assert r[ "path" ] == "receptionist"
    assert r[ "route_reason" ] == "replay_error"


# ────────────────────────────────────────────────────────────── branch 2 — router

def test_router_unknown_degrades_to_receptionist( tmp_path, notifier ):
    router = FakeRouter( command="unknown", raw_args="" )
    f = _make_flow( tmp_path, FakeCache(), router, FakeExpeditor(), FakeExecutor(),
                    FakePending(), notifier )
    r = f.ask( "gibberish", **_CTX )
    assert r[ "path" ] == "receptionist"
    assert r[ "route_reason" ] == "router_error"


def test_resolve_none_degrades_to_receptionist( tmp_path, notifier, monkeypatch ):
    monkeypatch.setattr( flow_mod, "resolve", lambda command, crud_enabled: None )
    router = FakeRouter( command="agent router go to deep research" )
    f = _make_flow( tmp_path, FakeCache(), router, FakeExpeditor(), FakeExecutor(),
                    FakePending(), notifier )
    r = f.ask( "do deep research", **_CTX )
    assert r[ "path" ] == "receptionist"
    assert r[ "route_reason" ] == "unknown_command"


# ────────────────────────────────────────────────────────────── branch — args_none

def test_args_none_runs_agent_directly( tmp_path, notifier, monkeypatch ):
    monkeypatch.setattr( flow_mod, "resolve", lambda command, crud_enabled: FakeSpec( required_args=(), snapshotable=True ) )
    exe = FakeExecutor( _outcome( status="done", answer="42", answer_raw="42" ) )
    f = _make_flow( tmp_path, FakeCache(), FakeRouter(), FakeExpeditor(), exe,
                    FakePending(), notifier )
    r = f.ask( "what time is it", **_CTX )
    assert r[ "path" ] == "agent"
    assert r[ "route_reason" ] == "args_none"
    assert exe.works[ 0 ].kind == "agent"


# ────────────────────────────────────────────────────────────── branch — extract fails

def test_extract_exception_degrades_to_receptionist( tmp_path, notifier, monkeypatch ):
    monkeypatch.setattr( flow_mod, "resolve", lambda command, crud_enabled: FakeSpec( required_args=( "location", ) ) )
    router    = FakeRouter( command="agent router go to weather" )
    expeditor = FakeExpeditor( raise_exc=RuntimeError( "extractor blew up" ) )
    f = _make_flow( tmp_path, FakeCache(), router, expeditor, FakeExecutor(),
                    FakePending(), notifier )
    r = f.ask( "weather", **_CTX )
    assert r[ "path" ] == "receptionist"
    assert r[ "route_reason" ] == "extract_error"


# ────────────────────────────────────────────────────────────── branch 3 — needs_input

def test_needs_input_interactive_parks_and_returns_first_question( tmp_path, notifier, monkeypatch ):
    monkeypatch.setattr( flow_mod, "resolve", lambda command, crud_enabled: FakeSpec( required_args=( "location", ) ) )
    router    = FakeRouter( command="agent router go to weather" )
    extraction = _extraction( final_args={}, missing=[ "location" ],
                              fallback_questions={ "location": "Which city?" } )
    expeditor = FakeExpeditor( extraction=extraction )
    pending   = FakePending()
    f = _make_flow( tmp_path, FakeCache(), router, expeditor, FakeExecutor(), pending, notifier )
    r = f.ask( "what's the weather", **_CTX, interactive=True )
    assert r[ "path" ] == "needs_input"
    assert r[ "status" ] == "parked"
    assert r[ "answer" ] == "Which city?"
    assert r[ "pending_id" ] == "pend-1"
    assert r[ "args_missing" ] == [ "location" ]
    assert len( pending.put_calls ) == 1


def test_needs_input_non_interactive_does_not_park( tmp_path, notifier, monkeypatch ):
    monkeypatch.setattr( flow_mod, "resolve", lambda command, crud_enabled: FakeSpec( required_args=( "location", ) ) )
    router     = FakeRouter( command="agent router go to weather" )
    extraction = _extraction( final_args={}, missing=[ "location" ], fallback_questions={} )
    expeditor  = FakeExpeditor( extraction=extraction )
    pending    = FakePending()
    f = _make_flow( tmp_path, FakeCache(), router, expeditor, FakeExecutor(), pending, notifier )
    r = f.ask( "what's the weather", **_CTX, interactive=False )
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

    monkeypatch.setattr( flow_mod, "resolve", lambda command, crud_enabled: FakeSpec( required_args=( "location", ) ) )
    router     = FakeRouter( command="agent router go to weather" )
    extraction = _extraction( final_args={}, missing=[ "location" ], fallback_questions={} )
    expeditor  = FakeExpeditor( extraction=extraction )
    pending    = FakePending()
    f = _make_flow( tmp_path, FakeCache(), router, expeditor, FakeExecutor(), pending, notifier )

    before = { t.ident for t in threading.enumerate() }
    r      = f.ask( "what's the weather", **_CTX, interactive=False )
    after  = { t.ident for t in threading.enumerate() }

    assert r[ "status" ] == "needs_input"
    assert after == before, (
        "non-interactive run spawned a background thread — the never-blocks "
        f"guarantee is broken. new thread ids: {after - before}"
    )


# ────────────────────────────────────────────────────────────── branch — args_complete

def test_args_complete_runs_agent_and_writes_back( tmp_path, notifier, monkeypatch ):
    monkeypatch.setattr( flow_mod, "resolve", lambda command, crud_enabled: FakeSpec( required_args=( "location", ), snapshotable=True ) )
    router     = FakeRouter( command="agent router go to weather" )
    extraction = _extraction( final_args={ "location": "Boston" }, missing=[] )
    expeditor  = FakeExpeditor( extraction=extraction )
    cache      = FakeCache( write_back_id="snap-999" )
    exe        = FakeExecutor( _outcome( status="done", answer="sunny", answer_raw="sunny raw" ) )
    f = _make_flow( tmp_path, cache, router, expeditor, exe, FakePending(), notifier,
                    writeback_enabled=True )
    r = f.ask( "weather in Chicago", **_CTX )
    assert r[ "path" ] == "agent"
    assert r[ "route_reason" ] == "args_complete"
    assert r[ "snapshot_id" ] == "snap-999"
    assert r[ "wrote_snapshot" ] is True
    assert len( cache.snapshot_calls ) == 1
    assert cache.write_back_calls[ 0 ][ 1 ] is True   # writeback_enabled forwarded


def test_agent_failure_degrades_to_receptionist( tmp_path, notifier, monkeypatch ):
    monkeypatch.setattr( flow_mod, "resolve", lambda command, crud_enabled: FakeSpec( required_args=(), snapshotable=True ) )
    outcomes = [ _outcome( status="failed", error="agent boom" ), _outcome( status="done" ) ]

    class _SeqExecutor( FakeExecutor ):
        def submit( self, work, trace ):
            self.works.append( work )
            return outcomes.pop( 0 )

    exe = _SeqExecutor()
    f = _make_flow( tmp_path, FakeCache(), FakeRouter(), FakeExpeditor(), exe,
                    FakePending(), notifier )
    r = f.ask( "do a thing", **_CTX )
    assert r[ "path" ] == "receptionist"
    assert r[ "route_reason" ] == "agent_error"


# ────────────────────────────────────────────────────────────── write-back seam

def test_no_write_back_when_agent_not_snapshotable( tmp_path, notifier, monkeypatch ):
    monkeypatch.setattr( flow_mod, "resolve", lambda command, crud_enabled: FakeSpec( required_args=(), snapshotable=False ) )
    cache = FakeCache()
    f = _make_flow( tmp_path, cache, FakeRouter(), FakeExpeditor(), FakeExecutor(),
                    FakePending(), notifier, writeback_enabled=True )
    r = f.ask( "do a thing", **_CTX )
    assert r[ "path" ] == "agent"
    assert r[ "snapshot_id" ] is None
    assert r[ "wrote_snapshot" ] is False
    assert cache.snapshot_calls == []


def test_write_back_returning_none_marks_no_snapshot( tmp_path, notifier, monkeypatch ):
    # snapshotable+done, but write_back returns None (flag off inside the cache) →
    # snapshot_from_result IS called, but no t_writeback mark and wrote_snapshot False.
    monkeypatch.setattr( flow_mod, "resolve", lambda command, crud_enabled: FakeSpec( required_args=(), snapshotable=True ) )
    cache = FakeCache( write_back_id=None )
    f = _make_flow( tmp_path, cache, FakeRouter(), FakeExpeditor(), FakeExecutor(),
                    FakePending(), notifier, writeback_enabled=True )
    r = f.ask( "do a thing", **_CTX )
    assert r[ "snapshot_id" ] is None
    assert r[ "wrote_snapshot" ] is False
    assert len( cache.snapshot_calls ) == 1


# ────────────────────────────────────────────────────────────── _speak forks

def test_speak_off_dispatches_no_notification( tmp_path, notifier, monkeypatch ):
    monkeypatch.setattr( flow_mod, "resolve", lambda command, crud_enabled: FakeSpec( required_args=() ) )
    f = _make_flow( tmp_path, FakeCache(), FakeRouter(), FakeExpeditor(), FakeExecutor(),
                    FakePending(), notifier )
    r = f.ask( "do a thing", **_CTX, speak=False )
    assert notifier.requests == []
    assert r[ "spoke" ] is False


def test_speak_on_with_answer_dispatches_notification( tmp_path, notifier, monkeypatch ):
    monkeypatch.setattr( flow_mod, "resolve", lambda command, crud_enabled: FakeSpec( required_args=() ) )
    exe = FakeExecutor( _outcome( status="done", answer="hello", answer_raw="hello" ) )
    f = _make_flow( tmp_path, FakeCache(), FakeRouter(), FakeExpeditor(), exe,
                    FakePending(), notifier )
    r = f.ask( "do a thing", **_CTX, speak=True )
    assert len( notifier.requests ) == 1
    assert r[ "spoke" ] is True


def test_speak_on_but_empty_message_dispatches_nothing( tmp_path, notifier, monkeypatch ):
    monkeypatch.setattr( flow_mod, "resolve", lambda command, crud_enabled: FakeSpec( required_args=() ) )
    exe = FakeExecutor( _outcome( status="done", answer=None, answer_raw=None ) )
    f = _make_flow( tmp_path, FakeCache(), FakeRouter(), FakeExpeditor(), exe,
                    FakePending(), notifier )
    r = f.ask( "do a thing", **_CTX, speak=True )
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

    monkeypatch.setattr( flow_mod, "resolve", lambda command, crud_enabled: FakeSpec( required_args=( "a", ), factory=_CapturingAgent,
                                                   snapshotable=False ) )
    f = _make_flow( tmp_path, FakeCache(), router, expeditor, FakeExecutor(),
                    FakePending(), notifier )
    f.ask( "weather in already", **_CTX )
    q = captured[ "question" ]
    assert "Boston" in q            # truthy + absent → appended
    assert q.lower().count( "already" ) == 1  # present already → not re-appended
    assert q.count( "" ) >= 0       # empty value → skipped (no crash)


# ────────────────────────────────────────────────────────────── _arg_spec_for forks

def test_arg_spec_for_synthesizes_weather_when_not_in_table( tmp_path, notifier, monkeypatch ):
    # weather is NOT in JOB_ARG_CONTRACTS → the call-site ArgSpec is synthesized (R-B3).
    monkeypatch.setattr( flow_mod, "resolve", lambda command, crud_enabled: FakeSpec( required_args=( "location", ) ) )
    router  = FakeRouter( command="agent router go to weather" )
    spec = AskFlow( FakeCache(), router, FakeExpeditor(), FakeExecutor(), FakePending(),
                    crud_enabled=False, notifier=notifier, trace_dir=str( tmp_path ) )._arg_spec_for(
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
    f = AskFlow( FakeCache(), FakeRouter(), FakeExpeditor(), FakeExecutor(), FakePending(), crud_enabled=False,
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
    monkeypatch.setattr( flow_mod, "resolve", lambda command, crud_enabled: FakeSpec( required_args=( "location", ), snapshotable=False ) )
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
    monkeypatch.setattr( flow_mod, "resolve", lambda command, crud_enabled: FakeSpec( required_args=( "location", "date" ) ) )
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


def test_second_resume_of_one_conversation_is_refused_as_already_resumed( tmp_path, notifier, monkeypatch ):
    """
    A second resume that loses the claim is refused, and says WHY in its own words.

    The first resume runs the agent and drives the entry to done; the second finds
    it no longer "pending" and must not run the agent again. Before claim(), the
    liveness read and the "running" write were two separate lock acquisitions with
    the agent run between them, so a second caller could pass the check and run a
    duplicate agent on the same conversation — unreachable while the handler was on
    the event loop, reachable the moment it moved to a worker thread.

    RED ON REVERT: put `self.pending.set_status( pending_id, "running" )` back in
    place of the claim() guard and the second resume runs the agent again.
    """
    monkeypatch.setattr( flow_mod, "resolve", lambda command, crud_enabled: FakeSpec( required_args=( "location", ), snapshotable=False ) )
    pending = PendingRequests()
    pid, _  = _park( pending )
    exe     = FakeExecutor( _outcome( status="done", answer="sunny", answer_raw="sunny raw" ) )
    f       = _make_flow( tmp_path, FakeCache(), FakeRouter(), FakeExpeditor(), exe, pending, notifier )

    first = f.resume( pending_id=pid, answer="Boston", websocket_id="ws1" )
    assert first[ "status" ] == "done"
    assert len( exe.works ) == 1

    second = f.resume( pending_id=pid, answer="Boston", websocket_id="ws1" )
    assert second[ "route_reason" ] == "already_resumed"
    assert second[ "path" ] == "needs_input"
    assert second[ "answer" ] is None
    assert len( exe.works ) == 1, "the losing resume ran the agent a second time on one conversation"


def test_second_resume_never_raises_indexerror( tmp_path, notifier, monkeypatch ):
    """
    The 500 this route used to return, pinned by its exception type.

    At HEAD a second resume of a completed conversation reached
    `extraction.missing[ 0 ]` (flow.py:163) on a list the FIRST resume had already
    emptied, and raised IndexError — a 500 out of the one path whose docstring
    promises "never a 500". Nothing checked whether the conversation had already
    been answered. It needed no concurrency: the entry lives in the store until its
    TTL, so a retry or a double-clicked answer reached it on the single event loop.

    The sibling tests assert the REFUSAL; this one asserts the ABSENCE OF THE
    CRASH. They are not the same claim — a future edit could return a well-formed
    refusal on one branch and still raise on another, and only this test would say
    so.

    RED ON REVERT: remove the `entry.status != "pending"` early refusal and this
    raises IndexError instead of failing an assertion.
    """
    monkeypatch.setattr( flow_mod, "resolve", lambda command, crud_enabled: FakeSpec( required_args=( "location", ), snapshotable=False ) )
    pending = PendingRequests()
    pid, _  = _park( pending )
    exe     = FakeExecutor( _outcome( status="done", answer="sunny", answer_raw="sunny raw" ) )
    f       = _make_flow( tmp_path, FakeCache(), FakeRouter(), FakeExpeditor(), exe, pending, notifier )
    f.resume( pending_id=pid, answer="Boston", websocket_id="ws1" )

    try:
        second = f.resume( pending_id=pid, answer="Boston", websocket_id="ws1" )
    except IndexError as e:
        raise AssertionError(
            f"second resume raised IndexError ({e}) — the 500 is back; the route's "
            f"contract says it degrades to a needs_input refusal, never a 500."
        )
    assert second[ "status" ] == "expired"
    assert second[ "path" ]   == "needs_input"


def test_a_second_resume_cannot_enter_the_interview_while_one_is_inside_it( tmp_path, notifier, monkeypatch ):
    """
    Two resumes must never both be inside the extraction mutation.

    María found this (row b28be422) and my first attempt to pin it FAILED TO
    DISCRIMINATE: racing two whole resumes, guarded and unguarded gave identical
    results in 30 runs each, because the critical section is a few statements wide
    and the threads almost never interleave inside it. I nearly reported the race
    as unobservable on that evidence.

    Holding one resume INSIDE the section makes it deterministic. `final_args` is a
    dict subclass whose first write parks until released, so the second resume
    arrives while the first is provably mid-mutation. Measured both ways:

        guarded   -> second refused "already_resumed"; writes = [ location ]
        unguarded -> second proceeds;                  writes = [ location, location ]

    Two writes to the SAME slot is one user's answer silently overwritten by
    another's. Not reachable while resume ran on the event loop; reachable the
    moment it moved to a worker thread — this commit.

    RED ON REVERT: drop the claim()/release_turn() pair from flow.resume and the
    second resume writes "location" a second time.
    """
    import threading

    inside  = threading.Event()
    hold    = threading.Event()
    writes  = []

    class ParkingArgs( dict ):
        """final_args whose FIRST write parks inside the critical section."""
        def __setitem__( self, key, value ):
            writes.append( key )
            if len( writes ) == 1:
                inside.set()
                hold.wait( timeout=5 )
            super().__setitem__( key, value )

    monkeypatch.setattr( flow_mod, "resolve", lambda command, crud_enabled: FakeSpec( required_args=( "location", "date" ), snapshotable=False ) )
    pending = PendingRequests()
    pid, _  = _park( pending )
    entry   = pending.get( pid )
    entry.extraction.missing    = [ "location", "date" ]
    entry.extraction.final_args = ParkingArgs()

    exe = FakeExecutor( _outcome( status="done", answer="sunny", answer_raw="raw" ) )
    f   = _make_flow( tmp_path, FakeCache(), FakeRouter(), FakeExpeditor(), exe, pending, notifier )

    first = threading.Thread(
        target=lambda: f.resume( pending_id=pid, answer="Boston", websocket_id="ws1" ) )
    first.start()
    assert inside.wait( timeout=5 ), "the first resume never entered the mutation — nothing was tested"

    second = f.resume( pending_id=pid, answer="Tuesday", websocket_id="ws1" )

    hold.set()
    first.join( timeout=5 )

    assert second[ "route_reason" ] == "already_resumed", second
    assert writes == [ "location" ], (
        f"both resumes wrote into the interview: {writes} — the second overwrote the "
        f"first caller's answer in the same slot."
    )


def test_the_flow_never_routes_through_the_expeditors_stateful_half( tmp_path, notifier, monkeypatch ):
    """
    TRIPWIRE: the shared expeditor must stay stateless across a v2 request.

    `RuntimeArgumentExpeditor` keeps per-call state on the instance —
    `_job_id`, `_bearer_token`, `_last_expedite_reason` (expeditor.py:309-311) —
    and the flow holds ONE expeditor. Those writes live in `expedite()` and
    `collect()`; `extract()`, which is all the flow calls (flow.py:121), writes
    none of them. Verified by walking the call graph, not by grep: `extract()`
    touches none of the three even transitively.

    So there is no bearer-token crossover on the v2 path today. But the handlers
    now run OFF the event loop, so two v2 requests can be in the flow at once —
    and if anyone ever routes the flow through the stateful half, one user's
    bearer token becomes readable by another's request. That is a security-shaped
    failure that no existing test would notice, because every functional
    assertion would still pass.

    This test is the tripwire for that day. It does not test today's behaviour so
    much as pin the boundary that makes today's behaviour safe.

    It compares the expeditor's ENTIRE __dict__ before and after, rather than a
    list of the attribute names known today. A hand-list would pass the day
    someone adds a fifth per-call attribute — exactly the change worth catching.

    RED ON REVERT — the exact mutation, which was run: in `flow.py`, replace
    `self.expeditor.extract( command, raw_args, question, arg_spec )` with
    `self.expeditor.expedite( command, raw_args, ctx[ 1 ], ctx[ 2 ], ctx[ 0 ], question,
    job_id="job-1", bearer_token="tok-1" )`. `expedite` stamps `_job_id`,
    `_bearer_token` and `_last_expedite_reason` on the instance before it does
    anything else (`expeditor.py:309-311`), so the sentinels come back changed.

    ⚠️ TWO THINGS MAKE THAT MUTATION ACTUALLY BITE, and without either one this
    test passes under its own named revert:
      1. The stub below carries `expedite()` and `collect()`, not `extract()`
         alone. A stub missing the method answers `AttributeError`, which
         `flow.py`'s `except Exception` folds into the receptionist path — the
         real instance is never touched and the comparison stays green.
      2. The real instance is wired far enough for `extract()` to RUN. Built by
         `__new__` alone it raises at `self.debug` (`expeditor.py:367`) before
         reaching a line that could write anything, so the delegation proved
         nothing. It gets the five wiring attributes `extract()` reads, with a
         fake LLM client and a fake template read: no config, no network, and
         still the real code path.
    """
    import cosa.agents.runtime_argument_expeditor.expeditor as expeditor_mod
    from cosa.agents.runtime_argument_expeditor.expeditor import RuntimeArgumentExpeditor

    monkeypatch.setattr( flow_mod, "resolve", lambda command, crud_enabled: FakeSpec( required_args=( "location", ), snapshotable=False ) )

    class FakeLlmClient:
        def run( self, prompt ):
            return ( "<response><all_required_met>true</all_required_met>"
                     "<args_present>location=Boston</args_present>"
                     "<args_missing></args_missing></response>" )

    # Fake the template read rather than depend on a real prompt file's brace
    # content — the LLM call and the file read are the only two things standing
    # between this test and the real extract() body.
    monkeypatch.setattr(
        expeditor_mod.cu, "get_file_as_string",
        lambda path: "SYS {system_args} HELP {help_text} Q {voice_command} "
                     "EXTRACTED {extracted_args} REQUIRED {required_args}"
    )

    real = RuntimeArgumentExpeditor.__new__( RuntimeArgumentExpeditor )   # no __init__: no config, no network
    real.debug                = False
    real.verbose              = False
    real.prompt_template_path = "/unused — the read above is faked"
    real.llm_spec_key         = "fake-llm"
    real.llm_factory          = types.SimpleNamespace(
        get_client=lambda key, debug=False, verbose=False: FakeLlmClient()
    )

    # Sentinel the WHOLE instance state, not a hand-list of the names I happen to
    # know about. A list of four would pass the day someone adds a fifth per-call
    # attribute — which is precisely the change this tripwire needs to catch.
    for name in ( "_job_id", "_bearer_token", "_last_expedite_reason",
                  "_last_notification_status" ):
        setattr( real, name, f"SENTINEL-{name}" )
    before = dict( real.__dict__ )

    class DelegatingExpeditor:
        """Delegates EVERY method the flow could reach to the real class, so a
        change of which method the flow calls is felt on the real instance.

        A stub carrying extract() alone was not enough, and made this test
        vacuous under its own named mutation: point the flow at expedite() and
        the stub answers AttributeError, which flow.py:123's `except Exception`
        turns into the receptionist path — the real instance is never touched
        and the sentinel comparison below passes while the boundary it exists to
        guard is gone. Each name is appended AFTER the real call returns, so
        `delegated` records methods that actually RAN, not merely ones that were
        entered.
        """

        def __init__( self ):
            self.delegated = []

        def extract( self, command, raw_args, question, spec ):
            RuntimeArgumentExpeditor.extract( real, command, raw_args, question, spec )
            self.delegated.append( "extract" )
            return _extraction( final_args={ "location": "Boston" }, missing=[] )

        def expedite( self, command, raw_args, user_email, session_id, user_id, original_question,
                      job_id=None, bearer_token=None ):
            RuntimeArgumentExpeditor.expedite( real, command, raw_args, user_email, session_id,
                                               user_id, original_question,
                                               job_id=job_id, bearer_token=bearer_token )
            self.delegated.append( "expedite" )
            return _extraction( final_args={ "location": "Boston" }, missing=[] )

        def collect( self, extraction, command, original_question, spec,
                     user_email, session_id, user_id ):
            RuntimeArgumentExpeditor.collect( real, extraction, command, original_question, spec,
                                              user_email, session_id, user_id )
            self.delegated.append( "collect" )
            return _extraction( final_args={ "location": "Boston" }, missing=[] )

    stub = DelegatingExpeditor()
    f = _make_flow( tmp_path, FakeCache(), FakeRouter(), stub,
                    FakeExecutor( _outcome( status="done", answer="sunny", answer_raw="raw" ) ),
                    PendingRequests(), notifier )
    f.ask( question="weather in Boston", user_id="u1", user_email="u@x", session_id="s1",
           websocket_id="ws1", speak=False, interactive=False )

    # Anti-vacuity control. Without this, a request that reached NO expeditor
    # method at all — or one whose real implementation threw before writing
    # anything — would leave the sentinels untouched and read as a pass.
    assert stub.delegated == [ "extract" ], (
        f"the flow ran {stub.delegated} to completion on the real expeditor. Empty means "
        f"no real method ran at all and the sentinel comparison below is vacuous; anything "
        f"other than ['extract'] means the flow has reached the stateful half"
    )

    after   = dict( real.__dict__ )
    changed = { k for k in set( before ) | set( after ) if before.get( k, object() ) != after.get( k, object() ) }
    assert not changed, (
        f"a v2 request wrote {sorted( changed )} on the SHARED expeditor. Both handlers "
        f"now run off the event loop, so two concurrent requests would read each other's "
        f"values — for _bearer_token that is one user's credential reaching another."
    )


def test_already_resumed_is_distinguishable_from_pending_expired( tmp_path, notifier, monkeypatch ):
    """
    The two refusals must not share a route_reason.

    They are the same SHAPE — status "expired", path needs_input, no answer — so a
    test asserting only the shape would pass with one reason serving both. A log
    that cannot tell a lost race from a timed-out conversation sends the reader
    looking at TTLs for a concurrency bug.

    RED ON REVERT: give the claim refusal route_reason="pending_expired" and this
    fails while every shape assertion above still passes.
    """
    monkeypatch.setattr( flow_mod, "resolve", lambda command, crud_enabled: FakeSpec( required_args=( "location", ), snapshotable=False ) )
    pending = PendingRequests()
    pid, _  = _park( pending )
    exe     = FakeExecutor( _outcome( status="done", answer="sunny", answer_raw="sunny raw" ) )
    f       = _make_flow( tmp_path, FakeCache(), FakeRouter(), FakeExpeditor(), exe, pending, notifier )
    f.resume( pending_id=pid, answer="Boston", websocket_id="ws1" )

    lost_race = f.resume( pending_id=pid, answer="Boston", websocket_id="ws1" )
    dead_id   = f.resume( pending_id="does-not-exist", answer="Boston", websocket_id="ws1" )

    assert lost_race[ "route_reason" ] == "already_resumed"
    assert dead_id[ "route_reason" ]   == "pending_expired"
    assert lost_race[ "route_reason" ] != dead_id[ "route_reason" ]


def test_resume_unknown_command_degrades_and_marks_failed( tmp_path, notifier, monkeypatch ):
    monkeypatch.setattr( flow_mod, "resolve", lambda command, crud_enabled: None )   # command no longer resolvable
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

    monkeypatch.setattr( flow_mod, "resolve", lambda command, crud_enabled: FakeSpec( required_args=( "location", ), snapshotable=False ) )
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
    monkeypatch.setattr( flow_mod, "resolve", lambda command, crud_enabled: FakeSpec( required_args=(), snapshotable=True ) )
    exe = FakeExecutor( _outcome( status="done", answer="42", answer_raw="42" ) )
    f = _make_flow( tmp_path, FakeCache(), FakeRouter(), FakeExpeditor(), exe,
                    FakePending(), notifier )
    r = f.ask( "what time is it", **_CTX )
    timings = r[ "timings_ms" ]
    assert "t_complete" in timings                              # the completion bookend exists
    assert timings[ "t_complete" ] >= timings[ "t_first_useful" ]  # after the useful answer
    assert timings[ "t_complete" ] >= timings[ "t_recv" ]         # after the anchor (0.0)


def test_replay_path_stamps_t_complete( tmp_path, notifier ):
    snap  = types.SimpleNamespace( routing_command="agent router go to math" )
    cache = FakeCache( lookup_result=_lookup( is_replay_hit=True, snapshot=snap ) )
    exe   = FakeExecutor( _outcome( status="done", answer="4", answer_raw="4" ) )
    f     = _make_flow( tmp_path, cache, FakeRouter(), FakeExpeditor(), exe, FakePending(), notifier )
    r = f.ask( "what is 2+2", **_CTX )
    assert "t_complete" in r[ "timings_ms" ]
    assert r[ "timings_ms" ][ "t_complete" ] >= r[ "timings_ms" ][ "t_first_useful" ]


def test_needs_input_path_stamps_t_complete( tmp_path, notifier, monkeypatch ):
    monkeypatch.setattr( flow_mod, "resolve", lambda command, crud_enabled: FakeSpec( required_args=( "location", ) ) )
    router     = FakeRouter( command="agent router go to weather" )
    extraction = _extraction( final_args={}, missing=[ "location" ],
                              fallback_questions={ "location": "Which city?" } )
    expeditor  = FakeExpeditor( extraction=extraction )
    f = _make_flow( tmp_path, FakeCache(), router, expeditor, FakeExecutor(), FakePending(), notifier )
    r = f.ask( "what's the weather", **_CTX, interactive=True )
    timings = r[ "timings_ms" ]
    assert r[ "path" ] == "needs_input"
    assert "t_complete" in timings                              # needs_input turn is bookended too
    assert timings[ "t_complete" ] >= timings[ "t_first_useful" ]


def test_resume_complete_stamps_t_complete( tmp_path, notifier, monkeypatch ):
    monkeypatch.setattr( flow_mod, "resolve", lambda command, crud_enabled: FakeSpec( required_args=( "location", ), snapshotable=False ) )
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


# ──────────────────────────────────── the degrade must not hide the fault it was reached by
#
# Live receipt, :8000 run ts-333d04de (2026-08-19): the v2 resume of a weather
# question degraded to the receptionist and the emitted error was the
# RECEPTIONIST's. The weather agent's own failure — the reason the degrade
# happened at all — was dropped on the floor, so the run said why the fallback
# died and nothing about why the real agent did. These three tests pin the three
# shapes of the composed error.

def _degrade_flow( tmp_path, notifier, monkeypatch, primary_error, fallback_outcome ):
    """Run a flow whose primary agent fails and whose receptionist returns fallback_outcome."""
    monkeypatch.setattr( flow_mod, "resolve", lambda command, crud_enabled: FakeSpec( required_args=(), snapshotable=True ) )
    outcomes = [ _outcome( status="failed", error=primary_error ), fallback_outcome ]

    class _SeqExecutor( FakeExecutor ):
        def submit( self, work, trace ):
            self.works.append( work )
            return outcomes.pop( 0 )

    f = _make_flow( tmp_path, FakeCache(), FakeRouter(), FakeExpeditor(), _SeqExecutor(),
                    FakePending(), notifier )
    return f.ask( "do a thing", **_CTX )


def test_degrade_keeps_the_primary_agent_error_when_receptionist_succeeds( tmp_path, notifier, monkeypatch ):
    """The cause survives even when the fallback answers fine — otherwise error is None."""
    r = _degrade_flow( tmp_path, notifier, monkeypatch,
                       primary_error="maximum context length is 8192 tokens",
                       fallback_outcome=_outcome( status="done", error=None ) )
    assert r[ "route_reason" ] == "agent_error"
    assert r[ "error" ] == "primary agent failed: maximum context length is 8192 tokens"


def test_degrade_reports_both_errors_when_the_receptionist_also_fails( tmp_path, notifier, monkeypatch ):
    """Tonight's live shape: both halves died and both must be readable."""
    r = _degrade_flow( tmp_path, notifier, monkeypatch,
                       primary_error="agent boom",
                       fallback_outcome=_outcome( status="failed", error="receptionist boom" ) )
    assert r[ "error" ] == "primary agent failed: agent boom | receptionist: receptionist boom"


def test_degrade_with_no_primary_error_still_reports_the_fallback_error( tmp_path, notifier, monkeypatch ):
    """Negative control — a primary that failed WITHOUT an error message must not
    invent a 'primary agent failed: None' prefix, and the fallback's error must
    still reach the caller unchanged."""
    r = _degrade_flow( tmp_path, notifier, monkeypatch,
                       primary_error=None,
                       fallback_outcome=_outcome( status="failed", error="receptionist boom" ) )
    assert r[ "error" ] == "receptionist boom"


# ──────────────────────────────────────────── steps 2+3 — the two "waiting" gates

class TestWaitingIsSuccessInFlight:
    """
    A queued executor answers `waiting`: the work was handed off, not finished
    and not failed. Exactly TWO status gates accept it — the replay branch in
    `run()` and `_run_agent` — and the write-back guard deliberately does NOT.

    One test per gate, each red when its OWN gate is narrowed back, plus the
    third holding the guard that must not move. Written together because the
    two gates ship in one commit: with only one widened, every queued job
    reaches the user as the receptionist while the real agent runs behind it.
    """

    def test_gate_1_replay_waiting_is_not_a_replay_error( self, tmp_path, notifier ):
        """
        GATE 1 — `flow.py`'s replay branch.

        RED ON REVERT: narrow that gate back to `outcome.status == "done"` and
        this returns the receptionist with route_reason "replay_error" — a cache
        hit apologising for a question the cache could already answer.
        """
        snap  = types.SimpleNamespace( routing_command="agent router go to math" )
        cache = FakeCache( lookup_result=_lookup( is_replay_hit=True, snapshot=snap ) )
        exe   = FakeExecutor( _outcome( status="waiting", answer=None, answer_raw=None,
                                        job_id=_SCOPED_JOB_ID ) )
        f     = _make_flow( tmp_path, cache, FakeRouter(), FakeExpeditor(), exe, FakePending(), notifier )

        r = f.ask( "what is 2+2", **_CTX )

        assert r[ "path" ]         == "replay",     "a waiting replay degraded to the receptionist"
        assert r[ "route_reason" ] == "exact_hit"
        assert r[ "status" ]       == "waiting",    "the hand-off must reach the caller as waiting"
        assert r[ "job_id" ]       == _SCOPED_JOB_ID, "the caller needs the id to follow the queued job"

    def test_gate_2_agent_waiting_is_not_an_agent_error( self, tmp_path, notifier, monkeypatch ):
        """
        GATE 2 — `_run_agent`.

        RED ON REVERT: narrow that gate back to `outcome.status != "done"` and
        EVERY queued job degrades to the receptionist the moment it is handed
        off, while the real agent still runs behind it.
        """
        monkeypatch.setattr( flow_mod, "resolve", lambda command, crud_enabled: FakeSpec( required_args=(), snapshotable=False ) )
        exe = FakeExecutor( _outcome( status="waiting", answer=None, answer_raw=None,
                                      job_id=_SCOPED_JOB_ID ) )
        f   = _make_flow( tmp_path, FakeCache(), FakeRouter(), FakeExpeditor(), exe,
                          FakePending(), notifier )

        r = f.ask( "what is 2+2", **_CTX )

        assert r[ "path" ]         == "agent",      "a waiting agent degraded to the receptionist"
        assert r[ "route_reason" ] == "args_none"
        assert r[ "status" ]       == "waiting"
        assert r[ "job_id" ]       == _SCOPED_JOB_ID
        assert len( exe.works )    == 1,            "the receptionist ran too — the gate did not hold"

    def test_the_write_back_guard_still_refuses_waiting( self, tmp_path, notifier, monkeypatch ):
        """
        THE GATE THAT MUST NOT MOVE — `_maybe_write_back`, still `"done"` alone.

        A waiting job has not run, so it has no answer. Widening this one too
        would write a cache row carrying None, which later replays to a user as
        a real answer. The positive control below is what makes the refusal
        meaningful: the same flow, same cache, same snapshotable spec, and only
        the outcome status different, DOES write back.

        RED ON REVERT: add "waiting" to the guard and the first half fails.
        """
        monkeypatch.setattr( flow_mod, "resolve", lambda command, crud_enabled: FakeSpec( required_args=(), snapshotable=True ) )

        waiting_cache = FakeCache()
        f_waiting = _make_flow( tmp_path, waiting_cache, FakeRouter(), FakeExpeditor(),
                                FakeExecutor( _outcome( status="waiting", answer=None,
                                                        answer_raw=None, job_id=_SCOPED_JOB_ID ) ),
                                FakePending(), notifier, writeback_enabled=True )
        r_waiting = f_waiting.ask( "what is 2+2", **_CTX )

        assert r_waiting[ "status" ] == "waiting"
        assert waiting_cache.snapshot_calls   == [], "a job that never ran was turned into a snapshot"
        assert waiting_cache.write_back_calls == [], "a job that never ran was written to the cache"
        assert r_waiting[ "snapshot_id" ] is None

        # Positive control — without it, a cache that simply never writes would
        # make the assertions above pass while proving nothing.
        done_cache = FakeCache()
        f_done = _make_flow( tmp_path, done_cache, FakeRouter(), FakeExpeditor(),
                             FakeExecutor( _outcome( status="done", answer="4", answer_raw="4" ) ),
                             FakePending(), notifier, writeback_enabled=True )
        r_done = f_done.ask( "what is 2+2", **_CTX )

        assert len( done_cache.write_back_calls ) == 1, "the control never wrote back — the refusal above proves nothing"
        assert r_done[ "snapshot_id" ] == "snap-123"
# ══════════════════════════════════════════════════════════════════════════════
# submit() — the door beside ask (step 10, Rick's entry-point ruling 2026-08-21)
#
# What distinguishes it is what it does NOT do. `ask` is handed prose and has to work
# out what it means: cache lookup, LLM routing, argument extraction. A `submit` caller
# has already decided, so the whole head is skipped. These tests pin the skipping —
# a submit that quietly routed would still return a plausible answer, which is exactly
# the kind of defect that survives a happy-path test.
# ══════════════════════════════════════════════════════════════════════════════

def _submit_flow( tmp_path, notifier, executor=None, cache=None, **kw ):
    return _make_flow( tmp_path, cache or FakeCache(), FakeRouter(), FakeExpeditor(),
                       executor or FakeExecutor(), FakePending(), notifier, **kw )


def test_submit_runs_a_named_command_without_routing_or_extracting( tmp_path, notifier, monkeypatch ):
    """
    The definition of the door, as a test. The router and expeditor are handed fakes that
    RECORD their calls; both lists must stay empty. If either fires, `submit` has become
    a slower `ask`.
    """
    router    = FakeRouter()
    expeditor = FakeExpeditor()
    router.route = lambda q: ( _ for _ in () ).throw( AssertionError( "submit must not route" ) )
    monkeypatch.setattr( flow_mod, "resolve", lambda c, crud_enabled: FakeSpec( required_args=( "location", ) ) )

    f = _make_flow( tmp_path, FakeCache(), router, expeditor, FakeExecutor(), FakePending(), notifier )
    r = f.submit( command="agent router go to weather", args={ "location": "Boston" }, **_CTX )

    assert r[ "status" ]       == "done"
    assert r[ "route_reason" ] == "submitted"
    assert expeditor.calls == [], "submit must not run the expeditor — the caller supplied the args"


def test_submit_never_reads_the_cache( tmp_path, notifier, monkeypatch ):
    """
    A submit names its command, so there is nothing for a cache lookup to decide. Reading
    it anyway would let a stale replay answer a request that asked for fresh work.
    """
    cache = FakeCache()
    cache.lookup = lambda q: ( _ for _ in () ).throw( AssertionError( "submit must not read the cache" ) )
    monkeypatch.setattr( flow_mod, "resolve", lambda c, crud_enabled: FakeSpec( required_args=() ) )

    f = _submit_flow( tmp_path, notifier, cache=cache )
    assert f.submit( command="agent router go to date and time", args={}, **_CTX )[ "status" ] == "done"


def test_submit_with_a_prebuilt_job_skips_the_registry_entirely( tmp_path, notifier, monkeypatch ):
    """
    The second shape: an in-process caller hands over a job it already constructed — a
    watchdog restoring a checkpoint, an expediter resuming its own work. Making it
    describe that object in a command string so the flow could rebuild it would be a
    round trip through a lossy format.
    """
    monkeypatch.setattr( flow_mod, "resolve",
                         lambda c, crud_enabled: ( _ for _ in () ).throw( AssertionError( "must not resolve a prebuilt job" ) ) )
    executor = FakeExecutor()
    job      = FakeAgent( question="already built" )

    f = _submit_flow( tmp_path, notifier, executor=executor )
    r = f.submit( job=job, question="already built", **_CTX )

    assert r[ "route_reason" ] == "submitted_prebuilt"
    assert executor.works[ 0 ].job is job, "the caller's own object must be run, not a rebuild"


def test_a_prebuilt_job_missing_routing_command_fails_loud( tmp_path, notifier ):
    """The protocol REQUIRES routing_command (queue_protocol.py:61), so a job without
    one is a broken caller, not a case to paper over.

    This used to be `getattr( job, "routing_command", "" ) or ""`, which turned that
    broken caller into a finished result carrying a BLANK command — the same nullable,
    blank-defaulted column this plan condemns in the cache. Loud beats blank.

    RED ON REVERT: restore the getattr fallback and this passes silently with command=""."""
    class JobWithoutRoutingCommand:
        def do_all( self ): return "unused"                # pragma: no cover - executor faked

    f = _submit_flow( tmp_path, notifier )
    with pytest.raises( AttributeError, match="routing_command" ):
        f.submit( job=JobWithoutRoutingCommand(), **_CTX )


def test_a_prebuilt_job_is_never_written_back( tmp_path, notifier ):
    """
    A caller handing over a constructed job has not said its result is a reusable answer
    to a reusable question. Writing one back on that guess would put a row in the cache
    that `ask` would later replay to somebody else.
    """
    cache = FakeCache()
    f = _submit_flow( tmp_path, notifier, cache=cache, writeback_enabled=True )
    f.submit( job=FakeAgent(), question="q", **_CTX )
    assert cache.write_back_calls == []


def test_submit_needs_input_does_not_park( tmp_path, notifier, monkeypatch ):
    """
    THE RULE THAT ONLY EXISTS ON THIS DOOR. `ask` parks a needs-input question because a
    human is waiting to answer it. A submit caller is a service account or a watchdog —
    parking there stores a question nobody will read and reports the request as handled.
    """
    monkeypatch.setattr( flow_mod, "resolve", lambda c, crud_enabled: FakeSpec( required_args=( "location", ) ) )
    pending = FakePending()
    f = _make_flow( tmp_path, FakeCache(), FakeRouter(), FakeExpeditor(), FakeExecutor(),
                    pending, notifier )

    r = f.submit( command="agent router go to weather", args={}, **_CTX )

    assert r[ "status" ]       == "needs_input"
    assert r[ "pending_id" ]   is None, "a submit must never hand back an id nobody can answer"
    assert r[ "args_missing" ] == [ "location" ]
    assert pending.put_calls   == [], "nothing may be stored — that is the whole difference"


def test_submit_needs_input_reports_which_args_were_supplied( tmp_path, notifier, monkeypatch ):
    """A refusal the caller can act on names both halves: what is missing AND what landed."""
    monkeypatch.setattr( flow_mod, "resolve",
                         lambda c, crud_enabled: FakeSpec( required_args=( "location", "when" ) ) )
    f = _submit_flow( tmp_path, notifier )
    r = f.submit( command="agent router go to weather", args={ "location": "Boston" }, **_CTX )

    assert r[ "args_missing" ] == [ "when" ]
    assert r[ "args_known" ]   == [ "location" ]


def test_an_empty_string_argument_counts_as_missing( tmp_path, notifier, monkeypatch ):
    """
    A key present with no value is not a supplied argument. Treating it as one sends the
    agent off with a blank where it needed a place or a date, and the failure surfaces
    much later as a bad answer rather than here as a refusal.
    """
    monkeypatch.setattr( flow_mod, "resolve", lambda c, crud_enabled: FakeSpec( required_args=( "location", ) ) )
    f = _submit_flow( tmp_path, notifier )
    r = f.submit( command="agent router go to weather", args={ "location": "" }, **_CTX )
    assert r[ "status" ] == "needs_input"


def test_submit_treats_waiting_as_a_success_not_a_degrade( tmp_path, notifier, monkeypatch ):
    """
    A queued executor returns status="waiting" with a job_id: the work was ACCEPTED and is
    running behind the response. Reading that as a failure would answer every queued
    submit with a receptionist reply while the real job ran on unseen.
    """
    monkeypatch.setattr( flow_mod, "resolve", lambda c, crud_enabled: FakeSpec( required_args=() ) )
    executor = FakeExecutor( _outcome( status="waiting", answer=None, answer_raw=None, job_id="j-1" ) )
    f = _submit_flow( tmp_path, notifier, executor=executor )

    r = f.submit( job=FakeAgent(), question="q", **_CTX )

    assert r[ "status" ] == "waiting"
    assert r[ "job_id" ] == "j-1"
    assert r[ "path" ]   != "receptionist", "waiting is an accepted job, not a failed one"


def test_a_prebuilt_job_that_fails_degrades_to_the_receptionist( tmp_path, notifier ):
    """The complement — a real failure must still degrade, or 'waiting is fine' would be
    satisfiable by treating everything as fine."""
    executor = FakeExecutor( _outcome( status="failed", answer=None, error="boom" ) )
    f = _submit_flow( tmp_path, notifier, executor=executor )
    r = f.submit( job=FakeAgent(), question="q", **_CTX )
    assert r[ "path" ] == "receptionist"
    assert "boom" in ( r[ "error" ] or "" )


def test_submit_with_an_unknown_command_degrades_to_the_receptionist( tmp_path, notifier, monkeypatch ):
    monkeypatch.setattr( flow_mod, "resolve", lambda c, crud_enabled: None )
    f = _submit_flow( tmp_path, notifier )
    r = f.submit( command="agent router go to nowhere", args={}, **_CTX )
    assert r[ "path" ]         == "receptionist"
    assert r[ "route_reason" ] == "unknown_command"


# ── the agentic arm of submit ─────────────────────────────────────────────────
#
# WHY THIS BLOCK EXISTS. `resolve()` is scoped to the CONVERSATIONAL class, so it
# returns None for every agentic command and `submit` fell straight through to the
# receptionist — measured before the fix: `podcast generator`, `deep research`,
# `swe team` and `bug fix expediter` all came back None while `math` returned a spec.
# `/api/v2/submit` therefore could not build a single agentic job, which is exactly
# what eleven retiring endpoints are about to name in their refusals.
#
# The tests below use the REAL registry rather than a monkeypatched `resolve`. That is
# deliberate: the defect WAS in the registry lookup, so a test that fakes the lookup
# cannot see it come back.

class _RecordingAgenticFactory:
    """Records what the flow asked it to build, and hands back a job."""

    def __init__( self, job=None ):
        self.calls = [ ]
        self._job  = job if job is not None else FakeAgent( routing_command="agent router go to podcast generator" )

    def __call__( self, **kwargs ):
        self.calls.append( kwargs )
        return self._job


def test_submit_builds_an_agentic_job_from_a_command_the_registry_knows( tmp_path, notifier ):
    """The whole point: an agentic command reaches its factory instead of the receptionist.

    Uses the real registry. Before the fix this returned path="receptionist",
    route_reason="unknown_command" for a command the registry knows perfectly well.
    """
    factory  = _RecordingAgenticFactory()
    executor = FakeExecutor()
    f = _submit_flow( tmp_path, notifier, executor=executor, agentic_factory=factory )
    r = f.submit( command="agent router go to podcast generator",
                  args={ "research": "io/x.md" }, **_CTX )

    assert r[ "path" ]         != "receptionist", r
    assert r[ "route_reason" ] == "submitted_prebuilt"
    assert len( factory.calls ) == 1
    assert factory.calls[ 0 ][ "command" ]    == "agent router go to podcast generator"
    assert factory.calls[ 0 ][ "args_dict" ]  == { "research": "io/x.md" }
    assert factory.calls[ 0 ][ "user_id" ]    == "u1"
    assert executor.works[ 0 ].job is factory._job, "the built job must be what runs"


def test_submit_checks_the_agentic_commands_own_required_args( tmp_path, notifier ):
    """The argument check is the SPEC's, not a list written in the flow.

    Nothing is built and nothing is queued — asserted as an absence, because a
    factory that was called and then discarded looks identical in the response.
    """
    factory  = _RecordingAgenticFactory()
    executor = FakeExecutor()
    f = _submit_flow( tmp_path, notifier, executor=executor, agentic_factory=factory )
    r = f.submit( command="agent router go to podcast generator", args={}, **_CTX )

    assert r[ "status" ]       == "needs_input"
    assert r[ "route_reason" ] == "args_incomplete_no_park"
    assert r[ "pending_id" ]   is None, "a submit must never park — nobody is there to answer"
    assert r[ "args_missing" ]
    assert factory.calls == [], "an under-specified command must not reach the factory"
    assert executor.works == [], "and must not reach the queue"


def test_submit_degrades_when_the_factory_cannot_build_the_command( tmp_path, notifier ):
    """The registry said agentic and the factory said no — the two tables disagree.

    Degrade rather than raise out of the door, and NAME the command, because a bare
    receptionist here would send the next reader hunting.
    """
    f = _submit_flow( tmp_path, notifier, agentic_factory=lambda **kw: None )
    r = f.submit( command="agent router go to podcast generator",
                  args={ "research": "io/x.md" }, **_CTX )

    assert r[ "path" ]         == "receptionist"
    assert r[ "route_reason" ] == "agentic_build_error"
    assert "podcast generator" in ( r[ "error" ] or "" )


def test_submit_degrades_when_the_factory_raises( tmp_path, notifier ):
    """A factory that throws must not become a 500 out of /api/v2/submit."""
    def _boom( **kw ):
        raise RuntimeError( "factory exploded" )
    f = _submit_flow( tmp_path, notifier, agentic_factory=_boom )
    r = f.submit( command="agent router go to podcast generator",
                  args={ "research": "io/x.md" }, **_CTX )

    assert r[ "path" ]         == "receptionist"
    assert r[ "route_reason" ] == "agentic_build_error"
    assert "factory exploded" in ( r[ "error" ] or "" )


def test_the_agentic_arm_does_not_route_or_read_the_cache_either( tmp_path, notifier ):
    """Everything `submit` skips, it skips on this arm too — otherwise the agentic
    path would be a slower `ask` wearing the submit name."""
    router = FakeRouter()
    cache  = FakeCache()
    router.route  = lambda q: ( _ for _ in () ).throw( AssertionError( "submit must not route" ) )
    cache.lookup  = lambda q: ( _ for _ in () ).throw( AssertionError( "submit must not read the cache" ) )
    expeditor     = FakeExpeditor()

    f = _make_flow( tmp_path, cache, router, expeditor, FakeExecutor(), FakePending(), notifier,
                    agentic_factory=_RecordingAgenticFactory() )
    r = f.submit( command="agent router go to podcast generator",
                  args={ "research": "io/x.md" }, **_CTX )

    assert r[ "route_reason" ] == "submitted_prebuilt"
    assert expeditor.calls == []


def test_with_no_factory_injected_the_flow_reaches_the_real_one( tmp_path, notifier, monkeypatch ):
    """The default is a LAZY IMPORT, and a lazy import is exactly the kind of wiring
    that is never exercised because every test injects a fake.

    Patched at its source module so the flow's `from ... import create_agentic_job`
    picks up the fake; the assertion is that the flow got there at all.
    """
    seen = [ ]
    def _fake( **kwargs ):
        seen.append( kwargs[ "command" ] )
        return FakeAgent( routing_command=kwargs[ "command" ] )
    monkeypatch.setattr( "cosa.rest.agentic_job_factory.create_agentic_job", _fake )

    f = _submit_flow( tmp_path, notifier )          # no agentic_factory
    r = f.submit( command="agent router go to deep research", args={ "query": "q" }, **_CTX )

    assert seen == [ "agent router go to deep research" ]
    assert r[ "route_reason" ] == "submitted_prebuilt"


def test_a_command_neither_reader_knows_still_reaches_the_receptionist( tmp_path, notifier ):
    """The agentic lookup is a SECOND chance, not a replacement for the refusal."""
    f = _submit_flow( tmp_path, notifier, agentic_factory=_RecordingAgenticFactory() )
    r = f.submit( command="agent router go to nowhere at all", args={}, **_CTX )
    assert r[ "path" ]         == "receptionist"
    assert r[ "route_reason" ] == "unknown_command"


def test_submit_with_neither_command_nor_job_raises( tmp_path, notifier ):
    """
    A caller bug, not a runtime condition. A flow that guessed which shape you meant would
    run the wrong work silently, so it refuses loudly instead.
    """
    f = _submit_flow( tmp_path, notifier )
    with pytest.raises( ValueError, match="exactly one" ):
        f.submit( **_CTX )


def test_submit_with_both_command_and_job_raises( tmp_path, notifier ):
    f = _submit_flow( tmp_path, notifier )
    with pytest.raises( ValueError, match="exactly one" ):
        f.submit( command="agent router go to weather", job=FakeAgent(), **_CTX )


def test_submit_writes_back_a_snapshotable_result( tmp_path, notifier, monkeypatch ):
    """The spine `ask` shares: a snapshotable, completed result goes through the same
    guarded write-back, so a submitted answer is replayable later.

    The question is REQUIRED for the write — see the test below. This one used to
    omit it and still assert a write, which is the defect that test now pins."""
    monkeypatch.setattr( flow_mod, "resolve",
                         lambda c, crud_enabled: FakeSpec( required_args=(), snapshotable=True ) )
    cache = FakeCache()
    f = _submit_flow( tmp_path, notifier, cache=cache, writeback_enabled=True )
    r = f.submit( command="agent router go to date and time", args={},
                  question="what time is it", **_CTX )

    assert len( cache.write_back_calls ) == 1
    assert r[ "wrote_snapshot" ] is True


def test_submit_without_a_question_writes_no_snapshot( tmp_path, notifier, monkeypatch ):
    """NO QUESTION ⇒ NO CACHE ROW, even for a command the registry calls snapshotable.

    `ask` looks rows up by the user's words. A question-less submit would file the row
    under the command string — "agent router go to math" — which no user will ever say,
    so the row can never be matched and only costs a read on every lookup.

    RED ON REVERT: drop the `and question is not None` in `submit`'s _run_agent call and
    the write happens, failing both assertions here.

    ⚠️ The absence is the assertion, at TWO depths. `wrote_snapshot is False` alone would
    pass with write-back merely disabled, so the cache is asserted untouched — and
    `snapshot_calls` is checked as well as `write_back_calls`, so the test stays red if the
    guard ever slides down to write_back and a snapshot object is built and then discarded.
    (Pocholo's addition: the cheaper guard is the one further up.)"""
    monkeypatch.setattr( flow_mod, "resolve",
                         lambda c, crud_enabled: FakeSpec( required_args=(), snapshotable=True ) )
    cache = FakeCache()
    f = _submit_flow( tmp_path, notifier, cache=cache, writeback_enabled=True )
    r = f.submit( command="agent router go to math", args={}, **_CTX )

    assert cache.snapshot_calls   == [], "a snapshot object was BUILT and thrown away"
    assert cache.write_back_calls == []
    assert r[ "wrote_snapshot" ] is False
    assert r[ "snapshot_id" ] is None
    assert r[ "status" ] == "done", "the work still RAN — only the cache row is refused"


def test_submit_speaks_when_asked_and_stays_quiet_when_not( tmp_path, notifier, monkeypatch ):
    monkeypatch.setattr( flow_mod, "resolve", lambda c, crud_enabled: FakeSpec( required_args=() ) )
    f = _submit_flow( tmp_path, notifier )

    f.submit( command="agent router go to date and time", args={}, speak=False, **_CTX )
    assert notifier.requests == []

    f.submit( command="agent router go to date and time", args={}, speak=True, **_CTX )
    assert len( notifier.requests ) == 1


# ───────────────────────────────────── the queue-time ack (row a4307873, before 6c)



class TestTheFlowAcksAQueuedJob:
    """
    v1 tells the user it is on the job the moment it queues one — the `_notify`
    at `todo_fifo_queue.py:855`, one line above the scope+push tail
    `QueuedExecutor` reproduces. The flow was silent there: a waiting Outcome
    carries no answer and `_speak` returns early on a falsy message, so with the
    queue path wired the user would say something and hear NOTHING until the job
    finished, where v1 answered immediately.

    The ack is spoken INSTEAD of the answer, never as well as, which is what
    holds it to exactly one spoken line per request whichever executor is wired.
    """

    def _spoken( self, notifier ):
        return [ r.message for r in notifier.requests ]

    def test_a_queued_agent_is_acked_once_in_v1s_words( self, tmp_path, notifier, monkeypatch ):
        """
        RED ON REVERT: drop the waiting branch from `_spoken_line` and nothing is
        spoken at all — the silence this row exists to end.
        """
        monkeypatch.setattr( flow_mod, "resolve", lambda command, crud_enabled: FakeSpec( required_args=(), snapshotable=False,
                                                       label="weather" ) )
        exe = FakeExecutor( _outcome( status="waiting", answer=None, answer_raw=None,
                                      job_id=_SCOPED_JOB_ID ) )
        f   = _make_flow( tmp_path, FakeCache(), FakeRouter(), FakeExpeditor(), exe,
                          FakePending(), notifier )

        r = f.ask( "weather in Boston", **_CTX, speak=True )

        assert self._spoken( notifier ) == [ "New weather job..." ], (
            "the user must hear v1's queue-time ack, exactly once"
        )
        assert r[ "status" ] == "waiting"

    def test_a_finished_job_is_not_acked( self, tmp_path, notifier, monkeypatch ):
        """
        The negative half of the bar: NO ack on done. The answer is what gets
        spoken, and an ack alongside it would make the assistant say "New math
        job..." about work it has already finished.

        RED ON REVERT: speak the ack unconditionally instead of only on waiting.
        """
        monkeypatch.setattr( flow_mod, "resolve", lambda command, crud_enabled: FakeSpec( required_args=(), snapshotable=False,
                                                       label="math" ) )
        exe = FakeExecutor( _outcome( status="done", answer="4", answer_raw="4" ) )
        f   = _make_flow( tmp_path, FakeCache(), FakeRouter(), FakeExpeditor(), exe,
                          FakePending(), notifier )

        f.ask( "what is 2+2", **_CTX, speak=True )

        spoken = self._spoken( notifier )
        assert spoken == [ "4" ],                        "a finished job spoke something other than its answer"
        assert not any( "New " in line for line in spoken ), "a finished job was acked as if it had just been queued"

    def test_a_queued_replay_is_acked_with_the_ROUTED_command( self, tmp_path, notifier, monkeypatch ):
        """
        The replay branch queues too, and since 6-pre its label comes from the
        command the ROUTER chose — which now always ran, because routing happens
        before the lookup.

        This test used to say the opposite ("its label comes from the snapshot's own
        routing_command — not from the router, which never ran on a cache hit"). That
        was true of the old order and is false of this one, so the premise is
        rewritten rather than the assertion patched. The snapshot below carries a
        DIFFERENT command from the routed one on purpose: reading the row's column
        would name "todo list" here, and the row's column is the nullable,
        blank-defaulted one this plan condemns.

        RED ON REVERT: resolve the snapshot's command again and the ack says "New
        todo list job..." instead.
        """
        monkeypatch.setattr( flow_mod, "resolve", lambda command, crud_enabled:
                             FakeSpec( label="calendaring" ) if command == "agent router go to calendar"
                             else FakeSpec( label="todo list" ) )
        snap  = types.SimpleNamespace( routing_command="agent router go to todo" )
        cache = FakeCache( lookup_result=_lookup( is_replay_hit=True, snapshot=snap ) )
        exe   = FakeExecutor( _outcome( status="waiting", answer=None, answer_raw=None,
                                        job_id=_SCOPED_JOB_ID ) )
        f     = _make_flow( tmp_path, cache, FakeRouter( "agent router go to calendar" ),
                            FakeExpeditor(), exe, FakePending(), notifier )

        r = f.ask( "what is on my calendar", **_CTX, speak=True )

        assert self._spoken( notifier ) == [ "New calendaring job..." ]
        assert r[ "path" ] == "replay"
        assert r[ "command" ] == "agent router go to calendar"

    def test_a_waiting_outcome_with_no_label_stays_silent( self, tmp_path, notifier, monkeypatch ):
        """
        The receptionist has no label in the registry and v1 does not say "New …
        job" for it either — it speaks a random hemming-and-hawing line built from
        word lists that live on the queue. Rather than invent a sentence or move
        queue-owned state into the flow, an unlabelled hand-off says nothing, and
        that is recorded here as a DECISION rather than left to be read as an
        oversight.
        """
        monkeypatch.setattr( flow_mod, "resolve", lambda command, crud_enabled: FakeSpec( required_args=(), snapshotable=False, label=None ) )
        exe = FakeExecutor( _outcome( status="waiting", answer=None, answer_raw=None, job_id=_SCOPED_JOB_ID ) )
        f   = _make_flow( tmp_path, FakeCache(), FakeRouter(), FakeExpeditor(), exe,
                          FakePending(), notifier )

        r = f.ask( "what is 2+2", **_CTX, speak=True )

        assert self._spoken( notifier ) == []
        assert r[ "status" ] == "waiting"


# ─────────────────────────────────────────── step 2b — the flow carries the CRUD flag

class TestTheFlowStatesTheCrudFlag:
    """
    One CRUD-aware resolver means every caller has to say which surface it is, and
    the flow is a caller. Before 2b it did not — `resolve()` was pinned to the
    non-CRUD class so the flow could stay ignorant, and a spoken command and a v2
    request could reach two different agents for the same question.

    These pin the wiring, not the registry: that the flow HANDS ITS FLAG OVER on
    every resolve, and that it has no default to fall back on.
    """

    def test_every_resolve_receives_the_flows_flag( self, tmp_path, notifier, monkeypatch ):
        """
        RED ON REVERT: hard-code either literal at any resolve call site in flow.py
        and the captured flag stops matching the flow's own.
        """
        seen = []

        def _capturing( command, crud_enabled ):
            seen.append( crud_enabled )
            return FakeSpec( required_args=(), snapshotable=False )

        monkeypatch.setattr( flow_mod, "resolve", _capturing )
        f = _make_flow( tmp_path, FakeCache(), FakeRouter(), FakeExpeditor(),
                        FakeExecutor( _outcome() ), FakePending(), notifier, crud_enabled=True )

        f.ask( "what is on my todo list", **_CTX )

        assert seen, "the flow never resolved at all — this proves nothing about the flag"
        assert set( seen ) == { True }, f"a resolve call ignored the flow's flag: {seen}"

    def test_the_flow_refuses_to_guess_the_flag( self, tmp_path, notifier ):
        """
        No default on AskFlow. A default would decide calendar and todo routing by
        omission — the same silent-wrong-class failure the single resolver removes,
        one layer up.

        RED ON REVERT: give crud_enabled a default in AskFlow.__init__.
        """
        with pytest.raises( TypeError, match="crud_enabled" ):
            AskFlow( FakeCache(), FakeRouter(), FakeExpeditor(), FakeExecutor(), FakePending(),
                     notifier=notifier, trace_dir=str( tmp_path ) )


# ──────────────────────────── step 2c — the write-back carries its owner

class TestTheWriteBackNamesItsOwner:
    """
    v2's own write-back was manufacturing ownerless rows — the same shape as the
    63-of-64 already on disk. `_maybe_write_back` held ctx and called
    snapshot_from_result passing NEITHER user_id nor session_id, so the cache's
    (then-defaulted) empty strings were written through.

    The cache now refuses a blank owner. This is the other half: the flow hands
    over the identity it has had in scope all along.
    """

    def test_the_snapshot_carries_the_callers_identity( self, tmp_path, notifier, monkeypatch ):
        """
        RED ON REVERT: stop passing user_id/session_id at the call site and the
        cache raises for a blank owner instead — which is the fail-loud half doing
        its job, and still a failure here.
        """
        monkeypatch.setattr( flow_mod, "resolve",
                             lambda command, crud_enabled: FakeSpec( required_args=(), snapshotable=True ) )
        cache = FakeCache()
        f     = _make_flow( tmp_path, cache, FakeRouter(), FakeExpeditor(),
                            FakeExecutor( _outcome( status="done", answer="4", answer_raw="4" ) ),
                            FakePending(), notifier, writeback_enabled=True )

        f.ask( "what is 2+2", **_CTX )

        assert cache.snapshot_calls, "nothing was written — this proves nothing about ownership"
        written = cache.snapshot_calls[ -1 ]
        assert written[ "user_id" ]    == _CTX[ "user_id" ],    "the row was written with someone else's owner, or none"
        assert written[ "session_id" ] == _CTX[ "session_id" ]

    def test_an_ownerless_write_cannot_pass_silently( self, tmp_path, notifier, monkeypatch ):
        """
        The two halves together: with a REAL V2Cache the flow cannot write an
        unowned row even if a future edit drops the identity, because the cache
        refuses it rather than defaulting.

        A test that only asserted a populated write works would have passed before
        this change, which is why the assertion is on the refusal.
        """
        from cosa.rest.v2.cache import V2Cache

        with pytest.raises( ValueError, match="non-empty user_id" ):
            V2Cache.snapshot_from_result(
                object.__new__( V2Cache ),
                question="q", answer="a", answer_conversational="c",
                routing_command="agent router go to math", user_id="",
            )


# ─────────────────────────────── step 4 — the flow builds the agent the queue builds

class TestAgentConstructionParity:
    """
    Finding 3: the flow and push_job built the same agent class with different
    kwargs, and nothing raised about it. All EIGHT differences are pinned here —
    five as parity, three as deliberate non-matches with their reasons, so a
    reader can tell a ruling from an oversight without re-deriving either.

    `question_gist` is the one with teeth: the query log reads that field, so a
    gist that is really the raw question makes every logged row wrong in a way
    nothing raises about.
    """

    def _built( self, tmp_path, notifier, monkeypatch, question="hey what is the weather" ):
        """Run one request and hand back the kwargs the agent was constructed with."""
        seen = {}

        class _Recording:
            def __init__( self, **kwargs ):
                seen.update( kwargs )
                self.answer                = "sunny"
                self.answer_conversational = "It is sunny."

            def do_all( self ):
                return self.answer_conversational

        monkeypatch.setattr( flow_mod, "resolve",
                             lambda command, crud_enabled: FakeSpec( required_args=( "location", ),
                                                                     factory=_Recording, snapshotable=False ) )
        expeditor = FakeExpeditor( _extraction( final_args={ "location": "Boston" }, missing=[] ) )
        f = _make_flow( tmp_path, FakeCache(), FakeRouter(), expeditor,
                        FakeExecutor( _outcome() ), FakePending(), notifier )
        f.auto_debug  = True      # the queue's flags, set to NON-defaults so a
        f.inject_bugs = True      # hardcoded False cannot pass here by coincidence
        f.ask( question, **_CTX )
        return seen

    def test_the_five_parity_kwargs( self, tmp_path, notifier, monkeypatch ):
        """
        RED ON REVERT: put back question_gist=agent_question, debug=self.debug,
        verbose=self.verbose, auto_debug=False or inject_bugs=False, and that row
        fails.
        """
        seen = self._built( tmp_path, notifier, monkeypatch )

        # The gist is computed from the SALUTATION-STRIPPED question, as v1 does —
        # not from the raw text, and not from the composed one.
        assert seen[ "question_gist" ] == "gist:what is the weather"
        assert seen[ "debug" ]         is True,  "v1 hardcodes debug=True; an agent that ran verbose must keep doing so"
        assert seen[ "verbose" ]       is False
        assert seen[ "auto_debug" ]    is True,  "the flow's own auto_debug did not reach the agent"
        assert seen[ "inject_bugs" ]   is True,  "the flow's own inject_bugs did not reach the agent"

    def test_the_three_ruled_non_matches( self, tmp_path, notifier, monkeypatch ):
        """
        Each of these DIFFERS from push_job on purpose. Pinned so the difference
        stays a decision: an unpinned non-match is indistinguishable from a bug.
        """
        seen = self._built( tmp_path, notifier, monkeypatch )

        # 1. question — composed, not bare. Bare parity would drop the expeditor's
        #    extracted args, since v1 never ran the expeditor for conversational
        #    commands and the agent re-parsed the raw text itself.
        assert seen[ "question" ] != "hey what is the weather", (
            "the flow passed the BARE question — the expeditor's extracted location is gone"
        )
        assert "Boston" in seen[ "question" ]

        # 2. last_question_asked — the INTENDED form. v1 builds it from the ORIGINAL
        #    question, which still contains the salutation, so v1 says it twice.
        assert seen[ "last_question_asked" ] == "hey what is the weather"
        assert not seen[ "last_question_asked" ].startswith( "hey hey" ), (
            "the flow copied v1's doubled salutation instead of the intended form"
        )

        # 3. push_counter — v1's lives on the queue singleton the flow cannot see.
        assert seen[ "push_counter" ] == -1

    def test_the_identity_three_still_agree( self, tmp_path, notifier, monkeypatch ):
        """The three that already matched must not drift while the other eight move."""
        seen = self._built( tmp_path, notifier, monkeypatch )
        assert seen[ "user_id" ]    == _CTX[ "user_id" ]
        assert seen[ "user_email" ] == _CTX[ "user_email" ]
        assert seen[ "session_id" ] == _CTX[ "websocket_id" ], "v1 passes the WEBSOCKET id as session_id"

    def test_an_agent_was_actually_built( self, tmp_path, notifier, monkeypatch ):
        """Without this, every assertion above would be vacuously true on an empty dict."""
        seen = self._built( tmp_path, notifier, monkeypatch )
        assert seen, "no agent was constructed"


# ───────────────────────── the fitness gate at the flow head (Rick's ruling 1)

class TestTheFlowRefusesAnUnfitQuestion:
    """
    v1 rejected empty / over-long / "invalid"-prefixed questions before anything
    else touched them (`todo_fifo_queue._is_fit` and its reason ladder). The flow
    had no gate at all, so after 6c an empty question would reach the router and
    route somewhere.

    The wording is v1's, kept verbatim: a user who hears a refusal today hears the
    same one after the switch.
    """

    def _flow( self, tmp_path, notifier ):
        return _make_flow( tmp_path, FakeCache(), FakeRouter(), FakeExpeditor(),
                           FakeExecutor( _outcome() ), FakePending(), notifier )

    @pytest.mark.parametrize( "question,reason,route_reason", [
        ( "",            "Question cannot be empty",                 "empty_question"    ),
        ( "   ",         "Question cannot be empty",                 "empty_question"    ),
        ( "x" * 1001,    "Question too long (max 1000 characters)",  "question_too_long" ),
        ( "invalid stuff", "Question contains invalid content",      "invalid_content"   ),
    ] )
    def test_each_rule_refuses_in_v1s_words( self, tmp_path, notifier, question, reason, route_reason ):
        """
        RED ON REVERT: drop any rule from _unfit_reason and its row routes instead
        of refusing; change any message and its row fails on the text.
        """
        r = self._flow( tmp_path, notifier ).ask( question, **_CTX )
        assert r[ "status" ]       == "rejected"
        assert r[ "route_reason" ] == route_reason
        assert r[ "answer" ]       == reason

    def test_the_gate_runs_BEFORE_the_router( self, tmp_path, notifier ):
        """
        The point of a gate at the HEAD. A router that never ran cannot have routed
        an empty question anywhere.

        RED ON REVERT: move the gate below the cache/router block and the router
        records a call.
        """
        class _LoudRouter( FakeRouter ):
            def __init__( self ):
                super().__init__()
                self.calls = 0

            def route( self, question ):
                self.calls += 1
                return super().route( question )

        router = _LoudRouter()
        cache  = FakeCache()
        f      = _make_flow( tmp_path, cache, router, FakeExpeditor(),
                             FakeExecutor( _outcome() ), FakePending(), notifier )

        f.ask( "", **_CTX )

        assert router.calls == 0,        "the router saw an unfit question"
        assert cache.gist_calls == [],   "the cache was consulted for a question that was refused"

    def test_a_fit_question_is_not_refused( self, tmp_path, notifier, monkeypatch ):
        """The control. Without it, a gate that refused EVERYTHING would pass above."""
        monkeypatch.setattr( flow_mod, "resolve",
                             lambda command, crud_enabled: FakeSpec( required_args=(), snapshotable=False ) )
        r = self._flow( tmp_path, notifier ).ask( "what is 2+2", **_CTX )
        assert r[ "status" ] != "rejected"

    def test_exactly_1000_characters_is_fit( self, tmp_path, notifier, monkeypatch ):
        """The boundary v1 drew: >1000 is refused, 1000 is not."""
        monkeypatch.setattr( flow_mod, "resolve",
                             lambda command, crud_enabled: FakeSpec( required_args=(), snapshotable=False ) )
        r = self._flow( tmp_path, notifier ).ask( "x" * 1000, **_CTX )
        assert r[ "status" ] != "rejected"


# ───────────────────────── the query log gets written again (Rick's ruling 19)

class FakeQueryLog:
    def __init__( self ):
        self.rows = []

    def log_query( self, **kwargs ):
        self.rows.append( kwargs )
        return "qid-1"


class TestTheFlowWritesTheQueryLog:
    """
    v1 wrote the query log from five places inside push_job. v2 wrote it from
    none, so once 6c lands the table simply stops growing for voice traffic and
    nothing raises about it — the failure this closes.

    ONE call site, at the terminal chokepoint every exit funnels through.
    """

    def _run( self, tmp_path, notifier, monkeypatch, question="hey what is 2+2", **flow_kw ):
        monkeypatch.setattr( flow_mod, "resolve",
                             lambda command, crud_enabled: FakeSpec( required_args=(), snapshotable=False ) )
        log = FakeQueryLog()
        f   = _make_flow( tmp_path, FakeCache(), FakeRouter(), FakeExpeditor(),
                          FakeExecutor( _outcome() ), FakePending(), notifier, **flow_kw )
        f.query_log = log
        r = f.ask( question, **_CTX )
        return log, r

    def test_an_answered_question_is_logged( self, tmp_path, notifier, monkeypatch ):
        """
        RED ON REVERT: delete the _log_query call from _emit and nothing is written.
        """
        log, _r = self._run( tmp_path, notifier, monkeypatch )

        assert len( log.rows ) == 1, "the query log was not written exactly once"
        row = log.rows[ 0 ]
        assert row[ "query_verbatim" ]   == "hey what is 2+2",  "the log must keep what the user actually said"
        assert row[ "query_gist" ]       == "gist:what is 2+2", "the gist is computed on the STRIPPED question"
        assert row[ "user_id" ]          == _CTX[ "user_id" ]
        assert row[ "session_id" ]       == _CTX[ "websocket_id" ]
        assert row[ "match_result" ][ "type" ] == "no_match_new_agent"

    def test_a_refused_question_is_logged_too( self, tmp_path, notifier, monkeypatch ):
        """
        v1's five call sites missed paths; one chokepoint does not. A refusal is
        exactly the traffic an analytics table wants and the easiest to lose.
        """
        log, r = self._run( tmp_path, notifier, monkeypatch, question="invalid thing" )
        assert r[ "status" ]     == "rejected"
        assert len( log.rows )   == 1
        assert log.rows[ 0 ][ "query_verbatim" ] == "invalid thing"

    def test_a_cache_hit_is_logged_as_an_exact_match( self, tmp_path, notifier, monkeypatch ):
        """The match_result v1 wrote on its replay path, carried over."""
        monkeypatch.setattr( flow_mod, "resolve",
                             lambda command, crud_enabled: FakeSpec( label="math" ) )
        snap  = types.SimpleNamespace( routing_command="agent router go to math" )
        cache = FakeCache( lookup_result=_lookup( is_replay_hit=True, snapshot=snap, similarity=100.0 ) )
        log   = FakeQueryLog()
        f     = _make_flow( tmp_path, cache, FakeRouter(), FakeExpeditor(),
                            FakeExecutor( _outcome( status="done", answer="4", answer_raw="4" ) ),
                            FakePending(), notifier )
        f.query_log = log

        f.ask( "what is 2+2", **_CTX )

        assert log.rows[ 0 ][ "match_result" ][ "type" ]       == "exact_match"
        assert log.rows[ 0 ][ "match_result" ][ "confidence" ] == 100.0

    def test_a_logging_failure_never_breaks_the_request( self, tmp_path, notifier, monkeypatch ):
        """
        v1 swallowed a log failure with a debug print, and so does this. A user's
        question must not 500 because an analytics row could not be written.

        RED ON REVERT: remove the try/except and this raises instead of answering.
        """
        class _BrokenLog:
            def log_query( self, **kwargs ):
                raise RuntimeError( "the log table is down" )

        monkeypatch.setattr( flow_mod, "resolve",
                             lambda command, crud_enabled: FakeSpec( required_args=(), snapshotable=False ) )
        f = _make_flow( tmp_path, FakeCache(), FakeRouter(), FakeExpeditor(),
                        FakeExecutor( _outcome() ), FakePending(), notifier )
        f.query_log = _BrokenLog()

        r = f.ask( "what is 2+2", **_CTX )     # must not raise

        assert r[ "status" ] == "done"

    def test_no_log_configured_is_not_an_error( self, tmp_path, notifier, monkeypatch ):
        """Every test double runs without one; that must stay a no-op, not a crash."""
        monkeypatch.setattr( flow_mod, "resolve",
                             lambda command, crud_enabled: FakeSpec( required_args=(), snapshotable=False ) )
        f = _make_flow( tmp_path, FakeCache(), FakeRouter(), FakeExpeditor(),
                        FakeExecutor( _outcome() ), FakePending(), notifier )
        assert f.query_log is None
        assert f.ask( "what is 2+2", **_CTX )[ "status" ] == "done"


class TestEveryEntryPointLogsItsQuestion:
    """
    Pocholo on 58f73b32: only `ask` stamped the question on the trace, so the
    query log wrote a BLANK question for every submit and every resumed turn —
    where v1 logged it on all three paths. The rows were being written; they were
    being written empty, which is worse than not writing them, because the table
    looks populated.

    The gap survived my own tests because none of them asserted the logged
    question on a submit- or resume-shaped row. One per path, here.
    """

    def _log_on( self, flow ):
        log = FakeQueryLog()
        flow.query_log = log
        return log

    def test_submit_logs_the_question_the_caller_supplied( self, tmp_path, notifier, monkeypatch ):
        """
        RED ON REVERT: drop `question=` from submit's trace.update and the logged
        question is "".
        """
        monkeypatch.setattr( flow_mod, "resolve",
                             lambda command, crud_enabled: FakeSpec( required_args=(), snapshotable=False ) )
        f   = _make_flow( tmp_path, FakeCache(), FakeRouter(), FakeExpeditor(),
                          FakeExecutor( _outcome() ), FakePending(), notifier )
        log = self._log_on( f )

        f.submit( command="agent router go to math", args={}, question="what is 2+2", **_CTX )

        assert log.rows, "the submit path logged nothing at all"
        assert log.rows[ -1 ][ "query_verbatim" ] == "what is 2+2"

    def test_a_question_less_submit_logs_the_command_it_named( self, tmp_path, notifier, monkeypatch ):
        """
        An internal caller submits a command with no prose. Logging "" there would
        make the row unattributable; the command is the only true thing available,
        and it is what `_run_agent` already files the row under.
        """
        monkeypatch.setattr( flow_mod, "resolve",
                             lambda command, crud_enabled: FakeSpec( required_args=(), snapshotable=False ) )
        f   = _make_flow( tmp_path, FakeCache(), FakeRouter(), FakeExpeditor(),
                          FakeExecutor( _outcome() ), FakePending(), notifier )
        log = self._log_on( f )

        f.submit( command="agent router go to math", args={}, **_CTX )

        assert log.rows[ -1 ][ "query_verbatim" ] == "agent router go to math"

    def test_resume_logs_the_original_question( self, tmp_path, notifier, monkeypatch ):
        """
        The resumed turn belongs to the question that started the interview, not to
        the one-word answer that finished it.

        RED ON REVERT: drop the trace.update in resume and the logged question is "".
        """
        monkeypatch.setattr( flow_mod, "resolve",
                             lambda command, crud_enabled: FakeSpec( required_args=( "location", ), snapshotable=False ) )
        pending    = PendingRequests()
        expeditor  = FakeExpeditor( _extraction( final_args={ "location": "Boston" }, missing=[] ) )
        f          = _make_flow( tmp_path, FakeCache(), FakeRouter(), expeditor,
                                 FakeExecutor( _outcome() ), pending, notifier )
        pending_id = pending.put( extraction=_extraction( final_args={}, missing=[ "location" ] ),
                                  user_email=_CTX[ "user_email" ], session_id=_CTX[ "session_id" ],
                                  user_id=_CTX[ "user_id" ], command="agent router go to weather",
                                  question="what is the weather" )
        log = self._log_on( f )

        f.resume( pending_id=pending_id, answer="Boston", websocket_id=_CTX[ "websocket_id" ] )

        assert log.rows, "the resume path logged nothing at all"
        assert log.rows[ -1 ][ "query_verbatim" ] == "what is the weather", (
            "a resumed turn logged the ANSWER, or nothing, instead of the question it belongs to"
        )


# ────────────────────────────────────────── 6-pre — route first, then the cache

class SpyCache( FakeCache ):
    """A FakeCache that records every lookup, so "never read" is provable.

    Asserting the RESULT is not enough for the CRUD skip: a flow that reads the
    cache and then throws the hit away would look identical from the outside on a
    miss. The count is what distinguishes "did not read" from "read and ignored".
    """

    def __init__( self, **kwargs ):
        super().__init__( **kwargs )
        self.lookup_calls = []

    def lookup( self, question ):
        self.lookup_calls.append( question )
        return self._lookup


def _registry_with_fake_agent_class( monkeypatch ):
    """Run the flow against the REAL registry, swapping only the agent CLASS.

    The CRUD skip is derived from the registry — the row's `crud_factory` under the
    live flag — so a FakeSpec here would bracket the seam instead of crossing it:
    the test would prove the flow honours a fake attribute, not that the real todo
    row forks. What this does replace is `factory`, which is what the flow
    CONSTRUCTS after the decision has already been made; building a real
    TodoCrudAgent would want config and a dataframe, and it sits downstream of
    everything under test here.
    """
    from dataclasses import replace as dataclass_replace

    real_resolve = registry_mod.resolve

    def _resolve_with_fake_factory( command, crud_enabled ):
        spec = real_resolve( command, crud_enabled )
        return None if spec is None else dataclass_replace( spec, factory=FakeAgent )

    monkeypatch.setattr( flow_mod, "resolve", _resolve_with_fake_factory )


def test_a_crud_command_never_reads_the_cache( tmp_path, notifier, monkeypatch ):
    """
    Rick's ruling (2026-08-20): route first, then look up — so the flow can apply
    the skip running_fifo_queue already applies. CRUD data is mutable; a cached
    answer about it is a stale answer.

    RED ON REVERT: delete the `crud_factory` branch and the todo question reads the
    cache, hits the planted replay row, and comes back path="replay".
    """
    _registry_with_fake_agent_class( monkeypatch )
    planted = types.SimpleNamespace( routing_command="agent router go to todo" )
    cache   = SpyCache( lookup_result=_lookup( is_replay_hit=True, snapshot=planted ) )
    f       = _make_flow( tmp_path, cache, FakeRouter( "agent router go to todo" ), FakeExpeditor(),
                          FakeExecutor(), FakePending(), notifier, crud_enabled=True )

    r = f.ask( "put milk on my todo list", **_CTX )

    assert cache.lookup_calls == [], "a CRUD command read the cache"
    assert r[ "path" ] == "agent", "a CRUD command replayed a cached answer"
    assert r[ "cache_hit" ] is False


def test_a_non_crud_command_still_reads_the_cache_with_the_flag_on( tmp_path, notifier ):
    """
    NEGATIVE CONTROL for the skip: the flag alone must not turn the cache off.

    Same flow, same live flag, one different routed command — math has no
    crud_factory, so it reads and replays as before.
    """
    planted = types.SimpleNamespace( routing_command="agent router go to math" )
    cache   = SpyCache( lookup_result=_lookup( is_replay_hit=True, snapshot=planted ) )
    f       = _make_flow( tmp_path, cache, FakeRouter( "agent router go to math" ), FakeExpeditor(),
                          FakeExecutor(), FakePending(), notifier, crud_enabled=True )

    r = f.ask( "what is 2+2", **_CTX )

    assert cache.lookup_calls == [ "what is 2+2" ]
    assert r[ "path" ] == "replay"


def test_the_todo_command_reads_the_cache_when_the_crud_flag_is_off( tmp_path, notifier ):
    """
    SECOND NEGATIVE CONTROL, driving the other axis: todo is not permanently
    excluded, it is excluded WHILE FORKED. With the flag off it resolves to the
    ordinary TodoListAgent, whose answers are snapshotable, and the cache is read.

    Together with the test above, the pair fails if either half of the condition is
    dropped — a skip on the flag alone, or a skip on the command alone.
    """
    planted = types.SimpleNamespace( routing_command="agent router go to todo" )
    cache   = SpyCache( lookup_result=_lookup( is_replay_hit=True, snapshot=planted ) )
    f       = _make_flow( tmp_path, cache, FakeRouter( "agent router go to todo" ), FakeExpeditor(),
                          FakeExecutor(), FakePending(), notifier, crud_enabled=False )

    r = f.ask( "what is on my todo list", **_CTX )

    assert cache.lookup_calls == [ "what is on my todo list" ]
    assert r[ "path" ] == "replay"


def test_a_router_error_precedes_any_cache_hit( tmp_path, notifier ):
    """
    Ruled with the reorder: no cache fallback underneath a broken router. A router
    that cannot name the command has told us nothing about the question, so the
    flow bails to the receptionist rather than serving a row it cannot vouch for.

    RED ON REVERT: put the lookup back above the router and the planted replay row
    is served, path="replay", before the router ever says "unknown".
    """
    planted = types.SimpleNamespace( routing_command="agent router go to math" )
    cache   = SpyCache( lookup_result=_lookup( is_replay_hit=True, snapshot=planted ) )
    f       = _make_flow( tmp_path, cache, FakeRouter( "unknown" ), FakeExpeditor(),
                          FakeExecutor(), FakePending(), notifier )

    r = f.ask( "what is 2+2", **_CTX )

    assert cache.lookup_calls == [], "the cache was read underneath a failed router"
    assert r[ "path" ] == "receptionist"
    assert r[ "route_reason" ] == "router_error"


def test_replay_reports_the_routed_command_not_the_snapshots_blank_column( tmp_path, notifier ):
    """
    The matched row's `routing_command` is nullable, blank-defaulted in the
    SolutionSnapshot constructor and `or ""`-coerced on write, so it reported an
    EMPTY command for any row whose provenance was unknown — and the label went out
    as None with it. Route-first means a real command exists by the time a replay is
    decided, so that is what `_finish` is given.

    RED ON REVERT: read `lookup.snapshot.routing_command` again and this row, whose
    column is blank, reports command="" and no label.
    """
    blank = types.SimpleNamespace( routing_command="" )
    cache = SpyCache( lookup_result=_lookup( is_replay_hit=True, snapshot=blank ) )
    f     = _make_flow( tmp_path, cache, FakeRouter( "agent router go to math" ), FakeExpeditor(),
                        FakeExecutor( _outcome( status="waiting", answer=None, job_id=_SCOPED_JOB_ID ) ),
                        FakePending(), notifier, crud_enabled=False )

    r = f.ask( "what is 2+2", **_CTX )

    assert r[ "path" ] == "replay"
    assert r[ "command" ] == "agent router go to math", "the replay reported the row's blank column"
    # The label rides the same fix: a waiting hand-off speaks v1's ack, and the ack
    # names the agent. Resolved off the blank column there is no label and the user
    # hears nothing at all.
    assert notifier.requests, "a waiting replay spoke no acknowledgment"
    assert "todo" not in notifier.requests[ -1 ].message
    assert "math" in notifier.requests[ -1 ].message


# ─────────────────────── the log says whose words the verbatim is

class TestTheQueryLogSaysWhoseWordsItLogged:
    """
    The question-less submit above files the COMMAND STRING under `query_verbatim`,
    which is the only true thing available — but it went into the log typed "api",
    the same value a question a person typed carries. Two rows, identical on every
    field, one of them a routing command and the other somebody's words. Nothing
    downstream could separate them, and a reader counting user questions would count
    both (Pocholo, reviewing the query-log commit).

    `input_type` is free text with no constraint, so the mark needs no migration.
    """

    def _log_on( self, flow ):
        log = FakeQueryLog()
        flow.query_log = log
        return log

    def _flow( self, tmp_path, notifier, monkeypatch ):
        monkeypatch.setattr( flow_mod, "resolve",
                             lambda command, crud_enabled: FakeSpec( required_args=(), snapshotable=False ) )
        return _make_flow( tmp_path, FakeCache(), FakeRouter(), FakeExpeditor(),
                           FakeExecutor( _outcome() ), FakePending(), notifier )

    def test_a_command_fallback_row_differs_from_a_typed_question_row( self, tmp_path, notifier, monkeypatch ):
        """
        THE WHOLE FINDING IN ONE TEST: the same flow, two submits, and the rows must
        not be interchangeable.

        RED ON REVERT: hard-code input_type back to "api" and the two rows match on
        it, which is the defect — a command string reading as a thing somebody said.
        """
        f   = self._flow( tmp_path, notifier, monkeypatch )
        log = self._log_on( f )

        f.submit( command="agent router go to math", args={}, question="what is 2+2", **_CTX )
        f.submit( command="agent router go to math", args={}, **_CTX )

        typed, fallback = log.rows[ -2 ], log.rows[ -1 ]
        assert typed[ "query_verbatim" ] == "what is 2+2"
        assert fallback[ "query_verbatim" ] == "agent router go to math"
        assert typed[ "input_type" ] != fallback[ "input_type" ], (
            "a routing command was logged as indistinguishable from a user's words"
        )
        assert typed[ "input_type" ]    == "api"
        assert fallback[ "input_type" ] == "api-command"

    def test_a_prebuilt_job_submit_is_marked_too( self, tmp_path, notifier, monkeypatch ):
        """
        The second shape of the same hole. An in-process caller hands over a job it
        built and names no question at all, so the verbatim is "" — and an EMPTY
        question is something a user can genuinely send (the fitness gate rejects it,
        and that refusal is logged). Blank-and-"api" therefore had two meanings.

        RED ON REVERT: mark only the command case and this row types "api" again,
        landing back in the same bucket as a rejected empty question.
        """
        f   = self._flow( tmp_path, notifier, monkeypatch )
        log = self._log_on( f )

        f.submit( job=FakeAgent( routing_command="agent router go to math" ), **_CTX )

        assert log.rows[ -1 ][ "query_verbatim" ] == ""
        assert log.rows[ -1 ][ "input_type" ]     == "api-job"

    def test_ask_is_untouched_and_still_types_api( self, tmp_path, notifier, monkeypatch ):
        """
        NEGATIVE CONTROL. The mark keys on a missing question, not on the entry
        point: everything that comes in through `ask` is a person's words and keeps
        v1's value.

        RED ON REVERT: key the mark on `entry` instead and an ordinary spoken
        question starts reporting a source it does not have.
        """
        f   = self._flow( tmp_path, notifier, monkeypatch )
        log = self._log_on( f )

        f.ask( "what is 2+2", **_CTX )

        assert log.rows[ -1 ][ "input_type" ] == "api"

    def test_an_empty_question_rejection_still_types_api( self, tmp_path, notifier, monkeypatch ):
        """
        The row the "api-job" mark exists to be separable FROM: a user really did
        send nothing, the fitness gate refused it, and that is a user row with a
        blank verbatim.
        """
        f   = self._flow( tmp_path, notifier, monkeypatch )
        log = self._log_on( f )

        r = f.ask( "   ", **_CTX )

        assert r[ "status" ] == "rejected"
        assert log.rows[ -1 ][ "input_type" ] == "api"


class TestAnEmptyQuestionIsNoQuestion:
    """
    The door's `question` field has no min_length, so "" is a legal thing to send —
    and `question or command` has always treated it as absent, filing the COMMAND
    under query_verbatim. Both guards downstream tested for None, so an ""-submit
    was typed "api" like a person's words, and wrote a cache row keyed on a routing
    command that `ask` can never match (Pocholo). Nothing covered the empty string.
    """

    def _log_on( self, flow ):
        log = FakeQueryLog()
        flow.query_log = log
        return log

    def test_an_empty_question_submit_is_marked_as_the_command_it_named( self, tmp_path, notifier, monkeypatch ):
        """
        RED ON REVERT: restore `if question is None:` and this row types "api" —
        indistinguishable from a question somebody typed.
        """
        monkeypatch.setattr( flow_mod, "resolve",
                             lambda command, crud_enabled: FakeSpec( required_args=(), snapshotable=True ) )
        f   = _make_flow( tmp_path, FakeCache(), FakeRouter(), FakeExpeditor(),
                          FakeExecutor( _outcome() ), FakePending(), notifier )
        log = self._log_on( f )

        f.submit( command="agent router go to math", args={}, question="", **_CTX )

        assert log.rows[ -1 ][ "query_verbatim" ] == "agent router go to math"
        assert log.rows[ -1 ][ "input_type" ]     == "api-command"

    def test_an_empty_question_submit_writes_no_cache_row( self, tmp_path, notifier, monkeypatch ):
        """
        The row would be filed under the command string, and `ask` looks rows up by
        the user's words — nobody says "agent router go to math". A row that can
        never be hit is landfill that still costs a read on every lookup.

        RED ON REVERT: restore `question is not None` and the write-back fires, with
        the registry saying snapshotable=True.
        """
        monkeypatch.setattr( flow_mod, "resolve",
                             lambda command, crud_enabled: FakeSpec( required_args=(), snapshotable=True ) )
        cache = FakeCache()
        f     = _make_flow( tmp_path, cache, FakeRouter(), FakeExpeditor(),
                            FakeExecutor( _outcome() ), FakePending(), notifier,
                            writeback_enabled=True )

        f.submit( command="agent router go to math", args={}, question="", **_CTX )

        assert cache.write_back_calls == [], "an empty-question submit wrote a cache row keyed on the command"

    def test_a_real_question_submit_still_writes_and_still_types_api( self, tmp_path, notifier, monkeypatch ):
        """
        NEGATIVE CONTROL on both lines at once: widen either guard past "no question"
        — to `not question.strip()`, say, or to the entry point — and a genuine
        submitted question stops being cached and starts being marked.
        """
        monkeypatch.setattr( flow_mod, "resolve",
                             lambda command, crud_enabled: FakeSpec( required_args=(), snapshotable=True ) )
        cache = FakeCache()
        f     = _make_flow( tmp_path, cache, FakeRouter(), FakeExpeditor(),
                            FakeExecutor( _outcome() ), FakePending(), notifier,
                            writeback_enabled=True )
        log   = self._log_on( f )

        f.submit( command="agent router go to math", args={}, question="what is 2+2", **_CTX )

        assert cache.write_back_calls, "a genuine submitted question was not cached"
        assert log.rows[ -1 ][ "input_type" ] == "api"

    def test_a_whitespace_only_question_is_no_question_either( self, tmp_path, notifier, monkeypatch ):
        """
        `bool( question )` admits "   " (Pocholo, on the fix for the empty string).
        `ask`'s fitness gate has always called blank-or-whitespace no question at all;
        `submit` has no gate, so it borrows the same rule instead of growing a looser
        one — otherwise a row is filed under three spaces, typed as a person's words,
        and cached under a key nobody will ever say.

        RED ON REVERT: swap _has_question back for `bool( question )` and this row
        types "api", logs "   ", and writes.
        """
        monkeypatch.setattr( flow_mod, "resolve",
                             lambda command, crud_enabled: FakeSpec( required_args=(), snapshotable=True ) )
        cache = FakeCache()
        f     = _make_flow( tmp_path, cache, FakeRouter(), FakeExpeditor(),
                            FakeExecutor( _outcome() ), FakePending(), notifier,
                            writeback_enabled=True )
        log   = self._log_on( f )

        f.submit( command="agent router go to math", args={}, question="   ", **_CTX )

        assert log.rows[ -1 ][ "query_verbatim" ] == "agent router go to math"
        assert log.rows[ -1 ][ "input_type" ]     == "api-command"
        assert cache.write_back_calls == [], "a whitespace-only question was cached"

    def test_one_rule_decides_it_for_ask_and_submit_alike( self, tmp_path, notifier, monkeypatch ):
        """
        The two doors must not disagree about what a question is. `ask` refuses the
        same whitespace `submit` declines to attribute or cache.

        RED ON REVERT: give either door its own test for emptiness and one of these
        two assertions stops holding.
        """
        f = self._flow_for_ask( tmp_path, notifier, monkeypatch )

        assert AskFlow._has_question( "   " ) is False
        assert f.ask( "   ", **_CTX )[ "route_reason" ] == "empty_question"

    def _flow_for_ask( self, tmp_path, notifier, monkeypatch ):
        monkeypatch.setattr( flow_mod, "resolve",
                             lambda command, crud_enabled: FakeSpec( required_args=(), snapshotable=False ) )
        return _make_flow( tmp_path, FakeCache(), FakeRouter(), FakeExpeditor(),
                           FakeExecutor( _outcome() ), FakePending(), notifier )


# ─────────────── bug 38815328 — a written row that could never be served

class TestAWrittenRowCanActuallyBeReplayed:
    """
    Mr Radio measured it on the 2026-08-21 warm pass: 117 of 300 requests came back
    as the receptionist with error=null. The v2 write-back copied question, answer,
    routing_command and class off the result and NOTHING ELSE, so every row it wrote
    had empty code — and SolutionSnapshot.run_code() raises "Cannot execute empty
    code list" for every class outside CODELESS_AGENT_CLASSES. Calculator rows
    replayed 60/60; MathAgent rows were written and could never be served.

    Three parts, all pinned here: the code travels out of the agent, the write-back
    persists it, and a row that still could not be served is not written at all.
    """

    class _PromptlessAgent( FakeAgent ):
        """An agent that answered without ever running a prompt.

        It carries `answer` because the executor reads that off every job — a fake
        missing it fails in the executor for an unrelated reason and would let the
        guard under test pass vacuously.
        """

        def __init__( self, **kwargs ):
            super().__init__( **kwargs )
            self.answer = "4"

        def do_all( self ):
            return "4"

    class _CodingAgent( FakeAgent ):
        """An agent that ran a prompt, as every code-generating agent does."""

        def __init__( self, **kwargs ):
            super().__init__( **kwargs )
            self.answer               = "4"
            self.prompt_response_dict = {
                "code"    : [ "solution = 2 + 2" ],
                "example" : "solution = 2 + 2",
                "returns" : "int",
            }

        def do_all( self ):
            return "4"

    def _flow_with( self, tmp_path, notifier, monkeypatch, factory, **flow_kw ):
        monkeypatch.setattr( flow_mod, "resolve",
                             lambda command, crud_enabled: FakeSpec( required_args=(), snapshotable=True,
                                                                     factory=factory ) )
        cache = FakeCache()
        f     = _make_flow( tmp_path, cache, FakeRouter(), FakeExpeditor(),
                            InlineExecutor(), FakePending(), notifier,
                            writeback_enabled=True, **flow_kw )
        return f, cache

    def test_the_agents_code_reaches_the_written_snapshot( self, tmp_path, notifier, monkeypatch ):
        """
        THE WHOLE BUG, end to end and through the REAL executor: agent → Outcome →
        write-back. A test that handed the flow a pre-built Outcome would prove the
        second half only, and the first half is where the code was being dropped.

        RED ON REVERT: stop copying prompt_response_dict in InlineExecutor._run_agent,
        or stop passing code= at the snapshot_from_result call, and the written
        snapshot has no code — which is a row run_code() can never execute.
        """
        f, cache = self._flow_with( tmp_path, notifier, monkeypatch, self._CodingAgent )

        f.ask( "what is 2+2", **_CTX )

        assert cache.snapshot_calls, "nothing was written back at all"
        written = cache.snapshot_calls[ -1 ]
        assert written[ "code" ]         == [ "solution = 2 + 2" ]
        assert written[ "code_example" ] == "solution = 2 + 2"
        assert written[ "code_returns" ] == "int"

    def test_an_agent_that_never_ran_a_prompt_is_not_reported_as_broken( self, tmp_path, notifier, monkeypatch ):
        """
        `prompt_response_dict` is set by AgentBase.run_prompt(), not by __init__, so an
        agent that answered without running a prompt does not have one. Reading it
        unguarded raises INSIDE the executor's try — turning a successful agent run
        into Outcome(failed) and sending the user the receptionist.

        RED ON REVERT: drop the hasattr guard in _generated_code.
        """
        f, _cache = self._flow_with( tmp_path, notifier, monkeypatch, self._PromptlessAgent )

        r = f.ask( "what is 2+2", **_CTX )

        assert r[ "path" ] == "agent", "an agent with no prompt_response_dict was reported as failed"
        assert r[ "status" ] == "done"

    def test_a_row_that_could_never_be_served_is_not_written( self, tmp_path, notifier, monkeypatch ):
        """
        THE SAFETY NET. The agent above produced no code and FakeAgent is not a
        codeless class, so a row written from it would raise "Cannot execute empty code
        list" on every hit — dead on arrival, and still costing a read on every lookup.

        RED ON REVERT: delete the _is_replayable check in _maybe_write_back.
        """
        f, cache = self._flow_with( tmp_path, notifier, monkeypatch, self._PromptlessAgent )

        r = f.ask( "what is 2+2", **_CTX )

        assert r[ "path" ] == "agent", "the agent did not even run — this proves nothing about the writer"
        assert cache.write_back_calls == [], "a row with no code was written for a class that needs code"

    def test_a_codeless_class_is_still_written_without_code( self, tmp_path, notifier, monkeypatch ):
        """
        NEGATIVE CONTROL, and the reason the guard reads the shared set instead of
        just asking "is there code": CalculatorAgent snapshots are codeless BY DESIGN —
        run_code() serves their cached answer. Refusing to write them would empty the
        one category that was replaying 60/60.

        RED ON REVERT: make the guard `bool( outcome.code )` alone and calculator
        results stop being cached.
        """
        class _CalculatorAgent( self._PromptlessAgent ):
            pass
        _CalculatorAgent.__name__ = "CalculatorAgent"

        f, cache = self._flow_with( tmp_path, notifier, monkeypatch, _CalculatorAgent )

        f.ask( "what is 2+2", **_CTX )

        assert cache.write_back_calls, "a codeless-by-design class stopped being cached"

    def test_whitespace_only_code_does_not_count_as_code( self, tmp_path, notifier, monkeypatch ):
        """
        run_code() rejects a code list whose lines are all blank with the same error as
        an empty one, so the writer has to agree with it. A row full of empty strings
        is as dead as a row with none.

        RED ON REVERT: test `outcome.code is not None` instead of looking at the lines.
        """
        class _BlankCodeAgent( self._CodingAgent ):
            def __init__( self, **kwargs ):
                super().__init__( **kwargs )
                self.prompt_response_dict = { "code": [ "", "   " ], "example": "", "returns": "" }

        f, cache = self._flow_with( tmp_path, notifier, monkeypatch, _BlankCodeAgent )

        f.ask( "what is 2+2", **_CTX )

        assert cache.write_back_calls == [], "a row of blank code lines was written"

    def test_a_failed_replay_now_says_why( self, tmp_path, notifier, monkeypatch ):
        """
        115 of the 117 failures reached the client with error=null, so the eval could
        not say what went wrong. The agent path has always passed primary_error; the
        replay path dropped it.

        RED ON REVERT: drop primary_error= from the replay degrade and the emitted
        error is the receptionist's own, which is None.
        """
        monkeypatch.setattr( flow_mod, "resolve",
                             lambda command, crud_enabled: FakeSpec( required_args=(), snapshotable=False ) )
        snap     = types.SimpleNamespace( routing_command="agent router go to math" )
        cache    = FakeCache( lookup_result=_lookup( is_replay_hit=True, snapshot=snap ) )
        outcomes = [ _outcome( status="failed", answer=None,
                               error="Cannot execute empty code list — snapshot has no executable code" ),
                     _outcome( status="done" ) ]

        class _SeqExecutor( FakeExecutor ):
            def submit( self, work, trace ):
                self.works.append( work )
                return outcomes.pop( 0 )

        f = _make_flow( tmp_path, cache, FakeRouter(), FakeExpeditor(), _SeqExecutor(),
                        FakePending(), notifier )

        r = f.ask( "what is 2+2", **_CTX )

        assert r[ "route_reason" ] == "replay_error"
        assert r[ "error" ] is not None, "a failed replay still reached the client with error=null"
        assert "empty code list" in r[ "error" ]


# ────────────────────────────── 6b — the near-match ask

class _FakeConfirmer:
    """Stands in for notify_user_sync: records the request, answers a scripted reply."""

    def __init__( self, status="responded", response_value="yes", raises=None ):
        self.requests = []
        self.kwargs   = []
        self._status  = status
        self._value   = response_value
        self._raises  = raises

    def __call__( self, request, **kwargs ):
        self.requests.append( request )
        self.kwargs.append( kwargs )
        if self._raises is not None:
            raise self._raises
        return types.SimpleNamespace( status=self._status, response_value=self._value )


class TestTheFlowAsksAboutANearMatch:
    """
    Rick's ruling, 2026-08-20: the brain gets the near-match ask. Above the
    confirmation threshold but short of exact, the flow asks the same question the
    voice path asks today and replays only on a yes.

    This is not a nicety. 7b deletes the queue's copy of the ask, and
    running_fifo_queue's accept-above-the-floor is safe ONLY because that upstream ask
    happened — so without this branch a 90-to-99% match would replay an answer nobody
    confirmed, arriving as a side effect of a deletion rather than a decision.
    """

    def _flow( self, tmp_path, notifier, monkeypatch, confirmer, score=95.0,
               threshold=90.0, enabled=True, candidate_question="what is on my todo list" ):
        monkeypatch.setattr( flow_mod, "resolve",
                             lambda command, crud_enabled: FakeSpec( required_args=(), snapshotable=False ) )
        candidate = types.SimpleNamespace( question=candidate_question, id_hash="near-1" )
        cache     = FakeCache( lookup_result=_lookup( is_replay_hit=False, best_candidate=candidate,
                                                      best_score=score, similarity=score, tier="ann" ) )
        return AskFlow(
            cache, FakeRouter(), FakeExpeditor(), FakeExecutor( _outcome() ), FakePending(),
            crud_enabled=False, confirmation_threshold=threshold, confirmation_enabled=enabled,
            confirmer=confirmer, receptionist_factory=FakeReceptionist, notifier=notifier,
            trace_dir=str( tmp_path ),
        )

    def test_a_near_match_asks_before_it_replays( self, tmp_path, notifier, monkeypatch ):
        """
        THE PIN. The user is asked, says yes, and the cached answer is served.

        RED ON REVERT: delete the near-match branch and a 95% match routes to the agent
        with nothing asked — the answer is re-derived and the prompt never happens.
        """
        confirmer = _FakeConfirmer( response_value="yes" )
        f         = self._flow( tmp_path, notifier, monkeypatch, confirmer )

        r = f.ask( "what's on my todo list", **_CTX )

        assert confirmer.requests, "a near match replayed without asking anybody"
        assert r[ "path" ] == "replay"
        assert r[ "route_reason" ] == "near_match_confirmed"
        assert r[ "cache_hit" ] is True

    def test_the_question_is_the_one_the_voice_path_asks( self, tmp_path, notifier, monkeypatch ):
        """
        Same sentence, same YES_NO shape, same 30s default-to-no, same retry ladder as
        the queue's. A user who hears this prompt today must hear the same one after
        the switch.

        RED ON REVERT: reword the prompt, or default it to anything but "no", and the
        behaviour a listener relies on changes silently.
        """
        confirmer = _FakeConfirmer()
        f         = self._flow( tmp_path, notifier, monkeypatch, confirmer,
                                candidate_question="what is on my todo list" )

        f.ask( "what's on my todo list", **_CTX )

        request = confirmer.requests[ -1 ]
        assert request.message          == "Is that the same as: what is on my todo list?"
        assert request.response_default == "no"
        assert request.timeout_seconds  == 30
        assert request.target_user      == _CTX[ "user_email" ]
        assert confirmer.kwargs[ -1 ] == { "retry_on_timeout": True, "max_attempts": 3,
                                           "backoff_multiplier": 2.0 }

    def test_a_no_routes_instead_of_replaying( self, tmp_path, notifier, monkeypatch ):
        """The whole point of asking is that the answer can be no."""
        confirmer = _FakeConfirmer( response_value="no" )
        f         = self._flow( tmp_path, notifier, monkeypatch, confirmer )

        r = f.ask( "what's on my todo list", **_CTX )

        assert r[ "path" ] == "agent", "a declined near match replayed anyway"
        assert r[ "cache_hit" ] is False

    def test_a_timeout_routes_too( self, tmp_path, notifier, monkeypatch ):
        """
        Silence is not consent. The prompt defaults to "no" because the cost of a wrong
        replay is a confident answer to a question nobody asked.

        RED ON REVERT: treat anything but an explicit "no" as a yes.
        """
        confirmer = _FakeConfirmer( status="timeout", response_value="no" )
        f         = self._flow( tmp_path, notifier, monkeypatch, confirmer )

        assert f.ask( "what's on my todo list", **_CTX )[ "path" ] == "agent"

    def test_a_yes_that_did_not_come_from_the_user_is_not_a_yes( self, tmp_path, notifier, monkeypatch ):
        """
        BOTH halves of the check, and the reason this test exists separately: the case
        above pairs a timeout with the value "no", so it stays green even if the STATUS
        is ignored and only the value is read. Pairing a non-responded status with the
        value "yes" is what tells the two apart.

        A "yes" the user never said — a stale value, a default, a replayed payload —
        must not license a replay.

        RED ON REVERT: check only `response_value == "yes"` and this replays.
        """
        confirmer = _FakeConfirmer( status="timeout", response_value="yes" )
        f         = self._flow( tmp_path, notifier, monkeypatch, confirmer )

        assert f.ask( "what's on my todo list", **_CTX )[ "path" ] == "agent"

    def test_a_broken_confirmer_is_a_no( self, tmp_path, notifier, monkeypatch ):
        """
        The notification path failing is not evidence that two questions are the same.
        A replay served because the ask BROKE is exactly the silent wrong-but-close
        answer this branch exists to prevent.

        RED ON REVERT: let the exception propagate (the request 500s) or swallow it and
        proceed — either is worse than routing.
        """
        confirmer = _FakeConfirmer( raises=RuntimeError( "notification service down" ) )
        f         = self._flow( tmp_path, notifier, monkeypatch, confirmer )

        assert f.ask( "what's on my todo list", **_CTX )[ "path" ] == "agent"

    def test_below_the_threshold_nobody_is_asked( self, tmp_path, notifier, monkeypatch ):
        """
        NEGATIVE CONTROL on the threshold: a weak match routes silently, as it does
        today. Asking about every candidate would make the assistant interrogate the
        user about questions that merely share a word.
        """
        confirmer = _FakeConfirmer()
        f         = self._flow( tmp_path, notifier, monkeypatch, confirmer, score=72.0 )

        r = f.ask( "what's on my todo list", **_CTX )

        assert confirmer.requests == [], "the user was asked about a 72% match"
        assert r[ "path" ] == "agent"

    @pytest.mark.parametrize( "score", [ -1.0, 101.0 ] )
    def test_an_out_of_range_score_is_refused_not_trusted( self, tmp_path, notifier, monkeypatch, score ):
        """
        Bug 78f21b1b, ported with the branch that re-opens the door to it. A similarity
        outside 0-100 is a broken MEASUREMENT, and 101% would otherwise sail past a 90%
        threshold and replay without even being asked about.

        v1 has this guard; v2 did not need it while a replay required a tier-1 exact
        hit, so no float ever decided one. The gist tier and this branch are what
        change that, which is why the guard arrives WITH them.

        RED ON REVERT: drop the range check and 101.0 replays.
        """
        confirmer = _FakeConfirmer()
        f         = self._flow( tmp_path, notifier, monkeypatch, confirmer, score=score )

        r = f.ask( "what's on my todo list", **_CTX )

        assert confirmer.requests == []
        assert r[ "path" ] == "agent"
        assert r[ "cache_hit" ] is False

    def test_with_confirmation_disabled_the_match_is_auto_accepted( self, tmp_path, notifier, monkeypatch ):
        """
        `similarity confirmation enabled = false` — v1 auto-accepts the best semantic
        match with no prompt, and so does this. The Sequence's step 6b describes the
        ask and says nothing about the key that turns the ask off; two behaviours in
        one step is how one of them ends up unbuilt.

        The route_reason NAMES which one happened, so a log can tell an answer the user
        confirmed from one the configuration accepted on their behalf.
        """
        confirmer = _FakeConfirmer()
        f         = self._flow( tmp_path, notifier, monkeypatch, confirmer, enabled=False )

        r = f.ask( "what's on my todo list", **_CTX )

        assert confirmer.requests == [], "confirmation is off but the user was asked anyway"
        assert r[ "path" ] == "replay"
        assert r[ "route_reason" ] == "near_match_auto_accepted"

    def test_a_flow_with_no_threshold_has_no_near_match_behaviour( self, tmp_path, notifier, monkeypatch ):
        """
        FAIL CLOSED. A caller that never wires the threshold gets what v2 did before
        this branch existed — route below a perfect hit — rather than a new replay
        nobody asked for. An omission must not be able to arm a guard.

        ⚠️ THE ARGUMENT IS OMITTED, NOT PASSED AS None, and that is the whole test.
        Passing `confirmation_threshold=None` explicitly proves only that the branch
        honours a None it was handed; a constructor that DEFAULTED the parameter to 90.0
        would leave this green while every flow in the process silently gained the
        behaviour. The first version of this test did exactly that (Pocholo).

        RED ON REVERT: default `confirmation_threshold` to 90.0 in AskFlow.__init__.
        """
        monkeypatch.setattr( flow_mod, "resolve",
                             lambda command, crud_enabled: FakeSpec( required_args=(), snapshotable=False ) )
        confirmer = _FakeConfirmer()
        candidate = types.SimpleNamespace( question="what is on my todo list", id_hash="near-1" )
        cache     = FakeCache( lookup_result=_lookup( is_replay_hit=False, best_candidate=candidate,
                                                      best_score=95.0, similarity=95.0, tier="ann" ) )
        f = AskFlow( cache, FakeRouter(), FakeExpeditor(), FakeExecutor( _outcome() ), FakePending(),
                     crud_enabled=False, confirmer=confirmer,     # <- no confirmation_threshold
                     receptionist_factory=FakeReceptionist, notifier=notifier, trace_dir=str( tmp_path ) )

        r = f.ask( "what's on my todo list", **_CTX )

        assert confirmer.requests == []
        assert r[ "path" ] == "agent"

    def test_an_exact_hit_is_never_put_to_the_user( self, tmp_path, notifier, monkeypatch ):
        """
        NEGATIVE CONTROL at the top end: tier 1 already decided. Asking "is that the
        same as" about the user's own words verbatim would be absurd, and it is the
        mistake a branch ordered after the exact check cannot make — this test is what
        keeps that ordering.
        """
        monkeypatch.setattr( flow_mod, "resolve",
                             lambda command, crud_enabled: FakeSpec( required_args=(), snapshotable=False ) )
        confirmer = _FakeConfirmer()
        snap      = types.SimpleNamespace( routing_command="agent router go to math", question="what is 2+2" )
        cache     = FakeCache( lookup_result=_lookup( is_replay_hit=True, snapshot=snap,
                                                      best_candidate=snap, best_score=100.0 ) )
        f = AskFlow( cache, FakeRouter(), FakeExpeditor(), FakeExecutor( _outcome() ), FakePending(),
                     crud_enabled=False, confirmation_threshold=90.0, confirmer=confirmer,
                     receptionist_factory=FakeReceptionist, notifier=notifier, trace_dir=str( tmp_path ) )

        r = f.ask( "what is 2+2", **_CTX )

        assert confirmer.requests == [], "an exact hit was put to the user for confirmation"
        assert r[ "route_reason" ] == "exact_hit"

    def test_a_non_interactive_caller_is_never_asked( self, tmp_path, notifier, monkeypatch ):
        """
        `interactive=False` says nobody is at the other end — dead_queue_watchdog's retry
        is one such caller. Asking anyway sends a prompt to a user who never sees it,
        holds the calling thread through the whole 30/60/120s retry ladder, and then
        defaults to "no". Same answer, three minutes later, on a watchdog's thread.

        It DECLINES rather than accepting: an unattended caller cannot consent.

        RED ON REVERT: drop the interactive check and the confirmer is called.
        """
        confirmer = _FakeConfirmer( response_value="yes" )
        f         = self._flow( tmp_path, notifier, monkeypatch, confirmer )

        r = f.ask( "what's on my todo list", **_CTX, interactive=False )

        assert confirmer.requests == [], "a caller with no human on it was put to the user"
        assert r[ "path" ] == "agent", "the near match was accepted without consent"

    def test_confirmation_off_still_auto_accepts_for_a_non_interactive_caller( self, tmp_path, notifier, monkeypatch ):
        """
        The two flags say different things and must not be collapsed. `interactive=False`
        means nobody can answer; `similarity confirmation enabled = false` means nobody
        should be asked at all — and under that setting v1 serves the match. Declining
        here would take the cache away from every unattended caller on a configuration
        that never wanted a prompt in the first place.
        """
        confirmer = _FakeConfirmer()
        f         = self._flow( tmp_path, notifier, monkeypatch, confirmer, enabled=False )

        r = f.ask( "what's on my todo list", **_CTX, interactive=False )

        assert confirmer.requests == []
        assert r[ "route_reason" ] == "near_match_auto_accepted"

    def test_a_crud_command_is_never_offered_a_near_match( self, tmp_path, notifier, monkeypatch ):
        """
        6-pre and 6b compose: a CRUD command reads no cache at all, so there is no
        candidate to ask about. Confirming a stale todo list with the user would not
        make it any less stale.
        """
        confirmer = _FakeConfirmer()
        candidate = types.SimpleNamespace( question="what is on my todo list", id_hash="near-1" )
        cache     = SpyCache( lookup_result=_lookup( is_replay_hit=False, best_candidate=candidate,
                                                     best_score=95.0, tier="ann" ) )
        _registry_with_fake_agent_class( monkeypatch )
        f = AskFlow( cache, FakeRouter( "agent router go to todo" ), FakeExpeditor(),
                     FakeExecutor( _outcome() ), FakePending(), crud_enabled=True,
                     confirmation_threshold=90.0, confirmer=confirmer,
                     receptionist_factory=FakeReceptionist, notifier=notifier, trace_dir=str( tmp_path ) )

        f.ask( "put milk on my todo list", **_CTX )

        assert cache.lookup_calls == []
        assert confirmer.requests == []
