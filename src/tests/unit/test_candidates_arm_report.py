"""
Unit tests for the results page of the offline comparison.

The page must carry the run and the five shas, and a missing one must stop the write.
"""
import hashlib

import pytest

from cosa.repo.symindex.candidates import arm_report as ar
from cosa.repo.symindex.candidates.errors import CandidateError

META  = { "run_id": "run-1", "code_sha": "c1", "index_sha": "i1", "manifest_hash": "m1", "needs_sha": "n1", "cache_sha": "k1" }
T1    = { "C0": { 32: { "mean": 0.5, "mean_size": 31.6 }, 128: { "mean": 0.75, "mean_size": 120.0 } },
          "B1": { 32: { "mean": None, "mean_size": None }, 128: { "mean": 1.0, "mean_size": 98.0 } } }
T3    = { "B1": { "py": { "members": 4, "unranked": 1, "median": 4, "median_all": 32.0, "within": { 10: 2, 50: 2, 128: 3 } } } }
T2    = { "B1": { "needs": 2, "flip_rate": 0.5, "agreement": None, "uncached": 3 } }
REDACT = { "count": 1, "of": 30, "ids": [ "f03" ], "control": True }


class TestRender:
    """The page content."""

    def page( self, **over ):
        args = dict( meta=META, t1=T1, t3=T3, t2=T2, vectors_choice="B1", fusion=( 60, 512, 5 ), redactable=REDACT )
        args.update( over )
        return ar.render_report( **args )

    def test_header_carries_run_and_shas( self ):
        text = self.page()
        for value in META.values(): assert f"| {value} |" in text

    def test_names_the_winner_and_constants( self ):
        text = self.page( vectors_choice="B2" )
        assert "**Winning vector arm:** B2" in text
        assert "k 60, depth 512, head 5" in text

    def test_t1_rows( self ):
        text = self.page()
        assert "| C0 | 50.0% (32 ids) | 75.0% (120 ids) |" in text
        assert "| B1 | - (- ids) | 100.0% (98 ids) |" in text

    def test_t3_and_t2_rows( self ):
        text = self.page()
        assert "| B1 | py | 4 | 1 | 4 | 32.0 | 2 | 2 | 3 |" in text
        assert "| B1 | 2 | 50.0% | - | 3 |" in text

    def test_states_it_is_in_sample( self ):
        assert "not a flip rate" in self.page()

    def test_redaction_control_both_ways( self ):
        assert "the redactor found a planted token" in self.page()
        assert "did NOT find" in self.page( redactable=dict( REDACT, control=False ) )
        assert "1 of 30 needs hold a redactable token" in self.page()

    def test_a_missing_sha_is_refused( self ):
        with pytest.raises( CandidateError ) as caught:
            self.page( meta=dict( META, index_sha="", cache_sha=None ) )
        assert caught.value.code == ar.REPORT_META_MISSING
        assert caught.value.detail == "index_sha, cache_sha"


class TestCountRedactable:
    """How many needs hold a token."""

    def test_counts_and_names( self ):
        needs  = { "f01": "plain words", "f02": "mail me at a@b.co", "f03": "see /home/x/y" }
        found  = ar.count_redactable( needs, lambda t: t.count( "@" ) + t.count( "/home" ), "x@y" )
        assert found == { "count": 2, "ids": [ "f02", "f03" ], "of": 3, "control": True }

    def test_a_redactor_that_misses_the_planted_token_fails_the_control( self ):
        found = ar.count_redactable( { "f01": "a@b.co" }, lambda t: t.count( "@" ), "nothing special" )
        assert found[ "count" ] == 1
        assert found[ "control" ] is False

    def test_none_found( self ):
        assert ar.count_redactable( { "f01": "x" }, lambda t: 0, "x" ) == { "count": 0, "ids": [], "of": 1, "control": False }


class TestWrite:
    """The page lands on disk and its hash is returned."""

    def test_writes_and_hashes( self, tmp_path ):
        target = tmp_path / "deep" / "results.md"
        digest = ar.write_report( target, "line one\nline two\n" )
        assert target.read_text( encoding="utf-8" ) == "line one\nline two\n"
        assert digest == hashlib.sha256( b"line one\nline two\n" ).hexdigest()
