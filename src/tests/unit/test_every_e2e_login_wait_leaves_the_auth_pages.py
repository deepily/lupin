"""
No e2e file may wait for a login redirect with the "**/app**" glob.

That glob matches the login page's own URL, so the wait returns before the page's 1 s redirect.
The next navigation then collides with it. Every wait goes through `wait_for_login_redirect`.
"""

import re
import subprocess

from cosa.utils import util as cu

BAD_WAIT = re.compile( r"""wait_for_url\(\s*["']\*\*/app\*\*["']""" )
HELPER   = re.compile( r"(?<!def )\bwait_for_login_redirect\(\s*page" )


def _e2e_files():
    """Ensures: returns the tracked .py files under src/tests/e2e_ui, as ( path, text ) pairs."""
    root  = cu.get_project_root()
    names = subprocess.run( [ "git", "ls-files", "src/tests/e2e_ui/*.py" ], cwd=root, capture_output=True, text=True, check=True ).stdout.split()
    return [ ( n, open( f"{root}/{n}", encoding="utf-8" ).read() ) for n in names ]


def test_the_scanner_finds_the_glob_it_forbids():
    """Positive control: the pattern matches both spellings, so a zero below means something."""
    assert BAD_WAIT.search( 'page.wait_for_url( "**/app**", timeout=10000 )' )
    assert BAD_WAIT.search( "page.wait_for_url('**/app**')" )
    assert not BAD_WAIT.search( 'page.wait_for_url( "**/login**", timeout=10000 )' )


def test_every_e2e_login_wait_leaves_the_auth_pages():
    """No tracked e2e file calls wait_for_url with the **/app** glob."""
    files = _e2e_files()
    assert len( files ) > 100, f"the denominator is {len( files )} files; the listing is wrong"
    offenders = [ n for n, text in files if BAD_WAIT.search( text ) ]
    assert offenders == [], f"these files wait with the **/app** glob: {offenders}"


def test_the_seven_login_waits_all_call_the_shared_helper():
    """The two fixtures and the five test waits each call the helper, so none went missing."""
    calls = sum( len( HELPER.findall( text ) ) for _, text in _e2e_files() )
    assert calls == 7, f"expected 7 helper calls, found {calls}"
