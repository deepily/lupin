"""
A spawned seat must land in ITS OWN working tree, not in the one every other seat
shares.

Rick ruled 2026-09-03 (row 9d654899): "Adopt, with drift disclosure." Until now the
spawn path DETECTED this and left the seat in it — `placement_alarm` said "you are in
the shared main checkout" and nothing moved. An alarm that names a hazard and leaves
you standing in it is not a control; the ruling makes the detection into the fix.

THE HAZARD IS PER-HUNK AND EVERY OTHER CONTROL IS PER-FILE. `git commit -- <path>`
commits that path's WORKING-TREE CONTENT, so a seat committing a file it legitimately
owns still commits whatever a peer left uncommitted inside it. The manifest says the
file is yours and it IS; the scope guard checks the path and it passes. Fired three
times — once as a completed hit, 57 lines under the wrong name, with every control
saying yes.

⚠️ WHERE THESE TESTS KNOCK, AND WHY IT MATTERS HERE MORE THAN USUAL. The first green I
got on this change was worthless: the real spawn path resolves project "lupin" to the
MAIN checkout, the provisioning script is not in the main checkout until this lands, so
provisioning reported `script_absent` and fell through — and every existing assertion
passed while the new code did nothing at all. A test that cannot reach the branch it is
written for is the "implemented but not installed" shape, arriving before the install.

So the seam stood down here is `_resolve_project_root` ONLY — the project-name-to-root
lookup, which has its own tests — and it is pointed at a REAL temporary git repository
carrying a REAL copy of the script. Everything below it runs: the real
`provision_seat_worktree`, the real `provision-seat-worktree.sh`, the real
`git worktree add`, the real per-seat argv construction.
"""

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

from lupin_mcp import session_spawner


def _repo_under_test():
    """The tree the CODE UNDER TEST came from — asked of the module, never of this file."""
    return Path( session_spawner.__file__ ).resolve().parents[ 2 ]


def _git( *args, cwd ):
    return subprocess.run( [ "git", *args ], cwd=cwd, capture_output=True, text=True )


@pytest.fixture
def fake_projects_dir():
    """
    A REAL git repository, inside a real `projects/` parent, carrying a real copy of the
    provisioning script. Not a fixture standing in for git — git actually runs.

    The parent matters: the script places a seat's tree as a SIBLING of the main
    checkout, which is the layout every worktree on this box already has.
    """
    with tempfile.TemporaryDirectory() as tmp:
        projects = Path( tmp ) / "projects"
        main     = projects / "demo"
        ( main / "src" / "scripts" ).mkdir( parents=True )
        # BOTH scripts, and the second one is not decoration. `provision_worktree_venv`
        # is what renders `placement_alarm`, and with its script absent it reports
        # "script_absent" instead of "main_repo" — so the fail-open arm below would see
        # a silent alarm and read it as a code defect. Measured while writing this: the
        # arm failed, and the fixture was the cause, not the change under test.
        for script in ( "provision-seat-worktree.sh", "link-worktree-venv.sh" ):
            shutil.copy( _repo_under_test() / "src" / "scripts" / script,
                         main / "src" / "scripts" / script )
        _git( "init", "-q", cwd=main )
        _git( "config", "user.email", "t@example.com", cwd=main )
        _git( "config", "user.name", "t", cwd=main )
        _git( "add", "-A", cwd=main )
        _git( "commit", "-q", "-m", "seed", cwd=main )
        yield main
        # git worktree metadata lives inside the temp repo, so the TemporaryDirectory
        # cleanup takes everything. Nothing is registered in the real repo.


class _Runner:
    """Captures the argv of every spawn so the seat's cwd can be read off it."""
    def __init__( self ):
        self.calls = []
    def __call__( self, argv, env=None ):
        self.calls.append( argv )
        class R: returncode = 0
        return R()

    def work_dir_of( self, i ):
        argv = self.calls[ i ]
        return argv[ argv.index( "--work-dir" ) + 1 ] if "--work-dir" in argv else None


def _spawn( monkeypatch, root, count=1, session_dir=None ):
    monkeypatch.setattr( session_spawner, "_resolve_project_root", lambda project: str( root ) )
    runner = _Runner()
    with tempfile.TemporaryDirectory() as sd:
        result = session_spawner.spawn_sessions(
            count, "task", "mgr-sid", script_path="/bin/true", project="demo",
            # dry_run=False ON PURPOSE: a dry run provisions nothing (it must not leave
            # worktrees on the box), so testing this branch through dry_run=True would
            # measure the gate rather than the provisioning. The injected runner is what
            # keeps it safe — no tmux, no child, and the manifest lands in a temp dir.
            session_dir=Path( session_dir or sd ), dry_run=False, runner=runner )
    return result, runner


