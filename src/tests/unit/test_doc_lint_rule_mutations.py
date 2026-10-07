"""
One committed mutation check per doc_lint rule: disable the rule, and a named test must fail.

Each row loads one doc_lint module with the rule's name swapped for a sentinel (see
tests/helpers/doc_lint_mutant_plugin.py), which makes the rule vanish from every result. The
named test is run on its own in a subprocess first with no edit, so it must pass, and then
with the edit, so it must fail. A row whose failure output lacks its fragment fired on a
different assertion than the one it is meant to prove.
"""

import json
import os
import re
import subprocess
import sys

import pytest

import cosa.utils.util as cu
from tests.helpers.doc_lint_mutant_plugin import SENTINEL

LINTERS  = "src/tests/unit/test_doc_lint_linters.py::"
TEXT     = "src/tests/unit/test_doc_lint_text_rules.py::"
TOOLS    = "src/tests/unit/test_doc_lint_tools_and_gate.py::"
PROSE    = "src/tests/unit/test_doc_lint_prose_judge.py::"
TSDOC    = "src/tests/unit/test_doc_lint_tsdoc_lint.py::"
SCOPE    = "src/tests/unit/test_doc_lint_scope_gate.py::"

# ( rule, module, anchor, expression inside the anchor that names the rule, killing test, failure fragment )
RULES = [
    ( "parse-error (docstring)", "docstring_lint", '"parse-error", f"does not parse', '"parse-error"', LINTERS + "test_docstring_lint_reports_rules_at_file_lines_and_the_length_cap_and_parse_errors", "['parse-error']" ),
    ( "docstring-length", "docstring_lint", '"docstring-length", f"{kind}', '"docstring-length"', LINTERS + "test_docstring_lint_reports_rules_at_file_lines_and_the_length_cap_and_parse_errors", "['docstring-length']" ),
    ( "ruff", "tool_runners", "f\"ruff:{item[ 'code' ]}\"", "f\"ruff:{item[ 'code' ]}\"", TOOLS + "test_run_ruff_parses_findings_with_the_rule_as_ruff_code", "ruff:D205" ),
    ( "markdownlint", "tool_runners", 'f"markdownlint:{m.group( 3 )}"', 'f"markdownlint:{m.group( 3 )}"', TOOLS + "test_run_markdownlint_parses_lines_with_and_without_columns", "markdownlint:MD040" ),
    ( "dart analyze", "tool_runners", 'f"dart:{parts[ 2 ].lower()}"', 'f"dart:{parts[ 2 ].lower()}"', TOOLS + "test_run_dart_analyze_keeps_documentation_diagnostics_and_ignores_the_rest", "dart:public_member_api_docs" ),
    ( "dead-link", "links", '"dead-link"', '"dead-link"', LINTERS + "test_markdown_links_resolve_relative_to_the_page_and_skip_external_and_anchor_links", "link target" ),
    ( "dead-design", "links", '"dead-design"', '"dead-design"', LINTERS + "test_docstring_lint_checks_design_paths_only_when_a_root_is_given", "dead-design" ),
    ( "dartdoc-length", "dartdoc_lint", '"dartdoc-length"', '"dartdoc-length"', LINTERS + "test_dartdoc_lint_reports_rules_at_file_lines_and_the_block_length_cap", "dartdoc-length" ),
    ( "capability-length", "md_lint", '"capability-length"', '"capability-length"', LINTERS + "test_md_lint_template_caps_by_page_kind", "['capability-length']" ),
    ( "reference-length", "md_lint", '"reference-length"', '"reference-length"', LINTERS + "test_md_lint_template_caps_by_page_kind", "['reference-length']" ),
    ( "runbook-template", "md_lint", '"runbook-template"', '"runbook-template"', LINTERS + "test_md_lint_runbook_needs_four_sections_and_reports_each_missing_one", "runbook has" ),
    ( "parse-error (comment)", "comment_lint", '"parse-error"', '"parse-error"', LINTERS + "test_comment_lint_flags_shouting_tics_and_dates_in_comments_but_not_strings_or_shebang", "parse-error" ),
    ( "parse-error (tsdoc)", "tsdoc_lint", '"parse-error"', '"parse-error"', TSDOC + "test_a_parse_error_is_one_finding_at_its_first_line_and_the_comments_are_still_read", "parse-error" ),
    ( "docstring-length (tsdoc)", "tsdoc_lint", '"docstring-length"', '"docstring-length"', TSDOC + "test_jsdoc_longer_than_the_docstring_cap_is_flagged_once_at_its_start", "docstring-length" ),
    ( "unreadable", "cli", '"unreadable"', '"unreadable"', LINTERS + "test_run_linter_reports_text_json_strict_exit_and_unreadable_files", "could not read" ),
    ( "unreadable (scope gate)", "scope_gate", '"unreadable", f"could not be read', '"unreadable"', SCOPE + "test_a_file_that_is_not_utf8_is_a_finding_and_is_still_counted", "binary.py:1: unreadable: could not be read: " ),
    ( "summary-length", "text_rules", '"summary-length"', '"summary-length"', TEXT + "test_summary_rule_flags_a_long_first_line_only_and_only_once", "summary-length" ),
    ( "preface-length", "text_rules", '"preface-length"', '"preface-length"', TEXT + "test_preface_rule_counts_lines_before_the_contract_and_ignores_contractless_text", "preface-length" ),
    ( "sentence-length", "text_rules", '"sentence-length"', '"sentence-length"', TEXT + "test_sentence_rule_skips_contract_sections_bullets_and_reports_each_long_sentence", "sentence-length" ),
    ( "caps", "text_rules", '"caps", f"ALL', '"caps"', TEXT + "test_emphasis_rule_reports_caps_words_and_glyphs_at_their_lines", "caps" ),
    ( "glyph", "text_rules", '"glyph"', '"glyph"', TEXT + "test_emphasis_rule_reports_caps_words_and_glyphs_at_their_lines", "glyph" ),
    ( "tic", "text_rules", '"tic"', '"tic"', TEXT + "test_rhetoric_rule_reports_each_tic", "tic phrase 'Deliberately'" ),
    ( "bare-ref (section)", "text_rules", '"bare-ref", f"section reference', '"bare-ref"', TEXT + "test_reference_rule_reports_bare_references_and_spares_paths_and_local_definitions", "= any(" ),
    ( "bare-ref (id and step)", "text_rules", '"bare-ref", f"bare reference', '"bare-ref"', TEXT + "test_step_definitions_cover_headings_numbered_items_and_lettered_items", "bare reference 'step 3'" ),
    ( "dated-banner", "text_rules", '"dated-banner"', '"dated-banner"', TEXT + "test_history_rule_reports_banners_iso_dates_and_model_addressed_text_but_not_quoted_dates", "'iso-date' != 'dated-banner'" ),
    ( "iso-date", "text_rules", '"iso-date"', '"iso-date"', TEXT + "test_history_rule_reports_banners_iso_dates_and_model_addressed_text_but_not_quoted_dates", "first extra item: 'iso-date'" ),
    ( "agent-imperative", "text_rules", '"agent-imperative"', '"agent-imperative"', TEXT + "test_history_rule_reports_banners_iso_dates_and_model_addressed_text_but_not_quoted_dates", "'dated-banner' != 'agent-imperative'" ),
    ( "prose rule (fresh judgement)", "prose_judge", 'Finding( item[ "path" ], line, RULES[ rule ]', 'RULES[ rule ]', PROSE + "test_findings_follow_the_text_and_land_on_the_right_lines", "_mutant_disabled_rule" ),
    ( "prose rule (ledger replay)", "prose_judge", 'Finding( item[ "path" ], item[ "first_line" ] + offset, rule,', 'rule', PROSE + "test_an_identical_docstring_in_another_file_gets_its_own_path_and_line_on_a_replay", "_mutant_disabled_rule" ),
    ( "prose-unjudged", "prose_judge", 'item[ "first_line" ], "prose-unjudged"', '"prose-unjudged"', PROSE + "test_an_item_that_fails_twice_becomes_an_unjudged_finding_not_a_clean_pass_or_an_abort", "StopIteration" ),
]


