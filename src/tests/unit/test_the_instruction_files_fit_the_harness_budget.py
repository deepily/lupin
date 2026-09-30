"""
The repo's instruction files must fit the harness budget, with room for the global file.

🔴 THE DEFECT THIS CLOSES (row cf97df79, Rick's direct order 2026-09-07, broadcast
e254ec7d: "file this as a P1 ticket: CLAUDE.md is over the 150.0k-char limit").

CLAUDE.md reached 303,113 chars — 2.02x the 150k harness limit. The harness truncates
there, so roughly HALF the file was in no session's context, and nothing in a session
said which half. Every seat believed it had read the whole thing. That is the file's own
§ A CLEAN EXIT IS NOT EVIDENCE THE WORK HAPPENED, firing on the file that contains it.

It was cut to ~61k in e7fba80e by pulling receipts out to src/docs/doctrine/ and leaving
rules behind.

⚠️ THE CUT IS NOT THE FIX. The file had grown ~4,000 chars in the four days before it was
measured, one doctrine section at a time, and every one of those additions was reasonable
on its own. Nothing stopped the growth then and nothing stops it now — so this guard is
the control, because a rule that depends on remembering is not installed.

=== WHY A BUDGET AND NOT THE LIMIT ===

The naive assertion is `CLAUDE.md < 150_000`. That is wrong in the direction that matters:
it passes right up until the moment a session actually truncates, because the harness
loads MORE than this one file. Measured 2026-09-08:

    CLAUDE.md              61,147   this repo, tracked, ours to control
    CLAUDE.local.md         2,995   this repo, untracked, still ours
    ~/.claude/CLAUDE.md    39,632   the operator's global file, NOT ours and NOT in this repo
                          -------
                          103,774   against a 150,000 limit

⇒ So the repo's own files do not get the whole budget. They get the limit MINUS whatever
the global file costs, and the global is outside this repository — a test cannot read it
reliably (a CI box, a fresh clone and a teammate's laptop each have a different one, or
none at all).

⇒ THE PREDICATE THIS ENCODES: the repo-controlled instruction files must leave enough
headroom that a realistic global file still fits. GLOBAL_HEADROOM is that reservation,
and it is deliberately larger than the global measured above — a budget that assumes
today's global exactly would redden the moment the operator added a paragraph to a file
this repo does not own, which is a red nobody here could act on.

⚠️ WHAT THIS GUARD CANNOT SEE, said plainly rather than left for someone to discover: it
does NOT measure the operator's global file, and it therefore cannot prove a given
session stayed under the limit. It proves only that THIS REPO is not the reason one
blew it. If the global grows past GLOBAL_HEADROOM the ceiling is breached and this test
stays green — that is a gap, not an oversight, and closing it needs a reader the harness
provides and we do not have.

=== NOT ESTABLISHED, and the row said so too ===

· WHICH half survives truncation — head or tail, and at what boundary. Never measured.
· Whether the truncation is announced to the model or silent.
Both are moot while the total is under the limit, which is the state this guard defends.
They stop being moot the moment it reddens.
"""

import os

import pytest

import cosa.utils.util as cu


# ── the budget, and the arithmetic that produced it ───────────────────────────

HARNESS_LIMIT   = 150_000   # chars the harness will load before it truncates
GLOBAL_HEADROOM =  60_000   # reserved for ~/.claude/CLAUDE.md, which this repo does not own
REPO_BUDGET     = HARNESS_LIMIT - GLOBAL_HEADROOM

# Repo-controlled files the harness loads at session start. CLAUDE.local.md is untracked
# but is still ours and still costs budget, so it is measured when present and skipped
# when it is not — a fresh clone has no local file and must not redden for that.
INSTRUCTION_FILES = (
    ( "CLAUDE.md",       True  ),   # ( relative path, must_exist )
    ( "CLAUDE.local.md", False ),
)


