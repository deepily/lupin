"""
The lean podcast proxy, server side: the door check for a document a seat names.

A seat asks for a podcast of a document on Rick's behalf. It names the document in the doc
viewer's form, `<scope>/<path within scope>`, for example `lupin/io/tmp/summary.md`. The fleet
tool turns a host path into that form on the host. The server never sees a host path and never
trusts one.

This module resolves the form through the server's own scope registry. It judges the file with
the doc viewer's whole read check, not a copy of its rule.

The check runs in this order:

- shape: a non-blank string in the form scope/path.
- the viewer: `_resolve_scoped` applies the floor blocklist, the scope whitelist, the per-scope
  patterns, and judges the path again where a link lands.
- the handle: `_open_judged_file` opens the file first and judges the open handle. A link swapped
  in after the check cannot redirect the read.
- the content: the viewer's credential decision runs on the whole text, read once from that
  same handle, and the same bytes are measured and hashed.
- the kind: a text extension a podcast script can use.

Every refusal is a `DoorRefusal` whose message names the path as the caller sent it.

A hard link to a file outside the scope is accepted: it is the same file, so no path check can tell.
The seat could already read that file as the same user.
"""

import hashlib
import os
import shutil
import uuid

from fastapi import HTTPException

from cosa.rest import task_promotion_gate as promotion_gate
from cosa.rest.routers._pinned_open import landed_path_of_fd
from cosa.rest.routers._scope_registry import _prefix_looks_like_credential, landed_relative_path
from cosa.rest.v2.source_document import ALLOWED_SOURCE_EXTENSIONS

_READ_CHUNK = 1024 * 1024

# The longest file a podcast will take. Past it the door refuses, because the whole file is held in memory.
MAX_BYTES = 8 * 1024 * 1024

# The two words that mark a card as this feature's. The server writes both; the start door reads them back.
CARD_KIND = "podcast_proxy_start"
COMMAND   = "agent router go to podcast generator"

# How long a yes stays good, and how long the card waits for an answer. The INI key overrides it.
MAX_AGE_KEY     = "podcast proxy card max age seconds"
MAX_AGE_DEFAULT = 900


class DoorRefusal( Exception ):
    """
    A podcast request the door refuses.

    `code` is the machine-readable word a client matches on: bad_path, not_found, viewer_refused,
    wrong_kind, too_large, credential or unreadable. `message` is the sentence a person reads.
    """

    def __init__( self, code, message ):
        super().__init__( message )
        self.code, self.message = code, message


def refusal_detail( code, message ):
    """The body every refusal carries: { code, message }. Clients match on the code."""
    return { "code": code, "message": message }


def _viewer_refusal( sent, refusal ):
    """The DoorRefusal for a viewer refusal: not_found for a 404, otherwise viewer_refused."""
    code = "not_found" if refusal.status_code == 404 else "viewer_refused"
    return DoorRefusal( code, f"'{sent}' was refused: {refusal.detail}." )


def _viewer():
    """
    The doc viewer's check functions, imported when first used.

    Importing the router module at load time would pull the web application into every importer.
    So the import waits for the first call.
    """
    from cosa.rest.routers import docs_files
    return docs_files


def _read_whole( fd ):
    """
    Read the whole file behind an open descriptor, once, refusing one past MAX_BYTES.

    Requires:
        - fd is an open descriptor for a regular file

    Ensures:
        - returns the bytes; raises DoorRefusal when the file is longer than MAX_BYTES
    """
    chunks, total = [ ], 0
    while True:
        chunk = os.read( fd, _READ_CHUNK )
        if not chunk: break
        total += len( chunk )
        if total > MAX_BYTES: raise DoorRefusal( "too_large", f"The file is longer than {MAX_BYTES // ( 1024 * 1024 )} MiB, which is too long for a podcast." )
        chunks.append( chunk )
    return b"".join( chunks )


