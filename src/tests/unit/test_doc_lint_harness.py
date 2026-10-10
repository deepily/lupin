"""
The harness runner, its ledger, its exit-gate figures and its off-peak scheduling.

One fake model plays both the extractor and the judge and answers from the text it is handed:
the extractor quotes the lines of the old text, the judge calls a claim present when its words
occur in the new text or the design doc. So a pair whose new text drops a line is flagged, and a
pair whose new text keeps every line is not, whatever the code under test does.
"""

import asyncio
import datetime
import json
import re
from zoneinfo import ZoneInfo

import pytest
from claude_agent_sdk import AssistantMessage, TextBlock

from cosa.repo.doc_lint import claim_extractor as ce
from cosa.repo.doc_lint import claim_judge as cj
from cosa.repo.doc_lint import harness_report as hr
from cosa.repo.doc_lint import harness_runner as hn
from cosa.repo.doc_lint import harness_schedule as hs
from cosa.repo.doc_lint import model_transport as mt

L1  = "Returns None when the row is parked."
L2  = "Raises ValueError if the id is blank."
L3  = "The window is ten minutes long."
L4  = "It maybe retries once more."
OLD = "\n".join( [ L1, L2, L3 ] )

CONFIG = hn.HarnessConfig( "ext-m", "judge-m", "esc-m", "writer-m" )


def tagged( prompt, tag ):
    match = re.search( rf"<{tag}_(\w+)>\n(.*?)\n</{tag}_\1>", prompt, re.DOTALL )
    return match.group( 2 ) if match else ""


class FakeModel:
    """Extractor and judge in one; records every call so a test can count them."""

    def __init__( self, skip=(), invent=False, flip_call=None, die_after=None ):
        self.skip       = skip
        self.invent     = invent
        self.flip_call  = flip_call
        self.die_after  = die_after
        self.calls      = []
        self.judge_seen = 0

    async def __call__( self, prompt, options ):
        if self.die_after is not None and len( self.calls ) >= self.die_after:
            raise RuntimeError( "killed" )
        if options.system_prompt == ce.SYSTEM_PROMPT:
            self.calls.append( ( "extract", options.model ) )
            lines  = [ l for l in tagged( prompt, "old_text" ).splitlines() if l not in self.skip ]
            claims = [ { "claim": l, "quote": l } for l in lines ]
            if self.invent: claims.append( { "claim": "made up", "quote": "A sentence that is not in the text." } )
            text = json.dumps( { "claims": claims } )
        else:
            self.calls.append( ( "judge", options.model ) )
            self.judge_seen += 1
            haystack = tagged( prompt, "new_text" ) + "\n" + tagged( prompt, "design_doc" )
            texts    = [ l.split( ". ", 1 )[ 1 ] for l in tagged( prompt, "claims" ).splitlines() ]
            verdicts = []
            for n, claim in enumerate( texts, start=1 ):
                if "maybe" in claim and options.model == "judge-m": v = "uncertain"
                else: v = "present" if all( w in haystack.lower() for w in re.findall( r"[a-z]+", claim.replace( "maybe", "" ).lower() ) ) else "absent"
                if self.flip_call == self.judge_seen and n == 1: v = "absent" if v == "present" else "present"
                verdicts.append( { "id": n, "verdict": v } )
            text = json.dumps( { "verdicts": verdicts } )
        yield AssistantMessage( content=[ TextBlock( text ) ], model=options.model )


def span_of( line ):
    return list( ce.locate_quote( line, OLD ) )


def pair( pid, new, seeded=None, design=None, old=OLD ):
    return { "id": pid, "old": old, "new": new, "design": design, "seed_span": span_of( seeded ) if seeded else None }


def run( pairs, ledger, model, config=CONFIG ):
    return asyncio.run( hn.run_all( pairs, config, ledger, query_fn=model ) )


# ---- configuration ---------------------------------------------------------------------------

def test_check_models_accepts_a_judge_that_is_not_the_writer_and_an_extractor_that_is():
    assert hn.check_models( CONFIG ) is None
    assert hn.check_models( CONFIG._replace( extractor_model="writer-m" ) ) is None


@pytest.mark.parametrize( "field", [ "extractor_model", "judge_model", "escalation_model", "writer_model" ] )
def test_check_models_requires_every_id( field ):
    with pytest.raises( ValueError, match=f"{field} is required" ):
        hn.check_models( CONFIG._replace( **{ field: "" } ) )


@pytest.mark.parametrize( "field", [ "judge_model", "escalation_model" ] )
def test_check_models_refuses_a_judge_that_is_the_writer( field ):
    with pytest.raises( ValueError, match="must not grade its own rewrite" ):
        hn.check_models( CONFIG._replace( **{ field: "writer-m" } ) )


def test_run_pair_refuses_a_self_grading_config_before_any_call(tmp_path):
    model = FakeModel()
    with pytest.raises( ValueError ):
        run( [ pair( "p", OLD ) ], hn.Ledger( str( tmp_path / "l" ) ), model, CONFIG._replace( judge_model="writer-m" ) )
    assert model.calls == []


# ---- ledger ----------------------------------------------------------------------------------

def test_ledger_key_changes_with_each_of_its_parts():
    base  = pair( "p", "new text", design="doc" )
    key   = hn.ledger_key( "judge", base, "v1", "m", 0 )
    other = [
        hn.ledger_key( "judge", dict( base, old="different old" ), "v1", "m", 0 ),
        hn.ledger_key( "judge", dict( base, new="different new" ), "v1", "m", 0 ),
        hn.ledger_key( "judge", dict( base, design="other doc" ), "v1", "m", 0 ),
        hn.ledger_key( "judge", base, "v2", "m", 0 ),
        hn.ledger_key( "judge", base, "v1", "other-m", 0 ),
        hn.ledger_key( "judge", base, "v1", "m", 1 ),
        hn.ledger_key( "extract", base, "v1", "m", 0 ),
    ]
    assert len( set( other + [ key ] ) ) == 8
    assert hn.ledger_key( "judge", { "old": "o", "new": "n" }, "v1", "m", 0 ) == hn.ledger_key( "judge", { "old": "o", "new": "n", "design": None }, "v1", "m", 0 )


def test_ledger_persists_and_survives_a_torn_last_line(tmp_path):
    path = str( tmp_path / "ledger.jsonl" )
    first = hn.Ledger( path )
    assert first.get( "k" ) is None
    first.put( "k", { "a": 1 } )
    first.put( "k2", [ 1, 2 ] )
    with open( path, "a" ) as f: f.write( '{"key": "k3", "val' )
    second = hn.Ledger( path )
    assert second.get( "k" ) == { "a": 1 } and second.get( "k2" ) == [ 1, 2 ] and second.get( "k3" ) is None


