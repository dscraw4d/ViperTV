# v1.2.0 — Advanced Scheduling & Branding

## 1.5.0 — Administration, Diagnostics & Setup
- First-run Setup Wizard.
- System Health, Stream Diagnostics, Media Integrity, Duplicate Detector and Metadata Repair Queue.
- Configuration import/export and named database snapshots.
- Admin/Editor/Viewer roles and audit logging.
- Recovery-safe Update Manager and About/System Info.


- Block Scheduling with Templates, Decos and per-channel Block Playouts.
- Pre/Mid/Post/Tail/Fallback commercial and filler presets with Count/Duration/Pad modes.
- Image and dynamic-text Graphics & Branding.
- Sequential YAML Scheduling with reusable content, sequences, reset and playout instructions.
- Classic-item commercial/graphics attachment and additive database migration.

# ViperTV 1.1.33

## v1.1.39 — search-first Collections

Collections now follow an ErsatzTV-style search workflow. Manual Collections are assembled by selecting search results and adding them to an existing or new Collection. Smart Collections are saved searches and dynamically re-evaluate as media metadata changes. Multi Collections combine manual and Smart Collections. Media Search adds boolean expressions plus actor/director/network/genre/year/library/source filters, exact local/Plex/Jellyfin/Emby item selections, and whole-show selection with `type:show`.







## v1.1.33 — Pluto recursive HLS repair

Pluto Kodi playback now keeps the entire HLS tree behind ViperTV. The root playlist, variant/media playlists, segments, encryption keys and init maps all use signed ViperTV proxy URLs, with Pluto-compatible request headers applied upstream. This fixes the failure pattern where Kodi repeatedly received a valid Pluto root M3U8 but never progressed to child playlist or segment requests.

## v1.1.32 — Retro TV Music Video filler

**Scheduling → Retro TV** can rebuild dated historical network schedules against your existing Plex/local catalog. Enter a date/network and ViperTV can try to import the historical grid from TVTango, or paste a transcribed listing manually as `HH:MM|Program|Episode`. Historical start times are treated as hard wall-clock boundaries.

ViperTV matches exact episodes when episode titles or Plex original-air dates are available, falls back to a show-level match when necessary, and records unresolved listings in **Wanted Programs**. Retro TV now automatically uses every indexed local/Plex library named **Music Videos** as its filler pool. Short programmes are followed by Music Videos until the next historical start time, and completely missing programmes are replaced by Music Videos for their full scheduled slot while remaining visible in Wanted Programs. Long programmes/music videos are cut at the next hard boundary so the following historical show still starts exactly on time. Retro schedules are also emitted in XMLTV and the standard EPG grid.

## v1.1.30 — Manual Live IPTV / M3U8 channels

A new **Media Sources → Live IPTV** page lets you paste a direct HLS/M3U8 stream URL and publish it as a normal ViperTV channel with its own channel number, name, logo and group. Optional User-Agent and Referer headers are supported.

ViperTV does not simply expose the upstream URL. It fetches and rewrites the HLS tree through signed per-channel proxy URLs, including variant manifests, media segments, encryption-key URIs and init-map URIs. This lets optional source headers continue to apply after the root playlist is loaded and prevents the proxy endpoint from being used as an arbitrary unsigned URL fetcher.

Manual live channels are included in the existing Kodi M3U and XMLTV channel list, appear in **System → Guide**, have built-in browser **Watch** pages, and can be tested, edited, enabled/disabled or deleted from the Live IPTV page. Channel-number collision checks cover normal ViperTV channels, imported Pluto channels and other manual live channels.

## v1.1.29 — Pluto native HLS compatibility fix

- Kodi/ IPTV Simple Pluto entries now use a real `.m3u8` ViperTV URL instead of a `.ts` URL that returns HTTP 302.
- ViperTV creates an isolated Pluto session, fetches the Pluto master playlist itself, and returns HLS immediately to the client.
- Child playlist/segment URIs are converted to absolute Pluto CDN URLs, so no FFmpeg relay or redirect loop is required for Kodi.
- Legacy `.ts` Pluto URLs still return an HLS playlist directly for cached clients.
- Multiple Pluto channels can start independently because each playlist open creates its own playback session.

## v1.1.28 — built-in Pluto TV live source

A new **Media Sources → Pluto TV** page discovers Pluto's regional FAST channel lineup directly from Pluto. Canada is the default region. ViperTV creates a persistent Pluto client ID, refreshes session tokens as needed, caches the lineup and 48-hour guide in SQLite, and lets you import individual channels or the whole regional lineup.

