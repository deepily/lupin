"""
Unit tests for cosa.repo.directory_analyzer.directory_scanner.

Tests the FileInfo dataclass and DirectoryScanner, which walks a real
filesystem tree yielding readable text files while honoring directory/pattern
exclusions, binary detection, size limits, and multi-encoding reads. Most
tests build a real tree under pytest's tmp_path (the honest way to exercise a
filesystem walker, including a cross-tree scan target OUTSIDE the project);
error paths (permission/OS errors, undecodable files) are driven via targeted
mocks.

Part of the CoSA 100% coverage campaign (repo module group).
"""
import os
from pathlib import Path
from unittest import mock

import pytest

from cosa.repo.directory_analyzer.directory_scanner import DirectoryScanner, FileInfo
from cosa.repo.directory_analyzer.exceptions import ScannerError


def _config( **overrides ):
    """
    Build a scanner config with sane test defaults.

    Ensures:
        - a 'directory' section + a 'file_types.extensions' map (with .png→binary)
        - any key in overrides replaces the matching directory-section default
    """
    directory = {
        "exclude_dirs"   : [ ".git", "node_modules" ],
        "exclude_files"  : [ "*.lock" ],
        "max_file_size"  : 1_048_576,
        "follow_symlinks": False,
        "encodings"      : [ "utf-8", "latin-1" ],
    }
    directory.update( overrides )
    return {
        "directory" : directory,
        "file_types": { "extensions": { ".py": "python", ".png": "binary" } },
    }


@pytest.fixture
def scanner():
    """A DirectoryScanner with default test config."""
    return DirectoryScanner( _config() )


class TestFileInfo:
    """FileInfo carries the per-file scan result."""

    def test_fields_round_trip( self ):
        """Ensures: all six dataclass fields store and read back."""
        fi = FileInfo(
            path="/a/b.py", relative_path="b.py",
            lines=[ "x = 1" ], line_count=1, size_bytes=5, encoding="utf-8",
        )
        assert fi.path == "/a/b.py"
        assert fi.relative_path == "b.py"
        assert fi.lines == [ "x = 1" ]
        assert fi.line_count == 1
        assert fi.size_bytes == 5
        assert fi.encoding == "utf-8"


class TestInit:
    """Construction reads exclusion/size/encoding knobs + folds extensions."""

    def test_defaults_and_extension_folding( self ):
        """
        Ensures:
            - exclude_dirs becomes a set; exclude_files a list
            - extension map keys are lowercased for case-insensitive lookup
        """
        s = DirectoryScanner( _config() )
        assert s.exclude_dirs == { ".git", "node_modules" }
        assert s.exclude_files == [ "*.lock" ]
        assert ".py" in s.extension_map
        assert s.max_file_size == 1_048_576

    def test_debug_init_logs( self, capsys ):
        """Ensures: debug=True emits the exclude/size summary lines."""
        DirectoryScanner( _config(), debug=True )
        out = capsys.readouterr().out
        assert "Exclude dirs" in out
        assert "Max file size" in out


class TestScanValidation:
    """scan() validates the root path before walking."""

    def test_missing_root_raises_scanner_error( self, scanner, tmp_path ):
        """Ensures: a nonexistent root raises ScannerError."""
        with pytest.raises( ScannerError ):
            list( scanner.scan( str( tmp_path / "nope" ) ) )

    def test_non_directory_root_raises_scanner_error( self, scanner, tmp_path ):
        """Ensures: a root that is a file (not a dir) raises ScannerError."""
        f = tmp_path / "afile.py"
        f.write_text( "x = 1\n" )
        with pytest.raises( ScannerError ):
            list( scanner.scan( str( f ) ) )


