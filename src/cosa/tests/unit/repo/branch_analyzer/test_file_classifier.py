"""
Unit tests for cosa.repo.branch_analyzer.file_classifier.

Tests FileTypeClassifier: configuration-driven, case-insensitive extension →
category mapping with an 'other' fallback. Coverage exercises real behaviour:
classification of known/unknown/extension-less/special filenames, the
case-insensitivity contract, config-shape validation (raising
ClassificationError), the debug/verbose logging branches, the defensive
suffix-extraction exception handlers, and the accessor/mutator helpers.

Part of the CoSA 100% coverage campaign (repo module group).
"""
from unittest import mock

import pytest

from cosa.repo.branch_analyzer.file_classifier import FileTypeClassifier
from cosa.repo.branch_analyzer.exceptions import ClassificationError


@pytest.fixture
def config():
    """
    A minimal, valid config carrying a mixed-case extension map.

    Ensures:
        - includes a binary mapping (for is_binary) and varied categories
        - includes an UPPERCASE key to prove case-folding at init
    """
    return {
        "file_types": {
            "extensions": {
                ".py"  : "python",
                ".js"  : "javascript",
                ".MD"  : "markdown",   # deliberately uppercase to test folding
                ".png" : "binary",
            }
        }
    }


@pytest.fixture
def classifier( config ):
    """A FileTypeClassifier built from the valid fixture config."""
    return FileTypeClassifier( config )


@pytest.fixture
def debug_classifier( config ):
    """A debug+verbose FileTypeClassifier (exercises logging branches)."""
    return FileTypeClassifier( config, debug=True, verbose=True )


class TestInit:
    """Construction folds keys to lowercase and validates config shape."""

    def test_extension_map_is_lowercased_at_init( self, classifier ):
        """
        Ensures:
            - every mapping key is stored lowercased (case-insensitive lookup)
            - the uppercase '.MD' fixture key is reachable as '.md'
        """
        keys = classifier.get_all_extensions().keys()
        assert all( k == k.lower() for k in keys )
        assert ".md" in keys

    def test_debug_init_logs_mapping_count( self, config, capsys ):
        """
        Ensures:
            - debug=True emits the "Loaded N extension mappings" line at init
        """
        FileTypeClassifier( config, debug=True )
        assert "extension mappings" in capsys.readouterr().out

    def test_missing_extensions_section_raises_classification_error( self ):
        """
        Ensures:
            - a config lacking file_types.extensions raises ClassificationError
            - the error is tagged as a 'file' classifier error
        """
        with pytest.raises( ClassificationError ) as exc_info:
            FileTypeClassifier( { "file_types": {} } )
        assert exc_info.value.classifier_type == "file"

    def test_non_dict_extensions_raises_classification_error( self ):
        """
        Ensures:
            - file_types.extensions that is not a dict raises ClassificationError
        """
        with pytest.raises( ClassificationError ):
            FileTypeClassifier( { "file_types": { "extensions": [ ".py" ] } } )


class TestClassify:
    """classify() maps a filename to its category, defaulting to 'other'."""

    def test_known_extension_maps_to_category( self, classifier ):
        """Ensures: a known extension resolves to its configured category."""
        assert classifier.classify( "module.py" ) == "python"
        assert classifier.classify( "app.js" ) == "javascript"

    def test_classification_is_case_insensitive( self, classifier ):
        """
        Ensures:
            - an uppercase filename extension still resolves
            - matches regardless of the source-key case ('.MD' → '.md')
        """
        assert classifier.classify( "README.MD" ) == "markdown"
        assert classifier.classify( "SCRIPT.PY" ) == "python"

    def test_unknown_extension_returns_other( self, classifier ):
        """Ensures: an unmapped extension falls back to 'other'."""
        assert classifier.classify( "weird.xyz" ) == "other"

    def test_unknown_extension_verbose_logs( self, debug_classifier, capsys ):
        """
        Ensures:
            - verbose=True emits an "Unknown extension" note for an unmapped ext
        """
        assert debug_classifier.classify( "weird.xyz" ) == "other"
        assert "Unknown extension" in capsys.readouterr().out

    def test_no_extension_returns_other( self, classifier ):
        """Ensures: a filename with no suffix returns 'other'."""
        assert classifier.classify( "Makefile" ) == "other"

    def test_empty_filename_returns_other( self, classifier ):
        """Ensures: an empty filename returns 'other' (guard branch)."""
        assert classifier.classify( "" ) == "other"

    def test_dev_null_returns_other( self, classifier ):
        """Ensures: the git-diff '/dev/null' sentinel returns 'other'."""
        assert classifier.classify( "/dev/null" ) == "other"

    def test_pathful_filename_uses_final_suffix( self, classifier ):
        """Ensures: a directory-qualified path still classifies by its suffix."""
        assert classifier.classify( "src/cosa/repo/thing.py" ) == "python"

    def test_suffix_extraction_failure_returns_other_and_logs( self, debug_classifier, capsys ):
        """
        Ensures:
            - if Path(...).suffix raises, classify() defensively returns 'other'
            - debug=True logs the extraction error (exception-handler branch)
        """
        with mock.patch(
            "cosa.repo.branch_analyzer.file_classifier.Path",
            side_effect=RuntimeError( "boom" ),
        ):
            assert debug_classifier.classify( "exploding.py" ) == "other"
        assert "Error extracting extension" in capsys.readouterr().out

    def test_suffix_extraction_failure_silent_when_not_debug( self, classifier, capsys ):
        """
        Ensures:
            - the same Path failure returns 'other' with NO log when debug=False
              (the exception handler's debug-falsy exit branch)
        """
        with mock.patch(
            "cosa.repo.branch_analyzer.file_classifier.Path",
            side_effect=RuntimeError( "boom" ),
        ):
            assert classifier.classify( "exploding.py" ) == "other"
        assert "Error extracting extension" not in capsys.readouterr().out


