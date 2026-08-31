"""
The postgres password left the tree on row baac2474. What kept the local-Docker tests
working is `_seed_db_password_from_dotenv` in src/conftest.py: it fills a BLANK
DB_PASSWORD from the untracked .env that docker-compose already reads.

Without a guard, a regression here does not look like a broken helper — it looks like
"fe_sendauth: no password supplied" in test_check_schema_at_head, i.e. a broken branch.

⚠️ Every fixture below uses a DISTINCTIVE dummy value and a .env whose value DIFFERS
from the exported one, so an implementation that ignored its input, or preferred the
wrong source, would produce a different observation rather than the same one.
"""

import importlib.util
import os

import pytest


_CONFTEST = os.path.join(
    os.path.dirname( os.path.dirname( os.path.dirname( os.path.dirname( os.path.abspath( __file__ ) ) ) ) ),
    "conftest.py"
)


def _load_seeder():
    """Import src/conftest.py by path — it is a pytest plugin, not an importable module."""
    spec = importlib.util.spec_from_file_location( "_lupin_root_conftest_probe", _CONFTEST )
    mod  = importlib.util.module_from_spec( spec )
    spec.loader.exec_module( mod )
    return mod._seed_db_password_from_dotenv


@pytest.fixture
def seeder():
    return _load_seeder()


def _write_env( d, value ):
    with open( os.path.join( d, ".env" ), "w" ) as fh:
        fh.write( "POSTGRES_DB=lupin_db_dev\n" )
        fh.write( f"POSTGRES_PASSWORD={value}\n" )
        fh.write( "SOMETHING_ELSE=ignored\n" )


def test_a_blank_db_password_is_filled_from_the_dotenv( seeder, tmp_path, monkeypatch ):

    monkeypatch.delenv( "DB_PASSWORD", raising=False )
    _write_env( str( tmp_path ), "seeded-from-dotenv-a1" )

    seeder( root=str( tmp_path ) )

    assert os.environ[ "DB_PASSWORD" ] == "seeded-from-dotenv-a1"


def test_an_exported_db_password_wins_over_the_dotenv( seeder, tmp_path, monkeypatch ):
    """The .env carries a DIFFERENT value, so a helper that overwrote would be visible."""

    monkeypatch.setenv( "DB_PASSWORD", "exported-wins-b2" )
    _write_env( str( tmp_path ), "dotenv-must-not-win-b2" )

    seeder( root=str( tmp_path ) )

    assert os.environ[ "DB_PASSWORD" ] == "exported-wins-b2"


def test_no_dotenv_anywhere_leaves_db_password_unset( seeder, tmp_path, monkeypatch ):

    monkeypatch.delenv( "DB_PASSWORD", raising=False )

    seeder( root=str( tmp_path ) )

    assert "DB_PASSWORD" not in os.environ


def test_a_worktree_reaches_the_main_checkouts_dotenv( seeder, tmp_path, monkeypatch ):
    """
    The case that actually bites this fleet: .env is untracked, so a worktree has none.
    A `.git` FILE naming <main>/.git/worktrees/<n> is how the main checkout is found.
    """
    monkeypatch.delenv( "DB_PASSWORD", raising=False )

    main = tmp_path / "main";  main.mkdir()
    wt   = tmp_path / "wt";    wt.mkdir()
    _write_env( str( main ), "from-the-main-checkout-c3" )
    ( wt / ".git" ).write_text( f"gitdir: {main}/.git/worktrees/wt\n" )

    assert not ( wt / ".env" ).exists(), "the worktree must have no .env of its own"

    seeder( root=str( wt ) )

    assert os.environ[ "DB_PASSWORD" ] == "from-the-main-checkout-c3"


def test_an_empty_dotenv_value_does_not_set_a_blank_password( seeder, tmp_path, monkeypatch ):
    """A blank export is worse than none — it turns a missing var into an auth failure."""

    monkeypatch.delenv( "DB_PASSWORD", raising=False )
    _write_env( str( tmp_path ), "" )

    seeder( root=str( tmp_path ) )

    assert "DB_PASSWORD" not in os.environ


def test_a_dotenv_without_the_key_is_a_no_op( seeder, tmp_path, monkeypatch ):

    monkeypatch.delenv( "DB_PASSWORD", raising=False )
    with open( tmp_path / ".env", "w" ) as fh:
        fh.write( "POSTGRES_USER=lupin_dev\n" )

    seeder( root=str( tmp_path ) )

    assert "DB_PASSWORD" not in os.environ


def test_an_unreadable_dotenv_is_swallowed_rather_than_raising( seeder, tmp_path, monkeypatch ):

    monkeypatch.delenv( "DB_PASSWORD", raising=False )
    env = tmp_path / ".env"
    _write_env( str( tmp_path ), "unreadable-d4" )
    os.chmod( env, 0o000 )
    try:
        seeder( root=str( tmp_path ) )
        assert "DB_PASSWORD" not in os.environ
    finally:
        os.chmod( env, 0o600 )


def test_a_malformed_git_file_does_not_break_the_local_lookup( seeder, tmp_path, monkeypatch ):
    """A `.git` file with no `gitdir:` must fall back, not raise — the local .env still wins."""

    monkeypatch.delenv( "DB_PASSWORD", raising=False )
    _write_env( str( tmp_path ), "local-still-found-e5" )
    ( tmp_path / ".git" ).write_text( "not a gitdir line at all\n" )

    seeder( root=str( tmp_path ) )

    assert os.environ[ "DB_PASSWORD" ] == "local-still-found-e5"
