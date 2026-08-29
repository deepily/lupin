"""
Fleet data root — rows 8758d0b1 / f56fc63b.

WHY RUNTIME STATE LEFT THE REPO
-------------------------------
`.dm-inbox-hwm-*`, `.heartbeat-hold-*`, `.heartbeat-acked-*`, `.task-store-map-*`
lived in the repo root, gitignored. **Gitignored is the kill list, not the shield**:
`git clean -xdf` deletes ignored files — that is what `-x` means. Measured
2026-07-26, a dry run listed **448 runtime files as "would remove"**, including
three cargo-bearing holds carrying hand-written successor notes.

They now live at `<DEEPILY_DATA_DIR>/<repo>/`, outside every repo, where no git
command reaches them.

THE TWO PREDICATES, AND WHY THEY MUST NOT BE UNIFIED
----------------------------------------------------
| question | predicate |
|---|---|
| which TREES does the janitor sweep? | **realpath** — each tree holds its own files |
| which dir does a session WRITE to?  | **repo identity** — that IS fleet-global |

Rick's 2026-07-16 ruling (`fleet_arbiter_loop.py:336-342`) refuted `--git-common-dir`
for the FIRST question: deduping sweep roots on repo identity would silently drop a
worktree root, and a hold lives in `cheech-orphan-bridge` today. That ruling stands.
Fleet-global answers the SECOND question. Rick confirmed both hold, 2026-07-26.

⚠️ A future reader will see two path predicates and want to unify them. These tests
exist so that attempt goes red.

Venue: :7999-eligible. tmp_path + env injection; no docker, no network.
"""
import os
import subprocess
from pathlib import Path

import pytest

from lupin_cli.claude_code.hooks.lib.heartbeat_hold import (
    fleet_data_root, _main_repo_path, _repo_identity, _resolve_base_dir,
    DATA_DIR_ENV, DATA_DIR_FALLBACK,
)


def _git( *args, cwd ):
    return subprocess.run( [ "git", *args ], cwd=str( cwd ), capture_output=True, text=True, timeout=30 )


@pytest.fixture
def repo_with_worktree( tmp_path ):
    """
    A real git repo with a real linked worktree.

    Ensures:
        - returns ( main_repo_path, worktree_path ), both real on disk
        - uses actual `git worktree add` rather than a mocked shape: the whole
          mechanism under test is what git reports for a worktree, and a fake would
          test the fake
    """
    main = tmp_path / "projects" / "lupin"
    main.mkdir( parents=True )
    _git( "init", "-q", cwd=main )
    _git( "config", "user.email", "t@t.t", cwd=main )
    _git( "config", "user.name", "t", cwd=main )
    ( main / "f.txt" ).write_text( "x" )
    _git( "add", "-A", cwd=main )
    _git( "commit", "-qm", "init", cwd=main )

    wt = main / ".claude" / "worktrees" / "wt-one"
    r  = _git( "worktree", "add", "-q", "--detach", str( wt ), cwd=main )
    assert wt.is_dir(), f"worktree fixture failed: {r.stderr}"
    return main, wt


# ── the env var is the authority ──────────────────────────────────────────

def test_the_env_var_is_honored( tmp_path, monkeypatch ):
    monkeypatch.setenv( DATA_DIR_ENV, str( tmp_path / "elsewhere" ) )
    assert fleet_data_root( tmp_path / "projects" / "lupin" ) == tmp_path / "elsewhere" / "lupin"


def test_unset_falls_back_BESIDE_the_projects_tree_not_into_the_repo( tmp_path, monkeypatch ):
    """
    ⚠️ The fallback must NOT degrade to the repo root — that would recreate exactly
    the clutter this removes, and it would do it only in long-lived sessions whose
    environment predates the variable, which is where nobody is watching.

    It resolves the SAME place the env var names, derived rather than read.
    """
    monkeypatch.delenv( DATA_DIR_ENV, raising=False )
    repo = tmp_path / "projects" / "lupin"
    repo.mkdir( parents=True )
    root = fleet_data_root( repo )

    assert root == tmp_path / DATA_DIR_FALLBACK / "lupin"
    assert DATA_DIR_FALLBACK in str( root )
    assert not str( root ).startswith( str( repo ) ), "the fallback landed INSIDE the repo"


# ── fleet-global: every tree of a repo shares one dir ─────────────────────

def test_a_worktree_and_its_main_repo_resolve_to_the_SAME_data_dir( repo_with_worktree, monkeypatch ):
    """
    THE FLEET-GLOBAL PROPERTY. Per-tree data dirs are the defect: a worktree session
    would read its own private bookmark and re-surface DMs the main checkout already
    consumed.
    """
    main, wt = repo_with_worktree
    monkeypatch.setenv( DATA_DIR_ENV, "/data" )
    assert fleet_data_root( wt ) == fleet_data_root( main )


