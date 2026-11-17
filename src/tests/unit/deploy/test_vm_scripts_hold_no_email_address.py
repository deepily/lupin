"""
Guard: lupin-vm.sh and the libraries it names hold no email address.

The privacy guard refuses a Bash command that names a file holding a personal address.
So an address in the script stopped every seat from running deploy, push-dist, test-server or tunnel.
The address now comes from LUPIN_VM_DEV_EMAIL in the git-ignored src/scripts/cloud-run.env.
"""

import os
import re

import pytest

ROOT = os.environ[ "LUPIN_ROOT" ]
VMSH = os.path.join( ROOT, "src/scripts/lupin-vm.sh" )

# Anything shaped like local@domain.tld; deliberately wider than one provider or one person.
EMAIL_SHAPE = re.compile( r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}" )


def find_addresses( text ):
    """
    List the lines of a text that hold an email-shaped string.

    Requires:
        - text is a string
    Ensures:
        - returns the 1-based line numbers, never the matched text
    """
    return [ n for n, line in enumerate( text.splitlines(), 1 ) if EMAIL_SHAPE.search( line ) ]


def _guarded_files():
    """lupin-vm.sh plus every src/scripts/lib/*.sh it names, derived from the script's own text."""
    text = open( VMSH ).read()
    libs = sorted( set( re.findall( r"lib/([A-Za-z0-9_.-]+\.sh)", text ) ) )
    return [ VMSH ] + [ os.path.join( ROOT, "src/scripts/lib", name ) for name in libs ]


def test_the_guard_finds_a_planted_address():
    """Positive control: the finder fires on planted addresses and skips clean text."""
    assert find_addresses( "a=1\nowner.name+x@mail.example.org\nb=2\n" ) == [ 2 ]
    assert find_addresses( "global_notification_recipient = someone@example.test\n" ) == [ 1 ]
    assert find_addresses( "echo '@' and \"$X@$Y\" and ssh user@host\n" ) == []


def test_the_guarded_set_names_the_script_and_at_least_one_library():
    """Denominator: the script plus the libraries it names, each present."""
    files = _guarded_files()
    assert len( files ) >= 2, files
    assert os.path.join( ROOT, "src/scripts/lib/preflight-vm-lib.sh" ) in files
    for f in files: assert os.path.isfile( f ), f


@pytest.mark.parametrize( "path", _guarded_files(), ids=lambda p: os.path.relpath( p, ROOT ) )
def test_no_email_address_in_the_vm_script_or_its_libraries( path ):
    """Line numbers only are reported, so a failure never prints an address."""
    hits = find_addresses( open( path ).read() )
    assert hits == [], f"{os.path.relpath( path, ROOT )} holds an email-shaped string on line(s) {hits}; move it to LUPIN_VM_DEV_EMAIL in src/scripts/cloud-run.env"
