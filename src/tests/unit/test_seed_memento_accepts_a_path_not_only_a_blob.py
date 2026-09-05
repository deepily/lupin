"""
Row 75b36135 — `seed_memento` had two documented contracts and the guards watched one.

=== WHAT WAS WRONG, AND WHAT WAS NOT ===

`render_task_prompt`'s docstring said `seed_memento` is a prior-context BLOB. The MCP
`spawn_sessions` tool's said it is a PATH/ref. CLAUDE.md's re-spin ladder tells the fleet
to pass a PATH. All three were satisfied by the same code, which appends the value verbatim
and cannot tell the two apart.

⚠️ THE SEVERE READING WAS TESTED AND REFUTED, so this file guards a contract rather than
repairing a disaster. A census of 1,660 transcripts found 270 carrying the seed heading,
130 with an ABSOLUTE path, and every one of those 130 children opened a memento file. It is
a DOCUMENTATION defect. Its two limits are kept rather than rounded off: 103 relative-path
seeds and 31 unparsed bodies were never measured, so 130 is a FLOOR; and "opened" is not
"used what it read".

🔴 THE NONCE ARM HAS NEVER RUN AND THIS FILE DOES NOT CLOSE IT. Whether a child USES the
memento it opened is a separate question, answerable only by seeding a nonce that exists
nowhere else and asking the child to state it. Nothing here supersedes that, and a reader
must not take this file's green as an answer to it.

=== WHY IT NEEDED A GUARD AT ALL ===

Every existing test pinned the BLOB side — `test_spawn_sessions.py` passes
"I authored this plan.", a blank, and None. ZERO passed a path-shaped value. So the contract
CLAUDE.md instructs the fleet to use was § UNGUARDED IS A THIRD STATE: present, correct, and
untestable-if-wrong. The docstrings now agree; these arms are what keep them honest.

=== AND ONE ARM THAT IS NOT ABOUT seed_memento AT ALL ===

The row carried a second, deliberately separate question: does `dry_run=True` skip the
`git worktree add`? Answered by reading the program — `provision_seat_worktree` is gated
behind `if not dry_run` at session_spawner.py, and `src/scripts/provision-seat-worktree.sh`
is the only thing that runs `git worktree add` on this path. The gate landed in `ef1c1c4a`
on 2026-09-03, two days BEFORE the row was written, so the concern was already closed and
unread rather than live.

🔴 AND IT WAS ALREADY GUARDED — I SAID OTHERWISE FIRST AND THAT WAS WRONG. My initial
reading was "the existing dry-run test asserts no ARTIFACTS were borrowed and says nothing
about the worktree." That is true of `test_the_real_spawn_path_provisions_a_tier_capable_
tree.py`, which is the file I looked in, and false of the tree as a whole:
`test_every_seat_gets_its_own_working_tree.py::test_a_dry_run_leaves_no_worktree_behind`
compares the worktree list before and after and asserts `worktree_status == "dry_run"`.
I searched one file and reported a gap — a partial population read as an absence, which is
the failure this repo names most often.

⇒ THE PROOF THAT IT REALLY IS GUARDED IS A MUTATION, NOT A SECOND READING. Un-gating
`provision_seat_worktree` under `dry_run` reddens that test. And it did NOT redden a
worktree-list arm I had written here, because my fixture ships no
`src/scripts/provision-seat-worktree.sh` — so the ungated provisioner fails and creates
nothing, and my arm could not see the defect it was written for. That blind arm has been
REMOVED rather than repaired: the existing guard already covers it correctly, and a second
test that looks like coverage and is not makes the suite read thicker than it is.

What survives here is the ONE dry-run claim the existing guard does not make — that the
payload SAYS it provisioned nothing, per-seat — and it earns its place by reddening under
the same mutation.
"""

import os
import subprocess
import tempfile
from pathlib import Path

import pytest

from lupin_mcp import session_spawner


HEADING = "# Prior context (memento — your earlier work on this, for reference)"


# ---------------------------------------------------------------------------------------
# ARM A — the PATH contract, which nothing watched
# ---------------------------------------------------------------------------------------

