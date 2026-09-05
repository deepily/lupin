"""
Scan the repo for `src/rnd/…` citations that no longer resolve, and REPORT ITS OWN CORPUS.

Row 88f4dfdb. This module exists because the same population exclusion was made TWICE by the
same author, in two sessions, and the correction in between was recorded as PROSE in a task-store
row rather than as code. A defect recorded in a document is not a control; only the code is.

🔴 THE EXCLUSION THAT BIT TWICE, AND WHY IT IS SPLIT HERE.
The obvious rule is `if path.startswith( "src/rnd/" ): skip` — a research doc citing a sibling
research doc is a RECORD, not an instruction, so skipping the tree is right for the DOCUMENTS.
It is WRONG for `src/rnd/README.md`, which is the one file in that tree whose entire job is to
send readers somewhere. Both sweeps skipped the index along with the documents and both hid the
same 52 dead links.

⇒ `INDEX_FILES` is carved out of the exclusion by name, and
`src/tests/unit/test_dead_rnd_citation_corpus_includes_the_index.py` fails if it stops being.

⚠️ THIS SCANNER DOES NOT ASSERT A COUNT AND MUST NOT BE MADE TO. A guard written today against
the live dead-citation total would ship RED on 133 sites, and a guard that ships red is one
somebody deletes. It guards the CORPUS — that the search can see what it claims to search.
"""

import os
import re
import subprocess

# a citation is a repo-relative path into src/rnd with a recognised extension
#
# 🔴 THE EXTENSION MUST BE ANCHORED ON ITS RIGHT, AND THIS COST A ROW TO FIND. Without the
# lookahead, `json` matches the first four characters of `jsonl` and the regex STOPS THERE, so the
# captured path is the real path minus its final `l`. That is not a miss — a miss reports nothing
# and looks like nothing. This reports a PRESENT path that exists nowhere: os.path.exists is asked
# about `….json`, answers False whichever way the real `.jsonl` file is, and a live citation is
# published as dead under a filename a reader cannot find by grepping the source.
#
# ⚠️ THIS COMMENT HAS BEEN WRONG TWICE AND BOTH CORRECTIONS ARE LEFT VISIBLE, because each one
# was a hand-narrowed character class and that is the defect this module keeps repeating.
#
# WRONG ONCE: "`\b` does not fix this — both `n` and `l` are word characters so the boundary never
# fires." `\b` DOES fix it. The boundary fails between `n` and `l`, the WHOLE PATTERN then fails at
# that position, and the result is NO MATCH rather than a short one.
#
# WRONG TWICE: "the underscore is the only case where a lookahead and `\b` disagree." Measured over
# twelve inputs, `(?![A-Za-z0-9_])` disagreed with `\b` on THREE, every one a non-ASCII word char:
#
#     input   (<rnd> = src/rnd, written so this COMMENT does not itself manufacture
#             the dead citations the module reports)
#                          \b          (?![A-Za-z0-9])   (?![A-Za-z0-9_])   (?!\w)  SHIPPED
#     <rnd>/a/b.jsonl      NO MATCH    NO MATCH          NO MATCH           NO MATCH
#     <rnd>/a/b.json       b.json      b.json            b.json             b.json
#     <rnd>/a/b.py_backup  NO MATCH    b.py     🔴       NO MATCH           NO MATCH
#     <rnd>/a/b.pyé         NO MATCH    b.py     🔴       b.py     🔴        NO MATCH
#
# 🔴 SO THE SHIPPED FORM STOPS ENUMERATING. `(?!\w)` is the engine's own notion of a word
# character — the same one `\b` consults — so it cannot drift out of date behind it. Every
# hand-written class here was too narrow, twice in one afternoon, and this module has now been
# bitten four times by the same shape: a sha hardcoded to one value, a four-name repo tuple, an
# enumerated separator list, and an enumerated "continues a filename" class.
#
# ⚠️ NOT REACHABLE TODAY: there are ZERO non-ASCII filenames under src/rnd/ at 2026-09-05. This is
# a latent defect closed on principle, and the principle is the one the row was already about.
#
CITATION_PAT   = re.compile( r"src/rnd/[A-Za-z0-9_.\-/]*[A-Za-z0-9_\-]\.(?:md|py|sh|json|txt)(?!\w)" )

