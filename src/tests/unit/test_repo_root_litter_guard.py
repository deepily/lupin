"""Unit tests for tests/helpers/repo_root_litter_guard.py."""

import subprocess
import types

from tests.helpers.repo_root_litter_guard import neutral_working_dir, new_litter, root_litter, SCRATCH_CONTAINER


def _run_ok( out ):
    return lambda *a, **k: types.SimpleNamespace( returncode=0, stdout=out )


def test_override_wins_when_it_exists():
    got = neutral_working_dir( "/r/lupin", "/tmp/x", env={ "LUPIN_TEST_SCRATCH_PROJECT_DIR": "/o" }, exists=lambda p: True )
    assert got == "/o"


def test_container_mount_used_when_no_override():
    got = neutral_working_dir( "/r/lupin", "/tmp/x", env={}, exists=lambda p: p == SCRATCH_CONTAINER )
    assert got == SCRATCH_CONTAINER


def test_sibling_scratchpad_used_when_only_it_exists():
    got = neutral_working_dir( "/r/lupin", "/tmp/x", env={}, exists=lambda p: p == "/r/scratchpad" )
    assert got == "/r/scratchpad"


def test_falls_back_to_temp_dir_when_nothing_exists():
    assert neutral_working_dir( "/r/lupin", "/tmp/x", env={}, exists=lambda p: False ) == "/tmp/x"


def test_never_returns_the_repo_root():
    got = neutral_working_dir( "/r/lupin", "/tmp/x", env={ "LUPIN_TEST_SCRATCH_PROJECT_DIR": "/r/lupin" }, exists=lambda p: p == "/r/lupin" )
    assert got == "/tmp/x"


def test_default_env_is_os_environ( monkeypatch ):
    monkeypatch.setenv( "LUPIN_TEST_SCRATCH_PROJECT_DIR", "/from-os" )
    assert neutral_working_dir( "/r/lupin", "/tmp/x", exists=lambda p: p == "/from-os" ) == "/from-os"


def test_root_litter_keeps_only_root_level_names():
    out = "stray.py\n\nsrc/deep/file.py\nnotes.md\n"
    assert root_litter( "/r", run=_run_ok( out ) ) == frozenset( { "stray.py", "notes.md" } )


def test_root_litter_quiet_on_git_failure():
    run = lambda *a, **k: types.SimpleNamespace( returncode=128, stdout="x.py\n" )
    assert root_litter( "/r", run=run ) == frozenset()


def test_root_litter_quiet_when_git_missing_or_slow():
    def missing( *a, **k ): raise FileNotFoundError( "git" )
    def slow( *a, **k ): raise subprocess.TimeoutExpired( "git", 30 )
    assert root_litter( "/r", run=missing ) == frozenset()
    assert root_litter( "/r", run=slow ) == frozenset()


def test_root_litter_against_a_real_repo( tmp_path ):
    subprocess.run( [ "git", "init", "-q", str( tmp_path ) ], check=True )
    ( tmp_path / "a.py" ).write_text( "x" )
    ( tmp_path / "sub" ).mkdir()
    ( tmp_path / "sub" / "b.py" ).write_text( "x" )
    assert root_litter( str( tmp_path ) ) == frozenset( { "a.py" } )


def test_new_litter_is_the_sorted_difference():
    assert new_litter( { "a" }, { "a", "c", "b" } ) == [ "b", "c" ]
    assert new_litter( { "a" }, { "a" } ) == []
