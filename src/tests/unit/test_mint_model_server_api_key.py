"""Unit tests for the model-server API key minter.

The decoupling test file proves a minted key satisfies the server regex.
This file covers the rest against a real temp directory.
The file mode is read back from the filesystem, never from the function.

Properties checked, each with a control in the opposite direction:

- A key is not overwritten without --force, and is overwritten with it.
- The file is mode 600 even when --force reopens a looser file.
- The plaintext key never reaches stdout, only its fingerprint.
- A dry run writes nothing.
"""

import importlib.util
import os
import re
import stat

import pytest

import cosa.utils.util as cu

SCRIPT = os.path.join( cu.get_project_root(), "src", "scripts", "mint-model-server-api-key.py" )


def _load():
    spec = importlib.util.spec_from_file_location( "mint_ms_key_edges", SCRIPT )
    mod  = importlib.util.module_from_spec( spec )
    spec.loader.exec_module( mod )
    return mod


@pytest.fixture
def mint():
    return _load()


def _mode( path ):
    return stat.S_IMODE( os.stat( path ).st_mode )


def test_import_without_lupin_root_refuses_loudly( monkeypatch ):
    monkeypatch.delenv( "LUPIN_ROOT", raising=False )
    with pytest.raises( RuntimeError, match="LUPIN_ROOT not set" ):
        _load()


def test_a_generated_key_that_fails_the_server_regex_is_refused( mint, monkeypatch ):
    monkeypatch.setattr( mint.secrets, "token_urlsafe", lambda n: "short" )
    with pytest.raises( RuntimeError, match="refusing to emit a key" ):
        mint.generate_model_server_key()


def test_key_file_path_is_under_the_project_conf_keys_dir( mint ):
    assert mint.key_file_path() == f"{cu.get_project_root()}/src/conf/keys/model-server-api"


def test_write_key_creates_the_parent_dir_and_a_mode_600_file_holding_exactly_the_key( mint, tmp_path ):
    key  = mint.generate_model_server_key()
    path = str( tmp_path / "deep" / "dir" / "model-server-api" )
    mint.write_key( key, path )
    with open( path ) as fh:
        assert fh.read() == key
    assert _mode( path ) == 0o600


def test_write_key_refuses_a_key_that_fails_the_regex_and_writes_nothing( mint, tmp_path ):
    path = str( tmp_path / "k" )
    with pytest.raises( ValueError, match="refusing to write" ):
        mint.write_key( "ck_live_tooshort", path )
    assert not os.path.exists( path )


def test_write_key_refuses_to_overwrite_without_force_and_leaves_the_old_key_intact( mint, tmp_path ):
    path = str( tmp_path / "k" )
    old, new = mint.generate_model_server_key(), mint.generate_model_server_key()
    mint.write_key( old, path )
    with pytest.raises( FileExistsError, match="already exists" ):
        mint.write_key( new, path )
    with open( path ) as fh:
        assert fh.read() == old


def test_write_key_with_force_rotates_the_key_and_tightens_a_loose_mode( mint, tmp_path ):
    path = str( tmp_path / "k" )
    old, new = mint.generate_model_server_key(), mint.generate_model_server_key()
    mint.write_key( old, path )
    os.chmod( path, 0o644 )                                # the loose pre-existing file
    mint.write_key( new, path, force=True )
    with open( path ) as fh:
        assert fh.read() == new
    assert _mode( path ) == 0o600


def test_main_dry_run_writes_nothing_and_says_so( mint, tmp_path, monkeypatch, capsys ):
    path = str( tmp_path / "k" )
    monkeypatch.setattr( mint, "key_file_path", lambda: path )
    monkeypatch.setattr( mint.sys, "argv", [ "mint" ] )
    assert mint.main() == 0
    out = capsys.readouterr().out
    assert "DRY RUN (no file written)" in out and "Dry run — nothing written" in out
    assert not os.path.exists( path )


def test_main_apply_writes_the_key_and_prints_its_fingerprint_but_never_the_key( mint, tmp_path, monkeypatch, capsys ):
    path = str( tmp_path / "k" )
    monkeypatch.setattr( mint, "key_file_path", lambda: path )
    monkeypatch.setattr( mint.sys, "argv", [ "mint", "--apply" ] )
    assert mint.main() == 0
    out = capsys.readouterr().out
    with open( path ) as fh:
        key = fh.read()
    assert re.match( mint.CK_LIVE_RE, key )
    assert key not in out, "the plaintext key reached stdout"
    assert f"fingerprint : {mint.key_fingerprint( key )}" in out
    assert "mode        : 0o600" in out
    assert "bug 574fd1dc" in out


def test_main_apply_over_an_existing_key_exits_1_and_keeps_it_until_force( mint, tmp_path, monkeypatch, capsys ):
    path = str( tmp_path / "k" )
    original = mint.generate_model_server_key()
    mint.write_key( original, path )
    monkeypatch.setattr( mint, "key_file_path", lambda: path )

    monkeypatch.setattr( mint.sys, "argv", [ "mint", "--apply" ] )
    assert mint.main() == 1
    assert "ERROR:" in capsys.readouterr().out
    with open( path ) as fh:
        assert fh.read() == original

    monkeypatch.setattr( mint.sys, "argv", [ "mint", "--apply", "--force" ] )
    assert mint.main() == 0
    with open( path ) as fh:
        assert fh.read() != original
