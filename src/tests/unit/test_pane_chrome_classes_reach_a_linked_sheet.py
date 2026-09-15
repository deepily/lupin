"""
The sibling guard to `test_every_pane_class_reaches_a_sheet_the_page_links.py`,
covering the part that one deliberately scopes OUT.

That guard's predicate is *"a class DEFINED somewhere must be defined in a sheet
this page LINKS"* — a linkage question. Its own SCOPE note says a class defined
in NO sheet anywhere is "a DIFFERENT question — dead weight or a JS/test hook —
and is deliberately out of scope here."

🔴 THAT IS CORRECT, AND IT LEAVES A REAL GAP. Row 87812328's census
(`src/rnd/2026.09.06-accordion-wiring-census.md`) found 23 classes the four
panes emit that no sheet defines at any path. Most must STAY undefined — the
legacy card emits them unstyled too, and Rick's ruling is "look EXACTLY" like
legacy, so a rule would make the multiplexer DIFFER. But a handful are
multiplexer-only PANE CHROME with no legacy counterpart at all, where parity
does not constrain and the pane simply had no styling: the Holding Area and
Epic Board refresh buttons rendered as raw browser-default controls.

⇒ This guard asserts THOSE reach a linked sheet, and it is written so that
deleting the rules reddens it BY NAME rather than silently.

🔴 WHY THE CHROME SIDE IS DERIVED AND NOT A LIST
(§ WHEN THE FIX FOR AN ENUMERATION DEFECT IS ITSELF AN ENUMERATION). The
refresh/updated affordances are found by PREDICATE — for every pane prefix, any
`<prefix>-refresh` / `<prefix>-updated` class the templates actually emit. So a
fifth pane, or a renamed prefix, is picked up without anyone editing this file.
The two remaining subjects cannot be derived that way and are named explicitly
WITH their reason, which is the honest form of a list.

⚠️ WHAT THIS GUARD MUST NOT BECOME. Do not widen it to "every emitted class must
be styled." That is false by construction and would redden on the 18 classes
that are unstyled ON PURPOSE — the exact way a guard stops meaning anything.
`test_the_parity_classes_are_still_unstyled` below pins that boundary from the
other side, so widening this file breaks a test that says why.

:7999-eligible — static, pure-Python, no server, no state mutation.
"""

import os
import re

import pytest

import cosa.utils.util as cu

STATIC   = os.path.join( cu.get_project_root(), "src", "lupin_app", "static" )
CSS_DIR  = os.path.join( STATIC, "css" )
PAGE     = os.path.join( STATIC, "html", "multiplexer.html" )

PANE_PREFIXES = ( "task-list", "fleet-status", "holding-area", "epic-board" )

TEMPLATE_DIR = os.path.join( STATIC, "js", "multiplexer", "render" )

# Named, not derived — and each carries the reason it cannot be.
EXPLICIT_SUBJECTS = {
    # A multiplexer-only STATE. The legacy card has no sentinel banner, so there
    # is no legacy look to copy and no parity constraint; it follows the house
    # amber that .task-list-unreachable / .fleet-status-offline already use.
    "holding-area-sentinel" : "store-unreachable banner; no legacy counterpart",
    # Inherits `white-space: nowrap` from .task-disclosed-field, which is right
    # for the single-token line-2 fields and wrong for the one that holds a LIST.
    "task-col-blocked"      : "must override the nowrap inherited from .task-disclosed-field",
}


def _read( path ):
    with open( path, encoding="utf-8" ) as fh:
        return fh.read()


def _linked_sheets():
    """Full paths of the stylesheets multiplexer.html links, permissive about ?v=."""
    html  = _read( PAGE )
    hrefs = re.findall( r"""<link[^>]+rel=["']stylesheet["'][^>]*href=["']([^"']+)["']""", html )
    out   = []
    for h in hrefs:
        rel = h.split( "?", 1 )[ 0 ]                       # tolerate cache-bust tokens
        if rel.startswith( "/static/" ):
            p = os.path.join( os.path.dirname( STATIC ), rel.lstrip( "/" ) )
            if os.path.isfile( p ):
                out.append( p )
    return out


def _classes_defined_in( paths ):
    """Every class name appearing in a selector across `paths`, comments stripped."""
    found = set()
    for p in paths:
        src = re.sub( r"/\*.*?\*/", " ", _read( p ), flags=re.S )   # comments are NOT rules
        src = re.sub( r"\{[^{}]*\}", " { } ", src )                 # blank declaration bodies
        for chunk in re.split( r"[{}]", src ):
            for m in re.finditer( r"\.(-?[A-Za-z_][-\w]*)", chunk ):
                found.add( m.group( 1 ) )
    return found


def _row_schema_fields():
    """
    The ROW_SCHEMA field names, read from the source of truth.

    🔴 WITHOUT THIS THE GUARD CANNOT SEE ITS OWN SUBJECT. `task-col-blocked` is
    never written down: `rowDisclosure.ts` and `taskRowDisclosed.ts` build it as
    `task-col-${ field }`. A literal-only sweep reports it as "not emitted" and
    the case fails for a reason that has nothing to do with styling — which is
    exactly the defect row 87812328's census is about, reproduced inside the
    guard written off that census.
    """
    src = _read( os.path.join( TEMPLATE_DIR, "rowSchema.ts" ) )
    body = re.search( r"ROW_SCHEMA\s*=\s*\{(.*?)\}\s*as const", src, re.S )
    assert body, "ROW_SCHEMA not found — rowSchema.ts moved or was restructured"
    return set( re.findall( r'"([a-z][\w-]*)"', body.group( 1 ) ) )


