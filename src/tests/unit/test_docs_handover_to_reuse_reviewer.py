"""
Pins the handover of reuse review to the skill.
"""

import os

import cosa.utils.util as cu

SKILL = ".claude/skills/reuse-reviewer/SKILL.md"


def _read( rel ):
    """
    Read one tracked file under the project root.

    Requires:
        - rel is a path relative to the project root

    Ensures:
        - returns the file's text
    """
    with open( os.path.join( cu.get_project_root(), rel ), encoding="utf-8" ) as handle:
        return handle.read()


def test_skill_file_exists():
    assert os.path.isfile( os.path.join( cu.get_project_root(), SKILL ) )


def test_docstring_standard_hands_enforcement_to_the_skill():
    text = _read( "src/docs/docstring-standard.md" )
    assert "## Ongoing enforcement" in text
    assert SKILL in text.split( "## Ongoing enforcement" )[ 1 ]


def test_claude_md_pointer_table_row_names_the_skill():
    rows = [ line for line in _read( "CLAUDE.md" ).splitlines() if line.startswith( "| Reuse review of a diff |" ) ]
    assert len( rows ) == 1
    assert SKILL in rows[ 0 ]


def test_skill_runs_both_linters_and_the_dashboard_check_and_cites_the_standard():
    step = _read( SKILL ).split( "6. **Run plan 1's linters**" )[ 1 ].split( "7. **Report or reject.**" )[ 0 ]
    for needle in [ "docstring_lint --strict", "md_lint --strict", "doc_metrics dashboard check", "src/docs/docstring-standard.md" ]:
        assert needle in step, needle
