"""
Unit tests for src/scripts/check_bundle_freshness.py — the dist/ staleness gate.

WHY THIS FILE EXISTS
--------------------
Nothing rebuilds `dist/` and nothing warned when it was behind. The check that closes that
was chosen over two rivals BY MEASUREMENT, and the arms below are what keep the choice honest
rather than merely asserted. Against one tree at one moment:

    mtime > bundle mtime              → 2 flagged, 2 WRONG
    sourcemap sourcesContent != file  → 1 flagged, 1 WRONG
    DRY-RUN REBUILD + HASH            → 0 flagged, CORRECT

Both losing arms flagged a file whose only change was an 18-line COMMENT. Minification strips
comments, so the delivered bytes had not moved. `test_a_comment_only_change_is_still_fresh` is
that exact case turned into a guard: it is the test that fails if anyone ever "improves" this
script back into a timestamp or a source-text comparison.

🔴 EVERY ARM HERE DRIVES THE REAL esbuild AND THE REAL SCRIPT ENTRY POINT (`mod.main`), never a
stand-in. A fake bundler would answer the same however the code behaved, and every assertion
written over it would inherit that blindness — the defect this repo files under
§ COVERAGE MEASURES WHETHER A LINE RAN, NEVER WHETHER THE TEST COULD HAVE NOTICED IT RUNNING
WRONG.

⚠️ THE MUTATION THAT DOES NOT WORK, RECORDED SO NOBODY REPEATS IT. The first negative control
appended `export const __probe_marker = 1` to a source and the hashes came back IDENTICAL —
esbuild TREE-SHOOK the unused export, so the mutation never reached the output and read as a
pass. A no-op break is indistinguishable from a check that cannot fail. The perturbation must
change a string that is actually EMITTED, which is what `_mutate_emitted_string` does, and
`test_the_stale_arm_perturbs_something_that_is_actually_emitted` asserts the marker really is
in the rebuilt bytes.

⚠️ SCOPE THIS FILE DOES NOT COVER, said out loud rather than left to be discovered: the script
cannot see work committed on an unmerged branch, by construction. That limit is not tested
because it is not fixable — it is asserted as OUTPUT TEXT instead, by
`test_the_report_states_the_limit_a_green_does_not_cover`.

VENUE: :7999-eligible. Pure reads plus a tmp_path build; esbuild runs in ~20 ms, nothing is
written outside the fixture, and no server is touched.
"""

import json
import os
import shutil
import subprocess
import sys

from pathlib import Path

import pytest


def _load_module():
    """Import the script under its real name so coverage targets the file."""
    root        = Path( __file__ ).resolve().parents[ 3 ]
    scripts_dir = str( root / "src" / "scripts" )
    if scripts_dir not in sys.path:
        sys.path.insert( 0, scripts_dir )
    import check_bundle_freshness
    return check_bundle_freshness


mod = _load_module()

REPO_ROOT = Path( __file__ ).resolve().parents[ 3 ]
ESBUILD   = REPO_ROOT / "node_modules" / ".bin" / "esbuild"

needs_esbuild = pytest.mark.skipif(
    not os.access( ESBUILD, os.X_OK ),
    reason=f"esbuild not executable at {ESBUILD} — run `npm install` from the project root"
)


# ── fixture tree ─────────────────────────────────────────────────────────────────

BUILD_SCRIPT = '''#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$( cd "$SCRIPT_DIR/../.." && pwd )"
cd "$PROJECT_ROOT"

ENTRY="src/lupin_app/static/js/probe/boot.ts"
OUTDIR="src/lupin_app/static/dist/probe"
OUTFILE="$OUTDIR/boot.js"

ESBUILD="$PROJECT_ROOT/node_modules/.bin/esbuild"

"$ESBUILD" \\
  "$ENTRY" \\
  --bundle \\
  --format=esm \\
  --target=es2022 \\
  --platform=browser \\
  --minify \\
  --keep-names \\
  --sourcemap \\
  --outfile="$OUTFILE" \\
  --log-level=warning

cat > "$OUTDIR/manifest.json" <<EOF
{ "boot.js" : "x", "hash" : "y", "built" : "z" }
EOF
'''

