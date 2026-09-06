"""
Guard for `src/scripts/delivery-collision-scan.py` — row d2dd3ee3.

WHAT THIS FILE IS FOR. The scan exists because four engineers wrote the same
gister fix in twenty-four hours, each looking at a clean tree. The scan is only
worth having if it actually DISCRIMINATES, so every case here is built on a
SYNTHETIC repository with one variable changed — not on the live tree, whose
branch set moves under the test and would make a red mean nothing.

🔴 THE CASE THAT CARRIES THE FILE IS `test_content_delivered_by_squash_is_not_reported`.
Lupin delivers epics by squash, and a squash destroys ancestry, patch-id AND
subject at once. Measured on the live repo at a3f45e6d, `merge-base --is-ancestor`
called 3,976 commits unmerged where content-probing found 1,283 — a 3.1x
over-report. A scan built on ancestry cries wolf at three times the real number,
and a check that cries wolf is a check nobody reads, which is the not-installed
failure the whole row is about. That case fails the moment somebody "simplifies"
the probe back to an ancestry test, which is the likeliest future regression.

⚠️ THE VACUOUS CASES ARE NOT CEREMONY. `disk-hygiene-report.sh` — the only other
script in this tree that computes merged-ness — dies on an unmatched glob and
prints nothing, and its silence is indistinguishable from a clean run. A scan that
discovered zero branches would print "no collisions" and be believed. Both refusal
cases below assert exit 2, never 0.
"""

import importlib.util
import subprocess
import sys

import pytest

import cosa.utils.util as cu

SCAN_PATH = cu.get_project_root() + "/src/scripts/delivery-collision-scan.py"


def _load_scan():
    """
    Import the scan module despite its dashed filename.

    Ensures:
        - returns the imported module object
    """
    spec   = importlib.util.spec_from_file_location( "delivery_collision_scan", SCAN_PATH )
    module = importlib.util.module_from_spec( spec )
    spec.loader.exec_module( module )
    return module


def _git( repo, *args ):
    """Run git in repo and return stdout, raising with context on failure."""
    done = subprocess.run(
        [ "git", "-C", str( repo ), *args ], capture_output=True, text=True
    )
    if done.returncode != 0 and args[ 0 ] not in ( "grep", ):
        raise RuntimeError( f"git {' '.join( args )} failed: {done.stderr}" )
    return done.stdout


def _commit( repo, path, text, message ):
    """Write text to path and commit it."""
    target = repo / path
    target.parent.mkdir( parents=True, exist_ok=True )
    target.write_text( text )
    _git( repo, "add", str( path ) )
    _git( repo, "commit", "-q", "-m", message )
    return _git( repo, "rev-parse", "HEAD" ).strip()


@pytest.fixture
def repo( tmp_path ):
    """
    A synthetic repo with a `target` branch and one shared base commit.

    Ensures:
        - returns a Path to an initialised repo whose current branch is `target`
    """
    root = tmp_path / "synth"
    root.mkdir()
    _git( root, "init", "-q", "-b", "target" )
    _git( root, "config", "user.email", "guard@example.com" )
    _git( root, "config", "user.name", "guard" )
    _commit( root, "src/shared.py", "def base():\n    return 'the original implementation line'\n", "base" )
    return root


@pytest.fixture
def scan( repo, monkeypatch ):
    """
    The scan module, pointed at the synthetic repo instead of the real one.

    The module resolves REPO_ROOT from its own __file__ on purpose (commit
    5e7f74e8 removed exactly that steering from purge-pycache.sh after it cleaned
    the main checkout from inside a worktree). Redirecting it is therefore
    deliberate test surgery, not a supported flag.
    """
    module = _load_scan()
    monkeypatch.setattr( module, "REPO_ROOT", repo )
    module._ABSENCE_CACHE.clear()
    return module


# A line long enough to clear MIN_PROBE_LINE, so the probe has something to find.
LONG_A = "    return 'alpha branch adds this distinctly long marker line here'"
LONG_B = "    return 'beta branch adds a different but equally long marker line'"


