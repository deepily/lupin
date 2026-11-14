"""
The daily test promotion, with the VM and the store faked.

Every wrapper call goes through one recording runner, so a test reads the exact calls a run made and in what
order. The git repository is a real one in a temporary folder, because the temporary branch the deploy takes
is the thing to prove deleted.
"""
import datetime
import fcntl
import json
import os
import pathlib
import subprocess
import sys

import pytest

_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

from lupin_mcp import daily_test_promotion as dtp
from lupin_mcp import duplicate_check_filing as filing
from lupin_mcp import job_run
from lupin_mcp import job_summary as js

UTC      = datetime.timezone.utc
NOW      = datetime.datetime( 2026, 11, 14, 23, 0, tzinfo=UTC )          # 18:00 in New York
GIT_ENV  = { "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com" }


def _git( folder, *args ):
    """Run git in folder and return the stripped stdout."""
    return subprocess.run( [ "git", *args ], cwd=folder, check=True, capture_output=True, text=True, env={ **os.environ, **GIT_ENV } ).stdout.strip()


class Repo( type( pathlib.Path() ) ):
    """A checkout path that carries two shas."""


@pytest.fixture
def repo( tmp_path ):
    """A checkout on branch wip-x with two commits: old is the first, new the second."""
    folder = Repo( tmp_path / "checkout" )
    folder.mkdir()
    _git( folder, "init", "-q", "-b", "wip-x" )
    ( folder / "a.txt" ).write_text( "one" )
    _git( folder, "add", "a.txt" )
    _git( folder, "commit", "-q", "-m", "one" )
    old = _git( folder, "rev-parse", "HEAD" )
    ( folder / "a.txt" ).write_text( "two" )
    _git( folder, "commit", "-q", "-am", "two" )
    new = _git( folder, "rev-parse", "HEAD" )
    folder.old, folder.new = old, new
    return folder


class Runner:
    """Records each wrapper call and answers from a script of replies."""

    def __init__( self, **replies ):
        self.calls   = []
        self.refs    = []                    # the branch each deploy was asked for, in order
        self.replies = { key: ( list( value ) if isinstance( value, list ) else [ value ] ) for key, value in replies.items() }

    def __call__( self, argv, timeout ):
        key = " ".join( argv[ 1:3 ] ) if argv[ 1 ] in ( "test-server", "preflight" ) else argv[ 1 ]
        self.calls.append( key )
        if key == "deploy": self.refs.append( argv[ 2 ] )
        queue = self.replies.get( key, [ ( 0, "" ) ] )
        return queue.pop( 0 ) if len( queue ) > 1 else queue[ 0 ]


class Store:
    """The filer's store in memory: it keeps rows by correlation key."""

    def __init__( self, probe_ok=True ):
        self.rows, self.probe_ok = {}, probe_ok

    def query( self, key ):
        return self.probe_ok, 200, { "count": 1 if key in self.rows else 0 }

    def create( self, payload ):
        self.rows[ payload[ "correlation_key" ] ] = payload
        return True, 201, { }


def vm_of( runner, root="/r" ):
    return dtp.Vm( root, runner )


# ── the wrapper ──────────────────────────────────────────────────────────

def test_run_command_returns_the_code_and_stdout():
    assert dtp.run_command( [ "sh", "-c", "echo hi; exit 3" ], 5 ) == ( 3, "hi\n" )


def test_run_command_turns_a_missing_program_and_a_timeout_into_127():
    code, text = dtp.run_command( [ "/no/such/program" ], 5 )
    assert code == 127 and "FileNotFoundError" in text
    code, text = dtp.run_command( [ "sleep", "5" ], 0.1 )
    assert code == 127 and "TimeoutExpired" in text


def test_the_power_state_is_the_last_word_upper_cased():
    assert vm_of( Runner( **{ "vm-status": ( 0, "[lupin-vm] x\nsuspended\n" ) } ) ).power() == "SUSPENDED"
    assert vm_of( Runner( **{ "vm-status": ( 1, "RUNNING" ) } ) ).power() is None
    assert vm_of( Runner( **{ "vm-status": ( 0, "" ) } ) ).power() is None