# ---- run, kill, resume -----------------------------------------------------------------------

def test_a_pair_costs_two_extractions_and_six_judge_runs_and_a_second_pass_costs_nothing(tmp_path):
    path   = str( tmp_path / "l" )
    first  = FakeModel()
    result = run( [ pair( "p", L1 + "\n" + L3, seeded=L2 ) ], hn.Ledger( path ), first )
    assert [ k for k, _ in first.calls ].count( "extract" ) == 2 and [ k for k, _ in first.calls ].count( "judge" ) == 6
    again = FakeModel()
    assert run( [ pair( "p", L1 + "\n" + L3, seeded=L2 ) ], hn.Ledger( path ), again ) == result
    assert again.calls == []


def test_a_killed_run_resumes_without_repeating_a_finished_call(tmp_path):
    path = str( tmp_path / "l" )
    dies = FakeModel( die_after=5 )
    with pytest.raises( mt.ModelCallError ):
        run( [ pair( "p", L1 + "\n" + L3, seeded=L2 ) ], hn.Ledger( path ), dies )
    finished = len( hn.Ledger( path ).entries )
    assert finished == 5
    resumed = FakeModel()
    run( [ pair( "p", L1 + "\n" + L3, seeded=L2 ) ], hn.Ledger( path ), resumed )
    assert len( resumed.calls ) == 8 - finished
    assert len( hn.Ledger( path ).entries ) == 8


def test_a_changed_judge_prompt_version_does_not_resume_stale_verdicts(tmp_path, monkeypatch):
    path = str( tmp_path / "l" )
    run( [ pair( "p", OLD ) ], hn.Ledger( path ), FakeModel() )
    monkeypatch.setattr( cj, "PROMPT_VERSION", "judge-v2" )
    rerun = FakeModel()
    run( [ pair( "p", OLD ) ], hn.Ledger( path ), rerun )
    assert [ k for k, _ in rerun.calls ].count( "extract" ) == 0 and [ k for k, _ in rerun.calls ].count( "judge" ) == 6


# ---- the exit-gate figures -------------------------------------------------------------------

def report_for( pairs, model=None, tmp_path=None ):
    model = FakeModel() if model is None else model
    return hr.build_report( run( pairs, hn.Ledger( str( tmp_path / "l" ) ), model ), CONFIG )


def test_a_removed_claim_is_caught_and_an_untouched_pair_raises_no_alarm(tmp_path):
    report = report_for( [ pair( "seeded", L1 + "\n" + L3, seeded=L2 ), pair( "same", OLD ) ], tmp_path=tmp_path )
    assert [ ( l[ "positives" ], l[ "misses" ], l[ "false_alarms" ], l[ "unseeded" ] ) for l in report[ "lists" ] ] == [ ( 1, 0, 0, 1 ), ( 1, 0, 0, 1 ) ]
    assert report[ "default_gate_pass" ] is False


def test_a_flag_on_some_other_claim_does_not_count_as_catching_the_seed(tmp_path):
    report = report_for( [ pair( "wrong", L1 + "\n" + L2, seeded=L2 ) ], tmp_path=tmp_path )
    assert [ l[ "misses" ] for l in report[ "lists" ] ] == [ 1, 1 ]


def test_a_removed_claim_the_extractor_never_listed_is_caught_only_by_the_flag_on_its_stretch(tmp_path, monkeypatch):
    monkeypatch.setattr( ce, "MIN_RUN_WORDS", 2 )  # the fixture lines are short; the shipped minimum is 11 words
    # Row ed2f9b4e: the stretch no kept quote covers is asked for once more and, still uncovered, flagged for a person.
    # Before the fix this pair was a plain miss; the flag is scored as a catch only because it overlaps the seeded span.
    report = report_for( [ pair( "unlisted", L1 + "\n" + L3, seeded=L2 ) ], model=FakeModel( skip=( L2, ) ), tmp_path=tmp_path )
    assert [ ( l[ "misses" ], l[ "caught_by_flag_only" ] ) for l in report[ "lists" ] ] == [ ( 0, 1 ), ( 0, 1 ) ]
    assert report[ "mean_uncovered" ] > 0.0 and report[ "reextract_calls" ] == 2


def test_an_edit_to_an_unseeded_pair_counts_as_a_false_alarm(tmp_path):
    report = report_for( [ pair( "edited", L1 + "\n" + L3 ), pair( "same", OLD ) ], tmp_path=tmp_path )
    assert [ ( l[ "false_alarms" ], l[ "false_alarm_rate" ] ) for l in report[ "lists" ] ] == [ ( 1, 0.5 ), ( 1, 0.5 ) ]


def test_a_claim_moved_into_the_design_doc_passes(tmp_path):
    report = report_for( [ pair( "moved", L1 + "\n" + L3, design=L2 ) ], tmp_path=tmp_path )
    assert report[ "lists" ][ 0 ][ "false_alarms" ] == 0


def test_agreement_is_counted_per_claim_over_all_claims_and_over_seeded_claims_alone(tmp_path):
    flip   = FakeModel( flip_call=2 )
    report = report_for( [ pair( "seeded", L2 + "\n" + L3, seeded=L1 ) ], model=flip, tmp_path=tmp_path )
    assert report[ "agreement_all" ][ "claims" ] == 6 and report[ "agreement_all" ][ "same" ] == 5
    assert report[ "agreement_seeded" ][ "claims" ] == 2 and report[ "agreement_seeded" ][ "same" ] == 1
    assert report[ "agreement_seeded" ][ "interval" ][ 0 ] < 0.5 < report[ "agreement_seeded" ][ "interval" ][ 1 ]
    assert report[ "lists" ][ 0 ][ "misses" ] == 1      # the dissenting run keeps the seeded claim; under the old majority rule this was 0


def test_escalations_discards_and_models_are_reported(tmp_path):
    report = report_for( [ pair( "p", OLD + "\n" + L4, old=OLD + "\n" + L4 ) ], model=FakeModel( invent=True ), tmp_path=tmp_path )
    assert report[ "escalations" ] == 6 and report[ "discarded_claims" ] == 2
    assert report[ "models" ] == { "extractor": "ext-m", "judge": "judge-m", "escalation": "esc-m", "writer": "writer-m" }
    assert report[ "prompt_versions" ] == { "extractor": ce.PROMPT_VERSION, "judge": cj.PROMPT_VERSION }