Imported Pluto channels are published through ViperTV's existing M3U/XMLTV URLs, appear in **System → Guide**, and have browser **Watch** pages. Kodi/IPTV playback uses ViperTV's stable MPEG-TS endpoint. Multiple viewers of the same Pluto channel share one upstream producer. The default ViperTV number offset is `1000`, so a Pluto channel numbered 100 normally appears as ViperTV channel 1100; this can be changed before importing.

Pluto lineup/guide metadata auto-refreshes every 24 hours by default. Session tokens are refreshed independently when playback starts, so live streams do not depend on a day-old token. Pluto availability remains region-dependent.

## v1.1.26 — colour-coded EPG

**System → Guide** now colour-codes programme blocks by media type: **Movies red**, **TV green**, and **YouTube blue**. A legend appears beside the guide-window controls. The colouring works for both local and Plex-backed media and follows ViperTV's existing YouTube library classification.

## v1.1.24 — concurrent playback stability

The shared-channel core is hardened for simultaneous browser/Kodi playback. One expensive source producer still exists per active channel, but each external MPEG-TS client gets a tiny stream-copy sanitizer that regenerates clean transport tables/continuity and timestamps. Browser HLS consumes the same shared producer. No additional Plex/local source transcode is started per viewer.

Transport failures are no longer interpreted as the end of a programme. If FFmpeg exits early, ViperTV resumes the **same show/movie** at the corresponding offset and leaves the playout cursor unchanged. A channel advances only after the current item's expected runtime is reached. Slow subscribers are disconnected instead of having bytes silently deleted from the middle of their transport stream.

Browser HLS uses a larger rolling segment retention window, atomic segment creation and epoch-based segment numbering. Automatic browser recovery rebuilds only the browser-side HLS client and does not tear down a healthy station. `/api/streams/shared` exposes retry, slow-viewer and programme-advance counters for diagnostics.

## v1.1.22 — Plex shared-stream reliability

Plex-backed stations now resolve the item's documented Plex **Media Part** (`/library/parts/...`) and stream that media into ViperTV's single shared station producer. The normal path no longer depends on Plex's universal-transcoder HLS start endpoint, which could return a response FFmpeg could not parse when multiple ViperTV clients were attached.

Kodi, browser Watch, and other IPTV clients still share one producer per active ViperTV channel. The channel's configured stream profile (Direct, Software, QSV, or Intel VAAPI) is applied by ViperTV to the Plex media Part. The older Plex universal-transcoder path is retained only as a compatibility fallback when an item exposes no Media Part.

`GET /api/streams/shared` now includes the source mode, current item, fallback warning, last FFmpeg return code, and output byte count. A healthy Plex-backed station should normally report `source_mode: plex-direct-part`.


## v1.1.22 — built-in browser channel preview

Clicking **Watch** now opens a ViperTV player page instead of navigating directly to the raw MPEG-TS feed. The player shows Now Playing / Up Next information and streams the current program as browser-compatible fragmented MP4 (H.264/AAC). When the current program ends the page automatically reconnects to the channel for the next program. Kodi/M3U clients continue using the existing MPEG-TS endpoints unchanged.

The preview is served entirely by ViperTV; no external JavaScript player or CDN is required. Local preview media is encoded to 720p H.264/AAC for broad browser compatibility, while Plex preview media requests H.264/AAC from Plex and remuxes it to fragmented MP4.

## v1.1.38 — People metadata and actor/director channels

ViperTV now keeps a persistent **People Metadata** index. Plex metadata sync imports actor, character and director credits that Plex exposes; local scans import `<actor>`/`<director>` data from `tvshow.nfo` and episode/movie sidecar NFO files. Browse or search the index at **Media → People**.

The AI Channel Builder understands people-oriented requests, for example:

- `Make channel 84 called John Ritter 80s with TV starring John Ritter from the 1980s.`
- `Make an 80s TV channel directed by Dave Powers.`
- `Create a channel starring John Ritter.`

For a person + year/decade request, the year is applied to each **episode's air date**, not merely the show's premiere year. This means a series that premiered before 1980 can still contribute its episodes that actually aired from 1980–1989. Actor/director filters are persisted on the channel, copied by channel cloning/templates, shown on the normal Edit Channel page, and can be removed independently of the selected shows.

After upgrading, run **Plex → Sync All Libraries** once to populate actors/directors for existing Plex libraries. For local libraries, run a normal **Scan** so ViperTV can index NFO people metadata.

