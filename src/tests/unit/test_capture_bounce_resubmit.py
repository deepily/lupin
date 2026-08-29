"""
Unit tests for the capture-bounce-resubmit :8000 control.

Venue: :7999-discretionary — pure in-process, no persistent state, no server,
sub-second. The script talks HTTP only through an injected client, so every
test drives a fake client + fake bouncer; nothing touches a real queue or
container.

DELETE-THE-STEP CONTROL (per f3beb6d5 doctrine — a test must go RED when the
step it guards is removed):
  - test_bounce_sits_between_capture_and_resubmit: delete the bounce call and
    the recorded call order loses "bounce" -> RED. This is the whole reason the
    script exists (resubmitting against the un-bounced, stale-code server is a
    no-op control).
  - test_resubmit_moves_every_recoverable_job: delete the resubmit loop body and
    submit is called 0 times -> RED.
  - test_capture_records_every_pending_job: delete the capture loop body and 0
    records are written -> RED.
  - test_other_owner_jobs_are_resubmitted: add any "skip if not mine" owner
    filter and the other-owner job stops moving -> RED.
  - test_unrecoverable_job_is_captured_not_dropped: drop non-test-suite jobs on
    capture and the count falls -> RED.
"""

import os
import json
import importlib.util

import pytest


# ── Import the hyphen-named script as a module ────────────────────────────────
_HERE   = os.path.dirname( __file__ )
_SCRIPT = os.path.abspath( os.path.join( _HERE, "..", "..", "scripts", "capture-bounce-resubmit.py" ) )
_spec   = importlib.util.spec_from_file_location( "capture_bounce_resubmit", _SCRIPT )
cbr     = importlib.util.module_from_spec( _spec )
_spec.loader.exec_module( cbr )


# ── Fakes ─────────────────────────────────────────────────────────────────────

class FakeClient:
    """Records fetch/submit calls; returns canned todo metadata."""

    def __init__( self, todo_jobs, call_log=None ):
        self.todo_jobs   = todo_jobs
        self.submitted   = []
        self.call_log    = call_log if call_log is not None else []
        self._next_id    = 0

    def fetch_todo( self ):
        self.call_log.append( "fetch" )
        return list( self.todo_jobs )

    def submit( self, payload ):
        self.call_log.append( "submit" )
        self.submitted.append( payload )
        self._next_id += 1
        return { "job_id": f"ts-new{self._next_id}", "status": "queued" }


