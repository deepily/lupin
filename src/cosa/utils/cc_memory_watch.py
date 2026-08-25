"""
Sample the resident memory of live Claude Code processes and name the ones that
run away (store row df5c3696).

THE GAP THIS CLOSES. On 2026-08-22 the kernel killed two node processes at 229 GB
and 124 GB, and nobody could say which session they were: the listener LOGS under
~/.claude/sessions do not record the owner pid in a form that greps back, and with
roughly two dozen sessions live, timing is not evidence.

But the listener PROCESS does carry it. Its command line reads:

    python3 -m …cc_notification_listener --session-id 0b7675fc --owner-pid 751918 …

So the mapping from a Claude Code pid to a session id was sitting in the process
table the whole time — it was only ever missing from the files anyone thought to
grep. This module reads it from there, which means attribution works for sessions
ALREADY RUNNING, with no change to how they were launched.

Three resolvers, tried in order, because each covers a different population:
  1. the listener's --owner-pid → --session-id   (any session with a listener)
  2. /proc/<pid>/cgroup → lupin-cc-<name>.scope  (sessions launched under the cap)
  3. /proc/<pid>/environ → TMUX_PANE → tmux      (anything in a tmux pane)
A process that answers to none of the three is reported with what IS known — the
pid and the command line — rather than dropped.

Deliberately does no killing and no notifying: it writes a line. The point is that
the NEXT time this happens somebody can name the session and read its transcript
back to the tool call that allocated.
"""

import os
import re
import subprocess
import time

# Default alert threshold. Well under the 24G containment cap so the line lands
# BEFORE the kill, leaving the transcript readable.
DEFAULT_THRESHOLD_GB = 16.0

# Default sampling interval, seconds. RSS grew from nothing to 229 GB inside one
# turn on 08-22, so a slow interval can miss the climb entirely.
DEFAULT_INTERVAL_SECONDS = 15.0

# Re-alert only after this much further growth, so one runaway does not write a
# line every interval for as long as it lives.
DEFAULT_RESTEP_GB = 8.0

KB_PER_GB = 1024.0 * 1024.0

LISTENER_MODULE = "cc_notification_listener"

# The scope unit the launcher's memory cap creates: lupin-cc-<session>-<pid>.scope
_SCOPE_RE  = re.compile( r"/(lupin-cc-(?P<session>.+?)-(?P<pid>\d+))\.scope" )
_VMRSS_RE  = re.compile( r"^VmRSS:\s+(\d+)\s+kB", re.MULTILINE )
_PANE_RE   = re.compile( r"^TMUX_PANE=(.+)$", re.MULTILINE )


class Sample:
    """One observation of one Claude Code process."""

    def __init__( self, pid, rss_kb, cmdline, session_id=None, scope_unit=None, tmux_session=None ):

        self.pid          = pid
        self.rss_kb       = rss_kb
        self.cmdline      = cmdline
        self.session_id   = session_id
        self.scope_unit   = scope_unit
        self.tmux_session = tmux_session

    @property
    def rss_gb( self ):

        return self.rss_kb / KB_PER_GB

    def __repr__( self ):

        return f"Sample( pid={self.pid}, rss_kb={self.rss_kb}, session_id={self.session_id!r} )"


# ── Pure parsers: every one takes text and returns a value, so the decisions ──
# ── this module makes are testable without a live process table. ─────────────

def parse_vm_rss_kb( status_text ):
    """
    Extract resident set size from /proc/<pid>/status text.

    Requires:
        - status_text is a string

    Ensures:
        - returns the VmRSS value in kB, or None when the field is absent
          (a kernel thread, or a process that exited mid-read)
    """

    match = _VMRSS_RE.search( status_text )

    return int( match.group( 1 ) ) if match else None


