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

Every model id and both call caps are required. Rerunning the same command resumes from the ledger.
"""

import argparse
import ast
import asyncio
import copy
import hashlib
import io
import json
import subprocess
import sys
import tokenize

import cosa.utils.util as cu

from . import harness_runner, model_transport, reader_rig

DOC_NODES = ( ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef )


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


def summarize( per_file, counts ):
    """
    Return the overall means weighted by question count, and the pass verdict.

    Requires:
        - per_file is { file: result of run_reader_test }, counts is { file: question count }

    Ensures:
        - returns { questions, old_mean, new_mean, old_total, new_total, passes }
        - each total is the sum of the file totals, so each file counts by its question count
        - each mean is that total over ( total questions x runs ), and passes compares the whole-number
          totals, never the float means
    """
    total = sum( counts.values() )
    runs  = len( next( iter( per_file.values() ) )[ "old_scores" ] )
    old   = sum( r[ "old_total" ] for r in per_file.values() )
    new   = sum( r[ "new_total" ] for r in per_file.values() )
    return { "questions": total, "old_mean": old / ( total * runs ), "new_mean": new / ( total * runs ), "old_total": old, "new_total": new, "passes": new >= old }


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
        - returns 2 and makes no model call when the calls still owed, added to those the ledger's
          call count already holds, pass --reader-cap or --grader-cap
        - a rerun against a full ledger makes zero calls
        - with --dry-run no model is contacted and nothing is written
        - the report holds both full shas, the questions file's sha256, the model ids, runs and the
          rig's prompt version

    Raises:
        - model_transport.CallBudgetExceeded, ReaderParseError or ModelCallError from a failed call;
          finished calls stay in the ledger
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
        return 0
    if used[ "reader" ] + owed[ "reader" ] > args.reader_cap or used[ "grader" ] + owed[ "grader" ] > args.grader_cap:
        return refuse( f"calls owed (reader {owed[ 'reader' ]}, grader {owed[ 'grader' ]}) on top of those used (reader {used[ 'reader' ]}, grader {used[ 'grader' ]}) pass a cap (reader {args.reader_cap}, grader {args.grader_cap}); no model was contacted" )

    async def run_all():
        return { f: await reader_rig.run_reader_test( texts[ f ][ 0 ], texts[ f ][ 1 ], rig_questions( group ), config, ledger=ledger, query_fn=query_fn ) for f, group in groups.items() }

    per_file = asyncio.run( run_all() )
    counts   = { f: len( group ) for f, group in groups.items() }
    overall  = summarize( per_file, counts )
    spent    = { m: model_transport.calls_used( m ) for m in ( args.reader_model, args.grader_model ) }
    for f, r in per_file.items(): print( f"{f}: questions={counts[ f ]} old_mean={r[ 'old_mean' ]:.3f} new_mean={r[ 'new_mean' ]:.3f} passes={r[ 'passes' ]}" )
    print( f"overall: questions={overall[ 'questions' ]} old_mean={overall[ 'old_mean' ]:.3f} new_mean={overall[ 'new_mean' ]:.3f} passes={overall[ 'passes' ]}" )
    for model, n in spent.items(): print( f"calls spent {model}: {n}" )
    if args.out is not None:
        report = { "old_rev": old_sha, "new_rev": new_sha, "questions_sha256": questions_sha, "reader_model": args.reader_model,
                   "grader_model": args.grader_model, "runs": args.runs, "file_prefix": args.file_prefix, "paths_read": list( groups ), "prompt_version": reader_rig.PROMPT_VERSION,
                   "files": { f: dict( per_file[ f ], questions=counts[ f ] ) for f in per_file }, "overall": overall, "calls_spent": spent }
        with open( args.out, "w", encoding="utf-8" ) as out: json.dump( report, out, indent=2 )
    return 0


if __name__ == "__main__":  # pragma: no cover - thin process entry, main() is what the tests drive
    sys.exit( main( sys.argv[ 1: ] ) )
