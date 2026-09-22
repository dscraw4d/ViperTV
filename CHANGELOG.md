# ViperTV Changelog

## 1.5.0 — Administration, Diagnostics & Setup
- Added seven-step first-run Setup Wizard.
- Added System Health dashboard and source connectivity probes.
- Added live stream diagnostics with sanitized FFmpeg command capture and station-producer restart.
- Added background Media Integrity scanner and cross-source duplicate detection.
- Added Metadata Repair Queue with local/Plex/Jellyfin/Emby retry actions.
- Added safe configuration export/import with automatic pre-import snapshot.
- Added named database snapshots with download/restore.
- Added Admin/Editor/Viewer local accounts plus OIDC default-role mapping.
- Added SYSOP audit log for management mutations and logins.
- Added recovery-safe Update Manager staging/validation and optional explicit writable source-root overlay.
- Added About/System Info page.
- Preserved v1.4.0 security/JWT/remote-stream/Trakt/script-runner behavior and v1.3.0 direct-path/FFmpeg-profile behavior.

# 1.4.0 — Media, Security & Automation Completion

- Added folder-level image duration inheritance with nearest-folder matching.
- Added general Remote Stream definitions for FFmpeg-readable URLs/files and trusted executable stdout.
- Added Trakt List mirroring to managed Playlists or Collections with automatic refresh.
- Added optional local administrator and OIDC management authentication.
- Added signed JWT IPTV access and a streaming-only port gate.
- Added executable scheduler Script Runner and bundled Python API client.
- Added Scripted graphics on/off events and Graphics Test Bench.
- Added relative-date search operators for released/added dates.
- Retains v1.3.0 Jellyfin/Emby direct paths and reusable FFmpeg Profiles.
- Additive migration; no Compose/database replacement.

# 1.3.0 — Direct Media Paths + FFmpeg Profiles

- Added Jellyfin stream-from-disk/path replacement rules with existing-file validation and automatic HTTP fallback.
- Added Emby stream-from-disk/path replacement rules with the same safe fallback behavior.
- Added cached direct-path coverage fields to external media without replacing existing library rows.
- Added named reusable FFmpeg Profiles with global and per-channel assignment.
- FFmpeg Profiles support hardware path, H.264/HEVC/copy video, AAC/AC-3/copy audio, resolution, video/audio bitrate, frame rate, preset, pixel format, sample rate, channel count, max-rate and buffer size.
- Preserved the v1.2.5 hardware availability/software fallback system and v1.2.9 stream-selector/graphics pipeline.
- Video copy automatically falls back to encoding when active filters make stream-copy invalid.
- Additive database migration only; no Compose/database replacement.

# 1.2.9

- Added prioritized Advanced Audio/Subtitle Stream Selector profiles.
- Added stream matching by language/title/codec/channels/forced/default/SDH/external/channel/time.
- Added Graphics Engine 2.0 subtitle graphics and looping motion/video overlays with richer templating and z-index layering.
- Added Plex stream-from-disk path replacement rules with automatic Plex HTTP fallback.
- Additive migration only; no Compose/database replacement.

# 1.2.8 — Scheduler Automation

- Added reusable **Deco Templates** with timed day-part entries and weekday masks.
- Added prioritized **Playout Templates** that pair Block Templates and Deco Templates.
- Playout Template rules can target recurring weekdays or exact dates; exact-date matches are considered before recurring rules and priority resolves competing matches.
- Added per-channel Playout Template assignments.
- Block playback resolves the active Deco Template dynamically as programming advances through the day; an explicit Deco on a Block Template slot still takes precedence.
- Added first-class **Scripted Schedules** and channel assignments.
- Added authenticated `/api/v1/scripted/*` REST endpoints, automatically included in FastAPI `/docs` and `/openapi.json`.
- External programs can search the ViperTV catalog, create schedules, atomically replace schedule items, assign schedules to channels, and reset playout state.
- Scripted schedule items support Smart Search queries, exact indexed-media UIDs, normal ViperTV source kinds, recurring weekday masks, exact dates, count/fill-window modes, EPG visibility and custom EPG titles.
- Scripted Scheduling API tokens are generated locally and stored only in the persistent settings database; update ZIPs never contain the token.
- Added database triggers that keep Classic, Block, Sequential, Playout Template and Scripted assignments mutually exclusive.
- Migration remains additive; existing v1.2.7 schedules/data are preserved.
- Recovery-safe update packaging continues to exclude Compose, `.env`, database, backups and media.

# ViperTV Change Log

## v1.2.7 — Scheduler Completion

- Added reusable **Marathons** under Scheduling → Marathons.
- Marathons can combine multiple Smart Search queries, group by show/season/artist/album, use chronological or shuffled item order, shuffle group order, and either rotate one item per group or play each group completely before advancing.
- Marathons are first-class sources for **Classic Schedules**, **Block Scheduling**, and **Sequential YAML**.
- Sequential YAML can reference saved marathons with `marathon: "Name"` and saved filler presets with `filler_preset: "Name"`.
- Unified Advanced Filler source selection so presets may use Collections, Smart/Multi Collections, Playlists, Shows, Seasons, Images, Marathons or entire local libraries.
- Preserved Pre-roll, Mid-roll, Post-roll, Tail and Fallback roles plus Count/Duration/Pad modes across Classic/Block/Sequential scheduling.
- Added chapter-aware mid-roll placement when source chapter timestamps are available; Auto falls back to even spacing when chapter metadata is absent.
- Added `chapters_json` metadata for Local/Plex/Jellyfin/Emby items so chapter-aware filler can use actual chapter start points after metadata refresh.
- Fallback filler now selects one deterministic item, loops it, and trims the final loop to exactly fill the remaining gap.
- Added reusable filler playback-order control and configurable minimum primary-program duration before mid-roll insertion.
- Added **Clone Block** and **Clone Template** actions for faster Block schedule construction.
- Existing Classic Schedule, Block, Sequential, graphics, streaming, hardware acceleration and persistent search data migrate in place.
- Recovery-safe update packages continue to exclude Compose files, `.env`, databases, backups and media paths.

