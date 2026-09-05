"""
Guard for `src/scripts/stale-process-scan.py` — row d2dd3ee3, link 2.

WHAT THIS FILE IS FOR. The delivery chain is
`committed -> merged -> respawned -> cache-busted`. Link 1 has a scan and a guard;
link 3 has a guard; **link 2 had neither**, and it was found by hand twice on
2026-09-05. The scan is only worth having if it DISCRIMINATES, so every case here
runs against a SYNTHETIC repo and a SYNTHETIC process list, one variable at a time.
Nothing here reads the live `/proc` or the live branch set — both move under the
test, and a red that moves on its own tells the reader nothing.

THE CASE THAT CARRIES THE FILE IS
`test_a_changed_file_NOT_reachable_from_the_entry_point_is_not_stale`.

The obvious instrument here is a start-time-versus-commit-time comparison, and it
is NOT SUFFICIENT. Run against the live box on 2026-09-05 it flagged three MCP
subprocesses as stale. **All three were false**: the commits behind them touched
`src/lupin_mcp/fleet_cap_admission.py`, which nothing in the tree imports. The
screen was right about the timestamps and wrong about the world. Delete the
reachability stage and those three flags come back — which is exactly what that
case asserts, and it is the likeliest future "simplification".

AND THAT CASE CARRIES ITS OWN POSITIVE CONTROL, deliberately. A negative
assertion is satisfied by a scan that found nothing for ANY reason — including a
fixture where no commit ever landed. So it first asserts that stage 1 genuinely
fires on the unreachable file (`changed_since` sees it), and only then that the
whole scan stays clean. Without that, the case would pass on an empty repo and
prove nothing about stage 2.

THE REFUSAL CASES ARE NOT CEREMONY. A scan that classified zero processes would
print "0 stale" and be believed — the same silent-clean failure that left
`disk-hygiene-report.sh` exiting 1 with no output for an unknown period. Every
vacuous case below asserts exit 2, never 0.
"""

import importlib.util
import os
import subprocess
import time

import pytest

import cosa.utils.util as cu

SCAN_PATH = cu.get_project_root() + "/src/scripts/stale-process-scan.py"

# The fake fleet's clock. Everything is anchored to one `NOW` so the cases read as
# a timeline rather than as arithmetic scattered through the fixtures.
NOW         = int( time.time() )
HOUR        = 3600
BASE_TIME   = NOW - 6 * HOUR      # the repo's first commits
CHANGE_TIME = NOW - 2 * HOUR      # the commit under test
OLD_PROC    = NOW - 4 * HOUR      # started BEFORE the change  -> can be stale
FRESH_PROC  = NOW - 1 * HOUR      # started AFTER  the change  -> cannot be stale


def _load_scan():
    """
    Import the scan module despite its dashed filename.

    Ensures:
        - returns the imported module object
    """
    spec   = importlib.util.spec_from_file_location( "stale_process_scan", SCAN_PATH )
    module = importlib.util.module_from_spec( spec )
    spec.loader.exec_module( module )
    return module


def _base_env():
    """A minimal, deterministic git environment — no user config, no signing."""
    keep = { k : v for k, v in os.environ.items() if k in ( "PATH", "HOME", "LANG" ) }
    keep.update( {
        "GIT_CONFIG_GLOBAL"   : "/dev/null",
        "GIT_CONFIG_SYSTEM"   : "/dev/null",
        "GIT_AUTHOR_NAME"     : "guard",
        "GIT_AUTHOR_EMAIL"    : "guard@example.com",
        "GIT_COMMITTER_NAME"  : "guard",
        "GIT_COMMITTER_EMAIL" : "guard@example.com",
    } )
    return keep


def _git( repo, *args, when=None ):
    """
    Run git in repo, optionally pinning the commit's author AND committer date.

    `changed_since` filters on `--since=@<epoch>`, which reads the COMMITTER date —
    so pinning only the author date would leave every commit stamped "now" and the
    before/after cases would silently collapse into one.

    Ensures:
        - returns stdout as str
    Raises:
        - RuntimeError carrying git's stderr when the command fails
    """
    env = _base_env()
    if when is not None:
        stamp = f"@{int( when )} +0000"
        env[ "GIT_AUTHOR_DATE" ]    = stamp
        env[ "GIT_COMMITTER_DATE" ] = stamp
    done = subprocess.run(
        [ "git", "-C", str( repo ), *args ], capture_output=True, text=True, env=env
    )
    if done.returncode != 0:
        raise RuntimeError( f"git {' '.join( args )} failed: {done.stderr}" )
    return done.stdout


