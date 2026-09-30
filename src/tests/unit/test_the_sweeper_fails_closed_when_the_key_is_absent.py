#!/usr/bin/env python3
"""
THE ORPHAN SWEEPER MUST FAIL CLOSED, AND THE INI MUST STATE ITS FLAG.

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

WHAT IT PINS NOW (row 65c594e5, 2026-09-11). This file once pinned the INI to
`false` and the INI and code default to AGREE. 11dcb6ee (2026-09-08) armed the
sweeper in the INI on Rick's direct word, and his 2026-09-09 ruling is quoted
above the key, which left the unit tier red on a guard whose premise had moved.
The two claims that still hold, and that this file holds:
    1. the code default is False, so an ABSENT key never arms it (fail closed)
    2. the INI names the key as a boolean, so a deployment runs on the ruled
       value, never on the default
Whether the value is true or false is Rick's to set, and nothing here pins it.
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

    def test_the_shipped_ini_states_the_flag_explicitly_as_a_boolean( self ):
        """
        The INI must SAY the value, so a deployment runs on the INI's word and
        never on the code default.

        This replaced two tests, "the shipped INI ships it off" and "the two
        AGREE" (row 65c594e5, 2026-09-11). Their premise was a sweeper shipped
        OFF. 11dcb6ee (2026-09-08, "Persist the armed orphan sweeper", on Rick's
        direct word) armed it in the INI, and Rick's ruling of 2026-09-09 is
        quoted in the comment above the key. So an armed INI over an off-by-default
        code path is now the intended pairing, and it is the SAFE direction: only a
        deployment whose INI names the key arms the sweeper. The value itself is
        Rick's to set, so this pins the key's presence and form, not true or false.
        """
        value = _ini_value_for( KEY )
        self.assertIsNotNone(
            value,
            "lupin-app.ini no longer names the sweep flag — the sweeper would "
            "silently fall back to main.py's default instead of the ruled value"
        )
        self.assertIn(
            value.lower(), ( "true", "false" ),
            f"the sweep flag's INI value {value!r} is not a boolean"
        )

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
