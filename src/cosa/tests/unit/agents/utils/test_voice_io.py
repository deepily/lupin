"""
Unit tests for cosa/agents/utils/voice_io.py.

voice_io is a module-global voice-first I/O layer. Every test resets the module
globals via an autouse fixture. Seams boundary-mocked:
- `_cosa_interface`  — injected fake module (AsyncMock methods); no real voice/network
- `builtins.input`   — patched for CLI-fallback paths
- `_is_interactive`  — patched to steer interactive vs background (queue/Docker) branches
ZERO API spend; nothing leaves the process.
"""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import cosa.agents.utils.voice_io as mod


# --------------------------------------------------------------------------- #
# fixtures + helpers
# --------------------------------------------------------------------------- #
@pytest.fixture( autouse=True )
def _reset_state():
    mod._force_cli_mode  = False
    mod._voice_available = None
    mod._cosa_interface  = None
    mod._job_id          = None
    yield
    mod._force_cli_mode  = False
    mod._voice_available = None
    mod._cosa_interface  = None
    mod._job_id          = None


def _run( coro ):
    return asyncio.run( coro )


def _fake_iface( **methods ):
    m = MagicMock()
    m.__name__         = "fake.cosa_interface"
    m.notify_progress  = methods.get( "notify_progress",  AsyncMock() )
    m.ask_confirmation = methods.get( "ask_confirmation", AsyncMock() )
    m.get_feedback     = methods.get( "get_feedback",     AsyncMock() )
    m.present_choices  = methods.get( "present_choices",  AsyncMock() )
    return m


def _enter_voice_mode( iface ):
    """Configure an interface and force the voice-available cache True (no probe)."""
    mod.configure( iface )
    mod._voice_available = True


# =========================================================================== #
# _is_interactive
# =========================================================================== #
def test_is_interactive_true():
    fake_stdin = MagicMock()
    fake_stdin.isatty.return_value = True
    with patch.object( mod.sys, "stdin", fake_stdin ):
        assert mod._is_interactive() is True


def test_is_interactive_false_when_not_tty():
    fake_stdin = MagicMock()
    fake_stdin.isatty.return_value = False
    with patch.object( mod.sys, "stdin", fake_stdin ):
        assert mod._is_interactive() is False


def test_is_interactive_exception_returns_false():
    fake_stdin = MagicMock()
    fake_stdin.isatty.side_effect = ValueError( "detached" )
    with patch.object( mod.sys, "stdin", fake_stdin ):
        assert mod._is_interactive() is False


# =========================================================================== #
# configure / set_cli_mode / reset_voice_check / set_job_id / clear_job_id
# =========================================================================== #
def test_configure_without_job_id():
    iface = _fake_iface()
    mod.configure( iface )
    assert mod._cosa_interface is iface
    assert mod._job_id is None
    assert mod._voice_available is None


def test_configure_with_job_id():
    mod.configure( _fake_iface(), job_id="dr-a1b2c3d4" )
    assert mod._job_id == "dr-a1b2c3d4"


def test_set_cli_mode_enable_and_disable():
    mod.set_cli_mode( True )
    assert mod._force_cli_mode is True
    mod.set_cli_mode( False )
    assert mod._force_cli_mode is False


def test_reset_voice_check():
    mod._voice_available = True
    mod.reset_voice_check()
    assert mod._voice_available is None


def test_set_and_clear_job_id():
    mod.set_job_id( "pg-deadbeef" )
    assert mod._job_id == "pg-deadbeef"
    mod.clear_job_id()
    assert mod._job_id is None


# =========================================================================== #
# is_voice_available
# =========================================================================== #
def test_is_voice_available_cached():
    mod._voice_available = True
    assert _run( mod.is_voice_available() ) is True


def test_is_voice_available_not_configured():
    assert _run( mod.is_voice_available() ) is False
    assert mod._voice_available is False


def test_is_voice_available_probe_succeeds():
    mod.configure( _fake_iface() )
    assert _run( mod.is_voice_available() ) is True


