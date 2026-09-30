"""
How a script or test rig submits a test-suite job now that `/api/test-suite/submit` (door 18)
is retired to 410: through `POST /api/v2/submit`, command `agent router go to test suite`.

Two pure functions, no HTTP, so every caller keeps its own transport:

  • `submit_body( … )` builds the v2 request from the old door's field names.
  • `read_reply( http_status, body )` turns the v2 answer into `( ok, info )`, where `info`
    carries `status`, `job_id`, `queue_position` and `message` (the old door's fields) plus
    `error` when the submit was refused.

WHAT CHANGED FOR A CALLER, said once here so the ~5 callers do not each rediscover it:

  · The request nests the suite arguments under `args`; `scheduled_at` and `websocket_id` are
    top-level; `monopolize` is not sent (the job forces it itself).
  · A submit that was UNDERSTOOD and then refused (unknown suite name, malformed or
    contradictory pytest_args) is HTTP 200 with `status: "failed"` and the cause in `error`,
    NOT the old door's HTTP 400. A caller that keyed on the HTTP code must key on `ok`.
  · Success is `status: "waiting"` (the old door said `queued`); `queue_position` is the todo
    queue's size right after the push, the same number the old door returned.
"""

TEST_SUITE_COMMAND = "agent router go to test suite"


def submit_body( test_types, pytest_args=None, dry_run=False, auto_fix_on_failure=None,
                 env_vars=None, scheduled_at=None, websocket_id=None, parent_id_hash=None ):
    """
    Requires:
        - test_types is the comma-separated string the old door took (e.g. "e2e_a,e2e_b")

    Ensures:
        - returns a /api/v2/submit body for the test-suite command
        - optional fields that are None/empty are omitted, exactly as the old callers did
        - auto_fix_on_failure False is KEPT (False means "force off", None means "INI default")
    """
    args = { "test_types": test_types, "dry_run": dry_run }
    if pytest_args:                       args[ "pytest_args" ]          = pytest_args
    if auto_fix_on_failure is not None:   args[ "auto_fix_on_failure" ]  = auto_fix_on_failure
    if env_vars:                          args[ "env_vars" ]             = env_vars
    body = { "command": TEST_SUITE_COMMAND, "args": args, "speak": False }
    if scheduled_at:    body[ "scheduled_at" ]    = scheduled_at
    if websocket_id:    body[ "websocket_id" ]    = websocket_id
    if parent_id_hash:  body[ "parent_id_hash" ]  = parent_id_hash
    return body


def read_reply( http_status, body ):
    """
    Requires:
        - http_status is the HTTP status code
        - body is the decoded JSON (a dict) or None when the body was not JSON

    Ensures:
        - returns ( ok, info ); ok is True only for HTTP 2xx AND status "waiting"
        - info always has status, job_id, queue_position, message, error (None when ok)
        - a non-2xx answer or a non-dict body yields ok False with the HTTP code in `error`
    """
    body = body if isinstance( body, dict ) else { }
    info = {
        "status"         : body.get( "status" ),
        "job_id"         : body.get( "job_id" ),
        "queue_position" : body.get( "queue_position" ),
        "message"        : body.get( "answer" ) or body.get( "message" ) or "",
        "error"          : None,
    }
    if not ( 200 <= http_status < 300 ):
        info[ "error" ] = body.get( "detail" ) or f"HTTP {http_status}"
        return False, info
    if body.get( "status" ) != "waiting":
        info[ "error" ] = body.get( "error" ) or f"submit not accepted: status={body.get( 'status' )!r}"
        return False, info
    return True, info
