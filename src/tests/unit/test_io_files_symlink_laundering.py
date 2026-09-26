"""
Unit tests for row 27398998: the io endpoint judges a path where it LANDS, not as typed.

`get_io_file` used `os.path.normpath`, which never follows a symlink. A link with an
innocent name planted inside `io/` therefore passed both guards — the containment check
and the secrets blocklist — while `open()` read the file it pointed at. Same defect
family as rows 9ab0bddb and 0cd3811a; the doc-viewer side was fixed in 2f51dda2 and
this is the io side of it.

Two holes are covered here, because the same line carried both:
  · a symlink's target was never examined at all;
  · containment was a BARE `startswith( io_base )`, which also admits a sibling
    directory whose name merely begins with it (`io-archive/`).

Every symlink is built under pytest's `tmp_path`, never in the repo. The endpoint
coroutine is invoked directly with `cu.get_project_root` monkeypatched, the same way
`src/cosa/tests/unit/rest/test_io_files_router.py` does it.

Tier: :7999-eligible unit — no server, no persistent state, no writes outside tmp_path,
milliseconds.
"""

import asyncio
import os

import pytest
from fastapi import HTTPException

import cosa.rest.routers.io_files as io_files


# Deliberately NOT shaped like a real credential. The blocklist this file exercises is
# FILENAME-based, so the bytes behind a blocked name are irrelevant to every assertion --
# and a fixture that looks like an AWS key trips the repo's own secret scanner at commit.
LEAK_CANARY = "canary-27398998-this-file-should-never-be-served\n"
ORDINARY = "# an ordinary io report\n"
OUTSIDE  = "# outside the io root\n"
SIBLING  = "# in a sibling directory, not in io/\n"


@pytest.fixture
def project_root( tmp_path ):
    """
    A project root whose io/ directory holds an ordinary file and four symlinks.

    Ensures:
        - root/io/report.md            an ordinary in-scope file
        - root/io/.env                 holds LEAK_CANARY; blocked by name (^\\.env(\\.|$))
        - root/.ssh/id_rsa             holds LEAK_CANARY; outside io/ entirely
        - root/io-archive/leak.md      holds SIBLING; a sibling whose name starts with "io"
        - root/io/notes.json  -> io/.env          same-scope laundering (the row's case)
        - root/io/key.md      -> .ssh/id_rsa      escape laundering
        - root/io/nearby.md   -> io-archive/leak.md   sibling-prefix laundering
        - root/io/alias.md    -> io/report.md     BENIGN link, must still be served
    """
    root = tmp_path / "proj"
    ( root / "io" ).mkdir( parents=True )
    ( root / ".ssh" ).mkdir()
    ( root / "io-archive" ).mkdir()

    ( root / "io" / "report.md"   ).write_text( ORDINARY )
    ( root / "io" / ".env"        ).write_text( LEAK_CANARY )
    ( root / ".ssh" / "id_rsa"    ).write_text( LEAK_CANARY )
    ( root / "io-archive" / "leak.md" ).write_text( SIBLING )
    ( tmp_path / "elsewhere.md"   ).write_text( OUTSIDE )

    os.symlink( root / "io" / ".env",            root / "io" / "notes.json" )
    os.symlink( root / ".ssh" / "id_rsa",        root / "io" / "key.md"     )
    os.symlink( root / "io-archive" / "leak.md", root / "io" / "nearby.md"  )
    os.symlink( root / "io" / "report.md",       root / "io" / "alias.md"   )
    os.symlink( tmp_path / "elsewhere.md",       root / "io" / "outside.md" )
    return root


@pytest.fixture
def patched_root( project_root, monkeypatch ):
    """Point the endpoint's project root at the tmp fixture."""
    monkeypatch.setattr( io_files.cu, "get_project_root", lambda: str( project_root ) )
    return project_root


