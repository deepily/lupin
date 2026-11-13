"""
Census guard: non-test source may hold only the Claude model id literals frozen here.

Rick, 13 Nov 2026: a model id lives in lupin-app.ini, read through ConfigurationManager, never in code.
The list is what the tree held when that rule was written, measured at 35e48e35c plus the change that moved the code-health ids.
It is a ratchet: a new literal fails, and so does a file that drops one until its count here is lowered or removed.
The count is of literal occurrences, so a model id quoted in a docstring counts too; the predicate is the text, not the use.
"""
import pathlib
import re
import subprocess

import cosa.utils.util as cu

MODEL_LITERAL = re.compile( r"[\"']claude-[a-z]+-[0-9]" )
TEST_DIR      = re.compile( r"(^|/)tests?/" )
SKIPPED_PARTS = ( ".venv", "node_modules", "site-packages" )
NOW_IN_INI    = ( "src/cosa/repo/duplicate_check/config.py", "src/lupin_mcp/reuse_needset/draft.py", "src/lupin_mcp/reuse_expansion.py" )

FROZEN = {
    "src/cosa/agents/bug_fix_expediter/config.py"          : 4,
    "src/cosa/agents/bug_fix_expediter/job.py"             : 1,
    "src/cosa/agents/bug_fix_expediter/orchestrator.py"    : 1,
    "src/cosa/agents/chained_pipeline_state.py"            : 2,
    "src/cosa/agents/deep_research/api_client.py"          : 1,
    "src/cosa/agents/deep_research/config.py"              : 5,
    "src/cosa/agents/deep_research/cost_tracker.py"        : 15,
    "src/cosa/agents/notification_proxy/config.py"         : 1,
    "src/cosa/agents/podcast_generator/api_client.py"      : 3,
    "src/cosa/agents/podcast_generator/config.py"          : 3,
    "src/cosa/agents/presentation_generator/api_client.py" : 3,
    "src/cosa/agents/presentation_generator/config.py"     : 4,
    "src/cosa/agents/swe_team/config.py"                   : 4,
    "src/cosa/agents/test_fix_expediter/config.py"         : 4,
    "src/cosa/agents/test_fix_expediter/job.py"            : 1,
    "src/cosa/repo/duplicate_check/proof/label_prep.py"    : 1,
    "src/cosa/repo/symindex/need_writer.py"                : 1,
    "src/cosa/utils/vertex_env.py"                         : 5,
    "src/cosa/utils/vertex_spend_ceiling.py"               : 1,
    "src/lupin_mcp/cosa_voice_mcp.py"                      : 1,
    "src/lupin_mcp/reuse_needset/smoke.py"                 : 1,
    "src/scripts/tfe_to_cc_phase1_smoke.py"                : 1,
    "src/scripts/tfe_to_cc_phase3_live.py"                 : 1,
    "src/scripts/verify_vertex_logging.py"                 : 1,
}


def source_files( root ):
    """
    List the tracked non-test Python source files of the tree.

    Ensures:
        - returns repo-relative paths from `git ls-files 'src/*.py'`, without test folders, virtualenvs or vendored packages
    """
    listed = subprocess.run( [ "git", "ls-files", "src/*.py" ], cwd=root, capture_output=True, text=True, check=True ).stdout.split()
    return [ path for path in listed if TEST_DIR.search( path ) is None and not any( part in path for part in SKIPPED_PARTS ) ]


def model_literals( root ):
    """
    Count the Claude model id literals per source file.

    Ensures:
        - returns { path: count } for every file holding at least one quoted `claude-<family>-<digit>` literal
    """
    counts = { path: len( MODEL_LITERAL.findall( ( pathlib.Path( root ) / path ).read_text( encoding="utf-8" ) ) ) for path in source_files( root ) }
    return { path: count for path, count in counts.items() if count > 0 }


def test_the_census_walks_the_source_tree_and_finds_the_known_literals():
    """Positive control: the walk sees over 1000 files and the BFE config's four literals."""
    root = cu.get_project_root()
    assert len( source_files( root ) ) > 1000
    assert model_literals( root )[ "src/cosa/agents/bug_fix_expediter/config.py" ] == 4


def test_every_model_id_literal_is_on_the_frozen_list():
    """A new hard-coded model id fails; put it in lupin-app.ini and read it from there."""
    found = model_literals( cu.get_project_root() )
    added = { path: count for path, count in found.items() if count > FROZEN.get( path, 0 ) }
    assert added == {}, f"new hard-coded model ids (move them to lupin-app.ini): {added}"
    assert found == FROZEN, f"a file dropped a model id; lower or remove its count in FROZEN: {found}"


def test_the_code_health_model_ids_now_live_only_in_the_ini():
    """The judge, rewrite, drafter and expansion ids are gone from their old modules."""
    found = model_literals( cu.get_project_root() )
    assert [ path for path in NOW_IN_INI if path in found ] == []
    assert "claude-fable" not in ( pathlib.Path( cu.get_project_root() ) / "src/cosa/repo/duplicate_check/proof/label_prep.py" ).read_text( encoding="utf-8" )