## v1.2.6 — Scheduled Images + Multiple Streaming Modes

- Added **Media → Images** as a first-class manager for indexed local JPG/JPEG, PNG, WebP, BMP and GIF media.
- Added a configurable global default image duration plus per-image duration overrides; changing duration updates ViperTV metadata only.
- Local images can be selected directly as Classic Schedule and Block Schedule sources, used in mixed-media Playlists/Collections, and referenced by Sequential YAML with `image: "Title"`.
- Scheduled images are rendered as normal timed H.264/AAC television segments with aspect-ratio-preserving scale/pad and silent audio.
- Added four per-channel delivery modes: **MPEG-TS Sanitized**, **MPEG-TS Legacy**, **HLS Segmenter**, and **HLS Direct**.
- M3U output automatically publishes `.ts` or `.m3u8` according to each generated channel's selected delivery mode.
- HLS Segmenter uses compatibility-oriented ~4-second segments; HLS Direct uses low-latency ~1-second segments. Both are stream-copy/remux downstream from the existing shared station producer.
- MPEG-TS Sanitized retains the per-viewer clean remux path; MPEG-TS Legacy attaches directly to the shared station feed for minimum overhead.
- Preserved the one-expensive-source-producer-per-active-channel architecture across every delivery mode.
- Existing channel modes and databases migrate in place. Recovery-safe packages do not include Compose files, `.env`, databases, backups or media paths.
- Added `docs/IMAGES-AND-STREAMING.md`.

## v1.2.5 — Hardware Acceleration Management

- Replaced the Intel-only hardware page with a unified Intel / AMD / NVIDIA hardware acceleration dashboard.
- Detects visible `/dev/dri/renderD*` devices, PCI vendor IDs, NVIDIA device nodes and FFmpeg H.264 hardware encoders.
- Added Global Default profiles: Auto Detect, Software, VAAPI, Intel QSV, NVIDIA NVENC and Direct/Copy.
- Added per-channel `Use Global Default`, Auto, Software, VAAPI, QSV, NVENC and Direct/Copy overrides.
- New channels follow the central Global Default instead of embedding a hardware choice at creation time.
- Added one-click encoder validation tests with the most recent FFmpeg result shown in the Hardware Acceleration page.
- Added `/api/hardware/status` for diagnostics.
- Added preferred VAAPI/QSV render-device selection for multi-GPU systems.
- Added automatic software fallback when a hardware encoder fails prerequisites or exits during initialization. A failed encoder retries the same programme instead of advancing playout state.
- Active shared streams show configured/effective profile and hardware-fallback counts.
- ViperTV's mixed-media image/song playback and v1.2 Block/Sequential command wrappers now accept the central hardware profile system.
- Graphics/branding remains deliberately software-filtered for maximum cross-host reliability; the Hardware page reports the effective profile used by the active station.
- Docker image keeps legacy Intel i965 support and attempts to install newer Intel media and Mesa VAAPI drivers when available. NVIDIA still requires the host's NVIDIA Container Toolkit/runtime.
- Existing databases migrate in place; there is no destructive schema migration.
- Recovery-safe update packages do not include Compose files, `.env`, databases, backups or media paths.

## v1.2.4 — Persistent Indexed Search

- Added a persistent SQLite search index so normal searches no longer rebuild the merged Local/Plex/Jellyfin/Emby/People catalog on every request.
- Uses SQLite FTS5 when available, with weighted title/show/person columns and technical/metadata aliases for Smart Global Search.
- The first index build happens once in the background; subsequent container restarts reuse the existing index.
- Local scans, Plex syncs, Jellyfin/Emby syncs, TheTVDB enrichment, rich Plex credit refreshes and local metadata enrichment mark the index dirty and schedule a background refresh.
- Searches continue using the last committed index while a refresh is being built, so a library sync does not make Search unavailable.
- Added Search → Indexed Search status and a manual Rebuild Search Index button.
- Preserved v1.2.3 search progress; the progress page now reports a one-time index build when required and then queries the persistent index.
- Smart Collections continue using the same simple/advanced query language, but read from indexed payloads after the index is ready.
- Added a safe fallback to the v1.2.3 catalog-search path if FTS/index access fails.
- Existing `vipertv.db` data is migrated in place. No Compose or storage-path changes are required.


## v1.2.3 — Search Progress

- Search requests now start as background jobs instead of holding the page open with only the browser tab spinner.
- Added an in-page progress meter with current stage, percentage, items checked/total and matches found.
- Progress is based on the actual searchable catalog size once catalog preparation completes.
- Search results redirect automatically when ranking is complete.
- Search jobs expire automatically to avoid retaining old result sets indefinitely.
- No database schema change and no Compose changes.


## v1.2.2 — Smart Global Search

- Plain search no longer requires field names: typing a person, show/movie title, year, decade, genre, network, artist, library or technical media term searches the appropriate metadata automatically.
- Person names such as `John Ritter` search actors, directors and writers; show names such as `M*A*S*H` are punctuation-insensitive and match the series title.
- Bare years and decades such as `1984`, `1980s` and `80s` match media air/release years.
- Natural combinations use AND-style narrowing, so searches such as `1980s comedy`, `Star Trek 1990s`, `4K HDR`, `Spanish subtitles` and `h265 10bit` work without special syntax.
- Added user-friendly aliases for common resolutions, HDR/SDR, codecs, bit depth, languages and media types.
- Plain results are relevance-ranked so exact title/person matches appear before incidental metadata/plot matches.
- Advanced `field:value`, AND/OR/NOT and parentheses remain fully supported for precise searches and Smart Collections.
- Search UI now leads with simple examples and moves field syntax into optional Advanced Search Help.
- No database schema change and no rescan is required for the search-engine upgrade itself.

