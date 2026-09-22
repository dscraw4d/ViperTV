
## Administration / diagnostics (v1.5.0)

- [x] Seven-step first-run Setup Wizard
- [x] System Health dashboard and source connectivity probe
- [x] Live station/FFmpeg diagnostics and producer restart
- [x] Background media-integrity scan
- [x] Cross-source duplicate detector
- [x] Metadata repair queue with source retry
- [x] Configuration export/import excluding media indexes and secrets
- [x] Named database snapshots / rollback points
- [x] Admin / Editor / Viewer local roles
- [x] OIDC default role mapping
- [x] SYSOP audit log
- [x] Recovery-safe update package validation/staging
- [x] Optional source-tree overlay only with explicit writable `VIPERTV_SOURCE_ROOT`
- [x] About / System Info page

- [x] Persistent Indexed Smart Global Search: plain person/title/year/genre/network/technical queries use SQLite FTS5/relevance ranking; advanced field syntax remains optional

## Collections and Smart Collections (v1.1.39)

- [x] Media Search page for collection building
- [x] Select individual episodes/movies and add to manual Collections
- [x] Select whole shows with `type:show`
- [x] Create a manual Collection while adding selected search results
- [x] Save a search as a dynamic Smart Collection
- [x] Boolean AND / OR / NOT and parentheses
- [x] Actor/director/network/genre/year/library/source search fields
- [x] Multi Collections composed from manual + Smart Collections
- [x] Rename/delete/edit/test collection definitions
- [x] Local, Plex and Jellyfin/Emby exact-item collection support

# ViperTV 1.5.0 feature matrix

| Area | Status |
|---|---|
| Durable SQLite outside container | Working |
| Two-location rolling backups | Working |
| Local libraries | Working |
| Plex discovery/sync/playback | Working |
| Jellyfin/Emby discovery/sync | Working |
| Pluto TV regional live source/import | Updated in 1.1.33 — discovery, guide, M3U/XMLTV, Watch plus signed recursive HLS proxy for Kodi playback |
| Manual Live IPTV / M3U8 channels | New in 1.1.30 — add/test/edit/disable/delete, signed recursive HLS proxy, M3U/XMLTV/Guide/Watch |
| Show/season channel picker | Working |
| MPEG-TS / Kodi playback | Working |
| M3U/XMLTV | Working |
| Collections / smart / multi | Working foundation |
| Classic Schedules / Playouts | Complete core workflow — reusable schedules/playouts, fixed/dynamic, One/Multiple/Duration/Flood, group fill, tails, EPG modes, Marathons |
| Block Scheduling / Templates / Decos | Completed through 1.2.7 — reusable Blocks/Templates/Decos, default filler, dead-air fallback, watermark rules, clone actions |
| Sequential YAML Scheduling | Completed through 1.2.7 — reusable content/sequences/reset/playout instructions plus saved Marathon and Filler Preset sources |
| Commercial / filler presets | Expanded in 1.2.7 — Pre/Mid/Post/Tail/Fallback; Count/Duration/Pad; reusable sources; chapter-aware mid-roll; exact loop/trim fallback |
| Graphics / station branding | New in 1.2.0 — image + dynamic text overlays |
| Guide preview | Working — standard grid; Movies red / TV green / YouTube blue in 1.1.26 |
| HDHomeRun-style endpoints | Working |
| Backup/restore UI | Working |
| ErsatzTV-style grouped sidebar | New in 1.1.0 |
| Dedicated media/list/scheduling pages | New in 1.1.0 |
| Native segmented HLS | v1.2.6 — per-channel HLS Segmenter (compatibility) + HLS Direct (low latency), both from shared producer |
| Hardware acceleration management | New in 1.2.5 — Intel/AMD VAAPI, Intel QSV, NVIDIA NVENC detection/tests, global + per-channel profiles, safe software fallback |
| Images as scheduled media | New in 1.2.6 — local images, default/per-image duration, Classic/Block/Playlist/Collection/Sequential support |
| Multiple generated-channel streaming modes | New in 1.2.6 — MPEG-TS Sanitized, MPEG-TS Legacy, HLS Segmenter, HLS Direct |
| Reusable Marathons | New in 1.2.7 — group by show/season/artist/album, shuffle groups, chronological/shuffle items, one-per-group or play-all |
| Deco Templates | New in 1.2.8 — timed reusable Deco changes across the broadcast day, with per-Block explicit Deco override |
| Playout Templates | New in 1.2.8 — prioritized weekday/exact-date rules pairing Block Templates with Deco Templates, assignable per channel |
| Scripted Scheduling | New in 1.2.8 — authenticated REST/OpenAPI scheduler for external Python/PowerShell/shell automation with atomic schedule replacement |

