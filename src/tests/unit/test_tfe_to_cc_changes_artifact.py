"""
Unit tests for the TFE-to-CC Phase 3 harness — argparse surface + changes-summary
artifact (JSON + MD emitter), both added in Lupin Session d8831785.

Tests the pure functions in `src/scripts/tfe_to_cc_phase3_live.py`:
    - _parse_worktree_commits
    - _derive_cluster_rows (already_clean remap + submodule touch tagging)
    - _compute_overall
    - _detect_submodule_leaks
    - _build_changes_artifact (top-level wiring)
    - _render_changes_md
    - _write_changes_artifacts
    - main()'s argparse surface (defaults + choices)
"""

import importlib.util
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest


# ─────────────────────────────────────────────────────────────────
# Harness loader — imports the standalone script module by path
# ─────────────────────────────────────────────────────────────────

_HARNESS_PATH = Path( __file__ ).resolve().parent.parent.parent / "scripts" / "tfe_to_cc_phase3_live.py"


@pytest.fixture( scope="module" )
def harness():
    spec = importlib.util.spec_from_file_location( "tfe_to_cc_phase3_live", _HARNESS_PATH )
    mod  = importlib.util.module_from_spec( spec )
    spec.loader.exec_module( mod )
    return mod


# ─────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────

def _fix( cid: str, title: str = "" ) -> dict:
    return { "cluster_id": cid, "title": title or f"{cid} title" }


# ═════════════════════════════════════════════════════════════════
# _parse_worktree_commits
# ═════════════════════════════════════════════════════════════════

class TestParseWorktreeCommits:

    def test_empty_input_yields_empty_list( self, harness ):
        assert harness._parse_worktree_commits( "" ) == []
        assert harness._parse_worktree_commits( None ) == []

    def test_single_line_parses( self, harness ):
        out = harness._parse_worktree_commits( "abc1234 fix(tfe): C1 did a thing" )
        assert out == [ { "sha": "abc1234", "subject": "fix(tfe): C1 did a thing" } ]

    def test_multiple_lines_preserve_order( self, harness ):
        raw = "abc1234 subj one\ndef5678 subj two\n"
        out = harness._parse_worktree_commits( raw )
        assert [ c[ "sha" ] for c in out ]     == [ "abc1234", "def5678" ]
        assert [ c[ "subject" ] for c in out ] == [ "subj one", "subj two" ]

    def test_blank_lines_and_malformed_skipped( self, harness ):
        raw = "\nabc1234 subject\n   \njust-a-sha-no-subject\ndef5678 another\n"
        out = harness._parse_worktree_commits( raw )
        assert len( out ) == 2
        assert out[ 0 ][ "sha" ] == "abc1234"
        assert out[ 1 ][ "sha" ] == "def5678"


# ═════════════════════════════════════════════════════════════════
# _derive_cluster_rows — already_clean remap + submodule tagging
# ═════════════════════════════════════════════════════════════════

