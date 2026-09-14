"""
A worktree the janitor refuses to remove must be VISIBLE, and announced only when the
refused set changes.

Row 033538f6 (2026-09-14). A reap refuses a tree holding ignored data. Mr. Radio's review
said a refusal nobody sees is the old pile, moved to `.claude/worktrees/`, where nobody
looks. His three conditions, each pinned below:

  1. the notify carries the COUNT, and its abstract lists each tree with its blockers;
  2. comparing the new set with the last one decides whether to send, and an unchanged
     set sends NOTHING;
  3. a failed notify is logged, never swallowed.

And the wiring it rides on: until this change the :8001 factory never passed
`worktree_janitor_fn` at all, so the janitor swept 0 trees on every poll since August.
"""

import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest

import cosa.utils.util as cu
from cosa.agents.shared import worktree_refusal_ledger as ledger


NOW   = datetime( 2026, 9, 14, 18, 0, tzinfo=timezone.utc )
TREE1 = "/repo/.claude/worktrees/seat-cc-author-maria-1"
TREE2 = "/repo/.claude/worktrees/rio-audit"


def _refusal( path, blockers, reason="ignored_files_present" ):
    return { "path": path, "result": { "removed": False, "skipped_reason": reason, "ignored_blockers": blockers } }


class _Notify:
    def __init__( self, outcomes=None, raises=None ):
        self.calls, self.outcomes, self.raises = [], outcomes, raises
    def __call__( self, message, abstract ):
        self.calls.append( ( message, abstract ) )
        if self.raises: raise self.raises
        return self.outcomes if self.outcomes is not None else [
            { "channel": "durable", "outcome": "posted" }, { "channel": "live", "outcome": "queued" } ]


class _Log:
    def __init__( self ): self.events = []
    def __call__( self, event, **fields ): self.events.append( ( event, fields ) )
    def names( self ): return [ e for e, _ in self.events ]


@pytest.fixture
def ledger_path( tmp_path ):
    return str( tmp_path / "io" / "worktree-janitor" / "refused.json" )


# ---------------------------------------------------------------------------
# Condition 2 — the set comparison decides
# ---------------------------------------------------------------------------
def test_an_unchanged_set_sends_nothing_and_writes_nothing( ledger_path ):
    out1   = { "swept": [ _refusal( TREE1, [ "io/results.json" ] ) ], "skipped": [] }
    notify = _Notify()
    ledger.report_refusals( out1, ledger_path, notify, _Log(), now=NOW )
    mtime  = os.stat( ledger_path ).st_mtime_ns

    second = ledger.report_refusals( out1, ledger_path, notify, _Log(), now=NOW )

    assert second[ "changed" ] is False
    assert len( notify.calls ) == 1, "an unchanged refused set sent a second notify"
    assert os.stat( ledger_path ).st_mtime_ns == mtime, "an unchanged set rewrote the ledger"


def test_blocker_order_alone_is_not_a_change( ledger_path ):
    notify = _Notify()
    ledger.report_refusals( { "swept": [ _refusal( TREE1, [ "b", "a" ] ) ] }, ledger_path, notify, _Log(), now=NOW )
    ledger.report_refusals( { "swept": [ _refusal( TREE1, [ "a", "b" ] ) ] }, ledger_path, notify, _Log(), now=NOW )
    assert len( notify.calls ) == 1


def test_a_new_tree_joining_the_set_is_announced( ledger_path ):
    notify = _Notify()
    ledger.report_refusals( { "swept": [ _refusal( TREE1, [ "x" ] ) ] }, ledger_path, notify, _Log(), now=NOW )
    ledger.report_refusals( { "swept": [ _refusal( TREE1, [ "x" ] ), _refusal( TREE2, [ "y" ] ) ] },
                            ledger_path, notify, _Log(), now=NOW )
    assert len( notify.calls ) == 2
    assert "2 worktrees" in notify.calls[ -1 ][ 0 ]


