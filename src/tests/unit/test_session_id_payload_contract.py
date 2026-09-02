"""
The field the browser reads out of /api/get-session-id must be the field the server puts in.

THE SHAPE (row a501a714)
------------------------
`notifications.js` asks the server for a session id and stores it. If the payload
lacks the field it reads, the client throws PAYLOAD_MISSING_FIELD, lands in the
fallback, and mints an id LOCALLY.

🔴 WHY THAT IS NOT A COSMETIC FAILURE. A self-minted id is drawn at random from
10 adjectives x 10 animals with NO uniqueness check, and 50 of those 100 names are
inside the server generator's own space — so a fallback client can collide with a
NORMALLY-PROVISIONED one. Measured on row a501a714 against a real WebSocketManager:
the second connection OVERWRITES `active_connections[ id ]` and flips
`session_to_user[ id ]`, so one user's notifications reach another user's socket.
A one-sided rename of this field is therefore a cross-user routing bug, arriving
silently — since ad2cbbbe the degraded path produces a WORKING socket.

Nothing pinned this contract. The endpoint's response and the client's read sat in
two files with no test between them.

WHY THE FIELD NAME IS EXTRACTED FROM THE CLIENT RATHER THAN WRITTEN DOWN HERE.
A literal in this file would only be a third place to rename. Reading the name the
CLIENT actually uses and asserting the SERVER supplies it makes the test a
cross-check between the two independent sides:

    rename BOTH sides together   -> passes  (correct: the contract still holds)
    rename the CLIENT only       -> fails   (server no longer supplies what it reads)
    rename the SERVER only       -> fails   (client reads what is no longer supplied)

That is the same discipline as counting a population by a different method than the
one under test: a check that reads one side twice cannot see the two sides disagree.

Venue: :7999-eligible. Reads two files off disk; no server, no network, no browser.
"""
import os
import pathlib
import re

import pytest


LUPIN_ROOT = pathlib.Path( os.environ[ "LUPIN_ROOT" ] )
CLIENT     = LUPIN_ROOT / "src/lupin_app/static/js/notifications.js"
ROUTER     = LUPIN_ROOT / "src/cosa/rest/routers/system.py"

ENDPOINT = "/api/get-session-id"


def _field_the_client_reads():
    """
    The payload key `notifications.js` pulls the session id out of.

    Ensures:
        - returns the attribute name from the `const sessionId = data.<name>;`
          assignment that follows the fetch of the session-id endpoint
        - raises rather than returning a default: a silent fallback here would make
          every assertion below pass against a client this test cannot actually read,
          which is the failure mode this file exists to prevent
    """
    src = CLIENT.read_text()
    m   = re.search( r"const\s+sessionId\s*=\s*data\.(\w+)\s*;", src )
    assert m, (
        "could not find the `const sessionId = data.<field>;` read in notifications.js — "
        "the extraction is stale, and a default here would make this file pass vacuously"
    )
    return m.group( 1 )


def _fields_the_router_returns():
    """
    The keys of the dict literal returned by the get-session-id handler.

    Ensures:
        - returns the set of string keys in the `return { ... }` that follows the
          endpoint's route decorator
        - raises rather than returning an empty set, for the same reason as above
    """
    src   = ROUTER.read_text()
    at    = src.find( ENDPOINT )
    assert at != -1, f"{ENDPOINT} is not registered in {ROUTER.name} — this test is aimed at the wrong file"

    ret   = src.find( "return {", at )
    assert ret != -1, f"no dict literal returned after {ENDPOINT}"
    close = src.find( "}", ret )
    keys  = set( re.findall( r'"(\w+)"\s*:', src[ ret : close ] ) )
    assert keys, f"parsed ZERO keys out of the {ENDPOINT} return — every assertion below would pass vacuously"
    return keys


def test_the_extraction_reaches_BOTH_files():
    """
    The instrument before the reading.

    Both helpers raise on a failed parse rather than returning a default, so this
    case is what proves they parsed something real — a regex that silently matched
    nothing would otherwise make the contract test below green by vacuity.
    """
    assert _field_the_client_reads()
    assert _fields_the_router_returns()


def test_the_server_supplies_the_field_the_browser_reads():
    """
    The contract itself.

    A one-sided rename lands the browser in PAYLOAD_MISSING_FIELD, which since
    ad2cbbbe degrades silently onto a self-minted id — and a self-minted id can
    collide with a server-issued one and cross-route notifications between users.
    """
    field  = _field_the_client_reads()
    served = _fields_the_router_returns()
    assert field in served, (
        f"notifications.js reads `data.{field}` out of {ENDPOINT}, but that handler "
        f"returns {sorted( served )}.\n"
        f"  Every browser would throw PAYLOAD_MISSING_FIELD and fall back to a "
        f"locally-minted session id, with a working socket and no visible symptom."
    )
