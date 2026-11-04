---
capability: rest-routers-admin-snapshots
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - cosa.rest.routers.admin.get_snapshot_manager@f59de6f4af
  - cosa.rest.routers.admin.SnapshotSearchResult@c18c56b120
  - cosa.rest.routers.admin.SearchSnapshotsResponse@5337da0463
  - cosa.rest.routers.admin.SnapshotDetailResponse@e29fa92073
  - cosa.rest.routers.admin.CodeSimilarityResult@72e0bc807d
  - cosa.rest.routers.admin.SimilarSnapshotsResponse@ddf76176f6
  - cosa.rest.routers.admin.SnapshotPreviewResponse@7830ea5616
  - cosa.rest.routers.admin.search_snapshots@80fbe4773e
  - cosa.rest.routers.admin.get_snapshot_details@a796c1f766
  - cosa.rest.routers.admin.delete_snapshot@0243e76bea
  - cosa.rest.routers.admin.get_snapshot_preview@3519782b8e
  - cosa.rest.routers.admin.get_similar_snapshots@058f937df8
  - cosa.rest.routers.admin.RefreshSourceResponse@766c035364
  - cosa.rest.routers.admin.refresh_source@7429bb5aa6
---
# Admin snapshot routes and refresh-source

The solution-snapshot routes of `cosa.rest.routers.admin`, all behind `require_admin`, plus the test-only source refresh.

## What it does
- `get_snapshot_manager` hands handlers the process-wide snapshot manager from `lupin_app.main`, the same one the math agent writes through.
- `search_snapshots`, `GET /admin/snapshots/search`: `q`, `threshold` (0 to 100, default 80) and `limit` (1 to 100, default 50). An empty `q` or a threshold or limit out of range answers 400. It sorts by score, best first. Rows are `SnapshotSearchResult` in a `SearchSnapshotsResponse`.
- `get_snapshot_details`, `GET /admin/snapshots/{id_hash}`, returns a `SnapshotDetailResponse` or 404.
- `delete_snapshot`, `DELETE /admin/snapshots/{id_hash}`, removes it physically, 404 when absent.
- `get_snapshot_preview`, `.../preview`, returns the first 300 characters of the joined code (with `...` added when cut) and the solution gist, or 404. With no gist it falls back to the full solution summary. Reply: `SnapshotPreviewResponse`.
- `get_similar_snapshots`, `.../similar`, returns two lists of `CodeSimilarityResult`, one by code and one by explanation, in a `SimilarSnapshotsResponse`. Thresholds default to 85, `limit` to 20, and `ensure_top_result` keeps the best match even below threshold. A failure in one list leaves it empty.
- `refresh_source`, `POST /admin/admin/refresh-source`, because the route's own path sits under the router prefix. It re-executes the server process after 0.2 seconds and answers 202 with a `RefreshSourceResponse` of status, pid and env.

## Don't
- Don't call `refresh_source` outside the test server. It answers 403 unless `LUPIN_ENV` is `test` or `testing` and the key `admin refresh source enabled` is true.

## Invariants
- Both similarity searches are called with `exclude_self=True`, and a missing source snapshot answers 404.
