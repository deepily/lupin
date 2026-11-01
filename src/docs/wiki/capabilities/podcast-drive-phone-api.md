---
capability: podcast-drive-phone-api
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - cosa.rest.routers.podcast_drive.list_podcasts@5a1c443337
  - cosa.rest.routers.podcast_drive.stream_podcast_file@71d684576c
---
# Podcast Drive for the phone

The phone lists and plays podcasts published to the owner's Google Drive. The server reads Drive with the desktop token, so the phone needs no Google sign-in. Routes are in `src/docs/rest-api-reference/07-podcast-proxy-and-skeleton-crew.md`, section 25d. Drive access is [[podcast-drive-publishing]].

## What it does
- `list_podcasts` lists the job folders under the configured folder, newest first, each with its files and a `stream_url`.
- A job's title is its script's first heading when the folder holds a `-script.md`, else the folder name without its timestamp ([[podcast-card-links]]).
- `stream_podcast_file` passes the browser's `Range` header to Drive and streams the answer back in chunks, with 200, 206 or 416 and the range headers.

## Invariants
- Only the user named by `podcast drive owner email` gets in. Anyone else gets 403 before any Drive call. An empty key means nobody.
- A stream serves only a file in a job folder directly under the configured folder. Any other id is 404 and is never requested from Drive.
- Only a Drive 404 on the file or its folder reads as 404. Any other Drive or token failure is 503. A folder not yet in Drive lists as empty.
- The body is never held whole in memory.

## Don't
- Don't take a file id from the phone and stream it without `file_inside_top_folder`.
- Don't widen the owner check to any logged-in user. The token reaches one person's Drive.
