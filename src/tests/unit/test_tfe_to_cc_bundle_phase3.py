"""
Unit tests for TFE-to-CC Phase 3 bundle-prompt builder (coordinator prompt).

Exercises `build_fix_bundle_prompt`:
- Required coordinator sections present
- Task subagent Brief is embedded
- Per-fix specs render in order with all fields
- Breadcrumb instructions toggled via flag
- MCP escalation toggled via flag
- Worktree path + commit identity injected correctly
- Output contract (tfe-result fence) named explicitly
"""

import pytest

from cosa.agents.tfe_to_cc.prompts.bundle_phase3 import build_fix_bundle_prompt


def _fix( cid: str, title: str, **extras ) -> dict:
    return {
        "cluster_id"    : cid,
        "title"         : title,
        "fix_type"      : extras.get( "fix_type", "code_patch" ),
        "confidence"    : extras.get( "confidence", 0.9 ),
        "description"   : extras.get( "description", f"Description for {cid}" ),
        "target_files"  : extras.get( "target_files", [ f"src/{cid.lower()}.py" ] ),
        "failing_tests" : extras.get( "failing_tests", [ f"test_{cid.lower()}_failure" ] ),
    }


def _diag( root: str = "Stale assertion", category: str = "test_bug" ) -> dict:
    return { "root_cause": root, "error_category": category }


# ═════════════════════════════════════════════════════════════════════════
# Basic structure
# ═════════════════════════════════════════════════════════════════════════

class TestStructure:

    def test_empty_fixes_raises( self ):
        with pytest.raises( ValueError, match="non-empty" ):
            build_fix_bundle_prompt(
                selected_fixes=[],
                diagnoses={},
                worktree_path="/var/lupin/.claude/worktrees/test",
            )

    def test_single_fix_renders_required_sections( self ):
        prompt = build_fix_bundle_prompt(
            selected_fixes = [ _fix( "C1", "Demo fix" ) ],
            diagnoses      = { "C1": _diag() },
            worktree_path  = "/var/lupin/.claude/worktrees/demo",
        )
        # Major sections
        assert "# TFE-to-CC Phase 3" in prompt
        assert "## Environment" in prompt
        assert "## Your workflow" in prompt
        assert "## Coordinator tool guidance" in prompt
        assert "## Subagent Brief template" in prompt
        assert "## The 1 fixes to apply" in prompt
        assert "## Final output contract" in prompt

    def test_n_value_in_header_matches_fixes( self ):
        for n in ( 1, 2, 11 ):
            fixes = [ _fix( f"C{i}", f"t{i}" ) for i in range( n ) ]
            diags = { f"C{i}": _diag() for i in range( n ) }
            prompt = build_fix_bundle_prompt(
                selected_fixes = fixes,
                diagnoses      = diags,
                worktree_path  = "/wt",
            )
            assert f"{n} fixes in parallel" in prompt
            assert f"The {n} fixes to apply" in prompt


# ═════════════════════════════════════════════════════════════════════════
# Environment + commit identity
# ═════════════════════════════════════════════════════════════════════════

class TestEnvironment:

    def test_worktree_path_appears_in_env_section_and_subagent_brief( self ):
        wt = "/var/lupin/.claude/worktrees/phase3-smoke-20260420"
        prompt = build_fix_bundle_prompt(
            selected_fixes = [ _fix( "C1", "x" ) ],
            diagnoses      = { "C1": _diag() },
            worktree_path  = wt,
        )
        # Appears at least twice — env section + subagent brief
        assert prompt.count( wt ) >= 2

    def test_custom_commit_identity_renders( self ):
        prompt = build_fix_bundle_prompt(
            selected_fixes      = [ _fix( "C1", "x" ) ],
            diagnoses           = { "C1": _diag() },
            worktree_path       = "/wt",
            commit_author_email = "custom@example.com",
            commit_author_name  = "Custom Author",
        )
        assert "custom@example.com" in prompt
        assert "Custom Author" in prompt

    def test_source_suite_renders_when_provided( self ):
        prompt = build_fix_bundle_prompt(
            selected_fixes = [ _fix( "C1", "x" ) ],
            diagnoses      = { "C1": _diag() },
            worktree_path  = "/wt",
            source_suite   = "ts-d3df4d87",
        )
        assert "ts-d3df4d87" in prompt

    def test_source_suite_omitted_when_absent( self ):
        prompt = build_fix_bundle_prompt(
            selected_fixes = [ _fix( "C1", "x" ) ],
            diagnoses      = { "C1": _diag() },
            worktree_path  = "/wt",
        )
        assert "Source test suite" not in prompt


