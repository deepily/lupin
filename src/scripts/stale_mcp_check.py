#!/usr/bin/env python3
"""
Find live cosa-voice MCP processes that are running code older than the tree.

WHY THIS RUNS OUTSIDE THE MCP. The in-process guard (row b5035039, merged 9f760b2a)
lives inside the process it judges, so a stale process runs a stale guard and sees
nothing. Only an outside reader can hold the process start time and the module mtimes
side by side. Prior art, cited rather than re-derived: Sam's instrument recorded on
row b5035039 (amendment 2026-09-16T00:55:57Z) — /proc start time against the mtimes of
cosa_voice_mcp.py, self_respin_observer.py and self_respin_core.py; three of eight live
processes stale at 20:31:57, validated live.

THE RULE. A process is STALE when it started before any watched module last changed.
Watched modules are resolved the way that process would import them: the script path
from its own argv (against its own cwd), the two imported modules from its own
PYTHONPATH, then the script's tree, then its own LUPIN_ROOT. A module found nowhere is
reported UNRESOLVED — never counted fresh.

WHAT IT DOES NOT CLAIM.
    - mtime newer means "the file changed after the process started", not "the process
      imported the changed code": self_respin_core is imported lazily, so a process that
      has never called self_respin would load current code on first call. It still
      flags — the check cannot see sys.modules from outside, and flagging is the safe side.
    - Boot time comes from now minus /proc/uptime (10ms resolution), NOT /proc/stat
      btime: btime is truncated to whole seconds, so a start built on it reads up to 1s
      early, and a live decoy launched 0.2s after its modules were written was falsely
      flagged STALE on 2026-09-16 21:53 (btime 1789565947 vs uptime-derived 1789565947.22).
      The residual error is the clock tick (10ms) plus the gap between reading the clock
      and reading uptime.
    - A process is recognised by argv shape only: a python interpreter whose argument
      is a path named cosa_voice_mcp.py, or `-m lupin_mcp.cosa_voice_mcp`. A launcher
      that hides that (a wrapper binary) is not counted.

REMEDY. A SEAT RESTART — exit claude in that pane and relaunch it. A /clear does NOT
reload the MCP: the MCP is a child of the pane's claude process and survives the clear.

READ-ONLY. It reads /proc, stats files and asks tmux to list panes. It never signals,
kills or restarts anything.

EXIT CODES (the interface a sweep or cron reads):
    0  every live MCP process measured and none is stale (zero processes is also 0;
       the report prints the denominator)
    1  at least one STALE process
    2  nothing trustworthy produced: /proc unreadable, or some module UNRESOLVED

USAGE:
    python3 src/scripts/stale_mcp_check.py          # text report
    python3 src/scripts/stale_mcp_check.py --json   # for the observer sweep
"""

import argparse
import datetime
import json
import os
import subprocess
import sys
import time

MCP_SCRIPT_NAME = "cosa_voice_mcp.py"
MCP_MODULE_NAME = "lupin_mcp.cosa_voice_mcp"

# relative to a tree's `src` directory; the first is the MCP script itself
WATCHED_MODULES = [
    "lupin_mcp/cosa_voice_mcp.py",
    "cosa/agents/heartbeat_arbiter/self_respin_observer.py",
    "lupin_mcp/self_respin_core.py",
]

REMEDY = (
    "Remedy: a SEAT RESTART — exit claude in that pane and relaunch it. "
    "A /clear does NOT reload the MCP: the MCP is a child of the pane's claude "
    "process and survives the clear."
)


# ---------------------------------------------------------------------------
# /proc readers — every one takes proc_root so tests can point at a fake tree
# ---------------------------------------------------------------------------

def read_boot_time( proc_root, now ):
    """
    Derive the boot time as now minus <proc_root>/uptime.

    Why not /proc/stat btime: it is truncated to whole seconds, which made a process
    started just after an edit read as started before it (see module docstring).

    Requires:
        - proc_root names a directory that may or may not exist
        - now is the current epoch time, read as close to this call as possible
    Ensures:
        - returns boot time as a float epoch, to the uptime file's 10ms resolution
    Raises:
        - OSError if the uptime file cannot be read
        - ValueError if its first field is not a number
    """
    with open( os.path.join( proc_root, "uptime" ) ) as fh:
        text = fh.read()
    fields = text.split()
    if not fields: raise ValueError( f"empty {proc_root}/uptime" )
    return now - float( fields[ 0 ] )


