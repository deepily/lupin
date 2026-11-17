"""
Unit tests for the dated census of Lupin-specific couplings (cosa.repo.coupling_census).
"""
import datetime
import subprocess

import pytest

import cosa.repo.coupling_census as cc
import cosa.utils.util as cu

NOW = datetime.datetime( 2026, 11, 11, 12, 0, tzinfo=datetime.timezone.utc )


def make_repo( tmp_path, files ):
    """Build a one-commit git repo holding the given { path: text } files, and return its root."""
    for name, text in files.items():
        target = tmp_path / name
        target.parent.mkdir( parents=True, exist_ok=True )
        if isinstance( text, bytes ): target.write_bytes( text )
        else: target.write_text( text )
    git = lambda *a: subprocess.run( [ "git", "-c", "user.email=t@t", "-c", "user.name=t", *a ], cwd=tmp_path, check=True, capture_output=True )
    git( "init", "-q" ); git( "add", "-A" ); git( "commit", "-q", "-m", "x" )
    return tmp_path


def needle( text, group=1, kind="pin", maps_to="a pin" ):
    return { "group": group, "needle": text, "kind": kind, "maps_to": maps_to }


def test_every_shipped_needle_maps_to_an_ini_key_a_pin_or_a_registry_key():
    cc.validate_needles( cc.NEEDLES )
    assert len( cc.NEEDLES ) == 22 and { n[ "kind" ] for n in cc.NEEDLES } <= set( cc.KINDS )


def test_validate_needles_refuses_a_bad_kind_a_blank_mapping_and_a_duplicate():
    with pytest.raises( ValueError, match="kind 'bogus'" ): cc.validate_needles( [ needle( "a", kind="bogus" ) ] )
    with pytest.raises( ValueError, match="maps_to is blank" ): cc.validate_needles( [ needle( "a", maps_to="  " ) ] )
    with pytest.raises( ValueError, match="listed twice" ): cc.validate_needles( [ needle( "a" ), needle( "a" ) ] )
    cc.validate_needles( [ needle( "a", group=1 ), needle( "a", group=2 ) ] )


def test_population_leaves_out_the_three_vendored_directory_names_only():
    assert [ cc.in_population( p ) for p in ( "src/a.py", "src/cosa/.venv/x.py", "web/node_modules/y.js", "z/site-packages/q.py", "src/venv_notes.py" ) ] == [ True, False, False, False, True ]


def test_the_script_never_counts_its_own_needle_list(tmp_path):
    root = make_repo( tmp_path, { cc.SELF_PATH: "def is_lupin_tree\n", "a.py": "def is_lupin_tree\n" } )
    assert cc.in_population( cc.SELF_PATH ) is False
    out = cc.run( root, NOW, needles=[ needle( "def is_lupin_tree" ) ], controls=[ { "needle": "def is_lupin_tree", "path": "a.py", "line": 1 } ] )
    assert "| 1 | `def is_lupin_tree` | 1 | 1 | `a.py:1` |" in out and cc.SELF_PATH not in out


def test_is_code_rejects_documents_backups_tests_and_history():
    assert [ cc.is_code( p ) for p in ( "src/a.py", "a.md", "src/cosa/history.md.backup-1", ".backup-x/a.py", "src/tests/u.py", "src/cosa/tests/u.py", "src/docs/a.json", "history/a.json", "src/conf/a.ini" ) ] == [ True, False, False, False, False, False, False, False, True ]


def test_scan_finds_fixed_strings_per_line_sorted_and_counts_unreadable_files(tmp_path):
    root = make_repo( tmp_path, { "b.py": "x\nfoo.bar and foo.bar\n", "a.py": "foo.bar\nFOOxbar\n", "bin.dat": b"\xff\xfe\x00foo.bar", "link.py": "x" } )
    ( root / "link.py" ).unlink(); ( root / "link.py" ).symlink_to( root / "missing" )
    got = cc.scan( root, [ "b.py", "a.py", "bin.dat", "link.py" ], [ needle( "foo.bar" ), needle( "zzz" ) ] )
    assert got[ "hits" ] == [ ( "foo.bar", "a.py", 1 ), ( "foo.bar", "b.py", 2 ) ]          # one hit per line; "." is not a wildcard
    assert got[ "unreadable" ] == 2


