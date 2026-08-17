"""
Unit tests for the memento-verify standing tick (row 505e5c12).

WHAT THIS GUARDS. The row exists because a check that cannot fire is indistinguishable
from a check that passes. So the tests that matter are not "does it run" — they are the
ones proving it CANNOT go quiet for the wrong reason.

🔴 THE CONTROLS, and each one reds if the tick regresses toward silence:
  - test_unreadable_ledger_triggers_a_run: a corrupt stamp must mean "never ran", not
    "ran recently". The opposite reading suppresses the check forever on one bad write.
  - test_unreadable_findings_line_is_not_reported_as_clean: a run whose output cannot be
    parsed returns a LOUD line. Rendering it as 0 findings is the exact "could not
    measure" wearing "measured, fine" defect this codebase keeps re-finding.
  - test_missing_env_var_is_loud / test_timeout_is_loud: the two infrastructure failures
    both say so. Silence is reserved for TTL-not-expired and genuinely-zero-findings.
  - test_never_raises: every failure path returns a string. A memento checker that could
    take the Stop hook down would be worse than the bug it was written to catch.

No subprocess is ever really spawned: `subprocess.run` is patched throughout, so these
run on :7999 in milliseconds and never touch the real repo or the real ledger.
"""
import json
import os
import subprocess

from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

_src = os.path.join( os.environ[ "LUPIN_ROOT" ], "src" )
import sys
if _src not in sys.path: sys.path.insert( 0, _src )

from lupin_cli.claude_code.hooks.lib import memento_verify_tick as tick


NOW = datetime( 2026, 8, 1, 12, 0, 0, tzinfo=timezone.utc )


@pytest.fixture
def ledger( tmp_path, monkeypatch ):
    p = tmp_path / "ledger.json"
    monkeypatch.setattr( tick, "_ledger_path", lambda: p )
    return p


@pytest.fixture
def script( tmp_path, monkeypatch ):
    s = tmp_path / "memento_io.py"
    s.write_text( "# stub", encoding="utf-8" )
    monkeypatch.setattr( tick, "_script_path", lambda: s )
    monkeypatch.setenv( "LUPIN_ROOT", str( tmp_path ) )
    return s


def _completed( stdout ):
    return subprocess.CompletedProcess( args=[], returncode=0, stdout=stdout, stderr="" )


# ── the ledger ────────────────────────────────────────────────────────────────

def test_missing_ledger_reads_as_never_ran( tmp_path ):
    assert tick._read_last_run( tmp_path / "nope.json", NOW ) is None


def test_unreadable_ledger_triggers_a_run( tmp_path ):
    # 🔴 CONTROL: a corrupt stamp must NOT read as "recently done".
    p = tmp_path / "l.json"
    p.write_text( "{ not json", encoding="utf-8" )
    assert tick._read_last_run( p, NOW ) is None


def test_ledger_without_a_timestamp_reads_as_never_ran( tmp_path ):
    p = tmp_path / "l.json"
    p.write_text( json.dumps( { "findings": 3 } ), encoding="utf-8" )
    assert tick._read_last_run( p, NOW ) is None


def test_ledger_age_is_measured_from_the_stamp( tmp_path ):
    p = tmp_path / "l.json"
    tick._write_last_run( p, NOW - timedelta( hours=5 ), 0 )
    assert 5 * 3600 - 2 < tick._read_last_run( p, NOW ) < 5 * 3600 + 2


def test_write_failure_is_swallowed( tmp_path ):
    # Losing the stamp costs one extra scan; raising costs the session.
    #
    # 🔴 THIS TEST DID NOT FAIL ON PURPOSE AT FIRST, and coverage caught it. The original
    # version passed a deep nonexistent path — but `_write_last_run` calls
    # `mkdir( parents=True )`, so the write SUCCEEDED and the except arm it claimed to
    # cover was never entered. A test named for a failure that never fails is exactly the
    # shape the tick itself exists to prevent, one level out. Force a real error.
    p = tmp_path / "l.json"
    with patch.object( Path, "write_text", side_effect=OSError( "disk full" ) ):
        tick._write_last_run( p, NOW, 0 )    # must not raise
    assert not p.exists()


def test_ledger_path_sits_with_the_other_hook_ledgers():
    assert tick._ledger_path().name == ".memento-verify-tick.json"


# ── the findings parser ───────────────────────────────────────────────────────

