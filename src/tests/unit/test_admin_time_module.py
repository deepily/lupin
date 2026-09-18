"""
Guards for the ONE shared relative-time formatter the admin pages use.

WHAT HAPPENED. proxy-dashboard.js:429-448 and proxy-ratify.js:744-763 held
byte-identical copies of `formatRelativeTime` (both ranges sha256
c212e07bca45935e935ffb5609166a49435bfef4edc2610e6f88d2b95c916e4c, measured
2026-09-15). They were consolidated into
static/html/auth/admin/js/admin-time.js and both pages now load it.

WHAT THIS FILE GUARDS, and why it is two questions rather than one:

  1. Exactly one served definition. A second copy reintroduces the divergence
     the consolidation removed, and nothing else in the suite would see it.

  2. Every page whose scripts CALL the function also LOADS the file that
     defines it, BEFORE the caller. This is the assertion that earns its keep.
     These are classic scripts — no modules, no bundler — so load order IS the
     dependency edge, and the failure mode of a consolidation is deleting a
     copy and forgetting the tag. That is a runtime ReferenceError on a page
     nobody opens until a demo. Reading the JS cannot reveal it; only asking
     the HTML which files it pulls, in what order, can.

The population is DERIVED from the served tree, never enumerated here. A third
admin page added next year is covered the day it is added, without anyone
remembering this file exists.

Venue: unit tier. No server, no browser, no DB.
"""

import re
from pathlib import Path

import pytest


_STATIC_ROOT = Path( __file__ ).resolve().parents[ 3 ] / "src" / "lupin_app" / "static"

# The symbol under guard, and the file that is allowed to define it.
_SYMBOL        = "formatRelativeTime"
_OWNING_SCRIPT = "admin-time.js"

# <script src="..."> — captures the src of a same-origin static script. Fixed
# attribute order is not assumed; the src is found wherever it sits in the tag.
_SCRIPT_TAG = re.compile( r"<script\b[^>]*\bsrc\s*=\s*[\"']([^\"']+)[\"'][^>]*>", re.IGNORECASE )

# A DEFINITION, not a mention. `function formatRelativeTime(` appears once per
# copy; a call site reads `formatRelativeTime(` with no `function` before it, and
# a comment naming the symbol matches neither.
_DEFINITION = re.compile( r"\bfunction\s+" + _SYMBOL + r"\s*\(" )

# A CALL OF THE GLOBAL — which is narrower than "the name appears with a paren".
#
# WHAT THIS HAD TO LEARN, measured 2026-09-15: notifications.js carries a CLASS
# METHOD of the same name (notifications.js:18776, `formatRelativeTime( date ) {`)
# called at :19798 as `this.formatRelativeTime( ... )`. It is a different function
# in a different scope with a different contract — it takes a Date rather than an
# ISO string and returns "5 min ago" where the admin one returns "5m ago". An
# earlier cut of this pattern counted both as calls of the global, which put
# notifications.html in the caller census and demanded it load a module it has no
# business loading.
#
# So three shapes must be told apart, and the third is the one that bites:
#     function formatRelativeTime( x )     a global DEFINITION
#     formatRelativeTime( x )              a global CALL          <- only this
#     formatRelativeTime( x ) {            a METHOD definition
#     this.formatRelativeTime( x )         a METHOD call
# `(?<![.\w])` drops anything reached through a dot; `(?!\s*[^()]*\)\s*\{)`
# drops a definition, whose parameter list is followed by an opening brace.
#
# HONEST LIMIT: this is a regex over JavaScript, not a parser. It cannot see a
# call built by string concatenation, one reached through a computed property, or
# an aliased reference. test_the_definition_census_can_find_a_positive pins the
# shapes it DOES claim to tell apart; anything outside them is out of its reach
# and is not silently counted either way.
_CALL = re.compile(
    r"(?<![.\w])(?<!function )" + _SYMBOL + r"\s*\((?![^()]*\)\s*\{)"
)


# ---------------------------------------------------------------------------
# Corpus helpers — every one asserts it found something before anyone loops
# ---------------------------------------------------------------------------