def parse_scope_unit( cgroup_text ):
    """
    Recover the memory-cap scope unit and its session name from /proc/<pid>/cgroup.

    Requires:
        - cgroup_text is a string

    Ensures:
        - returns ( unit_name, session_name ), or ( None, None ) when the process
          is not running under a lupin-cc scope
    """

    match = _SCOPE_RE.search( cgroup_text )

    if not match: return ( None, None )

    return ( match.group( 1 ), match.group( "session" ) )


def parse_tmux_pane( environ_text ):
    """
    Read TMUX_PANE out of a NUL-to-newline translated /proc/<pid>/environ.

    Requires:
        - environ_text is a string with entries separated by newlines

    Ensures:
        - returns the pane id (e.g. '%2'), or None when the process has no pane
    """

    match = _PANE_RE.search( environ_text )

    return match.group( 1 ).strip() if match else None


def parse_listener_owner_map( listener_cmdlines ):
    """
    Build owner-pid → session-id from the notification listeners' command lines.

    THIS IS THE ATTRIBUTION FIX. The listener log files do not record the owner
    pid in a greppable form, which is why the 08-22 kills could not be pinned to
    a session — but the listener's own argv carries both ids.

    Requires:
        - listener_cmdlines is an iterable of argv lists

    Ensures:
        - returns { owner_pid:int -> session_id:str } for every listener that
          declares both flags
        - a listener missing either flag is skipped, never guessed at
    """

    owners = {}

    for argv in listener_cmdlines:

        session_id = _flag_value( argv, "--session-id" )
        owner_pid  = _flag_value( argv, "--owner-pid" )

        if session_id is None or owner_pid is None: continue
        if not owner_pid.isdigit():                 continue

        owners[ int( owner_pid ) ] = session_id

    return owners


def _flag_value( argv, flag ):
    """
    Return the value following `flag` in an argv list, or None.

    Requires:
        - argv is a list of strings

    Ensures:
        - supports both '--flag value' and '--flag=value'
    """

    for index, token in enumerate( argv ):

        if token == flag and index + 1 < len( argv ): return argv[ index + 1 ]
        if token.startswith( flag + "=" ):            return token[ len( flag ) + 1 : ]

    return None


def is_claude_process( comm, argv ):
    """
    Decide whether a process is a Claude Code session.

    Requires:
        - comm is the process's /proc/<pid>/comm value
        - argv is its command line as a list

    Ensures:
        - True for the node process Claude Code renames to 'claude'
        - False for look-alikes that merely mention claude — the monitor UI, a
          grep, an editor with the word in its path — because a watcher that
          alerts on the wrong process teaches people to ignore it
    """

    if comm.strip() != "claude": return False
    if not argv:                 return False

    return os.path.basename( argv[ 0 ] ) == "claude"


def is_listener_process( argv ):
    """
    Decide whether a process is a cc_notification_listener.

    Requires:
        - argv is a command line as a list

    Ensures:
        - True when the listener module appears as a -m target or script path
    """

    return any( LISTENER_MODULE in token for token in argv )


class AlertTracker:
    """
    Decide when a sample deserves a line.

    Emits on the crossing, then stays quiet until the process grows another
    `restep_kb` — otherwise one runaway writes a line every interval for as long
    as it lives, and the log stops being readable exactly when it matters.
    """

    def __init__( self, threshold_kb, restep_kb ):

        self.threshold_kb = threshold_kb
        self.restep_kb    = restep_kb
        self._last_alert  = {}   # pid -> rss_kb at the last emitted line

    def should_alert( self, pid, rss_kb ):
        """
        Requires:
            - pid is an int, rss_kb an int

        Ensures:
            - True on the first crossing of the threshold
            - True again only once the process has grown by restep_kb
            - False while below the threshold
        """

        if rss_kb < self.threshold_kb:
            self._last_alert.pop( pid, None )   # dropped back: re-arm the crossing
            return False

        previous = self._last_alert.get( pid )

        if previous is not None and rss_kb - previous < self.restep_kb: return False

        self._last_alert[ pid ] = rss_kb

        return True

    def forget_absent( self, live_pids ):
        """
        Drop state for processes that are gone.

        Requires:
            - live_pids is a container of currently-observed pids

        Ensures:
            - a pid recycled by the kernel cannot inherit a stale alert level
        """

        for pid in [ p for p in self._last_alert if p not in live_pids ]:
            del self._last_alert[ pid ]


