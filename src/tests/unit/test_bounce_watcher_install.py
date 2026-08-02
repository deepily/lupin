"""
Consistency tests for the bounce-watcher systemd install (row 1b4211ac R2).

R2 is only real if the watcher actually STARTS — and stays up across a reboot.
These pin the wiring that makes that true, without touching real systemd:

  1. the unit TEMPLATE points its ExecStart at bounce-watcher.sh, respawns on
     crash, and installs into the boot target;
  2. rendering the template (the same substitution the installer does) leaves NO
     placeholder and resolves ExecStart/LUPIN_ROOT to the given root;
  3. the INSTALLER keeps the two reboot-safety steps — `enable --now` and
     `enable-linger` — plus its own leftover-placeholder guard.

If any of those is dropped, the button silently reverts to "works only if someone
started a script by hand" — the exact failure the row exists to remove.
"""

import os
import re
import unittest


REPO_ROOT = os.path.abspath( os.path.join( os.path.dirname( __file__ ), "..", "..", ".." ) )
SCRIPTS   = os.path.join( REPO_ROOT, "src", "scripts" )
TEMPLATE  = os.path.join( SCRIPTS, "lupin-bounce-watcher.service" )
INSTALLER = os.path.join( SCRIPTS, "install-bounce-watcher.sh" )
WATCHER   = os.path.join( SCRIPTS, "bounce-watcher.sh" )

PLACEHOLDER = "__LUPIN_ROOT__"


def _read( path ):
    with open( path ) as f:
        return f.read()


def _render( template_text, root ):
    """Mirror the installer's substitution (sed s#__LUPIN_ROOT__#root#g)."""
    return template_text.replace( PLACEHOLDER, root )


class TestUnitTemplate( unittest.TestCase ):

    def setUp( self ):
        self.text = _read( TEMPLATE )

    def test_template_uses_a_placeholder_not_a_hardcoded_path( self ):
        # Host-agnostic: no absolute repo path baked in, only the placeholder.
        self.assertIn( PLACEHOLDER, self.text )
        self.assertNotIn( "/mnt/DATA01", self.text )

    def test_execstart_runs_the_watcher( self ):
        self.assertRegex( self.text, r"ExecStart=.*bash\s+%s/src/scripts/bounce-watcher\.sh" % re.escape( PLACEHOLDER ) )

    def test_respawns_on_crash( self ):
        self.assertIn( "Restart=always", self.text )

    def test_installs_into_the_boot_target( self ):
        self.assertIn( "WantedBy=default.target", self.text )


class TestRendering( unittest.TestCase ):

    def test_rendering_leaves_no_placeholder_and_resolves_paths( self ):
        rendered = _render( _read( TEMPLATE ), "/opt/lupin" )
        self.assertNotIn( PLACEHOLDER, rendered )
        self.assertIn( "Environment=LUPIN_ROOT=/opt/lupin", rendered )
        self.assertIn( "ExecStart=/usr/bin/env bash /opt/lupin/src/scripts/bounce-watcher.sh", rendered )


class TestInstaller( unittest.TestCase ):

    def setUp( self ):
        self.text = _read( INSTALLER )

    def test_requires_lupin_root( self ):
        self.assertIn( "LUPIN_ROOT", self.text )
        self.assertIn( "exit 1", self.text )

    def test_enables_and_starts_the_service( self ):
        self.assertRegex( self.text, r"systemctl --user enable --now" )

    def test_enables_linger_for_reboot_safety( self ):
        # Without lingering the user service does not start at boot — the reboot
        # half of the row's requirement.
        self.assertIn( "enable-linger", self.text )

    def test_guards_against_a_leftover_placeholder( self ):
        self.assertIn( PLACEHOLDER, self.text )   # the guard greps for it

    def test_watcher_header_points_at_the_installer( self ):
        # The by-hand path must not read as the sanctioned one.
        self.assertIn( "install-bounce-watcher.sh", _read( WATCHER ) )


if __name__ == "__main__":
    unittest.main()