def _served_files( suffix ):
    """
    Every served file with this suffix, read once.

    Requires:
        - suffix includes the dot (".js", ".html")

    Ensures:
        - returns a non-empty list of (path, text)
        - an empty tree fails HERE rather than silently satisfying every
          assertion downstream — a search over zero files reports every symbol
          as absent, which reads exactly like a clean result

    Raises:
        - AssertionError if the tree yields no files of that suffix
    """
    files = [ p for p in _STATIC_ROOT.rglob( f"*{suffix}" ) if p.is_file() ]
    assert files, f"no {suffix} files under {_STATIC_ROOT} — every guard below would be vacuous"
    return [ ( p, p.read_text( encoding="utf-8", errors="replace" ) ) for p in files ]


def _script_srcs( html_text ):
    """
    The script srcs this page loads, in document order.

    Ensures:
        - returns the list in the order the browser will execute them, because
          for classic scripts that order is the dependency edge
    """
    return _SCRIPT_TAG.findall( html_text )


def _resolve( src ):
    """
    Map a served URL path back to the file on disk, or None if it is off-tree.

    Requires:
        - src is the literal src attribute from a <script> tag

    Ensures:
        - returns a Path under _STATIC_ROOT for a /static/... url that exists
        - returns None for a CDN url, a protocol-relative url, or a path that
          resolves to nothing — those are not this guard's business and must
          not be reported as violations
    """
    if not src.startswith( "/static/" ):
        return None

    # Strip the cache-bust token before touching the disk. This repo bumps ?v=
    # tokens as a matter of routine (see test_task_body_overlay_cache_bust.py),
    # and a served url like /static/js/notifications.js?v=20260915a names a real
    # file. Measured 2026-09-15: 9 of the 65 script refs across the 34 served
    # pages carry one, and without this strip every one of them resolved to None.
    # That is not a cosmetic miss — an unresolvable script is invisible to the
    # CALLER census, so the day anyone cache-busts an admin script this guard
    # would stop asserting on that page and say nothing.
    bare = src.split( "?" )[ 0 ].split( "#" )[ 0 ]

    candidate = _STATIC_ROOT / bare[ len( "/static/" ) : ]
    return candidate if candidate.is_file() else None


# ---------------------------------------------------------------------------
# 1. Exactly one definition
# ---------------------------------------------------------------------------

def test_exactly_one_served_definition_of_the_formatter():
    """
    The whole point of the consolidation: one copy, not two.

    Ensures:
        - the corpus is non-empty
        - exactly one served .js file defines the symbol
        - that file is the one named as its owner
        - the failure lists every file that defines it, so a reader does not
          re-derive which copy came back
    """
    sources = _served_files( ".js" )
    definers = sorted(
        str( p.relative_to( _STATIC_ROOT ) )
        for p, text in sources
        if _DEFINITION.search( text )
    )

    assert len( definers ) == 1, (
        f"{len( definers )} served files define {_SYMBOL}: {definers}. Exactly one may. "
        f"Two copies of one rule agree until they do not, and no test in this repo is "
        f"positioned to notice the day they diverge — which is why they were "
        f"consolidated into {_OWNING_SCRIPT} rather than guarded in place. "
        f"Searched {len( sources )} served .js files."
    )
    assert definers[ 0 ].endswith( _OWNING_SCRIPT ), (
        f"{_SYMBOL} is defined in {definers[ 0 ]}, not in {_OWNING_SCRIPT}. If ownership "
        f"moved deliberately, move _OWNING_SCRIPT with it."
    )