def test_check_controls_passes_on_the_known_line_and_names_each_failure():
    hits = [ ( "n", "f.py", 3 ), ( "n", "f.py", 9 ) ]
    cc.check_controls( hits, [ { "needle": "n", "path": "f.py", "line": 3 } ] )
    with pytest.raises( cc.ControlFailed, match="first hit in f.py is line 3, expected 9" ): cc.check_controls( hits, [ { "needle": "n", "path": "f.py", "line": 9 } ] )
    with pytest.raises( cc.ControlFailed, match="found nothing in g.py" ): cc.check_controls( hits, [ { "needle": "n", "path": "g.py", "line": 1 } ] )


def test_render_counts_code_hits_apart_from_tests_and_states_the_population():
    hits = [ ( "n", "a.py", 1 ), ( "n", "a.py", 2 ), ( "n", "b.py", 5 ), ( "n", "c.py", 6 ), ( "n", "src/tests/t.py", 1 ), ( "n", "d.md", 1 ) ]
    stats = { "stamp": "T", "sha": "abc", "tracked": 10, "population": 8, "scanned": 7, "unreadable": 1, "controls": 2 }
    out = cc.render( hits, [ needle( "n", group=4, kind="ini", maps_to="the key" ), needle( "none" ) ], stats )
    assert "Census taken T at commit `abc`." in out
    assert "| 4 | `n` | 4 | 3 | `a.py:1`, `a.py:2`, `b.py:5` | ini: the key |" in out
    assert "| 1 | `none` | 0 | 0 | none in code | pin: a pin |" in out
    assert "10 tracked files, 2 left out" in out and "8 counted, 7 read as UTF-8 text, 1 not readable" in out and f"2 of {len( cc.CONTROLS )}" in out


def test_run_on_a_small_tree_gives_the_table_and_a_failed_control_refuses(tmp_path):
    root = make_repo( tmp_path, { "a.py": "x = 1\nfoo\n", "vend/.venv/b.py": "foo\n" } )
    ctl = [ { "needle": "foo", "path": "a.py", "line": 2 } ]
    out = cc.run( root, NOW, needles=[ needle( "foo" ) ], controls=ctl )
    assert "2026-11-11T12:00:00+00:00" in out and "| 1 | `foo` | 1 | 1 | `a.py:2` |" in out and "2 tracked files, 1 left out" in out
    with pytest.raises( cc.ControlFailed ): cc.run( root, NOW, needles=[ needle( "foo" ) ], controls=[ { "needle": "foo", "path": "a.py", "line": 1 } ] )
    with pytest.raises( ValueError ): cc.run( root, NOW, needles=[ needle( "foo", kind="x" ) ], controls=ctl )
    assert cc.run( root, NOW, needles=[ needle( "foo" ) ], controls=ctl ).startswith( f"Census taken 2026-11-11T12:00:00+00:00 at commit `{subprocess.run( [ 'git', 'rev-parse', '--short', 'HEAD' ], cwd=root, capture_output=True, text=True ).stdout.strip()}`" )


def test_the_real_tree_finds_both_known_couplings_before_it_prints_anything():
    out = cc.run( cu.get_project_root(), NOW )
    assert "`src/cosa/repo/symindex/spec.py:79`" in out and "`src/cosa/repo/symindex/spec.py:14`" in out
    assert cc.SELF_PATH not in out                                         # no first-location list names the script that holds the needles
    assert "| 1 | `def is_lupin_tree` | 1 | 1 |" in out


def test_main_prints_the_census_and_returns_1_with_a_message_when_refused(tmp_path, tmp_path_factory, capsys):
    root = make_repo( tmp_path, { "a.py": "x\n" } )
    assert cc.main( [ "--root", str( root ) ] ) == 1                       # the shipped controls cannot be found in this tree
    assert "census refused: control" in capsys.readouterr().err
    assert cc.main( [] ) == 0
    assert "Positive controls passed: 2 of 2." in capsys.readouterr().out
    bare = tmp_path_factory.mktemp( "plain" )
    assert cc.main( [ "--root", str( bare ) ] ) == 1
    assert "git ls-files failed" in capsys.readouterr().err
