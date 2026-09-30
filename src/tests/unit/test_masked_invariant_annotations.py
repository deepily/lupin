"""
R1's mechanical half: a masked line stays PAIRED with the comment defending it.

R1, ruled fleet doctrine by Rick 2026-09-01 (row cc335a42): a line that is MASKED — its
removal does not redden the suite — is KEPT and ANNOTATED with why, never deleted to quiet
a mutation harness, when it sits at a fail-closed boundary.

WHY A TEST EXISTS AT ALL. The row that raised R1 said "there is no mechanical control
available for it." Maya 🌻 showed that claim is too strong, and the distinction is the whole
design of this file:

    DISCOVERING which lines are masked   -> needs a human and a mutation. Not automatable.
    PRESERVING ones already annotated    -> automatable, and that is the half R1 asked
                                            reviewers to hold forever.

So this does not make R1 self-enforcing. It shrinks the part that must survive in people's
heads down to the moment of ANNOTATION. After that, a test holds it with no reviewer present
— which matters because this fleet's own doctrine is that a rule depending on memory is not
installed, and the checked-hash mandate was documented, prominent, and broken three times in
one afternoon by the people who wrote it.

🔴 THE NAIVE VERSION OF THIS CONTROL IS ITSELF AN INSTRUMENT THAT CANNOT FAIL, and that is
not a hypothetical — Maya measured it. A test asserting only that the ANNOTATION exists goes
GREEN on the exact deletion it was built to prevent, because the comment survives the line:

    comment-only check   -> PASS (green) on the forbidden deletion
    paired check         -> FAIL, catches it

`test_the_comment_only_check_is_green_on_the_deletion_the_paired_check_catches` below runs
both arms and asserts they DISAGREE. Without it this file would be one careless refactor away
from becoming the thing it guards against, and nothing would say so.

⚠️ THE TWO SITES ARE NOT EQUALLY ESTABLISHED, and flattening that would overstate the
evidence. Site 1's masking is measured twice, by two seats, by two methods — Rachel 🕊️ via
mutation at a35ce8ef, Tiberius 👑 by hand at 625665bb (deleted the line, 127 passed either
way, no harness involved). Site 2 SELF-DESCRIBES as the same shape in its own comment and has
never been mutation-verified. Site 1 is evidence; site 2 is a claim by its author. A census
counting them as two data points is counting one measurement and one assertion.

⚠️ THE MECHANISM IS UNIFORM EVEN THOUGH THE SHAPES DIFFER. Site 1's masked thing is a
redundant LINE; site 2's is the WRAPPING of a call, whose effect is invisible only because
another caller happens to run first. Different defects — but both reduce to "this exact source
text must still be present", so one assertion form covers both.
"""

import re
from pathlib import Path

import pytest

import cosa.utils.util as cu


# The tag every catalogued site carries. Registry membership is checked against the tree in
# `test_every_tagged_site_is_in_the_registry`, so a third site cannot be added silently.
MASKED_INVARIANT_TAG = "masked-invariant"


# (repo-relative path, comment anchor, the source text that comment defends)
#
# Anchors are CONTENT, never line numbers — a coordinate says where something sat when you
# looked, and both these files have moved this week. Each is asserted to match EXACTLY ONCE,
# so an anchor that goes ambiguous fails loudly instead of silently matching the wrong place.
MASKED_INVARIANT_SITES = [
    pytest.param(
        "src/cosa/utils/coverage_contention.py",
        "Catalogued as `masked-invariant`",
        'if comm == "":    return True',
        id="coverage_contention-empty-comm-admits-a-running-suite",
    ),
    pytest.param(
        "src/lupin_cli/claude_code/hooks/lib/hook_common.py",
        "Same masked-invariant shape as two sites agreeing for a",
        "cap = quiet_stdout( cu.get_spoken_char_cap )",
        id="hook_common-quiet_stdout-wrapping-is-order-dependent",
    ),
]


def _repo_root() -> Path:
    """
    Resolve the tree under test from the canonical project-root function.

    Requires:
        - LUPIN_ROOT names the tree the caller intends to check, or the default applies.

    Ensures:
        - returns an absolute Path to the repo root.

    ⚠️ This reads LUPIN_ROOT, which is inherited from the caller's shell and is the single
    most common way a check in this repo certifies a tree nobody asked about. Run from a
    worktree without pinning it and this would assert against the MAIN checkout. That case is
    caught UPSTREAM by the conftest worktree false-green guard (row a9f87d29), which refuses
    at COLLECTION time — see the note further down explaining why this file carries no
    wrong-tree guard of its own.
    """
    return Path( cu.get_project_root() )


