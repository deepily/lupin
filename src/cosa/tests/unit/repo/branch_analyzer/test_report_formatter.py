"""
Unit tests for cosa.repo.branch_analyzer.report_formatter.

Tests ReportFormatter, which renders a StatisticsCollector summary as console
(human banner), JSON, or Markdown. Coverage drives all three renderers plus
their option branches: the du.print_banner happy path AND its ImportError
fallback to a simple banner, the HEAD-vs-named comparison line, per-language
breakdowns (python/js/ts present AND absent), the docstring>0 arc, JSON
metadata on/off + pretty on/off, and Markdown timestamp on/off + empty
language-details.

Part of the CoSA 100% coverage campaign (repo module group).
"""
import json as json_mod
from unittest import mock

import pytest

from cosa.repo.branch_analyzer.report_formatter import ReportFormatter


def _make_stats( languages=("python", "javascript", "typescript") ):
    """
    Build a realistic get_summary()-shaped stats dict.

    Ensures:
        - python carries docstring>0 (exercises the docstring arc)
        - javascript/typescript carry docstring==0 (exercises the other arc)
        - only the requested languages appear in language_details
    """
    lang_template = {
        "python"     : { "code": 10, "comment": 4, "docstring": 6, "removed": 3,
                         "total_added": 20, "net": 17,
                         "percentages": { "code": 50.0, "comment": 20.0, "docstring": 30.0 } },
        "javascript" : { "code": 8, "comment": 2, "docstring": 0, "removed": 1,
                         "total_added": 10, "net": 9,
                         "percentages": { "code": 80.0, "comment": 20.0 } },
        "typescript" : { "code": 5, "comment": 0, "docstring": 0, "removed": 0,
                         "total_added": 5, "net": 5,
                         "percentages": { "code": 100.0, "comment": 0.0 } },
    }
    return {
        "overall" : {
            "total_added"   : 35,
            "total_removed" : 4,
            "net_change"    : 31,
            "files_changed" : 3,
        },
        "by_file_type" : [
            { "file_type": "python", "added": 20, "removed": 3, "net": 17, "total": 23 },
            { "file_type": "javascript", "added": 10, "removed": 1, "net": 9, "total": 11 },
        ],
        "language_details" : { k: lang_template[ k ] for k in languages },
        "files_changed_set" : [ "a.py", "b.js", "c.ts" ],
    }


@pytest.fixture
def formatter():
    """A ReportFormatter with default (empty) config."""
    return ReportFormatter( {} )


class TestInit:
    """Construction reads formatting/output/json/markdown config knobs."""

    def test_defaults( self, formatter ):
        """Ensures: sensible defaults for widths, chars, and number format."""
        assert formatter.col_file_type == 15
        assert formatter.border_char == "="
        assert formatter.show_percentages is True
        assert formatter.decimal_places == 1

    def test_config_overrides( self ):
        """Ensures: column widths and chars are read from config."""
        cfg = {
            "formatting": {
                "column_widths": { "file_type": 20, "counts": 8, "net_change": 10 },
                "border_char": "*",
                "section_border_width": 40,
            },
            "output": { "show_percentages": False, "decimal_places": 2 },
        }
        f = ReportFormatter( cfg )
        assert f.col_file_type == 20
        assert f.border_char == "*"
        assert f.border_width == 40
        assert f.show_percentages is False
        assert f.decimal_places == 2

    def test_debug_init_logs( self, capsys ):
        """Ensures: debug=True emits an init line."""
        ReportFormatter( {}, debug=True )
        assert "Initialized" in capsys.readouterr().out