def test_start_and_restore_make_the_calls_each_state_needs():
    runner = Runner()
    vm     = vm_of( runner )
    assert vm.start() is True
    assert [ vm.restore( word ) for word in ( "SUSPENDED", "SUSPENDING", "STOPPED", "TERMINATED", "RUNNING", None ) ] == [ True ] * 6
    assert runner.calls == [ "vm-start", "vm-suspend", "vm-suspend", "vm-stop", "vm-stop" ]
    assert vm_of( Runner( **{ "vm-start": ( 1, "" ) } ) ).start() is False
    assert vm_of( Runner( **{ "vm-suspend": ( 1, "" ) } ) ).restore( "SUSPENDED" ) is False


def test_the_deployed_sha_is_the_first_field_of_the_stamp():
    assert vm_of( Runner( run=( 0, "abc123 2026-11-14T00:00:00Z push-bundle-reset\n" ) ) ).deployed_sha() == "abc123"
    assert vm_of( Runner( run=( 1, "abc123" ) ) ).deployed_sha() is None
    assert vm_of( Runner( run=( 0, "" ) ) ).deployed_sha() is None


def test_smoke_names_the_first_check_that_failed():
    assert vm_of( Runner() ).smoke() is None
    assert vm_of( Runner( **{ "test-server idle": ( 1, "" ) } ) ).smoke() is None, "busy still means the server answers"
    assert vm_of( Runner( **{ "preflight post": ( 1, "" ) } ) ).smoke() == "post preflight"
    assert vm_of( Runner( **{ "test-server idle": ( 2, "" ) } ) ).smoke() == "test server idle read"
    assert vm_of( Runner() ).idle() == 0 and vm_of( Runner() ).deploy( "b" ) is True
    assert vm_of( Runner( deploy=( 4, "" ) ) ).deploy( "b" ) is False


# ── time ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize( "now,expected", [
    ( datetime.datetime( 2026, 11, 14, 22, 59, tzinfo=UTC ), "2026-11-13T18:00:00-05:00" ),     # 17:59 in New York: yesterday's slot
    ( datetime.datetime( 2026, 11, 14, 23, 0, tzinfo=UTC ),  "2026-11-14T18:00:00-05:00" ),     # exactly 18:00
    ( datetime.datetime( 2026, 11, 15, 14, 0, tzinfo=UTC ),  "2026-11-14T18:00:00-05:00" ),     # morning after
    ( datetime.datetime( 2026, 3, 9, 14, 0, tzinfo=UTC ),    "2026-03-08T18:00:00-04:00" ),     # the day after spring forward: the slot is on summer time
    ( datetime.datetime( 2026, 11, 1, 13, 0, tzinfo=UTC ),   "2026-10-31T18:00:00-04:00" ),     # the morning of fall back: the slot is the evening before, summer time
], ids=[ "before", "exact", "morning", "spring-forward", "fall-back" ] )
def test_the_latest_slot_is_the_last_18_00_new_york_time_across_daylight_saving( now, expected ):
    assert dtp.latest_slot( now ).isoformat() == expected


def test_a_cron_or_hand_entry_is_always_due_and_a_boot_only_when_no_attempt_follows_the_slot():
    state = { "last_attempt_at": "2026-11-14T18:00:05-05:00" }
    assert dtp.due( "cron", state, NOW ) and dtp.due( "hand", state, NOW )
    assert dtp.due( "boot", { }, NOW ) is True
    assert dtp.due( "boot", state, NOW ) is False                                        # 18:00:05 is after the 18:00 slot
    assert dtp.due( "boot", { "last_attempt_at": "2026-11-13T18:00:05-05:00" }, NOW ) is True
    morning = datetime.datetime( 2026, 11, 15, 14, 0, tzinfo=UTC )                       # the host was off at 18:00 and boots next morning
    assert dtp.due( "boot", { "last_attempt_at": "2026-11-13T18:00:05-05:00" }, morning ) is True


# ── state and the stretch behind ─────────────────────────────────────────