ENTRY_TS = '''import { label } from "./label";

export function boot(): void {
  const node = document.createElement( "div" );
  node.className = label();
  document.body.appendChild( node );
}

boot();
'''

LABEL_TS = '''export function label(): string {
  return "probe-emitted-class";
}
'''


def _make_tree( tmp_path ):
    """
    Build a miniature repo the script can resolve: src/scripts + src/lupin_app/static + a
    node_modules symlink to the real esbuild.

    The script derives its root from its own location, so placing a copy at
    <tree>/src/scripts/ is what aims it at the fixture rather than at this repo.
    """
    tree = tmp_path / "tree"
    ( tree / "src" / "scripts" ).mkdir( parents=True )
    ( tree / "src" / "lupin_app" / "static" / "js" / "probe" ).mkdir( parents=True )

    ( tree / "node_modules" ).symlink_to( REPO_ROOT / "node_modules" )

    shutil.copy( REPO_ROOT / "src" / "scripts" / "check_bundle_freshness.py",
                 tree / "src" / "scripts" / "check_bundle_freshness.py" )
    ( tree / "src" / "scripts" / "build-probe.sh" ).write_text( BUILD_SCRIPT, encoding="utf-8" )
    ( tree / "src" / "lupin_app" / "static" / "js" / "probe" / "boot.ts"  ).write_text( ENTRY_TS, encoding="utf-8" )
    ( tree / "src" / "lupin_app" / "static" / "js" / "probe" / "label.ts" ).write_text( LABEL_TS, encoding="utf-8" )
    return tree


def _build( tree ):
    """Run the fixture's own build script, exactly as a human would run `npm run build`."""
    outdir = tree / "src" / "lupin_app" / "static" / "dist" / "probe"
    outdir.mkdir( parents=True, exist_ok=True )
    completed = subprocess.run(
        [ "bash", str( tree / "src" / "scripts" / "build-probe.sh" ) ],
        capture_output=True, text=True, check=False
    )
    assert completed.returncode == 0, f"fixture build failed: {completed.stderr}"

    built = ( outdir / "boot.js" ).read_bytes()
    ( outdir / "manifest.json" ).write_text(
        json.dumps( { "boot.js": "boot.js", "hash": mod.short_sha( built ), "built": "fixture" } ),
        encoding="utf-8"
    )
    return mod.short_sha( built )


def _run( tree ):
    """Drive the REAL entry point against the fixture and return (exit_code, stdout)."""
    completed = subprocess.run(
        [ sys.executable, str( tree / "src" / "scripts" / "check_bundle_freshness.py" ) ],
        capture_output=True, text=True, check=False
    )
    return completed.returncode, completed.stdout + completed.stderr


def _source( tree, name ):
    return tree / "src" / "lupin_app" / "static" / "js" / "probe" / name


def _mutate_emitted_string( tree ):
    """Change a string that survives minification into the output bytes."""
    path = _source( tree, "label.ts" )
    path.write_text( path.read_text( encoding="utf-8" ).replace(
        "probe-emitted-class", "probe-MUTATED-class" ), encoding="utf-8" )


# ── the discriminating pair ──────────────────────────────────────────────────────

@needs_esbuild
def test_a_tree_whose_bundle_matches_is_reported_fresh( tmp_path ):
    """The positive half. Without it, a STALE result would only prove the script can say STALE."""
    tree = _make_tree( tmp_path )
    _build( tree )

    code, out = _run( tree )

    assert code == mod.EXIT_FRESH, out
    assert "FRESH" in out
    assert "STALE" not in out


