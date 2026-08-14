#!/usr/bin/env python3
"""
INI/splainer TWIN guard for the context-pressure budget-fraction threshold keys
(store row 9e0678f6, amendment B): the runtime-configurable threshold that
self-re-spin reads MUST ship with its splainer entry in the SAME commit.

WHY A FOCUSED GUARD AND NOT THE GENERAL ONE. A general "every INI key has a
splainer entry" parity test already exists — test_ini_key_naming.py
::TestIniSplainerParity — but it is @pytest.mark.xfail'd ("17 pre-existing
splainer gaps"), so it enforces NOTHING: a new key with no splainer entry sails
through. This guard is scoped to ONLY the three budget-fraction keys, so it steps
around those 17 unrelated gaps and actually bites when THIS twin is broken.

The threshold keys are the self-respin trigger source: app.py:276-278 reads
`arbiter context budget fraction {1000000,200000,default}` from lupin-app.ini into
the policy the /api/arbiter/context-pressure payload publishes (status:over_budget
is what every reader, including the 15-minute tick, keys on). One number to change,
one place — and it must stay explained.

Venue: :7999-eligible / local — pure file reads, no server, no state.
"""
import configparser
import os
import sys

import pytest

# Bootstrap
_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

import cosa.utils.util as cu

# The keys this row governs — the self-respin threshold source. Kept explicit (not
# derived) so a rename of the real key without updating this list is itself a red.
BUDGET_FRACTION_KEYS = (
    "arbiter context budget fraction 1000000",
    "arbiter context budget fraction 200000",
    "arbiter context budget fraction default",
)

_CONF_DIR = cu.get_project_root() + "/src/conf"


def _all_keys( ini_filename ):
    """
    Requires:
        - ini_filename names a file under src/conf

    Ensures:
        - Returns the set of every key across every section of that INI file
    """
    parser = configparser.ConfigParser()
    parser.read( os.path.join( _CONF_DIR, ini_filename ) )
    keys = set()
    for section in parser.sections():
        for key in parser[ section ]:
            keys.add( key )
    return keys


def _missing_splainer_twins( ini_keys, splainer_keys, required ):
    """
    The parity predicate, isolated so a must-fail control can exercise it directly.

    Requires:
        - ini_keys, splainer_keys are sets of key strings
        - required is an iterable of keys that must appear in BOTH

    Ensures:
        - Returns the sorted list of required keys that are present in ini_keys
          but absent from splainer_keys (an empty list == the twin holds)
    """
    return sorted( k for k in required if k in ini_keys and k not in splainer_keys )


@pytest.fixture( scope="module" )
def ini_keys():
    return _all_keys( "lupin-app.ini" )


@pytest.fixture( scope="module" )
def splainer_keys():
    return _all_keys( "lupin-app-splainer.ini" )


def test_each_budget_fraction_key_is_present_in_ini( ini_keys ):
    """The three threshold keys must actually exist in lupin-app.ini."""
    absent = [ k for k in BUDGET_FRACTION_KEYS if k not in ini_keys ]
    assert not absent, f"budget-fraction key(s) missing from lupin-app.ini: {absent}"


def test_each_budget_fraction_key_has_a_splainer_twin( ini_keys, splainer_keys ):
    """LIVE guard — each present threshold key MUST have a splainer entry. Non-xfail,
    unlike the general parity test, so this one actually goes red on a broken twin."""
    missing = _missing_splainer_twins( ini_keys, splainer_keys, BUDGET_FRACTION_KEYS )
    assert not missing, (
        "budget-fraction key(s) in lupin-app.ini WITHOUT a splainer twin:\n"
        + "\n".join( f"  {k}" for k in missing )
        + "\n\nThe threshold key and its splainer entry must ship in the same commit (row 9e0678f6, amendment B)."
    )


def test_parity_predicate_goes_red_when_a_splainer_entry_is_deleted( ini_keys, splainer_keys ):
    """MUST-FAIL CONTROL — prove the guard bites: delete one key from the splainer
    set and confirm the predicate flags exactly that key. Without this, a predicate
    that never reports missing would pass the live guard vacuously."""
    victim = "arbiter context budget fraction default"
    doctored_splainer = splainer_keys - { victim }
    flagged = _missing_splainer_twins( ini_keys, doctored_splainer, BUDGET_FRACTION_KEYS )
    assert flagged == [ victim ], f"expected the deleted twin to be flagged, got {flagged}"


if __name__ == "__main__":
    sys.exit( pytest.main( [ __file__, "-v" ] ) )