def _without_comments( src ):
    """
    `src` with /* block */ and // line comments blanked.

    Ensures:
        - block comments are removed across lines
        - a `//` preceded by `:` or a quote (a URL or a string opening with //) is kept
    """
    src = re.sub( r"/\*.*?\*/", " ", src, flags=re.S )
    return re.sub( r"(?m)(^|[^:\"'`\\])//.*$", r"\1", src )


def _emitted_classes():
    """Class names the pane templates/renderers emit — literals AND generated."""
    found = set()
    for root, _dirs, files in os.walk( TEMPLATE_DIR ):
        for f in files:
            if not f.endswith( ".ts" ):
                continue
            src = _read( os.path.join( root, f ) )
            # 🔴 THE QUOTE-PAIRING SWEEP IS KNOCKED OUT OF PHASE BY AN APOSTROPHE IN A COMMENT.
            # Measured on the merged triage line (row ef0fa72b): three renderers gained comment
            # prose with an odd number of quote characters, every later literal paired with the
            # wrong partner, and task-list-refresh & co. vanished from this set while still
            # being emitted. Sweeping a comment-stripped copy AS WELL only ever adds names, so
            # nothing the raw sweep found is lost.
            for text in ( src, _without_comments( src ) ):
                for raw in re.findall( r"""["'`]([^"'`]*)["'`]""", text ):
                    for tok in re.sub( r"\$\{[^}]*\}", " ", raw ).split():
                        if re.fullmatch( r"[A-Za-z_][-\w]*", tok ):
                            found.add( tok )
    # Generated names, reconstructed from their generator rather than guessed.
    found |= { f"task-col-{f}" for f in _row_schema_fields() }
    return found


@pytest.fixture( scope="module" )
def linked():
    sheets = _linked_sheets()
    assert sheets, "no linked stylesheets resolved — the parser, not the page, is broken"
    return _classes_defined_in( sheets )


@pytest.fixture( scope="module" )
def emitted():
    e = _emitted_classes()
    assert len( e ) > 50, f"only {len(e)} emitted classes found — the template walk is broken"
    return e


# 🔴 NOT ALL PANE CHROME IS MULTIPLEXER-ONLY, AND THE FIRST CUT OF THIS FILE
# ASSUMED IT WAS. The derived predicate swept in `epic-board-updated`, which the
# LEGACY card also emits and no sheet styles — so demanding a rule for it would
# have driven someone to break parity in order to green a test. Excluded here by
# the same measurement that produced PARITY_UNSTYLED below.
CHROME_PARITY_EXCLUSIONS = ( "epic-board-updated", "epic-board-container" )


def _chrome_subjects( emitted ):
    """Derived: every <pane>-refresh / <pane>-updated the templates emit, minus
    the ones legacy also emits unstyled (parity — see the exclusions above)."""
    return sorted(
        c for c in emitted
        if any( c == f"{p}-{suffix}" for p in PANE_PREFIXES for suffix in ( "refresh", "updated" ) )
        and c not in CHROME_PARITY_EXCLUSIONS
    )


# --------------------------------------------------------------------------
# POSITIVE CONTROL. Without this, a parser that returned the empty set would
# make every assertion below vacuously true (§ a loop over nothing is green).
# --------------------------------------------------------------------------
def test_the_instrument_finds_rules_that_exist( linked ):
    for known in ( "task-list-refresh", "task-list-updated", "task-action-btn", "task-title" ):
        assert known in linked, f"positive control failed: .{known} should resolve in a linked sheet"


def test_the_derivation_is_not_empty( emitted ):
    subjects = _chrome_subjects( emitted )
    # 4 panes x 2 affordances is the ceiling; anything under 4 means the walk broke.
    assert len( subjects ) >= 4, f"derived only {subjects} — the predicate found too little to be meaningful"


@pytest.mark.parametrize( "suffix", ( "refresh", "updated" ) )
def test_every_pane_chrome_affordance_reaches_a_linked_sheet( linked, emitted, suffix ):
    missing = [
        c for c in _chrome_subjects( emitted )
        if c.endswith( f"-{suffix}" ) and c not in linked
    ]
    assert not missing, (
        f"pane chrome emitted but styled by no sheet multiplexer.html links: {missing}. "
        f"These are multiplexer-only affordances with no legacy counterpart, so they "
        f"render as raw browser defaults. Add a rule to a LINKED sheet."
    )


@pytest.mark.parametrize( "cls,why", sorted( EXPLICIT_SUBJECTS.items() ) )
def test_named_multiplexer_only_class_reaches_a_linked_sheet( linked, emitted, cls, why ):
    assert cls in emitted, f".{cls} is no longer emitted — retire this case rather than weakening it"
    assert cls in linked, f".{cls} is emitted but unstyled — {why}"


# --------------------------------------------------------------------------
# THE BOUNDARY, PINNED FROM THE OTHER SIDE. These are unstyled ON PURPOSE:
# the legacy card emits them and styles them nowhere, so a rule would make the
# multiplexer DIFFER from legacy (Rick, 2026-09-05: "look exactly").
# Measured against notifications.html's live CSSOM, 2026-09-06.
# --------------------------------------------------------------------------
PARITY_UNSTYLED = ( "fleet-col-role", "fleet-col-state", "fleet-col-holding" )


@pytest.mark.parametrize( "cls", PARITY_UNSTYLED )
def test_the_parity_classes_are_still_unstyled( linked, emitted, cls ):
    assert cls in emitted, f".{cls} is no longer emitted — this case is stale"
    assert cls not in linked, (
        f".{cls} has acquired a rule. Legacy emits it and styles it nowhere, so styling it "
        f"here makes the multiplexer DIFFER from legacy. If this was deliberate, it needs a "
        f"ruling — do not delete this assertion to make a build green."
    )
