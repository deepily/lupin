"""
The seat-side half of "podcast that": ask Rick, wait for his answer, then start the job.

The server owns every decision. It checks the file, writes the yes/no card and re-checks the card at
start. This module only turns a host path into the form the server accepts, polls the card, and calls
the two doors in order. It never trusts or supplies anything the server should decide.
"""
import os
import time
from datetime import datetime, timezone

from lupin_mcp.memento_repo_root import _default_run, _git_answer, repo_root_owning
from lupin_mcp.task_store_tools import task_store_request

PODCAST_ASK_PATH      = "/api/podcast-proxy/ask"
PODCAST_START_PATH    = "/api/podcast-proxy/start"
CARD_RESPONSE_PATH    = "/api/notifications/response/{card_id}"
POLL_INTERVAL_SECONDS = 3.0
POLL_FAILURE_LIMIT    = 5
WORKTREE_ADVICE       = "write it to the main checkout's io/tmp"


def _refusal( reason, detail, **extra ):
    """
    Build the error dict every refusal in this module returns.

    Requires:
        - reason is a short machine word; detail is a sentence for the seat

    Ensures:
        - returns { status: "error", reason, detail } plus any extra keys
    """
    return { "status": "error", "reason": reason, "detail": detail, **extra }


def translate_host_path( host_path, run_fn=_default_run ):
    """
    Turn a seat's absolute host path into the "scope/relative" form the server accepts.

    Requires:
        - host_path is the string the seat supplied
        - run_fn( argv, cwd ) returns git's stdout, or None when git cannot answer

    Ensures:
        - returns { status: "ok", path: "<scope>/<relative>" } for a file inside a main checkout
        - the scope is the main checkout's directory name; the server's table decides whether it is registered
        - refuses a relative path, a missing file, a file under no git repository, and a file inside a linked worktree
        - a worktree file is refused because the server mounts only the main checkout, so its relative path would name a different file
        - never raises
    """
    if not isinstance( host_path, str ) or not os.path.isabs( host_path ):
        return _refusal( "path_not_absolute", f"The path must be absolute, got {host_path!r}." )
    real = os.path.realpath( host_path )
    if not os.path.isfile( real ):
        return _refusal( "file_not_found", f"No file exists at {real}." )

    folder   = os.path.dirname( real )
    toplevel = _git_answer( folder, "--show-toplevel", run_fn )
    main     = repo_root_owning( folder, run_fn=run_fn, warn_fn=lambda message: None )
    if toplevel is None or main is None:
        return _refusal( "outside_any_repo", f"{real} is not inside a git repository, so no registered project owns it." )
    if toplevel != main:
        return _refusal( "inside_a_worktree", f"{real} is inside a linked worktree, which the server cannot see; {WORKTREE_ADVICE}." )

    return { "status": "ok", "path": f"{main.name}/{os.path.relpath( real, str( main ) )}" }


def _parse_instant( text ):
    """
    Parse an ISO-8601 instant into an aware datetime.

    Ensures:
        - returns None for anything that is not a string holding an instant
        - a value with no zone is read as UTC
    """
    if not isinstance( text, str ): return None
    try:
        parsed = datetime.fromisoformat( text )
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace( tzinfo=timezone.utc )


def _read_answer( card_id, api_base_url, api_key, request_fn ):
    """
    Read the card's state once.

    Ensures:
        - returns the server's { state, response_value, responded_at } dict
        - returns None when the read failed, so the caller counts a failure rather than guessing
    """
    answer = request_fn( "GET", CARD_RESPONSE_PATH.format( card_id=card_id ), api_base_url, api_key )
    if answer.get( "status" ) == "error": return None
    return answer


def _verdict( answer ):
    """
    Classify a responded card.

    Ensures:
        - returns "yes" only for an answer a person gave: not a timed-out default
        - returns "default" for a timed-out default, whatever its value
        - returns "no" for every other answer, including "neither"
    """
    value = answer.get( "response_value" )
    value = value if isinstance( value, dict ) else { }
    if value.get( "source" ) == "timeout_default": return "default"
    return "yes" if str( value.get( "value", "" ) ).strip().lower() == "yes" else "no"


def podcast_for_rick_impl(
    api_base_url,
    api_key,
    actor,
    host_path,
    request_fn = task_store_request,
    sleep_fn   = time.sleep,
    now_fn     = lambda: datetime.now( timezone.utc ),
    run_fn     = _default_run,
):
    """
    Ask Rick about a podcast of one file, wait for his answer, and start it on a yes.

    Requires:
        - actor is the bridge-stamped identity, set by the caller and never a tool parameter
        - host_path is the seat's absolute path to a file in a main checkout

    Ensures:
        - returns { status: "started", card_id, ... } only after a person's yes and a successful start
        - returns { status: "declined", card_id } for a no or a neither, and never calls start
        - returns { status: "default_used", card_id } for a timed-out default, and never calls start
        - returns { status: "expired", card_id } when the card's expiry passes unanswered
        - returns { status: "error", reason, detail } for a path refusal, a refused ask, a refused start, or an unreadable card
        - a card already waiting for the same file surfaces as reason "card_already_waiting"
        - a spent card surfaces as reason "card_already_spent"
        - start is called at most once and is never retried
        - never raises
    """
    translated = translate_host_path( host_path, run_fn )
    if translated[ "status" ] != "ok": return translated

    asked = request_fn( "POST", PODCAST_ASK_PATH, api_base_url, api_key,
                        json_body={ "path": translated[ "path" ], "actor": actor } )
    if asked.get( "status" ) == "error":
        # A 409 here means a card for this very file already waits on Rick; asking again would be noise.
        refused = { **asked, "stage": "ask" }
        if asked.get( "http_status" ) == 409: refused[ "reason" ] = "card_already_waiting"
        return refused

    card_id = asked.get( "card_id" )
    expires = _parse_instant( asked.get( "expires_at" ) )
    if not card_id or expires is None:
        return _refusal( "ask_answer_malformed", "The ask door answered without a card_id and an expires_at.", stage="ask", answer=asked )

    failures = 0
    while now_fn() < expires:
        answer = _read_answer( card_id, api_base_url, api_key, request_fn )
        if answer is None:
            failures += 1
            if failures >= POLL_FAILURE_LIMIT:
                return _refusal( "card_unreadable", f"The card {card_id} could not be read {failures} times in a row; its answer is unknown.", card_id=card_id )
        elif answer.get( "state" ) == "responded":
            verdict = _verdict( answer )
            if verdict == "default": return { "status": "default_used", "card_id": card_id }
            if verdict == "no":      return { "status": "declined", "card_id": card_id }
            return _start( card_id, api_base_url, api_key, actor, request_fn )
        else:
            failures = 0
        sleep_fn( POLL_INTERVAL_SECONDS )
    return { "status": "expired", "card_id": card_id }


def _start( card_id, api_base_url, api_key, actor, request_fn ):
    """
    Call the start door once for an answered card.

    Ensures:
        - returns { status: "started", card_id, ...the door's answer } on success
        - maps a 409 to reason "card_already_spent"
        - passes any other refusal through with the card id and stage "start"
    """
    started = request_fn( "POST", PODCAST_START_PATH, api_base_url, api_key,
                          json_body={ "card_id": card_id, "actor": actor } )
    if started.get( "status" ) != "error":
        return { **started, "status": "started", "card_id": card_id }
    if started.get( "http_status" ) == 409:
        return { **started, "reason": "card_already_spent", "card_id": card_id, "stage": "start" }
    return { **started, "card_id": card_id, "stage": "start" }
