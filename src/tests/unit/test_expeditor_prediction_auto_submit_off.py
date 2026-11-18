#!/usr/bin/env python3
"""
Pin tests: the expeditor's prediction auto-submit is switched off and marked dormant.

Rick ruled on 18 Nov 2026 to disable it and keep the code. The keys stay, the committed value is
false, and the docs say Dormant. A forecast shown to Rick never answers for him. :7999-eligible.
"""

import re

import cosa.utils.util as cu

KEYS = [
    "expeditor prediction auto submit enabled",
    "expeditor prediction auto submit confidence floor",
    "expeditor prediction auto submit grace window seconds",
]


def _line( path, key ):
    """Return the value of `key` on its single line in an INI file."""
    with open( path ) as handle:
        hits = re.findall( rf"^{re.escape( key )}\s*=\s*(.*)$", handle.read(), flags=re.MULTILINE )
    assert len( hits ) == 1, f"{key!r} must appear exactly once in {path}, found {len( hits )}"
    return hits[ 0 ].strip()


def test_committed_switch_is_false():
    assert _line( cu.get_project_root() + "/src/conf/lupin-app.ini", KEYS[ 0 ] ) == "false"


def test_the_other_two_keys_are_still_present():
    ini = cu.get_project_root() + "/src/conf/lupin-app.ini"
    assert _line( ini, KEYS[ 1 ] ) == "0.9"
    assert _line( ini, KEYS[ 2 ] ) == "5"


def test_the_servers_own_fallback_is_off_too():
    """The route reads the switch with default=False, so an INI without the key is also off."""
    with open( cu.get_project_root() + "/src/cosa/rest/routers/notifications.py" ) as handle:
        source = handle.read()
    assert re.search( r'"expeditor prediction auto submit enabled",\s*default=False', source ), "route fallback must be False"


def test_every_splainer_row_is_marked_dormant():
    splainer = cu.get_project_root() + "/src/conf/lupin-app-splainer.ini"
    for key in KEYS:
        assert _line( splainer, key ).startswith( "Dormant" ), f"{key!r} explainer must start with Dormant"


def test_the_ini_comment_says_dormant():
    with open( cu.get_project_root() + "/src/conf/lupin-app.ini" ) as handle:
        assert "# DORMANT since 18 Nov 2026" in handle.read()


def test_both_capability_pages_mark_the_auto_submit_keys_dormant():
    """The expeditor guide and the prediction engine page each carry the marker beside the key."""
    root = cu.get_project_root()
    for page in ( "prediction-engine.md", "runtime-argument-expeditor.md" ):
        with open( f"{root}/src/docs/wiki/capabilities/{page}" ) as handle:
            text = handle.read()
        assert "**Dormant**" in text, f"{page} must carry the Dormant marker"
        assert "expeditor prediction auto submit enabled" in text, f"{page} must name the switch"
