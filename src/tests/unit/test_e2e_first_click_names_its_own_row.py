"""
Row 9691ca7a — an e2e `.first.click()` must name a row the test OWNS.

Row 0a678842 (2026-09-29): the doc-link e2e clicked `.first` over every doc anchor, took a
live-fleet notification's link, and a <p> covered it. The same shape sat at 16 more
`.first.click(` sites. At a DELETE button the harm is worse than a red test: a wrong pick
removes a real row from the venue's DB.

Two guards and one behavioural proof:

  1. EVERY `.first.click(` in src/tests/e2e_ui/*.py is either routed through
     `own_delete_buttons(` (seeded rows only, matched by id_hash prefix AND user id), or listed
     below with the reason it cannot reach a shared row. A new one fails here, naming file and line.
  2. A line naming "delete" next to `.first` must come from `own_delete_buttons(` (directly, or via
     a variable assigned from it in the same file) — no exception list, because a wrong pick is
     destructive.
  3. The helper, driven on a synthetic page holding another user's card FIRST, clicks only the
     seeded card; the unscoped locator clicks the other user's.

⚠️ CEILINGS, named: the delete rule keys on the word "delete" in the line, so a delete button held
in a variable named otherwise escapes it; and only the `.first.click(` spelling is enforced — a
`.first` assigned to a variable and clicked later (25 such lines exist, unclassified) is not.
"""

import re
import subprocess
from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright

from tests.e2e_ui.own_history_rows import own_delete_buttons, own_history_cards, seeded_user_id

ROOT = Path( __file__ ).resolve().parents[ 3 ]   # tree root from THIS file, never LUPIN_ROOT

# (file, stripped line) -> ( expected count, why this `.first` cannot reach a shared row )
ALLOWED = {
    ( "task_panes.py", "headers.first.click()" ):
        ( 1, "locator is only the still-COLLAPSED groups; each click removes one from the set, and the function asserts none remain" ),
    ( "test_action_required_self_content_pane.py", "page.locator( \"a[data-test-foreign='1']\" ).first.click()" ):
        ( 1, "data-test-foreign is the marker this test's own injector plants" ),
    ( "test_action_required_self_content_pane.py", "page.locator( \".abstract-indicator[data-test-foreign='1']\" ).first.click()" ):
        ( 1, "data-test-foreign is the marker this test's own injector plants" ),
    ( "test_broadcast_panel.py", "notifications_page.locator( \".broadcast-chip-all\" ).first.click()" ):
        ( 2, "panel chrome, one class-specific chip; the click only inserts literal text into a textarea and mutates nothing" ),
    ( "test_holding_area_per_row_editor.py", "logged_in_page.locator( \"#holding-area-container .task-disclose-button\" ).first.click()" ):
        ( 1, "the page is route-seeded (_route_tasks fulfils /api/tasks*), and a disclose toggle mutates nothing" ),
    ( "test_row_geometry_is_one_shape_in_all_three_panes.py", "button.first.click()" ):
        ( 1, "route-seeded panes (_route_tasks); a test-id'd expand-all toggle mutates nothing" ),
    ( "test_row_geometry_is_one_shape_in_all_three_panes.py", "toggles.first.click()" ):
        ( 2, "route-seeded panes (_route_tasks); disclose toggles mutate nothing" ),
    ( "doc_link_click.py", "anchors.first.click()" ):
        ( 1, "the locator is narrowed by has_text=marker and the helper asserts exactly one match before clicking" ),
}

_HELPER_CALL = "own_delete_buttons("


def _e2e_sources():
    tracked = subprocess.run( [ "git", "-C", str( ROOT ), "ls-files", "src/tests/e2e_ui" ],
                              capture_output=True, text=True, check=True ).stdout.split( "\n" )
    return { f: ( ROOT / f ).read_text( errors="replace" ) for f in tracked if f.endswith( ".py" ) }


def _code_lines( text ):
    for n, line in enumerate( text.split( "\n" ), 1 ):
        if not line.lstrip().startswith( "#" ):
            yield n, line


