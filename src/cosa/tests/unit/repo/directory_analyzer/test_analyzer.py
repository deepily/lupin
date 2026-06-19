"""
Unit tests for cosa.repo.directory_analyzer.analyzer.

Tests DirectoryAnalyzer, the orchestrator that loads + merges config (its own
default_config.yaml over branch_analyzer's), wires the scanner / classifiers /
stats collector / formatter, and runs the scan→classify→aggregate pipeline.
DirectoryScanner.scan is fed synthetic FileInfo objects so the pipeline runs
fully offline (no real filesystem walk); the real classifiers + collector +
formatter are exercised end-to-end.

Harvested from analyzer.quick_smoke_test (the __main__ block) — its intent
(config load, scan, py code/comment separation, console/json/markdown render,
scan-stats, error handling) is preserved here with REAL assertions and no
real-FS dependency.

Part of the CoSA 100% coverage campaign (repo module group).
"""
from unittest import mock

import pytest

from cosa.repo.directory_analyzer.analyzer import DirectoryAnalyzer
from cosa.repo.directory_analyzer.directory_scanner import FileInfo
from cosa.repo.directory_analyzer.exceptions import DirectoryAnalyzerError


def _file_info( path, lines ):
    """Build a FileInfo from a path + list of source lines."""
    return FileInfo(
        path=path, relative_path=path, lines=lines,
        line_count=len( lines ), size_bytes=sum( len( l ) for l in lines ), encoding="utf-8",
    )


@pytest.fixture
def patched_scan():
    """
    Patch DirectoryScanner.scan + get_scan_stats so analyze() runs offline.

    Ensures:
        - scan() yields whatever the test assigns to scan.return_value
        - get_scan_stats() returns a benign dict
    Yields the DirectoryScanner mock instance held by the analyzer.
    """
    with mock.patch( "cosa.repo.directory_analyzer.analyzer.DirectoryScanner" ) as ScannerCls:
        instance = ScannerCls.return_value
        instance.scan.return_value = iter( [] )
        instance.get_scan_stats.return_value = { "files_scanned": 0 }
        yield instance


class TestInit:
    """Construction loads+merges config and wires components."""

    def test_config_loaded_and_merged( self, patched_scan ):
        """
        Ensures:
            - config carries both branch_analyzer (file_types) and the merged
              directory section
        """
        analyzer = DirectoryAnalyzer()
        assert "file_types" in analyzer.config
        assert "directory" in analyzer.config

    def test_debug_init_logs( self, patched_scan, capsys ):
        """Ensures: debug=True emits the init banner."""
        DirectoryAnalyzer( debug=True )
        assert "Initialized" in capsys.readouterr().out

    def test_config_failure_wrapped( self, patched_scan ):
        """Ensures: a ConfigLoader failure is wrapped as DirectoryAnalyzerError."""
        with mock.patch(
            "cosa.repo.directory_analyzer.analyzer.ConfigLoader",
            side_effect=RuntimeError( "cfg boom" ),
        ):
            with pytest.raises( DirectoryAnalyzerError ) as exc:
                DirectoryAnalyzer()
        assert "Failed to load configuration" in str( exc.value )


class TestLoadDirectoryConfig:
    """_load_directory_config reads the shipped default_config.yaml."""

    def test_missing_default_config_raises_wrapped( self, patched_scan ):
        """
        Ensures:
            - a missing directory default_config.yaml surfaces as a wrapped
              DirectoryAnalyzerError at init (the _load_directory_config
              not-found raise, caught + re-wrapped by __init__)

        Only the directory-analyzer default is made to vanish; branch_analyzer's
        ConfigLoader (which loads FIRST in __init__) must still find its own
        default, so the patch delegates every other path to the real
        os.path.exists rather than reusing the patched Path.exists.
        """
        import os
        from pathlib import Path

        def fake_exists( self ):
            if self.name == "default_config.yaml" and "directory_analyzer" in str( self ):
                return False
            return os.path.exists( str( self ) )

        with mock.patch.object( Path, "exists", fake_exists ):
            with pytest.raises( DirectoryAnalyzerError ):
                DirectoryAnalyzer()

    def test_invalid_yaml_raises_wrapped( self, patched_scan ):
        """
        Ensures:
            - invalid YAML in the DIRECTORY default config wraps to
              DirectoryAnalyzerError (the _load_directory_config YAMLError arc)

        __init__ loads the branch_analyzer config FIRST (call 1 to yaml.safe_load)
        then the directory config (call 2). A blanket patch would also break the
        branch load and hit the wrong path, so this delegates call 1 to the real
        safe_load and only raises YAMLError on the directory (2nd) call.
        """
        import yaml
        real_safe_load = yaml.safe_load
        calls = { "n": 0 }

        def call_ordered( stream ):
            calls[ "n" ] += 1
            if calls[ "n" ] == 1:          # branch_analyzer default — load for real
                return real_safe_load( stream )
            raise yaml.YAMLError( "bad" )  # directory default — the path under test

        with mock.patch( "yaml.safe_load", side_effect=call_ordered ):
            with pytest.raises( DirectoryAnalyzerError ):
                DirectoryAnalyzer()
        assert calls[ "n" ] == 2

    def test_empty_yaml_treated_as_empty_dict( self, patched_scan ):
        """
        Ensures:
            - an empty DIRECTORY default config (safe_load → None) becomes {}
              and init still succeeds (the `if config is None: config = {}` arc)

        Same call-ordering as above: branch config loads for real (call 1), only
        the directory config (call 2) returns None — otherwise a blanket None
        would empty the branch config and fail its required-sections validation.
        """
        import yaml
        real_safe_load = yaml.safe_load
        calls = { "n": 0 }

        def call_ordered( stream ):
            calls[ "n" ] += 1
            if calls[ "n" ] == 1:
                return real_safe_load( stream )
            return None

        with mock.patch( "yaml.safe_load", side_effect=call_ordered ):
            analyzer = DirectoryAnalyzer()
        assert isinstance( analyzer.config, dict )
        assert "git" in analyzer.config        # branch config survived intact


