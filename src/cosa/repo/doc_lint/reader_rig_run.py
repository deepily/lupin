"""
Command line for the reader-test rig: fixed questions over a file at two revisions.

    python -m cosa.repo.doc_lint.reader_rig_run --old-rev A --new-rev B --questions q.json \
        --reader-model ... --grader-model ... --ledger run.jsonl --reader-cap N --grader-cap N --out report.json

The reader sees the file's documentation text only, never its code. Maria's design choice: the code is
the same in both revisions. Leaving it in would let the reader answer from code and hide a lost
docstring claim. Each module, class and function contributes its signature line and docstring, and every
# comment line is kept, in file order.

The extraction leaves out, on both revisions: decorators, attribute docstrings (a string under an
assignment) and any string that is not a docstring. Signatures are re-rendered by ast.unparse on one
line, so line breaks and quote style in the source are not shown to the reader.

The runner scores one question at a time through reader_rig.score_text. It tries a question up to
three times when a reply is off contract or a call fails. A question that fails all three is unscored.
It is then dropped from both texts for that run, so old and new are compared on the same questions.

Every model id and both call caps are required. Rerunning the same command resumes from the ledger.

A ledger grade carries no mode, so a rerun with --strict-grader reuses grades salvaged earlier.
Start a strict run on a fresh ledger; otherwise its report says strict but holds salvaged scores.
"""

import argparse
import ast
import asyncio
import copy
import dataclasses
import hashlib
import io
import json
import re
import subprocess
import sys
import tokenize

from claude_agent_sdk import AssistantMessage, TextBlock

import cosa.utils.util as cu

from . import harness_runner, model_transport, reader_rig

DOC_NODES    = ( ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef )
ATTEMPTS     = 3
RAW_HEAD     = 600     # the start of a reply names what the grader was weighing
RAW_TAIL     = 1400    # the end holds its last words and the score object, so the tail is the larger share
RAW_LIMIT    = RAW_HEAD + RAW_TAIL
SCORE_MENTION = re.compile( r'\{[^{}]*"score"[^{}]*\}' )
SCORE_STRICT  = re.compile( r'\{\s*"score"\s*:\s*([01])\s*\}' )
FENCE_OPEN    = re.compile( r"^```(?:json)?" )


class RunRefused( Exception ):
    """The run cannot start; the message names why."""


def parse_args( argv ):
    """
    Parse the command line.

    Requires:
        - argv is the argument list without the program name

    Ensures:
        - returns the parsed namespace; models, ledger and both caps are required and have no default
        - --runs defaults to 3
    """
    parser = argparse.ArgumentParser( description="Run the reader test over a file at two revisions." )
    parser.add_argument( "--old-rev", required=True, help="git revision holding the old text" )
    parser.add_argument( "--new-rev", required=True, help="git revision holding the new text" )
    parser.add_argument( "--questions", required=True, help="JSON file: { count, questions: [ { id, file, question, key_points, ... } ] }" )
    parser.add_argument( "--reader-model", required=True )
    parser.add_argument( "--grader-model", required=True )
    parser.add_argument( "--runs", type=int, default=3 )
    parser.add_argument( "--ledger", required=True, help="append-only ledger of finished calls; reuse it to resume" )
    parser.add_argument( "--reader-cap", type=int, required=True, help="most reader calls this ledger may ever hold" )
    parser.add_argument( "--grader-cap", type=int, required=True, help="most grader calls this ledger may ever hold" )
    parser.add_argument( "--out", help="where to write the JSON report" )
    parser.add_argument( "--file-prefix", default="", help="put in front of each question's file before reading it from git, e.g. src/cosa/rest/" )
    parser.add_argument( "--repo", default=None, help="git repository to read from; default is the project root" )
    parser.add_argument( "--claude-cli-path", help="run this Claude Code binary instead of the SDK's bundled one" )
    parser.add_argument( "--strict-grader", action="store_true", help="refuse every grader reply that is not a bare score object; the default salvages a score that follows the grader's reasoning; use a fresh ledger, since cached grades are reused whatever their mode" )
    parser.add_argument( "--dry-run", action="store_true", help="print sizes and projected calls, make no model call" )
    return parser.parse_args( argv )


