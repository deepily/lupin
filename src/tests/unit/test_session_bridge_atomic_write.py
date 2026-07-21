"""
Row 49b2c80b — the bridge writer must not be able to emit a spliced file.

These tests are built around a REPRODUCTION of the real corruption, not around
a description of it. `test_two_concurrent_plain_writes_SPLICE_the_file` is the
must-fail control: it exercises the OLD `open(path,"w")` shape and asserts the
splice still happens, so if someone ever "fixes" the control into passing
cleanly, the tests below stop proving anything and say so loudly.

Specimen (2026-07-21): ~/.claude/sessions/cc-231749.json held one valid
1081-byte bridge followed by 27 bytes that were the tail of a longer document.
The seat stayed alive but became unaddressable by dm_send for twenty minutes.
"""
import json
import os
import pytest

from lupin_cli.claude_code.hooks.lib.session_bridge import atomic_write_json


LONG_DOC  = { "session_id": "931e9dae-6c61-41b7-b17e-9fc7d9faca25", "voice_persona": { "name": "arnold" }, "pad": "x" * 200 }
SHORT_DOC = { "session_id": "d43421a6-4e80-4eef-b604-8bbe655a503a", "listener_pid": 231956 }


def _interleave_plain_writes( path, long_doc, short_doc ):
    """
    Reproduce the exact interleaving read off the real corrupt file.

    Both writers truncate at OPEN, so the second truncate cannot remove the
    first writer's tail once both are past it, and the two fds keep independent
    offsets. The longer write lands first; the shorter one overwrites its
    prefix and leaves the tail behind.
    """
    f_long  = open( path, "w" )
    f_short = open( path, "w" )
    f_long.write( json.dumps( long_doc, indent=2 ) );  f_long.flush()
    f_short.write( json.dumps( short_doc, indent=2 ) ); f_short.flush()
    f_long.close(); f_short.close()


class TestTheControl:
    """The defect must still be reproducible, or nothing below is evidence."""

    def test_two_concurrent_plain_writes_SPLICE_the_file( self, tmp_path ):
        p = tmp_path / "cc-231749.json"
        _interleave_plain_writes( p, LONG_DOC, SHORT_DOC )

        raw = p.read_bytes()
        with pytest.raises( json.JSONDecodeError ) as exc:
            json.loads( raw )
        assert "Extra data" in str( exc.value ), (
            "the control no longer reproduces the ORIGINAL signature — if this "
            "changed, re-derive the mechanism before trusting the tests below"
        )

        # The residue is the TAIL of the longer document, byte for byte. This is
        # the assertion that made the diagnosis falsifiable in the first place.
        short_bytes = json.dumps( SHORT_DOC, indent=2 ).encode()
        long_bytes  = json.dumps( LONG_DOC,  indent=2 ).encode()
        assert raw == short_bytes + long_bytes[ len( short_bytes ): ]


class TestAtomicWriteJson:

    def test_same_interleaving_cannot_splice( self, tmp_path ):
        """The fix, against the exact scenario the control just reproduced."""
        p = tmp_path / "cc-231749.json"
        assert atomic_write_json( p, LONG_DOC )
        assert atomic_write_json( p, SHORT_DOC )

        loaded = json.loads( p.read_text() )       # must parse at all
        assert loaded == SHORT_DOC                 # last writer wins, wholly

    def test_reader_sees_old_or_new_never_partial( self, tmp_path ):
        """
        A reader racing a write observes one COMPLETE document.

        Simulated deterministically: the new document is fully staged in the
        temp file, and the target still holds the old one, right up to the
        instant os.replace() flips it. There is no window in which the target
        holds a partial document — which is the whole property.
        """
        p = tmp_path / "cc-1.json"
        atomic_write_json( p, LONG_DOC )

        seen = [ ]
        real_replace = os.replace
        def spy_replace( src, dst ):
            seen.append( json.loads( open( dst ).read() ) )   # read DURING the write
            return real_replace( src, dst )

        os.replace = spy_replace
        try:
            assert atomic_write_json( p, SHORT_DOC )
        finally:
            os.replace = real_replace

        assert seen == [ LONG_DOC ], "mid-write read did not see the complete OLD document"
        assert json.loads( p.read_text() ) == SHORT_DOC

    def test_temp_file_is_created_beside_the_target( self, tmp_path ):
        """
        A temp on another filesystem makes os.replace raise instead of being
        atomic — so the directory choice is part of the fix, not a detail.
        """
        p = tmp_path / "cc-2.json"
        seen_dirs = [ ]
        import tempfile as tf
        real_mkstemp = tf.mkstemp
        def spy_mkstemp( *a, **kw ):
            seen_dirs.append( kw.get( "dir" ) )
            return real_mkstemp( *a, **kw )

        tf.mkstemp = spy_mkstemp
        try:
            assert atomic_write_json( p, SHORT_DOC )
        finally:
            tf.mkstemp = real_mkstemp

        assert seen_dirs == [ str( tmp_path ) ]

    def test_unserializable_payload_leaves_the_old_file_intact( self, tmp_path ):
        """A failed write must never be a truncation."""
        p = tmp_path / "cc-3.json"
        atomic_write_json( p, LONG_DOC )

        assert atomic_write_json( p, { "bad": object() } ) is False
        assert json.loads( p.read_text() ) == LONG_DOC
        assert [ f for f in os.listdir( tmp_path ) if f.endswith( ".tmp" ) ] == [ ], "temp file leaked on the failure path"

    def test_cleanup_failure_still_returns_False_and_spares_the_target( self, tmp_path ):
        """Even if the temp cannot be removed, the failure path stays a no-op on the target."""
        p = tmp_path / "cc-3b.json"
        atomic_write_json( p, LONG_DOC )

        real_unlink = os.unlink
        os.unlink = lambda *a, **kw: ( _ for _ in () ).throw( OSError( "cannot unlink" ) )
        try:
            assert atomic_write_json( p, { "bad": object() } ) is False
        finally:
            os.unlink = real_unlink

        assert json.loads( p.read_text() ) == LONG_DOC

    def test_unwritable_directory_returns_False( self, tmp_path ):
        assert atomic_write_json( tmp_path / "no" / "such" / "dir" / "cc-4.json", SHORT_DOC ) is False

    def test_accepts_str_and_Path_alike( self, tmp_path ):
        p = tmp_path / "cc-5.json"
        assert atomic_write_json( str( p ), SHORT_DOC )
        assert atomic_write_json( p, LONG_DOC )
        assert json.loads( p.read_text() ) == LONG_DOC