def test_an_absolute_path_reaches_the_child_intact( tmp_path ):
    """
    THE CONTRACT CLAUDE.md PRESCRIBES. A re-spin passes a path; the child opens it. If the
    path does not survive into the prompt byte-for-byte, the child has nothing to open —
    and the failure is silent, because the heading still appears.
    """
    record = tmp_path / "io" / "mementos" / "krishna-056ca4c8.md"
    record.parent.mkdir( parents=True )
    record.write_text( "the record's real content" )

    rendered = session_spawner.render_task_prompt( "do the thing", { }, str( record ) )

    assert HEADING in rendered
    assert str( record ) in rendered, "the absolute path must reach the child byte-for-byte"
    assert rendered.rstrip().endswith( str( record ) ), \
        "the path must be the appendix BODY, not merely mentioned somewhere in it"


def test_the_path_is_appended_NOT_resolved( tmp_path ):
    """
    🔴 THE ARM THAT SAYS WHICH CONTRACT ACTUALLY SHIPPED, and it is the one a reader is
    most likely to guess wrong. `render_task_prompt` does NOT open the file. A future
    editor who "helpfully" made it read the path would change what every child receives —
    and every other assertion in this file would still pass, because the heading and the
    content would both be present.
    """
    record = tmp_path / "memento.md"
    # Named `marker`, not `secret`: the repo's secret scanner flags a 37-char literal
    # assigned to a variable called `secret`, and it is right to — the honest fix is to
    # stop looking like one, never `--no-verify`.
    marker = "CONTENT-THAT-MUST-NOT-BE-INLINED-7731"
    record.write_text( marker )

    rendered = session_spawner.render_task_prompt( "task", { }, str( record ) )

    assert str( record ) in rendered
    assert marker not in rendered, (
        "render_task_prompt resolved the path and inlined the file. That may be a fine "
        "change to make, but it is a CHANGE: the child no longer opens anything, and the "
        "docstring and CLAUDE.md's ladder both describe the old behaviour."
    )


def test_a_path_that_does_not_exist_is_still_appended( tmp_path ):
    """
    The function neither reads nor validates. A dead path reaches the child unchanged —
    which is worth pinning because it is the behaviour that makes a typo'd seed silent, and
    somebody deciding to fix THAT should have to change a test that says so out loud.
    """
    dead = str( tmp_path / "nope" / "gone.md" )
    assert not os.path.exists( dead )

    rendered = session_spawner.render_task_prompt( "task", { }, dead )
    assert dead in rendered


@pytest.mark.parametrize( "shape", [
    "/abs/path/to/io/mementos/rio-1234abcd.md",
    "io/mementos/rio.md",
    ".claude-memento-mr-radio.md",
] )
def test_every_path_shape_the_fleet_actually_passes_survives( shape ):
    """
    The three forms in circulation: an absolute record path, a relative pointer, and a
    root-slot pointer. The census could only measure the absolute ones — a bare relative
    path is ambiguous to search a transcript for — so the other two are exactly the shapes
    with no field evidence behind them.
    """
    rendered = session_spawner.render_task_prompt( "task", { }, shape )
    assert shape in rendered, f"{shape!r} did not survive into the prompt"


# ---------------------------------------------------------------------------------------
# ARM B — the BLOB contract still works. Without this, "accept anything" satisfies arm A.
# ---------------------------------------------------------------------------------------

def test_a_blob_still_reaches_the_child_intact():
    blob = "I authored this plan.\nSecond paragraph with detail."
    rendered = session_spawner.render_task_prompt( "task", { }, blob )
    assert HEADING in rendered
    assert blob in rendered


def test_no_seed_means_no_heading():
    """
    THE CONTROL. Without it every arm above is satisfied by a function that appends the
    heading unconditionally.
    """
    for empty in ( None, "", "   ", "\n\t " ):
        rendered = session_spawner.render_task_prompt( "task", { }, empty )
        assert HEADING not in rendered, f"{empty!r} produced a Prior-context heading"
        assert rendered == "task"


def test_the_task_leads_and_the_memento_follows():
    """
    Rick's 2026-05-28 directive: APPEND, never prepend, so a large memento cannot bury the
    instruction. Pinned because the two contracts differ most in SIZE — a blob can be
    thousands of lines where a path is one — and an ordering regression would be invisible
    on the path form and severe on the blob form.
    """
    rendered = session_spawner.render_task_prompt( "THE-TASK", { }, "THE-MEMENTO" )
    assert rendered.index( "THE-TASK" ) < rendered.index( "THE-MEMENTO" )