def violations( sources ):
    """
    Every breach of guards 1 and 2 across `sources` ({ path: text }).

    Ensures:
        - returns a list of human-readable strings, empty when the sources are clean
    """
    found, seen = [], {}
    for path, text in sources.items():
        name = Path( path ).name
        for n, line in _code_lines( text ):
            if ".first" not in line:
                continue
            stripped = line.strip()
            var      = re.match( r"(\w+)\.first\.click\(", stripped )
            via_var  = var is not None and re.search( rf"\b{var.group( 1 )}\s*=\s*own_delete_buttons\(", text ) is not None
            routed   = _HELPER_CALL in line or via_var
            if "delete" in line.lower() and not routed:
                found.append( f"{path}:{n}: a delete button picked with .first must come from own_delete_buttons(): {stripped}" )
            if ".first.click(" in line and not routed:
                key = ( name, stripped )
                seen[ key ] = seen.get( key, 0 ) + 1
                if key not in ALLOWED:
                    found.append( f"{path}:{n}: unlisted .first.click() — name a planted/seeded element, or add it to ALLOWED with the reason it cannot reach a shared row: {stripped}" )
    for key, ( count, _why ) in ALLOWED.items():
        if seen.get( key, 0 ) != count:
            found.append( f"ALLOWED entry {key} expected {count} occurrence(s), found {seen.get( key, 0 )} — stale entry or a moved site" )
    return found


def test_the_population_is_swept_and_the_positive_controls_bite():
    sources = _e2e_sources()
    sites   = sum( t.count( ".first.click(" ) for t in sources.values() )
    print( f"[first-click guard] {len( sources )} e2e_ui files swept, {sites} .first.click( sites, {len( ALLOWED )} listed" )
    assert len( sources ) > 100 and sites >= 15, f"sweep reached {len( sources )} files / {sites} sites"
    unlisted = violations( { "src/tests/e2e_ui/test_new.py": "page.locator( '.row' ).first.click()\n" } )
    assert any( "unlisted .first.click()" in v for v in unlisted )
    delete   = violations( { "src/tests/e2e_ui/test_new.py": "page.locator( '.delete-btn' ).first.click()\n" } )
    assert any( "own_delete_buttons()" in v for v in delete )
    assert not any( "test_new.py" in v for v in violations( { "src/tests/e2e_ui/test_new.py": "x = own_delete_buttons( c, r ).first\n" } ) )
    assert not any( "test_new.py" in v for v in violations( { "src/tests/e2e_ui/test_new.py": "# page.locator( '.row' ).first.click()\n" } ) )


def test_no_e2e_first_click_reaches_a_row_the_test_does_not_own():
    assert violations( _e2e_sources() ) == []


# ── the helper, on a synthetic page ─────────────────────────────────────────

_OTHER = "test-job-001::user-OTHER"
_MINE  = "test-job-001::user-MINE"

_PAGE = f"""<!doctype html><body>
<div id="history-jobs-container">
  <div class="job-card" data-job-id="{_OTHER}"><button class="delete-btn">del other</button></div>
  <div class="job-card" data-job-id="prod-job-77::user-MINE"><button class="delete-btn">del prod</button></div>
  <div class="job-card" data-job-id="{_MINE}"><button class="delete-btn">del mine</button></div>
</div>
<script>
  window.__clicked = [];
  for ( const b of document.querySelectorAll( ".delete-btn" ) )
    b.addEventListener( "click", () => window.__clicked.push( b.closest( ".job-card" ).dataset.jobId ) );
</script></body>"""

RECORDS = [ { "id_hash": _MINE } ]


@pytest.fixture( scope="module" )
def page():
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        yield browser.new_page()
        browser.close()


def test_the_unscoped_first_delete_button_clicks_another_users_row( page ):
    page.set_content( _PAGE )
    page.locator( "#history-jobs-container" ).locator( ".delete-btn" ).first.click()
    assert page.evaluate( "() => window.__clicked" ) == [ _OTHER ]      # the hazard, shown live


def test_own_delete_buttons_click_only_the_seeded_row( page ):
    page.set_content( _PAGE )
    container = page.locator( "#history-jobs-container" )
    assert own_delete_buttons( container, RECORDS ).count() == 1
    own_delete_buttons( container, RECORDS ).first.click()
    assert page.evaluate( "() => window.__clicked" ) == [ _MINE ]        # not the other user's, not the prod-prefixed one


def test_the_prefix_and_the_user_suffix_are_both_required( page ):
    page.set_content( _PAGE )
    assert own_history_cards( page, RECORDS ).count() == 1
    assert own_history_cards( page, [ { "id_hash": "test-job-001::user-OTHER" } ] ).count() == 1
    assert own_history_cards( page, [ { "id_hash": "test-job-001::nobody" } ] ).count() == 0


def test_the_helper_refuses_to_build_a_locator_from_nothing():
    assert seeded_user_id( RECORDS ) == "user-MINE"
    with pytest.raises( AssertionError, match="no seeded records" ):
        seeded_user_id( [] )
    with pytest.raises( AssertionError, match="no '::<user_id>'" ):
        seeded_user_id( [ { "id_hash": "bare-id" } ] )
