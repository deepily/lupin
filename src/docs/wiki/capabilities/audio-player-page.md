---
capability: audio-player-page
---
# Audio player page

`src/lupin_app/static/html/audio-player.html`, served at `/app/audio`. It has two faces, picked by `embed=1`. Both podcast clients open it: the floating widget described in [[web-client-render-items-podcast-links]] and a full tab.

## Query values
- `path`: the mp3, relative to `io/`. `script`: the script, relative to `io/`.
- `source`: the original document. `io/<rel>` for a file under `io/`; `lupin/<rel>` for any other project file.
- `title`: the plain title. Built by [[podcast-card-links]].
- `embed=1`: the mini face. `autoplay=1`: start playing on load.

## The two faces
- **Mini face** (`embed=1`): the browser's own audio element and nothing else. No heading, download, links or details.
- **Full face**: the clean title, the player, Download MP3, a Script link, an Original document link, and the file details.
- With no `title`, the title is the file name minus the date, time and serial. An old card still plays.

## Invariants
- A Script or Original link is drawn only when its file answers. An absent file is left out, not shown broken.
- Script and Original are real links into the doc viewer, opened in a new tab. The script is `lupin/io/<script>`; an `io/` original is `lupin/<source>`; any other original is as given.
- The page probes each link with the user's token and leaves out one that does not answer.
- The mp3 is fetched with the token and handed to the audio element as a blob URL, because an audio tag cannot send a header.

## Don't
- Don't link a podcast script through `/app/docs?path=podcasts/...`. The first segment must be the project: `lupin/io/podcasts/...`, which [[doc-viewer]] serves to the folder's owner only.
- Don't fetch the text and draw it in the page or a new tab. The doc viewer renders it and sanitises it.
