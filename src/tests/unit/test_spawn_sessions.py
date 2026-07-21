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
    _scan_persona_by_tmux_session,
    _build_identity_warning,
    _slug,
    DEFAULT_SPAWN_CAP,
    PERSONA_STATE_ALLOCATED,
    PERSONA_STATE_NONE,
    PERSONA_STATE_UNKNOWN,
    PERSONA_STATE_UNREADABLE,
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


# ── spawn_sessions model-directive (argv threading + roster echo) ─────────────

class TestSpawnSessionsModel:
    """Model-directive (2026-07-02): the resolved model threads to `--model` via
    the claude_args seam and is echoed on every roster entry + at the top level."""

    def _argv_of( self, runner, i=0 ):
        return runner.calls[ i ][ 0 ]

    def test_model_threads_into_argv_before_prompt( self, tmp_path ):
        runner = FakeRunner( returncode=0 )
        res = spawn_sessions( 1, "t", "sid-m", script_path="/s.sh", manager_persona="Rio",
                              model="claude-opus-4-8", runner=runner, session_dir=tmp_path )
        argv = self._argv_of( runner )
        # --model <id> present, and inserted BEFORE --prompt (the claude_args seam)
        assert "--model" in argv
        assert argv[ argv.index( "--model" ) + 1 ] == "claude-opus-4-8"
        assert argv.index( "--model" ) < argv.index( "--prompt" )
        # echoed on the roster entry AND the top-level result
        assert res[ "spawned" ][ 0 ][ "model" ] == "claude-opus-4-8"
        assert res[ "model" ] == "claude-opus-4-8"

    def test_model_none_omits_flag_and_echoes_none( self, tmp_path ):
        runner = FakeRunner( returncode=0 )
        res = spawn_sessions( 1, "t", "sid-mn", script_path="/s.sh", manager_persona="Rio",
                              runner=runner, session_dir=tmp_path )
        argv = self._argv_of( runner )
        assert "--model" not in argv          # fail-open: no flag → inherit user default
        assert res[ "spawned" ][ 0 ][ "model" ] is None
        assert res[ "model" ] is None

    def test_empty_model_string_omits_flag( self, tmp_path ):
        # An empty string is falsy → treated as "no model" (no --model flag).
        runner = FakeRunner( returncode=0 )
        res = spawn_sessions( 1, "t", "sid-me", script_path="/s.sh", manager_persona="Rio",
                              model="", runner=runner, session_dir=tmp_path )
        assert "--model" not in self._argv_of( runner )
        assert res[ "model" ] == ""

    def test_model_on_every_child_in_a_batch( self, tmp_path ):
        runner = FakeRunner( returncode=0 )
        res = spawn_sessions( 3, "t", "sid-mb", script_path="/s.sh", manager_persona="Rio",
                              model="claude-opus-4-8", runner=runner, session_dir=tmp_path )
        assert all( s[ "model" ] == "claude-opus-4-8" for s in res[ "spawned" ] )
        for i in range( 3 ):
            assert "--model" in self._argv_of( runner, i )

    def test_model_coexists_with_dry_run( self, tmp_path ):
        runner = FakeRunner( returncode=0 )
        spawn_sessions( 1, "t", "sid-md", script_path="/s.sh", dry_run=True,
                        model="claude-opus-4-8", runner=runner, session_dir=tmp_path )
        argv = self._argv_of( runner )
        # both flags present; --dry-run precedes the session name, --model follows it
        assert "--dry-run" in argv and "--model" in argv
        assert argv.index( "--dry-run" ) < argv.index( "--model" )


# ── list_spawned_sessions model surfacing (bug 35bdd68f) ──────────────────────