# ═════════════════════════════════════════════════════════════════════════
# Coordinator workflow + tool guidance
# ═════════════════════════════════════════════════════════════════════════

class TestWorkflow:

    def test_todowrite_and_task_mentioned_in_workflow( self ):
        prompt = build_fix_bundle_prompt(
            selected_fixes = [ _fix( "C1", "x" ) ],
            diagnoses      = { "C1": _diag() },
            worktree_path  = "/wt",
        )
        assert "TodoWrite" in prompt
        assert "Task" in prompt

    def test_coordinator_forbidden_from_edit_write_bash( self ):
        prompt = build_fix_bundle_prompt(
            selected_fixes = [ _fix( "C1", "x" ) ],
            diagnoses      = { "C1": _diag() },
            worktree_path  = "/wt",
        )
        # Coordinator does NOT edit or commit
        assert "Edit / Write" in prompt
        assert "you do NOT edit files directly" in prompt
        assert "Subagents own" in prompt

    def test_breadcrumbs_enabled_by_default_and_mention_notify( self ):
        prompt = build_fix_bundle_prompt(
            selected_fixes = [ _fix( "C1", "x" ) ],
            diagnoses      = { "C1": _diag() },
            worktree_path  = "/wt",
        )
        assert "mcp__cosa-voice__notify" in prompt
        assert "Emit progress breadcrumbs" in prompt

    def test_breadcrumbs_disabled_suppresses_notify_instructions( self ):
        prompt = build_fix_bundle_prompt(
            selected_fixes   = [ _fix( "C1", "x" ) ],
            diagnoses        = { "C1": _diag() },
            worktree_path    = "/wt",
            emit_breadcrumbs = False,
        )
        assert "Progress notifications not required for this run" in prompt
        assert "Emit progress breadcrumbs" not in prompt

    def test_mcp_escalation_enabled_by_default( self ):
        prompt = build_fix_bundle_prompt(
            selected_fixes = [ _fix( "C1", "x" ) ],
            diagnoses      = { "C1": _diag() },
            worktree_path  = "/wt",
        )
        assert "mcp__cosa-voice__ask_yes_no" in prompt
        assert "mcp__cosa-voice__ask_multiple_choice" in prompt

    def test_mcp_escalation_disabled_omits_ask_tools( self ):
        prompt = build_fix_bundle_prompt(
            selected_fixes       = [ _fix( "C1", "x" ) ],
            diagnoses            = { "C1": _diag() },
            worktree_path        = "/wt",
            allow_mcp_escalation = False,
        )
        assert "mcp__cosa-voice__ask_yes_no" not in prompt


# ═════════════════════════════════════════════════════════════════════════
# Subagent Brief template
# ═════════════════════════════════════════════════════════════════════════