## v1.1.18 — live TVDB enrichment progress

System → Metadata Providers now includes a live progress dashboard while TV-show enrichment is running. It reports the current show, completed/total shows, percentage, matches, unresolved shows, cached/skipped shows, elapsed time and an estimated time remaining. The panel polls `/api/tvdb/status` once per second and does not reload the whole admin page while the job is active.

## v1.1.17 — TheTVDB canonical TV metadata

ViperTV can now enrich every TV show from TheTVDB v4. Open **System → Metadata Providers**, enter your TheTVDB v4 API key and optional subscriber PIN, click **Save & Test TheTVDB**, then click **Enrich New / Stale Shows**.

For Plex-backed shows, ViperTV first asks Plex for provider GUIDs and uses the `tvdb://...` ID when available. If no TVDB ID is exposed, ViperTV uses a conservative exact title/year search. TheTVDB's `originalNetwork` and series year become the canonical metadata used by Channel Builder and AI Channel Builder.

Metadata priority is: **manual ViperTV override → TheTVDB → Plex/local fallback**. Production-company values from Plex's broad `studio` field are no longer treated as networks. Existing false Plex station values are cleared once during the v1.1.17 migration.

The enrichment cache is stored in `/data/vipertv.db`, survives container recreation, and normally refreshes only metadata older than 30 days. When TheTVDB is configured, the scheduled 72-hour Plex sync is followed by incremental TVDB enrichment.

Metadata provided by TheTVDB. See https://thetvdb.com for attribution/source information.



## v1.1.16 — robust Plex station/network detection

Plex network metadata is now read from both supported shapes: the long-standing show-level `network="NBC"` XML attribute and the newer `Network` child array. TV sync performs a bulk raw-XML compatibility pass, then falls back to individual show XML only for unresolved shows. The Plex page now shows how many distinct networks are cached per TV library, and Sync All reports show/network totals. Run **Plex → Sync All Libraries** once after upgrading.


## v1.1.14 — Plex network metadata fix

Plex TV sync now reads the original broadcaster from Plex's optional `Network` metadata element. If a Plex library listing omits this element, ViperTV fetches the individual show metadata as a compatibility fallback. Run **Plex → Sync All Libraries** once after upgrading to populate NBC/ABC/CBS/etc. for already-cached shows.

## v1.1.12 — AI Channel Builder

**Scheduling → AI Channel Builder** accepts plain-English requests and turns them into normal ViperTV channels. The interpreter runs locally inside ViperTV and does not send prompts or media metadata to a cloud AI service.

Examples:

- `Make me channel 25 called 90s NBC using NBC shows from the 1990s and shuffle them.`
- `Create channel 42 named Frasier and Cheers with Frasier and Cheers.`
- `Make an ABC channel from 1985 to 1995.`
- `Create a YouTube channel called Retro YouTube on channel 70.`
- `Make channel 80 called Music Videos from Plex.`

It understands show titles, original networks, actors, directors, exact years and decades, Plex/local source hints, named libraries, YouTube/You Tube, Music Videos, Game Shows, channel name/number, and shuffle vs sequential playback. The request is previewed before creation, including matched shows and estimated episode count. AI-built channels are ordinary ViperTV channels and remain editable, clonable, schedulable and deletable.

If both Plex and local copies of the same TV show are available and the request does not specify a source, the AI builder prefers Plex to avoid programming duplicate episodes. Genre words such as `sitcom` are currently recognized as advisory text but are not yet a metadata filter.

### v1.1.11 channel management

Scheduling → Channels now supports selecting multiple channels and deleting them together, plus a guarded Reset All Channels action for starting the channel lineup over without touching media libraries or files. Editing a channel shows an **Already Selected** table first so the current TV shows/seasons are obvious before making changes.

## v1.1.11 — Channel reset, bulk delete, and selection summary

ViperTV can now clone a channel directly from **Scheduling → Channels**. The clone wizard can create 1–20 copies at once, choose the first channel number and increment, and automatically name the copies.

A clone copies the source channel's:

- local/Plex show and season selections
- collections
- Jellyfin/Emby selections
- filler/commercial preset
- schedule and schedule items
- logo, watermark, subtitles and offline media
- streaming/transcoding profile
- shuffle/sequential mode

Runtime playout state is intentionally **not** copied. Stable shuffle uses the new channel's unique database id as part of its shuffle seed, so cloned shuffle channels get different episode orders. This is intended for cases such as one Frasier source channel feeding Frasier 2, Frasier 3 and Frasier 4 with different episodes airing at the same time.

