"""
Guard for `src/scripts/stale-seat-scan.py` — row d2dd3ee3, the sixth sighting.

WHAT THIS FILE IS FOR. The scan exists because a census found 7 of 8 live-occupied
worktrees behind the working branch, and because the seat that took that census came
back from a context clear 30 commits behind, having just written it. A scan is only
worth having if it DISCRIMINATES, so every case here is built on a SYNTHETIC
repository with one variable changed — never on the live tree, whose worktree set and
process table move under the test and would make a red mean nothing.

🔴 THE CASE THAT CARRIES THE FILE IS
`test_a_seat_behind_on_files_it_never_touched_is_not_reported`. Stage 1 alone —
"is this tree behind?" — reports 7 of 8 seats on an ordinary afternoon, and a check
that fires on almost everybody is a check nobody reads by the second day. That case
fails the moment somebody "simplifies" stage 2 away, which is the likeliest future
regression and the one that would quietly turn this into the cry-wolf instrument the
row already rejected once for ancestry.

🔴 THE SECOND LOAD-BEARING CASE IS
`test_the_refusal_reaches_the_shell`. It drives the script as a SUBPROCESS rather
than calling `main()` in-process. On 2026-09-05 this author shipped a guard that
asserted `main()`'s return value and therefore never executed `__main__` or its
`sys.exit()` — the exit code, which is the entire caller-facing contract of a
three-code scan, was untested at the only boundary that matters. Tiberius found it
with a mutation. It is not being shipped that way twice.

⚠️ THE REFUSAL CASES ARE NOT CEREMONY. An empty scan satisfies every per-item
assertion in the loop, so a scan that discovered zero occupied worktrees would print
"no seats stale" and be believed — the same defect that let `disk-hygiene-report.sh`
print nothing for weeks and read as healthy. Both refusal cases assert exit 2 or the
LookupError behind it, never 0.
"""

import importlib.util
import os
import subprocess
import sys
import time

import pytest

import cosa.utils.util as cu

SCAN_PATH = cu.get_project_root() + "/src/scripts/stale-seat-scan.py"


def _load_scan():
    """
    Import the scan module despite its dashed filename.

    Ensures:
        - returns the imported module object
    """
    spec   = importlib.util.spec_from_file_location( "stale_seat_scan", SCAN_PATH )
    module = importlib.util.module_from_spec( spec )
    spec.loader.exec_module( module )
    return module


def _git( repo, *args ):
    """Run git in repo and return stdout, raising with context on failure."""
    done = subprocess.run(
        [ "git", "-C", str( repo ), *args ], capture_output=True, text=True
    )
    if done.returncode != 0:
        raise RuntimeError( f"git {' '.join( args )} failed: {done.stderr}" )
    return done.stdout


def _write( repo, relative, text ):
    """Write a file inside repo, creating parents."""
    path = repo / relative
    path.parent.mkdir( parents=True, exist_ok=True )
    path.write_text( text )
    return path


@pytest.fixture
def fleet( tmp_path ):
    """
    A synthetic repo plus one seat worktree that the target has moved past.

    The shape is the incident in miniature: `shared.py` and `other.py` both exist at
    the point the seat was cut; the target then advances by one commit touching ONLY
    `shared.py`. What the seat goes on to touch is the single variable each case
    changes.

    Ensures:
        - returns ( module, base_repo, seat_worktree )
        - the seat is exactly 1 commit behind `target`
        - the only file the target moved is `shared.py`
    """
    # 🔴 THE TWO NAMES ARE DELIBERATELY DIFFERENT LENGTHS. They were `base` and
    # `seat` — four characters each — and a mutation reversing the longest-first sort
    # SURVIVED, because sorting equal-length strings by length is the identity either
    # way. The fixture could not distinguish the two orders it existed to pin. Values
    # that are interchangeable in the data cannot reveal a swap between them.
    base = tmp_path / "base-delivery-target"
    base.mkdir()
    _git( base, "init", "-q", "-b", "target" )
    _git( base, "config", "user.email", "guard@example.com" )
    _git( base, "config", "user.name", "guard" )

    _write( base, "shared.py", "value = 1\n" )
    _write( base, "other.py",  "value = 1\n" )
    _git( base, "add", "-A" )
    _git( base, "commit", "-q", "-m", "base" )
    cut = _git( base, "rev-parse", "HEAD" ).strip()

    seat = tmp_path / "seat"
    _git( base, "worktree", "add", "-q", "--detach", str( seat ), cut )

    # The target advances past the seat, touching shared.py and nothing else.
    _write( base, "shared.py", "value = 2\n" )
    _git( base, "add", "-A" )
    _git( base, "commit", "-q", "-m", "target moves shared.py" )

    module = _load_scan()
    return module, base, seat