def test_read_state_answers_a_dict_for_every_kind_of_file( tmp_path ):
    path = tmp_path / "state.json"
    assert dtp.read_state( path ) == { }
    path.write_text( "{" )
    assert dtp.read_state( path ) == { }
    path.write_text( "[1]" )
    assert dtp.read_state( path ) == { }
    path.write_text( '{"a": 1}' )
    assert dtp.read_state( path ) == { "a": 1 }


def test_the_stretch_behind_starts_once_and_clears_on_success():
    state = { }
    dtp.behind_state( state, NOW, True )
    first = state[ "behind_since" ]
    dtp.behind_state( state, NOW + datetime.timedelta( days=1 ), True )
    assert state[ "behind_since" ] == first
    state[ "stale_filed_for" ] = first
    dtp.behind_state( state, NOW, False )
    assert state == { }


def test_stale_is_due_after_three_days_and_only_once_per_stretch():
    since = "2026-11-10T18:00:00-05:00"
    assert dtp.stale_due( { }, NOW ) is None
    assert dtp.stale_due( { "behind_since": since }, datetime.datetime( 2026, 11, 13, 22, 59, tzinfo=UTC ) ) is None
    assert dtp.stale_due( { "behind_since": since }, datetime.datetime( 2026, 11, 13, 23, 0, tzinfo=UTC ) ) == since
    assert dtp.stale_due( { "behind_since": since, "stale_filed_for": since }, NOW ) is None


def test_a_row_names_its_kind_and_sha_in_its_key_and_is_filed_by_the_job():
    row = dtp.row_payload( "failed", "a" * 40, "why", "mr radio" )
    assert row[ "correlation_key" ] == "epic:daily-test-promotion-failed-" + "a" * 12
    assert row[ "owner_persona" ] == row[ "accountable_manager" ] == "mr radio" and row[ "created_by" ].endswith( "(test-promotion)" )
    assert "URGENT" in dtp.row_payload( "rollback-failed", "b" * 40, "x", "mr radio" )[ "title" ]
    assert dtp.row_payload( "stale", "c" * 40, "x", "m", "2026-11-10" )[ "correlation_key" ].endswith( "stale-2026-11-10" )


# ── git: the pick and the temporary branch ───────────────────────────────

def test_the_pick_is_the_tip_of_the_newest_working_branch( repo ):
    assert dtp.pick_sha( str( repo ), "auto" ) == ( "wip-x", repo.new )
    assert dtp.pick_sha( str( repo ), "wip-x" ) == ( "wip-x", repo.new )


def test_the_temporary_branch_exists_during_the_action_and_is_gone_after_it_returns_or_raises( repo ):
    seen = []

    def action( name ):
        seen.append( ( name, _git( repo, "rev-parse", f"refs/heads/{name}" ) ) )
        return "done"

    assert dtp.with_ref( str( repo ), repo.new, action ) == "done"
    assert seen == [ ( f"promote/test-{repo.new[ :12 ]}", repo.new ) ]
    assert _git( repo, "for-each-ref", "refs/heads/promote" ) == ""

    def boom( name ): raise KeyError( name )

    with pytest.raises( KeyError ):
        dtp.with_ref( str( repo ), repo.old, boom )
    assert _git( repo, "for-each-ref", "refs/heads/promote" ) == ""


def test_this_checkout_holds_a_commit_it_has_and_not_one_it_lacks( repo ):
    assert dtp.holds_commit( str( repo ), repo.old ) is True
    assert dtp.holds_commit( str( repo ), "f" * 40 ) is False


# ── promote ──────────────────────────────────────────────────────────────

def test_a_clean_deploy_and_smoke_promotes( repo ):
    runner = Runner()
    assert dtp.promote( str( repo ), vm_of( runner ), repo.new, repo.old )[ 0 ] == dtp.PROMOTED
    assert runner.calls == [ "deploy", "preflight post", "test-server idle" ]
    assert _git( repo, "for-each-ref", "refs/heads/promote" ) == ""


