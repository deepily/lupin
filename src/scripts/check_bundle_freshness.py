#!/usr/bin/env python3
"""
Bundle-freshness gate — would a rebuild change the DELIVERED BYTES?

WHY THIS EXISTS
---------------
Nothing rebuilds `src/lupin_app/static/dist/` automatically and nothing warns when it is
behind. Measured 2026-09-05 at be1d58b2, each probe naming its population and carrying a
control:

  * git hooks           → only `pre-commit` → pre-commit-secret-scan.py. No build hook.
  * bounce-dev-server.sh → no build step  (control: it names `docker` 12x, so the grep works)
  * run-fastapi-lupin.sh → no build step  (control: it names `uvicorn` 3x) — and that is the
                           dev container's CMD, so a bounce does not rebuild either
  * crontab / user systemd timers → none naming a build
  * docker/lupin/Dockerfile:102 DOES bake `RUN npm run build`, but on dev the `src` bind mount
    MASKS it. The Dockerfile's own comment at :69 says so.

⇒ The only rebuild is a human typing `npm run build`. `:7999` bind-mounts the working tree, so
raw js/css/html has ZERO lag and lands on refresh, while `dist/` sits in the same directory,
is served the same way, and only moves when somebody rebuilds it. Same mount, two freshness
rules, no signal telling them apart. This script is that signal.

WHAT IT CHECKS — AND WHY IT IS A DRY-RUN REBUILD RATHER THAN A TIMESTAMP
------------------------------------------------------------------------
It rebuilds each bundle into a TEMPORARY directory using the production flags read out of the
build script itself, and compares the output's short sha256 to the hash the shipped
`manifest.json` records. Nothing is written into the repository.

Three instruments were measured against the same tree at the same moment. Only one was right:

    mtime > bundle mtime              → 2 flagged, 2 WRONG
    sourcemap sourcesContent != file  → 1 flagged, 1 WRONG
    DRY-RUN REBUILD + HASH            → 0 flagged, CORRECT

Both of the losing arms flagged `render/templates/taskListTable.ts`, whose only change since
the build was an 18-line COMMENT BLOCK (1,177 bytes). Minification strips comments, so it
cannot reach the emitted bytes. THE SOURCE HAD DRIFTED AND THE DELIVERY HAD NOT — two
different facts, and only the second one is staleness.

⚠️ WHAT THE SILENCE MEANS, because it will look like a gap and is not. Drift that does not
change the delivered bytes is reported as FRESH, deliberately. Receipt: `render/index.ts`
joined the import graph after the shipped build (94 inputs today against 93 shipped) and the
output hash did NOT move, because it is a barrel that tree-shakes to nothing. A check keyed on
the input SET cries wolf there; this one correctly stays quiet. A bundle whose bytes would not
change is not stale.

⇒ SO THE PRECISE CLAIM IS: one comparison catches every drift that changes the delivered
bytes — content or population — and is silent on drift that does not. It is NOT "any new file
in the graph moves the hash": a file that emits nothing does not.

WHAT IT CANNOT SEE — SAID IN ITS OWN OUTPUT, NOT ONLY HERE
----------------------------------------------------------
It measures the tree it is run in. Work that is committed on another branch and not merged is
invisible to it, permanently and by construction — no instrument choice fixes that. On
2026-09-05 two modules (`render/epicBoardCollapse.ts`, `render/holdingAreaModel.ts`) sat
committed on a worktree branch and absent from the served tree; a green from this script said
nothing about them and must never be read as if it did. That is why every report line names
the sha it measured and states the limit in words.

WHY IT RESOLVES ITS ROOT FROM `__file__` RATHER THAN `LUPIN_ROOT`
-----------------------------------------------------------------
The global path mandate says to resolve from `LUPIN_ROOT`. This script is the documented
exception class: a tool that MEASURES THE TREE IT LIVES IN. `LUPIN_ROOT` is inherited from the
shell and keeps naming the main checkout from inside a worktree, which is precisely how the
pyc verifier blessed the wrong tree and printed a checkmark about it (CLAUDE.md § THE
CHECKED-HASH VERIFIER SCANS `$LUPIN_ROOT/src`). The ruling that followed — `purge-pycache.sh`
and `migrate-pyc-to-checked-hash.sh` now derive their root from `BASH_SOURCE`
unconditionally — is that a script shipped inside the tree it inspects can only be DISAGREED
WITH by the environment, never informed by it. `$LUPIN_ROOT` is not consulted here. To aim
this script, run the copy that lives in the tree you mean.

EXIT CODES — FOUR STATES, THREE CODES
-------------------------------------
    0  every judged bundle FRESH — a rebuild would produce byte-identical output. NOT-BUILT
       bundles do not block this; see below.
    1  at least one bundle STALE — a rebuild would change the delivered bytes
    2  REFUSED — could not answer (no esbuild, unparseable build script, a build that failed,
       or a bundle that has never been built AND is referenced by something). A question this
       script could not answer is never reported as a clean 0.

WHY NOT-BUILT IS A FOURTH STATE RATHER THAN A REFUSAL
------------------------------------------------------
`dist/diagnostic/` has never been built in this checkout, and the first cut of this script
called that REFUSED — which made exit 0 UNREACHABLE in the main checkout, permanently, over a
bundle nobody ships. That is the same false alarm the mtime instrument was rejected for, and
an alarm that can never be cleared is one people route around.

MEASURED 2026-09-05 over all 5,067 tracked files, with a control on the same strings:
`dist/diagnostic` appears in exactly 3 files — its own build driver's comments,
`tsconfig.diagnostic.json`'s outDir, and one R&D doc. NOT ONE PAGE LOADS IT. The live page
`static/html/test/diagnostic-websocket-test.html` loads the RAW `/static/js/
websocket-diagnostic.js` (200), while `/static/dist/diagnostic/websocket-diagnostic.js`
answers 404 and nothing asks for it. It is a dormant TS port, same shape as `dist/nav`.

⇒ So the distinction is drawn on CONSUMERS, not on the absence itself, and it discriminates:

    never built, nothing references its output   →  NOT-BUILT   informational, exit 0 survives
    never built, something DOES reference it     →  REFUSED     that is a live 404, be loud

A reference in the driver's own comments, in a tsconfig `outDir`, or in prose under `src/rnd`,
`history`, `src/docs` or a top-level `.md` does not count — those describe the output, they do
not load it. This is § A HIT IS NOT A USE applied to the tool's own population.
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
    Twelve-character sha256 prefix of some bytes — the same convention build-multiplexer.sh
    uses (`sha256sum "$OUTFILE" | awk '{print substr($1, 1, 12)}'`).

    Requires:
        - data is a bytes object

    Ensures:
        - returns a lowercase hex string of exactly HASH_LENGTH characters
    """
    return hashlib.sha256( data ).hexdigest()[ :HASH_LENGTH ]