def _scan_with_occupants( module, monkeypatch, roots, occupied ):
    """
    Run scan() with the process table stood in for.

    Occupancy is the ONE thing a synthetic fixture cannot create honestly inside a
    unit test, so it is substituted here and guarded separately, against a REAL
    process, by `test_occupancy_is_read_from_a_live_process_cwd`.

    Ensures:
        - returns ( stale, stats ) from the real scan over real git repositories
    """
    monkeypatch.setattr(
        module, "occupied_worktrees",
        lambda _roots: { str( path ): [ "12345" ] for path in occupied }
    )
    return module.scan( "target", roots=[ str( path ) for path in roots ] )


# ---------------------------------------------------------------- stage 2 discriminates

def test_a_seat_behind_on_files_it_never_touched_is_not_reported( fleet, monkeypatch ):
    """
    STAGE 1 IS NOT SUFFICIENT, AND THIS IS THE CASE THAT SAYS SO.

    The seat is genuinely 1 commit behind. It has dirtied `other.py`. The target
    moved `shared.py`. Behind, and not harmed — the state 7 of 8 live seats were in
    when the census was taken, and reporting it is how the scan gets switched off.
    """
    module, base, seat = fleet
    _write( seat, "other.py", "value = 99\n" )

    assert module.behind_commits( str( seat ), "target" ), "fixture broken: seat is not behind"

    stale, stats = _scan_with_occupants( module, monkeypatch, [ base, seat ], [ seat ] )

    assert stats[ "behind" ]      == 1, "stage 1 must still see it — the point is that stage 2 clears it"
    assert stats[ "overlapping" ] == 0
    assert stale == {}


def test_a_seat_dirtying_the_file_the_target_moved_is_reported( fleet, monkeypatch ):
    """
    BOTH STAGES FIRE. The seat is behind, and the file it has open is the file that
    moved under it. This is the four-people-wrote-the-same-gister-fix shape.
    """
    module, base, seat = fleet
    _write( seat, "shared.py", "value = 99\n" )

    stale, stats = _scan_with_occupants( module, monkeypatch, [ base, seat ], [ seat ] )

    assert stats[ "overlapping" ] == 1
    assert stale[ str( seat ) ][ "overlap" ] == [ "shared.py" ]
    assert stale[ str( seat ) ][ "behind" ]  == 1


def test_a_seat_that_committed_the_moved_file_is_reported( fleet, monkeypatch ):
    """
    THE UNDELIVERED-COMMIT ARM. A seat's work lives in three places and a committed,
    not-yet-merged change is the one this whole row is about — the fix that sits on a
    branch while somebody else writes it again. Dropping `target..HEAD` from the
    touched set would leave exactly that case invisible.
    """
    module, base, seat = fleet
    _write( seat, "shared.py", "value = 99\n" )
    _git( seat, "add", "-A" )
    _git( seat, "commit", "-q", "-m", "seat edits shared.py and does not merge" )

    assert not _git( seat, "status", "--porcelain" ).strip(), "fixture broken: tree should be clean"

    stale, _ = _scan_with_occupants( module, monkeypatch, [ base, seat ], [ seat ] )

    assert stale[ str( seat ) ][ "overlap" ] == [ "shared.py" ]


