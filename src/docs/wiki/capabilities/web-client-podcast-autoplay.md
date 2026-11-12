---
capability: web-client-podcast-autoplay
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - src.lupin_app.static.js.multiplexer.render.podcastLinks.removePodcastOverlay@431a5f121a
  - src.lupin_app.static.js.multiplexer.render.podcastLinks.isPodcastOverlayOpen@c43862cd01
  - src.lupin_app.static.js.multiplexer.render.podcastLinks.onPodcastOverlayClosed@04d75fbbdd
  - src.lupin_app.static.js.multiplexer.shared.podcastAutoplayLink.firstPlayHereLink@9578cbcf5a
  - src.lupin_app.static.js.multiplexer.shared.podcastAutoplayLink.playHereTitle@2ca2609813
  - src.lupin_app.static.js.multiplexer.wirePodcastAutoplay.PodcastAutoplay@3c15c056d9
  - src.lupin_app.static.js.multiplexer.wirePodcastAutoplay.PodcastAutoplay.constructor@850e1fc5d5
  - src.lupin_app.static.js.multiplexer.wirePodcastAutoplay.PodcastAutoplay.offer@dee512ea8c
  - src.lupin_app.static.js.multiplexer.wirePodcastAutoplay.PodcastAutoplay.queued@b7872ded37
  - src.lupin_app.static.js.multiplexer.wirePodcastAutoplay.PodcastAutoplay.onPlaying@ee1b0c83fa
  - src.lupin_app.static.js.multiplexer.wirePodcastAutoplay.PodcastAutoplay.onEnded@18fb75ef67
  - src.lupin_app.static.js.multiplexer.wirePodcastAutoplay.PodcastAutoplay.onClosed@e632d09118
  - src.lupin_app.static.js.multiplexer.wirePodcastAutoplay.wirePodcastAutoplay@370abf9910
---
# Podcast auto-play

A finished podcast starts in the Play Here player by itself, in the multiplexer and in the legacy client. The player is described in [[web-client-render-items-podcast-links]].

## What it does
- The INI key `podcast auto play here on finish` (default true) reaches both pages as `podcast_auto_play_here_on_finish` in `/api/config/client`. Until that answer lands the feature is off.
- `NotificationStore` emits `store_podcast_autoplay_intent` for a live arrival whose abstract has a Play Here link. `firstPlayHereLink( abstract )` returns the first `/app/audio?path=` link that carries `embed=1`, else null.
- `playHereTitle( url )` returns the link's `title=` value, else "Podcast".
- `PodcastAutoplay.offer( embedUrl, title )` shows the podcast at once, or queues it while audio plays. `queued()` counts the waiting ones.
- `onPlaying()` marks the player busy. `onEnded()` and `onClosed()` free it and start the next waiting podcast.
- `wirePodcastAutoplay( bus, autoplay, win )` offers each intent and passes on the player page's same-origin `playing` and `ended` messages. It returns a function that stops both listeners.
- `onPodcastOverlayClosed( listener )` tells a listener when the overlay is dismissed, not when a new Play Here replaces it. `isPodcastOverlayOpen()` says whether the overlay is on the page, and `removePodcastOverlay()` removes it silently.
- The legacy `NotificationsUI` keeps parallel methods, because that page loads no TypeScript module. `_maybeAutoPlayPodcast` is the entry, called by `handleNotificationUpdate`.
- `audio-player.html` posts `playing` and `ended` to its parent, and shows a visible Play button when the browser blocks the start. See [[audio-player-page]].

## Don't
- Don't start a podcast while audio plays. Queue it, and never cut the audio off.
- Don't offer a history reload to the auto-play. Only the live path does.
