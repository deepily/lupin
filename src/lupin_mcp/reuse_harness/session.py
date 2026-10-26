"""
The session port of the run harness: the Claude Code session that builds a run's client.

It also probes the arm.

Both arms start the same command. The without arm adds the deny rules, and its worktree has no reuse skill folder.
The session is a headless `claude -p` process in the run's worktree with project hooks off, so a run is not a fleet seat.
Named gap: no real session has been started by this port. It is proven against a fake command here and live in plan 3, section 7.4 (the pilot).
"""
import json
import os
import time
import uuid

from lupin_mcp.reuse_harness import arms
from lupin_mcp.reuse_harness import commands
from lupin_mcp.reuse_harness import errors as err

SLICE_HOURS     = 2.0
PROBE_TIMEOUT   = 300
STOPS_TO_FINISH = 2
TAIL            = 20
PERMISSION_MODE = "bypassPermissions"
SETTINGS        = json.dumps( { "disableAllHooks" : True } )
BRIEF           = ("Read src/rnd/v0.2.2/2026.09.30-wiki-and-jev-for-code-reuse-review/2026.10.25-experiment-build-task-generic-plan.md and build what it describes. "
                   "Run the acceptance tests in src/tests/experiment_acceptance against the server at $EXPERIMENT_SERVER_URL until every one passes. "
                   "Put everything you create inside src/lupin_app/static, including package.json and tsconfig.json with a build script. A change anywhere else ends the run.")
RESUME_PROMPT   = "Continue. Run the acceptance tests again and keep going until every one passes."
PROBE_PROMPTS   = {
    arms.SURFACE_CHECK_EXISTS    : "Call the tool mcp__cosa-voice__check_exists once, about a function that parses an ISO date. Then stop.",
    arms.SURFACE_FETCH_SIMILAR   : "Call the tool mcp__cosa-voice__fetch_similar once, about a function that parses an ISO date. Then stop.",
    arms.SURFACE_READ_CAPABILITY : "Call the tool mcp__cosa-voice__read_capability once, for any capability page. Then stop.",
    arms.SURFACE_REVIEWER        : "Invoke the skill reuse-reviewer once. Then stop.",
}
# A tool result carrying one of these words is a refusal by the session, not an answer from the surface.
REFUSAL_WORDS   = ( "permission", "denied", "not allowed", "no such tool", "not available" )


def events_of( output ):
    """
    Read the JSON events out of a stream-json output.

    Ensures:
        - returns the lines that parse as JSON objects, in order; any other line is skipped
    """
    events = []
    for line in output.splitlines():
        try:
            event = json.loads( line )
        except ValueError:
            continue
        if isinstance( event, dict ): events.append( event )
    return events


def blocks_of( events, kind ):
    """Return the content blocks of one type from the assistant and user messages."""
    found = []
    for event in events:
        content = event.get( "message", {} ).get( "content", [] ) if event.get( "type" ) in ( "assistant", "user" ) else []
        if isinstance( content, list ): found.extend( block for block in content if isinstance( block, dict ) and block.get( "type" ) == kind )
    return found


def surface_answered( output, surface ):
    """
    Say whether a probe session called the surface and was not refused.

    Requires:
        - output is the stream-json output of a probe session

    Ensures:
        - true when the session issued a call to the surface and its result is not a refusal
        - false when no call was issued, which is what a denied tool looks like: the session never offers it
    """
    events = events_of( output )
    wanted = "Skill" if surface == arms.SURFACE_REVIEWER else arms.DENY_RULES[ surface ]
    calls  = [ block for block in blocks_of( events, "tool_use" ) if block.get( "name" ) == wanted
               and ( surface != arms.SURFACE_REVIEWER or block.get( "input", {} ).get( "skill" ) == surface ) ]
    if not calls: return False
    results = { block.get( "tool_use_id" ) : block for block in blocks_of( events, "tool_result" ) }
    for call in calls:
        result = results.get( call[ "id" ] )
        if result is not None and result.get( "is_error" ) and any( word in str( result.get( "content" ) ).lower() for word in REFUSAL_WORDS ): return False
    return True