@needs_esbuild
def test_a_changed_emitted_string_is_reported_stale( tmp_path ):
    """The negative half — one variable against the test above: an emitted string."""
    tree = _make_tree( tmp_path )
    shipped = _build( tree )
    _mutate_emitted_string( tree )

    code, out = _run( tree )

    assert code == mod.EXIT_STALE, out
    assert "STALE" in out
    assert shipped in out, "the report must name the shipped hash it compared against"
    assert "npm run build" in out, "a STALE line must carry the remedy"


@needs_esbuild
def test_the_stale_arm_perturbs_something_that_is_actually_emitted( tmp_path ):
    """
    Guards the guard. The first negative control appended an unused export, esbuild tree-shook
    it, and the pair came back identical — a no-op break reading as a pass. This asserts the
    mutation really does reach the bytes, so the arm above cannot silently stop discriminating.
    """
    tree = _make_tree( tmp_path )
    _build( tree )
    _mutate_emitted_string( tree )

    rebuilt = mod.check_bundle(
        tree, tree / "src" / "scripts" / "build-probe.sh", str( ESBUILD )
    )
    built_path = tree / "src" / "lupin_app" / "static" / "dist" / "probe" / "boot.js"

    subprocess.run( [ "bash", str( tree / "src" / "scripts" / "build-probe.sh" ) ],
                    capture_output=True, text=True, check=False )

    assert b"probe-MUTATED-class" in built_path.read_bytes(), \
        "the perturbation never reached the emitted bytes — this arm cannot fail"
    assert rebuilt[ "status" ] == mod.STALE


@needs_esbuild
def test_a_comment_only_change_is_still_fresh( tmp_path ):
    """
    🔴 THE ARM THAT SETTLED THE DESIGN. A comment-only edit is exactly what the two rejected
    instruments called STALE and what the delivered bytes call unchanged. If someone replaces
    this check with an mtime or a source-text comparison, this test goes red.
    """
    tree = _make_tree( tmp_path )
    _build( tree )

    path = _source( tree, "label.ts" )
    path.write_text( "// a comment that minification strips\n" + path.read_text( encoding="utf-8" ),
                     encoding="utf-8" )
    os.utime( path, ( 0, 0 ) )   # and an mtime moved BACKWARDS, to pin that mtime is not consulted

    code, out = _run( tree )

    assert code == mod.EXIT_FRESH, out
    assert "FRESH" in out


# ── refusal arms: a question it cannot answer is never a clean zero ──────────────

@needs_esbuild
def test_a_missing_manifest_refuses_rather_than_reporting_fresh( tmp_path ):
    """
    A tree that has never been built has nothing to compare against. That is not FRESH.

    The fixture tree is not a git repo, so `consumers_of` cannot be asked who references the
    output — and the script must REFUSE rather than assume nobody does. That is the
    conservative branch, and this pins it.
    """
    tree = _make_tree( tmp_path )

    code, out = _run( tree )

    assert code == mod.EXIT_REFUSED, out
    assert mod.REFUSED in out
    assert "FRESH" not in out
    assert "never been built" in out


# ── NOT-BUILT: the fourth state, and why it is not a refusal ─────────────────────

def test_a_never_built_bundle_nothing_loads_is_not_built_not_refused( tmp_path, monkeypatch ):
    """
    🔴 THE CORRECTION mr radio ASKED FOR. The first cut called an unbuilt bundle REFUSED, which
    made exit 0 UNREACHABLE in the main checkout forever over a bundle nobody ships — the same
    unclearable false alarm that got the mtime instrument rejected.

    Measured over all 5,067 tracked files: `dist/diagnostic` is named only by its own driver, a
    tsconfig outDir and one R&D doc, and is LOADED by nothing. So absence-with-no-consumers is
    informational, not a refusal.
    """
    tree = _make_tree( tmp_path )
    monkeypatch.setattr( mod, "consumers_of", lambda root, outdir: [] )

    result = mod.check_bundle( tree, tree / "src" / "scripts" / "build-probe.sh", str( ESBUILD ) )

    assert result[ "status" ] == mod.NOT_BUILT
    assert "dormant driver" in result[ "reason" ]