class TestGetExtension:
    """get_extension() returns the lowercased suffix or None."""

    def test_returns_lowercase_extension_with_dot( self, classifier ):
        """Ensures: returns the '.ext' suffix, lowercased."""
        assert classifier.get_extension( "Thing.PY" ) == ".py"

    def test_returns_none_for_no_extension( self, classifier ):
        """Ensures: a suffix-less name yields None (not '')."""
        assert classifier.get_extension( "LICENSE" ) is None

    def test_returns_none_for_empty_and_dev_null( self, classifier ):
        """Ensures: empty string and '/dev/null' both yield None."""
        assert classifier.get_extension( "" ) is None
        assert classifier.get_extension( "/dev/null" ) is None

    def test_suffix_extraction_failure_returns_none( self, classifier ):
        """
        Ensures:
            - if Path(...).suffix raises, get_extension() returns None
              (defensive exception-handler branch)
        """
        with mock.patch(
            "cosa.repo.branch_analyzer.file_classifier.Path",
            side_effect=RuntimeError( "boom" ),
        ):
            assert classifier.get_extension( "exploding.py" ) is None


class TestIsBinary:
    """is_binary() is True only for extensions mapped to 'binary'."""

    def test_true_for_binary_mapped_extension( self, classifier ):
        """Ensures: a '.png' (mapped to binary) is reported binary."""
        assert classifier.is_binary( "image.png" ) is True

    def test_false_for_non_binary( self, classifier ):
        """Ensures: a python file is not binary."""
        assert classifier.is_binary( "module.py" ) is False


class TestGetCategoriesAndExtensions:
    """Accessors expose the category set and a defensive map copy."""

    def test_get_categories_includes_other_and_mapped_values( self, classifier ):
        """
        Ensures:
            - the returned set always contains 'other'
            - every configured category value is present
        """
        cats = classifier.get_categories()
        assert "other" in cats
        assert { "python", "javascript", "markdown", "binary" } <= cats

    def test_get_all_extensions_returns_defensive_copy( self, classifier ):
        """
        Ensures:
            - mutating the returned dict does not corrupt internal state
        """
        snapshot = classifier.get_all_extensions()
        snapshot[ ".rs" ] = "rust"
        assert ".rs" not in classifier.get_all_extensions()


class TestAddExtension:
    """add_extension() inserts/updates a lowercased mapping with validation."""

    def test_adds_new_mapping_lowercased( self, classifier ):
        """
        Ensures:
            - a new (uppercase) extension is stored lowercased
            - subsequent classify() honours the new mapping
        """
        classifier.add_extension( ".RS", "rust" )
        assert classifier.classify( "main.rs" ) == "rust"
        assert ".rs" in classifier.get_all_extensions()

    def test_debug_add_logs_mapping( self, debug_classifier, capsys ):
        """
        Ensures:
            - debug=True emits an "Added mapping" line for a new extension
        """
        debug_classifier.add_extension( ".rs", "rust" )
        assert "Added mapping" in capsys.readouterr().out

    def test_overwrites_existing_mapping( self, classifier ):
        """Ensures: re-adding an existing extension overwrites its category."""
        classifier.add_extension( ".py", "python3" )
        assert classifier.classify( "x.py" ) == "python3"

    def test_extension_without_leading_dot_raises( self, classifier ):
        """Ensures: an extension not starting with '.' raises ClassificationError."""
        with pytest.raises( ClassificationError ):
            classifier.add_extension( "rs", "rust" )

    def test_empty_extension_raises( self, classifier ):
        """Ensures: an empty extension string raises ClassificationError."""
        with pytest.raises( ClassificationError ):
            classifier.add_extension( "", "rust" )

    def test_empty_category_raises( self, classifier ):
        """Ensures: a valid extension with an empty category raises."""
        with pytest.raises( ClassificationError ):
            classifier.add_extension( ".rs", "" )