@pytest.mark.parametrize( "line, expected", [
    ( "--- FINDINGS    : 0", 0 ),
    ( "--- FINDINGS    : 5", 5 ),
    ( "--- FINDINGS : 12",  12 ),
] )
def test_findings_line_is_parsed( line, expected ):
    assert tick._parse_findings( f"noise\n{line}\n" ) == expected


def test_missing_findings_line_is_none_not_zero():
    # 🔴 CONTROL. None means "unknown"; 0 means "measured, clean". Collapsing them
    # reproduces this row's own defect inside its fix.
    assert tick._parse_findings( "no summary at all" ) is None


def test_unparseable_findings_count_is_none_not_zero():
    assert tick._parse_findings( "--- FINDINGS    : many" ) is None


def test_last_findings_line_wins():
    assert tick._parse_findings( "--- FINDINGS : 1\n--- FINDINGS : 7" ) == 7


# ── the script locator ────────────────────────────────────────────────────────

def test_script_path_is_none_without_the_env_var( monkeypatch ):
    monkeypatch.delenv( "PLANNING_IS_PROMPTING_ROOT", raising=False )
    assert tick._script_path() is None


def test_script_path_is_none_when_the_file_is_absent( monkeypatch, tmp_path ):
    monkeypatch.setenv( "PLANNING_IS_PROMPTING_ROOT", str( tmp_path ) )
    assert tick._script_path() is None


def test_script_path_resolves_when_present( monkeypatch, tmp_path ):
    s = tmp_path / "workflow" / "scripts" / "memento_io.py"
    s.parent.mkdir( parents=True )
    s.write_text( "# stub", encoding="utf-8" )
    monkeypatch.setenv( "PLANNING_IS_PROMPTING_ROOT", str( tmp_path ) )
    assert tick._script_path() == s


# ── the tick itself ───────────────────────────────────────────────────────────

def test_fresh_ledger_suppresses_the_run( ledger, script ):
    tick._write_last_run( ledger, NOW, 0 )
    with patch.object( subprocess, "run" ) as run:
        assert tick.verify_tick_line( now=NOW ) == ""
        assert not run.called, "the TTL did not suppress the subprocess"


def test_expired_ledger_runs_again( ledger, script ):
    tick._write_last_run( ledger, NOW - timedelta( seconds=tick.MEMENTO_VERIFY_TTL_SECONDS + 1 ), 0 )
    with patch.object( subprocess, "run", return_value=_completed( "--- FINDINGS : 0" ) ) as run:
        assert tick.verify_tick_line( now=NOW ) == ""
        assert run.called


def test_force_bypasses_the_ttl( ledger, script ):
    tick._write_last_run( ledger, NOW, 0 )
    with patch.object( subprocess, "run", return_value=_completed( "--- FINDINGS : 0" ) ) as run:
        tick.verify_tick_line( now=NOW, force=True )
        assert run.called


def test_zero_findings_is_silent( ledger, script ):
    with patch.object( subprocess, "run", return_value=_completed( "--- FINDINGS : 0" ) ):
        assert tick.verify_tick_line( now=NOW, force=True ) == ""


def test_findings_produce_a_line_naming_the_count_and_the_remedy( ledger, script ):
    with patch.object( subprocess, "run", return_value=_completed( "--- FINDINGS : 3" ) ):
        line = tick.verify_tick_line( now=NOW, force=True )
    assert "3 finding" in line and "migrate" in line
    assert "Nothing has been changed for you" in line, "the tick must state that it did not repair"


def test_unreadable_findings_line_is_not_reported_as_clean( ledger, script ):
    # 🔴 THE CONTROL THIS ROW IS ABOUT.
    with patch.object( subprocess, "run", return_value=_completed( "ran, but no summary" ) ):
        line = tick.verify_tick_line( now=NOW, force=True )
    assert line and "unknown rather than clean" in line


def test_missing_env_var_is_loud( ledger, monkeypatch ):
    monkeypatch.setattr( tick, "_script_path", lambda: None )
    line = tick.verify_tick_line( now=NOW, force=True )
    assert "SKIPPED" in line and "not a clean result" in line


# ── scope: the verdict must not claim more than it checked (row 890c07d3) ─────