def check_source( scope_path, registry=None, keep_content=False ):
    """
    Judge a document a seat named, and describe it, or refuse.

    Requires:
        - scope_path is whatever the caller sent
        - registry, when given, maps scope name -> ScopeConfig; None means the server's own registry

    Ensures:
        - returns { scope, rel, name, server_path, size, sha256 } for a file that passed every guard
          in the module docstring; rel and server_path are where the opened file really lives
        - the file is read once, from the judged handle: the same bytes are judged for credential
          material, measured, hashed and, when keep_content is True, returned under "content"
        - the whole text is judged, not the viewer's first window, because a podcast sends all of it out
        - raises DoorRefusal, naming the path as sent, for a blank or malformed path, an unknown
          scope, a path the viewer's whitelist or blocklist refuses, a link that lands outside the
          scope, a missing file, a folder, an unreadable file, a file past MAX_BYTES, credential
          content and an extension a podcast cannot read, judged on the file the path lands on
        - the opened handle is closed on every path out
        - nothing here trusts a host path: the caller's text is only the key into the registry

    Raises:
        - DoorRefusal
    """
    if not isinstance( scope_path, str ) or not scope_path.strip():
        raise DoorRefusal( "bad_path", "A podcast needs a document path in the form <scope>/<path>, and none was given." )
    sent = scope_path.strip()
    if "/" not in sent.lstrip( "/" ):
        raise DoorRefusal( "bad_path", f"'{sent}' is not a scoped path. Send it as <scope>/<path within scope>." )
    viewer = _viewer()
    if registry is None: registry = viewer._get_scope_registry()

    try:
        scope, cfg, _, full_path = viewer._resolve_scoped( sent, registry )
        fd = viewer._open_judged_file( full_path, cfg )
    except HTTPException as refusal:
        raise _viewer_refusal( sent, refusal ) from refusal

    try:
        landed = landed_path_of_fd( fd )
        data   = _read_whole( fd )
    except DoorRefusal as refusal:
        raise DoorRefusal( refusal.code, f"'{sent}' was refused: {refusal}" ) from refusal
    finally:
        os.close( fd )

    extension = os.path.splitext( landed )[ 1 ].lower()
    if extension not in ALLOWED_SOURCE_EXTENSIONS:
        raise DoorRefusal( "wrong_kind", f"'{sent}' is a {extension or 'no-extension'} file. A podcast reads {', '.join( ALLOWED_SOURCE_EXTENSIONS )}." )
    try:
        verdict = "credential" if _prefix_looks_like_credential( data.decode( "utf-8" ) ) else "clean"
    except Exception:
        verdict = "unreadable"
    if verdict == "credential":
        raise DoorRefusal( "credential", f"'{sent}' was refused: its content is credential material." )
    if verdict == "unreadable":
        raise DoorRefusal( "unreadable", f"'{sent}' could not be read or decoded as text, so it cannot be judged." )

    rel   = landed_relative_path( landed, cfg.root )
    facts = { "scope": scope, "rel": rel, "name": os.path.basename( rel ), "server_path": landed,
              "size": len( data ), "sha256": hashlib.sha256( data ).hexdigest() }
    if keep_content: facts[ "content" ] = data
    return facts


def max_age_seconds( config_mgr=None ):
    """
    How many seconds a podcast card stays good, from the INI key.

    Requires:
        - config_mgr, when given, answers get( key, default=, return_type= ); None builds the server's own

    Ensures:
        - returns a positive int; a missing key gives MAX_AGE_DEFAULT
        - raises ValueError for a value of zero or less, because a card that is old on arrival starts nothing
    """
    if config_mgr is None:
        from cosa.config.configuration_manager import ConfigurationManager
        config_mgr = ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" )
    seconds = config_mgr.get( MAX_AGE_KEY, default=MAX_AGE_DEFAULT, return_type="int" )
    if seconds <= 0: raise ValueError( f"'{MAX_AGE_KEY}' must be positive, got {seconds}" )
    return seconds


def human_size( size ):
    """The size in the unit a person reads: bytes, KiB or MiB, with one decimal above bytes."""
    if size < 1024: return f"{size} bytes"
    if size < 1024 * 1024: return f"{size / 1024:.1f} KiB"
    return f"{size / ( 1024 * 1024 ):.1f} MiB"