## v1.1.6 — Sidebar media totals

The ErsatzTV-style Media sidebar now shows cached live totals beside **TV Shows**, **Movies**, **YouTube**, **Music Videos**, and **Game Shows**. TV and Game Shows are counted by distinct show; Movies, YouTube, and Music Videos count media items. Special libraries remain excluded from ordinary TV/Movie totals.


## v1.1.4 — Game Shows media category

Any local or Plex library whose title contains `Game Shows` (case-insensitive) is automatically classified under **Media → Game Shows** and excluded from the generic TV Shows and Movies catalog pages. No re-scan or Plex re-sync is required.
ViperTV is a durable Docker/OMV virtual-TV server with local media, Plex, Jellyfin/Emby, custom channels, schedules, collections, filler, IPTV/EPG output, HDHomeRun-style endpoints and redundant SQLite backups.

## v1.1.3 — YouTube / You Tube matching

YouTube classification now recognizes both `YouTube` and `You Tube` anywhere in a local or Plex library title, case-insensitively. No rescan or Plex re-sync is required.

## v1.1.2 — Music Videos media category

Any local or Plex library whose title contains `Music Videos` (case-insensitive) is automatically classified under **Media → Music Videos** and excluded from the TV Shows and Movies catalog pages. No re-scan or Plex re-sync is required.


## v1.1.1 — YouTube media category

Any local or Plex library with `YouTube` (or `You Tube`) anywhere in its title (case-insensitive) is now automatically classified as **YouTube** in the Media area. YouTube-named libraries are excluded from the TV Shows and Movies catalogs and appear under the new **Media → YouTube** page. No rescan or re-sync is required.

## v1.1.0 — ErsatzTV-style interface

This release keeps the proven v1.0.2 streaming/database engine and replaces the administration interface with an ErsatzTV Legacy-inspired workflow so existing ErsatzTV users can navigate ViperTV by muscle memory.

### New administration layout

- Permanent grouped left sidebar.
- Media Sources: Local, Plex, Jellyfin / Emby, Pluto TV, Live IPTV.
- Media: Libraries, TV Shows, Movies, YouTube, Music Videos, Game Shows.
- Lists: Collections, Smart Collections, Multi Collections, Filler.
- Scheduling: Channels, Schedules, Playouts, Blocks / Templates.
- System: Streaming Profiles, Guide, Backup & Restore.
- M3U and XMLTV links are always available at the top-right.
- Dense ErsatzTV-style tables, dark forms, green primary actions and compact page headers.
- Mobile sidebar support.

### New browse / management pages

- `/media/local` and `/media/libraries`
- `/media/tv`
- `/media/movies`
- `/media/youtube`
- `/media/music-videos`
- `/channels`
- `/lists/collections`
- `/lists/smart`
- `/lists/multi`
- `/lists/filler`
- `/scheduling/schedules`
- `/scheduling/playouts`
- `/scheduling/blocks`
- `/system/streaming`

Existing v1.0 pages and endpoints remain available for compatibility.

## Upgrade from v1.1.0

1. OMV Compose -> `vipertv` -> **Down**.
2. Replace the files in the existing `vipertv` Compose project with this package.
3. **Do not delete** `ViperTV-Data` or `ViperTV-Backups`.
4. OMV Compose -> `vipertv` -> **Up**.
5. Open `http://<VIPERTV-LAN-IP>:8409`.

The Docker image tag is `vipertv:1.1.38`, so OMV rebuilds the image. No database reset is required; existing channels, Plex metadata, schedules and backups are preserved.

## IPTV / tuner endpoints

- `/iptv/channels.m3u`
- `/iptv/xmltv.xml`
- `/stream/channel/<channel-number>.ts`
- legacy `/stream/<id-or-number>.ts`
- `/hls/<channel-id>/index.m3u8`
- `/discover.json`
- `/lineup.json`

## Persistence

Everything durable remains under `/data`. The supplied OMV Compose maps `/data` to disk 1 and `/backup2` to disk 2. Recreating the Docker container does not remove ViperTV configuration.

## Automatic Channel Builder (v1.1.11)

Open **Scheduling → Channel Builder** to create a channel from TV show metadata instead of manually selecting every show. Filters can use original network, actor, director, a year/range, or combinations of them. Without a People filter the year is the show premiere year; with an actor/director filter it becomes the episode air year. Examples include `NBC`, `1994`, `John Ritter + 1980–1989`, or `directed by Dave Powers + 1980–1989`.

