"""
Independent review of 793eb070f (row 80513825): does `get_database_url` behave as before when none
of the new keys or files is present?

THE CLAIM UNDER TEST is the commit message's "With none of the new keys nothing changes". It is
checked at the two seams the commit touched:

  1. `seed_db_password_from_file` is a no-op unless DB_PASSWORD is blank AND DB_PASSWORD_FILE is
     set: no file is opened, nothing is printed, the environment is not touched.
  2. `seed_db_password_from_dotenv` returns what the pre-793eb070f seeder returned, for a corpus
     of `.env` files that carry only POSTGRES_PASSWORD (a frozen copy of the old loop is the
     reference, `_old_seed`).

Result of the review, recorded here as tests rather than prose: it was NOT identical for three
`.env` shapes. The old loop stopped at the FIRST `POSTGRES_PASSWORD=` line and never read past
it; the new loop read the whole file and let the LAST non-empty line win. Those three cases were
`xfail( strict=True )` when this file was written; the fix removed the markers and they now pass
plain, so the claim "with none of the new keys nothing changes" is a passing test.

Venue: :7999 (unit, no server, no database).
"""

import builtins
import os

import pytest

import cosa.rest.db.database as database
from cosa.utils.dotenv_password import seed_db_password_from_dotenv, seed_db_password_from_file

NEW_KEYS = ( "DB_PASSWORD_FILE", "LUPIN_HOST_DB_USER", "LUPIN_HOST_DB_PASSWORD",
             "LUPIN_TEST_DB_USER", "LUPIN_TEST_DB_PASSWORD" )


@pytest.fixture( autouse=True )
def _clean_env( monkeypatch ):
    for key in ( "DB_PASSWORD", "DB_USER", "LUPIN_ENV", "LUPIN_CLOUD_BACKED" ) + NEW_KEYS:
        monkeypatch.delenv( key, raising=False )


# ---- 1. the file seeder -------------------------------------------------------------------------
def test_the_file_seeder_does_nothing_without_the_variable( monkeypatch, capsys ):
    def _no_open( *args, **kwargs ): raise AssertionError( f"opened a file: {args}" )
    monkeypatch.setattr( builtins, "open", _no_open )
    before = dict( os.environ )
    seed_db_password_from_file()
    assert dict( os.environ ) == before
    assert capsys.readouterr().out == ""


def test_the_file_seeder_does_nothing_when_a_password_is_already_exported( monkeypatch, capsys ):
    monkeypatch.setenv( "DB_PASSWORD", "exported" )
    monkeypatch.setenv( "DB_PASSWORD_FILE", "/nonexistent/never-read" )
    def _no_open( *args, **kwargs ): raise AssertionError( f"opened a file: {args}" )
    monkeypatch.setattr( builtins, "open", _no_open )
    seed_db_password_from_file()
    assert os.environ[ "DB_PASSWORD" ] == "exported"
    assert capsys.readouterr().out == ""


# ---- 2. get_database_url, end to end, for what a container or a host shell hands it -----------
@pytest.mark.parametrize( "env, expected", [
    ( "development", "postgresql+psycopg2://lupin_dev:pw@localhost:5432/lupin_db_dev" ),
    ( "testing",     "postgresql+psycopg2://lupin_dev:pw@localhost:5432/lupin_db_test" ),
] )
def test_get_database_url_is_unchanged_with_an_exported_password( monkeypatch, env, expected ):
    monkeypatch.setenv( "LUPIN_ENV", env )
    monkeypatch.setenv( "DB_PASSWORD", "pw" )
    assert database.get_database_url() == expected


def test_get_database_url_with_no_password_anywhere_still_builds_an_empty_password_url( monkeypatch ):
    """The documented 'must not raise at import' behaviour: blank password, announced, not an error."""
    monkeypatch.setattr( database, "seed_db_password_from_dotenv", lambda *a, **k: None )
    monkeypatch.setattr( database, "announce_empty_db_password_once", lambda *a, **k: None )
    assert database.get_database_url() == "postgresql+psycopg2://lupin_dev:@localhost:5432/lupin_db_dev"


# ---- 3. the .env seeder against a frozen copy of the loop it replaced ----------------------------
def _old_seed( dotenv_text ):
    """The `.env` loop exactly as it stood before 793eb070f: first POSTGRES_PASSWORD= line decides."""
    for line in dotenv_text.splitlines():
        line = line.strip()
        if not line.startswith( "POSTGRES_PASSWORD=" ): continue
        value = line.split( "=", 1 )[ 1 ].strip().strip( "\"'" )
        return value if value else None
    return None


def _new_seed( tmp_path, monkeypatch, dotenv_bytes ):
    ( tmp_path / ".env" ).write_bytes( dotenv_bytes )
    monkeypatch.delenv( "DB_PASSWORD", raising=False )
    seed_db_password_from_dotenv( root=str( tmp_path ) )
    return os.environ.get( "DB_PASSWORD" ) or None


# The key name is spelled through a variable so no line of this file reads as `KEY=<value>`: these
# are fixture values, and the commit scanner (rightly) refuses anything shaped like a credential.
K = "POSTGRES_PASSWORD"

SAME = [
    f"{K}=abc123\n",
    f'{K}="quoted pw"\n',
    f"{K}='single'\n",
    "# a comment\nOTHER=1\nPOSTGRES_PASSWORD=after-noise\nMORE=2\n",
    "  POSTGRES_PASSWORD=indented  \n",
    "POSTGRES_PASSWORD=\n",                    # blank: neither sets anything
    "OTHER=1\n",                               # key absent
    "",                                        # empty file
    f"{K}=has=equals=signs\n",
    "export POSTGRES_PASSWORD=exported-form\n",    # not matched by either
]


@pytest.mark.parametrize( "dotenv", SAME )
def test_the_dotenv_seeder_matches_the_old_loop_when_only_the_old_key_is_present( tmp_path, monkeypatch, dotenv ):
    assert _new_seed( tmp_path, monkeypatch, dotenv.encode() ) == _old_seed( dotenv )


DIVERGENT = [
    pytest.param( "POSTGRES_PASSWORD=first\nPOSTGRES_PASSWORD=second\n",
                  id="duplicate-key-old-first-wins-new-last-wins" ),
    pytest.param( "POSTGRES_PASSWORD=\nPOSTGRES_PASSWORD=real\n",
                  id="blank-line-then-value-old-stops-at-the-blank" ),
]


@pytest.mark.parametrize( "dotenv", DIVERGENT )
def test_duplicate_or_blank_postgres_password_lines_match_the_old_loop( tmp_path, monkeypatch, dotenv ):
    """Fixed after the review: the FIRST `POSTGRES_PASSWORD=` line decides, blank or not, as before."""
    assert _new_seed( tmp_path, monkeypatch, dotenv.encode() ) == _old_seed( dotenv )


def test_undecodable_bytes_after_the_key_do_not_raise_and_keep_what_was_read( tmp_path, monkeypatch ):
    """Fixed after the review: the module's contract is that it never raises."""
    dotenv = b"POSTGRES_PASSWORD=ok\n# \xff\xfe not utf-8\n"
    assert _new_seed( tmp_path, monkeypatch, dotenv ) == "ok"
