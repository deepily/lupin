#!/usr/bin/env python3
"""
Bundle-freshness gate: would a rebuild change the delivered bytes?

Why it exists: nothing rebuilds `src/lupin_app/static/dist/` and nothing warns when it is behind.
Git hooks have only `pre-commit` (pre-commit-secret-scan.py), no build hook. bounce-dev-server.sh and
run-fastapi-lupin.sh (the dev container's CMD) have no build step. No crontab or user systemd
timer names a build. docker/lupin/Dockerfile bakes `RUN npm run build`, but on dev the `src` bind mount
masks it. The only rebuild is a human typing `npm run build`.
`:7999` bind-mounts the working tree, so raw js/css/html has zero lag.
`dist/` sits in the same directory but only moves on a rebuild.
Same mount, two freshness rules, no signal telling them apart. This script is that signal.

What it checks: it rebuilds each bundle into a temporary directory using the production flags read
out of the build script itself. It compares the output's short sha256 to the hash the shipped
`manifest.json` records. Nothing is written into the repository.
A dry-run rebuild plus hash beat two other instruments measured on the same tree.
An mtime comparison and a sourcemap `sourcesContent` comparison were both wrong.
Both flagged `render/templates/taskListTable.ts`, whose only change was an 18-line comment block
that minification strips. The source had drifted and the delivery had not. Only the second is staleness.

What the silence means: drift that does not change the delivered bytes is reported `FRESH`.
A barrel such as `render/index.ts` can join the import graph and tree-shake to nothing, so the hash does not move.
A check keyed on the input set cries wolf there. The precise claim is narrower.
One comparison catches every drift that changes the delivered bytes (content or population).
It is silent on drift that does not.

What it cannot see, and says so in its own output: it measures the tree it is run in.
Work committed on another branch and not merged is invisible to it, whatever the instrument.
An example is `render/epicBoardCollapse.ts` and `render/holdingAreaModel.ts` on a worktree branch.
A green says nothing about such work and must never be read as if it did.
Every report line therefore names the sha it measured and states the limit.

Root resolution: the root comes from `__file__`, not `LUPIN_ROOT`. This script measures the tree it lives in.
`LUPIN_ROOT` is inherited from the shell and keeps naming the main checkout from inside a worktree.
That is how the pyc verifier blessed the wrong tree. `purge-pycache.sh` and
`migrate-pyc-to-checked-hash.sh` derive their root from `BASH_SOURCE` for the same reason.
A script shipped inside the tree it inspects can only be disagreed with by the environment, never informed by it.
To aim this script, run the copy that lives in the tree you mean.

Exit codes (four states, three codes):
    0  every judged bundle is `FRESH`: a rebuild would produce byte-identical output.
       `NOT-BUILT` bundles do not block this.
    1  at least one bundle is `STALE`: a rebuild would change the delivered bytes.
    2  `REFUSED`: could not answer (no esbuild, unparseable build script, a build that failed,
       or a bundle never built that something references). An unanswered question is never a clean 0.

Why `NOT-BUILT` is a fourth state: `dist/diagnostic/` has never been built in this checkout.
Calling that `REFUSED` would make exit 0 unreachable in the main checkout over a bundle nobody ships.
An alarm that can never be cleared gets routed around.
Measured over all tracked files, `dist/diagnostic` appears only in its own build driver's comments,
`tsconfig.diagnostic.json`'s outDir and one R&D doc. No page loads it.
The live page `static/html/test/diagnostic-websocket-test.html` loads the raw
`/static/js/websocket-diagnostic.js` (200). `/static/dist/diagnostic/websocket-diagnostic.js`
answers 404 and nothing asks for it. It is a dormant TypeScript port, same shape as `dist/nav`.
So the distinction is drawn on consumers, not on the absence itself:

    never built, nothing references its output   ->  `NOT-BUILT`   informational, exit 0 survives
    never built, something does reference it     ->  `REFUSED`     a live 404, be loud

A reference in the driver's own comments, a tsconfig `outDir`, or prose does not count.
Prose means `src/rnd`, `history`, `src/docs` or a top-level `.md`. Those describe the output, they do not load it.
A hit is not a use, applied to the tool's own population.
"""

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

from pathlib import Path


