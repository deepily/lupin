"""
Contract between the symbol-index builder and the language extractors (JS/TS, Dart).

An extractor is a function `extract_<lang>( root, files, data_root ) -> list[ dict ]`:

    root       pathlib.Path  the index root (a git working-tree root; read-only for Dart)
    files      list[Path]    absolute paths, taken from spec.all_files( spec ); the extractor
                             never globs and never applies skip rules
    data_root  pathlib.Path  per-repo fleet data directory for scratch projects and caches

Each returned dict is one symbol record with exactly these keys:

    lang      "ts" | "dart"
    file      posix path relative to root
    name      qualified name inside the file, for example "Foo.bar" or "mapRows"
    kind      "function" | "class" | "method" | "constructor" | "enum" | "mixin" | "extension"
    sig       "(args)" plus any generics and return type, or "" for a class
    doc       first non-empty doc-comment line, or ""
    pin_text  token lexemes joined by one space, comments excluded. The builder hashes it
              (sha1, first 10 hex) into `pin`, so a comment or whitespace edit never changes it.
              An extractor that hashes itself returns `pin` (10 hex) instead of pin_text.
    line      1-based line of the declaration
    public    bool; names starting with "_" are False and are still returned

The builder computes `id` itself: "<file without extension, '/' as '.'>.<name>", prefixed
"<repo>:" for every root that is not the lupin tree, with "#2", "#3" on a collision.

The extractor module also defines PIN_ALGORITHM, a short string naming the parser and its version
(for example "dart3.8.0/analyzer7.7.1"). The builder records it in the index header, and a change in
it is reported once as "algorithm changed, re-pin" instead of as one stale finding per page.

A missing external tool raises errors.DependencyMissing( what ). The builder records it in
the index header and the caller maps it to the cause DEPENDENCY_MISSING; it is never an
empty result.
"""

RECORD_KEYS   = ( "lang", "file", "name", "kind", "sig", "doc", "line", "public" )
KINDS         = frozenset( { "function", "class", "method", "constructor", "enum", "mixin", "extension" } )


def validate_record( rec ):
    """
    Check one extractor record against the contract.

    Requires:
        - rec is a dict
    Ensures:
        - returns None when the record is valid
    Raises:
        - ValueError naming the first violation: a missing key, a bad type, an unknown kind,
          or neither `pin` nor `pin_text`
    """
    for k in RECORD_KEYS:
        if k not in rec: raise ValueError( f"record is missing key {k!r}: {rec!r}" )
    if rec[ "kind" ] not in KINDS: raise ValueError( f"unknown kind {rec[ 'kind' ]!r}" )
    if not isinstance( rec[ "line" ], int ) or rec[ "line" ] < 1: raise ValueError( f"line must be a positive int: {rec[ 'line' ]!r}" )
    if not isinstance( rec[ "public" ], bool ): raise ValueError( f"public must be a bool: {rec[ 'public' ]!r}" )
    if "pin" not in rec and "pin_text" not in rec: raise ValueError( "record needs `pin` or `pin_text`" )
