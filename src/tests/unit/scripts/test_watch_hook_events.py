"""
Coverage ramp for `src/scripts/watch-hook-events.py` — 149 statements, 38 branches,
previously zero (row 9b1edfff).

LOAD MECHANISM: `importlib.import_module( "watch-hook-events" )` with `src/scripts` on
`sys.path`. The dashed filename is not a valid identifier so `import watch-hook-events` is a
syntax error, but `import_module` takes a STRING and never needs one — no
`spec_from_file_location`, no `runpy`, no subprocess. And nothing here risks pytest
collecting the script itself: `python_files` is pinned to `test_*.py`, so a script is not
collected by directory recursion or by explicit path (measured by Krishna, row `9ad838d6`).

WHAT THIS FILE IS. The script is a terminal watcher: it formats JSONL hook entries and tails
a file forever. Two things make it worth real tests rather than smoke:
  · the FORMATTERS decide what an operator sees about fleet state, and a wrong `owed=` or a
    missing `← STUCK` is a wrong picture of who is stuck;
  · `_follow()` is an infinite loop with rotation and truncation handling — the part most
    likely to be wrong and least likely to be exercised by running it.

🔴 NO REAL SLEEPING AND NO REAL TAILING. `_follow()` never returns on its own, so every test
of it drives a stub clock that raises a sentinel to break the loop at a chosen point. The
stub is installed as `mod.time`, a stand-in object — NOT `monkeypatch.setattr( mod.time,
"sleep", … )`, which would reach through and patch the real `time` module for every importer
in the process. Same for `mod.os` where a failure has to be injected.

⚠️ RENAME-PROOF ON PURPOSE. Every expected outcome value comes from the emitting side's
`OUTCOME_*` constants, never from a literal, so a value rename (there has already been one —
`poke` → `poked`, 2026-06-09) reddens these tests rather than sliding past them. That
matters because the script itself has one place that does NOT do this — see row filed
alongside this suite.
"""

import importlib
import io
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

_ROOT = os.environ.get( "LUPIN_ROOT", os.getcwd() )
for _p in ( os.path.join( _ROOT, "src", "scripts" ), os.path.join( _ROOT, "src" ) ):
    if _p not in sys.path:
        sys.path.insert( 0, _p )

whe = importlib.import_module( "watch-hook-events" )

from lupin_cli.claude_code.hooks.lib.heartbeat_decision import (
    OUTCOME_POKE, OUTCOME_HONORED, OUTCOME_NOT_OWED, OUTCOME_CAP_REACHED,
)
from lupin_cli.claude_code.hooks.lib.heartbeat_events import EVENT_IDLE


def _args( **over ):
    """The argparse namespace the module reads out of its own global."""
    base = { "all": False, "replay": False, "once": False, "no_color": True, "path": None }
    base.update( over )
    return SimpleNamespace( **base )


@pytest.fixture( autouse=True )
def _plain_args( monkeypatch ):
    """Colour off and every flag false unless a test says otherwise."""
    monkeypatch.setattr( whe, "_ARGS", _args() )


class _Clock:
    """
    A stand-in for the module's `time`. Installed AS `mod.time`, so the real time module is
    never touched — patching `mod.time.sleep` would reach through to every importer in the
    process (Krishna's hazard, row 9ad838d6).
    """
    class Stop( Exception ):
        """Breaks an otherwise-infinite loop at a chosen iteration."""

    def __init__( self, stop_after ):
        self.calls      = 0
        self.stop_after = stop_after

    def sleep( self, _seconds ):
        self.calls += 1
        if self.calls >= self.stop_after:
            raise _Clock.Stop()


# ── _project_root ─────────────────────────────────────────────────────────────

