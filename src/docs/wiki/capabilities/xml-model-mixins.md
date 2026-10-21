---
capability: xml-model-mixins
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - cosa.agents.io_models.xml_models.CodeLinesMixin@45503194f3
  - cosa.agents.io_models.xml_models.CommaListMixin@2a13caa229
  - cosa.agents.io_models.utils.util_xml_pydantic.CdataSafeXMLMixin@50b8b5186a
  - cosa.agents.io_models.utils.util_xml_pydantic.extract_tagged_xml@a0538ed96c
---
# XML model mixins and tag extraction

Shared behaviour for the response models of [[xml-io-models]], and the one function the dispatchers use to cut a tag out of a reply.

## What it does
- `CodeLinesMixin` is for models with a `code` field. A before-validator turns the nested line structure from `xmltodict` into a list of strings, and a missing line becomes an empty string.
- `get_function_name` returns the first function name in the code, or `None`. `to_xml` writes `code` as nested line tags in the order of `XML_FIELDS`.
- `CommaListMixin.get_matches_list` splits a comma-separated `matches` string into trimmed, non-empty names. It returns `[]` for a blank string.
- `CdataSafeXMLMixin.from_xml` lifts each CDATA span behind a sentinel, lets the base class repair the rest, then puts the spans back unchanged. List it before `BaseXMLModel` in the bases.
- `extract_tagged_xml( raw_response, tag )` returns the first `<tag>` block, tags included, after it drops code fences.

## Don't
- Don't expect `extract_tagged_xml` to return a default. A blank reply or a missing block raises `ValueError`.
- Don't put a sentinel of your own in a CDATA reply. An index with no saved span is left as written.

## Invariants
- CDATA payloads survive byte for byte, ampersands included. A document with no CDATA parses as the base class does.
- The calculator and CRUD dispatchers call `extract_tagged_xml` with their own tag names.