def test_is_voice_available_probe_fails():
    mod.configure( _fake_iface( notify_progress=AsyncMock( side_effect=RuntimeError( "no voice" ) ) ) )
    assert _run( mod.is_voice_available() ) is False


# =========================================================================== #
# get_mode_description / is_cli_mode
# =========================================================================== #
def test_get_mode_description_forced():
    mod._force_cli_mode = True
    assert "forced" in mod.get_mode_description().lower()


def test_get_mode_description_not_configured():
    assert "not configured" in mod.get_mode_description().lower()


def test_get_mode_description_voice_mode():
    mod.configure( _fake_iface() )
    mod._voice_available = True
    assert "voice mode" in mod.get_mode_description().lower()


def test_get_mode_description_voice_unavailable():
    mod.configure( _fake_iface() )
    mod._voice_available = False
    assert "voice unavailable" in mod.get_mode_description().lower()


def test_get_mode_description_not_determined():
    mod.configure( _fake_iface() )
    mod._voice_available = None
    assert "not yet determined" in mod.get_mode_description().lower()


def test_is_cli_mode_forced_and_unconfigured():
    assert mod.is_cli_mode() is True       # unconfigured
    mod.configure( _fake_iface() )
    assert mod.is_cli_mode() is False
    mod.set_cli_mode( True )
    assert mod.is_cli_mode() is True


# =========================================================================== #
# notify
# =========================================================================== #
def test_notify_cli_mode_prints( capsys ):
    mod.set_cli_mode( True )
    _run( mod.notify( "hello", abstract="extra ctx" ) )
    out = capsys.readouterr().out
    assert "hello" in out
    assert "Context:" in out


def test_notify_unconfigured_prints_no_abstract( capsys ):
    _run( mod.notify( "bare" ) )
    assert "bare" in capsys.readouterr().out


def test_notify_voice_dispatch_and_job_id_autoinject():
    iface = _fake_iface()
    _enter_voice_mode( iface )
    mod._job_id = "dr-deadbeef"
    _run( mod.notify( "progress" ) )
    iface.notify_progress.assert_awaited_once()
    assert iface.notify_progress.await_args[ 1 ][ "job_id" ] == "dr-deadbeef"


def test_notify_voice_dispatch_failure_falls_back_to_print( capsys ):
    iface = _fake_iface( notify_progress=AsyncMock( side_effect=RuntimeError( "boom" ) ) )
    mod.configure( iface )
    _run( mod.notify( "progress" ) )
    assert "progress" in capsys.readouterr().out


# =========================================================================== #
# ask_yes_no
# =========================================================================== #
def test_ask_yes_no_cli_non_interactive_uses_default( capsys ):
    mod.set_cli_mode( True )
    with patch.object( mod, "_is_interactive", return_value=False ):
        assert _run( mod.ask_yes_no( "Proceed?", default="yes", abstract="ctx" ) ) is True
    assert "auto-default" in capsys.readouterr().out


def test_ask_yes_no_cli_interactive_yes():
    mod.set_cli_mode( True )
    with patch.object( mod, "_is_interactive", return_value=True ), \
         patch( "builtins.input", return_value="yes" ):
        assert _run( mod.ask_yes_no( "Proceed?" ) ) is True


def test_ask_yes_no_cli_interactive_empty_uses_default():
    mod.set_cli_mode( True )
    with patch.object( mod, "_is_interactive", return_value=True ), \
         patch( "builtins.input", return_value="" ):
        assert _run( mod.ask_yes_no( "Proceed?", default="yes" ) ) is True


def test_ask_yes_no_voice_success():
    iface = _fake_iface( ask_confirmation=AsyncMock( return_value=True ) )
    _enter_voice_mode( iface )
    assert _run( mod.ask_yes_no( "Proceed?" ) ) is True


def test_ask_yes_no_voice_failure_non_interactive_default():
    iface = _fake_iface( ask_confirmation=AsyncMock( side_effect=RuntimeError( "x" ) ) )
    _enter_voice_mode( iface )
    with patch.object( mod, "_is_interactive", return_value=False ):
        assert _run( mod.ask_yes_no( "Proceed?", default="yes" ) ) is True


