"""
A pane can MOUNT, RENDER, and be entirely unstyled — and every test that builds
the component itself stays green, because none of them loads CSS.

THE DEFECT THIS EXISTS FOR (measured 2026-09-06 at merge sha ffc53bd6, Rio ⚡,
row 87812328): `epicBoardTable.ts` emits `.epic-group`; `.epic-group` is defined
ONLY in `static/css/epic-board.css`; `multiplexer.html` linked 21 stylesheets and
that was not one of them. So `epic-board.css:135`

    tbody.epic-group.collapsed .epic-row { display: none; }

never reached the page: the accordion's chevron flipped, the class toggled, and
NOTHING MOVED. A user reads that as a broken toggle, not a missing stylesheet.
The holding area carried the same defect by the same mechanism — its
`.holding-area-*` rules lived in the legacy `static/css/task-list.css`, and the
multiplexer links `static/css/multiplexer/task-list.css`, a different file.

🔴 WHY THE OBVIOUS TEST DOES NOT WORK. A test asserting the class is EMITTED
passes today AND after a broken fix — it cannot see the defect it is written for.
The assertion has to be that THE PAGE LOADS A SHEET THAT DEFINES THE CLASS.

🔴 AND WHY NEITHER SIDE IS HAND-WRITTEN (§ WHEN THE FIX FOR AN ENUMERATION DEFECT
IS ITSELF AN ENUMERATION). Three provenances, none of them a list in this file:

    what a pane emits      <- parsed from the .ts template source
    what a page loads      <- parsed from that page's own <link rel=stylesheet>
    what a sheet defines   <- parsed from the .css files those links name

The comparison's two sides therefore cannot move together. A hand-written
expected-list on both ends would agree with itself no matter what shipped
(§ A COMPARISON WHOSE TWO SIDES COME FROM ONE SOURCE CANNOT DISAGREE).

SCOPE — read this before widening the assertion. The predicate is "a class that
IS defined in the CSS tree must be defined in a sheet THIS page links." A class
defined in NO sheet anywhere (`.fleet-col-role`, `.holding-area-table`,
`.holding-wont-fix-all-reason` at this sha) is a DIFFERENT question — dead weight
or a JS/test hook — and is deliberately out of scope here. Folding it in would
redden this guard for a reason that has nothing to do with linkage, which is how
a guard stops meaning anything.

:7999-eligible — static, pure-Python, no server, no state mutation.
"""

import os
import re

import pytest

import cosa.utils.util as cu

STATIC = os.path.join( cu.get_project_root(), "src", "lupin_app", "static" )
CSS_DIR = os.path.join( STATIC, "css" )

# 🔴 THE CONTRACT ARM IS multiplexer.html ALONE, AND THAT IS A CORRECTION, NOT A
# NARROWING FOR CONVENIENCE. The first cut of this file also asserted the contract
# against notifications.html and reddened its fleet-status pane over
# `.fleet-offline-toggle`. That was a FALSE ACCUSATION: these templates live under
# `js/multiplexer/` and notifications.html does not load them — measured, it loads
# `notifications.js` and its own legacy renderer, and the mux ES modules appear in
# no <script> tag on that page. Asking whether the legacy page styles a class the
# MULTIPLEXER's template emits is the wrong question, and the answer it produced
# was a mux-only feature reported as a legacy-page defect.
#
# ⚠️ It also cost me a positive control I had believed in. `epic board ×
# notifications.html` PASSED in that cut and I read it as the instrument proving
# it can return OK. It passes because the legacy client is a carbon-copy that
# happens to emit the same class NAMES — two routes coinciding, not agreeing
# (§ TWO SIDES THAT DERIVE ONE VALUE BY DIFFERENT ROUTES). The real control is the
# `task list` arm below: same page, same code path, genuinely styled, so a parser
# that reported everything as missing would redden it.
PAGES = ( "multiplexer.html", )

# notifications.html is still READ — but only as the reference side of the drift
# check at the bottom, in the one direction that is meaningful: a class the legacy
# client styles and the multiplexer does not.
LEGACY_PAGE = "notifications.html"

