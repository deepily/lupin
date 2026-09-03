"""
Give `/static` an explicit cache policy, decided by whether the URL carries a `?v=` token.

THE DEFECT THIS CLOSES, measured 2026-09-02 against the live :7999. The SPA shell is
served `Cache-Control: no-cache` (`cosa/rest/routers/pages.py`), so a reload revalidates it
and picks up whatever `?v=` tokens the page now links. The static mount underneath set NO
cache-control at all — only `Last-Modified` and an ETag.

⇒ SO THE WHOLE CACHE-BUSTING SCHEME RESTED ON THE HTML BEING REVALIDATED FIRST, AND
NOTHING ENFORCED THAT. Bumping a token mints a new URL, which is the point; but the OLD
URL is also a cache key, and with no freshness directive on it a browser may serve it from
heuristic cache indefinitely without ever asking. A tab already open when the token moved
keeps running the old asset — and because the old asset is valid JavaScript that simply
lacks the newest wiring, the operator sees a control that does nothing and throws nothing.
Measured at 1184bd8e: 9 of the 9 assets the notifications shell links with `?v=` came back
with no cache-control, and the token made no difference to the answer.

WHY TWO POLICIES RATHER THAN ONE. They are not a preference; each is wrong where the other
belongs.

  · A `?v=`-TOKENED URL IS IMMUTABLE BY CONSTRUCTION. The token names one revision, so
    changing the file means minting a different URL. The old one can never need to change,
    which is exactly what earns a year-long `max-age` and `immutable`.
  · AN UN-TOKENED URL HAS NO REVISION IN IT. The same URL must serve tomorrow's bytes, so
    caching it hard is the stale-asset trap one level down — the file changes underneath a
    URL that never does. It gets `no-cache`: cacheable, but revalidated every time, which
    an ETag makes a cheap conditional GET.

⚠️ THIS IS A SERVING POLICY, NOT A FIX FOR ANY ONE ASSET. The hole was never about a file
somebody was looking at; it was a policy absent everywhere, so a per-file remedy would have
left the other eight exactly as they were.

🔴 AND "THE OTHER EIGHT" UNDERSTATES IT BY SIX TIMES — MEASURED ACROSS EVERY SHELL, NOT THE
ONE THE INCIDENT HAPPENED ON. 54 asset links across 7 shells, 53 of which serve. Before this
policy: 53 of 53 with no cache directive. After: 0 with none — 44 revalidating, 9 immutable.

⇒ SO THE `?v=` SCHEME IS NOT THE SUBJECT, IT IS ONE PAGE'S CORNER OF IT. `notifications.html`
is the ONLY shell that versions anything; the other six — multiplexer (23 assets), dev-tools,
document-viewer, landing, parity-harness, audio-player — link 44 assets with no token at all.
They never had a busting mechanism to have a hole in. They were relying on nothing, and the
`no-cache` half of this policy is what they get instead. That is the larger half of the
change and it is easy to miss, because the bug that surfaced it happened on the one page
where a token scheme already existed.
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