def test_the_shared_dir_is_keyed_on_the_MAIN_repo_name_not_the_worktree_name( repo_with_worktree, monkeypatch ):
    """
    The discriminator for the test above. Both could agree while being wrong — e.g.
    if both resolved to the worktree's own name. This pins WHICH name wins.
    """
    main, wt = repo_with_worktree
    monkeypatch.setenv( DATA_DIR_ENV, "/data" )
    assert fleet_data_root( wt ).name == "lupin"
    assert _repo_identity( wt ) == "lupin"
    assert wt.name == "wt-one", "fixture drifted — the names must differ for this to discriminate"


def test_MUTATION_keying_on_the_TREE_would_split_the_data_dir( repo_with_worktree ):
    """
    Proves the property above is DERIVED, not accidental. The tempting simplification
    — use the directory's own basename — is applied here and must produce two
    different dirs, which is the bug.
    """
    main, wt = repo_with_worktree
    assert main.name != wt.name
    assert _main_repo_path( wt ) == _main_repo_path( main ), "git did not resolve the worktree to its main repo"


def test_the_fallback_base_is_derived_from_the_MAIN_repo_not_the_worktree( repo_with_worktree, monkeypatch ):
    """
    ⚠️ REGRESSION PIN. The first version derived the fallback from the PASSED tree,
    so a worktree yielded `.claude/projects-data/lupin` — inside the repo, and a
    different location from the main checkout's. Measured, then fixed.
    """
    main, wt = repo_with_worktree
    monkeypatch.delenv( DATA_DIR_ENV, raising=False )
    assert fleet_data_root( wt ) == fleet_data_root( main )
    assert ".claude" not in str( fleet_data_root( wt ) )


# ── the janitor must actually be pointed at it ────────────────────────────

def test_the_sweep_roots_CONTAIN_the_data_root( tmp_path ):
    """
    THE STEP WHOSE FAILURE IS SILENT. Every other source of `_compute_hold_roots`
    yields a REPO — the parent scan appends only dirs containing `.git` — so the
    data root is invisible to it by construction.

    Omit this and `roots_swept` stays non-empty (the repos still exist), the no-roots
    alarm never fires, and the report reads `roots N · files 0 · prunable 0` —
    indistinguishable from a clean fleet while BOTH janitors quietly stop reclaiming.
    """
    from lupin_arbiter_app.fleet_arbiter_loop import _compute_hold_roots

    class Cfg:
        def get( self, key, default=None, **kw ): return default

    host  = tmp_path / "projects" / "lupin"
    host.mkdir( parents=True )
    roots = _compute_hold_roots( Cfg(), str( host ), scan_fn=lambda: [ ] )
    assert str( fleet_data_root( host ) ) in roots


def test_adding_a_worktree_does_NOT_add_a_SECOND_data_root( repo_with_worktree, monkeypatch ):
    """
    If it does, fleet-global did not land — and the symptom is per-tree bookmarks
    again, with everything still reporting green.
    """
    from lupin_arbiter_app.fleet_arbiter_loop import _compute_hold_roots

    class Cfg:
        def get( self, key, default=None, **kw ): return default

    main, wt = repo_with_worktree
    monkeypatch.setenv( DATA_DIR_ENV, str( main.parent.parent / "data" ) )

    roots     = _compute_hold_roots( Cfg(), str( main ), scan_fn=lambda: [ str( main ), str( wt ) ] )
    data_root = str( fleet_data_root( main ) )
    assert roots.count( data_root ) == 1, f"data root appears {roots.count( data_root )} times: {roots}"
    assert str( wt ) in roots, "the worktree stopped being SWEPT — sweep roots are realpath-keyed, unchanged"


# ── the prefix trap ───────────────────────────────────────────────────────

def test_projects_data_is_NOT_inside_projects():
    """
    `projects-data` IS a string-prefix of `projects`, and the naive check returns
    True — failing TOWARD "inside", which is the quiet direction. Both real call
    sites guard with a separator; this pins all three shapes so a future one cannot
    quietly get it wrong.
    """
    root = "/mnt/DATA01/include/www.deepily.ai/projects"
    cand = "/mnt/DATA01/include/www.deepily.ai/projects-data"

    assert cand.startswith( root ) is True                      # the trap, stated out loud
    assert cand.startswith( root + os.sep ) is False            # the guarded form
    assert cand != root                                         # and the exact-equality arm
    assert os.path.commonpath( [ root, cand ] ) == "/mnt/DATA01/include/www.deepily.ai"


