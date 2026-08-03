"""
Unit tests for git date-bound normalization (row d0b3cd84).

The defect: git resolves a BARE ISO date to a time-of-day that is not midnight,
so `--since=<today>` selected nothing and `--today` — the DEFAULT mode — reported
zero on a 35-commit day, as a successful empty result rather than an error.

These tests pin three things:
  1. the pure normalization itself,
  2. that BOTH call sites (the numstat walk and the independent coverage guard)
     normalize IDENTICALLY — the guard mirrors the walk's flags on purpose, so if
     they drift it audits a different window than the one it is auditing,
  3. that `--until` is left alone, because a bare upper-bound date already means
     end-of-day and "fixing" the asymmetry would lop a day off every range.

Created: 2026-08-02 (Cheech 🌿)
"""
import pytest

from cosa.repo.git_loc_delta.coverage_guard import _rev_list_shas
from cosa.repo.git_loc_delta.date_bounds import normalize_since, normalize_until
from cosa.repo.git_loc_delta.git_log_parser import GitLogParser


class TestNormalizeSince:

    def test_bare_iso_date_is_pinned_to_day_start( self ):
        assert normalize_since( "2026-08-02" ) == "2026-08-02 00:00:00"

    def test_none_passes_through( self ):
        assert normalize_since( None ) is None

    @pytest.mark.parametrize( "value", [
        "2026-08-02 00:00",
        "2026-08-02 13:45:01",
        "2026-08-02T13:45:01",
    ] )
    def test_a_value_that_already_has_a_time_is_untouched( self, value ):
        assert normalize_since( value ) == value

    @pytest.mark.parametrize( "value", [ "1 day ago", "midnight", "yesterday", "2 weeks ago" ] )
    def test_relative_expressions_are_untouched( self, value ):
        # These are already unambiguous to git; rewriting them would break them.
        assert normalize_since( value ) == value

    @pytest.mark.parametrize( "value", [ "2026-8-2", "26-08-02", "2026/08/02", "2026-08-02 ", "" ] )
    def test_near_misses_are_not_treated_as_bare_iso_dates( self, value ):
        # The predicate must match the thing, not a description of the thing:
        # only an exact YYYY-MM-DD gets a time appended.
        assert normalize_since( value ) == value

    def test_normalization_is_idempotent( self ):
        once  = normalize_since( "2026-08-02" )
        twice = normalize_since( once )
        assert once == twice


class TestNormalizeUntil:

    @pytest.mark.parametrize( "value", [ "2026-08-02", "2026-08-02 23:59:59", None, "1 day ago" ] )
    def test_upper_bound_is_always_returned_unchanged( self, value ):
        # A bare upper-bound date already lands at END of day, which is the
        # inclusive bound the CLI documents. Appending a time here would make
        # --until exclusive and silently drop a day.
        assert normalize_until( value ) == value


class TestBothCallSitesAgree:
    """
    The guard is only meaningful if it asks the SAME question as the walk.

    This detects CONTACT — it reads the flags each side actually builds — rather
    than asserting that each one calls a helper. A future edit that inlines or
    re-implements normalization on one side fails here.
    """

    @staticmethod
    def _flag( argv, name ):
        return next( ( a for a in argv if a.startswith( f"--{name}=" ) ), None )

    def _guard_argv( self, monkeypatch, since, until ):
        captured = {}

        class _Result:
            returncode = 0
            stdout     = ""
            stderr     = ""

        def _fake_run( cmd, **kwargs ):
            captured[ "cmd" ] = cmd
            return _Result()

        monkeypatch.setattr( "cosa.repo.git_loc_delta.coverage_guard.subprocess.run", _fake_run )
        _rev_list_shas(
            repo_path      = ".",
            since          = since,
            until          = until,
            rev_range      = None,
            all_branches   = False,
            include_merges = False,
            timeout        = 10,
        )
        return captured[ "cmd" ]

    @pytest.mark.parametrize( "since", [ "2026-08-02", "2026-08-02 09:30:00", "1 day ago" ] )
    def test_since_flag_is_identical_on_both_sides( self, monkeypatch, since ):
        walk_argv  = GitLogParser( repo_path=".", since=since )._build_command()
        guard_argv = self._guard_argv( monkeypatch, since, None )
        assert self._flag( walk_argv, "since" ) == self._flag( guard_argv, "since" )

    def test_until_flag_is_identical_on_both_sides( self, monkeypatch ):
        walk_argv  = GitLogParser( repo_path=".", since="2026-08-01", until="2026-08-02" )._build_command()
        guard_argv = self._guard_argv( monkeypatch, "2026-08-01", "2026-08-02" )
        assert self._flag( walk_argv, "until" ) == self._flag( guard_argv, "until" )

    def test_the_walk_actually_pins_a_bare_today_date( self, monkeypatch ):
        # The regression itself: without this the flag reads --since=2026-08-02
        # and git returns nothing for that day.
        walk_argv = GitLogParser( repo_path=".", since="2026-08-02" )._build_command()
        assert self._flag( walk_argv, "since" ) == "--since=2026-08-02 00:00:00"

    def test_the_guard_actually_pins_a_bare_today_date( self, monkeypatch ):
        guard_argv = self._guard_argv( monkeypatch, "2026-08-02", None )
        assert self._flag( guard_argv, "since" ) == "--since=2026-08-02 00:00:00"
