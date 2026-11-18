"""
Keep the prediction integration tests off the dev server.

Three integration files post to the reset route with drop_table, which empties the decision rows.
They read their server from LUPIN_TEST_BASE_URL, default :8000. Pointed at :7999 they would empty the
dev database, so each file passes its base url through this guard when it is imported.
"""

from urllib.parse import urlparse

DEV_SERVER_PORT = 7999


def refuse_dev_server( base_url ):
    """
    Return the base url, or refuse it when it names the dev server.

    Requires:
        - base_url is an http or https url string

    Ensures:
        - returns base_url unchanged when its port is not the dev server's
        - any host counts: localhost, 127.0.0.1 and a hostname are all refused on port 7999

    Raises:
        - RuntimeError naming the url when the port is 7999
    """
    if urlparse( base_url ).port == DEV_SERVER_PORT:
        raise RuntimeError( f"LUPIN_TEST_BASE_URL {base_url!r} is the dev server (:{DEV_SERVER_PORT}); these tests empty the prediction decision rows and run only against the :8000 test server" )
    return base_url