def test_a_failed_deploy_rolls_back_to_the_sha_the_vm_ran_before( repo ):
    runner = Runner( deploy=[ ( 5, "" ), ( 0, "" ) ] )
    result, stage, detail = dtp.promote( str( repo ), vm_of( runner ), repo.new, repo.old )
    assert ( result, stage ) == ( dtp.ROLLED_BACK, "deploy" ) and repo.old[ :12 ] in detail
    assert runner.calls == [ "deploy", "deploy", "preflight post", "test-server idle" ]
    assert runner.refs == [ f"promote/test-{repo.new[ :12 ]}", f"promote/test-{repo.old[ :12 ]}" ], "the second deploy is the rollback, to the sha the VM ran before"


def test_a_failed_smoke_rolls_back_and_a_failed_rollback_says_so( repo ):
    runner = Runner( **{ "preflight post": [ ( 1, "" ), ( 0, "" ) ] } )
    assert dtp.promote( str( repo ), vm_of( runner ), repo.new, repo.old )[ :2 ] == ( dtp.ROLLED_BACK, "post preflight" )
    runner = Runner( **{ "preflight post": ( 1, "" ) } )
    result, stage, detail = dtp.promote( str( repo ), vm_of( runner ), repo.new, repo.old )
    assert ( result, stage ) == ( dtp.ROLLBACK_FAIL, "post preflight" ) and "also failed at post preflight" in detail
    assert _git( repo, "for-each-ref", "refs/heads/promote" ) == ""


def test_no_rollback_is_possible_without_a_known_previous_sha_or_one_this_checkout_holds( repo ):
    for previous in ( None, "f" * 40 ):
        runner = Runner( deploy=( 5, "" ) )
        result, stage, detail = dtp.promote( str( repo ), vm_of( runner ), repo.new, previous )
        assert ( result, stage ) == ( dtp.ROLLBACK_FAIL, "deploy" ) and "no rollback was possible" in detail
        assert runner.calls == [ "deploy" ]


# ── decide: the order of the calls ───────────────────────────────────────

def test_a_stored_sha_settles_the_run_with_no_call_to_the_vm( repo ):
    runner = Runner()
    assert dtp.decide( str( repo ), vm_of( runner ), repo.new, { "last_promoted_sha": repo.new } )[ 0 ] == dtp.UP_TO_DATE
    assert runner.calls == []


def test_an_unreadable_power_state_ends_the_run_before_anything_is_started( repo ):
    runner = Runner( **{ "vm-status": ( 1, "" ) } )
    assert dtp.decide( str( repo ), vm_of( runner ), repo.new, { } )[ :2 ] == ( dtp.VM_FAILED, "vm-status" )
    assert runner.calls == [ "vm-status" ]


def test_a_vm_that_cannot_be_started_is_put_back_and_reported( repo ):
    runner = Runner( **{ "vm-status": ( 0, "SUSPENDED" ), "vm-start": ( 1, "" ) } )
    assert dtp.decide( str( repo ), vm_of( runner ), repo.new, { } )[ :2 ] == ( dtp.VM_FAILED, "vm-start" )
    assert runner.calls == [ "vm-status", "vm-start", "vm-suspend" ]


def test_a_vm_already_on_the_pick_is_up_to_date_and_its_sha_is_stored( repo ):
    runner = Runner( **{ "vm-status": ( 0, "RUNNING" ), "run": ( 0, repo.new + " stamp" ) } )
    state  = { }
    assert dtp.decide( str( repo ), vm_of( runner ), repo.new, state )[ 0 ] == dtp.UP_TO_DATE
    assert state == { "last_promoted_sha": repo.new} and runner.calls == [ "vm-status", "run" ]


def test_a_sha_that_cannot_be_read_from_the_vm_is_a_failure_and_the_vm_is_put_back( repo ):
    runner = Runner( **{ "vm-status": ( 0, "SUSPENDED" ), "run": ( 1, "" ) } )
    assert dtp.decide( str( repo ), vm_of( runner ), repo.new, { } )[ :2 ] == ( dtp.VM_FAILED, "vm-sha" )
    assert runner.calls == [ "vm-status", "vm-start", "run", "vm-suspend" ]


