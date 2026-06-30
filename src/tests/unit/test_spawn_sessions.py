#!/usr/bin/env python3
"""
Unit tests for src/lupin_mcp/session_spawner.py — the manager-spawned headless
reviewer orchestration. All subprocess side effects are injected via a fake
runner; manifests live in a tmp dir. Target: 100% line + branch coverage.

See: src/rnd/v0.1.7/2026.05.28-manager-spawned-reviewers.md
"""
import asyncio
import importlib
import json
import os
import sys
from pathlib import Path

import pytest
from unittest.mock import MagicMock, patch

# Bootstrap
_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

from lupin_mcp.session_spawner import (
    render_task_prompt,
    persona_chain_csv,
    build_spawn_argv,
    spawn_sessions,
    dismiss_sessions,
    list_spawned_sessions,
    reap_stale_spawned,
    resolve_manager_identity,
    resolve_spawn_config,
    default_runner,
    quick_smoke_test,
    _manifest_path,
    _read_manifest,
    _write_manifest,
    _capture_reap_identity,
    _slug,
    DEFAULT_SPAWN_CAP,
)


class _FakeConfigMgr:
    """ConfigurationManager test double: returns configured values or default."""
    def __init__( self, values=None ):
        self.values = values or {}
    def get( self, key, default=None, return_type="string", silent=False ):
        return self.values.get( key, default )


# ── Fake runner ───────────────────────────────────────────────────────────────

class _Result:
    def __init__( self, returncode=0, stdout="", stderr="" ):
        self.returncode = returncode
        self.stdout     = stdout
        self.stderr     = stderr


class FakeRunner:
    """Records (argv, env) calls; returns a configurable returncode."""
    def __init__( self, returncode=0 ):
        self.returncode = returncode
        self.calls      = []

    def __call__( self, argv, env=None ):
        self.calls.append( ( argv, env ) )
        return _Result( returncode=self.returncode )


# ── render_task_prompt ────────────────────────────────────────────────────────

class TestRenderTaskPrompt:
    def test_token_substitution( self ):
        assert render_task_prompt( "Review {section} as {role}",
                                   { "section": "A", "role": "reviewer" } ) == "Review A as reviewer"

    def test_none_tokens_ok( self ):
        assert render_task_prompt( "plain text", None ) == "plain text"

    def test_unknown_placeholder_left_intact( self ):
        assert render_task_prompt( "keep {unknown}", { "x": "1" } ) == "keep {unknown}"

    def test_non_string_value_coerced( self ):
        assert render_task_prompt( "n={index}", { "index": 3 } ) == "n=3"

    def test_memento_appended_task_leads( self ):
        # Append semantics (Rick 2026-05-28): task leads, memento trails as reference.
        out = render_task_prompt( "do the work", {}, seed_memento="I authored this plan." )
        assert out.startswith( "do the work" )
        assert "Prior context" in out
        assert out.rstrip().endswith( "I authored this plan." )

    def test_blank_memento_ignored( self ):
        assert render_task_prompt( "task", {}, seed_memento="   " ) == "task"
        assert render_task_prompt( "task", {}, seed_memento=None ) == "task"


# ── persona_chain_csv ─────────────────────────────────────────────────────────

class TestPersonaChainCsv:
    """Normalization of spawn persona_preference → COSA_VOICE_PERSONA_CHAIN CSV."""

    def test_str_passed_through_stripped( self ):
        assert persona_chain_csv( "Rio" )      == "Rio"
        assert persona_chain_csv( "  Rio  " )  == "Rio"

    def test_str_inner_csv_verbatim( self ):
        # Inner whitespace is the server-side parser's job — outer strip only
        assert persona_chain_csv( "Rio, Krishna ,*" ) == "Rio, Krishna ,*"

    def test_list_joined_with_commas( self ):
        assert persona_chain_csv( [ "Rio", "Krishna", "*" ] ) == "Rio,Krishna,*"

    def test_list_items_stripped_non_str_and_empty_skipped( self ):
        assert persona_chain_csv( [ " Rio ", 42, "", "   ", None, "*" ] ) == "Rio,*"

    def test_empty_or_invalid_inputs_return_none( self ):
        assert persona_chain_csv( None )    is None
        assert persona_chain_csv( "" )      is None
        assert persona_chain_csv( "   " )   is None
        assert persona_chain_csv( [] )      is None
        assert persona_chain_csv( [ 42 ] )  is None
        assert persona_chain_csv( 42 )      is None
        assert persona_chain_csv( { "x": 1 } ) is None


# ── build_spawn_argv ──────────────────────────────────────────────────────────

class TestBuildSpawnArgv:
    def test_basic( self ):
        argv = build_spawn_argv( "/s.sh", "sess-1", "do it" )
        assert argv == [ "bash", "/s.sh", "--headless", "sess-1", "--prompt", "do it" ]

    def test_dry_run_flag( self ):
        argv = build_spawn_argv( "/s.sh", "sess-1", "do it", dry_run=True )
        assert "--dry-run" in argv and argv.index( "--dry-run" ) < argv.index( "sess-1" )

    def test_claude_args_inserted_before_prompt( self ):
        argv = build_spawn_argv( "/s.sh", "sess-1", "brief", claude_args=[ "--resume" ] )
        assert argv == [ "bash", "/s.sh", "--headless", "sess-1", "--resume", "--prompt", "brief" ]