class TestListSpawnedSessionsModel:
    """Bug 35bdd68f (2026-07-07): the roster row must SURFACE the persisted model
    id so the fleet can answer 'what LLM is this worker running' without asking the
    worker. Model is captured + persisted at spawn (see TestSpawnSessionsModel);
    the bug was the read-side row builder dropping it. A pre-fix record (no 'model'
    key) surfaces None — honest absence, never a guessed default."""

    def _seed( self, tmp_path, records ):
        _write_manifest( _manifest_path( "mgr", tmp_path ), records )

    def test_model_surfaces_per_row_echoing_persisted_value( self, tmp_path ):
        # two DIFFERENT model ids prove the row echoes the PERSISTED value,
        # not a hardcoded opus default.
        self._seed( tmp_path, [
            { "session_name": "cc-author-rio",  "requested_role": "author", "model": "claude-opus-4-8" },
            { "session_name": "cc-tester-clay", "requested_role": "tester", "model": "claude-sonnet-5"  },
        ] )
        res  = list_spawned_sessions( "mgr", runner=FakeRunner( returncode=0 ), session_dir=tmp_path )
        rows = { r[ "session_name" ]: r for r in res[ "sessions" ] }
        assert rows[ "cc-author-rio"  ][ "model" ] == "claude-opus-4-8"
        assert rows[ "cc-tester-clay" ][ "model" ] == "claude-sonnet-5"
        # contract: EVERY row carries the key, not just the asserted ones
        assert all( "model" in r for r in res[ "sessions" ] )

    def test_prefix_record_without_model_surfaces_none( self, tmp_path ):
        # a record persisted BEFORE model capture has no 'model' key
        self._seed( tmp_path, [ { "session_name": "cc-legacy", "requested_role": "reviewer" } ] )
        res = list_spawned_sessions( "mgr", runner=FakeRunner( returncode=0 ), session_dir=tmp_path )
        row = res[ "sessions" ][ 0 ]
        assert "model" in row            # key present — honest absence, not omission
        assert row[ "model" ] is None    # None, never a guessed default


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
                                           "status": "live", "alive": True, "model": None,
                                           "persona": None, "persona_state": "unknown_no_bridge",
                                           "identity_verified": False, "age_seconds": None }
        # default requested_role when missing
        assert res[ "sessions" ][ 1 ][ "requested_role" ] == "reviewer"

    def test_dead_status( self, tmp_path ):
        _write_manifest( _manifest_path( "mgr", tmp_path ), [ { "session_name": "a" } ] )
        res = list_spawned_sessions( "mgr", runner=FakeRunner( returncode=1 ), session_dir=tmp_path )
        assert res[ "sessions" ][ 0 ][ "status" ] == "dead" and res[ "sessions" ][ 0 ][ "alive" ] is False


# ── list_spawned_sessions IDENTITY axis (row 6f8fd858) ────────────────────────
#
# The defect: the roster answered LIVENESS while presenting as a health check,
# so a manager asking "who is in this seat?" got a green row and learned
# nothing — then briefed the wrong session by name. These tests pin the four
# identity states apart, and pin the roster's refusal to let a green liveness
# row stand in for identity verification.
#
# Bridge files here are REAL files written to a real (tmp) session_dir and read
# by the real scanner. Nothing about the persona lookup is mocked — a mocked
# green is precisely the failure mode this row is about.

def _write_bridge( session_dir, filename, *, tmux_session=None, voice_persona="__omit__", raw=None ):
    """Write a real bridge file into session_dir; return its Path."""
    path = session_dir / filename
    if raw is not None:
        path.write_text( raw )
        return path
    data = { }
    if tmux_session is not None: data[ "tmux_session" ]  = tmux_session
    if voice_persona != "__omit__": data[ "voice_persona" ] = voice_persona
    path.write_text( json.dumps( data ) )
    return path


