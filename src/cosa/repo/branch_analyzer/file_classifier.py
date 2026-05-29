"""
File Type Classifier for Branch Analyzer

Classifies files by extension into categories for grouping statistics.
Uses configuration-driven mappings for extensibility.

Design Principles:
- Configuration-driven (no hardcoded mappings)
- Fast lookup (uses dict internally)
- Unknown extensions map to 'other' category
- Case-insensitive extension matching

Usage:
    from cosa.repo.branch_analyzer.file_classifier import FileTypeClassifier

    classifier = FileTypeClassifier( config, debug=True )

    file_type = classifier.classify( 'test.py' )
    # Returns: 'python'

    file_type = classifier.classify( 'README.MD' )
    # Returns: 'markdown' (case-insensitive)

    file_type = classifier.classify( 'weird.xyz' )
    # Returns: 'other' (unknown extension)
"""

from pathlib import Path
from typing import Dict, Optional

from .exceptions import ClassificationError


class FileTypeClassifier:
    """
    Classifies files by extension into categories.

    Uses configuration-driven extension-to-category mappings.
    Unknown extensions default to 'other' category.
    """

    def __init__( self, config: Dict, debug: bool = False, verbose: bool = False ):
        """
        Initialize file type classifier.

        Requires:
            - config is dict with 'file_types.extensions' section
            - debug is boolean
            - verbose is boolean

        Ensures:
            - Classifier initialized with extension mappings
            - Extension lookup is case-insensitive

        Raises:
            - ClassificationError if config missing required section
        """
        self.debug   = debug
        self.verbose = verbose

        # Extract extension mappings from config
        try:
            self.extension_map = config['file_types']['extensions']
        except KeyError as e:
            raise ClassificationError(
                message         = "Configuration missing file_types.extensions section",
                classifier_type = "file"
            )

        # Validate that mappings is a dict
        if not isinstance( self.extension_map, dict ):
            raise ClassificationError(
                message         = "file_types.extensions must be a dictionary",
                classifier_type = "file"
            )

        # Convert all extensions to lowercase for case-insensitive matching
        self.extension_map = {
            ext.lower(): category
            for ext, category in self.extension_map.items()
        }

        if self.debug:
            print( f"[FileTypeClassifier] Loaded {len(self.extension_map)} extension mappings" )

    def classify( self, filename: str ) -> str:
        """
        Classify file by extension.

        Requires:
            - filename is non-empty string

        Ensures:
            - Returns file type category (str)
            - Returns 'other' for unknown extensions
            - Returns 'other' for files with no extension
            - Returns 'other' for /dev/null (git diff convention)

        Raises:
            - Never raises (always returns valid category)
        """
        # Handle special git diff filenames
        if not filename or filename == '/dev/null':
            return 'other'

        # Extract extension using pathlib
        try:
            ext = Path( filename ).suffix.lower()
        except Exception as e:
            if self.debug:
                print( f"[FileTypeClassifier] Error extracting extension from {filename}: {e}" )
            return 'other'

        # Handle files with no extension
        if not ext:
            return 'other'

        # Lookup extension in mapping
        category = self.extension_map.get( ext, 'other' )

        if self.verbose and category == 'other' and ext:
            print( f"[FileTypeClassifier] Unknown extension '{ext}' in {filename}" )

        return category

    def get_extension( self, filename: str ) -> Optional[str]:
        """
        Extract file extension.

        Requires:
            - filename is non-empty string

        Ensures:
            - Returns lowercase extension with dot (e.g., '.py')
            - Returns None if no extension

        Raises:
            - Never raises
        """
        if not filename or filename == '/dev/null':
            return None

        try:
            ext = Path( filename ).suffix.lower()
            return ext if ext else None
        except Exception:
            return None

    def is_binary( self, filename: str ) -> bool:
        """
        Check if file is classified as binary.

        Requires:
            - filename is non-empty string

        Ensures:
            - Returns True if file classified as 'binary'
            - Returns False otherwise

        Raises:
            - Never raises
        """
        return self.classify( filename ) == 'binary'

    def get_all_extensions( self ) -> Dict[str, str]:
        """
        Get all extension mappings.

        Ensures:
            - Returns copy of extension map dict
            - Caller cannot modify internal mappings

        Raises:
            - Never raises
        """
        return self.extension_map.copy()

    def get_categories( self ) -> set:
        """
        Get all file type categories.

        Ensures:
            - Returns set of unique category names
            - Includes 'other' category

        Raises:
            - Never raises
        """
        categories = set( self.extension_map.values() )
        categories.add( 'other' )  # Always include 'other' as possible category
        return categories

    def add_extension( self, extension: str, category: str ) -> None:
        """
        Add or update extension mapping (runtime configuration).

        Requires:
            - extension is non-empty string starting with '.'
            - category is non-empty string

        Ensures:
            - Extension added to mapping (lowercase)
            - Existing mapping overwritten if present

        Raises:
            - ClassificationError if extension invalid format
        """
        if not extension or not extension.startswith( '.' ):
            raise ClassificationError(
                message         = f"Extension must start with '.': {extension}",
                classifier_type = "file"
            )

        if not category:
            raise ClassificationError(
                message         = f"Category cannot be empty for extension {extension}",
                classifier_type = "file"
            )

        self.extension_map[extension.lower()] = category

        if self.debug:
            print( f"[FileTypeClassifier] Added mapping: {extension.lower()} → {category}" )
