# ViperTV 1.5.0

ViperTV is a self-hosted virtual TV server for turning local media, Plex libraries, Jellyfin/Emby libraries, Pluto TV and direct HLS sources into scheduled IPTV channels with M3U/XMLTV output, browser playback and HDHomeRun-style discovery endpoints.

This public package is sanitized for installation on another user's machine: it contains **no ViperTV database, Plex token, API key, private NAS path, or private LAN address**.


## New in 1.5.0 — Administration, Diagnostics & Setup
- Seven-step first-run Setup Wizard for timezone, storage, sources, hardware, metadata/search, and first channel.
- System Health dashboard with database integrity, disk space, source connectivity probes, FFmpeg/FFprobe, hardware, search-index and active-stream status.
- Live Stream Diagnostics with viewers, source mode/item, effective encoder, hardware fallbacks, sanitized FFmpeg command and per-channel producer restart.
- Background Media Integrity scanner for missing/zero-byte media, missing duration metadata and broken direct-path mappings.
- Cross-source Duplicate Detector and Metadata Repair Queue with source rescan/retry actions.
- Public-safe configuration export/import with automatic pre-import database snapshots.
- Named point-in-time database snapshots with download/restore.
- Multi-user local roles: Admin, Editor and Viewer, plus configurable OIDC default role and SYSOP audit log.
- Update Manager that validates/stages recovery-safe ZIPs, rejects Compose/.env/database payloads, and can overlay a source tree only when an explicit writable `VIPERTV_SOURCE_ROOT` is provided.
- Expanded About/System Info page.
- See `docs/ADMINISTRATION-DIAGNOSTICS-SETUP.md`.

## New in 1.4.0 — Media, Security & Automation Completion
- Folder-level image duration inheritance with nearest-child rules.
- General Remote Streams: FFmpeg-readable URL/file or trusted executable stdout, with Live/VOD behavior and scheduled duration.
- Trakt Lists with automatic Playlist/Collection mirroring and scheduled refresh.
- Optional local administrator login and generic OIDC management authentication.
- JWT-protected IPTV endpoints and streaming-only port gating.
- Executable Python/shell Script Runner with build ID/mode/args/API credentials and bundled dependency-free client.
- Scripted graphics on/off events plus a Graphics Engine Test Bench.
- Relative-date search operators for release/added dates.
- Preserves v1.3.0 Jellyfin/Emby direct paths and reusable FFmpeg Profiles.
- See `docs/MEDIA-SECURITY-AUTOMATION.md`.

## New in 1.3.0 — Direct Media Paths + FFmpeg Profiles
- Jellyfin and Emby can now translate server-side media paths to existing ViperTV container mounts and read the file directly from disk.
- Direct-path playback validates the translated file and automatically falls back to Jellyfin/Emby HTTP streaming when unavailable.
- Added named reusable FFmpeg Profiles with global and per-channel assignment.
- Profiles cover hardware selection, H.264/HEVC/copy video, AAC/AC-3/copy audio, resolution, bitrate, FPS, preset, pixel format, audio sample rate/channels, max-rate and buffer size.
- See `docs/DIRECT-PATHS-FFMPEG-PROFILES.md`.

## New in 1.2.9 — Streams + Graphics + Direct Media Paths
- Prioritized Audio/Subtitle Stream Selector profiles with global/per-channel assignment.
- Rules for language, title, codec, channel count, forced/default, SDH, external status, channel and time-of-day.
- Graphics Engine 2.0 adds subtitle graphics, motion/video overlays, cross-type z-index ordering, timing and richer templates.
- Plex Direct Media Paths translate Plex file paths into existing ViperTV container mounts and fall back to Plex HTTP automatically when a file is unavailable.
- See `docs/STREAMS-GRAPHICS-PLEX-PATHS.md`.

## New in 1.2.8 — Scheduler Automation

ViperTV now adds dedicated **Deco Templates**, prioritized **Playout Templates**, and authenticated **Scripted Scheduling**. Deco Templates schedule presentation/branding changes across a generic day. Playout Templates pair Block Templates with Deco Templates by weekday or exact date, with priority rules for holidays/special programming. Scripted Scheduling exposes an authenticated REST API that external Python, PowerShell, shell, or other HTTP clients can use to atomically replace schedules and assign them to channels. All Scripted endpoints are published automatically in FastAPI's `/docs` and `/openapi.json`. See `docs/SCHEDULER-AUTOMATION.md`.



## New in 1.2.7 — Scheduler Completion

ViperTV now treats **Classic, Block and Sequential scheduling as one complete scheduling stack**. Reusable **Marathons** can rotate content by show, season, artist or album and can be selected directly by Classic Schedules, Block items or Sequential YAML. Advanced Filler is shared across all schedulers with reusable Pre-roll, Mid-roll, Post-roll, Tail and Fallback presets, Count/Duration/Pad modes, chapter-aware mid-roll placement when chapter metadata is available, and exact loop/trim fallback behavior. Blocks and Templates can also be cloned for faster schedule construction. See `docs/SCHEDULER-COMPLETION.md`.

