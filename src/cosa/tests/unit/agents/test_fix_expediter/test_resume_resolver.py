#!/usr/bin/env python3
"""
Unit tests for cosa.agents.test_fix_expediter.resume_resolver

Targets the resume-dispatch surface:
  - resolve_resume_target (4-way type dispatch)
  - _resolve_by_job_id        (checkpoint lookup)
  - _resolve_by_plan_path     (path normalize + filename parse + job lookup)
  - _find_stalled_tfe_by_plan_path  (DB query, exact + basename match)
  - _resolve_by_fuzzy_match   (candidate listing + ranking + auto-select)
  - list_resume_candidates    (stalled + recent DB rows)
  - _row_to_candidate_dict    (row normalization)
  - fuzzy_match_candidates    (LLM-ranked matching)

ALL boundaries are mocked — call-time imports (cosa.rest.job_persistence,
sqlalchemy, cosa.rest.db.database, postgres_models, job_state, the LLM stack)
are injected as fakes into sys.modules; the module-level fuzzy delegators are
patched on the module object. NO real DB / LLM / network / disk. Zero spend.

quick_smoke_test + __main__ are coverage-excluded by repo config.

Created 2026-05-31 by Rachel 🕊️ (CoSA coverage campaign, TFE lane).
"""

import sys
import types
from contextlib import contextmanager
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

import cosa.agents.test_fix_expediter.resume_resolver as rr
from cosa.agents.test_fix_expediter.resume_resolver import (
    resolve_resume_target,
    ResumeTarget,
    list_resume_candidates,
    fuzzy_match_candidates,
    _row_to_candidate_dict,
    _PLAN_FILENAME_PATTERN,
)


# ----------------------------------------------------------------------------
# Fake-module plumbing for call-time imports
# ----------------------------------------------------------------------------
def _exec_result( rows ):
    """A fake session.execute(...) return whose .scalars().all() yields rows."""
    res = MagicMock()
    res.scalars.return_value.all.return_value = rows
    return res


@contextmanager
def _db_fakes( checkpoint="__unset__", execute_side_effect=None ):
    """
    Inject fake DB-stack modules so the call-time imports resolve to mocks.

    - get_checkpoint_for_job returns `checkpoint` (unless left unset)
    - get_db() yields a session whose .execute side-effect is configurable
    """
    session = MagicMock()
    if execute_side_effect is not None:
        session.execute.side_effect = execute_side_effect

    @contextmanager
    def _get_db():
        yield session

    job_persistence = types.ModuleType( "cosa.rest.job_persistence" )
    job_persistence.get_checkpoint_for_job = MagicMock(
        return_value=( None if checkpoint == "__unset__" else checkpoint )
    )

    sa = types.ModuleType( "sqlalchemy" )
    sa.select = lambda *a, **k: MagicMock()
    sa.desc   = lambda *a, **k: MagicMock()

    db_database = types.ModuleType( "cosa.rest.db.database" )
    db_database.get_db = _get_db

    postgres_models = types.ModuleType( "cosa.rest.postgres_models" )
    postgres_models.JobHistory = MagicMock()

    job_state = types.ModuleType( "cosa.rest.job_state" )
    job_state.JobState = MagicMock()
    job_state.JobState.STALLED.value = "stalled"

    mods = {
        "cosa.rest.job_persistence": job_persistence,
        "sqlalchemy"               : sa,
        "cosa.rest.db.database"    : db_database,
        "cosa.rest.postgres_models": postgres_models,
        "cosa.rest.job_state"      : job_state,
    }
    with patch.dict( sys.modules, mods ):
        handles = types.SimpleNamespace(
            session              = session,
            get_checkpoint_for_job = job_persistence.get_checkpoint_for_job,
        )
        yield handles


def _row( **over ):
    base = dict(
        id_hash      = "tfe-abc::u@e.com",
        status       = "stalled",
        metadata_json= {},
        question_text= "",
        updated_at   = datetime( 2026, 1, 2, 3, 4, 5 ),
        completed_at = None,
    )
    base.update( over )
    return types.SimpleNamespace( **base )


