"""
split_check: a page cut into an index and parts keeps every old line, once.

OLD_PAGE has the shapes the real splits meet. It holds a title, headings and a table with a separator rule.
It also holds a fence with a heading-like line and a relative link, repeated lines, and relative and absolute
link targets. An image, a code span with link-shaped text and in-page anchor links complete it. The git
tests build a small real repo in a temp directory. The mutants (a dropped line, a doubled line and an
unmoved link) each must fail by name.
"""

import io
import json
import runpy
import subprocess
import sys

import pytest

from cosa.repo.doc_lint import split_check as sc

OLD_PAGE = """# Page title

Intro line with a [sibling](other.md) and an [outside](https://example.com/x) and a [top](#page-title).

## Alpha

| name | value |
|------|-------|
| one  | 1     |
| two  | 2     |

Alpha prose, see [the design](../rnd/design.md#intro) and ![shot](images/shot.png).

```python
# a comment that looks like a heading
link = "[not a link](local.md)"
```

Code span `[kept](local.md)` stays, and [absolute](/app/docs) too.

---

## Beta

Beta prose, back to [Alpha](#alpha).

---

Last line.
"""

INDEX = """# Page title

One line about the page.

- [Alpha](page/part-a.md#alpha)
- [Beta](page/part-b.md#beta)
"""

PART_A = """Part A of the page.

# Page title

Intro line with a [sibling](../other.md) and an [outside](https://example.com/x) and a [top](#page-title).

## Alpha

| name | value |
|------|-------|
| one  | 1     |
| two  | 2     |

Alpha prose, see [the design](../../rnd/design.md#intro) and ![shot](../images/shot.png).

```python
# a comment that looks like a heading
link = "[not a link](local.md)"
```

Code span `[kept](local.md)` stays, and [absolute](/app/docs) too.

---
"""

PART_B = """Part B of the page.

## Beta

Beta prose, back to [Alpha](a.md#alpha).

---

Last line.
"""

PART_B_GIT = PART_B.replace( "(a.md#alpha)", "(part-a.md#alpha)" )

NORMAL_KEYS = { "dropped", "doubled", "unmoved", "dangling", "index_added", "index_repeats", "parts", "structure", "unresolved_anchors", "max_added_exceeded", "pass", "old", "index", "refused", "message" }


def _compare( index=INDEX, a=PART_A, b=PART_B, **kwargs ):
    return sc.compare( OLD_PAGE, index, { "a.md": a, "b.md": b }, **kwargs )


def test_a_clean_split_passes_and_lists_what_it_added_and_moved():
    result = _compare()
    assert result[ "pass" ] is True
    assert result[ "dropped" ] == [] and result[ "doubled" ] == [] and result[ "unmoved" ] == []
    assert [ line for _, line in result[ "parts" ][ "a.md" ][ "added" ] ] == [ "Part A of the page." ]
    assert [ line for _, line in result[ "parts" ][ "b.md" ][ "added" ] ] == [ "Part B of the page." ]
    moved = result[ "parts" ][ "a.md" ][ "moved" ]
    assert [ ( m[ "old" ], m[ "new" ] ) for m in moved ] == [
        ( "other.md", "../other.md" ), ( "../rnd/design.md#intro", "../../rnd/design.md#intro" ), ( "images/shot.png", "../images/shot.png" )
    ]
    assert result[ "parts" ][ "b.md" ][ "moved" ] == []


def test_a_target_with_a_scheme_a_hash_a_slash_a_code_span_or_a_fence_does_not_move():
    assert sc.move_targets( "[a](https://x.org) [b](#h) [c](/app) [d](mailto:a@b.c) [e]()" ) == "[a](https://x.org) [b](#h) [c](/app) [d](mailto:a@b.c) [e]()"
    assert sc.move_targets( "see `[k](local.md)` and [m](local.md)" ) == "see `[k](local.md)` and [m](../local.md)"
    rows = sc.expected_lines( "[m](local.md)\n```\n[f](local.md)\n```\n" )
    assert [ ( old, expected ) for _, old, expected in rows ] == [
        ( "[m](local.md)", "[m](../local.md)" ), ( "```", "```" ), ( "[f](local.md)", "[f](local.md)" ), ( "```", "```" )
    ]


def test_a_dropped_line_fails_and_is_named_with_its_old_line_number():
    result = _compare( b=PART_B.replace( "Last line.\n", "" ) )
    assert result[ "pass" ] is False
    assert result[ "dropped" ] == [ { "line": "Last line.", "old_line": 29, "missing": 1 } ]
    assert result[ "doubled" ] == []


