"""
File one triage row for a run of the daily check, listing the duplicates it found.

The row goes to a persona on the project's manager roster, never to a role label.
A finding carries a key made of its definition id and its content hash, with no date.
The triaged file keeps the keys already on a row. So a repeat run, a run on the next day and a run that failed before it advanced list no finding twice.
A row the store did not take, or the ratio gate refused, waits in a spool file. It is tried first next run.
"""
import datetime
import hashlib
import json
import pathlib

from cosa.repo.symindex import librarian_queue as lq
from cosa.repo.symindex.task_store_adapter import TaskStoreAdapter
from cosa.rest.task_store_rules import filer_created_by
from cosa.utils import secret_drift
from cosa.utils.jsonl_file import read_jsonl
from lupin_mcp.persona_normalization import canonical_persona_key

KEY_PREFIX     = "epic:dupcheck-"
KEY_HEX        = 16
CREATED_BY     = "duplicate-check-daily"
PROJECT        = "lupin"
PRIORITY       = "P5"
ITEM_CLASS     = "task"
PENDING_FILE   = "pending-rows.jsonl"
AMEND_REASON   = "daily duplicate check verdict line"
GATED_PHRASE   = "New tickets are gated"          # how the store's ratio gate opens its refusal; the filing keeps such a row and tries again
RUN_KEY_PREFIX = "epic:dupcheck-run-"
TRIAGED_FILE   = "triaged.jsonl"
LIST_LIMIT     = 200                              # findings named in a row's body; the rest are named by count and result file
OTHERS_LIMIT   = 5                                # definitions named after "repeats:" on one finding; the rest are counted
BODY_LIMIT     = 30000                            # characters a row's body may carry; the store sets no limit (body is a Text column), so this is our own, chosen to keep the row readable
DETAIL_LIMIT   = 300                              # characters of the store's answer kept on a refused or queued outcome
FILED          = "filed"
ALREADY        = "already_filed"
QUEUED         = "queued_for_retry"
REFUSED        = "refused"
RETIRED        = "retired_shape"
OVERSIZE       = "oversize_body"


def correlation_key( definition_id, text ):
    """
    Give the store key that makes one row per definition text.

    Ensures:
        - returns "epic:dupcheck-" and the first 16 hex digits of the sha256 of the definition id, a colon and the text's content hash
        - the key holds no date, and it matches the store's epic key pattern
    """
    return KEY_PREFIX + hashlib.sha256( f"{definition_id}:{secret_drift.sha256_of( text )}".encode( "utf-8" ) ).hexdigest()[ :KEY_HEX ]


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


class NoTriageOwner( ValueError ):
    """The project's manager roster is empty, so no persona can own the triage row."""


def triage_owner( declared, roster ):
    """
    Pick the persona that owns a run's triage row.

    Requires:
        - declared is the configured duplicate-check triage owner, a persona name; roster is the declared manager names of the project
    Ensures:
        - returns { owner, note }: owner is the lowercase persona key of the roster entry that matches declared, whatever the case or accent
    Raises:
        - NoTriageOwner when the roster is empty, or when declared is blank, a role label or any name not on the roster; the filer never guesses an owner, so a row cannot land on a seat of another project
    """
    names = [ n for n in roster if n ]
    if not names: raise NoTriageOwner( f"no manager on the roster to own the triage row (configured triage owner: {declared!r})" )
    match = [ n for n in names if canonical_persona_key( declared ) and canonical_persona_key( n ) == canonical_persona_key( declared ) ]
    if not match: raise NoTriageOwner( f"the configured triage owner, {declared!r}, is not a persona on the {PROJECT} manager roster {names!r}; set 'duplicate check triage owner' to one of them" )
    return { "owner": canonical_persona_key( match[ 0 ] ), "note": f"the configured triage owner, {declared}, is on the roster" }


def run_key( finding_keys ):
    """
    Give the store key of a run's triage row.

    Ensures:
        - returns RUN_KEY_PREFIX and 16 hex digits of the sha256 of the sorted finding keys
        - so the same findings always have the same row key
    """
    return RUN_KEY_PREFIX + hashlib.sha256( "\n".join( sorted( finding_keys ) ).encode( "utf-8" ) ).hexdigest()[ :KEY_HEX ]