def test_a_report_with_no_pairs_has_no_figures():
    report = hr.build_report( [], CONFIG )
    assert report[ "agreement_all" ][ "rate" ] is None and report[ "agreement_all" ][ "interval" ] is None
    assert report[ "mean_uncovered" ] is None and report[ "default_gate_pass" ] is False
    assert [ l[ "false_alarm_rate" ] for l in report[ "lists" ] ] == [ None, None ]


def synthetic( n, missed=0, unseeded=0, alarmed=0, flip_second_list_misses=False ):
    """n seeded pairs (the first `missed` flag nothing), then `unseeded` pairs (the first `alarmed` flag a claim)."""
    row  = lambda verdict: { "verdict": verdict, "escalated": False }
    flag = { "claims": [ { "start": 0, "end": 10, "text": "q", "quote": "q" } ], "discarded": 0, "discards": [], "flags": [], "flag_words": [], "reextract_calls": 0, "parse_failed": False, "retry_calls": 0, "uncovered": 0.0, "longest_quote": 0.25, "runs": [ [ row( "absent" ) ] ] * 3 }
    calm = dict( flag, runs=[ [ row( "present" ) ] ] * 3 )
    out  = []
    for i in range( n ):
        second = calm if flip_second_list_misses and i == 0 else ( calm if i < missed else flag )
        out.append( { "id": i, "seed_span": [ 2, 5 ], "lists": [ dict( calm if i < missed else flag ), dict( second ) ] } )
    for i in range( unseeded ):
        pick = flag if i < alarmed else calm
        out.append( { "id": f"u{i}", "seed_span": None, "lists": [ dict( pick ), dict( pick ) ] } )
    return out


@pytest.mark.parametrize( "n, missed, passes", [ ( 60, 0, True ), ( 59, 0, False ), ( 60, 1, False ) ] )
def test_the_default_gate_needs_sixty_positives_and_no_misses( n, missed, passes ):
    report = hr.build_report( synthetic( n, missed, unseeded=20 ), CONFIG )
    assert report[ "miss_criterion_met" ] is passes and report[ "default_gate_pass" ] is passes
    assert report[ "lists" ][ 0 ][ "misses" ] == missed


@pytest.mark.parametrize( "misses, trials, expected", [
    ( 0, 20, 0.1391 ), ( 0, 33, 0.0868 ), ( 0, 60, 0.0487 ), ( 1, 60, 0.0766 ), ( 1, 94, 0.0499 ), ( 5, 5, 1.0 ), ( 0, 0, None ),
] )
def test_upper_bound_matches_the_recomputed_one_sided_figures( misses, trials, expected ):
    got = hr.upper_bound( misses, trials )
    assert got == expected if expected in ( None, 1.0 ) else got == pytest.approx( expected, abs=5e-4 )


def test_interval_edges_and_middle():
    assert hr.interval( 0, 0 ) is None
    assert hr.interval( 0, 10 )[ 0 ] == 0.0 and hr.interval( 10, 10 )[ 1 ] == 1.0
    low, high = hr.interval( 57, 60 )
    assert low < 0.95 < high


# ---- scheduling and submission ---------------------------------------------------------------

def at( hour, day=1 ):
    return datetime.datetime( 2026, 10, day, hour, 30, tzinfo=ZoneInfo( "America/New_York" ) )


@pytest.mark.parametrize( "now, expected", [
    ( at( 11 ), "2026-10-01T11:30:00-04:00" ),
    ( at( 9 ), "2026-10-01T10:00:00-04:00" ),
    ( at( 13 ), "2026-10-02T10:00:00-04:00" ),
    ( at( 23 ), "2026-10-02T10:00:00-04:00" ),
    ( at( 2 ), "2026-10-01T10:00:00-04:00" ),
] )
def test_scheduled_at_lands_in_the_ten_to_one_window( now, expected ):
    assert hs.scheduled_at( now ) == expected


def test_scheduled_at_converts_other_zones_and_defaults_to_now():
    utc_noon_eastern = datetime.datetime( 2026, 10, 1, 16, 0, tzinfo=datetime.timezone.utc )
    assert hs.scheduled_at( utc_noon_eastern ).startswith( "2026-10-01T12:00:00" )
    assert datetime.datetime.fromisoformat( hs.scheduled_at() ).hour in ( 10, 11, 12 )


def test_the_submit_payload_is_a_bounded_job_with_a_top_level_schedule():
    payload = hs.build_submit_payload( [ "python", "-m", "cosa.repo.doc_lint.x", "--go" ], "2026-10-02T10:00:00-04:00" )
    assert payload[ "command" ] == "agent router go to claude code"
    assert payload[ "args" ][ "task_type" ] == "BOUNDED" and "python -m cosa.repo.doc_lint.x --go" in payload[ "args" ][ "prompt" ]
    assert payload[ "scheduled_at" ] == "2026-10-02T10:00:00-04:00" and "scheduled_at" not in payload[ "args" ]


class Reply:
    def __init__( self, code, body=None ):
        self.status_code, self._body, self.text = code, body, "refused"
    def json( self ):
        return self._body


def fake_post( login=200, submit=200, seen=None ):
    def post( url, json=None, headers=None, timeout=None ):
        if seen is not None: seen.append( ( url, headers ) )
        if url.endswith( "/auth/login" ): return Reply( login, { "tokens": { "access_token": "tok" } } )
        return Reply( submit, { "job_id": "j1" } )
    return post


def test_submit_logs_in_then_posts_with_the_bearer_token():
    seen = []
    assert hs.submit( { "x": 1 }, "http://h", "e", "p", post=fake_post( seen=seen ) ) == { "job_id": "j1" }
    assert seen == [ ( "http://h/auth/login", None ), ( "http://h/api/v2/submit", { "Authorization": "Bearer tok" } ) ]


def test_submit_raises_on_a_refused_login_or_submit():
    with pytest.raises( RuntimeError, match="login to http://h answered 401" ):
        hs.submit( {}, "http://h", "e", "p", post=fake_post( login=401 ) )
    with pytest.raises( RuntimeError, match="submit answered 410" ):
        hs.submit( {}, "http://h", "e", "p", post=fake_post( submit=410 ) )


def test_submit_defaults_to_requests_post( monkeypatch ):
    monkeypatch.setattr( hs.requests, "post", fake_post() )
    assert hs.submit( {}, "http://h", "e", "p" ) == { "job_id": "j1" }


