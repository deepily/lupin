# Podcast Generator: Google Drive publishing

After a podcast finishes, Lupin can copy it to your own Google Drive so the phone can play it. The feature is **off by default**.

## What you get

A folder `Lupin AF Mobile/Podcasts/<timestamp>-<topic>/` in your Drive holds:

- the mp3 for each language
- the original source document (markdown, not converted)
- the script for each language, if you switch that on

The completion card gains a `☁️ Drive` link on each language line and one `Drive folder` line. An upload failure never fails the podcast. If the whole publish fails, the card shows a single `Drive: upload failed (<reason>)` line and no Drive links. If only some files fail, the card keeps the `Drive folder` line and the links that worked. It adds one `Drive: upload failed (<file>: <reason>; ...)` line naming each file that failed.

Both podcast jobs use it: `PodcastGeneratorJob` and `DeepResearchToPodcastJob`. They share one function, `publish_podcast_to_drive`, in `src/cosa/agents/podcast_generator/drive_hook.py`.

## One-time setup (a person does this)

1. In Google Cloud Console, in any project you own, enable the **Google Drive API** (APIs & Services → Library). Without it every upload is refused. Then create an OAuth client ID of type **Desktop app** and download its JSON. The project is only the app's identity; the files go to the Drive of whoever signs in.
2. Save it as `src/conf/keys/google-drive-oauth-client.json`.
3. In the OAuth consent screen, set the publishing status to **In production** (single user; `drive.file` needs no review). A token issued while the app is in *Testing* expires after 7 days.
4. Run the authorize script once. It opens a browser consent page:

   ```bash
   LUPIN_ROOT="$PWD" PYTHONPATH="$PWD/src" .venv/bin/python src/scripts/google-drive-authorize.py
   ```

   It writes `src/conf/keys/google-drive-oauth-token.json` (mode 600), then lists the app's own files and prints the account email.
5. Let the app create the `Lupin AF Mobile/Podcasts` folders. Under the `drive.file` scope the app cannot see a folder you made by hand, so it would create a second one.

Both key files are secrets. They are never committed and never linked into worktrees.

## Settings (`src/conf/lupin-app.ini`)

| Key | Default | Meaning |
|---|---|---|
| `podcast publish to google drive` | `false` | master switch; read before any Google module is imported |
| `podcast drive folder name` | `Lupin AF Mobile/Podcasts` | folder path from the Drive root; each `/` makes one level, and the app creates each level itself |
| `podcast drive upload script` | `false` | also upload each language's script |
| `podcast drive upload source document` | `true` | also upload the source document, once per job |
| `podcast drive token path` | `/src/conf/keys/google-drive-oauth-token.json` | joined to the project root at run time |
| `podcast drive owner email` | empty | the one Lupin user who may list and stream the folder through `/api/podcast-drive`; empty means nobody |
| `podcast drive upload users` | `owner` | whose podcasts are uploaded: `owner` (only the user in `podcast drive owner email`), `all` (every user), or a comma list of emails. A change takes effect after a :7999 bounce. A skipped job logs the user and reason, and its card says `not uploaded to Drive (setting)`, or `not uploaded to Drive (no user email)` when the job has no user. An empty owner with `owner` means nobody is uploaded |

## Switching it off

Set `podcast publish to google drive = false`. With the flag off no Google module is imported and nothing changes.

## Dependencies and containers

`google-api-python-client`, `google-auth` and `google-auth-oauthlib` are in the root `pyproject.toml`. The containers install them at image build.

`:7999` and `:8000` need an image rebuild plus `docker compose up -d --force-recreate`, not a bounce, before they can import the publisher.

## Troubleshooting

| Symptom | Cause |
|---|---|
| `Drive: upload failed (token file missing ...)` | the authorize script was never run |
| `... token could not be refreshed ...` | consent revoked, or the app was in Testing mode for over 7 days; re-run the authorize script |
| A second `Lupin AF Mobile` or `Podcasts` folder | the folder was made by hand; delete it and let the app create its own |
| After **Allow**, the browser shows an unreachable `http://localhost:<port>/?state=…&code=…` page | the browser cannot reach the script's local port. While the script is still waiting, open that exact address from the machine running the script (for example with Python's `urllib.request.urlopen`); the script then saves the token |
| Publishing the app is refused until links are added | Google asked for an app home page, a privacy policy link and a terms of service link on the Branding page |