def load_questions( path ):
    """
    Read and check the questions file.

    Requires:
        - path names a readable file

    Ensures:
        - returns ( questions, sha256 of the file's bytes ); each question is the file's own dict
        - the file's count equals the number of questions

    Raises:
        - RunRefused if the file is not JSON of the expected shape, count differs from the number of
          questions, an id repeats, or a question lacks an id, a file, a question or any key_points
    """
    with open( path, "rb" ) as f: raw = f.read()
    try:
        data = json.loads( raw )
    except ValueError as e:
        raise RunRefused( f"questions file is not JSON: {e}" ) from e
    if not isinstance( data, dict ) or not isinstance( data.get( "questions" ), list ) or not data[ "questions" ]:
        raise RunRefused( "questions file must be an object holding a non-empty questions list" )
    questions = data[ "questions" ]
    if data.get( "count" ) != len( questions ):
        raise RunRefused( f"count is {data.get( 'count' )!r} but the file holds {len( questions )} questions" )
    seen = set()
    for q in questions:
        if not isinstance( q, dict ): raise RunRefused( "every question must be an object" )
        for field in ( "id", "file", "question" ):
            if not isinstance( q.get( field ), str ) or not q[ field ].strip(): raise RunRefused( f"question {q.get( 'id' )!r} has no {field}" )
        if q[ "id" ] in seen: raise RunRefused( f"id {q[ 'id' ]!r} repeats" )
        seen.add( q[ "id" ] )
        points = q.get( "key_points" )
        if not isinstance( points, list ) or not points or not all( isinstance( p, str ) and p.strip() for p in points ):
            raise RunRefused( f"question {q[ 'id' ]!r} has no key_points" )
    return questions, hashlib.sha256( raw ).hexdigest()


def check_prefix( prefix ):
    """
    Refuse a file prefix that could leave the repository.

    Requires:
        - prefix is a string, empty for none

    Ensures:
        - returns None for a prefix that is empty or relative and holds no ".." part

    Raises:
        - RunRefused if the prefix starts with a slash or contains ".."
    """
    if prefix.startswith( "/" ) or ".." in prefix: raise RunRefused( f"--file-prefix {prefix!r} must be relative and hold no '..'" )


def rig_questions( questions ):
    """
    Return the questions as the rig takes them: id, question and one key string, nothing else.

    Ensures:
        - the key is the key_points joined with "; "
        - common_wrong_answer, verified, symbols and file are dropped
    """
    return [ { "id": q[ "id" ], "question": q[ "question" ], "key": "; ".join( q[ "key_points" ] ) } for q in questions ]


def group_by_file( questions ):
    """
    Group questions by their file.

    Requires:
        - questions is a list of dicts that each hold "file"

    Ensures:
        - returns { file: [ question, ... ] }, files and questions in the order first seen
    """
    groups = {}
    for q in questions: groups.setdefault( q[ "file" ], [] ).append( q )
    return groups


def resolve_rev( repo, rev ):
    """
    Return the full sha a revision names.

    Raises:
        - RunRefused if git cannot resolve it to a commit
    """
    done = subprocess.run( [ "git", "-C", repo, "rev-parse", "--verify", "--end-of-options", rev + "^{commit}" ], capture_output=True, text=True )
    if done.returncode != 0: raise RunRefused( f"revision {rev!r} does not resolve to a commit in {repo}" )
    return done.stdout.strip()


def read_at( repo, sha, path ):
    """
    Return a file's text at a commit, read from git and never from the working tree.

    Raises:
        - RunRefused if the file is not in that commit
    """
    done = subprocess.run( [ "git", "-C", repo, "show", f"{sha}:{path}" ], capture_output=True )
    if done.returncode != 0: raise RunRefused( f"{path} is not in commit {sha[ :9 ]}" )
    return done.stdout.decode( "utf-8" )


def signature_line( node ):
    """
    Return the one-line signature of a class or function, with no decorators and no body.

    Requires:
        - node is an ast.ClassDef, FunctionDef or AsyncFunctionDef

    Ensures:
        - returns the signature as ast.unparse renders it, on one line; node is not changed
    """
    bare = copy.copy( node )
    bare.body           = [ ast.Pass() ]
    bare.decorator_list = []
    return ast.unparse( bare ).split( "\n    pass" )[ 0 ].replace( "\n", " " )


