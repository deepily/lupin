#!/usr/bin/env python3
"""
THE ORPHAN SWEEPER MUST FAIL CLOSED, AND THE CODE DEFAULT MUST AGREE WITH THE INI.

WHY THIS FILE EXISTS. The sweeper shipped with the INI key set to `false` and
the CODE default set to `True`. Both were written by the same person in the same
hour, and they disagreed in the DANGEROUS direction: any deployment reaching
that call with the key absent — an older config, a partial merge, a container
mounting a tree where only the code landed — would have ARMED it.

That is not a hypothetical direction. This sweeper is the first thing in the
system that can refuse a real human answer:

    MEASURED 2026-09-05 at the real HTTP door on :7999, one variable, control first
        inside grace (60s past expires_at)   -> 200, response_value {"value":...,"source":"ui"}
        past grace  (3600s past expires_at)  -> 400, response_value NULL, responded_at NULL

    ⇒ a past-grace keypress is DISCARDED WITH NO TRACE, and (read from
      notifications.js, not driven) the client reports "Default response was
      used" and files response_default as the outcome — a default nothing
      applied, replacing an answer a human actually gave.

⇒ An absent key must therefore mean OFF. A comment saying so is not a control;
  this file is.

🔴 IT PINS THE TWO TOGETHER RATHER THAN PINNING EITHER ONE. Asserting only that
the code default is False would still let someone flip the INI to `true` and
ship an armed sweeper while this stayed green. Asserting only the INI would miss
the code. The claim is that they AGREE, and that what they agree ON is off.
"""
import os
import re
import unittest

os.environ.setdefault( "JWT_SECRET_KEY", "test-only-sweeper-fail-closed-guard" )

import cosa.utils.util as cu


def _ini_value_for( key ):
    """
    The value the SHIPPED lupin-app.ini gives a key, read from the file rather
    than through ConfigurationManager — an env var or a section override could
    otherwise mask what the file actually ships, and the file is what a fresh
    deployment gets.

    Returns None when the key is absent, so "absent" and "present but false"
    stay distinguishable — they are different failures and this file cares
    about both.
    """
    path = cu.get_project_root() + "/src/conf/lupin-app.ini"
    with open( path ) as handle:
        for line in handle:
            stripped = line.strip()
            if stripped.startswith( "#" ) or "=" not in stripped: continue
            name, _, value = stripped.partition( "=" )
            if name.strip() == key: return value.strip()
    return None


def _code_default_for( key ):
    """
    The `default=` literal on the config_mgr.get call for `key` in main.py.

    Read from the source text deliberately: the call sits inside `lifespan`,
    which cannot be executed in a unit test without booting the app. The regex
    is anchored on the key string so it cannot drift onto a neighbouring call.

    Returns None when no such call is found — which this file's own control
    turns into a failure rather than a quiet pass.
    """
    path = cu.get_project_root() + "/src/lupin_app/main.py"
    with open( path ) as handle:
        source = handle.read()
    match = re.search(
        r'config_mgr\.get\(\s*"' + re.escape( key ) + r'"\s*,\s*default\s*=\s*(\w+)',
        source
    )
    return match.group( 1 ) if match else None


KEY = "notification expiry sweep enabled"


class TheSweeperFailsClosed( unittest.TestCase ):

    def test_the_code_default_is_False_so_an_absent_key_does_not_arm_it( self ):
        self.assertEqual(
            _code_default_for( KEY ), "False",
            "main.py's default for the sweep flag is not False — an absent key "
            "would ARM a sweeper that can destroy a real keypress"
        )

    def test_the_shipped_ini_ships_it_off( self ):
        self.assertEqual(
            ( _ini_value_for( KEY ) or "" ).lower(), "false",
            "lupin-app.ini ships the sweep flag armed; it is blocked on the "
            "client-side mislabel — see the comment on the key"
        )

    def test_the_two_AGREE_which_is_the_actual_claim( self ):
        """
        Neither arm above is sufficient alone: one passes with an armed INI,
        the other with an armed code default. The property is agreement.
        """
        ini  = ( _ini_value_for( KEY ) or "" ).lower() == "true"
        code = _code_default_for( KEY ) == "True"

        self.assertEqual(
            ini, code,
            "the INI value and main.py's code default for the sweep flag "
            "DISAGREE — they were written disagreeing once already"
        )
        self.assertFalse( ini, "both agree, but they agree on ARMED" )

    def test_the_readers_can_find_a_key_that_IS_present_CONTROL( self ):
        """
        Without this, every assertion above would pass against readers that can
        never find anything — an absent key and a broken reader both return
        None, and they are different failures wearing one face.
        """
        self.assertIsNotNone(
            _ini_value_for( "notification grace period seconds" ),
            "the INI reader cannot find a key known to be present"
        )
        self.assertIsNotNone(
            _code_default_for( "notification expiry sweep interval seconds" ),
            "the source reader cannot find a config_mgr.get known to be present"
        )

    def test_the_readers_return_None_for_a_key_that_does_not_exist( self ):
        """The negative control: a reader matching anything would satisfy the above."""
        self.assertIsNone( _ini_value_for( "a key nobody ever wrote" ) )
        self.assertIsNone( _code_default_for( "a key nobody ever wrote" ) )


if __name__ == "__main__":
    unittest.main()