## v1.2.1 — Powerful Playlists + Deep Search

- Expanded Playlists to support mixed granular sources: shows, seasons, exact episodes/items, artists, Collections, movies, music videos, other videos, songs, images and configured remote live streams.
- Added per-playlist-entry **Play All** behavior and **Show in EPG** visibility.
- Media Search can add selected results directly to an existing/new Playlist.
- Added grouped `type:season` and `type:artist` search results for playlist programming.
- Added deep searchable metadata: writer, content rating, audio/subtitle languages, tags, added date, chapters, duration, resolution, video/audio codec, bit depth, HDR/dynamic range, artist and album.
- Local scans now index audio and image media with stable IDs; audio is presented over a TV-safe black video canvas and images receive a default 10-second duration when scheduled.
- Plex and Jellyfin/Emby metadata enrichment populates the new search fields where the source exposes them.
- Existing v1.2.0 databases migrate in place; no data wipe is required.
- Update package intentionally excludes Compose files, `.env`, databases, backups and media paths.


## Advanced scheduling, commercials and station branding
- Added **Block Scheduling** with reusable fixed-duration Blocks, day Templates, per-channel Block Playouts and reusable Decos.
- Added hard Block boundaries so commercials/filler are trimmed rather than delaying the next fixed Block.
- Expanded Filler into **Pre-roll, Mid-roll, Post-roll, Tail and Fallback** presets with Count, Duration and Pad modes plus exact-boundary trimming and configurable mid-roll break counts.
- Added Classic Schedule Item UI for attaching the new commercial/filler presets and graphics without replacing the existing Classic engine.
- Added **Graphics & Branding** with reusable image overlays and dynamic text overlays, channel scopes (all/primary/filler), Block/Deco attachment, and Sequential graphics controls.
- Added **Sequential YAML Scheduling** with reusable content sources, sequences, reset instructions, looping playout instructions, wall-clock padding/waits, marathon content, graphics toggles and watermark control.
- Classic, Block and Sequential playout assignments are mutually exclusive per channel to avoid ambiguous schedules.
- Guide/XMLTV handling now honors grouped guide duration for split programmes such as mid-roll commercial breaks.
- Added additive v1.2 schema tables/columns; existing `vipertv.db` is preserved and migrated in place.
- Added `PyYAML` runtime dependency and `docs/ADVANCED-SCHEDULING.md`.
- Preserved the v1.1.46 shared producer, direct Plex Part path, slow-viewer behavior, Pluto recursive proxy and Retro TV engines.
- Plex universal-transcoder fallback now preserves v1.2 split-segment offsets and advanced branding when the direct Part path is unavailable.

# ViperTV v1.1.46

## ErsatzTV-style Classic Schedules and Playouts
- Rebuilt Scheduling around reusable **Classic Schedules** and per-channel **Playouts** instead of requiring every schedule to live directly on one channel.
- Added schedule-level **Keep Multi-Part Episodes Together**, **Treat Collections As Shows**, **Shuffle Schedule Items**, and **Random Start Point** controls.
- Schedule Items can source Manual Collections, Smart Collections, Multi Collections, Playlists, complete TV Shows, and individual TV Seasons from Local/Plex/Jellyfin/Emby indexes.
- Added **Dynamic** and **Fixed** starts with **Flexible** / **Strict** fixed-start behavior.
- Added playback orders: Chronological, Season/Episode, Shuffle, Random, and Shuffle In Order.
- Added playout modes: Flood, One, Multiple, and Duration, including Multiple Count/Collection Size/Multi-Episode Group/Playlist Item modes.
- Added Ordered/Shuffled group filling, duration-tail Offline/Filler handling, discard-to-fill attempts, custom EPG titles, and Guide Mode.
- Added schedule-item Edit, Up/Down, Delete, schedule Clone/Delete, and per-channel Playout Reset.
- Classic playout output is integrated into the normal channel stream, Guide and XMLTV output. Fixed-time gaps/offline tails use generated black video with silent audio.
- Existing v1.1.45 and older channel-bound schedule blocks are preserved as **Legacy Time Blocks** and remain active whenever no Classic Playout is assigned.
- Added `docs/SCHEDULING.md` with a beginner-friendly workflow and examples.
- No database reset is required.

# ViperTV v1.1.45

## Rich Plex episode metadata
- Plex TV sync now follows the lightweight episode listing with a batched full-metadata pass so per-episode `Role` and `Director` records can be imported.
- Exact guest-star and episode-director credits are stored against the actual episode, fixing cases such as John Ritter appearing only in M*A*S*H S02E13 rather than the entire series.
- Full metadata requests use Plex's multi-rating-key metadata endpoint in batches instead of one request per episode whenever the server supports it.
- Added incremental caching using Plex `updatedAt`; after the first pass, ordinary sync revisits only new or changed episodes.
- Added **Refresh Rich Credits** beside Plex TV libraries to force a complete per-episode credit rebuild after a Plex metadata refresh.
- Added a **Rich Episodes** checked/total count on the Plex page.
- Local episode NFO credits continue to be imported as before.
- No database reset is required; the new cache columns are added automatically.

# ViperTV v1.1.44

## People performance + exact episode credits
- Reworked actor/director detail pages to query the indexed `people_credits` table directly instead of rebuilding the full searchable media catalog on every click.
- Actor/director pages now fetch only the movies and episodes referenced by that person's exact credits.
- Fixed series-level cast/director metadata expanding a guest appearance across every episode of a show.
- TV filmography now lists exact episode-level credits only. Series-level-only credits are displayed as associations without inventing episode appearances.
- Person-created Smart Collections now use exact movie/episode people arrays for `actor_exact:` and `director_exact:` queries.
- Channel people filters now prefer exact episode credits when exact credits exist for that person/show.
- Added people-detail and people/show lookup indexes for large libraries.

# ViperTV v1.1.43