def _read( rel_path ):
    """
    Read one registered file as text.

    Requires:
        - rel_path is repo-relative and the file exists.

    Ensures:
        - returns the file's full text.

    Raises:
        - AssertionError if the file is absent, naming the resolved path — a registry entry
          pointing at a moved file must fail as a registry error, not as a missing anchor.
    """
    full = _repo_root() / rel_path
    assert full.is_file(), (
        f"registry entry points at a file that is not here: {full}\n"
        f"The file moved or was deleted. Update MASKED_INVARIANT_SITES — and if the masked "
        f"line went with it, say so in the commit rather than dropping the entry quietly."
    )
    return full.read_text()


def _occurrences( haystack, needle ):
    """
    Count non-overlapping literal occurrences of `needle` in `haystack`.

    Requires:
        - both are strings; needle is non-empty.

    Ensures:
        - returns an int >= 0, counting the literal text (never a regex).
    """
    return len( re.findall( re.escape( needle ), haystack ) )


# --------------------------------------------------------------------------------------
# The control itself
# --------------------------------------------------------------------------------------

@pytest.mark.parametrize( "rel_path, comment_anchor, defended_text", MASKED_INVARIANT_SITES )
def test_the_annotation_and_the_line_it_defends_are_both_still_here(
    rel_path, comment_anchor, defended_text
):
    """
    Both halves of the pair are present, each exactly once.

    This is the assertion R1 needs and the comment-only version does not make: deleting the
    masked line to quiet a mutation harness breaks the pair even though the comment survives.

    EXACTLY ONCE matters in both directions. Zero means it was deleted — the forbidden move.
    Two or more means the anchor is no longer a pointer at all, and a check that matches
    ambiguously reports on whichever copy it happened to find.
    """
    source = _read( rel_path )

    comment_hits  = _occurrences( source, comment_anchor )
    defended_hits = _occurrences( source, defended_text )

    assert comment_hits == 1, (
        f"{rel_path}: the masked-invariant ANNOTATION should appear exactly once, found "
        f"{comment_hits}.\n"
        f"  anchor: {comment_anchor!r}\n"
        f"If you reworded the comment, update the anchor in MASKED_INVARIANT_SITES. Do not "
        f"delete the entry — R1 (row cc335a42) is fleet doctrine as of 2026-09-01."
    )
    assert defended_hits == 1, (
        f"{rel_path}: the line the annotation DEFENDS should appear exactly once, found "
        f"{defended_hits}.\n"
        f"  defended: {defended_text!r}\n"
        f"🔴 If a mutation harness told you this line is dead, that is EXPECTED and is the "
        f"whole reason it is catalogued — it is masked by a downstream check, not unreachable. "
        f"Deleting it is the move R1 forbids. Read the comment above it before changing this."
    )


def test_every_tagged_site_is_in_the_registry():
    """
    A file carrying the tag but absent from the registry is a site nobody is guarding.

    Without this the registry rots in the quietest possible way: somebody catalogues a third
    masked line, believes it is protected because a control exists, and it is not in the list.
    The check reads the TREE rather than the list, so its stated reach is its actual reach —
    which is Maya's own argument for detectors over door-guards, applied to this file.

    ⚠️ Scope, named because an empty result is two different failures wearing one face: this
    walks tracked-or-not `.py` files under `src/`, EXCLUDING vendored trees. `src/cosa/.venv`
    holds ~29,000 third-party files for an interpreter this repo does not run, and a sweep
    that includes it is inflated roughly 13x. The positive control is the registry itself —
    the walk must find the files already registered, or the walk is broken rather than clean.
    """
    root     = _repo_root()
    skip     = ( ".venv", "node_modules", "site-packages", "__pycache__" )
    tagged   = set()

    for path in ( root / "src" ).rglob( "*.py" ):
        if any( part in skip for part in path.parts ): continue
        try:
            text = path.read_text()
        except ( OSError, UnicodeDecodeError ):
            continue
        # This test file names the tag constantly; it is the guard, not a guarded site.
        if path.resolve() == Path( __file__ ).resolve(): continue
        if MASKED_INVARIANT_TAG in text: tagged.add( str( path.relative_to( root ) ) )

    registered = { p.values[ 0 ] for p in MASKED_INVARIANT_SITES }

    # POSITIVE CONTROL. A walk that finds nothing would pass the subset check below
    # vacuously, and "no hits" is byte-identical to "searched nothing". Prove the instrument
    # can see the files we already know carry the tag before trusting it about files we do not.
    assert registered <= tagged, (
        f"the tree walk did not find files that ARE registered: {sorted( registered - tagged )}\n"
        f"That is a broken search, not a clean result — this assertion exists so an empty or "
        f"misdirected walk cannot pass as 'nothing unregistered'."
    )

    unregistered = tagged - registered
    assert not unregistered, (
        f"these files carry a `{MASKED_INVARIANT_TAG}` tag but are NOT in "
        f"MASKED_INVARIANT_SITES, so nothing is holding their pair together:\n"
        + "".join( f"  {p}\n" for p in sorted( unregistered ) ) +
        "Add (path, comment anchor, defended text) for each. Tagging a line without "
        "registering it buys the appearance of protection."
    )