def _branch_with( repo, name, path, text, message ):
    """Create name off target, commit one change, and return to target."""
    _git( repo, "checkout", "-q", "-b", name, "target" )
    sha = _commit( repo, path, text, message )
    _git( repo, "checkout", "-q", "target" )
    return sha


def test_two_branches_on_one_file_is_reported( scan, repo ):
    """
    POSITIVE CONTROL — the shape that cost Rick two days.

    Two branches carry undelivered edits to one file. That is the whole trigger,
    and it must fire regardless of age: the pair proven to conflict on 2026-09-05
    (dd81cc7f, 755b821c) were 14 hours and 0 hours old, so an age filter would
    have excluded both.
    """
    a = _branch_with( repo, "wt-alpha", "src/shared.py", f"def base():\n{LONG_A}\n", "alpha fix" )
    b = _branch_with( repo, "wt-beta",  "src/shared.py", f"def base():\n{LONG_B}\n", "beta fix" )

    collisions, stats = scan.scan( "target", max_tip_age_days=365 )

    assert "src/shared.py" in collisions, f"collision missed; stats={stats}"
    branches = { br for br, _ in collisions[ "src/shared.py" ] }
    assert branches == { "wt-alpha", "wt-beta" }
    assert { sha for _, sha in collisions[ "src/shared.py" ] } == { a, b }


def test_two_branches_on_DIFFERENT_files_is_not_reported( scan, repo ):
    """
    NEGATIVE CONTROL — without it, a scan that flagged everything would pass the
    case above and still be worthless.
    """
    _branch_with( repo, "wt-alpha", "src/alpha.py", f"def a():\n{LONG_A}\n", "alpha" )
    _branch_with( repo, "wt-beta",  "src/beta.py",  f"def b():\n{LONG_B}\n", "beta" )

    collisions, stats = scan.scan( "target", max_tip_age_days=365 )

    assert collisions == {}, f"false positive: {collisions}"
    assert stats[ "candidate_commits" ] == 2, "the scan must still have LOOKED at both"


def test_one_branch_alone_on_a_file_is_not_reported( scan, repo ):
    """A lone undelivered commit is not a collision — one branch is not two."""
    _branch_with( repo, "wt-alpha", "src/shared.py", f"def base():\n{LONG_A}\n", "alpha only" )

    collisions, _stats = scan.scan( "target", max_tip_age_days=365 )

    assert collisions == {}


def test_content_delivered_by_squash_is_not_reported( scan, repo ):
    """
    🔴 THE LOAD-BEARING CASE. Both branches' content is ALREADY in target, arriving
    the way this repo actually delivers — squashed into one commit, so neither
    branch is an ancestor and neither patch-id matches.

    An ancestry-based scan reports this as a two-branch collision. It is not one:
    the work has landed. Measured on the live repo, that mistake inflates the
    finding 3.1x, and a check that cries wolf is a check nobody reads.
    """
    # 🔴 BOTH BRANCHES MUST TOUCH THE SAME FILE, and this is not incidental. The
    # first cut of this case put them on DIFFERENT files, so the cheap contested
    # filter cleared it before the probe ever ran and the assertion below was
    # satisfied by a path it was not testing. Mutation M1 — replacing the probe
    # body with `return True` — SURVIVED that version: 11 passed, nothing red.
    # An assertion satisfied by more than one path cannot tell you which one fired.
    _branch_with( repo, "wt-alpha", "src/shared.py", f"def base():\n{LONG_A}\n", "alpha fix" )
    _branch_with( repo, "wt-beta",  "src/shared.py", f"def base():\n{LONG_B}\n", "beta fix" )

    # the squash: ONE commit on target carrying both branches' lines, so the file
    # is genuinely contested AND both contributions are genuinely delivered
    ( repo / "src" / "shared.py" ).write_text( f"def base():\n{LONG_A}\n{LONG_B}\n" )
    _git( repo, "add", "-A" )
    _git( repo, "commit", "-q", "-m", "Squash of alpha and beta (#99)" )

    # ancestry still calls both branches unmerged — the premise of the case
    for branch in ( "wt-alpha", "wt-beta" ):
        done = subprocess.run(
            [ "git", "-C", str( repo ), "merge-base", "--is-ancestor", branch, "target" ],
            capture_output=True, text=True
        )
        assert done.returncode != 0, f"{branch} became an ancestor; the case no longer tests what it says"

    collisions, _stats = scan.scan( "target", max_tip_age_days=365 )

    # The cheap filter CANNOT clear this one — both branches are on src/shared.py,
    # so it reaches the probe by construction. Only content-presence can clear it.
    assert collisions == {}, (
        "delivered-by-squash content was reported as undelivered — the probe has "
        f"regressed to an ancestry test: {collisions}"
    )