def read_stat( pid, proc_root ):
    """
    Parse ppid and starttime (clock ticks since boot) from <proc_root>/<pid>/stat.

    Requires:
        - pid is an int
    Ensures:
        - returns ( ppid, start_ticks ), or None if the process is gone or unreadable
        - a comm containing spaces or parens does not shift the fields
    """
    try:
        with open( os.path.join( proc_root, str( pid ), "stat" ) ) as fh:
            text = fh.read()
    except OSError:
        return None
    # fields after the LAST ")" start at field 3 (state); ppid is 4, starttime is 22
    rest = text[ text.rfind( ")" ) + 1 : ].split()
    return ( int( rest[ 1 ] ), int( rest[ 19 ] ) )


def read_cmdline( pid, proc_root ):
    """
    Read the argv of a process.

    Requires:
        - pid is an int
    Ensures:
        - returns a list of strings (empty for a kernel thread), or None if unreadable
    """
    try:
        with open( os.path.join( proc_root, str( pid ), "cmdline" ), "rb" ) as fh:
            raw = fh.read()
    except OSError:
        return None
    return [ part.decode( "utf-8", "replace" ) for part in raw.split( b"\0" ) if part ]


def read_environ( pid, proc_root ):
    """
    Read a process's environment.

    Requires:
        - pid is an int
    Ensures:
        - returns a dict, empty if the environ cannot be read (another user, gone)
    """
    try:
        with open( os.path.join( proc_root, str( pid ), "environ" ), "rb" ) as fh:
            raw = fh.read()
    except OSError:
        return {}
    env = {}
    for part in raw.split( b"\0" ):
        key, sep, value = part.decode( "utf-8", "replace" ).partition( "=" )
        if sep: env[ key ] = value
    return env


def read_cwd( pid, proc_root ):
    """
    Resolve a process's working directory.

    Requires:
        - pid is an int
    Ensures:
        - returns the cwd path, or None if unreadable
    """
    try:
        return os.readlink( os.path.join( proc_root, str( pid ), "cwd" ) )
    except OSError:
        return None


def ancestors( pid, proc_root ):
    """
    List the ancestor pids of a process, nearest first.

    Requires:
        - pid is an int
    Ensures:
        - excludes pid itself; stops at pid 1, at an unreadable parent, or on a cycle
    """
    chain = []
    seen  = { pid }
    cur   = pid
    while True:
        stat = read_stat( cur, proc_root )
        if stat is None: return chain
        ppid = stat[ 0 ]
        if ppid <= 1 or ppid in seen: return chain
        chain.append( ppid )
        seen.add( ppid )
        cur = ppid


def list_tmux_panes():
    """
    Ask tmux for every pane's shell pid.

    Requires:
        - nothing; tmux may be absent
    Ensures:
        - returns { pane_pid: ( session_name, pane_id ) }
        - returns {} when tmux is missing, has no server, or times out
        - read-only: `tmux list-panes` changes nothing
    """
    cmd = [ "tmux", "list-panes", "-a", "-F", "#{pane_pid}\t#{session_name}\t#{pane_id}" ]
    try:
        result = subprocess.run( cmd, capture_output=True, text=True, timeout=5 )
    except ( OSError, subprocess.SubprocessError ):
        return {}
    if result.returncode != 0: return {}
    panes = {}
    for line in result.stdout.splitlines():
        parts = line.split( "\t" )
        if len( parts ) != 3 or not parts[ 0 ].isdigit(): continue
        panes[ int( parts[ 0 ] ) ] = ( parts[ 1 ], parts[ 2 ] )
    return panes


# ---------------------------------------------------------------------------
# recognising and resolving an MCP process
# ---------------------------------------------------------------------------