# The render templates whose emissions are under contract. This IS a list, and it
# is the one side that has to be: a directory walk would sweep in templates for
# panes these two pages do not host, and the resulting failures would be about
# the walk rather than about linkage. It is pinned by
# `test_every_named_template_exists` below, so a rename cannot silently empty it.
TEMPLATES = {
    "epic board"   : "js/multiplexer/render/templates/epicBoardTable.ts",
    "holding area" : "js/multiplexer/render/templates/holdingAreaTable.ts",
    "task list"    : "js/multiplexer/render/templates/taskListTable.ts",
    "fleet status" : "js/multiplexer/render/templates/fleetStatusTable.ts",
    "section bar"  : "js/multiplexer/render/templates/sectionToolbar.ts",
}


def _read( path ):
    with open( path, encoding="utf-8" ) as fh:
        return fh.read()


def _strip_css_comments( css ):
    return re.sub( r"/\*.*?\*/", "", css, flags=re.DOTALL )


def _strip_ts_comments( ts ):
    ts = re.sub( r"/\*.*?\*/", "", ts, flags=re.DOTALL )
    return re.sub( r"^\s*//.*$", "", ts, flags=re.MULTILINE )


def _linked_sheets( page ):
    """Absolute paths of the stylesheets THIS page links, in cascade order.

    Read from the page's own <link> tags — the point of the whole guard is that
    nobody gets to assert this from memory.
    """
    html  = _read( os.path.join( STATIC, "html", page ) )
    hrefs = re.findall( r'<link[^>]+rel="stylesheet"[^>]*href="([^"]+)"', html )
    hrefs += re.findall( r'<link[^>]+href="([^"]+)"[^>]*rel="stylesheet"', html )
    out = []
    for href in hrefs:
        href = href.split( "?" )[ 0 ]           # drop the ?v= cache-bust token
        if not href.startswith( "/static/" ):
            continue
        path = os.path.join( STATIC, href[ len( "/static/" ): ] )
        if path not in out:
            out.append( path )
    return out


def _selectors_defined( css_paths ):
    """(classes, ids) any of these sheets defines.

    Only selector text is scanned — everything OUTSIDE a `{ }` block — so a
    colour value or a font name can never be mistaken for a class.
    """
    classes, ids = set(), set()
    for path in css_paths:
        if not os.path.isfile( path ):
            continue
        css = _strip_css_comments( _read( path ) )
        for chunk in re.findall( r'([^{}]*)\{', css ):
            classes.update( re.findall( r'\.([A-Za-z][A-Za-z0-9_-]*)', chunk ) )
            ids.update(     re.findall( r'#([A-Za-z][A-Za-z0-9_-]*)', chunk ) )
    return classes, ids


def _elements_emitted( ts_path ):
    """[( class-tokens, id-or-None )] — one entry per element the template builds.

    Grouped BY ELEMENT rather than flattened into one class set, because an
    element may legitimately be styled through its id instead of its class:
    `sectionToolbar.ts` sets className "section-toolbar" AND id "section-toolbar",
    and the multiplexer deliberately styles `#section-toolbar`. Flattening would
    accuse that element of being unstyled when it is not.
    """
    ts = _strip_ts_comments( _read( ts_path ) )

    by_var = {}                                   # var -> { "classes": set, "id": str|None }

    def slot( var ):
        return by_var.setdefault( var, { "classes": set(), "id": None } )

    def tokens_of( literal ):
        out = set()
        for tok in literal.split():
            # `${ x }` interpolations are runtime values, not literals we can check
            if "${" in tok or "$" in tok or "{" in tok or "}" in tok:
                continue
            if re.fullmatch( r'[a-z][a-z0-9-]*', tok ):
                out.add( tok )
        return out

    for m in re.finditer( r'(\w+)\.className\s*\+?=\s*([`"\'])(.*?)\2', ts, flags=re.DOTALL ):
        slot( m.group( 1 ) )[ "classes" ] |= tokens_of( m.group( 3 ) )

    for m in re.finditer( r'(\w+)\.classList\.(?:add|toggle)\(([^)]*)\)', ts ):
        lits = re.findall( r'["\']([A-Za-z0-9_-]+)["\']', m.group( 2 ) )
        slot( m.group( 1 ) )[ "classes" ] |= { l for l in lits if re.fullmatch( r'[a-z][a-z0-9-]*', l ) }

    for m in re.finditer( r'(\w+)\.id\s*=\s*([`"\'])([A-Za-z0-9_-]+)\2', ts ):
        slot( m.group( 1 ) )[ "id" ] = m.group( 3 )

    # class="..." inside template strings — these carry no variable name, so each
    # becomes its own element with no id.
    anon = []
    for m in re.finditer( r'class=\\?["\']([^"\'\\]+)', ts ):
        toks = tokens_of( m.group( 1 ) )
        if toks:
            anon.append( ( toks, None ) )

    return [ ( v[ "classes" ], v[ "id" ] ) for v in by_var.values() if v[ "classes" ] ] + anon


