"""
The legacy page must load a `notifications.js` that carries the forecast fold.

The built `dist/` is gitignored, and the legacy page links `notifications.js` with a `?v=` token that
the browser caches as immutable. A fold added without a new token is invisible to every tab that
already holds the old URL, and it throws nothing. So the token is pinned away from the value it had
before the fold, and the script is pinned to contain the fold.
"""

import re
from pathlib import Path

STATIC_DIR = Path( __file__ ).resolve().parents[ 2 ] / "lupin_app" / "static"

# The token the legacy page carried before the forecast fold (phase 5). A later bump moves off it too.
TOKEN_BEFORE_THE_FOLD = "c96216638454"


def _linked_token():
    html  = ( STATIC_DIR / "html" / "notifications.html" ).read_text( encoding="utf-8" )
    found = re.findall( r"/static/js/notifications\.js\?v=([0-9a-f]+)", html )
    assert len( found ) == 1, f"expected one notifications.js link with a token, found {found}"
    return found[ 0 ]


def test_the_legacy_page_links_a_new_token():
    """The token is not the pre-fold value and is a 12-character hash."""
    token = _linked_token()
    assert token != TOKEN_BEFORE_THE_FOLD, "the fold shipped without a new ?v= token"
    assert len( token ) == 12


def test_the_script_the_token_names_carries_the_fold():
    """The linked script builds the fold, names the states and reports both seen events."""
    js = ( STATIC_DIR / "js" / "notifications.js" ).read_text( encoding="utf-8" )
    for needle in ( "prediction-hint-fold", "<details", "insufficient_evidence", "below_threshold", "unavailable",
                    "/api/notify/prediction-seen/", "fold_opened", "always_yes_rate" ):
        assert needle in js, f"notifications.js lacks {needle}"