class TestScanRealTree:
    """scan() over a real tmp_path tree (the honest filesystem exercise)."""

    def test_yields_text_files_and_skips_exclusions( self, scanner, tmp_path ):
        """
        Ensures:
            - readable text files are yielded with correct relative paths + lines
            - excluded dirs (.git) are not descended
            - pattern-excluded files (*.lock) are skipped
            - binary-by-extension files (.png) are skipped
        """
        ( tmp_path / "a.py" ).write_text( "x = 1\ny = 2\n" )
        ( tmp_path / "keep.lock" ).write_text( "nope\n" )       # pattern-excluded
        ( tmp_path / "img.png" ).write_bytes( b"\x89PNG\r\n" )  # binary by ext
        sub = tmp_path / "pkg"
        sub.mkdir()
        ( sub / "b.py" ).write_text( "z = 3\n" )
        git = tmp_path / ".git"
        git.mkdir()
        ( git / "config" ).write_text( "secret\n" )             # excluded dir

        results = list( scanner.scan( str( tmp_path ) ) )
        rel = { fi.relative_path for fi in results }
        assert "a.py" in rel
        assert os.path.join( "pkg", "b.py" ) in rel
        assert "keep.lock" not in rel
        assert "img.png" not in rel
        assert not any( ".git" in r for r in rel )

        stats = scanner.get_scan_stats()
        assert stats[ "files_scanned" ] == 2
        assert stats[ "files_skipped" ] >= 1            # the .lock
        assert stats[ "binary_files_skipped" ] >= 1     # the .png
        assert stats[ "dirs_skipped" ] >= 1             # the .git

    def test_cross_tree_scan_outside_project( self, scanner, tmp_path ):
        """
        Ensures (cross-target invocation, per the campaign mandate):
            - a scan root that is an isolated tmp dir OUTSIDE the project tree
              resolves and yields its files with correct relative paths
        """
        ( tmp_path / "lonely.py" ).write_text( "a = 1\n" )
        results = list( scanner.scan( str( tmp_path ) ) )
        assert [ fi.relative_path for fi in results ] == [ "lonely.py" ]

    def test_empty_file_yielded_with_zero_lines( self, scanner, tmp_path ):
        """Ensures: a zero-byte file is yielded with line_count 0 (not skipped)."""
        ( tmp_path / "empty.py" ).write_text( "" )
        results = list( scanner.scan( str( tmp_path ) ) )
        assert len( results ) == 1
        assert results[ 0 ].line_count == 0
        assert results[ 0 ].size_bytes == 0

    def test_large_file_skipped( self, tmp_path ):
        """Ensures: a file exceeding max_file_size is skipped + counted."""
        s = DirectoryScanner( _config( max_file_size=10 ) )
        ( tmp_path / "big.py" ).write_text( "x = 1\n" * 100 )
        results = list( s.scan( str( tmp_path ) ) )
        assert results == []
        assert s.get_scan_stats()[ "large_files_skipped" ] == 1

    def test_verbose_progress_at_100_file_boundary( self, scanner, tmp_path, capsys ):
        """
        Ensures:
            - verbose mode prints a progress line at the 100-file boundary
              (drives the `files_scanned % 100 == 0` branch deterministically)

        Uses 150 files so the boundary lands MID-stream: the progress print
        sits after `yield`, so it only executes when the consumer resumes the
        generator for the next item — guaranteed when files remain after the
        boundary (exactly-100 would put it on the terminal element).
        """
        scanner.verbose = True
        for i in range( 150 ):
            ( tmp_path / f"f{i:04d}.py" ).write_text( "x = 1\n" )
        list( scanner.scan( str( tmp_path ) ) )
        assert "Scanned 100 files" in capsys.readouterr().out


