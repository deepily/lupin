#!/usr/bin/env python3
"""
Unit tests — stale cc-buffer janitor (bug 59f355e0 follow-up, task 18603e57).

Venue: :7999-eligible / local — no server, no real process scan (subprocess +
bridge scan injected; buffers/bridges under tmp_path). Covers the pure logic +
IO shell to 100% lines/branches/functions.

Contract: DRY-RUN by default (never moves); --apply does REVERSIBLE MOVEs to a
quarantine dir (never delete, never replay); BIAS-TO-KEEP — a buffer is archived
ONLY when its session is definitively not live AND the buffer is older than a
grace window; any ambiguity keeps the file.
"""
import json
import os
import sys

import pytest

# Bootstrap
_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

from lupin_cli.claude_code.hooks.lib import stale_buffer_janitor as sbj

HOUR = 3600
NOW  = 1_800_000_000   # fixed epoch for deterministic age math


# ── pure: name parsing ──────────────────────────────────────────────────────────

class TestParseHash:

    def test_valid( self ):
        assert sbj.parse_hash_from_buffer_name( "cc-buffer-46ffe611.jsonl" ) == "46ffe611"

    def test_not_a_buffer( self ):
        assert sbj.parse_hash_from_buffer_name( "cc-listener-46ffe611.log" ) is None

    def test_empty( self ):
        assert sbj.parse_hash_from_buffer_name( "" ) is None


class TestParseListenerHashes:

    def test_extracts_session_ids( self ):
        out = (
            "1234 python -m ...cc_notification_listener --session-id 8a92b253 --debug\n"
            "5678 python -m ...cc_notification_listener --session-id 95c8eba0\n"
            "9999 grep cc_notification_listener\n"        # no --session-id → skipped
        )
        assert sbj.parse_listener_hashes( out ) == { "8a92b253", "95c8eba0" }

    def test_empty_output( self ):
        assert sbj.parse_listener_hashes( "" ) == set()


class TestCountBufferLines:

    def test_counts_total_and_ai_to_ai( self ):
        text = (
            json.dumps( { "message": "a", "direction": "ai_to_ai" } ) + "\n"
            + json.dumps( { "message": "b", "direction": "human_to_ai" } ) + "\n"
            + "\n"                                          # blank skipped
            + "{bad json\n"                                 # malformed skipped
            + json.dumps( { "message": "c", "direction": "ai_to_ai" } ) + "\n"
        )
        assert sbj.count_buffer_lines( text ) == ( 3, 2 )   # 3 valid rows, 2 ai_to_ai

    def test_empty( self ):
        assert sbj.count_buffer_lines( "" ) == ( 0, 0 )


# ── pure: classify ──────────────────────────────────────────────────────────────

def _meta( hash8="dead0001", mtime_epoch=NOW - 5 * HOUR, total=3, ai=2, path=None ):
    return { "hash8": hash8, "path": path or f"/x/cc-buffer-{hash8}.jsonl",
             "total": total, "ai_to_ai": ai, "mtime_epoch": mtime_epoch }


class TestClassify:

    def test_dead_old_session_archived( self ):
        c = sbj.classify_buffer( _meta(), live_hashes={ "live0001" }, now_epoch=NOW, min_age_hours=1.0 )
        assert c[ "dead" ] is True
        assert "ARCHIVE" in c[ "reason" ]
        assert c[ "age_hours" ] == pytest.approx( 5.0 )

    def test_live_session_kept( self ):
        c = sbj.classify_buffer( _meta( hash8="live0001" ), live_hashes={ "live0001" },
                                 now_epoch=NOW, min_age_hours=1.0 )
        assert c[ "dead" ] is False
        assert "KEEP" in c[ "reason" ] and "live" in c[ "reason" ]

    def test_recent_dead_session_kept_grace( self ):
        c = sbj.classify_buffer( _meta( mtime_epoch=NOW - 600 ), live_hashes=set(),
                                 now_epoch=NOW, min_age_hours=1.0 )
        assert c[ "dead" ] is False                        # <1h old → bias-to-keep
        assert "too recent" in c[ "reason" ]