def _commit( repo, path, text, message, when ):
    """Write text to path and commit it at a pinned time."""
    target = repo / path
    target.parent.mkdir( parents=True, exist_ok=True )
    target.write_text( text )
    _git( repo, "add", str( path ) )
    _git( repo, "commit", "-q", "-m", message, when=when )
    return _git( repo, "rev-parse", "HEAD" ).strip()


@pytest.fixture
def repo( tmp_path ):
    """
    A synthetic repo whose import graph has a REACHED half and an UNREACHED half.

        src/pkg/entry.py  ->  imports pkg.used  ->  imports pkg.deep
        src/pkg/orphan.py     imported by nothing

    That asymmetry is the whole point: `orphan.py` is the synthetic stand-in for
    `fleet_cap_admission.py`, the real file whose three flags were all false.

    Ensures:
        - returns a Path to an initialised repo on branch `target`
    """
    root = tmp_path / "synth"
    root.mkdir()
    _git( root, "init", "-q", "-b", "target" )
    _commit(
        root, "src/pkg/entry.py",
        "import os\nimport pkg.used\n\n\ndef main():\n    return pkg.used.value()\n",
        "base: entry", when=BASE_TIME
    )
    _commit(
        root, "src/pkg/used.py",
        "import pkg.deep\n\n\ndef value():\n    return pkg.deep.n()\n",
        "base: used", when=BASE_TIME
    )
    _commit( root, "src/pkg/deep.py",   "def n():\n    return 1\n", "base: deep",   when=BASE_TIME )
    _commit( root, "src/pkg/orphan.py", "def x():\n    return 2\n", "base: orphan", when=BASE_TIME )
    return root


@pytest.fixture
def scan( repo, monkeypatch ):
    """
    The scan module, pointed at the synthetic repo and a synthetic process list.

    The module resolves REPO_ROOT from its own `__file__` on purpose (commit
    5e7f74e8 removed exactly that steering from purge-pycache.sh after it cleaned
    the main checkout from inside a worktree and printed its success banner).
    Redirecting it here is deliberate test surgery, not a supported flag.

    `_container_of` and `_safe_cgroup` are stood down because they shell out to
    docker and read a real `/proc`; neither is what any case here measures, and a
    test that needs docker running is a test that goes red for the wrong reason.
    """
    module = _load_scan()
    monkeypatch.setattr( module, "REPO_ROOT", repo )
    monkeypatch.setattr( module, "KNOWN_CLASSES",
                         [ ( "synthetic_daemon", "synthetic daemon", "src/pkg/entry.py" ) ] )
    monkeypatch.setattr( module, "_container_of", lambda pid: None )
    monkeypatch.setattr( module, "_safe_cgroup",  lambda pid: "" )
    return module


def _fleet( module, monkeypatch, *procs ):
    """Install a synthetic process list. Each proc is ( pid, cmdline, started )."""
    listing = [
        {
            "pid"     : pid,
            "comm"    : "python3",
            "cwd"     : "/synthetic/lupin",
            "root"    : "/synthetic/lupin",
            "started" : started,
            "cmdline" : cmdline,
        }
        for pid, cmdline, started in procs
    ]
    monkeypatch.setattr( module, "running_processes", lambda: listing )


# ---------------------------------------------------------------------------
# the two stages, together and separately
# ---------------------------------------------------------------------------

def test_a_changed_reachable_file_makes_a_long_lived_process_stale( scan, repo, monkeypatch ):
    """
    POSITIVE CONTROL — the shape found by hand twice on 2026-09-05.

    A commit lands on a module the running process imported at startup. The file
    on disk changed; the running code did not.
    """
    sha = _commit( repo, "src/pkg/deep.py", "def n():\n    return 99\n", "fix deep", when=CHANGE_TIME )
    _fleet( scan, monkeypatch, ( "4242", "python3 -m synthetic_daemon", OLD_PROC ) )

    stale, stats = scan.scan()

    assert "4242" in stale, f"missed a genuinely stale process; stats={stats}"
    assert stale[ "4242" ][ "changed" ] == { "src/pkg/deep.py" : sha }
    assert stats[ "classified" ]  == 1
    assert stats[ "both_stages" ] == 1