class TestProcessFileErrors:
    """_process_file / _read_file error + skip paths via targeted mocks."""

    def test_stat_oserror_returns_none( self, scanner, tmp_path ):
        """Ensures: if stat() raises OSError, the file is skipped (errors++), None returned."""
        f = tmp_path / "a.py"
        f.write_text( "x = 1\n" )
        with mock.patch.object( Path, "stat", side_effect=OSError( "boom" ) ):
            assert scanner._process_file( f ) is None
        assert scanner.get_scan_stats()[ "errors" ] >= 1

    def test_unreadable_file_skipped( self, scanner, tmp_path ):
        """
        Ensures:
            - when _read_file returns (None, None), the file is counted as
              unreadable and skipped

        Driven through the public scan() (which sets _scan_root itself) with a
        class-level _read_file patch, so the test is order-independent.
        """
        ( tmp_path / "a.py" ).write_text( "x = 1\n" )
        with mock.patch.object( DirectoryScanner, "_read_file", return_value=( None, None ) ):
            results = list( scanner.scan( str( tmp_path ) ) )
        assert results == []
        assert scanner.get_scan_stats()[ "unreadable_files_skipped" ] == 1

    def test_read_file_tries_second_encoding_on_unicode_error( self, scanner, tmp_path ):
        """
        Ensures:
            - a UnicodeDecodeError on the first encoding falls through to the
              next encoding (latin-1), which succeeds
        """
        f = tmp_path / "a.txt"
        f.write_bytes( b"caf\xe9\n" )   # valid latin-1, invalid utf-8
        lines, encoding = scanner._read_file( f )
        assert encoding == "latin-1"
        assert lines == [ "caf\xe9" ]

    def test_read_file_generic_error_returns_none_pair( self, scanner, tmp_path ):
        """Ensures: a non-UnicodeDecodeError during read returns (None, None) (generic-except arc)."""
        f = tmp_path / "a.py"
        f.write_text( "x = 1\n" )
        with mock.patch( "builtins.open", side_effect=OSError( "boom" ) ):
            assert scanner._read_file( f ) == ( None, None )

    def test_read_file_all_encodings_fail_returns_none_pair( self, tmp_path ):
        """
        Ensures:
            - if every configured encoding raises UnicodeDecodeError, the read
              returns (None, None) (the loop-exhausted arc)
        """
        s = DirectoryScanner( _config( encodings=[ "utf-8" ] ) )
        f = tmp_path / "a.txt"
        f.write_bytes( b"\xff\xfe\x00" )
        assert s._read_file( f ) == ( None, None )


class TestIsBinaryAndExclude:
    """Helper predicates for binary detection + pattern exclusion."""

    def test_is_binary_true_for_binary_extension( self, scanner ):
        """Ensures: a .png (mapped to binary) is detected as binary."""
        assert scanner._is_binary( Path( "x.png" ) ) is True

    def test_is_binary_false_for_text_and_extensionless( self, scanner ):
        """Ensures: text + extension-less files are not binary."""
        assert scanner._is_binary( Path( "x.py" ) ) is False
        assert scanner._is_binary( Path( "Makefile" ) ) is False

    def test_should_exclude_file_matches_pattern( self, scanner ):
        """Ensures: a filename matching an exclude pattern is excluded."""
        assert scanner._should_exclude_file( Path( "deps.lock" ) ) is True
        assert scanner._should_exclude_file( Path( "main.py" ) ) is False