def mcp_launch( argv, cwd ):
    """
    Decide whether argv launches the cosa-voice MCP, and with which script path.

    Requires:
        - argv is a list of strings; cwd is a path or None
    Ensures:
        - returns None when argv is not an MCP launch — including a process that only
          MENTIONS the name inside a longer argument (claude's prompt, `bash -c`)
        - returns ( True, script_path ) for the path form, resolved against cwd
        - returns ( True, None ) for `-m lupin_mcp.cosa_voice_mcp`
    """
    if not argv or not os.path.basename( argv[ 0 ] ).startswith( "python" ): return None
    for i, arg in enumerate( argv[ 1: ], start=1 ):
        if arg == "-m" and i + 1 < len( argv ) and argv[ i + 1 ] == MCP_MODULE_NAME:
            return ( True, None )
        if os.path.basename( arg ) == MCP_SCRIPT_NAME:
            path = arg if os.path.isabs( arg ) or cwd is None else os.path.join( cwd, arg )
            return ( True, os.path.normpath( path ) )
    return None


def resolve_modules( script_path, environ ):
    """
    Find the file each watched module would load from, for one process.

    Requires:
        - script_path is the MCP script's absolute path, or None for module form
        - environ is that process's environment dict
    Ensures:
        - returns ( resolved, unresolved ): resolved is a list of { rel, path }
        - the script entry is script_path itself when known, UNRESOLVED if it no
          longer exists
        - other entries search, in order: the process PYTHONPATH, the script's own
          `src` tree, the process LUPIN_ROOT/src; first existing file wins
    """
    search = [ p for p in environ.get( "PYTHONPATH", "" ).split( os.pathsep ) if p ]
    if script_path is not None:
        search.append( os.path.dirname( os.path.dirname( script_path ) ) )
    if environ.get( "LUPIN_ROOT" ):
        search.append( os.path.join( environ[ "LUPIN_ROOT" ], "src" ) )

    resolved   = []
    unresolved = []
    for rel in WATCHED_MODULES:
        if rel == WATCHED_MODULES[ 0 ] and script_path is not None:
            # a script deleted since launch (a reaped worktree) cannot be measured
            if os.path.isfile( script_path ): resolved.append( { "rel": rel, "path": script_path } )
            else: unresolved.append( rel )
            continue
        hit = next( ( os.path.join( d, rel ) for d in search if os.path.isfile( os.path.join( d, rel ) ) ), None )
        if hit is None: unresolved.append( rel )
        else: resolved.append( { "rel": rel, "path": hit } )
    return ( resolved, unresolved )


# ---------------------------------------------------------------------------
# the census
# ---------------------------------------------------------------------------

def census( proc_root="/proc", self_pid=None, pane_lister=None, clk_tck=None, now=None ):
    """
    Measure every live cosa-voice MCP process against the files it loaded.

    Requires:
        - proc_root is a readable proc-format directory
        - now, when given, is the current epoch time (default: time.time())
    Ensures:
        - returns one record per MCP process, sorted by pid, each carrying
          pid, start_epoch, cwd, script, pane_pid, tmux_session, tmux_pane,
          modules (each with mtime), newer_modules, unresolved, stale
        - excludes self_pid (default: this process) and all of its ancestors, so the
          census never counts itself or the shell that launched it
        - a process that exits mid-census is skipped
        - stale is True iff some resolved module's mtime is later than start_epoch
    Raises:
        - OSError / ValueError if proc_root carries no readable uptime
    """
    self_pid    = os.getpid() if self_pid is None else self_pid
    pane_lister = list_tmux_panes if pane_lister is None else pane_lister
    clk_tck     = os.sysconf( "SC_CLK_TCK" ) if clk_tck is None else clk_tck
    now         = time.time() if now is None else now
    boot_time   = read_boot_time( proc_root, now )
    excluded    = { self_pid, *ancestors( self_pid, proc_root ) }
    panes       = None

    records = []
    for name in sorted( os.listdir( proc_root ), key=lambda n: ( len( n ), n ) ):
        if not name.isdigit(): continue
        pid = int( name )
        if pid in excluded: continue
        argv = read_cmdline( pid, proc_root )
        if argv is None: continue
        cwd    = read_cwd( pid, proc_root )
        launch = mcp_launch( argv, cwd )
        if launch is None: continue
        stat = read_stat( pid, proc_root )
        if stat is None: continue

        start_epoch = boot_time + stat[ 1 ] / clk_tck
        environ     = read_environ( pid, proc_root )
        script      = launch[ 1 ]
        resolved, unresolved = resolve_modules( script, environ )

        modules = []
        for mod in resolved:
            mtime = os.stat( mod[ "path" ] ).st_mtime
            modules.append( { "rel": mod[ "rel" ], "path": mod[ "path" ], "mtime": mtime, "newer": mtime > start_epoch } )

        if panes is None: panes = pane_lister()
        pane_pid = next( ( a for a in ancestors( pid, proc_root ) if a in panes ), None )
        session, pane_id = panes[ pane_pid ] if pane_pid is not None else ( None, environ.get( "TMUX_PANE" ) )

        newer = [ m for m in modules if m[ "newer" ] ]
        records.append( {
            "pid"           : pid,
            "start_epoch"   : start_epoch,
            "cwd"           : cwd,
            "script"        : script,
            "pane_pid"      : pane_pid,
            "tmux_session"  : session,
            "tmux_pane"     : pane_id,
            "modules"       : modules,
            "newer_modules" : newer,
            "unresolved"    : unresolved,
            "stale"         : bool( newer ),
        } )
    return sorted( records, key=lambda r: r[ "pid" ] )


