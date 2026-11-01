"""
The guard that keeps unit tests off Rick's real Drive.

Both unit conftests install it. These tests drive the helper and prove it refuses the shipped token path
and a symlink to it. A real pytest in a subprocess proves a test that swallows the refusal still fails.
"""

import os
import subprocess
import sys
import textwrap

import pytest

from cosa.utils.drive_publisher import DrivePublishError, DrivePublisher
from tests.helpers import no_real_drive


@pytest.fixture
def shipped( tmp_path ):
    """A stand-in for the shipped token file, which need not exist."""
    return str( tmp_path / "keys" / "google-drive-oauth-token.json" )


@pytest.fixture
def violations( shipped ):
    """Install the guard on a private monkeypatch, guarding the stand-in."""
    with pytest.MonkeyPatch.context() as private:
        yield no_real_drive.install( private, shipped=shipped )


def test_the_shipped_token_path_is_refused_and_recorded( violations, shipped ):
    with pytest.raises( AssertionError, match="real Drive service" ):
        DrivePublisher( shipped, "Folder" )
    assert violations == [ shipped ]


def test_a_symlink_to_the_token_is_refused_too( violations, shipped, tmp_path ):
    link = tmp_path / "innocent-name.json"
    link.symlink_to( shipped )
    with pytest.raises( AssertionError, match="real Drive service" ):
        DrivePublisher( str( link ), "Folder" )
    assert violations == [ str( link ) ]


def test_a_dotted_path_to_the_token_is_refused_too( violations, shipped, tmp_path ):
    with pytest.raises( AssertionError, match="real Drive service" ):
        DrivePublisher( str( tmp_path / "keys" / ".." / "keys" / "google-drive-oauth-token.json" ), "Folder" )
    assert len( violations ) == 1


def test_any_other_token_path_reaches_the_real_method( violations, tmp_path ):
    with pytest.raises( DrivePublishError, match="token file missing" ):
        DrivePublisher( str( tmp_path / "other-token.json" ), "Folder" )
    assert violations == []


def test_an_injected_service_never_builds_anything( violations, shipped ):
    DrivePublisher( shipped, "Folder", service=object() )
    assert violations == []


def test_the_autouse_guard_is_installed_in_this_tree():
    from cosa.utils import drive_publisher
    assert drive_publisher.DrivePublisher._build_service.__name__ == "guarded"


def test_the_ini_names_the_token_the_guard_protects():
    import cosa.utils.util as cu
    assert no_real_drive.shipped_token_path() == os.path.realpath( cu.get_project_root() + "/src/conf/keys/google-drive-oauth-token.json" )


# ── a test that swallows the refusal must still fail ─────────────────────────

_CONFTEST = """
from tests.helpers.no_real_drive import guard_fixture
_guard = guard_fixture()
"""

_SWALLOWER = """
from cosa.utils.drive_publisher import DrivePublisher
from tests.helpers import no_real_drive


def test_that_swallows_the_refusal():
    try:
        DrivePublisher( no_real_drive.shipped_token_path(), "Folder" )
    except Exception:
        pass   # the Drive hook does exactly this, and the test below still has to fail
"""

_INNOCENT = """
import pytest
from cosa.utils.drive_publisher import DrivePublishError, DrivePublisher


def test_with_its_own_token_path(tmp_path):
    with pytest.raises( DrivePublishError ):
        DrivePublisher( str( tmp_path / "mine.json" ), "Folder" )
"""


def _run_pytest_in( directory, test_source ):
    """Run a real pytest in a scratch directory that has the shared guard as its only conftest."""
    (directory / "conftest.py").write_text( textwrap.dedent( _CONFTEST ) )
    (directory / "test_sample.py").write_text( textwrap.dedent( test_source ) )
    return subprocess.run(
        [ sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "--rootdir", str( directory ), str( directory / "test_sample.py" ) ],
        capture_output=True, text=True, cwd=str( directory ), env=os.environ,
    )


def test_a_test_that_swallows_the_refusal_still_fails_at_teardown( tmp_path ):
    run = _run_pytest_in( tmp_path, _SWALLOWER )
    assert run.returncode != 0, run.stdout + run.stderr
    assert "1 passed, 1 error" in run.stdout, run.stdout
    assert "unit test reached the real Drive token" in run.stdout, run.stdout


def test_a_test_with_its_own_token_path_passes_under_the_same_guard( tmp_path ):
    run = _run_pytest_in( tmp_path, _INNOCENT )
    assert run.returncode == 0 and "1 passed" in run.stdout, run.stdout + run.stderr
