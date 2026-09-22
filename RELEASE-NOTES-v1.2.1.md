# ViperTV v1.2.1 — Powerful Playlists + Deep Search

ViperTV v1.2.1 expands programming and discovery without replacing the v1.2.0 scheduling/streaming core.

## Powerful Playlists

Playlists can now mix whole shows, seasons, exact episodes/media items, artists, Collections, movies, Music Videos, Other Videos, songs, images and configured remote HLS streams. Each playlist entry has:

- **Play All** — expand the entire grouped source before advancing, or turn it off to contribute one deterministic item.
- **Show in EPG** — include or hide that entry from Guide/XMLTV output.
- Existing chronological, season/episode, shuffle and random-daily ordering.

Media → Search can add selected results directly to an existing or new Playlist. `type:season` and `type:artist` return grouped selections suitable for one playlist entry.

## Deep Search

New searchable fields include `writer`, `content_rating`/`rating`, `audio_language`, `subtitle_language`, `tag`, `added`, `chapters`, `duration` (minutes), `duration_seconds`, `resolution`, `video_codec`, `audio_codec`, `bit_depth`, `hdr`, `dynamic_range`, `artist`, and `album`. Existing actor/director/network/year/genre/source/library fields remain available.

Examples:

- `writer:"Aaron Sorkin"`
- `rating:TV-14 AND duration:>=45`
- `audio_language:eng AND subtitle_language:spa`
- `resolution:1920x1080 AND video_codec:h264`
- `bit_depth:10 AND hdr:true`
- `chapters:>0`
- `type:song AND artist:"Test Artist"`
- `type:remote_stream`

## Metadata population

Local rescans collect technical metadata with ffprobe and read compatible NFO/container tags. The first rescan after upgrading can therefore take longer on a large existing local library. Plex metadata sync populates the new fields from detailed Plex metadata where available. Jellyfin/Emby sync requests the corresponding rich fields where supported.

## Upgrade safety

The migration is additive and preserves the existing SQLite database. The recovery-safe update contains no Compose YAML, `.env`, database, backup or media files. In OMV, overwrite the application files, then **Build** and **Up** the stack.
