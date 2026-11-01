---
capability: podcast-drive-publishing
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - cosa.agents.podcast_generator.drive_hook.make_job_folder_name@98083b5a3c
  - cosa.agents.podcast_generator.drive_hook.resolve_source_path@9a8d24cb0a
  - cosa.agents.podcast_generator.drive_hook.publish_podcast_to_drive@543c171ab4
  - cosa.utils.drive_publisher.DrivePublishError@9c2b053c46
  - cosa.utils.drive_publisher.DriveNotFound@7fedcdda9b
  - cosa.utils.drive_publisher.DrivePublisher@ec56dd132b
  - cosa.utils.drive_publisher.DrivePublisher.ensure_folder@5cd34502cc
  - cosa.utils.drive_publisher.DrivePublisher.upload@5aeb9b087f
  - cosa.utils.drive_publisher.DrivePublisher.publish_job@f11b84bfdd
---
# Publishing finished podcasts to Google Drive

After a podcast's audio is written, both podcast jobs can copy the files to the user's own Google Drive. It is off by default. Setup steps and settings are in `src/docs/agents/podcast-generator-google-drive.md`; the token comes from [[google-drive-authorize-script]].

## The hook
- `publish_podcast_to_drive` is the one shared hook. `PodcastGeneratorJob` ([[podcast-generation]]) and `DeepResearchToPodcastJob` ([[research-chained-pipelines]]) call it after the audio exists and before the completion notice is built.
- It returns `language_links` (language to Drive link), `extra_lines` (notice lines) and `folder_link`. The jobs add a `☁️ Drive` link per language and store `drive_folder_link` in their artifacts.
- With `publish_to_google_drive` off it returns the empty result and imports no Google module. The upload runs in a worker thread.
- It never fails the job. Loading the config, resolving the path, naming the folder and the upload all sit inside one catch-all. An error before the upload starts, or in it as a whole, becomes one `**Drive**: upload failed (...)` line. If only some files fail, the links that uploaded are kept. The notice then gets the folder line and a second `**Drive**: upload failed (...)` line naming each failed file.
- `make_job_folder_name` builds `<timestamp>-<topic>` from the source file's name. `resolve_source_path` joins a relative path to the project root and returns `None` for an empty one.
- Files sent: one mp3 per language. Scripts go only if `drive_upload_script` is on. The source document goes if `drive_upload_source_document` is on (the default) and the file exists.

## The publisher
- `DrivePublisher` talks to Drive with the `drive.file` scope, so the app sees only files it created. Google libraries are imported inside the methods that need them.
- `ensure_folder` finds a folder by name or creates it. A slash-separated name such as `Lupin AF Mobile/Podcasts` is a chain: each level is found or made under the one above. The top folder's id, keyed to the full path, is cached in `src/conf/keys/google-drive-folder-id.json` and reused while that folder still exists.
- `find_top_folder` finds the top folder without creating it. `list_job_folders`, `list_folder_files`, `file_inside_top_folder`, `read_head` and `open_media` serve the phone door in [[podcast-drive-phone-api]].
- `upload` sends one file with an 8 MiB resumable upload. `publish_job` makes the job subfolder, uploads each file, and reports a link or an error per file plus the folder link. A new job folder carries the podcast's plain title as its Drive description.
- `DrivePublishError` is raised for a missing or unrefreshable token and for API errors. Its message names the file or folder. `DriveNotFound` is the subclass for a Drive 404, so a caller can tell "not there" from "Drive is unwell".

## Don't
- Don't import `cosa.utils.drive_publisher` at module top level in a job. The flag must be read first so a disabled feature imposes no Google dependency.