def triage_payload( findings, owner, day ):
    """
    Build the one store row of a run.

    Requires:
        - findings are { id, name, file, line, others, window } plus correlation_key or text; there is at least one
        - owner is triage_owner's answer; day is a date
    Ensures:
        - returns a TaskCreateIn payload at P5 with no status, so the store's holding default applies and a manager raises it
        - the title starts with the project tag, names the check, the day and the question to answer
        - the body says why the row exists, what to do, the owner and the first LIST_LIMIT findings with the definitions they repeat
        - each finding names at most OTHERS_LIMIT of the definitions it repeats and counts the rest
        - the rest are counted in a last line naming the result file, the first finding's run_file; the title counts every finding
        - finding_keys always lists every finding, so none is lost from the triaged file
        - created_by is "<owner persona> (<job name>)", so the row is filed by a persona; it carries no session id, so the store reads the caller as a worker, not a manager
        - owner_persona and accountable_manager are the owner's persona key
        - finding_keys lists the findings' keys so the filer can mark them triaged; send_row's caller removes it before the create
    """
    keys  = [ f[ "correlation_key" ] if "correlation_key" in f else correlation_key( f[ "id" ], f[ "text" ] ) for f in findings ]
    count = len( findings )
    lines = [ f"- {f['name']} ({f['file']}:{f['line']}, {f['id']}) repeats: " + "; ".join( f"{o['name']} in {o['file']}" for o in f[ "others" ][ :OTHERS_LIMIT ] )
              + ( f"; and {len( f[ 'others' ] ) - OTHERS_LIMIT} more" if len( f[ "others" ] ) > OTHERS_LIMIT else "" ) for f in findings[ :LIST_LIMIT ] ]
    if count > LIST_LIMIT: lines.append( f"- and {count - LIST_LIMIT} more in {findings[ 0 ].get( 'run_file', 'the result file' )}" )
    key   = run_key( keys )
    body  = ( f"Why this row exists: the daily duplicate check found {count} new function(s) that repeat code the tree already has.\n"
              f"What to do: for each function below, rule duplicate (reuse the existing one), extend (change the existing one) or distinct (keep both). "
              f"Write one DUPCHECK-VERDICT line per function with lupin_mcp.duplicate_check_verdicts; it amends this row.\n"
              f"Window: {findings[ 0 ][ 'window' ][ 'start' ]}..{findings[ 0 ][ 'window' ][ 'end' ]}. Owner: {owner[ 'owner' ]} ({owner[ 'note' ]}).\n"
              f"Correlation: one row per batch of findings, key {key}; a function already on an earlier row is not listed again.\n\n" + "\n".join( lines ) )
    return { "item_class": ITEM_CLASS, "title": f"[LUPIN] Duplicate check {day.day} {day.strftime( '%b' )}: decide whether {count} new function(s) should reuse existing ones",
             "project": PROJECT, "created_by": filer_created_by( owner[ "owner" ], CREATED_BY ), "body": body, "owner_persona": owner[ "owner" ], "accountable_manager": owner[ "owner" ],
             "priority": PRIORITY, "correlation_key": key, "finding_keys": keys }


def triage_payloads( findings, owner, day ):
    """
    Build the rows of a run, each small enough to list all of its findings.

    Requires:
        - findings and owner are triage_payload's; there is at least one finding
    Ensures:
        - returns a list of triage_payload rows, in the findings' order, each listing every one of its findings, with a body of at most BODY_LIMIT characters and at most LIST_LIMIT findings
        - every finding is in exactly one row, and a row's finding_keys are the keys of its own findings only
        - a finding whose line alone passes the limit has a row of its own, which send_row then cuts
        - with more than one row each title ends with its part and the count of parts
    """
    parts, chunk = [], []
    for f in findings:
        if chunk and ( len( chunk ) + 1 > LIST_LIMIT or len( triage_payload( [ *chunk, f ], owner, day )[ "body" ] ) > BODY_LIMIT ):
            parts.append( chunk )
            chunk = []
        chunk.append( f )
    parts.append( chunk )
    rows = [ triage_payload( c, owner, day ) for c in parts ]
    if len( rows ) > 1:
        for n, row in enumerate( rows, 1 ): row[ "title" ] += f" (part {n} of {len( rows )})"
    return rows


