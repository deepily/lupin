"""
Unit tests of the run harness: arm switch, stop condition and per-run database.

The ports are stubs that behave like what they stand for. The session stub refuses a call by the deny rules, as the CLI does.
So the arm tests redden if the configuration stops denying a surface. The server stub keeps real per-name databases.
A shared or reused database then shows up as rows that should not be there.
"""
import re

import pytest

from cosa.repo.semdup import frozen
from lupin_mcp.reuse_harness import arms
from lupin_mcp.reuse_harness import errors as err
from lupin_mcp.reuse_harness import run as harness

TEST_IDS = [ "t1", "t2", "t3", "t4" ]


class StubWorktree:
    """A worktree port that keeps the files of each path it made."""

    def __init__( self, client=None, keep_paths=False ):
        """Remember what the client folder holds, and whether removals are ignored."""
        self.client     = client or []
        self.keep_paths = keep_paths
        self.made       = {}

    def create( self, run_id, commit, remove_paths ):
        """Make a worktree holding the skill folder, minus what the arm removes (unless keep_paths)."""
        path             = f"/wt/{run_id}"
        files            = { arms.SKILL_PATH, "CLAUDE.md" }
        if not self.keep_paths: files -= set( remove_paths )
        self.made[ path ] = { "commit" : commit, "files" : files }
        return path

    def client_entries( self, path ):
        """Return the client folder's entries."""
        return list( self.client )

    def exists( self, path, relative ):
        """Say whether the worktree holds the file."""
        return relative in self.made[ path ][ "files" ]


class StubServer:
    """A server port with one real database per name, shared across runs so reuse would show."""

    def __init__( self, preload=None, wrong_name=False ):
        """Start with no databases, or with rows already in the one a run is about to get."""
        self.dbs        = {}
        self.preload    = preload
        self.wrong_name = wrong_name
        self.history    = []

    def start( self, run_id, path ):
        """Create the run's database and container, or hand back a mismatched name."""
        name = harness.db_name( "someone-else" ) if self.wrong_name else harness.db_name( run_id )
        self.dbs[ name ] = list( self.preload or [] )
        self.history.append( ( "start", name ) )
        return { "url" : "http://stub", "container" : harness.container_name( run_id ), "db_name" : name }

    def db_is_fresh( self, handle ):
        """Say whether the database holds no rows."""
        return self.dbs[ handle[ "db_name" ] ] == []

    def stop( self, handle ):
        """Drop the database."""
        self.history.append( ( "stop", handle[ "db_name" ] ) )
        del self.dbs[ handle[ "db_name" ] ]


class StubSession:
    """
    A session port: the client under construction passes `per_slice` more tests each slice.

    probe() refuses by the configuration's deny rules, as the CLI does; leaky=True models a CLI that ignores them.
    """

    def __init__( self, per_slice=1, hours=1.0, finish_after=None, leaky=False, blind=False ):
        """Set how fast the stub client gains passing tests and how many hours a slice costs."""
        self.per_slice    = per_slice
        self.hours        = hours
        self.finish_after = finish_after
        self.leaky        = leaky
        self.blind        = blind
        self.slices       = 0
        self.progress     = 0
        self.budgets      = []

    def probe( self, config, surface ):
        """Answer a call to the surface unless a deny rule of the config names it."""
        if self.blind: return False
        return self.leaky or arms.DENY_RULES[ surface ] not in config[ "deny_rules" ]

    def work( self, config, path, handle, remaining_hours ):
        """Do one slice: gain passing tests and report the hours used."""
        self.slices   += 1
        self.progress += self.per_slice
        self.budgets.append( remaining_hours )
        return { "seat_hours" : self.hours, "finished" : self.finish_after is not None and self.slices >= self.finish_after }


class StubTests:
    """A test port: the first `progress` tests pass. It writes a row, as the acceptance tests do."""

    def __init__( self, session, server, builds=True ):
        """Read the progress from the session and write to the server's databases."""
        self.session = session
        self.server  = server
        self.builds  = builds

    def run( self, handle, path, test_ids ):
        """Run the tests against the run's own database."""
        self.server.dbs[ handle[ "db_name" ] ].append( "row" )
        return { "results" : { test_id : index < self.session.progress for index, test_id in enumerate( test_ids ) }, "client_builds" : self.builds }


