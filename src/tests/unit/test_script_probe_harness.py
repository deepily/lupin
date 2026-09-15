"""
Unit tests for `tests.helpers.script_probe_harness`.

🔴 A HARNESS THAT CANNOT BE PROVEN TO DISCRIMINATE IS WORSE THAN NO HARNESS. Measured
twice on this branch on 2026-08-30: an instrument reported a mutation KILLED that had
never run, and a converted tree reported isolation it did not have. Both looked like
results. So every claim this harness makes is posed HERE in both directions — the
thing it is supposed to catch, and the thing it must not falsely accuse.

The synthetic script under test is written into a tmp dir rather than pointed at a real
operator script, because the only honest proof needs a file whose behaviour the test
controls. That is what the `scripts_dir` override exists for.
"""

import sys
import textwrap

import pytest

from tests.helpers.script_probe_harness import (
    HttpDouble, Response, ScriptHarness, SleepRecorder, UnprogrammedRequest,
    project_root )


# ═══════════════════════════════════════════════════════════════════════════════
# The synthetic operator script — the same three obstacles as the real family
# ═══════════════════════════════════════════════════════════════════════════════

_SCRIPT = textwrap.dedent( '''
    import os
    import time
    import requests

    # obstacle 1: configuration read at IMPORT time
    EMAIL    = os.environ.get( "PROBE_TEST_EMAIL" )
    PASSWORD = os.environ.get( "PROBE_TEST_PASSWORD" )
    BASE_URL = os.environ.get( "PROBE_TEST_URL", "http://localhost:7999" )

    def submit():
        # obstacle 2: module-level requests use
        return requests.post( f"{BASE_URL}/api/v2/submit",
                              json={ "command": "go" }, timeout=30 ).json()

    def poll():
        # obstacle 3: real pacing
        seen = []
        for _ in range( 3 ):
            seen.append( requests.get( f"{BASE_URL}/api/job-history", timeout=30 ).json() )
            time.sleep( 60 )
        return seen

    def no_timeout():
        return requests.get( f"{BASE_URL}/api/health" )
''' )


@pytest.fixture
def scripts_dir( tmp_path ):
    d = tmp_path / "scripts"
    d.mkdir()
    ( d / "synthetic_probe.py" ).write_text( _SCRIPT )
    yield str( d )
    sys.modules.pop( "synthetic_probe", None )


@pytest.fixture
def harness( monkeypatch, scripts_dir ):
    return ScriptHarness( monkeypatch, scripts_dir=scripts_dir )


# ═══════════════════════════════════════════════════════════════════════════════
# Obstacle 1 — configuration read at import time
# ═══════════════════════════════════════════════════════════════════════════════

class TestTheEnvironmentIsAppliedBeforeImport:

    def test_a_staged_value_reaches_a_module_level_constant( self, harness ):
        """
        🔴 THE WHOLE REASON THIS HARNESS EXISTS. The constant is assigned while the
        module body runs, so a value set afterwards is set too late. The staged value
        is deliberately distinctive, so "read from the environment" and "left at the
        default" are different strings.
        """
        harness.env( PROBE_TEST_EMAIL="STAGED-EMAIL-VALUE" )
        mod = harness.import_script( "synthetic_probe" )
        assert mod.EMAIL == "STAGED-EMAIL-VALUE"

    def test_an_unstaged_name_comes_out_as_none_rather_than_stale( self, harness ):
        harness.env( PROBE_TEST_EMAIL="X" )
        mod = harness.import_script( "synthetic_probe" )
        assert mod.PASSWORD is None

    def test_unset_removes_a_name_that_the_real_environment_holds( self, harness, monkeypatch ):
        """
        The missing-credential path. Without an explicit unset, a value present in the
        developer's own shell would leak in and the refusal branch would never run —
        a test that passes on one machine and not another.
        """
        monkeypatch.setenv( "PROBE_TEST_EMAIL", "LEAKED-FROM-THE-REAL-SHELL" )
        harness.unset( "PROBE_TEST_EMAIL" )
        mod = harness.import_script( "synthetic_probe" )
        assert mod.EMAIL is None

    def test_a_default_is_used_when_nothing_is_staged( self, harness ):
        mod = harness.import_script( "synthetic_probe" )
        assert mod.BASE_URL == "http://localhost:7999"

    def test_each_import_is_FRESH_so_one_test_cannot_answer_anothers_question( self, harness, monkeypatch, scripts_dir ):
        """
        🔴 A CACHED MODULE CARRIES THE PREVIOUS TEST'S CONSTANTS. Two imports with
        different staged values must give different constants; if `sys.modules` were
        consulted the second would silently return the first, and every later test
        would be measuring the first one's environment.
        """
        harness.env( PROBE_TEST_EMAIL="FIRST-VALUE" )
        first = harness.import_script( "synthetic_probe" )
        assert first.EMAIL == "FIRST-VALUE"

        second_harness = ScriptHarness( monkeypatch, scripts_dir=scripts_dir )
        second_harness.env( PROBE_TEST_EMAIL="SECOND-VALUE" )
        second = second_harness.import_script( "synthetic_probe" )
        assert second.EMAIL == "SECOND-VALUE"
        assert first is not second