- Fixed actor/director names that could appear clickable but fail to open the person detail page on some installations.
- People links now use a stable numeric credit route (`/media/person/<id>`) instead of depending on a name in the query string.
- Updated People, TV-show metadata and movie metadata links to use the stable route, while keeping the old name-based URL for compatibility with bookmarks.
- Both the actor/director name and **View Person** button now resolve to the same stable person page.
- No database reset or metadata rescan is required. Existing People credits, Collections, Playlists, channels and schedules remain intact.

# ViperTV v1.1.42

- Rebuilt **Media → People** into a click-through actor/director filmography browser.
- Person names are clickable from the People list and from TV-show/movie metadata pages.
- Added a full person detail page showing actor/director roles, imported characters, source types, libraries, years represented in the indexed library, TV-show count, matching episode count, movie count and raw imported-credit count.
- Person pages list all matching movies and group TV credits by series with individual matching episode rows.
- TV episode rows identify whether the match came from an exact **Episode credit** or inherited **Series cast / Series director** metadata, so ViperTV does not disguise series-level source data as episode-specific metadata.
- Added one-click **Create Actor Smart Collection** and **Create Director Smart Collection** actions with editable collection names.
- Person-created Smart Collections use new `actor_exact:` / `director_exact:` search fields so similarly named people cannot leak into the Collection; these Collections remain dynamic across future scans and Plex syncs.
- No database reset is required. Existing People metadata, Collections, Playlists, channels and schedules remain compatible.

# ViperTV v1.1.41

- Extended the v1.1.40 click-through library workflow to **movies**.
- Movie titles in **Media → Libraries** are now clickable for Local, Plex, Jellyfin and Emby libraries.
- Added a full movie metadata page showing source/library, release date/year, runtime, plot/summary, imported actors/characters, directors, file/path or source ID, and artwork references when available.
- Added **Add Movie To Collection** directly from the movie metadata page, including one-step creation of a new manual Collection.
- Added **Add Movie To Playlist** directly from the movie metadata page, including one-step creation of a new Playlist.
- **Media → Movies** now includes Local, Plex, Jellyfin and Emby movies and makes every movie title clickable.
- Playlist help text now explicitly includes movie entries.
- No database reset is required; v1.1.40 Collections, Playlists, channels and schedules remain compatible.

# ViperTV v1.1.40

- Rebuilt **Media → Libraries** as a unified browse view for Local, Plex, Jellyfin and Emby libraries.
- Library rows now have a **Browse** action. TV shows inside a library are clickable.
- Added a full TV-show metadata page showing source/library, network, original year, TVDB genres/status, imported actors/characters, directors, season/episode counts, total runtime and an episode table with dates, runtimes and plots when available.
- Added **Add Entire Show To Collection** directly on the show page. Users can choose an existing manual Collection or create a new one in the same step.
- Added ViperTV **Playlists** as persistent ordered programming lists. A Playlist may contain whole TV-show selections and Collections.
- Added **Lists → Playlists**, playlist create/rename/delete, ordered entry display, move up/down, remove, and collection insertion.
- TV-show pages can add a show to an existing Playlist or create a Playlist on the spot. Each Playlist entry supports Season/Episode, Chronological, Shuffle or Random Daily ordering.
- Channel **Schedule / Presentation** blocks can now use a Playlist as a programming source in addition to Collections. Sequential schedule blocks preserve the Playlist entry order.
- `/media/tv` now includes clickable show names and also includes Jellyfin/Emby TV metadata.
- No database reset is required; Playlist tables are added automatically. Existing v1.1.39 Collections and schedules remain compatible.

# ViperTV v1.1.39

- Reworked manual Collections around a search/select/add workflow inspired by ErsatzTV: search media, tick results, then add them to an existing collection or create a new collection in the same step.
- Added **Media → Search** with AND/OR/NOT, parentheses, quoted values and useful media fields including title, show, type, actor, director, network, genre, library, source, year/date, season/episode, plot and status.
- Smart Collections are now created by **saving a search** rather than entering raw rule JSON. Saved queries are evaluated dynamically whenever the collection is used, so future media scans and Plex syncs automatically change membership.
- Added whole-show selection mode with `type:show`; manual collections can mix entire shows with exact episodes and movies.
- Added exact-item collection tokens for local, Plex and Jellyfin/Emby media.
- Multi Collections now present only manual and Smart Collections as members, matching their intended role as reusable collection groups.
- Added collection rename/delete tools, Smart Collection query editing/testing, manual selection removal, current result counts, and direct Search links throughout the collection UI.
- Existing v1.1.38 collection rows remain compatible; the older field/value Smart Collection rule format is retained as a fallback for previously-created data.
- No database reset is required. Pluto, Retro TV, People metadata and channel playback behavior are otherwise unchanged.

# ViperTV v1.1.38

- Added a persistent **People Metadata** index for actors, character names and directors across Plex and local media.
- Plex metadata sync now imports show-level cast/directors plus episode/movie credits when Plex exposes them; **Plex → Sync All Libraries** repopulates existing libraries after upgrade.
- Local library scans now import people credits from `tvshow.nfo` and episode/movie sidecar NFO files without requiring media re-probing.
- Added **Media → People**, with searchable actor/director coverage and direct links into AI Channel Builder.
- AI Channel Builder now understands requests such as `Make channel 84 called John Ritter 80s with TV starring John Ritter from the 1980s` and `Make an 80s TV channel directed by Dave Powers`.
- Actor/director decade and year filters use **episode air dates**, not only the show's premiere year, so a show that began in the 1970s can contribute only its qualifying 1980s episodes.
- Added actor/director selectors to the metadata Channel Builder. People-filtered channels retain their filter when cloned or saved/applied as a template.
- Channel edit pages now show the active People filter and allow it to be removed without deleting the underlying show selections.
- Person-name requests fail closed when that person is not present in the imported People index instead of silently creating an unrelated broad decade channel.
- Pluto and Retro TV playback/import behavior is otherwise unchanged from the v1.1.37 baseline.

