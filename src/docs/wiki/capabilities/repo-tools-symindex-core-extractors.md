---
capability: repo-tools-symindex-core-extractors
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - cosa.repo.symindex.extractor_contract.validate_record@c6244fad7b
  - cosa.repo.symindex.py_index.extract_python@bb7bf1b82c
  - cosa.repo.symindex.py_index.first_doc_line@4c6c8b6af4
  - cosa.repo.symindex.py_index.module_name@71607f21a1
  - cosa.repo.symindex.py_index.strip_docs@d5cc02f76a
  - cosa.repo.symindex.js_index.extract_js@30a75fd6b5
  - cosa.repo.symindex.js_index.extract_js_shapes@e5d26fac9e
  - cosa.repo.symindex.js_index.find_node@f5983cc3f3
  - cosa.repo.symindex.js_index.find_typescript@4753386bcd
  - cosa.repo.symindex.js_index.typescript_version@9152ec9bbf
---
# Symbol index: Python and script extractors

What a symbol record is and how the Python and TypeScript extractors produce one. Dart is on [[repo-tools-symindex-core-dart]]; the pin rules are on [[symbol-index]].

## The record contract
- A record has the keys `lang`, `file`, `name`, `kind`, `sig`, `doc`, `line`, `public`, plus `pin` or `pin_text`. `kind` is function, class, method, constructor, enum, mixin or extension.
- `validate_record( rec )` returns `None` for a valid record. It raises `ValueError` for a missing key, an unknown kind, a bad `line` or `public`, or neither `pin` nor `pin_text`. The build runs it on Dart records only.

## Python
- `extract_python( spec, path, include_all=False )` parses one file and returns its records. A file that does not parse raises `SyntaxError` (an unreadable one, `UnicodeDecodeError`), and the caller lists it as unparsed.
- Without `include_all` only names with no leading underscore come back, plus a class's `__init__`. With it, private names and helpers nested inside functions come back too, and `public` marks which are public.
- `module_name( spec, path )` gives the dotted name relative to `spec.module_base`; a package `__init__.py` is named after the package.
- `strip_docs( node )` returns a deep copy with every docstring removed, an emptied body holding `pass`. `first_doc_line( node )` returns the first non-empty docstring line, or an empty string.

## JavaScript and TypeScript
- `find_node()` tries `$LUPIN_NODE`, then `PATH`, then the last `~/.nvm` install in sorted order. `find_typescript( root )` wants `node_modules/typescript` under the root, else under `$LUPIN_ROOT`. Each raises `DependencyMissing` when it finds nothing.
- `typescript_version( ts_dir )` reads the version from that package's `package.json`; it feeds the pin algorithm.
- `extract_js( root, files )` runs `ts_extract.js` under node once and returns public records only. An empty list returns `[]` without starting node, and a non-zero exit raises `RuntimeError`.
- `extract_js_shapes( root, files, public_only=False )` returns `scanned`, `skipped` and `defs`, where each def carries its node-kind list with names and literals erased. The duplicate finder uses it ([[repo-tools-symindex-core-routes-diff-dups]]).