def test_findings_line_names_the_repo_it_actually_checked( ledger, script ):
    """
    This tick reads ONE repo — the LUPIN_ROOT one. It used to report "N finding(s)
    in this repo's mementos", which a reader sitting in a DIFFERENT repo takes to
    mean theirs; six of the 23 live seats are planning-is-prompting-resident and
    none are covered here. The verdict must name its subject so it cannot be read
    fleet-wide.
    """
    with patch.object( subprocess, "run", return_value=_completed( "--- FINDINGS : 3" ) ):
        line = tick.verify_tick_line( repo_root="/repos/lupin", now=NOW, force=True )

    assert "lupin" in line, "the verdict does not name the repo it read"
    assert "this repo's mementos" not in line, "unscoped phrasing is back"
    # The remedy must be runnable as printed, not a <lupin> placeholder to fill in.
    assert "/repos/lupin" in line and "<lupin>" not in line


def test_scope_naming_follows_the_repo_actually_passed( ledger, script ):
    """
    The name must come from the repo under test, not a constant — otherwise the
    assertion above passes for a hardcoded "lupin" while the tick reads elsewhere.
    This is the input where those two possibilities diverge.
    """
    with patch.object( subprocess, "run", return_value=_completed( "--- FINDINGS : 2" ) ):
        line = tick.verify_tick_line( repo_root="/repos/planning-is-prompting", now=NOW, force=True )

    assert "planning-is-prompting" in line
    assert "/repos/lupin" not in line


def test_unreadable_findings_line_also_names_its_repo( ledger, script ):
    """The unknown-result path makes a claim too, so it carries the same scope."""
    with patch.object( subprocess, "run", return_value=_completed( "ran, but no summary" ) ):
        line = tick.verify_tick_line( repo_root="/repos/lupin", now=NOW, force=True )

    assert "unknown rather than clean" in line
    assert "lupin" in line and "<lupin>" not in line


def test_missing_repo_root_is_loud( ledger, script, monkeypatch ):
    # Since row 890c07d3 an unset LUPIN_ROOT is no longer enough to mean "nothing to
    # check" — the bridges are consulted too. Stub discovery empty so this asserts the
    # nothing-to-check path rather than whatever repos happen to be live on this box;
    # without the stub the test silently depended on the real sessions dir.
    monkeypatch.delenv( "LUPIN_ROOT", raising=False )
    monkeypatch.setattr( tick, "fleet_repo_roots", lambda *a, **k: [] )
    line = tick.verify_tick_line( now=NOW, force=True, repo_root=None )
    assert "SKIPPED" in line and "no repo to check" in line


# ── fleet coverage: the sweep spans repos (row 890c07d3, Rick's ruling) ───────

def test_fleet_repo_roots_reads_cwd_from_bridges_and_needs_io_mementos( tmp_path ):
    """
    The list is OBSERVED from live bridges, not declared. A repo only qualifies if it
    actually holds io/mementos — otherwise there is nothing to verify and naming it
    would be noise dressed as coverage.
    """
    bridges = tmp_path / "sessions"; bridges.mkdir()
    has     = tmp_path / "has-mementos"; ( has / "io" / "mementos" ).mkdir( parents=True )
    without = tmp_path / "no-mementos"; without.mkdir()

    ( bridges / "cc-1.json" ).write_text( json.dumps( { "cwd": str( has ) } ) )
    ( bridges / "cc-2.json" ).write_text( json.dumps( { "cwd": str( without ) } ) )
    ( bridges / "cc-3.json" ).write_text( "{ half-written" )          # must not be fatal
    ( bridges / "cc-4-buffer.json" ).write_text( json.dumps( { "cwd": str( has ) } ) )

    roots = tick.fleet_repo_roots( bridges_dir=bridges )
    assert roots == [ str( has ) ]


def test_fleet_repo_roots_is_empty_not_raising_when_the_dir_is_missing( tmp_path ):
    assert tick.fleet_repo_roots( bridges_dir=tmp_path / "nope" ) == []


