"""
The text a card wait prints on a timeout, so the failing run carries its evidence.

An e2e wait that times out says only that a selector stayed attached. Three readings say what the page held
then: the card's markup, the element with focus, and the ids in the action-required store.
The formatter is a plain function so a unit test can pin the text without a browser.
"""


def format_card_wait_report( nid, card_html, active, store_ids ):
    """
    Build the report for a card wait that timed out.

    Requires:
        - nid is the id_hash of the card that was waited on
        - card_html is the card's outer HTML as a str, or None when no card carries that id
        - active is a dict with tag, class_name and testid for the focused element, or None
        - store_ids is a list of the id_hash values the store holds, or None when the store was unreadable

    Ensures:
        - returns a multi-line str, one labelled line per reading
        - a missing reading is named as missing, never left blank
    """
    if card_html is None: html_line = "card outerHTML: no element carries this id"
    else:                 html_line = f"card outerHTML: {card_html}"
    if active is None:    focus_line = "document.activeElement: none"
    else:                 focus_line = f"document.activeElement: tag={active[ 'tag' ]} class={active[ 'class_name' ]!r} data-testid={active[ 'testid' ]!r}"
    if store_ids is None: store_line = "actionRequired store ids: store was not readable"
    else:                 store_line = f"actionRequired store ids ({len( store_ids )}): {', '.join( store_ids ) if store_ids else 'none'}"
    return "\n".join( [ f"card wait timed out for {nid}", html_line, focus_line, store_line ] )