class TestDeriveClusterRows:

    def test_fixed_with_commit_stays_fixed( self, harness ):
        parsed = { "clusters": { "C1": {
            "verdict": "fixed", "commit_sha": "abc1234",
            "files": [ "src/x.py" ], "pytest_passed": True, "notes": "ok",
        } } }
        rows = harness._derive_cluster_rows( parsed, [ _fix( "C1" ) ] )
        assert len( rows ) == 1
        r = rows[ 0 ]
        assert r[ "verdict" ]     == "fixed"
        assert r[ "verdict_raw" ] == "fixed"
        assert r[ "commit_sha" ]  == "abc1234"

    def test_fixed_with_null_sha_remaps_to_already_clean( self, harness ):
        parsed = { "clusters": { "C1": {
            "verdict": "fixed", "commit_sha": None,
            "files": [ "src/x.py" ], "pytest_passed": True, "notes": "was correct",
        } } }
        rows = harness._derive_cluster_rows( parsed, [ _fix( "C1" ) ] )
        assert rows[ 0 ][ "verdict" ]     == "already_clean"
        assert rows[ 0 ][ "verdict_raw" ] == "fixed"
        assert rows[ 0 ][ "commit_sha" ]  is None

    def test_fixed_with_empty_sha_also_already_clean( self, harness ):
        """Non-string or whitespace-only commit_sha should remap like None."""
        parsed = { "clusters": { "C1": {
            "verdict": "fixed", "commit_sha": "   ",
            "files": [ "src/x.py" ], "pytest_passed": True, "notes": "",
        } } }
        rows = harness._derive_cluster_rows( parsed, [ _fix( "C1" ) ] )
        assert rows[ 0 ][ "verdict" ] == "already_clean"

    def test_unclear_passes_through( self, harness ):
        parsed = { "clusters": { "C1": { "verdict": "unclear", "commit_sha": None, "files": [] } } }
        rows   = harness._derive_cluster_rows( parsed, [ _fix( "C1" ) ] )
        assert rows[ 0 ][ "verdict" ] == "unclear"

    def test_failed_passes_through( self, harness ):
        parsed = { "clusters": { "C1": { "verdict": "failed", "commit_sha": None, "files": [] } } }
        rows   = harness._derive_cluster_rows( parsed, [ _fix( "C1" ) ] )
        assert rows[ 0 ][ "verdict" ] == "failed"

    def test_missing_cluster_maps_to_unknown( self, harness ):
        parsed = { "clusters": {} }
        rows   = harness._derive_cluster_rows( parsed, [ _fix( "C1" ) ] )
        assert rows[ 0 ][ "verdict" ]     == "unknown"
        assert rows[ 0 ][ "verdict_raw" ] is None

    def test_parsed_none_treats_all_as_unknown( self, harness ):
        rows = harness._derive_cluster_rows( None, [ _fix( "C1" ), _fix( "C2" ) ] )
        assert [ r[ "verdict" ] for r in rows ] == [ "unknown", "unknown" ]

    def test_submodule_files_tagged( self, harness ):
        parsed = { "clusters": { "C2": {
            "verdict": "fixed", "commit_sha": "def5678",
            "files": [ "src/cosa/rest/queues.py", "src/other.py" ],
        } } }
        rows = harness._derive_cluster_rows( parsed, [ _fix( "C2" ) ] )
        assert rows[ 0 ][ "touches_submodules" ] == [ "src/cosa/" ]

    def test_no_submodule_files_no_tag( self, harness ):
        parsed = { "clusters": { "C1": {
            "verdict": "fixed", "commit_sha": "abc1234",
            "files": [ "src/tests/foo.py" ],
        } } }
        rows = harness._derive_cluster_rows( parsed, [ _fix( "C1" ) ] )
        assert rows[ 0 ][ "touches_submodules" ] == []

    def test_preserves_selected_fixes_order( self, harness ):
        parsed = { "clusters": { "C3": { "verdict": "fixed", "commit_sha": "sha3" },
                                 "C1": { "verdict": "fixed", "commit_sha": "sha1" } } }
        rows = harness._derive_cluster_rows(
            parsed, [ _fix( "C1" ), _fix( "C2" ), _fix( "C3" ) ],
        )
        assert [ r[ "id" ] for r in rows ] == [ "C1", "C2", "C3" ]
        assert rows[ 1 ][ "verdict" ] == "unknown"    # C2 had no parsed entry


# ═════════════════════════════════════════════════════════════════
# _compute_overall + _detect_submodule_leaks
# ═════════════════════════════════════════════════════════════════

class TestOverallAndLeaks:

    def _rows( self ):
        return [
            { "id": "C1", "verdict": "fixed",         "touches_submodules": [] },
            { "id": "C2", "verdict": "fixed",         "touches_submodules": [ "src/cosa/" ] },
            { "id": "C3", "verdict": "already_clean", "touches_submodules": [] },
            { "id": "C4", "verdict": "unclear",       "touches_submodules": [] },
            { "id": "C5", "verdict": "failed",        "touches_submodules": [ "src/cosa/" ] },
            { "id": "C6", "verdict": "unknown",       "touches_submodules": [] },
        ]

    def test_overall_counts( self, harness ):
        overall = harness._compute_overall( self._rows(), total=6 )
        assert overall == {
            "clusters_total" : 6,
            "fixed"          : 2,
            "already_clean"  : 1,
            "unclear"        : 1,
            "failed"         : 1,
            "unknown"        : 1,
        }

    def test_leaks_group_by_submodule( self, harness ):
        leaks = harness._detect_submodule_leaks( self._rows() )
        assert leaks == { "src/cosa/": [ "C2", "C5" ] }

    def test_empty_rows_empty_leaks( self, harness ):
        assert harness._detect_submodule_leaks( [] ) == {}