def test_a_set_that_empties_sends_one_all_clear_then_goes_quiet( ledger_path ):
    notify = _Notify()
    ledger.report_refusals( { "swept": [ _refusal( TREE1, [ "x" ] ) ] }, ledger_path, notify, _Log(), now=NOW )
    ledger.report_refusals( { "swept": [ { "path": TREE1, "result": { "removed": True } } ] }, ledger_path, notify, _Log(), now=NOW )
    ledger.report_refusals( { "swept": [], "skipped": [] }, ledger_path, notify, _Log(), now=NOW )
    assert len( notify.calls ) == 2
    assert "no worktrees are being refused" in notify.calls[ 1 ][ 0 ]
    assert json.loads( Path( ledger_path ).read_text() )[ "count" ] == 0


def test_a_refused_tree_that_was_merely_skipped_this_poll_does_not_flap( ledger_path ):
    """A refused tree someone touched is skipped as "active" on the next poll, and is not
    re-judged. Dropping it from the set would announce an all-clear, then re-announce the
    refusal six hours later — noise about nothing."""
    notify = _Notify()
    ledger.report_refusals( { "swept": [ _refusal( TREE1, [ "x" ] ) ] }, ledger_path, notify, _Log(), now=NOW )
    ledger.report_refusals( { "swept": [], "skipped": [ { "path": TREE1, "reason": "active_0.1h" } ] },
                            ledger_path, notify, _Log(), now=NOW )
    assert len( notify.calls ) == 1


def test_no_ledger_and_nothing_refused_is_silence( ledger_path ):
    notify = _Notify()
    out = ledger.report_refusals( { "swept": [], "skipped": [] }, ledger_path, notify, _Log(), now=NOW )
    assert out[ "changed" ] is False and notify.calls == [] and not os.path.exists( ledger_path )


# ---------------------------------------------------------------------------
# Condition 1 — count in the message, each tree and its blockers in the abstract
# ---------------------------------------------------------------------------
def test_the_notice_carries_the_count_and_every_tree_with_its_blockers( ledger_path ):
    notify = _Notify()
    ledger.report_refusals( { "swept": [ _refusal( TREE1, [ "io/results.json", ".claude-memento.md" ] ),
                                         _refusal( TREE2, [], reason="ignored_check_failed" ) ] },
                            ledger_path, notify, _Log(), now=NOW )
    message, abstract = notify.calls[ 0 ]
    assert "2 worktrees" in message
    assert "seat-cc-author-maria-1" in abstract and "`io/results.json`" in abstract and "`.claude-memento.md`" in abstract
    assert "rio-audit" in abstract and "could not list" in abstract
    assert ledger_path in abstract
    recorded = json.loads( Path( ledger_path ).read_text() )
    assert recorded[ "count" ] == 2 and recorded[ "refused" ][ TREE1 ] == [ ".claude-memento.md", "io/results.json" ]


def test_the_spoken_message_stays_short_however_many_trees( ledger_path ):
    notify  = _Notify()
    swept   = [ _refusal( f"/repo/.claude/worktrees/t{i}", [ f"io/f{i}" ] ) for i in range( 60 ) ]
    ledger.report_refusals( { "swept": swept }, ledger_path, notify, _Log(), now=NOW )
    message, abstract = notify.calls[ 0 ]
    assert len( message ) < 200
    assert "35 more trees in the ledger" in abstract


# ---------------------------------------------------------------------------
# Condition 3 — a failed notify is logged, never swallowed
# ---------------------------------------------------------------------------
def test_a_notify_that_raises_is_logged( ledger_path ):
    log = _Log()
    out = ledger.report_refusals( { "swept": [ _refusal( TREE1, [ "x" ] ) ] }, ledger_path,
                                  _Notify( raises=RuntimeError( "gateway down" ) ), log, now=NOW )
    assert out[ "notified" ] is False
    assert ( "worktree_refusal_notify_failed", { "count": 1, "error": "gateway down" } ) in log.events


