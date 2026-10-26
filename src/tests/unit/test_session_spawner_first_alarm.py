"""
Unit tests for two small session_spawner helpers: _first_alarm and the unset-root arm.

Nothing in src calls _first_alarm today; the tests pin its contract so a caller can rely on it.
"""

from lupin_mcp.session_spawner import _first_alarm, _resolve_project_root


def _render( sub ):
    """A renderer that says something only for a sub-dict marked bad."""
    return f"alarm:{sub[ 'seat' ]}" if sub and sub.get( "bad" ) else None


def test_the_first_seat_with_something_to_say_wins():
    """Clean seats are skipped; the first alarming seat's line is returned, later ones ignored."""
    verdicts = [ { "venv": { "bad": False, "seat": "a" } },
                 { "venv": { "bad": True,  "seat": "b" } },
                 { "venv": { "bad": True,  "seat": "c" } } ]
    assert _first_alarm( verdicts, "venv", _render ) == "alarm:b"


def test_every_clean_seat_and_an_empty_list_give_none():
    """All clean, a missing key, or no seats at all: None."""
    assert _first_alarm( [ { "venv": { "bad": False, "seat": "a" } }, { } ], "venv", _render ) is None
    assert _first_alarm( [], "venv", _render ) is None


def test_the_key_names_which_sub_dict_is_rendered():
    """The renderer receives the sub-dict under the given key, not the whole verdict."""
    seen = []
    _first_alarm( [ { "placement": "P", "venv": "V" } ], "placement", lambda sub: seen.append( sub ) )
    assert seen == [ "P" ]


def test_a_project_cannot_be_resolved_without_lupin_root( monkeypatch ):
    """No LUPIN_ROOT in the environment: None, so the caller refuses instead of guessing a cwd."""
    monkeypatch.delenv( "LUPIN_ROOT", raising=False )
    assert _resolve_project_root( "lupin" ) is None
    monkeypatch.setenv( "LUPIN_ROOT", "" )
    assert _resolve_project_root( "lupin" ) is None