class TestProjectRoot:

    def test_lupin_root_wins_when_set( self, monkeypatch ):
        monkeypatch.setenv( "LUPIN_ROOT", "/somewhere/else" )
        assert whe._project_root() == Path( "/somewhere/else" )

    def test_falls_back_to_the_repo_the_script_lives_in( self, monkeypatch ):
        """
        The fallback is `parents[2]` from `<root>/src/scripts/watch-hook-events.py`. Asserted
        as a real repo root rather than a string: an off-by-one here would point the watcher
        at `<root>/src` and it would sit forever on a log path that never appears.
        """
        monkeypatch.delenv( "LUPIN_ROOT", raising=False )

        root = whe._project_root()

        assert ( root / "src" / "scripts" / "watch-hook-events.py" ).exists()

    def test_an_empty_lupin_root_is_treated_as_unset_not_as_the_filesystem_root( self, monkeypatch ):
        """
        `if env:` — an empty string must fall through to the file-relative fallback, not
        become `Path( "" )`, which is the CWD.

        ⚠️ ASSERTED AS AN ABSOLUTE PATH, and that is the whole test. Checking only that
        `root / "src" / "scripts" / …` exists passes for BOTH answers when pytest happens to
        run from the repo root: `Path( "" ) / "src" / …` is a relative path that resolves to
        the same file. Krishna's fourth reading of a survivor (row 9ad838d6) — the fixture
        could not discriminate, so the assertion was measuring the CWD, not the function.
        Caught by mutation M2, which survived the first version of this test.
        """
        monkeypatch.setenv( "LUPIN_ROOT", "" )

        root = whe._project_root()

        assert root.is_absolute(), "Path( '' ) is relative and only looks right from the repo root"
        assert root == Path( whe.__file__ ).resolve().parents[ 2 ]


# ── module bootstrap ──────────────────────────────────────────────────────────

class TestBootstrap:

    def test_importing_with_src_absent_from_the_path_inserts_it_at_the_front( self, monkeypatch ):
        """
        The import-time guard's TRUE half. It is skipped in a normal test run only because
        this very file puts `src` on the path before importing the module — so without a
        deliberate reload the line never executes, and the script's ability to find the hook
        constants when run standalone would be untested.

        `insert( 0, … )` and not append: the script imports `lupin_cli…heartbeat_decision`,
        and another `lupin_cli` earlier on the path would shadow it.
        """
        src = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
        monkeypatch.setattr( sys, "path", [ p for p in sys.path if p != src ] )

        importlib.reload( whe )

        assert sys.path[ 0 ] == src

    def test_reimporting_with_src_already_present_does_not_duplicate_it( self, monkeypatch ):
        """The FALSE half — an unconditional insert would grow sys.path on every import."""
        src    = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
        before = sys.path.count( src )
        assert before >= 1, "precondition: this module is already importable"

        importlib.reload( whe )

        assert sys.path.count( src ) == before


# ── colour ────────────────────────────────────────────────────────────────────

class TestColour:

    def test_no_color_flag_suppresses_ansi( self, monkeypatch ):
        monkeypatch.setattr( whe, "_ARGS", _args( no_color=True ) )
        monkeypatch.setattr( whe.sys, "stdout", SimpleNamespace( isatty=lambda: True ) )

        assert whe._no_color() is True
        assert whe._c( whe.C.RED, "hello" ) == "hello"

    def test_a_pipe_suppresses_ansi_even_without_the_flag( self, monkeypatch ):
        """
        The reason this matters: this watcher's output gets piped into files and greps, and
        escape codes in a log make it unsearchable.
        """
        monkeypatch.setattr( whe, "_ARGS", _args( no_color=False ) )
        monkeypatch.setattr( whe.sys, "stdout", SimpleNamespace( isatty=lambda: False ) )

        assert whe._no_color() is True
        assert whe._c( whe.C.RED, "hello" ) == "hello"

    def test_a_tty_without_the_flag_gets_colour( self, monkeypatch ):
        monkeypatch.setattr( whe, "_ARGS", _args( no_color=False ) )
        monkeypatch.setattr( whe.sys, "stdout", SimpleNamespace( isatty=lambda: True ) )

        assert whe._no_color() is False
        assert whe._c( whe.C.RED, "hello" ) == f"{whe.C.RED}hello{whe.C.RESET}"


# ── _hhmmss ───────────────────────────────────────────────────────────────────

