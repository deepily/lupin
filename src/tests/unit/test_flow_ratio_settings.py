"""
The operator's ratio controls: window + threshold, their layering, and their limits.

WHY THIS MODULE EXISTS AT ALL. The window (24) and the threshold (1.0) were hardcoded in
three places, two of which were copies of the SAME number — the endpoint's verdict and
the create gate. The endpoint's docstring promises that number is computed in one place
"so the header and the gate cannot drift apart"; it was not, so they could.

🔴 EVERY TEST HERE POINTS THE MODULE AT A tmp_path, NEVER THE REAL DATA ROOT. The
override is a file under `fleet_data_root()`, which is shared by every process on this
box — a test that wrote there would move the LIVE fleet gate. `_isolated` monkeypatches
`override_path`, and the guard test below proves the isolation actually holds rather
than assuming it.

Venue: :7999-eligible — in-process, no server, no network, writes only under tmp_path.
"""

import json
import os

import pytest

from cosa.rest import flow_ratio_settings as frs


@pytest.fixture
def isolated( tmp_path, monkeypatch ):
    """
    Point the module's override file at tmp_path and clear its mtime cache.

    Ensures:
        - `override_path()` resolves inside tmp_path for the duration of the test
        - the module-level mtime cache is reset before AND after, so one test's write
          cannot be served to the next out of cache
    """
    target = tmp_path / "flow-ratio-settings.json"
    monkeypatch.setattr( frs, "override_path", lambda: str( target ) )
    monkeypatch.setattr( frs, "_cache", { "window_hours": None, "allow_below": None } )
    monkeypatch.setattr( frs, "_cache_mtime", None )
    return target


def test_the_isolation_actually_isolates( isolated ):
    """
    THE GUARD ON EVERY OTHER TEST IN THIS FILE, so it runs first.

    If the monkeypatch silently failed, every test below would still pass while writing
    to the real fleet data root and moving the live create gate. A fixture that does not
    isolate looks exactly like one that does — the failure and the success are invisible
    to the tests that depend on it.

    Ensures:
        - override_path() is the tmp file, not the real data root
        - a write lands THERE and nowhere else
    """
    assert frs.override_path() == str( isolated )
    assert "projects-data" not in frs.override_path()

    frs.set_overrides( allow_below=1.5 )
    assert isolated.exists(), "the write did not land in the isolated path"
    assert json.loads( isolated.read_text() )[ "allow_below" ] == 1.5


def test_with_no_override_the_values_come_from_config( isolated ):
    """
    Absent an override, the INI governs and says so.

    ⚠️ ASSERTS THE SOURCE, NOT THE NUMBER. The INI ships 24 / 1.0 and so do the module
    fallbacks, so a value assertion could not tell a real config read from a fallback
    masquerading as one — the two are byte-identical. `window_source` can.
    """
    settings = frs.current_settings()
    assert settings[ "window_source" ]    == "config"
    assert settings[ "threshold_source" ] == "config"


def test_an_override_wins_over_config_and_is_reported_as_such( isolated ):
    """A saved override governs, and current_settings() names it as the source."""
    frs.set_overrides( window_hours=168, allow_below=1.25 )

    assert frs.get_window_hours() == 168
    assert frs.get_allow_below()  == 1.25
    settings = frs.current_settings()
    assert settings[ "window_source" ]    == "override"
    assert settings[ "threshold_source" ] == "override"


def test_setting_one_value_leaves_the_other_alone( isolated ):
    """
    PATCH semantics, and the reason they are not optional.

    An operator dragging the threshold slider must not silently reset a window somebody
    else set. A replace-instead-of-patch would do exactly that, and nothing in the UI
    would report it — the other slider would simply jump.
    """
    frs.set_overrides( window_hours=168, allow_below=1.25 )
    frs.set_overrides( allow_below=0.8 )

    assert frs.get_allow_below()  == 0.8
    assert frs.get_window_hours() == 168, "the window was reset by a threshold-only write"


def test_the_override_survives_a_fresh_read( isolated, monkeypatch ):
    """
    PERSISTENCE, measured by discarding the cache rather than trusting it.

    An in-memory override would pass a naive read-back test and still be lost at the
    next bounce and invisible to the other server. Clearing the cache first is what makes
    this a test of the FILE.
    """
    frs.set_overrides( allow_below=1.75 )

    monkeypatch.setattr( frs, "_cache", { "window_hours": None, "allow_below": None } )
    monkeypatch.setattr( frs, "_cache_mtime", None )

    assert frs.get_allow_below() == 1.75