def test_a_changed_file_NOT_reachable_from_the_entry_point_is_not_stale( scan, repo, monkeypatch ):
    """
    THE LOAD-BEARING CASE — stage 2, and the whole reason this scan has two
    stages rather than one.

    A commit lands on `orphan.py`, which nothing imports. A timing-only screen
    calls this process stale; it is not. Measured on the live box, that mistake
    produced three false flags out of three — and a scan that cries wolf on its
    first day is a scan somebody switches off.

    THE POSITIVE CONTROL IS INSIDE THE CASE. Asserting only "no stale processes"
    would pass on a repo where nothing changed at all, so this first proves stage 1
    genuinely fires on the orphan, and only then that the full scan stays clean.
    Without it the case is satisfied by a path it is not testing.
    """
    sha = _commit( repo, "src/pkg/orphan.py", "def x():\n    return 77\n", "touch orphan", when=CHANGE_TIME )
    _fleet( scan, monkeypatch, ( "4242", "python3 -m synthetic_daemon", OLD_PROC ) )

    # positive control: the TIMING stage, on its own, does see this commit
    timing_only = scan.changed_since( OLD_PROC, [ "src/pkg/orphan.py" ] )
    assert timing_only == { "src/pkg/orphan.py" : sha }, (
        "stage 1 did not fire on the orphan — this case would then pass for the "
        "wrong reason and prove nothing about reachability"
    )

    stale, stats = scan.scan()

    assert stale == {}, (
        "an unreachable changed file was reported stale — the reachability stage "
        f"has been removed or bypassed: {stale}"
    )
    assert stats[ "classified" ] == 1, "the process must still have been LOOKED at"


def test_a_process_started_after_the_commit_is_not_stale( scan, repo, monkeypatch ):
    """
    NEGATIVE CONTROL for stage 1 — the respawn actually happened.

    Same reachable file, same commit; only the process's start time moves. Without
    this case a scan that flagged every classified process would pass everything
    above.
    """
    _commit( repo, "src/pkg/deep.py", "def n():\n    return 99\n", "fix deep", when=CHANGE_TIME )
    _fleet( scan, monkeypatch, ( "4242", "python3 -m synthetic_daemon", FRESH_PROC ) )

    stale, stats = scan.scan()

    assert stale == {}, f"a process started after the commit was called stale: {stale}"
    assert stats[ "classified" ] == 1


def test_a_transitive_import_two_hops_out_still_counts_as_reachable( scan, repo ):
    """
    `deep.py` is imported by `used.py`, which is imported by `entry.py`. A
    one-hop-only walk would clear the positive control above for the wrong reason
    and quietly halve the scan's reach.
    """
    reachable = scan.reachable_modules( "src/pkg/entry.py" )

    assert reachable == { "src/pkg/entry.py", "src/pkg/used.py", "src/pkg/deep.py" }
    assert "src/pkg/orphan.py" not in reachable


def test_a_function_level_import_is_counted_as_reachable( scan, repo ):
    """
    PINS A DELIBERATE OVER-REPORT, so nobody "fixes" it silently.

    `cosa_voice_mcp.py` imports `session_spawner` inside a function, so that module
    is read at CALL time and may already be fresh in a running process. Counting it
    reachable over-reports — and that direction is chosen: a false "go and check"
    costs a minute, a false all-clear costs a day chasing a fix that was never
    running.
    """
    _commit(
        repo, "src/pkg/entry.py",
        "import pkg.used\n\n\ndef late():\n    import pkg.orphan\n    return pkg.orphan.x()\n",
        "entry imports orphan lazily", when=CHANGE_TIME
    )

    reachable = scan.reachable_modules( "src/pkg/entry.py" )

    assert "src/pkg/orphan.py" in reachable, (
        "a function-level import stopped counting as reachable — that is a real "
        "behaviour change toward false all-clears, not a cleanup"
    )


def test_stdlib_and_third_party_imports_are_not_walked( scan, repo ):
    """
    `entry.py` imports `os`. Resolving that outside the repo would send the walk
    into site-packages, where 29,303 vendored files live in this tree.
    """
    assert scan._module_to_path( "os" ) is None
    assert scan._module_to_path( "pkg.used" ) == "src/pkg/used.py"

    # And the `src.`-prefixed spelling is NOT ours either: `src` is already on the
    # path, so nothing imports `src.pkg.used`. Resolving it would invent a second
    # name for every module and let a changed file be counted twice.
    assert scan._module_to_path( "src.pkg.used" ) is None