def test_the_definition_census_can_find_a_positive():
    """
    Positive control for the pattern above — it must distinguish the three shapes.

    A census that matched nothing, or matched everything, would report a clean
    tree either way. This pins the discriminator instead of trusting it.

    Ensures:
        - a definition matches _DEFINITION and is NOT counted as a call
        - a call site matches _CALL and is NOT counted as a definition
        - a comment naming the symbol matches neither
    """
    definition  = "function formatRelativeTime( isoString ) {"
    call        = "<td>${formatRelativeTime( decision.created_at )}</td>"
    mention     = "// formatRelativeTime lives in admin-time.js now"
    method_def  = "    formatRelativeTime( date ) {"
    method_call = "activityEl.textContent = `Last: ${this.formatRelativeTime( group.lastActivity )}`;"

    assert _DEFINITION.search( definition ), "the definition pattern cannot see a definition"
    assert not _CALL.search( definition ),   "a definition was miscounted as a call"

    assert _CALL.search( call ),             "the call pattern cannot see a call"
    assert not _DEFINITION.search( call ),   "a call was miscounted as a definition"

    assert not _DEFINITION.search( mention ), "a comment was miscounted as a definition"
    assert not _CALL.search( mention ),       "a comment was miscounted as a call"

    # The two shapes that actually cost a false positive. Both are taken verbatim
    # from notifications.js (:18776 and :19798) rather than invented, because a
    # hand-written fixture is better-formed than reality exactly where a pattern
    # depends on the mess.
    assert not _DEFINITION.search( method_def ),  "a method definition read as a global definition"
    assert not _CALL.search( method_def ),        "a method definition read as a call of the global"
    assert not _CALL.search( method_call ),       "a method call read as a call of the global"
    assert not _DEFINITION.search( method_call ), "a method call read as a definition"


# ---------------------------------------------------------------------------
# 2. Every caller's page loads the owner, first
# ---------------------------------------------------------------------------

def _pages_whose_scripts_call_the_formatter():
    """
    Derive, from the served tree, every page that will execute a call.

    Ensures:
        - returns [ ( page_path, [ resolved script paths in load order ] ) ]
        - a page is included iff at least one script it loads CALLS the symbol
        - the population comes from the tree, so a page added later is covered
          without anyone editing this file
    """
    pages = []

    for page_path, html in _served_files( ".html" ):
        loaded = [ ( src, _resolve( src ) ) for src in _script_srcs( html ) ]
        calls  = any(
            resolved is not None and _CALL.search( resolved.read_text( encoding="utf-8", errors="replace" ) )
            for _src, resolved in loaded
        )
        if calls:
            pages.append( ( page_path, loaded ) )

    return pages


def test_the_caller_page_census_is_not_empty():
    """
    The loop-found-something guard for the ordering test below.

    Two live callers exist today (the trust dashboard and the ratify queue). If
    this census goes to zero, the ordering test passes while asserting nothing,
    and the consolidation loses its only real guard silently.

    Ensures:
        - at least one served page loads a script that calls the symbol
    """
    pages = _pages_whose_scripts_call_the_formatter()
    assert pages, (
        f"no served page loads a script calling {_SYMBOL}. Either every caller was "
        f"removed — in which case delete {_OWNING_SCRIPT} and this file together — or "
        f"the census is broken and the ordering guard below is now vacuous."
    )


def _ordering_violation( loaded ):
    """
    The RULE, in one place: why this load order would break, or None if it would not.

    Extracted so the real-tree guard and its positive control call the SAME
    function rather than each implementing the check. Two pieces of code deciding
    one rule agree until they do not, and a control that restates the rule cannot
    catch the day the rule itself is wrong — it can only agree with itself.

    Requires:
        - loaded is [ ( src, resolved_path_or_None ) ] in document order

    Ensures:
        - returns None when the owning module loads before the first caller
        - returns a reason string naming the positions otherwise
        - a page with no caller at all returns None; it has nothing to break
    """
    owner_at  = next( ( i for i, ( src, _r ) in enumerate( loaded )
                        if src.endswith( _OWNING_SCRIPT ) ), None )
    caller_at = next( ( i for i, ( _src, r ) in enumerate( loaded )
                        if r is not None and _CALL.search( r.read_text( encoding="utf-8", errors="replace" ) ) ), None )

    if caller_at is None:
        return None
    if owner_at is None:
        return f"never loads {_OWNING_SCRIPT}"
    if owner_at > caller_at:
        return ( f"loads {_OWNING_SCRIPT} at position {owner_at}, "
                 f"AFTER its caller at {caller_at}" )
    return None


