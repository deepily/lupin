"""
The frozen lists, the marker counts and the text rules of the documentation linters.

Each rule has a failing and a passing example, with two or more elements wherever order or
membership is asserted, so a rule that matches everything or nothing is caught.
"""

import pytest

from cosa.repo.doc_lint import rule_lists as rl
from cosa.repo.doc_lint import marker_counts as mc
from cosa.repo.doc_lint import text_rules as tr
from cosa.repo.doc_lint import word_list as wl

WORDS = frozenset( { "not", "never", "only", "the", "red", "row", "load", "point" } )


# ---- rule_lists: the predicates --------------------------------------------------------------

@pytest.mark.parametrize( "text, expected", [
    ( "see ruling 2 and ruling R1=B", [ "ruling 2", "ruling R1=B" ] ),
    ( "ruling is final, ruling in force, ruling on it", [] ),
    ( "Rick's ruling 2026-09-03 stands", [] ),
] )
def test_ruling_reference_matches_numbers_and_labels_but_not_words_or_dates( text, expected ):
    assert [ m.group( 0 ) for m in rl.RULING_REF_REGEX.finditer( text ) ] == expected


@pytest.mark.parametrize( "text, expected", [
    ( "step 12, Phase 3.3, option (b), Step 1.5", [ "step 12", "Phase 3.3", "option (b)", "Step 1.5" ] ),
    ( "step by step, a stage play, no item here", [] ),
] )
def test_step_reference_needs_a_number_letter_or_parenthesised_letter( text, expected ):
    assert [ m.group( 0 ) for m in rl.STEP_REF_REGEX.finditer( text ) ] == expected


@pytest.mark.parametrize( "text, expected", [
    ( "against 8b9a10e9 and again 1a2b3c4d", [ "8b9a10e9", "1a2b3c4d" ] ),
    ( "src/a-8b9a10e9.py and x.8b9a10e9 and cafebabe and 12345678", [] ),
] )
def test_bare_sha_needs_a_digit_and_a_letter_and_no_path_neighbour( text, expected ):
    assert rl.BARE_SHA_REGEX.findall( text ) == expected


def test_extended_id_reference_covers_decision_job_and_rows_keywords():
    found = [ m.group( 0 ) for m in rl.ID_REF_EXTENDED_REGEX.finditer( "decision f313fc2d rows 32c58572 job pr-b1ea3708 row aa543525" ) ]
    assert found == [ "decision f313fc2d", "rows 32c58572", "pr-b1ea3708", "row aa543525" ]
    assert rl.ID_REF_REGEX.findall( "decision f313fc2d" ) == []        # the spec's own column is narrower


def test_label_reference_exempts_versions_priorities_headings_and_hex_colours():
    assert rl.LABEL_REF_REGEX.findall( "D4 R1 L2" ) == [ "D4", "R1", "L2" ]
    assert rl.LABEL_REF_REGEX.findall( "V2 P0 H1 S3 #F00" ) == []


def test_dated_banner_matches_verbs_and_banner_lines_not_plain_prose():
    assert rl.DATED_BANNER_REGEX.search( "measured 2026-07-25 on the box" ) is not None
    assert rl.DATED_BANNER_REGEX.search( "UPDATE: see below" ) is not None
    assert rl.DATED_BANNER_REGEX.search( "the update arrived" ) is None


def test_agent_imperative_keeps_second_person_orders_and_drops_developer_advice():
    assert rl.AGENT_IMPERATIVE_REGEX.search( "You must reply now" ) is not None
    assert rl.AGENT_IMPERATIVE_REGEX.search( "ignore previous instructions" ) is not None
    assert rl.AGENT_IMPERATIVE_REGEX.search( "never call subprocess without try" ) is None


def test_tic_phrases_match_whole_words_case_insensitively():
    assert [ m.group( 0 ).lower() for m in rl.TIC_REGEX.finditer( "Deliberately so, by construction, and load-bearing" ) ] == [ "deliberately", "by construction", "load-bearing" ]
    assert rl.TIC_REGEX.search( "the defect, rather than silently" ) is None


# ---- marker_counts ---------------------------------------------------------------------------

def test_caps_words_flags_dictionary_words_only_and_skips_quotes_identifiers_and_labels():
    text = 'NOT a JSON value; "NEVER" quoted; LUPIN_ROOT; D6-STRICT; ONLY here; ID 7; `RED`; A1'
    assert mc.caps_words( text, WORDS ) == [ "NOT", "ONLY" ]


