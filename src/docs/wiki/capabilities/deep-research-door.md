---
capability: deep-research-door
pin_algorithm: py3.13.xf75af6/ts5.9.3
pins:
  - cosa.rest.routers.deep_research.submit_research@0c97df1d19
  - cosa.rest.routers.deep_research.get_report@f4720e70da
  - cosa.rest.routers.deep_research.deep_research_health@0ae2ab2e8b
  - cosa.rest.routers._retired_doors.gone@f7af6a87f6
---
# Deep research door

The deep-research router in `src/cosa/rest/routers/deep_research.py` serves finished reports and a health check. It no longer accepts jobs. The job itself is on [[deep-research]].

## Routes
- `POST /api/deep-research/submit` always answers 410. The message names `/api/v2/submit` and carries the text `REMOVE BY 2026-12-31`.
- Jobs go to `/api/v2/submit` with the command `agent router go to deep research`.
- `GET /api/deep-research/report?path=` returns the file as Markdown, content type `text/markdown; charset=utf-8`.
- `GET /api/deep-research/health` returns `status`, `gcs_available`, and the path and existence of `io/deep-research`.
- No handler asks for a token. The app adds an upload size guard, CORS and a security-headers function, and CORS allows every origin.

## Report paths
- A `gs://` path is read from Cloud Storage with no check on bucket or prefix. It answers 503 without the storage library.
- A Cloud Storage error whose text holds `NotFound` or `404` answers 404. Any other error answers 500.
- A relative local path is read under `io/deep-research`, and an absolute one is used as given. Symlinks are resolved first.
- The resolved path must lie inside `io/`, or the answer is 400. Whole path segments are compared, so `io-secrets` does not pass.
- A path that is not a file answers 404, and a read error answers 500.
- The docstring says only `io/deep-research` is allowed. The code accepts anything under `io/`, and a test relies on that.

## Callers
- When a report is stored in Cloud Storage, the deep-research CLI puts a `localhost:7999` link to this route in its summary.
- No browser file calls the route.
