"""
Content-keyed cache-bust tokens for the `/static` client (row 80f46993).

THE RULE, in one place so nothing else restates it
--------------------------------------------------
A `?v=` token is the first 12 lowercase hex characters of the SHA-256 of the asset's
bytes, read from the WORKING TREE. It is not a date and it is not a commit.

    ALGORITHM     = "sha256"
    TOKEN_HEX_LEN = 12        (48 bits: a same-file collision needs ~2**24 edits to that file)

WHY NOT A DATE. The old guard compared the token's day to the asset's last-commit day and
was wrong in both directions: blind to a second edit on the same day, and red wholesale after
any squash merge or rebase, which re-date every file's last commit with no content change
(PR #22, 2026-09-30: all 12 guarded assets read stale at once). A content hash has neither
failure: same bytes always give the same token, and a changed byte always gives a new one.

A token therefore records exactly the content it vouches for, and `verify()` recomputes it.

CASCADE. An asset that embeds another asset's token (notifications.js imports ws-channel.js)
has that token inside its own bytes, so its hash moves when the import's does. `stamp()`
iterates to a fixed point; a reference cycle never converges and is reported, not looped.

Usage:
    python -m lupin_app.asset_tokens            # verify; exit 1 on drift
    python -m lupin_app.asset_tokens --stamp    # rewrite every token from current content
"""

import hashlib
import os
import re
import sys

ALGORITHM     = "sha256"
TOKEN_HEX_LEN = 12

# Third-party bundles this repo neither authors nor versions.
EXCLUDED_DIRS = frozenset( { "vendor", "canvaskit", "lupin-mobile-test" } )

# Any quoted literal `/static/...?v=<value>` — an href/src attribute or a JS import(). The
# value is deliberately NOT restricted to the token shape, so an old date token or a typo
# is found and reported as drift instead of silently going unparsed.
REF_RE = re.compile( r"""(["'])(/static/[^"'?\s]+)\?v=([^"'\s]*)\1""" )

TOKEN_RE = re.compile( r"[0-9a-f]{%d}" % TOKEN_HEX_LEN )


def project_static_root( project_root ):
    """
    Requires: project_root is the repo root (or a copy of its `src/lupin_app/static`)
    Ensures:  returns the static directory path under it
    """
    return os.path.join( project_root, "src", "lupin_app", "static" )


def content_token( data ):
    """
    Requires: data is bytes
    Ensures:  returns the first TOKEN_HEX_LEN hex chars of the SHA-256 of data
    """
    return hashlib.sha256( data ).hexdigest()[ : TOKEN_HEX_LEN ]


def static_url_to_path( project_root, static_url ):
    """
    Requires: static_url starts with "/static/"
    Ensures:  returns the on-disk path of the asset under project_root
    """
    return os.path.join( project_static_root( project_root ), static_url[ len( "/static/" ) : ] )


def source_files( project_root ):
    """
    Every authored `.html` and `.js` under the static tree, repo-relative POSIX, sorted.

    Ensures:
        - reads the disk (a new file is covered before it is committed)
        - skips EXCLUDED_DIRS
    """
    static = project_static_root( project_root )
    found  = []
    for dirpath, dirnames, filenames in os.walk( static ):
        dirnames[ : ] = [ d for d in dirnames if d not in EXCLUDED_DIRS ]
        for name in filenames:
            if name.endswith( ( ".html", ".js" ) ):
                found.append( os.path.relpath( os.path.join( dirpath, name ), project_root ).replace( os.sep, "/" ) )
    return sorted( found )


def collect_refs( project_root ):
    """
    Every versioned reference in the authored sources.

    Ensures:
        - returns [ ( source_rel, static_url, token ), ... ] sorted, one per occurrence
    """
    refs = []
    for rel in source_files( project_root ):
        with open( os.path.join( project_root, rel ), encoding="utf-8" ) as fh:
            text = fh.read()
        for match in REF_RE.finditer( text ):
            refs.append( ( rel, match.group( 2 ), match.group( 3 ) ) )
    return sorted( refs )


def verify( project_root ):
    """
    Compare every reference's token with the current bytes of the asset it names.

    Ensures:
        - returns [ ( source_rel, static_url, found_token, expected_token_or_None ), ... ]
          for each reference that does NOT vouch for its asset's current bytes; empty = clean
        - expected is None when the named asset does not exist on disk
        - reads working-tree bytes only; git is never consulted
    """
    bad = []
    for source_rel, url, token in collect_refs( project_root ):
        path = static_url_to_path( project_root, url )
        if not os.path.isfile( path ):
            bad.append( ( source_rel, url, token, None ) )
            continue
        with open( path, "rb" ) as fh:
            expected = content_token( fh.read() )
        if token != expected:
            bad.append( ( source_rel, url, token, expected ) )
    return bad


def stamp( project_root ):
    """
    Rewrite every token from current content, to a fixed point.

    Ensures:
        - returns the sorted list of source_rel paths that were rewritten
        - afterwards verify() is empty, or ValueError is raised

    Raises:
        - ValueError when a reference names a missing asset, or the references form a
          cycle so no fixed point exists
    """
    changed = set()
    limit   = len( collect_refs( project_root ) ) + 2
    for _ in range( limit ):
        bad = verify( project_root )
        if not bad:
            return sorted( changed )
        missing = [ b for b in bad if b[ 3 ] is None ]
        if missing:
            raise ValueError( f"reference(s) to missing asset(s): {[ ( m[ 0 ], m[ 1 ] ) for m in missing ]}" )
        for source_rel in sorted( { b[ 0 ] for b in bad } ):
            path = os.path.join( project_root, source_rel )
            with open( path, encoding="utf-8" ) as fh:
                text = fh.read()

            def _swap( match ):
                with open( static_url_to_path( project_root, match.group( 2 ) ), "rb" ) as fh:
                    fresh = content_token( fh.read() )
                return f"{match.group( 1 )}{match.group( 2 )}?v={fresh}{match.group( 1 )}"

            # A source listed by verify() has at least one stale token, so the rewrite
            # always changes it — there is no unchanged branch to guard.
            with open( path, "w", encoding="utf-8" ) as fh:
                fh.write( REF_RE.sub( _swap, text ) )
            changed.add( source_rel )
    raise ValueError( "tokens did not converge — the assets reference each other in a cycle" )


def main( argv, project_root ):
    """
    Requires: argv is the argument list without the program name
    Ensures:  prints drift (or the rewritten files) and returns the exit code:
              0 clean/stamped, 1 drift found by --check, 2 stamp could not converge
    """
    if "--stamp" in argv:
        try:
            changed = stamp( project_root )
        except ValueError as error:
            print( f"[asset-tokens] cannot stamp: {error}" )
            return 2
        print( f"[asset-tokens] rewrote {len( changed )} file(s): {changed}" )
        return 0
    bad = verify( project_root )
    for source_rel, url, found, expected in bad:
        print( f"[asset-tokens] DRIFT {source_rel} -> {url}?v={found}  expected {expected}" )
    if bad:
        print( "[asset-tokens] remedy: python -m lupin_app.asset_tokens --stamp" )
        return 1
    print( "[asset-tokens] every token matches its asset's current bytes" )
    return 0


if __name__ == "__main__":  # pragma: no cover — thin CLI shell; main() is fully tested
    import cosa.utils.util as cu
    sys.exit( main( sys.argv[ 1: ], cu.get_project_root() ) )
