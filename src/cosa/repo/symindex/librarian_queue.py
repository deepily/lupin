"""
Turn wiki lint findings and reuse misses into task-store rows for the librarian.

One rollup row per package carries that package's lint findings. One row per miss carries the
block that miss_record renders, and the daily tick exports those blocks. Every row shares one
correlation key, because the store accepts only keys that start with "epic:".

A create the store refuses, or one that never arrives, is not lost. It goes to a pending file
under the data root and is retried on the next run.

The store is reached through a small adapter with four callables, so tests and the tick pass
their own. The live adapter is built by librarian_tick.
"""
import hashlib
import json
import os
import re

from cosa.repo.symindex.wiki_lint import package_of

CORRELATION_KEY = "epic:wiki-librarian"
ROLLUP_PREFIX   = "[LUPIN] wiki-librarian rollup: "
MISS_PREFIX     = "[LUPIN] wiki-librarian miss: "
FINGERPRINT_TAG = "rollup-fingerprint:"
CLEARED_TAG     = "rollup-cleared:"
WIKI_PACKAGE    = "wiki"
DETAIL_LIMIT    = 25

FINGERPRINT_RE = re.compile( r"^rollup-fingerprint:\s*([0-9a-f]{40})\s*$", re.M )


def finding_package( finding ):
    """
    Name the package a finding belongs to.

    Requires:
        - finding is a dict with a "kind"

    Ensures:
        - an orphan or a package finding returns its own package
        - a stale or dangling finding returns the package of its symbol
        - an unindexed or pin-algorithm finding returns WIKI_PACKAGE
    """
    if "package" in finding: return finding[ "package" ]
    if "symbol" in finding: return package_of( finding[ "symbol" ] )
    return WIKI_PACKAGE


def group_by_package( findings ):
    """
    Group findings by package.

    Requires:
        - findings is a list of finding dicts

    Ensures:
        - returns a dict of package name to its findings, in input order
        - an empty list returns an empty dict
    """
    groups = {}
    for finding in findings: groups.setdefault( finding_package( finding ), [] ).append( finding )
    return groups


def fingerprint( findings ):
    """
    Hash a package's findings so an unchanged rollup is never amended.

    Requires:
        - findings is a list of JSON-serializable dicts

    Ensures:
        - returns a 40-character hex digest
        - the digest does not depend on the order of the findings
    """
    lines = sorted( json.dumps( f, sort_keys=True ) for f in findings )
    return hashlib.sha1( "\n".join( lines ).encode( "utf-8" ) ).hexdigest()


def _detail_line( finding ):
    """Render one finding as a short line for a rollup body."""
    parts = [ finding[ "kind" ] ]
    for key in ( "page", "symbol", "package", "count" ):
        if key in finding: parts.append( f"{key}={finding[ key ]}" )
    return "- " + " ".join( parts )


def render_rollup( package, findings ):
    """
    Build the title and body of one package rollup.

    Requires:
        - findings is a non-empty list for that package

    Ensures:
        - returns ( title, body )
        - the title is ROLLUP_PREFIX plus the package, so the row can be found again
        - the body counts findings by kind, lists at most DETAIL_LIMIT of them, and ends with the fingerprint line
    """
    counts = {}
    for finding in findings: counts[ finding[ "kind" ] ] = counts.get( finding[ "kind" ], 0 ) + 1
    shown  = [ _detail_line( f ) for f in findings[ : DETAIL_LIMIT ] ]
    more   = len( findings ) - len( shown )
    lines  = [ f"Wiki lint findings for package {package}: " + ", ".join( f"{k} {counts[ k ]}" for k in sorted( counts ) ) + "." ]
    lines += shown
    if more > 0: lines.append( f"- and {more} more" )
    lines.append( f"{FINGERPRINT_TAG} {fingerprint( findings )}" )
    return ROLLUP_PREFIX + package, "\n".join( lines )


def read_fingerprint( body ):
    """
    Read the fingerprint line from a rollup body.

    Ensures:
        - returns the digest of the last fingerprint line, or None when the body has none or is None
        - the last one wins because an amendment appends to the body and keeps the original text
    """
    found = FINGERPRINT_RE.findall( body or "" )
    return found[ -1 ] if found else None


def is_cleared( body ):
    """
    Say whether a rollup body already carries a clear notice after its last fingerprint.

    Requires:
        - body is a string or None

    Ensures:
        - returns True when the last clear notice sits after the last fingerprint line
        - a notice followed by a newer fingerprint, which means findings came back, returns False
    """
    text = body or ""
    return text.rfind( CLEARED_TAG ) > text.rfind( FINGERPRINT_TAG )