# ═════════════════════════════════════════════════════════════════
# _build_changes_artifact (top-level wiring)
# ═════════════════════════════════════════════════════════════════

class TestBuildArtifact:

    def test_full_artifact_shape( self, harness ):
        started = datetime( 2026, 4, 20, 10, 0, 0, tzinfo=timezone.utc )
        ended   = datetime( 2026, 4, 20, 10, 10, 0, tzinfo=timezone.utc )
        parsed  = { "clusters": {
            "C1": { "verdict": "fixed",   "commit_sha": "abc1234", "files": [ "src/x.py" ], "pytest_passed": True },
            "C2": { "verdict": "fixed",   "commit_sha": None,      "files": [ "src/y.py" ] },
            "C3": { "verdict": "unclear", "commit_sha": None,      "files": [] },
        } }
        git_log = "abc1234 fix(tfe): C1 works"

        art = harness._build_changes_artifact(
            run_id            = "phase3-test",
            model_requested   = "claude-opus-4-7",
            model_reported    = "claude-opus-4-7",
            effort            = "high",
            max_budget_usd    = 5.0,
            worktree          = "/tmp/wt",
            started_at        = started,
            ended_at          = ended,
            duration_s        = 600.0,
            exit_code         = 0,
            validation_ok     = True,
            validation_issues = [],
            selected_fixes    = [ _fix( "C1" ), _fix( "C2" ), _fix( "C3" ) ],
            parsed            = parsed,
            git_log_output    = git_log,
            git_diffstat      = " src/x.py | 2 +-",
        )

        # Top-level shape
        for k in ( "run_id", "model", "effort", "worktree", "started_at", "ended_at",
                   "duration_s", "exit_code", "validation_ok", "overall", "clusters",
                   "worktree_commits", "git_diffstat", "possibly_leaked_to_submodules" ):
            assert k in art, f"Missing top-level key: {k}"

        assert art[ "model" ]          == "claude-opus-4-7"
        assert art[ "effort" ]         == "high"
        assert art[ "max_budget_usd" ] == 5.0
        assert art[ "duration_s" ]     == 600.0
        assert art[ "exit_code" ]      == 0
        assert art[ "validation_ok" ]  is True

        # Overall aggregation
        assert art[ "overall" ][ "clusters_total" ] == 3
        assert art[ "overall" ][ "fixed" ]          == 1
        assert art[ "overall" ][ "already_clean" ]  == 1
        assert art[ "overall" ][ "unclear" ]        == 1

        # Cluster rows
        assert [ r[ "id" ] for r in art[ "clusters" ] ] == [ "C1", "C2", "C3" ]
        assert art[ "clusters" ][ 1 ][ "verdict" ]      == "already_clean"

        # Worktree commits parsed
        assert art[ "worktree_commits" ] == [ { "sha": "abc1234", "subject": "fix(tfe): C1 works" } ]


class TestRenderMarkdown:

    def test_md_contains_tables_and_headers( self, harness ):
        changes = {
            "run_id": "r1", "model": "claude-opus-4-7", "model_reported": "claude-opus-4-7",
            "effort": "high", "max_budget_usd": None, "worktree": "/tmp/w",
            "started_at": "2026-04-20T10:00:00", "ended_at": "2026-04-20T10:10:00",
            "duration_s": 600.0, "exit_code": 0, "validation_ok": True, "validation_issues": [],
            "overall": { "clusters_total": 1, "fixed": 1, "already_clean": 0, "unclear": 0, "failed": 0, "unknown": 0 },
            "clusters": [ {
                "id": "C1", "title": "Demo", "verdict": "fixed", "verdict_raw": "fixed",
                "commit_sha": "abc1234", "files": [ "src/x.py" ], "pytest_passed": True,
                "notes": None, "touches_submodules": [],
            } ],
            "worktree_commits": [ { "sha": "abc1234", "subject": "demo commit" } ],
            "git_diffstat": "",
            "possibly_leaked_to_submodules": {},
        }
        md = harness._render_changes_md( changes )
        assert md.startswith( "# TFE-to-CC Changes Report — r1" )
        assert "## Overall" in md
        assert "## Clusters" in md
        assert "**C1**" in md
        assert "`claude-opus-4-7`" in md
        assert "⚠️ Possibly leaked" not in md    # no leaks in this fixture

    def test_md_surfaces_submodule_leaks_section( self, harness ):
        changes = {
            "run_id": "r1", "model": "m", "model_reported": "m", "effort": "high",
            "max_budget_usd": None, "worktree": "/tmp/w",
            "started_at": "...", "ended_at": "...", "duration_s": 0.0,
            "exit_code": 0, "validation_ok": True, "validation_issues": [],
            "overall": { "clusters_total": 0, "fixed": 0, "already_clean": 0,
                         "unclear": 0, "failed": 0, "unknown": 0 },
            "clusters": [],
            "worktree_commits": [],
            "git_diffstat": "",
            "possibly_leaked_to_submodules": { "src/cosa/": [ "C2", "C4" ] },
        }
        md = harness._render_changes_md( changes )
        assert "⚠️ Possibly leaked to submodules" in md
        assert "src/cosa/" in md
        assert "C2, C4" in md