class StubLog:
    """A log port that keeps the records."""

    def __init__( self ):
        """Start empty."""
        self.records = []

    def write( self, record ):
        """Keep the record."""
        self.records.append( record )


class Ports:
    """The five ports of a run."""

    def __init__( self, session=None, server=None, worktree=None ):
        """Wire the stubs, each overridable."""
        self.session  = session  or StubSession()
        self.server   = server   or StubServer()
        self.worktree = worktree or StubWorktree()
        self.tests    = StubTests( self.session, self.server )
        self.log      = StubLog()


def spec( **over ):
    """Build a valid spec with some fields replaced."""
    base = { "run_id" : "pair01-a", "arm" : arms.ARM_WITH, "model_id" : "claude-opus-5-5", "server_commit" : "abc1234", "cap_seat_hours" : 10, "test_ids" : list( TEST_IDS ) }
    base.update( over )
    return base


# ── the arm switch ──────────────────────────────────────────────────────────────────────────

def test_the_four_surfaces_are_the_plans_four():
    """The plan names three tools and one skill."""
    assert arms.SURFACES == ( "check_exists", "fetch_similar", "read_capability", "reuse-reviewer" )


@pytest.mark.parametrize( "surface", arms.SURFACES )
def test_without_arm_cannot_call_a_surface_and_with_arm_can( surface ):
    """The dry run of plan 7.3: each surface is refused without and answers with."""
    session = StubSession()
    assert session.probe( arms.build_session_config( arms.ARM_WITHOUT, "m" ), surface ) is False
    assert session.probe( arms.build_session_config( arms.ARM_WITH, "m" ), surface ) is True


def test_verify_arm_returns_what_the_session_answered_for_each_arm():
    """The proof is the session's answers, in surface order."""
    without = arms.verify_arm( arms.ARM_WITHOUT, arms.build_session_config( arms.ARM_WITHOUT, "m" ), StubSession() )
    with_   = arms.verify_arm( arms.ARM_WITH, arms.build_session_config( arms.ARM_WITH, "m" ), StubSession() )
    assert list( without.items() ) == [ ( surface, False ) for surface in arms.SURFACES ]
    assert list( with_.items() )   == [ ( surface, True ) for surface in arms.SURFACES ]


def test_a_leaky_session_in_the_without_arm_is_refused_naming_every_surface():
    """A session that ignores the deny rules answers all four; the error names them."""
    with pytest.raises( err.HarnessError ) as raised:
        arms.verify_arm( arms.ARM_WITHOUT, arms.build_session_config( arms.ARM_WITHOUT, "m" ), StubSession( leaky=True ) )
    assert raised.value.code == err.SURFACE_REACHABLE
    assert all( surface in raised.value.detail for surface in arms.SURFACES )


def test_a_blind_session_in_the_with_arm_is_refused_naming_every_surface():
    """A with-arm session that reaches none of the surfaces is refused."""
    with pytest.raises( err.HarnessError ) as raised:
        arms.verify_arm( arms.ARM_WITH, arms.build_session_config( arms.ARM_WITH, "m" ), StubSession( blind=True ) )
    assert raised.value.code == err.SURFACE_MISSING
    assert all( surface in raised.value.detail for surface in arms.SURFACES )


def test_one_leaking_surface_is_enough_to_refuse_the_without_arm():
    """Three denied and one reachable still fails: the check is per surface."""
    config = arms.build_session_config( arms.ARM_WITHOUT, "m" )
    config[ "deny_rules" ].remove( arms.DENY_RULES[ arms.SURFACE_REVIEWER ] )
    with pytest.raises( err.HarnessError ) as raised:
        arms.verify_arm( arms.ARM_WITHOUT, config, StubSession() )
    assert raised.value.code == err.SURFACE_REACHABLE and raised.value.detail.count( "reuse-reviewer" ) == 1 and "check_exists" not in raised.value.detail


def test_verify_arm_refuses_an_unknown_arm():
    """An unknown arm name is BAD_ARM."""
    with pytest.raises( err.HarnessError ) as raised:
        arms.verify_arm( "both", {}, StubSession() )
    assert raised.value.code == err.BAD_ARM