@pytest.mark.parametrize( "idle", [ 1, 2 ] )
def test_a_busy_or_unknown_test_server_defers_the_run_without_a_deploy( repo, idle ):
    runner = Runner( **{ "vm-status": ( 0, "RUNNING" ), "run": ( 0, repo.old ), "test-server idle": ( idle, "" ) } )
    assert dtp.decide( str( repo ), vm_of( runner ), repo.new, { } )[ :2 ] == ( dtp.DEFERRED, "venue" )
    assert "deploy" not in runner.calls


def test_a_full_promotion_from_a_suspended_vm_makes_these_calls_in_this_order( repo ):
    runner = Runner( **{ "vm-status": ( 0, "SUSPENDED" ), "run": ( 0, repo.old ) } )
    state  = { }
    assert dtp.decide( str( repo ), vm_of( runner ), repo.new, state )[ 0 ] == dtp.PROMOTED
    assert runner.calls == [ "vm-status", "vm-start", "run", "test-server idle", "deploy", "preflight post", "test-server idle", "vm-suspend" ]
    assert state[ "last_promoted_sha" ] == repo.new


def test_a_failed_promotion_does_not_store_the_sha( repo ):
    runner = Runner( **{ "vm-status": ( 0, "RUNNING" ), "run": ( 0, repo.old ), "deploy": [ ( 5, "" ), ( 0, "" ) ] } )
    state  = { }
    assert dtp.decide( str( repo ), vm_of( runner ), repo.new, state )[ 0 ] == dtp.ROLLED_BACK
    assert "last_promoted_sha" not in state


def test_no_call_carries_a_credential_word( repo ):
    class Spy( Runner ):
        def __call__( self, argv, timeout ):
            self.argv = getattr( self, "argv", [] ) + [ argv ]
            return super().__call__( argv, timeout )

    runner = Spy( **{ "vm-status": ( 0, "SUSPENDED" ), "run": ( 0, repo.old ) } )
    dtp.decide( str( repo ), vm_of( runner ), repo.new, { } )
    words = " ".join( " ".join( argv ) for argv in runner.argv ).lower()
    assert runner.argv and not any( bad in words for bad in ( "password", "token", "secret", "authorization", "curl", "api-key", "apikey" ) )


# ── run: records, rows, lock, check ──────────────────────────────────────

def _run( repo, runner, store, now=NOW, trigger="cron", check=False ):
    return dtp.run( str( repo ), now, trigger, "auto", vm_of( runner, repo ), store, "mr radio", check )


def _folder( repo ):
    return pathlib.Path( repo ) / "io" / "jobs" / "test-promotion"


def test_a_promotion_writes_a_clean_record_and_state_and_files_nothing( repo ):
    store = Store()
    code  = _run( repo, Runner( **{ "vm-status": ( 0, "RUNNING" ), "run": ( 0, repo.old ) } ), store )
    record, state = js.read_summary( _folder( repo ) / "job-summary.json" ), dtp.read_state( _folder( repo ) / "state.json" )
    assert code == 0 and store.rows == { }
    assert record[ "last_attempt" ][ "outcome" ] == "clean" and record[ "last_attempt" ][ "mode" ] == dtp.PROMOTED
    assert state[ "last_promoted_sha" ] == repo.new and state[ "last_result" ] == dtp.PROMOTED and "behind_since" not in state


def test_a_second_run_on_the_same_sha_is_up_to_date_with_no_vm_call( repo ):
    _run( repo, Runner( **{ "vm-status": ( 0, "RUNNING" ), "run": ( 0, repo.old ) } ), Store() )
    runner = Runner()
    assert _run( repo, runner, Store() ) == 0 and runner.calls == []
    assert js.read_summary( _folder( repo ) / "job-summary.json" )[ "last_attempt" ][ "mode" ] == dtp.UP_TO_DATE