def _run( node, mutant ):
    """
    Run one test node alone in a subprocess, with or without a mutant.

    Requires:
        - node is a pytest node id relative to the project root
        - mutant is { module, old, new }

    Ensures:
        - returns ( returncode, combined output )
        - LUPIN_ROOT and PYTHONPATH are pinned to the tree this test runs in

    Raises:
        - nothing
    """
    root = cu.get_project_root()
    env  = dict( os.environ, DOC_LINT_MUTANT=json.dumps( mutant ), LUPIN_ROOT=root, PYTHONPATH=f"{root}/src" )
    env.pop( "COVERAGE_PROCESS_START", None )
    cmd  = [ sys.executable, "-m", "pytest", node, "-q", "-vv", "--tb=short", "-rf", "--no-cov", "-p", "no:cacheprovider", "-p", "tests.helpers.doc_lint_mutant_plugin" ]
    res  = subprocess.run( cmd, cwd=root, env=env, capture_output=True, text=True )
    return res.returncode, res.stdout + res.stderr


@pytest.mark.parametrize( "rule,module,anchor,expr,node,fragment", RULES, ids=[ r[ 0 ] for r in RULES ] )
def test_disabling_the_rule_reddens_its_named_test( rule, module, anchor, expr, node, fragment ):
    control_rc, control_out = _run( node, { "module": module, "old": anchor, "new": anchor } )
    assert control_rc == 0, f"the test must pass unmutated:\n{control_out}"
    mutant_rc, mutant_out = _run( node, { "module": module, "old": anchor, "new": anchor.replace( expr, f'"{SENTINEL}"' ) } )
    assert mutant_rc == 1, f"disabling {rule} did not redden {node}:\n{mutant_out}"
    assert f"FAILED {node}" in mutant_out
    assert fragment in mutant_out, f"{node} failed, but not on the {rule} assertion:\n{mutant_out}"


def test_every_finding_site_in_the_package_has_a_mutation_row():
    package = os.path.join( cu.get_project_root(), "src", "cosa", "repo", "doc_lint" )
    sites   = []
    for name in sorted( os.listdir( package ) ):
        if not name.endswith( ".py" ): continue
        text = open( os.path.join( package, name ), encoding="utf-8" ).read()
        for m in re.finditer( r"Finding\(", text ):
            line_start = text.rfind( "\n", 0, m.start() ) + 1
            if text[ line_start : m.start() ].lstrip().startswith( ( "def ", "class ", "#" ) ) or "namedtuple" in text[ line_start : m.start() + 40 ]: continue
            sites.append( ( name[ :-3 ], text[ m.start() : m.start() + 400 ] ) )
    assert len( sites ) >= 20, sites
    for module, window in sites:
        assert any( row[ 1 ] == module and row[ 2 ] in window for row in RULES ), f"no mutation row for the Finding site in {module}: {window[ :120 ]}"
    assert len( { r[ 0 ] for r in RULES } ) == len( RULES )


def test_the_census_sees_a_finding_call_split_over_several_lines():
    window = "Finding(\n    path, 1,\n    \"parse-error\", f\"x\" )"
    assert not any( row[ 2 ] in window for row in RULES if row[ 1 ] == "no_such_module" )
    assert re.search( r"Finding\(", window )