def test_an_untracked_file_counts_as_touched( fleet, monkeypatch ):
    """
    THE THIRD SOURCE. A brand-new file is the purest duplicate-work signal there is —
    two seats creating the same module is the incident, not a near miss.
    """
    module, base, seat = fleet
    _write( base, "src/newthing.py", "pass\n" )
    _git( base, "add", "-A" )
    _git( base, "commit", "-q", "-m", "target adds newthing" )
    _write( seat, "src/newthing.py", "pass  # written independently\n" )

    stale, _ = _scan_with_occupants( module, monkeypatch, [ base, seat ], [ seat ] )

    assert "src/newthing.py" in stale[ str( seat ) ][ "overlap" ]


def test_a_seat_that_is_not_behind_is_never_reported( fleet, monkeypatch ):
    """
    THE NEGATIVE CONTROL FOR STAGE 1. A seat sitting ON the target, with the shared
    file dirty, must not be reported — otherwise the scan is reporting dirtiness, not
    staleness, and every seat mid-edit is a hit.
    """
    module, base, seat = fleet
    # `--detach`: the base checkout already holds the `target` branch, and git
    # refuses a second checkout of one branch. Detaching AT the target is the same
    # position for every question this scan asks.
    _git( seat, "checkout", "-q", "--detach", "target" )
    _write( seat, "shared.py", "value = 99\n" )

    stale, stats = _scan_with_occupants( module, monkeypatch, [ base, seat ], [ seat ] )

    assert stats[ "behind" ] == 0
    assert stale == {}


def test_an_unoccupied_stale_tree_is_not_reported( fleet, monkeypatch ):
    """
    THE POPULATION RULE, AS A TEST. 183 of 185 worktrees on this box are behind and
    abandoned. A scan that judged trees rather than seats would report a number that
    is true and unusable, which is the cry-wolf figure this row already rejected once.
    """
    module, base, seat = fleet
    _write( seat, "shared.py", "value = 99\n" )

    stale, stats = _scan_with_occupants( module, monkeypatch, [ base, seat ], [ base ] )

    assert stats[ "occupied" ] == 1
    assert stale == {}, "an unoccupied tree must be outside the population entirely"


# ---------------------------------------------------------------- refusals

def test_zero_worktrees_refuses_rather_than_reporting_clean( fleet ):
    """
    An empty root list passes every per-item assertion in the loop. It must raise.
    """
    module, _base, _seat = fleet
    with pytest.raises( LookupError, match="ZERO worktrees" ):
        module.scan( "target", roots=[] )


def test_worktrees_with_no_live_seat_refuses_rather_than_reporting_clean( fleet, monkeypatch ):
    """
    The likelier vacuous case: trees exist, nobody is in any of them. Same rule.
    """
    module, base, seat = fleet
    monkeypatch.setattr( module, "occupied_worktrees", lambda _roots: {} )
    with pytest.raises( LookupError, match="NONE has a live process" ):
        module.scan( "target", roots=[ str( base ), str( seat ) ] )


def test_a_tree_that_cannot_resolve_the_target_is_counted_not_cleared( fleet, monkeypatch ):
    """
    UNRESOLVED IS NOT UP-TO-DATE, AND THAT IS THE FLATTERING READING TO REFUSE. A
    worktree of some OTHER repository has no `target` ref at all. Treating that as
    "nothing behind" would silently shrink the denominator and read as a cleaner
    fleet than the one that exists.
    """
    module, base, seat = fleet
    stranger = base.parent / "stranger"
    stranger.mkdir()
    _git( stranger, "init", "-q" )
    _git( stranger, "config", "user.email", "guard@example.com" )
    _git( stranger, "config", "user.name", "guard" )
    _write( stranger, "shared.py", "value = 1\n" )
    _git( stranger, "add", "-A" )
    _git( stranger, "commit", "-q", "-m", "unrelated" )

    assert module.behind_commits( str( stranger ), "target" ) is None

    stale, stats = _scan_with_occupants( module, monkeypatch, [ base, seat, stranger ], [ stranger ] )

    assert stats[ "unresolved" ] == 1
    assert stats[ "behind" ]     == 0
    assert stale == {}


# ---------------------------------------------------------------- occupancy, against a real process