def test_ask_yes_no_voice_failure_interactive_cli_fallback():
    iface = _fake_iface( ask_confirmation=AsyncMock( side_effect=RuntimeError( "x" ) ) )
    _enter_voice_mode( iface )
    with patch.object( mod, "_is_interactive", return_value=True ), \
         patch( "builtins.input", return_value="y" ):
        assert _run( mod.ask_yes_no( "Proceed?", abstract="ctx" ) ) is True


def test_ask_yes_no_voice_failure_interactive_no_abstract():
    # abstract falsy → `if abstract:` False arc ( 383->385 ) → straight to input
    iface = _fake_iface( ask_confirmation=AsyncMock( side_effect=RuntimeError( "x" ) ) )
    _enter_voice_mode( iface )
    with patch.object( mod, "_is_interactive", return_value=True ), \
         patch( "builtins.input", return_value="yes" ):
        assert _run( mod.ask_yes_no( "Proceed?" ) ) is True


def test_job_id_autoinject_across_blocking_helpers():
    # exercises the `if job_id is None and _job_id is not None` auto-inject line
    # in ask_yes_no (357), get_input (419), choose (485), present_choices (597)
    mod.set_cli_mode( True )
    mod._job_id = "dr-deadbeef"
    with patch.object( mod, "_is_interactive", return_value=False ):
        assert _run( mod.ask_yes_no( "Q?", default="yes" ) ) is True
        assert _run( mod.get_input( "Q?" ) ) is None
        assert _run( mod.choose( "Q?", [ "a", "b" ] ) ) == "a"
        assert _run( mod.present_choices( _Q_SINGLE ) ) == { "answers": { "Pick": "a" } }


# =========================================================================== #
# get_input
# =========================================================================== #
def test_get_input_cli_non_interactive_returns_none():
    mod.set_cli_mode( True )
    with patch.object( mod, "_is_interactive", return_value=False ):
        assert _run( mod.get_input( "Name?" ) ) is None


def test_get_input_cli_interactive_returns_text():
    mod.set_cli_mode( True )
    with patch.object( mod, "_is_interactive", return_value=True ), \
         patch( "builtins.input", return_value="Rick" ):
        assert _run( mod.get_input( "Name?" ) ) == "Rick"


def test_get_input_cli_interactive_empty_disallowed_returns_none():
    mod.set_cli_mode( True )
    with patch.object( mod, "_is_interactive", return_value=True ), \
         patch( "builtins.input", return_value="" ):
        assert _run( mod.get_input( "Name?", allow_empty=False ) ) is None


def test_get_input_voice_success():
    iface = _fake_iface( get_feedback=AsyncMock( return_value="spoken answer" ) )
    _enter_voice_mode( iface )
    assert _run( mod.get_input( "Name?" ) ) == "spoken answer"


def test_get_input_voice_empty_disallowed_returns_none():
    iface = _fake_iface( get_feedback=AsyncMock( return_value="" ) )
    _enter_voice_mode( iface )
    assert _run( mod.get_input( "Name?", allow_empty=False ) ) is None


def test_get_input_voice_failure_non_interactive_none():
    iface = _fake_iface( get_feedback=AsyncMock( side_effect=RuntimeError( "x" ) ) )
    _enter_voice_mode( iface )
    with patch.object( mod, "_is_interactive", return_value=False ):
        assert _run( mod.get_input( "Name?" ) ) is None


def test_get_input_voice_failure_interactive_cli():
    iface = _fake_iface( get_feedback=AsyncMock( side_effect=RuntimeError( "x" ) ) )
    _enter_voice_mode( iface )
    with patch.object( mod, "_is_interactive", return_value=True ), \
         patch( "builtins.input", return_value="typed" ):
        assert _run( mod.get_input( "Name?" ) ) == "typed"