# ── root resolution ──────────────────────────────────────────────────────────────
# Derived from this file's own location, unconditionally. See the module docstring:
# $LUPIN_ROOT IS NOT CONSULTED. src/scripts/check_bundle_freshness.py → ../..
PROJECT_ROOT = Path( __file__ ).resolve().parents[ 2 ]

HASH_LENGTH  = 12          # matches build-multiplexer.sh: substr( sha256, 1, 12 )

FRESH        = "FRESH"
STALE        = "STALE"
REFUSED      = "REFUSED"
NOT_BUILT    = "NOT-BUILT"

EXIT_FRESH   = 0
EXIT_STALE   = 1
EXIT_REFUSED = 2

# Paths that MENTION a bundle's output without LOADING it. A driver names its own outputs in
# comments, a tsconfig names an outDir, and prose describes both — none of that is a consumer.
# § A HIT IS NOT A USE, applied to this tool's own population.
#
# 🔴 `src/tests/` IS ON THIS LIST AND IT WAS NOT AT FIRST — THIS FILE'S OWN TEST BECAME A
# "CONSUMER" THE MOMENT IT WAS COMMITTED. `git grep` cannot see an untracked file, so while
# test_check_bundle_freshness.py was new-and-uncommitted it was outside the searched population
# and the check passed. Committing it (ec1f1cd5) put it in, and a test that merely NAMES the
# path in a docstring came back as a loader. The tier that had been green went red on it.
# ⇒ THE POPULATION CHANGED UNDER A CHECK THAT NEVER SAID WHAT ITS POPULATION WAS. A test is a
#   mention, never a shipping surface: the question this list serves is "is this bundle a
#   dormant port or a live 404", and only code the SERVER SHIPS can answer it.
# ⚠️ THE COST, STATED: a test that genuinely loads a bundle in a browser is now invisible here.
#   Right for this question, wrong for "who touches this bundle" — do not reuse the list for a
#   different question without re-deriving it.
NON_CONSUMER_PREFIXES = ( "src/rnd/", "history/", "src/docs/", "src/scripts/", "src/tests/",
                          "docker/" )
NON_CONSUMER_SUFFIXES = ( ".md", )

# 🔴 AND THE SEARCH KEY WAS SHORTER THAN THE ONE LOADERS USE, WHICH IS WHY THIS FUNCTION HAD
# NEVER FOUND A REAL LOADER IN ITS LIFE. It searched the REPO path
# (`src/lupin_app/static/dist/multiplexer`); a page loads the URL path
# (`/static/dist/multiplexer`). Two different strings, two different populations.
# MEASURED at 5a9b9096: the repo form names 8 tracked files and NOT ONE of them loads the
# bundle; the URL form names 20, including `multiplexer.html` and `parity-harness.html`, which
# are the actual loaders. Everything the old key returned was a mention, by construction.
# ⇒ § YOUR MATCH KEY IS SHORTER THAN THE ROUTER'S KEY, in a tool whose whole subject is telling
#   a use from a mention. Search BOTH: the URL is how it is loaded, the repo path how it is
#   built and configured.
STATIC_ROOT = "src/lupin_app/static"


class BuildScriptError( Exception ):
    """Raised when a build script cannot be parsed into a runnable dry-run invocation."""


def short_sha( data ):
    """
    Twelve-character sha256 prefix of some bytes.

    Same convention as build-multiplexer.sh: `sha256sum "$OUTFILE" | awk '{print substr($1, 1, 12)}'`.

    Requires:
        - data is a bytes object

    Ensures:
        - returns a lowercase hex string of exactly HASH_LENGTH characters
    """
    return hashlib.sha256( data ).hexdigest()[ :HASH_LENGTH ]