# ── default_runner (real subprocess, trivial commands) ────────────────────────

class TestDefaultRunner:
    def test_zero_exit_no_env( self ):
        r = default_runner( [ "true" ] )
        assert r.returncode == 0

    def test_nonzero_exit( self ):
        r = default_runner( [ "false" ] )
        assert r.returncode == 1

    def test_env_merge_branch( self ):
        # env != None exercises the {**os.environ, **env} merge branch
        r = default_runner( [ "sh", "-c", 'test "$COSA_TEST_VAR" = "yes"' ],
                            env={ "COSA_TEST_VAR": "yes" } )
        assert r.returncode == 0


# ── manifest helpers ──────────────────────────────────────────────────────────

class TestManifestHelpers:
    def test_manifest_path_sanitizes( self, tmp_path ):
        p = _manifest_path( "abc/../weird id!", session_dir=tmp_path )
        assert p.parent == tmp_path
        assert p.name.startswith( "spawned-" ) and p.name.endswith( ".json" )
        assert "/" not in p.name and "!" not in p.name

    def test_read_missing_returns_empty( self, tmp_path ):
        assert _read_manifest( tmp_path / "nope.json" ) == []

    def test_read_corrupt_returns_empty( self, tmp_path ):
        bad = tmp_path / "bad.json"
        bad.write_text( "{not json" )
        assert _read_manifest( bad ) == []

    def test_read_non_list_returns_empty( self, tmp_path ):
        obj = tmp_path / "obj.json"
        obj.write_text( '{"a": 1}' )
        assert _read_manifest( obj ) == []

    def test_read_valid_list( self, tmp_path ):
        good = tmp_path / "good.json"
        good.write_text( '[{"session_name": "x"}]' )
        assert _read_manifest( good ) == [ { "session_name": "x" } ]

    def test_write_then_read_roundtrip( self, tmp_path ):
        p = tmp_path / "sub" / "m.json"
        assert _write_manifest( p, [ { "session_name": "y" } ] ) is True
        assert _read_manifest( p ) == [ { "session_name": "y" } ]

    def test_write_oserror_returns_false( self, tmp_path ):
        # Make the parent path a FILE so mkdir(parents=True) raises OSError
        blocker = tmp_path / "blocker"
        blocker.write_text( "i am a file" )
        p = blocker / "x.json"
        assert _write_manifest( p, [] ) is False


# ── _slug ─────────────────────────────────────────────────────────────────────

class TestSlug:
    def test_basic_lowercase( self ):
        assert _slug( "Tiberius" ) == "tiberius"

    def test_special_chars_collapsed( self ):
        assert _slug( "Mr. Radio!" ) == "mr-radio"

    def test_empty_becomes_anon( self ):
        assert _slug( "" ) == "anon"
        assert _slug( "###" ) == "anon"


# ── spawn_sessions ────────────────────────────────────────────────────────────

