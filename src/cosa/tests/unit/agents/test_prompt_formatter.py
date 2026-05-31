"""
Unit tests for cosa.agents.prompt_formatter.PromptFormatter.

Exercises the model-specific prompt formatter against its CURRENT contract:

- __init__                       — explicit vs config template dir, debug trace,
                                   make-dir-when-missing
- get_prompt_format              — explicit per-model config, model-family config,
                                   best-guess fallback
- _get_prompt_format_best_guess  — json_message / special_token / instruction_completion
                                   pattern matching + config default fallback
- format_prompt                  — all three format types + the unknown-type ValueError,
                                   special-token model-specific vs fallback template,
                                   json_message with/without an assistant output turn
- _load_template                 — read existing vs create-on-FileNotFoundError
- _create_default_template       — every filename → content branch + the ValueError
- _extract_model_id              — phi/llama/mistral normalizers + the re.sub fallback
- create_template_examples       — create-when-missing vs skip-existing

Filesystem work happens inside a tempfile.TemporaryDirectory (writes confined to /tmp);
ConfigurationManager is mocked at the boundary. No network / model I/O.

Created 2026-05-31 (CoSA coverage campaign, agents lane — Tiffany 💍). New file.
"""

import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest.mock import Mock, patch

import cosa.utils.util as du
from cosa.agents.prompt_formatter import PromptFormatter


