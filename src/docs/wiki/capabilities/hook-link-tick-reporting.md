---
capability: hook-link-tick-reporting
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - cosa.utils.hook_link_tick.build_payload@4384401cb6
  - cosa.utils.hook_link_tick.decide@7f5b077f87
  - cosa.utils.hook_link_tick.deliver@5c480ead11
  - cosa.utils.hook_link_tick.fingerprint@9e70573955
  - cosa.utils.hook_link_tick.main@0f6fdf5342
  - cosa.utils.hook_link_tick.post_json@36a047e0be
  - cosa.utils.hook_link_tick.post_query@59a641fd22
  - cosa.utils.hook_link_tick.read_findings@a012f52fe0
  - cosa.utils.hook_link_tick.report_lines@7cdf20e578
  - cosa.utils.hook_link_tick.sentence@bac0d2eb44
---
# Git hook link tick reporting

`cosa.utils.hook_link_tick` reports broken git hook links. It only reports and never repairs a link.

## What it does
- `main( [ findings_file ] )` is the reporting half of `src/scripts/hook-link-tick.sh`. `read_findings( text )` parses its tab-separated lines into dicts and raises `ValueError` for a line with fewer than three fields.
- `sentence( finding )` words one finding from a fixed table, and names an unknown state word instead of hiding it. `report_lines` and `build_payload` produce the printed lines and the spoken line, abstract table and direct message.
- `fingerprint( findings )` is an order-independent 16-character hash. `decide( fp, state, now, resend_hours )` returns `( send, reason )`. A changed fingerprint sends at once, and an unchanged one only after the resend window.
- `deliver( ... )` sends `/api/notify` and, when `HOOK_LINK_DM` names a persona, `/api/dm/send`, through `post_query` and `post_json`. Both return `( status, text )` and never raise.
- Settings: `HOOK_LINK_API_BASE`, `HOOK_LINK_RESEND_HOURS` (6), `HOOK_LINK_DELIVER` (`0` prints only), `HOOK_LINK_DRILL`, `HOOK_LINK_STATE`, `HOOK_LINK_DM` and `LUPIN_DEV_EMAIL`.
- Exit codes: 0 clean, 1 could not look, 2 delivered, 3 a due channel failed, 4 unchanged inside the window, 5 delivery off.

## Don't
- Do not rely on a failed channel being retried together with the others. Each channel's ledger advances only when that channel arrived.

## Invariants
- A clean findings file prints nothing and exits 0. A missing key or recipient counts as a failed delivery.
- Callers are the shell script and `repo/symindex/librarian_tick.py`.