# ---------------------------------------------------------------------------
# THE DEFECT — a seat placed in the shared checkout
# ---------------------------------------------------------------------------
def test_a_spawned_seat_does_not_land_in_the_shared_main_checkout( monkeypatch, fake_projects_dir ):
    result, runner = _spawn( monkeypatch, fake_projects_dir )
    landed = runner.work_dir_of( 0 )
    assert landed is not None
    assert Path( landed ).resolve() != fake_projects_dir.resolve(), \
        "the seat was placed in the shared main checkout — the hazard this row exists for"


def test_the_seat_lands_in_a_real_worktree_git_agrees_is_one( monkeypatch, fake_projects_dir ):
    """Not "a directory appeared" — git itself must call it a LINKED worktree.

    ⚠️ THE OBVIOUS ASSERTION IS BLIND, AND A MUTATION ARM CAUGHT IT. This test first
    checked only that the landed path appears in `git worktree list`. It SURVIVED a
    revert of the whole change — because git lists the MAIN CHECKOUT as a worktree too,
    so the assertion was true of the very state the row exists to prevent. The
    discriminating property is `.git`: a linked worktree has a FILE pointing at the
    shared git dir, the main checkout has a DIRECTORY."""
    result, runner = _spawn( monkeypatch, fake_projects_dir )
    landed = Path( runner.work_dir_of( 0 ) )
    listed = _git( "worktree", "list", "--porcelain", cwd=fake_projects_dir ).stdout
    assert f"worktree {landed}" in listed
    assert ( landed / ".git" ).is_file(), \
        "the seat's .git is a directory — that is the main checkout, not a linked worktree"


def test_two_seats_in_one_spawn_get_two_different_trees( monkeypatch, fake_projects_dir ):
    """🔴 THE ARM THAT NAMES THE MEASURED INCIDENT. `work_dir` is resolved ONCE per
    spawn, so a per-SPAWN tree would put both authors of a two-author batch in one
    directory — which is exactly what happened to this row's own crew on 2026-09-03,
    two authors aimed at the same two modules. The tree is keyed on `session_name`."""
    result, runner = _spawn( monkeypatch, fake_projects_dir, count=2 )
    first, second = runner.work_dir_of( 0 ), runner.work_dir_of( 1 )
    assert first != second, "two seats of one spawn shared a working tree"
    assert len( { r[ "work_dir" ] for r in result[ "spawned" ] } ) == 2


def test_a_re_spun_seat_returns_to_its_own_tree( monkeypatch, fake_projects_dir ):
    """Idempotence, and it is not cosmetic: a seat re-spun under the same name must come
    back to its tree with its uncommitted work still in it, not to a fresh one."""
    first,  _ = _spawn( monkeypatch, fake_projects_dir )
    second, _ = _spawn( monkeypatch, fake_projects_dir )
    assert first[ "spawned" ][ 0 ][ "work_dir" ] == second[ "spawned" ][ 0 ][ "work_dir" ]
    assert first[  "spawned" ][ 0 ][ "worktree_status" ] == "created"
    assert second[ "spawned" ][ 0 ][ "worktree_status" ] == "reused"


def test_the_placement_alarm_falls_silent_because_the_seat_moved( monkeypatch, fake_projects_dir ):
    """The alarm going quiet is the RULING LANDING, not the check being weakened — the
    seat is no longer in the shared checkout for it to complain about. Paired with the
    arm above that proves the seat actually moved, which is what makes a silent alarm
    readable as success rather than as a disabled guard."""
    result, _ = _spawn( monkeypatch, fake_projects_dir )
    assert result[ "placement_alarm" ] is None


def test_the_payload_says_where_every_seat_went( monkeypatch, fake_projects_dir ):
    result, _ = _spawn( monkeypatch, fake_projects_dir, count=2 )
    seats = result[ "seat_worktrees" ]
    assert len( seats ) == 2
    assert all( s[ "work_dir" ] and s[ "status" ] == "created" for s in seats )
    assert { s[ "session_name" ] for s in seats } == { r[ "session_name" ] for r in result[ "spawned" ] }