class TestScanPersonaByTmuxSession:
    def test_missing_dir_yields_empty_scan( self, tmp_path ):
        index, unattributable = _scan_persona_by_tmux_session( tmp_path / "does-not-exist" )
        assert index == { } and unattributable == 0

    def test_allocated_reads_the_name( self, tmp_path ):
        _write_bridge( tmp_path, "cc-1.json", tmux_session="seat-a",
                       voice_persona={ "name": "Krishna", "voice_id": "v1" } )
        index, _ = _scan_persona_by_tmux_session( tmp_path )
        assert index[ "seat-a" ] == { "persona": "Krishna", "persona_state": PERSONA_STATE_ALLOCATED }

    def test_allocated_name_is_stripped( self, tmp_path ):
        _write_bridge( tmp_path, "cc-1.json", tmux_session="seat-a", voice_persona={ "name": "  Rio  " } )
        index, _ = _scan_persona_by_tmux_session( tmp_path )
        assert index[ "seat-a" ][ "persona" ] == "Rio"

    def test_explicit_null_persona_is_none_not_unknown( self, tmp_path ):
        # THE distinction the row turns on: this child BOOTED and got nothing.
        # It must not read the same as a child with no bridge on disk at all.
        _write_bridge( tmp_path, "cc-1.json", tmux_session="seat-a", voice_persona=None )
        index, _ = _scan_persona_by_tmux_session( tmp_path )
        assert index[ "seat-a" ] == { "persona": None, "persona_state": PERSONA_STATE_NONE }

    def test_absent_persona_key_is_none( self, tmp_path ):
        _write_bridge( tmp_path, "cc-1.json", tmux_session="seat-a" )
        index, _ = _scan_persona_by_tmux_session( tmp_path )
        assert index[ "seat-a" ][ "persona_state" ] == PERSONA_STATE_NONE

    @pytest.mark.parametrize( "bad", [ "Krishna", 42, [ "Krishna" ], { }, { "name": "" },
                                       { "name": "   " }, { "name": 7 } ] )
    def test_malformed_persona_is_unreadable_not_none( self, tmp_path, bad ):
        # A record we FOUND but cannot read is an instrument failure, not an
        # absent persona — collapsing it into "none" would invent a fact.
        _write_bridge( tmp_path, "cc-1.json", tmux_session="seat-a", voice_persona=bad )
        index, _ = _scan_persona_by_tmux_session( tmp_path )
        assert index[ "seat-a" ] == { "persona": None, "persona_state": PERSONA_STATE_UNREADABLE }

    def test_corrupt_json_is_counted_not_silently_skipped( self, tmp_path ):
        # Bridge filenames key on pid, not tmux session, so a corrupt bridge is
        # unattributable — but the scan must confess it was partially blind.
        _write_bridge( tmp_path, "cc-bad.json", raw="{ not json" )
        _write_bridge( tmp_path, "cc-1.json", tmux_session="seat-a", voice_persona={ "name": "Rio" } )
        index, unattributable = _scan_persona_by_tmux_session( tmp_path )
        assert unattributable == 1 and index[ "seat-a" ][ "persona" ] == "Rio"

    def test_non_dict_json_is_counted( self, tmp_path ):
        _write_bridge( tmp_path, "cc-list.json", raw="[1, 2, 3]" )
        _, unattributable = _scan_persona_by_tmux_session( tmp_path )
        assert unattributable == 1

    def test_unreadable_file_is_counted( self, tmp_path, monkeypatch ):
        path = _write_bridge( tmp_path, "cc-1.json", tmux_session="seat-a" )
        def _boom( self, *a, **k ):
            if self == path: raise OSError( "permission denied" )
            return "{}"
        monkeypatch.setattr( Path, "read_text", _boom )
        _, unattributable = _scan_persona_by_tmux_session( tmp_path )
        assert unattributable == 1

    def test_glob_oserror_yields_empty_scan( self, tmp_path, monkeypatch ):
        monkeypatch.setattr( Path, "glob", lambda self, pat: ( _ for _ in () ).throw( OSError( "nope" ) ) )
        assert _scan_persona_by_tmux_session( tmp_path ) == ( { }, 0 )

    def test_buffer_and_listener_sidecars_are_skipped( self, tmp_path ):
        _write_bridge( tmp_path, "cc-buffer-x.json", raw="{ not json" )
        _write_bridge( tmp_path, "cc-listener-x.json", raw="{ not json" )
        assert _scan_persona_by_tmux_session( tmp_path ) == ( { }, 0 )

    @pytest.mark.parametrize( "tmux", [ None, "", 42 ] )
    def test_bridge_without_usable_tmux_session_is_ignored( self, tmp_path, tmux ):
        _write_bridge( tmp_path, "cc-1.json", tmux_session=tmux, voice_persona={ "name": "Rio" } )
        index, unattributable = _scan_persona_by_tmux_session( tmp_path )
        assert index == { } and unattributable == 0


class TestBuildIdentityWarning:
    def test_all_allocated_yields_no_warning( self ):
        rows = [ { "session_name": "a", "persona_state": PERSONA_STATE_ALLOCATED, "age_seconds": 5 } ]
        assert _build_identity_warning( rows, 0 ) is None

    def test_empty_roster_yields_no_warning( self ):
        assert _build_identity_warning( [ ], 0 ) is None

    def test_names_every_unverified_seat_with_state_and_age( self ):
        rows = [ { "session_name": "a", "persona_state": PERSONA_STATE_ALLOCATED, "age_seconds": 5 },
                 { "session_name": "b", "persona_state": PERSONA_STATE_UNKNOWN,   "age_seconds": 3.7 },
                 { "session_name": "c", "persona_state": PERSONA_STATE_NONE,      "age_seconds": None } ]
        w = _build_identity_warning( rows, 0 )
        assert "2 of 3" in w
        assert "b (unknown_no_bridge, 3s old)" in w
        assert "c (none, age unknown)" in w
        assert "a (" not in w                     # verified seats are not nagged about
        assert "LIVENESS" in w                    # the refusal is stated, not implied

    def test_blindness_note_only_when_scan_was_blind( self ):
        rows = [ { "session_name": "b", "persona_state": PERSONA_STATE_UNKNOWN, "age_seconds": 1 } ]
        assert "unreadable bridge file" not in _build_identity_warning( rows, 0 )
        assert "skipped 2 unreadable bridge file" in _build_identity_warning( rows, 2 )


