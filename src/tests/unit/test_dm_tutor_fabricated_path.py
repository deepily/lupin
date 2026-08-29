"""
The path-fabrication guard — row f3d96537.

⚠️ THE DEFECT (María, 2026-08-26). The condenser read the prose "seven guards in dm.py"
and delivered `seven-guards-in-dm.py` — a filename that exists nowhere in the tree and
that nobody has ever written — into the slot Rick ruled protected (a0151611). The shipped
fabrication guard did not fire, and it was not broken: it was never asked the question.
`_restore_dropped_pointers` is one-way by design (it restores what a rewrite DROPPED and
never inspects what it INVENTED), and the old `_FAB_PATH` pattern required a slash or a
URL scheme, so a bare filename was not a path to it — while `restorable_pointers`, in the
same codebase, has always recognised that shape.

THE FIXTURES ARE REAL, NOT CONSTRUCTED. `_SPECIMEN_SUBMITTED` and `_SPECIMEN_DELIVERED`
are the verbatim submitted and delivered bodies of Mr Radio's 19:31:04 DM to María on
2026-08-26, lifted out of the live traffic corpus. That pair is the one that PROVES
fabrication rather than transcription: `four-guards-in-dm.py` appears in the original, so
carrying it forward is faithful — `seven-guards-in-dm.py` appears nowhere, in the corpus
or the tree, and the model produced it anyway.
"""
import unittest

import cosa.rest.routers.dm as dm
from cosa.rest.routers.dm import ( _fabricated_paths, _fabricated_facts,
                                   _fabricated_paths_legacy,
                                   _parse_product_names, _parse_path_fab_mode, _FAB_NOT_PATHS,
                                   _DM_TUTOR_DEFAULTS, DM_TUTOR_NOTICE, _apply_dm_tutor )


def _cfg( **overrides ):
    """
    A tutor config seeded from the shipped defaults, never a hand-written literal.

    The send path indexes its config directly, so a literal that misses a key added
    later raises KeyError inside `_apply_dm_tutor` and the test fails with an assertion
    about delivered text that names nothing about config.
    """
    config = dict( _DM_TUTOR_DEFAULTS )
    config.update( { "enabled": True, "trigger_claims": 4, "gate_enabled": False,
                     "gate_max_claims": 4, "fab_guard_strict": True,
                     "attribution_guard": False } )
    config.update( overrides )
    return config


# The 19:31:04 pair, verbatim from the corpus.
_SPECIMEN_SUBMITTED = 'Confirmed, and it is the better fix. restorable_pointers( "see four-guards-in-dm.py for this" ) returns [\'four-guards-in-dm.py\'] — the recogniser is already there and already correct on the bare-filename shape, while _FAB_PATH returns nothing for the same token. So the repair is reuse, not a new regex: the fabrication guard should ask restorable_pointers what looks like a pointer instead of carrying its own narrower pattern.\n\nNoting the shape for the record, since it is the same one we have been writing up all day: two guards over the same class of thing, one of which knows something the other does not, and nothing makes them agree. My contended-coverage guard has the identical hazard — a coverage-flag list duplicated in two shell files — so I pinned the two detectors to agree over a shared corpus rather than trusting them to stay in step. That is the shape of test worth adding beside f3d96537.\n\nFiled my measurements as row 7a560d94 and pointed it at f3d96537 as the parent; I am not touching dm.py, it is live under another seat.'

_SPECIMEN_DELIVERED = 'The repair is to reuse the existing recognizer instead of creating a new regex.\nThe `restorable_pointers` function correctly identifies the filename, while `_FAB_PATH` returns nothing for the same token.\nThe coverage-flag list issue is noted, and measurements are filed as row 7a560d94, pointing to f3d96537 as the parent.\nseven-guards-in-dm.py\nfour-guards-in-dm.py\nThis DM was condensed in transit. Need more detail? Ask the sender one question'

# The rewrite the guard actually judges: the delivered body without the notice
# the tutor appends after every check has passed.
_SPECIMEN_REWRITE = _SPECIMEN_DELIVERED[ : -len( DM_TUTOR_NOTICE ) ].rstrip()