class TestBuildPlan:

    def test_partitions_archive_and_keep( self ):
        classified = [
            { "dead": True,  "hash8": "d1" },
            { "dead": False, "hash8": "k1" },
            { "dead": True,  "hash8": "d2" },
        ]
        plan = sbj.build_plan( classified )
        assert [ c[ "hash8" ] for c in plan[ "archive" ] ] == [ "d1", "d2" ]
        assert [ c[ "hash8" ] for c in plan[ "keep" ] ] == [ "k1" ]


class TestPlanMoveDst:

    def test_dst_in_quarantine_keeps_basename( self, tmp_path ):
        src = tmp_path / "cc-buffer-dead0001.jsonl"
        dst = sbj.plan_move_dst( str( src ), str( tmp_path / "q" ) )
        assert dst.name == "cc-buffer-dead0001.jsonl"
        assert dst.parent.name == "q"


class TestFormatReport:

    def _plan( self ):
        return {
            "archive": [ { "hash8": "d1", "path": "/x/cc-buffer-d1.jsonl", "total": 3,
                           "ai_to_ai": 2, "age_hours": 50.0, "reason": "ARCHIVE: dead" } ],
            "keep":    [ { "hash8": "k1", "path": "/x/cc-buffer-k1.jsonl", "total": 1,
                           "ai_to_ai": 1, "age_hours": 0.2, "reason": "KEEP: session live" } ],
        }

    def test_dry_run_report_mentions_would( self ):
        r = sbj.format_report( self._plan(), apply=False, quarantine_dir="/q" )
        assert "DRY-RUN" in r and "WOULD" in r.upper()
        assert "d1" in r and "k1" in r
        assert "2 DM" in r or "ai_to_ai" in r.lower() or "2" in r

    def test_apply_report_mentions_moved( self ):
        r = sbj.format_report( self._plan(), apply=True, quarantine_dir="/q" )
        assert "APPLY" in r.upper() or "MOVED" in r.upper()

    def test_empty_plan_report( self ):
        r = sbj.format_report( { "archive": [], "keep": [] }, apply=False, quarantine_dir="/q" )
        assert "0" in r


# ── IO shell ────────────────────────────────────────────────────────────────────

class TestListListenerHashes:

    def test_parses_run_fn_output( self ):
        out = "1 x --session-id aaaa1111\n2 y --session-id bbbb2222\n"
        assert sbj.list_listener_hashes( run_fn=lambda: out ) == { "aaaa1111", "bbbb2222" }

    def test_run_fn_error_raises( self ):
        def boom():
            raise OSError( "no ps" )
        with pytest.raises( OSError ):
            sbj.list_listener_hashes( run_fn=boom )

    def test_default_run_fn_real_ps( self ):
        # Exercise the real subprocess default path; assert only the shape (a set),
        # never the content (host-dependent).
        result = sbj.list_listener_hashes()
        assert isinstance( result, set )