class TestSpawnSessions:
    def test_cap_too_low_raises( self, tmp_path ):
        with pytest.raises( ValueError ):
            spawn_sessions( 0, "t", "mgr", script_path="x", runner=FakeRunner(), session_dir=tmp_path )

    def test_cap_exceeded_raises( self, tmp_path ):
        with pytest.raises( ValueError ):
            spawn_sessions( 99, "t", "mgr", script_path="x", spawn_cap=8,
                            runner=FakeRunner(), session_dir=tmp_path )

    def test_happy_path_persists_and_keys_on_persona( self, tmp_path ):
        runner = FakeRunner( returncode=0 )
        res = spawn_sessions( 3, "Review {section} as {role}", "sid-0da4",
                              script_path="/s.sh", manager_persona="Tiberius",
                              role="reviewer", tokens={ "section": "A" },
                              runner=runner, session_dir=tmp_path )
        assert res[ "collection_topic" ] == "dm-tiberius"
        assert res[ "manager_persona" ] == "Tiberius"
        assert res[ "requested" ] == 3
        assert [ s[ "session_name" ] for s in res[ "spawned" ] ] == [
            "cc-reviewer-tiberius-1", "cc-reviewer-tiberius-2", "cc-reviewer-tiberius-3"
        ]
        # env carries lineage + headless markers
        _argv, env = runner.calls[ 0 ]
        assert env[ "COSA_VOICE_SPAWNED_BY" ] == "sid-0da4"
        assert env[ "COSA_VOICE_HEADLESS" ]   == "1"
        assert env[ "COSA_VOICE_ROLE" ]       == "reviewer"
        # owner-lineage drift fix: the manager's persona-at-spawn is frozen into the
        # child env so the child can stamp it onto its bridge (resolver snapshot).
        assert env[ "COSA_VOICE_SPAWNED_BY_PERSONA" ] == "Tiberius"
        # manifest persisted with 3 entries
        manifest = _read_manifest( _manifest_path( "sid-0da4", tmp_path ) )
        assert len( manifest ) == 3

    def test_persona_fallback_to_session_id( self, tmp_path ):
        # manager_persona omitted → topic keys on the session_id slug (stays on
        # `_slug`, so the hyphen survives: "Mgr-XYZ" → "dm-mgr-xyz"). This is the
        # surgical proof the session-id path is UNCHANGED by Phase 3.
        runner = FakeRunner()
        res = spawn_sessions( 1, "t", "Mgr-XYZ", script_path="x",
                              runner=runner, session_dir=tmp_path )
        assert res[ "collection_topic" ] == "dm-mgr-xyz"
        # no manager_persona resolved → NO snapshot env (resolver falls back to
        # re-derivation, the legacy behavior — the omitted-snapshot branch).
        _argv, env = runner.calls[ 0 ]
        assert "COSA_VOICE_SPAWNED_BY_PERSONA" not in env

    def test_persona_path_canonicalizes_accent_FLIP( self, tmp_path ):
        """Phase 3 FLIP: a PERSONA-derived topic/session name now routes through
        `persona_slug`, so "María" canonicalizes to "maria" (was the accent-leaky
        "maría" the old `_slug` produced, since "í".isalnum() is True). Revert the
        persona branch at session_spawner.py:315 to `_slug(manager_persona)` and
        both assertions fail. The session-id fallback stays on `_slug` — surgical."""
        res = spawn_sessions( 1, "t", "sid-maria", script_path="x",
                              manager_persona="María", role="author",
                              runner=FakeRunner(), session_dir=tmp_path )
        assert res[ "collection_topic" ] == "dm-maria"
        assert res[ "spawned" ][ 0 ][ "session_name" ] == "cc-author-maria-1"

    def test_multiword_persona_topic_underscore_session_hyphen_FLIP( self, tmp_path ):
        """One-name mandate (2026-06-22): for a MULTI-WORD persona the DM/collection
        topic and the tmux SESSION name use DIFFERENT separators and each MUST be the
        canonical form of its own convention:
          • collection_topic → "dm-mr_radio"  (persona_slug sep="_" — byte-identical
            to _derive_dm_topic / _dm_topic_for / every *_gateway.dm_topic_for).
          • session_name     → "cc-author-mr-radio-1"  (persona_slug sep="-" — the
            tmux cc-<role>-<persona>-<n> convention the sweep's scan_tmux_mismatches
            validates with sep="-").
        FLIP: revert dm_persona_key to sep="-" → the topic assertion fails (the old
        DIVERGENT "dm-mr-radio" regenerates). Revert name_persona_key to sep="_" →
        the session-name assertion fails. Single-word personas (Tiberius/María) can
        NEVER catch this — they have no internal space to separate."""
        res = spawn_sessions( 1, "t", "sid-radio", script_path="x",
                              manager_persona="Mr. Radio", role="author",
                              runner=FakeRunner(), session_dir=tmp_path )
        assert res[ "collection_topic" ] == "dm-mr_radio"
        assert res[ "spawned" ][ 0 ][ "session_name" ] == "cc-author-mr-radio-1"

    def test_punctuation_only_persona_falls_back_to_anon( self, tmp_path ):
        """The `or "anon"` guard preserves `_slug`'s never-empty contract when a
        truthy persona canonicalizes to "" (e.g. emoji/punct-only)."""
        res = spawn_sessions( 1, "t", "sid-anon", script_path="x",
                              manager_persona="🦉", role="reviewer",
                              runner=FakeRunner(), session_dir=tmp_path )
        assert res[ "collection_topic" ] == "dm-anon"

    def test_failed_spawn_not_persisted( self, tmp_path ):
        runner = FakeRunner( returncode=1 )  # every spawn "fails"
        res = spawn_sessions( 2, "t", "sid-fail", script_path="x",
                              runner=runner, session_dir=tmp_path )
        assert all( s[ "status" ] == "failed" for s in res[ "spawned" ] )
        # no successful spawns → manifest never written
        assert not _manifest_path( "sid-fail", tmp_path ).exists()

    def test_dry_run_does_not_persist( self, tmp_path ):
        runner = FakeRunner( returncode=0 )
        res = spawn_sessions( 2, "t", "sid-dry", script_path="x", dry_run=True,
                              runner=runner, session_dir=tmp_path )
        assert res[ "dry_run" ] is True
        assert "--dry-run" in runner.calls[ 0 ][ 0 ]
        assert not _manifest_path( "sid-dry", tmp_path ).exists()

    def test_append_to_existing_manifest( self, tmp_path ):
        runner = FakeRunner()
        spawn_sessions( 1, "t", "sid-a", script_path="x", manager_persona="Rio",
                        runner=runner, session_dir=tmp_path )
        spawn_sessions( 1, "t", "sid-a", script_path="x", manager_persona="Rio",
                        runner=runner, session_dir=tmp_path )
        assert len( _read_manifest( _manifest_path( "sid-a", tmp_path ) ) ) == 2

    def test_role_in_session_name( self, tmp_path ):
        res = spawn_sessions( 1, "t", "sid-x", script_path="x", manager_persona="Tiberius",
                              role="author", runner=FakeRunner(), session_dir=tmp_path )
        assert res[ "spawned" ][ 0 ][ "session_name" ] == "cc-author-tiberius-1"

    def test_no_collision_across_roles( self, tmp_path ):
        # 3 reviewers then 1 author for the same manager → author does NOT clash
        # with reviewer #1 (role is in the name).
        runner = FakeRunner()
        spawn_sessions( 3, "t", "sid-c", script_path="x", manager_persona="Rio",
                        role="reviewer", runner=runner, session_dir=tmp_path )
        author = spawn_sessions( 1, "t", "sid-c", script_path="x", manager_persona="Rio",
                                 role="author", runner=runner, session_dir=tmp_path )
        assert author[ "spawned" ][ 0 ][ "session_name" ] == "cc-author-rio-1"
        names = [ r[ "session_name" ] for r in _read_manifest( _manifest_path( "sid-c", tmp_path ) ) ]
        assert names == [ "cc-reviewer-rio-1", "cc-reviewer-rio-2", "cc-reviewer-rio-3", "cc-author-rio-1" ]

    def test_lowest_free_index_across_batches( self, tmp_path ):
        runner = FakeRunner()
        spawn_sessions( 3, "t", "sid-b", script_path="x", manager_persona="Rio", runner=runner, session_dir=tmp_path )
        batch2 = spawn_sessions( 2, "t", "sid-b", script_path="x", manager_persona="Rio", runner=runner, session_dir=tmp_path )
        assert [ s[ "session_name" ] for s in batch2[ "spawned" ] ] == [ "cc-reviewer-rio-4", "cc-reviewer-rio-5" ]

    def test_persona_chain_env_injected_for_str_preference( self, tmp_path ):
        # The transport fix (2026-06-11): persona_preference must reach EVERY
        # child's env as COSA_VOICE_PERSONA_CHAIN — previously a silent no-op.
        runner = FakeRunner( returncode=0 )
        spawn_sessions( 2, "t", "sid-chain-s", script_path="x",
                        persona_preference="Rio,Krishna,*",
                        runner=runner, session_dir=tmp_path )
        assert len( runner.calls ) == 2
        for _argv, env in runner.calls:
            assert env[ "COSA_VOICE_PERSONA_CHAIN" ] == "Rio,Krishna,*"
            # chain rides ALONGSIDE the standard lineage markers
            assert env[ "COSA_VOICE_SPAWNED_BY" ] == "sid-chain-s"
            assert env[ "COSA_VOICE_HEADLESS" ]   == "1"
            assert env[ "COSA_VOICE_ROLE" ]       == "reviewer"

    def test_persona_chain_env_injected_for_list_preference( self, tmp_path ):
        runner = FakeRunner( returncode=0 )
        res = spawn_sessions( 1, "t", "sid-chain-l", script_path="x",
                              persona_preference=[ "Rio", "Krishna" ],
                              runner=runner, session_dir=tmp_path )
        _argv, env = runner.calls[ 0 ]
        assert env[ "COSA_VOICE_PERSONA_CHAIN" ] == "Rio,Krishna"
        # the raw preference is echoed in the result roster
        assert res[ "persona_preference" ] == [ "Rio", "Krishna" ]

    def test_persona_chain_env_absent_for_none_preference( self, tmp_path ):
        runner = FakeRunner( returncode=0 )
        spawn_sessions( 1, "t", "sid-chain-n", script_path="x",
                        runner=runner, session_dir=tmp_path )
        _argv, env = runner.calls[ 0 ]
        assert "COSA_VOICE_PERSONA_CHAIN" not in env

    def test_persona_chain_env_absent_for_empty_preference( self, tmp_path ):
        runner = FakeRunner( returncode=0 )
        spawn_sessions( 1, "t", "sid-chain-e", script_path="x",
                        persona_preference="   ",
                        runner=runner, session_dir=tmp_path )
        _argv, env = runner.calls[ 0 ]
        assert "COSA_VOICE_PERSONA_CHAIN" not in env

    def test_index_token_reflects_assigned_number( self, tmp_path ):
        # After a batch of 3, the next batch's {index} token = 4, not 1
        runner = FakeRunner()
        spawn_sessions( 3, "t", "sid-i", script_path="x", manager_persona="Rio", runner=runner, session_dir=tmp_path )
        # render uses {index}; confirm via the rendered prompt reaching the script arg
        spawn_sessions( 1, "msg #{index}", "sid-i", script_path="x", manager_persona="Rio",
                        runner=runner, session_dir=tmp_path )
        # the 5th call argv (index 4 of sid-i) carries "msg #4"
        last_argv = runner.calls[ -1 ][ 0 ]
        assert "msg #4" in last_argv


