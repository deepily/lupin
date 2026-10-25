---
capability: ts-doc-extract-script
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - src.scripts.ts_doc_extract.lineBody@58db6afb46
  - src.scripts.ts_doc_extract.blockBody@a48da3658c
  - src.scripts.ts_doc_extract.isDirective@9e929758bf
  - src.scripts.ts_doc_extract.looksLikeCode@1f114d422d
  - src.scripts.ts_doc_extract.nameText@04d3bb9910
  - src.scripts.ts_doc_extract.declName@85106127f8
  - src.scripts.ts_doc_extract.symbolOf@25ab69eb90
  - src.scripts.ts_doc_extract.isBareToken@4d8487b947
  - src.scripts.ts_doc_extract.collectRanges@865ce60740
  - src.scripts.ts_doc_extract.tagType@30bc08ba8a
  - src.scripts.ts_doc_extract.tagName@4183436b3a
  - src.scripts.ts_doc_extract.readBlock@4e46bada18
  - src.scripts.ts_doc_extract.tagsOf@523c95238b
  - src.scripts.ts_doc_extract.buildRecords@a8164892f4
  - src.scripts.ts_doc_extract.onlyDirectivesBefore@c4559ef49b
  - src.scripts.ts_doc_extract.extractFile@83a3f38965
  - src.scripts.ts_doc_extract.main@c2765595ca
---
# Script comment extractor
`src/scripts/ts_doc_extract.mjs` extracts every comment of TypeScript and JavaScript files as JSON Lines. The compiler finds the comments, so a double slash in a string or a regular expression is never taken for one. Users are [[ts-code-and-export-scripts]].
- `extractFile` returns a file record and the comment records in source order. A file that does not parse is read as far as the compiler recovers.
- `main` runs it over the files in its arguments and writes the lines. It returns 2 and a usage line when the root or file list is missing, or an option is unknown.
- `lineBody` and `blockBody` give a comment's body without its delimiters and star margin.
- `isDirective` is true for a type, lint, coverage or formatter directive or a region marker. It also covers triple-slash references, source map comments, bang comments and license blocks.
- `looksLikeCode` is true only when the text parses cleanly and holds a call, an assignment or a declaration.
- `nameText`, `declName` and `symbolOf` give the name of a node, of a declaration, and of the nearest enclosing declaration.
- `isBareToken` is true for punctuation, a keyword or the end of the file.
- `collectRanges` finds the comment ranges and each one's owner. A trailing comment's owner is the outermost node that ends where it begins.
- `tagType` and `tagName` read a doc tag's type and name. `readBlock` returns each tag with its raw source text, and `tagsOf` does so for one comment range.
- `buildRecords` builds the records, with a symbol key per comment. A directive has none and takes no ordinal.
- `onlyDirectivesBefore` says whether only whitespace, a hashbang and directives sit before a position.
