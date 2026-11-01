"""
The guard that keeps unit tests off Rick's real Drive.

Both unit conftests install it. These tests drive the helper itself and prove it refuses the shipped token
path, records the attempt, and leaves other token paths alone.
"""

import pytest

from cosa.utils.drive_publisher import DrivePublishError, DrivePublisher
from tests.helpers import no_real_drive


@pytest.fixture
def violations( monkeypatch ):
    """Install the guard on a private monkeypatch and hand back its record."""
    with pytest.MonkeyPatch.context() as private:
        yield no_real_drive.install( private )


def test_the_shipped_token_path_is_refused_and_recorded( violations ):
    path = "/any/root/src/conf/keys/google-drive-oauth-token.json"
    with pytest.raises( AssertionError, match="real Drive service" ):
        DrivePublisher( path, "Folder" )
    assert violations == [ path ]


def test_any_other_token_path_reaches_the_real_method( violations, tmp_path ):
    with pytest.raises( DrivePublishError, match="token file missing" ):
        DrivePublisher( str( tmp_path / "other-token.json" ), "Folder" )
    assert violations == []


def test_an_injected_service_never_builds_anything( violations ):
    DrivePublisher( "/any/root/src/conf/keys/google-drive-oauth-token.json", "Folder", service=object() )
    assert violations == []


def test_the_autouse_guard_is_installed_in_this_tree( ):
    from cosa.utils import drive_publisher
    assert drive_publisher.DrivePublisher._build_service.__name__ == "guarded"
