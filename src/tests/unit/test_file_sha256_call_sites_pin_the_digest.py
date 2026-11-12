"""
Pins for call sites of file_sha256 that no other test checked against a real digest.

Each test hands the site a file whose sha256 is known and asserts the digest as a literal.
A constant in place of the call then fails it. The bytes abc hash to ABC_SHA.
"""

from cosa.agents.test_suite import attestation

ABC_SHA = "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"


def test_sha256_file_returns_the_digest_of_the_file_bytes( tmp_path ):
    target = tmp_path / "junit.xml"
    target.write_bytes( b"abc" )
    assert attestation.sha256_file( str( target ) ) == ABC_SHA


def test_sha256_file_names_none_for_a_missing_path_and_for_none( tmp_path ):
    assert attestation.sha256_file( str( tmp_path / "absent.xml" ) ) is None
    assert attestation.sha256_file( None ) is None