# ---- command line ----------------------------------------------------------------------------

def cli_args( tmp_path, **override ):
    names = { "extractor-model": "ext-m", "judge-model": "judge-m", "escalation-model": "esc-m", "writer-model": "writer-m" }
    names.update( override )
    argv  = [ "--pairs", str( tmp_path / "pairs.json" ), "--ledger", str( tmp_path / "l" ), "--out", str( tmp_path / "out.json" ) ]
    for k, v in names.items(): argv += [ f"--{k}", v ]
    return argv


def test_the_command_line_runs_pairs_and_writes_the_report(tmp_path, capsys):
    from cosa.repo.doc_lint import harness_cli as cli
    ( tmp_path / "pairs.json" ).write_text( json.dumps( [ pair( "seeded", L1 + "\n" + L3, seeded=L2 ) ] ) )
    assert cli.main( cli_args( tmp_path ), query_fn=FakeModel() ) == 0
    written = json.loads( ( tmp_path / "out.json" ).read_text() )
    assert written[ "lists" ][ 0 ][ "positives" ] == 1 and written[ "lists" ][ 0 ][ "misses" ] == 0
    assert "default_gate_pass=False" in capsys.readouterr().out


def test_the_command_line_refuses_a_judge_that_is_the_writer(tmp_path, capsys):
    from cosa.repo.doc_lint import harness_cli as cli
    assert cli.main( cli_args( tmp_path, **{ "judge-model": "writer-m" } ), query_fn=FakeModel() ) == 2
    assert "REFUSED" in capsys.readouterr().err and not ( tmp_path / "out.json" ).exists()


def test_the_command_line_has_no_default_model(tmp_path):
    from cosa.repo.doc_lint import harness_cli as cli
    with pytest.raises( SystemExit ):
        cli.parse_args( [ "--pairs", "a", "--ledger", "b", "--out", "c" ] )


def test_the_report_carries_the_longest_verified_quote():
    assert hr.build_report( synthetic( 2 ), CONFIG )[ "longest_quote" ] == 0.25
    assert hr.build_report( [], CONFIG )[ "longest_quote" ] == 0.0


# ---- review findings: ledger key, gate, torn line, alias, identical lists, shell quoting, frozen versions ----

def test_the_judge_ledger_key_follows_the_claim_list_so_an_extractor_change_reruns_the_judge(tmp_path, monkeypatch):
    path = str( tmp_path / "l" )
    run( [ pair( "p", L1 + "\n" + L3 ) ], hn.Ledger( path ), FakeModel() )
    monkeypatch.setattr( ce, "PROMPT_VERSION", "extractor-changed" )
    rerun = FakeModel( skip=( L1, ) )  # the changed extractor now lists two claims, not three
    result = run( [ pair( "p", L1 + "\n" + L3 ) ], hn.Ledger( path ), rerun )
    # the stretch the changed extractor leaves uncovered is under the 11-word flag minimum, so no re-extraction (ed2f9b4e)
    assert [ k for k, _ in rerun.calls ].count( "extract" ) == 2 and [ k for k, _ in rerun.calls ].count( "judge" ) == 6
    assert all( len( lst[ "claims" ] ) == len( lst[ "runs" ][ 0 ] ) == 2 for lst in result[ 0 ][ "lists" ] )


def test_flagging_everything_does_not_pass_the_default_gate():
    report = hr.build_report( synthetic( 60, unseeded=100, alarmed=100 ), CONFIG )
    assert report[ "miss_criterion_met" ] is True and report[ "false_alarm_ok" ] is False and report[ "default_gate_pass" ] is False
    assert report[ "lists" ][ 0 ][ "false_alarm_rate" ] == 1.0


def test_the_false_alarm_ceiling_is_ten_percent_inclusive():
    assert hr.build_report( synthetic( 60, unseeded=100, alarmed=10 ), CONFIG )[ "false_alarm_ok" ] is True
    assert hr.build_report( synthetic( 60, unseeded=100, alarmed=11 ), CONFIG )[ "false_alarm_ok" ] is False
    assert hr.build_report( synthetic( 60 ), CONFIG )[ "false_alarm_ok" ] is False


def test_the_miss_criterion_must_hold_on_every_extractor_list():
    report = hr.build_report( synthetic( 60, unseeded=20, flip_second_list_misses=True ), CONFIG )
    assert [ l[ "misses" ] for l in report[ "lists" ] ] == [ 0, 1 ]
    assert report[ "miss_criterion_met" ] is False and report[ "default_gate_pass" ] is False


def test_agreement_below_the_bar_blocks_the_default_gate():
    wobbly = synthetic( 60, unseeded=20 )
    for r in wobbly[ :4 ]:
        for lst in r[ "lists" ]:
            lst[ "runs" ] = [ lst[ "runs" ][ 0 ], [ { "verdict": "present", "escalated": False } ], lst[ "runs" ][ 2 ] ]
    report = hr.build_report( wobbly, CONFIG )
    assert report[ "agreement_seeded" ][ "rate" ] < 0.95 and report[ "agreement_ok" ] is False
    assert report[ "false_alarm_ok" ] is True and report[ "default_gate_pass" ] is False
    assert report[ "miss_criterion_met" ] is False      # a dissenting run keeps the seeded claim, so wobble now also costs misses; the old majority rule hid it
    assert hr.build_report( synthetic( 60, unseeded=20 ), CONFIG )[ "default_gate_pass" ] is True


def test_identical_extractor_lists_are_counted():
    report = hr.build_report( synthetic( 3, unseeded=2 ), CONFIG )
    assert report[ "identical_list_pairs" ] == 5 and report[ "pairs" ] == 5
    different = synthetic( 1 )
    different[ 0 ][ "lists" ][ 1 ] = dict( different[ 0 ][ "lists" ][ 1 ], claims=[ { "text": "other", "start": 0, "end": 10, "quote": "other" } ] )
    assert hr.build_report( different, CONFIG )[ "identical_list_pairs" ] == 0


def test_a_torn_ledger_line_does_not_swallow_the_next_record(tmp_path):
    path = str( tmp_path / "l" )
    ledger = hn.Ledger( path )
    ledger.put( "a", 1 )
    with open( path, "a" ) as f: f.write( '{"key": "b", "val' )
    hn.Ledger( path ).put( "c", 3 )
    reloaded = hn.Ledger( path )
    assert reloaded.get( "a" ) == 1 and reloaded.get( "c" ) == 3 and reloaded.get( "b" ) is None


