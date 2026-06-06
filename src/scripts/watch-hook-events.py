#!/usr/bin/env python3
"""
Live watcher for the Claude Code hook event stream
(`io/claude_code_hooks/logs/hook-events.jsonl`).

Tails the JSONL stream (`tail -f` style) and pretty-prints each entry, with
special highlighting for the per-Stop **heartbeat oracle** line (added
2026-06-05) so you can watch the fleet's heartbeat state update in real time:

    HH:MM:SS  🫀 Tiberius      not_owed     owed=False(0)  poke=0/3
    HH:MM:SS  🫀 Tiffany       poke         owed=True(2)   poke=1/3
    HH:MM:SS  🫀 Rachel        honored      owed=True      poke=0/3  awaiting=peer:Maria
    HH:MM:SS  🫀 Mr. Radio     cap_reached  owed=True(1)   poke=3/3   ← stuck

Outcome legend (the four heartbeat states):
    not_owed     idle & FREE      (reassignable)        — green
    poke         owed, nudged     (working)             — yellow
    honored      blocked on a peer                      — cyan
    cap_reached  owed but pokes spent (idle & STUCK)    — red

Usage:
    python src/scripts/watch-hook-events.py                 # follow heartbeat lines (default)
    python src/scripts/watch-hook-events.py --all           # follow EVERY hook entry, not just heartbeat
    python src/scripts/watch-hook-events.py --replay         # print existing history first, then follow
    python src/scripts/watch-hook-events.py --no-color       # plain text (also auto-off when piped)
    python src/scripts/watch-hook-events.py --once           # print current contents and exit (no follow)

Requires: nothing beyond the stdlib. LUPIN_ROOT is honored for path resolution;
falls back to the repo this script lives in.
"""
import argparse
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path


# ── Path resolution (no sys.path / cosa import needed — pure stdlib utility) ──
def _project_root():
    env = os.environ.get( "LUPIN_ROOT" )
    if env:
        return Path( env )
    # This file lives at <root>/src/scripts/watch-hook-events.py
    return Path( __file__ ).resolve().parents[ 2 ]


LOG_PATH = _project_root() / "io" / "claude_code_hooks" / "logs" / "hook-events.jsonl"


# ── Colours ──────────────────────────────────────────────────────────────────
class C:
    RESET  = "\033[0m"
    DIM    = "\033[2m"
    BOLD   = "\033[1m"
    RED    = "\033[31m"
    GREEN  = "\033[32m"
    YELLOW = "\033[33m"
    CYAN   = "\033[36m"
    GREY   = "\033[90m"
    WHITE  = "\033[97m"


OUTCOME_STYLE = {
    "not_owed"    : ( C.GREEN,  "idle & free"  ),
    "poke"        : ( C.YELLOW, "working"      ),
    "honored"     : ( C.CYAN,   "blocked"      ),
    "cap_reached" : ( C.RED,    "idle & STUCK" ),
    "idle"        : ( C.GREEN,  "idle beacon"  ),
}

_HEARTBEAT_PHASES = (
    "heartbeat_oracle", "heartbeat_emit_error", "heartbeat_report_error",
    "heartbeat_cap_reached", "heartbeat_idle_emit_error", "heartbeat_settings_invalid",
)


def _no_color():
    # Disabled explicitly, or when stdout is not a TTY (piped / redirected).
    return _ARGS.no_color or not sys.stdout.isatty()


def _c( color, text ):
    if _no_color():
        return text
    return f"{color}{text}{C.RESET}"


def _hhmmss( ts ):
    """Best-effort HH:MM:SS from the entry's `ts` field.

    Handles ISO (`2026-06-06T01:45:55...`) AND the project's hook-log format
    (`2026.06.06 @ 01:45 55,752ms` → `01:45:55`).
    """
    if not ts:
        return "--:--:--"
    s = str( ts )
    try:
        return datetime.fromisoformat( s.replace( "Z", "+00:00" ) ).strftime( "%H:%M:%S" )
    except ValueError:
        pass
    # Project format: "<date> @ HH:MM SS,mmmms"
    try:
        after = s.split( "@", 1 )[ 1 ].strip()          # "01:45 55,752ms"
        parts = after.split()
        hm    = parts[ 0 ]                               # "01:45"
        if ":" in hm:
            ss = "00"
            if len( parts ) > 1:
                digits = "".join( ch for ch in parts[ 1 ] if ch.isdigit() )
                ss = ( digits[ :2 ] or "00" )
            return f"{hm}:{ss.zfill( 2 )}"
    except ( IndexError, ValueError ):
        pass
    return s[ :8 ]


