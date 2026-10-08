"""
The acks smoke test builds "today" in the repository method's zone, not the process zone.

The method hides a day by its date in America/New_York. A test that builds the date in
the process zone disagrees from 20:00 to midnight Eastern, when UTC is already tomorrow.
"""

import datetime as dt
import inspect
import time

import pytest

from cosa.rest.db.repositories.notification_repository import NotificationRepository
from tests.smoke.test_acks_are_not_conversations import _today_in_repo_zone


# 02:52 UTC on the 8th is 22:52 on the 7th in New York.
_LATE_EVENING_UTC = dt.datetime( 2026, 10, 8, 2, 52, tzinfo=dt.timezone.utc )


@pytest.fixture( params=[ "UTC", "America/New_York", "Asia/Tokyo" ] )
def process_zone( request, monkeypatch ):
    monkeypatch.setenv( "TZ", request.param )
    time.tzset()
    yield request.param
    monkeypatch.undo()
    time.tzset()


def test_today_is_the_repo_zone_date_whatever_the_process_zone( process_zone ):
    assert _today_in_repo_zone( _LATE_EVENING_UTC ) == "2026-10-07"


def test_the_helper_reads_the_zone_from_the_method_signature():
    default = inspect.signature( NotificationRepository.soft_delete_by_date ).parameters[ "timezone_name" ].default
    assert default == "America/New_York"


def test_the_process_zone_date_would_have_been_wrong_under_utc( monkeypatch ):
    monkeypatch.setenv( "TZ", "UTC" )
    time.tzset()
    try:
        assert _LATE_EVENING_UTC.astimezone().strftime( "%Y-%m-%d" ) == "2026-10-08"
    finally:
        monkeypatch.undo()
        time.tzset()