# ---------------------------------------------------------------------------
# refusals — a vacuous scan must never print an all-clear
# ---------------------------------------------------------------------------

def test_zero_classified_processes_REFUSES_rather_than_reporting_clean( scan, repo, monkeypatch ):
    """
    VACUOUS DISCOVERY. Python processes are running on a lupin tree, but none
    matches a known long-lived class — so nothing was scanned. "0 stale" here is a
    confident answer to a question nobody asked.
    """
    _fleet( scan, monkeypatch, ( "4242", "python3 -m something_else", OLD_PROC ) )

    with pytest.raises( LookupError, match="ZERO matched a known long-lived class" ):
        scan.scan()


def test_a_fleet_of_only_young_processes_REFUSES_rather_than_reporting_clean( scan, repo, monkeypatch ):
    """
    A DIFFERENT vacuous route to the same silence, which is why it is its own case:
    the process IS classified, then filtered out by `min_age_seconds`. The loop
    that follows runs over nothing, and a loop over nothing satisfies every
    assertion inside it.
    """
    _fleet( scan, monkeypatch, ( "4242", "python3 -m synthetic_daemon", NOW - 5 ) )

    with pytest.raises( LookupError ):
        scan.scan( min_age_seconds=3600 )


def test_an_empty_process_list_REFUSES( scan, repo, monkeypatch ):
    """The degenerate case — `/proc` yielded nothing at all."""
    _fleet( scan, monkeypatch )

    with pytest.raises( LookupError ):
        scan.scan()


# ---------------------------------------------------------------------------
# the caller-facing contract
# ---------------------------------------------------------------------------

@pytest.mark.parametrize( "case, expected", [ ( "stale", 1 ), ( "clean", 0 ), ( "vacuous", 2 ) ] )
def test_exit_codes_are_three_distinct_answers( scan, repo, monkeypatch, case, expected ):
    """
    The three exit codes are a CONTRACT. A caller reading `rc == 0` as "nothing to
    do" must be right — so REFUSED (nothing scanned) can never share a code with a
    real all-clear. Local precedent: `purge-pycache.sh`, whose exit 2 covers three
    conditions and is routinely misread as a finding.
    """
    if case == "stale":
        _commit( repo, "src/pkg/deep.py", "def n():\n    return 99\n", "fix", when=CHANGE_TIME )
        _fleet( scan, monkeypatch, ( "4242", "python3 -m synthetic_daemon", OLD_PROC ) )
    elif case == "clean":
        _commit( repo, "src/pkg/orphan.py", "def x():\n    return 3\n", "orphan", when=CHANGE_TIME )
        _fleet( scan, monkeypatch, ( "4242", "python3 -m synthetic_daemon", OLD_PROC ) )
    else:
        _fleet( scan, monkeypatch, ( "4242", "python3 -m something_else", OLD_PROC ) )

    assert scan.main( [ "--min-age-seconds", "0" ] ) == expected


def test_the_scan_states_its_own_denominator_on_a_clean_run( scan, repo, monkeypatch, capsys ):
    """
    A guard that cannot state how much it looked at is telling you about its
    corpus, not about your fleet. The counts print on a CLEAN run too — that is
    the point, and it is what separates "scanned 19, found 0" from "scanned 0".
    """
    _commit( repo, "src/pkg/orphan.py", "def x():\n    return 3\n", "orphan", when=CHANGE_TIME )
    _fleet( scan, monkeypatch, ( "4242", "python3 -m synthetic_daemon", OLD_PROC ) )

    assert scan.main( [ "--min-age-seconds", "0" ] ) == 0

    out = capsys.readouterr().out
    for field in ( "python processes on a lupin tree", "classified as long-lived", "STALE" ):
        assert field in out, f"clean run did not state {field!r}: {out}"


def test_the_refusal_says_nothing_was_scanned_rather_than_printing_counts( scan, repo, monkeypatch, capsys ):
    """
    The refusal's WORDING is load-bearing. A reader who sees a count assumes a scan
    happened; the exit-2 path must say plainly that it did not, or exit 2 becomes
    another silent clean run.
    """
    _fleet( scan, monkeypatch, ( "4242", "python3 -m something_else", OLD_PROC ) )

    assert scan.main( [ "--min-age-seconds", "0" ] ) == 2

    err = capsys.readouterr().err
    assert "REFUSED" in err
    assert "Do not read this as a clean run" in err