# a markdown link, used for the index, whose targets are relative to src/rnd/
MD_LINK_PAT    = re.compile( r"\]\(([^)]+\.md)\)" )

# 🔴 the carve-out. Inside src/rnd/ but an INDEX, so it is scanned like any instructing doc.
INDEX_FILES    = ( "src/rnd/README.md", )

# an ARCHIVE is a frozen record of what was true then; a dead citation there is not a defect
ARCHIVE_PREFIX = ( "todo-history/", "history/", "src/cosa/history/", "src/cosa/rnd/" )

# the fix form embeds the dead path inside its own recovery command, so a naive re-scan re-flags
# exactly what it just fixed. These two markers are how an already-annotated site is recognised.
#
# 🔴 THESE WERE HARDCODED TO `c752ab9e` AND THAT WAS WRONG. The row this module serves names THREE
# deletion shas; deriving the set from `git log --diff-filter=D` rather than from that written list
# turns up FIVE — c752ab9e, 172cb57f, 8bf71a64, a4a27b0c, 942fe0b8. A marker keyed on one sha
# recognises one sha's cleanup and re-flags the other four's, so the scanner reports its own fix as
# the disease for 80% of the population. Measured: 40 sites annotated, only 15 stopped being
# reported. Matching ANY sha is not a generalisation for its own sake — it is the only form that
# cannot go stale the next time a doc is deleted.
ANNOTATED_NEAR = re.compile( r"\b[0-9a-f]{7,40}\^:$" )
ANNOTATED_LINE = re.compile( r"REMOVED by `?[0-9a-f]{7,40}`?" )


def tracked_files( repo_root ):
    """
    List every file git tracks, relative to the repo root.

    Requires:
        - repo_root is a directory inside a git working tree

    Ensures:
        - returns a list of repo-relative path strings
        - the list is empty only if git tracks nothing, never because the call failed silently

    Raises:
        - subprocess.CalledProcessError if git cannot answer
    """
    out = subprocess.run(
        [ "git", "-C", repo_root, "ls-files" ], capture_output=True, text=True, check=True
    ).stdout
    return out.split()


def is_archive( path ):
    """
    Ensures: True iff `path` is a frozen historical record rather than an instructing document.
    """
    return path.startswith( ARCHIVE_PREFIX ) or ".backup-" in path


def in_corpus( path ):
    """
    Decide whether a tracked file belongs in the scanned corpus.

    🔴 THE INDEX CARVE-OUT LIVES HERE. `src/rnd/` is skipped because a research doc citing a
    sibling is a record — but `INDEX_FILES` is scanned, because an index instructs.

    Requires:
        - path is a repo-relative path string

    Ensures:
        - returns True for every tracked file except src/rnd documents that are not an index
        - returns True for every member of INDEX_FILES
    """
    if path in INDEX_FILES:            return True
    if path.startswith( "src/rnd/" ):  return False
    return True


# 🔴 A `src/rnd/…` MATCH CAN BELONG TO ANOTHER REPO, AND THEN IT IS NOT OURS TO RESOLVE.
# Sibling repos use the same `src/rnd/` layout, so a correctly-written cross-repo citation reads
# `planning-is-prompting/src/rnd/<doc>.md`. CITATION_PAT matches the `src/rnd/…` TAIL of that path
# and the prefix sits outside the match, so the resolver looks for the doc in LUPIN, does not find
# it, and reports a correct citation as dead. Measured: 15 of 52 cross-repo sites were already
# prefixed properly and every one was being flagged.
#
# This is the mirror of the annotation defect above: there the scanner failed to recognise its own
# FIX, here it fails to recognise a citation that was never broken.
#
# 🔴 AND THE FIRST FIX FOR IT WAS A HAND-TYPED TUPLE OF FOUR NAMES AGAINST FOURTEEN REGISTERED
# REPOS — the same shape as the hardcoded sha above, one level along. `external repos` in
# lupin-app.ini already names every registered sibling, so the names are DERIVED from that key.
# A list somebody must remember to extend is not a control.
#
# Three corrections the derivation cannot make on its own, each measured rather than assumed:
#   · `lupin` IS in that key and IS this repo. Treating it as cross-repo stops the scanner
#     resolving its own citations — 61 sites — so it is removed by name.
#   · `lupin-plugin-firefox` is a real sibling and is NOT registered, so pure derivation DROPS a
#     prefix that was already working. The unregistered siblings are UNIONed back in.
#   · a trailing slash is NOT appended any more; the separator is handled below, and a name
#     without one would suffix-match `lupin` inside `lupin-mobile`. The word-boundary lookbehind
#     in the pattern is what replaces it.
THIS_REPO             = "lupin"
UNREGISTERED_SIBLINGS = ( "lupin-plugin-firefox", )