# ViperTV v1.1.37

- Fixed Retro TV automatic imports when TVTango returns 403 and Jina Reader HTML mode returns `401 Unauthorized`.
- Returned Jina Reader fallback to its unauthenticated default Markdown mode and added a tolerant TVTango Markdown parser for image/network labels, rich multi-line cells, episode titles and line-wrapped rows.
- Added a final TVmaze public daily-schedule fallback (no API key) so historical network/date imports can still build automatically when both TVTango and Reader are unavailable.
- TVmaze fallback restores historical airtime/runtime for premiere records and is also used to repair 60/90/120-minute spans that Reader Markdown cannot preserve.
- TVmaze is explicitly treated as a last resort because it tracks premiere airings rather than rerun-inclusive TV Guide listings; manual import remains available for exact scanned/printed schedules.
- Pluto playback code is unchanged from the working v1.1.35/v1.1.36 short-token recursive HLS proxy baseline.

# ViperTV v1.1.36

- Fixed Pluto recursive HLS proxy `400 Bad Request` failures by replacing multi-kilobyte encoded Pluto/JWT URLs with short server-side HMAC tokens.
- Pluto child manifests, segments, keys and init maps remain recursively proxied with the required Pluto request context.
- Retro TV now falls back to Jina Reader when TVTango returns HTTP 403 to the ViperTV server.
- Added parser for TVTango's Reader/Markdown schedule grid while keeping the direct HTML importer and manual importer.

# ViperTV Changelog

## 1.1.34
- Fixed Retro TV web imports returning `HTTP Error 403: Forbidden` from TVTango.
- Historical fetches now use a browser-compatible request profile instead of the ViperTV application user-agent.
- Automatically retries `www.tvtango.com`, `mail.tvtango.com`, and the bare host when TVTango returns 403/429/503 or a connection error.
- Improved source-fetch error messages while preserving the manual historical listing importer as a fallback.

## 1.1.33
- Fixed Pluto channels returning a valid root M3U8 to Kodi but then failing before the client requested child manifests/segments.
- Pluto playback now recursively proxies the entire HLS tree through ViperTV: variant playlists, media playlists, TS/fMP4 segments, keys and init maps.
- Every Pluto child URL is HMAC-signed and bound to its channel ID, preventing the route from becoming an unsigned arbitrary HTTP proxy.
- Pluto browser-like Origin/Referer/User-Agent headers are preserved on every upstream child request, not only the root playlist.
- Kept the fast no-FFmpeg Kodi path and isolated Pluto session creation from v1.1.29.
- `/api/pluto/streams` now reports `recursive-vipertv-hls-proxy` for Kodi playback mode.

## 1.1.32
- Retro TV now automatically uses all playable local and Plex libraries named **Music Videos** as its filler pool.
- Removed the need to select a separate commercial/filler library when creating Retro TV schedules.
- Short historical programmes are followed by Music Videos until the next hard start time.
- Missing historical programmes now play Music Videos for their entire scheduled slot instead of a Coming Soon video, while the original title remains in the EPG and **Wanted Programs**.
- Music Videos are clipped at the next schedule boundary so :00/:30 (and other imported) programme starts remain exact.
- Added Plex Music Videos support to Retro TV filler; local and Plex Music Videos can be mixed in the same automatic pool.
- The generated unavailable slate remains only as a safety fallback when no Music Videos are indexed.

## 1.1.31
- Added **Scheduling → Retro TV** historical schedule reconstruction.
- Best-effort dated TVTango network import plus manual listing transcription fallback.
- Historical programmes are matched against Plex/local media using episode title, Plex air date, movie/title, then show fallback.
- Missing programmes populate **Wanted Programs** and play a generated `COMING SOON / PROGRAM UNAVAILABLE` slate or optional custom missing-program video.
- Exact wall-clock slot boundaries are authoritative: short programmes receive commercial/filler clips; long programmes are clipped so the next show starts on time.
- Retro schedules appear correctly in the standard EPG and XMLTV output.
- Added DejaVu font package and BeautifulSoup parser dependency.

## 1.1.30
- Added **Media Sources → Live IPTV** for manually creating channels from direct HLS/M3U8 stream URLs.
- Manual streams support channel number, name, logo, group, optional User-Agent, optional Referer and enabled/disabled state.
- Added signed recursive HLS proxying so child manifests, media segments, encryption keys and init maps continue through ViperTV with configured source headers.
- Manual live channels are published in the main M3U/XMLTV lineup, standard EPG grid and browser Watch interface.
- Added Test, Edit, Enable/Disable and Delete controls plus cross-source channel-number collision checks.
- Added `LIVE-IPTV-SETUP.txt` and updated developer handoff/feature documentation.

## 1.1.29
- Fixed Kodi repeatedly receiving `302 Found` for Pluto channels and never settling on the HLS stream.
- Pluto M3U entries now use `/stream/pluto/<id>.m3u8`.
- ViperTV fetches the isolated Pluto master playlist and returns it directly with absolute CDN child URLs.
- Retained `.ts` route as no-redirect HLS compatibility endpoint for cached playlists.
- Pluto Kodi path no longer uses FFmpeg or ViperTV shared transport-stream fanout.

## 1.1.28
- Fixed Pluto TV multi-channel playback and slow cold starts for Kodi/IPTV clients.
- Kodi Pluto playback now gets a fresh per-viewer Pluto boot/stitcher session and a 302 redirect directly to Pluto HLS, removing the two nested FFmpeg relay/remux stages.
- Concurrent Pluto viewers/channels no longer reuse one stitcher playback identity.
- HEAD probes remain local and instant, so Kodi does not burn a Pluto session just to test a channel.
- Browser Watch keeps the server-assisted HLS path, but its upstream Pluto producer now also uses an isolated playback session.
- Added direct-play fallback to the server relay if Pluto session bootstrap fails.
- Pluto stream diagnostics report the new direct-HLS/session-isolation mode.