class TestSubagentBrief:

    def test_brief_names_the_focused_sub_engineer_role( self ):
        prompt = build_fix_bundle_prompt(
            selected_fixes = [ _fix( "C1", "x" ) ],
            diagnoses      = { "C1": _diag() },
            worktree_path  = "/wt",
        )
        assert "focused sub-engineer" in prompt

    def test_brief_has_three_hard_rules( self ):
        prompt = build_fix_bundle_prompt(
            selected_fixes = [ _fix( "C1", "x" ) ],
            diagnoses      = { "C1": _diag() },
            worktree_path  = "/wt",
        )
        assert "Do NOT run `git push`" in prompt
        assert "Do NOT run the full pytest suite" in prompt
        assert "Do NOT touch files outside the worktree" in prompt

    def test_brief_demands_structured_return_json( self ):
        prompt = build_fix_bundle_prompt(
            selected_fixes = [ _fix( "C1", "x" ) ],
            diagnoses      = { "C1": _diag() },
            worktree_path  = "/wt",
        )
        assert "Return value (required)" in prompt
        assert '"cluster_id"' in prompt
        assert '"verdict"' in prompt
        assert '"commit_sha"' in prompt
        assert '"pytest_passed"' in prompt

    def test_brief_commit_message_format( self ):
        prompt = build_fix_bundle_prompt(
            selected_fixes = [ _fix( "C1", "x" ) ],
            diagnoses      = { "C1": _diag() },
            worktree_path  = "/wt",
        )
        # Commit convention matching GitStrategist expectations
        assert "fix(tfe):" in prompt

    def test_brief_pytest_filter_usage( self ):
        prompt = build_fix_bundle_prompt(
            selected_fixes = [ _fix( "C1", "x" ) ],
            diagnoses      = { "C1": _diag() },
            worktree_path  = "/wt",
        )
        assert "pytest -k" in prompt
        assert "--tb=short" in prompt


# ═════════════════════════════════════════════════════════════════════════
# Per-fix specs
# ═════════════════════════════════════════════════════════════════════════

class TestPerFixSpecs:

    def test_every_fix_renders_cluster_id_and_title( self ):
        fixes = [
            _fix( "C1", "Alpha fix" ),
            _fix( "C2", "Beta fix" ),
            _fix( "C3", "Gamma fix" ),
        ]
        diags = { "C1": _diag(), "C2": _diag(), "C3": _diag() }
        prompt = build_fix_bundle_prompt(
            selected_fixes = fixes,
            diagnoses      = diags,
            worktree_path  = "/wt",
        )
        for cid, title in ( ( "C1", "Alpha fix" ), ( "C2", "Beta fix" ), ( "C3", "Gamma fix" ) ):
            assert f"`{cid}`" in prompt
            assert title in prompt

    def test_fixes_render_in_provided_order( self ):
        fixes = [
            _fix( "C7", "seventh" ),
            _fix( "C1", "first-listed" ),
            _fix( "C4", "fourth" ),
        ]
        diags = { f.get( "cluster_id" ): _diag() for f in fixes }
        prompt = build_fix_bundle_prompt(
            selected_fixes = fixes,
            diagnoses      = diags,
            worktree_path  = "/wt",
        )
        pos = [ prompt.index( f"Fix {i+1}:" ) for i in range( 3 ) ]
        assert pos == sorted( pos )
        # And the title alignment matches
        assert prompt.index( "seventh" ) < prompt.index( "first-listed" ) < prompt.index( "fourth" )

    def test_target_files_listed( self ):
        prompt = build_fix_bundle_prompt(
            selected_fixes = [ _fix(
                "C1", "x",
                target_files=[ "src/a.py", "src/b.py" ],
            ) ],
            diagnoses     = { "C1": _diag() },
            worktree_path = "/wt",
        )
        assert "src/a.py" in prompt
        assert "src/b.py" in prompt

    def test_failing_tests_listed_for_pytest_k( self ):
        prompt = build_fix_bundle_prompt(
            selected_fixes = [ _fix(
                "C1", "x",
                failing_tests=[ "test_foo", "test_bar" ],
            ) ],
            diagnoses     = { "C1": _diag() },
            worktree_path = "/wt",
        )
        assert "test_foo" in prompt
        assert "test_bar" in prompt

    def test_root_cause_from_diagnosis_renders( self ):
        prompt = build_fix_bundle_prompt(
            selected_fixes = [ _fix( "C1", "x" ) ],
            diagnoses      = { "C1": _diag( root="The registry grew to 10 entries while the test still asserts 5" ) },
            worktree_path  = "/wt",
        )
        assert "The registry grew to 10 entries" in prompt

    def test_missing_diagnosis_tolerated( self ):
        # Some subagents may run without a Phase 1 diagnosis (e.g. SDK Phase 1 skipped)
        prompt = build_fix_bundle_prompt(
            selected_fixes = [ _fix( "C1", "x" ) ],
            diagnoses      = {},  # empty
            worktree_path  = "/wt",
        )
        # Doesn't raise; renders a placeholder
        assert "no Phase 1 diagnosis" in prompt or "use the description" in prompt

    def test_confidence_formatted_as_percent( self ):
        prompt = build_fix_bundle_prompt(
            selected_fixes = [ _fix( "C1", "x", confidence=0.97 ) ],
            diagnoses      = { "C1": _diag() },
            worktree_path  = "/wt",
        )
        assert "97%" in prompt