class TestListBridgeLiveHashes:

    def _write_bridge( self, d, name, data, mtime=None ):
        p = d / name
        p.write_text( json.dumps( data ) )
        if mtime is not None:
            os.utime( p, ( mtime, mtime ) )
        return p

    def test_fresh_bridge_counts_live( self, tmp_path ):
        self._write_bridge( tmp_path, "cc-1.json",
                            { "session_id": "aaaa1111-full", "stable_session_id": "aaaa1111-full",
                              "listener_pid": 999999 },
                            mtime=NOW - 100 )
        live = sbj.list_bridge_live_hashes( tmp_path, now_epoch=NOW, fresh_seconds=HOUR,
                                            is_pid_alive=lambda pid: False )
        assert "aaaa1111" in live                          # fresh mtime → live even if pid dead

    def test_stale_bridge_but_live_pid_counts( self, tmp_path ):
        self._write_bridge( tmp_path, "cc-2.json",
                            { "stable_session_id": "bbbb2222-full", "listener_pid": 4242 },
                            mtime=NOW - 10 * HOUR )
        live = sbj.list_bridge_live_hashes( tmp_path, now_epoch=NOW, fresh_seconds=HOUR,
                                            is_pid_alive=lambda pid: pid == 4242 )
        assert "bbbb2222" in live                          # stale mtime but live pid → live

    def test_stale_bridge_dead_pid_excluded( self, tmp_path ):
        self._write_bridge( tmp_path, "cc-3.json",
                            { "stable_session_id": "cccc3333-full", "listener_pid": 1 },
                            mtime=NOW - 10 * HOUR )
        live = sbj.list_bridge_live_hashes( tmp_path, now_epoch=NOW, fresh_seconds=HOUR,
                                            is_pid_alive=lambda pid: False )
        assert "cccc3333" not in live

    def test_malformed_bridge_skipped( self, tmp_path ):
        ( tmp_path / "cc-bad.json" ).write_text( "{not json" )
        assert sbj.list_bridge_live_hashes( tmp_path, now_epoch=NOW, fresh_seconds=HOUR,
                                            is_pid_alive=lambda pid: False ) == set()

    def test_no_pid_field_uses_mtime_only( self, tmp_path ):
        self._write_bridge( tmp_path, "cc-4.json",
                            { "session_id": "dddd4444-full" }, mtime=NOW - 100 )
        live = sbj.list_bridge_live_hashes( tmp_path, now_epoch=NOW, fresh_seconds=HOUR,
                                            is_pid_alive=lambda pid: False )
        assert "dddd4444" in live

    def test_missing_dir_returns_empty( self, tmp_path ):
        assert sbj.list_bridge_live_hashes( tmp_path / "nope", now_epoch=NOW,
                                            fresh_seconds=HOUR, is_pid_alive=lambda p: False ) == set()

    def test_non_dict_bridge_skipped( self, tmp_path ):
        ( tmp_path / "cc-list.json" ).write_text( "[1, 2, 3]" )   # valid JSON, not a dict
        assert sbj.list_bridge_live_hashes( tmp_path, now_epoch=NOW, fresh_seconds=HOUR,
                                            is_pid_alive=lambda p: False ) == set()


class TestIsPidAlive:

    def test_current_process_alive( self ):
        assert sbj.is_pid_alive( os.getpid() ) is True

    def test_pid_zero_or_bogus( self ):
        assert sbj.is_pid_alive( 0 ) is False
        assert sbj.is_pid_alive( -5 ) is False

    def test_almost_certainly_dead_pid( self ):
        assert sbj.is_pid_alive( 2_000_000_000 ) is False

    def test_non_int_pid( self ):
        assert sbj.is_pid_alive( "not-an-int" ) is False

    def test_permission_error_means_alive( self, monkeypatch ):
        def raise_perm( pid, sig ):
            raise PermissionError( "not yours" )
        monkeypatch.setattr( sbj.os, "kill", raise_perm )
        assert sbj.is_pid_alive( 4242 ) is True            # exists, owned by another user


class TestCollectLiveHashes:

    def test_union_of_listeners_and_bridges( self, tmp_path, monkeypatch ):
        monkeypatch.setattr( sbj, "list_listener_hashes", lambda: { "aaaa1111" } )
        monkeypatch.setattr( sbj, "list_bridge_live_hashes",
                             lambda *a, **k: { "bbbb2222" } )
        live = sbj.collect_live_hashes( tmp_path, now_epoch=NOW )
        assert live == { "aaaa1111", "bbbb2222" }


