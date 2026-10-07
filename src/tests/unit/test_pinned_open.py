"""
The shared descriptor helpers: open first, then judge where the descriptor landed.
"""
import os

import pytest

from cosa.rest.routers._pinned_open import PinnedPathGone, landed_path_of_fd, open_pinned


def _open_fds():
    return len( os.listdir( "/proc/self/fd" ) )


def test_a_regular_file_is_pinned_and_the_judge_sees_where_it_landed( tmp_path ):
    target = tmp_path / "f.txt"
    target.write_text( "x" )
    seen = []
    fd   = open_pinned( str( target ), seen.append )
    try:
        assert seen == [ str( target.resolve() ) ]
    finally:
        os.close( fd )


def test_a_path_reached_through_a_link_is_judged_where_the_link_lands( tmp_path ):
    real = tmp_path / "real.txt"; real.write_text( "x" )
    link = tmp_path / "link.txt"; os.symlink( real, link )
    seen = []
    os.close( open_pinned( str( link ), seen.append ) )
    assert seen == [ str( real.resolve() ) ]


def test_a_missing_path_is_gone( tmp_path ):
    with pytest.raises( PinnedPathGone ):
        open_pinned( str( tmp_path / "nope" ), lambda landed: None )


def test_a_folder_is_not_a_regular_file_and_nothing_stays_open( tmp_path ):
    before = _open_fds()
    with pytest.raises( PinnedPathGone ):
        open_pinned( str( tmp_path ), lambda landed: None )
    assert _open_fds() == before


def test_a_folder_pins_as_a_folder_when_asked( tmp_path ):
    fd = open_pinned( str( tmp_path ), lambda landed: None, directory=True )
    os.close( fd )


def test_a_file_cannot_be_pinned_as_a_folder( tmp_path ):
    target = tmp_path / "f.txt"; target.write_text( "x" )
    with pytest.raises( PinnedPathGone ):
        open_pinned( str( target ), lambda landed: None, directory=True )


def test_the_judge_refusing_closes_the_descriptor_and_its_error_leaves_untouched( tmp_path ):
    target = tmp_path / "f.txt"; target.write_text( "x" )
    before = _open_fds()

    def refuse( landed ):
        raise ValueError( "judge says no" )

    with pytest.raises( ValueError, match="judge says no" ):
        open_pinned( str( target ), refuse )
    assert _open_fds() == before


def test_an_unlinked_inode_is_gone_not_judged( tmp_path ):
    victim = tmp_path / "v.txt"; victim.write_text( "x" )
    fd = os.open( victim, os.O_RDONLY )
    try:
        os.unlink( victim )
        with pytest.raises( PinnedPathGone ):
            landed_path_of_fd( fd )
    finally:
        os.close( fd )
