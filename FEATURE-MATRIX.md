
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

# ViperTV 1.1.33 feature matrix

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
| Scheduling / playout blocks | Working foundation |
| Filler presets | Working foundation |
| Guide preview | Working — standard grid; Movies red / TV green / YouTube blue in 1.1.26 |
| HDHomeRun-style endpoints | Working |
| Backup/restore UI | Working |
| ErsatzTV-style grouped sidebar | New in 1.1.0 |
| Dedicated media/list/scheduling pages | New in 1.1.0 |
| Native segmented HLS | Compatibility implementation; further refinement possible |

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
