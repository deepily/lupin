#!/usr/bin/env python3
"""
report_lint: a planted bad table and an archive cohort in confirmation are refused.

Venue: :7999-eligible / local, pure.
"""
import os
import sys

# Bootstrap
_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

import pytest

from cosa.research.preference_replay import report_lint as rl


def good( **changed ):
    table = { "title": "accuracy by arm", "cohort": "archive", "stamp": "development", "unit": "cards", "denominator": { "count": 1926, "unit": "cards" },
              "paired_differences": [ { "name": "principles - history", "difference": 0.02, "interval": [ -0.01, 0.05 ] } ] }
    return { **table, **changed }


def test_a_complete_report_passes():
    assert rl.check_report( [ good(), good( cohort="window", stamp=None, paired_differences=[] ) ] ) is None


def test_the_planted_bad_table_is_refused_with_every_fault_named():
    bad = { "title": "bad", "cohort": "archive", "stamp": "final", "unit": "cards", "denominator": { "count": 10, "unit": "fields" },
            "paired_differences": [ { "name": "a - b", "difference": 0.1 } ] }
    with pytest.raises( rl.ReportRefused ) as caught: rl.check_report( [ good(), bad ] )
    assert str( caught.value ) == ( "table 'bad' is an archive table not stamped development; table 'bad' counts 'cards' over a denominator of 'fields'; "
                                    "table 'bad' has a paired difference 'a - b' with no interval around it" )


@pytest.mark.parametrize( "changed, fault", [
    ( { "title": " " },                                    "has no title" ),
    ( { "cohort": "other" },                               "has no cohort" ),
    ( { "stamp": None },                                   "not stamped development" ),
    ( { "unit": "" },                                      "has no unit" ),
    ( { "denominator": None },                             "has no denominator count" ),
    ( { "denominator": { "count": 0, "unit": "cards" } },  "has no denominator count" ),
    ( { "denominator": { "count": True, "unit": "cards" } }, "has no denominator count" ),
    ( { "denominator": { "count": 5 } },                   "denominator with no unit" ),
    ( { "paired_differences": None },                      "does not list its paired differences" ),
    ( { "paired_differences": [ { "name": "d", "interval": [ 0, 1 ] } ] },                              "with no number" ),
    ( { "paired_differences": [ { "name": "d", "difference": 0.5, "interval": [ 0 ] } ] },              "no interval around it" ),
    ( { "paired_differences": [ { "name": "d", "difference": 0.5, "interval": [ 0.6, 0.9 ] } ] },       "no interval around it" ),
    ( { "paired_differences": [ { "name": "d", "difference": 0.5, "interval": [ None, 0.9 ] } ] },      "no interval around it" ),
    ( { "paired_differences": [ { "name": "d", "difference": float( "nan" ), "interval": [ 0, 1 ] } ] }, "with no number" ),
] )
def test_each_fault_on_its_own_is_found( changed, fault ):
    found = rl.table_findings( good( **changed ) )
    assert len( found ) >= 1 and any( fault in f for f in found ), found


def test_a_table_with_no_unit_reports_only_that_and_not_a_mismatch():
    assert rl.table_findings( good( unit=None ) ) == [ "table 'accuracy by arm' has no unit" ]


def test_a_report_with_no_table_is_refused():
    with pytest.raises( rl.ReportRefused, match="no table" ): rl.check_report( [] )


def test_the_confirmatory_path_refuses_an_archive_cohort():
    assert rl.refuse_archive_cohort( "window" ) is None
    for cohort in ( "archive", "", None ):
        with pytest.raises( rl.ReportRefused, match="only the window cohort" ): rl.refuse_archive_cohort( cohort )