# ============================================================================
# resolve_resume_target — 4-way dispatch
# ============================================================================
class TestResolveDispatch:
    def test_empty_string_not_found( self ):
        out = resolve_resume_target( "", "u@e.com" )
        assert out.source_type == "not_found"
        assert "Empty resume_from" in out.diagnostic

    def test_whitespace_only_not_found( self ):
        # `not resume_from` False, `not resume_from.strip()` True (second OR arm)
        out = resolve_resume_target( "   ", "u@e.com" )
        assert out.source_type == "not_found"

    def test_tfe_prefix_routes_to_job_id( self ):
        with patch.object( rr, "_resolve_by_job_id", return_value=ResumeTarget( source_type="job_id" ) ) as m:
            out = resolve_resume_target( "tfe-abc", "u@e.com" )
        m.assert_called_once_with( "tfe-abc", "u@e.com" )
        assert out.source_type == "job_id"

    def test_plan_md_suffix_routes_to_plan_path( self ):
        with patch.object( rr, "_resolve_by_plan_path", return_value=ResumeTarget( source_type="plan_path" ) ) as m:
            out = resolve_resume_target( "io/x-plan.md", "u@e.com" )
        m.assert_called_once()
        assert out.source_type == "plan_path"

    def test_plans_dir_substring_routes_to_plan_path( self ):
        # second OR arm: "/plans/" in s
        with patch.object( rr, "_resolve_by_plan_path", return_value=ResumeTarget( source_type="plan_path" ) ) as m:
            resolve_resume_target( "io/plans/whatever.txt", "u@e.com" )
        m.assert_called_once()

    def test_checkpoint_json_not_implemented( self ):
        out = resolve_resume_target( "io/my-checkpoint.json", "u@e.com" )
        assert out.source_type == "not_found"
        assert "not yet implemented" in out.diagnostic

    def test_fallthrough_routes_to_fuzzy( self ):
        with patch.object( rr, "_resolve_by_fuzzy_match", return_value=ResumeTarget( source_type="fuzzy" ) ) as m:
            out = resolve_resume_target( "the auth tests from yesterday", "u@e.com" )
        m.assert_called_once()
        assert out.source_type == "fuzzy"


# ============================================================================
# _resolve_by_job_id
# ============================================================================
class TestResolveByJobId:
    def test_fully_qualified_found( self ):
        with _db_fakes( checkpoint={ "phase": "x" } ):
            out = rr._resolve_by_job_id( "tfe-abc::u@e.com", "u@e.com" )
        assert out.source_type == "job_id"
        assert out.job_id == "tfe-abc::u@e.com"
        assert out.confidence == 1.0

    def test_bare_scoped_to_user( self ):
        with _db_fakes( checkpoint={ "phase": "x" } ) as h:
            out = rr._resolve_by_job_id( "tfe-abc", "u@e.com" )
        # bare id gets user-scoped before lookup
        h.get_checkpoint_for_job.assert_called_once_with( "tfe-abc::u@e.com" )
        assert out.job_id == "tfe-abc::u@e.com"

    def test_no_checkpoint_not_found( self ):
        with _db_fakes( checkpoint="__unset__" ):
            out = rr._resolve_by_job_id( "tfe-missing", "u@e.com" )
        assert out.source_type == "not_found"
        assert "not found, not stalled" in out.diagnostic


