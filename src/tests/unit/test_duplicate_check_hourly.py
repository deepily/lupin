"""The hourly duplicate check: branch, usage, rate limit, back-off, the slot and the alerts."""
import asyncio
import datetime
import json

import pytest

from cosa.repo.doc_lint import model_transport as mt
from lupin_mcp import duplicate_check_daily as dd
from lupin_mcp import duplicate_check_history as hist
from tests.unit.test_duplicate_check_daily import NOW, commit, git, history, parts_of, repo   # noqa: F401  (repo is a fixture)
from tests.unit.test_duplicate_check_score_run import FakeBackend
from tests.unit.test_librarian_tick import cron   # noqa: F401  (fixture: the fake crontab and the fake lock)


class LimitedBackend( FakeBackend ):
    """A backend whose service refuses every call for its rate limit."""

    async def complete( self, model, system_prompt, user_prompt ):
        self.calls += 1
        raise mt.ModelRateLimited( "usage limit reached" )


class Meter:
    """A usage tally that grows by 10 calls' worth of tokens every time it is read after a call."""

    def __init__( self ): self.reads = 0

    def __call__( self ):
        self.reads += 1
        return { "calls": self.reads * 3, "input_tokens": self.reads * 5, "output_tokens": self.reads * 7, "cache_creation_input_tokens": self.reads * 100,
                 "cache_read_input_tokens": self.reads * 11, "cost_usd": self.reads * 0.12345 }


class Hooks:
    """Notifier stand-ins that remember what they were sent."""

    def __init__( self ): self.sent = []

    def hook( self, name ): return lambda spoken, abstract: self.sent.append( ( name, spoken, abstract ) ) or True


def test_a_rate_limited_call_is_counted_and_every_later_call_is_refused_without_reaching_the_service():
    inner = LimitedBackend()
    count = dd.Counting( inner )
    with pytest.raises( mt.ModelRateLimited, match="usage limit" ): asyncio.run( count.complete( "m", "s", "u" ) )
    with pytest.raises( mt.ModelRateLimited, match="no further call" ): asyncio.run( count.complete( "m", "s", "u" ) )
    assert ( count.calls, count.limited, inner.calls ) == ( 1, 1, 1 )


def test_branch_auto_names_the_newest_wip_branch_by_tip_time_and_otherwise_main( repo ):
    commit( repo, { "a.py": "x = 1\n" }, "base", 48 )
    assert dd.resolve_branch( repo, "auto" ) == "main", "no wip branch exists"
    git( repo, "branch", "wip-old" )
    git( repo, "checkout", "-q", "-b", "wip-new" )
    commit( repo, { "b.py": "y = 2\n" }, "newer", 1 )
    git( repo, "checkout", "-q", "-b", "other-newest" )
    commit( repo, { "c.py": "z = 3\n" }, "newest of all", 0 )
    assert dd.resolve_branch( repo, "auto" ) == "wip-new", "a branch outside wip-* is never chosen, however new"
    assert dd.resolve_branch( repo, "wip-old" ) == "wip-old" and dd.resolve_branch( repo, "main" ) == "main", "a named branch is kept as given"


def test_the_usage_since_is_the_difference_with_the_cost_rounded():
    before = { "calls": 1, "input_tokens": 10, "cost_usd": 0.1 }
    assert dd.usage_since( before, { "calls": 4, "input_tokens": 25, "cost_usd": 0.3500004 } ) == { "calls": 3, "input_tokens": 15, "cost_usd": 0.25 }


def line( status="ok", at="2026-11-07T12:00:00-05:00", until=None, **over ):
    """Ensures: returns a history line of the daily mode."""
    return { **hist.line_of( { "status": status, "trigger": "cron", "started_at": at, "carried": [], "backoff_until": until, **over }, "x.json" ) }