After upgrading, run **Plex → Sync All Libraries** once so existing Plex TV libraries receive show-level network/year metadata. Plex network data is stored separately from production-studio metadata. Local libraries can populate the same fields from `tvshow.nfo`; a normal local Scan is sufficient and unchanged media files are not FFprobed again.

If source metadata is missing or wrong, Channel Builder includes a persistent ViperTV show-metadata override editor.


### Shared concurrent live streaming (v1.1.22)
Each active ViperTV channel now has one station producer. Kodi, the browser player, and other clients fan out from that producer, avoiding redundant hardware/Plex transcodes.


## Low-latency live TV (v1.1.24)
Kodi/IPTV output is tuned for LAN live-TV use: small probe/analyze windows, immediate MPEG-TS flushing, shallow per-client queues, and one shared station producer. Browser Watch uses ~1-second HLS segments with a small live-edge buffer. Defaults can be adjusted with `VIPERTV_LIVE_PROBE_SIZE`, `VIPERTV_LIVE_ANALYZE_US`, `VIPERTV_SHARED_STREAM_QUEUE_CHUNKS`, and `VIPERTV_HLS_SEGMENT_SECONDS`.


## Standard EPG guide (v1.1.25)
System → Guide now uses a standard TV-grid layout with channels fixed on the left and time across the top. Programme tiles span their real scheduled duration, the current programme is highlighted, and a red NOW line marks the live position. Use the 6h/12h/24h/7-day buttons or the ±3-hour controls to move through the schedule.


### Retro TV historical source reliability (v1.1.37)
Retro TV now uses a three-stage automatic lookup: direct TVTango HTML, unauthenticated Jina Reader Markdown for the same public TVTango page, then TVmaze's public no-key daily schedule API. This avoids the `401 Unauthorized` triggered by Reader HTML/raw mode on some deployments. The Reader parser understands TVTango network/logo rows, episode-title lines and wrapped Markdown table cells. TVmaze is deliberately the last automatic fallback because its schedule data represents premiere airings rather than rerun-inclusive TV Guide listings. Manual schedule paste remains available for exact scanned/newspaper schedules.

When Reader Markdown loses an HTML `colspan`, ViperTV opportunistically uses matching TVmaze premiere metadata to restore the historical airtime/runtime (for example, a 10:00–11:00 one-hour drama) without replacing TVTango's rerun rows.

## v1.2.4
- Persistent SQLite/FTS5 Smart Search index.
- Background/debounced index refresh after library and metadata changes.
- Search index status and manual rebuild UI.
- v1.2.3 catalog-search fallback retained.

## v1.2.6

- First-class scheduled local images with configurable display duration.
- Direct image sources for Classic/Block scheduling and Sequential `image:` support.
- Per-channel MPEG-TS Sanitized, MPEG-TS Legacy, HLS Segmenter and HLS Direct delivery modes.
- M3U URLs automatically follow channel delivery mode while all generated modes preserve the shared station producer.



## v1.2.7 — Scheduler Completion

- Added first-class reusable **Marathons**.
- Marathon grouping by Show, Season, Artist or Album.
- Chronological/shuffled item ordering, optional shuffled groups, and play-all vs round-robin group behavior.
- Marathons are selectable by Classic Schedules and Blocks and referenceable from Sequential YAML.
- Unified Advanced Filler sources across Classic, Block and Sequential schedules.
- Filler sources now include libraries, Manual/Smart/Multi Collections, Playlists, shows, seasons, images and saved Marathons.
- Added chapter metadata (`chapters_json`) for local/Plex/Jellyfin/Emby media where available.
- Added chapter-aware Mid-roll placement with automatic even-spacing fallback.
- Added exact loop-and-trim Fallback behavior for hard schedule gaps/dead air.
- Sequential YAML can reference saved filler presets with `filler_preset:`.
- Added Clone actions for Blocks and Block Templates.
- Database migration remains additive; no reset is required.
- Recovery-safe update packaging continues to exclude Compose, `.env`, database, backups and media.


## v1.2.8 — Scheduler Automation

- Added timed reusable Deco Templates.
- Added prioritized weekday/exact-date Playout Templates combining Block + Deco Templates.
- Added authenticated Scripted Scheduling REST/OpenAPI endpoints and first-class Scripted playouts.
- Added atomic external schedule replacement and scheduler-assignment exclusivity.