def format_alert_line( sample, threshold_kb, timestamp ):
    """
    Render one alert as a single greppable line.

    Requires:
        - sample is a Sample
        - threshold_kb is the int threshold that was crossed
        - timestamp is a preformatted string

    Ensures:
        - returns exactly one line, no embedded newlines
        - always carries pid and RSS; carries session/tmux/scope when resolved
          and the literal 'unresolved' when not, so a gap reads as a gap
    """

    session = sample.session_id   or "unresolved"
    tmux    = sample.tmux_session or "unresolved"
    scope   = sample.scope_unit   or "none"
    command = " ".join( sample.cmdline )[ :160 ].replace( "\n", " " )

    return (
        f"{timestamp} [CC-MEM] pid={sample.pid} "
        f"rss_gb={sample.rss_gb:.1f} threshold_gb={threshold_kb / KB_PER_GB:.1f} "
        f"session={session} tmux={tmux} scope={scope} cmd=\"{command}\""
    )


# ── IO layer ─────────────────────────────────────────────────────────────────

def _read( path ):
    """Read a proc file, returning None when it vanished or is not ours."""

    try:
        with open( path, "rb" ) as handle: return handle.read().decode( "utf-8", "replace" )
    except ( FileNotFoundError, ProcessLookupError, PermissionError, OSError ):
        return None


def _read_argv( pid ):
    """Return a process's argv list, or None."""

    raw = _read( f"/proc/{pid}/cmdline" )

    if raw is None: return None

    return [ token for token in raw.split( "\0" ) if token ]


def iter_pids():
    """
    Yield the numeric pids currently in /proc.

    Ensures:
        - bounded by the size of the process table; never walks the filesystem
    """

    for entry in os.listdir( "/proc" ):
        if entry.isdigit(): yield int( entry )


def resolve_tmux_session( pane, runner=subprocess.run ):
    """
    Map a tmux pane id to its session name.

    Requires:
        - pane is a tmux pane id, or None
        - runner has subprocess.run's signature (injected for tests)

    Ensures:
        - returns the session name, or None when tmux cannot answer
        - never raises: an absent tmux is a missing label, not a crash
    """

    if not pane: return None

    try:
        result = runner(
            [ "tmux", "display-message", "-p", "-t", pane, "#S" ],
            capture_output=True, text=True, timeout=5,
        )
    except ( OSError, subprocess.SubprocessError ):
        return None

    if result.returncode != 0: return None

    name = result.stdout.strip()

    return name or None


def collect_samples():
    """
    Take one pass over the process table.

    Ensures:
        - returns a list of Sample for every live Claude Code process
        - a process that exits mid-scan is skipped, not reported at RSS 0
    """

    claude_pids       = []
    listener_cmdlines = []

    for pid in iter_pids():

        argv = _read_argv( pid )
        if not argv: continue

        if is_listener_process( argv ):
            listener_cmdlines.append( argv )
            continue

        comm = _read( f"/proc/{pid}/comm" )
        if comm is None: continue

        if is_claude_process( comm, argv ): claude_pids.append( ( pid, argv ) )

    owners  = parse_listener_owner_map( listener_cmdlines )
    samples = []

    for pid, argv in claude_pids:

        status = _read( f"/proc/{pid}/status" )
        if status is None: continue

        rss_kb = parse_vm_rss_kb( status )
        if rss_kb is None: continue

        scope_unit, scope_session = parse_scope_unit( _read( f"/proc/{pid}/cgroup" ) or "" )
        pane                      = parse_tmux_pane( ( _read( f"/proc/{pid}/environ" ) or "" ).replace( "\0", "\n" ) )

        samples.append( Sample(
            pid          = pid,
            rss_kb       = rss_kb,
            cmdline      = argv,
            session_id   = owners.get( pid ),
            scope_unit   = scope_unit,
            tmux_session = resolve_tmux_session( pane ) or scope_session,
        ) )

    return samples