def test_sweep_checks_every_discovered_repo_and_attributes_each_finding( ledger, script, monkeypatch ):
    """
    🔴 THE GUARD THIS ROW EXISTS FOR. Before the ruling only lupin was ever checked,
    so a divergence in planning-is-prompting was never looked at and the silence read
    as clean. Both repos must be verified, and each finding must name ITS OWN repo —
    a sweep that reported "2 findings" without saying where would be unactionable.
    """
    monkeypatch.setattr( tick, "fleet_repo_roots",
                         lambda *a, **k: [ "/repos/lupin", "/repos/planning-is-prompting" ] )
    monkeypatch.delenv( "LUPIN_ROOT", raising=False )

    seen = []
    def _run( argv, **kw ):
        seen.append( argv[ argv.index( "--repo" ) + 1 ] )
        return _completed( "--- FINDINGS : 2" if "planning" in argv[ -1 ] else "--- FINDINGS : 0" )

    with patch.object( subprocess, "run", side_effect=_run ):
        line = tick.verify_tick_line( now=NOW, force=True )

    assert sorted( seen ) == [ "/repos/lupin", "/repos/planning-is-prompting" ], \
        "the sweep did not visit every discovered repo"
    # lupin was clean, so it must stay silent; the other repo's findings must surface
    # AND be attributed, or a reader cannot tell which repo to go fix.
    assert "planning-is-prompting" in line and "2 finding" in line
    assert "lupin's mementos" not in line, "a clean repo was reported as having findings"


def test_lupin_is_swept_even_when_no_lupin_seat_is_live( ledger, script, monkeypatch ):
    """
    The union with LUPIN_ROOT is load-bearing: discovery alone would drop lupin the
    moment no lupin seat happens to be live, trading one blind spot for another.
    """
    monkeypatch.setattr( tick, "fleet_repo_roots", lambda *a, **k: [ "/repos/planning-is-prompting" ] )
    monkeypatch.setenv( "LUPIN_ROOT", "/repos/lupin" )

    seen = []
    def _run( argv, **kw ):
        seen.append( argv[ argv.index( "--repo" ) + 1 ] )
        return _completed( "--- FINDINGS : 0" )

    with patch.object( subprocess, "run", side_effect=_run ):
        tick.verify_tick_line( now=NOW, force=True )

    assert "/repos/lupin" in seen, "lupin dropped out of the sweep when no lupin seat was live"


def test_one_repo_failing_does_not_silence_another( ledger, script, monkeypatch ):
    """
    A timeout on the first repo must not swallow the second's findings — that would
    reinstate exactly the silence this row is about, one level up.
    """
    monkeypatch.setattr( tick, "fleet_repo_roots",
                         lambda *a, **k: [ "/repos/aaa", "/repos/zzz" ] )
    monkeypatch.delenv( "LUPIN_ROOT", raising=False )

    def _run( argv, **kw ):
        if "aaa" in argv[ -1 ]: raise subprocess.TimeoutExpired( "cmd", 120 )
        return _completed( "--- FINDINGS : 4" )

    with patch.object( subprocess, "run", side_effect=_run ):
        line = tick.verify_tick_line( now=NOW, force=True )

    assert "TIMED OUT" in line and "aaa" in line
    assert "4 finding" in line and "zzz" in line


def test_timeout_is_loud( ledger, script ):
    with patch.object( subprocess, "run", side_effect=subprocess.TimeoutExpired( "cmd", 120 ) ):
        line = tick.verify_tick_line( now=NOW, force=True )
    assert "TIMED OUT" in line and "UNVERIFIED" in line


def test_a_failure_still_stamps_the_ledger( ledger, script ):
    # Otherwise a persistently-failing scan re-runs on EVERY stop and floods the seat.
    with patch.object( subprocess, "run", side_effect=subprocess.TimeoutExpired( "cmd", 120 ) ):
        tick.verify_tick_line( now=NOW, force=True )
    assert ledger.exists()


def test_never_raises( ledger, monkeypatch ):
    # 🔴 CONTROL: the hook must survive anything this module can do.
    monkeypatch.setattr( tick, "_script_path", lambda: ( _ for _ in () ).throw( RuntimeError( "boom" ) ) )
    line = tick.verify_tick_line( now=NOW, force=True )
    assert "tick failed" in line and "UNVERIFIED" in line


def test_it_never_passes_a_mutating_verb( ledger, script ):
    # The row flagged auto-restore as tempting and probably wrong. Prove the tick can
    # only ever READ: the argv must carry `verify`, never `migrate`/`write`/`adopt`.
    with patch.object( subprocess, "run", return_value=_completed( "--- FINDINGS : 0" ) ) as run:
        tick.verify_tick_line( now=NOW, force=True )
    argv = run.call_args[ 0 ][ 0 ]
    assert "verify" in argv
    for mutating in ( "migrate", "write", "amend", "adopt", "--apply" ):
        assert mutating not in argv


def test_smoke_test_passes():
    assert tick.quick_smoke_test() is True
