"""
Unit tests for `src/scripts/purge-offline-heartbeat-events.py` — the tool that
archives heartbeat-event files for sessions the live arbiter marks offline.

LOAD MECHANISM: `importlib.import_module( "purge-offline-heartbeat-events" )` with
`src/scripts` on `sys.path`. The dashed stem is not a valid identifier, so
`import purge-offline-heartbeat-events` is a syntax error — but `import_module`
takes a STRING and never needs one. Same mechanism as `test_watch_hook_events.py`.

NO NETWORK AND NO ARBITER. `urllib.request.urlopen` is replaced in the module's own
namespace, never globally, so nothing here depends on `:8001` being up — and a run
on a box where it IS up cannot silently measure the live roster instead of the
fixture.

THE REAL FILESYSTEM MOVE IS EXERCISED, via `--archive-dir` into a tmp_path. That
argument exists because this test could not honestly be written without it: `main()`
used to build `/tmp/lupin-heartbeat-purge-<timestamp>` inline with nothing able to
redirect it, so an end-to-end `--apply` test would have had to write into the one
directory this fleet's doctrine tells every seat to stay out of. Reported as a
finding, then made injectable on Mr. Radio's ruling. The DEFAULT path is still
asserted, with `shutil.move` recorded rather than run, so the untouched behaviour is
covered too.
"""

import datetime
import importlib
import io
import json
import os
import runpy
import sys

import pytest

_ROOT = os.environ.get( "LUPIN_ROOT", os.getcwd() )
for _p in ( os.path.join( _ROOT, "src", "scripts" ), os.path.join( _ROOT, "src" ) ):
    if _p not in sys.path:
        sys.path.insert( 0, _p )

purge = importlib.import_module( "purge-offline-heartbeat-events" )

SCRIPT_PATH = os.path.join( _ROOT, "src", "scripts", "purge-offline-heartbeat-events.py" )


# ── fixture helpers ──────────────────────────────────────────────────────────

def _session( persona, sid, verdict ):
    return { "persona": persona, "session_id": sid, "liveness": { "verdict": verdict } }


def _state( *sessions ):
    return { "fleet_arbiter": { "sessions": list( sessions ) } }


def _serve( monkeypatch, payload ):
    """Replace urlopen in the MODULE's namespace with one that returns `payload`."""
    calls = [ ]

    def fake_urlopen( url, timeout=None ):
        calls.append( ( url, timeout ) )
        return io.BytesIO( json.dumps( payload ).encode() )

    monkeypatch.setattr( purge.urllib.request, "urlopen", fake_urlopen )
    return calls


class _Recorder:
    """Stands in for shutil.move / os.makedirs so no real /tmp write happens."""

    def __init__( self ): self.moves, self.dirs = [ ], [ ]

    def install( self, monkeypatch ):
        monkeypatch.setattr( purge.shutil, "move",
                             lambda src, dst: self.moves.append( ( src, dst ) ) )
        monkeypatch.setattr( purge.os, "makedirs",
                             lambda path, exist_ok=False: self.dirs.append( path ) )
        return self


# ── fetch_offline_and_live ───────────────────────────────────────────────────

def test_fetch_partitions_sessions_by_the_offline_verdict( monkeypatch ):
    calls = _serve( monkeypatch, _state(
        _session( "Rio", "aaa", "offline" ),
        _session( "Maya", "bbb", "live" ),
        _session( "Sam", "ccc", "quiet" ) ) )
    offline, live = purge.fetch_offline_and_live( "http://arbiter/state", 7 )
    assert [ s[ "session_id" ] for s in offline ] == [ "aaa" ]
    assert [ s[ "session_id" ] for s in live ]    == [ "bbb", "ccc" ]
    assert calls == [ ( "http://arbiter/state", 7 ) ]


@pytest.mark.parametrize( "payload", [
    { },                                          # no fleet_arbiter key
    { "fleet_arbiter": None },                    # present but null
    { "fleet_arbiter": { } },                     # no sessions key
    { "fleet_arbiter": { "sessions": None } },    # present but null
] )
def test_fetch_treats_every_missing_or_null_layer_as_an_empty_roster( monkeypatch, payload ):
    """
    Four ways the snapshot can carry nothing. A KeyError or TypeError on any of them
    would abort a purge on a healthy fleet that simply has no sessions yet.
    """
    _serve( monkeypatch, payload )
    assert purge.fetch_offline_and_live( "http://arbiter/state", 1 ) == ( [ ], [ ] )