# 🔴 THE INI IS READ FROM BESIDE THIS FILE, NOT THROUGH `LUPIN_ROOT`. This module ships inside the
# tree it scans, and a root taken from the environment names whichever checkout the caller's shell
# happens to point at — the wrong-tree defect that has now bitten three other scripts in this repo.
# A script shipped inside its own tree can be disagreed with by the environment, never informed by
# it, so its location is the honest source. `scan()` still takes an explicit repo_root: repo NAMES
# are fleet-wide configuration, the tree being scanned is the caller's business, and they are
# deliberately not the same question.
_INI_PATH = os.path.join( os.path.dirname( os.path.dirname( os.path.abspath( __file__ ) ) ),
                          "conf", "lupin-app.ini" )

# 🔴 THE SEPARATOR IS NOT ALWAYS A SLASH, AND ENUMERATING THE FORMS IS THIS SAME DEFECT AGAIN.
# Counted across the tree, the text sitting between a repo name and `src/rnd/`:
#
#     /  121     →  8     → `  7     `  5     >/  2     (empty)  1
#
# 22 non-slash against 121 slash, in FOUR distinct shapes. Special-casing the arrow fixes 8 of the
# 22 and LOOKS finished, which is exactly how the four-name tuple above came to exist.
#
# ⇒ RULED BY MARÍA 2026-09-05: match a repo name followed by any SHORT RUN of separator
# characters — NOT an explicit list of the four observed shapes. Her reason, kept verbatim because
# it is the durable half: "an explicit list is a rule that depends on someone remembering to update
# it, which is not installed in this project."
#
# ⚠️ IT ERRS TOWARD NOT FLAGGING, AND THAT IS THE DELIBERATE DIRECTION. An unrecognised separator
# leaves a correct cross-repo citation reported as dead — a false positive a later pass catches.
# The opposite error silences a real dead link, and nothing catches that. The run is capped at 6
# against a measured maximum of 4, so a fifth shape a little wider than today's still lands.
SEPARATOR_RUN = r"[\s`'\"()\[\]<>:,;/|*→–—-]{0,6}"


def cross_repo_names( ini_path=_INI_PATH ):
    """
    Read the sibling-repo names a `src/rnd/…` citation may legitimately belong to.

    Requires:
        - ini_path names lupin-app.ini, carrying an `external repos = a, b, c` key

    Ensures:
        - returns a tuple of repo names, LONGEST FIRST so alternation cannot settle for a
          shorter name that is a prefix of a longer one
        - THIS_REPO is absent from the result and UNREGISTERED_SIBLINGS are present in it
        - no name carries a trailing slash; the separator is the pattern's business

    Raises:
        - OSError if ini_path cannot be read
        - ValueError if the `external repos` key is absent, because a silent fallback here
          would narrow the scanner's idea of the fleet with nothing in its output saying so
    """
    with open( ini_path, "r", encoding="utf-8" ) as fh:
        for raw in fh:
            line = raw.strip()
            if line.startswith( "#" ) or "=" not in line: continue
            key, _, value = line.partition( "=" )
            if key.strip() != "external repos": continue
            registered = [ n.strip() for n in value.split( "," ) if n.strip() ]
            names      = set( registered ) | set( UNREGISTERED_SIBLINGS )
            names.discard( THIS_REPO )
            return tuple( sorted( names, key=lambda n: ( -len( n ), n ) ) )
    raise ValueError( "no `external repos` key in %s — cannot derive the sibling-repo set" % ini_path )


