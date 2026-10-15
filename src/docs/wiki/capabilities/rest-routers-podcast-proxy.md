---
capability: rest-routers-podcast-proxy
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - cosa.rest.routers.podcast_proxy.AskIn@580f498a12
  - cosa.rest.routers.podcast_proxy.ask_for_a_podcast@6146da7129
  - cosa.rest.routers.podcast_proxy.StartIn@835326d441
  - cosa.rest.routers.podcast_proxy.copy_directory@1e0fec326a
  - cosa.rest.routers.podcast_proxy.start_a_podcast@20db8c9947
  - cosa.rest.routers.podcast_proxy.podcast_card_status@e1921af7a0
  - cosa.rest.routers.podcast_proxy.ViewerIn@831c2eb80f
  - cosa.rest.routers.podcast_proxy.check_a_viewer_file@f21d3ce2e8
  - cosa.rest.routers.podcast_proxy.start_a_podcast_from_viewer@de1d2240f8
---
# Podcast proxy doors

The `/api/podcast-proxy` routes. A seat asks, the operator answers yes on a card, and the seat starts the job. A signed-in person can start one from the doc viewer. Every refusal body is `{ detail: { code, message } }`.

## What it does
- `ask_for_a_podcast` takes `AskIn` (`path`, `actor`), judges the file, writes the yes/no card itself and returns `card_id`. A live card for the same file and bytes answers 409 `waiting_card`.
- `start_a_podcast` takes `StartIn` (`card_id`, `actor`). It re-reads the card and the file, spends the card once, and queues the job.
- `podcast_card_status` describes a card: state, `spent` and `job_id`.
- `ViewerIn` carries a `path`. `check_a_viewer_file` says whether the viewer may offer a podcast, and returns `{ ok, name, size }`.
- `start_a_podcast_from_viewer` treats the click as the yes and queues a job for the caller. It answers 409 `spent` or `claimed_no_job` for a repeat.
- `copy_directory` is `io/podcast-proxy` under the project root, where the judged bytes are copied.

## Don't
- Don't start twice on one card. A yes covers one job.
- Don't call the viewer doors with an API key alone. They answer 403 `not_a_person`.

## Invariants
- A failed queue call removes only its own copy and releases the claim (502 `queue_failed`).
