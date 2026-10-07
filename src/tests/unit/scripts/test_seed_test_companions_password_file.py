"""
The companion seed reads its database password from a file when DB_PASSWORD is blank.

The two app containers log in as lupin_app from a password file and carry no DB_PASSWORD.
The seed used to read only DB_PASSWORD, so it connected with an empty password and skipped.

Each test loads the script fresh with a chosen environment. Nothing connects to a database:
the script reads its password at import and opens a connection only inside a function.
"""

import importlib.util
import os

import pytest

SCRIPT = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src", "scripts", "seed_test_companions.py" )


def _load( monkeypatch, db_password=None, password_file=None ):
    """Import the script under a fixed DB_PASSWORD and DB_PASSWORD_FILE, each unset when None."""
    for name, value in ( ( "DB_PASSWORD", db_password ), ( "DB_PASSWORD_FILE", password_file ) ):
        if value is None: monkeypatch.delenv( name, raising=False )
        else:             monkeypatch.setenv( name, value )
    spec   = importlib.util.spec_from_file_location( "seed_test_companions_under_test", SCRIPT )
    module = importlib.util.module_from_spec( spec )
    spec.loader.exec_module( module )
    return module


def test_a_blank_password_is_read_from_the_named_file( monkeypatch, tmp_path ):
    path = tmp_path / "db_app_password"
    path.write_text( "from-the-file\n" )
    assert _load( monkeypatch, db_password="", password_file=str( path ) ).DB_PASSWORD == "from-the-file"


def test_an_unset_password_is_read_from_the_named_file( monkeypatch, tmp_path ):
    path = tmp_path / "db_app_password"
    path.write_text( "  from-the-file  \n" )
    assert _load( monkeypatch, password_file=str( path ) ).DB_PASSWORD == "from-the-file"


def test_a_set_password_wins_over_the_file( monkeypatch, tmp_path ):
    path = tmp_path / "db_app_password"
    path.write_text( "from-the-file\n" )
    assert _load( monkeypatch, db_password="from-the-env", password_file=str( path ) ).DB_PASSWORD == "from-the-env"


def test_with_neither_the_password_is_empty( monkeypatch ):
    assert _load( monkeypatch ).DB_PASSWORD == ""


def test_an_unreadable_file_gives_an_empty_password_and_a_warning_without_its_content( monkeypatch, tmp_path, capsys ):
    missing = tmp_path / "absent"
    module  = _load( monkeypatch, password_file=str( missing ) )
    printed = capsys.readouterr().out
    assert module.DB_PASSWORD == ""
    assert str( missing ) in printed and "FileNotFoundError" in printed


def test_a_file_that_is_not_text_gives_an_empty_password_and_a_warning_without_its_bytes( monkeypatch, tmp_path, capsys ):
    path = tmp_path / "db_app_password"
    path.write_bytes( b"\xff\xfe-not-utf8" )
    module  = _load( monkeypatch, password_file=str( path ) )
    printed = capsys.readouterr().out
    assert module.DB_PASSWORD == ""
    assert "UnicodeDecodeError" in printed and "not-utf8" not in printed and "0xff" not in printed


def test_an_empty_file_gives_an_empty_password( monkeypatch, tmp_path ):
    path = tmp_path / "db_app_password"
    path.write_text( "\n" )
    assert _load( monkeypatch, password_file=str( path ) ).DB_PASSWORD == ""
