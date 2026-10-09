"""
The shared library of the three seat-worktree scripts, and its copy in lupin-mobile.

src/scripts/lib/worktree-link-lib.sh holds what three scripts all need. They are
link-worktree-venv.sh, link-worktree-artifacts.sh and provision-seat-worktree.sh.
The library finds the main checkout of a repository. It also says whether a directory is that checkout.
lupin-mobile has its own three scripts and is meant to carry a byte-identical copy.

Four things are pinned. The functions find the primary tree, including a path with spaces.
They refuse a directory outside any repository. They tell one directory from another through a symlink.
The copy in lupin-mobile is byte-identical. While the sibling repo has no copy, the check skips
and names the file to add.

Venue: :7999-eligible. Scratch git repos under tmp_path, no server, no network.
"""

import os
import subprocess

import pytest

_REPO_ROOT = os.path.abspath( os.path.join( os.path.dirname( __file__ ), "..", "..", ".." ) )
_LIB       = os.path.join( _REPO_ROOT, "src", "scripts", "lib", "worktree-link-lib.sh" )
_LIB_REL   = os.path.join( "src", "scripts", "lib", "worktree-link-lib.sh" )
_GIT_ENV   = { **os.environ, "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_SYSTEM": "/dev/null" }


def _sibling_repo_root( name ):
    """
    The sibling repo `name` beside the main lupin checkout, or None when it is not there.

    Requires:
        - _REPO_ROOT is inside a git work tree

    Ensures:
        - returns an absolute path to an existing directory holding src/scripts, or None
        - never writes anywhere
    """
    result = subprocess.run( [ "git", "-C", _REPO_ROOT, "rev-parse", "--path-format=absolute", "--git-common-dir" ],
                             capture_output=True, text=True )
    if result.returncode != 0: return None
    sibling = os.path.join( os.path.dirname( os.path.dirname( result.stdout.strip() ) ), name )
    return sibling if os.path.isdir( os.path.join( sibling, "src", "scripts" ) ) else None


def _identical( first, second ):
    """True when both files hold the same bytes."""
    with open( first, "rb" ) as a, open( second, "rb" ) as b:
        return a.read() == b.read()


def _git( cwd, *args ):
    subprocess.run( [ "git", *args ], cwd=cwd, check=True, capture_output=True, env=_GIT_ENV )


def _bash( script, cwd=None ):
    """Run a bash snippet that has sourced the library under test; returns the completed process."""
    return subprocess.run( [ "bash", "-c", f'source "{_LIB}"\n{script}' ], capture_output=True, text=True, timeout=60, cwd=cwd )


@pytest.fixture
def main_with_worktree( tmp_path ):
    """A scratch repo with one commit and one linked worktree; the paths hold a space."""
    main = tmp_path / "main repo"
    main.mkdir()
    _git( main, "init", "-q", "-b", "main", "." )
    _git( main, "config", "user.email", "t@example.com" )
    _git( main, "config", "user.name", "t" )
    ( main / "a.txt" ).write_text( "a\n" )
    _git( main, "add", "-A" )
    _git( main, "commit", "-q", "-m", "seed" )
    linked = tmp_path / "linked tree"
    _git( main, "worktree", "add", "-q", "--detach", str( linked ) )
    return main, linked


# ---- the functions -----------------------------------------------------------------------------

def test_the_library_sets_no_shell_option_and_never_exits():
    text = open( _LIB ).read()
    code = [ ln for ln in text.splitlines() if not ln.lstrip().startswith( "#" ) ]
    assert not any( ln.lstrip().startswith( ( "set -", "exit" ) ) for ln in code ), "a sourced library must leave both to its caller"


@pytest.mark.parametrize( "which", [ "main", "linked" ] )
def test_the_main_checkout_is_found_from_the_main_tree_and_from_a_linked_one( main_with_worktree, which ):
    main, linked = main_with_worktree
    start        = main if which == "main" else linked
    done         = _bash( f'wt_resolve_main "{start}"; echo "rc=$?"; echo "main=$WT_MAIN"' )
    assert done.stdout.splitlines() == [ "rc=0", f"main={main}" ], done.stderr