def test_a_doubled_line_fails_and_is_named_with_the_parts_that_hold_it():
    result = _compare( b=PART_B.replace( "## Beta\n", "## Beta\n\nAlpha prose, see [the design](../../rnd/design.md#intro) and ![shot](../images/shot.png).\n" ) )
    assert result[ "pass"] is False
    assert result[ "dropped" ] == []
    assert result[ "doubled" ] == [ { "line": "Alpha prose, see [the design](../rnd/design.md#intro) and ![shot](images/shot.png).", "extra": 1, "parts": [ "b.md" ] } ]
    again = _compare( b=PART_B + "Alpha prose, see [the design](../../rnd/design.md#intro) and ![shot](../images/shot.png).\n" + "Alpha prose, see [the design](../../rnd/design.md#intro) and ![shot](../images/shot.png).\n" )
    assert again[ "doubled" ][ 0 ][ "extra" ] == 2 and again[ "doubled" ][ 0 ][ "parts" ] == [ "b.md" ]


def test_a_line_the_old_page_had_twice_must_be_in_the_parts_twice():
    both = _compare()
    assert both[ "pass" ] is True
    one_rule = _compare( b=PART_B.replace( "---\n\n", "", 1 ) )
    assert one_rule[ "pass" ] is False
    assert one_rule[ "dropped" ] == [ { "line": "---", "old_line": 21, "missing": 1 } ]


def test_a_relative_target_left_without_the_prefix_is_unmoved_and_fails_by_name():
    result = _compare( a=PART_A.replace( "[sibling](../other.md)", "[sibling](other.md)" ) )
    assert result[ "pass" ] is False
    assert [ u[ "part" ] for u in result[ "unmoved" ] ] == [ "a.md" ]
    assert "[sibling](other.md)" in result[ "unmoved" ][ 0 ][ "line" ]
    assert len( result[ "dropped" ] ) == 1


def test_any_other_change_to_a_line_is_a_drop_and_an_addition():
    result = _compare( b=PART_B.replace( "Beta prose, back", "Beta prose, going back" ) )
    assert result[ "pass" ] is False
    assert [ d[ "line" ] for d in result[ "dropped" ] ] == [ "Beta prose, back to [Alpha](#alpha)." ]
    assert [ line for _, line in result[ "parts" ][ "b.md" ][ "added" ] ] == [ "Part B of the page.", "Beta prose, going back to [Alpha](a.md#alpha)." ]


def test_a_line_that_changed_inside_a_fence_or_a_code_span_is_not_excused_by_the_prefix_rule():
    fence   = _compare( a=PART_A.replace( 'link = "[not a link](local.md)"', 'link = "[not a link](../local.md)"' ) )
    span    = _compare( a=PART_A.replace( "`[kept](local.md)`", "`[kept](../local.md)`" ) )
    for result in ( fence, span ):
        assert result[ "pass" ] is False
        assert len( result[ "dropped" ] ) == 1


def test_the_index_adds_lines_freely_and_its_copies_of_old_lines_are_listed():
    result = _compare( index=INDEX + "\n---\n" )
    assert result[ "pass" ] is True
    assert [ r[ "line" ] for r in result[ "index_added" ] ][ :2 ] == [ "One line about the page.", "- [Alpha](page/part-a.md#alpha)" ]
    assert [ r[ "line" ] for r in result[ "index_repeats" ] ] == [ "# Page title", "---" ]


def test_an_old_line_kept_only_in_the_index_is_dropped_unless_index_lines_are_allowed():
    without_title = _compare( a=PART_A.replace( "# Page title\n\n", "" ) )
    assert without_title[ "pass" ] is False
    assert without_title[ "dropped" ] == [ { "line": "# Page title", "old_line": 1, "missing": 1 } ]
    allowed = _compare( a=PART_A.replace( "# Page title\n\n", "" ), allow_index_lines=True )
    assert allowed[ "pass" ] is True
    linked = sc.compare( "[a](x.md)\n", "[a](x.md)\n", { "p.md": "Part\n" }, allow_index_lines=True )
    assert linked[ "pass" ] is True and linked[ "dropped" ] == []