class TestFormatConsole:
    """Console rendering: banner, branch context, summary, breakdowns."""

    def test_contains_summary_and_breakdown( self, formatter ):
        """
        Ensures:
            - the console output carries the overall summary banner, the
              file-type breakdown, and per-language sections for all 3 langs
        """
        out = formatter.format_console( _make_stats(), "main", "feature", repo_path="." )
        assert "OVERALL SUMMARY" in out
        assert "BREAKDOWN BY FILE TYPE" in out
        assert "PYTHON FILES" in out
        assert "JAVASCRIPT FILES" in out
        assert "TYPESCRIPT FILES" in out

    def test_head_input_adds_explanation_line( self, formatter ):
        """
        Ensures:
            - when head_branch_input == 'HEAD', the explanatory "(Shows what
              you added/changed...)" line is emitted
        """
        out = formatter.format_console(
            _make_stats(), "main", "feature",
            repo_path=".", head_branch_input="HEAD",
        )
        assert "Shows what you added/changed" in out

    def test_named_head_omits_explanation_line( self, formatter ):
        """
        Ensures:
            - a non-HEAD head_branch_input does NOT emit the explanation line
              (the else arc of the comparison-direction branch)
        """
        out = formatter.format_console(
            _make_stats(), "main", "feature",
            repo_path=".", head_branch_input="feature",
        )
        assert "Shows what you added/changed" not in out
        assert "Comparing:" in out

    def test_no_language_details_skips_language_sections( self, formatter ):
        """
        Ensures:
            - with empty language_details, none of the per-language sections
              are emitted (the false arcs of the python/js/ts ifs)
        """
        out = formatter.format_console(
            _make_stats( languages=() ), "main", "feature", repo_path="."
        )
        assert "PYTHON FILES" not in out
        assert "JAVASCRIPT FILES" not in out
        assert "TYPESCRIPT FILES" not in out

    def test_uses_du_banner_when_available( self, formatter ):
        """
        Ensures:
            - the happy path (cosa.utils.util importable) renders the banner
              and still includes the analysis title
        """
        out = formatter.format_console( _make_stats(), "main", "feature", repo_path="." )
        assert "BRANCH COMPARISON ANALYSIS" in out

    def test_falls_back_to_simple_banner_on_importerror( self, formatter ):
        """
        Ensures:
            - if cosa.utils.util cannot be imported, the formatter falls back to
              the simple banner (the except ImportError arc) without crashing
        """
        with mock.patch.dict( "sys.modules", { "cosa.utils.util": None } ):
            out = formatter.format_console( _make_stats(), "main", "feature", repo_path="." )
        assert "BRANCH COMPARISON ANALYSIS" in out


class TestFormatJson:
    """JSON rendering: valid payload, metadata on/off, pretty on/off."""

    def test_valid_json_with_metadata_by_default( self, formatter ):
        """
        Ensures:
            - output is valid JSON carrying branches, repository, statistics
            - metadata block is present by default
        """
        out = formatter.format_json( _make_stats(), "main", "feature", repo_path="." )
        payload = json_mod.loads( out )
        assert payload[ "base_branch" ] == "main"
        assert payload[ "head_branch" ] == "feature"
        assert "statistics" in payload
        assert "metadata" in payload

    def test_metadata_can_be_disabled( self ):
        """Ensures: json_output.include_metadata=False omits the metadata block."""
        f = ReportFormatter( { "json_output": { "include_metadata": False } } )
        payload = json_mod.loads( f.format_json( _make_stats(), "main", "feature" ) )
        assert "metadata" not in payload

    def test_non_pretty_json_has_no_indentation_newlines( self ):
        """
        Ensures:
            - json_output.pretty=False produces compact JSON (indent=None →
              no newlines), still valid and round-trippable
        """
        f = ReportFormatter( { "json_output": { "pretty": False } } )
        out = f.format_json( _make_stats(), "main", "feature" )
        assert "\n" not in out
        assert json_mod.loads( out )[ "base_branch" ] == "main"


class TestFormatMarkdown:
    """Markdown rendering: header, tables, timestamp on/off, language arcs."""

    def test_header_and_tables( self, formatter ):
        """
        Ensures:
            - the markdown carries the 'Branch Comparison Analysis' title and a
              file-type table, plus per-language sections incl. a docstring line
              for python (docstring>0 arc)
        """
        out = formatter.format_markdown(
            _make_stats(), "main", "feature", repo_path="."
        )
        assert "# Branch Comparison Analysis" in out
        assert "| File Type | Added | Removed | Net Change |" in out
        assert "### Python" in out
        assert "Docstrings" in out          # python docstring>0 arc
        assert "### Typescript" in out      # docstring==0 arc (no Docstrings line)

    def test_timestamp_can_be_disabled( self ):
        """
        Ensures:
            - markdown_output.include_timestamp=False omits the Generated/Repo
              metadata block (the false arc)
        """
        f = ReportFormatter( { "markdown_output": { "include_timestamp": False } } )
        out = f.format_markdown( _make_stats(), "main", "feature", repo_path="." )
        assert "**Generated**" not in out

    def test_empty_language_details_omits_section( self, formatter ):
        """
        Ensures:
            - with no language_details, the 'Language-Specific Details' section
              is omitted (the `if lang_details:` false arc)
        """
        out = formatter.format_markdown(
            _make_stats( languages=() ), "main", "feature", repo_path="."
        )
        assert "Language-Specific Details" not in out


class TestBanners:
    """The banner helpers render with and without du."""

    def test_simple_banner_wraps_title_in_borders( self, formatter ):
        """Ensures: the simple banner brackets the title with border chars."""
        banner = formatter._create_simple_banner( "HELLO" )
        assert "HELLO" in banner
        assert formatter.border_char * formatter.border_width in banner