class TestWalkErrorHandling:
    """_walk tolerates permission/OS errors during traversal."""

    def test_scandir_permission_error_counted( self, scanner, tmp_path ):
        """Ensures: a PermissionError from os.scandir on the root is swallowed + counted."""
        with mock.patch(
            "cosa.repo.directory_analyzer.directory_scanner.os.scandir",
            side_effect=PermissionError( "denied" ),
        ):
            assert list( scanner._walk( tmp_path ) ) == []
        assert scanner.get_scan_stats()[ "errors" ] >= 1

    def test_scandir_oserror_counted( self, scanner, tmp_path ):
        """Ensures: an OSError from os.scandir is swallowed + counted."""
        with mock.patch(
            "cosa.repo.directory_analyzer.directory_scanner.os.scandir",
            side_effect=OSError( "boom" ),
        ):
            assert list( scanner._walk( tmp_path ) ) == []
        assert scanner.get_scan_stats()[ "errors" ] >= 1

    def test_entry_permission_error_skips_entry( self, scanner, tmp_path ):
        """
        Ensures:
            - a PermissionError while classifying a single entry is swallowed
              + counted, and the walk continues (per-entry try/except arc)
        """
        entry = mock.Mock()
        entry.name = "a.py"
        entry.path = str( tmp_path / "a.py" )
        entry.is_dir.side_effect = PermissionError( "denied" )

        with mock.patch(
            "cosa.repo.directory_analyzer.directory_scanner.os.scandir",
            return_value=iter( [ entry ] ),
        ):
            assert list( scanner._walk( tmp_path ) ) == []
        assert scanner.get_scan_stats()[ "errors" ] >= 1

    def test_entry_neither_dir_nor_file_is_skipped( self, scanner, tmp_path ):
        """
        Ensures:
            - an entry that is NEITHER a directory NOR a regular file (e.g. a
              FIFO / socket / broken symlink) is silently skipped and the loop
              continues (the 194->181 fall-through: is_dir() False AND
              is_file() False → neither yielded nor descended)
        """
        entry = mock.Mock()
        entry.name = "weird.sock"
        entry.path = str( tmp_path / "weird.sock" )
        entry.is_dir.return_value = False
        entry.is_file.return_value = False

        with mock.patch(
            "cosa.repo.directory_analyzer.directory_scanner.os.scandir",
            return_value=iter( [ entry ] ),
        ):
            assert list( scanner._walk( tmp_path ) ) == []
        # not counted as an error — it's a clean skip
        assert scanner.get_scan_stats()[ "errors" ] == 0

    def test_entry_oserror_skips_entry( self, scanner, tmp_path ):
        """
        Ensures:
            - an OSError while classifying a single entry is swallowed + counted
              (the per-entry OSError arc, distinct from PermissionError)
        """
        entry = mock.Mock()
        entry.name = "a.py"
        entry.path = str( tmp_path / "a.py" )
        entry.is_dir.side_effect = OSError( "boom" )

        with mock.patch(
            "cosa.repo.directory_analyzer.directory_scanner.os.scandir",
            return_value=iter( [ entry ] ),
        ):
            assert list( scanner._walk( tmp_path ) ) == []
        assert scanner.get_scan_stats()[ "errors" ] >= 1


class TestGetScanStats:
    """get_scan_stats returns a defensive copy of the running counters."""

    def test_returns_copy( self, scanner ):
        """Ensures: mutating the returned stats does not corrupt internal state."""
        snapshot = scanner.get_scan_stats()
        snapshot[ "files_scanned" ] = 999
        assert scanner.get_scan_stats()[ "files_scanned" ] == 0


@pytest.fixture
def dscanner():
    """A debug+verbose DirectoryScanner (drives all the logging branches)."""
    return DirectoryScanner( _config(), debug=True, verbose=True )


