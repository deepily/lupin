#!/usr/bin/env python3
"""
Tests for cosa.utils.gcp_project — the project-id resolver.

THESE RUN ALWAYS. Rachel, 2026-08-16: a drift check written as "assert the two sources agree
whenever both are present" is conditional, and its condition is FALSE BY DEFAULT — cloud-run.env is
git-ignored, so on CI the check finds one source, skips, and reports green. A guard whose condition
fails by default is not a guard; it is a test that has never run.

So the weight sits here instead, on hermetic temp files with an injected environ: override wins →
else the env file → else raise. No real config is read, nothing is skipped, and the suite fails on
a box with no credentials just as loudly as on Rick's.

Run: pytest src/tests/unit/test_gcp_project_resolution.py -q
"""

import pytest

from cosa.utils.gcp_project import (
    DEFAULT_LOCATION,
    PROJECT_ENV_KEY,
    LOCATION_ENV_KEY,
    parse_env_file,
    resolve_gcp_location,
    resolve_gcp_project_id,
)


@pytest.fixture
def env_file( tmp_path ):
    """A cloud-run.env shaped file, written per-test."""
    def _write( body ):
        p = tmp_path / "cloud-run.env"
        p.write_text( body, encoding="utf-8" )
        return p
    return _write


# ── precedence: this is the contract cloud-run-config.sh already has in shell ────────────────────

def test_environment_wins_over_the_file( env_file ):
    p = env_file( 'LUPIN_GCP_PROJECT_ID="from-file"\n' )
    assert resolve_gcp_project_id( environ={ PROJECT_ENV_KEY: "from-env" }, env_file=p ) == "from-env"


def test_file_is_used_when_the_environment_is_empty( env_file ):
    p = env_file( 'LUPIN_GCP_PROJECT_ID="from-file"\n' )
    assert resolve_gcp_project_id( environ={}, env_file=p ) == "from-file"


def test_an_empty_environment_value_does_not_beat_the_file( env_file ):
    """An exported-but-blank variable is not a configured value; it is the absence of one."""
    p = env_file( 'LUPIN_GCP_PROJECT_ID="from-file"\n' )
    assert resolve_gcp_project_id( environ={ PROJECT_ENV_KEY: "   " }, env_file=p ) == "from-file"


# ── the failure that matters: never default, never fall back to a key ────────────────────────────

def test_missing_everywhere_raises( tmp_path ):
    with pytest.raises( RuntimeError ) as e:
        resolve_gcp_project_id( environ={}, env_file=tmp_path / "absent.env" )
    msg = str( e.value )
    assert PROJECT_ENV_KEY in msg
    assert "absent.env" in msg, "the error must name the file it looked in, not just the variable"


def test_the_error_says_there_is_no_api_key_fallback( tmp_path ):
    """The whole point of the ruling. If this message ever softens, someone will add a fallback."""
    with pytest.raises( RuntimeError ) as e:
        resolve_gcp_project_id( environ={}, env_file=tmp_path / "absent.env" )
    assert "no API-key fallback" in str( e.value )


def test_an_empty_file_value_is_not_a_project( env_file ):
    p = env_file( 'LUPIN_GCP_PROJECT_ID=""\n' )
    with pytest.raises( RuntimeError ):
        resolve_gcp_project_id( environ={}, env_file=p )


def test_the_committed_template_placeholder_resolves_to_nothing( env_file ):
    """
    cloud-run.env.example ships `LUPIN_GCP_PROJECT_ID="${LUPIN_GCP_PROJECT_ID:-}"`. An unexpanded
    shell reference must read as EMPTY — if it ever parsed as the literal string, a box that copied
    the template without filling it in would sail past this guard and fail much later, at the API.
    """
    p = env_file( 'LUPIN_GCP_PROJECT_ID="${LUPIN_GCP_PROJECT_ID:-}"   # REQUIRED\n' )
    with pytest.raises( RuntimeError ):
        resolve_gcp_project_id( environ={}, env_file=p )


# ── parsing a shell file without executing it ────────────────────────────────────────────────────

@pytest.mark.parametrize( "line,want", [
    ( 'FOO="bar"',            "bar" ),
    ( "FOO='bar'",            "bar" ),
    ( "FOO=bar",              "bar" ),
    ( "export FOO=bar",       "bar" ),
    ( '  FOO="bar"  ',        "bar" ),
    ( 'FOO="bar"   # trailing comment', "bar" ),
] )
def test_env_line_shapes( env_file, line, want ):
    assert parse_env_file( env_file( line + "\n" ) ).get( "FOO" ) == want


def test_comments_and_blanks_are_ignored( env_file ):
    p = env_file( "# a comment\n\n#FOO=commented-out\nFOO=real\n" )
    assert parse_env_file( p ) == { "FOO": "real" }


def test_a_missing_file_parses_to_empty_not_an_error( tmp_path ):
    assert parse_env_file( tmp_path / "nope.env" ) == {}


# ── location: this one DOES default, and the default is load-bearing ─────────────────────────────

def test_location_defaults_to_global( tmp_path ):
    assert resolve_gcp_location( environ={}, env_file=tmp_path / "absent.env" ) == DEFAULT_LOCATION


def test_the_default_location_is_not_us_central1():
    """
    Measured 2026-08-16: us-central1 returns 404 NOT_FOUND for gemini-3.1-flash-lite, and
    vertex_env.py:90-92 already records rawPredict "genuinely 400s" there. Two APIs, two failure
    modes. If someone ever changes the default to us-central1, this fails and tells them why.
    """
    assert DEFAULT_LOCATION == "global"


def test_location_environment_wins( env_file ):
    p = env_file( 'LUPIN_GCP_LOCATION="from-file"\n' )
    assert resolve_gcp_location( environ={ LOCATION_ENV_KEY: "from-env" }, env_file=p ) == "from-env"


def test_location_comes_from_the_file_when_unset( env_file ):
    p = env_file( 'LUPIN_GCP_LOCATION="europe-west4"\n' )
    assert resolve_gcp_location( environ={}, env_file=p ) == "europe-west4"


if __name__ == "__main__":
    import sys
    sys.exit( pytest.main( [ __file__, "-q" ] ) )