def test_the_back_off_holds_while_the_newest_unskipped_run_names_a_later_time( tmp_path ):
    now = datetime.datetime.fromisoformat( "2026-11-07T12:30:00-05:00" )
    assert dd.backoff_until( tmp_path, now ) is None, "no history"
    hist.append_line( tmp_path, line( until="2026-11-07T13:30:00-05:00" ) )
    assert dd.backoff_until( tmp_path, now ) == "2026-11-07T13:30:00-05:00"
    hist.append_line( tmp_path, line( status="skipped", at="2026-11-07T12:20:00-05:00" ) )
    assert dd.backoff_until( tmp_path, now ) == "2026-11-07T13:30:00-05:00", "a skipped run in between does not end the back-off"
    assert dd.backoff_until( tmp_path, now + datetime.timedelta( hours=2 ) ) is None, "past its time it no longer holds"
    hist.append_line( tmp_path, line( at="2026-11-07T12:25:00-05:00" ) )
    assert dd.backoff_until( tmp_path, now ) is None, "a later run with no limit clears it"


def test_a_run_records_the_branch_what_was_owed_and_the_tokens_the_calls_used( repo, tmp_path ):
    history( repo )
    meter = Meter()
    doc   = dd.run( repo, NOW, "hand", 10, "/bin/claude", parts_of( tmp_path, usage=meter ), branch="main" )
    assert ( doc[ "branch" ], doc[ "owed" ], doc[ "rate_limited" ], doc[ "backoff_until" ] ) == ( "main", 3, 0, None )
    assert doc[ "usage" ] == { "calls": 3, "input_tokens": 5, "output_tokens": 7, "cache_creation_input_tokens": 100, "cache_read_input_tokens": 11, "cost_usd": 0.1235 }
    row = hist.read_lines( tmp_path / "io" / "duplicate-check-daily" )[ 0 ]
    assert ( row[ "branch" ], row[ "owed" ], row[ "cache_creation_tokens" ], row[ "cache_read_tokens" ], row[ "usage_calls" ] ) == ( "main", 3, 100, 11, 3 )


def test_a_rate_limit_carries_the_work_records_the_limit_and_skips_the_next_slot_then_resumes( repo, tmp_path ):
    history( repo )
    limited = parts_of( tmp_path, backend=LimitedBackend() )
    doc     = dd.run( repo, NOW, "cron", 10, "/bin/claude", limited )
    assert doc[ "status" ] == "carried" and doc[ "rate_limited" ] >= 1 and len( doc[ "carried" ] ) == 3 and doc[ "judged" ] == 0
    assert doc[ "backoff_until" ] == ( NOW + datetime.timedelta( seconds=dd.BACKOFF_SECONDS ) ).isoformat()
    skipped = dd.run( repo, NOW + datetime.timedelta( hours=1 ), "cron", 10, "/bin/claude", parts_of( tmp_path ) )
    assert skipped[ "status" ] == "skipped" and "backing off" in skipped[ "note" ] and skipped[ "judge_calls" ] == 0 and skipped[ "judged" ] is None
    later = dd.run( repo, NOW + datetime.timedelta( hours=2 ), "cron", 10, "/bin/claude", parts_of( tmp_path ) )
    assert later[ "status" ] == "ok" and later[ "judged" ] == 3


def test_a_failed_judging_stage_still_records_the_usage_and_the_count_of_limited_calls( repo, tmp_path, monkeypatch ):
    history( repo )
    monkeypatch.setattr( dd.pipeline, "judge_all", lambda *a, **k: ( _ for _ in () ).throw( RuntimeError( "boom" ) ) )
    doc = dd.run( repo, NOW, "cron", 10, "/bin/claude", parts_of( tmp_path, usage=Meter() ) )
    assert doc[ "status" ] == "failed" and doc[ "stage" ] == dd.STAGE_JUDGING and doc[ "usage" ][ "calls" ] == 3 and doc[ "rate_limited" ] == 0


