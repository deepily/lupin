"""
The two Jev call errors share one shape and stay two types.

JevConfigError (refused or misconfigured) and JevCallError (no usable answer) carry a status and an
attempt log. Callers catch them separately, so neither may be a subclass of the other.
"""
import pytest

from cosa.repo.doc_lint import jev_transport as jt


@pytest.mark.parametrize( "error_class", [ jt.JevConfigError, jt.JevCallError ] )
def test_each_error_defaults_to_no_status_and_an_empty_attempt_log( error_class ):
    error = error_class( "boom" )
    assert str( error ) == "boom" and error.status is None and error.attempt_log == []


@pytest.mark.parametrize( "error_class", [ jt.JevConfigError, jt.JevCallError ] )
def test_each_error_keeps_the_status_and_the_log_it_is_given( error_class ):
    log   = [ { "status": 503, "request_ids": {} } ]
    error = error_class( "boom", status=503, attempt_log=log )
    assert error.status == 503 and error.attempt_log is log


def test_two_errors_never_share_one_attempt_log_list():
    assert jt.JevCallError( "a" ).attempt_log is not jt.JevCallError( "b" ).attempt_log


def test_the_two_errors_are_siblings_not_parent_and_child():
    assert issubclass( jt.JevConfigError, jt._JevError ) and issubclass( jt.JevCallError, jt._JevError )
    assert not issubclass( jt.JevConfigError, jt.JevCallError ) and not issubclass( jt.JevCallError, jt.JevConfigError )