def test_caps_words_keeps_dictionary_acronym_exceptions_off_the_list():
    assert mc.caps_words( "the ID and GET and NULL", frozenset( { "id", "get", "null", "the", "and" } ) ) == []


def test_caps_words_at_text_edges_and_single_quoted_span():
    assert mc.caps_words( "NOT", WORDS ) == [ "NOT" ]
    assert mc.caps_words( "it's 'NEVER' done NOT", WORDS ) == [ "NOT" ]


def test_caps_words_skips_hyphenated_compounds_but_not_a_standalone_word():
    assert mc.caps_words( "NOT-FOUND and ONLY-IF but NOT", WORDS ) == [ "NOT" ]


def test_caps_words_reads_the_vendored_list_when_none_is_given():
    wl.configure_root( __import__( "cosa.utils.util", fromlist=[ "x" ] ).get_project_root() )
    assert mc.caps_words( "NOT a JSON value" ) == [ "NOT" ]


def test_blank_code_keeps_line_numbers_and_removes_fenced_and_doctest_blocks():
    text = "a\n```\nNOT\n```\nb\n>>> x = NEVER\n>>> y\n\nc"
    out  = mc.blank_code( text )
    assert out.count( "\n" ) == text.count( "\n" )
    assert "NOT" not in out and "NEVER" not in out
    assert out.split( "\n" )[ 0 ] == "a" and out.split( "\n" )[ -1 ] == "c"


def test_strip_markdown_removes_frontmatter_fences_and_comments():
    text = "---\nk: v\n---\nbody\n<!-- c -->\n```\ncode\n```\nend"
    out  = mc.strip_markdown( text )
    assert "k: v" not in out and "code" not in out and "c -->" not in out
    assert "body" in out and "end" in out


def test_section_reference_resolves_with_a_path_in_the_same_paragraph_even_when_wrapped():
    wrapped = "Design: §3.5 of\n`src/rnd/v0.1.9/a-note.md` says so"
    assert mc.bare_section_refs( wrapped ) == []
    assert mc.bare_section_refs( "see §4.3 and §0" ) == [ "§4.3", "§0" ]
    assert mc.bare_section_refs( "src/a.md lists it\nsee \u00a74.3 here" ) == []                   # the path is on the previous wrapped line
    assert mc.bare_section_refs( "src/a.md\n\nsee §4.3" ) == [ "§4.3" ]          # a blank line ends the paragraph


def test_count_markers_counts_each_column_and_blanks_code_first():
    text = "It is NOT so — deliberately. ⚠️ row aa543525 §5\n```\nNEVER\n```"
    c = mc.count_markers( text, WORDS )
    assert ( c[ "em_dash" ], c[ "caps_words" ], c[ "section_refs" ], c[ "id_refs" ], c[ "tics" ], c[ "emphasis_glyphs" ] ) == ( 1, 1, 1, 1, 1, 1 )
    assert c[ "words" ] == 8


def test_rates_per_thousand_scales_counts_and_survives_an_empty_corpus():
    assert mc.rates_per_thousand( { "words": 2000, "em_dash": 4, "caps_words": 1, "section_refs": 0, "id_refs": 0, "tics": 2, "emphasis_glyphs": 0 } )[ "em_dash" ] == 2.0
    assert set( mc.rates_per_thousand( { "words": 0, **{ c: 0 for c in mc.MARKER_COLUMNS } } ).values() ) == { 0.0 }


# ---- word_list -------------------------------------------------------------------------------

def test_load_words_reads_one_word_per_line_and_refuses_a_missing_file(tmp_path):
    f = tmp_path / "w.txt"
    f.write_text( "alpha\n\nbeta\n", encoding="utf-8" )
    assert wl.load_words( str( f ) ) == frozenset( { "alpha", "beta" } )
    with pytest.raises( OSError ):
        wl.load_words( str( tmp_path / "missing.txt" ) )


