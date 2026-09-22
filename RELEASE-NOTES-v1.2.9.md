# ViperTV v1.2.9 — Streams + Graphics + Direct Media Paths

This release completes three major parity areas without replacing the shared live-channel producer.

## Advanced Audio / Subtitle Stream Selector
- New **System → Audio / Subtitles** management page.
- Reusable selector profiles with a global default and per-channel overrides.
- Independent prioritized Audio and Subtitle rule stacks.
- Match by language, stream title, codec, minimum/maximum audio channels, forced/default flags, SDH/hearing-impaired marker, external subtitle status, channel, and time of day.
- Subtitle actions: Burn, Copy when MPEG-TS compatible, or None.
- Text subtitle codecs that cannot be safely passed through MPEG-TS automatically fall back to burn-in instead of taking the station down.
- Local sidecar subtitle discovery (`.srt`, `.ass`, `.ssa`, `.vtt`, `.sub`).
- Plex Media Part stream metadata is used when available.
- Legacy `none/burn/copy` channel behavior remains the fallback when no advanced profile is assigned.

## Graphics Engine 2.0
- Existing reusable image and dynamic-text graphics remain compatible.
- Added dedicated **Subtitle Graphic** elements using the selected subtitle stream and optional ASS styling.
- Added **Motion / Video Overlay** elements with optional looping.
- True reusable-graphics z-index ordering across image, text, subtitle and motion/video layers.
- Per-element start/end timing remains supported.
- Expanded dynamic templates: channel, programme, show/episode, SxxExx, year, air date, rating, network, artist, album, library, time, date and weekday.
- Existing legacy channel watermark remains supported.

## Plex Stream From Disk / Path Replacements
- New **Plex → Direct Media Paths** manager.
- Per-server prioritized Plex-path → ViperTV-container-path rules.
- Windows-style Plex paths are normalized for Linux container matching.
- Path-boundary-safe prefix translation and one-click test tool.
- When the translated file exists inside the container, ViperTV reads that file directly while continuing to use Plex as the metadata source.
- Missing/unmapped files automatically retain the existing Plex Media Part HTTP path.
- Cached original Plex Part path and resolved direct path are stored only in ViperTV's database; Plex is never modified.
- ViperTV never changes OMV/Docker bind mounts automatically.

## Safety / migration
- Additive SQLite migration only.
- Existing v1.2.8 channels, schedules, playlists, Marathons, Deco/Playout Templates, scripted schedules and settings remain intact.
- Recovery-safe update contains no Compose YAML, `.env`, database, backups, or media directories.