def test_a_notify_with_a_failed_outcome_is_logged( ledger_path ):
    log = _Log()
    out = ledger.report_refusals( { "swept": [ _refusal( TREE1, [ "x" ] ) ] }, ledger_path,
                                  _Notify( outcomes=[ { "channel": "durable", "outcome": "posted" },
                                                      { "channel": "live", "outcome": "http_error" } ] ),
                                  log, now=NOW )
    assert out[ "notified" ] is False
    assert "worktree_refusal_notify_failed" in log.names()


def test_a_ledger_that_cannot_be_written_is_logged_and_the_operator_still_hears( tmp_path ):
    blocker = tmp_path / "not-a-dir"
    blocker.write_text( "" )
    notify  = _Notify()
    log     = _Log()
    ledger.report_refusals( { "swept": [ _refusal( TREE1, [ "x" ] ) ] }, str( blocker / "refused.json" ), notify, log, now=NOW )
    assert "worktree_refusal_ledger_write_failed" in log.names()
    assert len( notify.calls ) == 1


# ---------------------------------------------------------------------------
# The :8001 wiring — the janitor was never connected here before
# ---------------------------------------------------------------------------
class _FakeStore:
    def __init__( self ): self.sections = {}
    def set_section( self, name, value ): self.sections[ name ] = value


class _FakeGateway:
    def __init__( self ): self.posts = []
    def who( self, retention_hours=24 ): return []
    def send_to( self, recipient, body, metadata=None ): pass
    def post( self, topic, body ): self.posts.append( ( topic, body ) )
    def read( self, topic, since=None, limit=50 ): return []


def test_the_8001_factory_wires_the_janitor_when_enabled( ledger_path ):
    from lupin_arbiter_app.fleet_arbiter_loop import build_fleet_arbiter_job_factory
    job = build_fleet_arbiter_job_factory( _FakeGateway(), _FakeStore(), log_fn=lambda *a, **k: None,
                                           worktree_janitor_enabled=True,
                                           worktree_refusal_ledger_path=ledger_path )()
    assert job._worktree_janitor_fn is not None, "the :8001 job has no janitor — the defect this row found"


def test_the_8001_factory_leaves_it_inert_when_disabled():
    from lupin_arbiter_app.fleet_arbiter_loop import build_fleet_arbiter_job_factory
    job = build_fleet_arbiter_job_factory( _FakeGateway(), _FakeStore(), log_fn=lambda *a, **k: None )()
    assert job._worktree_janitor_fn is None


def test_the_app_reads_the_ini_flag_into_the_factory():
    """The INI keys were only read by the dead in-process bootstrap. Pin that app.py reads them."""
    source = Path( cu.get_project_root(), "src", "lupin_arbiter_app", "app.py" ).read_text()
    assert 'worktree_janitor_enabled   = cfg.get( "arbiter worktree janitor enabled"' in source


def test_the_janitor_reconciles_then_reports_and_the_refusal_reaches_the_gateway( ledger_path ):
    from lupin_arbiter_app.fleet_arbiter_loop import make_worktree_janitor_fn, make_refusal_notify_fn
    gateway = _FakeGateway()
    live    = []
    janitor = make_worktree_janitor_fn(
        sandbox_root=".claude/worktrees", age_hours=6, ledger_path=ledger_path,
        notify_fn=make_refusal_notify_fn( gateway, live_notify_fn=lambda m, abstract=None: live.append( ( m, abstract ) ) or { "channel": "live", "outcome": "queued" } ),
        log_fn=lambda *a, **k: None,
        reconcile_fn=lambda **kw: { "swept": [ _refusal( TREE1, [ "io/results.json" ] ) ], "skipped": [], "errors": [] } )

    result = janitor()

    assert result[ "refusals" ][ "changed" ] is True and result[ "refusals" ][ "notified" ] is True
    assert "io/results.json" in gateway.posts[ 0 ][ 1 ], "the durable post lost the per-tree detail"
    assert live[ 0 ][ 1 ] is not None and "io/results.json" in live[ 0 ][ 1 ], "the live push lost the abstract"


