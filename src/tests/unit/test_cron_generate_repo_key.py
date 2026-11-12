"""The registry repo key: Lupin lines stay as they were, another repo gets lines of its own."""
import json
import pathlib
import subprocess
import sys

import pytest

import cosa.repo.code_health_settings as chs
import cosa.repo.symindex.paths as paths
import cosa.rest.job_registry as jr
from lupin_mcp import cron_generate as cg
from lupin_mcp import job_run as jrun
from tests.unit.test_cron_generate import tree   # noqa: F401  (fixture: a root with a registry of managed jobs)

REAL_ROOT = str( pathlib.Path( __file__ ).resolve().parents[ 3 ] )
GOLDEN    = pathlib.Path( __file__ ).resolve().parents[ 1 ] / "fixtures" / "cron-generate-lupin-lines.txt"
DATA      = "/DATA/projects-data/lupin"
HOME      = "/HOME"


@pytest.fixture
def fixed_places( monkeypatch ):
    """Pin the data folder, home and planning root, so the lines do not depend on the machine."""
    monkeypatch.setattr( paths, "data_dir", lambda root: pathlib.Path( DATA ) / "reuse-review" )
    monkeypatch.setattr( chs, "data_dir", lambda root=None, config=None: pathlib.Path( DATA ) / "code-health" )
    monkeypatch.setenv( "HOME", HOME )
    monkeypatch.setenv( "PLANNING_IS_PROMPTING_ROOT", "/PIP" )
    monkeypatch.setenv( "DEEPILY_DATA_DIR", "/DATA" )


def normalised_lines( root=REAL_ROOT ):
    """Return the generator's lines for the real registry, with the checkout path as a token."""
    lines, _tags, _legacy = cg.generate( root, { } )
    return [ line.replace( root, "<ROOT>" ) for line in lines ]


def test_lupins_generated_lines_are_the_ones_captured_before_the_repo_key_existed( fixed_places ):
    """Compare the real registry's lines with a golden file the unchanged generator wrote."""
    golden = GOLDEN.read_text().splitlines()
    assert len( golden ) == 18, "the header and Lupin's 17 job lines"
    assert normalised_lines() == golden


def second_repo_tree( tmp_path, monkeypatch, **extra ):
    """Write a registry with one Lupin job and one job of repo `other`; return the Lupin root."""
    monkeypatch.setattr( paths, "data_dir", lambda root: pathlib.Path( root ) / "data" )
    lupin  = { "job": "dup", "title": "dup", "owner": "cheech", "schedule": [ { "cron": "0 10 * * *" } ], "summary_path": "{root}/s.json", "cron_managed": True, "cron_tag": "dup-tag" }
    other  = { **lupin, "job": "dup-other", "cron_tag": "dup-other-tag", "schedule": [ { "cron": "5 * * * *" }, { "after_boot_seconds": 60 } ], "repo": "other",
               "repo_root": "/work/other", "cron_log": "{root}/code-health/dup/daily.log", **extra }
    doc    = { "schema": "job-registry/1", "defaults": { "run_env": { CONFIG: "config_path=/lupin.ini" } }, "jobs": [ lupin, other ] }
    ( tmp_path / "src" / "conf" ).mkdir( parents=True )
    ( tmp_path / "src" / "conf" / "job-registry.json" ).write_text( json.dumps( doc ) )
    return str( tmp_path )


CONFIG = cg.CONFIG_ENV


def test_a_second_repos_row_yields_lines_with_its_own_root_flag_and_config( tmp_path, monkeypatch ):
    root = second_repo_tree( tmp_path, monkeypatch, run={ "env": { CONFIG: "config_path=/other.ini" } } )
    lines, tags, _legacy = cg.generate( root, { } )
    lupin = [ l for l in lines if l.endswith( "# dup-tag" ) ]
    other = [ l for l in lines if l.endswith( "# dup-other-tag" ) ]
    script = f"{root}/src/scripts/cron-job.sh"
    assert lupin == [ f"0 10 * * * {script} dup cron >> {root}/io/jobs/dup/cron.log 2>&1 # dup-tag" ], "a row with no repo key is Lupin's, unchanged"
    assert other == [ f"5 * * * * {CONFIG}=config_path=/other.ini {script} dup-other cron --root /work/other >> /work/other/code-health/dup/daily.log 2>&1 # dup-other-tag",
                      f"@reboot sleep 60 && {CONFIG}=config_path=/other.ini {script} dup-other boot --root /work/other >> /work/other/code-health/dup/daily.log 2>&1 # dup-other-tag" ]
    assert "# dup-other-tag" in tags and not any( "/work/other" in l for l in lupin )


def test_a_second_repos_row_without_its_own_config_takes_the_registry_default( tmp_path, monkeypatch ):
    root = second_repo_tree( tmp_path, monkeypatch )
    other = [ l for l in cg.generate( root, { } )[ 0 ] if l.endswith( "# dup-other-tag" ) ]
    assert other and all( f"{CONFIG}=config_path=/lupin.ini " in l for l in other ), "no run.env config falls back to defaults.run_env"


