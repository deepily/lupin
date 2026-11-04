"""
The fd probe counts descriptors under one folder and ignores the rest of the process.
"""
import os

from tests.helpers import fd_probe


def test_a_descriptor_under_the_folder_is_counted_until_it_is_closed( tmp_path ):
    target = tmp_path / "f.txt"; target.write_text( "x" )
    assert fd_probe.fds_under( tmp_path ) == 0
    fd = os.open( target, os.O_RDONLY )
    try:
        assert fd_probe.fds_under( tmp_path ) == 1
    finally:
        os.close( fd )
    assert fd_probe.fds_under( tmp_path ) == 0


def test_a_descriptor_elsewhere_is_not_counted( tmp_path ):
    fd = os.open( os.devnull, os.O_RDONLY )
    try:
        assert fd_probe.fds_under( tmp_path ) == 0
    finally:
        os.close( fd )


def test_a_sibling_folder_sharing_a_name_prefix_is_not_counted( tmp_path ):
    ( tmp_path / "proj" ).mkdir(); ( tmp_path / "proj-other" ).mkdir()
    ( tmp_path / "proj-other" / "f.txt" ).write_text( "x" )
    fd = os.open( tmp_path / "proj-other" / "f.txt", os.O_RDONLY )
    try:
        assert fd_probe.fds_under( tmp_path / "proj" ) == 0
        assert fd_probe.fds_under( tmp_path / "proj-other" ) == 1
    finally:
        os.close( fd )


def test_an_unlinked_file_still_counts( tmp_path ):
    target = tmp_path / "gone.txt"; target.write_text( "x" )
    fd = os.open( target, os.O_RDONLY )
    try:
        os.unlink( target )
        assert fd_probe.fds_under( tmp_path ) == 1
    finally:
        os.close( fd )


def test_a_descriptor_that_vanishes_during_the_read_is_skipped( tmp_path, monkeypatch ):
    real = os.readlink
    def vanishing( path ):
        if path.startswith( "/proc/self/fd/" ): raise FileNotFoundError( path )
        return real( path )
    monkeypatch.setattr( fd_probe.os, "readlink", vanishing )
    assert fd_probe.fds_under( tmp_path ) == 0
