---
capability: podcast-card-links
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - cosa.agents.podcast_generator.play_links.clean_title@d9fce3f41d
  - cosa.agents.podcast_generator.play_links.read_script_title@79229cef0c
  - cosa.agents.podcast_generator.play_links.title_from_script_text@0c820ee701
  - cosa.agents.podcast_generator.play_links.title_from_folder_name@0a51c933fa
  - cosa.agents.podcast_generator.play_links.source_ref@b60d79bab5
  - cosa.agents.podcast_generator.play_links.player_query@d03688e872
  - cosa.agents.podcast_generator.play_links.audio_triplet@f8e5467aae
  - cosa.agents.podcast_generator.play_links.script_link@00253a5fbf
  - cosa.agents.podcast_generator.play_links.io_relative@cce4350262
  - cosa.agents.podcast_generator.play_links.ordered_languages@d2c95462d9
  - cosa.agents.podcast_generator.play_links.language_card_lines@4c92d3b583
---
# Podcast card links

Builds the Play Here, Listen and Download links on a finished podcast card. `PodcastGeneratorJob` and `DeepResearchToPodcastJob` both call it, so the two cannot drift. The player page that reads them is [[audio-player-page]].

## What it does
- `audio_triplet( audio_rel, script_rel, source_rel, title )` returns the three markdown links for one mp3. Play Here is the player URL with `embed=1`; Listen is the same URL without it.
- `player_query` writes `path=`, then `script=`, `source=` and `title=` only when given. A missing value is left out, never written empty.
- `read_script_title` reads a script file's first top-level heading; `title_from_script_text` does the same for text already in hand. `clean_title` removes the `Podcast:` label. No heading gives None.
- `title_from_folder_name` turns a Drive job folder name into a title: every leading date, time and serial removed, words capitalised.
- `script_link` builds the Script link to the doc viewer, `lupin/io/<script_rel>`; None without a script.
- `source_ref` names the original document: `io/<rel>` under `io/`, `lupin/<rel>` for any other project file, None outside the project.

- `script_link( script_rel )` returns the 📝 Script link: the doc viewer URL `/app/docs?path=lupin/io/<script_rel>`, or None with no script. It does not need audio.
- `io_relative( path, io_base )` makes an artifact path relative to `io/`. It removes the `io_base` prefix, else a leading `io/`, else leading slashes. An empty path gives None.
- `ordered_languages( languages, audio_by_lang, script_by_lang )` lists each language once. Requested languages that made an artifact come first, in request order. Extra languages that made one follow.
- `language_card_lines( ordered_langs, names, audio_by_lang, script_by_lang, source_rel, io_base, drive_links )` builds one line per language that has a link. A line reads `**Label**: 📝 Script | ▶️ Play Here | 🎧 Listen | ⬇️ Download | ☁️ Drive`. The label falls back to the language code.

## Invariants
- The job passes the script path. The script and mp3 carry different time stamps, so the player cannot pair them by file name.
- Each language gets its own title, read from its own script.

## Don't
- Don't build a Play Here URL by hand in a job. Call `audio_triplet`.