def test_every_calling_page_loads_the_owner_before_the_caller():
    """
    The assertion that catches the real failure mode of this consolidation.

    Deleting a duplicated function and forgetting the <script> tag is a runtime
    ReferenceError on a page a human opens rarely. Classic scripts execute in
    document order, so "loaded" is not enough — it must be loaded EARLIER than
    the file that calls it.

    The rule itself lives in _ordering_violation(); this asks it about the real
    served tree. Its positive control below asks the same function about
    synthetic orders, so neither side restates the other.

    Ensures:
        - every page with a calling script also loads the owning module
        - the owning module appears before the first caller in document order
        - the failure names the page, the reason, and the load order
    """
    violations = [
        ( str( page_path.relative_to( _STATIC_ROOT ) ), reason, [ src for src, _r in loaded ] )
        for page_path, loaded in _pages_whose_scripts_call_the_formatter()
        if ( reason := _ordering_violation( loaded ) ) is not None
    ]

    assert not violations, (
        f"{len( violations )} page(s) would hit a ReferenceError calling {_SYMBOL}:\n"
        + "\n".join( f"  {page}: {why}\n    load order: {order}" for page, why, order in violations )
        + f"\nThese are classic scripts — no modules, no bundler — so document order IS "
          f"the dependency. Add <script src=\"/static/html/auth/admin/js/{_OWNING_SCRIPT}\">"
          f"</script> BEFORE the page's own script."
    )


def test_the_ordering_rule_rejects_the_two_ways_a_page_can_break():
    """
    Positive control: the SAME function the guard uses, driven over synthetic orders.

    A guard nobody has watched fail may be asserting over an empty list, a
    swallowed exception, or a comparison true either way. This is also what
    covers the two failure arms, which a green tree can never reach.

    Ensures:
        - owner before caller yields no violation
        - owner absent yields a reason naming the missing file
        - owner after caller yields a reason naming both positions
        - a page loading no caller at all yields no violation
    """
    owner  = ( f"/static/html/auth/admin/js/{_OWNING_SCRIPT}",
               _resolve( f"/static/html/auth/admin/js/{_OWNING_SCRIPT}" ) )
    caller = ( "/static/html/auth/admin/js/proxy-ratify.js",
               _resolve( "/static/html/auth/admin/js/proxy-ratify.js" ) )

    assert caller[ 1 ] is not None, "the caller fixture did not resolve — the control is vacuous"

    assert _ordering_violation( [ owner, caller ] ) is None

    missing = _ordering_violation( [ caller ] )
    assert missing is not None and _OWNING_SCRIPT in missing, f"unhelpful: {missing}"

    late = _ordering_violation( [ caller, owner ] )
    assert late is not None and "AFTER its caller" in late, f"unhelpful: {late}"

    assert _ordering_violation( [ owner ] ) is None, "a page with no caller cannot break"


# ---------------------------------------------------------------------------
# 3. Resolution refuses to guess
# ---------------------------------------------------------------------------

@pytest.mark.parametrize( "src", [
    "https://cdn.example.com/lib.js",
    "//cdn.example.com/lib.js",
    "/static/html/auth/admin/js/there-is-no-such-file.js",
] )
def test_resolution_returns_none_for_what_it_cannot_own( src ):
    """
    Off-tree and non-existent srcs are not this guard's business.

    Reporting a CDN script as a violation would train readers to ignore the
    failure, which is how a guard becomes decoration.

    ⚠️ These three cases CANNOT tell you WHY they were rejected — see the test
    below, which is the one that pins it. Measured 2026-09-15: deleting the
    `/static/` prefix check from _resolve left all three of these green, because
    each is also rejected downstream by `is_file()`. They are kept as a
    smoke-level sanity check, not as the guard.

    Ensures:
        - a CDN url, a protocol-relative url and a dead path all resolve to None
    """
    assert _resolve( src ) is None