def parse_build_script( script_path ):
    """
    Read a build-*.sh driver and extract what is needed to reproduce its PRODUCTION build.

    The flags are read out of the script rather than chosen here, so this check cannot drift
    away from the build it is checking. The `--watch` branch is skipped deliberately: it runs
    `exec "$ESBUILD"` and omits --minify/--keep-names, so reproducing it would compare against
    a bundle nobody ships.

    Requires:
        - script_path names a readable bash build driver

    Ensures:
        - returns a dict with "entry", "outdir", "out_basename" and "flags"
        - "flags" excludes --outfile and --log-level (this caller supplies its own)

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
    Tracked files that LOAD a bundle's output, as opposed to merely naming it.

    The distinction decides whether a never-built bundle is a dormant port (harmless) or a live
    404 (loud). Measured over all 5,067 tracked files: `dist/diagnostic` is named by its own
    driver, a tsconfig outDir and one R&D doc, and loaded by nothing — while the page that
    might have loaded it fetches the raw pre-port .js instead.

    Requires:
        - root is the project root as a Path
        - outdir is a repo-relative output directory such as "src/lupin_app/static/dist/nav"

    Ensures:
        - searches BOTH the repo path and the URL path a page loads it by; the second is the one
          loaders actually write, and searching only the first can never find one
        - returns a sorted list of repo-relative paths, excluding build drivers, tsconfigs,
          tests and prose
        - returns None when git cannot answer, so the caller can refuse rather than assume zero
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

    A driver without a manifest (build-parity-harness.sh) is skipped: with no recorded hash
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
    on the way out. The output basename is preserved because esbuild embeds a
    `//# sourceMappingURL=<basename>.map` comment, so a different filename changes the bytes
    and would manufacture a false STALE.

    Requires:
        - root is the project root as a Path
        - script_path names a build driver discovered by discover_bundles
        - esbuild is a path to an executable esbuild binary, or None

    Ensures:
        - returns a dict carrying "name", "status" and enough detail to print a report row
        - "status" is one of FRESH, STALE, REFUSED — never a bare boolean
        - a question that cannot be answered returns REFUSED with a "reason", never FRESH
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
    the easiest thing in a log to wave at. The scope sentence is not optional decoration: a
    green here says nothing about unmerged or unwired work, and a reader who does not know
    that will over-read it.

    Requires:
        - results is a list of dicts returned by check_bundle
        - sha is the string returned by current_sha

    Ensures:
        - returns a list of strings, one per output line
        - the scope limit appears in the output whenever any bundle was judged
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
        - returns EXIT_FRESH only when at least one bundle was judged and all were FRESH
        - returns EXIT_REFUSED when any bundle could not be judged, and when none were found
        - returns EXIT_STALE when any judged bundle was STALE
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