# ============================================================================
# _resolve_by_plan_path
# ============================================================================
class TestResolveByPlanPath:
    _GOOD = "2026.04.12-1-clusters-from-ts86c172f70cf47-c1-plan.md"

    def test_absolute_missing_file_not_found( self ):
        with patch( "os.path.isabs", return_value=True ), \
             patch( "os.path.exists", return_value=False ):
            out = rr._resolve_by_plan_path( "/abs/x-plan.md", "u@e.com" )
        assert out.source_type == "not_found"
        assert "Plan doc not found" in out.diagnostic

    def test_relative_path_joined_to_root( self ):
        captured = {}
        with patch( "cosa.utils.util.get_project_root", return_value="/proj" ), \
             patch( "os.path.isabs", return_value=False ), \
             patch( "os.path.exists", side_effect=lambda p: captured.setdefault( "p", p ) or False ):
            rr._resolve_by_plan_path( "io/x-plan.md", "u@e.com" )
        assert captured[ "p" ] == "/proj/io/x-plan.md"

    def test_filename_unparseable_not_found( self ):
        with patch( "cosa.utils.util.get_project_root", return_value="/proj" ), \
             patch( "os.path.isabs", return_value=True ), \
             patch( "os.path.exists", return_value=True ):
            out = rr._resolve_by_plan_path( "/abs/random-file.md", "u@e.com" )
        assert out.source_type == "not_found"
        assert "does not match expected pattern" in out.diagnostic

    def test_parsed_with_matching_stalled_job( self ):
        with patch( "cosa.utils.util.get_project_root", return_value="/proj" ), \
             patch( "os.path.isabs", return_value=True ), \
             patch( "os.path.exists", return_value=True ), \
             patch.object( rr, "_find_stalled_tfe_by_plan_path", return_value="tfe-xyz::u@e.com" ):
            out = rr._resolve_by_plan_path( f"/abs/{self._GOOD}", "u@e.com" )
        assert out.source_type == "plan_path"
        assert out.job_id == "tfe-xyz::u@e.com"
        assert out.confidence == 1.0

    def test_parsed_but_no_stalled_job( self ):
        with patch( "cosa.utils.util.get_project_root", return_value="/proj" ), \
             patch( "os.path.isabs", return_value=True ), \
             patch( "os.path.exists", return_value=True ), \
             patch.object( rr, "_find_stalled_tfe_by_plan_path", return_value=None ):
            out = rr._resolve_by_plan_path( f"/abs/{self._GOOD}", "u@e.com" )
        assert out.source_type == "not_found"
        assert "no stalled TFE job references it" in out.diagnostic
        assert "ts86c172f70cf47" in out.diagnostic   # source_id echoed


# ============================================================================
# _find_stalled_tfe_by_plan_path
# ============================================================================
class TestFindStalledByPlanPath:
    def test_exact_path_match_returns_id( self ):
        row = _row( id_hash="tfe-1", metadata_json={ "artifacts": { "plan_path": "io/p-plan.md" } } )
        with _db_fakes( execute_side_effect=[ _exec_result( [ row ] ) ] ):
            out = rr._find_stalled_tfe_by_plan_path( "io/p-plan.md", "u@e.com" )
        assert out == "tfe-1"

    def test_basename_match_when_paths_differ( self ):
        # stored relative, queried absolute -> matched via basename
        row = _row( id_hash="tfe-2", metadata_json={ "artifacts": { "plan_path": "io/sub/p-plan.md" } } )
        with _db_fakes( execute_side_effect=[ _exec_result( [ row ] ) ] ):
            out = rr._find_stalled_tfe_by_plan_path( "/abs/other/p-plan.md", "u@e.com" )
        assert out == "tfe-2"

    def test_row_without_plan_path_skipped_then_none( self ):
        row = _row( id_hash="tfe-3", metadata_json={ "artifacts": {} } )   # no plan_path -> continue
        with _db_fakes( execute_side_effect=[ _exec_result( [ row ] ) ] ):
            out = rr._find_stalled_tfe_by_plan_path( "io/p-plan.md", "u@e.com" )
        assert out is None

    def test_nonmatching_stored_path_continues_to_none( self ):
        # stored_path present but neither exact nor basename match -> if False -> next iteration
        row = _row( id_hash="tfe-4", metadata_json={ "artifacts": { "plan_path": "io/sub/other-plan.md" } } )
        with _db_fakes( execute_side_effect=[ _exec_result( [ row ] ) ] ):
            out = rr._find_stalled_tfe_by_plan_path( "io/p-plan.md", "u@e.com" )
        assert out is None

    def test_no_rows_returns_none( self ):
        with _db_fakes( execute_side_effect=[ _exec_result( [] ) ] ):
            out = rr._find_stalled_tfe_by_plan_path( "io/p-plan.md", "u@e.com" )
        assert out is None

    def test_exception_returns_none( self, capsys ):
        # get_db raises -> caught -> printed -> None
        with _db_fakes() as h:
            h.session.execute.side_effect = RuntimeError( "db down" )
            out = rr._find_stalled_tfe_by_plan_path( "io/p-plan.md", "u@e.com" )
        assert out is None
        assert "_find_stalled_tfe_by_plan_path error" in capsys.readouterr().out