def _get( path, download=False ):
    """Invoke the endpoint coroutine directly; return the response object."""
    return asyncio.run(
        io_files.get_io_file( path=path, download=download, current_user={ "uid": "test" } )
    )


def _refused( path ):
    """Return the HTTPException the door raises for `path`; fail the test if it serves."""
    with pytest.raises( HTTPException ) as exc_info:
        _get( path )
    return exc_info.value


class TestPositiveControlsFirst:
    """
    Run FIRST and deliberately so. A door wired to refuse everything would make every
    negative below pass for the wrong reason, and this file's whole subject is a guard
    that said yes when it should have said no.
    """

    def test_an_ordinary_io_file_is_served( self, patched_root ):
        response = _get( "report.md" )
        assert response.status_code == 200
        assert ORDINARY.strip() in response.body.decode()

    def test_a_symlink_landing_on_an_allowed_io_file_is_served( self, patched_root ):
        """The fix must not refuse every link — only the ones that land somewhere blocked."""
        response = _get( "alias.md" )
        assert response.status_code == 200
        assert ORDINARY.strip() in response.body.decode()

    def test_the_io_root_listing_is_still_served( self, patched_root ):
        response = _get( "" )
        assert response.status_code == 200


class TestLaunderingRefused:

    def test_symlink_to_a_blocklisted_file_in_io_is_refused( self, patched_root ):
        """
        The row's own case: `notes.json` is a clean name, `.env` is not, and normpath
        never looked. Asserts the payload is absent as well as the status, because a
        400 whose detail echoed the file would leak it anyway.
        """
        exc = _refused( "notes.json" )
        assert exc.status_code == 400
        assert "blocklist" in exc.detail.lower()
        assert "canary-27398998" not in exc.detail

    def test_symlink_escaping_the_io_root_is_refused( self, patched_root ):
        exc = _refused( "key.md" )
        assert exc.status_code == 400
        assert "within io/" in exc.detail
        assert "canary-27398998" not in exc.detail

    def test_symlink_into_a_sibling_whose_name_starts_with_io_is_refused( self, patched_root ):
        """
        The second hole in the same line. A bare `startswith( io_base )` admits
        `/proj/io-archive/...` because it is a string prefix of nothing it should be —
        the separator is what makes it a directory boundary rather than a substring.
        """
        exc = _refused( "nearby.md" )
        assert exc.status_code == 400
        assert "within io/" in exc.detail

    def test_symlink_to_a_file_outside_the_project_is_refused( self, patched_root ):
        exc = _refused( "outside.md" )
        assert exc.status_code == 400
        assert "within io/" in exc.detail

    def test_a_download_request_cannot_bypass_the_landed_check( self, patched_root ):
        """`?download=true` takes a different response branch; the guards run before it."""
        exc = _refused( "notes.json" )
        assert exc.status_code == 400
        with pytest.raises( HTTPException ) as exc_info:
            _get( "notes.json", download=True )
        assert exc_info.value.status_code == 400


class TestTypedGuardsStillApply:
    """The landed check is defence in depth — it ADDS to the typed checks, not replaces."""

    def test_a_blocklisted_name_typed_directly_is_still_refused( self, patched_root ):
        exc = _refused( ".env" )
        assert exc.status_code == 400
        assert "blocklist" in exc.detail.lower()

    def test_dot_dot_traversal_is_still_refused( self, patched_root ):
        exc = _refused( "../.ssh/id_rsa" )
        assert exc.status_code == 400
        assert "within io/" in exc.detail


