"""
The guard for row aa68800d: `in_corpus` answered a CITATION question with a FILE answer, and hid
dead citations TWICE — the index (52 links, twice) and a script under src/rnd whose citation is a
live runtime dependency.

María 🌸 ruled candidate C on 2026-09-05: classify by whether a citation is OPENED OR FOLLOWED,
not by which file it sits in. Her reason is the durable half — C TRACKS THE PROPERTY; A AND B
ENUMERATE MEMBERS OF A SET, and an enumeration's guard cannot fail for a member nobody enumerated.

🔴 THE SHAPE OF THIS FILE IS HER REQUIREMENT AND IT IS NOT DECORATIVE. The both-directions
assertion lives in ONE invocation of `scan`, not in two tests and not in two runs. Her mechanism,
which is better than the reason I first offered:

    "Two separate green runs can both pass while the property is INVERTED; one run cannot."

An inverted classifier — one that admits records and refuses instructs — makes each
one-directional test green, because each asserts about the file it was handed. Only a single
result carrying BOTH outcomes at once can fail on an inversion. So `test_one_invocation_...`
below reads `index_scanned` and `records_declined` off the SAME dict, deliberately.
"""
import importlib.util
import os
import unittest

import cosa.utils.util as cu


def _load_scanner():
    path = os.path.join( cu.get_project_root(), "src", "scripts", "dead_rnd_citations.py" )
    spec = importlib.util.spec_from_file_location( "dead_rnd_citations", path )
    mod  = importlib.util.module_from_spec( spec )
    spec.loader.exec_module( mod )
    return mod


