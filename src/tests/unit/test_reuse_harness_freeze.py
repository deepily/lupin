"""
Unit tests of the run spec builder and its git port.

The map tests feed real test source through the real parser.
The git tests build a real repository, so the port is proven against git's own answers.
Those are a commit main holds, a commit it does not, and a file edited after the freeze.
"""
import subprocess

import pytest

from lupin_mcp.reuse_harness import errors as err
from lupin_mcp.reuse_harness import freeze
from lupin_mcp.reuse_harness import gitrepo

LIST_TEXT = "| F01 | a |\n| F02 (opt) | b |\nnot a row | F09 |\n"
GOOD_TEST = 'import pytest\n\n@pytest.mark.feature( "F01" )\ndef test_one():\n    pass\n\n@pytest.mark.feature( "F02" )\n@pytest.mark.slow\nasync def test_two():\n    pass\n\ndef helper():\n    pass\n'


def code_of( call ):
    """Return the code of the HarnessError a call raises."""
    with pytest.raises( err.HarnessError ) as caught: call()
    return caught.value.code


def test_feature_ids_read_only_table_rows_in_order():
    assert freeze.feature_ids( LIST_TEXT ) == [ "F01", "F02" ]


def test_collect_tests_maps_each_test_function_to_its_markers_and_skips_helpers():
    tests = freeze.collect_tests( { "d/test_a.py": GOOD_TEST, "d/conftest.py": "def test_not_read():\n    pass\n", "d/readme.txt": "x" } )
    assert tests == { "d/test_a.py::test_one": [ "F01" ], "d/test_a.py::test_two": [ "F02" ] }


def test_collect_tests_gives_an_unmarked_test_an_empty_list_and_ignores_other_marks():
    source = 'import pytest\n\n@pytest.mark.slow\ndef test_x():\n    pass\n\n@pytest.mark.feature( some_name )\ndef test_y():\n    pass\n\n@feature( "F01" )\ndef test_z():\n    pass\n'
    assert freeze.collect_tests( { "d/test_a.py": source } ) == { "d/test_a.py::test_x": [], "d/test_a.py::test_y": [], "d/test_a.py::test_z": [] }


def test_collect_tests_refuses_a_test_class_because_its_methods_would_go_uncounted():
    assert code_of( lambda: freeze.collect_tests( { "d/test_a.py": "class TestBox:\n    def test_m(self):\n        pass\n" } ) ) == err.FEATURE_MAP


def test_collect_tests_allows_a_class_that_is_not_a_test_class():
    assert freeze.collect_tests( { "d/test_a.py": "class Helper:\n    pass\n" } ) == {}


def test_check_feature_map_passes_a_closed_map():
    assert freeze.check_feature_map( { "t1": [ "F01" ], "t2": [ "F01", "F02" ] }, [ "F01", "F02" ] ) is None


@pytest.mark.parametrize( "tests, ids, word", [
    ( {}, [ "F01" ], "no acceptance tests" ),
    ( { "t1": [ "F01" ], "t2": [] }, [ "F01" ], "t2" ),
    ( { "t1": [ "F01", "F99" ] }, [ "F01" ], "F99" ),
    ( { "t1": [ "F01" ] }, [ "F01", "F02" ], "F02" ),
] )
def test_check_feature_map_names_each_way_the_map_fails_to_close( tests, ids, word ):
    with pytest.raises( err.HarnessError ) as caught: freeze.check_feature_map( tests, ids )
    assert caught.value.code == err.FEATURE_MAP and word in caught.value.detail


def git_in( root, *args ):
    """Run git in a test repository and return its output."""
    return subprocess.run( [ "git", "-C", str( root ), "-c", "user.name=t", "-c", "user.email=t@example.com", *args ], check=True, capture_output=True, text=True ).stdout.strip()