class TestTheIoRootMayItselfBeASymlink:
    """
    Resolving the ROOT is load-bearing, not symmetry. If io/ is a symlink and only the
    child is resolved, every containment comparison holds a resolved child against an
    unresolved root — two spellings of one directory — and the door refuses everything.
    """

    def test_an_ordinary_file_is_served_when_io_itself_is_a_symlink( self, tmp_path, monkeypatch ):
        real_root = tmp_path / "real"
        ( real_root / "io" ).mkdir( parents=True )
        ( real_root / "io" / "report.md" ).write_text( ORDINARY )

        link_root = tmp_path / "linked"
        link_root.mkdir()
        os.symlink( real_root / "io", link_root / "io" )

        monkeypatch.setattr( io_files.cu, "get_project_root", lambda: str( link_root ) )
        response = _get( "report.md" )
        assert response.status_code == 200
        assert ORDINARY.strip() in response.body.decode()

    def test_laundering_is_still_refused_when_io_itself_is_a_symlink( self, tmp_path, monkeypatch ):
        real_root = tmp_path / "real"
        ( real_root / "io" ).mkdir( parents=True )
        ( real_root / "io" / ".env" ).write_text( LEAK_CANARY )
        os.symlink( real_root / "io" / ".env", real_root / "io" / "notes.json" )

        link_root = tmp_path / "linked"
        link_root.mkdir()
        os.symlink( real_root / "io", link_root / "io" )

        monkeypatch.setattr( io_files.cu, "get_project_root", lambda: str( link_root ) )
        exc = _refused( "notes.json" )
        assert exc.status_code == 400
        assert "blocklist" in exc.detail.lower()
        assert "canary-27398998" not in exc.detail


class TestLegacyAbsolutePrefixStripping:
    """
    Callers embed an absolute io path in older artifacts. Both spellings of the root must
    strip, since the endpoint now knows two of them.
    """

    def test_the_typed_absolute_prefix_still_strips( self, patched_root ):
        response = _get( f"{patched_root}/io/report.md" )
        assert response.status_code == 200
        assert ORDINARY.strip() in response.body.decode()

    def test_the_resolved_absolute_prefix_also_strips( self, patched_root ):
        resolved = os.path.realpath( str( patched_root ) + "/io" )
        response = _get( f"{resolved}/report.md" )
        assert response.status_code == 200
        assert ORDINARY.strip() in response.body.decode()

    def test_the_relative_io_prefix_still_strips( self, patched_root ):
        response = _get( "io/report.md" )
        assert response.status_code == 200
        assert ORDINARY.strip() in response.body.decode()


class TestAForeignAbsolutePathCannotEscape:
    """
    The `else` arm of the prefix-strip loop — the one that lstrips a path whose absolute
    prefix is NOT either spelling of the io root.

    Rachel flagged this arm as unguarded on review. It is not: `test_leading_slash_stripped`
    in the COSA-tier router suite EXECUTES it, which is why a run including that tier reports
    this file at 100% while a unit-and-smoke-only run reports 66%.

    What genuinely had no assertion anywhere is the SECURITY BEHAVIOUR of the arm — that
    lstripping a foreign absolute path makes it relative, so the join always lands under
    io_base and containment then holds trivially. "The line is executed" and "the outcome is
    asserted" are different claims, and only the first was true. These cover the second, and
    they live in the unit tier so it no longer depends on the cosa tier to watch this arm.
    """

    def test_a_foreign_absolute_path_lands_inside_io_and_404s( self, patched_root ):
        """/etc/passwd becomes io/etc/passwd — refused as missing, never read from /etc."""
        exc = _refused( "/etc/passwd" )
        assert exc.status_code == 404
        assert "etc/passwd" in exc.detail
        assert not exc.detail.startswith( "/" )

    def test_a_foreign_absolute_path_is_still_blocklist_checked( self, patched_root ):
        """The lstrip must not smuggle a blocked basename past the secrets check."""
        exc = _refused( "/.env" )
        assert exc.status_code == 400
        assert "blocklist" in exc.detail.lower()
        assert "canary-27398998" not in exc.detail

    def test_a_bare_leading_slash_still_serves_an_ordinary_io_file( self, patched_root ):
        """Positive control for the arm: it must not refuse the benign case it exists to handle."""
        response = _get( "/report.md" )
        assert response.status_code == 200
        assert ORDINARY.strip() in response.body.decode()
