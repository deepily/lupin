"""
No stylesheet gives the task row's Detail field a width (row 1657a852, the multiplexer half of
Rick's P0 row 17393c56).

THE DEFECT. The row once had a Detail COLUMN, sized `width: 1%`. ROW_SCHEMA moved Detail into the
disclosed controls row, where the same selector now lands on `div.task-disclosed-field.task-col-detail`
and collapses it to 9px, so its 📄 sits under the Actions field's label and a click cannot reach it.
17393c56 deleted the rule from css/task-list.css on 2026-09-04. An identical copy in
css/multiplexer/task-list.css survived, and multiplexer.html links that sheet AFTER the legacy one, so
the multiplexer kept the collapse for a week. Measured 2026-09-11 on the served page at 1280/1600/1920.

WHAT THIS PINS, AND WHAT IT CANNOT. A declaration: no rule whose selector names `task-col-detail`
declares `width`, in ANY stylesheet under static/css — every sheet, not the two that had the rule,
because the defect was precisely a copy living in a sheet nobody looked at. It cannot pin geometry;
the real-browser guards are test_row_geometry_is_one_shape_in_all_three_panes.py (classic page) and
the 📄 tests in test_multiplexer_task_list.py (multiplexer).

Venue: :7999 (unit tier). Reads files only.
"""

import glob
import re

import cosa.utils.util as cu

CSS_ROOT = cu.get_project_root() + "/src/lupin_app/static/css"

_COMMENT = re.compile( r"/\*.*?\*/", re.S )
_RULE    = re.compile( r"([^{}]+)\{([^{}]*)\}" )
_WIDTH   = re.compile( r"(^|;)\s*width\s*:", re.M )


def _css_files():
    return sorted( glob.glob( CSS_ROOT + "/**/*.css", recursive=True ) )


def _rules( path ):
    """(selector, body) pairs with comments stripped — a deletion note quoting the old rule is not a rule."""
    with open( path, encoding="utf-8" ) as f:
        text = _COMMENT.sub( "", f.read() )
    return [ ( m.group( 1 ).strip(), m.group( 2 ) ) for m in _RULE.finditer( text ) ]


def test_the_scan_sees_both_task_list_sheets_and_the_detail_selector():
    """
    The instrument can find something: without this, a wrong CSS_ROOT or a parser that matched
    nothing would make the real assertion below pass over an empty population.
    """
    files = _css_files()
    names = [ f[ len( CSS_ROOT ): ] for f in files ]
    assert "/task-list.css" in names, names
    assert "/multiplexer/task-list.css" in names, names

    detail_rules = [ ( f, sel ) for f in files for sel, _ in _rules( f ) if "task-col-detail" in sel ]
    assert detail_rules, "no rule names task-col-detail anywhere — the selector below would match nothing"


def test_no_rule_that_names_the_detail_field_declares_a_width():
    offenders = [
        f"{ path[ len( CSS_ROOT ): ] }: { sel }"
        for path in _css_files()
        for sel, body in _rules( path )
        if "task-col-detail" in sel and _WIDTH.search( body )
    ]
    assert offenders == [ ], (
        "a width on the Detail field collapses the disclosed field and puts its 📄 under the Actions "
        f"label (rows 17393c56, 1657a852): { offenders }"
    )