# ═════════════════════════════════════════════════════════════════════════
# Output contract
# ═════════════════════════════════════════════════════════════════════════

class TestOutputContract:

    def test_tfe_result_fence_name_present( self ):
        prompt = build_fix_bundle_prompt(
            selected_fixes = [ _fix( "C1", "x" ) ],
            diagnoses      = { "C1": _diag() },
            worktree_path  = "/wt",
        )
        assert "```tfe-result" in prompt

    def test_schema_fields_documented( self ):
        prompt = build_fix_bundle_prompt(
            selected_fixes = [ _fix( "C1", "x" ) ],
            diagnoses      = { "C1": _diag() },
            worktree_path  = "/wt",
        )
        for field in ( "verdict", "commit_sha", "files", "pytest_passed", "notes", "summary" ):
            assert field in prompt

    def test_verdict_values_enumerated( self ):
        prompt = build_fix_bundle_prompt(
            selected_fixes = [ _fix( "C1", "x" ) ],
            diagnoses      = { "C1": _diag() },
            worktree_path  = "/wt",
        )
        for v in ( "fixed", "failed", "unclear" ):
            assert f'"{v}"' in prompt


# ═════════════════════════════════════════════════════════════════════════
# Bounds + determinism
# ═════════════════════════════════════════════════════════════════════════

class TestBoundsAndDeterminism:

    def test_eleven_fix_prompt_bounded_in_size( self ):
        # Realistic full 11-fix prompt should stay under ~100KB
        fixes = [
            _fix(
                f"C{i}", f"Fix {i}",
                description="Some detailed description. " * 40,
                target_files=[ f"src/f_{i}_{j}.py" for j in range( 3 ) ],
                failing_tests=[ f"test_{i}_{j}" for j in range( 3 ) ],
            )
            for i in range( 1, 12 )
        ]
        diags = { f[ "cluster_id" ]: _diag( root="Detailed root cause " * 20 ) for f in fixes }
        prompt = build_fix_bundle_prompt(
            selected_fixes = fixes,
            diagnoses      = diags,
            worktree_path  = "/var/lupin/.claude/worktrees/phase3-smoke-xyz",
        )
        assert len( prompt ) < 100_000, f"Prompt too large: {len( prompt )} chars"
        # All 11 fix headers present
        for i in range( 1, 12 ):
            assert f"Fix {i}:" in prompt

    def test_deterministic_same_input_same_output( self ):
        fixes = [ _fix( "C1", "x" ), _fix( "C2", "y" ) ]
        diags = { "C1": _diag(), "C2": _diag() }
        p1 = build_fix_bundle_prompt( selected_fixes=fixes, diagnoses=diags, worktree_path="/wt" )
        p2 = build_fix_bundle_prompt( selected_fixes=fixes, diagnoses=diags, worktree_path="/wt" )
        assert p1 == p2


if __name__ == "__main__":
    import sys
    sys.exit( pytest.main( [ __file__, "-v" ] ) )