def _format_oracle( e ):
    """The headline heartbeat-oracle line."""
    outcome       = e.get( "outcome", "?" )
    color, label  = OUTCOME_STYLE.get( outcome, ( C.WHITE, "?" ) )
    persona       = e.get( "persona" ) or ( e.get( "session_id", "" )[ :8 ] or "unknown" )
    work_owed     = e.get( "work_owed" )
    owed_items    = e.get( "owed_items" )
    owed_str      = f"{work_owed}" + ( f"({owed_items})" if owed_items is not None else "" )
    poke          = f"{e.get( 'poke_count', '?' )}/{e.get( 'cap', '?' )}"
    awaiting      = e.get( "awaiting" )
    tail          = f"  awaiting={awaiting}" if awaiting else ""
    stuck         = _c( C.RED + C.BOLD, "  ← STUCK" ) if outcome == "cap_reached" else ""

    line = (
        f"{_c( C.GREY, _hhmmss( e.get( 'ts' ) ) )}  "
        f"🫀 {_c( C.BOLD, f'{persona:<14}' )} "
        f"{_c( color, f'{outcome:<12}' )} "
        f"{_c( C.DIM, f'({label})' ):<14} "
        f"owed={owed_str:<9} poke={poke}{tail}{stuck}"
    )
    return line


def _format_generic( e ):
    """Any non-oracle hook entry — a compact dim one-liner."""
    phase   = e.get( "phase", "" )
    hook    = e.get( "hook", "" )
    event   = e.get( "event", "" )
    sid     = e.get( "session_id", "" )
    tool    = e.get( "tool", "" )
    err     = e.get( "error", "" )
    bits    = [ b for b in ( phase or event, hook, sid, tool ) if b ]
    body    = "  ".join( str( b ) for b in bits )
    if err:
        body += f"  {_c( C.RED, 'error=' + str( err ) )}"
    # Heartbeat-family non-oracle lines (errors etc.) get a faint heart.
    marker  = "🫀" if ( phase or "" ).startswith( "heartbeat" ) else " ·"
    return f"{_c( C.GREY, _hhmmss( e.get( 'ts' ) ) )}  {marker} {_c( C.DIM, body )}"


def _render( raw_line ):
    raw_line = raw_line.strip()
    if not raw_line:
        return None
    try:
        e = json.loads( raw_line )
    except json.JSONDecodeError:
        return _c( C.GREY, raw_line )  # show the raw line rather than swallow it

    phase = e.get( "phase", "" )
    if phase == "heartbeat_oracle":
        return _format_oracle( e )
    if _ARGS.all or phase in _HEARTBEAT_PHASES:
        return _format_generic( e )
    return None  # filtered out (non-heartbeat) unless --all


def _emit( raw_line ):
    out = _render( raw_line )
    if out is not None:
        print( out, flush=True )


def _print_existing():
    if not LOG_PATH.exists():
        return
    with open( LOG_PATH, "r" ) as f:
        for raw in f:
            _emit( raw )


def _follow():
    """Tail -f with rotation/truncation handling. Ctrl-C to stop."""
    print( _c( C.CYAN, f"▶ watching {LOG_PATH}" ) )
    print( _c( C.DIM, "  outcomes: not_owed=free  poke=working  honored=blocked  cap_reached=STUCK   (Ctrl-C to stop)\n" ) )
    while True:
        while not LOG_PATH.exists():
            time.sleep( 0.5 )
        with open( LOG_PATH, "r" ) as f:
            if not _ARGS.replay:
                f.seek( 0, os.SEEK_END )      # start at the tail; skip history
            try:
                inode = os.fstat( f.fileno() ).st_ino
            except OSError:
                inode = None
            while True:
                raw = f.readline()
                if raw:
                    _emit( raw )
                    continue
                time.sleep( 0.3 )
                # Rotation/truncation check → break to reopen.
                try:
                    st = LOG_PATH.stat()
                    if ( inode is not None and st.st_ino != inode ) or st.st_size < f.tell():
                        break
                except OSError:
                    break


def main():
    global _ARGS
    parser = argparse.ArgumentParser( description="Live watcher for the Claude Code hook event stream." )
    parser.add_argument( "--all",      action="store_true", help="show EVERY hook entry, not just heartbeat lines" )
    parser.add_argument( "--replay",   action="store_true", help="print existing history first, then follow" )
    parser.add_argument( "--once",     action="store_true", help="print current contents and exit (no follow)" )
    parser.add_argument( "--no-color", action="store_true", help="disable ANSI colour" )
    parser.add_argument( "--path",     default=None,        help="override the log path" )
    _ARGS = parser.parse_args()

    if _ARGS.path:
        global LOG_PATH
        LOG_PATH = Path( _ARGS.path )

    try:
        if _ARGS.once:
            _print_existing()
        else:
            _follow()
    except KeyboardInterrupt:
        print( _c( C.DIM, "\n■ stopped." ) )


_ARGS = None
if __name__ == "__main__":
    main()
