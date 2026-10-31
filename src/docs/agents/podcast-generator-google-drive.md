# Podcast Generator: Google Drive publishing

After a podcast finishes, Lupin can copy it to your own Google Drive so the phone can play it. The feature is **off by default**.

## What you get

A folder `Lupin Podcasts/<timestamp>-<topic>/` in your Drive holds:

- the mp3 for each language
- the original source document (markdown, not converted)
- the script for each language, if you switch that on

The completion card gains a `☁️ Drive` link on each language line and one `Drive folder` line. If the upload fails the podcast still completes, and the card says `Drive: upload failed (<reason>)`.

Both podcast jobs use it: `PodcastGeneratorJob` and `DeepResearchToPodcastJob`. They share one function, `publish_podcast_to_drive`, in `src/cosa/agents/podcast_generator/drive_hook.py`.

## One-time setup (a person does this)

1. In Google Cloud Console, create an OAuth client ID of type **Desktop app**. Download its JSON.
2. Save it as `src/conf/keys/google-drive-oauth-client.json`.
3. In the OAuth consent screen, set the publishing status to **In production** (single user; `drive.file` needs no review). A token issued while the app is in *Testing* expires after 7 days.
4. Run the authorize script once. It opens a browser consent page:

   ```bash
   LUPIN_ROOT="$PWD" PYTHONPATH="$PWD/src" .venv/bin/python src/scripts/google-drive-authorize.py
   ```

   It writes `src/conf/keys/google-drive-oauth-token.json` (mode 600), then lists the app's own files and prints the account email.
5. Let the app create the `Lupin Podcasts` folder. Under the `drive.file` scope the app cannot see a folder you made by hand, so it would create a second one.

Both key files are secrets. They are never committed and never linked into worktrees.

## Settings (`src/conf/lupin-app.ini`)

| Key | Default | Meaning |
|---|---|---|
| `podcast publish to google drive` | `false` | master switch; read before any Google module is imported |
| `podcast drive folder name` | `Lupin Podcasts` | top folder in Drive |
| `podcast drive upload script` | `false` | also upload each language's script |
| `podcast drive upload source document` | `true` | also upload the source document, once per job |
| `podcast drive token path` | `/src/conf/keys/google-drive-oauth-token.json` | joined to the project root at run time |

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
| A second `Lupin Podcasts` folder | the folder was made by hand; delete it and let the app create its own |
