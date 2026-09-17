"""
A parity test names the legacy `file:line` it mirrors — build plan §6 item 19,
weak form, ruled by Mr. Radio 🦉 2026-09-17.

WHY THIS FILE EXISTS: §6 item 19 was a convention, and a rule that depends on
remembering is not installed. Nine test files already claim a parity row key in
their header; two of them name the legacy coordinate they mirror. Nothing
noticed the other seven, because nothing was looking.

THE RECOGNISER IS THE CLAIM, NOT THE CITATION. The obvious predicate — "a
parity test is one that cites a legacy file:line" — is a tautology: the citation
IS the thing being checked, so a test that forgot its citation is invisible to a
guard that finds parity tests by their citations. Such a guard is green on an
empty set and can never report a violation. So the population here is DECLARED:
a test opts in by naming its build-item row key in its header comment
("Parity A-0", "parity A-2 #2b"), and the row key must be one the manifest
actually lists. The denominator is the manifest's 42 row keys, and this file
asserts that denominator before it asserts anything about the tests.

"HEADER COMMENT", NOT "DOCSTRING". Item 19's cell said docstring; these are
TypeScript files and have none. The header is the first HEADER_LINES lines.

WEAK FORM vs STRONG FORM. Weak (here): the coordinate is PRESENT and
well-formed. Strong (owed, registered separately): the coordinate RESOLVES —
it appears in the accordion the row derives from. The strong form was not
buildable until `io/phase2` was tracked (§6 item 20, commit f63350e3); it is
owed work, not a thing this file quietly covers.

WHAT THIS FILE DOES NOT ASSERT: that a cited coordinate is the RIGHT one, or
that it still points at the code it pointed at when it was written. A line
number is a coordinate and goes stale; catching that is the strong form's job.
"""

import re

from pathlib import Path

import pytest

import cosa.utils.util as cu


MANIFEST_REL = "src/rnd/v0.2.1/2026.09.16-parity-build-row-manifest.md"

# The first N lines of a test file are its header comment. Generous enough to
# clear a licence block, tight enough that a citation buried beside an
# assertion 200 lines down does not count as naming the test's source.
HEADER_LINES = 12

# A row key as the manifest's summary table writes it: A-0, A-1c3, A-2 #2b, B-7.
ROW_KEY = r"(?:A-\d+[a-z]?\d*(?:\s*#\d+[a-z]?)?|B-\d+)"

# A test opts in by naming its row key after the word "parity", in any case.
CLAIMS_A_ROW = re.compile( r"parity\s+(" + ROW_KEY + r")", re.IGNORECASE )

# The legacy client is two files, and a coordinate is a line or a line range.
LEGACY_COORD = re.compile( r"notifications\.(?:js|html):\d+(?:-\d+)?" )

# The manifest's summary table: | Row key | Title | Pri | Depends-on |
MANIFEST_ROW = re.compile( r"^\|\s*(" + ROW_KEY + r")\s*\|" )

# Seven files claimed a row key before this guard existed and none of them names
# its legacy source. They are GRANDFATHERED so the guard can land green, and the
# list is a CEILING, not a floor: `test_the_grandfather_list_only_shrinks`
# fails when an entry stops violating, so the list cannot outlive the debt it
# records. Do not add to it — a new parity test names its source or goes red.
GRANDFATHERED = frozenset( {
    "src/tests/unit/multiplexer/action_required_persistence.test.ts",
    "src/tests/unit/multiplexer/boot_wires_action_required_to_reveal_through_the_toolbar.test.ts",
    "src/tests/unit/multiplexer/render/action_required_cancel.test.ts",
    "src/tests/unit/multiplexer/render/action_required_pause.test.ts",
    "src/tests/unit/multiplexer/render/action_required_progress.test.ts",
    "src/tests/unit/multiplexer/render/shared_row_controls_reach_every_pane.test.ts",
    "src/tests/unit/notifications_js/two_renderers_one_class_name.test.ts",
} )


def _normalize( row_key ):
    """
    Collapse a row key to a comparable form.

    Requires:
        - row_key is a string

    Ensures:
        - returns the key upper-cased with all internal whitespace removed,
          so "A-2 #2b", "A-2  #2B" and "A-2#2b" compare equal

    Raises:
        - AttributeError if row_key is not a string
    """
    return re.sub( r"\s+", "", row_key ).upper()


@pytest.fixture( scope="module" )
def project_root():
    return Path( cu.get_project_root() )


@pytest.fixture( scope="module" )
def manifest_row_keys( project_root ):
    """Every row key the manifest's summary table lists, normalized."""
    text = ( project_root / MANIFEST_REL ).read_text( encoding="utf-8" )

    keys = set()
    for line in text.splitlines():
        match = MANIFEST_ROW.match( line )
        if match: keys.add( _normalize( match.group( 1 ) ) )

    return keys