class Sessions:
    """Starts the probe sessions and the working sessions of one run."""

    def __init__( self, notify_api_key, runner=commands.run_command, clock=time.monotonic, claude="claude", environ=None, brief=BRIEF,
                  resume_prompt=RESUME_PROMPT, slice_hours=SLICE_HOURS, permission_mode=PERMISSION_MODE, mcp_config=None, seats=1 ):
        """
        Remember how a session is started.

        Requires:
            - notify_api_key is the key the run's tests send as the sender side
            - runner( argv, env=, cwd=, timeout= ) returns ( exit code, output ); claude names the command
            - mcp_config, when given, is a file naming the same MCP servers for both arms

        Ensures:
            - nothing is started; no session is bound to a worktree yet; environ defaults to os.environ
        """
        self.notify_api_key  = notify_api_key
        self.runner          = runner
        self.clock           = clock
        self.claude          = claude
        self.environ         = os.environ if environ is None else environ
        self.brief           = brief
        self.resume_prompt   = resume_prompt
        self.slice_hours     = slice_hours
        self.permission_mode = permission_mode
        self.mcp_config      = mcp_config
        self.seats           = seats
        self.path            = None
        self.handle          = None
        self.session_id      = None
        self.slices          = 0
        self.stops           = 0

    def bind( self, path, handle ):
        """
        Tie the sessions to the run's worktree and server, before anything is probed.

        Ensures:
            - the session id is derived from the container name, so one run has one id
            - no slice has run yet
        """
        self.path       = path
        self.handle     = handle
        self.session_id = str( uuid.uuid5( uuid.NAMESPACE_URL, handle[ "container" ] ) )
        self.slices     = 0
        self.stops      = 0

    def probe( self, config, surface ):
        """
        Start a short session under the arm's configuration and try the surface.

        Requires:
            - bind has been called; config is the arm's configuration

        Ensures:
            - the probe is not stored as a session and uses the arm's flags
            - returns whether surface_answered holds for the session's output

        Raises:
            - HarnessError SESSION_START if the command could not start
        """
        argv = self._argv( config, PROBE_PROMPTS[ surface ] ) + [ "--no-session-persistence" ]
        code, output = self.runner( argv, env=self._env(), cwd=self.path, timeout=PROBE_TIMEOUT )
        self._check_started( code, output )
        return surface_answered( output, surface )

    def work( self, config, path, handle, remaining_hours ):
        """
        Run one slice of the working session, within the slice length and the hours left.

        Requires:
            - bind has been called for this path; remaining_hours is positive

        Ensures:
            - the first slice starts the session with the brief; each later slice resumes it
            - the slice is stopped at min( slice length, remaining hours )
            - returns { seat_hours, finished }; seat_hours is the wall time times the seats
            - finished is true once the session has stopped on its own STOPS_TO_FINISH times in a row; a slice stopped by its time limit resets the count

        Raises:
            - HarnessError SESSION_START if the command could not start
            - HarnessError SESSION_FAILED if the command ended with an error before its time limit
        """
        hours   = min( self.slice_hours, remaining_hours )
        argv    = self._argv( config, self.resume_prompt if self.slices else self.brief ) + ( [ "--resume", self.session_id ] if self.slices else [ "--session-id", self.session_id ] )
        started = self.clock()
        code, output = self.runner( argv, env=self._env(), cwd=path, timeout=hours * 3600 )
        elapsed = self.clock() - started
        timed_out = code == 127 and "TimeoutExpired" in output
        if not timed_out:
            self._check_started( code, output )
            if code != 0: raise err.HarnessError( err.SESSION_FAILED, f"the session ended with {code}: {' | '.join( output.splitlines()[ -TAIL: ] )}" )
        self.slices += 1
        self.stops   = 0 if timed_out else self.stops + 1
        return { "seat_hours" : elapsed / 3600 * self.seats, "finished" : self.stops >= STOPS_TO_FINISH }

    def _argv( self, config, prompt ):
        """Build the command of one session; the prompt comes first, so no flag takes it as a value."""
        argv = [ self.claude, "-p", prompt, "--model", config[ "model" ], "--setting-sources", ",".join( config[ "setting_sources" ] ),
                 "--settings", SETTINGS, "--permission-mode", self.permission_mode, "--output-format", "stream-json", "--verbose" ]
        if config[ "deny_rules" ]: argv += [ "--disallowedTools", ",".join( config[ "deny_rules" ] ) ]
        if self.mcp_config: argv += [ "--mcp-config", self.mcp_config, "--strict-mcp-config" ]
        return argv

    def _env( self ):
        """Build the session's environment: the run's server and the sender key, by value."""
        env = dict( self.environ )
        env.update( { "EXPERIMENT_SERVER_URL" : self.handle[ "url" ], "EXPERIMENT_NOTIFY_API_KEY" : self.notify_api_key } )
        return env

    def _check_started( self, code, output ):
        """Refuse a command that could not start, which the runner reports as 127 with the cause."""
        if code == 127: raise err.HarnessError( err.SESSION_START, f"{self.claude} answered 127: {output}" )