def test_default_words_is_read_once_per_configured_root_and_reread_after_reconfigure(tmp_path):
    ( tmp_path / "src" / "conf" ).mkdir( parents=True )
    ( tmp_path / "src" / "conf" / "dm-tutor-lowercase-words.txt" ).write_text( "zeta\n", encoding="utf-8" )
    wl.configure_root( tmp_path )
    first = wl.default_words()
    assert first == frozenset( { "zeta" } ) and wl.default_words() is first
    ( tmp_path / "src" / "conf" / "dm-tutor-lowercase-words.txt" ).write_text( "eta\n", encoding="utf-8" )
    wl.configure_root( tmp_path )
    assert wl.default_words() == frozenset( { "eta" } )


def test_default_words_falls_back_to_the_project_root_when_unconfigured():
    wl._state[ "root" ] = None
    wl._state[ "words" ] = None
    assert "the" in wl.default_words()


# ---- text_rules ------------------------------------------------------------------------------

def test_summary_rule_flags_a_long_first_line_only_and_only_once():
    long_line = "x" * 91
    assert [ f.rule for f in tr.summary_findings( f"\n{long_line}\nbody is also {long_line}", "a.py", 10 ) ] == [ "summary-length" ]
    assert tr.summary_findings( f"\n{long_line}", "a.py", 10 )[ 0 ].line == 11
    assert tr.summary_findings( "short\n\n" + long_line, "a.py", 1 ) == []             # a later paragraph is not the summary
    assert len( tr.summary_findings( "short\n" + long_line, "a.py", 1 ) ) == 1         # a wrapped second line joins the summary
    assert tr.summary_findings( "\n\n", "a.py", 1 ) == []


def test_preface_rule_counts_lines_before_the_contract_and_ignores_contractless_text():
    body = "\n".join( [ "s" ] + [ "line" ] * 7 + [ "Requires:", "  - x" ] )
    assert [ f.rule for f in tr.preface_findings( body, "a.py", 1 ) ] == [ "preface-length" ]
    assert tr.preface_findings( "s\nmore\nRequires:\n  - x", "a.py", 1 ) == []
    assert tr.preface_findings( "\n".join( [ "line" ] * 20 ), "a.py", 1 ) == []


def test_sentence_rule_skips_contract_sections_bullets_and_reports_each_long_sentence():
    long_sentence = " ".join( [ "word" ] * 26 ) + "."
    text = f"Short one. {long_sentence} Another short.\n- {long_sentence}\nRequires:\n  {long_sentence}"
    found = tr.sentence_findings( text, "a.py", 5 )
    assert [ ( f.line, f.rule ) for f in found ] == [ ( 5, "sentence-length" ) ]
    md = tr.sentence_findings( f"# {long_sentence}\n| {long_sentence} |\n- {long_sentence}\nplain", "a.md", 1, markdown=True )
    assert [ f.line for f in md ] == [ 3 ]                   # the bullet counts in markdown; heading and table do not


def test_a_summary_wrapped_over_two_lines_is_judged_as_one_sentence():
    wrapped = "\n" + " ".join( [ "word" ] * 10 ) + "\n" + " ".join( [ "more" ] * 12 ) + "\n\nBody."
    found   = tr.summary_findings( wrapped, "a.py", 10 )
    assert [ ( f.line, f.rule ) for f in found ] == [ ( 11, "summary-length" ) ] and "characters" in found[ 0 ].message
    assert tr.summary_findings( "\nShort first line\ncontinues here.\n\nBody " + "x" * 200, "a.py", 1 ) == []


def test_a_sentence_wrapped_over_hard_lines_is_judged_whole_and_reported_where_it_starts():
    wrapped = "Intro.\nWord " + " ".join( [ "word" ] * 8 ) + "\n" + "\n".join( [ " ".join( [ "word" ] * 9 ) ] * 2 ) + ".\nNext short one."
    found   = tr.sentence_findings( wrapped, "a.py", 1 )
    assert [ ( f.line, f.message ) for f in found ] == [ ( 2, "sentence of 27 words, limit 25" ) ]   # starts on line 2, not at the paragraph head
    assert tr.sentence_findings( "\n".join( [ " ".join( [ "w" ] * 9 ) ] * 2 ) + ".", "a.py", 1 ) == []