def extract_doc_text( source, path="<file>" ):
    """
    Build the text a reader may use: signatures, docstrings and comments, with no code bodies.

    Requires:
        - source is Python source text

    Ensures:
        - each class and function (nested ones too) gives its signature line then its docstring
        - the module docstring and every # comment line are included
        - everything is in file order, and the same extraction runs on both revisions

    Raises:
        - RunRefused if source is not valid Python
    """
    try:
        tree   = ast.parse( source )
        tokens = list( tokenize.generate_tokens( io.StringIO( source ).readline ) )
    except ( SyntaxError, tokenize.TokenError ) as e:
        raise RunRefused( f"{path} does not parse: {e}" ) from e
    items = []
    for node in ast.walk( tree ):
        if not isinstance( node, DOC_NODES ): continue
        line = 0 if isinstance( node, ast.Module ) else node.lineno
        if not isinstance( node, ast.Module ): items.append( ( line, 0, signature_line( node ) ) )
        doc = ast.get_docstring( node )
        if doc is not None: items.append( ( line, 1, doc ) )
    items.extend( ( t.start[ 0 ], 2, t.string ) for t in tokens if t.type == tokenize.COMMENT )
    return "\n".join( text for _, _, text in sorted( items, key=lambda i: ( i[ 0 ], i[ 1 ] ) ) )


def projected_calls( texts, questions, config, ledger ):
    """
    Count the calls still owed for these texts, given what the ledger already holds.

    Requires:
        - texts is a list of document texts; questions are { id, question, key } dicts

    Ensures:
        - returns { "reader": n, "grader": n }, each the worst case ( questions x texts x runs ) less the
          calls the ledger already finished, keyed the way the rig keys them
        - a reader call not yet made is counted with its grader call; a made one with its grader call
          only if that is missing
    """
    reader_keys, grader_keys = set(), set()
    owed_pairs = 0
    for text in texts:
        for q in questions:
            base = "|".join( [ harness_runner.text_hash( text ), harness_runner.text_hash( q[ "question" ] ), reader_rig.PROMPT_VERSION ] )
            for run in range( config.runs ):
                rkey   = f"read|{base}|{config.reader_model}|{run}"
                answer = ledger.get( rkey )
                if answer is None:
                    if rkey not in reader_keys:
                        reader_keys.add( rkey )
                        owed_pairs += 1
                    continue
                grader_keys.add( f"grade|{base}|{harness_runner.text_hash( q[ 'key' ] + chr( 0 ) + answer )}|{config.grader_model}" )
    missing = { k for k in grader_keys if ledger.get( k ) is None }
    return { "reader": len( reader_keys ), "grader": owed_pairs + len( missing ) }


def take_score_object( raw ):
    """
    Take the grader's score object out of a reply that reasons first and ends with it.

    Requires:
        - raw is the text of one grader reply

    Ensures:
        - returns the text '{"score": 0}' or '{"score": 1}' when the reply holds text before the object
          (more than a code fence), exactly one object that mentions score, that object is a score of 0 or 1
          with no other key, and nothing follows it but whitespace and an optional closing code fence
        - returns None otherwise, so the rig sees the reply unchanged: a bare object (fenced or not), no
          object, two or more objects, text after the object, a score other than 0 or 1
    """
    text = raw.strip()
    found = SCORE_MENTION.findall( text )
    if len( found ) != 1: return None
    taken = SCORE_STRICT.fullmatch( found[ -1 ] )
    if taken is None: return None
    start = text.rfind( found[ -1 ] )
    if not FENCE_OPEN.sub( "", text[ :start ].strip() ).strip(): return None
    if text[ start + len( found[ -1 ] ): ].strip() not in ( "", "```" ): return None
    return '{"score": ' + taken.group( 1 ) + "}"


def cut_raw( raw ):
    """
    Return a raw reply cut to head and tail, with the cut marked.

    Requires:
        - raw is the text of one model reply

    Ensures:
        - a reply of RAW_LIMIT characters or fewer is returned unchanged
        - a longer one is returned as its first RAW_HEAD characters, a line "[... N characters cut ...]" with N the
          number of characters left out, and its last RAW_TAIL characters
    """
    if len( raw ) <= RAW_LIMIT: return raw
    return raw[ :RAW_HEAD ] + f"\n[... {len( raw ) - RAW_LIMIT} characters cut ...]\n" + raw[ -RAW_TAIL: ]