def test_zero_branches_REFUSES_rather_than_reporting_clean( scan, repo ):
    """
    VACUOUS DISCOVERY, case 1. No branch is inside the window, so nothing was
    scanned. Reporting "no collisions" here would be a confident answer to a
    question nobody asked.
    """
    _branch_with( repo, "wt-alpha", "src/shared.py", f"def base():\n{LONG_A}\n", "alpha" )

    with pytest.raises( LookupError, match="ZERO branches" ):
        scan.scan( "target", max_tip_age_days=0.0000001 )


def test_zero_candidate_commits_REFUSES_rather_than_reporting_clean( scan, repo ):
    """
    VACUOUS DISCOVERY, case 2 — and it is a DIFFERENT failure from case 1, which is
    why both exist. Branches are found, but none carries a non-ancestor commit, so
    the probe loop never executes. A loop over nothing satisfies every assertion
    inside it.
    """
    _git( repo, "branch", "wt-alpha", "target" )

    with pytest.raises( LookupError, match="ZERO candidate commits" ):
        scan.scan( "target", max_tip_age_days=365 )


def test_a_partial_scan_REFUSES_rather_than_reporting_what_it_reached( scan, repo ):
    """
    A scan cut short has looked at some of the corpus and none of the rest.
    Returning its findings would present a partial answer in the shape of a
    complete one.
    """
    _branch_with( repo, "wt-alpha", "src/shared.py", f"def base():\n{LONG_A}\n", "alpha" )
    _branch_with( repo, "wt-beta",  "src/shared.py", f"def base():\n{LONG_B}\n", "beta" )

    with pytest.raises( TimeoutError, match="PARTIAL scan is not a clean scan" ):
        scan.scan( "target", max_tip_age_days=365, deadline_seconds=-1.0 )


@pytest.mark.parametrize(
    "case, expected",
    [ ( "collision", 1 ), ( "clean", 0 ), ( "vacuous", 2 ) ],
)
def test_exit_codes_are_three_distinct_answers( scan, repo, case, expected, capsys ):
    """
    The three exit codes are a CONTRACT, and a caller reading `rc == 0` as "fine"
    must be right. Two failure modes wanting opposite remedies — fix your invocation
    versus deliver your work — must never share one code.
    """
    if case == "collision":
        _branch_with( repo, "wt-alpha", "src/shared.py", f"def base():\n{LONG_A}\n", "alpha" )
        _branch_with( repo, "wt-beta",  "src/shared.py", f"def base():\n{LONG_B}\n", "beta" )
        argv = [ "--target", "target", "--max-tip-age-days", "365" ]
    elif case == "clean":
        _branch_with( repo, "wt-alpha", "src/alpha.py", f"def a():\n{LONG_A}\n", "alpha" )
        argv = [ "--target", "target", "--max-tip-age-days", "365" ]
    else:
        _branch_with( repo, "wt-alpha", "src/shared.py", f"def base():\n{LONG_A}\n", "alpha" )
        argv = [ "--target", "target", "--max-tip-age-days", "0.0000001" ]

    assert scan.main( argv + [ "--quiet" ] ) == expected


