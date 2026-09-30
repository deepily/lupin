"""
Lupin LoC roll-up: added / deleted / net, two views.

View A — release chain: the 18 squash-merge commits on `main`, one per release.
View B — authoring: monthly adds/deletes across ALL branches with the squash
         merges excluded, so feature-branch work is counted once, not twice.

Writes two PNGs plus a CSV of both series.
"""

import subprocess
import collections
import csv
import os

import matplotlib
matplotlib.use( "Agg" )
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter

REPO    = "/mnt/DATA01/include/www.deepily.ai/projects/lupin"
OUT_DIR = os.path.join( REPO, "io", "git-delta-analysis" )

# Paths that are generated, vendored, or data — never hand-authored.
EXCLUDE_PREFIXES = (
    "src/ephemera/",
    "src/lupin_app/static/lupin-mobile-test/",
    "io/",
    "node_modules/",
)
EXCLUDE_SUFFIXES = (
    "package-lock.json", "uv.lock", ".min.js", ".golden.json",
    "src/docs/fastapi/api.json", "src/docs/fastapi/api.md",
)


def git( *args ):
    """
    Run a git command in the Lupin repo and return its stdout.

    Requires:
        - args is a non-empty sequence of git arguments

    Ensures:
        - returns decoded stdout with trailing newline stripped
    """
    return subprocess.run(
        [ "git", "-C", REPO ] + list( args ),
        capture_output=True, text=True, check=True
    ).stdout.rstrip( "\n" )


def counted( path ):
    """
    Decide whether a path counts as hand-authored work.

    Ensures:
        - returns False for generated, vendored, or data artifacts
        - returns True otherwise
    """
    if path.startswith( EXCLUDE_PREFIXES ): return False
    if path.endswith( EXCLUDE_SUFFIXES ):   return False
    return True


def commit_delta( sha ):
    """
    Compute (added, deleted) for one commit, excluding generated artifacts.

    Ensures:
        - binary rows ('-' in numstat) contribute zero
        - returns a two-tuple of non-negative ints
    """
    out = git( "show", "--numstat", "--format=", sha )
    added = deleted = 0
    for line in out.splitlines():
        parts = line.split( "\t" )
        if len( parts ) != 3: continue
        a, d, path = parts
        if a == "-" or d == "-":  continue
        if not counted( path ):   continue
        added   += int( a )
        deleted += int( d )
    return added, deleted