def cross_repo_pattern( names ):
    """
    Build the pattern that recognises `<sibling-repo><separators>` immediately before a match.

    Requires:
        - names is a non-empty iterable of repo names

    Ensures:
        - returns a compiled regex anchored at end-of-string
        - the lookbehind forbids a name that is merely the tail of a longer word, so
          `xlupin-mobile/` is not read as `lupin-mobile/`
    """
    alternation = "|".join( re.escape( n ) for n in names )
    return re.compile( r"(?<![A-Za-z0-9_.\-])(?:%s)%s$" % ( alternation, SEPARATOR_RUN ) )


CROSS_REPO_NAMES = cross_repo_names()
CROSS_REPO_RE    = cross_repo_pattern( CROSS_REPO_NAMES )


def is_cross_repo( line, col ):
    """
    Decide whether the `src/rnd/…` match at `col` is the tail of ANOTHER repo's path.

    Requires:
        - line is the full source line (or a dewrapped logical line), col is the match start

    Ensures:
        - returns True iff the text immediately before the match names a sibling repo,
          in the slash form OR separated from it by a short run of punctuation
        - returns False for a bare lupin-relative citation, so those are still resolved here
        - returns False for a lookalike directory that is not a registered sibling
    """
    return bool( CROSS_REPO_RE.search( line[ : col ] ) )


def is_annotated( line, col ):
    """
    Ensures: True iff the match at `col` is already-fixed text rather than a live dead citation —
             either it sits inside a recovery command, or its line carries the REMOVED marker.
    """
    return bool( ANNOTATED_NEAR.search( line[ max( 0, col - 45 ) : col ] ) ) \
        or bool( ANNOTATED_LINE.search( line ) )


# 🔴 A CITATION SPLIT ACROSS A LINE WRAP IS INVISIBLE TO A LINE-ORIENTED SCANNER, AND ITS ABSENCE
# LOOKS EXACTLY LIKE A CLEAN TREE. `scan` reads the file with readlines() and runs CITATION_PAT
# per line, so a path broken over two physical lines matches neither half and is silently never
# checked. Measured: 49 wrapped lines carry a src/rnd citation, 44 of them lupin-relative, 6 with
# dead targets, and 3 of those 6 are split by the wrap — three real dead links the scanner has
# never once reported.
#
# ⚠️ AND A PLAIN GREP FOR ANY OF THEM IS A FALSE GREEN IN BOTH DIRECTIONS — the string you would
# search for does not exist on either line before OR after the fix. That is how this hid across
# two rounds of review.
#
# The three wrap shapes in the tree, all three of which these two helpers must join:
#     prose/markdown   `…2026.08.22-qa-card-` + `registry-driven-….md`      (head ends in `-`)
#     path continuation `…session_bridge/` + `creating-unique-session-id/…` (head ends in `/`)
#     python concat     `"…/live-runs/"` + `"sentence-band-….jsonl"`        (quotes both sides)
_CONT_MARKER = re.compile( r"^\s*(?:#+|//+|\*|;|>)\s*" )


def wrap_head( line ):
    """
    Return `line` stripped of its wrap furniture, or None if the line does not continue.

    Requires:
        - line is one physical source line, newline optional

    Ensures:
        - returns the text to join FROM iff it ends in `-` or `/` once a trailing line
          continuation backslash and one trailing quote have been removed
        - returns None otherwise, so an ordinary line is never joined to its neighbour
    """
    s = line.rstrip( "\n" ).rstrip()
    if s.endswith( "\\" ):       s = s[ :-1 ].rstrip()
    if s[ -1: ] in ( '"', "'" ): s = s[ :-1 ]
    return s if s[ -1: ] in ( "-", "/" ) else None


