---
capability: ts-extractor-records
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - src.cosa.repo.symindex.ts_extract.scriptKind@f2d9a2be27
  - src.cosa.repo.symindex.ts_extract.emit@78a1a8a072
  - src.cosa.repo.symindex.ts_extract.firstDocLine@40e7271f5f
  - src.cosa.repo.symindex.ts_extract.fullDoc@256bf0bc0d
  - src.cosa.repo.symindex.ts_extract.leafTokens@e1a87cba1a
  - src.cosa.repo.symindex.ts_extract.pinOf@f58136cf90
  - src.cosa.repo.symindex.ts_extract.params@80781d7315
---
# TypeScript extractor: records, docs and pins
`src/cosa/repo/symindex/ts_extract.js` is the Node program that reads TypeScript and JavaScript files for the [[symbol-index]]. This page covers how one record is made. Function bodies are on [[ts-extractor-shapes]].
- `scriptKind` is the one place a file extension picks the parse mode. A `.tsx` file is read with markup support, `.ts` as TypeScript, anything else as JavaScript.
- `emit` adds one record: file, name, kind, signature, first doc line, full doc, pin, start and end line, and the public flag.
- `firstDocLine` is the first non-empty line of a node's last doc comment, or an empty string.
- `fullDoc` is the whole doc comment with its tags, whitespace folded to single spaces. It is cut to the requested length and a marker added.
- `leafTokens` lists the leaf tokens of a node and leaves out doc comment nodes. `pinOf` joins them with single spaces and keeps the first ten hex digits of the sha1.
- `params` gives a function-like node's type parameters, parameters and return type as one signature, with whitespace folded.
