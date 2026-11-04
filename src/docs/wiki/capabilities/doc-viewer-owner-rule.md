---
capability: doc-viewer-owner-rule
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - cosa.rest.routers._owner_scope.card_is_owned_by@6642017df9
  - cosa.rest.routers._owner_scope.owned_prefix@e4c86cc6c9
  - cosa.rest.routers._owner_scope.registry_for@5fe5b6233f
---
# Doc viewer owner rule

`cosa.rest.routers._owner_scope` lets a person read their own podcast files in the doc viewer, and nobody else's. It adds one folder to the `lupin` scope for one read. The rest of [[doc-viewer]] runs unchanged on it.

## What it does
- `owned_prefix` names the one folder a request may read, or none. `registry_for` returns a copy of the scope registry with that folder added, and `card_is_owned_by` answers the card check.
- `io/podcasts/<email>/` and `io/deep-research/<email>/` open when the path segment equals the caller's email.
- `io/podcast-proxy/<card id>/` opens when the card has a spent-cards row and its notification's `recipient_id` is the caller.
- `started_by` on the spent-cards row names the seat that asked, so it is not used.

## Invariants
- Reads only. Upload never calls it.
- `.docview.yml` stays closed. A listed prefix is open to every signed-in user.
- The blocklists, the landing check and the credential check still apply, so a link or `..` into another person's folder is refused where it lands.

## Don't
- Don't list a per-person folder in `.docview.yml`.
- Don't judge ownership from the seat name.
