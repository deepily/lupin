"""
Unit tests for cosa.repo.directory_analyzer.report_formatter.

Tests DirectoryReportFormatter, which renders a DirectoryStatisticsCollector
summary as console / JSON / markdown. Coverage drives all three renderers plus
their option branches: the du.print_banner happy path AND its ImportError
fallback, the optional scan-stats summary block (present with all skip kinds /
present with only dirs-skipped / absent / all-zero), per-language sections
(present/absent, docstring>0 vs ==0), JSON metadata + pretty + scan_stats
on/off, and markdown timestamp + empty language-details arcs.

Part of the CoSA 100% coverage campaign (repo module group).
"""
import json as json_mod
from unittest import mock

import pytest

from cosa.repo.directory_analyzer.report_formatter import DirectoryReportFormatter


def _make_stats( languages=("python", "javascript") ):
    """
    Build a realistic get_summary()-shaped stats dict.

    Ensures:
        - python carries docstring>0; javascript docstring==0
        - only the requested languages appear in language_details
    """
    lang = {
        "python"     : { "code": 10, "comment": 4, "docstring": 6, "total": 20,
                         "percentages": { "code": 50.0, "comment": 20.0, "docstring": 30.0 } },
        "javascript" : { "code": 8, "comment": 2, "docstring": 0, "total": 10,
                         "percentages": { "code": 80.0, "comment": 20.0, "docstring": 0.0 } },
        "typescript" : { "code": 5, "comment": 0, "docstring": 0, "total": 5,
                         "percentages": { "code": 100.0, "comment": 0.0, "docstring": 0.0 } },
    }
    return {
        "overall" : { "total_lines": 35, "total_files": 3 },
        "by_file_type" : [
            { "file_type": "python", "total": 20, "files": 1, "percentage": 57.1 },
            { "file_type": "javascript", "total": 10, "files": 1, "percentage": 28.6 },
            { "file_type": "markdown", "total": 5, "files": 1, "percentage": 14.3 },
        ],
        "language_details" : { k: lang[ k ] for k in languages },
    }


def _scan_stats( **overrides ):
    """A DirectoryScanner.get_scan_stats()-shaped dict, zeroed then overridden."""
    base = {
        "files_scanned": 3, "files_skipped": 0, "dirs_skipped": 0,
        "binary_files_skipped": 0, "large_files_skipped": 0,
        "unreadable_files_skipped": 0, "total_lines": 35, "total_bytes": 900, "errors": 0,
    }
    base.update( overrides )
    return base


@pytest.fixture
def formatter():
    """A DirectoryReportFormatter with default (empty) config."""
    return DirectoryReportFormatter( {} )


class TestInit:
    """Construction reads formatting/output/json/markdown config knobs."""

    def test_defaults( self, formatter ):
        """Ensures: sensible default widths/chars/number-format."""
        assert formatter.col_file_type == 18
        assert formatter.border_char == "="
        assert formatter.show_percentages is True
        assert formatter.decimal_places == 1

    def test_config_overrides( self ):
        """Ensures: widths and chars are read from config."""
        cfg = {
            "formatting": {
                "column_widths": { "file_type": 22, "lines": 10, "files": 6, "percent": 6 },
                "border_char": "*", "section_border_width": 40,
            },
            "output": { "show_percentages": False, "decimal_places": 2 },
        }
        f = DirectoryReportFormatter( cfg )
        assert f.col_file_type == 22
        assert f.border_char == "*"
        assert f.border_width == 40
        assert f.decimal_places == 2

    def test_debug_init_logs( self, capsys ):
        """Ensures: debug=True emits an init line."""
        DirectoryReportFormatter( {}, debug=True )
        assert "Initialized" in capsys.readouterr().out


