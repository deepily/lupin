---
capability: ts-extractor-shapes
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - src.cosa.repo.symindex.ts_extract.isPrivate@fb7c77287a
  - src.cosa.repo.symindex.ts_extract.isHiddenFn@0d75c6063c
  - src.cosa.repo.symindex.ts_extract.kindName@acf3bd6c46
  - src.cosa.repo.symindex.ts_extract.preorder@300c62acfa
  - src.cosa.repo.symindex.ts_extract.isFnLike@193b48358c
  - src.cosa.repo.symindex.ts_extract.fnName@b879168849
  - src.cosa.repo.symindex.ts_extract.countFnLike@e0b0030681
  - src.cosa.repo.symindex.ts_extract.calleeName@b2bb3eae38
  - src.cosa.repo.symindex.ts_extract.callsOf@83fb45fe0a
  - src.cosa.repo.symindex.ts_extract.bindingNames@b8fb5bf879
  - src.cosa.repo.symindex.ts_extract.declaredIn@d7c7e79407
  - src.cosa.repo.symindex.ts_extract.dedentedText@a4d0d1850d
  - src.cosa.repo.symindex.ts_extract.bodiesOf@437bb2d6d2
  - src.cosa.repo.symindex.ts_extract.shapes@d73680aafc
---
# TypeScript extractor: function shapes
The second mode of `ts_extract.js` lists every function-like node of a file with its syntax kinds, for the duplicate checker. Records are on [[ts-extractor-records]].
- `isPrivate` is true for a private or protected member, or one with a hash-private name. `isHiddenFn` adds a function held in a private or protected class property.
- `isFnLike` is true for functions, methods, constructors, accessors, arrow functions and function expressions.
- `fnName` is the name a function-like node answers to, or null for an anonymous callback. Such a callback is still walked, never reported.
- `countFnLike` counts every function-like node of a file, anonymous and nested ones included.
- `kindName` gives a node's syntax kind name, with all literals folded into one kind. `preorder` collects the kinds of a subtree, leaving out doc comments and modifiers.
- `calleeName` is the identifier called, or the member name of `a.b()`. Anything else has none. `callsOf` lists distinct callee names inside a function, at most 50.
- `bindingNames` lists the names a parameter or variable introduces, destructuring included. `declaredIn` lists those declared inside a function, not its own name.
- `dedentedText` is a function's source without the indentation of its first line. `bodiesOf` adds the line range, signature, text, calls, declared names and public flag.
- `shapes` walks each file and returns the files scanned, the files skipped and the definitions. A file with parse errors is skipped whole.