# =========================================================================== #
# choose
# =========================================================================== #
def test_choose_empty_options_raises():
    with pytest.raises( ValueError, match="cannot be empty" ):
        _run( mod.choose( "Pick", [] ) )


def test_choose_cli_non_interactive_first_label():
    mod.set_cli_mode( True )
    with patch.object( mod, "_is_interactive", return_value=False ):
        assert _run( mod.choose( "Pick", [ "a", "b" ] ) ) == "a"


def test_choose_cli_interactive_valid_number():
    mod.set_cli_mode( True )
    opts = [ { "label": "a", "description": "first" }, "b", 99 ]   # str / dict / non-str-non-dict
    with patch.object( mod, "_is_interactive", return_value=True ), \
         patch( "builtins.input", return_value="2" ):
        assert _run( mod.choose( "Pick", opts ) ) == "b"


def test_choose_cli_interactive_custom_other():
    mod.set_cli_mode( True )
    with patch.object( mod, "_is_interactive", return_value=True ), \
         patch( "builtins.input", side_effect=[ "3", "my custom" ] ):
        assert _run( mod.choose( "Pick", [ "a", "b" ], allow_custom=True ) ) == "my custom"


def test_choose_cli_interactive_custom_other_empty_uses_default():
    mod.set_cli_mode( True )
    with patch.object( mod, "_is_interactive", return_value=True ), \
         patch( "builtins.input", side_effect=[ "3", "" ] ):
        assert _run( mod.choose( "Pick", [ "a", "b" ], allow_custom=True ) ) == "a"


def test_choose_cli_interactive_non_numeric_uses_default( capsys ):
    mod.set_cli_mode( True )
    with patch.object( mod, "_is_interactive", return_value=True ), \
         patch( "builtins.input", return_value="abc" ):
        assert _run( mod.choose( "Pick", [ "a", "b" ] ) ) == "a"
    assert "Invalid selection" in capsys.readouterr().out


def test_choose_cli_interactive_out_of_range_uses_default():
    mod.set_cli_mode( True )
    with patch.object( mod, "_is_interactive", return_value=True ), \
         patch( "builtins.input", return_value="99" ):
        assert _run( mod.choose( "Pick", [ "a", "b" ] ) ) == "a"


def test_choose_voice_selection_in_labels():
    iface = _fake_iface( present_choices=AsyncMock( return_value={ "answers": { "Choice": "b" } } ) )
    _enter_voice_mode( iface )
    assert _run( mod.choose( "Pick", [ "a", "b" ] ) ) == "b"


def test_choose_voice_custom_other_not_in_labels():
    iface = _fake_iface( present_choices=AsyncMock( return_value={ "answers": { "Choice": "custom!" } } ) )
    _enter_voice_mode( iface )
    assert _run( mod.choose( "Pick", [ "a", "b" ] ) ) == "custom!"


def test_choose_voice_no_selection_returns_default():
    iface = _fake_iface( present_choices=AsyncMock( return_value={ "answers": {} } ) )
    _enter_voice_mode( iface )
    assert _run( mod.choose( "Pick", [ "a", "b" ] ) ) == "a"


def test_choose_voice_failure_returns_default():
    iface = _fake_iface( present_choices=AsyncMock( side_effect=RuntimeError( "x" ) ) )
    _enter_voice_mode( iface )
    assert _run( mod.choose( "Pick", [ "a", "b" ] ) ) == "a"


# =========================================================================== #
# present_choices
# =========================================================================== #
_Q_SINGLE = [ { "question": "Which?", "header": "Pick", "multiSelect": False,
                "options": [ { "label": "a", "description": "first" }, { "label": "b" } ] } ]
_Q_MULTI  = [ { "question": "Which?", "header": "Pick", "multiSelect": True,
                "options": [ { "label": "a" }, { "label": "b" } ] } ]