class TestDebugVerboseLogging:
    """Every debug/verbose print branch executed with logging enabled.

    These mirror the behavioural tests above but run under debug=True +
    verbose=True so the `if self.debug:` / `if self.verbose:` print arcs in
    scan / _walk / _process_file / _read_file actually execute. The behaviour
    asserted is identical; the added value is exercising the operator-facing
    diagnostic output paths.
    """

    def test_scan_start_and_complete_debug_lines( self, dscanner, tmp_path, capsys ):
        """Ensures: debug emits the 'Starting scan' + 'Scan complete' lines."""
        ( tmp_path / "a.py" ).write_text( "x = 1\n" )
        list( dscanner.scan( str( tmp_path ) ) )
        out = capsys.readouterr().out
        assert "Starting scan" in out
        assert "Scan complete" in out

    def test_excluded_dir_verbose_line( self, dscanner, tmp_path, capsys ):
        """Ensures: verbose emits the 'Skipping excluded dir' line for .git."""
        ( tmp_path / "a.py" ).write_text( "x = 1\n" )
        git = tmp_path / ".git"
        git.mkdir()
        ( git / "cfg" ).write_text( "x\n" )
        list( dscanner.scan( str( tmp_path ) ) )
        assert "Skipping excluded dir" in capsys.readouterr().out

    def test_large_file_verbose_line( self, tmp_path, capsys ):
        """Ensures: verbose emits the 'Skipping large file' line."""
        s = DirectoryScanner( _config( max_file_size=10 ), debug=True, verbose=True )
        ( tmp_path / "big.py" ).write_text( "x = 1\n" * 100 )
        list( s.scan( str( tmp_path ) ) )
        assert "Skipping large file" in capsys.readouterr().out

    def test_stat_oserror_debug_line( self, dscanner, tmp_path, capsys ):
        """Ensures: debug emits 'Cannot stat file' when stat() raises OSError."""
        f = tmp_path / "a.py"
        f.write_text( "x = 1\n" )
        dscanner._scan_root = tmp_path
        with mock.patch.object( Path, "stat", side_effect=OSError( "boom" ) ):
            assert dscanner._process_file( f ) is None
        assert "Cannot stat file" in capsys.readouterr().out

    def test_scandir_permission_error_debug_line( self, dscanner, tmp_path, capsys ):
        """Ensures: debug emits 'Permission denied scanning' on root scandir error."""
        with mock.patch(
            "cosa.repo.directory_analyzer.directory_scanner.os.scandir",
            side_effect=PermissionError( "denied" ),
        ):
            list( dscanner._walk( tmp_path ) )
        assert "Permission denied scanning" in capsys.readouterr().out

    def test_scandir_oserror_debug_line( self, dscanner, tmp_path, capsys ):
        """Ensures: debug emits 'OS error scanning' on root scandir OSError."""
        with mock.patch(
            "cosa.repo.directory_analyzer.directory_scanner.os.scandir",
            side_effect=OSError( "boom" ),
        ):
            list( dscanner._walk( tmp_path ) )
        assert "OS error scanning" in capsys.readouterr().out

    def test_entry_permission_error_debug_line( self, dscanner, tmp_path, capsys ):
        """Ensures: debug emits per-entry 'Permission denied' line."""
        entry = mock.Mock()
        entry.name = "a.py"
        entry.path = str( tmp_path / "a.py" )
        entry.is_dir.side_effect = PermissionError( "denied" )
        with mock.patch(
            "cosa.repo.directory_analyzer.directory_scanner.os.scandir",
            return_value=iter( [ entry ] ),
        ):
            list( dscanner._walk( tmp_path ) )
        assert "Permission denied:" in capsys.readouterr().out

    def test_entry_oserror_debug_line( self, dscanner, tmp_path, capsys ):
        """Ensures: debug emits per-entry 'OS error' line."""
        entry = mock.Mock()
        entry.name = "a.py"
        entry.path = str( tmp_path / "a.py" )
        entry.is_dir.side_effect = OSError( "boom" )
        with mock.patch(
            "cosa.repo.directory_analyzer.directory_scanner.os.scandir",
            return_value=iter( [ entry ] ),
        ):
            list( dscanner._walk( tmp_path ) )
        assert "OS error:" in capsys.readouterr().out

    def test_read_file_generic_error_debug_line( self, dscanner, tmp_path, capsys ):
        """Ensures: debug emits 'Error reading' on a non-Unicode read failure."""
        f = tmp_path / "a.py"
        f.write_text( "x = 1\n" )
        with mock.patch( "builtins.open", side_effect=OSError( "boom" ) ):
            assert dscanner._read_file( f ) == ( None, None )
        assert "Error reading" in capsys.readouterr().out

    def test_read_file_undecodable_debug_line( self, tmp_path, capsys ):
        """Ensures: debug emits 'Cannot decode file' when all encodings fail."""
        s = DirectoryScanner( _config( encodings=[ "utf-8" ] ), debug=True )
        f = tmp_path / "a.txt"
        f.write_bytes( b"\xff\xfe\x00" )
        assert s._read_file( f ) == ( None, None )
        assert "Cannot decode file" in capsys.readouterr().out