def parse_build_script( script_path ):
    """
    Read a build-*.sh driver and extract what reproduces its production build.

    The flags are read out of the script rather than chosen here, so this check cannot drift
    away from the build it is checking.

    Requires:
        - script_path names a readable bash build driver

    Ensures:
        - returns a dict with "entry", "outdir", "out_basename" and "flags"
        - "flags" excludes --outfile and --log-level (this caller supplies its own)

    Notes:
        - The `--watch` branch is skipped: it runs `exec "$ESBUILD"` and omits --minify/--keep-names,
          so reproducing it would compare against a bundle nobody ships.

    Raises:
        - BuildScriptError if any of entry, outdir, outfile or the production esbuild
          invocation cannot be located
    """
    text = Path( script_path ).read_text( encoding="utf-8" )

    def scalar( name ):
        match = re.search( rf'^{name}="([^"]+)"', text, re.M )
        return match.group( 1 ) if match else None

    entry  = scalar( "ENTRY"  )
    outdir = scalar( "OUTDIR" )
    if entry is None or outdir is None:
        raise BuildScriptError( f"could not find ENTRY= and OUTDIR= in {script_path.name}" )

    outfile = scalar( "OUTFILE" )
    if outfile is None:
        raise BuildScriptError( f"could not find OUTFILE= in {script_path.name}" )
    out_basename = os.path.basename( outfile )

    # The production invocation is the bare `"$ESBUILD" \` line — the watch branch is
    # `exec "$ESBUILD" \` and is skipped on purpose.
    lines  = text.splitlines()
    starts = [ i for i, line in enumerate( lines ) if line.strip() == '"$ESBUILD" \\' ]
    if not starts:
        raise BuildScriptError(
            f"no production '\"$ESBUILD\" \\' invocation found in {script_path.name}"
        )

    flags = []
    for line in lines[ starts[ -1 ] + 1: ]:
        stripped = line.strip().rstrip( "\\" ).strip()
        if not stripped:
            break
        if stripped.startswith( "--" ):
            if stripped.startswith( ( "--outfile", "--log-level" ) ):
                continue
            flags.append( stripped )
        if not line.rstrip().endswith( "\\" ):
            break

    if not flags:
        raise BuildScriptError( f"production esbuild block in {script_path.name} carried no flags" )

    return {
        "entry"        : entry,
        "outdir"       : outdir,
        "out_basename" : out_basename,
        "flags"        : flags,
    }


def consumers_of( root, outdir ):
    """
    Tracked files that load a bundle's output, as opposed to merely naming it.

    The distinction decides whether a never-built bundle is a dormant port (harmless) or a live
    404 (loud).

    Requires:
        - root is the project root as a Path
        - outdir is a repo-relative output directory such as "src/lupin_app/static/dist/nav"

    Ensures:
        - searches both the repo path and the URL path a page loads it by. The second is the one
          loaders actually write, and searching only the first can never find one
        - returns a sorted list of repo-relative paths, excluding build drivers, tsconfigs,
          tests and prose
        - returns None when git cannot answer, so the caller can refuse rather than assume zero

    Notes:
        - Measured over all tracked files: `dist/diagnostic` is named by its own driver, a tsconfig
          outDir and one R&D doc, and loaded by nothing. The page that might have loaded it fetches
          the raw pre-port .js instead.
    """
    keys = [ outdir ]
    if outdir.startswith( STATIC_ROOT + "/" ):
        keys.append( outdir[ len( STATIC_ROOT ): ] )   # …/static/dist/nav -> /static/dist/nav

    hits = set()
    for key in keys:
        completed = subprocess.run(
            [ "git", "grep", "-l", "--", key ],
            cwd=root, capture_output=True, text=True, check=False
        )
        # git grep exits 1 on "no matches", which is an answer; anything else is a failure to ask.
        if completed.returncode not in ( 0, 1 ):
            return None
        hits.update( line.strip() for line in completed.stdout.splitlines() if line.strip() )

    return sorted(
        path for path in hits
        if not path.startswith( NON_CONSUMER_PREFIXES )
        and not path.endswith( NON_CONSUMER_SUFFIXES )
        and not os.path.basename( path ).startswith( "tsconfig" )
    )


def discover_bundles( root ):
    """
    Find every build driver that emits a dist manifest, newest name first.

    A driver without a manifest (build-parity-harness.sh) is skipped. With no recorded hash
    there is nothing to compare against, and inventing one would be a check that cannot fail.

    Requires:
        - root is the project root as a Path

    Ensures:
        - returns a sorted list of Paths under src/scripts matching build-*.sh
        - each returned script mentions manifest.json
    """
    scripts = sorted( ( root / "src" / "scripts" ).glob( "build-*.sh" ) )
    return [ s for s in scripts if "manifest.json" in s.read_text( encoding="utf-8" ) ]