def test_wrapped_lines_join_only_within_a_paragraph_and_markdown_bullets_stay_separate():
    long_half = " ".join( [ "word" ] * 14 )
    assert tr.sentence_findings( f"{long_half}\n\n{long_half}", "a.py", 1 ) == []                       # a blank line ends the paragraph
    assert tr.sentence_findings( f"- {long_half}\n- {long_half}", "a.md", 1, markdown=True ) == []        # each bullet is its own paragraph
    assert len( tr.sentence_findings( f"{long_half}\n{long_half}", "a.md", 1, markdown=True ) ) == 1
    assert tr.sentence_findings( f"{long_half}\nRequires:\n  - {long_half}", "a.py", 1 ) == []             # contract lines are not joined in


def test_summary_cap_is_exact_across_a_wrap_and_joins_with_one_space():
    assert tr.summary_findings( "a" * 45 + "\n" + "b" * 44, "a.py", 1 ) == []                    # 45 + 1 space + 44 = 90, at the cap
    assert len( tr.summary_findings( "a" * 45 + "\n" + "b" * 45, "a.py", 1 ) ) == 1             # 91, one over: the join adds a space


def test_a_wrapped_sentence_is_reported_at_the_line_it_starts_even_when_lines_are_one_character():
    wrapped = "One.\nA\n" + "\n".join( [ "b" ] * 25 )
    assert [ f.line for f in tr.sentence_findings( wrapped, "a.py", 1 ) ] == [ 2 ]


REAL_WRAPPED_SUMMARY  = "\n    Mark phases up to phase_ordinal as completed so phase methods can skip a long stretch of\n    work that has already been done on resume and so on.\n\n    Requires:\n        - phase_ordinal >= 0\n    "
REAL_WRAPPED_SENTENCE = "\n    Rewrites one frozen DM body into a shorter one, preserving its placeholders.\n\n    Shaped after `MathAgent`, the minimal canonical `AgentBase` form, with a\n    bounded retry loop borrowed from `DmQualityJudge`, because the base class\n    does not have one and a transient vLLM hiccup should not cost a message its\n    compression.\n    "
REAL_FIELD_LIST      = "\n    Result of a CBR prediction.\n\n    Attributes:\n        verdict: Predicted decision value (majority vote) or None if no cases\n        confidence: Combined confidence score (0.0-1.0) = max_similarity * consistency\n        similar_cases: List of retrieved similar case dicts\n        case_count: Number of cases used in prediction\n    "


def test_hard_wrapped_docstrings_drawn_from_the_population_are_caught():
    assert [ ( f.line, f.rule ) for f in tr.summary_findings( REAL_WRAPPED_SUMMARY, "a.py", 1 ) ] == [ ( 2, "summary-length" ) ]   # first line alone is under the cap
    assert max( len( raw.strip() ) for raw in REAL_WRAPPED_SUMMARY.split( "\n" )[ :3 ] ) <= tr.SUMMARY_MAX_CHARS
    found = tr.sentence_findings( REAL_WRAPPED_SENTENCE, "a.py", 1 )
    assert [ ( f.line, f.rule ) for f in found ] == [ ( 4, "sentence-length" ) ]                                                  # starts on the "Shaped" line


def test_field_sections_are_not_joined_into_one_sentence():
    assert tr.sentence_findings( REAL_FIELD_LIST, "a.py", 1 ) == []
    assert [ f.rule for f in tr.sentence_findings( REAL_FIELD_LIST.replace( "Attributes:", "Details:" ), "a.py", 1 ) ] == [ "sentence-length" ]   # the header is what exempts it


def test_a_field_section_ends_at_the_first_line_not_indented_under_its_header():
    after = "    Intro.\n\n    Example:\n        run_the_thing( with_args )\n\n" + "\n".join( [ "    " + " ".join( [ "word" ] * 9 ) ] * 3 ) + ".\n"
    assert [ ( f.line, f.rule ) for f in tr.sentence_findings( after, "a.py", 1 ) ] == [ ( 6, "sentence-length" ) ]   # prose after the section is read
    inside = "    Intro.\n\n    Example:\n        " + "\n        ".join( [ " ".join( [ "word" ] * 9 ) ] * 3 ) + ".\n"
    assert tr.sentence_findings( inside, "a.py", 1 ) == []                                                          # indented lines belong to the section
    reset = "    Example:\n        code()\n\n    " + " ".join( [ "word" ] * 12 ) + "\n        " + " ".join( [ "more" ] * 14 ) + ".\n"
    assert [ f.line for f in tr.sentence_findings( reset, "a.py", 1 ) ] == [ 4 ]                                    # a deeper continuation line is prose again once the section has ended
    assert tr.sentence_findings( after, "a.md", 1, markdown=True ) != []                                            # markdown is untouched


