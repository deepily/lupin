"""
What font does the BROWSER actually pick for each of Lupin's CSS stacks?

The visual baselines are pixels, and pixels depend on the font the browser SELECTS —
not on what `fc-match` would return for a name in isolation. Those two answers differ,
and the difference is what this module exists to measure.

MEASURED 2026-09-15 (row f0e00f01), with a canvas width probe at 16px:

    'Helvetica Neue', Helvetica, Arial, sans-serif   ->  402.91  == Liberation Sans
    -apple-system, …, Oxygen, Ubuntu, Cantarell, …   ->  409.39  == Ubuntu   (host)
    DejaVu Sans                                      ->  455.23

The browser walks a stack left to right and stops at the first family that EXISTS. So
the notifications stack never reaches the generic `sans-serif`: it stops at Helvetica
or Arial, which fontconfig aliases to Liberation Sans. Asking `fc-match` for
'Helvetica Neue' answers a question the browser never asks, because `fc-match` always
returns a best match and so can never report "absent" — the very signal that decides
which entry in the stack wins.

The same walk is why one page can move while another does not. `Ubuntu` is a real
Linux font: installed on the host (3 families), ABSENT from lupin-rest-test (0). So
the dev-tools stack resolves to Ubuntu on the host and falls through to DejaVu Sans in
the container — about a 10% metric difference — while every notifications surface is
unaffected, Liberation Sans being present in both.

⇒ A width fingerprint is therefore the honest predicate. It notices ANY substitution,
whatever caused it — a font package added or removed, an alias retargeted, a family
renamed — without enumerating names that the next stylesheet will outgrow.

THE FINGERPRINT IS PER-VENUE, AND THAT IS NOT A TOLERANCE — IT IS THE POINT. The
`lupin-base.css` stack is the standard SYSTEM-FONT stack, whose whole purpose is to
render in the platform's own UI font. It is SUPPOSED to resolve differently on a machine
with Ubuntu installed than on one without. Asserting host and container agree would
assert that stack out of its job, and the only way to make it pass would be to degrade
the product so a test could be satisfied (Mr. Radio's ruling, 2026-09-15).

So the predicate is "the fonts THIS venue selects have not moved since this venue was
fingerprinted", recorded once per venue. That is strictly more coverage than a
cross-venue equality would give: it watches drift inside the container, which is the
class that actually moved dev-tools, AND drift on the host, which a container-only
check would not see at all.

Requires:
    - a Playwright Page (about:blank is enough; no server, no network)
Ensures:
    - `declared_font_stacks` returns the distinct stacks Lupin's CSS/HTML actually
      declares, derived from the tree rather than from a hand-kept list
    - `measure_stacks` returns {stack: width} as the browser resolves them
    - `identify_families` names the installed families whose own width matches, so a
      failure says WHICH font it drifted to rather than only that a number moved
"""

import json
import os
import re
import subprocess

# One fixed string, one fixed size. The string mixes wide and narrow glyphs, digits and
# a space-heavy run so a substitution moves the number; the size is the body size most
# Lupin surfaces render at.
PROBE_STRING = "Peer Queue Monitoring and a longer sample string 12:00"
PROBE_SIZE   = "16px"

# Width equality is exact by intent. These are computed by the same Chromium build the
# baselines were rendered against (the fingerprint guard pins that build separately), so
# a difference of any size means a different font was selected, not measurement noise.
WIDTH_TOLERANCE = 0.01

# Declarations that name no font of their own.
_NON_STACKS = ( "inherit", "initial", "unset", "revert" )

_FONT_FAMILY_RE = re.compile( r"font-family\s*:\s*([^;}{]+)" )

# A declaration written in a comment is not a declaration. CSS comments in both file types
# (an HTML page's <style> uses them), and markup comments in HTML.
_CSS_COMMENT_RE  = re.compile( r"/\*.*?\*/", re.DOTALL )
_HTML_COMMENT_RE = re.compile( r"<!--.*?-->", re.DOTALL )


