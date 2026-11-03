"""
The Keep place toggle's on and hover rules carry Active's colours, in both sheets.

Requires:
    - The two stylesheets that style the focus bar toggles are tracked in the tree.

Ensures:
    - Each sheet has a rule for the on state and one for its hover.
    - Those rules declare the same background, border and text colour as the Active toggle.
    - Deleting a rule reddens this file, without a server.
"""

import re
from pathlib import Path

import pytest

import cosa.utils.util as cu

SHEETS = {
    "multiplexer" : "src/lupin_app/static/css/multiplexer/session-strip.css",
    "legacy"      : "src/lupin_app/static/css/notifications.css",
}

# The literal on look per sheet, so the comparison with Active is not the only anchor.
ON_LOOK = {
    "multiplexer" : { "background": "rgb(80, 160, 255, 0.28)", "border-color": "rgb(255, 255, 255, 0.4)", "color": "#fff" },
    "legacy"      : { "background": "#495057", "border-color": "#343a40", "color": "#fff" },
}
HOVER_LOOK = {
    "multiplexer" : ON_LOOK[ "multiplexer" ],
    "legacy"      : { "background": "#343a40", "border-color": "#212529" },
}

KEEP       = '.cc-strip-toggle[data-keep-place="true"]'
ACTIVE     = '.cc-strip-toggle[data-hide-inactive="true"]'
LOOK_KEYS  = ( "background", "border-color", "color" )
RULE_RE    = re.compile( r"([^{}]+)\{([^{}]*)\}" )
COMMENT_RE = re.compile( r"/\*.*?\*/", re.DOTALL )


def _rules( sheet: str ) -> list[ tuple[ list[ str ], dict ] ]:
    """Return the sheet's flat rules as ( selectors, declarations ), comments removed."""
    text  = COMMENT_RE.sub( "", Path( cu.get_project_root(), SHEETS[ sheet ] ).read_text() )
    rules = []
    for head, body in RULE_RE.findall( text ):
        decls = {}
        for line in body.split( ";" ):
            if ":" in line:
                key, value = line.split( ":", 1 )
                decls[ key.strip() ] = " ".join( value.split() )
        rules.append( ( [ s.strip() for s in head.split( "," ) ], decls ) )
    return rules


def _look( sheet: str, selector: str ) -> dict:
    """Merge the declarations of every rule that names the selector, later rules winning."""
    merged = {}
    for selectors, decls in _rules( sheet ):
        if selector in selectors: merged.update( decls )
    return merged


@pytest.mark.parametrize( "sheet", list( SHEETS ) )
def test_the_on_rule_has_the_active_toggles_colours( sheet ):
    keep, active = _look( sheet, KEEP ), _look( sheet, ACTIVE )
    assert keep, f"{sheet}: no rule for {KEEP}"
    assert active, f"{sheet}: no rule for {ACTIVE}, so the comparison has nothing to compare"
    for key in LOOK_KEYS:
        assert keep.get( key ) == active.get( key ), f"{sheet}: {key} keep={keep.get( key )} active={active.get( key )}"
        assert keep[ key ] == ON_LOOK[ sheet ][ key ], f"{sheet}: {key} is {keep[ key ]}"


@pytest.mark.parametrize( "sheet", list( SHEETS ) )
def test_the_hover_rule_has_the_active_toggles_hover_colours( sheet ):
    keep = _look( sheet, KEEP + ":hover" )
    assert keep, f"{sheet}: no rule for {KEEP}:hover"
    active = _look( sheet, ACTIVE + ":hover" ) or _look( sheet, ACTIVE )
    for key, want in HOVER_LOOK[ sheet ].items():
        assert keep.get( key ) == want == active.get( key ), f"{sheet}: hover {key} keep={keep.get( key )} active={active.get( key )}"
