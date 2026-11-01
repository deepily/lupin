"""
A unit test must never build the Google Drive service from the shipped token.

The shipped INI has publishing on. A test that runs a podcast job without its own config reads that INI.
The job would then build the real Drive service and could write to Rick's Drive.

The guard watches DrivePublisher._build_service. A call whose token path resolves to the INI's token file
is recorded and refused, and the test fails at teardown. The refusal alone is not enough: the Drive hook
catches every exception, so a test would pass with the failure hidden in its card text.

The comparison is between resolved real paths, so a symlink to the token cannot get past it. A test with
its own token path, such as a temp file, is not touched. That is how the publisher's own tests build the
service with fake Google modules.
"""

import os

import pytest

DEFAULT_TOKEN_REL_PATH = "/src/conf/keys/google-drive-oauth-token.json"
TOKEN_INI_KEY          = "podcast drive token path"

_shipped_token_path = None


def shipped_token_path():
    """
    Name the token file the shipped INI points at, as a resolved real path.

    Requires:
        - LUPIN_ROOT and LUPIN_CONFIG_MGR_CLI_ARGS are set, as the unit conftests set them

    Ensures:
        - returns realpath( project root + the INI's token path ); the file need not exist
        - the answer is computed once per process

    Raises:
        - nothing
    """
    global _shipped_token_path
    if _shipped_token_path is None:
        import cosa.utils.util as cu
        from cosa.config.configuration_manager import ConfigurationManager
        rel = ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" ).get( TOKEN_INI_KEY, default=DEFAULT_TOKEN_REL_PATH, silent=True )
        _shipped_token_path = os.path.realpath( cu.get_project_root() + rel )
    return _shipped_token_path


def install( monkeypatch, shipped=None ):
    """
    Put the guard on DrivePublisher._build_service for the life of one monkeypatch.

    Requires:
        - monkeypatch is a pytest MonkeyPatch
        - shipped is the token path to guard, or None for the INI's

    Ensures:
        - a build whose token path resolves to the guarded file is recorded in the returned list and refused
        - any other token path reaches the real method unchanged

    Raises:
        - nothing
    """
    from cosa.utils import drive_publisher
    real       = drive_publisher.DrivePublisher._build_service
    violations = []

    def guarded( self ):
        if os.path.realpath( self.token_path ) == ( os.path.realpath( shipped ) if shipped is not None else shipped_token_path() ):
            violations.append( self.token_path )
            raise AssertionError( f"a unit test tried to build the real Drive service from {self.token_path}" )
        return real( self )

    monkeypatch.setattr( drive_publisher.DrivePublisher, "_build_service", guarded )
    return violations


def guard_fixture():
    """
    Build the autouse fixture both unit conftests share.

    Requires:
        - nothing; cosa.utils.drive_publisher is imported only when the fixture runs

    Ensures:
        - returns a pytest fixture that fails any test whose DrivePublisher builds the service from the shipped token
        - the failure is raised at teardown, so a broad except inside the code under test cannot hide it

    Raises:
        - nothing
    """
    @pytest.fixture( autouse=True )
    def _no_unit_test_builds_the_real_drive_service( monkeypatch ):
        violations = install( monkeypatch )
        yield
        assert violations == [], f"unit test reached the real Drive token: {violations}. Patch drive_hook._load_config or _make_publisher."
    return _no_unit_test_builds_the_real_drive_service