def test_resolution_rejects_an_off_tree_src_that_would_otherwise_resolve():
    """
    The prefix check is load-bearing, and this is the only test that can say so.

    THE TRAP, because it is not visible from reading _resolve: the function
    slices `src[ len( "/static/" ): ]` — eight characters — and "https://" is
    itself exactly eight characters. So for a url of that shape the slice does
    not mangle anything; it hands a clean relative path to the join. Delete the
    prefix check and `https://js/lupin-nav.js` resolves to the real served file
    static/js/lupin-nav.js, and an off-tree script is silently adopted as ours.

    The three parametrized cases above cannot see this. Each of them is rejected
    by `is_file()` whether the prefix check runs or not, so the assertion passes
    for a reason that has nothing to do with what it claims to test — an
    assertion satisfiable by two paths cannot tell you which one ran. This one
    eliminates the second path by choosing a fixture that WOULD resolve.

    Ensures:
        - the fixture is real: its slice names a file that genuinely exists, so
          the test would fail if the prefix check were removed
        - _resolve rejects it anyway, on the prefix
    """
    off_tree = "https://js/lupin-nav.js"
    assert off_tree[ : len( "/static/" ) ] == "https://", (
        "the fixture's discriminating property is that its first eight characters "
        "are exactly as long as the prefix being sliced off — check it, do not assume it"
    )

    would_resolve = _STATIC_ROOT / off_tree[ len( "/static/" ) : ]
    assert would_resolve.is_file(), (
        f"{would_resolve} does not exist, so this test cannot discriminate and is "
        f"vacuous. Pick another served file whose path makes the slice land on it."
    )

    assert _resolve( off_tree ) is None, (
        "an off-tree src was adopted as ours. The /static/ prefix check in _resolve "
        "is what stops this, and without it the slice happens to produce a valid "
        "relative path for any url whose scheme is eight characters long."
    )


def test_resolution_finds_a_file_that_is_really_there():
    """
    The other half of the control above — resolution must actually resolve.

    A `_resolve` that returned None unconditionally would make every page look
    caller-free, and the ordering guard would pass over an empty population.

    Ensures:
        - the owning module's served url maps to a real file on disk
    """
    resolved = _resolve( f"/static/html/auth/admin/js/{_OWNING_SCRIPT}" )
    assert resolved is not None and resolved.is_file()


def test_resolution_sees_through_a_cache_bust_token():
    """
    A ?v= token must not hide a script from the caller census.

    THE RISK THIS CLOSES, which is live rather than theoretical: this repo bumps
    cache-bust tokens routinely, and the two admin pages do not carry one TODAY.
    The day someone adds `?v=` to proxy-ratify.js, an unstripped _resolve would
    return None for it, the page would drop out of
    _pages_whose_scripts_call_the_formatter entirely, and
    test_every_calling_page_loads_the_owner_before_the_caller would go on passing
    while asserting nothing at all about that page. A guard that narrows its own
    population in silence is the defect this whole module exists to remove.

    Ensures:
        - the fixture is real: the bare path names a file that exists, so the
          test cannot pass by both sides being None
        - a ?v= url resolves to the SAME file as its bare form
        - a #fragment is stripped too
        - the token does not make the file resolvable when it is not there
    """
    bare = f"/static/html/auth/admin/js/{_OWNING_SCRIPT}"

    assert _resolve( bare ) is not None, (
        f"{bare} does not resolve, so this test compares None to None and proves nothing"
    )

    assert _resolve( f"{bare}?v=20260915a" ) == _resolve( bare ), "?v= token hid a real file"
    assert _resolve( f"{bare}#frag" )        == _resolve( bare ), "#fragment hid a real file"

    assert _resolve( "/static/js/there-is-no-such-file.js?v=1" ) is None, (
        "stripping the token must not invent a file that is absent"
    )


def test_the_caller_census_is_not_narrowed_by_a_cache_bust_token():
    """
    The population the ordering guard asserts on survives a token bump.

    This is the consequence test for the one above: it asks the CENSUS, not
    _resolve, because that is the thing whose silent narrowing would matter.

    Ensures:
        - both admin pages are in the census as the tree stands
        - the count is stated, so a future narrowing is visible as a number
    """
    pages = { str( p.relative_to( _STATIC_ROOT ) ) for p, _l in _pages_whose_scripts_call_the_formatter() }

    expected = { "html/auth/admin/proxy-dashboard.html", "html/auth/admin/proxy-ratify.html" }
    assert pages == expected, (
        f"caller census is {sorted( pages )}, expected {sorted( expected )}. If a page left "
        f"the census, ask WHY before updating this list — a script that stopped resolving "
        f"removes its page silently, and the ordering guard then passes vacuously."
    )