class TestPromptFormatter( unittest.TestCase ):
    """
    Comprehensive unit tests for PromptFormatter.

    Ensures:
        - Construction + format detection + template loading + prompt building all
          behave per contract across every documented branch
    """

    def setUp( self ):
        """Create an isolated temp template directory for each test."""
        self._tmp   = tempfile.TemporaryDirectory( prefix="prompt_fmt_test_" )
        self.tmpdir = self._tmp.name

    def tearDown( self ):
        """Remove the temp template directory."""
        self._tmp.cleanup()

    def _make( self, debug=False, verbose=False ):
        """
        Build a PromptFormatter rooted at the temp dir with ConfigurationManager mocked.

        Returns:
            Tuple of (formatter, mock_config). Configure mock_config.exists/get in the
            test body to steer format detection.
        """
        with patch( "cosa.agents.prompt_formatter.ConfigurationManager" ) as MockCfg:
            mock_cfg = MockCfg.return_value
            formatter = PromptFormatter( template_dir=self.tmpdir, debug=debug, verbose=verbose )
        return formatter, mock_cfg

    def _write_template( self, name, content ):
        """Write a template file into the temp dir and return its path.

        Uses a plain open() (correct arg order is unambiguous) so the helper is
        unaffected by the production write_string_to_file arg-swap bug at
        prompt_formatter.py:303.
        """
        path = os.path.join( self.tmpdir, name )
        with open( path, "w" ) as fh:
            fh.write( content )
        return path

    # ------------------------------------------------------------------ #
    # __init__                                                            #
    # ------------------------------------------------------------------ #

    def test_init_explicit_dir_existing_with_debug( self ):
        """
        Test __init__ with an explicit, already-existing template dir under debug.

        Ensures:
            - The provided directory is used verbatim
            - The existing dir is NOT recreated
        """
        with patch( "cosa.agents.prompt_formatter.ConfigurationManager" ):
            buf = io.StringIO()
            with redirect_stdout( buf ):
                f = PromptFormatter( template_dir=self.tmpdir, debug=True )

        self.assertEqual( f.template_dir, self.tmpdir )
        self.assertIn( "Using template directory", buf.getvalue() )

    def test_init_explicit_dir_missing_creates_it( self ):
        """
        Test __init__ creates an explicit template dir when it does not exist.

        Ensures:
            - The missing directory is created (debug trace emitted)
        """
        new_dir = os.path.join( self.tmpdir, "made", "here" )
        with patch( "cosa.agents.prompt_formatter.ConfigurationManager" ):
            buf = io.StringIO()
            with redirect_stdout( buf ):
                f = PromptFormatter( template_dir=new_dir, debug=True )

        self.assertTrue( os.path.isdir( new_dir ) )
        self.assertIn( "Creating template directory", buf.getvalue() )

    def test_init_config_dir_no_debug( self ):
        """
        Test __init__ derives the template dir from config when none is supplied.

        Ensures:
            - With template_dir=None the config key + project root are joined
            - The (missing) derived dir is created; no debug output with debug=False
        """
        rel = "made_from_config"
        with patch( "cosa.agents.prompt_formatter.ConfigurationManager" ) as MockCfg, \
             patch( "cosa.agents.prompt_formatter.du.get_project_root", return_value=self.tmpdir ):
            MockCfg.return_value.get.return_value = rel
            f = PromptFormatter( template_dir=None, debug=False )

        self.assertEqual( f.template_dir, os.path.join( self.tmpdir, rel ) )
        self.assertTrue( os.path.isdir( f.template_dir ) )

    # ------------------------------------------------------------------ #
    # get_prompt_format                                                   #
    # ------------------------------------------------------------------ #

    def test_get_prompt_format_explicit_model_config( self ):
        """
        Test get_prompt_format honors an explicit per-model config entry.

        Ensures:
            - When prompt_format_<model> exists, its value is returned directly
        """
        f, cfg = self._make()
        cfg.exists.side_effect = lambda key: key == "prompt_format_my-model"
        cfg.get.return_value   = "special_token"

        self.assertEqual( f.get_prompt_format( "my-model" ), "special_token" )

    def test_get_prompt_format_family_config( self ):
        """
        Test get_prompt_format falls back to a model-family config entry.

        Ensures:
            - No per-model key, but a matching family key (e.g. openai) is returned
        """
        f, cfg = self._make()
        cfg.exists.side_effect = lambda key: key == "prompt_format_default_openai"
        cfg.get.return_value   = "json_message"

        self.assertEqual( f.get_prompt_format( "openai:gpt-4" ), "json_message" )

    def test_get_prompt_format_falls_back_to_best_guess( self ):
        """
        Test get_prompt_format defers to the best-guess heuristic when no config matches.

        Ensures:
            - With no config keys present, the pattern-based guess is used
        """
        f, cfg = self._make()
        cfg.exists.return_value = False

        self.assertEqual( f.get_prompt_format( "anthropic:claude-3" ), "json_message" )

    # ------------------------------------------------------------------ #
    # _get_prompt_format_best_guess                                       #
    # ------------------------------------------------------------------ #

    def test_best_guess_json_message( self ):
        """Test API-style model names guess json_message."""
        f, _ = self._make()
        self.assertEqual( f._get_prompt_format_best_guess( "gpt-4o" ), "json_message" )

    def test_best_guess_special_token( self ):
        """Test phi-family model names guess special_token."""
        f, _ = self._make()
        self.assertEqual( f._get_prompt_format_best_guess( "kaitchup/phi-4" ), "special_token" )

    def test_best_guess_instruction_completion( self ):
        """Test mistral/llama model names guess instruction_completion."""
        f, _ = self._make()
        self.assertEqual( f._get_prompt_format_best_guess( "mistral-7b" ), "instruction_completion" )

    def test_best_guess_config_default_fallback( self ):
        """
        Test an unrecognized model name falls back to the configured default.

        Ensures:
            - When no pattern matches, the 'prompt format default' config value wins
        """
        f, cfg = self._make()
        cfg.get.return_value = "instruction_completion"

        self.assertEqual( f._get_prompt_format_best_guess( "totally-unknown" ), "instruction_completion" )

    # ------------------------------------------------------------------ #
    # format_prompt                                                       #
    # ------------------------------------------------------------------ #

    def test_format_prompt_instruction_completion( self ):
        """
        Test instruction_completion formatting fills the template placeholders.

        Ensures:
            - The on-disk template is filled with instructions/input/output
        """
        f, _ = self._make()
        f.get_prompt_format = lambda m: "instruction_completion"
        # Pre-create the template so _load_template takes the read path (the
        # create-default fallback is blocked by the prod write-arg-swap bug:303).
        self._write_template( "instruction-completion-default.txt",
                              "[INST] {instructions} | {input} [/INST] {output}" )

        prompt = f.format_prompt( "mistral-7b", "be helpful", "hi there", output="ok" )

        self.assertIn( "be helpful", prompt )
        self.assertIn( "hi there", prompt )
        self.assertIn( "ok", prompt )

    def test_format_prompt_special_token_model_specific_template( self ):
        """
        Test special_token formatting uses a model-specific template when present.

        Ensures:
            - An existing special-token-<model_id>.txt is loaded (no fallback)
        """
        f, _ = self._make()
        f.get_prompt_format = lambda m: "special_token"
        # phi-4 → model_id 'phi_4' → special-token-phi_4.txt
        self._write_template( "special-token-phi_4.txt",
                              "MS:{instructions}|{input}|{output}" )

        prompt = f.format_prompt( "phi-4", "sys", "usr", output="out" )

        self.assertEqual( prompt, "MS:sys|usr|out" )

    def test_format_prompt_special_token_fallback_template( self ):
        """
        Test special_token formatting falls back to the default template.

        Ensures:
            - With no model-specific template, special-token-default.txt is used
        """
        f, _ = self._make()
        f.get_prompt_format = lambda m: "special_token"
        # No special-token-phi_4.txt → falls back to the default, which we pre-create
        # (the create-default fallback is blocked by the prod write-arg-swap bug:303).
        self._write_template( "special-token-default.txt",
                              "<|system|>{instructions}<|user|>{input}<|assistant|>{output}" )

        prompt = f.format_prompt( "phi-4", "sys", "usr" )

        self.assertIn( "sys", prompt )
        self.assertIn( "usr", prompt )

    def test_format_prompt_json_message_with_output( self ):
        """
        Test json_message formatting includes an assistant turn when output is given.

        Ensures:
            - Returns JSON with system + user + assistant messages
        """
        f, _ = self._make()
        f.get_prompt_format = lambda m: "json_message"

        messages = json.loads( f.format_prompt( "openai:gpt-4", "sys", "usr", output="ans" ) )

        self.assertEqual( len( messages ), 3 )
        self.assertEqual( messages[0], { "role": "system", "content": "sys" } )
        self.assertEqual( messages[2], { "role": "assistant", "content": "ans" } )

    def test_format_prompt_json_message_without_output( self ):
        """
        Test json_message formatting omits the assistant turn when output is empty.

        Ensures:
            - Returns JSON with only system + user messages
        """
        f, _ = self._make()
        f.get_prompt_format = lambda m: "json_message"

        messages = json.loads( f.format_prompt( "openai:gpt-4", "sys", "usr" ) )

        self.assertEqual( len( messages ), 2 )

    def test_format_prompt_unknown_type_raises( self ):
        """
        Test format_prompt raises on an unrecognized format type.

        Ensures:
            - A bogus format_type triggers ValueError
        """
        f, _ = self._make()
        f.get_prompt_format = lambda m: "bogus_format"

        with self.assertRaises( ValueError ):
            f.format_prompt( "x", "i", "t" )

    # ------------------------------------------------------------------ #
    # _load_template                                                      #
    # ------------------------------------------------------------------ #

    def test_load_template_reads_existing_file( self ):
        """
        Test _load_template returns the contents of an existing template file.

        Ensures:
            - An on-disk template is read back verbatim
        """
        f, _ = self._make()
        path = self._write_template( "existing.txt", "HELLO {input}" )

        self.assertEqual( f._load_template( path ), "HELLO {input}" )

    def test_load_template_creates_default_when_missing( self ):
        """
        Test _load_template creates a default when the file is absent.

        Ensures:
            - A missing known-name template triggers default creation + returns content

        The write boundary (du.write_string_to_file) is mocked because the production
        call at prompt_formatter.py:303 swaps its args (bug flagged to Tiberius); the
        tripwire below asserts the correct contract.
        """
        f, _ = self._make()
        path = os.path.join( self.tmpdir, "instruction-completion-default.txt" )

        buf = io.StringIO()
        with patch( "cosa.agents.prompt_formatter.du.write_string_to_file" ) as mock_write:
            with redirect_stdout( buf ):
                content = f._load_template( path )

        self.assertIn( "{instructions}", content )
        mock_write.assert_called_once()

    # ------------------------------------------------------------------ #
    # _create_default_template (every filename branch)                    #
    # ------------------------------------------------------------------ #

    def test_create_default_template_all_known_names( self ):
        """
        Test _create_default_template produces the right content per known filename.

        Ensures:
            - instruction-completion / special-token-default / phi- / llama- names
              each yield placeholder-bearing content and call the write boundary

        The write boundary is mocked (prod arg-swap bug:303); the tripwire below
        asserts the real-write contract.
        """
        f, _ = self._make( debug=True )
        cases = [
            "instruction-completion-default.txt",
            "special-token-default.txt",
            "special-token-phi-foo.txt",
            "special-token-llama-foo.txt",
        ]
        for name in cases:
            with self.subTest( name=name ):
                path = os.path.join( self.tmpdir, name )
                buf = io.StringIO()
                with patch( "cosa.agents.prompt_formatter.du.write_string_to_file" ) as mock_write:
                    with redirect_stdout( buf ):
                        content = f._create_default_template( path )
                self.assertIn( "{instructions}", content )
                mock_write.assert_called_once()

    def test_create_default_template_unknown_name_raises( self ):
        """
        Test _create_default_template raises for an unrecognized filename.

        Ensures:
            - A name with no known mapping raises ValueError
        """
        f, _ = self._make()
        path = os.path.join( self.tmpdir, "mystery-template.txt" )

        with self.assertRaises( ValueError ):
            f._create_default_template( path )

    @unittest.expectedFailure
    def test_TRIPWIRE_create_default_template_writes_content_to_path( self ):
        """
        TRIPWIRE (prod bug) — _create_default_template must write `content` to `template_path`.

        prompt_formatter.py:303 calls `du.write_string_to_file( content, template_path )`
        but the util signature is write_string_to_file( path, string ) — the args are
        SWAPPED. With a real write, the content (which contains '/') is treated as the
        path and the call raises FileNotFoundError, so nothing lands at template_path.

        This test asserts the CORRECT contract (the file at template_path holds the
        template content) and is marked expectedFailure; it will start PASSING — and
        should then have the decorator removed — once Tiberius fixes line 303 to
        `du.write_string_to_file( template_path, content )`. Flagged via dm-tiberius
        (question_id 27a555d7), 2026-05-31.
        """
        f, _ = self._make()
        path = os.path.join( self.tmpdir, "instruction-completion-default.txt" )

        content = f._create_default_template( path )   # raises today (arg-swap bug)

        self.assertTrue( os.path.exists( path ) )
        self.assertEqual( du.get_file_as_string( path ), content )

    # ------------------------------------------------------------------ #
    # _extract_model_id                                                   #
    # ------------------------------------------------------------------ #

    def test_extract_model_id_known_families( self ):
        """
        Test _extract_model_id normalizes recognized model families.

        Ensures:
            - phi-4 / phi-3 / llama-3 / mistral-7b map to their canonical ids
        """
        f, _ = self._make()
        self.assertEqual( f._extract_model_id( "kaitchup/phi-4-14b" ), "phi_4" )
        self.assertEqual( f._extract_model_id( "microsoft/phi-3-mini" ), "phi_3" )
        self.assertEqual( f._extract_model_id( "meta/llama-3-8b" ), "llama_3" )
        self.assertEqual( f._extract_model_id( "mistralai/mistral-7b-v0.1" ), "mistral_7b" )

    def test_extract_model_id_sanitizes_unknown( self ):
        """
        Test _extract_model_id sanitizes an unrecognized name via re.sub fallback.

        Ensures:
            - Non-alphanumeric characters become underscores; result is lowercased
        """
        f, _ = self._make()
        self.assertEqual( f._extract_model_id( "Foo/Bar:Baz-1" ), "foo_bar_baz_1" )

    # ------------------------------------------------------------------ #
    # create_template_examples                                            #
    # ------------------------------------------------------------------ #

    def test_create_template_examples_creates_all( self ):
        """
        Test create_template_examples writes all example templates when none exist.

        Ensures:
            - Four templates are created and their paths returned (debug trace emitted)
        """
        f, _ = self._make( debug=True )

        buf = io.StringIO()
        with redirect_stdout( buf ):
            paths = f.create_template_examples()

        self.assertEqual( len( paths ), 4 )
        for p in paths.values():
            self.assertTrue( os.path.exists( p ) )

    def test_create_template_examples_skips_existing( self ):
        """
        Test create_template_examples does not overwrite an existing template.

        Ensures:
            - A pre-existing template's original content is preserved (skip branch)
        """
        f, _ = self._make()
        existing = self._write_template( "instruction-completion-default.txt", "ORIGINAL" )

        paths = f.create_template_examples()

        self.assertEqual( du.get_file_as_string( existing ), "ORIGINAL" )
        self.assertIn( "instruction-completion-default.txt", paths )


if __name__ == "__main__":
    unittest.main()
