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
- The script and `io/` originals are read with the user's token and shown in a new tab as markdown. Other originals open in the doc viewer as `lupin/<rel>`.
- The mp3 is fetched with the token and handed to the audio element as a blob URL, because an audio tag cannot send a header.

## Don't
- Don't link a podcast script through `/app/docs?path=podcasts/...`. The doc viewer refuses `io/podcasts`.