# ── dismiss_sessions ──────────────────────────────────────────────────────────

class TestDismissSessions:
    def _seed( self, tmp_path, names ):
        _write_manifest( _manifest_path( "mgr", tmp_path ),
                         [ { "session_name": n, "requested_role": "reviewer" } for n in names ] )

    def test_dismiss_explicit_subset_rewrites_manifest( self, tmp_path ):
        self._seed( tmp_path, [ "a", "b", "c" ] )
        runner = FakeRunner( returncode=0 )
        res = dismiss_sessions( "mgr", session_names=[ "a" ], reason="done",
                                runner=runner, session_dir=tmp_path )
        assert res[ "dismissed" ][ 0 ] == { "session_name": "a", "status": "killed" }
        assert sorted( res[ "remaining" ] ) == [ "b", "c" ]
        assert runner.calls[ 0 ][ 0 ] == [ "tmux", "kill-session", "-t", "a" ]
        assert len( _read_manifest( _manifest_path( "mgr", tmp_path ) ) ) == 2

    def test_dismiss_all_deletes_manifest( self, tmp_path ):
        self._seed( tmp_path, [ "a", "b" ] )
        res = dismiss_sessions( "mgr", runner=FakeRunner( returncode=0 ), session_dir=tmp_path )
        assert res[ "remaining" ] == []
        assert not _manifest_path( "mgr", tmp_path ).exists()

    def test_already_gone_status( self, tmp_path ):
        self._seed( tmp_path, [ "a" ] )
        res = dismiss_sessions( "mgr", runner=FakeRunner( returncode=1 ), session_dir=tmp_path )
        assert res[ "dismissed" ][ 0 ][ "status" ] == "already_gone"

    def test_dismiss_with_no_manifest_unlink_noop( self, tmp_path ):
        # No manifest exists → targets empty → remaining empty → unlink misses (caught)
        res = dismiss_sessions( "ghost", runner=FakeRunner(), session_dir=tmp_path )
        assert res[ "dismissed" ] == [] and res[ "remaining" ] == []

    def test_write_memento_and_reason_echoed( self, tmp_path ):
        self._seed( tmp_path, [ "a" ] )
        res = dismiss_sessions( "mgr", reason="cascade complete", write_memento=False,
                                runner=FakeRunner(), session_dir=tmp_path )
        assert res[ "reason" ] == "cascade complete" and res[ "write_memento" ] is False


