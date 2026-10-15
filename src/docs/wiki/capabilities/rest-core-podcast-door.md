---
capability: rest-core-podcast-door
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - cosa.rest.podcast_proxy.DoorRefusal@3ecda4611b
  - cosa.rest.podcast_proxy.refusal_detail@799cdd1eb5
  - cosa.rest.podcast_proxy.check_source@063bcebc7e
  - cosa.rest.podcast_proxy.viewer_claim_id@fa85c639ff
  - cosa.rest.podcast_proxy.human_size@bbb3e899df
  - cosa.rest.podcast_proxy.file_changed_refusal@af2c93ee5c
  - cosa.rest.podcast_proxy.write_copy@92e23682bf
  - cosa.rest.podcast_proxy.remove_copy@8ecec91309
---
# Podcast proxy: the document door

A seat asks for a podcast of a document on the operator's behalf. The server judges the file named as `<scope>/<path>`, with the doc viewer's own read rules, before any card is shown. The card side is [[rest-core-podcast-cards]].

## Door check
- `check_source( scope_path )` returns `{scope, rel, name, server_path, size, sha256}` or raises `DoorRefusal`. It opens the file first and judges that handle, so a link swapped in later cannot redirect the read.
- It reads the whole file once. The same bytes are checked for credential text, measured and hashed.
- It refuses a blank or malformed path, an unknown scope, and a path the viewer's whitelist or blocklist refuses.
- It refuses a symlink landing outside the scope, a missing file, a folder, a file that is not UTF-8 text, and one over 8 MiB. A hard link to an outside file is accepted.
- It refuses credential content and an extension a podcast cannot read.
- `DoorRefusal` carries a `code` (`bad_path`, `not_found`, `viewer_refused`, `wrong_kind`, `too_large`, `credential`, `unreadable`) and a message naming the path as sent, unless the path was blank. `refusal_detail( code, message )` is the `{code, message}` body.

## After the yes
- `file_changed_refusal( payload, facts )` is `None` only when the hash, size and server path all match the card. Otherwise it is a 409 `hash_mismatch`.
- `write_copy( directory, card_id, name, content )` writes the bytes the door judged, mode 0640, into a folder for that card. `content` comes from `check_source( ..., keep_content=True )`. It removes a stale copy and creates the file exclusively.
- `remove_copy( directory, card_id )` removes that folder and never raises.
- `viewer_claim_id( user_id, scope_path, sha256 )` is a stable uuid for one person, one file and one set of bytes. `human_size` prints bytes, KiB or MiB.

## Don't
- Don't send a host path. Only the scope form is accepted.