def test_every_put_is_synced_to_disk(tmp_path, monkeypatch):
    synced = []
    monkeypatch.setattr( hn.os, "fsync", lambda fd: synced.append( fd ) )
    ledger = hn.Ledger( str( tmp_path / "l" ) )
    ledger.put( "a", 1 )
    ledger.put( "b", 2 )
    assert len( synced ) == 2


def test_a_writer_alias_that_differs_only_in_case_or_space_is_refused():
    with pytest.raises( ValueError, match="own rewrite" ):
        hn.check_models( CONFIG._replace( judge_model="  WRITER-M " ) )


def test_the_submit_prompt_keeps_every_argument_a_single_shell_word():
    payload = hs.build_submit_payload( [ "python", "--pairs", "my pairs; rm -rf x.json", "--out", "it's.json" ], "2026-10-02T10:00:00-04:00" )
    import shlex
    tail = payload[ "args" ][ "prompt" ].split( "last line: ", 1 )[ 1 ]
    assert shlex.split( tail ) == [ "python", "--pairs", "my pairs; rm -rf x.json", "--out", "it's.json" ]


def cli_gate_args( tmp_path, versions, pairs_sha="default" ):
    import hashlib
    sha = hashlib.sha256( ( tmp_path / "pairs.json" ).read_bytes() ).hexdigest() if pairs_sha == "default" else pairs_sha
    return cli_args( tmp_path ) + [ "--gate" ] + ( [ "--frozen-versions", versions ] if versions is not None else [] ) + ( [ "--frozen-pairs-sha", sha ] if sha is not None else [] )


def test_a_gate_run_needs_the_registered_prompt_versions_and_pairs_file(tmp_path, capsys):
    from cosa.repo.doc_lint import harness_cli as cli
    ( tmp_path / "pairs.json" ).write_text( json.dumps( [ pair( "seeded", L1 + "\n" + L3, seeded=L2 ) ] ) )
    good = f"{ce.PROMPT_VERSION},{cj.PROMPT_VERSION}"
    for versions, sha, message in ( ( None, "default", "--frozen-versions" ), ( "extractor-old,judge-old", "default", "--frozen-versions" ),
                                    ( good, None, "--frozen-pairs-sha" ), ( good, "0" * 64, "--frozen-pairs-sha" ) ):
        model = FakeModel()
        assert cli.main( cli_gate_args( tmp_path, versions, sha ), query_fn=model ) == 3
        assert model.calls == [] and f"REFUSED: gate run needs {message}" in capsys.readouterr().err
    assert cli.main( cli_gate_args( tmp_path, good ), query_fn=FakeModel() ) == 0


def test_the_report_names_the_sha_of_the_pairs_file(tmp_path):
    import hashlib
    from cosa.repo.doc_lint import harness_cli as cli
    body = json.dumps( [ pair( "seeded", L1 + "\n" + L3, seeded=L2 ) ] )
    ( tmp_path / "pairs.json" ).write_text( body )
    cli.main( cli_args( tmp_path ), query_fn=FakeModel() )
    assert json.loads( ( tmp_path / "out.json" ).read_text() )[ "pairs_sha" ] == hashlib.sha256( body.encode() ).hexdigest()


def test_seeded_claim_agreement_alone_can_block_the_gate_when_overall_agreement_is_fine():
    wobbly = synthetic( 60, unseeded=100 )
    for r in wobbly[ :5 ]:
        for lst in r[ "lists" ]:
            lst[ "runs" ] = [ lst[ "runs" ][ 0 ], [ { "verdict": "present", "escalated": False } ], lst[ "runs" ][ 2 ] ]
    report = hr.build_report( wobbly, CONFIG )
    assert report[ "agreement_all" ][ "rate" ] >= 0.95 > report[ "agreement_seeded" ][ "rate" ]
    assert report[ "agreement_ok" ] is False


def test_the_command_line_survives_an_unreadable_reply_keeps_it_and_prints_the_count(tmp_path, capsys):
    from cosa.repo.doc_lint import harness_cli as cli
    ( tmp_path / "pairs.json" ).write_text( json.dumps( [ pair( "seeded", L1 + "\n" + L3, seeded=L2 ) ] ) )
    async def junk( prompt, options ):
        yield AssistantMessage( content=[ TextBlock( "{\"claims\": []}\n{\"claims\": []}" ) ], model=options.model )
    raw = tmp_path / "raw.jsonl"
    assert cli.main( cli_args( tmp_path ) + [ "--raw-failures", str( raw ) ], query_fn=junk ) == 0
    written = json.loads( ( tmp_path / "out.json" ).read_text() )
    assert written[ "parse_failed_pairs" ] == 1 and written[ "retry_calls" ] == 2 and written[ "lists" ][ 0 ][ "misses" ] == 1
    rows = [ json.loads( l ) for l in raw.read_text().splitlines() ]
    assert len( rows ) == 4 and "Extra data" in rows[ 0 ][ "error" ] and rows[ 0 ][ "id" ] == "seeded"
    assert "parse_failed_pairs=1 retry_calls=2" in capsys.readouterr().out


# ---- judge thinking, parallel pairs and per-call timing (row: fast claim check) ---------------

class OptionsSpy( FakeModel ):
    """FakeModel that also keeps each call's thinking option, in call order, with a fixed pause so calls overlap."""

    def __init__( self, pause=0.0, **kwargs ):
        super().__init__( **kwargs )
        self.thinking = []
        self.pause    = pause
        self.live     = 0
        self.peak     = 0

    async def __call__( self, prompt, options ):
        self.thinking.append( ( options.model, options.thinking ) )
        self.live += 1
        self.peak  = max( self.peak, self.live )
        try:
            await asyncio.sleep( self.pause )
            async for message in super().__call__( prompt, options ): yield message
        finally:
            self.live -= 1


MAYBE = pair( "p", OLD + "\n" + L4, old=OLD + "\n" + L4 )        # L4 makes the first-pass judge answer uncertain, so the escalation model is asked


def thinking_of( spy, model ):
    return [ t for m, t in spy.thinking if m == model ]


async def one_call( model, **kwargs ):
    seen = []
    async def query( prompt, options ):
        seen.append( options )
        yield AssistantMessage( content=[ TextBlock( "ok" ) ], model="m" )
    await mt.complete( model, "sys", "user", query_fn=query, **kwargs )
    return seen[ 0 ]