def test_a_rolled_back_promotion_files_exactly_one_row_even_when_it_repeats( repo ):
    store  = Store()
    script = { "vm-status": ( 0, "RUNNING" ), "run": ( 0, repo.old ), "deploy": [ ( 5, "" ), ( 0, "" ), ( 5, "" ), ( 0, "" ) ] }
    assert _run( repo, Runner( **script ), store ) == 1
    assert list( store.rows ) == [ "epic:daily-test-promotion-failed-" + repo.new[ :12 ] ]
    assert _run( repo, Runner( **script ), store ) == 1
    assert len( store.rows ) == 1, "the same fault on the next day is the same row"
    record = js.read_summary( _folder( repo ) / "job-summary.json" )[ "last_attempt" ]
    assert record[ "outcome" ] == "failed" and record[ "stage" ] == "deploy" and "row already_filed" in record[ "evidence" ]


def test_a_failed_rollback_files_the_urgent_row_and_an_unreachable_vm_its_own( repo ):
    store = Store()
    assert _run( repo, Runner( **{ "vm-status": ( 0, "RUNNING" ), "run": ( 0, repo.old ), "deploy": ( 5, "" ) } ), store ) == 1
    assert list( store.rows ) == [ "epic:daily-test-promotion-rollback-failed-" + repo.new[ :12 ] ]
    store = Store()
    assert _run( repo, Runner( **{ "vm-status": ( 1, "" ) } ), store ) == 1
    assert list( store.rows ) == [ "epic:daily-test-promotion-vm-unreachable-" + repo.new[ :12 ] ]


def test_a_row_the_store_cannot_take_is_named_in_the_record( repo ):
    assert _run( repo, Runner( **{ "vm-status": ( 1, "" ) } ), Store( probe_ok=False ) ) == 1
    assert "row queued_for_retry" in js.read_summary( _folder( repo ) / "job-summary.json" )[ "last_attempt" ][ "evidence" ]


def test_deferrals_for_three_days_file_one_stale_row_and_never_a_second_in_the_same_stretch( repo ):
    store  = Store()
    script = { "vm-status": ( 0, "RUNNING" ), "run": ( 0, repo.old ), "test-server idle": ( 1, "" ) }
    days   = [ NOW + datetime.timedelta( days=n ) for n in range( 5 ) ]
    codes  = [ _run( repo, Runner( **script ), store, now=day ) for day in days ]
    assert codes == [ 0 ] * 5, "a deferral is not a failure"
    stale  = [ key for key in store.rows if "-stale-" in key ]
    assert stale == [ "epic:daily-test-promotion-stale-2026-11-14" ], "one row, named for the day the stretch began"
    state = dtp.read_state( _folder( repo ) / "state.json" )
    assert state[ "stale_filed_for" ] == state[ "behind_since" ]
    assert js.read_summary( _folder( repo ) / "job-summary.json" )[ "last_attempt" ][ "outcome" ] == "carried"


def test_a_promotion_after_a_stretch_behind_clears_the_stretch( repo ):
    store = Store()
    _run( repo, Runner( **{ "vm-status": ( 0, "RUNNING" ), "run": ( 0, repo.old ), "test-server idle": ( 1, "" ) } ), store )
    assert "behind_since" in dtp.read_state( _folder( repo ) / "state.json" )
    _run( repo, Runner( **{ "vm-status": ( 0, "RUNNING" ), "run": ( 0, repo.old ) } ), store, now=NOW + datetime.timedelta( days=1 ) )
    assert "behind_since" not in dtp.read_state( _folder( repo ) / "state.json" )


def test_a_boot_after_the_slot_was_served_writes_nothing_and_a_boot_after_a_missed_slot_runs( repo ):
    first = Runner( **{ "vm-status": ( 0, "RUNNING" ), "run": ( 0, repo.old ) } )
    _run( repo, first, Store(), now=NOW + datetime.timedelta( seconds=5 ) )
    before = ( _folder( repo ) / "job-summary.json" ).read_text()
    runner = Runner()
    assert _run( repo, runner, Store(), now=NOW + datetime.timedelta( hours=3 ), trigger="boot" ) == 0
    assert runner.calls == [] and ( _folder( repo ) / "job-summary.json" ).read_text() == before
    next_morning = NOW + datetime.timedelta( hours=15 )
    ran = Runner( **{ "vm-status": ( 0, "RUNNING" ), "run": ( 0, repo.new ) } )
    assert _run( repo, ran, Store(), now=next_morning + datetime.timedelta( days=1 ), trigger="boot" ) == 0
    assert js.read_summary( _folder( repo ) / "job-summary.json" )[ "last_attempt" ][ "trigger" ] == "boot"