def test_fetch_keeps_a_session_whose_liveness_block_is_missing_or_null( monkeypatch ):
    """
    Unknown is NOT offline. A session with no verdict must be KEPT — archiving it
    would delete the event file of a session nobody has proven dead.
    """
    _serve( monkeypatch, _state(
        { "persona": "NoBlock", "session_id": "ddd" },
        { "persona": "NullBlock", "session_id": "eee", "liveness": None } ) )
    offline, live = purge.fetch_offline_and_live( "http://arbiter/state", 1 )
    assert offline == [ ]
    assert [ s[ "session_id" ] for s in live ] == [ "ddd", "eee" ]


def test_fetch_propagates_a_bad_payload_rather_than_guessing( monkeypatch ):
    monkeypatch.setattr( purge.urllib.request, "urlopen",
                         lambda url, timeout=None: io.BytesIO( b"not json" ) )
    with pytest.raises( json.JSONDecodeError ):
        purge.fetch_offline_and_live( "http://arbiter/state", 1 )


# ── main ─────────────────────────────────────────────────────────────────────

def _argv( monkeypatch, *args ):
    monkeypatch.setattr( sys, "argv", [ "purge-offline-heartbeat-events.py", *args ] )


def test_main_dry_run_moves_nothing_and_says_so( monkeypatch, tmp_path, capsys ):
    ( tmp_path / "aaa.jsonl" ).write_text( "{}\n" )
    _serve( monkeypatch, _state( _session( "Rio", "aaa", "offline" ) ) )
    recorder = _Recorder().install( monkeypatch )
    _argv( monkeypatch, "--events-dir", str( tmp_path ) )

    purge.main()

    out = capsys.readouterr().out
    assert "[DRY-RUN] snapshot: offline=1 | keep(live/quiet)=0" in out
    assert "WOULD ARCHIVE 1 offline event files" in out
    assert "(DRY-RUN — nothing moved." in out
    assert recorder.moves == [ ]
    assert ( tmp_path / "aaa.jsonl" ).exists()          # the file is still there
    assert "-> /tmp/lupin-heartbeat-purge" not in out   # no destination is claimed


def test_main_apply_archives_each_offline_file_under_a_timestamped_dir(
        monkeypatch, tmp_path, capsys ):
    ( tmp_path / "aaa.jsonl" ).write_text( "{}\n" )
    ( tmp_path / "bbb.jsonl" ).write_text( "{}\n" )
    _serve( monkeypatch, _state( _session( "Rio", "aaa", "offline" ),
                                 _session( "Maya", "bbb", "offline" ) ) )
    recorder = _Recorder().install( monkeypatch )

    class _Fixed( datetime.datetime ):
        @classmethod
        def now( cls, tz=None ): return cls( 2026, 8, 30, 16, 45, 5 )
    monkeypatch.setattr( purge.datetime, "datetime", _Fixed )
    _argv( monkeypatch, "--apply", "--events-dir", str( tmp_path ) )

    purge.main()

    archive = "/tmp/lupin-heartbeat-purge-2026.08.30-at-164505"
    assert recorder.dirs == [ archive, archive ]
    assert recorder.moves == [
        ( str( tmp_path / "aaa.jsonl" ), os.path.join( archive, "aaa.jsonl" ) ),
        ( str( tmp_path / "bbb.jsonl" ), os.path.join( archive, "bbb.jsonl" ) ),
    ]
    out = capsys.readouterr().out
    assert f"ARCHIVED 2 offline event files -> {archive}" in out
    assert "(DRY-RUN" not in out


def test_main_lists_live_sessions_as_kept_and_never_archives_them(
        monkeypatch, tmp_path, capsys ):
    ( tmp_path / "bbb.jsonl" ).write_text( "{}\n" )
    _serve( monkeypatch, _state( _session( "Maya", "bbb", "live" ) ) )
    recorder = _Recorder().install( monkeypatch )
    _argv( monkeypatch, "--apply", "--events-dir", str( tmp_path ) )

    purge.main()

    out = capsys.readouterr().out
    assert "KEEP (untouched):" in out
    assert "Maya" in out and "bbb" in out and "[live]" in out
    assert recorder.moves == [ ]
    assert "ARCHIVED 0 offline event files" in out