class TestTimestamp:
    """
    A timestamp is the only thing tying a watched line to anything else in the fleet's logs,
    so a wrong-but-plausible one is worse than a visibly broken one. Both accepted formats
    are pinned, and so is every way the parse can give up.
    """

    def test_a_missing_timestamp_renders_as_a_placeholder_not_an_empty_column( self ):
        assert whe._hhmmss( None ) == "--:--:--"
        assert whe._hhmmss( "" )   == "--:--:--"

    def test_iso_is_parsed( self ):
        assert whe._hhmmss( "2026-06-06T01:45:55.123456" ) == "01:45:55"

    def test_a_trailing_z_is_accepted_as_utc( self ):
        """`fromisoformat` rejects a bare Z on older spellings; the module rewrites it."""
        assert whe._hhmmss( "2026-06-06T01:45:55Z" ) == "01:45:55"

    def test_the_projects_own_hook_log_format_is_parsed( self ):
        """`2026.06.06 @ 01:45 55,752ms` → `01:45:55` — the format the emitting side writes."""
        assert whe._hhmmss( "2026.06.06 @ 01:45 55,752ms" ) == "01:45:55"

    def test_the_project_format_without_a_seconds_field_pads_to_zero( self ):
        assert whe._hhmmss( "2026.06.06 @ 01:45" ) == "01:45:00"

    def test_a_seconds_field_with_no_digits_falls_back_to_zero( self ):
        """`digits[:2] or "00"` — a non-numeric tail must not produce `01:45:`."""
        assert whe._hhmmss( "2026.06.06 @ 01:45 abc" ) == "01:45:00"

    def test_a_single_digit_seconds_field_is_zero_PADDED_not_left_bare( self ):
        """
        `ss.zfill( 2 )`. The no-digits case above cannot test this: it produces "00", which
        is already two characters, so zfill is a no-op and the assertion holds with or
        without it. Only a one-digit value separates `01:45:07` from `01:45:7` — and a
        ragged column is exactly what makes a scrolling watcher unreadable.
        Caught by mutation M5, which survived until this case existed.
        """
        assert whe._hhmmss( "2026.06.06 @ 01:45 7ms" ) == "01:45:07"

    def test_an_at_sign_with_no_clock_after_it_gives_up_to_the_raw_prefix( self ):
        """The `":" in hm` guard: no colon means this is not the project format at all."""
        assert whe._hhmmss( "2026.06.06 @ garbage" ) == "2026.06."

    def test_something_unparseable_shows_its_first_eight_characters( self ):
        """
        The final fallback shows the raw value rather than a placeholder — an operator
        seeing `not-a-ti` knows the emitter is wrong, where `--:--:--` would look like a
        missing field.
        """
        assert whe._hhmmss( "not-a-timestamp-at-all" ) == "not-a-ti"

    def test_a_non_string_timestamp_does_not_raise( self ):
        """`str( ts )` up front — an integer epoch from a future emitter must not crash the watcher."""
        assert whe._hhmmss( 1234567890 ) == "12345678"


# ── _format_oracle ────────────────────────────────────────────────────────────

