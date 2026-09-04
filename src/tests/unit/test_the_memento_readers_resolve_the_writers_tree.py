"""
The memento READERS must resolve the same tree the WRITER writes to (row aba30387
family, measured 2026-09-04 by john 🏄🏽).

🔴 WHAT THIS GUARDS, AND WHY PROSE COULD NOT. `memento_slot.resolve_repo_root`'s
docstring opened with "resolved the way memento_io resolves it" — a claim of parity
that was FALSE for six weeks. The writer moved off `--show-toplevel` on 2026-07-21
(memento_io row af0c5700); the readers never did. Nobody compared the two, because
the sentence said there was nothing to compare.

⇒ A DOCSTRING CANNOT HOLD A PARITY CLAIM ACROSS A REPOSITORY BOUNDARY. The writer
lives in planning-is-prompting and is not importable from here, so the parity is a
claim this repo has to KEEP rather than one it can inherit. That is this file's job.

WHAT WOULD BREAK WITHOUT IT: all three readers go green on their own unit tests
while resolving a tree holding none of the seat's records — 623 in the main checkout,
0 in the worktree at the time of measurement. The failure surfaces as
`timeout_no_memento`, `SEED_NOT_CONSUMED` and `STALE_MEMENTO`, none of which names a
path, so it reads as a missing memento rather than a reader looking in the wrong tree.

⚠️ EVERY CASE HERE DRIVES REAL `git` AGAINST REAL FIXTURES. The bug is entirely in
what git answers for a linked worktree, so a fake `run_fn` returning canned strings
would agree with whatever the implementation asked it — the fixture would be the
thing under test. `_git` is the only seam and it is the real binary.
"""

import os
import shutil
import subprocess

import pytest

from lupin_cli.claude_code.hooks.register_session import _resolve_repo_root
from lupin_mcp.memento_repo_root                 import repo_root_owning
from lupin_mcp.memento_slot                      import resolve_repo_root
from lupin_mcp.reap_memento                      import seat_repo_root


pytestmark = pytest.mark.skipif( shutil.which( "git" ) is None,
                                 reason="these cases drive the real git binary" )


def _git( *args, cwd ):
    """Ensures: runs git in `cwd`, raising with git's own stderr on failure."""
    proc = subprocess.run( [ "git", *args ], cwd=str( cwd ),
                           capture_output=True, text=True )
    if proc.returncode != 0:
        raise AssertionError( f"git {' '.join( args )} failed in {cwd}: {proc.stderr.strip()}" )
    return proc.stdout.strip()


def _init_repo( path ):
    """Ensures: `path` is a git repo with one commit (a worktree needs a commit)."""
    os.makedirs( path, exist_ok=True )
    _git( "init", "-q", cwd=path )
    _git( "-c", "user.email=t@t", "-c", "user.name=t",
          "commit", "-q", "--allow-empty", "-m", "init", cwd=path )
    return path


@pytest.fixture
def trees( tmp_path ):
    """
    The four shapes the discriminator has to tell apart, built for real.

    Ensures: a dict of { main, subdir, nested, worktree } absolute path strings,
             where `worktree` is a genuine `git worktree add` of `main` and `nested`
             is an independent repo living INSIDE main's tree.
    """
    main = _init_repo( tmp_path / "main" )

    subdir = main / "src" / "deep"
    os.makedirs( subdir )

    nested = _init_repo( main / "vendor" / "nested" )

    worktree = tmp_path / "main-wt"
    _git( "worktree", "add", "-q", str( worktree ), "-b", "wt-branch", cwd=main )

    return { "main"     : str( main ),     "subdir"   : str( subdir ),
             "nested"   : str( nested ),   "worktree" : str( worktree ) }


@pytest.fixture
def submodule( tmp_path ):
    """
    A TRUE submodule — the only shape that can catch an unconditional collapse.

    🔴 THIS FIXTURE EXISTS BECAUSE A MUTATION SURVIVED. Replacing the whole
    discriminator with a bare `return common_dir.parent` was posed against the four
    shapes above and ALL TEN CASES STAYED GREEN — because for a plain repo, a
    subdirectory and a nested repo, `parent( common_dir )` ALREADY EQUALS
    `--show-toplevel`. Measured: three SAME, one DIFFER. The mutation was a no-op on
    that corpus, so the green said nothing about the code and everything about the
    fixtures.

    A submodule is where the two part company, and it parts the DANGEROUS way:

        toplevel        <parent>/sub
        git-common-dir  <parent>/.git/modules/sub
        parent(common)  <parent>/.git/modules      <- not a working tree AT ALL

    ⚠️ The module docstring ASSERTED this carve-out before anything proved it. That
    is the same defect as the parity docstring this whole file exists to replace — a
    claim standing in for a check — so it is now a fixture rather than a sentence.

    Ensures: the submodule's working-tree path as a str, or a skip when this git
             refuses a file-protocol submodule (a security default on some builds).
    """
    upstream = _init_repo( tmp_path / "upstream" )
    parent   = _init_repo( tmp_path / "parent" )

    proc = subprocess.run(
        [ "git", "-c", "protocol.file.allow=always",
          "-c", "user.email=t@t", "-c", "user.name=t",
          "submodule", "add", "-q", str( upstream ), "sub" ],
        cwd=str( parent ), capture_output=True, text=True
    )
    if proc.returncode != 0:
        pytest.skip( f"this git refuses a file-protocol submodule: {proc.stderr.strip()}" )

    return str( parent / "sub" )


