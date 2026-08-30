"""
Control-proof for the dm_compression loud-skip conftest.

WHAT IS UNDER TEST, AND WHY IT NEEDED ITS OWN CONTROL. The conftest exists to
stop a silent skip reading as a pass. A reporting hook that is never watched
failing is exactly the untested assertion it was written to prevent — so every
test here breaks it on purpose and checks that it notices.

THE CENTRAL ONE IS `test_the_count_is_measured_not_declared`. The absent corpus
costs 6 tests today. A conftest that PRINTS 6 and a conftest that COUNTS 6 are
indistinguishable on this tree and diverge the moment somebody adds a seventh
corpus test. That test feeds the hook 3 skips and then 9 and demands the output
change, which no hardcoded number survives.

Venue :7999/unit — pure in-process assertions on hook return values. No server,
no corpus, no state, well under a second.
"""

import pytest


def _load_conftest():
    """
    Import the dm_compression conftest as a module.

    Requires:
        - the repo root is importable (the unit tier's standing arrangement)

    Ensures:
        - returns the loaded module object
        - raises loudly if the file has moved, rather than skipping quietly —
          a control that vanishes when its target moves is not a control
    """
    import os
    import importlib.util

    import cosa.utils.util as cu

    path = os.path.join(
        cu.get_project_root(), "src", "tests", "unit", "dm_compression", "conftest.py" )
    assert os.path.exists( path ), f"the conftest under test is missing: {path}"

    spec   = importlib.util.spec_from_file_location( "dm_compression_conftest", path )
    module = importlib.util.module_from_spec( spec )
    spec.loader.exec_module( module )
    return module


class FakeReport:
    """One skipped test report, in the shape pytest hands the summary hook."""

    def __init__( self, nodeid, longrepr ):
        self.nodeid  = nodeid
        self.longrepr = longrepr


class FakeTerminalReporter:
    """Records what the hook wrote, so the assertions can read it back."""

    def __init__( self, skipped ):
        self.stats = { "skipped": skipped }
        self.lines = []
        self.seps  = []

    def write_sep( self, char, title, **kwargs ):
        self.seps.append( title )

    def write_line( self, line ):
        self.lines.append( line )

    def text( self ):
        return "\n".join( self.lines )


def _our_skip( nodeid ):
    """A skip carrying the fixture's real reason, in pytest's 3-tuple shape."""
    return FakeReport(
        nodeid, ( "test_freeze.py", 68, "Skipped: corpus snapshot not present: /nope/snap.jsonl" ) )


def _foreign_skip( nodeid ):
    """A skip for some unrelated reason, which must NOT be counted."""
    return FakeReport( nodeid, ( "test_other.py", 12, "Skipped: needs a GPU" ) )


# ----------------------------------------------------------------------------
# The header hook was REMOVED after measurement — this test holds it removed
# ----------------------------------------------------------------------------

def test_there_is_no_report_header_hook():
    """
    A header here would fire only without `-q` and only when the run is rooted
    near this directory — neither of which is how this tier is ever run. Its
    absence would then read as "corpus present", which is the false-green this
    package exists to close. Measured before removing it; held removed here so
    a well-meaning re-add has to argue with a red test first.
    """
    module = _load_conftest()

    assert not hasattr( module, "pytest_report_header" ), (
        "a report header fires only in non-quiet, directory-rooted runs; the fleet runs -q "
        "over the whole tier, so its silence would be mistaken for a present corpus" )


# ----------------------------------------------------------------------------
# The summary — the count, and the discrimination
# ----------------------------------------------------------------------------

def test_the_summary_reports_the_skips_and_names_them():
    module   = _load_conftest()
    reporter = FakeTerminalReporter( [ _our_skip( "a::t1" ), _our_skip( "b::t2" ) ] )

    module.pytest_terminal_summary( reporter, exitstatus=0, config=None )

    assert "2 test(s) skipped" in reporter.text()
    assert "a::t1" in reporter.text() and "b::t2" in reporter.text(), (
        "naming the tests is the point — a bare count cannot be acted on" )
    assert reporter.seps, "the block must be separated, not buried in passing dots"


def test_the_count_is_measured_not_declared():
    """
    THE ONE THAT MATTERS. A hardcoded 6 passes every other test in this file.
    """
    module = _load_conftest()

    three = FakeTerminalReporter( [ _our_skip( f"x::t{i}" ) for i in range( 3 ) ] )
    module.pytest_terminal_summary( three, exitstatus=0, config=None )

    nine = FakeTerminalReporter( [ _our_skip( f"y::t{i}" ) for i in range( 9 ) ] )
    module.pytest_terminal_summary( nine, exitstatus=0, config=None )

    assert "3 test(s) skipped" in three.text()
    assert "9 test(s) skipped" in nine.text()
    assert "6" not in three.text().split( "skipped" )[ 0 ], (
        "the count must come from the run, never from a constant that goes stale the moment "
        "somebody adds a seventh corpus test" )


def test_a_skip_for_another_reason_is_not_counted():
    module   = _load_conftest()
    reporter = FakeTerminalReporter( [ _our_skip( "mine::t" ), _foreign_skip( "theirs::t" ) ] )

    module.pytest_terminal_summary( reporter, exitstatus=0, config=None )

    assert "1 test(s) skipped" in reporter.text(), "only corpus skips belong to this count"
    assert "theirs::t" not in reporter.text()


def test_the_summary_is_silent_when_nothing_skipped_for_the_corpus():
    module   = _load_conftest()
    reporter = FakeTerminalReporter( [ _foreign_skip( "theirs::t" ) ] )

    module.pytest_terminal_summary( reporter, exitstatus=0, config=None )

    assert reporter.lines == [], "a run that lost nothing must say nothing"


def test_no_skips_at_all_is_silent():
    module   = _load_conftest()
    reporter = FakeTerminalReporter( [] )

    module.pytest_terminal_summary( reporter, exitstatus=0, config=None )

    assert reporter.lines == []


# ----------------------------------------------------------------------------
# The shapes pytest actually hands us — the hook must not take a run down
# ----------------------------------------------------------------------------

@pytest.mark.parametrize( "longrepr,expected", [
    ( ( "f.py", 1, "Skipped: corpus snapshot not present: /x" ), True  ),
    ( "corpus snapshot not present: /x",                         True  ),
    ( ( "f.py", 1, "Skipped: unrelated" ),                       False ),
    ( "unrelated",                                               False ),
    ( None,                                                      False ),
] )
def test_every_longrepr_shape_is_classified_without_raising( longrepr, expected ):
    module = _load_conftest()

    assert module._skipped_for_missing_corpus( FakeReport( "n::t", longrepr ) ) is expected


def test_the_reason_prefix_matches_the_fixture_that_produces_it():
    """
    The conftest matches on a prefix the fixture writes. If somebody reworded the
    fixture's skip message, this hook would silently count zero and the loud skip
    would go quiet again — the exact failure it exists to prevent.
    """
    import os

    import cosa.utils.util as cu

    module = _load_conftest()
    path   = os.path.join(
        cu.get_project_root(), "src", "tests", "unit", "dm_compression", "test_freeze.py" )
    source = open( path ).read()

    assert module.SKIP_REASON_PREFIX in source, (
        f"the fixture no longer emits {module.SKIP_REASON_PREFIX!r}; the summary hook is now "
        "matching a string nobody writes and will report zero skips forever" )