def test_a_second_run_that_finds_the_lock_held_exits_without_touching_the_vm( repo ):
    _folder( repo ).mkdir( parents=True )
    with open( _folder( repo ) / "run.lock", "w" ) as held:
        fcntl.flock( held, fcntl.LOCK_EX )
        runner = Runner()
        assert _run( repo, runner, Store() ) == 0 and runner.calls == []
    assert not ( _folder( repo ) / "job-summary.json" ).exists()


def test_check_changes_nothing_and_does_not_touch_the_vm( repo, capsys ):
    runner = Runner()
    assert _run( repo, runner, None, check=True ) == 0
    out = capsys.readouterr().out
    assert runner.calls == [] and repo.new[ :12 ] in out and "the VM is not contacted" in out and "due for cron" in out
    assert not ( _folder( repo ) / "state.json" ).exists() and not ( _folder( repo ) / "job-summary.json" ).exists()


def test_check_says_not_due_for_a_boot_whose_slot_was_served( repo, capsys ):
    _folder( repo ).mkdir( parents=True )
    ( _folder( repo ) / "state.json" ).write_text( json.dumps( { "last_attempt_at": "2026-11-14T18:00:05-05:00" } ) )
    _run( repo, Runner(), None, trigger="boot", check=True )
    assert "not due for boot" in capsys.readouterr().out


# ── main and the registry ────────────────────────────────────────────────

def test_main_builds_the_vm_and_the_live_store_and_maps_reboot_to_boot( repo, monkeypatch ):
    built = []

    class FakeLive( Store ):
        def __init__( self ):
            super().__init__()
            built.append( self )

    monkeypatch.setattr( filing, "LiveStore", FakeLive )
    runner = Runner( **{ "vm-status": ( 0, "RUNNING" ), "run": ( 0, repo.new ) } )
    assert dtp.main( [ "--trigger", "reboot", "--owner", "someone" ], environ={ "LUPIN_ROOT": str( repo ) }, runner=runner, now=NOW ) == 0
    assert len( built ) == 1 and runner.calls == [ "vm-status", "run" ]
    assert js.read_summary( _folder( repo ) / "job-summary.json" )[ "last_attempt" ][ "trigger" ] == "boot"


def test_main_with_check_builds_no_store_and_takes_the_root_from_the_project_when_the_environment_has_none( repo, monkeypatch, capsys ):
    monkeypatch.setattr( dtp.cu, "get_project_root", lambda: str( repo ) )
    assert dtp.main( [ "--check" ], environ={ }, runner=Runner() ) == 0
    assert "test-promotion --check" in capsys.readouterr().out


def test_the_registry_entry_runs_this_module_through_job_run_with_its_switch_off_and_its_trigger_flag_set():
    root  = pathlib.Path( os.environ.get( "LUPIN_ROOT", os.getcwd() ) )
    entry = next( job for job in json.loads( ( root / "src/conf/job-registry.json" ).read_text() )[ "jobs" ] if job[ "job" ] == "test-promotion" )
    assert entry[ "enabled_key" ] == "cron job test-promotion enabled" and entry[ "cron_managed" ] is True and entry[ "own_summary" ] is True
    assert entry[ "summary_path" ] == "{root}/io/jobs/test-promotion/job-summary.json" and entry[ "fix_debt_key" ] == "prefix:" + dtp.KEY_PREFIX
    assert entry[ "schedule" ] == [ { "cron": "0 18 * * *" }, { "after_boot_seconds": 600 } ]
    assert entry[ "run" ][ "argv" ][ 1:3 ] == [ "-m", "lupin_mcp.daily_test_promotion" ]
    assert job_run.with_trigger( entry[ "run" ][ "argv" ], "boot" )[ -1 ] == "reboot"
    ini = ( root / "src/conf" / ( "lupin-app" + ".ini" ) ).read_text()
    assert ini.count( "cron job test-promotion enabled           = false\n" ) == 1, "the switch ships off"