class TestFormatOracle:
    """
    The headline line. Every expected outcome value comes from the emitting side's constants,
    never a literal, so a rename reddens these rather than sliding past.
    """

    def _line( self, **over ):
        entry = { "ts": "2026-06-06T01:45:55", "outcome": OUTCOME_POKE, "persona": "Maya",
                  "work_owed": True, "owed_items": 2, "poke_count": 1, "cap": 3 }
        entry.update( over )
        return whe._format_oracle( entry )

    def test_a_working_line_carries_persona_outcome_owed_and_poke_budget( self ):
        line = self._line()

        assert "Maya" in line
        assert OUTCOME_POKE in line
        assert "working" in line
        assert "owed=True(2)" in line
        assert "poke=1/3" in line

    def test_each_outcome_gets_its_own_label( self ):
        assert "idle & free"  in self._line( outcome=OUTCOME_NOT_OWED )
        assert "working"      in self._line( outcome=OUTCOME_POKE )
        assert "blocked"      in self._line( outcome=OUTCOME_HONORED )
        assert "idle & STUCK" in self._line( outcome=OUTCOME_CAP_REACHED )
        assert "idle beacon"  in self._line( outcome=EVENT_IDLE )

    def test_an_unknown_outcome_renders_as_a_question_mark_rather_than_crashing( self ):
        """
        A new outcome value from a newer emitter must degrade, not take the watcher down —
        the operator still sees the raw value and can tell something is newer than the tool.
        """
        line = self._line( outcome="teleported" )

        assert "teleported" in line
        assert "(?)" in line

    def test_a_missing_outcome_key_also_degrades( self ):
        entry = { "ts": "x", "persona": "Maya" }
        assert "?" in whe._format_oracle( entry )

    def test_cap_reached_gets_the_stuck_marker_and_nothing_else_does( self ):
        """
        The marker is the whole point of the line — it is what an operator scans for. Driven
        off the CONSTANT, so if the value is ever renamed this test reddens rather than
        quietly losing the marker.
        """
        assert "← STUCK" in     self._line( outcome=OUTCOME_CAP_REACHED )
        assert "← STUCK" not in self._line( outcome=OUTCOME_POKE )
        assert "← STUCK" not in self._line( outcome=OUTCOME_HONORED )
        assert "← STUCK" not in self._line( outcome=OUTCOME_NOT_OWED )

    def test_a_missing_persona_falls_back_to_the_session_id_prefix( self ):
        line = whe._format_oracle( { "session_id": "d7a687c7-d17b-48be", "outcome": OUTCOME_POKE } )
        assert "d7a687c7" in line
        assert "d17b" not in line, "only the first 8 characters belong on a fixed-width line"

    def test_no_persona_and_no_session_id_says_unknown( self ):
        assert "unknown" in whe._format_oracle( { "outcome": OUTCOME_POKE } )

    def test_an_empty_persona_string_also_falls_back( self ):
        """`e.get( "persona" ) or …` — an empty string is falsy and must not print a blank column."""
        line = whe._format_oracle( { "persona": "", "session_id": "abcdefgh1234", "outcome": OUTCOME_POKE } )
        assert "abcdefgh" in line

    def test_owed_items_absent_prints_the_flag_without_a_count( self ):
        assert "owed=True " in self._line( owed_items=None )

    def test_owed_items_zero_still_prints_the_count( self ):
        """
        `if owed_items is not None` rather than a truthiness test: zero owed items is a real
        measurement and `owed=True(0)` is the interesting disagreement to see.
        """
        assert "owed=True(0)" in self._line( owed_items=0 )

    def test_awaiting_is_appended_only_when_present( self ):
        assert "awaiting=peer:Maria" in self._line( awaiting="peer:Maria" )
        assert "awaiting=" not in    self._line( awaiting=None )

    def test_missing_poke_and_cap_render_as_question_marks( self ):
        entry = { "outcome": OUTCOME_POKE, "persona": "Maya" }
        assert "poke=?/?" in whe._format_oracle( entry )


# ── _format_generic ───────────────────────────────────────────────────────────

class TestFormatGeneric:

    def test_joins_the_fields_that_are_present_and_skips_the_ones_that_are_not( self ):
        line = whe._format_generic( { "ts": "2026-06-06T01:45:55", "phase": "tool_use",
                                      "hook": "PreToolUse", "session_id": "d7a687c7",
                                      "tool": "Bash" } )

        assert "01:45:55" in line
        assert "tool_use" in line and "PreToolUse" in line and "Bash" in line

    def test_event_stands_in_when_there_is_no_phase( self ):
        """`phase or event` — one emitter writes `phase`, another `event`; neither wins by default."""
        assert "SessionStart" in whe._format_generic( { "event": "SessionStart" } )

    def test_an_entry_with_nothing_printable_still_yields_a_line( self ):
        """An empty body must not raise on the join — a blank row is a visible anomaly, a crash is not."""
        assert whe._format_generic( {} )

    def test_an_error_field_is_appended_and_labelled( self ):
        assert "error=boom" in whe._format_generic( { "phase": "x", "error": "boom" } )

    def test_a_heartbeat_phase_gets_the_heart_marker( self ):
        assert "🫀" in whe._format_generic( { "phase": "heartbeat_emit_error" } )

    def test_a_non_heartbeat_phase_gets_the_plain_marker( self ):
        line = whe._format_generic( { "phase": "tool_use" } )
        assert "🫀" not in line
        assert "·" in line

    def test_a_none_phase_does_not_crash_the_marker_test( self ):
        """`( phase or "" ).startswith` — a None phase must not raise on startswith."""
        assert "·" in whe._format_generic( { "event": "x", "phase": None } )


