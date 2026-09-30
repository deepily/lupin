"""
Unit tests for `src/tests/e2e_ui/selector_census.py` — row `04735b66`.

THE CENSUS EXISTS TO STATE A DENOMINATOR, so the cases that matter are the ones that pin what
it REFUSES to count. Two of them are regressions of defects the census committed on itself:

  · it matched only DOUBLE-quoted outer strings, and reported SIX literals where a fixed-string
    grep found forty-four — the tree writes `'[data-testid="x"]'`, single outside;
  · it rewrote ANY bare name into a data-testid selector, inventing selectors nobody had
    written and then confidently reporting them DEAD.

Both are the same shape as the defect the census was built to count. They are pinned here, not
just fixed, because a census that has never been caught inventing is one nobody has checked.
"""
import pathlib, subprocess, sys

import pytest

sys.path.insert( 0, str( pathlib.Path( __file__ ).resolve().parents[ 1 ] / "e2e_ui" ) )

import selector_census as sc


@pytest.fixture
def repo( tmp_path ):
    """A real one-commit git repo — the population must come from git, so the test gives it one."""
    ( tmp_path / "src/tests" ).mkdir( parents=True )
    ( tmp_path / "src/lupin_app/static/html" ).mkdir( parents=True )
    ( tmp_path / "src/lupin_app/static/html/multiplexer.html" ).write_text(
        '<div id="fleet-status-pane" data-testid="multiplexer-fleet-status-pane"></div>' )
    ( tmp_path / "src/lupin_app/static/html/notifications.html" ).write_text(
        '<div id="section-fleet-status"></div><div id="clock"></div>' )
    ( tmp_path / "src/tests/probe.py" ).write_text(
        "SEL = '[data-testid=\"multiplexer-fleet-status-pane\"]'\n"
        "OTHER = \"#section-fleet-status\"\n"
        "page.locator( '#fleet-status-pane .inner' )\n"
        "page.get_by_test_id( 'multiplexer-fleet-pane' )\n"
        "LOOKUP = { 'audio': 'clock' }\n"
        "COMPOSED = f'[data-testid=\"multiplexer-{name}-pane\"]'\n" )
    ( tmp_path / "src/tests/thing.test.ts" ).write_text(
        'el.querySelector( \'[data-testid="multiplexer-task-list-pane"]\' );\n' )
    ( tmp_path / "src/tests/unrelated.py" ).write_text( "x = '#login-submit'\n" )
    subprocess.run( [ "git", "init", "-q" ], cwd=tmp_path, check=True )
    subprocess.run( [ "git", "add", "-A" ], cwd=tmp_path, check=True )
    subprocess.run( [ "git", "-c", "user.email=t@t", "-c", "user.name=t",
                      "commit", "-qm", "seed" ], cwd=tmp_path, check=True )
    return tmp_path


# --------------------------------------------------------------------------------------
# _root
# --------------------------------------------------------------------------------------
def test_root_prefers_the_explicit_argument( tmp_path ):
    assert sc._root( tmp_path ) == tmp_path


def test_root_reads_the_environment_when_no_argument_is_given( monkeypatch ):
    monkeypatch.setenv( "LUPIN_ROOT", "/some/root" )
    assert sc._root() == pathlib.Path( "/some/root" )


def test_root_refuses_when_lupin_root_is_unset( monkeypatch ):
    monkeypatch.delenv( "LUPIN_ROOT", raising=False )
    with pytest.raises( RuntimeError, match="LUPIN_ROOT not set" ):
        sc._root()


# --------------------------------------------------------------------------------------
# population_files — derived from git, and refusing an empty answer
# --------------------------------------------------------------------------------------
def test_the_population_comes_from_git_not_a_disk_walk( repo ):
    """A disk walk of src/ in the real tree is ~92% .venv. Untracked files must not count."""
    ( repo / "src/tests/untracked.py" ).write_text( "x = '#fleet-status-pane'\n" )
    files = sc.population_files( repo )
    assert "src/tests/probe.py" in files
    assert "src/tests/untracked.py" not in files


def test_the_population_is_filtered_to_source_suffixes( repo ):
    ( repo / "src/tests/notes.md" ).write_text( "#fleet-status-pane\n" )
    subprocess.run( [ "git", "add", "-A" ], cwd=repo, check=True )
    assert not any( f.endswith( ".md" ) for f in sc.population_files( repo ) )


def test_an_empty_population_is_refused_rather_than_reported_as_a_clean_zero( repo ):
    """A census over nothing returns zeros that look exactly like a clean surface."""
    with pytest.raises( RuntimeError, match="ZERO files" ):
        sc.population_files( repo, pathspecs=[ "src/nothing-here" ] )