class TestListSpawnedSessionsIdentity:
    def _seed_manifest( self, tmp_path, records ):
        _write_manifest( _manifest_path( "mgr", tmp_path ), records )

    def test_three_states_are_distinguishable_in_one_roster( self, tmp_path ):
        # The core acceptance: allocated / none / unknown_no_bridge, side by side,
        # all three tmux-ALIVE. The old roster rendered these as identical greens.
        self._seed_manifest( tmp_path, [ { "session_name": "seat-alloc" },
                                         { "session_name": "seat-null" },
                                         { "session_name": "seat-nobridge" } ] )
        _write_bridge( tmp_path, "cc-1.json", tmux_session="seat-alloc", voice_persona={ "name": "Krishna" } )
        _write_bridge( tmp_path, "cc-2.json", tmux_session="seat-null",  voice_persona=None )

        res  = list_spawned_sessions( "mgr", runner=FakeRunner( returncode=0 ), session_dir=tmp_path )
        rows = { s[ "session_name" ]: s for s in res[ "sessions" ] }

        assert all( r[ "alive" ] is True for r in rows.values() )   # liveness identical…
        assert rows[ "seat-alloc"    ][ "persona_state" ] == PERSONA_STATE_ALLOCATED
        assert rows[ "seat-alloc"    ][ "persona" ]       == "Krishna"
        assert rows[ "seat-null"     ][ "persona_state" ] == PERSONA_STATE_NONE
        assert rows[ "seat-nobridge" ][ "persona_state" ] == PERSONA_STATE_UNKNOWN
        # …identity is NOT. A null persona never arrives without a state saying why.
        assert rows[ "seat-null" ][ "persona" ] is None and rows[ "seat-nobridge" ][ "persona" ] is None
        assert rows[ "seat-null" ][ "persona_state" ] != rows[ "seat-nobridge" ][ "persona_state" ]

    def test_identity_verified_tracks_allocated_only( self, tmp_path ):
        self._seed_manifest( tmp_path, [ { "session_name": "a" }, { "session_name": "b" } ] )
        _write_bridge( tmp_path, "cc-1.json", tmux_session="a", voice_persona={ "name": "Rio" } )
        res  = list_spawned_sessions( "mgr", runner=FakeRunner( returncode=0 ), session_dir=tmp_path )
        rows = { s[ "session_name" ]: s for s in res[ "sessions" ] }
        assert rows[ "a" ][ "identity_verified" ] is True
        assert rows[ "b" ][ "identity_verified" ] is False

    def test_fully_identified_roster_declares_itself_complete( self, tmp_path ):
        self._seed_manifest( tmp_path, [ { "session_name": "a" } ] )
        _write_bridge( tmp_path, "cc-1.json", tmux_session="a", voice_persona={ "name": "Rio" } )
        res = list_spawned_sessions( "mgr", runner=FakeRunner( returncode=0 ), session_dir=tmp_path )
        assert res[ "identity_complete" ] is True and res[ "identity_warning" ] is None

    def test_green_liveness_cannot_be_read_as_identity_verified( self, tmp_path ):
        # (b) half of the done-condition: every row is alive/live — the caller
        # must STILL be unable to read this dict as identity-verified.
        self._seed_manifest( tmp_path, [ { "session_name": "seat-x" } ] )
        res = list_spawned_sessions( "mgr", runner=FakeRunner( returncode=0 ), session_dir=tmp_path )
        assert res[ "sessions" ][ 0 ][ "status" ] == "live"
        assert res[ "sessions" ][ 0 ][ "alive" ] is True
        assert res[ "identity_complete" ] is False
        assert "seat-x" in res[ "identity_warning" ]

    def test_empty_roster_claims_nothing_and_warns_about_nothing( self, tmp_path ):
        res = list_spawned_sessions( "mgr", runner=FakeRunner(), session_dir=tmp_path )
        assert res[ "count" ] == 0
        assert res[ "identity_complete" ] is True and res[ "identity_warning" ] is None

    def test_unattributable_bridges_surfaced_on_the_roster( self, tmp_path ):
        self._seed_manifest( tmp_path, [ { "session_name": "a" } ] )
        _write_bridge( tmp_path, "cc-bad.json", raw="{{{" )
        res = list_spawned_sessions( "mgr", runner=FakeRunner( returncode=0 ), session_dir=tmp_path )
        assert res[ "unattributable_bridges" ] == 1
        assert "scan blindness" in res[ "identity_warning" ]

    def test_age_seconds_computed_from_spawned_ts( self, tmp_path ):
        self._seed_manifest( tmp_path, [ { "session_name": "a", "spawned_ts": 1000.0 } ] )
        res = list_spawned_sessions( "mgr", runner=FakeRunner( returncode=0 ),
                                     session_dir=tmp_path, now_fn=lambda: 1042.5 )
        assert res[ "sessions" ][ 0 ][ "age_seconds" ] == pytest.approx( 42.5 )

    @pytest.mark.parametrize( "bad_ts", [ None, "yesterday" ] )
    def test_age_is_none_for_legacy_or_malformed_stamp( self, tmp_path, bad_ts ):
        # Legacy records predate spawn-time capture: honest absence, never a guess.
        rec = { "session_name": "a" }
        if bad_ts is not None: rec[ "spawned_ts" ] = bad_ts
        self._seed_manifest( tmp_path, [ rec ] )
        res = list_spawned_sessions( "mgr", runner=FakeRunner( returncode=0 ),
                                     session_dir=tmp_path, now_fn=lambda: 1042.5 )
        assert res[ "sessions" ][ 0 ][ "age_seconds" ] is None

    def test_age_separates_a_fresh_race_from_a_dead_sessionstart( self, tmp_path ):
        # Both seats are "no bridge". Nothing on disk resolves the ambiguity, so
        # the STATE stays ambiguous for both — age is the caller's evidence.
        self._seed_manifest( tmp_path, [ { "session_name": "fresh", "spawned_ts": 1000.0 },
                                         { "session_name": "stale", "spawned_ts": 0.0 } ] )
        res  = list_spawned_sessions( "mgr", runner=FakeRunner( returncode=0 ),
                                      session_dir=tmp_path, now_fn=lambda: 1003.0 )
        rows = { s[ "session_name" ]: s for s in res[ "sessions" ] }
        assert rows[ "fresh" ][ "persona_state" ] == PERSONA_STATE_UNKNOWN
        assert rows[ "stale" ][ "persona_state" ] == PERSONA_STATE_UNKNOWN
        assert rows[ "fresh" ][ "age_seconds" ] == pytest.approx( 3.0 )
        assert rows[ "stale" ][ "age_seconds" ] == pytest.approx( 1003.0 )

    def test_dead_seat_still_reports_identity_axis( self, tmp_path ):
        # Liveness and identity are independent axes — a dead seat whose bridge
        # survives still answers "who was in it?".
        self._seed_manifest( tmp_path, [ { "session_name": "a" } ] )
        _write_bridge( tmp_path, "cc-1.json", tmux_session="a", voice_persona={ "name": "Rachel" } )
        res = list_spawned_sessions( "mgr", runner=FakeRunner( returncode=1 ), session_dir=tmp_path )
        assert res[ "sessions" ][ 0 ][ "alive" ] is False
        assert res[ "sessions" ][ 0 ][ "persona" ] == "Rachel"
        assert res[ "identity_complete" ] is True

    def test_unreadable_state_reaches_the_roster( self, tmp_path ):
        self._seed_manifest( tmp_path, [ { "session_name": "a" } ] )
        _write_bridge( tmp_path, "cc-1.json", tmux_session="a", voice_persona="Krishna" )
        res = list_spawned_sessions( "mgr", runner=FakeRunner( returncode=0 ), session_dir=tmp_path )
        assert res[ "sessions" ][ 0 ][ "persona_state" ] == PERSONA_STATE_UNREADABLE
        assert res[ "sessions" ][ 0 ][ "identity_verified" ] is False

    def test_bridge_scan_runs_once_regardless_of_roster_size( self, tmp_path, monkeypatch ):
        self._seed_manifest( tmp_path, [ { "session_name": f"s{i}" } for i in range( 6 ) ] )
        calls = [ ]
        real  = Path.glob
        def _counting_glob( self, pat ):
            calls.append( pat )
            return real( self, pat )
        monkeypatch.setattr( Path, "glob", _counting_glob )
        list_spawned_sessions( "mgr", runner=FakeRunner( returncode=0 ), session_dir=tmp_path )
        assert calls.count( "cc-*.json" ) == 1