def main():
    """
    Run both views, write the two PNGs and the CSV, and print the summary tables.

    THIS USED TO BE MODULE-LEVEL CODE, so merely IMPORTING this file ran a full
    `git log` over every branch, rendered two charts and wrote three files into
    io/git-delta-analysis/. Nothing imported it, so nothing noticed — but it also
    meant the file could not be unit-tested at all without doing all of that for
    real, which is a persistent-state mutation and a :8000-class action. Wrapping
    it changes nothing about running the script; it only makes importing it free.

    Ensures:
        - writes lupin-loc-by-release.png, lupin-loc-by-month.png and
          lupin-loc-rollup.csv under OUT_DIR, creating it if absent
        - returns the ( releases, monthly ) pair so a caller can assert on the
          numbers without re-parsing the CSV
    """
    # ---------------------------------------------------------------- View A
    main_shas = git( "log", "main", "--format=%H|%ad|%s", "--date=short" ).splitlines()
    releases  = []
    for row in reversed( main_shas ):          # oldest first
        sha, date, subject = row.split( "|", 2 )
        added, deleted = commit_delta( sha )
        releases.append( {
            "date"    : date,
            "sha"     : sha[ :8 ],
            "subject" : subject,
            "added"   : added,
            "deleted" : deleted,
            "net"     : added - deleted,
        } )

    squash_shas = { row.split( "|", 1 )[ 0 ] for row in main_shas }

    # ---------------------------------------------------------------- View B
    all_rows = git( "log", "--all", "--no-merges", "--format=%H|%ad", "--date=short" ).splitlines()
    monthly  = collections.defaultdict( lambda: { "added": 0, "deleted": 0, "commits": 0 } )
    for row in all_rows:
        sha, date = row.split( "|" )
        if sha in squash_shas: continue        # the double-count
        added, deleted = commit_delta( sha )
        bucket = monthly[ date[ :7 ] ]
        bucket[ "added"   ] += added
        bucket[ "deleted" ] += deleted
        bucket[ "commits" ] += 1

    months = sorted( monthly.keys() )

    # ---------------------------------------------------------------- output
    os.makedirs( OUT_DIR, exist_ok=True )
    thousands = FuncFormatter( lambda v, _: f"{v/1000:,.0f}k" if abs( v ) >= 1000 else f"{v:.0f}" )

    # --- Chart 1: release chain
    fig, ax = plt.subplots( figsize=( 15, 8 ) )
    labels  = [ f"{r['date']}\n{r['subject'][:28]}" for r in releases ]
    x       = range( len( releases ) )
    ax.bar( x, [  r[ "added"   ] for r in releases ], color="#2e7d32", label="added"   )
    ax.bar( x, [ -r[ "deleted" ] for r in releases ], color="#c62828", label="deleted" )

    cum, running = [], 0
    for r in releases:
        running += r[ "net" ]
        cum.append( running )
    ax2 = ax.twinx()
    ax2.plot( x, cum, color="#1565c0", marker="o", linewidth=2.5, label="cumulative net" )
    ax2.yaxis.set_major_formatter( thousands )
    ax2.set_ylabel( "cumulative net lines", color="#1565c0" )

    ax.set_xticks( list( x ) )
    ax.set_xticklabels( labels, rotation=45, ha="right", fontsize=7 )
    ax.yaxis.set_major_formatter( thousands )
    ax.axhline( 0, color="#333", linewidth=0.8 )
    ax.set_ylabel( "lines added / deleted per release" )
    ax.set_title( "Lupin — lines added, deleted, and cumulative net, by release\n"
                  "(main-line squash merges, oldest branch to today; generated artifacts excluded)" )
    ax.legend( loc="upper left" )
    ax2.legend( loc="lower right" )
    fig.tight_layout()
    p1 = os.path.join( OUT_DIR, "lupin-loc-by-release.png" )
    fig.savefig( p1, dpi=140 )

    # --- Chart 2: monthly authoring
    fig, ax = plt.subplots( figsize=( 15, 7 ) )
    xm = range( len( months ) )
    ax.bar( xm, [  monthly[ m ][ "added"   ] for m in months ], color="#2e7d32", label="added"   )
    ax.bar( xm, [ -monthly[ m ][ "deleted" ] for m in months ], color="#c62828", label="deleted" )
    ax.plot( xm, [ monthly[ m ][ "added" ] - monthly[ m ][ "deleted" ] for m in months ],
             color="#1565c0", marker="o", linewidth=2, label="net" )
    ax.set_xticks( list( xm ) )
    ax.set_xticklabels( months, rotation=45, ha="right" )
    ax.yaxis.set_major_formatter( thousands )
    ax.axhline( 0, color="#333", linewidth=0.8 )
    ax.set_ylabel( "lines" )
    ax.set_title( "Lupin — monthly authoring volume across all branches\n"
                  "(squash-merge commits excluded so feature work is counted once)" )
    ax.legend()
    fig.tight_layout()
    p2 = os.path.join( OUT_DIR, "lupin-loc-by-month.png" )
    fig.savefig( p2, dpi=140 )

    # --- CSV
    p3 = os.path.join( OUT_DIR, "lupin-loc-rollup.csv" )
    with open( p3, "w", newline="" ) as fh:
        w = csv.writer( fh )
        w.writerow( [ "view", "key", "added", "deleted", "net", "commits", "detail" ] )
        for r in releases:
            w.writerow( [ "release", r[ "date" ], r[ "added" ], r[ "deleted" ], r[ "net" ], 1, r[ "subject" ] ] )
        for m in months:
            b = monthly[ m ]
            w.writerow( [ "month", m, b[ "added" ], b[ "deleted" ], b[ "added" ] - b[ "deleted" ], b[ "commits" ], "" ] )

    # --- console summary
    print( "RELEASE CHAIN (main, oldest first)" )
    print( f"{'date':<12}{'added':>10}{'deleted':>10}{'net':>11}  subject" )
    for r in releases:
        print( f"{r['date']:<12}{r['added']:>10,}{r['deleted']:>10,}{r['net']:>11,}  {r['subject'][:52]}" )
    ta = sum( r[ "added" ] for r in releases )
    td = sum( r[ "deleted" ] for r in releases )
    print( f"{'TOTAL':<12}{ta:>10,}{td:>10,}{ta-td:>11,}" )
    print()
    print( "MONTHLY AUTHORING (all branches, squash merges excluded)" )
    print( f"{'month':<10}{'added':>10}{'deleted':>10}{'net':>11}{'commits':>9}" )
    for m in months:
        b = monthly[ m ]
        print( f"{m:<10}{b['added']:>10,}{b['deleted']:>10,}{b['added']-b['deleted']:>11,}{b['commits']:>9,}" )
    ma = sum( monthly[ m ][ "added" ] for m in months )
    md = sum( monthly[ m ][ "deleted" ] for m in months )
    mc = sum( monthly[ m ][ "commits" ] for m in months )
    print( f"{'TOTAL':<10}{ma:>10,}{md:>10,}{ma-md:>11,}{mc:>9,}" )
    print()
    print( "wrote:", p1 )
    print( "wrote:", p2 )
    print( "wrote:", p3 )

    return releases, monthly


if __name__ == "__main__":
    main()