def test_max_added_fails_a_part_that_adds_more_lines_than_the_cap():
    padded = PART_B.replace( "Part B of the page.\n", "Part B of the page.\nA second added line.\n" )
    assert _compare( b=padded )[ "pass" ] is True
    assert _compare( b=padded, max_added=2 )[ "pass" ] is True
    over = _compare( b=padded, max_added=1 )
    assert over[ "pass" ] is False and over[ "max_added_exceeded" ] is True


def test_structure_counts_ignore_separator_rules_and_fenced_text():
    counts = sc.structure_counts( OLD_PAGE )
    assert counts == { "table_rows": 3, "fences": 2, "headings": 3, "link_targets": 8 }
    result = _compare()
    assert result[ "structure" ][ "old" ] == counts
    assert result[ "structure" ][ "parts" ][ "table_rows" ] == 3
    assert result[ "structure" ][ "parts" ][ "headings" ] == 3 and result[ "structure" ][ "index" ][ "headings" ] == 1 and result[ "structure" ][ "new_total" ][ "headings" ] == 4


def test_an_in_page_link_to_a_heading_that_moved_may_become_a_link_to_that_part_and_is_listed():
    result = _compare()
    assert result[ "pass" ] is True and result[ "dangling" ] == []
    assert result[ "parts" ][ "b.md" ][ "repointed" ] == [ { "line_number": 5, "old": "#alpha", "new": "a.md#alpha" } ]
    assert result[ "parts" ][ "a.md" ][ "repointed" ] == []


def test_an_in_page_link_left_pointing_at_a_heading_now_in_another_part_is_dangling_and_fails_by_name():
    result = _compare( b=PART_B.replace( "[Alpha](a.md#alpha)", "[Alpha](#alpha)" ) )
    assert result[ "pass" ] is False
    assert result[ "dropped" ] == [] and result[ "doubled" ] == [] and result[ "unmoved" ] == []
    assert result[ "dangling" ] == [ { "part": "b.md", "line_number": 5, "anchor": "alpha", "should_be": "a.md#alpha" } ]
    assert "DANGLING in-page link in b.md L5 (#alpha is in a.md)" in "\n".join( sc.format_report( { **result, "old": "r:p", "index": "i", "refused": None, "message": "x" } ) )


def test_a_link_to_the_wrong_part_for_the_heading_is_a_changed_line_not_a_repoint():
    result = _compare( b=PART_B.replace( "[Alpha](a.md#alpha)", "[Alpha](b.md#alpha)" ) )
    assert result[ "pass" ] is False
    assert [ d[ "line" ] for d in result[ "dropped" ] ] == [ "Beta prose, back to [Alpha](#alpha)." ]


def test_an_in_page_link_with_the_heading_in_its_own_part_stays_and_one_with_no_heading_anywhere_is_only_listed():
    old    = "## One\n\n[self](#one) and [gone](#nowhere)\n"
    result = sc.compare( old, "# idx\n", { "p.md": old } )
    assert result[ "pass" ] is True and result[ "dangling" ] == []
    assert result[ "unresolved_anchors" ] == [ { "part": "p.md", "anchor": "nowhere" } ]


def test_a_repointed_link_inside_a_code_span_or_a_fence_is_not_excused():
    old    = "## One\n\n`[x](#two)` is code.\n\n```\n[y](#two)\n```\n\n## Two\n"
    parts  = { "a.md": "## One\n\n`[x](#two)` is code.\n\n```\n[y](#two)\n```\n", "b.md": "## Two\n" }
    assert sc.compare( old, "# idx\n", parts )[ "pass" ] is True
    moved  = { "a.md": parts[ "a.md" ].replace( "`[x](#two)`", "`[x](b.md#two)`" ), "b.md": "## Two\n" }
    assert sc.compare( old, "# idx\n", moved )[ "pass" ] is False


def test_a_second_heading_with_the_same_text_has_the_suffixed_anchor():
    old    = "## Notes\n\nfirst\n\n## Notes\n\nsecond, see [first](#notes) and [again](#notes-1)\n"
    parts  = { "a.md": "## Notes\n\nfirst\n", "b.md": "## Notes\n\nsecond, see [first](a.md#notes) and [again](#notes-1)\n" }
    result = sc.compare( old, "# idx\n", parts )
    assert result[ "pass" ] is True and result[ "dangling" ] == []
    assert result[ "parts" ][ "b.md" ][ "repointed" ] == [ { "line_number": 3, "old": "#notes", "new": "a.md#notes" } ]