def test_complete_sends_no_thinking_option_by_default_and_disables_it_on_request():
    assert asyncio.run( one_call( "m" ) ).thinking is None
    assert asyncio.run( one_call( "m", thinking="default" ) ).thinking is None
    assert asyncio.run( one_call( "m", thinking="off" ) ).thinking == { "type": "disabled" }


def test_complete_refuses_an_unknown_thinking_setting_before_any_call():
    with pytest.raises( ValueError, match="thinking must be one of" ):
        asyncio.run( one_call( "m", thinking="maybe" ) )


def test_record_calls_times_each_finished_call_by_the_stage_its_plan_names_and_repeats_the_last():
    async def three():
        with mt.record_calls( ( ( "judge", "off" ), ( "escalation", "default" ) ) ) as calls:
            first  = await one_call( "m" )
            second = await one_call( "m" )
            third  = await one_call( "m" )
        return calls, first, second, third
    calls, first, second, third = asyncio.run( three() )
    assert [ s for s, _ in calls ] == [ "judge", "escalation", "escalation" ] and all( t >= 0 for _, t in calls )
    assert first.thinking == { "type": "disabled" } and second.thinking is None and third.thinking is None


def test_a_call_that_names_its_own_thinking_keeps_it_inside_a_record_calls_block():
    async def go():
        with mt.record_calls( ( ( "judge", "off" ), ) ): return await one_call( "m", thinking="default" ), None
    assert asyncio.run( go() )[ 0 ].thinking == { "type": "disabled" }


def test_a_failed_call_is_not_recorded_and_the_block_restores_the_outer_scope():
    async def bad( prompt, options ):
        raise RuntimeError( "boom" )
        yield
    async def go():
        with mt.record_calls() as outer:
            with mt.record_calls() as inner:
                with pytest.raises( mt.ModelCallError ): await mt.complete( "m", "s", "u", query_fn=bad )
            await one_call( "m" )
        return outer, inner
    outer, inner = asyncio.run( go() )
    assert inner == [] and [ s for s, _ in outer ] == [ "call" ]


def test_a_call_outside_any_block_records_nothing_and_default_plan_is_one_call_stage():
    asyncio.run( one_call( "m" ) )
    assert mt._SCOPE.get() is None


def test_check_models_refuses_an_unknown_judge_thinking():
    with pytest.raises( ValueError, match="judge_thinking must be one of" ):
        hn.check_models( CONFIG._replace( judge_thinking="maybe" ) )


def test_thinking_off_reaches_the_first_pass_judge_only_never_the_extractor_or_escalation(tmp_path):
    spy = OptionsSpy()
    run( [ MAYBE ], hn.Ledger( str( tmp_path / "l" ) ), spy, CONFIG._replace( extractor_lists=1, judge_runs=1, judge_thinking="off" ) )
    assert thinking_of( spy, "ext-m" ) == [ None ]
    assert thinking_of( spy, "judge-m" ) == [ { "type": "disabled" } ]
    assert thinking_of( spy, "esc-m" ) == [ None ]


def test_thinking_default_sends_the_options_it_always_sent(tmp_path):
    spy = OptionsSpy()
    run( [ MAYBE ], hn.Ledger( str( tmp_path / "l" ) ), spy, CONFIG._replace( extractor_lists=1, judge_runs=1 ) )
    assert { t for _, t in spy.thinking } == { None }


def test_a_default_run_keeps_the_judge_key_it_always_had(tmp_path):
    ledger = hn.Ledger( str( tmp_path / "l" ) )
    run( [ pair( "p", OLD ) ], ledger, FakeModel(), CONFIG._replace( extractor_lists=1, judge_runs=1 ) )
    judge_keys = [ k for k in ledger.entries if k.startswith( "judge|" ) ]
    assert len( judge_keys ) == 1 and "thinking" not in judge_keys[ 0 ] and f"|{CONFIG.judge_model}+{CONFIG.escalation_model}|" in judge_keys[ 0 ]


def test_a_row_judged_under_one_thinking_setting_is_never_reused_under_the_other_in_either_direction(tmp_path):
    path  = str( tmp_path / "l" )
    small = CONFIG._replace( extractor_lists=1, judge_runs=1 )
    first = FakeModel()
    run( [ pair( "p", OLD ) ], hn.Ledger( path ), first, small )
    off   = FakeModel()
    run( [ pair( "p", OLD ) ], hn.Ledger( path ), off, small._replace( judge_thinking="off" ) )
    assert [ c[ 0 ] for c in off.calls ] == [ "judge" ]          # extractor list reused, judge rerun
    ledger = hn.Ledger( path )
    judge_keys = [ k for k in ledger.entries if k.startswith( "judge|" ) ]
    assert len( judge_keys ) == 2 and sum( 1 for k in judge_keys if "|judge-m+esc-m|thinking=off|" not in k and "thinking" not in k ) == 1
    again = FakeModel()
    run( [ pair( "p", OLD ) ], ledger, again, small )
    assert again.calls == []                                        # back to default: its own row is found
    third = FakeModel()
    run( [ pair( "p", OLD ) ], hn.Ledger( path ), third, small._replace( judge_thinking="off" ) )
    assert third.calls == []


def test_timing_is_recorded_by_stage_and_a_resumed_row_reports_its_recorded_time_not_zero(tmp_path):
    path  = str( tmp_path / "l" )
    small = CONFIG._replace( extractor_lists=1, judge_runs=1 )
    fresh = run( [ MAYBE ], hn.Ledger( path ), OptionsSpy( pause=0.02 ), small )[ 0 ][ "timing" ]
    assert set( fresh[ "stages" ] ) == { "extractor", "judge", "escalation" } and fresh[ "untimed_rows" ] == 0
    assert [ fresh[ "stages" ][ s ][ "calls" ] for s in ( "extractor", "judge", "escalation" ) ] == [ 1, 1, 1 ]
    assert all( fresh[ "stages" ][ s ][ "seconds" ] >= 0.02 for s in fresh[ "stages" ] )
    model   = FakeModel()
    resumed = run( [ MAYBE ], hn.Ledger( path ), model, small )[ 0 ][ "timing" ]
    assert model.calls == [] and resumed == fresh


