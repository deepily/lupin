"""
One adapter for the four suites that used the retired `POST /api/mock-job/submit` (door 14,
row 432511fd), now that the same two modes are the command `agent router go to mock job` on
`POST /api/v2/submit`.

WHY AN ADAPTER AND NOT FOUR EDITS. The suites read the old door's response shape all through
their validators (`status == "queued"`, `config`, `job_id`, `"cancelled"`). Moving the four
call sites to read v2's shape would rewrite four validators; mapping the response back
keeps each suite's assertions exactly what they were.

The mapping, from a v2 `AskResponse` body to the old door's:

  v2                                              old door
  status "waiting"                          →     status "queued"
  status "failed" + route_reason
      "expeditor_cancelled"                 →     status "cancelled", job_id "expeditor-test-cancelled"
  any other status                          →     status "error"
  submit_details["config"]                  →     config
  submit_details["message"]                 →     message
  queue_position, job_id                    →     unchanged

Pure functions, no HTTP: the smoke suites post with `requests` and the e2e with Playwright's
request context, so each keeps its own transport.
"""

MOCK_COMMAND = "agent router go to mock job"

# The three fields the old door took in its body that v2 takes at the TOP level of the
# request, not inside `args`.
_TOP_LEVEL = ( "websocket_id", "scheduled_at", "monopolize" )


def submit_body( fields ):
    """
    Turn the old door's request body into a v2 submit body.

    Requires:
        - fields is a dict of the old door's field names

    Ensures:
        - websocket_id / scheduled_at / monopolize move to the top level; every other field
          becomes an `args` entry
        - the command is the mock-job command and speak is False
    """
    body = { "command": MOCK_COMMAND, "args": { }, "speak": False }
    for name, value in fields.items():
        if name in _TOP_LEVEL:
            body[ name ] = value
        else:
            body[ "args" ][ name ] = value
    return body


def legacy_response( v2_body ):
    """
    Map a v2 response body back to the old door's response shape.

    Requires:
        - v2_body is the JSON dict `/api/v2/submit` answered

    Ensures:
        - returns a dict with status, job_id, queue_position, config and message, per the
          table in the module docstring
    """
    details = v2_body.get( "submit_details" ) or { }
    result  = {
        "status"         : "error",
        "job_id"         : v2_body.get( "job_id" ),
        "queue_position" : v2_body.get( "queue_position" ),
        "config"         : details.get( "config", { } ),
        "message"        : details.get( "message", v2_body.get( "error" ) or "" ),
    }
    if v2_body.get( "status" ) == "waiting":
        result[ "status" ] = "queued"
    elif v2_body.get( "status" ) == "failed" and v2_body.get( "route_reason" ) == "expeditor_cancelled":
        result[ "status" ] = "cancelled"
        result[ "job_id" ] = "expeditor-test-cancelled"
    return result