# ── _capture_reap_identity + dismiss bridge-unlink edge arcs ──────────────────

class TestCaptureReapIdentityEdges:
    """Defensive arcs of the pre-kill bridge-identity capture (never raises)."""

    def test_glob_oserror_returns_none( self ):
        bad_dir = MagicMock()
        bad_dir.glob.side_effect = OSError( "boom" )
        assert _capture_reap_identity( bad_dir, "sess-x" ) is None

    def test_buffer_and_listener_bridges_skipped( self, tmp_path ):
        ( tmp_path / "cc-buffer-1.json"   ).write_text( json.dumps( { "tmux_session": "sess-x" } ) )
        ( tmp_path / "cc-listener-1.json" ).write_text( json.dumps( { "tmux_session": "sess-x" } ) )
        assert _capture_reap_identity( tmp_path, "sess-x" ) is None

    def test_tmux_session_mismatch_skipped( self, tmp_path ):
        ( tmp_path / "cc-1.json" ).write_text( json.dumps( { "tmux_session": "other" } ) )
        assert _capture_reap_identity( tmp_path, "sess-x" ) is None

    def test_sender_id_build_failure_tolerated( self, tmp_path ):
        # build_sender_id_for_cc blowing up must not break the capture
        ( tmp_path / "cc-1.json" ).write_text( json.dumps(
            { "tmux_session": "sess-x", "stable_session_id": "sid-1",
              "voice_persona": { "name": "Rio" } } ) )
        with patch( "lupin_cli.claude_code.hooks.lib.session_bridge.build_sender_id_for_cc",
                    side_effect=RuntimeError( "bridge lib broken" ) ):
            ident = _capture_reap_identity( tmp_path, "sess-x" )
        assert ident[ "session_id" ]        == "sid-1"
        assert ident[ "sender_id" ]         is None
        assert ident[ "persona" ][ "name" ] == "Rio"