# ═══════════════════════════════════════════════════════════════════════════════
# Obstacle 2 — the HTTP double
# ═══════════════════════════════════════════════════════════════════════════════

class TestTheHttpDouble:

    def test_a_programmed_route_answers_and_is_recorded( self, harness ):
        harness.http.post( "/api/v2/submit", json={ "id": "JOB-ID-VALUE" } )
        mod = harness.import_script( "synthetic_probe" )
        assert mod.submit() == { "id": "JOB-ID-VALUE" }
        assert harness.http.call_to( "POST", "/api/v2/submit" ).kwargs[ "json" ] == { "command": "go" }

    def test_an_UNPROGRAMMED_url_raises_rather_than_answering_emptily( self, harness ):
        """
        🔴 THE STRICTNESS IS THE POINT. A double answering every URL with an empty 200
        would let a script post to a RETIRED door and still look healthy — and catching
        exactly that is why several of these scripts exist. The error names what was
        called and what was available, so the failure is actionable.
        """
        mod = harness.import_script( "synthetic_probe" )
        with pytest.raises( UnprogrammedRequest ) as exc:
            mod.submit()
        assert "/api/v2/submit" in str( exc.value )
        assert "never programmed" in str( exc.value )

    def test_a_call_with_no_timeout_is_refused( self, harness ):
        """
        An operator script without a timeout hangs forever against a wedged server,
        and no assertion about the RESPONSE can see that. So it is refused at the seam.
        """
        harness.http.get( "/api/health", json={} )
        mod = harness.import_script( "synthetic_probe" )
        with pytest.raises( UnprogrammedRequest ) as exc:
            mod.no_timeout()
        assert "timeout" in str( exc.value )

    def test_the_timeout_requirement_can_be_waived_deliberately( self, harness ):
        """The other side — the guard must be escapable on purpose, not only by accident."""
        harness.http.timeout_required = False
        harness.http.get( "/api/health", json={ "ok": True } )
        mod = harness.import_script( "synthetic_probe" )
        assert mod.no_timeout().json() == { "ok": True }

    def test_a_sequence_answers_a_polled_endpoint_in_order( self, harness ):
        """
        🔴 THE THREE RESPONSES ARE DISTINCT ON PURPOSE. Identical ones could not tell
        "polled three times and read each answer" from "polled once and reused it",
        which is the actual failure a poll loop has.
        """
        harness.http.get( "/api/job-history", responses=[
            Response( 200, { "state": "FIRST" } ),
            Response( 200, { "state": "SECOND" } ),
            Response( 200, { "state": "THIRD" } ) ] )
        mod = harness.import_script( "synthetic_probe" )
        assert [ r[ "state" ] for r in mod.poll() ] == [ "FIRST", "SECOND", "THIRD" ]

    def test_a_route_matches_by_suffix_so_a_test_need_not_restate_the_host( self, harness ):
        harness.http.post( "/api/v2/submit", json={ "ok": True } )
        mod = harness.import_script( "synthetic_probe" )
        assert mod.submit() == { "ok": True }
        assert harness.http.urls == [ ( "POST", "http://localhost:7999/api/v2/submit" ) ]

    def test_the_LONGEST_matching_suffix_wins_so_two_doors_stay_distinguishable( self, harness ):
        """
        A short suffix would swallow a longer one and quietly answer for the wrong
        endpoint — the same class of defect as a route ordering bug. Both are
        registered and the specific one must win.
        """
        harness.http.post( "/submit", json={ "which": "SHORT-ROUTE" } )
        harness.http.post( "/api/v2/submit", json={ "which": "LONG-ROUTE" } )
        mod = harness.import_script( "synthetic_probe" )
        assert mod.submit() == { "which": "LONG-ROUTE" }

    def test_a_programmed_failure_raises_the_scripts_own_error_path( self, harness ):
        harness.http.fail( "POST", "/api/v2/submit", ConnectionError( "connection reset" ) )
        mod = harness.import_script( "synthetic_probe" )
        with pytest.raises( ConnectionError ):
            mod.submit()

    def test_call_to_refuses_when_an_endpoint_was_hit_more_than_once( self, harness ):
        """
        "The first call to X" hides a second one. `call_to` fails instead, so a script
        that retries silently cannot be mistaken for one that asked once.
        """
        harness.http.get( "/api/job-history", json={ "state": "S" } )
        mod = harness.import_script( "synthetic_probe" )
        mod.poll()
        with pytest.raises( AssertionError ) as exc:
            harness.http.call_to( "GET", "/api/job-history" )
        assert "saw 3" in str( exc.value )

    def test_assert_never_called_fails_when_the_endpoint_WAS_reached( self, harness ):
        """A negative assertion that cannot fail is not an assertion."""
        harness.http.post( "/api/v2/submit", json={} )
        mod = harness.import_script( "synthetic_probe" )
        mod.submit()
        with pytest.raises( AssertionError ):
            harness.http.assert_never_called( "POST", "/api/v2/submit" )

    def test_assert_never_called_passes_when_it_genuinely_was_not( self, harness ):
        harness.import_script( "synthetic_probe" )
        harness.http.assert_never_called( "POST", "/api/v2/submit" )