def test_a_markdown_page_has_no_field_sections_so_prose_under_an_example_line_is_still_judged():
    page = "Example:\n  " + "\n  ".join( [ " ".join( [ "word" ] * 9 ) ] * 3 ) + ".\n"                # prose indented under an Example: line
    assert tr.sentence_findings( page, "a.py", 1 ) == []                                                          # control: in a docstring the header exempts it
    assert [ ( f.line, f.rule ) for f in tr.sentence_findings( page, "a.md", 1, markdown=True ) ] == [ ( 1, "sentence-length" ) ]                  # the sentence starts at the Example: line, which a page reads as prose
    assert [ i for i, _, _ in tr.prose_lines( page, markdown=True ) ] == [ 0, 1, 2, 3 ]                           # the header line is prose too


def test_emphasis_rule_reports_caps_words_and_glyphs_at_their_lines():
    found = tr.emphasis_findings( "ok\nThis is NOT fine ⚠️\nAnd `NEVER` here", "a.py", 7, WORDS )
    assert [ ( f.line, f.rule ) for f in found ] == [ ( 8, "caps" ), ( 8, "glyph" ) ]


def test_rhetoric_rule_reports_each_tic():
    found = tr.rhetoric_findings( "fine\nDeliberately odd\nby construction and load-bearing", "a.py", 1 )
    assert [ ( f.line, f.message ) for f in found ] == [ ( 2, "tic phrase 'Deliberately'" ), ( 3, "tic phrase 'by construction'" ), ( 3, "tic phrase 'load-bearing'" ) ]


def test_reference_rule_reports_bare_references_and_spares_paths_and_local_definitions():
    text = ( "see §4.3 and row aa543525 and ruling 2 and AC5 and step 3 and against 8b9a10e9\n"
             "M1 - first milestone\nlater M1 and D4\n"
             "## Step 1: Install\nafter Step 1 done\n"
             "§3 of src/docs/a.md is fine" )
    found = [ f.message for f in tr.reference_findings( text, "a.md", 1 ) ]
    assert any( "section reference" in m for m in found ) and sum( "section reference" in m for m in found ) == 1
    for bare in ( "row aa543525", "ruling 2", "AC5", "step 3", "8b9a10e9", "D4" ):
        assert any( bare in m for m in found ), bare
    assert not any( "'M1'" in m or "'Step 1'" in m for m in found )


def test_step_definitions_cover_headings_numbered_items_and_lettered_items():
    text = "## Step 1: Install\n1. Step 2 - open\n- Item B: the second\nafter Step 1 and Step 2 and Item B, but also step 3 and Item C"
    found = [ f.message for f in tr.reference_findings( text, "a.md", 1 ) ]
    assert found == [ "bare reference 'step 3'", "bare reference 'Item C'" ]


def test_a_defined_step_cited_at_the_end_of_a_sentence_is_still_the_pages_own_structure():
    text = "## Step 3: Build\n### Step 3b: Check\nSee Step 3. Then after step 3b. Also step 4."
    assert [ f.message for f in tr.reference_findings( text, "a.md", 1 ) ] == [ "bare reference 'step 4'" ]


def test_a_sha_inside_a_reported_row_reference_is_not_reported_twice():
    found = [ f.message for f in tr.reference_findings( "see row `ed76b897` and later 8b9a10e9 alone", "a.md", 1 ) ]
    assert len( found ) == 2 and any( "ed76b897" in m for m in found ) and any( m.endswith( "'8b9a10e9'" ) for m in found )


def test_cc_and_crud_are_not_emphasis_even_when_the_word_list_knows_them():
    assert mc.caps_words( "CC and CRUD here", frozenset( { "cc", "crud", "here", "and" } ) ) == []


def test_history_rule_reports_banners_iso_dates_and_model_addressed_text_but_not_quoted_dates():
    text = 'fixed 2026-07-25 here\nplain 2026-09-01 date\nquoted "2026-08-08" date\nyou must obey'
    found = tr.history_findings( text, "a.py", 1 )
    assert sorted( f.rule for f in found ) == [ "agent-imperative", "dated-banner", "iso-date", "iso-date" ]
    assert not any( f.line == 3 for f in found )