# ── resolver wiring ───────────────────────────────────────────────────────

def test_resolve_base_dir_none_gives_the_data_root_and_creates_it( tmp_path, monkeypatch ):
    """A missing dir would surface to every caller as "no files" — the silent-empty
    reading this whole family keeps getting bitten by."""
    import cosa.utils.util as cu
    repo = tmp_path / "projects" / "lupin"
    repo.mkdir( parents=True )
    monkeypatch.setattr( cu, "get_project_root", lambda: str( repo ) )
    monkeypatch.setenv( DATA_DIR_ENV, str( tmp_path / "data" ) )

    resolved = _resolve_base_dir( None )
    assert resolved == tmp_path / "data" / "lupin"
    assert resolved.is_dir(), "the resolver did not create the data root"


def test_an_explicit_base_dir_still_wins( tmp_path ):
    """Tests and explicit callers must keep their override, or every suite in this
    family would start writing to the real fleet data root."""
    assert _resolve_base_dir( tmp_path ) == tmp_path


# ── row 1facc18e: THE DEPTH ASSUMPTION, AND THE PROPERTY THAT OUTLIVES IT ──
#
# The old fallback base was `main.parent.parent / projects-data` — a fixed DEPTH.
# It is right only for a repo sitting exactly one level under `projects/`, and two
# other depths were sitting on disk when this was written:
#
#   projects/lupin/src/lupin-mobile      -> projects/lupin/projects-data/...  (INSIDE a tree)
#   projects/google/weil-parallel-search -> projects/projects-data/...        (not the fleet dir)
#
# Both had a real specimen. The first is the one row 011f1f90 warns about — a file
# where the arbiter and the Stop hook do not look. The second passes the
# "not inside a tree" check while still being unread, which is why there are TWO
# properties below and not one.
#
# ⚠️ These are PROPERTIES over generated shapes, not assertions about the two paths
# we happened to find. Two hardcoded paths go stale the day somebody adds a third
# nested repo — that is exactly how this defect survived.

from lupin_cli.claude_code.hooks.lib.heartbeat_hold import (
    _fleet_data_base, _enclosing_tree_root, PROJECTS_DIR_NAME,
)


# The shapes are RELATIVE to a generated `projects/` dir, so the test says what a
# layout IS rather than where it happens to live today. `nested_in` names the repo
# whose working tree encloses this one.
REPO_SHAPES = [
    ( "flat",              "lupin",                              None ),
    ( "grouped",           "google/weil-parallel-search",        None ),
    ( "grouped_deeper",    "acme/team/some-service",             None ),
    ( "nested_1",          "lupin/src/lupin-mobile",             "lupin" ),
    ( "nested_2",          "lupin/src/lupin-plugin-firefox",     "lupin" ),
    ( "nested_deep",       "lupin/src/vendor/a/b/deep-repo",     "lupin" ),
    ( "nested_in_grouped", "acme/team/some-service/sub/inner",   "acme/team/some-service" ),
]


def _independent_enclosing_tree( path ):
    """
    Is this path inside a git working tree? Written HERE, deliberately, instead of
    calling the production `_enclosing_tree_root`.

    A guard that asks the code under test whether the code under test is correct
    agrees with itself for free. This walks the ancestor chain for a `.git` entry
    with nothing imported from the module it is judging.
    """
    here = Path( os.path.realpath( path ) )
    for candidate in [ here, *here.parents ]:
        if ( candidate / ".git" ).exists():
            return candidate
    return None


@pytest.fixture
def fleet_layout( tmp_path, monkeypatch ):
    """
    A generated `projects/` tree carrying every shape in REPO_SHAPES as a REAL repo.

    Ensures:
        - returns ( projects_dir, { name: repo_path } )
        - each repo is a real git tree (a `.git` dir), so the enclosing-tree walk
          is answering about the filesystem and not about a fixture's opinion
        - DEEPILY_DATA_DIR is UNSET — the env var short-circuits the whole
          derivation, so leaving it set would test nothing
    """
    monkeypatch.delenv( DATA_DIR_ENV, raising=False )
    projects = tmp_path / PROJECTS_DIR_NAME
    repos    = { }
    for name, rel, _ in REPO_SHAPES:
        repo = projects / rel
        repo.mkdir( parents=True )
        ( repo / ".git" ).mkdir()
        repos[ name ] = repo
    return projects, repos