def test_non_blank_lines_drop_trailing_white_space_and_blank_lines():
    assert sc.non_blank_lines( "a  \r\n\n  b\n \t\n" ) == [ ( 1, "a" ), ( 3, "  b" ) ]


def _git( root, *args ):
    res = subprocess.run( [ "git", "-C", str( root ), "-c", "user.email=t@t", "-c", "user.name=t", *args ], capture_output=True, text=True )
    assert res.returncode == 0, res.stderr
    return res.stdout.strip()


@pytest.fixture
def repo( tmp_path ):
    _git( tmp_path, "init", "-q" )
    ( tmp_path / "docs" ).mkdir()
    ( tmp_path / "docs" / "page.md" ).write_text( OLD_PAGE, encoding="utf-8" )
    _git( tmp_path, "add", "." )
    _git( tmp_path, "commit", "-q", "-m", "old page" )
    old = _git( tmp_path, "rev-parse", "HEAD" )
    ( tmp_path / "docs" / "page" ).mkdir()
    ( tmp_path / "docs" / "page.md" ).write_text( INDEX, encoding="utf-8" )
    ( tmp_path / "docs" / "page" / "part-a.md" ).write_text( PART_A, encoding="utf-8" )
    ( tmp_path / "docs" / "page" / "part-b.md" ).write_text( PART_B_GIT, encoding="utf-8" )
    _git( tmp_path, "add", "." )
    _git( tmp_path, "commit", "-q", "-m", "split" )
    return { "root": tmp_path, "old": old, "new": _git( tmp_path, "rev-parse", "HEAD" ) }


PARTS = [ "docs/page/part-a.md", "docs/page/part-b.md" ]


def test_check_split_reads_the_old_page_from_its_revision_and_the_new_files_from_the_tree( repo ):
    result = sc.check_split( repo[ "root" ], repo[ "old" ], "docs/page.md", "docs/page.md", PARTS )
    assert result[ "pass" ] is True and result[ "refused" ] is None and result[ "message" ] == "nothing lost"
    assert result[ "part_paths" ] == PARTS
    assert NORMAL_KEYS <= result.keys()


def test_check_split_reads_new_files_as_of_a_revision_when_given_one( repo ):
    ( repo[ "root" ] / "docs" / "page" / "part-b.md" ).write_text( "mangled\n", encoding="utf-8" )
    assert sc.check_split( repo[ "root" ], repo[ "old" ], "docs/page.md", "docs/page.md", PARTS )[ "pass" ] is False
    pinned = sc.check_split( repo[ "root" ], repo[ "old" ], "docs/page.md", "docs/page.md", PARTS, new_rev=repo[ "new" ] )
    assert pinned[ "pass" ] is True


def test_check_split_names_a_dropped_line_in_its_message( repo ):
    ( repo[ "root" ] / "docs" / "page" / "part-b.md" ).write_text( PART_B_GIT.replace( "Last line.\n", "" ), encoding="utf-8" )
    result = sc.check_split( repo[ "root" ], repo[ "old" ], "docs/page.md", "docs/page.md", PARTS )
    assert result[ "pass" ] is False and result[ "message" ] == "1 dropped, 0 doubled"


@pytest.mark.parametrize( "kwargs, needle", [
    ( { "part_paths": [] }, "no parts" ),
    ( { "old_rev": "no-such-rev" }, "no-such-rev" ),
    ( { "part_paths": [ "docs/page/missing.md" ] }, "missing.md" ),
    ( { "old_path": "docs/nothing.md" }, "nothing.md" ),
] )
def test_check_split_refuses_with_a_reason_and_no_partial_result( repo, kwargs, needle ):
    args   = { "old_rev": repo[ "old" ], "old_path": "docs/page.md", "part_paths": PARTS }
    args.update( kwargs )
    result = sc.check_split( repo[ "root" ], args[ "old_rev" ], args[ "old_path" ], "docs/page.md", args[ "part_paths" ] )
    assert result[ "pass" ] is False and needle in result[ "refused" ]
    assert "dropped" not in result