def test_the_arms_differ_in_the_surface_keys_and_nothing_else():
    """The model, settings sources, CLAUDE.md and grep are the same in both arms."""
    with_, without = arms.build_session_config( arms.ARM_WITH, "m" ), arms.build_session_config( arms.ARM_WITHOUT, "m" )
    differing = sorted( key for key in with_ if with_[ key ] != without[ key ] )
    assert differing == [ "arm_label", "deny_rules", "remove_paths" ]
    assert with_[ "deny_rules" ] == [] and with_[ "remove_paths" ] == []
    assert with_[ "model" ] == without[ "model" ] == "m"


def test_the_without_arm_denies_exactly_the_four_surfaces_and_removes_the_skill_folder():
    """The deny list is the four rules and nothing else; the skill folder is removed."""
    config = arms.build_session_config( arms.ARM_WITHOUT, "m" )
    assert config[ "deny_rules" ] == [ "mcp__cosa-voice__check_exists", "mcp__cosa-voice__fetch_similar", "mcp__cosa-voice__read_capability",
                                        "Skill(reuse-reviewer)" ]
    assert config[ "remove_paths" ] == [ ".claude/skills/reuse-reviewer" ]


def test_configs_do_not_share_state_with_the_base_or_each_other():
    """Editing one built config leaves the base and the next config alone."""
    first = arms.build_session_config( arms.ARM_WITH, "m" )
    first[ "setting_sources" ].append( "user" )
    first[ "deny_rules" ].append( "x" )
    assert arms.BASE_CONFIG[ "setting_sources" ] == [ "project", "local" ]
    assert arms.build_session_config( arms.ARM_WITH, "m" )[ "deny_rules" ] == []


def test_arm_labels_are_the_two_strings_of_the_frozen_scrub_list():
    """The harness writes the strings the frozen configuration scrubs, so the census covers them."""
    assert arms.ARM_LABELS == { "with" : "arm-label-with-9c41e7", "without" : "arm-label-without-9c41e7" }
    assert tuple( arms.ARM_LABELS.values() ) == frozen.ARM_LABELS


def test_build_session_config_refuses_an_unknown_arm_and_an_empty_model():
    """The two bad inputs have their own codes."""
    with pytest.raises( err.HarnessError ) as bad_arm:
        arms.build_session_config( "both", "m" )
    with pytest.raises( err.HarnessError ) as bad_model:
        arms.build_session_config( arms.ARM_WITH, "" )
    assert ( bad_arm.value.code, bad_model.value.code ) == ( err.BAD_ARM, err.BAD_SPEC )


# ── names ───────────────────────────────────────────────────────────────────────────────────

def test_db_name_is_a_postgres_identifier_stable_per_run_and_distinct_across_runs():
    """Lowercase, under 63 characters, the same for one id and different for two."""
    name = harness.db_name( "pair01-a" )
    assert re.fullmatch( r"[a-z0-9_]{1,62}", name ) and name == harness.db_name( "pair01-a" ) and name != harness.db_name( "pair01-b" )
    assert name == "rrun_" + harness.db_name( "pair01-a" )[ 5: ]


def test_container_name_carries_the_database_hash():
    """The container and the database of one run share the hash and no other run's."""
    assert harness.container_name( "pair01-a" ).endswith( harness.db_name( "pair01-a" )[ 5: ] )
    assert harness.container_name( "pair01-a" ) != harness.container_name( "pair01-b" )


# ── the spec ────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize( "key", harness.SPEC_KEYS )
def test_a_spec_missing_any_key_is_refused_naming_it( key ):
    """Every key of SPEC_KEYS is required."""
    bad = spec()
    del bad[ key ]
    with pytest.raises( err.HarnessError ) as raised:
        harness.check_spec( bad )
    assert raised.value.code == err.BAD_SPEC and key in raised.value.detail


@pytest.mark.parametrize( "key", [ "run_id", "model_id", "server_commit" ] )
def test_an_empty_text_field_is_refused( key ):
    """An empty run id, model id or commit cannot start a run."""
    with pytest.raises( err.HarnessError ) as raised:
        harness.check_spec( spec( **{ key : "" } ) )
    assert raised.value.code == err.BAD_SPEC and key in raised.value.detail