# ============================================================================
# list_resume_candidates
# ============================================================================
class TestListResumeCandidates:
    def test_stalled_plus_recent_combined( self ):
        stalled = _row( id_hash="tfe-s", status="stalled" )
        recent  = _row( id_hash="tfe-r", status="completed",
                        completed_at=datetime( 2026, 2, 2 ) )
        with _db_fakes( execute_side_effect=[ _exec_result( [ stalled ] ), _exec_result( [ recent ] ) ] ):
            out = list_resume_candidates( "u@e.com", max_count=20 )
        assert [ c[ "job_id" ] for c in out ] == [ "tfe-s", "tfe-r" ]

    def test_stalled_fills_cap_skips_recent_query( self ):
        # max_count==1, one stalled row -> remaining==0 -> recent query NOT issued
        stalled = _row( id_hash="tfe-s" )
        results = [ _exec_result( [ stalled ] ) ]
        with _db_fakes( execute_side_effect=results ) as h:
            out = list_resume_candidates( "u@e.com", max_count=1 )
        assert [ c[ "job_id" ] for c in out ] == [ "tfe-s" ]
        assert h.session.execute.call_count == 1   # recent query skipped

    def test_exception_returns_empty( self, capsys ):
        with _db_fakes() as h:
            h.session.execute.side_effect = RuntimeError( "boom" )
            out = list_resume_candidates( "u@e.com" )
        assert out == []
        assert "list_resume_candidates error" in capsys.readouterr().out


# ============================================================================
# _row_to_candidate_dict
# ============================================================================
class TestRowToCandidateDict:
    def test_clusters_plural_and_proposed_summary( self ):
        row = _row(
            metadata_json={ "artifacts": { "checkpoint": { "state_snapshot": {
                "clusters"      : [ 1, 2, 3 ],
                "proposed_fixes": [ 1, 2 ],
            }, "stalled_at": "2026-01-01T00:00:00" } } },
        )
        d = _row_to_candidate_dict( row )
        assert d[ "summary" ] == "3 clusters, 2 proposed"
        assert d[ "stalled_at" ] == "2026-01-01T00:00:00"

    def test_single_cluster_singular_wording( self ):
        row = _row( metadata_json={ "checkpoint": { "state_snapshot": { "clusters": [ 1 ] } } } )
        d = _row_to_candidate_dict( row )
        assert d[ "summary" ] == "1 cluster"   # no trailing 's', metadata-level checkpoint fallback

    def test_question_text_fallback_when_no_snapshot( self ):
        row = _row( metadata_json={}, question_text="X" * 100 )
        d = _row_to_candidate_dict( row )
        assert d[ "summary" ] == "X" * 80      # truncated to 80

    def test_no_summary_no_question_text_placeholder( self ):
        row = _row( metadata_json={}, question_text="" )
        d = _row_to_candidate_dict( row )
        assert d[ "summary" ] == "(no summary available)"

    def test_updated_at_none_stalled_at_none( self ):
        row = _row( metadata_json={}, updated_at=None, completed_at=None )
        d = _row_to_candidate_dict( row )
        assert d[ "stalled_at" ] is None
        assert d[ "completed_at" ] is None

    def test_completed_at_isoformatted( self ):
        row = _row( completed_at=datetime( 2026, 3, 3, 12, 0, 0 ) )
        d = _row_to_candidate_dict( row )
        assert d[ "completed_at" ] == "2026-03-03T12:00:00"


