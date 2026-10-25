---
capability: rest-routers-page-shells-and-stats
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - cosa.rest.routers.pages.page_app@b67a295465
  - cosa.rest.routers.pages.page_multiplexer@66d9f71270
  - cosa.rest.routers.pages.page_auth_login@fa156bb999
  - cosa.rest.routers.pages.page_auth_register@b10e57b12a
  - cosa.rest.routers.pages.page_auth_profile@c6081160e4
  - cosa.rest.routers.pages.page_auth_change_password@adae7b4c88
  - cosa.rest.routers.pages.page_admin@bc26829727
  - cosa.rest.routers.pages.page_admin_users@c90a63b659
  - cosa.rest.routers.pages.page_admin_snapshots@d0742af435
  - cosa.rest.routers.pages.page_admin_proxy_ratify@25f7a4a937
  - cosa.rest.routers.pages.page_admin_proxy_dashboard@5fac96a307
  - cosa.rest.routers.pages.page_admin_dev_tools@e6710c1db3
  - cosa.rest.routers.pages.page_admin_peer_queue_watch@c0ce07d613
  - cosa.rest.routers.pages.page_docs@59137a71d0
  - cosa.rest.routers.pages.page_audio@363cb46297
  - cosa.rest.routers.pages.page_console@85476695b6
  - cosa.rest.routers.stats.get_snapshot_mgr@a7f7321be2
  - cosa.rest.routers.stats.get_global_time_saved_stats@05827481d5
---
# Page shells and time-saved statistics

`routers/pages.py` maps clean `/app/*` URLs to static HTML files, and `routers/stats.py` serves the global time-saved leaderboard.

## What it does
- Each `page_*` handler returns one static file as `text/html` with `Cache-Control: no-cache`, so a browser revalidates the page shell on every load.
- Paths: `page_app` `/app`, `page_multiplexer` `/app/multiplexer`, `page_auth_login`, `page_auth_register`, `page_auth_profile` and `page_auth_change_password` under `/app/auth/`, `page_docs` `/app/docs`, `page_audio` `/app/audio`, `page_console` `/app/console`.
- The admin shells are `page_admin` (`/app/admin`) and, under `/app/admin/`, `page_admin_users`, `page_admin_snapshots`, `page_admin_proxy_ratify`, `page_admin_proxy_dashboard`, `page_admin_dev_tools` and `page_admin_peer_queue_watch`.
- None of them checks a credential.
- `get_global_time_saved_stats` (`GET /api/stats/time-saved/global`) needs a signed-in user. It returns total solutions, replays, time saved, unique users and up to ten of the most replayed solutions. Only solutions with at least one replay are listed, and a question over 50 characters is cut to 50 and ends in `...`.
- `get_snapshot_mgr` is the dependency that fetches the snapshot manager from the main module.

## Don't
- Don't add a route here without an entry in the `_ROUTE_TABLE` dict. Handlers look their file up there.

## Invariants
- `/app/notifications` is the one page that may answer a 302 to `/app/multiplexer`. That happens when the INI key `legacy notifications redirect enabled` is on and `?classic` is not set.