def test_the_list_is_kept_for_a_caller_that_reads_it_again( main_with_worktree ):
    main, linked = main_with_worktree
    done = _bash( f'wt_resolve_main "{linked}"; printf "%s\\n" "$WT_LIST"' )
    assert f"worktree {main}" in done.stdout and f"worktree {linked}" in done.stdout


def test_a_directory_outside_any_repository_returns_one_and_sets_nothing( tmp_path ):
    plain = tmp_path / "not a repo"
    plain.mkdir()
    done = _bash( f'wt_resolve_main "{plain}"; echo "rc=$?"; echo "main=[$WT_MAIN]"; echo "list=[$WT_LIST]"' )
    assert done.stdout.splitlines() == [ "rc=1", "main=[]", "list=[]" ]


def test_the_same_directory_is_recognised_through_a_symlink( main_with_worktree, tmp_path ):
    main, linked = main_with_worktree
    alias        = tmp_path / "alias"
    os.symlink( main, alias )
    done = _bash( f'wt_same_dir "{main}" "{alias}"; echo "same=$?"; wt_same_dir "{main}" "{linked}"; echo "other=$?"' )
    assert done.stdout.splitlines() == [ "same=0", "other=1" ]


def test_the_library_reads_the_list_without_a_pipe():
    code = "\n".join( ln for ln in open( _LIB ).read().splitlines() if not ln.lstrip().startswith( "#" ) )
    reads = [ ln for ln in code.splitlines() if "worktree list --porcelain" in ln ]
    assert len( reads ) == 1, f"expected one line that reads the worktree list, got {reads}"
    assert "|" not in reads[ 0 ], "git worktree list must not feed any reader through a pipe"
    assert reads[ 0 ].lstrip().startswith( ( 'if ! WT_LIST="$( git -C "$dir" worktree list --porcelain', 'WT_LIST="$( git -C "$dir" worktree list --porcelain' ) )


def test_the_three_scripts_source_the_library_and_hold_no_copy_of_its_functions():
    for name in ( "link-worktree-venv.sh", "link-worktree-artifacts.sh", "provision-seat-worktree.sh" ):
        text = open( os.path.join( _REPO_ROOT, "src", "scripts", name ) ).read()
        code = [ ln for ln in text.splitlines() if not ln.lstrip().startswith( "#" ) ]
        assert any( "lib/worktree-link-lib.sh" in ln and "source" in ln for ln in code ), f"{name} does not source the library"
        assert not any( "worktree list --porcelain" in ln for ln in code ), f"{name} reads the worktree list itself"


# ---- the copy in lupin-mobile ------------------------------------------------------------------

def test_the_identity_check_can_tell_two_different_files_apart( tmp_path ):
    """The negative control: a comparison that cannot fail would make the test below say nothing."""
    first, second, third = tmp_path / "a", tmp_path / "b", tmp_path / "c"
    first.write_bytes( b"same\n" )
    second.write_bytes( b"same\n" )
    third.write_bytes( b"same \n" )
    assert _identical( first, second ) is True
    assert _identical( first, third ) is False


def test_the_copy_of_the_library_in_lupin_mobile_is_byte_identical():
    mobile = _sibling_repo_root( "lupin-mobile" )
    if mobile is None:
        pytest.skip( "sibling repo lupin-mobile not found beside the main lupin checkout; nothing to compare" )
    copy = os.path.join( mobile, _LIB_REL )
    if not os.path.isfile( copy ):
        pytest.skip( f"lupin-mobile has no {_LIB_REL}: add a byte-identical copy of lupin's file there, from a lupin-mobile session" )
    assert _identical( _LIB, copy ), f"{copy} differs from {_LIB}: the two copies must stay byte-identical"