def _measured_files():
    """
    Read the repo's instruction files off disk and return their sizes.

    Requires:
        - LUPIN_ROOT resolves to a real checkout of this repository

    Ensures:
        - returns a list of ( rel_path, chars ) for every INSTRUCTION_FILES entry
          that exists on disk, in declaration order
        - a must_exist entry that is absent raises rather than being skipped, so a
          renamed or deleted CLAUDE.md is a LOUD failure and never a silent pass
        - sizes are CHARACTER counts decoded as UTF-8, not byte counts — the harness
          limit is quoted in chars and this file is full of multi-byte glyphs, so
          os.path.getsize would over-report and redden the guard for the wrong reason

    Raises:
        - FileNotFoundError if a must_exist file is missing
    """
    root    = cu.get_project_root()
    results = []

    for rel, must_exist in INSTRUCTION_FILES:
        path = os.path.join( root, rel )
        if not os.path.isfile( path ):
            if must_exist:
                raise FileNotFoundError(
                    f"{rel} is missing from {root}. This guard measures the instruction "
                    f"files the harness loads; if the file was renamed, rename it here too "
                    f"rather than deleting this assertion."
                )
            continue
        with open( path, encoding="utf-8" ) as fh:
            results.append( ( rel, len( fh.read() ) ) )

    return results


def test_the_guard_found_the_files_it_claims_to_measure():
    """
    A loop over nothing passes every assertion inside it, so prove the corpus is non-empty
    and that CLAUDE.md itself is in it BEFORE any size assertion is allowed to mean anything.

    Ensures:
        - at least one instruction file was measured
        - CLAUDE.md specifically is among them
        - every measured size is greater than zero, so an empty or unreadable file cannot
          buy headroom by looking small
    """
    measured = _measured_files()

    assert measured, "no instruction files were measured — the guard is vacuous"

    names = [ rel for rel, _ in measured ]
    assert "CLAUDE.md" in names, f"CLAUDE.md was not measured; corpus was {names}"

    for rel, chars in measured:
        assert chars > 0, f"{rel} measured {chars} chars — an empty file is not a small file"


def test_the_repo_instruction_files_stay_inside_the_budget():
    """
    The load-bearing assertion. The repo's own instruction files must total under
    REPO_BUDGET, leaving GLOBAL_HEADROOM for the operator's global file.

    Ensures:
        - the sum of all measured instruction files is strictly under REPO_BUDGET
        - the failure message names the per-file breakdown, the total, the budget and the
          overage, so whoever hits it can act without re-deriving anything

    Raises:
        - AssertionError naming what to do: split receipts out to src/docs/doctrine/ and
          leave a one-line pointer, which is the move that took 303k to 61k in e7fba80e
    """
    measured = _measured_files()
    total    = sum( chars for _, chars in measured )

    breakdown = "\n".join( f"    {rel:20s} {chars:>8,}" for rel, chars in measured )

    assert total < REPO_BUDGET, (
        f"the repo's instruction files total {total:,} chars, over the {REPO_BUDGET:,} budget "
        f"by {total - REPO_BUDGET:,}.\n"
        f"{breakdown}\n"
        f"    {'':20s} {'':>8s}\n"
        f"    budget = {HARNESS_LIMIT:,} harness limit - {GLOBAL_HEADROOM:,} reserved for the "
        f"global ~/.claude/CLAUDE.md, which this repo does not own.\n"
        f"⇒ THE FIX IS NOT TO RAISE THE BUDGET. Move receipts — the measurements, the "
        f"reconciliations, the worked examples — out to src/docs/doctrine/ and leave the RULE "
        f"plus a one-line pointer. That is what took CLAUDE.md from 303,113 to ~61,000 in "
        f"e7fba80e without losing a single finding.\n"
        f"⚠️ Raising GLOBAL_HEADROOM or HARNESS_LIMIT to go green is tuning a threshold to "
        f"hide a regression; the harness limit is not ours to change."
    )


@pytest.mark.parametrize( "rel,ceiling", [ ( "CLAUDE.md", REPO_BUDGET ) ] )
def test_no_single_file_can_consume_the_whole_budget( rel, ceiling ):
    """
    The total assertion above can be satisfied by one enormous file and one tiny one, so
    pin the file that actually grew. Parametrized rather than inlined so a second
    instruction file can be pinned later without a new test body.

    Ensures:
        - the named file alone is under the budget
        - the message distinguishes this from the total failure, which has a different remedy
    """
    sizes = dict( _measured_files() )

    assert rel in sizes, f"{rel} was not measured; corpus was {sorted( sizes )}"
    assert sizes[ rel ] < ceiling, (
        f"{rel} alone is {sizes[ rel ]:,} chars against a {ceiling:,} budget. This is the file "
        f"that reached 303,113 and truncated silently at every session start (row cf97df79). "
        f"Split its receipts out to src/docs/doctrine/, do not raise the ceiling."
    )
