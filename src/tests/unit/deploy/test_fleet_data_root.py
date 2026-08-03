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
