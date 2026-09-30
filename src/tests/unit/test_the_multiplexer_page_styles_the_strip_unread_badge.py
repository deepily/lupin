"""
The multiplexer page links a stylesheet that draws the strip's unread badge (row d04ff119).

THE DEFECT. SessionStripRenderer sets `data-unread` and `data-unread-count` on a hidden session's icon
while focus is on. The rules that draw them lived only in css/notifications.css, which multiplexer.html
does not link, so the attributes were set and nothing showed. Every unit test passed, because they read
attributes; Chrome on the served bundle (3d959d529554, 2026-09-11) found no rule on the page matching
`data-unread` at all.

WHAT THIS PINS, AND WHAT IT CANNOT. That a sheet multiplexer.html links (not any sheet in the tree — the
defect was a rule in the wrong sheet) declares: the pulse on `.cc-strip-icon[data-unread="true"]`, with
its @keyframes defined in a linked sheet; the count via `content: attr(data-unread-count)` on its ::after;
and a rule hiding that ::after when the count attribute is absent (a managed worker). It cannot pin paint;
the Chrome check on the row is the real-browser proof.

Venue: :7999 (unit tier). Reads files only.
"""

import re

import cosa.utils.util as cu

STATIC   = cu.get_project_root() + "/src/lupin_app/static"
MUX_PAGE = STATIC + "/html/multiplexer.html"

_COMMENT   = re.compile( r"/\*.*?\*/", re.S )
_RULE      = re.compile( r"([^{}]+)\{([^{}]*)\}" )
_LINK      = re.compile( r'<link\s+rel="stylesheet"\s+href="/static/([^"?]+)' )
_KEYFRAMES = re.compile( r"@keyframes\s+([\w-]+)" )

PULSE_SELECTOR  = '.cc-strip-icon[data-unread="true"]'
COUNT_SELECTOR  = '.cc-strip-icon[data-unread="true"]::after'
WORKER_SELECTOR = '.cc-strip-icon[data-unread="true"]:not([data-unread-count])::after'


def _sheet_text( rel ):
    with open( STATIC + "/" + rel, encoding="utf-8" ) as f:
        return _COMMENT.sub( "", f.read() )


def _linked_sheets():
    with open( MUX_PAGE, encoding="utf-8" ) as f:
        html = re.sub( r"<!--.*?-->", "", f.read(), flags=re.S )
    return _LINK.findall( html )


def _rules( text ):
    """(selector, body) pairs; a selector list is split so each selector is matched alone."""
    out = []
    for m in _RULE.finditer( text ):
        for sel in m.group( 1 ).split( "," ):
            out.append( ( " ".join( sel.split() ), m.group( 2 ) ) )
    return out


def _bodies_for( selector, sheets ):
    return [ body for rel in sheets for sel, body in _rules( _sheet_text( rel ) ) if sel == selector ]


def test_the_instrument_sees_the_legacy_rules_and_the_page_links():
    """
    Positive control: the parser finds the badge rules in css/notifications.css, where they have always
    been, and reads a non-trivial link list off multiplexer.html. Without this, a broken parser or a moved
    page would make the assertions below fail for the wrong reason, or pass over nothing.
    """
    assert _bodies_for( COUNT_SELECTOR, [ "css/notifications.css" ] ), "the parser cannot see the legacy count rule"
    links = _linked_sheets()
    assert "css/multiplexer/session-strip.css" in links, links
    assert "css/notifications.css" not in links, "multiplexer.html now links the legacy sheet; revisit this guard"


def test_a_linked_sheet_draws_the_count():
    bodies = _bodies_for( COUNT_SELECTOR, _linked_sheets() )
    assert any( re.search( r"content\s*:\s*attr\(\s*data-unread-count\s*\)", b ) for b in bodies ), (
        f"no sheet multiplexer.html links gives { COUNT_SELECTOR } the count; the badge attributes "
        f"are set and nothing draws them"
    )


def test_a_linked_sheet_pulses_the_icon_with_keyframes_it_defines():
    sheets  = _linked_sheets()
    bodies  = _bodies_for( PULSE_SELECTOR, sheets )
    names   = [ m.group( 1 ) for b in bodies for m in re.finditer( r"animation\s*:\s*([\w-]+)", b ) ]
    assert names, f"no linked sheet animates { PULSE_SELECTOR }"
    defined = { k for rel in sheets for k in _KEYFRAMES.findall( _sheet_text( rel ) ) }
    missing = [ n for n in names if n not in defined ]
    assert missing == [ ], f"the pulse names @keyframes no linked sheet defines: { missing }"


def test_a_linked_sheet_hides_the_empty_circle_on_a_worker():
    bodies = _bodies_for( WORKER_SELECTOR, _linked_sheets() )
    assert any( re.search( r"display\s*:\s*none", b ) for b in bodies ), (
        f"no linked sheet hides { WORKER_SELECTOR }; a worker's icon has no count, so the circle draws empty"
    )