# ── _render ───────────────────────────────────────────────────────────────────

class TestRender:

    def test_a_blank_line_renders_nothing( self ):
        assert whe._render( "" ) is None
        assert whe._render( "   \n" ) is None

    def test_unparseable_json_is_SHOWN_rather_than_swallowed( self ):
        """
        The deliberate choice worth pinning: a corrupt line is displayed raw. Dropping it
        would make a truncated write look like an idle fleet, which is the one thing this
        watcher must never do.
        """
        assert "{not json" in whe._render( "{not json" )

    def test_an_oracle_entry_takes_the_headline_format( self ):
        raw = json.dumps( { "phase": "heartbeat_oracle", "outcome": OUTCOME_CAP_REACHED,
                            "persona": "Maya", "poke_count": 3, "cap": 3 } )
        assert "← STUCK" in whe._render( raw )

    def test_a_heartbeat_family_entry_renders_generically_without_all( self ):
        assert whe._render( json.dumps( { "phase": "heartbeat_emit_error" } ) ) is not None

    def test_a_non_heartbeat_entry_is_FILTERED_OUT_by_default( self ):
        """The default is heartbeat-only; without this the stream is unreadable."""
        assert whe._render( json.dumps( { "phase": "tool_use" } ) ) is None

    def test_all_shows_the_entries_the_default_filters( self, monkeypatch ):
        monkeypatch.setattr( whe, "_ARGS", _args( all=True ) )
        assert whe._render( json.dumps( { "phase": "tool_use" } ) ) is not None

    def test_every_declared_heartbeat_phase_survives_the_filter( self ):
        """
        Pinned as a set rather than one example: this tuple IS the filter, and a phase
        dropped from it disappears from the default view silently.
        """
        for phase in whe._HEARTBEAT_PHASES:
            assert whe._render( json.dumps( { "phase": phase } ) ) is not None, phase


# ── _emit ─────────────────────────────────────────────────────────────────────

class TestEmit:

    def test_prints_what_render_returns( self, capsys ):
        whe._emit( json.dumps( { "phase": "heartbeat_oracle", "outcome": OUTCOME_POKE,
                                 "persona": "Maya" } ) )
        assert "Maya" in capsys.readouterr().out

    def test_prints_nothing_for_a_filtered_line( self, capsys ):
        whe._emit( json.dumps( { "phase": "tool_use" } ) )
        assert capsys.readouterr().out == ""


# ── _print_existing ───────────────────────────────────────────────────────────

class TestPrintExisting:

    def test_a_missing_log_is_silent_rather_than_an_error( self, monkeypatch, tmp_path, capsys ):
        """A watcher started before the first hook fires must not look broken."""
        monkeypatch.setattr( whe, "LOG_PATH", tmp_path / "absent.jsonl" )

        whe._print_existing()

        assert capsys.readouterr().out == ""

    def test_every_line_of_an_existing_log_is_rendered_in_order( self, monkeypatch, tmp_path, capsys ):
        log = tmp_path / "hook-events.jsonl"
        log.write_text( "\n".join( [
            json.dumps( { "phase": "heartbeat_oracle", "outcome": OUTCOME_POKE,    "persona": "First"  } ),
            json.dumps( { "phase": "tool_use" } ),
            json.dumps( { "phase": "heartbeat_oracle", "outcome": OUTCOME_HONORED, "persona": "Second" } ),
        ] ) + "\n" )
        monkeypatch.setattr( whe, "LOG_PATH", log )

        whe._print_existing()

        out = capsys.readouterr().out
        assert out.index( "First" ) < out.index( "Second" )
        assert "tool_use" not in out, "the default filter applies to replayed history too"