# ---------------------------------------------------------------------------
# FAIL-OPEN — the condition that makes this safe to put in the fleet's spawn path
# ---------------------------------------------------------------------------
def test_a_broken_provisioner_still_spawns_and_still_warns( monkeypatch, fake_projects_dir ):
    """🔴 THE CONDITION MR. RADIO SET, PROVEN BY AN ARM RATHER THAN CLAIMED.

    `session_spawner` is the path every manager on this box staffs itself through. A
    defect here does not break one row, it stops the fleet hiring. So provisioning is
    fail-open: break it deliberately and the spawn must still succeed, the seat must
    land exactly where it landed before this change, and the alarm that used to be the
    whole behaviour must still fire."""
    monkeypatch.setattr( session_spawner, "provision_seat_worktree",
                         lambda main_root, seat_name: {
                             "provisioned": False, "status": "failed", "work_dir": None,
                             "drift_behind": None, "exit_code": 5, "message": "boom" } )
    result, runner = _spawn( monkeypatch, fake_projects_dir )

    assert result[ "spawned" ][ 0 ][ "status" ] == "spawned"          # the spawn survived
    assert Path( runner.work_dir_of( 0 ) ).resolve() == fake_projects_dir.resolve()
    assert result[ "placement_alarm" ] is not None                    # and it says so
    assert str( fake_projects_dir ) in result[ "placement_alarm" ]


def test_a_provisioner_that_raises_cannot_kill_a_spawn( monkeypatch, fake_projects_dir ):
    """The helper's contract is that it never raises. This asserts the contract from the
    OUTSIDE, so a future edit that lets an exception escape is caught here rather than
    by a manager whose crew will not start."""
    from cosa.utils import seat_worktree
    monkeypatch.setattr( seat_worktree.subprocess, "run",
                         lambda *a, **k: ( _ for _ in () ).throw( OSError( "no bash" ) ) )
    result, runner = _spawn( monkeypatch, fake_projects_dir )
    assert result[ "spawned" ][ 0 ][ "status" ] == "spawned"
    assert Path( runner.work_dir_of( 0 ) ).resolve() == fake_projects_dir.resolve()


# ---------------------------------------------------------------------------
# DRIFT DISCLOSURE — the other half of the ruling
# ---------------------------------------------------------------------------
def test_a_fresh_tree_discloses_nothing_because_there_is_nothing_to_disclose( monkeypatch, fake_projects_dir ):
    """None means the line does not appear, so when it DOES appear it means something.
    A disclosure printed on every spawn is noise a reader learns to skip."""
    result, _ = _spawn( monkeypatch, fake_projects_dir )
    assert result[ "spawned" ][ 0 ][ "drift_disclosure" ] is None
    assert result[ "seat_worktrees" ][ 0 ][ "drift_behind" ] == 0


def test_a_reused_tree_that_has_fallen_behind_says_so( monkeypatch, fake_projects_dir ):
    """The row's own re-diagnosis: the problem was never drift, it was UNSTATED drift —
    the tree furthest behind was the harmless one because its pin was declared."""
    first, _ = _spawn( monkeypatch, fake_projects_dir )
    ( fake_projects_dir / "newfile.txt" ).write_text( "moved on\n" )
    _git( "add", "-A", cwd=fake_projects_dir )
    _git( "commit", "-q", "-m", "main moves ahead", cwd=fake_projects_dir )

    second, _ = _spawn( monkeypatch, fake_projects_dir )
    row = second[ "spawned" ][ 0 ]
    assert second[ "seat_worktrees" ][ 0 ][ "drift_behind" ] == 1
    assert row[ "drift_disclosure" ] is not None
    assert "1 commit" in row[ "drift_disclosure" ]


def test_a_dry_run_leaves_no_worktree_behind( monkeypatch, fake_projects_dir ):
    """🔴 A DRY RUN MUST PROVISION NOTHING, and this arm exists because the alternative
    was measured rather than imagined: two existing tests drive the REAL spawn path
    against the REAL main checkout with dry_run=True, so an ungated provisioner would
    leave one `lupin-wt-…` tree on this box per unit-tier run, forever."""
    monkeypatch.setattr( session_spawner, "_resolve_project_root", lambda project: str( fake_projects_dir ) )
    before = _git( "worktree", "list", "--porcelain", cwd=fake_projects_dir ).stdout
    with tempfile.TemporaryDirectory() as sd:
        result = session_spawner.spawn_sessions(
            1, "task", "mgr-sid", script_path="/bin/true", project="demo",
            session_dir=Path( sd ), dry_run=True, runner=_Runner() )
    after = _git( "worktree", "list", "--porcelain", cwd=fake_projects_dir ).stdout
    assert after == before, "a dry run created a worktree"
    assert result[ "spawned" ][ 0 ][ "worktree_status" ] == "dry_run"