def wrap_tail( line ):
    """
    Return `line` stripped of what an author put at the START of a continuation line.

    Requires:
        - line is one physical source line, newline optional

    Ensures:
        - returns the text to join TO, with leading whitespace, a comment marker and one
          opening quote removed — the marker matters because an INI or shell comment wraps
          with a `#` that is not part of the path
    """
    s = _CONT_MARKER.sub( "", line.rstrip( "\n" ) ).lstrip()
    return s[ 1: ] if s[ :1 ] in ( '"', "'" ) else s


def scan( repo_root ):
    """
    Scan the corpus and report BOTH the findings and the corpus they came from.

    Requires:
        - repo_root is a directory inside a git working tree

    Ensures:
        - returns a dict with keys: scanned, skipped, live, dead, index_scanned
        - `scanned` counts files actually read, so a caller can tell an empty result from an
          empty search — an absence is the one finding that looks identical either way
        - `index_scanned` names every INDEX_FILES member that was reached, so the exclusion
          that bit twice is visible in the OUTPUT rather than only in the source
        - already-annotated sites are not reported as dead
    """
    scanned, skipped   = [], 0
    live, dead         = set(), []

    for rel in tracked_files( repo_root ):
        if not in_corpus( rel ):
            skipped += 1
            continue
        try:
            with open( os.path.join( repo_root, rel ), "r", encoding="utf-8" ) as fh:
                lines = fh.readlines()
        except ( UnicodeDecodeError, OSError ):
            skipped += 1
            continue
        scanned.append( rel )

        def record( text, m, n, rel=rel ):
            """Classify one match. `text` may be a physical line or a dewrapped logical one."""
            path = m.group( 0 )
            if is_cross_repo( text, m.start() ):
                return
            if os.path.exists( os.path.join( repo_root, path ) ):
                live.add( path )
            elif not is_annotated( text, m.start() ):
                dead.append( { "path": path, "file": rel, "line": n,
                               "archive": is_archive( rel ) } )

        for n, line in enumerate( lines, 1 ):
            for m in CITATION_PAT.finditer( line ):
                record( line, m, n )

            # 🔴 THE STRADDLE PASS, AND IT DELIBERATELY LOOKS AT NOTHING ELSE. Joining a line to
            # the next and re-scanning the whole join would report every citation TWICE — once on
            # its own line, once inside the join. Only a match that CROSSES the seam is new, so
            # that is the only kind taken here. It is reported at the line the path STARTS on,
            # which is where a reader has to go to fix it.
            head = wrap_head( line )
            if head is None or n >= len( lines ):
                continue
            joined = head + wrap_tail( lines[ n ] )
            for m in CITATION_PAT.finditer( joined ):
                if m.start() < len( head ) < m.end():
                    record( joined, m, n )

    return {
        "scanned"       : scanned,
        "skipped"       : skipped,
        "live"          : sorted( live ),
        "dead"          : dead,
        "index_scanned" : [ f for f in INDEX_FILES if f in scanned ],
    }


def scan_index_links( repo_root, index_rel="src/rnd/README.md" ):
    """
    Resolve the markdown links in the rnd index, whose targets are relative to `src/rnd/`.

    Kept separate from `scan` on purpose: these are a DIFFERENT POPULATION with a different fix
    shape — a list of links in one file, versus per-citation prose surgery across the tree. They
    must not be merged into one headline number.

    Requires:
        - index_rel names a markdown file inside the repo

    Ensures:
        - returns ( live_count, dead_targets ) with dead_targets a list of link targets
        - live_count > 0 is the caller's positive control that the resolver works

    Raises:
        - FileNotFoundError if the index is missing
    """
    live, dead = 0, []
    with open( os.path.join( repo_root, index_rel ), "r", encoding="utf-8" ) as fh:
        text = fh.read()
    base = os.path.dirname( index_rel )
    for m in MD_LINK_PAT.finditer( text ):
        target  = m.group( 1 )
        resolved = target if target.startswith( "src/" ) else os.path.normpath(
            os.path.join( base, target ) )
        if os.path.exists( os.path.join( repo_root, resolved ) ): live += 1
        else:                                                     dead.append( target )
    return live, dead