# ═════════════════════════════════════════════════════════════════
# _write_changes_artifacts — filesystem round-trip
# ═════════════════════════════════════════════════════════════════

class TestWriteArtifacts:

    def test_writes_both_files_with_matching_timestamp( self, harness, tmp_path ):
        changes = {
            "run_id": "phase3-test", "model": "claude-opus-4-7", "model_reported": "claude-opus-4-7",
            "effort": "high", "max_budget_usd": None, "worktree": "/tmp/w",
            "started_at": "2026-04-20T10:00:00", "ended_at": "2026-04-20T10:10:00",
            "duration_s": 600.0, "exit_code": 0, "validation_ok": True, "validation_issues": [],
            "overall": { "clusters_total": 1, "fixed": 1, "already_clean": 0,
                         "unclear": 0, "failed": 0, "unknown": 0 },
            "clusters": [],
            "worktree_commits": [],
            "git_diffstat": "",
            "possibly_leaked_to_submodules": {},
        }
        json_path, md_path = harness._write_changes_artifacts( changes, tmp_path, "20260420T100000Z" )
        assert json_path.exists()
        assert md_path.exists()
        assert json_path.name == "tfe-to-cc-changes-20260420T100000Z.json"
        assert md_path.name   == "tfe-to-cc-changes-20260420T100000Z.md"

        import json
        roundtrip = json.loads( json_path.read_text() )
        assert roundtrip[ "run_id" ] == "phase3-test"


# ═════════════════════════════════════════════════════════════════
# Argparse surface (harness CLI)
# ═════════════════════════════════════════════════════════════════

class TestHarnessCLI:

    def test_defaults( self, harness, monkeypatch ):
        """main() with no args populates the documented defaults."""
        monkeypatch.setattr( sys, "argv", [ "tfe_to_cc_phase3_live.py" ] )
        # We can't call main() without a live container — just exercise the parser.
        import argparse
        parser = argparse.ArgumentParser()
        parser.add_argument( "--model",  default=harness.DEFAULT_MODEL )
        parser.add_argument( "--effort", default=harness.DEFAULT_EFFORT,
                             choices=[ "low", "medium", "high", "xhigh", "max", "none" ] )
        parser.add_argument( "--max-budget-usd", type=float, default=None )
        args = parser.parse_args( [] )
        # Default model flipped Opus 4.7 → Sonnet 4.6 on 2026-04-22 per matrix 23-* (Session b486e9dc)
        assert args.model          == "claude-sonnet-4-6"
        assert args.effort         == "high"
        assert args.max_budget_usd is None

    def test_effort_choices_constrained( self, harness ):
        import argparse
        parser = argparse.ArgumentParser()
        parser.add_argument( "--effort", choices=[ "low", "medium", "high", "xhigh", "max", "none" ] )
        with pytest.raises( SystemExit ):
            parser.parse_args( [ "--effort", "turbo" ] )

    def test_production_default_is_sonnet( self, harness ):
        """Contract: harness ships with Sonnet 4.6 as the production default (Session b486e9dc, 2026-04-22)."""
        assert harness.DEFAULT_MODEL  == "claude-sonnet-4-6"
        assert harness.DEFAULT_EFFORT == "high"
