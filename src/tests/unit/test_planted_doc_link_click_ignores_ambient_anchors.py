"""
Row 0a678842 — the doc-link viewport e2e clicked an AMBIENT anchor and blamed CSS.

ts-742c706c (2026-09-28): the page carried a live-history doc anchor that sorted before the
one the test planted; `anchors.first.click()` took it, and a <p> from another message sat
over it — "intercepts pointer events". This drives the REAL helper against a synthetic page
built the same way (ambient anchor first, covered by a <p>; planted anchor second, clear):

    OLD selector (`.first`)  → click times out on the covered ambient anchor
    click_planted_doc_link   → clicks the planted anchor, and only that one

Runs a headless chromium; needs no server, so it is unit-tier.
"""

import pytest
from playwright.sync_api import sync_playwright, Error as PlaywrightError

from tests.e2e_ui.doc_link_click import click_planted_doc_link

_MARKER = "E2E doc-link marker (test)"

_PAGE = f"""<!doctype html><body style="margin:0">
<div style="position:relative;height:60px">
  <a id="ambient" href="/app/docs?path=lupin-mobile/ambient.md">ambient history link</a>
  <p id="cover" style="position:absolute;left:0;top:0;width:400px;height:40px;margin:0;background:#ccc">
    I'm going for a walk. The 3 of you can coordinate…</p>
</div>
<div><a id="planted" href="/app/docs?path=lupin/CLAUDE.md">{_MARKER}</a></div>
<script>
  window.__clicked = [];
  for ( const a of document.querySelectorAll( "a" ) ) {{
    a.addEventListener( "click", ( e ) => {{ e.preventDefault(); window.__clicked.push( a.id ); }} );
  }}
</script></body>"""


@pytest.fixture( scope="module" )
def page():
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        yield browser.new_page()
        browser.close()


def _load( page, html=_PAGE ):
    page.set_content( html )


def test_the_old_first_anchor_selector_is_stopped_by_the_ambient_cover( page ):
    _load( page )
    # Positive control on the fixture: the cover really sits on the ambient anchor.
    assert page.evaluate( "() => { const r = document.getElementById( 'ambient' ).getBoundingClientRect();"
                          " return document.elementFromPoint( r.x + r.width / 2, r.y + r.height / 2 ).id }" ) == "cover"
    with pytest.raises( PlaywrightError, match="intercepts pointer events" ):
        page.locator( 'a[href*="/app/docs?path="]' ).first.click( timeout=1500 )
    assert page.evaluate( "() => window.__clicked" ) == []


def test_the_planted_link_helper_clicks_the_planted_anchor_only( page ):
    _load( page )
    assert click_planted_doc_link( page, _MARKER ) == 1
    assert page.evaluate( "() => window.__clicked" ) == [ "planted" ]


def test_zero_matches_is_a_loud_failure_not_a_vacuous_pass( page ):
    _load( page )
    with pytest.raises( AssertionError, match="found 0" ):
        click_planted_doc_link( page, "no such label" )


def test_an_ambiguous_label_is_refused( page ):
    _load( page, _PAGE.replace( "ambient history link", _MARKER ) )
    with pytest.raises( AssertionError, match="found 2" ):
        click_planted_doc_link( page, _MARKER )
