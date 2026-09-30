"""
The worktree janitor sweeps every fleet repo named in the INI (row 129cc96b, P2).

Before this it looked only at lupin's own `.claude/worktrees`, and lupin-mobile plus
planning-is-prompting piled up 26 trees between them. The list now lives in
`arbiter worktree janitor repos`, as names from the `external repo <name>` registry.
Those paths are container-side, so each is translated to the host the way the hold sweep
does. A name that cannot be resolved is reported and skipped, never guessed at.
"""

import os
import subprocess
import time

import pytest

from lupin_arbiter_app import fleet_arbiter_loop as fal


class _Cfg:
    """Dict-backed stand-in for ConfigurationManager.get."""
    def __init__( self, values ): self.values = values
    def get( self, key, default=None, return_type=None ):
        value = self.values.get( key, default )
        if return_type == "list-string" and isinstance( value, str ):
            return [ v.strip() for v in value.split( "," ) ]
        return value


def _registry( names, **extra ):
    values = { "external repos": ", ".join( names ) }
    for name in names:
        values[ f"external repo {name} path" ] = f"/var/external-projects/{name}"
    values.update( extra )
    return values


@pytest.fixture
def projects( tmp_path ):
    root = tmp_path / "projects"
    for name in ( "lupin", "lupin-mobile", "planning-is-prompting" ):
        ( root / name ).mkdir( parents=True )
    return root


# ---------------------------------------------------------------------------
# Resolving the list
# ---------------------------------------------------------------------------
def test_every_configured_name_resolves_to_its_host_repo( projects ):
    names = [ "lupin", "lupin-mobile", "planning-is-prompting" ]
    cfg   = _Cfg( _registry( names, **{ "arbiter worktree janitor repos": ", ".join( names ) } ) )

    out = fal.janitor_repo_roots( cfg, str( projects / "lupin" ) )

    assert out == { "roots": [ str( projects / n ) for n in names ], "unresolved": [] }


def test_the_list_comes_from_the_ini_not_from_the_registry( projects ):
    """The registry names three repos; the janitor key names one. The key wins."""
    cfg = _Cfg( _registry( [ "lupin", "lupin-mobile", "planning-is-prompting" ],
                           **{ "arbiter worktree janitor repos": "lupin-mobile" } ) )
    assert fal.janitor_repo_roots( cfg, str( projects / "lupin" ) )[ "roots" ] == [ str( projects / "lupin-mobile" ) ]


def test_an_unresolvable_name_is_reported_never_guessed( projects ):
    cfg = _Cfg( _registry( [ "lupin" ], **{
        "arbiter worktree janitor repos"      : "lupin, ghost, no-such-dir",
        "external repo no-such-dir path"      : "/var/external-projects/no-such-dir" } ) )
    out = fal.janitor_repo_roots( cfg, str( projects / "lupin" ) )
    assert out == { "roots": [ str( projects / "lupin" ) ], "unresolved": [ "ghost", "no-such-dir" ] }


def test_the_same_repo_named_twice_is_swept_once( projects ):
    cfg = _Cfg( _registry( [ "lupin" ], **{ "arbiter worktree janitor repos": "lupin, lupin" } ) )
    assert fal.janitor_repo_roots( cfg, str( projects / "lupin" ) )[ "roots" ] == [ str( projects / "lupin" ) ]


@pytest.mark.parametrize( "value", [ None, "", " , " ] )
def test_a_blank_list_means_this_project_only( projects, value ):
    values = _registry( [ "lupin", "lupin-mobile" ] )
    if value is not None:
        values[ "arbiter worktree janitor repos" ] = value
    out = fal.janitor_repo_roots( _Cfg( values ), str( projects / "lupin" ) )
    assert out == { "roots": [ str( projects / "lupin" ) ], "unresolved": [] }


def test_a_config_that_raises_falls_back_to_this_project( projects ):
    class _Broken:
        def get( self, *a, **k ): raise ValueError( "bad ini" )
    assert fal.janitor_repo_roots( _Broken(), str( projects / "lupin" ) )[ "roots" ] == [ str( projects / "lupin" ) ]


def test_host_root_defaults_to_the_project_root( monkeypatch, projects ):
    monkeypatch.setenv( "LUPIN_ROOT", str( projects / "lupin" ) )
    assert fal.janitor_repo_roots( _Cfg( {} ) )[ "roots" ] == [ str( projects / "lupin" ) ]


def test_the_app_passes_the_resolved_list_to_the_factory():
    import cosa.utils.util as cu
    from pathlib import Path
    source = Path( cu.get_project_root(), "src", "lupin_arbiter_app", "app.py" ).read_text()
    assert "worktree_janitor_repos     = janitor_repo_roots( cfg )," in source


def test_the_ini_names_the_three_fleet_repos():
    import configparser
    import cosa.utils.util as cu
    ini = configparser.ConfigParser( interpolation=None, strict=False )
    ini.read( os.path.join( cu.get_project_root(), "src", "conf", "lupin-app.ini" ) )
    value = ini[ "Lupin: Baseline" ][ "arbiter worktree janitor repos" ]   # the section the janitor keys live in
    assert [ v.strip() for v in value.split( "," ) ] == [ "lupin", "lupin-mobile", "planning-is-prompting" ]


# ---------------------------------------------------------------------------
# One janitor, many repos
# ---------------------------------------------------------------------------
def _janitor( roots, reconcile_fn, events=None ):
    events = events if events is not None else []
    return fal.make_worktree_janitor_fn(
        sandbox_root=".claude/worktrees", age_hours=6, ledger_path="/nowhere",
        notify_fn=lambda m, a: [], log_fn=lambda e, **f: events.append( ( e, f ) ),
        reconcile_fn=reconcile_fn, report_fn=lambda *a, **k: { "changed": False },
        repo_roots=roots )