class CallTracker:
    """
    Wrap a query function: remember the last step and raw reply, and maybe salvage a score.

    Requires:
        - inner is an async generator function with sdk_query's signature ( prompt=..., options=... )
        - salvage is True to hand the rig only the score object of a grader reply that reasons first (see take_score_object)

    Ensures:
        - after a call, step is "reader" or "grader" by the system prompt and raw is the reply text so far
        - salvaged is None, or { score, raw } when the last call was a grader call whose reply was cut down to its object
        - a reader reply is never changed, and a grader reply is changed only by salvage
        - every other message passes through unchanged
    """

    def __init__( self, inner, salvage=True ):
        self.inner    = inner
        self.salvage  = salvage
        self.step     = None
        self.raw      = ""
        self.salvaged = None

    async def __call__( self, prompt, options ):
        self.step     = "reader" if options.system_prompt == reader_rig.READER_SYSTEM else "grader"
        self.raw      = ""
        self.salvaged = None
        messages      = []
        async for message in self.inner( prompt=prompt, options=options ):
            messages.append( message )
            if isinstance( message, AssistantMessage ): self.raw += "".join( b.text for b in message.content if isinstance( b, TextBlock ) )
        taken = take_score_object( self.raw ) if self.salvage and self.step == "grader" else None
        if taken is None:
            for message in messages: yield message
            return
        self.salvaged = { "score": json.loads( taken )[ "score" ], "raw": cut_raw( self.raw ) }
        first = True
        for message in messages:
            if not isinstance( message, AssistantMessage ): yield message
            elif first:
                first = False
                yield dataclasses.replace( message, content=[ TextBlock( taken ) ] )


async def score_question( text, question, config, run, ledger, query_fn, salvage=True ):
    """
    Score one question on one text for one run, trying up to three times.

    Requires:
        - question is one { id, question, key } dict; query_fn is None or a stand-in for the SDK
        - salvage is False to hand the rig every grader reply as the model wrote it

    Ensures:
        - returns ( 1 or 0, None, salvaged ) on the first attempt that gets a parseable reply to both steps;
          salvaged is { score, raw } when that attempt's grader reply was cut down to its score object, else None
        - returns ( None, { step, error, raws }, None ) when every attempt failed: the step and error of the last
          attempt, and raws holding the raw reply of every attempt, each cut by cut_raw to its head and tail
        - a ModelUnavailableError ends the attempts at once, and is reported as the last attempt
        - a retry is a real call, charged to the cap; a reader answer cached after it parsed is not asked again
        - a score read from the ledger, not from a call made now, reports no salvage

    Raises:
        - model_transport.CallBudgetExceeded: a cap is not a failure to retry
    """
    tracker = CallTracker( model_transport.sdk_query if query_fn is None else query_fn, salvage )
    raws    = []
    for _ in range( ATTEMPTS ):
        try:
            return int( await reader_rig.score_text( text, [ question ], config, run, ledger=ledger, query_fn=tracker ) ), None, tracker.salvaged
        except ( reader_rig.ReaderParseError, model_transport.ModelCallError ) as e:
            error = f"{type( e ).__name__}: {e}"
            raws.append( cut_raw( tracker.raw ) )
            if isinstance( e, model_transport.ModelUnavailableError ): break
    return None, { "step": tracker.step, "error": error, "raws": raws }, None


async def score_pair( old_text, new_text, question, config, run, ledger, query_fn, salvage=True ):
    """
    Score one question and run on both texts.

    Ensures:
        - returns ( old, new ), each the three-part result score_question returns
        - when the two texts are identical the question is scored once and both sides share the result, so a
          reply that never parses is not retried a second time for the same words

    Raises:
        - model_transport.CallBudgetExceeded when a cap stops a call
    """
    old = await score_question( old_text, question, config, run, ledger, query_fn, salvage )
    if new_text == old_text: return old, old
    return old, await score_question( new_text, question, config, run, ledger, query_fn, salvage )


def verdict_word( old_total, new_total, dropped ):
    """
    Name the outcome in capitals: incomplete, pass or fail.

    Requires:
        - old_total and new_total are whole numbers of answers graded 1 over the same compared pairs
        - dropped is the count of pairs left out because a text could not be scored

    Ensures:
        - returns "INCOMPLETE" when dropped is above zero, whatever the totals
        - otherwise returns "PASS" when new_total is at least old_total, else "FAIL"
    """
    if dropped: return "INCOMPLETE"
    return "PASS" if new_total >= old_total else "FAIL"