def test_a_never_built_bundle_something_loads_is_a_live_404_and_refuses( tmp_path, monkeypatch ):
    """
    The discriminating other half. Same absence, one variable — a consumer exists. Without this
    arm the state above would just be a way of going quiet, and a genuinely 404ing page would
    pass unnoticed.
    """
    tree = _make_tree( tmp_path )
    monkeypatch.setattr( mod, "consumers_of",
                         lambda root, outdir: [ "src/lupin_app/static/html/probe.html" ] )

    result = mod.check_bundle( tree, tree / "src" / "scripts" / "build-probe.sh", str( ESBUILD ) )

    assert result[ "status" ] == mod.REFUSED
    assert "live 404" in result[ "reason" ]
    assert "probe.html" in result[ "reason" ]


def test_an_all_not_built_tree_still_refuses_because_nothing_was_measured( tmp_path, monkeypatch ):
    """
    NOT-BUILT must not become a way to earn a green by measuring nothing. A tree where every
    bundle is unbuilt has answered no question at all — § A CLEAN EXIT IS NOT EVIDENCE THE WORK
    HAPPENED.
    """
    monkeypatch.setattr( mod, "discover_bundles", lambda root: [ "driver" ] )
    monkeypatch.setattr( mod, "check_bundle",
                         lambda root, script, esbuild: { "name": "probe", "status": mod.NOT_BUILT,
                                                         "reason": "dormant", "shipped_hash": None,
                                                         "rebuilt_hash": None, "sources": None } )
    monkeypatch.setattr( mod, "current_sha", lambda root: "deadbeef" )

    assert mod.main( [] ) == mod.EXIT_REFUSED


def test_consumers_of_counts_loaders_and_ignores_mere_mentions():
    """
    § A HIT IS NOT A USE, on the real repo. `dist/diagnostic` is MENTIONED by its driver, a
    tsconfig and an R&D doc — none of which loads it — so the consumer list must be empty while
    a plain grep for the same string is not.
    """
    mentions = subprocess.run(
        [ "git", "grep", "-l", "--", "src/lupin_app/static/dist/diagnostic" ],
        cwd=REPO_ROOT, capture_output=True, text=True, check=False
    ).stdout.split()

    loaders = mod.consumers_of( REPO_ROOT, "src/lupin_app/static/dist/diagnostic" )

    assert mentions, "positive control: the string must appear somewhere, or this proves nothing"
    assert loaders == [], f"expected no loaders, got {loaders}"
    assert len( mentions ) > len( loaders ), "a mention count equal to the loader count means no filtering happened"


def test_consumers_of_still_finds_a_REAL_loader():
    """
    🔴 THE CONTROL THE ASSERTION ABOVE CANNOT DO WITHOUT, and its absence let two defects ship.

    `consumers_of( diagnostic ) == []` is satisfied by a correct answer AND by a filter that
    returns nothing for everything. Only a bundle that IS loaded can tell those apart, and the
    multiplexer is loaded by two real pages.

    WHAT THIS WOULD HAVE CAUGHT, both measured at 5a9b9096:
    · the SEARCH KEY was the repo path (`src/lupin_app/static/dist/multiplexer`) while a page
      loads the URL path (`/static/dist/multiplexer`). Different strings, different populations
      — 8 tracked files against 20 — and the function had therefore never found a loader in its
      life. It returned the Dockerfile and some tests, every one a mention.
    · the DENY LIST did not exclude `src/tests/`, so this very file became a "consumer" the
      moment it was committed. `git grep` cannot see an untracked file, so the check passed
      while the file was new and went red the instant it was tracked.
    """
    loaders = mod.consumers_of( REPO_ROOT, "src/lupin_app/static/dist/multiplexer" )

    assert loaders is not None, "git could not answer — this arm proves nothing without a list"
    assert "src/lupin_app/static/html/multiplexer.html" in loaders, (
        f"the page that loads the multiplexer is missing from {loaders} — the search key is "
        f"probably the repo path again, which no loader ever writes"
    )
    assert all( not p.startswith( ( "src/tests/", "src/scripts/", "docker/" ) ) for p in loaders ), (
        f"a mention was counted as a loader: {loaders}"
    )