def test_clearing_returns_to_config_and_is_a_no_op_when_already_clear( isolated ):
    """Clearing removes the file; clearing twice is not an error."""
    frs.set_overrides( allow_below=1.9 )
    assert isolated.exists()

    settings = frs.clear_overrides()
    assert not isolated.exists()
    assert settings[ "threshold_source" ] == "config"

    frs.clear_overrides()          # already clear — must not raise


@pytest.mark.parametrize( "given,expected", [
    ( 0,      frs.MIN_WINDOW_HOURS ),
    ( 99_999, frs.MAX_WINDOW_HOURS ),
] )
def test_the_window_clamps_into_range( isolated, given, expected ):
    """Out-of-range windows clamp rather than being stored as given."""
    assert frs.set_overrides( window_hours=given )[ "window_hours" ] == expected


def test_set_overrides_returns_what_took_effect_not_what_was_asked( isolated ):
    """
    The returned value is the LIVE one, which is the point.

    A caller echoing its own request would show the operator a threshold the gate is not
    using whenever a value clamps — a slider that lies about the number it is enforcing
    is worse than one that refuses.
    """
    asked    = 99_999
    returned = frs.set_overrides( window_hours=asked )
    assert returned[ "window_hours" ] != asked
    assert returned[ "window_hours" ] == frs.get_window_hours()


@pytest.mark.parametrize( "kwargs,offending", [
    ( { "allow_below" : "banana" }, "allow_below"  ),
    ( { "window_hours": "soon"   }, "window_hours" ),
] )
def test_a_non_numeric_write_is_REFUSED_not_silently_defaulted( isolated, kwargs, offending ):
    """
    It raises rather than falling back, and the message names the argument.

    A fallback here would answer an operator's explicit write with a DIFFERENT number and
    report success — the failure mode this whole build exists to remove.
    """
    with pytest.raises( ValueError ) as caught:
        frs.set_overrides( **kwargs )
    assert offending in str( caught.value )

    assert not isolated.exists(), "a refused write still touched the override file"


def test_a_corrupt_override_file_falls_back_to_config_instead_of_throwing( isolated, capsys ):
    """
    Unparseable JSON degrades to config AND says so on stdout.

    A bad settings file must not take the board's header down. But it must not be silent
    either: an operator whose write vanished with no message has no way to tell a broken
    file from a working default.
    """
    isolated.write_text( "{ this is not json" )

    assert frs.current_settings()[ "threshold_source" ] == "config"
    assert "unusable" in capsys.readouterr().out


def test_a_json_file_that_is_not_an_object_is_also_rejected( isolated ):
    """A JSON array parses fine and is still not a settings file."""
    isolated.write_text( "[ 1, 2, 3 ]" )
    assert frs.current_settings()[ "threshold_source" ] == "config"


def test_a_write_is_visible_immediately_even_within_the_same_second( isolated ):
    """
    The write invalidates the cache rather than relying on the file's mtime moving.

    mtime has one-second granularity on some filesystems, so a write followed by a read
    inside the same second could otherwise be served the PREVIOUS value out of cache —
    the same whole-second trap that defeats .pyc invalidation elsewhere in this repo, and
    it would make the slider look like it had ignored every fast adjustment.
    """
    frs.set_overrides( allow_below=1.1 )
    frs.set_overrides( allow_below=1.2 )
    assert frs.get_allow_below() == 1.2


def test_the_write_is_atomic_leaving_no_temp_file_behind( isolated ):
    """The temp file is renamed into place, not left beside the real one."""
    frs.set_overrides( allow_below=1.3 )
    siblings = os.listdir( os.path.dirname( str( isolated ) ) )
    assert siblings == [ os.path.basename( str( isolated ) ) ], siblings


# ---------------------------------------------------------------------------
# The degradation paths. Each one is reached by BREAKING the layer beneath it,
# because these branches exist precisely for the case where something upstream is
# wrong — and a branch that has never executed is a guess about what it does.
# ---------------------------------------------------------------------------