class TestMeasuredBootSequence:
    """
    Replays the boot sequence MEASURED on a live spawn (2026-07-21, row 6f8fd858
    verification): a healthy child walks unknown_no_bridge → none → allocated in
    about one second, by writing its bridge first and its persona a beat later.

    This is pinned because it is the empirical reason the roster does NOT treat
    "none" or "unknown_no_bridge" as failure verdicts. If a future change makes
    either state assert a failure, this test says why that is wrong.
    """
    def test_healthy_child_walks_all_three_states( self, tmp_path ):
        _write_manifest( _manifest_path( "mgr", tmp_path ),
                         [ { "session_name": "seat", "spawned_ts": 0.0 } ] )
        runner   = FakeRunner( returncode=0 )
        observed = [ ]

        def _roster( t ):
            res = list_spawned_sessions( "mgr", runner=runner, session_dir=tmp_path, now_fn=lambda: t )
            observed.append( res[ "sessions" ][ 0 ][ "persona_state" ] )
            return res

        # t+0.00s — parent recorded the seat; the child has written nothing yet.
        assert _roster( 0.00 )[ "identity_complete" ] is False
        # t+0.77s — bridge lands, persona still null.
        _write_bridge( tmp_path, "cc-1.json", tmux_session="seat", voice_persona=None )
        assert _roster( 0.77 )[ "identity_complete" ] is False
        # t+1.02s — SessionStart names the persona.
        _write_bridge( tmp_path, "cc-1.json", tmux_session="seat", voice_persona={ "name": "Tiberius" } )
        final = _roster( 1.02 )

        assert observed == [ PERSONA_STATE_UNKNOWN, PERSONA_STATE_NONE, PERSONA_STATE_ALLOCATED ]
        assert final[ "identity_complete" ] is True
        assert final[ "sessions" ][ 0 ][ "persona" ] == "Tiberius"

    def test_same_two_states_are_reported_identically_when_aged( self, tmp_path ):
        # A 40-minute-old "none" is a dead child; a 1-second-old "none" is a
        # healthy one. The STATE is deliberately the same for both — only the
        # age differs — because nothing on disk distinguishes them.
        _write_manifest( _manifest_path( "mgr", tmp_path ),
                         [ { "session_name": "seat", "spawned_ts": 0.0 } ] )
        _write_bridge( tmp_path, "cc-1.json", tmux_session="seat", voice_persona=None )
        young = list_spawned_sessions( "mgr", runner=FakeRunner( returncode=0 ),
                                       session_dir=tmp_path, now_fn=lambda: 1.0 )
        old   = list_spawned_sessions( "mgr", runner=FakeRunner( returncode=0 ),
                                       session_dir=tmp_path, now_fn=lambda: 2400.0 )
        assert young[ "sessions" ][ 0 ][ "persona_state" ] == old[ "sessions" ][ 0 ][ "persona_state" ]
        assert young[ "sessions" ][ 0 ][ "age_seconds" ] == pytest.approx( 1.0 )
        assert old[ "sessions" ][ 0 ][ "age_seconds" ]   == pytest.approx( 2400.0 )
        assert "1s old"    in young[ "identity_warning" ]
        assert "2400s old" in old[ "identity_warning" ]