def test_consumers_of_refuses_rather_than_assuming_zero_when_git_cannot_answer( tmp_path ):
    """
    A non-git directory must yield None, not []. Returning an empty list there would turn 'I
    could not ask' into 'nobody references it' — an empty result wearing a measured face.
    """
    assert mod.consumers_of( tmp_path, "some/outdir" ) is None


def test_a_missing_esbuild_refuses_rather_than_reporting_fresh( tmp_path ):
    """No bundler, no answer. Mr. Radio's requirement, and it must not degrade to a pass."""
    tree = _make_tree( tmp_path )

    result = mod.check_bundle( tree, tree / "src" / "scripts" / "build-probe.sh", None )

    assert result[ "status" ] == mod.REFUSED
    assert "esbuild" in result[ "reason" ]


def test_an_unparseable_build_script_refuses( tmp_path ):
    """A driver this script cannot reproduce is a refusal, never an assumption about its flags."""
    tree   = _make_tree( tmp_path )
    script = tree / "src" / "scripts" / "build-probe.sh"
    script.write_text( "#!/usr/bin/env bash\necho nothing useful here\n", encoding="utf-8" )

    result = mod.check_bundle( tree, script, str( ESBUILD ) )

    assert result[ "status" ] == mod.REFUSED
    assert "unparseable" in result[ "reason" ]


@needs_esbuild
def test_a_build_that_fails_refuses_rather_than_reporting_stale( tmp_path ):
    """
    A broken build produces no bytes to hash. Calling that STALE would send someone to run
    `npm run build`, which would fail the same way — the report must say it could not answer.
    """
    tree = _make_tree( tmp_path )
    _build( tree )
    _source( tree, "label.ts" ).write_text( "this is not valid typescript ((( \n", encoding="utf-8" )

    result = mod.check_bundle(
        tree, tree / "src" / "scripts" / "build-probe.sh", str( ESBUILD )
    )

    assert result[ "status" ] == mod.REFUSED
    assert "dry-run build failed" in result[ "reason" ]


@needs_esbuild
def test_a_missing_entry_refuses( tmp_path ):
    """An entry that is gone is a refusal, not a verdict about bytes."""
    tree = _make_tree( tmp_path )
    _build( tree )
    _source( tree, "boot.ts" ).unlink()

    result = mod.check_bundle(
        tree, tree / "src" / "scripts" / "build-probe.sh", str( ESBUILD )
    )

    assert result[ "status" ] == mod.REFUSED
    assert "entry not found" in result[ "reason" ]


# ── the report has to carry its own scope, or a green gets over-read ─────────────

@needs_esbuild
def test_the_report_states_the_limit_a_green_does_not_cover( tmp_path ):
    """
    A FRESH is silent about unmerged and unwired work, permanently. That limit is unfixable by
    instrument choice, so it lives in the output text — and a reader who never sees it will
    over-read the green. This asserts the sentence is actually printed.
    """
    tree = _make_tree( tmp_path )
    _build( tree )

    code, out = _run( tree )

    assert code == mod.EXIT_FRESH, out
    assert "unmerged" in out
    assert "not yet imported" in out