def asker_label( session_id, persona_name ):
    """
    Who the card says is asking, built from the server's own facts.

    Requires:
        - session_id is the id parsed from the caller's actor string; persona_name is what the session bridge
          knows for that id, or None

    Ensures:
        - returns "<persona> (<session id>)" when the bridge knows the session
        - otherwise returns "an unrecognized session (<session id>)"
        - the caller's actor string is never part of the result: only the id parsed from it is
    """
    if persona_name: return f"{persona_name} ({session_id})"
    return f"an unrecognized session ({session_id})"


def card_payload( facts, asker, session_id ):
    """
    The binding a podcast card carries in its payload, written by the server.

    Requires:
        - facts is the dict check_source returned; asker is the label asker_label made
        - session_id is the asking session's id, parsed from its actor string

    Ensures:
        - returns { kind, command, scope_path, server_path, name, size, sha256, asked_by, asked_by_session }
        - every value comes from the server: the file's measured facts, the constant command, and the label
    """
    return {
        "kind"             : CARD_KIND,
        "command"          : COMMAND,
        "scope_path"       : f"{facts[ 'scope' ]}/{facts[ 'rel' ]}",
        "server_path"      : facts[ "server_path" ],
        "name"             : facts[ "name" ],
        "size"             : facts[ "size" ],
        "sha256"           : facts[ "sha256" ],
        "asked_by"         : asker,
        "asked_by_session" : session_id,
    }


def card_text( payload ):
    """
    The question and the card abstract Rick reads, built from the stored payload alone.

    Requires:
        - payload is a card_payload dict

    Ensures:
        - returns a (question, abstract) pair
        - both name the file, its size and who asked; the abstract also names who will start it
        - the abstract ends with `UNANSWERED_MEANS`, because silence refuses here as everywhere
        - the question carries no path and no hash, which a voice would read as noise
    """
    size = human_size( payload[ "size" ] )
    question = f"{payload[ 'asked_by' ]} asks for a podcast of {payload[ 'name' ]}, {size}. Start it?"
    abstract = (
        f"**Make a podcast**\n\n"
        f"- file: `{payload[ 'scope_path' ]}`\n"
        f"- size: {size}, SHA-256 `{payload[ 'sha256' ][ :12 ]}`\n"
        f"- asked by: {payload[ 'asked_by' ]}\n"
        f"- will be started by: {payload[ 'asked_by' ]}, once you say yes\n"
        f"- the script is written first and a Script Review card follows; audio is bought after that\n\n"
        f"{promotion_gate.UNANSWERED_MEANS}"
    )
    return question, abstract


PAYLOAD_KEYS = frozenset( { "kind", "command", "scope_path", "server_path", "name", "size", "sha256", "asked_by", "asked_by_session" } )


class StartRefusal( Exception ):
    """A start the server refuses: HTTP status, the client-facing code, and the message."""

    def __init__( self, status, code, message ):
        super().__init__( message )
        self.status, self.code, self.message = status, code, message


