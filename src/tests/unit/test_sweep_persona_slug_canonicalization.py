#!/usr/bin/env python3
"""
Unit tests for `src/scripts/sweep_persona_slug_canonicalization.py` — the Phase 3
persona-slug canonicalization sweep (dry-run default).

Covers (100% lines/branches/functions on the script's testable surface; the
live tmux + bridge discovery + `__main__` entry are env-only `pragma: no cover`):
  - topic_stem / persona_segment_of_session parsing
  - scan_topic_mismatches: variant detection across separator spellings, the
    merge-required vs plain-rename split, archive dir, already-canonical no-op
  - FLIP guard: an accented variant (dm-maría) is only caught because
    persona_slug accent-strips — revert that and the assertion fails
  - scan_tmux_mismatches: report-only detection
  - apply_topic_renames: rename + merge-skip, real os.rename + injected renamer
  - run_sweep / main: dry-run vs --apply, no-op reporting, owner injection

R&D: src/rnd/v0.1.9/2026.06.19-persona-name-normalization/01-centralized-persona-normalization-plan.md §Phase 3
"""
import importlib.util
import os
import sys
from pathlib import Path

import pytest

# Bootstrap
_LUPIN_ROOT = os.environ.get( "LUPIN_ROOT", os.getcwd() )
_src_path = os.path.join( _LUPIN_ROOT, "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

# The script lives under src/scripts (not importable as a package) — load by path.
_SCRIPT_PATH = Path( _LUPIN_ROOT ) / "src" / "scripts" / "sweep_persona_slug_canonicalization.py"
_spec = importlib.util.spec_from_file_location( "sweep_persona_slug_canonicalization", _SCRIPT_PATH )
sweep = importlib.util.module_from_spec( _spec )
_spec.loader.exec_module( sweep )


def _touch( directory, name ):
    """Create an empty topic file and return its Path."""
    p = directory / name
    p.write_text( "x", encoding="utf-8" )
    return p


class TestTopicStem:
    def test_extracts_persona_stem( self ):
        assert sweep.topic_stem( "dm-maría.md" )    == "maría"
        assert sweep.topic_stem( "dm-mr_radio.md" ) == "mr_radio"

    def test_non_dm_prefix_returns_empty( self ):
        assert sweep.topic_stem( "presence.md" ) == ""

    def test_non_md_suffix_returns_empty( self ):
        assert sweep.topic_stem( "dm-tiberius.txt" ) == ""


class TestPersonaSegmentOfSession:
    def test_recovers_persona_with_internal_hyphen( self ):
        assert sweep.persona_segment_of_session( "cc-author-mr-radio-1" ) == "mr-radio"

    def test_recovers_simple_persona( self ):
        assert sweep.persona_segment_of_session( "cc-reviewer-tiberius-2" ) == "tiberius"

    def test_non_spawn_name_returns_none( self ):
        assert sweep.persona_segment_of_session( "random-session" ) is None
        assert sweep.persona_segment_of_session( "cc-author-tiberius" ) is None  # no index


class TestScanTopicMismatches:
    def test_no_op_when_already_canonical( self, tmp_path ):
        _touch( tmp_path, "dm-tiberius.md" )
        assert sweep.scan_topic_mismatches( tmp_path, [ "Tiberius" ] ) == []

    def test_variant_without_canonical_is_plain_rename( self, tmp_path ):
        _touch( tmp_path, "dm-mr radio.md" )          # space variant; no canonical yet
        res = sweep.scan_topic_mismatches( tmp_path, [ "Mr. Radio" ] )
        assert len( res ) == 1
        assert res[ 0 ][ "current" ]        == "dm-mr radio.md"
        assert res[ 0 ][ "canonical" ]      == "dm-mr_radio.md"
        assert res[ 0 ][ "merge_required" ] is False

    def test_variant_with_existing_canonical_requires_merge( self, tmp_path ):
        _touch( tmp_path, "dm-mr_radio.md" )          # canonical already present
        _touch( tmp_path, "dm-mr-radio.md" )          # hyphen variant
        res = sweep.scan_topic_mismatches( tmp_path, [ "Mr. Radio" ] )
        assert len( res ) == 1
        assert res[ 0 ][ "current" ]        == "dm-mr-radio.md"
        assert res[ 0 ][ "merge_required" ] is True

    def test_separator_agnostic_matching_catches_hyphen_and_space( self, tmp_path ):
        """Both the space form AND the hyphen form must map to owner Mr. Radio —
        the reason matching uses normalize_for_match, not persona_slug('_')."""
        _touch( tmp_path, "dm-mr radio.md" )
        _touch( tmp_path, "dm-mr-radio.md" )
        res = sweep.scan_topic_mismatches( tmp_path, [ "Mr. Radio" ] )
        currents = sorted( r[ "current" ] for r in res )
        assert currents == [ "dm-mr radio.md", "dm-mr-radio.md" ]
        assert all( r[ "canonical" ] == "dm-mr_radio.md" for r in res )

    def test_accent_variant_caught_FLIP( self, tmp_path ):
        """FLIP guard: dm-maría is flagged ONLY because persona_slug accent-strips
        ("María"->"maria"). Revert persona_slug to accent-leaky and normalize_for_match
        keeps the accent -> dm-maría is its OWN canonical -> this assertion fails."""
        _touch( tmp_path, "dm-maría.md" )
        res = sweep.scan_topic_mismatches( tmp_path, [ "María" ] )
        assert len( res ) == 1
        assert res[ 0 ][ "current" ]   == "dm-maría.md"
        assert res[ 0 ][ "canonical" ] == "dm-maria.md"

    def test_non_persona_topics_are_left_alone( self, tmp_path ):
        _touch( tmp_path, "dm-2-reviewers.md" )
        _touch( tmp_path, "dm-mr_radio_tiberius.md" )   # compound — different match key
        _touch( tmp_path, "dm-07fba31d.md" )            # session-id topic
        res = sweep.scan_topic_mismatches( tmp_path, [ "Mr. Radio", "Tiberius" ] )
        assert res == []

    def test_empty_owner_is_skipped( self, tmp_path ):
        _touch( tmp_path, "dm-maría.md" )
        # An all-punctuation "owner" has an empty match key and must not match anything.
        assert sweep.scan_topic_mismatches( tmp_path, [ "!!!" ] ) == []

    def test_archive_dir_is_scanned( self, tmp_path ):
        archive = tmp_path / "archive"
        archive.mkdir()
        _touch( archive, "dm-Tiberius.md" )
        res = sweep.scan_topic_mismatches( tmp_path, [ "Tiberius" ] )
        assert len( res ) == 1
        assert res[ 0 ][ "current" ] == "dm-Tiberius.md"

    def test_missing_commons_dir_returns_empty( self, tmp_path ):
        assert sweep.scan_topic_mismatches( tmp_path / "nope", [ "Tiberius" ] ) == []


class TestScanTmuxMismatches:
    def test_non_canonical_persona_segment_flagged( self ):
        res = sweep.scan_tmux_mismatches( [ "cc-author-María-1" ], [ "María" ] )
        assert len( res ) == 1
        assert res[ 0 ][ "session" ]           == "cc-author-María-1"
        assert res[ 0 ][ "persona_segment" ]   == "María"
        assert res[ 0 ][ "canonical_segment" ] == "maria"

    def test_canonical_segment_not_flagged( self ):
        assert sweep.scan_tmux_mismatches( [ "cc-author-mr-radio-1" ], [ "Mr. Radio" ] ) == []

    def test_non_spawn_session_skipped( self ):
        assert sweep.scan_tmux_mismatches( [ "lupin-arbiter-app" ], [ "María" ] ) == []

    def test_unknown_persona_segment_skipped( self ):
        assert sweep.scan_tmux_mismatches( [ "cc-author-buster-1" ], [ "María" ] ) == []

    def test_empty_owner_skipped( self ):
        assert sweep.scan_tmux_mismatches( [ "cc-author-María-1" ], [ "!!!" ] ) == []


class TestApplyTopicRenames:
    def test_renames_plain_and_skips_merge( self, tmp_path ):
        _touch( tmp_path, "dm-mr radio.md" )
        _touch( tmp_path, "dm-maría.md" )
        _touch( tmp_path, "dm-maria.md" )           # forces merge_required for María
        mm  = sweep.scan_topic_mismatches( tmp_path, [ "Mr. Radio", "María" ] )
        log = sweep.apply_topic_renames( mm )       # default renamer = os.rename
        actions = { l[ "current" ]: l[ "action" ] for l in log }
        assert actions[ "dm-mr radio.md" ] == "renamed"
        assert actions[ "dm-maría.md" ]    == "skipped_merge_required"
        # The plain rename actually happened on disk; the merge variant survived.
        assert ( tmp_path / "dm-mr_radio.md" ).exists()
        assert not ( tmp_path / "dm-mr radio.md" ).exists()
        assert ( tmp_path / "dm-maría.md" ).exists()

    def test_injected_renamer_is_used( self, tmp_path ):
        _touch( tmp_path, "dm-mr radio.md" )
        calls = []
        mm = sweep.scan_topic_mismatches( tmp_path, [ "Mr. Radio" ] )
        sweep.apply_topic_renames( mm, renamer=lambda s, d: calls.append( ( Path( s ).name, Path( d ).name ) ) )
        assert calls == [ ( "dm-mr radio.md", "dm-mr_radio.md" ) ]
        # injected renamer did NOT touch disk
        assert ( tmp_path / "dm-mr radio.md" ).exists()


class TestRunSweep:
    def test_no_op_reports_clean( self, tmp_path ):
        _touch( tmp_path, "dm-tiberius.md" )
        lines = []
        res = sweep.run_sweep( commons_dir=tmp_path, owners=[ "Tiberius" ],
                               session_names=[], apply=False, out=lines.append )
        assert res[ "no_op" ] is True
        assert any( "no-op" in ln for ln in lines )
        # Nit (Phase 4): the resolved commons dir is logged so a worktree-launched
        # sweep can't silently report a misleading no-op against the wrong path.
        assert any( "commons dir resolved" in ln and str( tmp_path ) in ln for ln in lines )

    def test_dry_run_reports_but_does_not_mutate( self, tmp_path ):
        _touch( tmp_path, "dm-mr radio.md" )
        lines = []
        res = sweep.run_sweep( commons_dir=tmp_path, owners=[ "Mr. Radio", "María" ],
                               session_names=[ "cc-author-María-1" ], apply=False, out=lines.append )
        assert res[ "applied" ] == []
        assert res[ "no_op" ] is False
        assert len( res[ "tmux_mismatches" ] ) == 1
        assert ( tmp_path / "dm-mr radio.md" ).exists()         # untouched
        assert any( "DRY-RUN" in ln for ln in lines )
        assert any( "re-run with --apply" in ln for ln in lines )
        assert any( "REPORT-ONLY" in ln for ln in lines )       # tmux line emitted

    def test_apply_renames_and_logs( self, tmp_path ):
        _touch( tmp_path, "dm-mr radio.md" )
        lines = []
        res = sweep.run_sweep( commons_dir=tmp_path, owners=[ "Mr. Radio" ],
                               session_names=[], apply=True, out=lines.append )
        assert ( tmp_path / "dm-mr_radio.md" ).exists()
        assert res[ "applied" ][ 0 ][ "action" ] == "renamed"
        assert any( "APPLY" in ln for ln in lines )
        assert any( "APPLIED" in ln for ln in lines )


class TestMain:
    def test_owners_injected_dry_run_returns_zero( self, tmp_path ):
        _touch( tmp_path, "dm-mr radio.md" )
        lines = []
        rc = sweep.main( [], owners=[ "Mr. Radio" ], session_names=[],
                         commons_dir=tmp_path, out=lines.append )
        assert rc == 0
        assert ( tmp_path / "dm-mr radio.md" ).exists()         # dry-run default

    def test_persona_cli_arg_path( self, tmp_path ):
        _touch( tmp_path, "dm-maría.md" )
        lines = []
        rc = sweep.main( [ "--persona", "María" ], owners=None, session_names=[],
                         commons_dir=tmp_path, out=lines.append )
        assert rc == 0
        assert any( "dm-maría.md" in ln for ln in lines )

    def test_apply_flag_mutates( self, tmp_path ):
        _touch( tmp_path, "dm-mr radio.md" )
        rc = sweep.main( [ "--apply" ], owners=[ "Mr. Radio" ], session_names=[],
                         commons_dir=tmp_path, out=lambda *_a, **_k: None )
        assert rc == 0
        assert ( tmp_path / "dm-mr_radio.md" ).exists()


if __name__ == "__main__":
    sys.exit( pytest.main( [ __file__, "-v" ] ) )