def test_present_choices_cli_non_interactive_single_and_multi():
    mod.set_cli_mode( True )
    with patch.object( mod, "_is_interactive", return_value=False ):
        out_single = _run( mod.present_choices( _Q_SINGLE ) )
        out_multi  = _run( mod.present_choices( _Q_MULTI ) )
    assert out_single == { "answers": { "Pick": "a" } }
    assert out_multi  == { "answers": { "Pick": [ "a" ] } }


def test_present_choices_cli_non_interactive_empty_options():
    mod.set_cli_mode( True )
    q = [ { "header": "Pick", "multiSelect": False, "options": [] } ]
    with patch.object( mod, "_is_interactive", return_value=False ):
        assert _run( mod.present_choices( q ) ) == { "answers": { "Pick": "" } }


def test_present_choices_cli_interactive_single_valid( capsys ):
    mod.set_cli_mode( True )
    with patch.object( mod, "_is_interactive", return_value=True ), \
         patch( "builtins.input", return_value="2" ):
        out = _run( mod.present_choices( _Q_SINGLE, abstract="ctx" ) )
    assert out == { "answers": { "Pick": "b" } }
    assert "ctx" in capsys.readouterr().out


def test_present_choices_cli_interactive_single_out_of_range_default():
    mod.set_cli_mode( True )
    with patch.object( mod, "_is_interactive", return_value=True ), \
         patch( "builtins.input", return_value="99" ):
        assert _run( mod.present_choices( _Q_SINGLE ) ) == { "answers": { "Pick": "a" } }


def test_present_choices_cli_interactive_single_custom_text():
    mod.set_cli_mode( True )
    with patch.object( mod, "_is_interactive", return_value=True ), \
         patch( "builtins.input", return_value="my own" ):
        assert _run( mod.present_choices( _Q_SINGLE ) ) == { "answers": { "Pick": "my own" } }


def test_present_choices_cli_interactive_multi_numbers():
    mod.set_cli_mode( True )
    with patch.object( mod, "_is_interactive", return_value=True ), \
         patch( "builtins.input", return_value="1,2" ):
        assert _run( mod.present_choices( _Q_MULTI ) ) == { "answers": { "Pick": [ "a", "b" ] } }


def test_present_choices_cli_interactive_multi_custom_text():
    mod.set_cli_mode( True )
    with patch.object( mod, "_is_interactive", return_value=True ), \
         patch( "builtins.input", return_value="freeform" ):
        assert _run( mod.present_choices( _Q_MULTI ) ) == { "answers": { "Pick": [ "freeform" ] } }


def test_present_choices_voice_success():
    iface = _fake_iface( present_choices=AsyncMock( return_value={ "answers": { "Pick": "a" } } ) )
    _enter_voice_mode( iface )
    assert _run( mod.present_choices( _Q_SINGLE ) ) == { "answers": { "Pick": "a" } }


def test_present_choices_voice_failure_returns_defaults():
    iface = _fake_iface( present_choices=AsyncMock( side_effect=RuntimeError( "x" ) ) )
    _enter_voice_mode( iface )
    assert _run( mod.present_choices( _Q_SINGLE ) ) == { "answers": { "Pick": "a" } }


# =========================================================================== #
# select_themes
# =========================================================================== #
_THEMES = [
    { "name": "T1", "description": "d1", "subquery_indices": [ 0, 1 ] },
    { "name": "T2", "description": "d2", "subquery_indices": [ 2 ] },
]


def test_select_themes_cli_non_interactive_all():
    mod.set_cli_mode( True )
    with patch.object( mod, "_is_interactive", return_value=False ):
        assert _run( mod.select_themes( _THEMES ) ) == [ 0, 1 ]


def test_select_themes_cli_interactive_all_keyword():
    mod.set_cli_mode( True )
    with patch.object( mod, "_is_interactive", return_value=True ), \
         patch( "builtins.input", return_value="all" ):
        assert _run( mod.select_themes( _THEMES ) ) == [ 0, 1 ]


def test_select_themes_cli_interactive_numbers():
    mod.set_cli_mode( True )
    with patch.object( mod, "_is_interactive", return_value=True ), \
         patch( "builtins.input", return_value="2" ):
        assert _run( mod.select_themes( _THEMES ) ) == [ 1 ]


