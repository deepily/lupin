"""
Render-environment fingerprint guard for the visual regression suite.

Bug a5559b49 (2026-06-30): the :8000 merge-gate visual suite went RED because the
`lupin-rest-test` container was missing `fonts-dejavu-core`. Lupin's CSS font stacks
all terminate in the generic `sans-serif` (the named fonts before it — `-apple-system`,
`Segoe UI`, `Roboto`, `Helvetica Neue` — do not exist on Linux), so fontconfig falls
through to the terminal generic. WITHOUT DejaVu, `fc-match sans-serif` resolves to
`WenQuanYi Zen Hei` (a CJK face) in the container, while the HOST (which has DejaVu)
resolves to `DejaVu Sans`. Body text then renders in a different typeface
container-vs-host, and every host-captured baseline mismatches the in-container render.

The `browser_type_launch_args` / `browser_context_args` fixtures in conftest.py pin
hinting / LCD / DPI / color / viewport — i.e. render *config* — but NOT the font SET.
A missing font package that flips the generic fallback slips right through them. This
guard closes that gap: it asserts the render environment resolves the generic families
to DejaVu, so the NEXT time a font package goes missing (image rebuild, base-image bump)
the failure is an explicit, named assertion instead of 37 mystery visual mismatches.

Pure environment introspection — no server or Playwright page needed, so it is cheap
enough to run on :7999 (host) as well as the :8000 (container) merge gate. On both, the
render env MUST resolve `sans-serif` → DejaVu Sans for the git-tracked baselines to be
portable.

Root-cause writeup: src/rnd/v0.1.9/2026.06.30-visual-regression-env-drift-root-cause.md

Requires:
    - fontconfig CLI (`fc-match`, `fc-list`) present on PATH
Ensures:
    - fails LOUD if the generic `sans-serif`/`serif`/`monospace` fallback does not
      resolve to a DejaVu family in the current render environment
"""

import glob
import os
import shutil
import subprocess

import pytest


# The Chromium build the git-tracked baselines were rendered against. Bump this in
# lockstep with any Playwright upgrade that changes the pinned Chromium build — a
# mismatch here means the render binary drifted out from under the baselines.
CHROMIUM_EXPECTED_BUILD = "1208"

# FreeType is the glyph rasterizer. This guard asserts the MAJOR line ONLY — deliberately,
# NOT because patch deltas are cosmetically irrelevant. Task 6975970a proved the opposite:
# the host↔container patch delta (host 2.11.1+dfsg-1ubuntu0.2 vs container …0.3) shifts
# glyph-edge anti-aliasing just past the 0.1px threshold — a real, if benign, AA axis.
# The resolution (task 47e0dfa9, Option-2, 2026-07-01) is CONTAINER-CANONICAL: baselines
# are captured in-container and the :8000 merge gate renders in-container, so the gate is
# always self-consistent at the container's freetype patch level. The host dev box sits one
# security patch behind, so HOST-side `-k visual` runs are NON-AUTHORITATIVE on glyph edges.
# This guard therefore stays MAJOR-only ON PURPOSE: it runs on BOTH :7999 (host, …0.2) and
# :8000 (container, …0.3), so a FULL-version assertion would false-fail the intentionally-
# unaligned host. A MAJOR bump WOULD change rasterization enough to invalidate baselines, so
# that remains load-bearing and asserted. Decision + rejected "pin both sides" alternatives:
# src/rnd/v0.1.9/2026.06.30-visual-regression-env-drift-root-cause.md §Resolution (Option-2).
FREETYPE_EXPECTED_MAJOR = "2"


# Every Lupin CSS stack terminates in one of these generics after a run of Linux-absent
# named fonts, so THESE are the resolutions that actually drive baseline pixels.
EXPECTED_GENERIC_FALLBACKS = {
    "sans-serif" : "DejaVu Sans",
    "serif"      : "DejaVu Serif",
    "monospace"  : "DejaVu Sans Mono",
}

# Named fonts that appear in Lupin's stacks but do not exist on Linux — they MUST fall
# through to the sans-serif generic (DejaVu Sans), never to a CJK face.
CSS_NAMED_SANS_FONTS = [ "Segoe UI", "Roboto", "Helvetica Neue" ]