def format_epoch( epoch ):
    """
    Render an epoch as local wall-clock time.

    Requires:
        - epoch is a number
    Ensures:
        - returns "YYYY-MM-DD HH:MM:SS" in local time
    """
    return datetime.datetime.fromtimestamp( epoch ).strftime( "%Y-%m-%d %H:%M:%S" )


def render_text( records ):
    """
    Render the census for a human.

    Requires:
        - records came from census()
    Ensures:
        - first line states the denominator: processes, stale, unmeasured
        - each stale process names pid, start time, pane pid, tmux session and pane, cwd,
          and every newer module with its mtime
        - the SEAT RESTART remedy is printed iff something is stale
    """
    stale = [ r for r in records if r[ "stale" ] ]
    unmet = [ r for r in records if r[ "unresolved" ] ]
    lines = [ f"{len( records )} live {MCP_SCRIPT_NAME} process(es), {len( stale )} stale, {len( unmet )} unmeasured" ]
    for r in records:
        verdict = "STALE" if r[ "stale" ] else "fresh"
        lines.append(
            f"  {verdict:5} pid {r[ 'pid' ]}  started {format_epoch( r[ 'start_epoch' ] )}"
            f"  pane_pid {r[ 'pane_pid' ]}  tmux {r[ 'tmux_session' ]} {r[ 'tmux_pane' ]}  cwd {r[ 'cwd' ]}"
        )
        for m in r[ "newer_modules" ]:
            lines.append( f"          changed after start: {m[ 'rel' ]} @ {format_epoch( m[ 'mtime' ] )}" )
        for rel in r[ "unresolved" ]:
            lines.append( f"          UNRESOLVED (not measured): {rel}" )
    if stale: lines.append( REMEDY )
    return "\n".join( lines )


def exit_code( records ):
    """
    Map a census to the exit-code contract.

    Requires:
        - records came from census()
    Ensures:
        - 1 if any record is stale; else 2 if any has an unresolved module; else 0
    """
    if any( r[ "stale" ] for r in records ): return 1
    if any( r[ "unresolved" ] for r in records ): return 2
    return 0


def main( argv, proc_root=None, clk_tck=None, now=None ):
    """
    Run the census and print the report.

    Requires:
        - argv is the argument list without the program name
    Ensures:
        - prints text, or JSON with --json, to stdout
        - returns the exit_code() contract; returns 2 with a stderr line if /proc
          cannot be read
    """
    parser = argparse.ArgumentParser( description="Flag cosa-voice MCP processes older than their code." )
    parser.add_argument( "--json", action="store_true", help="machine-readable output" )
    parser.add_argument( "--proc-root", default="/proc", help=argparse.SUPPRESS )
    args = parser.parse_args( argv )
    root = proc_root if proc_root is not None else args.proc_root

    try:
        records = census( proc_root=root, clk_tck=clk_tck, now=now )
    except ( OSError, ValueError ) as exc:
        print( f"stale_mcp_check: cannot read {root}: {exc}", file=sys.stderr )
        return 2

    if args.json:
        print( json.dumps( {
            "processes"   : records,
            "stale_count" : sum( 1 for r in records if r[ "stale" ] ),
            "remedy"      : REMEDY,
        }, indent=2 ) )
    else:
        print( render_text( records ) )
    return exit_code( records )


if __name__ == "__main__":
    sys.exit( main( sys.argv[ 1: ] ) )
