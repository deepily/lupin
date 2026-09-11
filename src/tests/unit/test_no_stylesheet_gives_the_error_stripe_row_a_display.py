"""
No stylesheet gives the task row's error-stripe ROW a display (row 1657a852).

THE DEFECT. Since f3cfe655 (2026-09-05) both clients render one `<tr class="task-row-error-stripe" hidden>`
under every task row and un-hide it only when a verb is refused. css/multiplexer/task-list.css still carried
`.task-list-table .task-row-error-stripe { display: block; background: #f8d7da; … }` from when the stripe
was a cell appended inside the row. An author `display` beats the browser's `[hidden] { display: none }`,
so every task row in the multiplexer showed an empty pink band. Found in the rebaselined
test_task_editing_controls_visual image (ts-12a6d962, 2026-09-11).

WHAT THIS PINS, AND WHAT IT CANNOT. A declaration: no rule, in ANY sheet under static/css, whose selector has
the stripe ROW as its subject (ends in `.task-row-error-stripe`, not `.task-row-error-stripe td`) declares
`display`. Every sheet, because this defect was a copy in a sheet nobody looked at. It cannot pin paint;
the real-browser guard is test_drop_blank_reason_shows_inline_error_and_fires_no_request, which now asserts
the stripe is hidden before the refusal and shown after it.

Venue: :7999 (unit tier). Reads files only.
"""

import glob
import re

import cosa.utils.util as cu

CSS_ROOT = cu.get_project_root() + "/src/lupin_app/static/css"

_COMMENT = re.compile( r"/\*.*?\*/", re.S )
_RULE    = re.compile( r"([^{}]+)\{([^{}]*)\}" )
_DISPLAY = re.compile( r"(^|;)\s*display\s*:", re.M )
# The stripe row as the subject of one selector: the class ends the selector, optionally
# followed by attribute/pseudo-class qualifiers on that same element (e.g. `[hidden]`, `:not(...)`).
_ROW_SUBJECT = re.compile( r"\.task-row-error-stripe(?![\w-])(?:[\[:][^\s,>+~]*)?\s*$" )


def _css_files():
    return sorted( glob.glob( CSS_ROOT + "/**/*.css", recursive=True ) )


def _selectors_and_bodies( path ):
    """(one selector, body) pairs with comments stripped; a selector list is split."""
    with open( path, encoding="utf-8" ) as f:
        text = _COMMENT.sub( "", f.read() )
    return [
        ( " ".join( sel.split() ), m.group( 2 ) )
        for m in _RULE.finditer( text )
        for sel in m.group( 1 ).split( "," )
    ]


def test_the_scan_sees_stripe_rules_in_both_task_list_sheets():
    """
    The instrument can find something: a wrong CSS_ROOT or a parser that matched nothing would make the
    assertion below pass over an empty population. Both task-list sheets style the stripe's cell.
    """
    names = { f[ len( CSS_ROOT ): ] for f in _css_files() for sel, _ in _selectors_and_bodies( f ) if "task-row-error-stripe" in sel }
    assert { "/task-list.css", "/multiplexer/task-list.css" } <= names, sorted( names )


def test_the_row_subject_pattern_tells_the_row_from_its_cell():
    """The predicate itself: the row and a qualified row match; the cell and a descendant do not."""
    assert _ROW_SUBJECT.search( ".task-list-table .task-row-error-stripe" )
    assert _ROW_SUBJECT.search( ".task-row-error-stripe[hidden]" )
    assert not _ROW_SUBJECT.search( ".task-list-table .task-row-error-stripe td" )
    assert not _ROW_SUBJECT.search( ".task-row-error-stripe-extra" )


def test_no_rule_on_the_stripe_row_declares_a_display():
    offenders = [
        f"{ path[ len( CSS_ROOT ): ] }: { sel }"
        for path in _css_files()
        for sel, body in _selectors_and_bodies( path )
        if _ROW_SUBJECT.search( sel ) and _DISPLAY.search( body )
    ]
    assert offenders == [ ], (
        "a display on the error-stripe row beats its `hidden` attribute and paints an empty stripe under "
        f"every task row (row 1657a852): { offenders }"
    )
