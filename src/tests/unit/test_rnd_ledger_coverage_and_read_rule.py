"""
The R&D ledger covers each doc present at its sha, and CLAUDE.md carries the read rule.

The exit gate of R&D triage in the documentation rewrite plan (section 9 of
`src/rnd/v0.2.2/2026.09.30-lupin-af-documentation-rewrite-plan/2026.09.30-docs-rewrite-implementation-plan.md`)
is two artifacts. One is a rule in the root CLAUDE.md that keeps history out of agent context. The
other is `src/docs/rnd-ledger.tsv`, which classifies every doc under `src/rnd` and `src/cosa/rnd`.

The population comes from git and never from the ledger. A test over every classified doc would
be circular, because a classified doc is in the ledger already. The required set is the tracked
files that were also present at the newest sha the ledger names.

A doc added after that sha is not required. It takes the default class `new` until the next
sweep, so this file stays green when a seat adds a doc between sweeps.

Each check is watched failing. The helper functions run against a ledger with a row removed.
They also run against a CLAUDE.md without the rule. A green result on the real tree then means
the instrument can find something.

This file does not assert that any class in the ledger is right, or that the rule is enforced.
The rule is advisory until an archive path can take a `permissions.deny` entry, as the plan's
ruling on history in agent context says.
"""

import csv
import subprocess

from pathlib import Path

import pytest

import cosa.utils.util as cu
from cosa.repo.doc_lint import rnd_gate0


LEDGER_REL    = "src/docs/rnd-ledger.tsv"
CLAUDE_MD_REL = "CLAUDE.md"
RULE_HEADING  = "## R&D read rule"
CLASSES       = frozenset( { "in force", "superseded", "history", "new", "follows folder" } )
COLUMNS       = [ "path", "class", "reason", "date", "sha" ]


def _git( root, *args ):
    """
    Run one git command in a tree and return its stdout.

    Requires:
        - root is a git working tree

    Ensures:
        - returns stdout text on exit code 0

    Raises:
        - AssertionError carrying git's stderr on a non-zero exit
    """
    res = subprocess.run( [ "git", "-C", str( root ), *args ], capture_output=True, text=True, encoding="utf-8" )
    assert res.returncode == 0, res.stderr
    return res.stdout


def read_ledger( root ):
    """
    Read the ledger into rows.

    Requires:
        - root holds src/docs/rnd-ledger.tsv

    Ensures:
        - returns ( header, rows ) where each row is a list of the five column values

    Raises:
        - FileNotFoundError when the ledger file is absent
    """
    with open( Path( root ) / LEDGER_REL, encoding="utf-8", newline="" ) as handle:
        table = list( csv.reader( handle, delimiter="\t" ) )
    return table[ 0 ], table[ 1: ]


def required_population( root, ledger_shas ):
    """
    List the R&D files the ledger must cover: tracked now and present at its newest sha.

    Requires:
        - root is a git working tree
        - ledger_shas is a non-empty collection of full shas, each reachable in root

    Ensures:
        - returns a sorted list of repo-relative paths from git ls-files, never from a disk walk
        - a file added after the newest sha is left out, a file deleted since is left out

    Raises:
        - AssertionError when a sha is not reachable or the newest sha cannot be chosen
    """
    newest = _git( root, "rev-list", "--no-walk", "--topo-order", *sorted( ledger_shas ) ).split()[ 0 ]
    for sha in ledger_shas:
        _git( root, "merge-base", "--is-ancestor", sha, newest )
    at_sha  = set( _git( root, "ls-tree", "-r", "--name-only", newest, "--", "src/rnd", "src/cosa/rnd" ).split( "\n" ) )
    tracked = rnd_gate0.rnd_population( root )
    return sorted( p for p in tracked if p in at_sha )


def uncovered( ledger_rows, required ):
    """
    Name every required path that has no ledger row.

    Requires:
        - ledger_rows is a list of rows whose first value is the path
        - required is an iterable of paths

    Ensures:
        - returns a sorted list of the required paths absent from the ledger

    Raises:
        - nothing
    """
    covered = { row[ 0 ] for row in ledger_rows }
    return sorted( p for p in required if p not in covered )


def read_rule_problems( claude_md_text ):
    """
    Say what is wrong with the read rule in a CLAUDE.md text, or return an empty list.

    Requires:
        - claude_md_text is a str

    Ensures:
        - checks the heading `## R&D read rule` occurs exactly once on a line of its own
        - checks the section under it, up to the next `## ` heading, names the ledger path
        - returns a list of plain-English problems, empty when the rule is present

    Raises:
        - nothing
    """
    lines    = claude_md_text.split( "\n" )
    at       = [ i for i, line in enumerate( lines ) if line.strip() == RULE_HEADING ]
    if len( at ) != 1: return [ f"expected exactly one line '{RULE_HEADING}', found {len( at )}" ]
    section  = []
    for line in lines[ at[ 0 ] + 1: ]:
        if line.startswith( "## " ): break
        section.append( line )
    body     = "\n".join( section )
    problems = []
    if LEDGER_REL not in body: problems.append( f"the section does not name {LEDGER_REL}" )
    return problems


