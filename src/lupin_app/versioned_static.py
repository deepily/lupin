"""
Give `/static` an explicit cache policy, decided by whether the URL carries a `?v=` token.

The page shell is served `Cache-Control: no-cache` (`cosa/rest/routers/pages.py`), so a
reload revalidates it and picks up whatever `?v=` tokens the page now links. The static
mount sets only `Last-Modified` and an ETag. The cache-busting scheme therefore rests on
the HTML being revalidated first, and nothing enforces that.

Bumping a token mints a new URL, but the old URL is also a cache key. With no freshness
directive on it, a browser may serve it from heuristic cache without ever asking. A tab
open when the token moved keeps running the old asset. That asset is valid JavaScript that
lacks the newest wiring, so the operator sees a control that does nothing and throws nothing.

Two policies, because each is wrong where the other belongs:

  - A `?v=`-tokened URL is immutable. The token names one revision, so changing the file
    means minting a different URL. The old one never needs to change, which earns a
    year-long `max-age` and `immutable`.
  - An un-tokened URL has no revision in it. The same URL must serve tomorrow's bytes, so
    caching it hard is the stale-asset trap one level down. It gets `no-cache`: cacheable,
    but revalidated every time, which an ETag makes a cheap conditional GET.

This is a serving policy, not a fix for one asset. A per-file remedy would leave every
other asset with no cache directive.

Only `notifications.html` versions anything. The other shells (multiplexer, dev-tools,
document-viewer, landing, parity-harness, audio-player) link their assets with no token,
so they have no busting mechanism at all. The `no-cache` half of this policy is what they
get instead, and it covers most of the assets.

`src/lupin_app/static/dist/` is gitignored, so a worktree has none of it and an asset
census run there reads live files as dead links. Run any census in the main checkout.
"""

from starlette.staticfiles import StaticFiles


# A year, the conventional ceiling for an immutable asset. `immutable` additionally tells
# the browser not to revalidate even on an explicit reload, which is the whole point: the
# URL cannot become wrong, so asking about it is pure cost.
_IMMUTABLE = "public, max-age=31536000, immutable"

# Cacheable but never used without asking. NOT `no-store` — revalidation against the ETag
# is a 304 in the common case, so this stays cheap while staying correct.
_REVALIDATE = "no-cache"


class VersionedStaticFiles( StaticFiles ):
    """
    `StaticFiles` that sets `Cache-Control` from the presence of a `?v=` query token.

    Requires:
        - constructed exactly like `StaticFiles` (it adds no arguments)

    Ensures:
        - a request whose query string contains a `v=` parameter is answered with
          `public, max-age=31536000, immutable`
        - every other request is answered with `no-cache`
        - the two answers differ for the same file, so the token is read rather than
          ignored
        - behaviour is otherwise `StaticFiles`' own — ETag, Last-Modified, range requests,
          404s and 304s are untouched
    """

    def file_response( self, full_path, stat_result, scope, status_code=200 ):
        response = super().file_response( full_path, stat_result, scope, status_code )
        response.headers[ "Cache-Control" ] = _IMMUTABLE if _has_version_token( scope ) else _REVALIDATE
        return response


def _has_version_token( scope ):
    """
    Does this request's query string carry a `v=` parameter?

    Parsed rather than substring-matched: a filename containing the letters "v=" is not a
    version token, and `?nov=1` is not one either.

    Requires:
        - scope is an ASGI scope dict, which may lack "query_string" entirely

    Ensures:
        - returns True only when a parameter literally named "v" is present
        - never raises on a missing or undecodable query string
    """
    from urllib.parse import parse_qs

    raw = scope.get( "query_string" ) or b""
    if isinstance( raw, bytes ): raw = raw.decode( "latin-1", "replace" )
    return "v" in parse_qs( raw, keep_blank_values=True )