# ============================================================================
# fuzzy_match_candidates
# ============================================================================
class TestFuzzyMatchCandidates:
    def _llm_fakes( self, matches ):
        """Inject the LLM-stack fake modules; return a config namespace."""
        xml_models = types.ModuleType( "cosa.agents.io_models.xml_models" )
        resp = MagicMock()
        resp.get_matches_list.return_value = matches
        xml_models.TFEResumeMatchResponse = MagicMock()
        xml_models.TFEResumeMatchResponse.from_xml.return_value = resp

        ptp = types.ModuleType( "cosa.agents.prompt_template_processor" )
        proc_inst = MagicMock()
        proc_inst.process_template.side_effect = lambda t, k: t
        ptp.PromptTemplateProcessor = MagicMock( return_value=proc_inst )

        llm_factory = types.ModuleType( "cosa.rest.llm_factory" )
        factory_inst = MagicMock()
        factory_inst.get_client.return_value = MagicMock( run=MagicMock( return_value="<xml/>" ) )
        llm_factory.LlmFactory = MagicMock( return_value=factory_inst )

        cfg_mod = types.ModuleType( "cosa.config.configuration_manager" )
        cfg_inst = MagicMock()
        cfg_inst.get.return_value = "/template-path"
        cfg_mod.ConfigurationManager = MagicMock( return_value=cfg_inst )

        return {
            "cosa.agents.io_models.xml_models"   : xml_models,
            "cosa.rest.llm_factory"              : llm_factory,
            "cosa.config.configuration_manager"  : cfg_mod,
            "cosa.agents.prompt_template_processor": ptp,
        }, factory_inst, cfg_mod.ConfigurationManager

    def test_empty_candidates_returns_empty( self ):
        assert fuzzy_match_candidates( "desc", [] ) == []

    def test_ranked_with_provided_client_and_cfg( self ):
        cands = [ { "job_id": "a", "status": "stalled", "summary": "s" },
                  { "job_id": "b", "status": "completed", "summary": "s" } ]
        mods, _, _ = self._llm_fakes( matches=[ "a", "b" ] )
        llm_client = MagicMock( run=MagicMock( return_value="<xml/>" ) )
        cfg = MagicMock(); cfg.get.return_value = "/template-path"
        with patch.dict( sys.modules, mods ), \
             patch( "cosa.utils.util.get_project_root", return_value="/proj" ), \
             patch( "cosa.utils.util.get_file_as_string", return_value="TEMPLATE" ):
            out = fuzzy_match_candidates( "desc", cands, llm_client=llm_client, config_mgr=cfg )
        assert [ c[ "job_id" ] for c in out ] == [ "a", "b" ]
        assert out[ 0 ][ "confidence" ] == 0.95
        assert out[ 1 ][ "confidence" ] == pytest.approx( 0.85 )
        assert out[ 0 ][ "reason" ] == "LLM ranked match #1"
        # provided client/cfg -> no factory/CM construction
        llm_client.run.assert_called_once()

    def test_constructs_cfg_and_factory_when_none( self ):
        cands = [ { "job_id": "a", "status": "stalled", "summary": "s" } ]
        mods, factory_inst, CM = self._llm_fakes( matches=[ "a" ] )
        with patch.dict( sys.modules, mods ), \
             patch( "cosa.utils.util.get_project_root", return_value="/proj" ), \
             patch( "cosa.utils.util.get_file_as_string", return_value="TEMPLATE" ):
            out = fuzzy_match_candidates( "desc", cands )   # llm_client & config_mgr both None
        assert out[ 0 ][ "job_id" ] == "a"
        CM.assert_called_once()                  # ConfigurationManager constructed
        factory_inst.get_client.assert_called_once()  # LlmFactory.get_client used

    def test_unknown_jid_skipped( self ):
        cands = [ { "job_id": "a", "status": "stalled", "summary": "s" } ]
        mods, _, _ = self._llm_fakes( matches=[ "a", "ghost", "  " ] )  # ghost + blank not in pool
        llm_client = MagicMock( run=MagicMock( return_value="<xml/>" ) )
        cfg = MagicMock(); cfg.get.return_value = "/template-path"
        with patch.dict( sys.modules, mods ), \
             patch( "cosa.utils.util.get_project_root", return_value="/proj" ), \
             patch( "cosa.utils.util.get_file_as_string", return_value="TEMPLATE" ):
            out = fuzzy_match_candidates( "desc", cands, llm_client=llm_client, config_mgr=cfg )
        assert [ c[ "job_id" ] for c in out ] == [ "a" ]

    def test_confidence_floor_at_half( self ):
        cands = [ { "job_id": f"j{i}", "status": "stalled", "summary": "s" } for i in range( 7 ) ]
        mods, _, _ = self._llm_fakes( matches=[ f"j{i}" for i in range( 7 ) ] )
        llm_client = MagicMock( run=MagicMock( return_value="<xml/>" ) )
        cfg = MagicMock(); cfg.get.return_value = "/template-path"
        with patch.dict( sys.modules, mods ), \
             patch( "cosa.utils.util.get_project_root", return_value="/proj" ), \
             patch( "cosa.utils.util.get_file_as_string", return_value="TEMPLATE" ):
            out = fuzzy_match_candidates( "desc", cands, llm_client=llm_client, config_mgr=cfg )
        assert out[ -1 ][ "confidence" ] == 0.5   # 0.95 - 6*0.1 = 0.35 -> floored to 0.5

    def test_exception_debug_true_prints_traceback( self, capsys ):
        cands = [ { "job_id": "a", "status": "stalled", "summary": "s" } ]
        # get_file_as_string raises -> except -> debug prints
        mods, _, _ = self._llm_fakes( matches=[ "a" ] )
        llm_client = MagicMock(); cfg = MagicMock(); cfg.get.return_value = "/p"
        with patch.dict( sys.modules, mods ), \
             patch( "cosa.utils.util.get_project_root", return_value="/proj" ), \
             patch( "cosa.utils.util.get_file_as_string", side_effect=RuntimeError( "io" ) ):
            out = fuzzy_match_candidates( "desc", cands, llm_client=llm_client, config_mgr=cfg, debug=True )
        assert out == []
        assert "fuzzy_match_candidates error" in capsys.readouterr().out

    def test_exception_debug_false_is_silent( self, capsys ):
        cands = [ { "job_id": "a", "status": "stalled", "summary": "s" } ]
        mods, _, _ = self._llm_fakes( matches=[ "a" ] )
        llm_client = MagicMock(); cfg = MagicMock(); cfg.get.return_value = "/p"
        with patch.dict( sys.modules, mods ), \
             patch( "cosa.utils.util.get_project_root", return_value="/proj" ), \
             patch( "cosa.utils.util.get_file_as_string", side_effect=RuntimeError( "io" ) ):
            out = fuzzy_match_candidates( "desc", cands, llm_client=llm_client, config_mgr=cfg, debug=False )
        assert out == []
        assert capsys.readouterr().out == ""   # silent when debug off


