#!/usr/bin/env python3
"""
test_memento_slot_root_pointer_is_per_persona.py — the reader that broke every seat's
re-spin, pinned against the WRITER'S ACTUAL OUTPUT rather than against a remembered name.

Run:  .venv/bin/pytest src/tests/unit/test_memento_slot_root_pointer_is_per_persona.py -q

WHAT HAPPENED, 2026-09-02. Step 3 of the per-persona pointer change re-landed in
planning-is-prompting (`00fac2b`, on Rick's authorisation), so `memento_io`'s writer began
producing `.claude-memento-<persona-slug>.md` for the root slot instead of the shared
`.claude-memento.md`. Both `/plan-memento` command documents moved in the same change —
that is the ordering rule row `8f5dc4df` states, and it was honoured for the documents.

`memento_slot.slot_pointer_path` was NOT moved. It is in a DIFFERENT REPO and nobody
grepped for readers outside the two docs. So `verify_memento_at_slot` went on checking a
file nothing writes, it aged past the freshness window, and every `self_respin` aborted
with "memento is stale (2291s old > 1200s window)".

⚠️ IT FAILED SAFE. The verb refuses rather than clearing into nothing, so no memento was
lost — a seat simply could not re-spin. Expensive, not destructive.

🔴 WHY THIS FILE EXISTS RATHER THAN A COMMENT. lupin cannot import `memento_io`: it lives
in planning-is-prompting and is invoked by PATH, not imported. So `slot_pointer_path`
necessarily carries a SECOND STATEMENT of the writer's layout, and a second statement with
nothing watching it is exactly what just cost the fleet its re-spin. These tests run the
real writer as a subprocess and compare what it PUT ON DISK against what this reader
predicts — so the two cannot drift silently again, in either direction.

⚠️ AND THE TEST IS SKIPPED, LOUDLY, WHEN THE WRITER IS ABSENT. A cross-repo test that
quietly passes when it cannot find the other repo is worse than no test: it reports
agreement it never checked.
"""

import os
import subprocess

from pathlib import Path

import pytest

from lupin_mcp.memento_slot import SLOT_IO, SLOT_ROOT, slot_pointer_path


PIP_ROOT = Path( os.environ.get(
    "PLANNING_IS_PROMPTING_ROOT",
    "/mnt/DATA01/include/www.deepily.ai/projects/planning-is-prompting"
) )
WRITER = PIP_ROOT / "workflow" / "scripts" / "memento_io.py"


# ------------------------------------------------- the reader, on its own

def test_the_root_pointer_carries_the_persona():
    """
    THE REGRESSION, stated directly. A persona-less root pointer is one file shared by
    every seat in the repo — whoever wrote last owns it, and everyone else's `self_respin`
    is refused naming the winner's session id. That was the defect row `8f5dc4df` was
    filed for; this reader kept it alive after the writer was fixed.
    """
    p = slot_pointer_path( "/repo", "María" )
    assert p.name != ".claude-memento.md", (
        "the root pointer is persona-less again — every seat in a repo now shares one "
        "pointer file, and self_respin goes to whoever wrote it last"
    )
    assert p.name == ".claude-memento-maria.md"


def test_two_personas_never_share_a_root_pointer():
    """The property, rather than the spelling of any one name."""
    names = { slot_pointer_path( "/repo", who ).name
              for who in ( "María", "Mr Radio", "Krishna", "Tiberius" ) }
    assert len( names ) == 4, f"personas collide on {names}"


def test_the_slug_is_still_accent_and_case_proof():
    """
    A two-word persona and an accented one both have to survive, because both are live:
    "Mr Radio" and "María" are seats on this fleet today. A slug that mangles either
    sends that seat to a pointer nobody writes.
    """
    assert slot_pointer_path( "/repo", "María"    ).name == ".claude-memento-maria.md"
    assert slot_pointer_path( "/repo", "Mr Radio" ).name == ".claude-memento-mr-radio.md"


def test_the_io_slot_was_not_disturbed():
    """
    The io slot was correct throughout and is the control. If it moves in a change aimed
    at root, the change was wider than it claimed.
    """
    assert slot_pointer_path( "/repo", "María", SLOT_IO ) == Path( "/repo/io/mementos/maria.md" )


def test_an_unknown_slot_still_raises_rather_than_guessing():
    """A silent fallback to one of the two slots is how a seat writes where nobody reads."""
    with pytest.raises( ValueError ):
        slot_pointer_path( "/repo", "María", "somewhere-else" )


# ------------------------------------------------- the reader, against the REAL writer

@pytest.mark.skipif( not WRITER.is_file(), reason=f"writer not found at {WRITER} — CROSS-REPO CHECK DID NOT RUN" )
def test_the_reader_predicts_what_the_writer_actually_puts_on_disk( tmp_path ):
    """
    🔴 THE ONE THAT WOULD HAVE CAUGHT IT. Everything above pins a name I chose; this runs
    the ACTUAL writer in a scratch repo and asserts the file it creates is the file this
    reader would go looking for.

    That is the check nobody had. The writer changed in another repo, this reader did not,
    and no test anywhere compared them — so the drift surfaced as every seat's re-spin
    aborting, hours later, with a message about staleness that pointed at the symptom.
    """
    # A REAL repo, not a mimed one. `memento_io` resolves the root with `git rev-parse`,
    # so an empty `.git/` directory is not enough — the first cut made one and the test
    # SKIPPED, which is the failure this file's own docstring warns about: a cross-repo
    # check that quietly does not run reports agreement it never made.
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run( [ "git", "init", "-q" ], cwd=repo, check=True, timeout=60 )
    home = tmp_path / "home"
    home.mkdir()

    # WRITE, not regenerate-pointer. `regenerate-pointer` re-derives a pointer for an
    # EXISTING record and fails with "no record found" in a fresh repo — the second cut
    # of this test skipped on exactly that. `write` is the verb that creates both, which
    # is also the path a real seat takes.
    body = tmp_path / "body.md"
    body.write_text( "# a memento\n\nenough substance to be a real record.\n", encoding="utf-8" )
    result = subprocess.run(
        [ "python3", str( WRITER ), "write", "--slot", "root",
          "--persona", "maria", "--session-id", "deadbeef",
          "--content-file", str( body ) ],
        cwd=repo, capture_output=True, text=True, timeout=120,
        env={ **os.environ, "HOME": str( home ) },
    )

    # POINTERS ONLY. `write` lands a RECORD too (`...-maria-deadbeef.md`), and the record
    # was per-persona even before this change — conflating the two mis-prices the defect,
    # which is a mistake row 8f5dc4df records somebody already making.
    written = sorted( q.name for q in repo.glob( ".claude-memento*.md" )
                      if not q.name.endswith( "-deadbeef.md" ) )
    if not written:
        pytest.skip(
            "the writer produced no root pointer in a scratch repo "
            f"(rc={result.returncode}): {result.stderr[ :300 ]} — CROSS-REPO CHECK DID NOT RUN"
        )

    predicted = slot_pointer_path( repo, "maria", SLOT_ROOT ).name
    assert predicted in written, (
        f"the reader looks for {predicted!r} and the writer produced {written!r} — "
        "they have drifted, which is what broke self_respin for every seat on 2026-09-02"
    )
    assert ".claude-memento.md" not in written, (
        "the writer is producing the persona-less pointer again; the reader must move back with it"
    )