@needs_esbuild
def test_the_report_names_the_source_count_and_both_hashes( tmp_path ):
    """Mr. Radio's requirement. A bare verdict is the easiest thing in a log to wave at."""
    tree    = _make_tree( tmp_path )
    shipped = _build( tree )

    code, out = _run( tree )
    header    = [ line for line in out.splitlines() if line.strip().startswith( "probe" ) ]

    assert code == mod.EXIT_FRESH, out
    assert header, f"no report row for the probe bundle:\n{out}"
    assert shipped in header[ 0 ], "the shipped hash must appear on the row"
    assert " 2 " in header[ 0 ], f"the source count (2) must appear on the row: {header[ 0 ]}"


def test_the_root_is_derived_from_the_script_not_from_lupin_root( tmp_path, monkeypatch ):
    """
    $LUPIN_ROOT IS NOT CONSULTED — the wrong-tree family's remedy. A script shipped inside the
    tree it inspects can only be disagreed with by the environment, never informed by it.
    """
    tree = _make_tree( tmp_path )
    monkeypatch.setenv( "LUPIN_ROOT", "/nonexistent/decoy" )

    completed = subprocess.run(
        [ sys.executable, str( tree / "src" / "scripts" / "check_bundle_freshness.py" ) ],
        capture_output=True, text=True, check=False
    )

    assert str( tree ) in completed.stdout, \
        "the script reported on a tree other than the one it lives in"
    assert "/nonexistent/decoy" not in completed.stdout


# ── parsing the real build drivers, not a fixture of them ────────────────────────

def test_the_production_flags_are_read_from_the_real_build_script():
    """
    The flags must come from build-multiplexer.sh, not from this checker. If the build changes
    its flags and the checker keeps its own copy, the comparison silently becomes meaningless.
    """
    spec = mod.parse_build_script( REPO_ROOT / "src" / "scripts" / "build-multiplexer.sh" )

    assert spec[ "entry"        ] == "src/lupin_app/static/js/multiplexer/boot.ts"
    assert spec[ "outdir"       ] == "src/lupin_app/static/dist/multiplexer"
    assert spec[ "out_basename" ] == "boot.js"
    assert "--minify"     in spec[ "flags" ], "the production build minifies; a non-minified compare is a false STALE"
    assert "--keep-names" in spec[ "flags" ]
    assert not any( f.startswith( "--outfile"   ) for f in spec[ "flags" ] )
    assert not any( f.startswith( "--log-level" ) for f in spec[ "flags" ] )


def test_the_watch_branch_is_not_mistaken_for_the_production_build():
    """
    build-multiplexer.sh has TWO esbuild invocations. The `--watch` one omits --minify and
    --keep-names, so reproducing it would compare against a bundle nobody ships — a false
    STALE on every run. This pins that the production block is the one selected.
    """
    text = ( REPO_ROOT / "src" / "scripts" / "build-multiplexer.sh" ).read_text( encoding="utf-8" )
    assert text.count( '"$ESBUILD" \\' ) >= 2, \
        "fixture assumption gone: the build script no longer has both a watch and a production block"

    spec = mod.parse_build_script( REPO_ROOT / "src" / "scripts" / "build-multiplexer.sh" )

    assert "--watch" not in spec[ "flags" ]
    assert "--watch=forever" not in spec[ "flags" ]
    assert "--minify" in spec[ "flags" ]


def test_discovery_skips_a_driver_that_emits_no_manifest():
    """
    build-parity-harness.sh writes no manifest, so there is no recorded hash to compare against.
    Including it would mean inventing a baseline — a check that cannot fail.
    """
    found = { path.name for path in mod.discover_bundles( REPO_ROOT ) }

    assert "build-parity-harness.sh" not in found
    assert "build-multiplexer.sh" in found, "positive control: a real manifest-emitting driver is found"


def test_short_sha_matches_the_build_scripts_own_convention():
    """build-multiplexer.sh computes substr( sha256, 1, 12 ). A different width breaks every compare."""
    assert mod.short_sha( b"" ) == \
        "e3b0c44298fc", "sha256 of empty input, first 12 — the build script's convention"
    assert len( mod.short_sha( b"anything" ) ) == mod.HASH_LENGTH == 12
