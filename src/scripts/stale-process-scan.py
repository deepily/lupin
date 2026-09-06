#!/usr/bin/env python3
"""
stale-process-scan.py — link 2 of the delivery chain, made loud.

WHY THIS EXISTS (row d2dd3ee3). The delivery chain is
`committed -> merged -> respawned -> cache-busted`. `delivery-collision-scan.py`
watches the first link. `test_task_body_overlay_cache_bust.py` watches the third.
**NOTHING watched the second**, and it was found by hand twice on 2026-09-05:
listeners pin their tree at boot, so a merge changes the file on disk and the
running process keeps the module it imported at startup. A saved file is not a
served file, and a merged file is not a running file.

Measured before this was written: no script, no test, and no route in the tree
detects it. The two commits that mention the symptom (`ceeab632`, `e9ade49e`)
fix instances; neither detects the class.

🔴 THE DESIGN IS SHAPED BY THE DEFECT IN MY OWN FIRST MEASUREMENT, AND THAT IS THE
POINT OF THE FILE. A start-time-versus-commit-time comparison is the obvious
instrument and it is NOT SUFFICIENT. Run on 2026-09-05 it flagged three MCP
subprocesses as stale. **All three were false.** The three commits behind them
touched exactly one file, `src/lupin_mcp/fleet_cap_admission.py`, which NOTHING in
the tree imports — it runs as a fresh subprocess per launch. The screen was
correct about the timestamps and wrong about the world.

⇒ So this scan runs TWO stages and reports a process stale only if BOTH fire:

    STAGE 1  TIMING       did a commit touching this process's tree land AFTER
                          the process started?
    STAGE 2  REACHABILITY is a changed module actually IMPORTED, transitively,
                          from the entry point this process is running?

Stage 1 alone over-reports. Stage 2 alone cannot tell you anything about
freshness. Reporting on stage 1 only is how a scan cries wolf on its first day
and gets switched off — the same failure the collision scan avoids by refusing
ancestry.

EXIT CODES — three, so two failure modes wanting opposite remedies never share
one (the local precedent is `purge-pycache.sh`, and `delivery-collision-scan.py`
uses the same contract):

    0  scanned, nothing stale        — a real all-clear
    1  STALE: a process is running superseded code
    2  REFUSED, nothing was scanned  — say so, never report clean

⚠️ WHAT IT CANNOT SEE, STATED HERE RATHER THAN DISCOVERED LATER:
  · **Unmerged work is invisible to it.** It compares against commits that LANDED.
    A fix stranded on a branch cannot make a process stale, because the process was
    never going to have it. That is link 1's job, and link 1 has its own scan.
  · **Lazy imports move the boundary.** `cosa_voice_mcp.py` does
    `from lupin_mcp import session_spawner` INSIDE a function, so that module is
    read at CALL time and picks up post-start merges. Stage 2 walks static imports
    and counts a function-level import as reachable, which OVER-reports for exactly
    this shape. The direction is deliberate: a false "check this" is cheaper than a
    false all-clear.
  · It reports; it restarts nothing. Bouncing shared infrastructure while jobs run
    is outside any standing authority.
"""

import argparse
import ast
import os
import subprocess
import sys
import time
from pathlib import Path

# Derived from THIS FILE, never from $LUPIN_ROOT — commit 5e7f74e8 removed exactly
# that steering from purge-pycache.sh after it cleaned the main checkout from
# inside a worktree and printed its success banner.
REPO_ROOT = Path( __file__ ).resolve().parents[ 2 ]

# Long-lived process classes and the entry module each one actually runs. The entry
# point is what makes stage 2 possible: reachability is meaningless without a root
# to walk from.
KNOWN_CLASSES = [
    # ( substring found in the process cmdline, human label, entry module path )
    ( "lupin_arbiter_app",        "arbiter :8001",  "src/lupin_arbiter_app/app.py" ),
    ( "lupin_app.main",           "lupin server",   "src/lupin_app/main.py" ),
    ( "cosa_voice_mcp",           "cosa-voice MCP", "src/lupin_mcp/cosa_voice_mcp.py" ),
    ( "cc_notification_listener", "CC listener",
      "src/lupin_cli/claude_code/hooks/lib/cc_notification_listener.py" ),
]