## 1.1.27
- Added a built-in **Pluto TV** media source under Media Sources.
- ViperTV now talks directly to Pluto's current boot, channel, category, timeline and stitcher APIs; no static third-party M3U is required.
- Canada is the default region. Region selection also includes US, UK, Germany, France, Italy, Spain, Brazil, Mexico, Australia and several additional Pluto regions.
- Added a persistent per-install Pluto client ID, automatic session-token refresh and regional channel discovery.
- Added channel selection/import, Import All, Remove Selected/All, stable ViperTV channel-number assignment with a configurable offset, channel logos and categories.
- Imported Pluto channels are added to ViperTV's main M3U/XMLTV output and the standard System → Guide grid.
- Pluto guide data is cached in SQLite from Pluto's real timeline API; movie entries use the red guide style and TV entries use green where metadata identifies the programme type.
- Added built-in browser Watch pages for Pluto channels and low-latency MPEG-TS output for Kodi/IPTV clients.
- Multiple viewers of one Pluto channel share one Pluto/FFmpeg producer, matching ViperTV's one-producer-per-station architecture.
- Added automatic Pluto lineup/guide refresh (24 hours by default, configurable) and `/api/pluto/status` / `/api/pluto/streams` diagnostics.

## 1.1.26
- Added media-type colour coding to the standard EPG grid: Movies are red, TV is green, and YouTube is blue.
- Added an EPG colour legend beside the guide window controls.
- Guide classification reuses ViperTV library metadata so local and Plex YouTube libraries remain identifiable in mixed channels.
- The currently airing programme keeps a neutral yellow NOW accent without obscuring its media-type colour.

## 1.1.25
- Rebuilt System → Guide as a conventional electronic programme guide (EPG) grid.
- Enabled channels are fixed in a sticky left column while programme time runs horizontally across the top.
- Programme blocks are sized to their actual scheduled duration and show title, episode/movie details and start/end time.
- Added 6-hour, 12-hour, 24-hour and 7-day guide windows plus Earlier / Now / Later navigation.
- Added a live NOW marker and highlighting for the programme currently airing.
- Channel rows include a direct Watch link, and the guide remembers horizontal scroll position when returning from Watch.
- Guide remains horizontally/vertically scrollable with sticky channel names and time headers for large channel lineups.

## 1.1.24
- Added a low-latency live-TV path aimed at reducing Kodi/browser buffering while preserving the v1.1.23 concurrency/corruption fixes.
- Kodi/IPTV remux probing reduced from multi-second generic-file defaults to a 128 KiB / 250 ms live probe, with FFmpeg `nobuffer`, low-delay input, zero mux delay and immediate packet flushing.
- Per-viewer live queues are much shallower by default (24 chunks) so ViperTV cannot silently build many seconds of latency behind a slow client. Slow clients still disconnect cleanly instead of receiving corrupt TS.
- Shared station producer now flushes MPEG-TS packets immediately; encoded profiles use a short GOP and x264 zerolatency tuning where applicable for quicker joins and recovery.
- Browser Watch uses 1-second HLS targets, starts after about two seconds of ready media, and keeps a small playback buffer near the live edge instead of intentionally buffering 30-60 seconds.
- `/api/streams/shared` reports the active low-latency profile values for troubleshooting.
- Added environment overrides for live probe size, analyze time, shared queue depth and HLS segment duration.

## 1.1.23
- Fixed corruption when browser Watch and Kodi (or multiple Kodi clients) view channels at the same time.
- External MPEG-TS viewers now receive a lightweight per-client stream-copy remux from the one shared station producer. This regenerates clean PAT/PMT tables and transport continuity without creating another source transcode.
- Shared producer queues no longer drop arbitrary bytes for a lagging viewer. A lagging viewer is disconnected cleanly and may reconnect without corrupting everyone else's feed.
- Source FFmpeg failures/reconnects no longer advance to another show/movie. ViperTV retries the same programme at the appropriate offset and advances playout state only after a genuine programme end.
- Separate source FFmpeg processes are placed on one monotonic station timestamp timeline and mark source boundaries as MPEG-TS discontinuities.
- Browser HLS no longer force-restarts the backend on a late/missing fragment. HLS uses epoch segment numbers, atomic temporary segment writes, a much larger retention window, and a 2-second segment-ready grace period.
- HLS startup now waits for at least six seconds of buffered media rather than assuming exactly three segments, which works with different source keyframe intervals.
- `/api/streams/shared` adds live byte count, retry/slow-viewer/program-advance counters, item offset and station timeline diagnostics.
- Added successful HEAD responses for M3U and XMLTV probes used by Kodi/PVR clients.

## 1.1.22
- Plex-backed shared channels now read Plex's documented `/library/parts/...` media Part URL directly instead of depending on `/video/:/transcode/universal/start.m3u8`.
- This fixes shared producers that showed `Invalid data found when processing input` when Plex returned a non-playable universal-transcoder response.
- The direct Plex Part is authenticated with `X-Plex-Token` headers; the token is not embedded in the media URL.
- ViperTV applies the channel's configured Direct / Software / QSV / VAAPI profile to the Plex Part, so one shared station producer still feeds every viewer.
- Universal-transcoder HLS remains only as a compatibility fallback for unusual Plex items that do not expose a Media Part.
- `/api/streams/shared` now reports `source_mode`, current source item, fallback warning, last FFmpeg return code, and bytes produced for easier diagnostics.
- Fixed Plex/API-key error redaction output so diagnostics no longer display a literal `\1=REDACTED`.