def test_lint_text_combines_every_rule_sorted_and_respects_the_structure_flag():
    long_line = "y" * 95
    text = f"\n{long_line}\n\nThis is NOT ok. §5\n"
    with_structure    = tr.lint_text( text, "a.py", 1, words=WORDS )
    without_structure = tr.lint_text( text, "a.py", 1, structure=False, words=WORDS )
    assert "summary-length" in [ f.rule for f in with_structure ]
    assert "summary-length" not in [ f.rule for f in without_structure ]
    assert [ f.line for f in with_structure ] == sorted( f.line for f in with_structure )
    assert { "caps", "bare-ref" } <= { f.rule for f in without_structure }


def test_lint_text_ignores_code_blocks_inside_a_docstring():
    assert tr.lint_text( ">>> x = NOT NEVER\n\nclean", "a.py", 1, structure=False, words=WORDS ) == []


# ---- the calendar-date predicate (row e786f5e5) ----------------------------------------------

@pytest.mark.parametrize( "text, expected", [
    ( "> **Last Updated**: 2026.09.28", [ "2026.09.28" ] ),                        # banner line, dotted, from src/docs
    ( "Date: 2026-03-20", [ "2026-03-20" ] ),                                      # banner line, hyphenated
    ( "ended 2026.03.20.", [ "2026.03.20" ] ),                                     # sentence-final dot
    ( "see 2026.09.30-foo.md and src/rnd/2026.09.30/x.md", [] ),                   # file and directory names
    ( "see 2026-09-30-foo.md", [] ),                                               # hyphenated file name
    ( "mixed 2026-03.20 and 2026.13.20 and 2026.03.32", [] ),                      # mixed separator, bad month, bad day
    ( "version 1.2026.03.20 and 2026.03.20x", [] ),                                # touching a dot or a word
    ( "pre-2026-06-05 and post-2026-05-16", [ "2026-06-05", "2026-05-16" ] ),      # a leading hyphen is prose, still a date
    ( "x2026.03.20 and 12026.03.20", [] ),                                         # a word character before
    ( "src/2026.03.20 and 2026.03.20/x", [] ),                                     # a slash before or after
    ( "2026-03-20-plan and 2026.03.20-plan", [] ),                                 # a trailing hyphen
    ( "2026-03-20.md and 2026.03.20.md", [] ),                                     # a file extension
    ( "2026.00.20 and 2026.03.00", [] ),                                           # month 00, day 00
    ( "ended 1999.01.01 here", [ "1999.01.01" ] ),                                 # the 19xx years are dates
    ( "ended 3026.06.11 here", [] ),                                               # a year outside 19xx and 20xx is not
] )
def test_calendar_date_predicate_takes_either_separator_and_refuses_file_names_and_non_dates( text, expected ):
    assert [ m.group( 0 ) for m in rl.ISO_DATE_REGEX.finditer( text ) ] == expected


def test_history_rule_reports_dotted_and_hyphenated_banners_but_not_a_backticked_file_name():
    text  = "Last Updated: 2025.10.04\nDate: 2026-03-20\nsee `2026.09.30-foo.md` and 2026.09.30-bar.md\n"
    found = tr.history_findings( text, "a.md", 1 )
    assert [ ( f.line, f.rule ) for f in found ] == [ ( 1, "iso-date" ), ( 2, "iso-date" ) ]


def test_history_rule_skips_the_agent_imperative_check_only_when_told_to():
    text = "you must obey"
    assert [ f.rule for f in tr.history_findings( text, "a.py", 1 ) ] == [ "agent-imperative" ]
    assert tr.history_findings( text, "a.py", 1, agent_rule=False ) == []
    assert [ f.rule for f in tr.lint_text( text, "a.py", 1, words=WORDS ) if f.rule == "agent-imperative" ] == [ "agent-imperative" ]
    assert [ f.rule for f in tr.lint_text( text, "a.py", 1, words=WORDS, agent_rule=False ) if f.rule == "agent-imperative" ] == []


# ---- a sentence that starts with Do not / Don't (row e59bd0b3) -------------------------------