async def score_file( path, old_text, new_text, group, config, ledger, query_fn, halt, salvage=True ):
    """
    Score every question of one file on both texts for every run, on the same questions.

    Requires:
        - group is the file's questions as { id, question, key } dicts
        - halt is a dict { "reason": None } shared by every file of the run
        - salvage is False for the strict grader, which refuses every reply that is not a bare score object

    Ensures:
        - a question and run that fails to score on either text is dropped from both totals
        - when a cap stops a call, halt["reason"] takes its message; that pair and every later pair, in this
          file and the next, make no call and are recorded unscored on both texts with step "cap"
        - returns { old_scores, new_scores, old_total, new_total, compared, dropped, old_answered, new_answered,
          unscored_records, salvaged_records, by_question, old_mean, new_mean, passes, verdict }, totals being whole numbers of answers graded 1
        - each unscored record holds file, text (old or new, never sent to a model), run, id, step, error and raws
        - each salvaged record holds file, text, run, id, the score taken and the raw reply cut by cut_raw to its head and tail; only
          pairs that were compared get one, since only they are in the totals
        - by_question is { question id: { old, new, old_total, new_total } } in the group's order; old and new list that
          text's score for each run, 1 or 0, or None when that text was not scored (failed or stopped by a cap); the
          two totals add only the pairs that were compared, so over the questions they sum to the file's old_total and new_total
        - old_mean and new_mean are None when nothing was compared
        - passes is None when any pair was dropped, else new_total >= old_total
    """
    totals    = { "old": 0, "new": 0 }
    answered  = { "old": 0, "new": 0 }
    per_run   = { "old": [], "new": [] }
    records   = []
    salvaged  = []
    by_question = { q[ "id" ]: { "old": [], "new": [], "old_total": 0, "new_total": 0 } for q in group }
    compared  = 0
    dropped   = 0
    for run in range( config.runs ):
        run_totals, run_compared = { "old": 0, "new": 0 }, 0
        for q in group:
            outcome = None
            if halt[ "reason" ] is None:
                try:
                    outcome = await score_pair( old_text, new_text, q, config, run, ledger, query_fn, salvage )
                except model_transport.CallBudgetExceeded as e:
                    halt[ "reason" ] = str( e )
            if outcome is None:
                stopped = { "step": "cap", "error": halt[ "reason" ], "raws": [] }
                outcome = ( ( None, stopped, None ), ( None, stopped, None ) )
            ( old, old_failure, old_salvage ), ( new, new_failure, new_salvage ) = outcome
            by_question[ q[ "id" ] ][ "old" ].append( old )
            by_question[ q[ "id" ] ][ "new" ].append( new )
            for label, failure in ( ( "old", old_failure ), ( "new", new_failure ) ):
                if failure is not None: records.append( dict( failure, file=path, text=label, run=run, id=q[ "id" ] ) )
            answered[ "old" ] += old is not None
            answered[ "new" ] += new is not None
            if old is None or new is None:
                dropped += 1
                continue
            for label, taken in ( ( "old", old_salvage ), ( "new", new_salvage ) ):
                if taken is not None: salvaged.append( dict( taken, file=path, text=label, run=run, id=q[ "id" ] ) )
            compared     += 1
            run_compared += 1
            run_totals[ "old" ] += old
            run_totals[ "new" ] += new
            by_question[ q[ "id" ] ][ "old_total" ] += old
            by_question[ q[ "id" ] ][ "new_total" ] += new
        for label in ( "old", "new" ):
            totals[ label ] += run_totals[ label ]
            per_run[ label ].append( run_totals[ label ] / run_compared if run_compared else None )
    return { "old_scores": per_run[ "old" ], "new_scores": per_run[ "new" ], "old_total": totals[ "old" ], "new_total": totals[ "new" ],
             "compared": compared, "dropped": dropped, "old_answered": answered[ "old" ], "new_answered": answered[ "new" ], "unscored_records": records, "salvaged_records": salvaged, "by_question": by_question,
             "old_mean": totals[ "old" ] / compared if compared else None, "new_mean": totals[ "new" ] / compared if compared else None,
             "passes": None if dropped else totals[ "new" ] >= totals[ "old" ], "verdict": verdict_word( totals[ "old" ], totals[ "new" ], dropped ) }