# 🔴 THE CMDLINE CANNOT TELL :7999 FROM :8000, AND A LIVE CONTROL IS WHAT REVEALED IT.
# Both containers run the byte-identical `python3 -m lupin_app.main`. On 2026-09-05 the
# dev server was bounced while this scan was being written; the scan was expected to drop
# it and did not appear to. Investigating rather than assuming showed the DETECTION was
# right and the LABEL was wrong: the fresh :7999 (pid 3067711, up 1 min) had correctly
# dropped out, and what remained was :8000 (pid 3348, up 5h) wearing the ":7999" label.
#
# A wrong label on a correct finding is worse than a wrong finding, because the reader
# goes and bounces the wrong server — and the one they bounce comes back clean, which
# reads as confirmation. So the container name is resolved from the process's own cgroup
# rather than guessed from its arguments.
CONTAINER_LABELS = {
    "lupin-rest-dev"  : ":7999 dev",
    "lupin-rest-test" : ":8000 test",
}

PY_COMM = ( "python", "python3", "python3.13" )


def _git( *args ):
    """
    Run git in REPO_ROOT and return stdout.

    Ensures:
        - returns stdout as str, empty on failure
    """
    return subprocess.run(
        [ "git", "-C", str( REPO_ROOT ), *args ], capture_output=True, text=True
    ).stdout


def running_processes():
    """
    Long-lived python processes executing code from a lupin tree.

    🔴 IDENTIFIED BY `/proc/<pid>/comm`, NEVER BY THE COMMAND LINE. A Claude seat's
    entire spawn briefing is its argv, so a `pgrep -f` for a module name matches
    every seat whose instructions merely DISCUSS that module. Measured 2026-08-29:
    a `pgrep -f pytest` gate matched three live seats that were only reading about
    testing. `comm` answers what a process IS; argv answers what someone wrote
    about it.

    Ensures:
        - returns [ { pid, comm, cwd, root, started, cmdline }, ... ]
        - excludes processes whose cwd is outside a lupin tree
    """
    found = []
    for entry in os.listdir( "/proc" ):
        if not entry.isdigit(): continue
        pid = entry
        try:
            comm = Path( f"/proc/{pid}/comm" ).read_text().strip()
            if comm not in PY_COMM: continue
            cwd = os.readlink( f"/proc/{pid}/cwd" )
            if "lupin" not in cwd and "cosa" not in cwd: continue
            environ = Path( f"/proc/{pid}/environ" ).read_bytes().decode( "utf-8", "replace" )
            cmdline = Path( f"/proc/{pid}/cmdline" ).read_bytes().decode( "utf-8", "replace" )
            started = os.stat( f"/proc/{pid}" ).st_mtime
        except ( OSError, PermissionError ):
            # A process that exits mid-scan is not an error — it is the normal case
            # on a busy box. Skipping it is correct; crashing on it would make the
            # scan fail more often the busier the machine is.
            continue

        root = ""
        for line in environ.split( "\x00" ):
            if line.startswith( "LUPIN_ROOT=" ):
                root = line.split( "=", 1 )[ 1 ]
                break

        found.append( {
            "pid"     : pid,
            "comm"    : comm,
            "cwd"     : cwd,
            "root"    : root,
            "started" : started,
            "cmdline" : cmdline.replace( "\x00", " " ).strip(),
        } )
    return found


