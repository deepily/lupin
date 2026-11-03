"""
File one store row for each duplicate the daily check finds, once per definition text.

A row goes to the manager of the seat that wrote the function. The store key is the definition id and its content hash.
It holds no date. So a repeat run, a run on the next day and a run that failed before it advanced file no second row.
A row the store did not take, or the ratio gate refused, waits in a spool file. It is tried first next run.
"""
import hashlib
import json
import pathlib

from cosa.agents.heartbeat_arbiter import manager_resolver
from lupin_mcp.persona_normalization import canonical_persona_key

KEY_PREFIX    = "epic:dupcheck-"
KEY_HEX       = 16
CREATED_BY    = "duplicate-check-daily"
PROJECT       = "lupin"
PRIORITY      = "P5"
ITEM_CLASS    = "task"
PENDING_FILE  = "pending-rows.jsonl"
GATED_PHRASE  = "New tickets are gated"          # how the store's ratio gate opens its refusal; the filing keeps such a row and tries again
RUNG_LINEAGE  = "lineage"
RUNG_DECLARED = "declared"
RUNG_NONE     = "unresolved"
FILED         = "filed"
ALREADY       = "already_filed"
QUEUED        = "queued_for_retry"
REFUSED       = "refused"


def content_hash( text ):
    """Ensures: returns the sha256 hex digest of the definition's text."""
    return hashlib.sha256( text.encode( "utf-8" ) ).hexdigest()


def correlation_key( definition_id, text ):
    """
    Give the store key that makes one row per definition text.

    Ensures:
        - returns "epic:dupcheck-" and the first 16 hex digits of the sha256 of the definition id, a colon and the text's content hash
        - the key holds no date, and it matches the store's epic key pattern
    """
    return KEY_PREFIX + hashlib.sha256( f"{definition_id}:{content_hash( text )}".encode( "utf-8" ) ).hexdigest()[ :KEY_HEX ]


def for_record( finding ):
    """
    Shrink a finding to what the result file keeps.

    Requires:
        - finding is { id, name, file, line, text, session_id, others, window }, plus any other keys
    Ensures:
        - returns a copy without the definition's text and with its correlation_key, so the file can be refiled with no source to hand
        - the key is the one correlation_key gives the id and the text, so a refiled row has the key of the original
    """
    return { **{ k: v for k, v in finding.items() if k != "text" }, "correlation_key": correlation_key( finding[ "id" ], finding[ "text" ] ) }


def manager_for( session_id, declared, roster, resolve=manager_resolver.resolve_manager ):
    """
    Find the manager a finding goes to, and say which rung found them.

    Requires:
        - session_id is the writing seat's session id, or None when it is not known
        - declared is the configured manager on duty; roster is the declared manager names of the project
    Ensures:
        - returns { manager, rung, note }: the rung is lineage when the seat's spawn lineage names a manager, declared when the bridge is gone and the configured manager is on the roster, else unresolved
        - an unresolved finding still goes to the configured manager, with a note saying so, so no row is ownerless
        - the configured manager is tested against the roster, because the resolver never checks it
    """
    if session_id is not None:
        found = resolve( session_id, declared_manager=declared )
        if found[ "source" ] == RUNG_LINEAGE: return { "manager": found[ "manager_persona" ], "rung": RUNG_LINEAGE, "note": "manager found from the seat's spawn lineage" }
        if found[ "source" ] == RUNG_DECLARED and canonical_persona_key( declared ) in { canonical_persona_key( n ) for n in roster }:
            return { "manager": declared, "rung": RUNG_DECLARED, "note": "the seat's bridge is gone; the configured manager on duty is on the roster" }
    return { "manager": declared, "rung": RUNG_NONE, "note": "manager unresolved" }


def row_payload( finding, found ):
    """
    Build the store row of one finding.

    Requires:
        - finding is { id, name, file, line, text, session_id, others, window }; others are { id, name, file } of the definitions it duplicates
        - a finding that holds a correlation_key (for_record's) needs no text
        - found is manager_for's answer
    Ensures:
        - returns a TaskCreateIn payload at P5 with no status, so the store's holding default applies and a manager raises it
        - created_by is the job's fixed name and carries no session id, so the store reads the caller as a worker, not a manager
        - owner_persona and accountable_manager are the manager found, and the body names the rung used
    """
    key    = finding[ "correlation_key" ] if "correlation_key" in finding else correlation_key( finding[ "id" ], finding[ "text" ] )
    others = "\n".join( f"- {o['name']} in {o['file']} ({o['id']})" for o in finding[ "others" ] )
    body   = ( f"The daily duplicate check judged {finding['name']} ({finding['file']}:{finding['line']}, {finding['id']}) a duplicate of:\n{others}\n\n"
               f"Window: {finding['window']['start']}..{finding['window']['end']}. Manager: {found['manager']} ({found['rung']}: {found['note']}).\n"
               f"Correlation: one row per definition text, key {key}." )
    return { "item_class": ITEM_CLASS, "title": f"Duplicate: {finding['name']} in {finding['file']} repeats {len( finding['others'] )} existing definition(s)",
             "project": PROJECT, "created_by": CREATED_BY, "body": body, "owner_persona": found[ "manager" ], "accountable_manager": found[ "manager" ],
             "priority": PRIORITY, "correlation_key": key }