- **YouTube category:** automatic classification for local/Plex libraries containing `YouTube` or `You Tube` in the title, with a dedicated Media browser.

| YouTube / You Tube media category | Updated in 1.1.3 |
| Music Videos media category | New in 1.1.2 |
| Game Shows media category | New in 1.1.4 |

| Sidebar TV/movie totals | New in 1.1.5 |

- Sidebar catalog totals: TV Shows, Movies, YouTube, Music Videos, Game Shows.


## Channel cloning (v1.1.9)

- Multi-copy clone wizard: **Implemented**
- Independent stable shuffle per clone: **Implemented**
- Independent playout cursor per clone: **Implemented**
- Copies schedules/filler/presentation/media selections: **Implemented**


## Channel management (v1.1.11)
- [x] Delete one channel
- [x] Select and delete multiple channels
- [x] Reset all channels while preserving libraries/media/collections
- [x] Pre-change backup before destructive channel operations
- [x] Show current show/season selections while editing a channel

## People metadata and person-filtered channels (v1.1.38)
- [x] Persistent actor / character / director credit index
- [x] Plex show/episode/movie people-credit import during metadata sync
- [x] Local `tvshow.nfo` and sidecar NFO actor/director import
- [x] Media → People searchable browser
- [x] Actor/director filters in AI Channel Builder
- [x] Actor/director filters in automatic Channel Builder
- [x] Person + year/decade filters use episode air date
- [x] People filters persist through clone and channel templates
- [x] Active People filter visible/removable from Edit Channel
- [x] Unknown explicit person requests fail closed rather than broad-match

## AI Channel Builder (v1.1.12)
- [x] Plain-English requests
- [x] Show-title matching
- [x] Original-network matching
- [x] Actor / director matching (v1.1.38)
- [x] Episode-air-year semantics for person channels (v1.1.38)
- [x] Exact year / year range / decade matching
- [x] Plex-only / local-only / named-library hints
- [x] YouTube / Music Videos / Game Shows category requests
- [x] Channel name and number parsing
- [x] Shuffle / sequential parsing
- [x] Preview before creation
- [x] Normal editable ViperTV channel output
- [x] Local-only interpreter; no cloud AI dependency
- [ ] Genre-aware filtering (future metadata expansion)



## TheTVDB metadata provider (v1.1.17)
- [x] v4 API key / optional PIN setup and test
- [x] Bearer token caching / automatic re-authentication
- [x] Plex TVDB GUID matching
- [x] Conservative title/year fallback matching
- [x] Canonical `originalNetwork` import
- [x] Premiere-year import
- [x] Genre/status cache for future smart-channel work
- [x] Background progress and unresolved-match reporting
- [x] 30-day stale refresh policy
- [x] Incremental enrichment after scheduled Plex sync
- [x] Manual override → TVDB → Plex/local precedence
- [x] TheTVDB attribution


## Live TheTVDB enrichment status (v1.1.18)

- Live one-second progress polling without full-page refresh
- Current show and library
- Completed / total and percentage bar
- Matched, unresolved and cached/fresh counters
- Elapsed time and ETA
- Indeterminate preparation state before the work queue is known


## Built-in browser preview (v1.1.22)
- [x] Watch button opens ViperTV player page
- [x] H.264/AAC fragmented MP4 browser preview
- [x] Now Playing / Up Next information
- [x] Automatic next-program reconnect
- [x] Automatic retry after interruption
- [x] Raw MPEG-TS remains unchanged for Kodi/IPTV clients


### Shared concurrent live streaming (v1.1.22)
Each active ViperTV channel now has one station producer. Kodi, the browser player, and other clients fan out from that producer, avoiding redundant hardware/Plex transcodes.


