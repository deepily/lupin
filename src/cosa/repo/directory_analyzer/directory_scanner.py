"""
Directory Scanner for Directory Analyzer

Walks directory tree and yields file contents for analysis. Handles exclusions,
binary detection, encoding issues, and progress reporting.

Design Principles:
- Configuration-driven exclusions (directories and file patterns)
- Generator-based yielding (memory efficient for large directories)
- Graceful handling of encoding errors and permission issues
- Progress callbacks for verbose mode

Usage:
    from cosa.repo.directory_analyzer.directory_scanner import DirectoryScanner

    scanner = DirectoryScanner( config, debug=True )

    for file_info in scanner.scan( '/path/to/project' ):
        print( f"{file_info.path}: {file_info.line_count} lines" )

    # Get scan statistics
    stats = scanner.get_scan_stats()
    print( f"Scanned: {stats['files_scanned']}, Skipped: {stats['files_skipped']}" )
"""

import os
import fnmatch
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterator, List, Optional

from .exceptions import ScannerError, FileReadError


@dataclass
class FileInfo:
    """
    Information about a scanned file.

    Attributes:
        path: Absolute path to the file
        relative_path: Path relative to scan root
        lines: List of line contents
        line_count: Number of lines in file
        size_bytes: File size in bytes
        encoding: Encoding used to read the file
    """
    path          : str
    relative_path : str
    lines         : List[str]
    line_count    : int
    size_bytes    : int
    encoding      : str