def run_once( tracker, emit, now=None ):
    """
    Sample once and emit a line for each process that deserves one.

    Requires:
        - tracker is an AlertTracker
        - emit is a callable taking one line

    Ensures:
        - returns the samples observed
        - emits at most one line per process per pass
    """

    samples   = collect_samples()
    timestamp = now or time.strftime( "%Y-%m-%dT%H:%M:%S%z" )

    tracker.forget_absent( { sample.pid for sample in samples } )

    for sample in samples:
        if tracker.should_alert( sample.pid, sample.rss_kb ):
            emit( format_alert_line( sample, tracker.threshold_kb, timestamp ) )

    return samples


def main( argv=None ):
    """
    CLI entry point.

    Ensures:
        - --once takes a single pass and exits; otherwise loops on --interval
        - exit code 0 on a clean pass, 1 on an unusable argument
    """

    import argparse
    import sys

    parser = argparse.ArgumentParser( description="Watch Claude Code sessions for runaway memory (row df5c3696)." )
    parser.add_argument( "--threshold-gb", type=float, default=DEFAULT_THRESHOLD_GB, help="alert above this RSS" )
    parser.add_argument( "--restep-gb",    type=float, default=DEFAULT_RESTEP_GB,    help="further growth before re-alerting" )
    parser.add_argument( "--interval",     type=float, default=DEFAULT_INTERVAL_SECONDS, help="seconds between samples" )
    parser.add_argument( "--log",          default=None, help="append alerts here as well as stdout" )
    parser.add_argument( "--once",         action="store_true", help="take one pass and exit" )
    parser.add_argument( "--report",       action="store_true", help="print every process seen, not just alerts" )

    args = parser.parse_args( argv )

    if args.threshold_gb <= 0:
        parser.error( "--threshold-gb must be positive" )

    tracker = AlertTracker(
        threshold_kb = int( args.threshold_gb * KB_PER_GB ),
        restep_kb    = int( args.restep_gb * KB_PER_GB ),
    )

    def emit( line ):

        print( line, flush=True )

        if args.log:
            with open( args.log, "a" ) as handle: handle.write( line + "\n" )

    while True:

        # ONE clock read per pass, shared by the alert lines and the report lines, so
        # a pass is a single instant in both streams rather than two nearby ones.
        # run_once already accepts the stamp; it was simply never passed, which is why
        # the report stream carried no time at all (row df5c3696, 2026-08-25).
        timestamp = time.strftime( "%Y-%m-%dT%H:%M:%S%z" )

        samples = run_once( tracker, emit, now=timestamp )

        if args.report:
            # THE STAMP IS WHAT MAKES THIS A MEASUREMENT RATHER THAN A TALLY. Without
            # it the stream yields per-process peaks and nothing else: no concurrency,
            # no growth curve, no "what else was running when this one climbed". 20.9h
            # of samples had already been collected that way before anyone noticed —
            # every line true, the whole file unable to answer the question it was
            # collected for. Lines from one pass share a stamp, so a pass groups by
            # equality and needs no separator or heuristic.
            for sample in sorted( samples, key=lambda s: -s.rss_kb ):
                print(
                    f"  ts={timestamp} "
                    f"pid={sample.pid} rss_gb={sample.rss_gb:6.2f} "
                    f"session={sample.session_id or 'unresolved'} "
                    f"tmux={sample.tmux_session or 'unresolved'}",
                    flush=True,
                )

        if args.once: return 0

        try:
            time.sleep( args.interval )
        except KeyboardInterrupt:
            return 0


if __name__ == "__main__":

    import sys
    sys.exit( main() )