def test_override_path_lands_under_the_fleet_data_root( monkeypatch ):
    """
    The real (un-monkeypatched) path resolver, HOST branch.

    Every other test replaces `override_path`, so without this one the function that
    decides WHERE fleet state is written would never run in the suite at all.

    ⚠️ THE SUBDIRECTORY IS THE POINT, and this test asserted it away until 2026-09-01.
    It expected `<root>/flow-ratio-settings.json` — the shape the code then had, which
    put the host branch one level ABOVE the mount the containers write into. The test
    ran the real resolver, as its docstring promises, and confirmed the defect rather
    than catching it. Expecting whatever the code returns is how a test that exercises
    the right function still endorses the wrong answer.
    """
    monkeypatch.delenv( frs._SETTINGS_DIR_ENV, raising=False )
    monkeypatch.setattr( frs, "fleet_data_root", lambda: "/tmp/does-not-need-to-exist" )
    assert frs.override_path() == (
        f"/tmp/does-not-need-to-exist/{frs.OVERRIDE_SUBDIR}/{frs.OVERRIDE_FILENAME}"
    )


def test_the_env_var_wins_over_the_fleet_data_root( monkeypatch ):
    """
    CONTAINER branch: $LUPIN_FLOW_RATIO_DIR is resolved FIRST.

    This is not a preference, it is the only thing that makes the feature work in
    Docker. Measured 2026-09-01 inside lupin-rest-dev, `fleet_data_root()` resolves to
    `/projects-data/lupin` — a path that does not exist and is not writable — so every
    settings PATCH answered 500 with PermissionError. The env var, pointed at a bind
    mount, is what `dm.py` already does for the DM corpus.

    Ensures:
        - the env var is used when set
        - the fleet-root resolver is NOT consulted at all in that case, which is the
          point: on the container it returns an unusable path, so merely preferring the
          env var while still calling the resolver would leave the failure one refactor
          away
    """
    def _must_not_be_called():
        raise AssertionError( "fleet_data_root() was consulted despite the env var being set" )

    monkeypatch.setenv( frs._SETTINGS_DIR_ENV, "/var/lupin/flow-ratio" )
    monkeypatch.setattr( frs, "fleet_data_root", _must_not_be_called )

    assert frs.override_path() == f"/var/lupin/flow-ratio/{frs.OVERRIDE_FILENAME}"


def test_an_empty_env_var_falls_through_to_the_fleet_root( monkeypatch ):
    """
    An empty string is not a path.

    Docker writes `KEY:` with no value as an empty string rather than leaving it unset,
    so treating "" as a real directory would put the settings file at `/flow-ratio-...`
    at the filesystem root. Falsy-check, not a presence-check — same reason `dm.py`
    writes `if override:` and not `if override is not None:`.
    """
    monkeypatch.setenv( frs._SETTINGS_DIR_ENV, "" )
    monkeypatch.setattr( frs, "fleet_data_root", lambda: "/tmp/fell-through" )
    assert frs.override_path() == (
        f"/tmp/fell-through/{frs.OVERRIDE_SUBDIR}/{frs.OVERRIDE_FILENAME}"
    )


def test_an_unreadable_ini_falls_back_and_reports_it( isolated, monkeypatch, capsys ):
    """
    A broken ConfigurationManager degrades to the shipped fallback, loudly.

    A silent fallback is how an operator's config edit appears to do nothing: the value
    they typed is ignored and the number they see is plausible.
    """
    def _explode( *args, **kwargs ):
        raise RuntimeError( "config is unavailable" )
    monkeypatch.setattr( frs, "ConfigurationManager", _explode )

    assert frs.get_window_hours() == frs.FALLBACK_WINDOW_HOURS
    assert frs.get_allow_below()  == frs.FALLBACK_ALLOW_BELOW
    assert "unreadable" in capsys.readouterr().out


@pytest.mark.parametrize( "stored,clamp,expected", [
    ( "not-a-number", "window",    frs.FALLBACK_WINDOW_HOURS ),
    ( "not-a-number", "threshold", frs.FALLBACK_ALLOW_BELOW  ),
] )
def test_a_non_numeric_value_already_on_disk_falls_back_and_reports_it(
    isolated, capsys, stored, clamp, expected
):
    """
    A junk value that reached the file by some other route degrades rather than throwing.

    `set_overrides` refuses non-numbers, so this cannot arrive through the API — it
    arrives from a hand-edited file or a bad INI. The READ path must survive it: the
    board's header going blank because somebody fat-fingered a config file would be a
    worse outcome than falling back.
    """
    key = "window_hours" if clamp == "window" else "allow_below"
    isolated.write_text( json.dumps( { key: stored } ) )

    actual = frs.get_window_hours() if clamp == "window" else frs.get_allow_below()
    assert actual == expected
    assert "is not a" in capsys.readouterr().out