def test_population_files_falls_back_to_the_environment_root( repo, monkeypatch ):
    monkeypatch.setenv( "LUPIN_ROOT", str( repo ) )
    assert sc.population_files()


# --------------------------------------------------------------------------------------
# shipped_anchor_names
# --------------------------------------------------------------------------------------
def test_shipped_anchors_are_read_from_both_surface_pages( repo ):
    names = sc.shipped_anchor_names( repo )
    assert "fleet-status-pane"             in names   # multiplexer, by id
    assert "multiplexer-fleet-status-pane" in names   # multiplexer, by testid
    assert "section-fleet-status"          in names   # legacy
    assert "clock"                         in names   # legacy


def test_an_empty_anchor_parse_is_refused( repo ):
    for rel in sc.SURFACE_HTML:
        ( repo / rel ).write_text( "<div></div>" )
    with pytest.raises( RuntimeError, match="ZERO anchors" ):
        sc.shipped_anchor_names( repo )


def test_shipped_anchor_names_falls_back_to_the_environment_root( repo, monkeypatch ):
    monkeypatch.setenv( "LUPIN_ROOT", str( repo ) )
    assert sc.shipped_anchor_names()


# --------------------------------------------------------------------------------------
# extraction — the two self-inflicted defects, pinned
# --------------------------------------------------------------------------------------
def test_a_single_quoted_outer_string_is_seen():
    """THE REGRESSION: matching only double-quoted outer strings reported 6 literals where a
    grep found 44. The tree's dominant spelling is single outside, double inside."""
    got = sc.extract_literals( """SEL = '[data-testid="multiplexer-fleet-pane"]'""" )
    assert '[data-testid="multiplexer-fleet-pane"]' in got


def test_a_double_quoted_outer_string_is_seen_too():
    assert "#fleet-status-pane" in sc.extract_literals( 'SEL = "#fleet-status-pane"' )


def test_a_bare_name_in_a_lookup_table_is_not_invented_into_a_selector():
    """THE REGRESSION: `{ "audio": "audio-ws-status" }` is an ID in a dict. Rewriting it into
    `[data-testid="audio-ws-status"]` manufactured a probe bug and blamed the tree for it."""
    got = sc.extract_literals( 'LOOKUP = { "audio": "audio-ws-status" }' )
    assert '[data-testid="audio-ws-status"]' not in got
    assert got == set()


def test_a_bare_name_inside_a_testid_call_IS_counted():
    """The paired positive: it is a selector when somebody used it as one."""
    for src in ( 'page.get_by_test_id( "multiplexer-fleet-pane" )',
                 'page.getByTestId( "multiplexer-fleet-pane" )' ):
        assert '[data-testid="multiplexer-fleet-pane"]' in sc.extract_literals( src )


def test_single_and_double_quoted_attribute_values_count_as_one_anchor():
    a = sc.extract_literals( """x = "[data-testid='multiplexer-x']" """ )
    b = sc.extract_literals( '''x = '[data-testid="multiplexer-x"]' ''' )
    assert a == b == { '[data-testid="multiplexer-x"]' }


def test_normalise_leaves_a_plain_id_alone():
    assert sc.normalise( "#fleet-status-pane" ) == "#fleet-status-pane"


# --------------------------------------------------------------------------------------
# names_surface — two clauses, and the gap they leave
# --------------------------------------------------------------------------------------
def test_a_multiplexer_spelled_literal_is_in_surface_even_when_shipped_by_nothing():
    """Clause 1 is what makes a DEAD selector COUNTABLE — it is in no registry, so a
    membership test alone could never see it."""
    assert sc.names_surface( '[data-testid="multiplexer-fleet-pane"]', set() )


def test_a_legacy_id_is_in_surface_by_shipped_membership():
    assert sc.names_surface( "#section-fleet-status", { "section-fleet-status" } )


def test_a_selector_for_another_page_is_not_counted():
    assert not sc.names_surface( "#login-submit", { "section-fleet-status" } )


def test_a_testid_literal_is_matched_on_its_attribute_value_not_the_whole_string():
    assert sc.names_surface( '[data-testid="clock"]', { "clock" } )


