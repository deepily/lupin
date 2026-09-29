"""
Row 9691ca7a — click the history rows a test SEEDED, never "the first delete button".

`seeded_history_page` inserts rows whose id_hash is `test-job-<NNN>::<user_id>` and the card
renders that id_hash as `data-job-id`. A locator over every `.delete-btn` is therefore only as
safe as the venue's user scoping: the day a history list also carries someone else's row, an
unscoped first-match click on a delete button removes a real row from the venue's DB. Pinning the locator to the seeded
prefix AND this user's id makes the site safe by its own text.

Lives in its own module so the unit tier can drive it on a synthetic page without importing the
e2e conftest (whose fixtures need a live test server).
"""

SEEDED_PREFIX = "test-job-"


def seeded_user_id( records ):
    """
    The user id the seed helper stamped on every row.

    Requires:
        - records is the non-empty list `seeded_history_page` returns

    Ensures:
        - returns the text after the first "::" of records[ 0 ][ "id_hash" ]

    Raises:
        - AssertionError when records is empty or an id_hash lacks the "::<user_id>" suffix
    """
    assert records, "no seeded records — a locator built from nothing would match every user's rows"
    id_hash = records[ 0 ][ "id_hash" ]
    assert "::" in id_hash, f"seeded id_hash {id_hash!r} has no '::<user_id>' suffix"
    return id_hash.split( "::", 1 )[ 1 ]


def own_history_cards( scope, records ):
    """
    Locator for the `.job-card`s this test seeded, under `scope` (a Page or a Locator).

    Ensures:
        - matches only cards whose data-job-id starts with SEEDED_PREFIX and ends with
          "::<the seeded user's id>"
    """
    uid = seeded_user_id( records )
    return scope.locator( f'.job-card[data-job-id^="{SEEDED_PREFIX}"][data-job-id$="::{uid}"]' )


def own_delete_buttons( scope, records, buttons_selector=".delete-btn" ):
    """
    Locator for the delete buttons inside the seeded cards only.

    Ensures:
        - never matches a button in a card the test did not seed
    """
    return own_history_cards( scope, records ).locator( buttons_selector )