def test_format_report_leads_with_the_verdict_and_names_each_defect():
    bad    = sc.check_split.__globals__[ "compare" ]( OLD_PAGE, INDEX, { "a.md": PART_A.replace( "[sibling](../other.md)", "[sibling](other.md)" ), "b.md": PART_B_GIT.replace( "Last line.\n", "" ) + "---\n---\n" }, max_added=0 )
    bad.update( { "old": "r:p", "index": "i", "refused": None, "message": "x" } )
    lines  = sc.format_report( bad )
    assert lines[ 0 ].startswith( "FAIL: x" )
    text   = "\n".join( lines )
    for needle in ( "DROPPED (old line", "DOUBLED (", "UNMOVED link in a.md", "a part adds more lines", "  added L", "index:", "structure", "table_rows" ):
        assert needle in text
    good = sc.compare( OLD_PAGE, INDEX, { "a.md": PART_A, "b.md": PART_B } )
    good.update( { "old": "r:p", "index": "i", "refused": None, "message": "nothing lost" } )
    report = "\n".join( sc.format_report( good ) )
    assert report.startswith( "PASS: nothing lost" ) and "  moved L" in report and "  index added L" in report and "  index repeats L" in report
    assert sc.format_report( { "refused": "OSError: gone" } ) == [ "REFUSED: OSError: gone" ]


def test_format_report_lists_an_in_page_link_that_leaves_its_part():
    result = sc.compare( "## A\n\n[b](#b)\n", "# idx\n", { "p.md": "## A\n\n[b](#b)\n" } )
    result.update( { "old": "r:p", "index": "i", "refused": None, "message": "x" } )
    assert "in-page link with no heading in any part (not made by the split): p.md #b" in sc.format_report( result )


def test_main_exit_codes_and_the_result_file( repo, tmp_path ):
    base   = [ "--repo-root", str( repo[ "root" ] ), "--old-rev", repo[ "old" ], "--old-path", "docs/page.md", "--index", "docs/page.md" ]
    parts  = [ arg for p in PARTS for arg in ( "--part", p ) ]
    out    = io.StringIO()
    assert sc.main( base + parts + [ "--out", str( tmp_path / "res" ), "--new-rev", repo[ "new" ] ], out ) == 0
    assert out.getvalue().startswith( "PASS: nothing lost" )
    saved  = json.loads( ( tmp_path / "res" / sc.RESULT_NAME ).read_text( encoding="utf-8" ) )
    assert saved[ "pass" ] is True and saved[ "refused" ] is None
    ( repo[ "root" ] / "docs" / "page" / "part-b.md" ).write_text( PART_B_GIT.replace( "Last line.\n", "" ), encoding="utf-8" )
    out    = io.StringIO()
    assert sc.main( base + parts, out ) == 1
    assert "DROPPED (old line 29, 1 missing): Last line." in out.getvalue()
    out    = io.StringIO()
    assert sc.main( base + parts + [ "--max-added", "0", "--allow-index-lines" ], out ) == 1
    out    = io.StringIO()
    assert sc.main( base, out ) == 2
    assert out.getvalue().startswith( "REFUSED: ValueError: no parts were given" )


def test_main_reads_sys_argv_and_writes_to_stdout_by_default( repo, monkeypatch, capsys ):
    monkeypatch.setattr( sys, "argv", [ "split_check", "--repo-root", str( repo[ "root" ] ), "--old-rev", repo[ "old" ], "--old-path", "docs/page.md",
                                        "--index", "docs/page.md", "--part", PARTS[ 0 ], "--part", PARTS[ 1 ] ] )
    assert sc.main() == 0
    assert capsys.readouterr().out.startswith( "PASS: nothing lost" )


def test_running_the_module_exits_with_main_s_code( repo, monkeypatch, capsys ):
    monkeypatch.setattr( sys, "argv", [ "split_check", "--repo-root", str( repo[ "root" ] ), "--old-rev", repo[ "old" ], "--old-path", "docs/page.md", "--index", "docs/page.md" ] )
    with pytest.raises( SystemExit ) as raised:
        runpy.run_module( "cosa.repo.doc_lint.split_check", run_name="__main__" )
    assert raised.value.code == 2
    assert "REFUSED" in capsys.readouterr().out


def test_a_part_that_holds_the_moved_line_and_an_unmoved_copy_fails_on_unmoved_alone():
    old    = "See [x](a.md) here.\nTail line.\n"
    result = sc.compare( old, "# idx\n", { "p1": "See [x](../a.md) here.\nTail line.\nSee [x](a.md) here.\n" } )
    assert result[ "dropped" ] == [] and result[ "doubled" ] == []
    assert result[ "unmoved" ] == [ { "part": "p1", "line_number": 3, "line": "See [x](a.md) here." } ]
    assert result[ "pass" ] is False