def test_the_scan_states_its_own_denominator( scan, repo, capsys ):
    """
    A guard that cannot state how much it scanned is telling you about its corpus,
    not about your code. The counts print on a CLEAN run too — that is the point.
    """
    _branch_with( repo, "wt-alpha", "src/alpha.py", f"def a():\n{LONG_A}\n", "alpha" )

    assert scan.main( [ "--target", "target", "--max-tip-age-days", "365", "--quiet" ] ) == 0

    out = capsys.readouterr().out
    for field in ( "branches", "candidate commits", "code files", "content-probed", "CONFIRMED" ):
        assert field in out, f"clean run did not state {field!r}: {out}"


# ---------------------------------------------------------------- the silent age filter
#
# Added 2026-09-05 (row d2dd3ee3, event 11968) after the scan's own confirmed count
# fell from 143 to 14 in EIGHTEEN MINUTES on this repo with nothing delivered: two
# branches carrying 1,626 and 1,627 undelivered commits crossed the seven-day
# boundary between two runs. **A falling number reads as a drain**, so a silent
# filter turned an unchanged backlog into apparent progress — the flattering
# reading this whole script exists to refuse, living inside the script.
#
# The filter is CORRECT and stays. What was wrong is that it said nothing.


def _age_branch( repo, name, days ):
    """
    Backdate a branch's tip so the age filter sees it as `days` old.

    Ensures:
        - the branch's committer date is moved back; nothing else about it changes
    """
    import subprocess, time as _t
    stamp = _t.strftime( "%Y-%m-%dT%H:%M:%S", _t.localtime( _t.time() - days * 86400 ) )
    subprocess.run(
        [ "git", "-C", str( repo ), "checkout", "-q", name ], capture_output=True, text=True
    )
    subprocess.run(
        [ "git", "-C", str( repo ), "commit", "-q", "--amend", "--no-edit", "--date", stamp ],
        capture_output=True, text=True,
        env={ **__import__( "os" ).environ, "GIT_COMMITTER_DATE": stamp },
    )
    subprocess.run(
        [ "git", "-C", str( repo ), "checkout", "-q", "target" ], capture_output=True, text=True
    )


def test_an_aged_out_branch_is_NAMED_rather_than_dropped( scan, repo ):
    """
    🔴 POSITIVE CONTROL — the branch the OLD parameterisation missed and the new one FINDS.

    `wt-old` collides with `wt-fresh` on one file and its tip is 40 days old, so a
    7-day window excludes it. Before this change the scan reported a smaller
    CONFIRMED count and said nothing at all about the exclusion; the reader had no
    way to tell a drained backlog from a filtered one.

    The claim under test is NOT that the collision is reported — it is correctly
    not reported at 7 days. The claim is that the branch is **named as unexamined**,
    so the absence is legible as invisibility rather than as absence.
    """
    _branch_with( repo, "wt-old",   "src/shared.py", f"def base():\n{LONG_A}\n", "old fix" )
    _branch_with( repo, "wt-fresh", "src/shared.py", f"def base():\n{LONG_B}\n", "fresh fix" )
    _age_branch( repo, "wt-old", days=40 )

    inside, excluded = scan.discover_branches( "target", max_tip_age_days=7 )

    assert "wt-old"   not in [ n for n, _ in inside ],   "fixture broken: wt-old should be outside the window"
    assert "wt-old"       in [ n for n, _ in excluded ], "the aged-out branch must be RETURNED, not dropped"
    assert "wt-fresh"     in [ n for n, _ in inside ]
    assert "wt-fresh" not in [ n for n, _ in excluded ]

    _collisions, stats = scan.scan( "target", max_tip_age_days=7 )
    assert stats[ "excluded_by_age" ] == 1
    assert [ n for n, _ in stats[ "excluded_branches" ] ] == [ "wt-old" ]