def read_pending( folder ):
    """Ensures: returns the spooled payloads, oldest first, or an empty list."""
    path = pathlib.Path( folder ) / PENDING_FILE
    return [ json.loads( line ) for line in path.read_text( encoding="utf-8" ).splitlines() if line.strip() ] if path.exists() else []


def write_pending( folder, payloads ):
    """Ensures: the spool holds exactly these payloads; an empty list removes the file."""
    path = pathlib.Path( folder ) / PENDING_FILE
    if not payloads:
        path.unlink( missing_ok=True )
        return
    path.parent.mkdir( parents=True, exist_ok=True )
    path.write_text( "".join( json.dumps( p, sort_keys=True ) + "\n" for p in payloads ), encoding="utf-8" )


def send_row( payload, store ):
    """
    Put one row in the store unless its key is already there.

    Requires:
        - store has query( correlation_key ) and create( payload ), each returning ( ok, status, body ) and never raising
    Ensures:
        - returns { outcome, status }: already_filed when the key has a row, filed on a 201, queued_for_retry on a transport failure or a ratio gate refusal, refused on any other verdict
        - a transport failure on the probe queues the row, because a row filed twice is worse than one filed late
    """
    ok, status, body = store.query( payload[ "correlation_key" ] )
    if status is None: return { "outcome": QUEUED, "status": None }
    if ok and body.get( "count", 0 ) > 0: return { "outcome": ALREADY, "status": status }
    ok, status, body = store.create( payload )
    if ok: return { "outcome": FILED, "status": status }
    if status is None or ( status == 422 and GATED_PHRASE in str( body.get( "error", "" ) ) ): return { "outcome": QUEUED, "status": status }
    return { "outcome": REFUSED, "status": status, "detail": str( body )[ :300 ] }


def file_findings( findings, folder, store, declared, roster, resolve=manager_resolver.resolve_manager ):
    """
    File the rows of a run's findings, the spooled ones first.

    Requires:
        - findings are row_payload's findings; folder is the daily check's record folder
    Ensures:
        - returns { filed, already_filed, queued_for_retry, refused } as lists of { key, ... }, the keys of every row this call handled
        - a spooled row is tried before any new one; the spool afterwards holds only the rows still queued
        - a new finding whose key is already spooled is not spooled twice
    """
    out     = { FILED: [], ALREADY: [], QUEUED: [], REFUSED: [] }
    waiting = []
    fresh   = [ row_payload( f, manager_for( f[ "session_id" ], declared, roster, resolve ) ) for f in findings ]
    held    = { p[ "correlation_key" ] for p in read_pending( folder ) }
    for payload in [ *read_pending( folder ), *[ p for p in fresh if p[ "correlation_key" ] not in held ] ]:
        sent = send_row( payload, store )
        out[ sent[ "outcome" ] ].append( { "key": payload[ "correlation_key" ], **{ k: v for k, v in sent.items() if k != "outcome" } } )
        if sent[ "outcome" ] == QUEUED: waiting.append( payload )
    write_pending( folder, waiting )
    return out


class LiveStore:
    """The store over HTTP with the hooks' own client, needing no MCP session."""

    def __init__( self, settings=None, api_key=None ):
        from lupin_cli.claude_code.hooks.lib import task_store_client as client, task_store_settings
        self.client   = client
        self.settings = task_store_settings.load_task_store_settings() if settings is None else settings
        self.api_key  = client.read_api_key() if api_key is None else api_key

    def query( self, key ):
        """Ensures: returns ( ok, status, body ) of the correlation key probe; never raises."""
        return self.client.query_by_correlation_key( self.settings, self.api_key, key )

    def create( self, payload ):
        """Ensures: returns ( ok, status, body ) of the create; never raises."""
        return self.client.create_task( self.settings, self.api_key, payload )
