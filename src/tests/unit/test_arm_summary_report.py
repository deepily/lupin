"""
The per-arm report command, driven over the six-card, four-arm cohort of test_arm_summary.

The expected figures are literals taken from that cohort.
Two of its arms hold a forecast row for every answered card, and the other two miss three each, so the no-row total is six.
No forecast is orphaned.
"""
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

import pytest

import cosa.research.preference_replay.arm_summary_report as asr
from cosa.research.preference_replay.arm_summary import per_arm_summary, render_summary
from tests.unit.test_arm_summary import T0, session  # noqa: F401  (session is a fixture)

STAMP = datetime( 2026, 11, 19, 22, 0, 0, tzinfo=timezone.utc )


def _factory( session ):
    """Wrap one open session as the context-managed factory the command takes."""
    @contextmanager
    def factory():
        yield session
    return factory


def _run( session, tmp_path, *extra ):
    """Run the command once and return the report text."""
    out = tmp_path / "report.md"
    assert asr.main( [ "--out", str( out ), *extra ], session_factory=_factory( session ), code_sha="abc1234def", clock=lambda: STAMP ) == 0
    return out.read_text( encoding="utf-8" )


def test_the_report_holds_the_summary_table_and_the_two_totals( session, tmp_path ):
    text = _run( session, tmp_path )
    assert render_summary( per_arm_summary( session ) ) in text
    assert text.count( "\n| A1 | 6 | 0 | 0 | 5 | 3 | 1 | 1 | 0 | 0.600 |" ) == 1
    assert "- orphaned forecasts, all arms: 0\n" in text
    assert text.endswith( "- answered cards with no forecast row, all arms: 6\n" )


def test_the_header_names_the_sha_the_window_the_time_and_the_command( session, tmp_path ):
    text = _run( session, tmp_path )
    assert text.startswith( "# Per-arm summary\n\n- code sha of this report: abc1234def\n- window starts: none\n- generated: 2026-11-19T22:00:00+00:00\n- command: `python -m" )
    assert f"arm_summary_report --out {tmp_path}/report.md`" in text


def test_since_narrows_the_window_and_is_named_in_the_header( session, tmp_path ):
    later = ( T0 + timedelta( seconds=1 ) ).isoformat()
    text  = _run( session, tmp_path, "--since", later )
    assert f"- window starts: {later}" in text
    assert render_summary( per_arm_summary( session, T0 + timedelta( seconds=1 ) ) ) in text
    assert "| A1 | 0 |" in text and "answered cards with no forecast row, all arms: 0\n" in text


def test_an_unreadable_since_is_refused_before_anything_is_written( session, tmp_path ):
    with pytest.raises( ValueError, match="not an ISO-8601 time" ):
        asr.main( [ "--out", str( tmp_path / "r.md" ), "--since", "yesterday" ], session_factory=_factory( session ), code_sha="x", clock=lambda: STAMP )
    assert not ( tmp_path / "r.md" ).exists()


def test_an_empty_database_reads_zero_totals():
    text = asr.render_report( [], { "code sha of this report": "x" } )
    assert text.endswith( "- orphaned forecasts, all arms: 0\n- answered cards with no forecast row, all arms: 0\n" )


def test_the_sha_clock_and_database_default_to_the_real_ones( session, tmp_path, monkeypatch ):
    monkeypatch.setattr( asr, "get_db", _factory( session ) )
    monkeypatch.setattr( asr, "resolve_commit", lambda root, ref: "feedface00" )
    out = tmp_path / "r.md"
    assert asr.main( [ "--out", str( out ) ] ) == 0
    text = out.read_text( encoding="utf-8" )
    assert "- code sha of this report: feedface00\n" in text and "- generated: 20" in text
    monkeypatch.setattr( asr.sys, "argv", [ "prog", "--out", str( out ) ] )
    assert asr.main() == 0 and f"arm_summary_report --out {out}`" in out.read_text( encoding="utf-8" )