@pytest.fixture( scope="module" )
def claiming_tests( project_root ):
    """
    Every test file whose header claims a parity row key.

    Returns a list of ( repo_relative_path, row_key, header_text ) — the
    declared population this guard polices.
    """
    found = []

    for path in sorted( project_root.glob( "src/tests/**/*.test.ts" ) ):
        header = "\n".join( path.read_text( encoding="utf-8" ).splitlines()[ :HEADER_LINES ] )
        match  = CLAIMS_A_ROW.search( header )
        if match: found.append( ( str( path.relative_to( project_root ) ), match.group( 1 ), header ) )

    return found


# ---------------------------------------------------------------------------
# The denominator — asserted before anything is asserted about the tests.
# A loop over nothing passes every assertion inside it.
# ---------------------------------------------------------------------------

def test_the_manifest_is_readable_and_lists_its_rows( manifest_row_keys ):
    """Without the manifest there is no declared population, only a corpus."""
    assert len( manifest_row_keys ) >= 40, (
        f"the manifest's summary table parsed to {len( manifest_row_keys )} row keys; "
        f"42 were counted on 2026-09-17. A parse that collapses to a handful means the "
        f"table's shape changed and this guard is now policing a denominator it invented"
    )


def test_at_least_one_test_claims_a_row( claiming_tests ):
    """
    The guard must be able to find a positive before a zero means anything.

    Nine files claimed a row on 2026-09-17. A drop to zero means the header
    convention changed and every assertion below is passing vacuously.
    """
    assert claiming_tests, (
        "no test file claims a parity row key in its header — either the convention "
        "changed or this guard's recogniser is broken. Either way it is now policing "
        "an empty set and cannot fail"
    )


# ---------------------------------------------------------------------------
# The rule itself
# ---------------------------------------------------------------------------

def test_every_claimed_row_key_is_one_the_manifest_lists( claiming_tests, manifest_row_keys ):
    """A test claiming a row that does not exist is pointing at nothing."""
    unknown = [
        ( path, key ) for path, key, _ in claiming_tests
        if _normalize( key ) not in manifest_row_keys
    ]

    assert not unknown, (
        "these tests claim a parity row key the manifest does not list — a typo, or a "
        "row key that was retired without sweeping the tests that vouch for it:\n  "
        + "\n  ".join( f"{path} claims {key!r}" for path, key in unknown )
    )


def test_a_parity_test_names_the_legacy_source_it_mirrors( claiming_tests ):
    """
    Build plan §6 item 19, weak form: if a test claims a build-item row, its
    header comment carries a well-formed legacy coordinate.

    Exemplar: `src/tests/unit/multiplexer/render/scroll_reveal.test.ts`, whose
    header names the row, the date, the author, and `notifications.js:25386-25408`.
    """
    offenders = [
        ( path, key ) for path, key, header in claiming_tests
        if not LEGACY_COORD.search( header ) and path not in GRANDFATHERED
    ]

    assert not offenders, (
        "these tests claim a parity row but do not name the legacy `file:line` they "
        f"mirror in their first {HEADER_LINES} lines (build plan §6 item 19). Add a "
        "`notifications.js:NNN` or `notifications.html:NNN-NNN` coordinate to the header, "
        "as `render/scroll_reveal.test.ts` does. The coordinate comes from the accordion "
        "the row derives from, in `io/phase2/`:\n  "
        + "\n  ".join( f"{path} claims {key!r}" for path, key in offenders )
    )


# ---------------------------------------------------------------------------
# The grandfather list is a ceiling, not a floor
# ---------------------------------------------------------------------------

def test_the_grandfather_list_only_shrinks( claiming_tests ):
    """
    An entry that no longer violates must leave the list.

    Without this, the list is a place debt goes to be forgotten: a file could be
    fixed and still sit here, and the next reader would take the length of the
    list for the size of the debt. Here it can only shrink.
    """
    claimed_paths = { path for path, _, _ in claiming_tests }

    still_clean = sorted(
        path for path, _, header in claiming_tests
        if path in GRANDFATHERED and LEGACY_COORD.search( header )
    )
    assert not still_clean, (
        "these files now name their legacy source and must be removed from "
        "GRANDFATHERED — the list records debt that is already paid:\n  "
        + "\n  ".join( still_clean )
    )

    departed = sorted( GRANDFATHERED - claimed_paths )
    assert not departed, (
        "GRANDFATHERED names files that no longer claim a parity row — deleted, renamed, "
        "or their header changed. Remove them; a stale entry silently exempts a path that "
        "may come back:\n  " + "\n  ".join( departed )
    )