def test_main_separates_offline_sessions_that_have_no_file_on_disk(
        monkeypatch, tmp_path, capsys ):
    """
    An offline session with no event file is commons-only and is reported apart, not
    counted as archived — otherwise the archived count overstates what was moved.
    """
    ( tmp_path / "aaa.jsonl" ).write_text( "{}\n" )
    _serve( monkeypatch, _state(
        _session( "Rio", "aaa", "offline" ),          # has a file
        _session( "Ghost", "zzz", "offline" ),        # no file on disk
        _session( "NoId", None, "offline" ) ) )       # no session id at all
    _Recorder().install( monkeypatch )
    _argv( monkeypatch, "--events-dir", str( tmp_path ) )

    purge.main()

    out = capsys.readouterr().out
    assert "WOULD ARCHIVE 1 offline event files" in out
    assert "OFFLINE but NO event file on disk (2)" in out
    assert "Ghost" in out and "NoId" in out


def test_main_omits_the_no_file_section_when_every_offline_session_has_one(
        monkeypatch, tmp_path, capsys ):
    ( tmp_path / "aaa.jsonl" ).write_text( "{}\n" )
    _serve( monkeypatch, _state( _session( "Rio", "aaa", "offline" ) ) )
    _Recorder().install( monkeypatch )
    _argv( monkeypatch, "--events-dir", str( tmp_path ) )

    purge.main()

    assert "NO event file on disk" not in capsys.readouterr().out


def test_main_uses_the_documented_defaults_for_url_and_timeout( monkeypatch, capsys ):
    calls = _serve( monkeypatch, _state() )
    _argv( monkeypatch )
    purge.main()
    assert calls == [ ( "http://localhost:8001/state", 5 ) ]


def test_main_honours_an_overridden_state_url_and_timeout( monkeypatch, capsys ):
    calls = _serve( monkeypatch, _state() )
    _argv( monkeypatch, "--state-url", "http://elsewhere/state", "--timeout", "30" )
    purge.main()
    assert calls == [ ( "http://elsewhere/state", 30 ) ]


# ── the __main__ guard ───────────────────────────────────────────────────────

def test_running_the_script_calls_main( monkeypatch, tmp_path, capsys ):
    """
    `runpy` re-executes the file, so the module-level `urllib` import is real again —
    the fixture is installed on the real `urllib.request` for the duration.
    """
    import urllib.request
    monkeypatch.setattr(
        urllib.request, "urlopen",
        lambda url, timeout=None: io.BytesIO( json.dumps( _state() ).encode() ) )
    _argv( monkeypatch, "--events-dir", str( tmp_path ) )
    runpy.run_path( SCRIPT_PATH, run_name="__main__" )
    assert "[DRY-RUN] snapshot: offline=0 | keep(live/quiet)=0" in capsys.readouterr().out


# ── the injectable archive destination ───────────────────────────────────────

def test_apply_really_moves_the_file_when_given_an_archive_dir(
        monkeypatch, tmp_path, capsys ):
    """
    The end-to-end move, on a real filesystem, with no recorder in the way — the test
    `--archive-dir` was added to make possible. Source gone, destination present, and
    the archive directory created on demand.
    """
    events  = tmp_path / "events";  events.mkdir()
    archive = tmp_path / "archive"                 # deliberately absent — main creates it
    ( events / "aaa.jsonl" ).write_text( "payload\n" )
    _serve( monkeypatch, _state( _session( "Rio", "aaa", "offline" ) ) )
    _argv( monkeypatch, "--apply", "--events-dir", str( events ),
           "--archive-dir", str( archive ) )

    purge.main()

    assert not ( events / "aaa.jsonl" ).exists()               # moved, not copied
    assert ( archive / "aaa.jsonl" ).read_text() == "payload\n"
    assert f"ARCHIVED 1 offline event files -> {archive}" in capsys.readouterr().out


def test_a_dry_run_with_an_archive_dir_still_creates_nothing(
        monkeypatch, tmp_path, capsys ):
    """--archive-dir must not turn a dry run into a real one."""
    events  = tmp_path / "events";  events.mkdir()
    archive = tmp_path / "archive"
    ( events / "aaa.jsonl" ).write_text( "payload\n" )
    _serve( monkeypatch, _state( _session( "Rio", "aaa", "offline" ) ) )
    _argv( monkeypatch, "--events-dir", str( events ), "--archive-dir", str( archive ) )

    purge.main()

    assert ( events / "aaa.jsonl" ).exists()
    assert not archive.exists()
    assert "(DRY-RUN — nothing moved." in capsys.readouterr().out
