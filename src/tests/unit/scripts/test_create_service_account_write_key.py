#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Pins `write_key_to_file` in the SQLite create_service_account script.

The Postgres script has the same function and its own tests. This file holds the SQLite copy to the
same contract: the path, the owner-only mode, the created directory, replace not append.
`cu.get_project_root()` is patched to tmp_path so no key file can land in the repo.
"""

import os
import sys

import pytest

sys.path.insert( 0, os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src", "scripts" ) )

import create_service_account as mod


@pytest.fixture
def project_root( tmp_path, monkeypatch ):
    """Point `cu.get_project_root()` at tmp_path."""

    class _Cu:
        @staticmethod
        def get_project_root():
            return str( tmp_path )

    monkeypatch.setattr( mod, "cu", _Cu )
    return tmp_path


def test_the_key_file_is_written_under_conf_keys_named_for_the_environment( project_root, capsys ):
    path = mod.write_key_to_file( "ck_live_abc", "prod" )

    assert path == project_root / "src" / "conf" / "keys" / "notification-api-claude-code-prod"
    assert path.read_text() == "ck_live_abc\n"
    out = capsys.readouterr().out
    assert "Wrote key to file" in out and "Permissions set: 600" in out


def test_the_key_file_is_owner_read_write_only( project_root ):
    path = mod.write_key_to_file( "ck_live_abc", "dev" )

    assert oct( path.stat().st_mode & 0o777 ) == "0o600"


def test_a_missing_keys_directory_is_created( project_root ):
    assert not ( project_root / "src" / "conf" / "keys" ).exists()

    mod.write_key_to_file( "ck_live_abc", "dev" )

    assert ( project_root / "src" / "conf" / "keys" ).is_dir()


def test_an_existing_key_file_is_replaced_not_appended_to( project_root ):
    mod.write_key_to_file( "ck_live_first", "dev" )
    path = mod.write_key_to_file( "ck_live_second", "dev" )

    assert path.read_text() == "ck_live_second\n"