@pytest.fixture( scope="module" )
def root():
    return cu.get_project_root()


@pytest.fixture( scope="module" )
def ledger( root ):
    return read_ledger( root )


def test_ledger_file_exists_with_the_five_columns( ledger ):
    """The ledger is present and its header is path, class, reason, date, sha."""
    header, rows = ledger
    assert header == COLUMNS
    assert len( rows ) > 0


def test_every_ledger_row_has_five_values_and_a_known_class( ledger ):
    """A row with a missing column or an invented class is a ledger nobody can parse."""
    _, rows = ledger
    bad = [ r[ 0 ] for r in rows if len( r ) != 5 or r[ 1 ] not in CLASSES ]
    assert bad == [], f"{len( bad )} rows are malformed or carry an unknown class, first: {bad[ :5 ]}"


def test_ledger_has_one_row_per_path( ledger ):
    """A path listed twice could carry two classes."""
    _, rows = ledger
    paths = [ r[ 0 ] for r in rows ]
    assert len( paths ) == len( set( paths ) )


def test_ledger_covers_every_rnd_doc_present_at_its_sha( root, ledger ):
    """
    The population is git's, restricted to what existed at the ledger's newest sha.

    Counted first, so a loop over nothing cannot pass: the required set has to be non-empty.
    """
    _, rows = ledger
    required = required_population( root, { r[ 4 ] for r in rows } )
    assert len( required ) > 0, "the required population is empty: the instrument found nothing"
    missing = uncovered( rows, required )
    assert missing == [], f"{len( missing )} R&D files present at the ledger sha have no row, first: {missing[ :5 ]}"


def test_the_coverage_check_reports_a_removed_row( root, ledger ):
    """Positive control: a removed ledger row is reported."""
    _, rows = ledger
    required = required_population( root, { r[ 4 ] for r in rows } )
    before   = uncovered( rows, required )
    dropped  = rows[ len( rows ) // 2 ][ 0 ]
    assert dropped in required, "the control row must be inside the required population"
    after    = uncovered( [ r for r in rows if r[ 0 ] != dropped ], required )
    assert after == sorted( set( before ) | { dropped } )


def test_the_coverage_check_reports_a_doc_the_ledger_never_saw( root, ledger ):
    """Positive control: a required path that is not in the ledger at all is reported."""
    _, rows = ledger
    required = required_population( root, { r[ 4 ] for r in rows } )
    phantom  = "src/rnd/v9.9.9/2099.01.01-never-ledgered.md"
    assert phantom in uncovered( rows, list( required ) + [ phantom ] )


def test_a_doc_added_after_the_ledger_sha_is_not_required( tmp_path ):
    """
    A doc added after the ledger sha is not required, and neither is a deleted one.

    Runs on a throwaway repo with one doc at the sha, one added later and one removed since.
    """
    _git( tmp_path, "init", "-q" )
    for rel in ( "src/rnd/a.md", "src/rnd/gone.md" ):
        ( tmp_path / rel ).parent.mkdir( parents=True, exist_ok=True )
        ( tmp_path / rel ).write_text( "x\n", encoding="utf-8" )
    _git( tmp_path, "add", "-A" )
    _git( tmp_path, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "base" )
    sha = _git( tmp_path, "rev-parse", "HEAD" ).strip()
    ( tmp_path / "src/rnd/later.md" ).write_text( "x\n", encoding="utf-8" )
    _git( tmp_path, "rm", "-q", "src/rnd/gone.md" )
    _git( tmp_path, "add", "-A" )
    _git( tmp_path, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "after" )
    assert required_population( tmp_path, { sha } ) == [ "src/rnd/a.md" ]


def test_claude_md_carries_the_read_rule( root ):
    """The root CLAUDE.md has the `## R&D read rule` section and it names the ledger path."""
    text = ( Path( root ) / CLAUDE_MD_REL ).read_text( encoding="utf-8" )
    assert read_rule_problems( text ) == []


def test_the_read_rule_check_reports_a_missing_rule():
    """Positive control: a CLAUDE.md with no rule, with two, and with the ledger path missing."""
    assert read_rule_problems( "# Lupin\n\n## Commands\n- x\n" ) != []
    assert read_rule_problems( f"{RULE_HEADING}\n{LEDGER_REL}\n\n{RULE_HEADING}\n{LEDGER_REL}\n" ) != []
    assert read_rule_problems( f"{RULE_HEADING}\nrule text without the path\n## Next\n{LEDGER_REL}\n" ) != []
    assert read_rule_problems( f"{RULE_HEADING}\nsee {LEDGER_REL}\n## Next\n" ) == []