def test_the_chunk_fills_four_fifths_of_an_hour_at_the_measured_speed_and_never_passes_the_ceiling( tmp_path ):
    assert dd.chunk_for( tmp_path, 5000 ) == 822, "no history: 3.5 seconds a call"
    assert dd.chunk_for( tmp_path, 800 ) == 800
    hist.append_line( tmp_path, line( judge_calls=100, elapsed_seconds=720.0 ) )       # 7.2 seconds a call
    assert dd.chunk_for( tmp_path, 5000 ) == 400
    assert dd.chunk_for( tmp_path, 0 ) == 1, "at least one call"


def adaptive_args( repo, tmp_path, parts, ceiling=10 ):
    """Ensures: returns adaptive_run's positional arguments."""
    return ( repo, NOW, "cron", "/bin/claude", parts, "main", 4, ceiling )


def test_the_hourly_slot_with_work_owed_judges_it_and_with_the_chunk_spent_leaves_the_baseline_alone( repo, tmp_path ):
    history( repo )
    hooks = Hooks()
    parts = parts_of( tmp_path, noter=hooks.hook( "noter" ), urgent=hooks.hook( "urgent" ) )
    docs  = dd.adaptive_run( *adaptive_args( repo, tmp_path, parts, ceiling=2 ) )
    assert [ d[ "mode" ] for d in docs ] == [ "daily" ] and docs[ 0 ][ "status" ] == "carried" and docs[ 0 ][ "judge_calls" ] == 2
    assert [ s[ 0 ] for s in hooks.sent ] == [ "noter" ] and "Duplicate check daily run" in hooks.sent[ 0 ][ 1 ]


def test_the_hourly_slot_gives_the_baseline_what_the_daily_work_left_once_the_daily_work_is_clear( repo, tmp_path, monkeypatch ):
    history( repo )
    monkeypatch.setattr( dd, "MIN_BASELINE_CALLS", 1 )
    parts = parts_of( tmp_path )
    docs  = dd.adaptive_run( *adaptive_args( repo, tmp_path, parts, ceiling=10 ) )
    assert [ d[ "mode" ] for d in docs ] == [ "daily", "baseline" ] and docs[ 0 ][ "status" ] == "ok"
    assert docs[ 1 ][ "ceiling" ] == 10 - docs[ 0 ][ "judge_calls" ] and docs[ 1 ][ "branch" ] == "main"
    assert len( list( ( tmp_path / "io" / "duplicate-check-daily" ).glob( "*.json" ) ) ) >= 4, "two result files with distinct names, last-success and baseline.json"
    lines = hist.read_lines( tmp_path / "io" / "duplicate-check-daily" )
    assert [ l[ "mode" ] for l in lines ] == [ "daily", "baseline" ] and lines[ 0 ][ "run_file" ] != lines[ 1 ][ "run_file" ]


def test_the_hourly_slot_runs_no_baseline_when_it_is_complete_or_the_leftover_is_below_the_floor( repo, tmp_path, monkeypatch ):
    history( repo )
    folder = tmp_path / "io" / "duplicate-check-daily"
    dd.write_json( folder / dd.BASELINE, { "status": dd.BASELINE_DONE } )
    monkeypatch.setattr( dd, "MIN_BASELINE_CALLS", 1 )
    assert [ d[ "mode" ] for d in dd.adaptive_run( *adaptive_args( repo, tmp_path, parts_of( tmp_path ) ) ) ] == [ "daily" ]
    ( folder / dd.BASELINE ).unlink()
    monkeypatch.setattr( dd, "MIN_BASELINE_CALLS", 100 )
    assert [ d[ "mode" ] for d in dd.adaptive_run( repo, NOW + datetime.timedelta( hours=1 ), "cron", "/bin/claude", parts_of( tmp_path ), "main", 4, 10 ) ] == [ "daily" ]