class TestSpawnRecordsSpawnedTs:
    def test_spawn_stamps_spawned_ts_into_the_manifest( self, tmp_path ):
        spawn_sessions( 2, "brief", "mgr", script_path="/s.sh",
                        runner=FakeRunner( returncode=0 ), session_dir=tmp_path,
                        now_fn=lambda: 1234.5 )
        records = _read_manifest( _manifest_path( "mgr", tmp_path ) )
        assert [ r[ "spawned_ts" ] for r in records ] == [ 1234.5, 1234.5 ]

    def test_spawned_ts_round_trips_into_age_seconds( self, tmp_path ):
        # End-to-end on the stamp: spawn writes it, roster reads it back.
        spawn_sessions( 1, "brief", "mgr", script_path="/s.sh",
                        runner=FakeRunner( returncode=0 ), session_dir=tmp_path,
                        now_fn=lambda: 100.0 )
        res = list_spawned_sessions( "mgr", runner=FakeRunner( returncode=0 ),
                                     session_dir=tmp_path, now_fn=lambda: 160.0 )
        assert res[ "sessions" ][ 0 ][ "age_seconds" ] == pytest.approx( 60.0 )


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
    _NO_MODELS = { "reviewer": None, "author": None, "observer": None, "default": None }

    def test_defaults_when_none( self ):
        cfg = resolve_spawn_config( None )
        assert cfg == { "spawn_cap": 8, "ack_timeout_seconds": 120, "write_memento_default": True,
                        "spawn_models": self._NO_MODELS }

    def test_reads_from_config_mgr( self ):
        mgr = _FakeConfigMgr( {
            "cc session spawn max reviewers"                 : 5,
            "cc session spawn reviewer ack timeout seconds"  : 90,
            "cc session spawn write memento default"         : False,
            "cc session spawn model reviewer"                : "claude-opus-4-8",
            "cc session spawn model author"                  : "claude-opus-4-8",
            "cc session spawn model observer"                : "claude-opus-4-8",
            "cc session spawn model default"                 : "claude-opus-4-8",
        } )
        cfg = resolve_spawn_config( mgr )
        assert cfg == { "spawn_cap": 5, "ack_timeout_seconds": 90, "write_memento_default": False,
                        "spawn_models": { "reviewer": "claude-opus-4-8", "author": "claude-opus-4-8",
                                          "observer": "claude-opus-4-8", "default": "claude-opus-4-8" } }

    def test_missing_keys_fall_back_to_defaults( self ):
        cfg = resolve_spawn_config( _FakeConfigMgr( {} ) )
        assert cfg[ "spawn_cap" ] == 8 and cfg[ "ack_timeout_seconds" ] == 120
        # absent model keys → all-None map (fail-open: no --model flag)
        assert cfg[ "spawn_models" ] == self._NO_MODELS

    def test_partial_model_keys_only_configured_roles_set( self ):
        # A role key present but others absent → only the present one resolves;
        # the rest stay None (fail-open per un-keyed role).
        mgr = _FakeConfigMgr( { "cc session spawn model author": "claude-fable-5" } )
        cfg = resolve_spawn_config( mgr )
        assert cfg[ "spawn_models" ] == { "reviewer": None, "author": "claude-fable-5",
                                          "observer": None, "default": None }


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