@pytest.mark.parametrize( "over,code", [
    ( { "arm" : "both" },               err.BAD_ARM ),
    ( { "cap_seat_hours" : 0 },         err.BAD_SPEC ),
    ( { "cap_seat_hours" : -1 },        err.BAD_SPEC ),
    ( { "test_ids" : [] },              err.BAD_SPEC ),
    ( { "test_ids" : [ "a", "a" ] },    err.BAD_SPEC ),
] )
def test_an_unusable_spec_is_refused_with_its_code( over, code ):
    """The arm, the cap and the test list each have a refusal."""
    with pytest.raises( err.HarnessError ) as raised:
        harness.check_spec( spec( **over ) )
    assert raised.value.code == code


def test_a_valid_spec_passes():
    """check_spec returns None for a valid spec."""
    assert harness.check_spec( spec() ) is None


# ── the stop condition, with a stub client that passes one test at a time ──────────────────

def test_a_client_that_passes_one_test_per_slice_stops_at_all_pass_with_the_hours_it_used():
    """Four tests, one per slice, one hour each: all_pass at four hours."""
    ports  = Ports()
    result = harness.run_one( spec(), ports )
    assert result == { "run" : "pair01-a", "passing_tests" : 4, "pass_rate" : 1.0, "client_builds" : True, "stop" : "all_pass", "seat_hours" : 4.0 }
    assert ports.session.slices == 4


def test_a_stub_that_passes_exactly_one_test_stops_at_the_cap_with_one_passing():
    """A stub client that passes one test never reaches all_pass, so the cap ends it."""
    ports  = Ports( session=StubSession( per_slice=0 ) )
    ports.session.progress = 1
    result = harness.run_one( spec( cap_seat_hours=3 ), ports )
    assert ( result[ "passing_tests" ], result[ "pass_rate" ], result[ "stop" ], result[ "seat_hours" ] ) == ( 1, 0.25, "cap", 3.0 )
    assert ports.session.slices == 3


def test_the_cap_is_the_seat_hours_remaining_that_each_slice_is_given():
    """Each slice is told the hours left under the cap: 10, 7, 4, 1."""
    ports = Ports( session=StubSession( per_slice=0, hours=3.0 ) )
    harness.run_one( spec( cap_seat_hours=10 ), ports )
    assert ports.session.budgets == [ 10, 7.0, 4.0, 1.0 ]


def test_all_pass_wins_over_the_cap_when_both_happen_at_the_same_verdict():
    """A run that passes everything on the slice that reaches the cap is all_pass."""
    ports  = Ports( session=StubSession( per_slice=4, hours=5.0 ) )
    result = harness.run_one( spec( cap_seat_hours=5 ), ports )
    assert ( result[ "stop" ], result[ "passing_tests" ] ) == ( "all_pass", 4 )


def test_a_session_that_finishes_short_of_all_pass_and_under_the_cap_stops_session_ended():
    """The agent says it is done at slice 2 with 2 of 4 passing and 2 of 10 hours used."""
    ports  = Ports( session=StubSession( per_slice=1, finish_after=2 ) )
    result = harness.run_one( spec(), ports )
    assert ( result[ "stop" ], result[ "passing_tests" ], result[ "seat_hours" ] ) == ( "session_ended", 2, 2.0 )


def test_a_slice_with_no_hours_that_is_not_finished_is_a_stalled_run():
    """Zero seat hours and not finished would loop forever; it is NO_PROGRESS."""
    with pytest.raises( err.HarnessError ) as raised:
        harness.run_one( spec(), Ports( session=StubSession( hours=0.0 ) ) )
    assert raised.value.code == err.NO_PROGRESS


def test_a_slice_with_no_hours_that_finished_is_not_a_stall():
    """A finished slice may cost nothing: the run still gets its verdict and stops session_ended."""
    result = harness.run_one( spec(), Ports( session=StubSession( hours=0.0, finish_after=1 ) ) )
    assert ( result[ "stop" ], result[ "seat_hours" ] ) == ( "session_ended", 0.0 )