class TestGatherBufferMeta:

    def test_reads_counts_and_mtime( self, tmp_path ):
        p = tmp_path / "cc-buffer-dead0001.jsonl"
        p.write_text( json.dumps( { "message": "x", "direction": "ai_to_ai" } ) + "\n" )
        os.utime( p, ( NOW - 3 * HOUR, NOW - 3 * HOUR ) )
        m = sbj.gather_buffer_meta( str( p ), now_epoch=NOW )
        assert m[ "hash8" ] == "dead0001"
        assert m[ "total" ] == 1 and m[ "ai_to_ai" ] == 1
        assert m[ "mtime_epoch" ] == NOW - 3 * HOUR

    def test_unreadable_file_counts_zero( self, tmp_path, monkeypatch ):
        p = tmp_path / "cc-buffer-dead0002.jsonl"
        p.write_text( "x" )
        os.utime( p, ( NOW - 3 * HOUR, NOW - 3 * HOUR ) )
        monkeypatch.setattr( sbj.Path, "read_text",
                             lambda self, *a, **k: ( _ for _ in () ).throw( OSError( "unreadable" ) ) )
        m = sbj.gather_buffer_meta( str( p ), now_epoch=NOW )
        assert m[ "total" ] == 0 and m[ "ai_to_ai" ] == 0   # unreadable → 0 counts, still classifiable
        assert m[ "mtime_epoch" ] == NOW - 3 * HOUR         # stat still worked

    def test_stat_error_falls_back_to_now( self, tmp_path, monkeypatch ):
        p = tmp_path / "cc-buffer-dead0003.jsonl"
        p.write_text( json.dumps( { "message": "x", "direction": "ai_to_ai" } ) + "\n" )
        monkeypatch.setattr( sbj.Path, "stat",
                             lambda self, *a, **k: ( _ for _ in () ).throw( OSError( "no stat" ) ) )
        m = sbj.gather_buffer_meta( str( p ), now_epoch=NOW )
        assert m[ "mtime_epoch" ] == NOW                    # stat error → now (→ within grace → kept)


# ── end-to-end run() ─────────────────────────────────────────────────────────────