class TestAnalyze:
    """analyze() runs the scan→classify→aggregate pipeline."""

    def test_counts_supported_and_other_file_types( self, patched_scan ):
        """
        Ensures:
            - python lines are code/comment/docstring classified
            - a non-supported file type (markdown) counts non-blank lines only
            - blank lines in a supported file are dropped (category None)
            - per-file-type totals + per-language breakdown are correct
        """
        patched_scan.scan.return_value = iter( [
            _file_info( "a.py", [ "# c", "x = 1", '"""d"""', "" ] ),  # comment, code, docstring, blank(skip)
            _file_info( "R.md", [ "# Title", "", "body" ] ),          # markdown: 2 non-blank
        ] )
        analyzer = DirectoryAnalyzer()
        stats = analyzer.analyze( "/anydir" )

        py = stats[ "language_details" ][ "python" ]
        assert py[ "comment" ] == 1
        assert py[ "code" ] == 1
        assert py[ "docstring" ] == 1
        assert "markdown" not in stats[ "language_details" ]

        by_type = { r[ "file_type" ]: r for r in stats[ "by_file_type" ] }
        assert by_type[ "python" ][ "total" ] == 3      # 3 non-blank py lines
        assert by_type[ "markdown" ][ "total" ] == 2    # 2 non-blank md lines
        assert stats[ "overall" ][ "total_files" ] == 2

    def test_verbose_progress_logging( self, patched_scan, capsys ):
        """Ensures: verbose mode emits a progress line at the 500-file boundary."""
        patched_scan.scan.return_value = iter(
            [ _file_info( f"f{i}.py", [ "x = 1" ] ) for i in range( 500 ) ]
        )
        DirectoryAnalyzer( verbose=True ).analyze( "/anydir" )
        assert "Processed 500 files" in capsys.readouterr().out

    def test_debug_completion_log( self, patched_scan, capsys ):
        """Ensures: debug=True emits the 'Analysis complete' line."""
        DirectoryAnalyzer( debug=True ).analyze( "/anydir" )
        assert "Analysis complete" in capsys.readouterr().out

    def test_scan_failure_wrapped( self, patched_scan ):
        """Ensures: an exception during scanning wraps to DirectoryAnalyzerError."""
        patched_scan.scan.side_effect = RuntimeError( "walk boom" )
        with pytest.raises( DirectoryAnalyzerError ) as exc:
            DirectoryAnalyzer().analyze( "/anydir" )
        assert "Analysis failed" in str( exc.value )


class TestFormatResults:
    """format_results() dispatches to the right formatter by name."""

    @pytest.fixture
    def analyzer_with_stats( self, patched_scan ):
        """An analyzer with a small real summary + stored scan stats."""
        patched_scan.scan.return_value = iter( [ _file_info( "a.py", [ "x = 1", "# c" ] ) ] )
        analyzer = DirectoryAnalyzer()
        analyzer._stats = analyzer.analyze( "/anydir" )
        return analyzer

    def test_console( self, analyzer_with_stats ):
        """Ensures: console format returns the OVERALL SUMMARY text."""
        out = analyzer_with_stats.format_results( analyzer_with_stats._stats, "/anydir", format="console" )
        assert "OVERALL SUMMARY" in out

    def test_json( self, analyzer_with_stats ):
        """Ensures: json format returns a string containing directory."""
        out = analyzer_with_stats.format_results( analyzer_with_stats._stats, "/anydir", format="json" )
        assert "directory" in out

    def test_markdown( self, analyzer_with_stats ):
        """Ensures: markdown format returns the directory-analysis header."""
        out = analyzer_with_stats.format_results( analyzer_with_stats._stats, "/anydir", format="markdown" )
        assert "# Directory Code Analysis" in out

    def test_invalid_format_raises( self, analyzer_with_stats ):
        """Ensures: an unsupported format name raises ValueError."""
        with pytest.raises( ValueError ):
            analyzer_with_stats.format_results( analyzer_with_stats._stats, "/anydir", format="pdf" )


class TestGetScanStats:
    """get_scan_stats returns the last run's stats or an empty default."""

    def test_returns_empty_before_analyze( self, patched_scan ):
        """Ensures: with no analysis yet, get_scan_stats returns {}."""
        assert DirectoryAnalyzer().get_scan_stats() == {}

    def test_returns_last_after_analyze( self, patched_scan ):
        """Ensures: after analyze(), the stored scan stats are returned."""
        patched_scan.scan.return_value = iter( [ _file_info( "a.py", [ "x = 1" ] ) ] )
        analyzer = DirectoryAnalyzer()
        analyzer.analyze( "/anydir" )
        assert analyzer.get_scan_stats() == { "files_scanned": 0 }
