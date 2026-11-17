"""Census: no code-health job path resolves under `io/`; the registry reads the moved folder."""
import json
import subprocess

import cosa.utils.util as cu
from cosa.rest import job_registry as jr

NEEDLES = ( "io/", "/io", '"io"' )
SCOPE   = ( "src/lupin_mcp/duplicate_check_*.py", "src/cosa/repo/duplicate_check/", "src/cosa/rest/routers/duplicate_check_status.py" )
HISTORY = "src/cosa/repo/duplicate_check/proof/proof_run.py"      # two comments that name the old folders as history; left as they are


def census( root, scope=SCOPE ):
    """Ensures: returns ( path, line, text ) of each tracked line holding a needle."""
    cmd = [ "git", "grep", "-n", "-F", *[ a for n in NEEDLES for a in ( "-e", n ) ], "--", *scope ]
    out = subprocess.run( cmd, cwd=root, capture_output=True, text=True ).stdout.splitlines()
    return [ ( p, int( n ), t ) for p, n, t in ( l.split( ":", 2 ) for l in out ) ]


def test_the_census_finds_a_planted_io_line_before_it_counts_the_real_tree( tmp_path ):
    """Positive control: the same search must see a line it is told about."""
    subprocess.run( [ "git", "init", "-q" ], cwd=tmp_path, check=True )
    ( tmp_path / "duplicate_check_x.py" ).write_text( 'a = 1\nfolder = root + "/io/x"\n' )
    subprocess.run( [ "git", "add", "duplicate_check_x.py" ], cwd=tmp_path, check=True )
    assert census( tmp_path, scope=( "duplicate_check_*.py", ) ) == [ ( "duplicate_check_x.py", 2, 'folder = root + "/io/x"' ) ]


def test_every_code_health_job_code_line_is_off_io_but_the_two_history_comments():
    hits = census( cu.get_project_root() )
    assert [ ( p, n ) for p, n, _ in hits if p != HISTORY ] == [], "a code line still names io/"
    assert [ n for p, n, t in hits if p == HISTORY ] == [ 11, 12 ] and all( t.startswith( "#" ) for p, _, t in hits )


def test_the_duplicate_check_registry_entry_has_no_io_path_and_resolves_under_the_data_folder( tmp_path, monkeypatch ):
    monkeypatch.setenv( "DEEPILY_DATA_DIR", str( tmp_path ) )
    registry = json.load( open( f"{cu.get_project_root()}/src/conf/job-registry.json", encoding="utf-8" ) )
    entry    = [ j for j in registry[ "jobs" ] if j[ "job" ] == "duplicate-check" ][ 0 ]
    paths    = [ entry[ "summary_path" ], entry[ "lock_path" ], entry[ "cron_log" ], *[ e[ "path" ] for e in entry[ "evidence" ] ] ]
    assert len( paths ) == 5 and not [ p for p in paths if "io/" in p ]
    assert jr.resolve_path( entry[ "summary_path" ], "/x/myrepo", "/d" ) == tmp_path / "myrepo" / "code-health" / "duplicate-check-daily" / "job-summary.json"