def test_occupancy_is_read_from_a_live_process_cwd( tmp_path ):
    """
    THE ONE THING THE SYNTHETIC FIXTURE STANDS DOWN, GUARDED AGAINST A REAL PROCESS.

    Every case above substitutes occupancy. If nothing drove the real
    `occupied_worktrees`, the population rule — the whole reason this scan reports 10
    seats rather than 185 trees — would be entirely unmeasured. So this one starts an
    actual process with its cwd inside one directory and not the other, and asserts
    the split.
    """
    module = _load_scan()
    here   = tmp_path / "occupied"
    there  = tmp_path / "empty"
    here.mkdir()
    there.mkdir()

    child = subprocess.Popen( [ sys.executable, "-c", "import time; time.sleep(30)" ], cwd=str( here ) )
    try:
        deadline = time.time() + 10
        while time.time() < deadline:
            occupants = module.occupied_worktrees( [ str( here ), str( there ) ] )
            if str( here ) in occupants: break
            time.sleep( 0.05 )

        assert str( here ) in occupants, "a live process's cwd must place it in that tree"
        assert str( child.pid ) in occupants[ str( here ) ]
        assert str( there ) not in occupants, "an empty directory must not appear at all"
    finally:
        child.kill()
        child.wait()


def test_a_cwd_below_a_worktree_is_attributed_to_the_longest_matching_root( tmp_path ):
    """
    NESTED ROOTS ARE WHY THE LIST IS SORTED LONGEST-FIRST. A seat standing in
    `<root>/nested` must be attributed to `nested`, not to its parent — an unsorted
    prefix match would credit the outer tree and clear the inner one, which is the
    silent-wrong-answer direction.
    """
    module = _load_scan()
    outer  = tmp_path / "outer"
    inner  = outer / "nested"
    inner.mkdir( parents=True )

    child = subprocess.Popen( [ sys.executable, "-c", "import time; time.sleep(30)" ], cwd=str( inner ) )
    try:
        roots    = sorted( [ str( outer ), str( inner ) ], key=len, reverse=True )
        deadline = time.time() + 10
        while time.time() < deadline:
            occupants = module.occupied_worktrees( roots )
            if occupants: break
            time.sleep( 0.05 )

        assert str( inner ) in occupants
        assert str( outer ) not in occupants
    finally:
        child.kill()
        child.wait()


def test_worktree_roots_are_returned_longest_first( fleet ):
    """
    The ordering the case above depends on is produced here, so it is asserted here
    too — a property held by two files is a property that survives an edit to one.
    """
    module, base, _seat = fleet
    roots = module.worktree_roots( repo=str( base ) )
    assert len( roots ) == 2
    assert roots == sorted( roots, key=len, reverse=True )


# ---------------------------------------------------------------- the process boundary

@pytest.fixture
def installed_fleet( tmp_path ):
    """
    The same synthetic fleet, with the scan INSTALLED INSIDE IT.

    The script derives its repo root from its own location, so a copy living at
    `<proj>/src/scripts/` scans `<proj>` and nothing else. That is what makes an
    end-to-end subprocess run DETERMINISTIC: without it the script scans the live
    box, whose worktree set and process table move under the test, and a case that
    must accept several outcomes cannot discriminate between any of them.

    Ensures:
        - returns ( scan_path, project_root, seat_worktree )
        - the seat is 1 commit behind `target` and has the moved file dirty
        - NO process has its cwd inside either tree
    """
    proj = tmp_path / "proj-delivery-target"
    proj.mkdir()
    _git( proj, "init", "-q", "-b", "target" )
    _git( proj, "config", "user.email", "guard@example.com" )
    _git( proj, "config", "user.name", "guard" )
    _write( proj, "shared.py", "value = 1\n" )
    _git( proj, "add", "-A" )
    _git( proj, "commit", "-q", "-m", "base" )
    cut = _git( proj, "rev-parse", "HEAD" ).strip()

    seat = tmp_path / "seat"
    _git( proj, "worktree", "add", "-q", "--detach", str( seat ), cut )

    _write( proj, "shared.py", "value = 2\n" )
    _git( proj, "add", "-A" )
    _git( proj, "commit", "-q", "-m", "target moves shared.py" )

    _write( seat, "shared.py", "value = 99\n" )

    installed = proj / "src" / "scripts" / "stale-seat-scan.py"
    installed.parent.mkdir( parents=True, exist_ok=True )
    installed.write_bytes( open( SCAN_PATH, "rb" ).read() )
    return installed, proj, seat