class TestTheLiveSpecimen( unittest.TestCase ):
    """The pair the row was filed on. If these pass, the reported defect is caught."""

    def test_the_invented_filename_is_reported( self ):
        self.assertEqual( [ "seven-guards-in-dm.py" ],
                          _fabricated_paths( _SPECIMEN_SUBMITTED, _SPECIMEN_REWRITE ) )

    def test_the_filename_the_sender_did_write_is_not_blamed( self ):
        """
        `four-guards-in-dm.py` is in the original, so the rewrite carrying it forward is
        FAITHFUL. A guard that reported both would double the rate on a pair the
        condenser handled correctly — María's own caution when she filed the row.
        """
        self.assertNotIn( "four-guards-in-dm.py",
                          _fabricated_paths( _SPECIMEN_SUBMITTED, _SPECIMEN_REWRITE ) )

    def test_the_old_pattern_could_not_see_it( self ):
        """
        The old pattern still EXISTS — as `_FAB_PATH_LEGACY`, the rollback branch — but it
        is no longer what the live check asks. Pinned both ways: the name it ran under is
        gone, and the pattern itself is proven blind to the specimen.
        """
        self.assertFalse( hasattr( dm, "_FAB_PATH" ) )
        self.assertEqual( [], _fabricated_paths_legacy( _SPECIMEN_SUBMITTED, _SPECIMEN_REWRITE ) )

    def test_an_invented_filename_ENDING_a_sentence_is_still_seen( self ):
        """
        ⚠️ A SENTENCE-FINAL FULL STOP HID ONE, and an existing test in
        `test_dm_tutor_send_path.py` caught it before this shipped. The token carries the
        trailing dot, so it no longer ends in a code extension and the recogniser's own
        path-signal test discards it. A guard that sees mid-sentence and not
        sentence-final has a branch nobody runs.
        """
        self.assertEqual( [ "seven-guards-in-dm.py" ],
                          _fabricated_paths( "see four guards in dm.py",
                                             "The measurements are in seven-guards-in-dm.py." ) )

    def test_the_send_path_refuses_it_and_delivers_the_sender_s_own_words( self ):
        out, meta = _apply_dm_tutor(
            _SPECIMEN_SUBMITTED,
            config=_cfg( attribution_guard=False ),
            rewrite_fn=lambda _body: _SPECIMEN_REWRITE )
        self.assertEqual( "fabrication_blocked", meta[ "tutor_outcome" ] )
        self.assertEqual( _SPECIMEN_SUBMITTED, out )
        self.assertIn( "seven-guards-in-dm.py", meta[ "tutor_fabricated" ][ "path" ] )


class TestWhatMustNotBeRefused( unittest.TestCase ):
    """
    ⚠️ THIS GUARD'S FAILURE MODE IS REFUSING REAL MAIL. Each case below is a shape the
    corpus actually contains, and each cost a measured share of the 26 substring hits.
    """

    def test_an_abbreviated_path_is_faithful( self ):
        """A rewrite shortening a full path to its filename has invented nothing."""
        self.assertEqual( [], _fabricated_paths(
            "the gate is at src/cosa/rest/todo_fifo_queue.py:363",
            "the gate is in todo_fifo_queue.py" ) )

    def test_capitalising_a_filename_is_not_inventing_one( self ):
        """"Registry.py" opening a sentence is `registry.py`. 11 of the 26 hits were this."""
        self.assertEqual( [], _fabricated_paths( "registry.py is at 100%",
                                                 "Registry.py is at 100%" ) )

    def test_an_elided_line_suffix_expanded_is_faithful( self ):
        """The sender wrote "executor.py:106, :108"; the rewrite says what was meant."""
        self.assertEqual( [], _fabricated_paths(
            "every construction: executor.py:106, :108, :115",
            "executor.py:106, executor.py:108, executor.py:115" ) )

    def test_a_product_name_is_not_a_file( self ):
        """A rewrite saying "the Node.js test" has cited nothing."""
        self.assertEqual( [], _fabricated_paths( "run node --test on the suite",
                                                 "run the Node.js test" ) )

    def test_a_faithful_rewrite_carrying_the_same_path_is_clean( self ):
        self.assertEqual( [], _fabricated_paths( "see src/cosa/rest/routers/dm.py for the guard",
                                                 "the guard is in src/cosa/rest/routers/dm.py" ) )