def check_bundle( root, script_path, esbuild ):
    """
    Dry-run one bundle into a temp directory and compare its hash to the shipped manifest.

    Nothing is written inside `root`: the rebuild lands in a TemporaryDirectory that is removed
    on the way out.

    Requires:
        - root is the project root as a Path
        - script_path names a build driver discovered by discover_bundles
        - esbuild is a path to an executable esbuild binary, or None

    Ensures:
        - returns a dict carrying "name", "status" and enough detail to print a report row
        - "status" is one of `FRESH`, `STALE`, `REFUSED` — never a bare boolean
        - a question that cannot be answered returns `REFUSED` with a "reason", never `FRESH`

    Notes:
        - The output basename is preserved because esbuild embeds a `//# sourceMappingURL=<basename>.map`
          comment, so a different filename changes the bytes and would manufacture a false `STALE`.
    """
    name   = script_path.stem.replace( "build-", "" )
    result = { "name": name, "script": script_path.name, "status": REFUSED, "reason": None,
               "shipped_hash": None, "rebuilt_hash": None, "sources": None, "entry": None }

    if esbuild is None:
        result[ "reason" ] = "esbuild binary not found — run `npm install` from the project root"
        return result

    try:
        spec = parse_build_script( script_path )
    except BuildScriptError as error:
        result[ "reason" ] = f"unparseable build script: {error}"
        return result

    result[ "entry" ] = spec[ "entry" ]

    entry_path = root / spec[ "entry" ]
    if not entry_path.is_file():
        result[ "reason" ] = f"entry not found: {spec['entry']}"
        return result

    manifest_path = root / spec[ "outdir" ] / "manifest.json"
    if not manifest_path.is_file():
        # Never built. Whether that matters depends entirely on whether anything LOADS it.
        loaders = consumers_of( root, spec[ "outdir" ] )
        if loaders is None:
            result[ "reason" ] = (
                f"{spec['outdir']} has never been built and git could not be asked who "
                f"references it — refusing rather than assuming nobody does"
            )
        elif loaders:
            result[ "reason" ] = (
                f"{spec['outdir']} has never been built, but {len( loaders )} file(s) "
                f"reference it — that is a live 404: {', '.join( loaders[ :3 ] )}"
            )
        else:
            result[ "status" ] = NOT_BUILT
            result[ "reason" ] = (
                f"{spec['outdir']} has never been built in this tree, and no tracked file "
                f"loads it — a dormant driver, not a delivery gap"
            )
        return result

    try:
        shipped_hash = json.loads( manifest_path.read_text( encoding="utf-8" ) )[ "hash" ]
    except ( ValueError, KeyError ) as error:
        result[ "reason" ] = f"manifest at {spec['outdir']}/manifest.json carries no readable 'hash': {error}"
        return result

    result[ "shipped_hash" ] = shipped_hash

    with tempfile.TemporaryDirectory( prefix="bundle-freshness-" ) as scratch:
        out_path  = os.path.join( scratch, spec[ "out_basename" ] )
        meta_path = os.path.join( scratch, "meta.json" )

        command = [ esbuild, spec[ "entry" ] ] + spec[ "flags" ] + [
            f"--outfile={out_path}",
            f"--metafile={meta_path}",
            "--log-level=warning",
        ]

        completed = subprocess.run(
            command, cwd=root, capture_output=True, text=True, check=False
        )

        if completed.returncode != 0 or not os.path.isfile( out_path ):
            detail = ( completed.stderr or completed.stdout or "" ).strip().splitlines()
            result[ "reason" ] = (
                f"dry-run build failed (exit {completed.returncode}): "
                f"{detail[ 0 ] if detail else 'no output produced'}"
            )
            return result

        with open( out_path, "rb" ) as handle:
            result[ "rebuilt_hash" ] = short_sha( handle.read() )

        if os.path.isfile( meta_path ):
            with open( meta_path, encoding="utf-8" ) as handle:
                result[ "sources" ] = len( json.load( handle ).get( "inputs", {} ) )

    result[ "status" ] = FRESH if result[ "rebuilt_hash" ] == shipped_hash else STALE
    return result


def current_sha( root ):
    """
    The commit this tree is standing on, for the report header.

    A figure without the sha it was taken at is a rumour with a timestamp, so the report names
    it even when git is unavailable.

    Requires:
        - root is the project root as a Path

    Ensures:
        - returns a short sha string, or "unknown" when git cannot answer
    """
    completed = subprocess.run(
        [ "git", "rev-parse", "--short", "HEAD" ],
        cwd=root, capture_output=True, text=True, check=False
    )
    return completed.stdout.strip() if completed.returncode == 0 else "unknown"