def test_results_that_do_not_name_the_runs_tests_are_refused():
    """A test port that reports other ids than the run's test list cannot give a verdict."""
    ports = Ports()
    ports.tests.run = lambda handle, path, test_ids: { "results" : { "other" : True }, "client_builds" : True }
    with pytest.raises( err.HarnessError ) as raised:
        harness.run_one( spec(), ports )
    assert raised.value.code == err.BAD_SPEC and "pair01-a" in raised.value.detail


def test_client_builds_false_is_carried_to_the_result():
    """The scorer reads client_builds; a failing build is reported as False."""
    ports = Ports()
    ports.tests.builds = False
    assert harness.run_one( spec(), ports )[ "client_builds" ] is False


# ── the log ─────────────────────────────────────────────────────────────────────────────────

def test_one_verdict_record_per_slice_and_one_stop_record_each_with_the_model_server_and_hours():
    """Section 7.3: seat-hours, the model id and the server per verdict."""
    ports = Ports()
    harness.run_one( spec( arm=arms.ARM_WITHOUT ), ports )
    verdicts = [ record for record in ports.log.records if record[ "event" ] == "verdict" ]
    assert [ record[ "seat_hours" ] for record in verdicts ] == [ 1.0, 2.0, 3.0, 4.0 ]
    assert [ record[ "passing_tests" ] for record in verdicts ] == [ 1, 2, 3, 4 ]
    assert all( record[ "model_id" ] == "claude-opus-5-5" and record[ "server_commit" ] == "abc1234" and record[ "arm_label" ] == "arm-label-without-9c41e7" and record[ "total_tests" ] == 4
                for record in verdicts )
    assert ports.log.records[ -1 ] == { "event" : "stop", "run" : "pair01-a", "arm_label" : "arm-label-without-9c41e7", "stop" : "all_pass", "seat_hours" : 4.0 }
    assert len( ports.log.records ) == 5


def test_the_arm_label_in_the_log_is_the_arms_and_never_the_word_with_or_without():
    """The log carries the scrub-safe label for the arm that ran."""
    ports = Ports()
    harness.run_one( spec( arm=arms.ARM_WITH ), ports )
    assert {  record[ "arm_label" ] for record in ports.log.records } == { "arm-label-with-9c41e7" }


# ── the per-run database and the worktree ───────────────────────────────────────────────────

def test_two_runs_each_get_their_own_database_and_the_first_runs_rows_do_not_reach_the_second():
    """Run A writes rows; run B starts on a database with none, and A's is dropped by then."""
    ports = Ports()
    harness.run_one( spec( run_id="pair01-a" ), ports )
    assert ports.server.dbs == {}
    harness.run_one( spec( run_id="pair01-b", arm=arms.ARM_WITHOUT ), ports )
    starts = [ name for event, name in ports.server.history if event == "start" ]
    assert starts == [ harness.db_name( "pair01-a" ), harness.db_name( "pair01-b" ) ] and ports.server.dbs == {}


def test_the_database_is_dropped_when_the_run_fails_after_it_started():
    """A failure in the loop still stops the server and drops the database."""
    ports = Ports( session=StubSession( hours=0.0 ) )
    with pytest.raises( err.HarnessError ):
        harness.run_one( spec(), ports )
    assert ports.server.dbs == {} and ports.server.history[ -1 ] == ( "stop", harness.db_name( "pair01-a" ) )


def test_a_database_that_already_holds_rows_is_refused_before_any_work():
    """A reused database is DB_NOT_FRESH, no slice runs and the database is dropped."""
    ports = Ports( server=StubServer( preload=[ "old" ] ) )
    with pytest.raises( err.HarnessError ) as raised:
        harness.run_one( spec(), ports )
    assert raised.value.code == err.DB_NOT_FRESH and ports.session.slices == 0 and ports.server.dbs == {}


def test_a_server_that_hands_back_another_runs_database_is_refused():
    """The names must be the ones derived from this run's id."""
    ports = Ports( server=StubServer( wrong_name=True ) )
    with pytest.raises( err.HarnessError ) as raised:
        harness.run_one( spec(), ports )
    assert raised.value.code == err.DB_NOT_OWN and ports.session.slices == 0