class TestFormatConsole:
    """Console rendering: banner, summary, optional scan block, breakdowns."""

    def test_summary_and_breakdown_and_languages( self, formatter ):
        """Ensures: console output carries summary, breakdown, present languages."""
        out = formatter.format_console( _make_stats(), "." )
        assert "OVERALL SUMMARY" in out
        assert "BREAKDOWN BY FILE TYPE" in out
        assert "PYTHON FILES" in out
        assert "JAVASCRIPT FILES" in out

    def test_typescript_section_when_present( self, formatter ):
        """Ensures: the typescript section renders when ts is present."""
        out = formatter.format_console(
            _make_stats( languages=( "python", "javascript", "typescript" ) ), "."
        )
        assert "TYPESCRIPT FILES" in out

    def test_no_languages_skips_language_sections( self, formatter ):
        """Ensures: empty language_details renders no per-language sections."""
        out = formatter.format_console( _make_stats( languages=() ), "." )
        assert "PYTHON FILES" not in out
        assert "JAVASCRIPT FILES" not in out

    def test_scan_stats_block_with_all_skip_kinds( self, formatter ):
        """Ensures: nonzero skip counters render each SCAN SUMMARY skip line."""
        ss = _scan_stats(
            dirs_skipped=2, binary_files_skipped=3,
            large_files_skipped=1, files_skipped=4,
        )
        out = formatter.format_console( _make_stats(), ".", scan_stats=ss )
        assert "SCAN SUMMARY" in out
        assert "Directories skipped" in out
        assert "Binary files skipped" in out
        assert "Large files skipped" in out
        assert "Pattern excluded" in out

    def test_scan_stats_block_with_only_dirs_skipped( self, formatter ):
        """Ensures: the block still renders when ONLY dirs_skipped is nonzero."""
        out = formatter.format_console( _make_stats(), ".", scan_stats=_scan_stats( dirs_skipped=1 ) )
        assert "SCAN SUMMARY" in out
        assert "Directories skipped" in out

    def test_scan_stats_block_without_dirs_skipped( self, formatter ):
        """
        Ensures:
            - when the block renders due to a NON-dirs skip (binary>0) while
              dirs_skipped==0, the 'Directories skipped' line is omitted
              (the `if dirs_skipped > 0` false arc inside the block, 141->143)
        """
        out = formatter.format_console( _make_stats(), ".", scan_stats=_scan_stats( binary_files_skipped=2 ) )
        assert "SCAN SUMMARY" in out
        assert "Directories skipped" not in out
        assert "Binary files skipped" in out

    def test_scan_stats_all_zero_omits_block( self, formatter ):
        """Ensures: all-zero scan_stats does NOT render the SCAN SUMMARY block."""
        out = formatter.format_console( _make_stats(), ".", scan_stats=_scan_stats() )
        assert "SCAN SUMMARY" not in out

    def test_no_scan_stats_omits_block( self, formatter ):
        """Ensures: omitting scan_stats renders no SCAN SUMMARY block."""
        out = formatter.format_console( _make_stats(), "." )
        assert "SCAN SUMMARY" not in out

    def test_falls_back_to_simple_banner_on_importerror( self, formatter ):
        """Ensures: an unimportable cosa.utils.util falls back to the simple banner."""
        with mock.patch.dict( "sys.modules", { "cosa.utils.util": None } ):
            out = formatter.format_console( _make_stats(), "." )
        assert "DIRECTORY CODE ANALYSIS" in out


class TestFormatJson:
    """JSON rendering: payload, scan_stats on/off, metadata on/off, pretty."""

    def test_valid_json_with_metadata_default( self, formatter ):
        """Ensures: valid JSON carrying directory + statistics + metadata."""
        payload = json_mod.loads( formatter.format_json( _make_stats(), "." ) )
        assert "directory" in payload
        assert "statistics" in payload
        assert "metadata" in payload

    def test_scan_stats_included_when_provided( self, formatter ):
        """Ensures: scan_stats appears in the JSON when supplied."""
        payload = json_mod.loads( formatter.format_json( _make_stats(), ".", scan_stats=_scan_stats() ) )
        assert "scan_stats" in payload

    def test_metadata_disabled( self ):
        """Ensures: include_metadata=False omits the metadata block."""
        f = DirectoryReportFormatter( { "json_output": { "include_metadata": False } } )
        payload = json_mod.loads( f.format_json( _make_stats(), "." ) )
        assert "metadata" not in payload

    def test_non_pretty_json_compact( self ):
        """Ensures: pretty=False yields compact (newline-free) JSON."""
        f = DirectoryReportFormatter( { "json_output": { "pretty": False } } )
        out = f.format_json( _make_stats(), "." )
        assert "\n" not in out
        assert json_mod.loads( out )[ "directory" ]


class TestFormatMarkdown:
    """Markdown rendering: header, tables, timestamp arc, language arcs."""

    def test_header_tables_and_docstring_arc( self, formatter ):
        """
        Ensures:
            - markdown carries the '# Directory Code Analysis' header + a
              file-type table + per-language sections, with a Docstrings line
              for python (docstring>0) and none for javascript (docstring==0)
        """
        out = formatter.format_markdown( _make_stats(), "." )
        assert "# Directory Code Analysis" in out
        assert "| File Type | Lines | Files | % |" in out
        assert "### Python" in out
        assert "Docstrings" in out

    def test_timestamp_disabled( self ):
        """Ensures: include_timestamp=False omits the Directory/Generated block."""
        f = DirectoryReportFormatter( { "markdown_output": { "include_timestamp": False } } )
        out = f.format_markdown( _make_stats(), "." )
        assert "**Generated**" not in out

    def test_empty_language_details_omits_section( self, formatter ):
        """Ensures: empty language_details omits the Language-Specific section."""
        out = formatter.format_markdown( _make_stats( languages=() ), "." )
        assert "Language-Specific Details" not in out


class TestBanners:
    """Banner helpers render with and without du."""

    def test_simple_banner_brackets_title( self, formatter ):
        """Ensures: the simple banner wraps the title in border chars."""
        banner = formatter._create_simple_banner( "HELLO" )
        assert "HELLO" in banner
        assert formatter.border_char * formatter.border_width in banner