# ── MCP-WRAPPER LAYER: spawn_sessions model-directive (2026-07-02) ────────────
#
# Two concerns, mirroring the dismiss-wrapper regression lock above:
#   (schema) the new `model` param MUST be typed Optional[str] so FastMCP emits a
#     string/null JSON schema — an UNTYPED param emits no `type` and a client's
#     string arrives uncoerced (the exact class of bug the dismiss lock caught).
#   (resolution) the wrapper resolves a child's model explicit-param → INI role
#     key → INI `default` key → None, then threads the RESOLVED value into the
#     inner session_spawner.spawn_sessions. Driven via `.fn()` (the underlying
#     function) with a spy inner fn — the wrapper body (the resolution) runs; only
#     FastMCP's own schema coercion is bypassed (that is the schema test's job).

class TestSpawnSessionsWrapperSchema:
    def test_model_schema_allows_string( self, cv_mcp ):
        m = cv_mcp.spawn_sessions.parameters[ "properties" ][ "model" ]
        assert "string" in _type_options( m ), f"model must allow string, got {m}"

    def test_model_schema_allows_null_optional( self, cv_mcp ):
        # Optional[str] → the null branch is what lets the param be omitted.
        m = cv_mcp.spawn_sessions.parameters[ "properties" ][ "model" ]
        assert "null" in _type_options( m ), f"model must allow null (Optional), got {m}"


