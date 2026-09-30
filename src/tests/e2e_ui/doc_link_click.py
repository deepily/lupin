"""
Row 0a678842 — click the doc link a test PLANTED, never "the first doc anchor on the page".

Lives in its own module so the unit tier can drive it against a synthetic page without
importing the e2e conftest (whose fixtures need a live test server).
"""


def click_planted_doc_link( page, marker ):
    """
    Click the one doc anchor whose text contains `marker`.

    Requires:
        - the test planted a link whose label contains `marker`, unique on the page

    Ensures:
        - exactly one anchor matches before the click, else AssertionError naming the count
        - the click lands on that anchor, whatever ambient doc anchors the page also carries
        - returns the match count (1)

    Raises:
        - AssertionError when zero anchors match (the planted link did not render) or more
          than one does (the label is not unique, so the click would be ambiguous again)
    """
    anchors = page.locator( 'a[href*="/app/docs?path="]', has_text=marker )
    count   = anchors.count()
    assert count == 1, \
        f"expected exactly one doc anchor labelled {marker!r}, found {count} — 0 means the emitted " \
        f"notification did not render its link (every geometry assertion after the click would be " \
        f"vacuous); 2+ means the label is not unique on this page and the click is ambiguous again"
    anchors.first.click()
    page.wait_for_timeout( 400 )
    return count
