"""
The browser must NEVER invent a session ID the server did not issue.

🔨 RICK RULED 2026-09-02 (row a501a714, option A): remove the fallback, surface
the failure. This file REPLACES test_browser_fallback_session_id_is_server_valid.py,
which pinned the opposite property — that the invented id was well FORMED. That
test was correct for its moment and its subject no longer exists.

WHY REMOVAL RATHER THAN A BETTER GENERATOR, the three measured reasons from the
row, kept here because a guard whose reason lives elsewhere gets deleted by the
next person who finds it inconvenient:

  1. A self-minted id was the ONLY source of session-id COLLISIONS. Server ids
     come from TwoWordIdGenerator, which holds a uniqueness set and opens a new
     namespace cycle when one fills, so a server id never repeats. The fallback
     drew at random from 10 adjectives x 10 animals with NO uniqueness check,
     and 50 of those 100 names lay inside the server's own cycle-1 space.
  2. A collision was PROBED, not inferred: connecting a second user on an id
     already held by a first OVERWRITES active_connections[id], flips
     session_to_user[id], and leaves the first user's socket unreachable. That
     is one user's notifications arriving at another user's socket.
  3. It PERSISTED to localStorage and was read back without re-asking the
     server, so one transient failure pinned that browser to a self-minted id
     for every later page load — a transient fault with a permanent symptom.

⚠️ THE HAZARD THIS GUARDS IS A REGRESSION THAT LOOKS LIKE A KINDNESS. Restoring
a fallback makes a broken page work again, which is exactly why someone will do
it. The failure it re-introduces is silent and lands on a DIFFERENT user than
the one being helped.
"""
import re
from pathlib import Path

import cosa.utils.util as cu


NOTIFICATIONS_JS = "/src/lupin_app/static/js/notifications.js"


def _source():
    return Path( cu.get_project_root() + NOTIFICATIONS_JS ).read_text()


def test_no_session_id_generator_survives_in_the_shipped_asset():
    """
    The generator is gone and must not come back under any name.

    Matches the SHAPE rather than the old function name: a two-word template
    built from a random adjective and animal is the thing being banned, so a
    rename does not slip past.
    """
    source = _source()

    named  = re.findall( r"generateFallbackSessionId", source )
    shaped = re.findall( r"return\s+`\$\{\s*adj\w*\s*\}.*?\$\{\s*animal\w*\s*\}`", source )

    assert named == [], (
        f"generateFallbackSessionId is back in {NOTIFICATIONS_JS} ({len( named )} hits). "
        f"Rick ruled it out on 2026-09-02 (row a501a714): an id the server never "
        f"issued can collide with a real session and cross-route notifications."
    )
    assert shaped == [], (
        f"a two-word session-id generator is back in {NOTIFICATIONS_JS} under another "
        f"name ({shaped}). The ban is on the behaviour, not on the identifier."
    )


def test_the_shape_matcher_can_actually_find_a_generator():
    """
    Positive control. Without it the test above passes for the wrong reason the
    moment the regex stops matching anything — a green that means the instrument
    broke, not that the tree is clean.
    """
    planted = "        return `${adj} ${animal}`;"
    shaped  = re.findall( r"return\s+`\$\{\s*adj\w*\s*\}.*?\$\{\s*animal\w*\s*\}`", planted )

    assert len( shaped ) == 1, (
        "the shape matcher cannot find a generator it is pointed straight at, so "
        "its zero-result on the real asset is evidence of nothing."
    )


def test_the_failure_path_throws_rather_than_returning_an_id():
    """
    The catch must hand the failure UP, not swallow it into a working socket.

    Read off disk rather than restated: a test asserting `throw` in a string it
    wrote itself would pass while the asset returned an id.
    """
    source = _source()

    assert "throw this.failSessionIdAcquisition(" in source, (
        "the session-id catch no longer throws. If it returns an id instead, the "
        "browser is inventing one again — see this file's docstring."
    )
    assert "return this.useFallbackSessionId(" not in source, (
        "the old fallback return is back in the catch."
    )