@pytest.fixture
def repo( tmp_path ):
    """Build a repository: a frozen commit, a later commit on main and a side commit off main."""
    git_in( tmp_path, "init", "-q", "-b", "main" )
    tests = tmp_path / freeze.TEST_DIR
    tests.mkdir( parents=True )
    ( tests / "test_a.py" ).write_text( 'import pytest\n\n@pytest.mark.feature( "F01" )\ndef test_one():\n    pass\n\n@pytest.mark.feature( "F02" )\ndef test_two():\n    pass\n' )
    ( tests / "sub" ).mkdir()
    ( tests / "sub" / "test_deep.py" ).write_text( "def test_deep():\n    pass\n" )
    ( tests / "README.md" ).write_text( "x" )
    listing = tmp_path / freeze.FEATURE_LIST
    listing.parent.mkdir( parents=True )
    listing.write_text( LIST_TEXT )
    git_in( tmp_path, "add", "." )
    git_in( tmp_path, "commit", "-q", "-m", "frozen" )
    frozen = git_in( tmp_path, "rev-parse", "HEAD" )
    ( tests / "test_a.py" ).write_text( 'import pytest\n\n@pytest.mark.feature( "F01" )\ndef test_later():\n    pass\n' )
    ( tests / "test_new.py" ).write_text( 'import pytest\n\n@pytest.mark.feature( "F02" )\ndef test_added_after_the_freeze():\n    pass\n' )
    listing.write_text( LIST_TEXT + "| F03 | added after the freeze |\n" )
    git_in( tmp_path, "add", "." )
    git_in( tmp_path, "commit", "-q", "-m", "later" )
    git_in( tmp_path, "checkout", "-q", "--detach", frozen )
    ( tests / "test_b.py" ).write_text( "x = 1\n" )
    git_in( tmp_path, "add", "." )
    git_in( tmp_path, "commit", "-q", "-m", "side" )
    side = git_in( tmp_path, "rev-parse", "HEAD" )
    git_in( tmp_path, "checkout", "-q", "main" )
    return { "root" : tmp_path, "frozen" : frozen, "side" : side, "git" : gitrepo.GitRepo( str( tmp_path ) ) }


def test_git_port_resolves_a_short_sha_and_refuses_an_unknown_one( repo ):
    assert repo[ "git" ].resolve( repo[ "frozen" ][ :10 ] ) == repo[ "frozen" ]
    with pytest.raises( RuntimeError ): repo[ "git" ].resolve( "0" * 40 )


def test_git_port_says_which_commits_main_holds( repo ):
    assert repo[ "git" ].is_ancestor( repo[ "frozen" ], "main" ) is True
    assert repo[ "git" ].is_ancestor( repo[ "side" ], "main" ) is False


def test_git_port_lists_files_directly_in_a_folder_at_the_commit_not_in_subfolders( repo ):
    assert repo[ "git" ].list_at( repo[ "frozen" ], freeze.TEST_DIR ) == [ f"{freeze.TEST_DIR}/README.md", f"{freeze.TEST_DIR}/test_a.py" ]


def test_git_port_reads_the_file_as_the_commit_held_it_not_as_main_holds_it( repo ):
    assert "F01" in repo[ "git" ].file_at( repo[ "frozen" ], f"{freeze.TEST_DIR}/test_a.py" )
    assert "test_later" in ( repo[ "root" ] / freeze.TEST_DIR / "test_a.py" ).read_text()
    with pytest.raises( RuntimeError ): repo[ "git" ].file_at( repo[ "frozen" ], "no/such/file" )


def test_build_spec_reads_the_frozen_commit_and_not_the_tip_of_main( repo ):
    spec = freeze.build_spec( repo[ "git" ], "r1", "with", "model-x", repo[ "frozen" ][ :12 ], 12.5 )
    assert spec == { "run_id" : "r1", "arm" : "with", "model_id" : "model-x", "server_commit" : repo[ "frozen" ], "cap_seat_hours" : 12.5,
                     "test_ids" : [ f"{freeze.TEST_DIR}/test_a.py::test_one", f"{freeze.TEST_DIR}/test_a.py::test_two" ] }


def test_build_spec_at_the_freeze_ignores_a_test_file_and_a_feature_row_main_gained_later( repo ):
    later = freeze.build_spec( repo[ "git" ], "r1", "with", "m", repo[ "frozen" ], 1 )
    assert later[ "test_ids" ] == [ f"{freeze.TEST_DIR}/test_a.py::test_one", f"{freeze.TEST_DIR}/test_a.py::test_two" ]
    assert "test_added_after_the_freeze" not in " ".join( later[ "test_ids" ] )


def test_build_spec_refuses_a_commit_main_does_not_hold( repo ):
    assert code_of( lambda: freeze.build_spec( repo[ "git" ], "r1", "with", "m", repo[ "side" ], 1 ) ) == err.NOT_FROZEN


def test_build_spec_refuses_a_bad_arm_through_check_spec( repo ):
    assert code_of( lambda: freeze.build_spec( repo[ "git" ], "r1", "both", "m", repo[ "frozen" ], 1 ) ) == err.BAD_ARM


def test_build_spec_refuses_a_map_that_does_not_close( repo ):
    assert code_of( lambda: freeze.build_spec( repo[ "git" ], "r1", "with", "m", "main", 1 ) ) == err.FEATURE_MAP