## 1.1.21
- Reworked live playback into one shared producer per channel.
- Kodi, browser Watch, and additional clients now subscribe to the same live MPEG-TS station output instead of launching competing source transcodes.
- Browser HLS now segments the internal shared station feed with stream copy; it no longer creates a second Plex/local source transcode.
- Added a 15-second warm grace period after the last viewer disconnects to smooth reconnects/channel changes.
- Slow viewers cannot block the station; bounded per-viewer queues drop stale chunks rather than stalling everyone.
- Added `/api/streams/shared` diagnostics showing active shared channels, viewer counts, producer state, uptime, and recent error text.
- Scheduled playout cursor is now advanced by the station producer once, rather than once per viewer.

# ViperTV v1.1.20

- Replaced the fragile endless fragmented-MP4 browser preview with real HLS segments.
- Added rolling 2-second HLS buffer, browser HLS recovery, and program-boundary reload.
- Kodi/IPTV MPEG-TS endpoints are unchanged.
- Preview workers are reused per channel and expire after inactivity.

# ViperTV v1.1.20

- Added built-in browser channel player at `/watch/channel/<number>`.
- Dashboard and Channels-page **Watch** buttons now open the player instead of raw MPEG-TS.
- Added browser-compatible fragmented MP4 preview endpoint at `/preview/channel/<number>.mp4`.
- Preview shows **Now Playing**, **Up Next**, and approximate time remaining.
- Player automatically reconnects when the current program ends and retries after stream interruptions.
- Kodi/M3U MPEG-TS routes are unchanged.
- No CDN or external JavaScript player dependency is required.
- Preview stream validation confirmed H.264 video + AAC audio in fragmented MP4.

# ViperTV v1.1.18

- Added a prominent live **TV Show Enrichment Status** panel under System → Metadata Providers.
- Progress updates every second without reloading the whole page.
- Shows current show/library, processed/total count, percentage, matched, unresolved, fresh/cached counts, elapsed time and estimated time remaining.
- Added an indeterminate progress animation while ViperTV authenticates and builds the TV-show work list.
- Enrichment is marked active immediately after clicking the button, so the UI no longer appears idle during preparation.
- The page automatically refreshes once after completion so cached-network/year totals update.
- Existing channels, Plex data, TheTVDB cache, schedules and backups are unchanged.

# ViperTV v1.1.17

- Added **System → Metadata Providers** with TheTVDB v4 API key/PIN configuration and connection testing.
- Added one-click/background TheTVDB enrichment for all local and Plex TV shows.
- Plex TVDB GUIDs are used when available; conservative exact title/year matching is used only as fallback.
- Channel Builder metadata priority is now **Manual override → TheTVDB → Plex/local fallback**.
- Uses TheTVDB series `originalNetwork` directly, preventing production studios from being mistaken for broadcast networks.
- Uses TheTVDB series year/first-air date for premiere-year channel filters.
- Stores TVDB IDs, network, year, genres, status, match method, refresh time, and unresolved-match errors in durable SQLite.
- Normal enrichment refreshes only new/stale metadata (30 days by default); Force Refresh All is available.
- After the scheduled 72-hour Plex sync, ViperTV performs incremental TheTVDB enrichment when configured.
- Removed the Plex `studio` fallback from station detection and clears the old polluted Plex station cache once on upgrade.
- Added provider attribution and TVDB enrichment progress/status.

# ViperTV v1.1.16

- Plex Station/Network detection now falls back to the TV-show `studio` field when Plex omits dedicated `network` metadata.
- Supports `studio` attributes and `Studio` child tags in JSON/XML responses.
- Plex sync log now prints sample resolved stations and raw Plex studio values for diagnosis.
- Existing manual station overrides remain authoritative.

# ViperTV v1.1.16

- Fixed Plex station/network import again using the same raw XML `network` attribute used by mature Plex clients.
- Supports both `network="NBC"` and `<Network tag="NBC">` metadata forms.
- Adds a bulk XML compatibility pass plus individual-show XML fallback for unresolved shows.
- Plex page now shows distinct network counts per TV library.
- Sync All result summary now includes show/network counts.
- Existing cached network/year values are preserved when a transient Plex response omits them.


- Plex libraries now sync automatically every 72 hours at 7:00 AM Pacific time.
- Schedule uses `America/Vancouver`, so 7:00 AM stays local across PDT/PST daylight-saving changes.
- The 72-hour cadence is persisted in SQLite and survives container restarts.
- The Plex page shows the last automatic sync and next scheduled sync.
- Manual Sync Metadata / Sync All controls remain available.

## 1.1.13

- Fixed Plex original-network detection for TV shows.
- Requests Plex's optional `Network` child element instead of incorrectly treating network as a scalar field.
- Falls back to each show's `/library/metadata/<ratingKey>` endpoint when the section listing omits Network metadata.
- A missing/broken network value on one show no longer aborts the full library sync.
- Plex sync status now tracks how many shows and networks were resolved.
- Existing channel, schedule, AI Channel Builder, and persistent database data are preserved.

## 1.1.12

- Added **Scheduling → AI Channel Builder** with local natural-language channel creation.
- Parses channel number/name, shuffle/sequential mode, show titles, original networks, exact years, year ranges and decades.
- Understands Plex/local source hints and named source libraries.
- Understands title-based special categories: YouTube / You Tube, Music Videos and Game Shows.
- Adds a preview step showing the interpreted plan, matched shows/libraries and estimated episode count before creation.
- AI-built channels use ordinary ViperTV channel selections, so all existing Edit/Clone/Schedule/Delete/Kodi functionality continues to work.
- When duplicate TV shows exist in Plex and local sources, Plex is preferred by default unless a source is explicitly requested.
- No cloud AI key is required and prompt text is not sent outside ViperTV.

## 1.1.11

