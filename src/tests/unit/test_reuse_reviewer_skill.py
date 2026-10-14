"""
Pins the reuse-reviewer skill to the plan and to the exit-gate script that enforces it.
"""
import pathlib
import re

import cosa.utils.util as cu
from lupin_mcp import reuse_exit_gate

ROOT  = pathlib.Path( cu.get_project_root() )
SKILL = ROOT / ".claude" / "skills" / "reuse-reviewer" / "SKILL.md"
PLAN  = ROOT / "src/rnd/v0.2.2/2026.09.30-wiki-and-jev-for-code-reuse-review/2026.09.30-reuse-review-implementation-plan.md"


def _table( text ):
    """Ensures: returns the lines of the verdict-vocabulary table, header row to the last row."""
    lines = text.splitlines()
    start = next( i for i, l in enumerate( lines ) if l.startswith( "| `check_exists` verdict" ) )
    out   = []
    for l in lines[ start: ]:
        if not l.startswith( "|" ): break
        out.append( l )
    return out


POINTER = "the third label in plan-review.md section 4 (no prior art found)"


def _cells( line ):
    """Return the cells of a table line, stripped of backticks and spaces."""
    return [ c.replace( "`", "" ).strip() for c in line.strip().strip( "|" ).split( "|" ) ]


def test_skill_carries_the_plan_table_and_points_at_the_third_label():
    plan_rows = [ _cells( l ) for l in _table( PLAN.read_text( encoding="utf-8" ) ) ]
    skill     = [ _cells( l ) for l in SKILL.read_text( encoding="utf-8" ).splitlines() if l.startswith( "|" ) ]
    assert len( plan_rows ) == 6                                   # header, rule, four verdicts
    third = plan_rows[ 4 ]                                         # the third data row: its label is the one the skill points at
    assert third[ 0 ] == "NEW" and third[ 1 ] == "genuinely-new"
    for row in plan_rows[ :4 ] + plan_rows[ 5: ]: assert row in skill
    assert [ third[ 0 ], POINTER, third[ 2 ] ] in skill            # the pointer stands for the label, nothing else differs
    assert "genuinely-new" not in SKILL.read_text( encoding="utf-8" ) and "&#" not in SKILL.read_text( encoding="utf-8" )


def test_skill_names_the_flag_and_the_gate_modules():
    text = SKILL.read_text( encoding="utf-8" )
    assert text.startswith( "---\nname: reuse-reviewer\n" )
    for needle in ( "reuse review gating", "lupin_mcp.reuse_review_gate", "reuse_exit_gate.py", "symindex diff", "--all", "fetch_similar" ):
        assert needle in text


def test_the_ruling_shape_in_the_skill_is_the_shape_the_gate_parses():
    text  = SKILL.read_text( encoding="utf-8" )
    shape = re.search( r"^\s*(RULING <symbol id> :: .+)$", text, re.M ).group( 1 )
    line  = shape.replace( "<symbol id>", "m.f" ).replace( "DUPLICATE | EXTEND <symbol> | DISTINCT <why>", "DUPLICATE" ).replace( "<receipt id>", "abc123" )
    assert reuse_exit_gate.parse_rulings( line ) == { "m.f": [ { "ruling": "DUPLICATE", "receipt": "abc123" } ] }
