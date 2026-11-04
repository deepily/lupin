"""
Unit tests for `find_stub_bodied_tests`, the detector of tests that assert nothing.

Requires:
    - cosa.repo.gate_reachability is importable

Ensures:
    - the detector reports stubs in reachable files, skips unreachable and unparseable ones
"""

import pytest

from cosa.repo import gate_reachability as gr


@pytest.fixture
def tree( tmp_path, monkeypatch ):
    """A fake repo whose only gate target is the directory src/gated."""
    monkeypatch.setattr( gr, "find_gate_targets", lambda root: { "src/gated" } )
    ( tmp_path / "src" / "gated" ).mkdir( parents=True )
    ( tmp_path / "src" / "loose" ).mkdir( parents=True )
    return tmp_path


def test_a_stub_in_a_reachable_file_is_reported_with_its_path( tree ):
    """Docstring-only, pass, and assert True are stubs; a real assertion is not."""
    ( tree / "src" / "gated" / "test_a.py" ).write_text(
        "def test_doc_only():\n    '''d'''\n\n"
        "def test_pass():\n    pass\n\n"
        "async def test_async_true():\n    assert True\n\n"
        "def test_real():\n    assert 1 + 1 == 2\n\n"
        "def helper_not_a_test():\n    pass\n" )
    assert gr.find_stub_bodied_tests( tree ) == [
        "src/gated/test_a.py::test_async_true",
        "src/gated/test_a.py::test_doc_only",
        "src/gated/test_a.py::test_pass" ]


def test_a_stub_in_an_unreachable_file_is_not_reported( tree ):
    """No runner names src/loose, so it cannot colour a gate and is not counted."""
    ( tree / "src" / "loose" / "test_b.py" ).write_text( "def test_pass():\n    pass\n" )
    assert gr.find_stub_bodied_tests( tree ) == []


def test_an_unparseable_or_undecodable_file_is_skipped_not_raised( tree ):
    """A syntax error or non-UTF-8 bytes skip the file; the next file is still scanned."""
    ( tree / "src" / "gated" / "test_bad.py" ).write_text( "def test_x(:\n" )
    ( tree / "src" / "gated" / "test_bytes.py" ).write_bytes( b"\xff\xfe\x00bad" )
    ( tree / "src" / "gated" / "test_ok.py" ).write_text( "def test_pass():\n    ...\n" )
    assert gr.find_stub_bodied_tests( tree ) == [ "src/gated/test_ok.py::test_pass" ]


def test_the_detector_is_empty_when_nothing_matches( tree ):
    """An empty gated directory yields an empty list, not an error."""
    assert gr.find_stub_bodied_tests( tree ) == []