# ── _follow ───────────────────────────────────────────────────────────────────

class TestFollow:
    """
    The infinite loop, and the part least likely to be exercised by simply running the tool:
    an operator notices a formatting bug in a second, and notices a missed rotation never.

    Every test here installs `_Clock` AS `mod.time` and lets it raise once the loop has been
    driven far enough. Nothing sleeps and nothing tails a real file.
    """

    def _run( self, monkeypatch, stop_after ):
        clock = _Clock( stop_after )
        monkeypatch.setattr( whe, "time", clock )
        with pytest.raises( _Clock.Stop ):
            whe._follow()
        return clock

    def test_waits_for_a_log_that_does_not_exist_yet_instead_of_exiting( self, monkeypatch, tmp_path, capsys ):
        """
        The watcher is routinely started before the first hook fires. Exiting there would
        make the operator think the fleet is silent when the file simply has not appeared.
        """
        monkeypatch.setattr( whe, "LOG_PATH", tmp_path / "not-yet.jsonl" )

        self._run( monkeypatch, stop_after=1 )

        assert "watching" in capsys.readouterr().out

    def test_starts_at_the_TAIL_so_history_does_not_replay_by_default( self, monkeypatch, tmp_path, capsys ):
        """
        `f.seek( 0, SEEK_END )`. Without it, every start would dump the whole backlog — and
        an operator watching for a live change would scroll past thousands of old lines.
        """
        log = tmp_path / "hook-events.jsonl"
        log.write_text( json.dumps( { "phase": "heartbeat_oracle", "outcome": OUTCOME_POKE,
                                      "persona": "Ancient" } ) + "\n" )
        monkeypatch.setattr( whe, "LOG_PATH", log )

        self._run( monkeypatch, stop_after=1 )

        assert "Ancient" not in capsys.readouterr().out

    def test_replay_prints_the_history_before_following( self, monkeypatch, tmp_path, capsys ):
        """The other half of the same branch — `--replay` must NOT seek to the end."""
        log = tmp_path / "hook-events.jsonl"
        log.write_text( json.dumps( { "phase": "heartbeat_oracle", "outcome": OUTCOME_POKE,
                                      "persona": "Ancient" } ) + "\n" )
        monkeypatch.setattr( whe, "LOG_PATH", log )
        monkeypatch.setattr( whe, "_ARGS", _args( replay=True ) )

        self._run( monkeypatch, stop_after=1 )

        assert "Ancient" in capsys.readouterr().out

    def test_a_line_appended_while_following_is_emitted( self, monkeypatch, tmp_path, capsys ):
        """
        The actual job. The append happens on the clock's first tick, so the loop reads it on
        the pass after the one that found the file empty.
        """
        log = tmp_path / "hook-events.jsonl"
        log.write_text( "" )
        monkeypatch.setattr( whe, "LOG_PATH", log )

        clock = _Clock( stop_after=3 )
        original_sleep = clock.sleep
        def _sleep_and_append( seconds ):
            if clock.calls == 0:
                with open( log, "a" ) as f:
                    f.write( json.dumps( { "phase": "heartbeat_oracle",
                                           "outcome": OUTCOME_CAP_REACHED,
                                           "persona": "Live" } ) + "\n" )
            original_sleep( seconds )
        monkeypatch.setattr( whe, "time", SimpleNamespace( sleep=_sleep_and_append ) )

        with pytest.raises( _Clock.Stop ):
            whe._follow()

        out = capsys.readouterr().out
        assert "Live" in out
        assert "← STUCK" in out

    def test_an_fstat_failure_does_not_stop_the_watcher( self, monkeypatch, tmp_path ):
        """
        `inode = None` on OSError. The rotation check then degrades to the size test rather
        than the watcher dying on a filesystem that will not answer.
        """
        log = tmp_path / "hook-events.jsonl"
        log.write_text( "" )
        monkeypatch.setattr( whe, "LOG_PATH", log )

        def _boom( _fd ):
            raise OSError( "no fstat here" )
        monkeypatch.setattr( whe, "os", SimpleNamespace( SEEK_END=os.SEEK_END, fstat=_boom ) )

        self._run( monkeypatch, stop_after=1 )

    def test_rotation_reopens_the_file_rather_than_tailing_a_deleted_inode( self, monkeypatch, tmp_path, capsys ):
        """
        THE ROTATION ARM. A rotated log leaves the watcher holding a file nobody writes to
        again — it would sit silent forever while looking perfectly healthy, which is the
        worst failure this tool has.
        """
        log = tmp_path / "hook-events.jsonl"
        log.write_text( "" )
        monkeypatch.setattr( whe, "LOG_PATH", log )

        clock = _Clock( stop_after=4 )
        original_sleep = clock.sleep
        def _sleep_and_rotate( seconds ):
            if clock.calls == 0:
                log.unlink()                                  # rotate: new inode, same path
                log.write_text( json.dumps( { "phase": "heartbeat_oracle",
                                              "outcome": OUTCOME_POKE,
                                              "persona": "AfterRotate" } ) + "\n" )
            original_sleep( seconds )
        monkeypatch.setattr( whe, "time", SimpleNamespace( sleep=_sleep_and_rotate ) )
        monkeypatch.setattr( whe, "_ARGS", _args( replay=True ) )   # read the reopened file from its start

        with pytest.raises( _Clock.Stop ):
            whe._follow()

        assert "AfterRotate" in capsys.readouterr().out

    def test_truncation_in_place_also_reopens( self, monkeypatch, tmp_path, capsys ):
        """
        `st.st_size < f.tell()` — truncation keeps the inode, so the size test is the only
        thing that catches it. Without this arm the watcher would wait at an offset past EOF.
        """
        log = tmp_path / "hook-events.jsonl"
        log.write_text( json.dumps( { "phase": "heartbeat_oracle", "outcome": OUTCOME_POKE,
                                      "persona": "Before" } ) + "\n" )
        monkeypatch.setattr( whe, "LOG_PATH", log )
        monkeypatch.setattr( whe, "_ARGS", _args( replay=True ) )

        clock = _Clock( stop_after=4 )
        original_sleep = clock.sleep
        def _sleep_and_truncate( seconds ):
            if clock.calls == 0:
                with open( log, "w" ) as f:                   # truncate in place, same inode
                    f.write( json.dumps( { "phase": "heartbeat_oracle",
                                           "outcome": OUTCOME_POKE,
                                           "persona": "After" } ) + "\n" )
            original_sleep( seconds )
        monkeypatch.setattr( whe, "time", SimpleNamespace( sleep=_sleep_and_truncate ) )

        with pytest.raises( _Clock.Stop ):
            whe._follow()

        assert "After" in capsys.readouterr().out

    def test_a_stat_failure_breaks_out_to_reopen_rather_than_raising( self, monkeypatch, tmp_path ):
        """
        The log vanishing under the watcher — `LOG_PATH.stat()` raises, and the loop must
        break to the outer wait-for-file rather than propagate.
        """
        log = tmp_path / "hook-events.jsonl"
        log.write_text( "" )
        monkeypatch.setattr( whe, "LOG_PATH", log )

        clock = _Clock( stop_after=2 )
        original_sleep = clock.sleep
        def _sleep_and_delete( seconds ):
            if clock.calls == 0:
                log.unlink()
            original_sleep( seconds )
        monkeypatch.setattr( whe, "time", SimpleNamespace( sleep=_sleep_and_delete ) )

        with pytest.raises( _Clock.Stop ):
            whe._follow()