def test_each_repo_is_reconciled_at_its_own_root_and_the_results_concatenate():
    seen = []
    def reconcile( **kw ):
        seen.append( kw[ "project_root" ] )
        return { "swept": [ f"{kw[ 'project_root' ]}/t" ], "skipped": [], "errors": [],
                 "branches_deleted": [], "branches_kept": [] }
    out = _janitor( [ "/a", "/b" ], reconcile )()
    assert seen == [ "/a", "/b" ]
    assert out[ "swept" ] == [ "/a/t", "/b/t" ]
    assert out[ "repos" ] == [ { "root": "/a", "swept": 1 }, { "root": "/b", "swept": 1 } ]


def test_one_repo_raising_does_not_stop_the_others():
    def reconcile( **kw ):
        if kw[ "project_root" ] == "/a": raise RuntimeError( "git gone" )
        return { "swept": [ "ok" ] }
    out = _janitor( [ "/a", "/b" ], reconcile )()
    assert out[ "swept" ] == [ "ok" ]
    assert out[ "errors" ] == [ "/a: janitor raised: git gone" ]


def test_no_roots_means_one_reconcile_at_the_default_root():
    seen = []
    _janitor( None, lambda **kw: seen.append( kw[ "project_root" ] ) or {} )()
    assert seen == [ None ]


def test_kept_and_deleted_branches_are_logged_as_one_report():
    events = []
    reconcile = lambda **kw: { "branches_deleted": [ { "branch": "wt-a" } ],
                               "branches_kept": [ { "branch": "wt-b", "kept_reason": "unmerged", "commits_ahead": 2 } ] }
    _janitor( [ "/a" ], reconcile, events )()
    assert events == [ ( "worktree_janitor_branches",
                         { "deleted": [ "wt-a" ],
                           "kept": [ { "branch": "wt-b", "reason": "unmerged", "commits_ahead": 2 } ] } ) ]


def test_a_poll_that_touched_no_branch_logs_nothing():
    events = []
    _janitor( [ "/a" ], lambda **kw: {}, events )()
    assert events == []


# ---------------------------------------------------------------------------
# The :8001 factory
# ---------------------------------------------------------------------------
class _Store:
    def set_section( self, name, value ): pass


class _Gateway:
    def post( self, topic, body ): pass


def test_the_factory_hands_the_roots_to_the_janitor_and_logs_the_unresolved( monkeypatch, tmp_path ):
    events, captured = [], {}
    real = fal.make_worktree_janitor_fn
    def spy( **kw ):
        captured.update( kw )
        return real( **kw )
    monkeypatch.setattr( fal, "make_worktree_janitor_fn", spy )
    fal.build_fleet_arbiter_job_factory(
        _Gateway(), _Store(), log_fn=lambda e, **f: events.append( ( e, f ) ),
        worktree_janitor_enabled=True, worktree_refusal_ledger_path=str( tmp_path / "l.json" ),
        worktree_janitor_repos={ "roots": [ "/a", "/b" ], "unresolved": [ "ghost" ] } )
    assert captured[ "repo_roots" ] == [ "/a", "/b" ]
    assert ( "worktree_janitor_repo_unresolved", { "names": [ "ghost" ] } ) in events


# ---------------------------------------------------------------------------
# End to end on two real repos
# ---------------------------------------------------------------------------
def _git( cwd, *args ):
    return subprocess.run( [ "git", *args ], cwd=cwd, capture_output=True, text=True, timeout=60 )


def _make_repo( path, branch ):
    _git( path, "init", "-q", "-b", branch )
    _git( path, "config", "user.email", "t@example.com" )
    _git( path, "config", "user.name", "T" )
    ( path / "README.md" ).write_text( "seed\n" )
    _git( path, "add", "-A" )
    _git( path, "commit", "-q", "-m", "seed" )


def _idle_tree( repo, name ):
    tree = repo / ".claude" / "worktrees" / name
    assert _git( repo, "worktree", "add", "-q", "-b", name, str( tree ), "HEAD" ).returncode == 0
    old = time.time() - 7 * 3600
    for p in tree.rglob( "*" ):
        if p.is_file() and p.name != ".git":
            os.utime( p, ( old, old ) )
    return tree


def test_two_real_repos_each_lose_their_idle_tree_and_merged_branch( projects, tmp_path ):
    _make_repo( projects / "lupin", "wip-v9" )
    _make_repo( projects / "lupin-mobile", "main" )
    tree_a = _idle_tree( projects / "lupin", "wt-a" )
    tree_b = _idle_tree( projects / "lupin-mobile", "wt-b" )
    cfg    = _Cfg( _registry( [ "lupin", "lupin-mobile" ],
                              **{ "arbiter worktree janitor repos": "lupin, lupin-mobile" } ) )
    roots  = fal.janitor_repo_roots( cfg, str( projects / "lupin" ) )[ "roots" ]

    janitor = fal.make_worktree_janitor_fn(
        sandbox_root=".claude/worktrees", age_hours=6, ledger_path=str( tmp_path / "refused.json" ),
        notify_fn=lambda m, a: [], log_fn=lambda *a, **k: None, repo_roots=roots )
    out = janitor()

    assert not tree_a.exists() and not tree_b.exists()
    assert sorted( ( o[ "branch" ], o[ "target" ] ) for o in out[ "branches_deleted" ] ) == [
        ( "wt-a", "wip-v9" ), ( "wt-b", "main" ) ], "each repo is measured against ITS OWN current branch"