def summarize( per_file ):
    """
    Return the overall figures over every file's compared pairs.

    Requires:
        - per_file is { file: result of score_file }

    Ensures:
        - returns { compared, dropped, salvaged, old_answered, new_answered, unscored, old_total, new_total, old_mean, new_mean, passes, verdict }
        - salvaged is the number of salvaged records over all files, one per text answer
        - each total is the sum of the file totals, so a file counts by its compared pairs, which is its question count times its runs
          unless pairs were dropped
        - passes compares the whole-number totals, never the float means, and is None when any pair was dropped
        - verdict says incomplete when any pair was dropped
        - the means are None when nothing was compared
    """
    old      = sum( r[ "old_total" ] for r in per_file.values() )
    new      = sum( r[ "new_total" ] for r in per_file.values() )
    compared = sum( r[ "compared" ] for r in per_file.values() )
    dropped  = sum( r[ "dropped" ] for r in per_file.values() )
    return { "compared": compared, "dropped": dropped, "salvaged": sum( len( r[ "salvaged_records" ] ) for r in per_file.values() ),
             "old_answered": sum( r[ "old_answered" ] for r in per_file.values() ),
             "new_answered": sum( r[ "new_answered" ] for r in per_file.values() ), "unscored": sum( len( r[ "unscored_records" ] ) for r in per_file.values() ),
             "old_total": old, "new_total": new, "old_mean": old / compared if compared else None, "new_mean": new / compared if compared else None,
             "passes": None if dropped else new >= old, "verdict": verdict_word( old, new, dropped ) }


def refuse( message ):
    """
    Print a refusal to stderr.

    Requires:
        - message is a string or an exception

    Ensures:
        - prints "REFUSED: " and the message, and returns 2
    """
    print( f"REFUSED: {message}", file=sys.stderr )
    return 2