def closing_receipt( package, index_sha ):
    """
    Build the receipt a manager closes a cleared rollup with.

    Requires:
        - package and index_sha are non-empty strings

    Ensures:
        - returns a receipt_refs dict holding one manager_attestation of at most 255 characters
        - the store accepts the shape as a closing receipt, and the tick never sends it itself
    """
    return { "manager_attestation": f"wiki lint is clean for {package} at index {index_sha}"[ : 255 ] }


def clear_note( package, index_sha ):
    """
    Build the note appended to a rollup whose package has no findings left.

    Requires:
        - package and index_sha are non-empty strings

    Ensures:
        - returns text that starts with the clear tag and the index sha
        - the text names the receipt the accountable manager closes the row with
    """
    receipt = json.dumps( closing_receipt( package, index_sha ) )
    return f"{CLEARED_TAG} {index_sha}\nNo wiki lint findings remain for {package} at index {index_sha}. The accountable manager closes this row with receipt_refs {receipt}."


def read_pending( path ):
    """
    Read the pending file.

    Requires:
        - path is a file path; the file may be absent

    Ensures:
        - returns a list of entry dicts, one per readable JSON line
        - an absent file returns an empty list
        - a line that is not a JSON object is skipped
    """
    if not os.path.isfile( path ): return []
    entries = []
    with open( path, encoding="utf-8" ) as handle:
        for line in handle:
            try: entry = json.loads( line )
            except ValueError: continue
            if isinstance( entry, dict ): entries.append( entry )
    return entries


def write_pending( path, entries ):
    """
    Replace the pending file.

    Requires:
        - entries is a list of JSON-serializable dicts

    Ensures:
        - the file is written to a temporary name and renamed, so a reader never sees half of it
        - an empty list removes the file
    """
    if not entries:
        if os.path.isfile( path ): os.remove( path )
        return
    os.makedirs( os.path.dirname( path ), exist_ok=True )
    temp = path + ".tmp"
    with open( temp, "w", encoding="utf-8" ) as handle:
        for entry in entries: handle.write( json.dumps( entry, sort_keys=True ) + "\n" )
    os.replace( temp, path )