# Skip cleanly (rather than error) if fontconfig tooling is somehow unavailable.
_HAS_FONTCONFIG = shutil.which( "fc-match" ) is not None and shutil.which( "fc-list" ) is not None
pytestmark = pytest.mark.skipif( not _HAS_FONTCONFIG, reason="fontconfig CLI (fc-match/fc-list) not on PATH" )


def _fc_match( family ):
    """
    Return the family name fontconfig resolves `family` to in this environment.

    Requires:
        - family is a non-empty fontconfig pattern string
        - fc-match is on PATH
    Ensures:
        - returns the resolved family field from `fc-match -f %{family}`
    """
    result = subprocess.run(
        [ "fc-match", "-f", "%{family}", family ],
        capture_output=True, text=True, timeout=10,
    )
    return result.stdout.strip()


@pytest.mark.parametrize( "generic,expected", list( EXPECTED_GENERIC_FALLBACKS.items() ) )
def test_generic_family_resolves_to_dejavu( generic, expected ):
    """The generic CSS families must resolve to DejaVu — the host-captured baseline typeface."""
    resolved = _fc_match( generic )
    assert expected in resolved, (
        f"Render-env drift (bug a5559b49): fc-match '{generic}' resolved to '{resolved}', "
        f"expected '{expected}'. Visual baselines are captured against DejaVu; a different "
        f"fallback (e.g. WenQuanYi Zen Hei) means fonts-dejavu-core is missing from this "
        f"environment — install it (docker/lupin/Dockerfile) before trusting the visual suite."
    )


@pytest.mark.parametrize( "named", CSS_NAMED_SANS_FONTS )
def test_css_named_sans_fonts_fall_through_to_dejavu( named ):
    """Linux-absent named fonts in Lupin's stacks must fall through to DejaVu Sans, not a CJK face."""
    resolved = _fc_match( named )
    assert "DejaVu Sans" in resolved, (
        f"Render-env drift (bug a5559b49): fc-match '{named}' resolved to '{resolved}', "
        f"expected 'DejaVu Sans'. A CJK fallback here means fonts-dejavu-core is missing."
    )


def test_dejavu_core_installed():
    """fonts-dejavu-core must actually be present so the fallbacks above stay stable."""
    listing = subprocess.run(
        [ "fc-list", ":", "family" ], capture_output=True, text=True, timeout=10,
    ).stdout
    assert "DejaVu Sans" in listing, (
        "Render-env drift (bug a5559b49): no DejaVu family in fc-list — fonts-dejavu-core "
        "is not installed in this render environment. See docker/lupin/Dockerfile."
    )


@pytest.mark.skipif( shutil.which( "dpkg-query" ) is None, reason="dpkg-query not on PATH" )
def test_freetype_major_version():
    """The FreeType rasterizer must stay on the major line the baselines were rendered with."""
    version = subprocess.run(
        [ "dpkg-query", "-W", "-f=${Version}", "libfreetype6" ],
        capture_output=True, text=True, timeout=10,
    ).stdout.strip()
    major = version.split( "." )[ 0 ]
    assert major == FREETYPE_EXPECTED_MAJOR, (
        f"Render-env drift (bug a5559b49): libfreetype6 major is '{major}' "
        f"(full '{version}'), expected '{FREETYPE_EXPECTED_MAJOR}'. A major FreeType bump "
        f"changes glyph rasterization enough to invalidate the visual baselines."
    )


def test_chromium_build_matches_baseline():
    """The Playwright Chromium build must match the one the baselines were rendered against."""
    cache_dir = os.path.expanduser( "~/.cache/ms-playwright" )
    builds    = sorted( os.path.basename( p ) for p in glob.glob( os.path.join( cache_dir, "chromium-*" ) )
                        if "headless" not in os.path.basename( p ) )
    expected  = f"chromium-{CHROMIUM_EXPECTED_BUILD}"
    assert expected in builds, (
        f"Render-env drift (bug a5559b49): Playwright Chromium build {builds} does not include "
        f"'{expected}'. A Chromium build change shifts subpixel rendering; rebaseline the visual "
        f"suite and bump CHROMIUM_EXPECTED_BUILD when this is an intentional Playwright upgrade."
    )
