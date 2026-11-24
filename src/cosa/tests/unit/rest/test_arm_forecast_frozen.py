"""
A forecast row is frozen once written: update_arm_forecast refuses any change to it.

Runs over a real in-memory SQLite copy of prediction_arm_forecast. Each test names what it would catch:
  - an update that changes a stored forecast                  -> the unchanged-row tests
  - a refusal that fires for a row that does not exist        -> the missing-row test
  - a refusal that depends on which column is changed         -> the parametrized test
"""
import uuid

import pytest

from cosa.research.preference_replay.scratch_db import scratch_session
from cosa.rest.db.repositories.arm_forecast_repository import ForecastAlreadyFrozen, update_arm_forecast
from cosa.rest.postgres_models import PredictionArmForecast

_NID = uuid.uuid4()


@pytest.fixture
def session():
    with scratch_session() as open_session:
        open_session.add( PredictionArmForecast( notification_id=_NID, arm="A1", predictor_version="v1", forecast={ "value": "yes", "confidence": 0.7 }, displayed=True ) )
        open_session.commit()
        yield open_session


@pytest.mark.parametrize( "changes", [
    { "forecast": { "value": "no" } },
    { "predictor_version": "v2" },
    { "abstention_reason": "later" },
    { "displayed": False },
    {},
] )
def test_any_update_to_a_stored_forecast_is_refused_and_the_row_is_unchanged( session, changes ):
    with pytest.raises( ForecastAlreadyFrozen ): update_arm_forecast( session, _NID, "A1", **changes )
    row = session.query( PredictionArmForecast ).one()
    assert ( row.forecast, row.predictor_version, row.abstention_reason, row.displayed ) == ( { "value": "yes", "confidence": 0.7 }, "v1", None, True )


def test_the_refusal_names_the_card_the_arm_and_the_columns_asked_for( session ):
    with pytest.raises( ForecastAlreadyFrozen ) as caught: update_arm_forecast( session, _NID, "A1", forecast=1, displayed=False )
    assert str( _NID ) in str( caught.value ) and "A1" in str( caught.value ) and "['displayed', 'forecast']" in str( caught.value )


def test_the_refusal_is_a_value_error_like_outcome_already_recorded():
    assert issubclass( ForecastAlreadyFrozen, ValueError )


def test_an_update_aimed_at_another_arm_or_another_card_finds_no_row_and_changes_nothing( session ):
    assert update_arm_forecast( session, _NID, "B1", forecast={ "value": "no" } ) is None
    assert update_arm_forecast( session, uuid.uuid4(), "A1", forecast={ "value": "no" } ) is None
    assert session.query( PredictionArmForecast ).one().forecast == { "value": "yes", "confidence": 0.7 }


def test_the_lookup_reads_the_row_under_a_lock():
    from sqlalchemy.dialects import postgresql
    from unittest.mock import MagicMock
    session = MagicMock()
    session.query.return_value.filter.return_value.with_for_update.return_value.first.return_value = None
    update_arm_forecast( session, _NID, "A1" )
    session.query.return_value.filter.return_value.with_for_update.assert_called_once_with()