class TestSpawnSessionsWrapperResolution:
    """explicit-param → role key → `default` key → None, threaded to the inner fn."""

    def _patch( self, cv_mcp, monkeypatch, captured, spawn_models ):
        import lupin_mcp.session_spawner as ss

        def _spy_spawn( count, task_prompt, sid, *, model=None, role="reviewer", **_kw ):
            captured[ "model" ] = model
            captured[ "role" ]  = role
            return { "spawned": [], "model": model }

        monkeypatch.setattr( cv_mcp, "_wait_for_sender_id", lambda: "sender" )
        monkeypatch.setattr( cv_mcp, "_get_cc_metadata",   lambda: { "session_id": "abc12345" } )
        monkeypatch.setattr( cv_mcp, "_spawn_config_mgr",  lambda: None )
        monkeypatch.setattr( cv_mcp, "_spawn_script_path", lambda: "/s.sh" )
        monkeypatch.setattr( ss, "resolve_manager_identity",
                             lambda meta, fallback_session_id=None: ( "mgr-sid", "Rio" ) )
        monkeypatch.setattr( ss, "resolve_spawn_config",
                             lambda mgr: { "spawn_cap": 8, "ack_timeout_seconds": 120,
                                           "write_memento_default": True, "spawn_models": spawn_models } )
        monkeypatch.setattr( ss, "spawn_sessions", _spy_spawn )
        return ss

    _ALL_OPUS = { "reviewer": "claude-opus-4-8", "author": "claude-opus-4-8",
                  "observer": "claude-opus-4-8", "default": "claude-opus-4-8" }

    def test_explicit_param_wins_over_ini( self, cv_mcp, monkeypatch ):
        captured = {}
        self._patch( cv_mcp, monkeypatch, captured, self._ALL_OPUS )
        cv_mcp.spawn_sessions.fn( 1, "t", model="claude-fable-5" )
        assert captured[ "model" ] == "claude-fable-5"   # explicit beats the opus INI

    def test_role_key_used_when_no_explicit( self, cv_mcp, monkeypatch ):
        captured = {}
        self._patch( cv_mcp, monkeypatch, captured,
                     { "reviewer": "claude-opus-4-8", "author": None, "observer": None, "default": None } )
        cv_mcp.spawn_sessions.fn( 1, "t", role="reviewer" )
        assert captured[ "model" ] == "claude-opus-4-8"  # from the reviewer role key

    def test_role_specific_beats_default( self, cv_mcp, monkeypatch ):
        captured = {}
        self._patch( cv_mcp, monkeypatch, captured,
                     { "reviewer": "claude-opus-4-8", "author": None, "observer": None,
                       "default": "claude-fable-5" } )
        cv_mcp.spawn_sessions.fn( 1, "t", role="reviewer" )
        assert captured[ "model" ] == "claude-opus-4-8"  # role key beats the default key

    def test_falls_to_default_key_for_unkeyed_role( self, cv_mcp, monkeypatch ):
        captured = {}
        self._patch( cv_mcp, monkeypatch, captured,
                     { "reviewer": None, "author": None, "observer": None, "default": "claude-opus-4-8" } )
        # an unknown/new role has no map entry → .get(role) is None → the default key
        cv_mcp.spawn_sessions.fn( 1, "t", role="manager" )
        assert captured[ "model" ] == "claude-opus-4-8"

    def test_all_none_resolves_to_none_no_flag( self, cv_mcp, monkeypatch ):
        captured = {}
        self._patch( cv_mcp, monkeypatch, captured,
                     { "reviewer": None, "author": None, "observer": None, "default": None } )
        cv_mcp.spawn_sessions.fn( 1, "t", role="reviewer" )
        assert captured[ "model" ] is None               # fail-open: inner fn omits --model

    def test_valueerror_becomes_error_dict( self, cv_mcp, monkeypatch ):
        # The cap ValueError from the inner fn must surface as {status:"error"} —
        # the model= threading must not disturb that pre-existing contract.
        import lupin_mcp.session_spawner as ss
        monkeypatch.setattr( cv_mcp, "_wait_for_sender_id", lambda: "sender" )
        monkeypatch.setattr( cv_mcp, "_get_cc_metadata",   lambda: { "session_id": "abc12345" } )
        monkeypatch.setattr( cv_mcp, "_spawn_config_mgr",  lambda: None )
        monkeypatch.setattr( cv_mcp, "_spawn_script_path", lambda: "/s.sh" )
        monkeypatch.setattr( ss, "resolve_manager_identity",
                             lambda meta, fallback_session_id=None: ( "mgr-sid", "Rio" ) )
        monkeypatch.setattr( ss, "resolve_spawn_config",
                             lambda mgr: { "spawn_cap": 8, "ack_timeout_seconds": 120,
                                           "write_memento_default": True, "spawn_models": self._ALL_OPUS } )
        def _raise( *a, **k ): raise ValueError( "count 99 exceeds spawn cap 8" )
        monkeypatch.setattr( ss, "spawn_sessions", _raise )
        res = cv_mcp.spawn_sessions.fn( 99, "t" )
        assert res[ "status" ] == "error" and "cap" in res[ "reason" ]