# NO WRONG-TREE GUARD HERE, AND ITS ABSENCE IS DELIBERATE — measured, not assumed.
#
# I wrote one. `_repo_root()` reads LUPIN_ROOT from the caller's shell, so running this from a
# worktree with LUPIN_ROOT still naming the main checkout would assert against files nobody is
# editing — the failure this repo already has three named instances of (the checked-hash
# verifier, purge-pycache.sh, and the unit tier itself).
#
# Then I ran that arm, and it produced NO OUTPUT AT ALL. The cause is the useful part: the
# repo's conftest ALREADY carries that guard (row a9f87d29) and it fires at COLLECTION time,
# before a single test in this file executes:
#
#     ERROR: WORKTREE FALSE-GREEN GUARD (row a9f87d29): the test file being collected lives in
#     a DIFFERENT git tree than LUPIN_ROOT ...
#     no tests ran in 0.09s        EXIT=4
#
# ⇒ So my guard could never fail. An assertion that cannot fail, inside a file whose entire
# subject is instruments that cannot fail, is the joke writing itself — and it would have
# passed green forever while looking like protection. It is deleted rather than kept "for
# belt and braces", on the same reasoning that deleted a weaker duplicate parity test at
# 0ad3efb2: a second, weaker check does not add safety, it adds a thing a reader must
# understand before trusting the first one.
#
# The real control is upstream, is stronger (it refuses to run rather than reporting a
# verdict), and needs nothing from this file.


# --------------------------------------------------------------------------------------
# The control on the control
# --------------------------------------------------------------------------------------

def test_the_comment_only_check_is_green_on_the_deletion_the_paired_check_catches( tmp_path ):
    """
    🔴 THE ARM THAT MAKES THIS FILE WORTH HAVING. Both checks are run against the SAME forged
    deletion and asserted to DISAGREE.

        comment-only  -> PASSES  (the comment survives the line, so it sees nothing wrong)
        paired        -> FAILS   (the defended text is gone)

    Without this, `test_the_annotation_and_the_line_it_defends_are_both_still_here` is a green
    test whose discriminating power nobody has demonstrated — and a fixture that cannot tell
    two behaviours apart is exactly the defect R1 was raised about. Coverage would call the
    assertion covered either way.

    ⚠️ Operates on a COPY under tmp_path. The live source is never written to — a control that
    mutates the tree it guards is a worse hazard than the one it checks, and doing this in a
    shared checkout would hand a peer a deleted line.
    """
    rel_path, comment_anchor, defended_text = MASKED_INVARIANT_SITES[ 0 ].values

    original = _read( rel_path )
    assert _occurrences( original, defended_text ) == 1, "precondition: one copy to remove"

    # The forbidden move, forged: remove the defended line, leave the annotation untouched.
    forged = original.replace( defended_text, "", 1 )

    scratch = tmp_path / "forged.py"
    scratch.write_text( forged )
    reread = scratch.read_text()

    comment_only_verdict = _occurrences( reread, comment_anchor ) == 1
    paired_verdict       = comment_only_verdict and _occurrences( reread, defended_text ) == 1

    assert comment_only_verdict is True, (
        "the comment-only check should be GREEN on this deletion — if it is not, the forgery "
        "removed the comment too and this arm is not testing what it claims."
    )
    assert paired_verdict is False, (
        "the PAIRED check must catch a deletion the comment-only check misses. It did not, so "
        "this control cannot discriminate and the guard above it is decorative."
    )
    assert comment_only_verdict != paired_verdict, (
        "the two checks agreed. The whole argument for pairing is that they disagree on "
        "exactly this input."
    )