def test_a_branch_inside_the_window_is_found_by_both_settings( scan, repo ):
    """
    NEGATIVE CONTROL — the branch BOTH settings find, unchanged by this work.

    Without this, "the aged-out branch is named" is satisfied by an implementation
    that names EVERY branch as excluded, which would be a scan that examines
    nothing while reporting loudly. Two settings, one variable, and the in-window
    pair must collide under both.
    """
    _branch_with( repo, "wt-alpha", "src/shared.py", f"def base():\n{LONG_A}\n", "alpha fix" )
    _branch_with( repo, "wt-beta",  "src/shared.py", f"def base():\n{LONG_B}\n", "beta fix" )

    narrow, narrow_stats = scan.scan( "target", max_tip_age_days=7 )
    wide,   wide_stats   = scan.scan( "target", max_tip_age_days=365 )

    assert "src/shared.py" in narrow, f"in-window collision missed at 7d; stats={narrow_stats}"
    assert "src/shared.py" in wide,   f"in-window collision missed at 365d; stats={wide_stats}"
    assert narrow_stats[ "excluded_by_age" ] == 0, "nothing here is old; excluding anything would be a false alarm"
    assert wide_stats[ "excluded_by_age" ]   == 0


def test_the_not_examined_line_prints_even_when_nothing_was_excluded( scan, capsys ):
    """
    SILENCE MUST NEVER MEAN "THE FILTER DID NOT RUN".

    A reader who sees no exclusion line cannot tell a clean window from a build
    where the reporting was removed. So the zero case prints its own sentence.
    """
    scan._print_not_examined( { "excluded_by_age": 0, "excluded_branches": [] }, 7.0 )
    out = capsys.readouterr().out
    assert "0 branches excluded by age" in out
    assert "every branch was examined at 7.0d" in out


def test_the_not_examined_line_caps_its_list_and_says_how_many_it_withheld( scan, capsys ):
    """
    THE WARNING MUST NOT BECOME THE NOISE IT WARNS ABOUT.

    A repo with hundreds of stale branches would drown the summary it is meant to
    qualify. The count is always exact; the names are capped and the remainder is
    stated rather than silently dropped — which is the same defect one level down.
    """
    now      = 1_000_000_000.0
    excluded = [ ( f"wt-stale-{i:03d}", now - ( 10 + i ) * 86400 ) for i in range( 25 ) ]
    scan._print_not_examined(
        { "excluded_by_age": 25, "excluded_branches": excluded }, 7.0, now=now, cap=20
    )
    out = capsys.readouterr().out

    assert "25 branches NOT EXAMINED" in out
    assert "INVISIBLE, not absent" in out
    assert out.count( "wt-stale-" ) == 20, "the list must be capped"
    assert "and 5 more" in out, "the withheld remainder must be stated, never silently dropped"


def test_main_actually_prints_the_not_examined_line( scan, repo, capsys ):
    """
    🔴 IMPLEMENTED IS NOT INSTALLED — this drives `main()`, not the helper.

    Every case above calls `_print_not_examined` directly, so all of them stay green
    if the call site in `main()` is deleted: the helper would be complete, correct,
    fully covered and never reached, and the summary would go silent exactly as it
    was before this change. That is the defect this row keeps finding in other
    people's code and it would have shipped here.
    """
    _branch_with( repo, "wt-old",   "src/shared.py", f"def base():\n{LONG_A}\n", "old fix" )
    _branch_with( repo, "wt-fresh", "src/shared.py", f"def base():\n{LONG_B}\n", "fresh fix" )
    _age_branch( repo, "wt-old", days=40 )

    scan.main( [ "--target", "target", "--quiet", "--max-tip-age-days", "7" ] )
    out = capsys.readouterr().out

    assert "NOT EXAMINED" in out, "main() must surface the exclusion, not just be able to"
    assert "wt-old" in out
    assert "INVISIBLE, not absent" in out
