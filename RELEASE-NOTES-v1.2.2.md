# ViperTV v1.2.2 — Smart Global Search

ViperTV Search is now designed for normal human searches first. You no longer need to know that an actor must be written as `actor:` or a year as `year:`.

## Simple searches

Just type what you remember, for example:

- `John Ritter`
- `M*A*S*H` or `MASH`
- `1984`
- `1980s comedy`
- `NBC`
- `Star Trek 1990s`
- `4K HDR`
- `Spanish subtitles`
- `h265 10bit`

ViperTV automatically searches appropriate titles, people, dates, network/genre/tag metadata, artists/albums, ratings, libraries, languages, codecs, resolution, bit depth and dynamic range. Multiple plain words narrow results naturally.

## Better ranking

Exact title, show-title and person matches are ranked above incidental metadata and plot matches. Punctuation-insensitive matching lets searches such as `MASH` find `M*A*S*H`.

## Advanced search is still there

Nothing was removed. Precise queries such as `actor:"John Ritter" AND year:1980-1989`, boolean AND/OR/NOT, parentheses and all v1.2.1 deep metadata fields continue to work. Advanced syntax is now shown as optional help instead of being the default workflow.

## Upgrade safety

There is no v1.2.2 database schema change. Existing channels, Collections, Smart Collections, Playlists, schedules, Plex/Jellyfin/Emby setup and metadata remain intact. The recovery-safe update package does not contain Compose files, `.env`, databases, backups or media folders.