def test_a_row_ledgered_without_timing_is_counted_untimed_not_as_zero_seconds(tmp_path):
    path  = str( tmp_path / "l" )
    small = CONFIG._replace( extractor_lists=1, judge_runs=1 )
    run( [ pair( "p", OLD ) ], hn.Ledger( path ), FakeModel(), small )
    stripped = [ { k: v for k, v in json.loads( line ).items() if k != "timing" } for line in open( path ) ]
    open( path, "w" ).write( "".join( json.dumps( r ) + "\n" for r in stripped ) )
    result = run( [ pair( "p", OLD ) ], hn.Ledger( path ), FakeModel(), small )[ 0 ]
    assert result[ "timing" ] == { "stages": {}, "untimed_rows": 2 }
    assert hr.call_timing( [ result ] ) == { "stages": {}, "untimed_rows": 2 }


def test_timing_is_no_part_of_a_ledger_key_and_shares_the_rows_line(tmp_path):
    path   = str( tmp_path / "l" )
    run( [ pair( "p", OLD ) ], hn.Ledger( path ), FakeModel(), CONFIG._replace( extractor_lists=1, judge_runs=1 ) )
    lines  = [ json.loads( l ) for l in open( path ) ]
    assert all( "timing" in l for l in lines if "key" in l ) and not any( "timing" in l[ "key" ] for l in lines if "key" in l )
    ledger = hn.Ledger( path )
    assert ledger.timing( lines[ 0 ][ "key" ] ) == lines[ 0 ][ "timing" ] and ledger.timing( "no such key" ) is None
    ledger.put( "k", [ 1 ] )
    assert ledger.timing( "k" ) is None and ledger.get( "k" ) == [ 1 ]


def test_a_backend_run_times_its_escalation_calls_under_that_stage(tmp_path):
    class Backend:
        prompt_version = "jev-v"
        key_id         = "jev-key"
        def complete( self, judged ): return True
        async def judge( self, claims, new, design, query_fn ):
            return await cj.finish_judgements( claims, [ "uncertain" ] * len( claims ), new, design, "esc-m", query_fn=query_fn )
    result = asyncio.run( hn.run_all( [ pair( "p", L1 + "\n" + L4 ) ], CONFIG._replace( extractor_lists=1, judge_runs=1 ),
                                      hn.Ledger( str( tmp_path / "l" ) ), query_fn=FakeModel(), judge_backend=Backend() ) )[ 0 ]
    assert set( result[ "timing" ][ "stages" ] ) == { "extractor", "escalation" }


def test_the_report_sums_call_time_and_counts_by_stage_and_names_the_thinking_setting(tmp_path):
    small   = CONFIG._replace( extractor_lists=1, judge_runs=2, judge_thinking="off" )
    results = run( [ pair( "a", L1 + "\n" + L4 ), pair( "b", OLD, old=OLD + "\n" + L4 ) ], hn.Ledger( str( tmp_path / "l" ) ), FakeModel(), small )
    report  = hr.build_report( results, small )
    stages  = report[ "call_timing" ][ "stages" ]
    assert report[ "judge_thinking" ] == "off" and report[ "call_timing" ][ "untimed_rows" ] == 0
    assert stages[ "extractor" ][ "calls" ] == 2 and stages[ "judge" ][ "calls" ] == 4
    assert stages[ "extractor" ][ "seconds" ] == sum( r[ "timing" ][ "stages" ][ "extractor" ][ "seconds" ] for r in results )


def test_a_result_without_timing_adds_nothing_to_the_report_timing():
    assert hr.call_timing( [ { "id": "old-style" } ] ) == { "stages": {}, "untimed_rows": 0 }


# ---- parallel pairs ------------------------------------------------------------------------------

def many( n ):
    return [ pair( f"p{i}", OLD, old=OLD + f"\nLine number {i} stays." ) for i in range( n ) ]


def run_parallel( pairs, ledger, model, parallel, config=CONFIG ):
    return asyncio.run( hn.run_all( pairs, config, ledger, query_fn=model, parallel=parallel ) )


def test_parallel_runs_up_to_n_pairs_at_once_and_returns_results_in_input_order(tmp_path):
    spy     = OptionsSpy( pause=0.01 )
    pairs   = many( 6 )
    results = run_parallel( pairs, hn.Ledger( str( tmp_path / "l" ) ), spy, 3, CONFIG._replace( extractor_lists=1, judge_runs=1 ) )
    assert [ r[ "id" ] for r in results ] == [ p[ "id" ] for p in pairs ]
    assert spy.peak == 3


def test_parallel_one_runs_one_pair_at_a_time_and_matches_the_sequential_results(tmp_path):
    small = CONFIG._replace( extractor_lists=1, judge_runs=1 )
    spy   = OptionsSpy( pause=0.005 )
    seq   = run_parallel( many( 3 ), hn.Ledger( str( tmp_path / "a" ) ), spy, 1, small )
    assert spy.peak == 1
    par   = run_parallel( many( 3 ), hn.Ledger( str( tmp_path / "b" ) ), FakeModel(), 4, small )
    strip = lambda rs: [ { k: v for k, v in r.items() if k != "timing" } for r in rs ]
    assert strip( seq ) == strip( par )


def test_parallel_below_one_is_refused():
    with pytest.raises( ValueError, match="parallel must be 1 or more" ):
        run_parallel( many( 1 ), None, FakeModel(), 0 )


def test_ledger_lines_stay_whole_under_concurrency(tmp_path):
    path = str( tmp_path / "l" )
    run_parallel( many( 8 ), hn.Ledger( path ), OptionsSpy( pause=0.005 ), 4 )
    lines = open( path ).read().splitlines()
    parsed = [ json.loads( l ) for l in lines ]          # a torn or interleaved line would not parse
    assert len( parsed ) == 8 * ( 2 + 6 ) and len( {p[ "key" ] for p in parsed} ) == len( parsed )


def test_the_call_budget_refuses_at_the_cap_and_never_overshoots_it_under_concurrency(tmp_path):
    budget = str( tmp_path / "calls.jsonl" )
    mt.set_budget( budget, { "judge-m": 5 } )
    try:
        with pytest.raises( mt.CallBudgetExceeded ):
            run_parallel( many( 8 ), hn.Ledger( str( tmp_path / "l" ) ), OptionsSpy( pause=0.005 ), 4, CONFIG._replace( extractor_lists=1, judge_runs=1 ) )
        assert mt.calls_used( "judge-m" ) == 5
    finally:
        mt.set_budget( None, {} )