## New in 1.2.0 — Advanced Scheduling & Station Branding

ViperTV now adds **Block Scheduling**, reusable **Decos**, five-role commercial/filler presets (Pre-roll/Mid-roll/Post-roll/Tail/Fallback), reusable image/dynamic-text **Graphics & Branding**, and programmable **Sequential YAML Scheduling**. Classic Schedules remain fully supported. See `docs/ADVANCED-SCHEDULING.md` and `docs/SCHEDULING.md`.

## New in 1.1.46 — Classic Schedules and Playouts

ViperTV now has reusable ErsatzTV-style Classic Schedules and per-channel Playouts, including Dynamic/Fixed starts, Flood/One/Multiple/Duration modes, Collections/Smart Collections/Multi Collections/Playlists/TV shows/seasons as sources, multiple playback orders, fixed-time gap handling, custom EPG titles, filler tails, and playout reset controls. See `docs/SCHEDULING.md`.

Recent releases also added click-through TV/movie metadata pages, Playlists, detailed People pages, exact episode-level actor/director credits, and rich Plex episode metadata sync. See `CHANGELOG.md` for the complete history.

## New in 1.1.39 — search-first Collections

ViperTV collections now use an ErsatzTV-style workflow:

- **Manual Collection** — open **Media → Search**, search or browse (`*`), select individual movies/episodes or whole shows, then **Add To Collection**. You can choose an existing collection or create a new one in the same step.
- **Smart Collection** — refine a media search until it matches what you want, then **Save As Smart Collection**. The saved query is evaluated dynamically after future scans/syncs.
- **Multi Collection** — combine existing manual and Smart Collections into one reusable programming source.

The ViperTV search language supports `AND`, `OR`, `NOT`, parentheses and the fields `title`, `show_title`, `type`, `actor`, `director`, `network`, `genre`, `library_name`, `source`, `year`, `release_date`, `season_number`, `episode_number`, `plot`, and `status`. Example: `type:episode AND actor:"John Ritter" AND year:1980-1989`.

See `docs/COLLECTIONS.md` for the complete beginner workflow and query examples.

## Quick start

### Windows / Docker Desktop

1. Install Docker Desktop and make sure Linux containers are enabled.
2. Extract this ZIP to a permanent folder.
3. Double-click `Start-ViperTV.cmd`.
4. When the build finishes, open `http://localhost:8409`.
5. For other devices on the same LAN, use `http://<this-PC-LAN-IP>:8409`.

### Linux / OpenMediaVault / Docker Engine

```bash
chmod +x install.sh
./install.sh
```

Then open `http://<server-LAN-IP>:8409`.

The first Docker build needs Internet access to download the Python image/packages, FFmpeg dependencies and the browser HLS library.

## Where ViperTV stores things

The public Compose file deliberately uses portable relative folders:

- `./data` — live SQLite database/configuration and normal ViperTV backups.
- `./backups` — independent secondary database backups.
- `./media` — optional local media mount, read-only inside the container at `/media`.
- `.env` — deployment settings such as timezone, port, Pluto region and local media path.

Do **not** include `data/`, `backups/` or a populated `.env` when making a clean redistributable ZIP from an installed copy.

## Existing media on another disk/NAS

Edit `.env` before starting and change:

```text
VIPERTV_MEDIA_DIR=./media
```

Linux example:

```text
VIPERTV_MEDIA_DIR=/mnt/storage/media
```

Windows Docker Desktop example:

```text
VIPERTV_MEDIA_DIR=D:/Media
```

That host folder appears inside ViperTV as `/media` and is mounted read-only. You can also add extra read-only media mounts to `compose.yml`.

## Plex / actor and director metadata

Open **Media Sources → Plex**, add the server URL/token, and run **Sync All Libraries**. ViperTV imports the actor, character and director credits Plex exposes.

For local libraries, ViperTV can import `<actor>` and `<director>` data from `tvshow.nfo` and episode/movie sidecar NFO files. See `docs/PEOPLE-METADATA.md`.

The AI Channel Builder can then handle requests such as:

```text
Make channel 84 called John Ritter 80s with TV starring John Ritter from the 1980s.
```

For a person + decade/year request, TV filtering uses the episode air date rather than only the series premiere year.

## Main features

- Local TV/movie libraries.
- Plex integration and metadata sync.
- Jellyfin / Emby sources.
- Actor, character and director people index.
- AI-style local natural-language Channel Builder (no cloud AI prompt service required).
- Manual channels, schedules, collections, smart collections, filler and cloning/templates.
- Pluto TV discovery/import and guide cache.
- Direct HLS / M3U8 live channels with recursive signed proxying.
- Retro TV historical schedule builder with TVTango/Jina/TVmaze fallback and Music Video filler.
- M3U and XMLTV endpoints for Kodi/IPTV clients.
- Browser Watch pages and guide.
- HDHomeRun-style discovery/lineup endpoints.
- Persistent SQLite data with primary and secondary backup locations.