@pytest.mark.parametrize( "name", [ s[ 0 ] for s in REPO_SHAPES ] )
def test_PROPERTY_no_data_root_ever_resolves_inside_a_git_working_tree( fleet_layout, name ):
    """
    THE PROPERTY, row 1facc18e. A data root inside a working tree is invisible to
    the arbiter and the Stop hook — `respin_wake_check.py`'s own header says so for
    the repo root, and this lands one directory below it.

    Stated over generated shapes at four different depths so a THIRD nested repo
    added next month is covered without anybody editing this file.
    """
    _, repos = fleet_layout
    root     = fleet_data_root( repos[ name ] )
    tree     = _independent_enclosing_tree( root )
    assert tree is None, f"{name}: data root {root} sits inside the working tree {tree}"


@pytest.mark.parametrize( "name,rel,nested_in", REPO_SHAPES )
def test_the_fixture_actually_BUILT_an_enclosing_tree( fleet_layout, name, rel, nested_in ):
    """
    The discriminator for the property above. If the fixture silently stopped
    creating `.git`, every shape would be "not inside a tree" and the property would
    pass vacuously — green because the hazard was never constructed.
    """
    projects, repos = fleet_layout
    enclosing = _independent_enclosing_tree( repos[ name ].parent )
    if nested_in is None:
        assert enclosing is None, f"{name} was supposed to sit outside every tree"
    else:
        assert enclosing == projects / nested_in, f"{name} was supposed to sit inside {nested_in}"


def test_PROPERTY_every_repo_in_the_fleet_shares_ONE_base_directory( fleet_layout ):
    """
    THE SECOND PROPERTY, and the one the "not inside a tree" check alone would miss.

    `projects/google/weil-parallel-search` produced `projects/projects-data/...` —
    outside every working tree, so property one is satisfied, and still not the
    directory any reader looks in. A real receipt for the maría seat was sitting
    there. Fleet-global means ONE base for every repo, at every depth.
    """
    projects, repos = fleet_layout
    bases = { name: fleet_data_root( repo ).parent for name, repo in repos.items() }
    assert len( set( bases.values() ) ) == 1, f"the fleet split into several data dirs: {bases}"
    assert set( bases.values() ) == { projects.parent / DATA_DIR_FALLBACK }


def test_each_repo_still_keeps_its_OWN_dir_under_that_base( fleet_layout ):
    """
    The counterweight. Collapsing every repo onto one base must not collapse them
    onto one DIR — lupin-mobile's holds are not lupin's, and a fix that merged them
    would satisfy the property above while corrupting every reader.
    """
    _, repos = fleet_layout
    names = { name: fleet_data_root( repo ).name for name, repo in repos.items() }
    assert names[ "nested_1" ]        == "lupin-mobile"
    assert names[ "flat" ]            == "lupin"
    assert names[ "grouped" ]         == "weil-parallel-search"
    assert len( set( names.values() ) ) == len( names ), f"two repos collided on one dir: {names}"


def test_MUTATION_the_old_depth_arithmetic_is_wrong_for_every_nested_shape( fleet_layout ):
    """
    Proves the property is DERIVED and not accidentally true of the fixture: the
    superseded rule is applied here by hand and must land inside a tree for every
    nested shape. If this ever goes green, the fixture stopped building the hazard.
    """
    projects, repos = fleet_layout
    for name, rel, nested_in in REPO_SHAPES:
        if nested_in is None:
            continue
        old_base = repos[ name ].parent.parent / DATA_DIR_FALLBACK   # the pre-1facc18e rule
        assert _independent_enclosing_tree( old_base ) == projects / nested_in, \
            f"{name}: the old rule was supposed to land inside {nested_in}"


# ── the anchor, stated directly ───────────────────────────────────────────

def test_the_anchor_is_the_projects_DIRECTORY_not_a_depth( tmp_path, monkeypatch ):
    """
    Two repos at different depths under one `projects/` must produce the same base.
    That is the whole content of the fix, said in one assertion.
    """
    monkeypatch.delenv( DATA_DIR_ENV, raising=False )
    shallow = tmp_path / PROJECTS_DIR_NAME / "a"
    deep    = tmp_path / PROJECTS_DIR_NAME / "a" / "b" / "c" / "d"
    assert _fleet_data_base( shallow ) == _fleet_data_base( deep ) == tmp_path / DATA_DIR_FALLBACK


def test_the_OUTERMOST_projects_ancestor_wins( tmp_path, monkeypatch ):
    """
    A repo carrying its own `projects/` subtree must map to the fleet's dir, not
    mint a second one beside its own. Nearest-match would give the inner answer.
    """
    monkeypatch.delenv( DATA_DIR_ENV, raising=False )
    inner = tmp_path / PROJECTS_DIR_NAME / "outer" / PROJECTS_DIR_NAME / "inner"
    assert _fleet_data_base( inner ) == tmp_path / DATA_DIR_FALLBACK
    assert _fleet_data_base( inner ) != tmp_path / PROJECTS_DIR_NAME / "outer" / DATA_DIR_FALLBACK