# ---------------------------------------------------------------------------------------
# ARM C — OPEN #2, the half the existing dry-run test does not cover
# ---------------------------------------------------------------------------------------

def _repo_with_a_worktree( tmp ):
    """
    A real git repo plus one real worktree, so the arm below measures the real verb.

    ⚠️ THE CHECKOUT MUST BE NAMED `lupin` AND THAT IS NOT COSMETIC. `_resolve_project_root`
    answers with `LUPIN_ROOT` only when the MAIN CHECKOUT'S DIRECTORY NAME matches the
    requested project. Name it anything else and `spawn_sessions` refuses with "no
    repository root resolves for it" — so the arm would be measuring the resolver instead
    of the dry-run gate, and the failure reads like a spawn defect rather than a fixture
    one. Learned by hitting it.
    """
    main = os.path.realpath( os.path.join( tmp, "lupin" ) )
    os.makedirs( main )
    for cmd in ( [ "init", "-q" ],
                 [ "config", "user.email", "t@t" ],
                 [ "config", "user.name", "t" ] ):
        subprocess.run( [ "git", *cmd ], cwd=main, check=True, capture_output=True )
    Path( main, "f.txt" ).write_text( "x" )
    subprocess.run( [ "git", "add", "-A" ], cwd=main, check=True, capture_output=True )
    subprocess.run( [ "git", "commit", "-qm", "init" ], cwd=main, check=True, capture_output=True )
    wt = os.path.join( tmp, "wt" )
    subprocess.run( [ "git", "worktree", "add", "--detach", "-q", wt, "HEAD" ],
                    cwd=main, check=True, capture_output=True )
    return main, wt


def _worktree_paths( main ):
    out = subprocess.run( [ "git", "worktree", "list", "--porcelain" ],
                          cwd=main, check=True, capture_output=True, text=True ).stdout
    return sorted( l.split( " ", 1 )[ 1 ] for l in out.splitlines() if l.startswith( "worktree " ) )


def test_the_dry_run_says_it_provisioned_nothing_rather_than_staying_silent( monkeypatch ):
    """
    THE ONE DRY-RUN CLAIM NOT ALREADY MADE ELSEWHERE. That no worktree is CREATED is
    guarded by `test_every_seat_gets_its_own_working_tree.py::
    test_a_dry_run_leaves_no_worktree_behind`, which compares the worktree list across the
    call — go there for that, not here.

    What this adds is that the PAYLOAD SAYS SO, per seat. A dry run that quietly returns
    the same shape as a real one leaves the caller unable to tell which it got, which is
    this repo's own a-clean-exit-is-not-evidence rule.

    ⚠️ It discriminates, and that was checked rather than assumed: un-gating
    `provision_seat_worktree` under `dry_run` reddens this test. A sibling arm asserting on
    the worktree LIST did not redden under the same mutation — this fixture ships no
    provisioning script, so the ungated call fails and creates nothing — and was removed
    for it.
    """
    with tempfile.TemporaryDirectory() as tmp:
        main, worktree = _repo_with_a_worktree( tmp )
        try:
            monkeypatch.setenv( "LUPIN_ROOT", worktree )
            with tempfile.TemporaryDirectory() as session_dir:
                result = session_spawner.spawn_sessions(
                    1, "task", "mgr-sid", script_path="/bin/true", project="lupin",
                    session_dir=Path( session_dir ), dry_run=True,
                )
            # The field is `seat_worktrees` — a LIST, one entry per seat — not a single
            # `seat_provisioning` dict. Found by driving the real call and printing the
            # keys rather than by reading the internal variable name, which is
            # `seat_provisioning` locally and is not what reaches the payload.
            seats = result[ "seat_worktrees" ]
            assert len( seats ) == 1, seats
            assert seats[ 0 ][ "status" ]       == "dry_run", seats[ 0 ]
            assert seats[ 0 ][ "drift_behind" ] is None,      seats[ 0 ]
            assert result[ "artifact_provisioning" ][ "status" ] == "dry_run"
        finally:
            subprocess.run( [ "git", "worktree", "prune" ], cwd=main, check=False, capture_output=True )