def _every_class_in_tree():
    """Every class defined ANYWHERE under static/css — the 'is this a real rule
    at all' reference, so a class nothing styles is not read as a linkage gap."""
    paths = []
    for root, _dirs, files in os.walk( CSS_DIR ):
        paths += [ os.path.join( root, f ) for f in files if f.endswith( ".css" ) ]
    return _selectors_defined( paths )[ 0 ]


def _unstyled( page, template_rel ):
    """Classes this template emits that the CSS tree DOES style but this page
    cannot reach. The defect, stated as a set."""
    linked_classes, linked_ids = _selectors_defined( _linked_sheets( page ) )
    in_tree = _every_class_in_tree()

    missing = set()
    for classes, elem_id in _elements_emitted( os.path.join( STATIC, template_rel ) ):
        if elem_id is not None and elem_id in linked_ids:
            continue                              # styled through its id — fine
        for cls in classes:
            if cls in in_tree and cls not in linked_classes:
                missing.add( cls )
    return missing


# ---------------------------------------------------------------------------
# Positive controls — a parser that reads nothing passes every assertion below
# it (§ AN EMPTY RESULT IS TWO DIFFERENT FAILURES WEARING ONE FACE)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize( "page", PAGES + ( LEGACY_PAGE, ) )
def test_the_page_parser_finds_the_sheets_it_links( page ):
    sheets = _linked_sheets( page )
    assert len( sheets ) >= 5, f"{page}: parsed only {len(sheets)} stylesheets — the parser, not the page"
    for path in sheets:
        assert os.path.isfile( path ), f"{page} links a sheet that is not on disk: {path}"


@pytest.mark.parametrize( "name,rel", sorted( TEMPLATES.items() ) )
def test_every_named_template_exists( name, rel ):
    assert os.path.isfile( os.path.join( STATIC, rel ) ), f"{name}: TEMPLATES names a file that is gone: {rel}"


@pytest.mark.parametrize( "name,rel", sorted( TEMPLATES.items() ) )
def test_the_template_parser_finds_classes( name, rel ):
    elements = _elements_emitted( os.path.join( STATIC, rel ) )
    emitted  = set().union( *[ c for c, _ in elements ] ) if elements else set()
    assert emitted, f"{name}: parsed ZERO classes out of {rel} — a loop over nothing passes everything"


def test_the_css_tree_scan_is_not_empty():
    assert len( _every_class_in_tree() ) >= 100, "the css-tree scan found almost nothing — the walk, not the tree"


# ---------------------------------------------------------------------------
# The contract
# ---------------------------------------------------------------------------

@pytest.mark.parametrize( "page", PAGES )
@pytest.mark.parametrize( "name,rel", sorted( TEMPLATES.items() ) )
def test_every_class_a_pane_emits_reaches_a_sheet_the_page_links( page, name, rel ):
    missing = _unstyled( page, rel )
    assert not missing, (
        f"{page} renders the {name} pane UNSTYLED.\n"
        f"  These classes are defined in the CSS tree but in NO sheet this page links:\n"
        f"    {sorted( missing )}\n"
        f"  The pane will mount and render; its styling and any display:none collapse\n"
        f"  rule will silently do nothing. Link the sheet that defines them.\n"
        f"  Sheets this page currently links:\n"
        + "".join( f"    {os.path.relpath( p, STATIC )}\n" for p in _linked_sheets( page ) )
    )


# ---------------------------------------------------------------------------
# ORDER. Presence is not enough — and this section exists because the presence
# assertion above PASSED with the links in either position, so it could not fail
# for the thing the ordering prevents (Mr. Radio 🦉 caught that, 2026-09-06).
# ---------------------------------------------------------------------------