def test_a_submodule_resolves_to_its_own_root_not_into_the_parents_git_dir( submodule ):
    """
    The case that kills an unconditional collapse.

    Without this the discriminator could be deleted entirely and every other test
    here would still pass — proven by mutation, not supposed.
    """
    got = repo_root_owning( submodule )

    assert str( got ) == os.path.realpath( submodule ), (
        "a submodule owns its own records; collapsing it lands in the PARENT's "
        f"internal .git/modules directory, which is not a working tree (got {got})"
    )
    assert ".git" not in str( got ).split( os.sep ), \
        "resolved a root INSIDE a .git directory — that is never a working tree"


def test_the_submodule_answer_matches_the_writer( submodule ):
    """Parity on the carve-out too, against the independently-stated writer rule."""
    assert str( repo_root_owning( submodule ) ) == _writers_answer( submodule )


def _writers_answer( start ):
    """
    The WRITER's algorithm, transcribed from `memento_io.find_repo_root`.

    ⚠️ DELIBERATELY A SECOND IMPLEMENTATION, NOT AN IMPORT OF THE ONE UNDER TEST.
    A comparison whose two sides come from one source cannot disagree. The writer is
    in another repository and cannot be imported, so the only way to check parity is
    to state its rule independently here and let the two derivations meet at the
    assertion. If this ever imports `repo_root_owning`, every case below becomes a
    tautology that passes whatever either side does.
    """
    toplevel = os.path.realpath( _git( "rev-parse", "--show-toplevel", cwd=start ) )

    def resolved( flag ):
        answer = _git( "rev-parse", flag, cwd=start )
        path   = answer if os.path.isabs( answer ) else os.path.join( start, answer )
        return os.path.realpath( path )

    if resolved( "--git-dir" ) == resolved( "--git-common-dir" ):
        return toplevel                                   # plain / subdir / nested
    return os.path.dirname( resolved( "--git-common-dir" ) )   # worktree -> MAIN


# ── The parity claim the docstring used to make ───────────────────────────────
@pytest.mark.parametrize( "shape", [ "main", "subdir", "nested", "worktree" ] )
def test_the_helper_answers_what_the_writer_answers( trees, shape ):
    """
    The claim `resolve_repo_root`'s docstring asserted and did not keep.

    The `worktree` case is the one that was wrong; the other three are the negative
    controls that make it meaningful. Without them a helper that returned the main
    checkout for EVERYTHING would pass — and would silently hoist a nested repo's
    records into its parent, which is a different bug wearing this fix's name.
    """
    start = trees[ shape ]
    assert str( repo_root_owning( start ) ) == _writers_answer( start )


def test_a_worktree_resolves_to_the_main_checkout_and_a_nested_repo_does_not( trees ):
    """
    The discriminator discriminates — stated as two directions in one test so a
    change that collapses EVERYTHING cannot pass by satisfying only the first.
    """
    assert str( repo_root_owning( trees[ "worktree" ] ) ) == trees[ "main" ], \
        "a linked worktree must resolve to the MAIN checkout — the tree the writer writes to"
    assert str( repo_root_owning( trees[ "nested" ] ) ) == trees[ "nested" ], \
        "a NESTED repo owns its own records and must NOT be hoisted to its parent"


# ── All three readers, not just the helper ────────────────────────────────────
def test_every_reader_resolves_the_worktree_to_the_main_checkout( trees ):
    """
    🔴 THE POPULATION IS THE POINT. Three readers reached the wrong tree by three
    DIFFERENT mechanisms, so fixing the one you happen to be looking at leaves the
    other two wrong and every unit test green:

        memento_slot.resolve_repo_root       `git rev-parse --show-toplevel`
        reap_memento.seat_repo_root          the bridge `cwd`, verbatim
        register_session._resolve_repo_root  nearest `.git` ANCESTOR — and a
                                             worktree's `.git` is a FILE, so
                                             `os.path.exists` stops there
    """
    wt, main = trees[ "worktree" ], trees[ "main" ]

    readers = {
        "memento_slot.resolve_repo_root"      : resolve_repo_root( start=wt ),
        "reap_memento.seat_repo_root"         : seat_repo_root( { "cwd": wt } ),
        "register_session._resolve_repo_root" : _resolve_repo_root( wt ),
    }
    wrong = { name: got for name, got in readers.items() if got != main }
    assert not wrong, (
        f"these readers resolved a tree the memento writer never writes to: {wrong} "
        f"(expected {main})"
    )