def read_pending( folder ):
    """Ensures: returns the spooled payloads, oldest first, or an empty list."""
    return read_jsonl( pathlib.Path( folder ) / PENDING_FILE, missing_ok=True )


def write_pending( folder, payloads ):
    """Ensures: the spool holds exactly these payloads, written atomically; none removes it."""
    lq.write_pending( str( pathlib.Path( folder ) / PENDING_FILE ), payloads )


def gated( body ):
    """
    Say whether a store answer is the ratio gate's refusal.

    Requires:
        - body is the dict a store client returns for a refusal
    Ensures:
        - returns True when GATED_PHRASE is in the body's `detail`, where the store puts a 422's text, or in its `error`, where the client wraps a body that is not an object
        - the test is on the text of the value, so a `detail` list or dict whose text holds the phrase counts, and one that does not hold it does not
        - returns False for any other body
    """
    return any( GATED_PHRASE in str( body.get( key, "" ) ) for key in ( "detail", "error" ) )


def fit_body( body, limit=BODY_LIMIT ):
    """
    Cut a row's body to a character limit at a line boundary, and say so.

    Requires:
        - body is a string; limit is a positive integer
    Ensures:
        - returns body unchanged when it holds no more than limit characters
        - otherwise returns whole lines of the body, then a last line that counts the omitted characters and names the result file as the place for the rest
        - the returned text is never longer than limit characters
    """
    if len( body ) <= limit: return body
    note = "\n- body cut: {n} characters left out; the full list is in the run's result file"
    room = limit - len( note.format( n=len( body ) ) )
    kept = body[ :room ].rsplit( "\n", 1 )[ 0 ] if "\n" in body[ :room ] else body[ :room ]
    return kept + note.format( n=len( body ) - len( kept ) )


def send_row( payload, store ):
    """
    Put one row in the store unless its key is already there.

    Requires:
        - store has query( correlation_key ) and create( payload ), each returning ( ok, status, body ) and never raising
    Ensures:
        - returns { outcome, status }: already_filed when the key has a row, filed on a 201, queued_for_retry on a transport failure or a ratio gate refusal (see gated), refused on any other verdict
        - a probe that did not answer ok, whatever the cause, queues the row, because a row filed twice is worse than one filed late
        - the body sent never exceeds BODY_LIMIT characters, whether the payload is new or was spooled by an earlier run
        - a queued or refused outcome keeps the first DETAIL_LIMIT characters of the store's answer as detail, so the cause is on record
    """
    payload = { **payload, "body": fit_body( payload[ "body" ] ) } if "body" in payload and payload[ "body" ] is not None else payload
    ok, status, body = store.query( payload[ "correlation_key" ] )
    if not ok: return { "outcome": QUEUED, "status": status, "detail": str( body )[ :DETAIL_LIMIT ] }
    if body.get( "count", 0 ) > 0: return { "outcome": ALREADY, "status": status }
    ok, status, body = store.create( payload )
    if ok: return { "outcome": FILED, "status": status }
    if status is None or ( status == 422 and gated( body ) ): return { "outcome": QUEUED, "status": status, "detail": str( body )[ :DETAIL_LIMIT ] }
    return { "outcome": REFUSED, "status": status, "detail": str( body )[ :DETAIL_LIMIT ] }


def read_triaged( folder ):
    """Ensures: returns the set of finding keys already on a triage row, or an empty set."""
    return { row[ "key" ] for row in read_jsonl( pathlib.Path( folder ) / TRIAGED_FILE, missing_ok=True ) }


def append_triaged( folder, keys, row_key, day ):
    """Ensures: appends one line a key to the triaged file; earlier lines are kept."""
    path = pathlib.Path( folder ) / TRIAGED_FILE
    path.parent.mkdir( parents=True, exist_ok=True )
    with path.open( "a", encoding="utf-8" ) as fh:
        for key in keys: fh.write( json.dumps( { "key": key, "row_key": row_key, "day": day.isoformat() }, sort_keys=True ) + "\n" )


