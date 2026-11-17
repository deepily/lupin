"""
The one container check: the LUPIN_IN_CONTAINER sentinel and /.dockerenv.
"""
import pytest

from cosa.utils import container_env as ce


@pytest.mark.parametrize( "value", [ "1", "true", "TRUE", " Yes ", "yes" ] )
def test_a_true_word_sets_the_sentinel( monkeypatch, value ):
    monkeypatch.setenv( "LUPIN_IN_CONTAINER", value )
    assert ce.container_sentinel_set() is True


@pytest.mark.parametrize( "value", [ "", "0", "false", "no", "on", "container" ] )
def test_any_other_text_leaves_the_sentinel_off( monkeypatch, value ):
    monkeypatch.setenv( "LUPIN_IN_CONTAINER", value )
    assert ce.container_sentinel_set() is False


def test_an_absent_sentinel_is_off( monkeypatch ):
    monkeypatch.delenv( "LUPIN_IN_CONTAINER", raising=False )
    assert ce.container_sentinel_set() is False


def test_the_sentinel_alone_makes_a_container_without_the_file( monkeypatch ):
    monkeypatch.setenv( "LUPIN_IN_CONTAINER", "yes" )
    monkeypatch.setattr( ce.os.path, "exists", lambda path: False )
    assert ce.running_in_container() is True


def test_the_dockerenv_file_alone_makes_a_container( monkeypatch ):
    monkeypatch.delenv( "LUPIN_IN_CONTAINER", raising=False )
    monkeypatch.setattr( ce.os.path, "exists", lambda path: path == "/.dockerenv" )
    assert ce.running_in_container() is True


def test_neither_signal_means_a_host_and_a_falsy_sentinel_hides_nothing( monkeypatch ):
    monkeypatch.setenv( "LUPIN_IN_CONTAINER", "0" )
    monkeypatch.setattr( ce.os.path, "exists", lambda path: False )
    assert ce.running_in_container() is False
    monkeypatch.setattr( ce.os.path, "exists", lambda path: path == "/.dockerenv" )
    assert ce.running_in_container() is True