def start_refusal( card, actor_session, now, max_age ):
    """
    None when the stored card lets this session start its job, else the refusal.

    Requires:
        - card is the Notification row read by the id the caller cited, or None when no row has it
        - actor_session is the caller's session id; now is aware; max_age is the INI age in seconds

    Ensures:
        - returns None only when every one of these holds: the card exists and carries the payload
          this feature's ask writes, no more and no less; it asked a question; it was answered; the answer is a yes a person gave,
          not the timed-out default; the server saw it arrive on the operator's own login; the caller is the
          session that asked; the card is no older than max_age
        - returns a StartRefusal otherwise, whose code names the first failed condition
        - the card's message and abstract are never read: they are text, and the payload is what the server wrote
    """
    if card is None:
        return StartRefusal( 404, "no_card", "No card with that id exists, so the podcast is not started." )
    payload = card.payload if isinstance( card.payload, dict ) else { }
    if payload.get( "kind" ) != CARD_KIND or set( payload ) != PAYLOAD_KEYS or payload.get( "command" ) != COMMAND:
        return StartRefusal( 403, "bad_card", "That card was not made by the server for a podcast, so the podcast is not started." )
    if card.response_requested is not True:
        return StartRefusal( 403, "bad_card", "That notification asked no question, so it cannot approve a podcast." )
    answer = card.response_value if isinstance( card.response_value, dict ) else { }
    if card.responded_at is None or card.state != "responded":
        return StartRefusal( 403, "not_answered", "That card has no answer yet, so the podcast is not started." )
    if answer.get( "source" ) == "timeout_default":
        return StartRefusal( 403, "default_answer", "That card was settled by its timed-out default, not by an answer, so the podcast is not started." )
    if str( answer.get( "value", "" ) ).strip().lower() != "yes":
        return StartRefusal( 403, "not_yes", "The answer on that card was not yes, so the podcast is not started." )
    answered_by = answer.get( "answered_by" )
    if not promotion_gate.answer_posted_by_the_operator( answered_by ):
        return StartRefusal( 403, "wrong_login", f"That card was answered by {promotion_gate.describe_who_answered( answered_by )}, "
                                                     f"not by the operator's own login, so the podcast is not started." )
    if payload[ "asked_by_session" ] != actor_session:
        return StartRefusal( 403, "wrong_session", f"That card was asked by {payload[ 'asked_by' ]}, and only that session starts it." )
    if card.created_at is None or ( now - card.created_at ).total_seconds() > max_age:
        return StartRefusal( 403, "too_old", f"That card is older than {max_age} seconds, so the yes has expired. Ask again." )
    return None


def file_changed_refusal( payload, facts ):
    """
    None when the file now matches what the card said, else the refusal.

    Requires:
        - payload is the stored card payload; facts is what check_source measured just now

    Ensures:
        - returns None only when the content hash, the size and the server path all equal the card's
        - otherwise returns a 409 hash_mismatch StartRefusal naming the file
    """
    for key in ( "sha256", "size", "server_path" ):
        if facts[ key ] != payload[ key ]:
            return StartRefusal( 409, "hash_mismatch", f"{payload[ 'scope_path' ]} is not the file Rick said yes to ({key} differs), so the podcast is not started. Ask again." )
    return None


def write_copy( directory, card_id, name, content ):
    """
    Write the copy the job will read, once, under a folder named for the card.

    Requires:
        - directory is the folder that holds all podcast proxy copies; name is a file name with no folder part
        - content is the bytes the door judged and hashed

    Ensures:
        - returns the absolute path of the new file, mode 0640, in a folder made for this card
        - a stale copy of the same card is removed first, and the new file is created exclusively, so nothing is
          written through a link that someone planted in its place
    """
    folder = os.path.join( directory, str( card_id ) )
    os.makedirs( folder, mode=0o750, exist_ok=True )
    path = os.path.join( folder, os.path.basename( name ) )
    if os.path.lexists( path ): os.unlink( path )
    fd   = os.open( path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o640 )
    with os.fdopen( fd, "wb" ) as handle: handle.write( content )
    return path


def card_state( card, now ):
    """
    Where a podcast card stands, in one word, for a client that resumes with only the card id.

    Requires:
        - card is a Notification written by the ask door; now is aware

    Ensures:
        - returns "waiting" for an open question that has not expired
        - "yes" only for a yes a person gave on the operator's own login; "wrong_login" for a yes from anyone else
        - "no" for a person's no, "default_answer" for the timed-out default, "expired" for a card that timed out unanswered
    """
    answer = card.response_value if isinstance( card.response_value, dict ) else { }
    if card.responded_at is None or card.state != "responded":
        if card.state == "expired" or ( card.expires_at is not None and card.expires_at <= now ): return "expired"
        return "waiting"
    if answer.get( "source" ) == "timeout_default": return "default_answer"
    if str( answer.get( "value", "" ) ).strip().lower() != "yes": return "no"
    return "yes" if promotion_gate.answer_posted_by_the_operator( answer.get( "answered_by" ) ) else "wrong_login"


def remove_copy( directory, card_id ):
    """Remove the folder write_copy made for a card. Best effort; it never raises."""
    shutil.rmtree( os.path.join( directory, str( card_id ) ), ignore_errors=True )