def _container_of( pid ):
    """
    The docker container name this pid runs in, from its own cgroup.

    Ensures:
        - returns the container name, or None when the pid is not containerised,
          docker is unavailable, or the id does not resolve
        - NEVER guesses: an unresolved container yields None so the caller can say
          "unknown" rather than print a confident wrong name
    """
    try:
        cgroup = Path( f"/proc/{pid}/cgroup" ).read_text()
    except OSError:
        return None
    marker = "docker-"
    if marker not in cgroup: return None
    container_id = cgroup.split( marker, 1 )[ 1 ].split( ".scope" )[ 0 ][ :12 ]
    if not container_id: return None
    listing = subprocess.run(
        [ "docker", "ps", "--no-trunc", "--format", "{{.ID}}\t{{.Names}}" ],
        capture_output=True, text=True
    )
    if listing.returncode != 0: return None
    for line in listing.stdout.splitlines():
        if "\t" not in line: continue
        cid, name = line.split( "\t", 1 )
        if cid.startswith( container_id ): return name.strip()
    return None


def classify( proc ):
    """
    Which known long-lived class is this, if any?

    Two processes can run the byte-identical command line in different containers
    (:7999 and :8000 both run `python3 -m lupin_app.main`), so the container is
    resolved from the process's own cgroup and appended to the label. See the note
    on CONTAINER_LABELS for the live control that caught this.

    Ensures:
        - returns ( label, entry_module ) or ( None, None ) for anything transient
        - a containerised process carries its venue in the label; an unresolved
          container is labelled "container?" rather than silently mislabelled
    """
    for needle, label, entry in KNOWN_CLASSES:
        if needle not in proc[ "cmdline" ]: continue
        container = _container_of( proc[ "pid" ] )
        if container is not None:
            label = f"{label} [{CONTAINER_LABELS.get( container, container )}]"
        elif "docker-" in _safe_cgroup( proc[ "pid" ] ):
            label = f"{label} [container?]"
        return label, entry
    return None, None


def _safe_cgroup( pid ):
    """Read a pid's cgroup, returning '' rather than raising for a vanished process."""
    try:
        return Path( f"/proc/{pid}/cgroup" ).read_text()
    except OSError:
        return ""


def _module_to_path( module ):
    """
    Map a dotted module name to a repo-relative source path, if it is ours.

    Ensures:
        - returns "src/<a>/<b>.py" or "src/<a>/<b>/__init__.py" when it exists
        - returns None for stdlib and third-party modules
    """
    rel = Path( "src" ) / Path( *module.split( "." ) )
    for candidate in ( rel.with_suffix( ".py" ), rel / "__init__.py" ):
        if ( REPO_ROOT / candidate ).is_file(): return str( candidate )
    return None


def reachable_modules( entry_path, max_files=4000 ):
    """
    Every in-repo module transitively imported from entry_path.

    STAGE 2, AND THE REASON THIS SCAN IS NOT A CRY-WOLF. Walks the static import
    graph with `ast`, following only modules that resolve to files inside this
    repo. A changed file outside this set cannot affect the process, however
    recently it landed — which is precisely the case that made all three of my
    first measurement's flags false.

    ⚠️ It counts a FUNCTION-LEVEL import as reachable. Those are read at call time,
    so such a module may already be fresh in a running process. That over-reports,
    deliberately: a false "go and check" costs a minute, a false all-clear costs a
    day of chasing a fix that was never running.

    Requires:
        - entry_path is repo-relative and exists

    Ensures:
        - returns a set of repo-relative paths, including entry_path itself
        - terminates on cycles and stops at max_files
    """
    seen    = set()
    pending = [ entry_path ]
    while pending and len( seen ) < max_files:
        current = pending.pop()
        if current in seen: continue
        seen.add( current )
        try:
            tree = ast.parse( ( REPO_ROOT / current ).read_text( encoding="utf-8" ) )
        except ( OSError, SyntaxError, UnicodeDecodeError ):
            continue
        for node in ast.walk( tree ):
            names = []
            if isinstance( node, ast.Import ):
                names = [ alias.name for alias in node.names ]
            elif isinstance( node, ast.ImportFrom ) and node.module and node.level == 0:
                names = [ node.module ] + [ f"{node.module}.{a.name}" for a in node.names ]
            for name in names:
                path = _module_to_path( name )
                if path and path not in seen: pending.append( path )
    return seen


