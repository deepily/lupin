"""
The wiki page list as one ranked list of entry ids, for the fusion.

A capability page names the symbols it pins.
A page that talks about the need says its pinned symbols are worth a look.
So the pages are ranked against the need, and each page's pins follow it in id order.
The list is a ranking input and never a gate.
"""
from cosa.repo.symindex.candidates import bm25

PAGE_FIELDS = ( "text", )


def wiki_ranked_ids( need, pages ):
    """
    Order the entry ids that capability pages pin by how well each page matches the need.

    Requires:
        - need is the redacted need with its redacted spans removed
        - pages is a list of { slug, text, pins } with a unique slug and a list of entry ids as pins

    Ensures:
        - pages are ranked by BM25 over their text, best first, ties by slug
        - a page that shares no word with the need contributes nothing
        - within a page the pinned ids are in id order
        - an id already listed under a better page is not listed again
        - the same need and pages always give the same list, whatever the order of pages
        - returns [] for no pages, or when no page matches
    """
    if not pages: return []
    by_slug = { p[ "slug" ]: p for p in pages }
    index   = bm25.build_bm25( [ { "id": p[ "slug" ], "text": p[ "text" ] } for p in pages ], PAGE_FIELDS )
    listed  = {}
    for slug in bm25.rank( index, need ):
        for pin in sorted( by_slug[ slug ][ "pins" ] ): listed.setdefault( pin, None )
    return list( listed )
