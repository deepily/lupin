"""
Pins the reuse-reviewer skill to the plan and to the exit-gate script that enforces it.
"""
import io
import json
import pathlib
import re

import cosa.utils.util as cu
from lupin_mcp import reuse_exit_gate
from lupin_mcp import reuse_review_gate as gate

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


def test_skill_carries_the_plan_table_without_the_retired_new_row():
    plan_rows = [ _cells( l ) for l in _table( PLAN.read_text( encoding="utf-8" ) ) ]
    skill     = [ _cells( l ) for l in SKILL.read_text( encoding="utf-8" ).splitlines() if l.startswith( "|" ) ]
    assert len( plan_rows ) == 6                                   # header, rule, four verdicts
    third = plan_rows[ 4 ]                                         # the old plan's NEW row: Rick's ruling D1 retired it from the checker's verdicts
    assert third[ 0 ] == "NEW" and third[ 1 ] == "genuinely-new"
    for row in plan_rows[ :4 ] + plan_rows[ 5: ]: assert row in skill
    assert not [ row for row in skill if row[ 0 ] == "NEW" ]       # the skill no longer lists NEW as a verdict
    text = SKILL.read_text( encoding="utf-8" ).splitlines()
    head = next( i for i, l in enumerate( text ) if l.startswith( "| `check_exists` verdict" ) )
    assert sum( 1 for l in text[ :head ] if l.startswith( "```" ) ) % 2 == 0     # an even number of fences above it: the table is outside every code block
    body = SKILL.read_text( encoding="utf-8" )
    assert "genuinely-new" not in body and "&#" not in body
    assert "`NO_MATCH`" in body and "no longer returns `NEW`" in body


def test_skill_names_the_flag_and_the_gate_modules():
    text = SKILL.read_text( encoding="utf-8" )
    assert text.startswith( "---\nname: reuse-reviewer\n" )
    for needle in ( "reuse review gating", "lupin_mcp.reuse_review_gate", "reuse_exit_gate.py", "symindex diff", "--all", "fetch_similar" ):
        assert needle in text


def test_the_ruling_shape_in_the_skill_is_the_shape_the_gate_parses():
    text  = SKILL.read_text( encoding="utf-8" )
    shape = re.search( r"^\s*(RULING <symbol id> :: .+)$", text, re.M ).group( 1 )
    line  = shape.replace( "<symbol id>", "m.f" ).replace( "DUPLICATE | EXTEND <symbol> | DISTINCT <why>", "DUPLICATE" ).replace( "<receipt id>", "abc123" )
    assert reuse_exit_gate.parse_rulings( line ) == { "m.f": [ { "ruling": "DUPLICATE", "receipt": "abc123", "search": None } ] }


def test_the_skill_asks_for_a_recorded_search_and_one_searched_line_per_candidate():
    text  = SKILL.read_text( encoding="utf-8" )
    shape = re.search( r"^\s*(SEARCHED <symbol id> :: .+)$", text, re.M ).group( 1 )
    assert shape == "SEARCHED <symbol id> :: <search id> :: <candidate id> :: SAME_JOB | RELATED | UNRELATED :: <why>"
    assert "`record_search( receipt_id )`" in text and "`extra_terms`" in text and "`entry` and `language`" in text
    assert text.index( "record_search" ) < text.index( "5. **Rule**" )                 # the search comes before the ruling
    assert text.index( "SEARCHED <symbol id>" ) < text.index( "RULING <symbol id>" )   # and the ruling line stays the first RULING line of the shape
    assert text.count( ":: search: <search id>" ) == 1                                # the DISTINCT form cites its search, and only that form does


# ---- C2: the skill writes a kind on every finding (Plan 3 section 12.3) ----

def _sample_findings():
    """Ensures: returns the findings list of the skill's own example."""
    text   = SKILL.read_text( encoding="utf-8" )
    blocks = re.findall( r"```json\n(.*?)\n   ```", text, re.S )
    assert len( blocks ) == 1
    return json.loads( "\n".join( line[ 3: ] if line.startswith( "   " ) else line for line in blocks[ 0 ].splitlines() ) )


def _ini( tmp_path, value ):
    path = tmp_path / "lupin-app.ini"
    path.write_text( f"[default]\nreuse review gating = {value}\n", encoding="utf-8" )
    return str( path )


def test_the_skills_example_findings_file_runs_through_the_gate_and_blocks_on_its_reuse_findings( tmp_path ):
    findings = _sample_findings()
    path     = tmp_path / "findings.json"; path.write_text( json.dumps( findings ), encoding="utf-8" )
    out      = io.StringIO()
    assert gate.main( [ "--findings", str( path ), "--ini", _ini( tmp_path, "true" ) ], out=out ) == 1
    verdict  = json.loads( out.getvalue() )
    assert ( verdict[ "mode" ], verdict[ "count" ] ) == ( "reject", 3 )
    assert [ f[ "kind" ] for f in verdict[ "blocking" ] ] == [ "no_outcome_line", "ignored_ruling" ]     # the linter record in the example is advisory and is not among them
    report = io.StringIO()
    assert gate.main( [ "--findings", str( path ), "--ini", _ini( tmp_path, "false" ) ], out=report ) == 0     # the same file only reports while the flag is false
    assert json.loads( report.getvalue() )[ "count" ] == 3


def test_every_finding_in_the_skills_example_has_a_kind_the_gate_knows_or_is_a_linter_record():
    for finding in _sample_findings():
        assert gate.kind_of( finding ) in gate.REUSE_KINDS + ( gate.ADVISORY_KIND, )


def test_the_skill_names_every_blocking_kind_the_gate_knows_and_the_could_not_check_exit():
    text = SKILL.read_text( encoding="utf-8" )
    for kind in gate.REUSE_KINDS: assert f"`{kind}`" in text
    assert "`docstring_lint`" in text and "Exit code 3 means the gate could not check" in text and str( gate.EXIT_COULD_NOT_CHECK ) in text
    assert "A finding with no kind blocks" in text