## v1.1.22 streaming reliability
- Plex Media Part direct source: **Implemented**
- Shared Watch + Kodi producer: **Implemented**
- Universal-transcoder fallback only: **Implemented**
- Shared stream source diagnostics: **Implemented**

## Concurrent playback stability (v1.1.24)
- [x] One expensive source producer per active channel
- [x] Multiple simultaneous viewers on the same channel
- [x] Different active channels run independent producers
- [x] Per-viewer MPEG-TS stream-copy sanitization for Kodi/IPTV
- [x] Browser HLS shares the same station producer
- [x] Slow viewer isolation without byte-dropping corruption
- [x] Early source failure retries the same programme instead of advancing
- [x] Monotonic station timestamp timeline across programme/source boundaries
- [x] HLS epoch segment numbering + expanded segment retention

- Standard cable/satellite-style EPG grid with sticky channel column, time ruler, duration-sized programme blocks, NOW marker and direct Watch links.

- **Retro TV Music Video filler:** automatic local/Plex `Music Videos` pool fills commercial gaps and replaces missing historical programmes while preserving Wanted Programs and exact hard start times.

- **Retro historical web fetch resilience (v1.1.37):** browser-compatible TVTango requests with alternate-host retry on 403/429/503.

- **Retro historical fallback chain:** direct TVTango -> unauthenticated Jina Reader Markdown -> TVmaze public daily schedule API.
- **Reader parser:** handles image/network labels, episode-title lines and line-wrapped TVTango Markdown rows.
- **Duration repair:** matching TVmaze premiere rows can restore exact airtime/runtime when Reader Markdown loses TVTango colspan.
- **Known source limitation:** TVmaze fallback is premiere-only, not rerun-inclusive; manual transcription remains the exact fallback for scanned/printed guides.

- **Search progress UI:** background search jobs with real catalog-item progress, match count, stage display and automatic results navigation.
- **Persistent search index:** SQLite/FTS5 materialized catalog, background refresh after media/metadata changes, restart persistence, manual rebuild UI, and v1.2.3 fallback path.


## v1.2.9 Streams / Graphics / Plex Direct Paths
- [x] Prioritized audio stream selector rules
- [x] Prioritized subtitle stream selector rules
- [x] Language / title / codec / channel-count matching
- [x] Forced / default / SDH / external matching
- [x] Per-channel and time-of-day selector rules
- [x] Global selector profile + per-channel overrides
- [x] Subtitle burn / compatible passthrough / disable actions
- [x] Subtitle Graphics
- [x] Motion / video overlays
- [x] Cross-type z-index and per-element timing
- [x] Expanded dynamic text templates
- [x] Plex per-server path replacements
- [x] Windows/Linux Plex path translation
- [x] Existing-file validation + automatic Plex HTTP fallback


## v1.3.0 Jellyfin/Emby Direct Paths + Reusable FFmpeg Profiles
- [x] Jellyfin per-server path replacements
- [x] Emby per-server path replacements
- [x] Windows/Linux path normalization and boundary-aware prefix matching
- [x] Existing-file validation before direct-disk playback
- [x] Automatic Jellyfin/Emby HTTP fallback when a mapped file is unavailable
- [x] Cached direct-path coverage + manual recheck
- [x] Named reusable FFmpeg Profiles
- [x] Global FFmpeg Profile default + per-channel override
- [x] H.264 / HEVC / video-copy modes
- [x] AAC / AC-3 / audio-copy modes
- [x] Resolution / video bitrate / audio bitrate / FPS / preset / pixel format
- [x] Audio sample rate / channel count / max-rate / buffer size
- [x] Hardware-profile integration with existing software fallback
- [x] Safe encode fallback when graphics/subtitle filters prevent stream-copy


## v1.4.0 completion layer
- [x] Folder-level image duration inheritance
- [x] General URL/file and executable-stdout Remote Streams
- [x] Trakt Lists -> managed Playlist/Collection refresh
- [x] Optional local/OIDC management authentication
- [x] JWT-protected IPTV access
- [x] Streaming-only external-port gate
- [x] Executable Script Runner + Python client
- [x] Scripted graphics on/off timeline API
- [x] Graphics Engine Test Bench
- [x] Relative-date search operators
- [x] v1.3.0 Jellyfin/Emby direct paths retained
- [x] v1.3.0 reusable FFmpeg Profiles retained