# Legacy top-level sheets the multiplexer links to reach rules the mux sheets
# never defined. Read from the page below rather than trusted from here — this
# tuple only says WHICH sheets carry the ordering obligation.
LEGACY_SHEETS_ON_MUX = ( "css/task-list.css", "css/epic-board.css" )


def test_the_legacy_sheets_load_before_the_multiplexer_block():
    """A legacy sheet linked AFTER the mux block re-styles the task list.

    🔴 THIS IS A CASCADE FACT, NOT A STYLE PREFERENCE. Measured 2026-09-06 at
    sha ffc53bd6: `css/task-list.css` defines 90 class names,
    `css/multiplexer/task-list.css` defines 60, and 51 of those names are the
    SAME — `.task-group`, `.task-row`, `.task-list-table`, every `.task-col-*`.
    At equal specificity the LAST sheet wins. So:

        legacy BEFORE mux  ->  mux keeps authority on all 51; legacy supplies only
                               what the mux never defined (.epic-group*, .holding-area-*)
        legacy AFTER  mux  ->  legacy wins all 51 and re-styles the pane Rick uses

    (A peer measured 57 of 70 over a wider sheet set. The two counts are taken
    over different populations and are not in conflict — both say the shared
    surface is large and the order decides it.)
    """
    sheets = [ os.path.relpath( p, STATIC ).replace( os.sep, "/" ) for p in _linked_sheets( "multiplexer.html" ) ]

    first_mux = next( ( i for i, s in enumerate( sheets ) if s.startswith( "css/multiplexer/" ) ), None )
    assert first_mux is not None, "no css/multiplexer/ sheet is linked at all — the parser, not the page"

    for legacy in LEGACY_SHEETS_ON_MUX:
        assert legacy in sheets, (
            f"multiplexer.html no longer links {legacy}. The epic-board and holding-area "
            f"panes render unstyled without it."
        )
        assert sheets.index( legacy ) < first_mux, (
            f"{legacy} is linked at position {sheets.index( legacy )}, AFTER the first "
            f"css/multiplexer/ sheet at position {first_mux} ({sheets[ first_mux ]}).\n"
            f"  51 class names are defined in BOTH that legacy sheet and "
            f"css/multiplexer/task-list.css. Later wins, so in this position the legacy\n"
            f"  sheet re-styles the multiplexer's task list. Move it above the block."
        )


def test_task_list_css_precedes_epic_board_css_on_every_page_linking_both():
    """`epic-board.css:9` says it deliberately RE-DECLARES the status custom props
    that `task-list.css` sets, so the pair is order-dependent wherever both appear.

    Asserted on EVERY page that links both rather than on a named page, so a third
    client inherits the constraint instead of re-discovering it.
    """
    for page in PAGES + ( LEGACY_PAGE, ):
        sheets = [ os.path.relpath( p, STATIC ).replace( os.sep, "/" ) for p in _linked_sheets( page ) ]
        if "css/task-list.css" in sheets and "css/epic-board.css" in sheets:
            assert sheets.index( "css/task-list.css" ) < sheets.index( "css/epic-board.css" ), (
                f"{page} links epic-board.css BEFORE task-list.css. epic-board.css:9 "
                f"re-declares over task-list.css, so this order drops those re-declarations."
            )


def test_the_two_pages_agree_on_what_they_style():
    """Same templates, two clients — a class one page styles and the other does not
    is the linkage defect stated a second, independent way.

    This reading is worth having on its own: it pins each page against the OTHER
    PAGE rather than against the CSS tree, so the two assertions cannot both go
    green for a shared reason.
    """
    drift = {}
    for name, rel in sorted( TEMPLATES.items() ):
        mux    = _unstyled( "multiplexer.html", rel )
        legacy = _unstyled( LEGACY_PAGE,        rel )
        only_mux = mux - legacy
        if only_mux:
            drift[ name ] = sorted( only_mux )
    assert not drift, (
        "The legacy client styles these classes and the multiplexer does not — "
        "the same pane is presented two different ways:\n"
        + "".join( f"    {k}: {v}\n" for k, v in drift.items() )
    )