# --------------------------------------------------------------------------------------
# bucket_for — exhaustive and mutually exclusive
# --------------------------------------------------------------------------------------
@pytest.mark.parametrize( "literal, jsdom, expected", [
    ( "#fleet-status-pane",                        False, sc.Bucket.PAGE_ANCHOR ),
    ( '[data-testid="multiplexer-x"]',             False, sc.Bucket.PAGE_ANCHOR ),
    ( "#fleet-status-pane .inner",                 False, sc.Bucket.COMPOUND ),
    ( '[data-testid="multiplexer-x"]',             True,  sc.Bucket.JSDOM_ONLY ),
    ( '[data-testid="multiplexer-{name}-pane"]',   False, sc.Bucket.UNRESOLVABLE ),
] )
def test_every_literal_lands_in_exactly_one_bucket( literal, jsdom, expected ):
    assert sc.bucket_for( literal, jsdom ) == expected


def test_an_interpolated_literal_outranks_its_jsdom_home():
    """A name-generator is unresolvable wherever it lives — the guard can only classify a name."""
    assert sc.bucket_for( "[data-testid=\"multiplexer-{x}\"]", True ) == sc.Bucket.UNRESOLVABLE


# --------------------------------------------------------------------------------------
# census
# --------------------------------------------------------------------------------------
def test_the_buckets_partition_the_distinct_literals( repo ):
    r     = sc.census( repo )
    total = sum( len( v ) for v in r[ "buckets" ].values() )
    assert total == len( r[ "homes" ] )
    assert r[ "files" ] > 0


def test_census_places_each_fixture_literal_where_it_belongs( repo ):
    b = sc.census( repo )[ "buckets" ]
    assert '[data-testid="multiplexer-fleet-status-pane"]' in b[ sc.Bucket.PAGE_ANCHOR ]
    assert "#section-fleet-status"                         in b[ sc.Bucket.PAGE_ANCHOR ]
    assert "#fleet-status-pane .inner"                     in b[ sc.Bucket.COMPOUND ]
    assert '[data-testid="multiplexer-task-list-pane"]'    in b[ sc.Bucket.JSDOM_ONLY ]
    assert any( "{" in lit for lit in b[ sc.Bucket.UNRESOLVABLE ] )


def test_a_literal_named_by_both_a_probe_and_a_jsdom_test_is_not_jsdom_only( repo ):
    """JSDOM_ONLY means ONLY — a shared literal is a real page anchor."""
    ( repo / "src/tests/probe2.py" ).write_text(
        "page.locator( '[data-testid=\"multiplexer-task-list-pane\"]' )\n" )
    subprocess.run( [ "git", "add", "-A" ], cwd=repo, check=True )
    b = sc.census( repo )[ "buckets" ]
    assert '[data-testid="multiplexer-task-list-pane"]' in b[ sc.Bucket.PAGE_ANCHOR ]


def test_census_records_every_home_of_a_literal( repo ):
    homes = sc.census( repo )[ "homes" ]
    assert homes[ "#section-fleet-status" ] == [ "src/tests/probe.py" ]


def test_census_ignores_a_selector_belonging_to_another_page( repo ):
    assert "#login-submit" not in sc.census( repo )[ "homes" ]


def test_census_falls_back_to_the_environment_root( repo, monkeypatch ):
    monkeypatch.setenv( "LUPIN_ROOT", str( repo ) )
    assert sc.census()[ "files" ] > 0


# --------------------------------------------------------------------------------------
# guard_coverage + render
# --------------------------------------------------------------------------------------
def test_guard_coverage_reports_a_verdict_for_every_page_anchor():
    """Runs against the REAL checkout, because the guard's authority is the real product."""
    root = pathlib.Path( __file__ ).resolve().parents[ 3 ]
    cov  = sc.guard_coverage( [ "#fleet-status-pane",
                                '[data-testid="multiplexer-fleet-pane"]' ], root )
    assert cov[ "#fleet-status-pane" ][ 0 ] == "SHIPPED_ID"
    assert cov[ '[data-testid="multiplexer-fleet-pane"]' ][ 0 ] == "DEAD"


def test_guard_coverage_falls_back_to_the_environment_root( monkeypatch ):
    monkeypatch.setenv( "LUPIN_ROOT", str( pathlib.Path( __file__ ).resolve().parents[ 3 ] ) )
    assert sc.guard_coverage( [ "#fleet-status-pane" ] )


def test_render_names_the_population_and_every_bucket( repo ):
    out = sc.render( sc.census( repo ) )
    assert "POPULATION:" in out
    assert "DISTINCT SURFACE SELECTOR LITERALS:" in out
    for name in sc.Bucket.ALL:
        assert name in out


def test_render_folds_in_the_guard_verdicts_when_given_them( repo ):
    out = sc.render( sc.census( repo ),
                     { "#a": ( "SHIPPED_ID", "" ), "#b": ( "DEAD", "" ) } )
    assert "selector_guard verdicts over the 2 PAGE_ANCHOR literals" in out
    assert "SHIPPED_ID" in out and "DEAD" in out