def test_the_env_var_short_circuits_the_whole_derivation( tmp_path, monkeypatch ):
    """A deployment that names its own base is not second-guessed — including for a
    path with no `projects` ancestor at all."""
    monkeypatch.setenv( DATA_DIR_ENV, "/named/by/hand" )
    assert _fleet_data_base( tmp_path / "anywhere" ) == Path( "/named/by/hand" )


# ── the last resort: no `projects` ancestor ───────────────────────────────

def test_with_no_projects_ancestor_the_legacy_arithmetic_still_applies( tmp_path, monkeypatch ):
    """
    The unchanged behaviour for a repo outside any `projects/` tree — the anchor has
    nothing to bite on, so the old rule stands.
    """
    monkeypatch.delenv( DATA_DIR_ENV, raising=False )
    repo = tmp_path / "code" / "solo"
    repo.mkdir( parents=True )
    assert _fleet_data_base( repo ) == tmp_path / DATA_DIR_FALLBACK


def test_the_last_resort_WALKS_OUT_of_a_working_tree_it_lands_in( tmp_path, monkeypatch ):
    """
    The escape loop. Without a `projects` anchor the depth arithmetic can still land
    inside a tree — a repo nested in a repo, somewhere else on disk — and the
    property must hold there too, or it is only true of today's layout.
    """
    monkeypatch.delenv( DATA_DIR_ENV, raising=False )
    outer = tmp_path / "code" / "outer"
    inner = outer / "vendor" / "inner"
    inner.mkdir( parents=True )
    ( outer / ".git" ).mkdir()
    ( inner / ".git" ).mkdir()

    base = _fleet_data_base( inner )
    assert _independent_enclosing_tree( base ) is None, f"{base} is still inside a tree"
    assert base == tmp_path / "code" / DATA_DIR_FALLBACK   # walked up out of `outer`, no further


def test_the_escape_loop_walks_out_of_NESTED_trees_not_just_one( tmp_path, monkeypatch ):
    """
    One iteration is not the contract. Three tiers deep, the loop must keep going —
    a single-step version passes the test above and fails here.
    """
    monkeypatch.delenv( DATA_DIR_ENV, raising=False )
    a = tmp_path / "top" / "a"
    b = a / "b"
    c = b / "c" / "repo"
    c.mkdir( parents=True )
    for d in ( a, b, c ):
        ( d / ".git" ).mkdir()

    base = _fleet_data_base( c )
    assert _independent_enclosing_tree( base ) is None
    assert base == tmp_path / "top" / DATA_DIR_FALLBACK


# ── _enclosing_tree_root, on its own ──────────────────────────────────────

def test_enclosing_tree_root_finds_the_tree_a_path_sits_in( tmp_path ):
    repo = tmp_path / "r"
    ( repo / "deep" / "deeper" ).mkdir( parents=True )
    ( repo / ".git" ).mkdir()
    assert _enclosing_tree_root( repo / "deep" / "deeper" ) == repo
    assert _enclosing_tree_root( repo ) == repo, "a repo root sits inside ITSELF"


def test_enclosing_tree_root_returns_None_outside_every_tree( tmp_path ):
    plain = tmp_path / "plain"
    plain.mkdir()
    assert _enclosing_tree_root( plain ) is None


def test_enclosing_tree_root_counts_a_worktrees_dot_git_FILE( tmp_path ):
    """
    ⚠️ `.git` is a DIRECTORY in a main checkout and a FILE in a linked worktree. A
    check written as `is_dir()` reads a worktree as "not a repo" and the data root
    lands inside it — the exact placement this fix exists to stop.
    """
    wt = tmp_path / "wt"
    wt.mkdir()
    ( wt / ".git" ).write_text( "gitdir: /elsewhere/.git/worktrees/wt\n" )
    assert _enclosing_tree_root( wt ) == wt


def test_enclosing_tree_root_handles_a_path_that_does_not_exist_yet( tmp_path ):
    """
    THE REASON THIS IS NOT `git rev-parse`. The data root is resolved BEFORE it is
    created, and `git -C <missing-dir>` answers about the CWD's repo instead — which
    on this box is lupin, for every caller, silently.
    """
    repo = tmp_path / "r"
    repo.mkdir()
    ( repo / ".git" ).mkdir()
    assert _enclosing_tree_root( repo / "not" / "created" / "yet" ) == repo