class TestTheResponseDouble:

    def test_json_returns_the_body( self ):
        assert Response( 200, { "k": "v" } ).json() == { "k": "v" }

    def test_json_on_a_bodyless_response_raises_like_the_real_thing( self ):
        """
        A real Response raises ValueError on a non-JSON body. Returning None instead
        would bypass a script's own error handling and test a path that cannot happen.
        """
        with pytest.raises( ValueError ):
            Response( 200, None ).json()

    def test_ok_follows_the_status_code( self ):
        assert Response( 204 ).ok is True
        assert Response( 404 ).ok is False

    def test_raise_for_status_is_silent_on_success_and_raises_on_error( self ):
        assert Response( 200 ).raise_for_status() is None
        with pytest.raises( RuntimeError ):
            Response( 500 ).raise_for_status()

    def test_the_boundary_status_is_not_an_error( self ):
        """399/400 is the boundary requests itself uses; off-by-one here is invisible."""
        assert Response( 399 ).ok is True
        assert Response( 400 ).ok is False


# ═══════════════════════════════════════════════════════════════════════════════
# Obstacle 3 — the clock
# ═══════════════════════════════════════════════════════════════════════════════

class TestTheSleepRecorder:

    def test_the_pacing_is_RECORDED_rather_than_silently_skipped( self, harness ):
        """
        🔴 A STUB THAT ONLY MADE TESTS FAST WOULD HIDE A REAL DEFECT. Deleting a
        sleep( 60 ) from a rate-limited probe is a genuine bug; recording it means a
        test can assert the pacing was REQUESTED even though none of it elapsed.
        """
        harness.http.get( "/api/job-history", json={ "state": "S" } )
        mod = harness.import_script( "synthetic_probe" )
        mod.poll()
        assert harness.sleeps.count     == 3
        assert harness.sleeps.durations == [ 60, 60, 60 ]
        assert harness.sleeps.total     == 180

    def test_no_time_actually_elapses( self, harness ):
        """The claim that makes the suite runnable at all: 180 seconds must not pass."""
        import time as real_time
        harness.http.get( "/api/job-history", json={ "state": "S" } )
        mod = harness.import_script( "synthetic_probe" )
        started = real_time.monotonic()
        mod.poll()
        assert real_time.monotonic() - started < 1.0

    def test_a_fresh_recorder_starts_empty( self ):
        r = SleepRecorder()
        assert r.count == 0 and r.total == 0 and r.durations == []


# ═══════════════════════════════════════════════════════════════════════════════
# The root resolver — the trap it inherits
# ═══════════════════════════════════════════════════════════════════════════════

class TestTheRootResolver:

    def test_the_env_var_wins_when_it_is_set( self, monkeypatch ):
        monkeypatch.setenv( "LUPIN_ROOT", "/some/explicit/root" )
        assert project_root() == "/some/explicit/root"

    def test_it_falls_back_to_this_files_own_tree_when_unset( self, monkeypatch ):
        """
        🔴 THE FALLBACK MUST BE ABSOLUTE, NOT RELATIVE. `Path( "" )`-style relative
        answers resolve correctly from the repo root and wrongly from anywhere else,
        so a test run from a subdirectory would pass for the wrong reason. Same defect
        measured on `watch-hook-events.py` on 2026-08-30.
        """
        import os
        import tests.helpers.script_probe_harness as mod
        monkeypatch.delenv( "LUPIN_ROOT", raising=False )
        root = project_root()
        assert os.path.isabs( root )
        assert root == os.path.abspath(
            os.path.join( os.path.dirname( mod.__file__ ), "..", "..", ".." ) )