def test_a_reporting_failure_never_discards_the_reconcile_result():
    from lupin_arbiter_app.fleet_arbiter_loop import make_worktree_janitor_fn
    events  = []
    def boom( *a, **kw ): raise RuntimeError( "ledger module broke" )
    janitor = make_worktree_janitor_fn(
        sandbox_root=".claude/worktrees", age_hours=6, ledger_path="/nowhere", notify_fn=lambda m, a: [],
        log_fn=lambda e, **f: events.append( e ), reconcile_fn=lambda **kw: { "swept": [ "x" ], "skipped": [], "errors": [] },
        report_fn=boom )
    assert janitor()[ "swept" ] == [ "x" ]
    assert "worktree_refusal_report_error" in events


# ---------------------------------------------------------------------------
# The live push carries the abstract, and nobody else's URL changes
# ---------------------------------------------------------------------------
def test_the_notify_request_carries_an_abstract_only_when_given():
    from lupin_arbiter_app.arbiter_live_notify import build_notify_request
    kw = dict( base_url="http://h:7999", target_user="r@e.com", sender_id="s", api_key="k" )
    plain, _    = build_notify_request( "hi", **kw )
    detailed, _ = build_notify_request( "hi", abstract="| a | b |", **kw )
    assert "abstract=" not in plain
    assert "abstract=%7C+a+%7C+b+%7C" in detailed


def test_a_message_only_transport_still_works_through_the_dedup_wrapper():
    from lupin_arbiter_app.arbiter_live_notify import make_live_notify_fn
    seen = []
    live = make_live_notify_fn( lambda message: seen.append( message ) or { "channel": "live", "outcome": "queued" },
                                log_fn=lambda *a, **k: None )
    assert live( "hello" )[ "outcome" ] == "queued" and seen == [ "hello" ]


# ---------------------------------------------------------------------------
# The disk hygiene report prints the count
# ---------------------------------------------------------------------------
@pytest.fixture
def report_root( tmp_path ):
    root = tmp_path / "projects" / "lupin"
    root.mkdir( parents=True )
    for args in ( [ "init", "-q", "-b", "main" ], [ "config", "user.email", "g@e.com" ], [ "config", "user.name", "g" ] ):
        subprocess.run( [ "git", "-C", str( root ), *args ], check=True )
    ( root / "seed.txt" ).write_text( "seed\n" )
    subprocess.run( [ "git", "-C", str( root ), "add", "-A" ], check=True )
    subprocess.run( [ "git", "-C", str( root ), "commit", "-q", "-m", "seed" ], check=True )
    return root


def _report( root ):
    script = cu.get_project_root() + "/src/scripts/disk-hygiene-report.sh"
    return subprocess.run( [ "bash", script ], capture_output=True, text=True,
                           env=dict( os.environ, LUPIN_ROOT=str( root ) ), timeout=600 )


def test_the_disk_report_says_zero_when_nothing_was_ever_refused( report_root ):
    done = _report( report_root )
    assert done.returncode == 0, done.stderr
    assert "janitor refused: 0" in done.stdout
    assert "⚠ janitor is refusing" not in done.stdout


def test_the_disk_report_prints_and_flags_the_refused_count( report_root ):
    ledger.write_ledger( str( report_root / "io" / "worktree-janitor" / "refused.json" ),
                         { TREE1: [ "x" ], TREE2: [ "y" ] }, NOW )
    done = _report( report_root )
    assert done.returncode == 0, done.stderr
    assert "janitor refused: 2" in done.stdout
    assert "⚠ janitor is refusing 2 worktree(s)" in done.stdout