class TestRun:

    def _make_buffer( self, d, hash8, mtime_epoch, n_ai=2 ):
        p = d / f"cc-buffer-{hash8}.jsonl"
        lines = "".join( json.dumps( { "message": f"m{i}", "direction": "ai_to_ai" } ) + "\n"
                         for i in range( n_ai ) )
        p.write_text( lines )
        os.utime( p, ( mtime_epoch, mtime_epoch ) )
        return p

    def test_dry_run_lists_dead_keeps_live_and_moves_nothing( self, tmp_path ):
        dead = self._make_buffer( tmp_path, "dead0001", NOW - 50 * HOUR )
        live = self._make_buffer( tmp_path, "live0001", NOW - 50 * HOUR )
        result = sbj.run( sessions_dir=tmp_path, apply=False, now_epoch=NOW,
                          live_hashes={ "live0001" } )
        archived = [ c[ "hash8" ] for c in result[ "plan" ][ "archive" ] ]
        assert archived == [ "dead0001" ]
        assert result[ "moved" ] == []                     # dry-run moves NOTHING
        assert dead.exists() and live.exists()             # both files untouched
        assert "DRY-RUN" in result[ "report" ]

    def test_apply_moves_dead_only_reversibly( self, tmp_path ):
        dead = self._make_buffer( tmp_path, "dead0001", NOW - 50 * HOUR )
        live = self._make_buffer( tmp_path, "live0001", NOW - 50 * HOUR )
        qdir = tmp_path / "q"
        result = sbj.run( sessions_dir=tmp_path, quarantine_dir=qdir, apply=True,
                          now_epoch=NOW, live_hashes={ "live0001" } )
        assert not dead.exists()                           # dead MOVED out
        assert ( qdir / "cc-buffer-dead0001.jsonl" ).exists()   # ...into quarantine (reversible)
        assert live.exists()                               # live untouched
        assert result[ "moved" ] == [ str( qdir / "cc-buffer-dead0001.jsonl" ) ]

    def test_run_collects_live_hashes_when_not_injected( self, tmp_path, monkeypatch ):
        monkeypatch.setattr( sbj, "collect_live_hashes", lambda *a, **k: set() )
        self._make_buffer( tmp_path, "dead0001", NOW - 50 * HOUR )
        result = sbj.run( sessions_dir=tmp_path, apply=False, now_epoch=NOW )
        assert [ c[ "hash8" ] for c in result[ "plan" ][ "archive" ] ] == [ "dead0001" ]

    def test_non_buffer_files_ignored( self, tmp_path ):
        ( tmp_path / "cc-listener-x.log" ).write_text( "noise" )
        ( tmp_path / "random.txt" ).write_text( "noise" )
        result = sbj.run( sessions_dir=tmp_path, apply=False, now_epoch=NOW, live_hashes=set() )
        assert result[ "plan" ][ "archive" ] == [] and result[ "plan" ][ "keep" ] == []

    def test_defaults_now_epoch_when_none( self, tmp_path ):
        # now_epoch=None → real time.time(); empty dir → empty plan, no crash.
        result = sbj.run( sessions_dir=tmp_path, apply=False, now_epoch=None, live_hashes=set() )
        assert result[ "plan" ] == { "archive": [], "keep": [] }
        assert result[ "moved" ] == []

    def test_default_quarantine_dir_used_on_apply( self, tmp_path ):
        self._make_buffer( tmp_path, "dead0001", NOW - 50 * HOUR )
        sbj.run( sessions_dir=tmp_path, apply=True, now_epoch=NOW, live_hashes=set() )
        assert ( tmp_path / sbj.QUARANTINE_DIRNAME / "cc-buffer-dead0001.jsonl" ).exists()

    def test_apply_move_uses_injected_move_fn( self, tmp_path ):
        self._make_buffer( tmp_path, "dead0001", NOW - 50 * HOUR )
        calls = []
        def fake_move( src, dst ):
            calls.append( ( src, dst ) )
        sbj.run( sessions_dir=tmp_path, quarantine_dir=tmp_path / "q", apply=True,
                 now_epoch=NOW, live_hashes=set(), move_fn=fake_move )
        assert len( calls ) == 1


# ── main() CLI ───────────────────────────────────────────────────────────────────

class TestMain:

    def test_dry_run_default_returns_zero( self, tmp_path, capsys, monkeypatch ):
        monkeypatch.setattr( sbj, "collect_live_hashes", lambda *a, **k: set() )
        ( tmp_path / "cc-buffer-dead0001.jsonl" ).write_text(
            json.dumps( { "message": "x", "direction": "ai_to_ai" } ) + "\n" )
        os.utime( tmp_path / "cc-buffer-dead0001.jsonl", ( NOW - 50 * HOUR, NOW - 50 * HOUR ) )
        rc = sbj.main( [ "--sessions-dir", str( tmp_path ), "--now-epoch", str( NOW ) ] )
        assert rc == 0
        out = capsys.readouterr().out
        assert "DRY-RUN" in out

    def test_apply_flag_moves( self, tmp_path, monkeypatch ):
        monkeypatch.setattr( sbj, "collect_live_hashes", lambda *a, **k: set() )
        buf = tmp_path / "cc-buffer-dead0001.jsonl"
        buf.write_text( json.dumps( { "message": "x", "direction": "ai_to_ai" } ) + "\n" )
        os.utime( buf, ( NOW - 50 * HOUR, NOW - 50 * HOUR ) )
        rc = sbj.main( [ "--sessions-dir", str( tmp_path ), "--quarantine-dir",
                         str( tmp_path / "q" ), "--apply", "--now-epoch", str( NOW ) ] )
        assert rc == 0
        assert not buf.exists()
        assert ( tmp_path / "q" / "cc-buffer-dead0001.jsonl" ).exists()
