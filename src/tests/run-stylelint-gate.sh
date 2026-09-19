#!/bin/bash
# Runs stylelint over EVERY git-tracked .css file and fails if any file has an error.
#
# Usage:
#   run-stylelint-gate.sh              # the whole population
#   run-stylelint-gate.sh --list       # print the population and exit 0
#
# WHY THIS EXISTS. Row d3d4a18c: "32 stylelint errors, pre-existing" was waved past at
# least twice, because no gate ran stylelint — not an npm script, not a runner, not the
# pre-commit hook, not ALL_SUITE_COMPONENTS. Re-measured 2026-09-18 at 2436af99 the real
# figure was 329 errors in 21 of 32 files; the "32" was one file's count. Cleared to 0 in
# three commits, and Rick ruled at 21:06 the same day that stylelint becomes a fast :7999
# merge gate so the number cannot grow back unseen.
#
# THE POPULATION IS `git ls-files '*.css'` — 32 files at 0d1a69f0. Derived from git, not
# from a glob, because a glob over the disk also sweeps untracked and ignored CSS (build
# output, a borrowed node_modules), which is a different population from the tree under
# review. ⚠️ A NAMED GAP: 33 tracked .html files carry inline <style> blocks, and stylelint
# does not read them without postcss-html, which is not installed. This gate says nothing
# about them.
#
# Called by TestSuiteJob when test_types="stylelint".
#
# Created: 2026-09-18 (row d3d4a18c, Rick's ruling 21:06)

set -uo pipefail

# Up TWO levels — this script lives at src/tests/. Derived from BASH_SOURCE, never from
# $LUPIN_ROOT, so it always checks the tree it was shipped in (the typecheck gate's rule).
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$( cd "$SCRIPT_DIR/../.." && pwd )"
cd "$PROJECT_ROOT" || exit 1

export LUPIN_ROOT="$PROJECT_ROOT"

STYLELINT="$PROJECT_ROOT/node_modules/.bin/stylelint"
CONFIG="$PROJECT_ROOT/.stylelintrc.json"

mapfile -t FILES < <( git -C "$PROJECT_ROOT" ls-files -- '*.css' )

if [ "${1:-}" = "--list" ]; then
    printf '%s\n' "${FILES[@]}"
    exit 0
fi

# 🔴 REFUSE RATHER THAN REPORT A CLEAN NOTHING. Every one of these makes the gate pass
# vacuously — a gate that checked nothing prints exactly what a clean tree prints — so
# each is named and exits 2, which TestSuiteJob reads as NOT EXECUTED, never PASSED.
if [ "${#FILES[@]}" -eq 0 ]; then
    echo "REFUSING: git ls-files found no .css files under $PROJECT_ROOT. Nothing was checked."
    exit 2
fi
if [ ! -f "$CONFIG" ]; then
    echo "REFUSING: .stylelintrc.json is not present at the project root. Nothing was checked."
    exit 2
fi
if [ ! -x "$STYLELINT" ]; then
    echo "REFUSING: no stylelint at node_modules/.bin/stylelint. Nothing was checked."
    echo "  In a worktree this usually means node_modules was never borrowed —"
    echo "  run src/scripts/link-worktree-artifacts.sh <worktree> first."
    exit 2
fi

echo "=========================================================================="
echo "Stylelint gate — ${#FILES[@]} tracked .css files"
echo "  root      : $PROJECT_ROOT"
echo "  stylelint : $( "$STYLELINT" --version )"
echo "=========================================================================="

REPORT="$( mktemp )"
trap 'rm -f "$REPORT"' EXIT

"$STYLELINT" --config "$CONFIG" --formatter json --output-file "$REPORT" -- "${FILES[@]}" > /dev/null 2>&1
RC=$?

# stylelint exits 0 clean, 2 on lint errors, 78 on a bad config and 1 on anything else.
# Only 0 and 2 produce a report that describes the files.
if [ "$RC" -ne 0 ] && [ "$RC" -ne 2 ]; then
    echo "REFUSING: stylelint exited $RC, which is not a lint result. Nothing was checked."
    "$STYLELINT" --config "$CONFIG" -- "${FILES[@]}" 2>&1 | tail -20 | sed 's/^/    /'
    exit 2
fi

# One line per problem, then the FILE counts. A file fails if it carries any error-severity
# problem, including a stylelint-disable with no `-- reason` (reportDescriptionlessDisables).
SUMMARY="$( node -e '
const fs = require( "fs" );
const results = JSON.parse( fs.readFileSync( process.argv[ 1 ], "utf8" ) );
const root = process.argv[ 2 ] + "/";
let failedFiles = 0, errors = 0;
for ( const r of results ) {
  const errs = r.warnings.filter( ( w ) => w.severity === "error" );
  if ( errs.length > 0 ) failedFiles++;
  errors += errs.length;
  for ( const w of r.warnings ) {
    console.log( `    ${ w.severity.toUpperCase() } ${ r.source.replace( root, "" ) }:${ w.line }:${ w.column }  ${ w.text }` );
  }
}
console.log( `COUNTS ${ results.length } ${ failedFiles } ${ errors }` );
' "$REPORT" "$PROJECT_ROOT" )"

printf '%s\n' "$SUMMARY" | grep -v '^COUNTS '
read -r _ LINTED FAILED ERRORS <<< "$( printf '%s\n' "$SUMMARY" | grep '^COUNTS ' )"

# stylelint must have read every file it was handed. Fewer means some were skipped, and a
# skipped file is an unchecked file.
if [ "$LINTED" -ne "${#FILES[@]}" ]; then
    echo "REFUSING: stylelint reported $LINTED files of the ${#FILES[@]} it was given."
    exit 2
fi

# Summary in the shape TestSuiteJob._parse_non_pytest_stdout already reads. ⚠️ ITS UNIT IS
# FILES, NOT TESTS AND NOT ERRORS: "Failed: 1" means one file is red, which may carry one
# error or a hundred. The error count is printed on its own line so the two are never merged.
echo
echo "=========================================================================="
echo "Total Tests: ${#FILES[@]}"
echo "Passed: $(( ${#FILES[@]} - FAILED ))"
echo "Failed: $FAILED"
echo "Errors: $ERRORS"
echo "=========================================================================="

if [ "$FAILED" -gt 0 ]; then
    echo "STYLELINT GATE FAILED — $ERRORS errors in $FAILED of ${#FILES[@]} files."
    exit 1
fi

echo "STYLELINT GATE PASSED — all ${#FILES[@]} files clean."
exit 0
