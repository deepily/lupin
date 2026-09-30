"""
Row 1661ece3 — a repo-ROOT file the test corpus reads must EXIST in the venue
that runs the corpus, not merely be declared somewhere.

WHAT WENT WRONG, AND WHY NOTHING CAUGHT IT
    On 2026-09-19 a scheduled :8000 run printed, in its own tree-state line,
    `tracked-dirty=129 deleted=127 ... root=/var/lupin`. 127 tracked files did
    not exist in the container. Among them CLAUDE.md, which two merge-gate tests
    read: test_typescript_suite_gate.py parses the `merge-pyramid-suites` marker
    out of it, test_bridge_dir_guard.py looks for `## PR MERGE REQUIREMENTS`.
    The first went red with FileNotFoundError. The second had been taught to
    SKIP when the file is missing — the same blindness, wearing a green.

    test_repo_root_artifact_mount_parity.py already guards this, and did not
    catch it, for a reason worth stating rather than patching around: its
    discovered arm derives its universe from ONE guard's predicate — the
    executable surfaces test_no_hardcoded_gcp_identifiers walks. CLAUDE.md is
    a markdown document, so it was never in that universe. A comparator is only
    as wide as the population it is built on.

    That file also asks a DIFFERENT question from this one. It reads
    docker-compose.yml and asks whether the mount is DECLARED. Declaration is
    not presence: mount specs resolve at container CREATE, so a compose file
    that names every root file still leaves them absent until somebody runs
    `docker compose up -d --force-recreate`. A `docker restart` will not do it.
    This file asks the runtime question instead — is the file HERE, in the
    venue actually executing this test — which is the only form that can fail
    on a container nobody recreated.

THE PREDICATE, WHICH DOES NOT GUESS
    universe = { depth-1 entries of `git ls-files` } ∩ { names the tracked
    Python under src/tests/ mentions as a literal string }.

    Both halves are derived: the first from git, the second from the corpus
    that would break. Neither is a list of filenames somebody thought of, which
    is the failure mode the 2026-09-19 miss and the first cut of
    test_repo_root_artifact_mount_parity.py share.

    ⚠️ A MENTION IS NOT A READ, and this file over-includes on purpose. A name
    in a docstring counts the same as an `open()`. For a presence guard that is
    the safe direction to be wrong in: the remedy for a false positive is to
    make the file present, which costs a mount and breaks nothing. It would be
    the wrong trade for a guard whose remedy were expensive.

Venue: runs wherever the unit tier runs — which is the point. On the host every
file is present and this is cheap and green; in a venue missing them it is red,
and it names them.
"""
import os
import subprocess

import pytest

import cosa.utils.util as cu

PROJECT_ROOT = cu.get_project_root()

# The anchor the row is about. Named explicitly so that a predicate that quietly
# stops finding anything cannot take this case down with it — see
# test_the_predicate_still_finds_the_anchor below.
MERGE_GATE_ANCHOR = "CLAUDE.md"


def _git( *args ):
    """
    Run a git command in PROJECT_ROOT and return its stdout lines.

    Requires:
        - args is a git sub-command and its arguments
    Ensures:
        - returns a list of non-empty stdout lines
    Raises:
        - RuntimeError if git is absent or exits non-zero. It REFUSES rather
          than returning an empty list, because an empty universe would make
          every comparator below vacuously green — certifying a venue it never
          examined, which is this file's own subject.
    """
    try:
        done = subprocess.run(
            [ "git", *args ], cwd=PROJECT_ROOT, capture_output=True, text=True
        )
    except OSError as e:
        raise RuntimeError( f"git is not runnable in {PROJECT_ROOT}: {e}" ) from e
    if done.returncode != 0:
        raise RuntimeError( f"git {' '.join( args )} exited {done.returncode}: {done.stderr.strip()}" )
    return [ line for line in done.stdout.split( "\n" ) if line ]


def _tracked_root_entries():
    """
    Ensures:
        - returns the sorted set of depth-1 names in the index — both files
          sitting directly at the repo root and the top directory of every
          deeper path
    """
    return sorted( { path.split( "/" )[ 0 ] for path in _git( "ls-files" ) } )


def _test_corpus_text():
    """
    Ensures:
        - returns the concatenated text of every tracked .py under src/tests/
        - a file that cannot be decoded contributes nothing rather than
          aborting the scan; the scan is a mention-finder, not a parser
    """
    chunks = []
    for rel in _git( "ls-files", "src/tests/*.py" ):
        full = os.path.join( PROJECT_ROOT, rel )
        with open( full, encoding="utf-8", errors="replace" ) as fh:
            chunks.append( fh.read() )
    return "\n".join( chunks )


def _root_entries_the_corpus_names():
    """
    Ensures:
        - returns the sorted depth-1 tracked names that appear as a literal
          substring anywhere in the tracked test corpus
    """
    text = _test_corpus_text()
    return [ name for name in _tracked_root_entries() if name in text ]


@pytest.fixture( scope="module" )
def named_entries():
    return _root_entries_the_corpus_names()


# ══════════════════════════════════════════════════════════════════════════
# Instrument checks — a broken predicate must fail here, not pass below
# ══════════════════════════════════════════════════════════════════════════

def test_the_predicate_yields_a_real_universe( named_entries ):
    """
    A scan that finds nothing looks exactly like a venue with nothing missing.
    Prove the instrument can find something before trusting it to find nothing.
    """
    assert len( named_entries ) >= 10, (
        f"only {len( named_entries )} root entries named by the test corpus — "
        f"the scan broke, it did not get cleaner"
    )


def test_the_predicate_still_finds_the_anchor( named_entries ):
    """
    CLAUDE.md is the file row 1661ece3 is about. If the derived universe ever
    stops containing it, the comparator below is no longer watching the case
    this file exists for — and would say so by passing.
    """
    assert MERGE_GATE_ANCHOR in named_entries, (
        f"{MERGE_GATE_ANCHOR} is no longer in the derived universe — the two "
        f"merge-gate tests that read it are now unwatched by this guard"
    )


# ══════════════════════════════════════════════════════════════════════════
# The venue check
# ══════════════════════════════════════════════════════════════════════════

def test_the_merge_gate_anchor_is_present_and_readable_here():
    """
    The specific failure of row 1661ece3, asserted on its own so the red names
    the file rather than a count.
    """
    path = os.path.join( PROJECT_ROOT, MERGE_GATE_ANCHOR )
    assert os.path.isfile( path ), (
        f"{MERGE_GATE_ANCHOR} is ABSENT from this venue ({PROJECT_ROOT}). "
        f"test_typescript_suite_gate.py and test_bridge_dir_guard.py both read "
        f"it; one goes red and the other SKIPS. If this is a container, its "
        f"mounts are stale — `docker compose up -d --force-recreate <service>`, "
        f"never a restart."
    )
    assert open( path, encoding="utf-8" ).read().strip(), f"{MERGE_GATE_ANCHOR} is present but EMPTY"


def test_every_root_entry_the_test_corpus_names_exists_here( named_entries ):
    """
    THE COMPARATOR. Every depth-1 tracked name the test corpus mentions must
    exist in the venue running this test.
    """
    absent = [ name for name in named_entries
               if not os.path.exists( os.path.join( PROJECT_ROOT, name ) ) ]
    assert not absent, (
        f"{len( absent )} repo-root entries named by the test corpus are ABSENT "
        f"from this venue ({PROJECT_ROOT}): {absent}. Tests reading them fail "
        f"here while passing on the host. If this is a container, recreate it — "
        f"`docker compose up -d --force-recreate <service>` — a restart keeps "
        f"the old mount specs."
    )