def test_a_second_repos_log_default_expands_against_its_own_checkout( tmp_path, monkeypatch ):
    root  = second_repo_tree( tmp_path, monkeypatch )
    doc   = json.loads( ( tmp_path / "src" / "conf" / "job-registry.json" ).read_text() )
    del doc[ "jobs" ][ 1 ][ "cron_log" ]
    ( tmp_path / "src" / "conf" / "job-registry.json" ).write_text( json.dumps( doc ) )
    other = [ l for l in cg.generate( root, { } )[ 0 ] if l.endswith( "# dup-other-tag" ) ]
    assert all( " >> /work/other/io/jobs/dup-other/cron.log " in l for l in other )


def test_a_job_naming_another_repo_without_a_checkout_is_refused( tmp_path, monkeypatch ):
    root = second_repo_tree( tmp_path, monkeypatch )
    doc  = json.loads( ( tmp_path / "src" / "conf" / "job-registry.json" ).read_text() )
    del doc[ "jobs" ][ 1 ][ "repo_root" ]
    ( tmp_path / "src" / "conf" / "job-registry.json" ).write_text( json.dumps( doc ) )
    with pytest.raises( ValueError, match="dup-other names repo other but has no repo_root" ):
        cg.generate( root, { } )


def run_job_run( tree, extra, monkeypatch ):
    """Run job_run on the `alpha` job of the shared three-job tree; return the command it ran."""
    seen = {}
    monkeypatch.setattr( jrun.hs, "refresh_best_effort", lambda environ=None: None )

    def fake( command, **kw ):
        seen.update( command=command )
        return type( "R", (), { "returncode": 0, "stdout": "", "stderr": "" } )()

    assert jrun.main( [ "--job", "alpha", "--from-registry", "--trigger", "boot", *extra ], { "LUPIN_ROOT": str( tree ) }, fake ) == 0
    return seen[ "command" ]


def test_job_run_appends_the_root_flag_after_the_trigger_only_when_it_is_given( tree, monkeypatch ):
    plain = run_job_run( tree, [], monkeypatch )
    other = run_job_run( tree, [ "--root", "/work/other" ], monkeypatch )
    assert plain[ -2: ] == [ "--trigger", "reboot" ] and "--root" not in plain, "an installed line from before the flag existed runs the registry command unchanged"
    assert other == [ *plain, "--root", "/work/other" ]


def test_a_second_repos_data_placeholder_expands_to_its_own_data_folder_not_lupins( tmp_path, monkeypatch ):
    """The patched data_dir answers root/data, so Lupin's and the other repo's folders differ."""
    root = second_repo_tree( tmp_path, monkeypatch, cron_log="{data}/librarian/librarian.log" )
    lines, _tags, _legacy = cg.generate( root, { } )
    other = [ l for l in lines if l.endswith( "# dup-other-tag" ) ]
    assert len( other ) == 2, "one cron line and one boot line"
    for line in other:
        assert ">> /work/other/data/librarian/librarian.log 2>&1" in line
        assert str( tmp_path ) not in line.split( ">>" )[ 1 ], "no part of the log path is Lupin's data folder"


def entry_script_run( tmp_path, *extra ):
    """Run cron-job.sh under cron's empty environment on a probe job; return its stdout lines."""
    real = pathlib.Path( REAL_ROOT )
    root = tmp_path / "tree"
    ( root / "src" / "conf" ).mkdir( parents=True )
    for child in ( real / "src" ).iterdir():
        if child.name != "conf": ( root / "src" / child.name ).symlink_to( child )
    for name in ( "lupin-app.ini", "lupin-app-splainer.ini" ): ( root / "src" / "conf" / name ).symlink_to( real / "src" / "conf" / name )
    ( root / ".venv" ).symlink_to( sys.prefix )
    shipped = jr.load_registry( REAL_ROOT )
    probe   = { "job": "probe", "title": "probe", "owner": "cheech", "schedule": [], "summary_path": "{root}/io/jobs/probe/job-summary.json",
                "run": { "argv": [ "{python}", "-c", "import os, sys; print( 'argv', sys.argv[ 1: ], 'root', os.environ[ 'LUPIN_ROOT' ] )", "--trigger", "hand" ], "env": {} } }
    ( root / "src" / "conf" / "job-registry.json" ).write_text( json.dumps( { "schema": "job-registry/1", "defaults": shipped[ "defaults" ], "jobs": [ probe ] } ) )
    done = subprocess.run( [ "env", "-i", f"HOME={tmp_path}", f"DEEPILY_DATA_DIR={tmp_path / 'data'}", f"LUPIN_ROOT={root}", str( real / "src/scripts/cron-job.sh" ), "probe", "cron", *extra ],
                           capture_output=True, text=True, cwd=str( tmp_path ), timeout=120 )
    assert done.returncode == 0, done.stderr[ -600: ]
    return root, done.stdout


def test_the_entry_script_hands_its_extra_flags_to_job_run( tmp_path ):
    root, out = entry_script_run( tmp_path, "--root", "/work/other" )
    assert f"argv ['--trigger', 'cron', '--root', '/work/other'] root {root}" in out


def test_an_installed_line_with_no_root_flag_runs_as_it_did_and_uses_lupins_root( tmp_path ):
    """A line installed before the repo key has no --root; the job runs as before."""
    root, out = entry_script_run( tmp_path )
    assert f"argv ['--trigger', 'cron'] root {root}" in out and "--root" not in out