class DirectoryScanner:
    """
    Walks directory tree and yields file contents for analysis.

    Handles configurable exclusions, binary detection, encoding
    issues, and provides progress reporting.
    """

    def __init__( self, config: Dict, debug: bool = False, verbose: bool = False ):
        """
        Initialize directory scanner.

        Requires:
            - config is dict with 'directory' section
            - debug is boolean
            - verbose is boolean

        Ensures:
            - Scanner initialized with exclusion patterns
            - Ready to scan directories

        Raises:
            - ScannerError if config missing required section
        """
        self.debug   = debug
        self.verbose = verbose
        self.config  = config

        # Extract directory settings
        dir_config = config.get( 'directory', {} )

        self.exclude_dirs    = set( dir_config.get( 'exclude_dirs', [] ) )
        self.exclude_files   = dir_config.get( 'exclude_files', [] )
        self.max_file_size   = dir_config.get( 'max_file_size', 1048576 )  # 1MB default
        self.follow_symlinks = dir_config.get( 'follow_symlinks', False )
        self.encodings       = dir_config.get( 'encodings', ['utf-8', 'latin-1'] )

        # Extract file type mappings for binary detection
        file_types = config.get( 'file_types', {} )
        self.extension_map = file_types.get( 'extensions', {} )

        # Convert to lowercase for case-insensitive matching
        self.extension_map = {
            ext.lower(): category
            for ext, category in self.extension_map.items()
        }

        # Scan statistics
        self._reset_stats()

        if self.debug:
            print( f"[DirectoryScanner] Exclude dirs: {len(self.exclude_dirs)}" )
            print( f"[DirectoryScanner] Exclude patterns: {len(self.exclude_files)}" )
            print( f"[DirectoryScanner] Max file size: {self.max_file_size:,} bytes" )

    def scan( self, root_path: str ) -> Iterator[FileInfo]:
        """
        Scan directory tree and yield file information.

        Requires:
            - root_path is valid directory path

        Ensures:
            - Yields FileInfo for each readable file
            - Skips excluded directories and files
            - Handles encoding errors gracefully
            - Updates scan statistics

        Raises:
            - ScannerError if root_path is not a valid directory
        """
        # Validate root path
        root = Path( root_path ).resolve()

        if not root.exists():
            raise ScannerError(
                message = f"Directory does not exist: {root_path}",
                path    = str( root )
            )

        if not root.is_dir():
            raise ScannerError(
                message = f"Path is not a directory: {root_path}",
                path    = str( root )
            )

        # Reset statistics for new scan
        self._reset_stats()
        self._scan_root = root

        if self.debug:
            print( f"[DirectoryScanner] Starting scan: {root}" )

        # Walk directory tree
        for file_path in self._walk( root ):
            file_info = self._process_file( file_path )

            if file_info is not None:
                self._stats['files_scanned'] += 1
                self._stats['total_lines'] += file_info.line_count
                self._stats['total_bytes'] += file_info.size_bytes
                yield file_info

                if self.verbose and self._stats['files_scanned'] % 100 == 0:
                    print( f"[DirectoryScanner] Scanned {self._stats['files_scanned']} files..." )

        if self.debug:
            print( f"[DirectoryScanner] Scan complete: {self._stats['files_scanned']} files" )

    def _walk( self, root: Path ) -> Iterator[Path]:
        """
        Walk directory tree, respecting exclusions.

        Requires:
            - root is Path object to existing directory

        Ensures:
            - Yields Path for each file (not directory)
            - Excludes configured directories
            - Respects follow_symlinks setting

        Raises:
            - Never raises (logs errors if debug enabled)
        """
        try:
            for entry in os.scandir( root ):
                try:
                    if entry.is_dir( follow_symlinks=self.follow_symlinks ):
                        # Check if directory should be excluded
                        if entry.name in self.exclude_dirs:
                            self._stats['dirs_skipped'] += 1
                            if self.verbose:
                                print( f"[DirectoryScanner] Skipping excluded dir: {entry.name}" )
                            continue

                        # Recursively walk subdirectory
                        yield from self._walk( Path( entry.path ) )

                    elif entry.is_file( follow_symlinks=self.follow_symlinks ):
                        yield Path( entry.path )

                except PermissionError as e:
                    self._stats['errors'] += 1
                    if self.debug:
                        print( f"[DirectoryScanner] Permission denied: {entry.path}" )

                except OSError as e:
                    self._stats['errors'] += 1
                    if self.debug:
                        print( f"[DirectoryScanner] OS error: {entry.path} - {e}" )

        except PermissionError as e:
            self._stats['errors'] += 1
            if self.debug:
                print( f"[DirectoryScanner] Permission denied scanning: {root}" )

        except OSError as e:
            self._stats['errors'] += 1
            if self.debug:
                print( f"[DirectoryScanner] OS error scanning: {root} - {e}" )

    def _process_file( self, file_path: Path ) -> Optional[FileInfo]:
        """
        Process a single file and return FileInfo.

        Requires:
            - file_path is Path to existing file

        Ensures:
            - Returns FileInfo if file can be read
            - Returns None if file should be skipped
            - Updates skip statistics appropriately

        Raises:
            - Never raises (returns None on errors)
        """
        # Check file pattern exclusions
        if self._should_exclude_file( file_path ):
            self._stats['files_skipped'] += 1
            return None

        # Check if binary file
        if self._is_binary( file_path ):
            self._stats['binary_files_skipped'] += 1
            return None

        # Check file size
        try:
            file_size = file_path.stat().st_size
        except OSError as e:
            self._stats['errors'] += 1
            if self.debug:
                print( f"[DirectoryScanner] Cannot stat file: {file_path} - {e}" )
            return None

        if file_size > self.max_file_size:
            self._stats['large_files_skipped'] += 1
            if self.verbose:
                print( f"[DirectoryScanner] Skipping large file ({file_size:,} bytes): {file_path.name}" )
            return None

        if file_size == 0:
            # Empty file - still include but with 0 lines
            return FileInfo(
                path          = str( file_path ),
                relative_path = str( file_path.relative_to( self._scan_root ) ),
                lines         = [],
                line_count    = 0,
                size_bytes    = 0,
                encoding      = 'utf-8'
            )

        # Try to read file
        lines, encoding = self._read_file( file_path )

        if lines is None:
            self._stats['unreadable_files_skipped'] += 1
            return None

        return FileInfo(
            path          = str( file_path ),
            relative_path = str( file_path.relative_to( self._scan_root ) ),
            lines         = lines,
            line_count    = len( lines ),
            size_bytes    = file_size,
            encoding      = encoding
        )

    def _should_exclude_file( self, file_path: Path ) -> bool:
        """
        Check if file should be excluded based on patterns.

        Requires:
            - file_path is Path object

        Ensures:
            - Returns True if file matches any exclusion pattern
            - Returns False otherwise

        Raises:
            - Never raises
        """
        filename = file_path.name

        for pattern in self.exclude_files:
            if fnmatch.fnmatch( filename, pattern ):
                return True

        return False

    def _is_binary( self, file_path: Path ) -> bool:
        """
        Check if file is classified as binary.

        Requires:
            - file_path is Path object

        Ensures:
            - Returns True if file extension maps to 'binary'
            - Returns False otherwise

        Raises:
            - Never raises
        """
        ext = file_path.suffix.lower()

        if not ext:
            return False

        return self.extension_map.get( ext, 'other' ) == 'binary'

    def _read_file( self, file_path: Path ) -> tuple:
        """
        Read file contents trying multiple encodings.

        Requires:
            - file_path is Path to existing file

        Ensures:
            - Returns (lines, encoding) if successful
            - Returns (None, None) if file cannot be read

        Raises:
            - Never raises (catches all exceptions)
        """
        for encoding in self.encodings:
            try:
                with open( file_path, 'r', encoding=encoding ) as f:
                    content = f.read()

                # Split into lines (preserving line count accuracy)
                lines = content.splitlines()

                return ( lines, encoding )

            except UnicodeDecodeError:
                # Try next encoding
                continue

            except Exception as e:
                if self.debug:
                    print( f"[DirectoryScanner] Error reading {file_path}: {e}" )
                return ( None, None )

        # No encoding worked - likely binary or corrupted
        if self.debug:
            print( f"[DirectoryScanner] Cannot decode file: {file_path}" )

        return ( None, None )

    def _reset_stats( self ) -> None:
        """Reset scan statistics."""
        self._stats = {
            'files_scanned'          : 0,
            'files_skipped'          : 0,
            'dirs_skipped'           : 0,
            'binary_files_skipped'   : 0,
            'large_files_skipped'    : 0,
            'unreadable_files_skipped' : 0,
            'total_lines'            : 0,
            'total_bytes'            : 0,
            'errors'                 : 0
        }
        self._scan_root = None

    def get_scan_stats( self ) -> Dict:
        """
        Get scan statistics.

        Ensures:
            - Returns dict with scan statistics
            - All counts are non-negative integers

        Raises:
            - Never raises
        """
        return self._stats.copy()
