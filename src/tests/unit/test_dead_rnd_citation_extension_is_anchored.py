"""
The guard for row 8f535031: CITATION_PAT's extension alternation was unanchored on its right, so
`json` matched the first four characters of `jsonl` and the regex stopped there.

🔴 THIS IS A WRONG ANSWER, NOT A MISSED ONE, AND THAT IS THE WHOLE REASON IT GETS ITS OWN FILE.
A citation the scanner cannot see is reported as nothing, and an absence at least looks like an
absence. A TRUNCATED citation is reported as a PRESENT path that exists nowhere: os.path.exists is
asked about `….json`, answers False whether or not the real `.jsonl` file is sitting right there,
and a live citation is published as DEAD under a filename a reader cannot find by grepping the
source. The reader then cannot tell whether the scanner or their own eyes are wrong.

⚠️ AND THE FIRST VERSION OF THIS FILE GOT THE REASON WRONG, RECORDED HERE RATHER THAN QUIETLY
DELETED. It said `\\b` "does not fix this". It DOES — the boundary fails between `n` and `l`, the
whole pattern then fails at that position, and the result is NO MATCH rather than a short one. The
test below went red and the claim was withdrawn from here, from the module comment and from the row.

🔴 WHAT THE RE-MEASUREMENT FOUND IS THE PART WORTH KEEPING: the first shipped lookahead,
`(?![A-Za-z0-9])`, was WEAKER THAN THE REFLEX IT REPLACED. On a path like `b.py_backup` the
underscore continues the filename; `\\b` refuses correctly and the alphanumeric-only lookahead
truncates — this row's own defect, one character class along, introduced by its own fix. The
shipped pattern carries `_`, and the underscore is the single case where the two forms disagree.

🔴 AND THIS GUARD IS THE ONLY THING THAT CAN SEE THE FIX. Measured 2026-09-05 across 5,056 tracked
files: THREE truncation sites, all `.jsonl`, all under src/rnd/ — which in_corpus() excludes, so
ZERO of them reach a report. The scanner's dead-citation SET is byte-identical before and after
(355 → 355). ⇒ There is no output in which this defect or its repair is visible. A test is not the
best evidence here, it is the only evidence.

⚠️ WHICH IS ALSO WHY THIS SHIPPED BEFORE row aa68800d. The two defects mask each other: widen the
corpus first and a wrong path is the first thing the widened corpus emits, with the corpus change
taking the blame for a defect it merely revealed.
"""

import os
import re
import unittest

import cosa.utils.util as cu

import importlib.util


def _load_scanner():
    """
    Ensures: returns the dead_rnd_citations module loaded from THIS tree, resolved through
             cu.get_project_root() so it follows LUPIN_ROOT rather than the import graph.
    """
    path = os.path.join( cu.get_project_root(), "src", "scripts", "dead_rnd_citations.py" )
    spec = importlib.util.spec_from_file_location( "dead_rnd_citations", path )
    mod  = importlib.util.module_from_spec( spec )
    spec.loader.exec_module( mod )
    return mod