class TestDismissBridgeUnlinkEdges:
    """Defensive arcs of the post-kill bridge unlink (producer never breaks the reap)."""

    def _seed( self, tmp_path, names ):
        """
        Write a one-manager manifest containing `names`.

        Requires:
            - tmp_path is a writable Path (pytest fixture)
            - names is a list of tmux session-name strings

        Ensures:
            - the manifest for manager "mgr" exists in tmp_path with one
              reviewer record per name
        """
        _write_manifest( _manifest_path( "mgr", tmp_path ),
                         [ { "session_name": n, "requested_role": "reviewer" } for n in names ] )

    def test_identity_with_none_bridge_path_skips_unlink_still_emits( self, tmp_path ):
        self._seed( tmp_path, [ "a" ] )
        emitted = []
        with patch( "lupin_mcp.session_spawner._capture_reap_identity",
                    return_value={ "bridge_path": None, "persona": None,
                                   "sender_id": None, "session_id": None } ):
            res = dismiss_sessions( "mgr", runner=FakeRunner( returncode=0 ), session_dir=tmp_path,
                                    emit_reap_fn=lambda ident, reason: emitted.append( ident ) )
        assert res[ "bridges_deleted" ] == 0
        assert len( emitted ) == 1

    def test_unlink_failure_tolerated( self, tmp_path ):
        self._seed( tmp_path, [ "a" ] )
        ghost = tmp_path / "ghost-bridge.json"   # never created → unlink raises FileNotFoundError
        with patch( "lupin_mcp.session_spawner._capture_reap_identity",
                    return_value={ "bridge_path": ghost, "persona": None,
                                   "sender_id": None, "session_id": "s" } ):
            res = dismiss_sessions( "mgr", runner=FakeRunner( returncode=0 ), session_dir=tmp_path,
                                    emit_reap_fn=lambda ident, reason: None )
        assert res[ "bridges_deleted" ] == 0
        assert res[ "dismissed" ][ 0 ][ "status" ] == "killed"


# ── list_spawned_sessions ─────────────────────────────────────────────────────

class TestListSpawnedSessions:
    def test_empty_when_no_manifest( self, tmp_path ):
        res = list_spawned_sessions( "nobody", runner=FakeRunner(), session_dir=tmp_path )
        assert res[ "count" ] == 0 and res[ "sessions" ] == []

    def test_live_and_dead( self, tmp_path ):
        _write_manifest( _manifest_path( "mgr", tmp_path ),
                         [ { "session_name": "a", "requested_role": "author" },
                           { "session_name": "b" } ] )
        # returncode 0 → all live
        res = list_spawned_sessions( "mgr", runner=FakeRunner( returncode=0 ), session_dir=tmp_path )
        assert res[ "count" ] == 2
        assert res[ "sessions" ][ 0 ] == { "session_name": "a", "requested_role": "author",
                                           "status": "live", "alive": True }
        # default requested_role when missing
        assert res[ "sessions" ][ 1 ][ "requested_role" ] == "reviewer"

    def test_dead_status( self, tmp_path ):
        _write_manifest( _manifest_path( "mgr", tmp_path ), [ { "session_name": "a" } ] )
        res = list_spawned_sessions( "mgr", runner=FakeRunner( returncode=1 ), session_dir=tmp_path )
        assert res[ "sessions" ][ 0 ][ "status" ] == "dead" and res[ "sessions" ][ 0 ][ "alive" ] is False


# ── module smoke body ─────────────────────────────────────────────────────────

class TestModuleSmoke:
    def test_quick_smoke_test_runs_clean( self ):
        quick_smoke_test()


def test_default_spawn_cap_constant():
    assert DEFAULT_SPAWN_CAP == 8


# ── reap_stale_spawned ────────────────────────────────────────────────────────

class TestReapStaleSpawned:
    def _seed( self, tmp_path, names ):
        _write_manifest( _manifest_path( "mgr", tmp_path ),
                         [ { "session_name": n, "requested_role": "reviewer" } for n in names ] )

    def test_none_stale_no_side_effects( self, tmp_path ):
        self._seed( tmp_path, [ "a", "b" ] )
        runner = FakeRunner()
        res = reap_stale_spawned( "mgr", is_stale=lambda n: False, runner=runner, session_dir=tmp_path )
        assert res[ "reaped" ] == []
        assert sorted( res[ "remaining" ] ) == [ "a", "b" ]
        assert runner.calls == []  # no tmux touched
        assert len( _read_manifest( _manifest_path( "mgr", tmp_path ) ) ) == 2  # manifest intact

    def test_some_stale_reaped( self, tmp_path ):
        self._seed( tmp_path, [ "a", "b", "c" ] )
        runner = FakeRunner( returncode=0 )
        res = reap_stale_spawned( "mgr", is_stale=lambda n: n in ( "a", "c" ),
                                  reason="idle", runner=runner, session_dir=tmp_path )
        assert sorted( res[ "reaped" ] ) == [ "a", "c" ]
        assert res[ "remaining" ] == [ "b" ]
        # only b remains in the manifest
        assert [ r[ "session_name" ] for r in _read_manifest( _manifest_path( "mgr", tmp_path ) ) ] == [ "b" ]


# ── resolve_manager_identity ──────────────────────────────────────────────────

class TestResolveManagerIdentity:
    def test_none_meta_uses_fallback( self ):
        sid, persona = resolve_manager_identity( None, fallback_session_id="fb" )
        assert sid == "fb" and persona is None

    def test_prefers_stable_session_id_and_persona_name( self ):
        meta = { "stable_session_id": "stable-1", "session_id": "trans-2",
                 "voice_persona": { "name": "Tiberius", "display_name": "Tiberius" } }
        sid, persona = resolve_manager_identity( meta )
        assert sid == "stable-1" and persona == "Tiberius"

    def test_falls_back_to_session_id_and_display_name( self ):
        meta = { "session_id": "trans-2", "voice_persona": { "display_name": "Mr. Radio" } }
        sid, persona = resolve_manager_identity( meta )
        assert sid == "trans-2" and persona == "Mr. Radio"

    def test_missing_persona_block( self ):
        sid, persona = resolve_manager_identity( { "session_id": "s" } )
        assert sid == "s" and persona is None