# ── main ──────────────────────────────────────────────────────────────────────

class TestMain:

    @pytest.fixture( autouse=True )
    def _restore_module_globals( self, monkeypatch ):
        """`main()` writes both `_ARGS` and `LOG_PATH` as globals; put them back after."""
        monkeypatch.setattr( whe, "LOG_PATH", whe.LOG_PATH )
        monkeypatch.setattr( whe, "_ARGS", whe._ARGS )

    def _argv( self, monkeypatch, *flags ):
        monkeypatch.setattr( sys, "argv", [ "watch-hook-events.py", *flags ] )

    def test_the_default_run_follows_rather_than_printing_once( self, monkeypatch ):
        called = { "follow": 0, "once": 0 }
        monkeypatch.setattr( whe, "_follow",         lambda: called.__setitem__( "follow", 1 ) )
        monkeypatch.setattr( whe, "_print_existing", lambda: called.__setitem__( "once", 1 ) )
        self._argv( monkeypatch )

        whe.main()

        assert called == { "follow": 1, "once": 0 }

    def test_once_prints_the_current_contents_and_does_not_follow( self, monkeypatch ):
        """`--once` is the scriptable form — following would hang a caller forever."""
        called = { "follow": 0, "once": 0 }
        monkeypatch.setattr( whe, "_follow",         lambda: called.__setitem__( "follow", 1 ) )
        monkeypatch.setattr( whe, "_print_existing", lambda: called.__setitem__( "once", 1 ) )
        self._argv( monkeypatch, "--once" )

        whe.main()

        assert called == { "follow": 0, "once": 1 }

    def test_every_flag_reaches_the_parsed_namespace( self, monkeypatch ):
        monkeypatch.setattr( whe, "_follow", lambda: None )
        self._argv( monkeypatch, "--all", "--replay", "--no-color" )

        whe.main()

        assert whe._ARGS.all      is True
        assert whe._ARGS.replay   is True
        assert whe._ARGS.no_color is True
        assert whe._ARGS.once     is False

    def test_path_overrides_the_log_location( self, monkeypatch, tmp_path ):
        """The override is what makes this script testable at all — and it must be a Path."""
        monkeypatch.setattr( whe, "_print_existing", lambda: None )
        target = tmp_path / "elsewhere.jsonl"
        self._argv( monkeypatch, "--once", "--path", str( target ) )

        whe.main()

        assert whe.LOG_PATH == target
        assert isinstance( whe.LOG_PATH, Path ), "a str here would break every LOG_PATH.exists() call"

    def test_without_path_the_default_log_location_is_left_alone( self, monkeypatch ):
        """The false half of `if _ARGS.path` — the default must survive a plain run."""
        monkeypatch.setattr( whe, "_print_existing", lambda: None )
        before = whe.LOG_PATH
        self._argv( monkeypatch, "--once" )

        whe.main()

        assert whe.LOG_PATH == before

    def test_ctrl_c_stops_cleanly_instead_of_dumping_a_traceback( self, monkeypatch, capsys ):
        """
        Ctrl-C is the DOCUMENTED way to stop this tool, so a traceback on the normal exit
        path would train an operator to ignore tracebacks.
        """
        def _interrupt():
            raise KeyboardInterrupt
        monkeypatch.setattr( whe, "_follow", _interrupt )
        self._argv( monkeypatch )

        # Caught explicitly rather than left to escape: an uncaught KeyboardInterrupt aborts
        # the pytest SESSION with rc=2, and this crew counts only rc==1 as a mutation kill.
        # Letting it escape would make a real defect report as "not evidence" (mutation M18).
        try:
            whe.main()
        except KeyboardInterrupt:
            pytest.fail( "main() let Ctrl-C escape; the documented way to stop this tool "
                         "would dump a traceback" )

        assert "stopped" in capsys.readouterr().out

    def test_ctrl_c_during_once_is_caught_on_that_path_too( self, monkeypatch, capsys ):
        """Both arms of the try sit under one except — pinned so a refactor cannot split them."""
        def _interrupt():
            raise KeyboardInterrupt
        monkeypatch.setattr( whe, "_print_existing", _interrupt )
        self._argv( monkeypatch, "--once" )

        whe.main()

        assert "stopped" in capsys.readouterr().out