class TheExtensionIsAnchoredOnItsRight( unittest.TestCase ):

    @classmethod
    def setUpClass( cls ):
        cls.mod = _load_scanner()

    def test_an_extension_that_merely_starts_with_a_known_one_is_not_truncated_to_it( self ):
        """
        🔴 THE DEFECT, ASSERTED AS THE THING THAT ACTUALLY WENT WRONG. The requirement is not
        "does not match" — it is "NEVER MATCHES SHORT". A pattern may decline `.jsonl` entirely or
        take the whole thing; what it must never do is hand back a prefix of it as though that
        were the citation.
        """
        for path in ( "src/rnd/a/b.jsonl",   # the measured instance, x3 in the live tree
                      "src/rnd/a/b.mdx",
                      "src/rnd/a/b.pyi",
                      "src/rnd/a/b.txtual",
                      "src/rnd/a/b.shx" ):
            with self.subTest( path=path ):
                found = [ m.group( 0 ) for m in self.mod.CITATION_PAT.finditer( path ) ]
                for got in found:
                    self.assertEqual( path, got,
                                      "%s was reported as %r — a path that appears nowhere in the "
                                      "source, which is worse than not matching at all" % ( path, got ) )

    def test_the_real_extensions_still_match_whole( self ):
        """
        🔴 THE NEGATIVE CONTROL, AND WITHOUT IT THE TEST ABOVE IS SATISFIED BY DELETING THE
        PATTERN. A regex that matches nothing never truncates anything. Every extension the
        scanner claims to recognise is asserted here, so "stop matching" is not an available way
        to go green.
        """
        for path in ( "src/rnd/a/b.md", "src/rnd/a/b.py", "src/rnd/a/b.sh",
                      "src/rnd/a/b.json", "src/rnd/a/b.txt" ):
            with self.subTest( path=path ):
                found = [ m.group( 0 ) for m in self.mod.CITATION_PAT.finditer( path ) ]
                self.assertEqual( [ path ], found,
                                  "%s must still be recognised whole" % path )

    def test_an_extension_followed_by_punctuation_is_still_a_citation( self ):
        """
        The anchor must refuse a CONTINUING extension without refusing ordinary prose. A citation
        at the end of a sentence, inside a markdown link, or in a parenthesis is the common case —
        if the lookahead were written as "must be end-of-string" this is what would break, silently
        and across the whole corpus.
        """
        for text, want in ( ( "see src/rnd/a/b.md.",            "src/rnd/a/b.md" ),
                            ( "see src/rnd/a/b.md)",            "src/rnd/a/b.md" ),
                            ( "see `src/rnd/a/b.json`,",        "src/rnd/a/b.json" ),
                            ( "see src/rnd/a/b.py for detail",  "src/rnd/a/b.py" ),
                            ( "[x](src/rnd/a/b.md) and more",   "src/rnd/a/b.md" ) ):
            with self.subTest( text=text ):
                found = [ m.group( 0 ) for m in self.mod.CITATION_PAT.finditer( text ) ]
                self.assertIn( want, found,
                               "a citation followed by punctuation must still be found" )

    def test_the_anchor_refuses_every_character_that_continues_a_filename( self ):
        """
        🔴 THIS TEST HAS NOW CAUGHT ITS OWN AUTHOR TWICE, AND BOTH CORRECTIONS ARE THE POINT.

        FIRST it asserted that `\\b` "does not fix this". FALSE — `\\b` stops the truncation fine: the
        boundary fails between `n` and `l`, the whole pattern then fails at that position, and the
        result is NO MATCH rather than a short one. Withdrawn.

        THEN it asserted that the UNDERSCORE is "the only case where the lookahead and `\\b`
        disagree". ALSO FALSE, and caught by María 🌸 running both patterns rather than reading
        them. Measured over twelve inputs, `(?![A-Za-z0-9_])` disagreed with `\\b` on THREE — every
        one a non-ASCII word character:

            input                \\b           (?![A-Za-z0-9_])    (?!\\w)  SHIPPED
            src/rnd/a/b.py\u00e9        NO MATCH     b.py     🔴          NO MATCH
            src/rnd/a/b.py\u0663        NO MATCH     b.py     🔴          NO MATCH
            src/rnd/a/b.py\u4e2d        NO MATCH     b.py     🔴          NO MATCH

        ⇒ TWICE I NARROWED A CHARACTER CLASS BY HAND AND TWICE IT WAS TOO NARROW — which is the
        SAME defect this scanner has now been bitten by four times over (a sha hardcoded to one
        value, a four-name repo tuple, an enumerated separator list, and now an enumerated
        "continues a filename" class). The shipped form stops enumerating: `(?!\\w)` is `\\b`'s own
        notion of a word character, so it cannot drift out of date behind the engine.

        ⚠️ NOT REACHABLE TODAY, said plainly so nobody reads this as a live incident: there are
        ZERO non-ASCII filenames under src/rnd/ at 2026-09-05. This is a latent defect closed on
        principle, and the principle is the one the row was already about.
        """
        # 🔴 DERIVED FROM THE SHIPPED PATTERN, NOT A HAND-COPY OF IT. An earlier cut pasted the
        # extension alternation here; when the alternation was replaced by a PREDICATE (ruled
        # 2026-09-05) this test failed against a base that existed nowhere in the module. A
        # test carrying its own copy of the thing under test is measuring the copy.
        anchor = "(?!" + chr( 92 ) + "w)"          # six characters, not five — a magic number
        base   = self.mod.CITATION_PAT.pattern     # here left a stray "(" and re raised
        self.assertTrue( base.endswith( anchor ),
                         "the shipped anchor changed — RE-DERIVE this guard, do not delete it" )
        base   = base[ : -len( anchor ) ]
        with_b = re.compile( base + r"\b" )
        narrow = re.compile( base + r"(?![A-Za-z0-9_])" )   # the superseded cut, kept as a control

        # 🔴 THE CONTROL THAT MAKES THIS A TEST: the superseded form MUST truncate here, or the
        # comparison below is asserting nothing and this file would pass on any pattern at all.
        self.assertEqual( [ "src/rnd/a/b.py" ],
                          [ m.group( 0 ) for m in narrow.finditer( "src/rnd/a/b.py\u00e9" ) ],
                          "control: the ASCII-only lookahead truncates on a unicode suffix" )

        # and the shipped pattern agrees with \b on every one of them, in BOTH directions
        for text in ( "src/rnd/a/b.jsonl", "src/rnd/a/b.py_backup",
                      "src/rnd/a/b.py\u00e9", "src/rnd/a/b.py\u0663", "src/rnd/a/b.py\u4e2d",
                      "src/rnd/a/b.py", "src/rnd/a/b.md.", "src/rnd/a/b.py-x",
                      "src/rnd/a/b.py.tmp", "src/rnd/a/b.json" ):
            with self.subTest( text=text ):
                self.assertEqual( [ m.group( 0 ) for m in with_b.finditer( text ) ],
                                  [ m.group( 0 ) for m in self.mod.CITATION_PAT.finditer( text ) ],
                                  "the shipped anchor must agree with a word boundary here" )



    def test_every_extension_ends_in_a_word_character( self ):
        """
        The premise (?!\\w) rests on, pinned so an EDIT cannot quietly remove it.

        🔴 RE-DERIVED 2026-09-05 RATHER THAN DELETED — which is precisely what this guard's own
        failure message instructs the next reader to do, and I was that reader. The alternation
        (?:md|py|sh|json|txt) was replaced by the predicate [A-Za-z][A-Za-z0-9]* ("an extension
        starts with a letter"), so the old extraction found nothing and this test went red. THE
        PREMISE DID NOT CHANGE; only the shape it is read off did.

        (?!\\w) is \\b's trailing half ONLY IF the character to its left is always a word
        character. Under an alternation that reads "every alternative ends in a word character".
        Under a character class it reads "the class contains only word characters". One premise,
        two shapes, and this guard now handles both rather than assuming either.

        Ensures:
            - the shipped anchor is still (?!\\w), or this guard demands to be re-derived
            - whichever shape the extension takes, its final character can only be a word one
            - a POSITIVE CONTROL, since an empty extraction satisfies every loop below vacuously
        """
        anchor = "(?!" + chr( 92 ) + "w)"
        pat    = self.mod.CITATION_PAT.pattern
        self.assertTrue( pat.endswith( anchor ),
                         "the anchor is no longer (?!\\w) — RE-DERIVE this guard, do not delete it" )
        head = pat[ : -len( anchor ) ]

        alternation = re.search( r"\(\?:([^)]+)\)$", head )
        if alternation:
            members = alternation.group( 1 ).split( "|" )
            self.assertGreaterEqual( len( members ), 3,
                                     "POSITIVE CONTROL: a tiny extraction would satisfy the loop "
                                     "below vacuously" )
            for ext in members:
                with self.subTest( ext=ext ):
                    self.assertRegex( ext[ -1 ], r"\w",
                                      "an extension ends in a NON-word character, so the two "
                                      "anchors part company and nothing else would say so" )
        else:
            trailing = re.search( r"\[([^\]]+)\][*+]?$", head )
            self.assertIsNotNone( trailing,
                                  "CITATION_PAT ends in neither an alternation nor a character "
                                  "class — RE-DERIVE this guard rather than deleting it" )
            body = trailing.group( 1 )
            self.assertGreaterEqual( len( body ), 3,
                                     "POSITIVE CONTROL: an empty class satisfies the checks below "
                                     "vacuously" )
            self.assertNotIn( "^", body,
                              "the final class is NEGATED, so it can match a non-word character "
                              "and the premise no longer holds" )
            for ch in body.replace( "A-Za-z", "" ).replace( "0-9", "" ).replace( "a-z", "" ):
                with self.subTest( ch=ch ):
                    self.assertRegex( ch, r"\w",
                                      "the final class admits a non-word character, so the two "
                                      "anchors part company and nothing would say so" )


if __name__ == "__main__":
    unittest.main()