- Added **Scheduling → Channel Builder** for automatically creating channels from TV show metadata.
- Channels can be filtered by **original network** (ABC, NBC, CBS, FOX, etc.), **premiere year**, a year range, or network + year together.
- Added source-library filtering so an automatic channel can use all TV libraries or one specific local/Plex TV library.
- Plex TV sync now imports show-level original network and premiere year metadata in addition to episode metadata.
- Local scans now read show-level `tvshow.nfo` `<studio>` / `<network>` and `<premiered>` / `<year>` fields without re-running FFprobe for unchanged files.
- Added persistent per-show metadata overrides for missing or incorrect network/year data.
- Added network and year summary tables with one-click filter shortcuts.
- Added a Channel Builder button to the main Channels page.
- Automatic channels store ordinary show selections, so they remain editable, clonable, schedulable and compatible with Kodi/M3U/XMLTV like manually-created channels.

## 1.1.10

- Added multi-select checkboxes on Scheduling → Channels.
- Added Delete Selected to remove several channels in one operation with one pre-change backup.
- Added Reset All Channels danger-zone action with double confirmation; libraries, media, collections and backups are preserved.
- Channel deletion now also cleans independent playout state and cross-channel schedule references.
- Channel Edit now shows an Already Selected table listing current source, show/media title and All Seasons / specific season selection before the picker.

## 1.1.9

- Added a visible red **Delete** button to Scheduling → Channels beside Edit, Clone, Schedule and Watch.
- Added a confirmation prompt before deleting a channel.
- Channel deletion creates a pre-change database backup.
- Deleting a channel removes only ViperTV channel configuration; source libraries and media files are not deleted.
- The completion message names the deleted channel.

## 1.1.8

- Added Clone action directly to Scheduling → Channels.
- Added multi-clone wizard supporting 1–20 copies in one operation.
- Added configurable first channel number, number increment, name base and name suffix.
- Clones preserve selections, collections, filler, schedules, external media sources and presentation/transcoding settings.
- Clones intentionally start with fresh playout state.
- Shuffled clones use independent stable shuffle orders through their unique channel ids.
- Schedule items that reference the source channel itself are remapped to the new clone.
- Existing `/studio/channel/{id}/clone` endpoint retained for backward compatibility.

## 1.1.6

- Added cached sidebar totals beside **YouTube**, **Music Videos**, and **Game Shows**.
- YouTube and Music Videos totals count indexed/synced media items across matching local and Plex libraries.
- Game Shows total counts distinct show titles across matching local and Plex libraries, not individual episodes.
- All five Media sidebar totals share the same 60-second cache to keep navigation responsive on large catalogs.

## 1.1.5

- Added live sidebar totals beside **TV Shows** and **Movies**.
- TV Shows counts show-level catalog entries rather than episodes.
- Movie count shows movie items currently synced into the standard Movies catalog.
- YouTube/You Tube, Music Videos, and Game Shows libraries are excluded from both totals.
- Sidebar totals are cached for 60 seconds to keep navigation responsive on large libraries.

## 1.1.4
- Added **Game Shows** as a first-class Media category.
- Any local or Plex library with `Game Shows` in its title is classified automatically (case-insensitive).
- Game Shows libraries are excluded from the generic TV Shows and Movies pages.
- Added **Media → Game Shows** browser with library and episode listings.
- No local re-scan or Plex re-sync is required.


## 1.1.3
- Expanded **YouTube** library detection to recognize both `YouTube` and `You Tube` anywhere in a local or Plex library title (case-insensitive).
- `You Tube` libraries are now excluded from TV Shows and Movies and appear under **Media → YouTube**.
- No rescan or Plex re-sync is required.

## 1.1.2
- Added **Music Videos** as a first-class Media category.
- Any local or Plex library with `Music Videos` in its title is classified automatically (case-insensitive).
- Music Videos libraries are excluded from TV Shows and Movies views.
- Added **Media → Music Videos** browser with library and video listings.
- Existing YouTube category behavior is unchanged.

## 1.1.1
- Added a dedicated **Media → YouTube** category.
- Any local or Plex library with `YouTube` in its title is classified as YouTube case-insensitively.
- YouTube-named libraries are excluded from TV Shows and Movies catalog pages.
- Added a responsive YouTube browser showing matching libraries and up to 1,000 indexed items per source.
- Local Libraries and Plex Libraries now display YouTube classification explicitly.
- Classification is automatic and does not require a media rescan or Plex re-sync.

## 1.1.0
- Rebuilt the web administration UI around an ErsatzTV Legacy-inspired permanent left sidebar and compact top bar.
- Added grouped navigation for Media Sources, Media, Lists, Scheduling and System.
- Added persistent top-right M3U and XMLTV links.
- Added dedicated Channels, Local Libraries, TV Shows, Movies, Collections, Smart Collections, Multi Collections, Filler, Schedules, Playouts, Blocks/Templates and Streaming Profiles pages.
- Added dashboard summary cards and lazy playable-item counts.
- Added responsive/mobile sidebar behavior.
- Channel CRUD and library actions now return to their natural management page instead of the dashboard.
- Kept the v1.0.2 playback, Kodi compatibility, Plex sync, database and backup engine unchanged.

## 1.0.2
- Fixed whole-show/season deduplication collapsing a selected show to one playable item.
- Reduced channel-creation UI stalls on very large catalogs.
- Lazy-loaded dashboard playable counts.
- Added local hierarchy indexes.
- Kept stable channel-number stream URLs and Kodi HEAD support from 1.0.1.

## 1.0.1
- Stable `/stream/channel/<number>.ts` M3U URLs.
- Legacy stream URL fallback.
- Kodi-compatible HTTP HEAD probes.

## v1.1.8
- Added Intel Ivy Bridge / HD 2500 hardware encoding support via VAAPI/i965.
- Container now installs `i965-va-driver`, `vainfo`, `libva2`, and `libva-drm2`.
- Added System → Hardware Acceleration diagnostics.
- Added one-click VAAPI enable/fallback for existing channels.
- New channels default to VAAPI in the supplied OMV Compose file.
- Existing `/dev/dri` passthrough is retained.
- Plex-backed channels continue to use Plex's transcoder; VAAPI applies to ViperTV local-file transcodes.
