"""
The height-tolerant fixture reports what it forgave, and keeps failing what it must.

The fixture body is driven directly, with a fake config, a fake request and a fake record_property, so no
browser and no server are needed. The comparator numbers are pinned in test_visual_forgiven_count.py.

Venue: :7999-discretionary.
"""

from __future__ import annotations

import importlib.util
import os
import sys
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image
from pytest_playwright_visual_snapshot.plugin import SnapshotPaths

_E2E_UI = Path( __file__ ).resolve().parents[ 1 ] / "e2e_ui"
if str( _E2E_UI ) not in sys.path: sys.path.insert( 0, str( _E2E_UI ) )

# The e2e_ui conftest pins the Testing config block in os.environ when it is imported. Pytest imports this file
# during collection, before any test runs, so that pin would stay for the whole unit run. Put the variable back.
_CONFIG_VAR    = "LUPIN_CONFIG_MGR_CLI_ARGS"
_CONFIG_BEFORE = os.environ.get( _CONFIG_VAR )
_spec = importlib.util.spec_from_file_location( "e2e_ui_conftest_under_test", _E2E_UI / "conftest.py" )
_conftest = importlib.util.module_from_spec( _spec )
_spec.loader.exec_module( _conftest )
if _CONFIG_BEFORE is None: os.environ.pop( _CONFIG_VAR, None )
else:                      os.environ[ _CONFIG_VAR ] = _CONFIG_BEFORE
_FIXTURE = _conftest.assert_snapshot_height_tolerant._get_wrapped_function()

GREY = ( 120, 120, 120, 255 )
NAME = "card.png"


def _png( dots=0, shade=2 ):
    img = Image.new( "RGBA", ( 40, 30 ), GREY )
    for x in range( dots ): img.putpixel( ( x, 0 ), ( GREY[ 0 ] + shade, GREY[ 1 ] + shade, GREY[ 2 ] + shade, 255 ) )
    buf = BytesIO()
    img.save( buf, "PNG" )
    return buf.getvalue()


@pytest.fixture
def driven( tmp_path, monkeypatch ):
    """The fixture's inner function, a baseline already on disk, and the recorder."""
    monkeypatch.setattr( SnapshotPaths, "failures_path", str( tmp_path / "failures" ), raising=False )
    config   = SimpleNamespace( rootdir=str( tmp_path ), getini=lambda key: "snaps", getoption=lambda key: False )
    node     = SimpleNamespace( fspath=str( tmp_path / "test_card_visual.py" ), name="test_card[chromium]" )
    request  = SimpleNamespace( config=config, node=node )
    recorded = [ ]
    check    = _FIXTURE( config, request, lambda key, value: recorded.append( ( key, value ) ) )
    baseline = tmp_path / "snaps" / "test_card_visual" / "test_card" / NAME
    baseline.parent.mkdir( parents=True )
    baseline.write_bytes( _png() )
    return SimpleNamespace( check=check, recorded=recorded, failures=tmp_path / "failures" )


def test_a_pass_inside_the_tolerance_prints_the_line_and_records_it( driven, capsys ):
    driven.check( _png( dots=12 ), name=NAME )
    printed = capsys.readouterr().out.strip()
    assert printed.startswith( "[height-tolerant-snapshot] card.png passed inside the tolerance" ), f"printed: {printed!r}"
    assert "12 pixel(s) differ at threshold 0.0" in printed and "40x30" in printed
    assert "threshold in force 0.03" in printed, f"the threshold in force is missing or wrong: {printed!r}"
    assert driven.recorded == [ ( "tolerance_forgiven", printed ) ], f"recorded: {driven.recorded}"


def test_an_exact_match_prints_nothing_and_records_nothing( driven, capsys ):
    driven.check( _png(), name=NAME )
    assert capsys.readouterr().out == "", "an exact match must print nothing"
    assert driven.recorded == [ ], "an exact match must record nothing"


def test_a_mismatch_over_the_tolerance_still_fails_and_saves_its_pictures( driven, capsys ):
    with pytest.raises( pytest.fail.Exception, match="DO NOT match" ):
        driven.check( _png( dots=5, shade=60 ), name=NAME )
    assert capsys.readouterr().out == "", "a failure must not print the forgiven line"
    assert driven.recorded == [ ]
    assert ( driven.failures / "test_card_visual" / "test_card" / f"actual_{NAME}" ).is_file(), "the failing capture was not saved"


def test_loading_the_e2e_conftest_leaves_the_config_block_as_it_was():
    assert os.environ.get( _CONFIG_VAR ) == _CONFIG_BEFORE
    assert _CONFIG_BEFORE is None or "Testing" not in _CONFIG_BEFORE