def declared_font_stacks( root ):
    """
    Return the distinct CSS font stacks Lupin declares, derived from the tree.

    Requires:
        - root is the project root as a string or Path
    Ensures:
        - returns a sorted tuple of normalized stack strings
        - excludes `inherit` and friends, which name no family
        - ignores anything inside a comment — `/* */` in both file types, `<!-- -->` in HTML.
          A comment in notifications-surface.css mentioning "font-family:inherit / background
          from …" used to be swept up as a stack (row f0e00f01, 2026-09-18)
        - reads .css AND .html, because several pages declare stacks inline
        - never raises; an unreadable file is skipped rather than failing the sweep
    """
    out = set()
    # git ls-files rather than a disk walk: it cannot wander into .venv or node_modules,
    # which is about 92% of any disk-derived sweep of this tree.
    listing = subprocess.run(
        [ "git", "-C", str( root ), "ls-files",
          "src/lupin_app/static/css", "src/lupin_app/static/html" ],
        capture_output=True, text=True, timeout=30,
    ).stdout.split( "\n" )

    for rel in listing:
        if not rel.endswith( ( ".css", ".html" ) ):
            continue
        try:
            with open( f"{root}/{rel}", encoding="utf-8", errors="replace" ) as fh:
                text = fh.read()
        except OSError:                                    # pragma: no cover - unreadable file in a git listing
            continue
        text = _CSS_COMMENT_RE.sub( " ", text )
        if rel.endswith( ".html" ): text = _HTML_COMMENT_RE.sub( " ", text )
        for raw in _FONT_FAMILY_RE.findall( text ):
            stack = " ".join( raw.split() ).strip().rstrip( "/" ).strip()
            if not stack or stack.lower() in _NON_STACKS:
                continue
            out.add( stack )
    return tuple( sorted( out ) )


def current_venue():
    """
    Name the render venue this process is running in.

    Requires:
        - nothing
    Ensures:
        - returns "container" inside a Docker container, "host" otherwise
        - keys on /.dockerenv, which the runtime creates and which is therefore a
          property the venue CARRIES, rather than a hostname or a path someone can
          move underneath it
    """
    return "container" if os.path.exists( "/.dockerenv" ) else "host"


# Each stack is assigned over a SENTINEL font of a different size. The canvas ignores a font
# string it cannot parse, so a stack that leaves the sentinel in place was rejected and is
# returned as null rather than measured in whatever font the previous stack left behind.
_MEASURE_JS = """
( [ stacks, probe, size ] ) => {
    const ctx = document.createElement( "canvas" ).getContext( "2d" );
    ctx.font = "1px serif";
    const sentinel = ctx.font;
    const out = {};
    for ( const stack of stacks ) {
        ctx.font = sentinel;
        ctx.font = size + " " + stack;
        out[ stack ] = ctx.font === sentinel ? null : Math.round( ctx.measureText( probe ).width * 100 ) / 100;
    }
    return out;
}
"""


def measure_stacks( page, stacks ):
    """
    Ensures:
        - returns {stack: width} for the probe string, as THIS browser resolves it
        - width is rounded to 2dp so the value is stable to serialize and compare
    Raises:
        - ValueError naming every stack the browser's font parser rejected. Such a stack
          used to be measured in the PREVIOUS stack's font, so its width depended on the
          sort order of the keys (row f0e00f01, 2026-09-18)
    """
    measured = page.evaluate( _MEASURE_JS, [ list( stacks ), PROBE_STRING, PROBE_SIZE ] )
    rejected = sorted( s for s, width in measured.items() if width is None )
    if rejected:
        raise ValueError( f"the browser rejected {len( rejected )} font stack(s), so they have no width of their own: {rejected}" )
    return measured


def installed_families():
    """
    Ensures:
        - returns the sorted distinct family names fontconfig reports for this machine
        - returns () when fontconfig is unavailable, so callers degrade to width-only
    """
    try:
        listing = subprocess.run(
            [ "fc-list", ":", "family" ], capture_output=True, text=True, timeout=20,
        ).stdout
    except ( OSError, subprocess.SubprocessError ):        # pragma: no cover - fontconfig absent
        return ()
    names = set()
    for line in listing.split( "\n" ):
        for name in line.split( "," ):
            name = name.strip()
            if name:
                names.add( name )
    return tuple( sorted( names ) )


def identify_families( page, width, families ):
    """
    Name the installed families whose OWN width matches `width`.

    A width alone says a font changed; this says which one it changed to, which is the
    difference between a red number and an actionable one.

    Requires:
        - width is a measured stack width from `measure_stacks`
    Ensures:
        - returns the sorted families matching within WIDTH_TOLERANCE, possibly several
          (Arimo and Liberation Sans are metric clones and will both match), possibly
          none when the selected font is not installed under a name of its own
    """
    measured = measure_stacks( page, [ f'"{name}"' for name in families ] )
    hits = [ name for name in families
             if abs( measured[ f'"{name}"' ] - width ) <= WIDTH_TOLERANCE ]
    return tuple( sorted( hits ) )


def build_fingerprint( page, root ):
    """
    Ensures:
        - returns {stack: width} for every stack the tree declares, ready to serialize
    """
    stacks = declared_font_stacks( root )
    return measure_stacks( page, stacks )


def load_fingerprint( path ):
    """
    Ensures:
        - returns the committed {stack: width} mapping
        - returns None when the file is absent, so the caller can say so plainly rather
          than comparing against an empty dict and passing over nothing
    """
    try:
        with open( path, encoding="utf-8" ) as fh:
            return json.load( fh )
    except FileNotFoundError:
        return None
