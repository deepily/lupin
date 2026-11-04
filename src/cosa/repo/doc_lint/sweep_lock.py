"""
The per-package lock of the docs-rewrite sweep: one seat at a time may work a package.

The lock is a git ref, `refs/sweep-locks/<slug>`, that points at a blob holding { package, persona, session, utc }.
Git creates a ref only if none exists. It changes or deletes one only if the ref still holds the value the caller names.
So two seats cannot both take a lock, and a seat cannot release another seat's lock. Two takeovers of the same stale
lock have one winner. The store row stays the visible claim; this ref is the lock.

The lock is cooperative, not access control. Persona and session are the caller's own word, and `show` prints them.
A seat that passes the holder's identity can release or take over that holder's lock. It stops two
honest seats working one package; it does not stop a seat that lies.
"""

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone

NAMESPACE   = "refs/sweep-locks/"
ZERO_OID    = "0" * 40
STALE_AFTER = timedelta( hours=24 )
FUTURE_SKEW = timedelta( minutes=5 )
SLUG_REGEX  = re.compile( r"^[A-Za-z0-9][A-Za-z0-9._-]*$" )


def _run( root, *args, stdin=None ):
    """
    Run git in root and return ( returncode, stdout, stderr ).

    Requires:
        - root is a git working tree

    Ensures:
        - returns the exit code, the decoded stdout and the decoded stderr; never raises on a git failure

    Raises:
        - nothing
    """
    res = subprocess.run( [ "git", "-C", str( root ), *args ], input=stdin, capture_output=True, text=True, encoding="utf-8" )
    return res.returncode, res.stdout.strip(), res.stderr.strip()


def slug_of( package ):
    """
    Turn a package directory into the ref name part of its lock.

    Requires:
        - package is a str naming a directory, such as `src/cosa/repo`, with at most one trailing slash

    Ensures:
        - returns the directory names joined by a single `-`, each name with `_` written `_5f` and `-` written `_2d`
        - two different paths never share a slug: the escape leaves `-` only as the separator, so the slug can be read back
        - `src/a--b` and `src/a/b` give `src-a_2d_2db` and `src-a-b`

    Raises:
        - ValueError when a directory name is empty, `.` or `..`, which covers a leading slash, a doubled slash and a path that is empty
        - ValueError when the slug does not start with a letter or digit, holds a character a ref name should not, ends in `.` or `.lock`, or holds `..`
    """
    if package.endswith( "/" ): package = package[ : -1 ]
    names = package.split( "/" )
    if any( name in ( "", ".", ".." ) for name in names ): raise ValueError( f"package {package!r} cannot name a lock" )
    slug  = "-".join( name.replace( "_", "_5f" ).replace( "-", "_2d" ) for name in names )
    if not SLUG_REGEX.match( slug ) or ".." in slug or slug.endswith( ".lock" ) or slug.endswith( "." ):
        raise ValueError( f"package {package!r} cannot name a lock" )
    return slug


def holder_of( root, package ):
    """
    Read who holds a package's lock.

    Requires:
        - root is a git working tree

    Ensures:
        - returns { package, persona, session, utc, blob } for a held lock, None for a free one
        - blob is the object id the ref holds, which is what a release or takeover compares against

    Raises:
        - RuntimeError when the ref exists and its blob cannot be read as a lock record
    """
    ref        = NAMESPACE + slug_of( package )
    code, blob, _ = _run( root, "rev-parse", "--verify", "--quiet", ref )
    if code != 0: return None
    code, text, err = _run( root, "cat-file", "blob", blob )
    if code != 0: raise RuntimeError( f"{ref} does not point at a readable blob: {err}" )
    try:
        record = json.loads( text )
        if not isinstance( record[ "utc" ], str ) or not isinstance( record[ "persona" ], str ): raise TypeError( "utc and persona must be strings" )
    except ( ValueError, KeyError, TypeError ) as err:
        raise RuntimeError( f"{ref} holds a record that is not a lock: {type( err ).__name__}" ) from err
    return { **record, "blob": blob }


def _record_blob( root, package, persona, session, now ):
    """
    Write a lock record into the object store and return its id.

    Requires:
        - now is a timezone-aware datetime

    Ensures:
        - returns the blob id of { package, persona, session, utc }

    Raises:
        - RuntimeError when git cannot write the object
    """
    text = json.dumps( { "package": package, "persona": persona, "session": session, "utc": now.astimezone( timezone.utc ).isoformat() } )
    code, blob, err = _run( root, "hash-object", "-w", "--stdin", stdin=text )
    if code != 0: raise RuntimeError( f"git hash-object failed: {err}" )
    return blob


def take( root, package, persona, session, now=None ):
    """
    Take the lock of a package that nobody holds.

    Requires:
        - root is a git working tree; persona and session are non-empty strs

    Ensures:
        - returns ( True, holder ) when this call created the ref, holder being the new record
        - returns ( False, holder ) when a lock already exists, holder being the current one; the ref is not changed
        - of two takers at the same moment exactly one gets True

    Raises:
        - ValueError when the package cannot name a lock or persona or session is empty
        - RuntimeError when git fails for any reason other than the lock already existing
    """
    if not persona or not session: raise ValueError( "a lock needs a persona and a session" )
    ref  = NAMESPACE + slug_of( package )
    blob = _record_blob( root, package, persona, session, now or datetime.now( timezone.utc ) )
    code, _, err = _run( root, "update-ref", ref, blob, ZERO_OID )
    if code == 0: return True, holder_of( root, package )
    held = holder_of( root, package )
    if held is None: raise RuntimeError( f"git update-ref {ref} failed: {err}" )
    return False, held