## IPTV endpoints

After installation, replace `<host>` with the ViperTV server's LAN IP/name:

```text
http://<host>:8409/iptv/channels.m3u
http://<host>:8409/iptv/xmltv.xml
```

## Hardware acceleration

The normal public configuration defaults to software encoding so it starts on the widest range of systems.

Compatible Linux systems with Intel `/dev/dri` can use:

```bash
docker compose -f compose.yml -f compose.intel-vaapi.yml up -d --build
```

or `./start-intel-vaapi.sh`.

## TheTVDB

TheTVDB enrichment is optional. No API key is included. Configure your own key under **System → Metadata Providers** if you want canonical TVDB metadata.

Actor/director imports from Plex/NFO do not require TheTVDB.

## Security

ViperTV 1.3.0 does not include a built-in admin login. It is intended for a trusted LAN. Do not expose port 8409 directly to the public Internet. For remote access, use a VPN or an authenticated HTTPS reverse proxy. See `docs/SECURITY.md`.

## Updating

Read `docs/UPGRADE.md`. The important rule is to keep `data/`, `backups/` and `.env` when replacing application files.

## Included documentation

- `docs/PEOPLE-METADATA.md`
- `docs/OMV.md`
- `docs/SECURITY.md`
- `docs/UPGRADE.md`
- `docs/HARDWARE-ACCELERATION.md`
- `docs/ADVANCED-SCHEDULING.md`
- `docs/SCHEDULER-COMPLETION.md`
- `docs/IMAGES-AND-STREAMING.md`
- `PLUTO-SETUP.txt`
- `RETRO-TV-SETUP.txt`
- `LIVE-IPTV-SETUP.txt`
- `TVDB-SETUP.txt`
- `FEATURE-MATRIX.md`
- `CHANGELOG.md`
- `docs/RELEASE-HISTORY.md`

## Licensing note

This packaging pass does not choose a new software license on the project owner's behalf. Before publishing ViperTV as an open-source project or granting third parties redistribution rights, add the license terms you want. See `LICENSE-NOTICE.txt`.



## v1.2.2 highlights

**Smart Global Search** removes the need to memorize search fields. Type `John Ritter`, `M*A*S*H`, `1984`, `1980s comedy`, `NBC`, `4K HDR`, `Spanish subtitles`, or similar plain-language terms. ViperTV searches titles, People metadata, years, networks, genres, tags, artists, ratings, languages and technical media metadata automatically, then relevance-ranks the matches. Advanced `field:value` syntax remains available when you need exact Smart Collection rules.

## v1.2.1 highlights

Powerful mixed-media Playlists now support Play All and EPG visibility per entry. Media Search adds deep technical metadata fields including writer, ratings, languages, tags, duration, resolution, codecs, bit depth and HDR/dynamic range.

## v1.2.3 highlights

Media Search now displays an in-page progress meter instead of leaving users with only the browser tab loading spinner. ViperTV shows the current search stage, percentage, searchable items checked, total searchable items, and matches found, then opens the results automatically when ranking finishes.
## v1.2.4 highlights

**Persistent Indexed Search** keeps a materialized SQLite/FTS5 search catalog instead of rebuilding all media, People and metadata relationships for every query. The first index build is a one-time/background operation; later searches query the persisted index and container restarts reuse it. Library and metadata syncs queue background refreshes while the existing committed index remains searchable. Search also includes an Indexed Search status card and a manual rebuild button.

## v1.2.6 highlights

**Scheduled Images + Multiple Streaming Modes** makes local JPG/PNG/WebP/BMP/GIF files normal timed programming with configurable default/per-image durations. Images can be selected directly in Classic and Block schedules and used through Playlists, Collections and Sequential YAML. Generated channels now choose between MPEG-TS Sanitized, MPEG-TS Legacy, HLS Segmenter and low-latency HLS Direct while preserving one shared source producer per active channel. See `docs/IMAGES-AND-STREAMING.md`.

## v1.2.5 highlights

**Hardware Acceleration Management** adds a unified System → Hardware Acceleration dashboard for Intel, AMD and NVIDIA encoding. ViperTV detects visible DRM/NVIDIA devices and FFmpeg encoders, provides one-click software/VAAPI/QSV/NVENC tests, supports a Global/Auto default plus per-channel overrides, and automatically retries a programme with software encoding when a hardware encoder fails to initialize. Existing channels keep their explicit profile until changed; new channels follow the global hardware default. ViperTV never rewrites the user's OMV Compose file.



## v1.2.7 highlights

**Scheduler Completion** adds reusable Marathons as first-class programming sources, unifies Advanced Filler across Classic/Block/Sequential schedules, adds chapter-aware mid-roll placement, exact loop-and-trim fallback filler, reusable filler sources beyond Collections, saved Marathon/Filler sources in Sequential YAML, and clone actions for Blocks and Templates.
