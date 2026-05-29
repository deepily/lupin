"""
Line Classifier for Branch Analyzer

Classifies individual lines as code, comment, docstring, or blank for
supported programming languages (Python, JavaScript, TypeScript).

Handles multiline constructs like Python docstrings and JavaScript
block comments. Maintains state across multiple line calls.

Design Principles:
- Stateful classification (tracks multiline constructs)
- Language-specific classifiers (easy to extend)
- Conservative classification (ambiguous → code)
- Fast simple checks before complex parsing

Usage:
    from cosa.repo.branch_analyzer.line_classifier import LineClassifier

    classifier = LineClassifier( config, debug=True )

    # Classify Python lines
    state = classifier.create_state( 'python' )
    category, state = classifier.classify_line( '# comment', 'python', state )
    # Returns: ('comment', updated_state)

    category, state = classifier.classify_line( 'x = 42', 'python', state )
    # Returns: ('code', updated_state)

    # Classify JavaScript lines
    state = classifier.create_state( 'javascript' )
    category, state = classifier.classify_line( '// comment', 'javascript', state )
    # Returns: ('comment', updated_state)
"""

from typing import Dict, Optional, Tuple

from .exceptions import ClassificationError


class LineClassifier:
    """
    Classifies lines as code, comment, docstring, or blank.

    Supports Python, JavaScript, and TypeScript with stateful
    multiline construct tracking.
    """

    def __init__( self, config: Dict, debug: bool = False, verbose: bool = False ):
        """
        Initialize line classifier.

        Requires:
            - config is dict with 'analysis' section
            - debug is boolean
            - verbose is boolean

        Ensures:
            - Classifier initialized and ready to classify lines
            - Supported languages determined from config

        Raises:
            - ClassificationError if config invalid
        """
        self.debug   = debug
        self.verbose = verbose
        self.config  = config

        # Get supported languages from config
        self.supported_languages = config.get( 'analysis', {} ).get(
            'supported_languages',
            ['python', 'javascript', 'typescript']
        )

        if self.debug:
            print( f"[LineClassifier] Supported languages: {', '.join(self.supported_languages)}" )

    def create_state( self, language: str ) -> Dict:
        """
        Create initial state for language.

        Requires:
            - language is non-empty string

        Ensures:
            - Returns state dict for tracking multiline constructs
            - State contains language-specific tracking fields

        Raises:
            - Never raises (returns empty state for unknown languages)
        """
        if language == 'python':
            return {
                'in_docstring'         : False,
                'docstring_delimiter'  : None,  # """ or '''
                'language'             : 'python'
            }
        elif language in ['javascript', 'typescript']:
            return {
                'in_block_comment' : False,
                'language'         : language
            }
        else:
            return { 'language': language }

    def classify_line( self, line: str, language: str, state: Dict ) -> Tuple[str, Dict]:
        """
        Classify single line and update state.

        Requires:
            - line is string (may be empty)
            - language is non-empty string
            - state is dict from create_state() or previous classify_line()

        Ensures:
            - Returns tuple (category, updated_state)
            - category is one of: 'code', 'comment', 'docstring', 'blank', None
            - state updated with multiline construct tracking

        Raises:
            - Never raises (returns ('code', state) for errors)
        """
        stripped = line.strip()

        # Empty/blank lines
        if not stripped:
            return ( None, state )

        # Dispatch to language-specific classifier
        if language == 'python':
            return self._classify_python_line( line, stripped, state )
        elif language in ['javascript', 'typescript']:
            return self._classify_javascript_line( line, stripped, state )
        else:
            # Unknown language - treat everything as code
            return ( 'code', state )

    def _classify_python_line( self, line: str, stripped: str, state: Dict ) -> Tuple[str, Dict]:
        """
        Classify Python line.

        Handles:
        - Single-line comments (#)
        - Docstrings (triple quotes)
        - Multiline docstrings
        - Code lines

        Requires:
            - line is full line string
            - stripped is stripped line
            - state contains Python state fields

        Ensures:
            - Returns (category, updated_state)
            - category is 'comment', 'docstring', 'code', or None

        Raises:
            - Never raises
        """
        # Check if we're currently in a docstring
        if state.get( 'in_docstring', False ):
            delimiter = state.get( 'docstring_delimiter' )

            # Check if this line ends the docstring
            if delimiter and delimiter in stripped:
                # Line contains closing delimiter
                state['in_docstring'] = False
                state['docstring_delimiter'] = None
                return ( 'docstring', state )
            else:
                # Still inside docstring
                return ( 'docstring', state )

        # Single-line comment
        if stripped.startswith( '#' ):
            return ( 'comment', state )

        # Check for docstring start
        if '"""' in stripped or "'''" in stripped:
            # Determine delimiter
            if '"""' in stripped:
                delimiter = '"""'
            else:
                delimiter = "'''"

            # Count occurrences to determine if it's single-line or multiline
            count = stripped.count( delimiter )

            if count >= 2:
                # Single-line docstring (e.g., """docstring""")
                return ( 'docstring', state )
            elif count == 1:
                # Start of multiline docstring
                state['in_docstring'] = True
                state['docstring_delimiter'] = delimiter
                return ( 'docstring', state )

        # Default to code
        return ( 'code', state )

    def _classify_javascript_line( self, line: str, stripped: str, state: Dict ) -> Tuple[str, Dict]:
        """
        Classify JavaScript/TypeScript line.

        Handles:
        - Single-line comments (//)
        - Block comments (/* */)
        - Multiline block comments
        - Code lines

        Requires:
            - line is full line string
            - stripped is stripped line
            - state contains JavaScript state fields

        Ensures:
            - Returns (category, updated_state)
            - category is 'comment', 'code', or None

        Raises:
            - Never raises
        """
        # Check if we're currently in a block comment
        if state.get( 'in_block_comment', False ):
            # Check if this line ends the block comment
            if '*/' in stripped:
                state['in_block_comment'] = False
                return ( 'comment', state )
            else:
                # Still inside block comment
                return ( 'comment', state )

        # Single-line comment
        if stripped.startswith( '//' ):
            return ( 'comment', state )

        # Block comment markers
        if stripped.startswith( '/*' ) or stripped.startswith( '*' ):
            # Check if it's a complete block comment on one line
            if '/*' in stripped and '*/' in stripped:
                # Single-line block comment
                return ( 'comment', state )
            elif stripped.startswith( '/*' ):
                # Start of multiline block comment
                state['in_block_comment'] = True
                return ( 'comment', state )
            elif stripped.startswith( '*' ):
                # Likely continuation of block comment
                # (Conservative: treat as comment if starts with *)
                return ( 'comment', state )

        # Check for inline block comment start (not at beginning of line)
        if '/*' in stripped and not stripped.startswith( '/*' ):
            # Could be code with inline comment like: x = 42; /* comment */
            # Conservative: treat as code if not at start
            return ( 'code', state )

        # Default to code
        return ( 'code', state )

    def supports_language( self, language: str ) -> bool:
        """
        Check if language is supported for code/comment separation.

        Requires:
            - language is non-empty string

        Ensures:
            - Returns True if language supported
            - Returns False otherwise

        Raises:
            - Never raises
        """
        return language in self.supported_languages

    def get_supported_languages( self ) -> list:
        """
        Get list of supported languages.

        Ensures:
            - Returns list of language names

        Raises:
            - Never raises
        """
        return self.supported_languages.copy()