def format_report( root, results, sha ):
    """
    Render the results as report lines.

    Every line names the bundle, its source count and both hashes, because a bare verdict is
    the easiest thing in a log to wave at.

    Requires:
        - results is a list of dicts returned by check_bundle
        - sha is the string returned by current_sha

    Ensures:
        - returns a list of strings, one per output line
        - the scope limit appears in the output whenever any bundle was judged

    Notes:
        - The scope sentence is not optional decoration. A green here says nothing about unmerged
          or unwired work, and a reader who does not know that will over-read it.
    """
    lines = [
        f"check_bundle_freshness: tree {root}",
        f"check_bundle_freshness: sha  {sha}",
        "",
        f"  {'bundle':<14} {'status':<8} {'sources':>7}  {'shipped':<13} {'rebuilt':<13}",
    ]

    for entry in results:
        if entry[ "status" ] in ( REFUSED, NOT_BUILT ):
            lines.append( f"  {entry['name']:<14} {entry['status']:<9} {'-':>7}  {'-':<13} {'-':<13}" )
            lines.append( f"      ↳ {entry['reason']}" )
            continue

        sources = "?" if entry[ "sources" ] is None else str( entry[ "sources" ] )
        lines.append(
            f"  {entry['name']:<14} {entry['status']:<9} {sources:>7}  "
            f"{entry['shipped_hash']:<13} {entry['rebuilt_hash']:<13}"
        )
        if entry[ "status" ] == STALE:
            lines.append(
                f"      ↳ a rebuild WOULD change the delivered bytes. Run: npm run build"
            )

    judged = [ e for e in results if e[ "status" ] in ( FRESH, STALE ) ]
    if judged:
        lines += [
            "",
            "  SCOPE — read this before trusting a FRESH:",
            f"    FRESH means a rebuild of THIS tree at {sha} would produce byte-identical output.",
            "    It says NOTHING about work committed on an unmerged branch, and nothing about a",
            "    module that exists but is not yet imported. Neither is visible from this tree.",
            "    Drift that does not change the delivered bytes is reported FRESH deliberately —",
            "    a bundle whose bytes would not change is not stale.",
        ]

    return lines


def main( argv=None ):
    """
    Entry point. Prints a report and returns the process exit code.

    Requires:
        - argv is a list of command-line arguments, or None to read sys.argv

    Ensures:
        - returns EXIT_FRESH only when at least one bundle was judged and all were `FRESH`
        - returns EXIT_REFUSED when any bundle could not be judged, and when none were found
        - returns EXIT_STALE when any judged bundle was `STALE`
        - a NOT_BUILT bundle does not block EXIT_FRESH, but EXIT_FRESH still requires that at
          least one bundle was actually judged — an all-NOT_BUILT tree has measured nothing
          and must not report a clean zero
    """
    parser = argparse.ArgumentParser(
        description="Would a rebuild change the delivered bundle bytes? ($LUPIN_ROOT is NOT consulted.)"
    )
    parser.add_argument( "--quiet", action="store_true", help="print only the verdict lines" )
    args = parser.parse_args( argv )

    root    = PROJECT_ROOT
    esbuild = root / "node_modules" / ".bin" / "esbuild"
    esbuild = str( esbuild ) if os.access( esbuild, os.X_OK ) else None

    scripts = discover_bundles( root )
    if not scripts:
        print( "check_bundle_freshness: REFUSED — no build-*.sh driver emits a manifest.json",
               file=sys.stderr )
        return EXIT_REFUSED

    results = [ check_bundle( root, script, esbuild ) for script in scripts ]

    lines = format_report( root, results, current_sha( root ) )
    if args.quiet:
        lines = [ line for line in lines if line.strip() ]
    print( "\n".join( lines ) )

    if any( entry[ "status" ] == REFUSED for entry in results ): return EXIT_REFUSED
    if any( entry[ "status" ] == STALE   for entry in results ): return EXIT_STALE

    if not any( entry[ "status" ] == FRESH for entry in results ):
        # Every bundle was NOT_BUILT: nothing was measured. A clean exit here would be the
        # vacuous green this file exists to prevent.
        print( "check_bundle_freshness: REFUSED — no bundle was built, so nothing was measured",
               file=sys.stderr )
        return EXIT_REFUSED

    return EXIT_FRESH


if __name__ == "__main__":
    sys.exit( main() )