def main( argv, query_fn=None ):
    """
    Run the reader test and write the report.

    Requires:
        - argv is the argument list without the program name
        - query_fn, when given, stands in for the SDK in tests

    Ensures:
        - returns 0 after printing a per-file line, an overall line and the calls spent per model
        - returns 2 before anything else when --runs is below 1
        - returns 2 and makes no model call when --file-prefix starts with a slash or contains ".."
        - --file-prefix goes in front of each question's file before the file is read from git; reports name the full paths
        - returns 2 and makes no model call when the questions file is refused (count differs, an id
          repeats, a question has no key_points), a revision or file cannot be read from git, the two
          model ids are equal or a cap is not an int of zero or more
        - returns 2 and makes no model call when the worst case of the calls still owed, each counted three
          times and added to those the ledger's call count already holds, passes --reader-cap or --grader-cap
        - returns 3 after writing the report when any question and run could not be scored; the verdict
          says incomplete and the stderr line gives the count of unscored answers; without --out the unscored
          records are printed to stderr, one JSON object per line
        - a cap reached mid-run does not end the run with a traceback: the report holds what was scored, the
          pairs after it are recorded unscored with step "cap", and the exit code is 3
        - a rerun against a full ledger makes zero calls
        - with --dry-run no model is contacted and nothing is written
        - the report holds both full shas, the questions file's sha256, the model ids, runs and the
          rig's prompt version

    """
    args = parse_args( argv )
    if args.runs < 1: return refuse( f"--runs must be 1 or more, got {args.runs}" )
    try:
        repo = args.repo if args.repo is not None else cu.get_project_root()
        if args.reader_model == args.grader_model: raise RunRefused( "reader and grader model ids must differ: the call caps are counted per model id" )
        check_prefix( args.file_prefix )
        questions, questions_sha = load_questions( args.questions )
        questions                = [ dict( q, file=args.file_prefix + q[ "file" ] ) for q in questions ]
        old_sha, new_sha         = resolve_rev( repo, args.old_rev ), resolve_rev( repo, args.new_rev )
        groups                   = group_by_file( questions )
        texts                    = { f: ( extract_doc_text( read_at( repo, old_sha, f ), f ), extract_doc_text( read_at( repo, new_sha, f ), f ) ) for f in groups }
        config                   = reader_rig.ReaderConfig( args.reader_model, args.grader_model, args.runs )
        calls_path               = args.ledger + ".calls"
        model_transport.configure( args.claude_cli_path )
        model_transport.set_budget( calls_path, { args.reader_model: args.reader_cap, args.grader_model: args.grader_cap } )
    except ( RunRefused, ValueError ) as e:
        return refuse( e )
    ledger = harness_runner.Ledger( args.ledger )
    owed   = { "reader": 0, "grader": 0 }
    for f, group in groups.items():
        for kind, n in projected_calls( list( texts[ f ] ), rig_questions( group ), config, ledger ).items(): owed[ kind ] += n
    used = { "reader": model_transport.calls_used( args.reader_model ), "grader": model_transport.calls_used( args.grader_model ) }
    if args.dry_run:
        for f, group in groups.items(): print( f"{f}: {len( group )} questions, old text {len( texts[ f ][ 0 ] )} chars, new text {len( texts[ f ][ 1 ] )} chars" )
        print( f"projected calls: reader {owed[ 'reader' ]} (cap {args.reader_cap}, used {used[ 'reader' ]}), grader {owed[ 'grader' ]} (cap {args.grader_cap}, used {used[ 'grader' ]})" )
        print( f"cap check uses the worst case of {ATTEMPTS} attempts per call: reader {ATTEMPTS * owed[ 'reader' ]}, grader {ATTEMPTS * owed[ 'grader' ]}" )
        return 0
    if used[ "reader" ] + ATTEMPTS * owed[ "reader" ] > args.reader_cap or used[ "grader" ] + ATTEMPTS * owed[ "grader" ] > args.grader_cap:
        return refuse( f"worst case with {ATTEMPTS} attempts per call (reader {ATTEMPTS * owed[ 'reader' ]}, grader {ATTEMPTS * owed[ 'grader' ]}) on top of those used (reader {used[ 'reader' ]}, grader {used[ 'grader' ]}) passes a cap (reader {args.reader_cap}, grader {args.grader_cap}); no model was contacted" )

    async def run_all():
        halt = { "reason": None }
        return { f: await score_file( f, texts[ f ][ 0 ], texts[ f ][ 1 ], rig_questions( group ), config, ledger, query_fn, halt, not args.strict_grader ) for f, group in groups.items() }

    per_file = asyncio.run( run_all() )
    counts   = { f: len( group ) for f, group in groups.items() }
    overall  = dict( summarize( per_file ), questions=sum( counts.values() ) )
    spent    = { m: model_transport.calls_used( m ) for m in ( args.reader_model, args.grader_model ) }
    for f, r in per_file.items(): print( f"{f}: questions={counts[ f ]} compared={r[ 'compared' ]} dropped={r[ 'dropped' ]} salvaged={len( r[ 'salvaged_records' ] )} old_total={r[ 'old_total' ]} new_total={r[ 'new_total' ]} verdict={r[ 'verdict' ]}" )
    print( f"overall: questions={overall[ 'questions' ]} compared={overall[ 'compared' ]} dropped={overall[ 'dropped' ]} salvaged={overall[ 'salvaged' ]} old_total={overall[ 'old_total' ]} new_total={overall[ 'new_total' ]} verdict={overall[ 'verdict' ]}" )
    for model, n in spent.items(): print( f"calls spent {model}: {n}" )
    if args.out is not None:
        report = { "old_rev": old_sha, "new_rev": new_sha, "questions_sha256": questions_sha, "reader_model": args.reader_model,
                   "grader_model": args.grader_model, "runs": args.runs, "file_prefix": args.file_prefix, "paths_read": list( groups ), "prompt_version": reader_rig.PROMPT_VERSION,
                   "attempts": ATTEMPTS, "strict_grader": args.strict_grader, "salvage_scope": "calls made in this run only: a grade cached by an earlier run is not recounted", "files": { f: dict( per_file[ f ], questions=counts[ f ] ) for f in per_file }, "overall": overall, "calls_spent": spent }
        with open( args.out, "w", encoding="utf-8" ) as out: json.dump( report, out, indent=2 )
    if overall[ "dropped" ]:
        if args.out is None:
            for r in per_file.values():
                for record in r[ "unscored_records" ]: print( json.dumps( record ), file=sys.stderr )
        print( f"UNSCORED: {overall[ 'unscored' ]} answers got no scoreable reply after {ATTEMPTS} attempts; {overall[ 'dropped' ]} pairs dropped from both texts; verdict INCOMPLETE", file=sys.stderr )
        return 3
    return 0


if __name__ == "__main__":  # pragma: no cover - thin process entry, main() is what the tests drive
    sys.exit( main( sys.argv[ 1: ] ) )