# ---------------------------------------------------------------------------
# THE HOLE RACHEL MEASURED — a manager standing in its OWN worktree
# ---------------------------------------------------------------------------
def test_a_manager_in_its_own_worktree_still_gets_each_seat_a_separate_tree( monkeypatch, fake_projects_dir ):
    """🔴 THE ARM THE CORPUS COULD NOT SEE, and it is a sibling of the blind assertion
    above rather than a new kind of mistake.

    `_resolve_project_root` returns the MANAGER'S OWN worktree on purpose (row 1cf6c918
    — sending its workers to the main checkout would quietly undo the manager's own
    isolation). So `work_dir` is routinely a worktree, not the main checkout. The first
    version of the script short-circuited on "am I somewhere other than the main
    checkout", which is TRUE of the manager's tree — so the seat name was ignored and
    every seat of the batch, plus the manager, shared one working tree with every alarm
    silent. Measured by Rachel and reproduced here: two seat names, one tree.

    ⚠️ NOT A REGRESSION — today's code puts them in the same place. It is a HOLE: the
    fix declining to fire in the configuration the hazard lives in, while reporting a
    clean pass. A manager is USUALLY in a worktree, so that is most spawns.

    ⚠️ AND NO EXISTING ARM COULD HAVE CAUGHT IT: every other test here points
    `_resolve_project_root` at a MAIN checkout, so the short-circuit is never entered.
    M2 proves per-seat keying on the path the corpus exercises; this proves it on the
    path the corpus did not have.

    The question a private-tree predicate must ask is "am I THIS SEAT'S OWN tree", never
    "am I not the main checkout" — the same distinction as a linked worktree's `.git`
    being a FILE rather than merely appearing in `git worktree list`."""
    managers_tree = fake_projects_dir.parent / "demo-wt-the-manager"
    _git( "worktree", "add", "--detach", str( managers_tree ), "HEAD", cwd=fake_projects_dir )
    monkeypatch.setattr( session_spawner, "_resolve_project_root", lambda project: str( managers_tree ) )

    runner = _Runner()
    with tempfile.TemporaryDirectory() as sd:
        session_spawner.spawn_sessions(
            2, "task", "mgr-sid", script_path="/bin/true", project="demo",
            session_dir=Path( sd ), dry_run=False, runner=runner )

    first, second = runner.work_dir_of( 0 ), runner.work_dir_of( 1 )
    assert first != second, "two seats shared a tree"
    assert Path( first ).resolve()  != managers_tree.resolve(), "a seat landed in the MANAGER's tree"
    assert Path( second ).resolve() != managers_tree.resolve(), "a seat landed in the MANAGER's tree"
    assert ( Path( first ) / ".git" ).is_file()


def test_a_seat_already_standing_in_its_own_tree_provisions_nothing( monkeypatch, fake_projects_dir ):
    """The other side of that predicate: when the path handed in IS the seat's own tree
    there is genuinely nothing to do. Without this arm the fix above is satisfied by
    code that provisions unconditionally, which would rebuild a tree on every re-spin
    and throw away the uncommitted work in it."""
    from cosa.utils.seat_worktree import provision_seat_worktree
    first = provision_seat_worktree( str( fake_projects_dir ), "seat-alpha" )
    again = provision_seat_worktree( first[ "work_dir" ], "seat-alpha" )
    assert first[ "status" ] == "created"
    assert again[ "status" ] == "already_seat_tree"
    assert again[ "work_dir" ] == first[ "work_dir" ]


def test_the_top_level_verdict_and_its_alarm_describe_the_same_seat( monkeypatch, fake_projects_dir ):
    """Rachel's point B. `venv_provisioning` was seat 0's dict while the two alarms were
    the FIRST ALARMING seat's — so a caller reading them together got a verdict about one
    seat and an alarm about another, with nothing saying so."""
    # ⚠️ THE FIRST SEAT IS SCRIPTED CLEAN, NOT LEFT TO THE REAL HELPER. Measured while
    # writing this: the fake repo has no real `.venv`, so `link-worktree-venv.sh` exits
    # 4 for EVERY seat — which made "only the second seat fails" false and the test
    # assert against seat 1's alarm. A fixture whose premise does not hold measures
    # something other than what its name says.
    calls = { "n": 0 }
    def only_the_second_seat_fails( target ):
        calls[ "n" ] += 1
        if calls[ "n" ] == 2:
            return { "provisioned": False, "status": "failed", "exit_code": 4,
                     "target": target, "detail": "seat two is the broken one" }
        return { "provisioned": True, "status": "ok", "exit_code": 0,
                 "target": target, "detail": "linked" }
    monkeypatch.setattr( session_spawner, "provision_worktree_venv", only_the_second_seat_fails )

    result, runner = _spawn( monkeypatch, fake_projects_dir, count=2 )
    assert result[ "venv_alarm" ] is not None
    assert "seat two is the broken one" in result[ "venv_alarm" ]
    assert result[ "venv_provisioning" ][ "status" ] == "failed", \
        "the top-level verdict describes a different seat than the alarm beside it"
    assert result[ "alarming_seat" ] == result[ "spawned" ][ 1 ][ "session_name" ]