# ---------------------------------------------------------------------------
# the container label — found UNGUARDED by a second harness, not by re-reading
# ---------------------------------------------------------------------------
#
# Tiberius 👑 independently guarded this same file on 2026-09-05 and posed an arm
# my five did not: label an UNRESOLVED container as if it had resolved. It SURVIVED
# against this file — 14 passed, nothing red — because every fixture above stands
# `_container_of` and `_safe_cgroup` down to avoid shelling out to docker. The
# whole labelling path was therefore untested, including the one hazard the scan's
# own docstring singles out.
#
# That is the argument for a second harness stated as a receipt rather than a
# principle: two harnesses aimed at one file find different things, and no amount
# of re-reading my own assertions would have surfaced this.


@pytest.fixture
def scan_with_real_labelling( repo, monkeypatch ):
    """
    The scan with its container-labelling path LIVE, and only docker stood down.

    Unlike the `scan` fixture, `_container_of` and `_safe_cgroup` are left in place
    so `classify` actually executes its labelling branches; the docker lookup is
    replaced per-test instead.
    """
    module = _load_scan()
    monkeypatch.setattr( module, "REPO_ROOT", repo )
    monkeypatch.setattr( module, "KNOWN_CLASSES",
                         [ ( "synthetic_daemon", "synthetic daemon", "src/pkg/entry.py" ) ] )
    return module


def test_an_unresolved_container_is_labelled_unknown_rather_than_guessed( scan_with_real_labelling, monkeypatch ):
    """
    🔴 THE CASE THE SECOND HARNESS FOUND. A containerised process whose container
    name does NOT resolve must be labelled `container?` — never given a venue.

    The scan's own docstring says why, and it is the sharper half of the point: a
    WRONG LABEL ON A CORRECT FINDING IS WORSE THAN A WRONG FINDING. The reader
    goes and bounces the server the label names, that server comes back clean, and
    the clean result READS AS CONFIRMATION that the report was noise. Two
    containers here run the byte-identical `python3 -m lupin_app.main`, so this is
    the live case and not a hypothetical.
    """
    module = scan_with_real_labelling
    monkeypatch.setattr( module, "_container_of", lambda pid: None )      # did not resolve
    monkeypatch.setattr( module, "_safe_cgroup",  lambda pid: "0::/docker-abc123.scope" )

    label, entry = module.classify( {
        "pid": "4242", "cmdline": "python3 -m synthetic_daemon", "started": OLD_PROC
    } )

    assert label == "synthetic daemon [container?]", (
        f"an unresolved container was given a concrete venue label: {label!r} — a "
        "reader following it bounces the wrong server, gets a clean result, and "
        "reads that as the report being noise"
    )
    assert entry == "src/pkg/entry.py"


def test_a_resolved_container_carries_its_mapped_venue( scan_with_real_labelling, monkeypatch ):
    """
    POSITIVE CONTROL for the case above, and not optional: without it, a scan that
    labelled EVERYTHING `container?` would pass that assertion perfectly while
    telling the reader nothing at all.
    """
    module = scan_with_real_labelling
    monkeypatch.setattr( module, "_container_of", lambda pid: "lupin-rest-test" )

    label, _entry = module.classify( {
        "pid": "4242", "cmdline": "python3 -m synthetic_daemon", "started": OLD_PROC
    } )

    assert label == "synthetic daemon [:8000 test]", f"resolved container lost its venue: {label!r}"


def test_a_process_outside_any_container_gets_no_container_suffix( scan_with_real_labelling, monkeypatch ):
    """
    The third state, which the two cases above cannot distinguish between them:
    NOT containerised at all is neither "resolved" nor "unresolved", and must not
    acquire a `container?` marker it has no business carrying.
    """
    module = scan_with_real_labelling
    monkeypatch.setattr( module, "_container_of", lambda pid: None )
    monkeypatch.setattr( module, "_safe_cgroup",  lambda pid: "0::/user.slice/session-3.scope" )

    label, _entry = module.classify( {
        "pid": "4242", "cmdline": "python3 -m synthetic_daemon", "started": OLD_PROC
    } )

    assert label == "synthetic daemon", f"a host process was marked as containerised: {label!r}"
