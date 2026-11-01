---
capability: podcast-card-links
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - cosa.agents.podcast_generator.play_links.clean_title@d9fce3f41d
  - cosa.agents.podcast_generator.play_links.read_script_title@9e38f07b11
  - cosa.agents.podcast_generator.play_links.source_ref@b60d79bab5
  - cosa.agents.podcast_generator.play_links.player_query@d03688e872
  - cosa.agents.podcast_generator.play_links.audio_triplet@f8e5467aae
---
# Podcast card links

Builds the Play Here, Listen and Download links on a finished podcast card. `PodcastGeneratorJob` and `DeepResearchToPodcastJob` both call it, so the two cannot drift. The player page that reads them is [[audio-player-page]].

## What it does
- `audio_triplet( audio_rel, script_rel, source_rel, title )` returns the three markdown links for one mp3. Play Here is the player URL with `embed=1`; Listen is the same URL without it.
- `player_query` writes `path=`, then `script=`, `source=` and `title=` only when given. A missing value is left out, never written empty.
- `read_script_title` reads the script's first top-level heading and `clean_title` removes the `Podcast:` label. An unreadable file or no heading gives None.
- `source_ref` names the original document: `io/<rel>` under `io/`, `lupin/<rel>` for any other project file, None outside the project.

## Invariants
- The job passes the script path. The script and mp3 carry different time stamps, so the player cannot pair them by file name.
- Each language gets its own title, read from its own script.

## Don't
- Don't build a Play Here URL by hand in a job. Call `audio_triplet`.