def test_the_hourly_slot_with_nothing_owed_and_nothing_left_is_quiet( repo, tmp_path, monkeypatch ):
    history( repo )
    monkeypatch.setattr( dd, "MIN_BASELINE_CALLS", 10**6 )
    hooks = Hooks()
    parts = parts_of( tmp_path, noter=hooks.hook( "noter" ), urgent=hooks.hook( "urgent" ) )
    dd.adaptive_run( *adaptive_args( repo, tmp_path, parts ) )
    hooks.sent.clear()
    dd.adaptive_run( repo, NOW + datetime.timedelta( hours=1 ), "cron", "/bin/claude", parts, "main", 4, 10 )
    assert hooks.sent == [], "no calls, and the backlog is only the baseline, never measured: the note would say nothing but unknown"


def test_a_failed_run_sends_one_urgent_alert_and_a_branch_guard_refusal_sends_none_of_its_own( repo, tmp_path ):
    history( repo )
    hooks = Hooks()
    parts = parts_of( tmp_path, noter=hooks.hook( "noter" ), urgent=hooks.hook( "urgent" ), version_fn=lambda p: None )
    dd.adaptive_run( *adaptive_args( repo, tmp_path, parts ) )
    assert [ s[ 0 ] for s in hooks.sent ].count( "urgent" ) == 1 and "claude_binary" in hooks.sent[ 0 ][ 1 ]
    folder = tmp_path / "io" / "duplicate-check-daily"
    refusal = { "status": "failed", "trigger": "cron", "mode": "daily", "started_at": "2026-11-07T12:00:00-05:00", "stage": "branch_guard", "refusal": "stale_branch" }
    hooks.sent.clear()
    dd.announce( parts, folder, [ refusal ], NOW, None )
    assert [ s for s in hooks.sent if s[ 0 ] == "urgent" ] == []


def test_a_projected_zero_date_that_moves_more_than_a_day_later_sends_an_urgent_alert( repo, tmp_path ):
    history( repo )
    hooks = Hooks()
    folder = tmp_path / "io" / "duplicate-check-daily"
    parts = parts_of( tmp_path, urgent=hooks.hook( "urgent" ) )
    dd.run( repo, NOW, "cron", 10, "/bin/claude", parts )
    dd.announce( parts, folder, [], NOW + datetime.timedelta( minutes=5 ), "2020-01-01" )
    assert [ s[ 0 ] for s in hooks.sent ] == [ "urgent" ] and "2020-01-01" in hooks.sent[ 0 ][ 1 ]


def test_a_missing_or_broken_hook_changes_nothing_about_the_run( repo, tmp_path ):
    history( repo )
    def broken( spoken, abstract ): raise OSError( "down" )
    docs = dd.adaptive_run( *adaptive_args( repo, tmp_path, parts_of( tmp_path, noter=broken, urgent=broken ), ceiling=2 ) )
    assert docs[ 0 ][ "status" ] == "carried"
    assert dd.adaptive_run( repo, NOW + datetime.timedelta( hours=1 ), "cron", "/bin/claude", parts_of( tmp_path ), "main", 4, 10 )[ 0 ][ "status" ] == "ok", "no hooks at all"


def test_the_exit_code_is_three_for_a_refusal_one_for_a_failure_and_otherwise_zero():
    assert dd.exit_code( [ { "status": "ok" } ] ) == 0 and dd.exit_code( [ { "status": "ok" }, { "status": "failed" } ] ) == 1
    assert dd.exit_code( [ { "status": "failed", "refusal": "stale_branch" }, { "status": "failed" } ] ) == dd.REFUSED_EXIT and dd.exit_code( [ { "status": "skipped" } ] ) == 0


def test_the_live_urgent_and_note_hooks_post_at_their_own_priority():
    seen = []
    def query( base, key, path, params ): seen.append( params ); return 200, ""
    kwargs = dict( environ={ }, query=query, api_key=lambda: "k", target_of=lambda e: "rick@x" )
    assert dd.live_urgent( "s", "a", **kwargs ) is True and dd.live_noter( "s", "a", **kwargs ) is True
    assert [ ( p[ "priority" ], p[ "type" ] ) for p in seen ] == [ ( "urgent", "alert" ), ( "low", "progress" ) ]