def test_select_themes_cli_interactive_invalid_returns_empty():
    mod.set_cli_mode( True )
    with patch.object( mod, "_is_interactive", return_value=True ), \
         patch( "builtins.input", return_value="xyz" ):
        assert _run( mod.select_themes( _THEMES ) ) == []


def test_select_themes_voice_maps_names_to_indices():
    iface = _fake_iface( present_choices=AsyncMock( return_value={ "answers": { "Themes": [ "T2" ] } } ) )
    _enter_voice_mode( iface )
    assert _run( mod.select_themes( _THEMES ) ) == [ 1 ]


def test_select_themes_voice_single_string_coerced():
    iface = _fake_iface( present_choices=AsyncMock( return_value={ "answers": { "Themes": "T1" } } ) )
    _enter_voice_mode( iface )
    assert _run( mod.select_themes( _THEMES ) ) == [ 0 ]


def test_select_themes_voice_failure_notifies_and_raises():
    iface = _fake_iface( present_choices=AsyncMock( side_effect=RuntimeError( "voice gate down" ) ) )
    _enter_voice_mode( iface )
    with pytest.raises( RuntimeError, match="Theme selection failed" ):
        _run( mod.select_themes( _THEMES ) )
    iface.notify_progress.assert_awaited()   # failure notice fired


# =========================================================================== #
# select_topics
# =========================================================================== #
_TOPICS = [ { "topic": "Topic A", "objective": "obj a" }, { "topic": "Topic B", "objective": "obj b" } ]


def test_select_topics_cli_non_interactive_all():
    mod.set_cli_mode( True )
    with patch.object( mod, "_is_interactive", return_value=False ):
        assert _run( mod.select_topics( _TOPICS ) ) == [ 0, 1 ]


def test_select_topics_cli_interactive_all_keyword():
    mod.set_cli_mode( True )
    with patch.object( mod, "_is_interactive", return_value=True ), \
         patch( "builtins.input", return_value="all" ):
        assert _run( mod.select_topics( _TOPICS ) ) == [ 0, 1 ]


def test_select_topics_cli_interactive_none_keyword():
    mod.set_cli_mode( True )
    with patch.object( mod, "_is_interactive", return_value=True ), \
         patch( "builtins.input", return_value="none" ):
        assert _run( mod.select_topics( _TOPICS ) ) == []


def test_select_topics_cli_interactive_numbers():
    mod.set_cli_mode( True )
    with patch.object( mod, "_is_interactive", return_value=True ), \
         patch( "builtins.input", return_value="1" ):
        assert _run( mod.select_topics( _TOPICS ) ) == [ 0 ]


def test_select_topics_cli_interactive_invalid_defaults_all():
    mod.set_cli_mode( True )
    with patch.object( mod, "_is_interactive", return_value=True ), \
         patch( "builtins.input", return_value="bogus" ):
        assert _run( mod.select_topics( _TOPICS ) ) == [ 0, 1 ]


def test_select_topics_voice_maps_names_to_indices():
    iface = _fake_iface( present_choices=AsyncMock( return_value={ "answers": { "Topics": [ "Topic B" ] } } ) )
    _enter_voice_mode( iface )
    assert _run( mod.select_topics( _TOPICS ) ) == [ 1 ]


def test_select_topics_voice_single_string_coerced():
    iface = _fake_iface( present_choices=AsyncMock( return_value={ "answers": { "Topics": "Topic A" } } ) )
    _enter_voice_mode( iface )
    assert _run( mod.select_topics( _TOPICS ) ) == [ 0 ]


def test_select_topics_voice_failure_notifies_and_raises():
    iface = _fake_iface( present_choices=AsyncMock( side_effect=RuntimeError( "voice gate down" ) ) )
    _enter_voice_mode( iface )
    with pytest.raises( RuntimeError, match="Topic selection failed" ):
        _run( mod.select_topics( _TOPICS ) )
    iface.notify_progress.assert_awaited()