def test_every_reader_leaves_a_nested_repo_alone( trees ):
    """The same three, in the direction that proves they are not collapsing blindly."""
    nested = trees[ "nested" ]

    readers = {
        "memento_slot.resolve_repo_root"      : resolve_repo_root( start=nested ),
        "reap_memento.seat_repo_root"         : seat_repo_root( { "cwd": nested } ),
        "register_session._resolve_repo_root" : _resolve_repo_root( nested ),
    }
    wrong = { name: got for name, got in readers.items() if got != nested }
    assert not wrong, (
        f"these readers hoisted a nested repo's records into its parent: {wrong} "
        f"(expected {nested})"
    )


# ── Degradation: a reader must not get WORSE than it was ──────────────────────
def test_the_reap_degrades_to_the_cwd_when_git_cannot_answer( tmp_path ):
    """
    A git failure must not turn a reap into a refusal. Before the collapse existed
    this returned the cwd unchanged; an unresolvable cwd must still do that, or a
    box without git stops reaping instead of reaping the old way.
    """
    plain = str( tmp_path / "not-a-repo" )
    os.makedirs( plain )
    assert seat_repo_root( { "cwd": plain } ) == plain


def test_the_reap_still_refuses_when_the_seat_reports_no_cwd():
    """
    The pre-existing contract, re-asserted because the collapse rewrote this
    function: no cwd is still None, so the caller refuses rather than guessing a
    root. A guessed root does not fail to find a memento — it finds a different
    seat's and reports on that.
    """
    assert seat_repo_root( { "cwd": "" } ) is None
    assert seat_repo_root( {} )            is None
    assert seat_repo_root( None )          is None


def test_the_hook_falls_back_rather_than_raising_when_the_helper_explodes( monkeypatch, tmp_path ):
    """
    SessionStart must survive a broken resolver. The hook runs fleet-wide, including
    where `lupin_mcp` is not importable, and a hook that raises takes the whole
    session start down — a worse outcome than a wrong root.
    """
    monkeypatch.setenv( "LUPIN_ROOT", str( tmp_path / "fallback" ) )

    def boom( start ):
        raise RuntimeError( "resolver unavailable" )

    assert _resolve_repo_root( str( tmp_path ), repo_root_fn=boom ) == str( tmp_path / "fallback" )


# ── Degradation inside the helper itself (100% coverage mandate) ──────────────
# Every branch below is REACHABLE, so each gets a real test rather than a pragma.
# The subprocess seam `_default_run` keeps its pragma — it is the one line that
# cannot be exercised without spawning git, and it is exercised by every case above.
def test_a_start_of_none_is_refused_rather_than_resolved_from_the_cwd():
    """
    `None` must not silently become "wherever this process happens to be standing".
    That is the ambient-root defect this whole module exists to end, and it would
    reappear the moment a caller passed a missing cwd through.
    """
    assert repo_root_owning( None ) is None


def test_an_unresolvable_toplevel_refuses():
    """No `--show-toplevel` means not in a working tree — refuse, never guess."""
    assert repo_root_owning( "/anywhere", run_fn=lambda argv, cwd: None ) is None


def test_a_path_that_cannot_be_resolved_refuses( monkeypatch ):
    """
    `Path.resolve()` can raise on a pathological path. The helper must return None
    rather than propagate — its contract says it never raises, and a reap that dies
    on a bad path is worse than one that declines to answer.
    """
    import lupin_mcp.memento_repo_root as mrr

    def exploding_resolve( self, *a, **k ):
        raise OSError( "cannot resolve" )

    monkeypatch.setattr( mrr.Path, "resolve", exploding_resolve )
    assert repo_root_owning( "/repo", run_fn=lambda argv, cwd: "/repo\n" ) is None


def test_it_degrades_to_the_toplevel_when_the_discriminator_cannot_be_read():
    """
    🔴 THE DEGRADATION THAT MUST NOT BECOME A COLLAPSE. When `--git-dir` or
    `--git-common-dir` cannot be read, the helper returns `--show-toplevel` —
    TODAY'S answer — rather than guessing a parent. Returning `common_dir.parent`
    on a half-read would invent a root from an answer git never gave.
    """
    def run( argv, cwd ):
        flag = argv[ -1 ]
        if flag == "--show-toplevel":  return "/repo\n"
        return None                     # both discriminator reads fail

    assert str( repo_root_owning( "/repo", run_fn=run ) ) == "/repo"