def release( root, package, persona, session ):
    """
    Release a lock its holder owns.

    Requires:
        - root is a git working tree

    Ensures:
        - returns ( True, None ) when the lock was held by this persona and session and is now gone
        - returns ( False, reason ) when the lock is free, belongs to another persona or session, or changed hands during the call
        - another seat's lock is never deleted

    Raises:
        - ValueError when the package cannot name a lock
    """
    held = holder_of( root, package )
    if held is None: return False, "the lock is not held"
    if held[ "persona" ] != persona or held.get( "session" ) != session:
        return False, f"the lock is held by {held[ 'persona' ]} ({held.get( 'session' )}), not by {persona} ({session})"
    code, _, _ = _run( root, "update-ref", "-d", NAMESPACE + slug_of( package ), held[ "blob" ] )
    return ( True, None ) if code == 0 else ( False, "the lock changed hands during the release" )


def takeover( root, package, persona, session, now=None ):
    """
    Take a lock over from a holder who has had it for at least 24 hours.

    Requires:
        - root is a git working tree; persona and session are non-empty strs

    Ensures:
        - returns ( True, holder ) when this call replaced the stale holder, holder being the new record
        - a lock stamped more than five minutes in the future is stale too, since a holder's fast clock must not freeze the package
        - returns ( False, reason ) when the lock is free, younger than 24 hours, unreadable in age, or another takeover won
        - of two takeovers of one stale lock exactly one gets True, because the swap names the holder it replaces

    Raises:
        - ValueError when the package cannot name a lock or persona or session is empty
        - RuntimeError when the lock record cannot be read
    """
    if not persona or not session: raise ValueError( "a lock needs a persona and a session" )
    now  = now or datetime.now( timezone.utc )
    held = holder_of( root, package )
    if held is None: return False, "the lock is not held; take it instead"
    try:
        since = datetime.fromisoformat( held[ "utc" ] )
    except ( ValueError, TypeError ):
        return False, "the lock's time cannot be read, so it is not provably stale"
    since = since if since.tzinfo else since.replace( tzinfo=timezone.utc )
    age   = now - since
    if since - now <= FUTURE_SKEW and age < STALE_AFTER: return False, f"the lock is {age} old; a takeover needs {STALE_AFTER}"
    blob = _record_blob( root, package, persona, session, now )
    code, _, _ = _run( root, "update-ref", NAMESPACE + slug_of( package ), blob, held[ "blob" ] )
    if code != 0: return False, "another seat took the lock over first"
    return True, holder_of( root, package )


def main( argv=None, out=None ):
    """
    Command-line entry point: take, release, takeover or show a package's lock.

    Requires:
        - argv is a list of arguments, or None for sys.argv[ 1: ]

    Ensures:
        - prints one line saying what happened
        - returns 0 on success, 1 when the lock is refused (held, not yours, too young), 2 when the call could not run

    Raises:
        - nothing
    """
    out    = out if out is not None else sys.stdout
    parser = argparse.ArgumentParser( description="Per-package lock of the docs-rewrite sweep. Cooperative: --persona and --session are your own word, not checked against anything." )
    parser.add_argument( "verb", choices=( "take", "release", "takeover", "show" ) )
    parser.add_argument( "package", help="the package directory, such as src/cosa/repo" )
    parser.add_argument( "--persona", help="the seat's persona name" )
    parser.add_argument( "--session", help="the seat's session id" )
    parser.add_argument( "--repo-root", default=".", help="git working tree" )
    args = parser.parse_args( sys.argv[ 1: ] if argv is None else argv )
    try:
        if args.verb == "show":
            held = holder_of( args.repo_root, args.package )
            out.write( "free\n" if held is None else f"held by {held[ 'persona' ]} ({held.get( 'session' )}) since {held[ 'utc' ]}\n" )
            return 0
        if not args.persona or not args.session: raise ValueError( f"{args.verb} needs --persona and --session" )
        ok, detail = { "take": take, "release": release, "takeover": takeover }[ args.verb ]( args.repo_root, args.package, args.persona, args.session )
    except ( ValueError, RuntimeError ) as err:
        out.write( f"ERROR: {err}\n" )
        return 2
    if args.verb == "release": out.write( f"released {args.package}\n" if ok else f"REFUSED: {detail}\n" )
    elif ok: out.write( f"{args.verb} ok: {args.package} held by {detail[ 'persona' ]} ({detail[ 'session' ]})\n" )
    else: out.write( f"REFUSED: {_why( detail )}\n" )
    return 0 if ok else 1


def _why( detail ):
    """
    Phrase a refusal detail, a reason str or the current holder record, as one line.

    Requires:
        - detail is a str or a holder dict

    Ensures:
        - returns a str naming the holder when given a record

    Raises:
        - nothing
    """
    if isinstance( detail, dict ): return f"already held by {detail[ 'persona' ]} ({detail.get( 'session' )}) since {detail[ 'utc' ]}"
    return detail


if __name__ == "__main__":
    sys.exit( main() )
