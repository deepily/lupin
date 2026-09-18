"""
No served page may reference a URL from an origin we do not control.

WHAT HAPPENED. static/html/test/notification_sound_tester.html pulled nine audio
clips from assets.mixkit.co and carried nine links to mixkit.co. Measured
2026-09-15: those eighteen were the ONLY off-origin references in the entire
served tree — every other page was already clean. They were stripped, and this
exists so the property holds without anyone remembering it.

HOW TO STATE THE FINDING, and this is deliberate: an ungated page emitted nine
third-party requests. That is true on any network. Whether the host is
internet-exposed or LAN-only was NOT measured, so no severity is claimed here in
either direction — a guard that overstates gets disabled, and one that understates
gets removed.

WHY A GUARD RATHER THAN A NOTE. The page was added in 53fef419 and sat for three
months; nothing was positioned to notice. A rule that depends on remembering is
not installed.

SCOPE, stated so the next reader knows what this does NOT cover:
  - It reads served HTML. A URL built at runtime in JavaScript is out of reach.
  - It checks the ORIGIN of a reference, not whether the target is reachable.
  - `src` and `href` only. A CSS url(), a form action, or a fetch() is not seen.
Those gaps are named rather than bridged.

Venue: unit tier. No server, no browser, no network.
"""

import re
from pathlib import Path

import pytest


_STATIC_ROOT = Path( __file__ ).resolve().parents[ 3 ] / "src" / "lupin_app" / "static"

# A src= or href= whose value starts a new origin: an absolute http(s) URL, or a
# protocol-relative one. Captures the tag name and the host so a failure can say
# WHAT is being pulled from WHERE without the reader opening the file.
_OFF_ORIGIN = re.compile(
    r"<\s*([a-zA-Z][a-zA-Z0-9-]*)\b[^>]*?\b(src|href)\s*=\s*[\"'](https?:)?//([^\"'/]+)",
    re.IGNORECASE,
)


def _served_html():
    """
    Every served HTML file, read once.

    Ensures:
        - returns a non-empty list of (path, text)
        - an empty corpus fails HERE rather than satisfying the guard below, since
          a sweep over zero files reports zero violations and looks like a pass

    Raises:
        - AssertionError if the served tree yields no HTML
    """
    files = sorted( p for p in _STATIC_ROOT.rglob( "*.html" ) if p.is_file() )
    assert files, f"no HTML under {_STATIC_ROOT} — this guard would be vacuous"
    return [ ( p, p.read_text( encoding="utf-8", errors="replace" ) ) for p in files ]


def _violations( sources ):
    """
    Every off-origin reference in the given corpus.

    Requires:
        - sources is [ ( path, text ) ]

    Ensures:
        - returns [ ( relative path, line, tag, attribute, host ) ], sorted
        - the same predicate serves both the real sweep and its positive control,
          so the control cannot agree with a rule the sweep does not use
    """
    found = []
    for path, text in sources:
        for m in _OFF_ORIGIN.finditer( text ):
            tag, attr, _scheme, host = m.groups()
            line = text[ : m.start() ].count( "\n" ) + 1
            found.append( ( str( path.relative_to( _STATIC_ROOT ) ), line, tag.lower(), attr.lower(), host ) )
    return sorted( found )


def test_no_served_page_references_an_off_origin_url():
    """
    The whole served surface is same-origin.

    Ensures:
        - the corpus is non-empty
        - no served HTML carries an off-origin src= or href=
        - the failure names file, line, tag and host, so the next reader does not
          have to re-derive which reference is new
    """
    sources = _served_html()
    found   = _violations( sources )

    assert not found, (
        f"{len( found )} off-origin reference(s) across {len( sources )} served HTML files:\n"
        + "\n".join( f"  {f}:{ln}  <{tag} {attr}=…> -> {host}" for f, ln, tag, attr, host in found )
        + "\nAn ungated page that references a third party emits a request to it on load. "
          "Vendor the asset under /static/ and point at the local copy instead."
    )


def test_the_off_origin_sweep_can_actually_find_one():
    """
    Positive control — the sweep must report a violation that is really there.

    A sweep nobody has watched fire could be asserting over an empty corpus, or
    running a pattern that matches nothing at all. Both print as a clean tree.

    Ensures:
        - a synthetic off-origin <source> and <a> are both found
        - the report carries the host
        - same-origin references in the SAME fixture are NOT reported
    """
    fixture = (
        '<source src="https://assets.example.com/clip.mp3" type="audio/mpeg">\n'
        '<a href="//cdn.example.org/page">x</a>\n'
        '<script src="/static/js/lupin-nav.js"></script>\n'
        '<a href="/app/admin/dev-tools">y</a>\n'
    )
    found = _violations( [ ( _STATIC_ROOT / "synthetic.html", fixture ) ] )

    hosts = sorted( host for _f, _l, _t, _a, host in found )
    assert hosts == [ "assets.example.com", "cdn.example.org" ], (
        f"sweep reported {hosts}; it must find both off-origin refs and neither local one"
    )

    tags = sorted( tag for _f, _l, tag, _a, _h in found )
    assert tags == [ "a", "source" ], f"tags reported as {tags}"


@pytest.mark.parametrize( "same_origin", [
    '<script src="/static/js/lupin-nav.js"></script>',
    '<script src="/static/js/notifications.js?v=20260915a"></script>',
    '<a href="/app/admin/dev-tools">Dev Tools</a>',
    '<a href="#anchor">jump</a>',
    '<source src="/static/audio/local.mp3" type="audio/mpeg">',
] )
def test_same_origin_references_are_not_reported( same_origin ):
    """
    The sweep must not fire on our own URLs, including cache-busted ones.

    A guard that cries on every local script gets switched off, and then the real
    violation lands in a suite nobody reads.

    Ensures:
        - a root-absolute path, a ?v= token, and a bare fragment are all clean
    """
    assert _violations( [ ( _STATIC_ROOT / "synthetic.html", same_origin ) ] ) == []