def changed_since( started, paths ):
    """
    Files among `paths` that a commit touched after `started`.

    Ensures:
        - returns { path: newest_sha } for paths with a commit newer than started
    """
    changed = {}
    since   = f"@{int( started )}"
    out     = _git( "log", "--no-merges", f"--since={since}", "--format=%x00%H", "--name-only", "HEAD" )
    touched = {}
    sha     = None
    for line in out.splitlines():
        if line.startswith( "\x00" ):
            sha = line[ 1: ].strip()
        elif line.strip() and sha:
            touched.setdefault( line.strip(), sha )
    for path in paths:
        if path in touched: changed[ path ] = touched[ path ]
    return changed


def scan( min_age_seconds=0.0 ):
    """
    Find long-lived processes running superseded code.

    Ensures:
        - returns ( stale, stats ); stale maps pid -> details for BOTH-stage hits

    Raises:
        - LookupError when zero classified processes are found. An empty scan
          passes every per-item check, so it must refuse rather than report clean.
    """
    procs      = running_processes()
    classified = []
    for proc in procs:
        label, entry = classify( proc )
        if label is None: continue
        if time.time() - proc[ "started" ] < min_age_seconds: continue
        classified.append( ( proc, label, entry ) )

    if not classified:
        raise LookupError(
            f"{len( procs )} python processes seen on a lupin tree, but ZERO matched a "
            "known long-lived class. Nothing was scanned; this is not an all-clear."
        )

    stale        = {}
    n_timing     = 0
    for proc, label, entry in classified:
        reachable = reachable_modules( entry )
        changed   = changed_since( proc[ "started" ], reachable )
        if not changed: continue
        n_timing += 1
        # Both stages fired: something reachable from this entry point changed after
        # the process started. Stage 2 is already applied — `reachable` IS the filter.
        stale[ proc[ "pid" ] ] = {
            "label"     : label,
            "entry"     : entry,
            "started"   : proc[ "started" ],
            "root"      : proc[ "root" ],
            "changed"   : changed,
            "reachable" : len( reachable ),
        }

    stats = {
        "python_on_lupin" : len( procs ),
        "classified"      : len( classified ),
        "both_stages"     : len( stale ),
    }
    return stale, stats


def main( argv=None ):
    """
    Report stale long-lived processes and exit 0 / 1 / 2.

    Ensures:
        - prints its denominators on every run, clean or not
    """
    parser = argparse.ArgumentParser( description="find processes running superseded code" )
    parser.add_argument( "--min-age-seconds", type=float, default=60.0,
                         help="ignore processes younger than this (a just-started one is fresh)" )
    args = parser.parse_args( argv )

    try:
        stale, stats = scan( args.min_age_seconds )
    except LookupError as refusal:
        print( f"REFUSED: {refusal}", file=sys.stderr )
        print( "exit 2 — nothing was scanned. Do not read this as a clean run.", file=sys.stderr )
        return 2

    # A scan that cannot state its own denominator is telling you about its corpus,
    # not about your fleet — so this prints on a clean run too.
    print( "stale-process scan" )
    print( "  python processes on a lupin tree {python_on_lupin} · "
           "classified as long-lived {classified} · STALE {both_stages}".format( **stats ) )

    if not stale: return 0

    print()
    print( "🔴 RUNNING CODE OLDER THAN A MERGE IT DEPENDS ON:" )
    for pid, info in sorted( stale.items(), key=lambda kv: kv[ 1 ][ "started" ] ):
        age = ( time.time() - info[ "started" ] ) / 3600
        print( f"  pid {pid}  {info[ 'label' ]}  up {age:.1f}h  "
               f"({info[ 'reachable' ]} modules reachable from {info[ 'entry' ]})" )
        for path, sha in sorted( info[ "changed" ].items() ):
            print( f"      {sha[ :8 ]}  {path}" )
    print()
    print( "These processes imported their modules at startup. The file on disk changed;" )
    print( "the running code did not. Respawn them, or the merge reached the tree and no further." )
    return 1


if __name__ == "__main__":
    sys.exit( main() )