# ============================================================================
# _resolve_by_fuzzy_match (delegators patched on the module)
# ============================================================================
class TestResolveByFuzzyMatch:
    def test_no_candidates_not_found( self ):
        with patch.object( rr, "list_resume_candidates", return_value=[] ):
            out = rr._resolve_by_fuzzy_match( "desc", "u@e.com" )
        assert out.source_type == "not_found"
        assert "No stalled or recent" in out.diagnostic

    def test_no_ranked_returns_full_candidate_list( self ):
        cands = [ { "job_id": "a" }, { "job_id": "b" } ]
        with patch.object( rr, "list_resume_candidates", return_value=cands ), \
             patch.object( rr, "fuzzy_match_candidates", return_value=[] ):
            out = rr._resolve_by_fuzzy_match( "desc", "u@e.com" )
        assert out.source_type == "not_found"
        assert out.candidates == cands

    def test_high_confidence_stalled_auto_selects( self ):
        ranked = [ { "job_id": "a", "confidence": 0.95, "status": "stalled", "reason": "best" } ]
        with patch.object( rr, "list_resume_candidates", return_value=[ { "job_id": "a" } ] ), \
             patch.object( rr, "fuzzy_match_candidates", return_value=ranked ):
            out = rr._resolve_by_fuzzy_match( "desc", "u@e.com" )
        assert out.source_type == "fuzzy"
        assert out.job_id == "a"
        assert out.confidence == 0.95

    def test_high_confidence_not_stalled_is_ambiguous( self ):
        # confidence high but status != stalled -> ambiguous branch
        ranked = [ { "job_id": "a", "confidence": 0.99, "status": "completed", "reason": "r" } ]
        with patch.object( rr, "list_resume_candidates", return_value=[ { "job_id": "a" } ] ), \
             patch.object( rr, "fuzzy_match_candidates", return_value=ranked ):
            out = rr._resolve_by_fuzzy_match( "desc", "u@e.com" )
        assert out.source_type == "fuzzy"
        assert out.job_id is None
        assert out.candidates == ranked

    def test_low_confidence_stalled_is_ambiguous( self ):
        # stalled but confidence < 0.9 -> ambiguous branch
        ranked = [ { "job_id": "a", "confidence": 0.6, "status": "stalled" } ]
        with patch.object( rr, "list_resume_candidates", return_value=[ { "job_id": "a" } ] ), \
             patch.object( rr, "fuzzy_match_candidates", return_value=ranked ):
            out = rr._resolve_by_fuzzy_match( "desc", "u@e.com" )
        assert out.source_type == "fuzzy"
        assert out.confidence == 0.6
        assert out.candidates == ranked


def test_plan_filename_pattern_round_trip():
    """The compiled pattern extracts the packed source id."""
    m = _PLAN_FILENAME_PATTERN.match(
        "2026.04.12-1-clusters-from-ts86c172f70cf47e2dd5a14cd4-c1-plan.md"
    )
    assert m is not None
    assert m.group( "source_id" ) == "ts86c172f70cf47e2dd5a14cd4"
