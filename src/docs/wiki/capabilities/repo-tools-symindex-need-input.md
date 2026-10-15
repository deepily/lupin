---
capability: repo-tools-symindex-need-input
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - cosa.repo.symindex.need_input.NeedInput@78c2e084eb
  - cosa.repo.symindex.need_input.resolve_member@dbd1b1e65e
  - cosa.repo.symindex.need_input.build_input@34eb2f01ab
  - cosa.repo.symindex.need_writer.extract_sentence@1f5cc74c87
  - cosa.repo.symindex.need_writer.own_words_found@2efa76534c
  - cosa.repo.symindex.need_writer.check_form@103343769f
  - cosa.repo.symindex.need_writer.build_prompt@eaedc8d046
---
# Need sentences: stripped input and form checks

Builds the text a need writer reads for one sampled code member, and checks the sentence it writes. The calling loop is on [[repo-tools-symindex-need-writing]].

## Stripped input (`need_input`)
- `resolve_member( member_id, src_root )` finds the module file for a dotted id, longest module first, and returns the path and the name inside it. It raises `ValueError` when no prefix names a module.
- `build_input( member_id, src_root )` returns a `NeedInput` with `member_id`, `kind` (function, method or class), `text` and `forbidden`. It replaces names with placeholders such as `NAME`, `CLASS`, `MODULE`, `ARG1` and `ATTR1`. The names swapped are the member's own, its class, a class's method names, the module path parts, parameter names and `self.x` or `cls.x` attributes.
- `self`, `cls`, dunder names and names under three characters stay. `forbidden` lists the replaced names, longest first.

## Checking the sentence (`need_writer`)
- `extract_sentence` collapses whitespace and trims quotes and ticks.
- `own_words_found( sentence, need )` lists the forbidden names found after the opening phrase.
- `check_form( sentence, need )` returns a sorted list of failure kinds: `opener`, `word_count`, `one_sentence`, `placeholder` and `own_identifier`. The opener is "A function that", "A method that" or "A class that", and the length is 8 to 40 words.
- `build_prompt` holds the stripped text and the form rules. After a failure it names the failure kinds, and the own words when `own_identifier` failed. Avoid words are always named as words not to use. It raises `ValueError` for an own word that is not one of the member's names. It does the same for an avoid word that is not a bare lower-case word.