class TestTheAllowListFailsClosed( unittest.TestCase ):
    """
    🔴 WHY A LIST AND NOT A SHAPE RULE (María's ruling, 2026-08-26). The shape rule reached
    for first — "a slashless token whose stem is a single capitalised word is a product
    name" — FAILS OPEN, and these are the names it would have released.
    """

    def test_a_fabricated_capitalised_doc_is_still_caught( self ):
        for invented in ( "CLAUDE.md", "README.md", "TODO.md" ):
            with self.subTest( invented=invented ):
                self.assertEqual( [ invented ],
                                  _fabricated_paths( "read the house rules", f"read {invented}" ) )

    def test_a_name_the_list_has_never_been_told_about_is_checked( self ):
        self.assertEqual( [ "Zircon.js" ],
                          _fabricated_paths( "run the bundler", "run Zircon.js" ) )

    def test_the_config_list_replaces_the_seed_rather_than_extending_it( self ):
        names = _parse_product_names( "zircon.js" )
        self.assertEqual( [], _fabricated_paths( "run the bundler", "run Zircon.js",
                                                 product_names=names ) )
        self.assertEqual( [ "Node.js" ], _fabricated_paths( "run node", "run Node.js",
                                                            product_names=names ) )


class TestTheRollbackIsARollbackAndNotADowngrade( unittest.TestCase ):
    """
    🔴 MARÍA'S RULING, 2026-08-26: "make OFF mean the OLD behaviour, not no behaviour. A kill
    switch whose OFF position is weaker than the state before the change is not a rollback,
    it is a downgrade." So the dial SELECTS a recogniser; there is no value that refuses
    nothing, and the legacy branch is pinned here so it cannot rot unnoticed.
    """

    def test_the_pointer_recogniser_is_the_default( self ):
        self.assertEqual( "pointer", _DM_TUTOR_DEFAULTS[ "path_fab_mode" ] )

    def test_a_slashed_invented_path_is_refused_in_BOTH_modes( self ):
        for mode in ( "pointer", "legacy" ):
            with self.subTest( mode=mode ):
                self.assertIn( "src/conf/x.ini",
                               _fabricated_facts( "the queue drained", "see src/conf/x.ini",
                                                  path_mode=mode )[ "path" ] )

    def test_an_invented_URL_is_refused_in_BOTH_modes( self ):
        for mode in ( "pointer", "legacy" ):
            with self.subTest( mode=mode ):
                self.assertIn( "path", _fabricated_facts( "the box came back",
                                                          "see https://example.com/x",
                                                          path_mode=mode ) )

    def test_only_the_pointer_mode_sees_a_bare_invented_filename( self ):
        """That blindness IS the defect of this row — it is what legacy rolls back to."""
        self.assertEqual( [ "seven-guards-in-dm.py" ],
                          _fabricated_paths( _SPECIMEN_SUBMITTED, _SPECIMEN_REWRITE ) )
        self.assertEqual( [], _fabricated_paths_legacy( _SPECIMEN_SUBMITTED, _SPECIMEN_REWRITE ) )

    def test_legacy_delivers_the_rewrite_this_row_was_filed_for( self ):
        out, meta = _apply_dm_tutor( _SPECIMEN_SUBMITTED,
                                     config=_cfg( path_fab_mode="legacy" ),
                                     rewrite_fn=lambda _body: _SPECIMEN_REWRITE )
        self.assertEqual( "rewritten", meta[ "tutor_outcome" ] )
        self.assertIn( "seven-guards-in-dm.py", out )

    def test_the_other_fabrication_classes_are_untouched_by_the_mode( self ):
        for mode in ( "pointer", "legacy" ):
            with self.subTest( mode=mode ):
                self.assertIn( "hex_id", _fabricated_facts( "the container came back",
                                                            "deployed commit b8d10bd3",
                                                            path_mode=mode ) )