def test_one_pairs_failure_keeps_the_rows_of_pairs_that_finished_and_the_earliest_failure_is_raised(tmp_path):
    path = str( tmp_path / "l" )
    class Dies( OptionsSpy ):
        async def __call__( self, prompt, options ):
            if "Line number 2 " in prompt or "Line number 3 " in prompt: raise RuntimeError( f"killed on {options.model}" )
            async for m in super().__call__( prompt, options ): yield m
    small = CONFIG._replace( extractor_lists=1, judge_runs=1 )
    with pytest.raises( mt.ModelCallError, match="failed" ):
        run_parallel( many( 4 ), hn.Ledger( path ), Dies( pause=0.01 ), 4, small )
    done = [ json.loads( l ) for l in open( path ) ]
    keys = [ d[ "key" ] for d in done ]
    ok   = [ pair_ for pair_ in many( 4 ) if "2 " not in pair_[ "old" ].splitlines()[ -1 ] and "3 " not in pair_[ "old" ].splitlines()[ -1 ] ]
    for p in ok: assert hn.ledger_key( "extract", p, ce.PROMPT_VERSION, "ext-m", 0 ) in keys
    after = FakeModel()
    run_parallel( many( 4 ), hn.Ledger( path ), after, 2, small )
    assert len( [ c for c in after.calls if c[ 0 ] == "extract" ] ) == 2          # only the two failed pairs extract again


def test_pairs_not_started_when_one_has_failed_are_skipped(tmp_path):
    class Dies( FakeModel ):
        async def __call__( self, prompt, options ):
            if "Line number 0 " in prompt: raise RuntimeError( "killed" )
            async for m in super().__call__( prompt, options ): yield m
    model = Dies()
    with pytest.raises( mt.ModelCallError ):
        run_parallel( many( 5 ), hn.Ledger( str( tmp_path / "l" ) ), model, 2, CONFIG._replace( extractor_lists=1, judge_runs=1 ) )
    assert len( [ c for c in model.calls if c[ 0 ] == "extract" ] ) < 5


def test_a_resumed_parallel_run_makes_no_duplicate_call(tmp_path):
    path  = str( tmp_path / "l" )
    first = FakeModel()
    run_parallel( many( 5 ), hn.Ledger( path ), first, 3 )
    second = FakeModel()
    run_parallel( many( 5 ), hn.Ledger( path ), second, 3 )
    assert len( first.calls ) == 5 * 8 and second.calls == []


def test_pairs_with_the_same_text_run_one_after_another_so_a_twin_never_repeats_a_call(tmp_path):
    model = OptionsSpy( pause=0.005 )
    run_parallel( [ pair( "a", OLD ), pair( "b", OLD ), pair( "c", OLD ) ], hn.Ledger( str( tmp_path / "l" ) ), model, 3 )
    assert len( model.calls ) == 8 and model.peak == 1


# ---- command line ---------------------------------------------------------------------------------

def test_the_command_line_passes_parallel_and_thinking_and_prints_call_time(tmp_path, capsys):
    from cosa.repo.doc_lint import harness_cli as cli
    ( tmp_path / "pairs.json" ).write_text( json.dumps( [ pair( "p0", L1 + "\n" + L3, seeded=L2 ), pair( "p1", OLD ) ] ) )
    spy = OptionsSpy( pause=0.01 )
    assert cli.main( cli_args( tmp_path ) + [ "--parallel", "2", "--judge-thinking", "off" ], query_fn=spy ) == 0
    out     = capsys.readouterr().out
    written = json.loads( ( tmp_path / "out.json" ).read_text() )
    assert spy.peak == 2 and written[ "judge_thinking" ] == "off" and written[ "call_timing" ][ "stages" ][ "judge" ][ "calls" ] > 0
    assert "call time extractor:" in out and "call time judge:" in out
    assert thinking_of( spy, "judge-m" ) and set( map( json.dumps, thinking_of( spy, "judge-m" ) ) ) == { json.dumps( { "type": "disabled" } ) }


def test_the_command_line_refuses_parallel_below_one_and_thinking_off_with_jev(tmp_path, capsys):
    from cosa.repo.doc_lint import harness_cli as cli
    ( tmp_path / "pairs.json" ).write_text( json.dumps( [ pair( "p", OLD ) ] ) )
    assert cli.main( cli_args( tmp_path ) + [ "--parallel", "0" ], query_fn=FakeModel() ) == 2
    assert "--parallel must be 1 or more" in capsys.readouterr().err
    assert cli.main( cli_args( tmp_path ) + [ "--judge-backend", "jev", "--judge-thinking", "off", "--t-lo", "0.3", "--t-hi", "0.8" ], query_fn=FakeModel() ) == 2
    assert "--judge-thinking only applies" in capsys.readouterr().err


def _runs( *verdicts_per_run ):
    """One run per argument; each argument lists one verdict per claim."""
    return [ [ { "verdict": v, "escalated": False } for v in run ] for run in verdicts_per_run ]


def test_a_claim_is_dropped_only_when_all_three_judge_runs_say_absent():
    assert hr.final_absent( _runs( [ "absent" ], [ "absent" ], [ "absent" ] ) ) == [ True ]


@pytest.mark.parametrize( "verdicts", [
    ( "absent", "absent", "present" ), ( "absent", "present", "absent" ), ( "present", "absent", "absent" ),
    ( "absent", "present", "present" ), ( "present", "present", "present" ),
] )
def test_a_claim_with_any_run_that_does_not_say_absent_is_kept( verdicts ):
    assert hr.final_absent( _runs( *[ [ v ] for v in verdicts ] ) ) == [ False ]


def test_each_claim_is_decided_on_its_own_three_verdicts():
    runs = _runs( [ "absent", "absent", "present" ], [ "absent", "present", "present" ], [ "absent", "absent", "present" ] )
    assert hr.final_absent( runs ) == [ True, False, False ]


def test_two_runs_out_of_three_absent_neither_catches_a_seeded_removal_nor_flags_a_pair():
    claim_list = { "claims": [ { "start": 0, "end": 10, "text": "q", "quote": "q" } ], "discarded": 0, "discards": [], "flags": [], "flag_words": [],
                   "reextract_calls": 0, "parse_failed": False, "retry_calls": 0, "uncovered": 0.0, "longest_quote": 0.25,
                   "runs": _runs( [ "absent" ], [ "absent" ], [ "present" ] ) }
    assert hr.caught( claim_list, ( 2, 5 ) ) is False and hr.flagged( claim_list ) is False
    assert hr.drop_tags( claim_list ) == ( [], [] )
    unanimous_list = dict( claim_list, runs=_runs( [ "absent" ], [ "absent" ], [ "absent" ] ) )
    assert hr.caught( unanimous_list, ( 2, 5 ) ) is True and hr.flagged( unanimous_list ) is True