def test_the_hourly_cron_lines_run_adaptively_each_hour_from_ten_to_ten_and_at_the_reboot_with_no_baseline_line():
    lines = dd.cron_lines( "/r", "/py", "/log", None, "/bin/claude", branch="auto", ceiling=800, baseline=True, adaptive=True )
    assert len( lines ) == 2 and all( l.endswith( dd.CRON_TAG ) and "--adaptive" in l and "--ceiling 800" in l and "--branch auto" in l for l in lines )
    assert lines[ 0 ].startswith( "0 10-22 * * * " ) and "--trigger cron" in lines[ 0 ] and "--trigger reboot" in lines[ 1 ] and "--baseline" not in " ".join( lines )


def test_main_installs_the_adaptive_lines_and_refuses_an_adaptive_run_without_a_ceiling_or_with_the_baseline( tmp_path, cron ):
    from tests.unit.test_duplicate_check_daily import cron_main
    code, out, _ = cron_main( tmp_path, [ "--print-install", "--ceiling", "800", "--adaptive", "--branch", "auto", "--claude-cli-path", "/bin/claude", "--python", "/py" ], cron )
    assert code == 0 and out[ 0 ].count( dd.CRON_TAG ) == 2 and "--adaptive" in out[ 0 ]
    with pytest.raises( SystemExit ): dd.main( [ "--cap", "5", "--adaptive", "--root", "." ] )
    with pytest.raises( SystemExit ): dd.main( [ "--ceiling", "5", "--adaptive", "--baseline", "--root", "." ] )


def test_main_runs_the_hourly_slot_on_the_resolved_branch_and_prints_every_document( repo, tmp_path, monkeypatch ):
    history( repo )
    git( repo, "checkout", "-q", "-b", "wip-now" )
    monkeypatch.setattr( dd.model_transport, "configure", lambda path=None: None )
    out = []
    rc  = dd.main( [ "--ceiling", "10", "--adaptive", "--branch", "auto", "--root", str( repo ), "--claude-cli-path", "/bin/claude" ], parts=parts_of( tmp_path ), now=NOW, out=out.append )
    docs = json.loads( out[ 0 ] )
    assert rc == 0 and docs[ 0 ][ "branch" ] == "wip-now" and docs[ 0 ][ "status" ] == "ok"
    monkeypatch.setattr( dd, "adaptive_run", lambda *a: [ { "status": "failed" } ] )
    assert dd.main( [ "--ceiling", "10", "--adaptive", "--root", str( repo ), "--claude-cli-path", "/bin/claude" ], parts=parts_of( tmp_path ), now=NOW, out=out.append ) == 1
    assert json.loads( out[ 1 ] ) == [ { "status": "failed" } ]



def test_every_run_rewrites_the_job_summary_and_a_failed_write_is_printed_and_changes_nothing( repo, tmp_path, monkeypatch, capsys ):
    history( repo )
    folder = tmp_path / "io" / "duplicate-check-daily"
    assert dd.run( repo, NOW, "hand", 10, "/bin/claude", parts_of( tmp_path ) )[ "status" ] == "ok"
    assert json.loads( ( folder / "job-summary.json" ).read_text() )[ "last_attempt" ][ "outcome" ] == "clean"
    monkeypatch.setattr( dd.status_mod, "write_job_summary", lambda f, n: ( _ for _ in () ).throw( OSError( "disk full" ) ) )
    assert dd.run( repo, NOW + datetime.timedelta( hours=1 ), "hand", 10, "/bin/claude", parts_of( tmp_path ) )[ "status" ] == "ok"
    assert "the job summary was not written: OSError: disk full" in capsys.readouterr().err