def file_findings( findings, folder, store, declared, roster, day=None ):
    """
    File the run's triage rows, the spooled rows first.

    Requires:
        - findings are triage_payload's findings; folder is the daily check's record folder
        - day is the date for the title; None takes the first finding's day field, an ISO date, else today
    Ensures:
        - returns { filed, already_filed, queued_for_retry, refused, retired_shape, oversize_body } as lists of { key, ... }, one entry for each row this run builds and one for each spooled row
        - a spooled payload with no finding_keys is in the retired one-row-per-definition shape: it is never sent, it is listed under retired_shape with its key and owner, and it stays in the spool for a person to remove
        - a finding already on an earlier triage row, or on a spooled one, is left out; with none left no row is filed
        - a spooled row whose body is over BODY_LIMIT is never sent: it is listed under oversize_body with its key, size and finding count, it stays in the spool for a person to remove, and its findings are not counted as seen, so a run that is given them files them again in rows under the limit
        - the findings go in as many rows as it takes for each row to list all of its findings under the body limit
        - a spooled row is tried before the new ones; the spool afterwards holds only the rows still queued
        - only the findings of a row the store took, or already held, are written to the triaged file; the findings of a queued row stay unmarked in its spooled payload
    Raises:
        - NoTriageOwner when there are findings to file and the owner is not on the roster, before anything is sent
    """
    if day is None: day = datetime.date.fromisoformat( findings[ 0 ][ "day" ] ) if findings and "day" in findings[ 0 ] else datetime.date.today()
    out     = { FILED: [], ALREADY: [], QUEUED: [], REFUSED: [], RETIRED: [], OVERSIZE: [] }
    spooled = read_pending( folder )
    retired = [ p for p in spooled if "finding_keys" not in p ]
    out[ RETIRED ] = [ { "key": p.get( "correlation_key" ), "owner": p.get( "owner_persona" ) } for p in retired ]
    waiting = list( retired )
    spooled = [ p for p in spooled if "finding_keys" in p ]
    over    = [ p for p in spooled if len( p.get( "body" ) or "" ) > BODY_LIMIT ]
    out[ OVERSIZE ] = [ { "key": p[ "correlation_key" ], "characters": len( p[ "body" ] ), "findings": len( p[ "finding_keys" ] ) } for p in over ]
    waiting.extend( over )
    spooled = [ p for p in spooled if p not in over ]
    seen    = read_triaged( folder ) | { k for p in spooled for k in p.get( "finding_keys", [] ) }
    fresh   = [ f for f in findings if ( f[ "correlation_key" ] if "correlation_key" in f else correlation_key( f[ "id" ], f[ "text" ] ) ) not in seen ]
    todo    = [ *spooled, *( triage_payloads( fresh, triage_owner( declared, roster ), day ) if fresh else [] ) ]
    for payload in todo:
        keys = payload.get( "finding_keys", [] )
        sent = send_row( { k: v for k, v in payload.items() if k != "finding_keys" }, store )
        out[ sent[ "outcome" ] ].append( { "key": payload[ "correlation_key" ], **{ k: v for k, v in sent.items() if k != "outcome" } } )
        if sent[ "outcome" ] == QUEUED: waiting.append( payload )
        if sent[ "outcome" ] in ( FILED, ALREADY ): append_triaged( folder, keys, payload[ "correlation_key" ], day )
    write_pending( folder, waiting )
    return out


class LiveStore( TaskStoreAdapter ):
    """The store over HTTP with the hooks' own client, needing no MCP session."""

    amend_extra = { "reason": AMEND_REASON, "authority": "standing" }

    def __init__( self, settings=None, api_key=None ):
        from lupin_cli.claude_code.hooks.lib import task_store_client as client, task_store_settings
        super().__init__( task_store_settings.load_task_store_settings() if settings is None else settings,
                          client.read_api_key() if api_key is None else api_key, client )

    def query( self, key ):
        """
        Look for any row that carries the correlation key, whatever its state.

        Ensures:
            - returns ( ok, status, body ) of one read that asks for every state, held rows included
            - every row this job files is held, so a plain read never sees its own earlier rows
            - never raises
        """
        return self.client.query_by_correlation_key( self.settings, self.api_key, key, every_state=True )