class Librarian:
    """
    Keep the store's wiki-librarian rows in step with the lint findings.

    Requires:
        - store is an object with query( correlation_key ), create( payload ) and amend( item_id, note )
        - query returns the open and held rows; each call returns ( ok, status, body ) and never raises
        - log is a callable taking one line
        - pending_path is where refused creates are kept
    """

    def __init__( self, store, pending_path, log, notify=None, project="lupin", owner="cheech", manager="cheech", priority="P5", max_creates=None ):
        """
        Keep the store, the pending path and the row settings.

        Ensures:
            - owner is the persona that does the librarian's work and manager is the one that chases and closes the rows
            - max_creates caps the create calls one sync may make, or None for no cap
        """
        self.max_creates  = max_creates
        self._budget      = None
        self._refused     = 0
        self.store        = store
        self.pending_path = pending_path
        self.log          = log
        self.notify       = notify
        self.project      = project
        self.owner        = owner
        self.manager      = manager
        self.priority     = priority

    def _payload( self, title, body ):
        """Build the create payload for one row."""
        return { "item_class": "task", "title": title, "body": body, "project": self.project, "owner_persona": self.owner,
                 "accountable_manager": self.manager, "priority": self.priority, "correlation_key": CORRELATION_KEY }

    def _existing( self ):
        """
        Read the open and held wiki-librarian rows.

        Ensures:
            - returns a dict of title to row
            - raises RuntimeError when the store could not be read, so a failed read is never taken for no rows
        """
        ok, status, body = self.store.query( CORRELATION_KEY )
        if not ok: raise RuntimeError( f"task store query failed: status {status}: {body}" )
        return { row[ "title" ]: row for row in body.get( "tasks", [] ) }

    def _take( self ):
        """
        Spend one create from this sync's budget.

        Ensures:
            - returns True when a create may be made, False when the budget is spent
            - with no cap it always returns True
        """
        if self._budget is None: return True
        if self._budget <= 0: return False
        self._budget -= 1
        return True

    def _create_or_hold( self, title, body, held ):
        """
        Create a row, or hold it in the pending list when the store does not take it.

        Ensures:
            - returns "created" when the store accepted it
            - otherwise appends one entry to held, once per title, and returns "pending"
        """
        ok, status, reply = self.store.create( self._payload( title, body ) )
        if ok: return "created"
        self._refused += 1
        self.log( f"create held: {title}: status {status}: {reply}" )
        if all( entry[ "title" ] != title for entry in held ): held.append( { "title": title, "body": body, "status": status } )
        return "pending"

    def sync( self, findings, index_sha ):
        """
        Bring the rollup rows in step with the findings, after retrying the pending creates.

        Requires:
            - findings is the list wiki_lint.queue returned
            - index_sha names the index the findings came from

        Ensures:
            - returns a dict of counts: created, amended, unchanged, cleared, waiting, deferred, pending
            - no more than max_creates create calls are made, pending retries first; a refused attempt counts
            - a rollup the cap kept back is counted as deferred and is derived again on the next run
            - a pending entry the cap kept back stays in the pending file untouched
            - a package with findings and no row gets one row; a changed fingerprint gets one amendment
            - a rollup whose package has no findings is amended once with a clear notice and is never closed here
            - a rollup that already carries its clear notice is counted as waiting
            - the manager is notified once about refused creates and once about newly cleared rollups
            - a run that finds rollups still waiting for their close notifies the manager again, so a daily run tells once a day
            - a notice the notifier reports as not delivered is logged
            - miss rows are never amended here
            - refused creates are written to the pending file before this returns
            - raises RuntimeError when the store could not be read, leaving the pending file as it was
        """
        existing = self._existing()
        counts   = { "created": 0, "amended": 0, "unchanged": 0, "cleared": 0, "waiting": 0, "deferred": 0, "pending": 0 }
        held     = []
        made     = set()
        cleared  = []
        self._budget  = self.max_creates
        self._refused = 0
        for entry in read_pending( self.pending_path ):
            if entry[ "title" ] in existing: continue
            if not self._take():
                held.append( entry )
                counts[ "deferred" ] += 1
                continue
            if self._create_or_hold( entry[ "title" ], entry[ "body" ], held ) == "created":
                counts[ "created" ] += 1
                made.add( entry[ "title" ] )
        wanted = {}
        for package, group in sorted( group_by_package( findings ).items() ):
            title, body = render_rollup( package, group )
            wanted[ title ] = body
        for title, body in wanted.items():
            row = existing.get( title )
            if title in made: continue
            if row is None:
                if any( entry[ "title" ] == title for entry in held ): continue
                if not self._take(): counts[ "deferred" ] += 1
                elif self._create_or_hold( title, body, held ) == "created": counts[ "created" ] += 1
            elif read_fingerprint( row.get( "body" ) ) == read_fingerprint( body ) and not is_cleared( row.get( "body" ) ): counts[ "unchanged" ] += 1
            else:
                ok, status, reply = self.store.amend( row[ "id" ], body )
                if ok: counts[ "amended" ] += 1
                else: self.log( f"amend failed: {title}: status {status}: {reply}" )
        for title, row in existing.items():
            if not title.startswith( ROLLUP_PREFIX ) or title in wanted: continue
            if is_cleared( row.get( "body" ) ):
                counts[ "waiting" ] += 1
                continue
            ok, status, reply = self.store.amend( row[ "id" ], clear_note( title[ len( ROLLUP_PREFIX ): ], index_sha ) )
            if ok:
                counts[ "cleared" ] += 1
                cleared.append( title )
            else: self.log( f"clear notice failed: {title}: status {status}: {reply}" )
        write_pending( self.pending_path, held )
        counts[ "pending" ] = len( held )
        if self._refused: self._tell( f"{len( held )} wiki-librarian rows were not created and are pending" )
        if cleared: self._tell( f"{len( cleared )} wiki-librarian rollups are clear; close each with a manager_attestation receipt" )
        if counts[ "waiting" ]: self._tell( f"{counts[ 'waiting' ]} wiki-librarian rollup(s) are still clear and wait for a manager_attestation close" )
        return counts

    def _tell( self, text ):
        """Send one notice to the manager and log it when it was not delivered."""
        if self.notify is not None and self.notify( text ) is False: self.log( f"manager notice failed: {text}" )

    def hold_or_create( self, title, body ):
        """
        Create one row, or hold it pending, unless a row with that title is open.

        Requires:
            - title and body are strings

        Ensures:
            - returns "exists" when a row with that title is already open, "created", or "pending"
            - a held row is added to the pending file, once per title
            - the create cap does not apply
        """
        if title in self._existing(): return "exists"
        held   = read_pending( self.pending_path )
        result = self._create_or_hold( title, body, held )
        if result == "pending": write_pending( self.pending_path, held )
        return result