# 🔴 THE SHIPPED DEFAULTS, PINNED BY LITERAL — AND WHY A LITERAL IS THE WHOLE POINT.
#
# Found by an independent mutation pass, 2026-09-02 (Tiberius 👑). Two arms — 24 -> 48
# and 1.0 -> 0.0 — SURVIVED the entire sixteen-file population. Not because the fallback
# path is uncovered; it is covered, and coverage reports these lines green at 100%.
#
# The assertions that cover it read:
#
#     assert frs.get_window_hours() == frs.FALLBACK_WINDOW_HOURS
#     assert frs.get_allow_below()  == frs.FALLBACK_ALLOW_BELOW
#
# They compare the function's result to THE SAME CONSTANT the function returns. Change
# the constant and both sides move together, so the comparison is true for every possible
# value. It is not a weak assertion — it is an UNFALSIFIABLE one, and no amount of reading
# the test body reveals that, because the test body is correct. Only replacing the source
# constant and watching nothing redden does.
#
# ⇒ These two tests are therefore the ONLY place in the population that holds the shipped
# numbers to account, and they must never be rewritten to reference `frs.FALLBACK_*`. The
# literal IS the control: it is written here independently of the source, so the two can
# disagree — which is the only way a test can notice the source moving.
#
# The module docstring above already names these numbers ("the window (24) and the
# threshold (1.0)"), so the literals below are not a new decision; they are the existing
# documented contract, finally asserted.

def test_the_shipped_window_default_is_24_hours():
    """
    The fallback window is 24, pinned by a literal written independently of the source.

    Ensures:
        - reddens if FALLBACK_WINDOW_HOURS is changed, which the reference-comparison
          assertions elsewhere in this module cannot do
    """
    assert frs.FALLBACK_WINDOW_HOURS == 24, (
        "the shipped fallback window changed. This is the documented default named in "
        "this module's own docstring; if the change is deliberate, update the docstring "
        "and this literal together — do NOT make this assertion reference "
        "frs.FALLBACK_WINDOW_HOURS, which would make it unfalsifiable again."
    )


def test_the_shipped_threshold_default_is_one_point_zero():
    """
    The fallback threshold is 1.0, pinned by a literal written independently of the source.

    Ensures:
        - reddens if FALLBACK_ALLOW_BELOW is changed
        - pins the SEMANTIC boundary too: at exactly 1.0 the gate is closed, because the
          gate opens on a ratio STRICTLY below the threshold
    """
    assert frs.FALLBACK_ALLOW_BELOW == 1.0, (
        "the shipped fallback threshold changed. 1.0 means 'closing as many as you file'; "
        "the gate opens strictly BELOW it. Update the docstring and this literal together "
        "— do NOT make this assertion reference frs.FALLBACK_ALLOW_BELOW."
    )


def test_an_unavailable_config_yields_the_LITERAL_defaults_not_merely_the_constants( monkeypatch, capsys ):
    """
    The degraded path returns 24 / 1.0 — the values, not whichever constants are shipped.

    This is `test_an_unreadable_ini_falls_back_and_reports_it` written so it can fail.
    That test asserts `get_window_hours() == frs.FALLBACK_WINDOW_HOURS`; this one asserts
    the number an operator would actually see.

    Ensures:
        - a broken ConfigurationManager degrades to 24 hours and 1.0
        - the degradation is still reported on stdout, not silent
    """
    def _explode( *args, **kwargs ):
        raise RuntimeError( "config is unavailable" )
    monkeypatch.setattr( frs, "ConfigurationManager", _explode )
    monkeypatch.setattr( frs, "_cache", { "window_hours": None, "allow_below": None } )
    monkeypatch.setattr( frs, "_cache_mtime", None )

    assert frs.get_window_hours() == 24
    assert frs.get_allow_below()  == 1.0
    assert "unreadable" in capsys.readouterr().out