# ── resolve_spawn_config ──────────────────────────────────────────────────────

class TestResolveSpawnConfig:
    def test_defaults_when_none( self ):
        cfg = resolve_spawn_config( None )
        assert cfg == { "spawn_cap": 8, "ack_timeout_seconds": 120, "write_memento_default": True }

    def test_reads_from_config_mgr( self ):
        mgr = _FakeConfigMgr( {
            "cc session spawn max reviewers"                 : 5,
            "cc session spawn reviewer ack timeout seconds"  : 90,
            "cc session spawn write memento default"         : False,
        } )
        cfg = resolve_spawn_config( mgr )
        assert cfg == { "spawn_cap": 5, "ack_timeout_seconds": 90, "write_memento_default": False }

    def test_missing_keys_fall_back_to_defaults( self ):
        cfg = resolve_spawn_config( _FakeConfigMgr( {} ) )
        assert cfg[ "spawn_cap" ] == 8 and cfg[ "ack_timeout_seconds" ] == 120


# ── MCP-WRAPPER LAYER: dismiss_sessions param-typing regression (2026-06-01) ──
#
# Bug (live, 2026-05-31): the @mcp.tool wrapper cosa_voice_mcp.dismiss_sessions
# declared `session_names=None` and `write_memento=None` WITHOUT type
# annotations. FastMCP builds each tool's JSON input-schema from the function's
# type hints, so untyped params emitted a schema entry with NO `type` field. An
# MCP client then had no array/boolean contract: a passed list arrived
# stringified (the inner `for name in targets:` loop char-iterated it, "killing"
# tmux sessions "c","c","-",...) and `write_memento=False` arrived as the string
# "false". The inner-fn tests above never caught this because they call
# session_spawner.dismiss_sessions directly, bypassing the @mcp.tool schema layer.
#
# Fix: annotate the wrapper `session_names: Optional[List[str]]` +
# `write_memento: Optional[bool]` so FastMCP emits array/boolean and coerces
# correctly. These tests are the durable lock: (a)/(b) assert the regenerated
# schema; (c)-(e) drive FastMCP's own deserialization (the path a direct Python
# call cannot reproduce, since Python never stringifies a list).
# Delegated fix — DM brief from Tiberius (session b8a9f332), 2026-06-01.


@pytest.fixture( scope="module" )
def cv_mcp():
    """
    Import the cosa-voice MCP module that holds the @mcp.tool wrappers.

    Ensures:
        - returns the imported `lupin_mcp.cosa_voice_mcp` module object
        - import is side-effect-tolerant: module-level `_validate_repo_account`
          never raises (it logs + returns) and the session-id watcher is a
          daemon thread, so it does not block pytest teardown
    """
    return importlib.import_module( "lupin_mcp.cosa_voice_mcp" )


def _type_options( prop_schema ):
    """
    Collect the JSON-schema `type` tokens a property allows, flattening `anyOf`.

    Requires:
        - prop_schema is a dict (a single JSON-schema property node)

    Ensures:
        - returns a set of type strings drawn from the node's own `type` plus
          every `anyOf` branch's `type` (e.g. an Optional[List[str]] node yields
          {"array", "null"})
    """
    opts = set()
    if "type" in prop_schema:
        opts.add( prop_schema[ "type" ] )
    for branch in prop_schema.get( "anyOf", [] ):
        if "type" in branch:
            opts.add( branch[ "type" ] )
    return opts


class TestDismissSessionsWrapperSchema:
    """(a)/(b): the regenerated tool schema must type the params (regression lock)."""

    def test_session_names_schema_is_array_of_strings( self, cv_mcp ):
        sn = cv_mcp.dismiss_sessions.parameters[ "properties" ][ "session_names" ]
        assert "array" in _type_options( sn ), f"session_names must allow array, got {sn}"
        array_branch = sn if sn.get( "type" ) == "array" else next(
            b for b in sn.get( "anyOf", [] ) if b.get( "type" ) == "array"
        )
        assert array_branch[ "items" ][ "type" ] == "string", \
            f"session_names items must be strings, got {array_branch}"

    def test_write_memento_schema_is_boolean( self, cv_mcp ):
        wm = cv_mcp.dismiss_sessions.parameters[ "properties" ][ "write_memento" ]
        assert "boolean" in _type_options( wm ), f"write_memento must allow boolean, got {wm}"

    def test_reason_schema_unchanged_string( self, cv_mcp ):
        # Control: the already-typed sibling param stays a plain string.
        reason = cv_mcp.dismiss_sessions.parameters[ "properties" ][ "reason" ]
        assert reason[ "type" ] == "string"