# ── Every degraded path ANNOUNCES itself (Rio ⚡'s review finding, 2026-09-04) ──
# 🔴 WHY THESE EXIST. The fallbacks were SILENT. That is this repo's WEAKENED-CHECK
# species — it passes, having done less, and nobody investigates. Here it is worse
# than usual: the fallback resolves the WRONG TREE, so the defect this module closes
# would come back reported as a normal boot. Each case below asserts the warning
# NAMES THE TREE IT SETTLED FOR, because "it warned" and "it told you what it did"
# are different, and only the second is actionable.
def test_the_helper_announces_when_it_cannot_read_the_discriminator():
    """The dangerous degradation: in a worktree, today's answer IS the bug."""
    said = []
    def run( argv, cwd ):
        return "/repo\n" if argv[ -1 ] == "--show-toplevel" else None

    got = repo_root_owning( "/repo", run_fn=run, warn_fn=said.append )

    assert str( got ) == "/repo"
    assert len( said ) == 1, f"expected exactly one warning, got {said}"
    assert "/repo" in said[ 0 ], "the warning must NAME the tree it settled for"
    assert "WARNING" in said[ 0 ]


def test_the_helper_announces_when_it_refuses_an_unresolvable_tree():
    said = []
    assert repo_root_owning( "/nowhere", run_fn=lambda a, c: None, warn_fn=said.append ) is None
    assert len( said ) == 1 and "/nowhere" in said[ 0 ]


def test_the_helper_announces_a_none_start():
    said = []
    assert repo_root_owning( None, warn_fn=said.append ) is None
    assert len( said ) == 1 and "WARNING" in said[ 0 ]


def test_a_clean_resolution_says_NOTHING( trees ):
    """
    🔴 THE NEGATIVE CONTROL, AND IT CARRIES THE WHOLE VALUE OF THE THREE ABOVE.
    A resolver that warned on EVERY call would satisfy all of them and tell a reader
    nothing — noise is how a real warning stops being read. Every non-degraded shape
    must be silent, so a warning in a log MEANS something went wrong.
    """
    for shape in ( "main", "subdir", "nested", "worktree" ):
        said = []
        repo_root_owning( trees[ shape ], warn_fn=said.append )
        assert said == [], f"{shape} resolved cleanly but warned: {said}"


def test_the_reap_announces_when_resolution_raises():
    """
    A reap that settles for a worktree cwd is about to verify a slot the writer never
    writes to — and alarm `timeout_no_memento` against a memento that is on disk.
    """
    said = []
    def boom( start ):
        raise RuntimeError( "resolver contract broken" )

    got = seat_repo_root( { "cwd": "/some/worktree" }, repo_root_fn=boom, warn_fn=said.append )

    assert got == "/some/worktree"
    assert len( said ) == 1
    assert "/some/worktree" in said[ 0 ], "the warning must NAME the tree it settled for"


def test_the_hook_announces_when_it_falls_back_to_the_walk( tmp_path, capsys ):
    """
    The walk is WRONG IN A WORKTREE by the hook's own docstring, so reaching it IS
    the defect returning. It must not look like a normal boot.
    """
    repo = tmp_path / "repo"
    os.makedirs( repo / ".git" )

    got = _resolve_repo_root( str( repo ), repo_root_fn=lambda start: None )

    assert got == str( repo )
    err = capsys.readouterr().err
    assert "WARNING" in err and str( repo ) in err, f"walk fallback was silent: {err!r}"


def test_the_hook_announces_when_it_settles_for_the_ambient_root( tmp_path, monkeypatch, capsys ):
    """LUPIN_ROOT describes the HOST, not this seat — the loudest degradation of all."""
    monkeypatch.setenv( "LUPIN_ROOT", "/fallback/root" )
    bare = tmp_path / "no-git-anywhere"
    os.makedirs( bare )

    got = _resolve_repo_root( str( bare ), repo_root_fn=lambda start: None )

    assert got == "/fallback/root"
    err = capsys.readouterr().err
    assert "/fallback/root" in err and "WARNING" in err


def test_the_hook_says_NOTHING_when_git_resolves_it( tmp_path, capsys ):
    """Negative control for the hook — same reason as the helper's."""
    got = _resolve_repo_root( str( tmp_path ), repo_root_fn=lambda start: "/resolved/root" )

    assert got == "/resolved/root"
    assert capsys.readouterr().err == "", "a clean resolution must be silent"
