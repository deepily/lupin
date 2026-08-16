"""
Unit tests for Coder tool-use notification summaries (2026-04-18).

Both TFE and BFE orchestrators carry an identical `_summarize_tool_use`
staticmethod that digests a ToolUseBlock into a compact, informative
single-line string for Phase 3 progress notifications. These tests
lock down the contract for both copies.

Replaces the prior bare-name format ("Coder: Bash") which was opaque
over long runs.
"""

from types import SimpleNamespace

from cosa.agents.test_fix_expediter.orchestrator import TFEOrchestrator
from cosa.agents.bug_fix_expediter.orchestrator import BFEOrchestrator


def _block( name: str, **inputs ) -> SimpleNamespace:
    """Minimal ToolUseBlock-duck for the summary function."""
    return SimpleNamespace( name=name, input=inputs )


# The two helpers are textually identical copies; test both to catch drift.
SUMMARIZERS = [ TFEOrchestrator._summarize_tool_use, BFEOrchestrator._summarize_tool_use ]


def test_bash_includes_command_first_line():
    for f in SUMMARIZERS:
        out = f( _block( "Bash", command="pytest src/tests/unit/test_x.py -v" ) )
        assert out == "Bash: pytest src/tests/unit/test_x.py -v"


def test_bash_truncates_long_command():
    long_cmd = "x" * 300
    for f in SUMMARIZERS:
        out = f( _block( "Bash", command=long_cmd ) )
        assert out.startswith( "Bash: " )
        assert len( out[ len( "Bash: " ): ] ) <= 100


def test_bash_uses_only_first_line_of_multiline_command():
    for f in SUMMARIZERS:
        out = f( _block( "Bash", command="echo hello\necho world\necho final" ) )
        assert out == "Bash: echo hello"


def test_bash_empty_command_falls_back_to_name():
    for f in SUMMARIZERS:
        assert f( _block( "Bash", command="" ) ) == "Bash"
        assert f( _block( "Bash" ) ) == "Bash"


def test_read_edit_write_show_file_path():
    for f in SUMMARIZERS:
        assert f( _block( "Read", file_path="src/conf/lupin-app.ini" ) ) == "Read: src/conf/lupin-app.ini"
        assert f( _block( "Edit", file_path="src/cosa/agents/registry.py" ) ) == "Edit: src/cosa/agents/registry.py"
        assert f( _block( "Write", file_path="/var/lupin/io/out.txt" ) ) == "Write: /var/lupin/io/out.txt"


def test_file_path_truncation_keeps_tail():
    # Long path — operator cares about basename + parent; keep the END.
    path = "src/tests/unit/" + ( "very_long_subdir/" * 10 ) + "test_something.py"
    for f in SUMMARIZERS:
        out = f( _block( "Read", file_path=path ) )
        assert out.startswith( "Read: " )
        assert out.endswith( "test_something.py" )  # tail preserved
        assert len( out[ len( "Read: " ): ] ) <= 100


def test_grep_and_glob_show_pattern():
    for f in SUMMARIZERS:
        assert f( _block( "Grep", pattern="JOB_ARG_CONTRACTS" ) ) == "Grep: JOB_ARG_CONTRACTS"
        assert f( _block( "Glob", pattern="**/*.py" ) ) == "Glob: **/*.py"


def test_unknown_tool_returns_bare_name():
    for f in SUMMARIZERS:
        assert f( _block( "WebSearch", query="anything" ) ) == "WebSearch"
        assert f( _block( "Task", subagent_type="Explore" ) ) == "Task"


def test_none_input_handled():
    b = SimpleNamespace( name="Bash", input=None )
    for f in SUMMARIZERS:
        assert f( b ) == "Bash"  # falls back to bare name


if __name__ == "__main__":
    import sys
    import pytest
    sys.exit( pytest.main( [ __file__, "-v" ] ) )