class TestAnUnrecognisedModeCannotWeakenTheGuard( unittest.TestCase ):
    """
    ⚠️ A TYPO MUST NOT SILENTLY WEAKEN A GUARD (María, 2026-08-26). "anything that is not
    `pointer` means legacy" would have let `Pointr` in the ini roll the fleet back to the
    blind pattern with nothing said.
    """

    def test_only_the_exact_word_selects_the_rollback( self ):
        for raw in ( "legacy", " LEGACY ", "Legacy" ):
            with self.subTest( raw=raw ): self.assertEqual( "legacy", _parse_path_fab_mode( raw ) )

    def test_blank_and_missing_resolve_to_the_stronger_check( self ):
        for raw in ( None, "", "   ", "pointer", "POINTER" ):
            with self.subTest( raw=raw ): self.assertEqual( "pointer", _parse_path_fab_mode( raw ) )

    def test_a_typo_resolves_to_the_stronger_check_and_says_so( self ):
        import io, contextlib
        out = io.StringIO()
        with contextlib.redirect_stdout( out ):
            self.assertEqual( "pointer", _parse_path_fab_mode( "Pointr" ) )
        self.assertIn( "Pointr", out.getvalue() )

    def test_a_valid_value_says_nothing( self ):
        import io, contextlib
        out = io.StringIO()
        with contextlib.redirect_stdout( out ):
            _parse_path_fab_mode( "legacy" ); _parse_path_fab_mode( "pointer" )
        self.assertEqual( "", out.getvalue() )

    def test_an_unrecognised_value_reaching_the_check_directly_still_resolves_strong( self ):
        """A caller that skips the parser must not be able to weaken it either."""
        self.assertIn( "seven-guards-in-dm.py",
                       _fabricated_facts( _SPECIMEN_SUBMITTED, _SPECIMEN_REWRITE,
                                          path_mode="nonsense" )[ "path" ] )


class TestTheProductNameParser( unittest.TestCase ):

    def test_a_missing_or_blank_key_falls_back_to_the_shipped_seed( self ):
        for raw in ( None, "", "   " ):
            with self.subTest( raw=raw ): self.assertIs( _FAB_NOT_PATHS, _parse_product_names( raw ) )

    def test_commas_and_whitespace_both_separate( self ):
        self.assertEqual( frozenset( { "a.js", "b.js", "c.js" } ),
                          _parse_product_names( "a.js, b.js   c.js" ) )

    def test_names_are_lowercased_so_the_comparison_can_be( self ):
        self.assertEqual( frozenset( { "node.js" } ), _parse_product_names( "Node.JS" ) )


class TestItNeverTakesTheSendPathDown( unittest.TestCase ):

    def test_a_raising_recogniser_reports_nothing_rather_than_exploding( self ):
        """
        An unreadable comparison must leave the tutor exactly as safe as it was before
        this check existed — never block every DM in the fleet.
        """
        import cosa.agents.dm_tutor.sentences as sentences
        original = sentences.restorable_pointers
        sentences.restorable_pointers = lambda _t: ( _ for _ in () ).throw( RuntimeError( "boom" ) )
        try:
            self.assertEqual( [], _fabricated_paths( "a", "b" ) )
        finally:
            sentences.restorable_pointers = original

    def test_the_ROLLBACK_branch_also_survives_a_raising_pattern( self ):
        """
        The live check's fail-soft is tested above; the rollback branch needs the same
        proof or it is an untested path that only runs on the day someone reaches for it.
        Caught by the coverage run, not by reading — lines 1094-1095 were the only two of
        the change's own lines left uncovered.
        """
        real = dm._FAB_PATH_LEGACY
        class _Boom:
            def findall( self, _text ): raise RuntimeError( "boom" )
        dm._FAB_PATH_LEGACY = _Boom()
        try:
            self.assertEqual( [], _fabricated_paths_legacy( "a", "b" ) )
        finally:
            dm._FAB_PATH_LEGACY = real

    def test_the_path_class_still_reaches_fabricated_facts( self ):
        """The caller's contract is unchanged: paths arrive under the "path" key."""
        self.assertIn( "src/conf/x.ini",
                       _fabricated_facts( "the queue drained", "see src/conf/x.ini" )[ "path" ] )


if __name__ == "__main__":
    unittest.main()