def _job( job_id, question_text, agent_type="test_suite", owner="tester@x", scheduled_at=None ):
    return {
        "job_id"        : job_id,
        "question_text" : question_text,
        "agent_type"    : agent_type,
        "user_email"    : owner,
        "scheduled_at"  : scheduled_at,
        "monopolize"    : True,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# Pure reconstruction
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize( "text,expected", [
    ( "[Tests] integration, e2e", [ "integration", "e2e" ] ),
    ( "[Tests] unit",             [ "unit" ] ),
    ( "[Tests] a,b , c",          [ "a", "b", "c" ] ),
    ( "[Tests] ",                 None ),
    ( "Deep Research: foo",       None ),
    ( None,                        None ),
    ( 123,                         None ),
] )
def test_parse_test_types( text, expected ):
    assert cbr.parse_test_types( text ) == expected


def test_build_record_reconstructs_test_suite_payload():
    rec = cbr.build_capture_record( _job( "ts-1", "[Tests] integration, e2e", scheduled_at="2026-08-16T02:00:00-04:00" ) )
    assert rec[ "resubmittable" ] is True
    assert rec[ "payload" ][ "test_types" ] == "integration,e2e"
    assert rec[ "payload" ][ "scheduled_at" ] == "2026-08-16T02:00:00-04:00"
    # Fidelity loss is surfaced, never silent.
    assert rec[ "fidelity_loss" ] == [ "pytest_args", "auto_fix_on_failure", "env_vars" ]


def test_build_record_marks_non_test_suite_unrecoverable():
    rec = cbr.build_capture_record( _job( "dr-9", "Deep Research: climate", agent_type="deep_research" ) )
    assert rec[ "resubmittable" ] is False
    assert rec[ "payload" ] is None
    assert "manual handling" in rec[ "reason" ]


# ═══════════════════════════════════════════════════════════════════════════════
# Capture
# ═══════════════════════════════════════════════════════════════════════════════

def test_capture_records_every_pending_job():
    client = FakeClient( [
        _job( "ts-1", "[Tests] integration" ),
        _job( "ts-2", "[Tests] e2e" ),
        _job( "ts-3", "[Tests] unit" ),
    ] )
    records = cbr.capture( client )
    assert len( records ) == 3            # delete capture loop body -> 0 -> RED
    assert [ r[ "job_id" ] for r in records ] == [ "ts-1", "ts-2", "ts-3" ]


def test_unrecoverable_job_is_captured_not_dropped():
    client = FakeClient( [
        _job( "ts-1", "[Tests] integration" ),
        _job( "dr-9", "Deep Research: x", agent_type="deep_research" ),
    ] )
    records = cbr.capture( client )
    assert len( records ) == 2            # non-test-suite job still captured
    unrecoverable = [ r for r in records if not r[ "resubmittable" ] ]
    assert len( unrecoverable ) == 1
    assert unrecoverable[ 0 ][ "job_id" ] == "dr-9"


def test_save_capture_writes_all_records( tmp_path ):
    records = cbr.capture( FakeClient( [ _job( "ts-1", "[Tests] integration" ), _job( "ts-2", "[Tests] e2e" ) ] ) )
    path    = str( tmp_path / "cap.json" )
    cbr.save_capture( records, path )
    doc = json.loads( open( path ).read() )
    assert doc[ "count" ] == 2
    assert len( doc[ "records" ] ) == 2


# ═══════════════════════════════════════════════════════════════════════════════
# Resubmit
# ═══════════════════════════════════════════════════════════════════════════════

def test_resubmit_moves_every_recoverable_job():
    client  = FakeClient( [ _job( "ts-1", "[Tests] integration" ), _job( "ts-2", "[Tests] e2e" ) ] )
    records = cbr.capture( client )
    cbr.resubmit( client, records )
    assert len( client.submitted ) == 2   # delete resubmit loop body -> 0 -> RED
    assert all( r[ "resubmit_status" ] == "moved" for r in records )
    assert all( r[ "new_job_id" ] for r in records )


def test_other_owner_jobs_are_resubmitted():
    # THE point of the control: a job owned by someone else is the one a human
    # forgets, so it MUST be resubmitted, not skipped.
    client  = FakeClient( [
        _job( "ts-mine",   "[Tests] integration", owner="krishna@lupin" ),
        _job( "ts-cheech", "[Tests] e2e",         owner="cheech@lupin" ),
    ] )
    records = cbr.capture( client )
    cbr.resubmit( client, records )
    moved_owners = [ r[ "owner_email" ] for r in records if r[ "resubmit_status" ] == "moved" ]
    assert "cheech@lupin" in moved_owners   # add owner filter -> RED
    assert len( client.submitted ) == 2


def test_resubmit_skips_unrecoverable_without_submitting():
    client  = FakeClient( [ _job( "dr-9", "Deep Research: x", agent_type="deep_research" ) ] )
    records = cbr.capture( client )
    cbr.resubmit( client, records )
    assert client.submitted == []
    assert records[ 0 ][ "resubmit_status" ] == "skipped"


def test_resubmit_failure_is_captured_not_raised():
    class Boom( FakeClient ):
        def submit( self, payload ):
            self.call_log.append( "submit" )
            raise RuntimeError( "500 from server" )

    client  = Boom( [ _job( "ts-1", "[Tests] integration" ) ] )
    records = cbr.capture( client )
    cbr.resubmit( client, records )       # must not raise
    assert records[ 0 ][ "resubmit_status" ] == "failed"
    assert "500 from server" in records[ 0 ][ "resubmit_error" ]


# ═══════════════════════════════════════════════════════════════════════════════
# Orchestration + THE delete-the-step control on ordering
# ═══════════════════════════════════════════════════════════════════════════════

def test_bounce_sits_between_capture_and_resubmit( tmp_path ):
    call_log = []
    client   = FakeClient( [ _job( "ts-1", "[Tests] integration" ), _job( "ts-2", "[Tests] e2e" ) ], call_log=call_log )

    def bouncer():
        call_log.append( "bounce" )

    cbr.run_capture_bounce_resubmit(
        client       = client,
        bouncer      = bouncer,
        capture_path = str( tmp_path / "cap.json" ),
        apply        = True,
    )

    # Fetch happens once, then exactly one bounce, then all submits — and the
    # bounce is strictly AFTER the fetch and strictly BEFORE the first submit.
    assert "bounce" in call_log                                    # delete bounce call -> RED
    assert call_log.count( "bounce" ) == 1
    bounce_i = call_log.index( "bounce" )
    fetch_i  = call_log.index( "fetch" )
    submit_i = call_log.index( "submit" )
    assert fetch_i < bounce_i < submit_i                          # reorder -> RED


def test_dry_run_never_bounces_or_resubmits( tmp_path ):
    call_log = []
    client   = FakeClient( [ _job( "ts-1", "[Tests] integration" ) ], call_log=call_log )

    def bouncer():
        call_log.append( "bounce" )

    report = cbr.run_capture_bounce_resubmit(
        client       = client,
        bouncer      = bouncer,
        capture_path = str( tmp_path / "cap.json" ),
        apply        = False,
    )

    assert "bounce" not in call_log
    assert client.submitted == []
    assert report[ "moved" ] == 0
    assert report[ "resubmittable" ] == 1   # it WOULD move, but dry-run holds


def test_capture_file_written_even_in_dry_run( tmp_path ):
    path   = str( tmp_path / "cap.json" )
    client = FakeClient( [ _job( "ts-1", "[Tests] integration" ) ] )
    cbr.run_capture_bounce_resubmit(
        client       = client,
        bouncer      = lambda: None,
        capture_path = path,
        apply        = False,
    )
    assert os.path.exists( path )           # capture is unconditional


def test_report_counts_and_render( tmp_path ):
    client = FakeClient( [
        _job( "ts-1", "[Tests] integration", owner="krishna@lupin" ),
        _job( "ts-2", "[Tests] e2e",         owner="cheech@lupin" ),
        _job( "dr-9", "Deep Research: x",     agent_type="deep_research", owner="radio@lupin" ),
    ] )
    report = cbr.run_capture_bounce_resubmit(
        client       = client,
        bouncer      = lambda: None,
        capture_path = str( tmp_path / "cap.json" ),
        apply        = True,
    )
    assert report[ "total" ] == 3
    assert report[ "resubmittable" ] == 2
    assert report[ "moved" ] == 2
    assert report[ "unrecoverable" ] == 1
    assert report[ "fidelity_loss_jobs" ] == 2

    text = cbr.format_report( report )
    # Every captured job appears exactly once in the render.
    assert text.count( "cheech@lupin" ) == 1
    assert "FIDELITY-LOSS" in text
    assert "deep_research" in text or "Deep Research" in text