class TestDismissSessionsWrapperCoercion:
    """(c)-(d): drive FastMCP's deserialization; list/bool must survive intact."""

    def _patch_wrapper_deps( self, cv_mcp, monkeypatch, captured, write_memento_default=True ):
        """
        Stub the wrapper's host-side collaborators so the only behavior under
        test is FastMCP arg-coercion + the wrapper's write_memento ternary.
        The inner `session_spawner.dismiss_sessions` is replaced by a spy that
        records exactly what it received.
        """
        import lupin_mcp.session_spawner as ss

        def _spy_dismiss( manager_session_id, *, session_names=None, reason="", write_memento=True, **_kw ):
            captured[ "manager" ]       = manager_session_id
            captured[ "session_names" ] = session_names
            captured[ "reason" ]        = reason
            captured[ "write_memento" ] = write_memento
            return { "dismissed": [], "remaining": [], "manager_session_id": manager_session_id }

        monkeypatch.setattr( cv_mcp, "_wait_for_sender_id", lambda: "sender" )
        monkeypatch.setattr( cv_mcp, "_get_cc_metadata",   lambda: { "session_id": "abc12345" } )
        monkeypatch.setattr( cv_mcp, "_spawn_config_mgr",  lambda: None )
        monkeypatch.setattr( ss, "resolve_manager_identity",
                             lambda meta, fallback_session_id=None: ( "mgr-sid", "Krishna" ) )
        monkeypatch.setattr( ss, "resolve_spawn_config",
                             lambda mgr: { "spawn_cap": 8, "ack_timeout_seconds": 120,
                                           "write_memento_default": write_memento_default } )
        monkeypatch.setattr( ss, "dismiss_sessions", _spy_dismiss )

    def test_list_arg_arrives_as_list_not_chars( self, cv_mcp, monkeypatch ):
        """A two-item list must reach the inner fn as a real list — NOT char-iterated."""
        captured = {}
        self._patch_wrapper_deps( cv_mcp, monkeypatch, captured )
        asyncio.run( cv_mcp.dismiss_sessions.run(
            { "session_names": [ "alpha", "beta" ], "write_memento": False, "reason": "cleanup" }
        ) )
        assert isinstance( captured[ "session_names" ], list )
        assert captured[ "session_names" ] == [ "alpha", "beta" ]   # not ['a','l','p','h','a',...]
        assert captured[ "reason" ] == "cleanup"

    def test_write_memento_false_stays_bool_not_string( self, cv_mcp, monkeypatch ):
        """write_memento=False must reach the inner fn as bool False, NOT the string 'false'."""
        captured = {}
        self._patch_wrapper_deps( cv_mcp, monkeypatch, captured )
        asyncio.run( cv_mcp.dismiss_sessions.run(
            { "session_names": [ "x" ], "write_memento": False }
        ) )
        assert captured[ "write_memento" ] is False                 # explicit-value ternary arm

    def test_none_session_names_and_ini_default_write_memento( self, cv_mcp, monkeypatch ):
        """
        Omitting both args: session_names → None (inner reaps all), and
        write_memento → the INI default (the `write_memento is None` ternary arm).
        """
        captured = {}
        self._patch_wrapper_deps( cv_mcp, monkeypatch, captured, write_memento_default=True )
        asyncio.run( cv_mcp.dismiss_sessions.run( {} ) )
        assert captured[ "session_names" ] is None
        assert captured[ "write_memento" ] is True                  # came from cfg default, not "false"

    def test_wrapper_threads_default_reconciler( self, cv_mcp, monkeypatch ):
        """d647b531: the LIVE reap entrypoint MUST wire the real reap-RECONCILE
        producer, so a reaped worker's non-terminal store items get reconciled
        instead of orphaning. session_spawner defaults reconcile_items_fn=None
        (hermetic); the wrapper is the production opt-in to the mutation."""
        import lupin_mcp.session_spawner as ss
        captured = {}
        def _spy_dismiss( manager_session_id, *, reconcile_items_fn=None, **_kw ):
            captured[ "reconcile_items_fn" ] = reconcile_items_fn
            return { "dismissed": [], "remaining": [], "manager_session_id": manager_session_id }
        monkeypatch.setattr( cv_mcp, "_wait_for_sender_id", lambda: "sender" )
        monkeypatch.setattr( cv_mcp, "_get_cc_metadata",   lambda: { "session_id": "abc12345" } )
        monkeypatch.setattr( cv_mcp, "_spawn_config_mgr",  lambda: None )
        monkeypatch.setattr( ss, "resolve_manager_identity",
                             lambda meta, fallback_session_id=None: ( "mgr-sid", "Krishna" ) )
        monkeypatch.setattr( ss, "resolve_spawn_config",
                             lambda mgr: { "spawn_cap": 8, "ack_timeout_seconds": 120,
                                           "write_memento_default": True } )
        monkeypatch.setattr( ss, "dismiss_sessions", _spy_dismiss )
        asyncio.run( cv_mcp.dismiss_sessions.run( {} ) )
        assert captured[ "reconcile_items_fn" ] is ss._default_reconcile_store_items