class CorpusClassifiesTheCitationNotTheFile( unittest.TestCase ):

    @classmethod
    def setUpClass( cls ):
        cls.mod    = _load_scanner()
        cls.root   = cu.get_project_root()
        # ONE invocation. Every assertion below reads this single result.
        cls.result = cls.mod.scan( cls.root )

    def test_one_invocation_admits_the_index_and_declines_a_record_simultaneously( self ):
        """
        María's acceptance, in her shape: a SINGLE scan whose output carries both outcomes.

        Ensures:
            - src/rnd/README.md is ADMITTED (it is an index; its links are followed)
            - at least one src/rnd citation is DECLINED as a record
            - both facts come off the same dict, so an inverted classifier fails here
        """
        r = self.result

        # POSITIVE CONTROL FIRST — an empty corpus satisfies "no bad citations" vacuously, and an
        # empty result and an empty search print identically.
        self.assertGreater( len( r[ "scanned" ] ), 1000,
                            "the scan read almost nothing — every assertion below would pass "
                            "vacuously, so this is an instrument failure, not a clean tree" )

        # 🔴 THE ADMITTED SIDE IS NOT `index_scanned`, AND IT IS NOT README's CITATIONS EITHER.
        # Two measured facts forced this shape:
        #   · `index_scanned` is derived from the files READ, so it is byte-identical under an
        #     inverted classifier. A test asserting on it CANNOT fail on an inversion — measured:
        #     an earlier cut of this very test stayed GREEN on an inversion while a sibling test
        #     caught it.
        #   · README.md's links are RELATIVE (`](v0.1.7/foo.md)`) and never match CITATION_PAT at
        #     all — the index's links are scanned by `scan_index_links`, a different function. So
        #     `citations_admitted` can never contain README.md, and asserting that it does would
        #     be asserting something false.
        # ⇒ Both sides are taken BY MEASUREMENT from this one result and the PROPERTY is checked
        #   on each. Under an inversion both flip and both assertions fail, which is the whole
        #   point of Maria's one-invocation shape.
        self.assertIn( "src/rnd/README.md", r[ "index_scanned" ],
                       "the index was not READ — instance 1 reopening" )

        md_admitted = [ d for d in r[ "citations_admitted" ] if d[ "file" ].endswith( ".md" ) ]
        md_declined = [ d for d in r[ "records_declined" ]   if d[ "file" ].endswith( ".md" ) ]
        self.assertGreater( len( md_admitted ), 0, "nothing admitted — half the shape missing" )
        self.assertGreater( len( md_declined ), 0, "nothing declined — the other half missing" )

        def _before( d ):
            with open( os.path.join( self.root, d[ "file" ] ), encoding="utf-8" ) as fh:
                line = fh.readlines()[ d[ "line" ] - 1 ]
            return line[ : line.find( d[ "path" ] ) ]

        a, b = md_admitted[ 0 ], md_declined[ 0 ]
        self.assertIn( "](", _before( a ),
                       f"ADMITTED {a['file']}:{a['line']} is NOT inside a link target — the "
                       f"classifier admitted a record. That is the inversion." )
        self.assertNotIn( "](", _before( b ),
                          f"DECLINED {b['file']}:{b['line']} IS inside a link target — the "
                          f"classifier declined an instruct. That is the inversion." )

        self.assertGreater( len( r[ "records_declined" ] ), 0,
                            "NOTHING was declined as a record. A classifier that admits every "
                            "citation passes a one-directional index test and is still wrong; "
                            "that is why both sides are asserted from one invocation" )

        # and the two sides must be DIFFERENT files — a result that declined the index itself
        # while listing it as scanned would satisfy both assertions above in isolation
        declined_files = { d[ "file" ] for d in r[ "records_declined" ] }
        self.assertNotIn( "src/rnd/README.md", declined_files,
                          "the index's own citations were declined — the classifier is inverted "
                          "for exactly the file this row exists to protect" )

    def test_a_python_citation_is_judged_by_argument_position_not_by_a_list_of_function_names( self ):
        """
        The python half is STRUCTURAL: a string literal that is an argument to a Call.

        This is the whole reason C was ruled over A and B. A list of opener names
        (open|Path|read_text|…) would be this module's sixth hand-maintained enumeration — see
        CLAUDE.md § WHEN THE FIX FOR AN ENUMERATION DEFECT IS ITSELF AN ENUMERATION — and would be
        silently wrong for the first call nobody thought of.

        Ensures:
            - a call argument is reported at its line, through a function this test never names
            - a docstring is NOT, and it falls out by grammar rather than by being excluded
        """
        source = (
            '"""a docstring citing src/rnd/v0.0.0/in-a-docstring.md — a RECORD"""\n'
            'import pathlib\n'
            'x = some_function_this_test_never_names( "src/rnd/v0.0.0/opened.md" )\n'
            'y = "src/rnd/v0.0.0/bare-assignment.md"\n'
        )
        lines = self.mod._python_call_argument_lines( source )

        self.assertIn( 3, lines, "a call argument was not recognised — and the call is deliberately "
                                 "a name no allow-list could contain" )
        self.assertNotIn( 1, lines, "a docstring was treated as a call argument" )
        self.assertNotIn( 4, lines, "a bare assignment was treated as a call argument" )

    def test_the_classifier_discriminates_rather_than_answering_one_way( self ):
        """
        A classifier that always returns True, and one that always returns False, each satisfy
        half of this file. Neither satisfies this.

        Ensures:
            - a markdown link target is FOLLOWED  -> instructs
            - the same path in prose is not       -> records
            - a file outside src/rnd is untouched by the rule
        """
        md = "src/rnd/doc.md"
        link  = "see [the design](src/rnd/v0.0.0/design.md) for more"
        prose = "see src/rnd/v0.0.0/design.md for more"
        col_l = link.index(  "src/rnd/v0.0.0" )
        col_p = prose.index( "src/rnd/v0.0.0" )

        self.assertTrue(  self.mod.citation_instructs( md, link,  col_l, set(), 1 ),
                          "a markdown LINK is followed by a reader; a dead one 404s them" )
        self.assertFalse( self.mod.citation_instructs( md, prose, col_p, set(), 1 ),
                          "a path in prose is a record — the sentence stays true either way" )
        self.assertTrue(  self.mod.citation_instructs( "src/docs/x.md", prose, col_p, set(), 1 ),
                          "the rule is scoped to src/rnd; everything else is admitted as before" )


if __name__ == "__main__":
    unittest.main()