def test_the_refusal_reaches_the_shell( installed_fleet ):
    """
    EXIT 2 MUST ARRIVE AS A PROCESS EXIT CODE, NOT AS A RETURN VALUE.

    A previous guard by this author asserted `main()`'s return value and so never ran
    `__main__` or its `sys.exit()`. Tiberius found it with a mutation. The FIRST
    version of this replacement had the same hole in a different shape: it ran the
    real box, where the exit is unpredictable, so it accepted both 0 and 2 — and a
    mutation deleting `sys.exit()` SURVIVED it. A test that accepts two answers
    cannot tell you which one it got.

    Here nobody is standing in either tree, so the refusal is deterministic.
    """
    scan_path, _proj, _seat = installed_fleet

    done = subprocess.run(
        [ sys.executable, str( scan_path ), "--target", "target" ],
        capture_output=True, text=True, timeout=300
    )

    assert done.returncode == 2, f"expected the refusal, got {done.returncode}: {done.stdout}{done.stderr}"
    assert "REFUSED" in done.stderr
    assert "NONE has a live process" in done.stderr
    assert "not read this as a clean run" in done.stderr


def test_a_stale_seat_exits_one_at_the_process_boundary( installed_fleet ):
    """
    EXIT 1 MUST REACH THE SHELL TOO, AND FROM THE PLAIN RUN.

    The `--mine` arm and this one take DIFFERENT paths out of `main()`, so a mutation
    that flattened the plain path to 0 survived a suite that only ever passed
    `--mine`. A caller wiring this into a preflight uses the plain form.

    One real process is started with its cwd in the seat, which is the only honest way
    to make the population non-empty at the process boundary.
    """
    scan_path, _proj, seat = installed_fleet

    child = subprocess.Popen( [ sys.executable, "-c", "import time; time.sleep(60)" ], cwd=str( seat ) )
    try:
        done = subprocess.run(
            [ sys.executable, str( scan_path ), "--target", "target" ],
            capture_output=True, text=True, timeout=300
        )
    finally:
        child.kill()
        child.wait()

    assert done.returncode == 1, f"expected a hit, got {done.returncode}: {done.stdout}{done.stderr}"
    assert "shared.py" in done.stdout
    assert "LIVE-OCCUPIED 1" in done.stdout


def test_a_clean_run_still_prints_its_denominators( fleet, monkeypatch, capsys ):
    """
    A scan that cannot state its own corpus is telling you about its corpus, not your
    fleet. The denominators must print on a clean run, which is the run nobody reads
    and therefore the one that goes silent first.
    """
    module, base, seat = fleet
    _write( seat, "other.py", "value = 99\n" )
    monkeypatch.setattr(
        module, "occupied_worktrees", lambda _roots: { str( seat ): [ "12345" ] }
    )
    monkeypatch.setattr( module, "worktree_roots", lambda repo=None: [ str( base ), str( seat ) ] )

    code = module.main( [ "--target", "target" ] )
    out  = capsys.readouterr().out

    assert code == 0
    assert "LIVE-OCCUPIED 1" in out
    assert "behind 1" in out
    assert "AND overlapping 0" in out


def test_mine_narrows_the_exit_code_to_this_seat( fleet, monkeypatch, capsys ):
    """
    `--mine` exists so a session-end preflight fails on ITS OWN collision and not on
    somebody else's. Both directions, because "always 0" and "always 1" each satisfy
    one of them.
    """
    module, base, seat = fleet
    _write( seat, "shared.py", "value = 99\n" )
    monkeypatch.setattr(
        module, "occupied_worktrees", lambda _roots: { str( seat ): [ "12345" ] }
    )
    monkeypatch.setattr( module, "worktree_roots", lambda repo=None: [ str( base ), str( seat ) ] )

    assert module.main( [ "--target", "target", "--mine", str( seat ) ] ) == 1
    capsys.readouterr()
    assert module.main( [ "--target", "target", "--mine", str( base ) ] ) == 0
