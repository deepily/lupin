"""Unit tests for cosa.utils.file_hash.file_sha256."""
import hashlib

import pytest

import cosa.utils.file_hash as fh
from cosa.utils.file_hash import file_sha256


def test_the_digest_is_the_sha256_of_the_bytes_and_a_str_path_works_too( tmp_path ):
    path = tmp_path / "a.bin"
    path.write_bytes( b"abc" )
    assert file_sha256( path ) == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    assert file_sha256( str( path ) ) == file_sha256( path )
    path.write_bytes( b"" )
    assert file_sha256( path ) == hashlib.sha256( b"" ).hexdigest(), "an empty file hashes as empty bytes"


def test_a_file_longer_than_one_chunk_hashes_the_same_as_one_read( tmp_path, monkeypatch ):
    data = bytes( range( 256 ) ) * 40
    path = tmp_path / "big.bin"
    path.write_bytes( data )
    monkeypatch.setattr( fh, "CHUNK_BYTES", 100 )               # 10,240 bytes read 100 at a time
    assert file_sha256( path ) == hashlib.sha256( data ).hexdigest()


def test_a_missing_file_raises_oserror( tmp_path ):
    with pytest.raises( OSError ):
        file_sha256( tmp_path / "gone.bin" )