@pytest.mark.parametrize( "text, lines", [
    ( "Do not call this twice.", [ 1 ] ),
    ( "Reads a row. Don't retry here.", [ 1 ] ),
    ( "Reads a row.\n  DO NOT retry it.", [ 2 ] ),
    ( "Don’t retry it.", [ 1 ] ),
    ( "Reads a row.\n\nDo not retry.\nDon't loop either.", [ 3, 4 ] ),
] )
def test_a_sentence_that_starts_with_do_not_is_found_at_its_line( text, lines ):
    assert [ tr.line_of_offset( text, o ) + 1 for o, _ in tr.do_not_starts( text ) ] == lines
    found = tr.history_findings( text, "a.py", 1 )
    assert [ f.line for f in found ] == lines and [ f.rule for f in found ] == [ "agent-imperative" ] * len( lines )


@pytest.mark.parametrize( "text", [
    "It does not matter, and we do not care.",
    "A long line that says\ndo not wrap here.",
    "Never raises on a blank id. Never call it twice.",
    "Use `Do not` here. The phrase \"Don't stop\" is quoted.",
    "Requires:\n    - Do not pass None\n    - Don't pass a blank id\nEnsures:\n    - Do not mutate its input",
    "Raises:\n    - Do not\n      continue",
    "Do nothing special. Donate it.",
    "He said \"Fine. Do not go.\" and then `x. Don't y` was run.",
    "The text says Do not here, and also so Don't there.",
    "Requires:\n    - x\n      Do not pass None",
    "Ensures:\n    - x\n      Do not mutate its input",
    "Raises:\n    - x\n      Don't raise on a blank id",
] )
def test_mid_sentence_quoted_contract_item_and_never_text_is_not_found( text ):
    assert tr.do_not_starts( text ) == [] and tr.history_findings( text, "a.py", 1 ) == []


def test_a_contract_section_ends_at_the_next_line_that_is_not_indented_deeper():
    text = "Requires:\n    - Do not pass None\n\nDo not call it twice.\n\nEnsures:\n    - x\nDon't loop."
    assert [ f.line for f in tr.history_findings( text, "a.py", 1 ) ] == [ 4, 8 ]
    assert tr.contract_item_lines( text ) == { 1, 2, 6 }


def test_the_first_line_offset_is_added_and_a_tool_docstring_stays_exempt():
    assert [ f.line for f in tr.history_findings( "x\nDo not y.", "a.py", 40 ) ] == [ 41 ]
    assert [ f.rule for f in tr.history_findings( "Do not retry.", "a.py", 1 ) ] == [ "agent-imperative" ]
    assert tr.history_findings( "Do not retry.", "a.py", 1, agent_rule=False ) == []
    assert [ f.rule for f in tr.lint_text( "Do not retry.", "a.py", 1, words=WORDS ) if f.rule == "agent-imperative" ] == [ "agent-imperative" ]


def test_the_do_not_rule_is_the_one_rule_the_markdown_and_dart_linters_run_too():
    from cosa.repo.doc_lint import md_lint
    assert "Do not retry." not in ( md_lint.__doc__ or "" )
    assert [ f.rule for f in tr.lint_text( "Do not retry.", "a.md", 1, structure=False, markdown=True, words=WORDS ) if f.rule == "agent-imperative" ] == [ "agent-imperative" ]


def test_a_step_word_inside_a_configuration_key_is_not_a_reference():
    text = "Flags:\n    test fix expediter phase 1 engine = sdk | claude_code\n    test fix expediter phase 3 engine = sdk | claude_code"
    assert tr.reference_findings( text, "a.py", 1 ) == []


def test_a_step_word_in_prose_a_value_or_a_capitalised_key_is_still_a_reference():
    text = "Phase 1 = the first stage.\nengine = phase 2\nSee phase 3 for details.\nthe engine for phase 4 is slow"
    assert [ f.message for f in tr.reference_findings( text, "a.py", 1 ) ] == [
        "bare reference 'Phase 1'", "bare reference 'phase 2'", "bare reference 'phase 3'", "bare reference 'phase 4'"
    ]


def test_caps_words_skips_an_enum_member_in_an_example_but_not_prose_after_a_full_stop():
    assert mc.caps_words( "    type=TaskType.BOUNDED\n    mode = Config.NOT_USED", WORDS ) == []
    assert mc.caps_words( "It is done.NOT here. It is done. ONLY here.", WORDS ) == [ "ONLY" ]


def test_caps_words_still_flags_a_capitalised_word_with_no_identifier_before_the_dot():
    assert mc.caps_words( "see (1).NOT and ...ONLY", WORDS ) == [ "NOT", "ONLY" ]