def test_a_container_name_from_another_run_is_refused_even_when_the_database_matches():
    """Both names are checked, so a matching database with a foreign container fails."""
    ports = Ports()
    original = ports.server.start
    ports.server.start = lambda run_id, path: dict( original( run_id, path ), container="rrun-server-deadbeef" )
    with pytest.raises( err.HarnessError ) as raised:
        harness.run_one( spec(), ports )
    assert raised.value.code == err.DB_NOT_OWN


def test_a_client_folder_that_is_not_empty_stops_the_run_before_a_server_starts():
    """The client is built from zero; leftovers are CLIENT_NOT_EMPTY and no server was started."""
    ports = Ports( worktree=StubWorktree( client=[ "src/client/index.ts" ] ) )
    with pytest.raises( err.HarnessError ) as raised:
        harness.run_one( spec(), ports )
    assert raised.value.code == err.CLIENT_NOT_EMPTY and "index.ts" in raised.value.detail and ports.server.history == []


def test_the_without_worktree_has_no_skill_folder_and_the_with_worktree_keeps_it():
    """The skill folder is gone in the without arm and kept in the with arm."""
    without, with_ = Ports(), Ports()
    harness.run_one( spec( arm=arms.ARM_WITHOUT ), without )
    harness.run_one( spec( arm=arms.ARM_WITH ), with_ )
    assert without.worktree.made[ "/wt/pair01-a" ][ "files" ] == { "CLAUDE.md" }
    assert with_.worktree.made[ "/wt/pair01-a" ][ "files" ] == { "CLAUDE.md", arms.SKILL_PATH }


def test_a_skill_folder_left_in_the_without_worktree_is_refused():
    """A worktree that keeps the skill folder is SURFACE_REACHABLE before any server."""
    ports = Ports( worktree=StubWorktree( keep_paths=True ) )
    with pytest.raises( err.HarnessError ) as raised:
        harness.run_one( spec( arm=arms.ARM_WITHOUT ), ports )
    assert raised.value.code == err.SURFACE_REACHABLE and ports.server.history == []


def test_a_with_worktree_that_lacks_the_skill_folder_is_refused():
    """The arm with the tools needs the skill folder; a worktree without it is SURFACE_MISSING."""
    ports = Ports( worktree=StubWorktree() )
    ports.worktree.create = lambda run_id, commit, remove_paths: ports.worktree.made.setdefault( "/wt/x", { "commit" : commit, "files" : {"CLAUDE.md"} } ) and "/wt/x"
    with pytest.raises( err.HarnessError ) as raised:
        harness.run_one( spec( arm=arms.ARM_WITH ), ports )
    assert raised.value.code == err.SURFACE_MISSING


def test_the_worktree_is_made_at_the_frozen_commit():
    """The server commit of the spec is the one the worktree is made from."""
    ports = Ports()
    harness.run_one( spec( server_commit="frozen99" ), ports )
    assert ports.worktree.made[ "/wt/pair01-a" ][ "commit" ] == "frozen99"


# ── the arm switch inside a run ─────────────────────────────────────────────────────────────

def test_a_leaky_session_stops_the_run_before_any_work_and_drops_the_database():
    """The arm is proven before the first slice: a leaky without-arm session never does work."""
    ports = Ports( session=StubSession( leaky=True ) )
    with pytest.raises( err.HarnessError ) as raised:
        harness.run_one( spec( arm=arms.ARM_WITHOUT ), ports )
    assert raised.value.code == err.SURFACE_REACHABLE and ports.session.slices == 0 and ports.server.dbs == {}


def test_the_session_is_given_the_arms_config_for_the_work():
    """The slices run under the arm's config: work() received the deny rules."""
    ports = Ports()
    seen  = []
    original = ports.session.work
    ports.session.work = lambda config, path, handle, remaining: ( seen.append( config ), original( config, path, handle, remaining ) )[ 1 ]
    harness.run_one( spec( arm=arms.ARM_WITHOUT ), ports )
    assert seen and all( config[ "deny_rules" ] and config[ "model" ] == "claude-opus-5-5" for config in seen )
