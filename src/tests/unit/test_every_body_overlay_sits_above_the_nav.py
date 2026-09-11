"""
Every stylesheet rule for the task body overlay stacks it above the nav (row 1657a852, the
multiplexer half of 59b31b6f).

THE DEFECT. `.lupin-nav` is a fixed 56px top bar at z-index 9999. 59b31b6f raised the legacy
`.task-body-overlay` in css/task-list.css from 1000 to 10000 on 2026-09-01, because the nav painted
over the backdrop and its links stayed clickable through the open overlay. An identical rule in
css/multiplexer/task-list.css kept 1000, and that sheet loads after the legacy one, so the multiplexer
kept the defect. Found by test_mux_body_overlay_dismisses_on_backdrop_click (ts-50ab1f5f, 2026-09-11):
every retry reported `.lupin-nav-inner` intercepting the click.

WHAT THIS PINS, AND WHAT IT CANNOT. A declaration: every rule, in ANY sheet under static/css, whose
selector names `.task-body-overlay` as its own subject and declares a z-index declares one above the
nav's, read from lupin-nav.css rather than restated. It cannot pin the cascade or geometry; the
real-browser guard is the backdrop-click test above (multiplexer) and its classic-page twin.

Venue: :7999 (unit tier). Reads files only.
"""

import glob
import re

import cosa.utils.util as cu

CSS_ROOT = cu.get_project_root() + "/src/lupin_app/static/css"

_COMMENT = re.compile( r"/\*.*?\*/", re.S )
_RULE    = re.compile( r"([^{}]+)\{([^{}]*)\}" )
_Z_INDEX = re.compile( r"(?:^|;)\s*z-index\s*:\s*(-?\d+)", re.M )
# `.task-body-overlay` as a whole class name ending the compound selector — not
# `.task-body-overlay-content`, and not a descendant such as `.task-body-overlay .x`.
_OVERLAY_SUBJECT = re.compile( r"\.task-body-overlay(?![\w-])(?:[.:#\[][^\s,>+~]*)?\s*$" )


def _css_files():
    return sorted( glob.glob( CSS_ROOT + "/**/*.css", recursive=True ) )


def _rules( path ):
    """(selector, body) pairs with comments stripped — a note quoting an old rule is not a rule."""
    with open( path, encoding="utf-8" ) as f:
        text = _COMMENT.sub( "", f.read() )
    return [ ( m.group( 1 ).strip(), m.group( 2 ) ) for m in _RULE.finditer( text ) ]


def _nav_z_index():
    values = [
        int( z.group( 1 ) )
        for sel, body in _rules( CSS_ROOT + "/lupin-nav.css" )
        if sel == ".lupin-nav"
        for z in _Z_INDEX.finditer( body )
    ]
    assert len( values ) == 1, f".lupin-nav should declare exactly one z-index in lupin-nav.css; found { values }"
    return values[ 0 ]


def _overlay_z_indexes():
    return [
        ( path[ len( CSS_ROOT ): ], sel, int( z.group( 1 ) ) )
        for path in _css_files()
        for sel, body in _rules( path )
        if any( _OVERLAY_SUBJECT.search( part.strip() ) for part in sel.split( "," ) )
        for z in _Z_INDEX.finditer( body )
    ]


def test_the_scan_finds_the_overlay_in_both_task_list_sheets():
    """
    The instrument can find something: a wrong CSS_ROOT or a selector pattern that matched nothing
    would make the real assertion below pass over an empty population.
    """
    sheets = sorted( { path for path, _, _ in _overlay_z_indexes() } )
    assert sheets == [ "/multiplexer/task-list.css", "/task-list.css" ], sheets


def test_every_body_overlay_z_index_is_above_the_nav():
    nav       = _nav_z_index()
    offenders = [ f"{ path }: { sel } z-index { z }" for path, sel, z in _overlay_z_indexes() if z <= nav ]
    assert offenders == [ ], (
        f"the nav is z-index { nav }; an overlay at or below it lets the nav cover the backdrop and keeps "
        f"its links clickable through the open overlay (59b31b6f, row 1657a852): { offenders }"
    )
