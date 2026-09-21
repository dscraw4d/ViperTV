# ViperTV developer handoff — v1.1.46

## v1.1.39 ErsatzTV-style Collections / saved-search Smart Collections
- New **Media → Search** route: `/media/search`. Search results can be selected and posted to `/media/search/add-to-collection`; a new manual Collection can be created in the same POST.
- Smart Collections are saved searches via `/media/search/save-smart`. Their `collections.rule_json` now normally stores `{"query":"..."}`. `collection_media()` evaluates the query dynamically; the v1.1.38 `field/value/channel_id` rule shape remains as a compatibility fallback.
- Search evaluator supports boolean AND/OR/NOT, parentheses, quoted values, wildcards, `year:YYYY-YYYY`, `release_date` wildcards/ranges, actor/director People metadata, TVDB network/genres, and local/Plex/external library/source metadata.
- Manual collection tokens can now target exact local/Plex/external items as well as whole shows/seasons. `_selection_items()` understands `selection_type=item` and external media.
- `type:show` searches display grouped show results; selecting one stores a whole-show token, while Smart Collections still dynamically expand matching shows to playable episodes.
- Manual edit UI removes selected tokens; Smart edit UI edits/tests the saved query; Multi edit UI combines only manual/smart collections. Rename and delete are available for all collection kinds.
- No schema migration is required; existing collection tables are reused.


## v1.1.38 People metadata / actor-director channel builder
- New tables: `people_credits` and `channel_people_filters`. Both are created idempotently at startup; no database reset is required.
- Plex sync indexes `Role`/`Actor` and `Director` metadata at show level and at episode/movie level when exposed by Plex. Local scan indexes `tvshow.nfo` plus sidecar episode/movie NFO credits.
- **Media → People** (`/media/people`) is the searchable index. Existing installs must run Plex **Sync All Libraries** and/or a local Scan once after upgrade to populate it.
- `interpret_ai_channel_prompt()` recognizes imported person names. Actor cues include `starring`, `staring`, `with`, and actor/cast wording; `directed by`/director wording creates a director filter.
- For people channels, year/decade matching is deliberately done against episode air date via `people_episode_match_counts()`. Ordinary non-person year filters retain the previous show-premiere-year behavior.
- `channel_people_filters` is applied in the middle `channel_media()` wrapper before filler injection. This is intentional: commercials/station IDs remain eligible even when the programme pool is person-filtered.
- People filters are copied by channel clone and channel templates. Edit Channel shows/removes the active filter without deleting the selected shows.
- Explicit person requests with no matching imported person fail closed so a typo or unsynced person cannot accidentally create a broad decade channel.
- Pluto/Retro logic is not changed in v1.1.38.



## v1.1.33 Pluto recursive HLS proxy fix
- Kodi still uses `/stream/pluto/<id>.m3u8`, but the returned master no longer exposes direct Pluto/CDN child URLs. `_pluto_rewrite_playlist()` converts every HLS URI (including `URI=` attributes) into `/stream/pluto/<id>/proxy/<signed-token>`.
- The proxy recursively rewrites child manifests and streams binary HLS assets with Range forwarding. Pluto Origin/Referer/User-Agent headers are applied to every upstream request.
- Tokens are HMAC-signed with a per-install `pluto_proxy_secret` and include the channel ID in the signature so one channel's token cannot be replayed under another channel route.
- Keep isolated Pluto boot/stitcher sessions from v1.1.29. Kodi does not use the older FFmpeg shared Pluto producer; that producer remains only for browser Watch HLS.
- Regression signature from v1.1.32: repeated `Pluto native HLS session ... 200 OK` on the root `.m3u8` with no subsequent child/segment requests.
- Validation used a local two-level HLS fixture requiring Pluto-style Origin/Referer headers; root, child manifest, encrypted-key URI and TS segment all traversed the signed recursive proxy successfully.

## v1.1.32 Retro TV Music Video filler
- Persistent tables: `retro_schedules`, `retro_slots`, `retro_wanted`. Retro schedules link to ordinary `channels` rows so existing M3U/stream routes still work.
- UI: **Scheduling → Retro TV** (`/retro`). Supports best-effort TVTango dated network import plus manual `HH:MM|title|episode` transcription.
- Matching priority: exact show+episode title, Plex original-air-date match, exact movie/title, then show-level fallback. Recheck after Plex/local sync via `/retro/{id}/recheck`.
- Playback: final `_shared_channel_producer` binding dispatches retro channels to `_retro_shared_channel_producer`; ordinary channels continue using the hardened shared producer unchanged. Retro slots are hard wall-clock boundaries in the configured timezone.
- Retro filler is automatic: `_retro_music_video_items()` pools playable local and Plex libraries whose name contains `Music Videos`. Short programmes and completely missing historical slots both use this pool. Missing programmes remain in `retro_wanted` and the EPG keeps the historical title. Long media/music videos are clipped at the next hard slot boundary. A generated slate remains only as a safety fallback when the Music Videos pool is empty.
- `/guide` and `/iptv/xmltv.xml` render the historical wall-clock schedule rather than synthesizing sequential playout. `retro_wanted` unresolved rows are surfaced as the sidebar badge and Wanted Programs table.
- Docker adds `fonts-dejavu-core` for the generated slate and requirements add `beautifulsoup4` for historical HTML parsing.

## v1.1.30 manual Live IPTV source
- Persistent table: `live_streams` (number, name, source M3U8 URL, logo, group, User-Agent, Referer, enabled flag, timestamps). It lives in `/data/vipertv.db` and is covered by existing backups.
- Admin routes: `/live`, `/live/add`, `/live/{id}/edit`, `/live/{id}/test`, `/live/{id}/toggle`, `/live/{id}/delete`.
- Playback route: `/stream/live/{id}.m3u8`. ViperTV fetches the root manifest and rewrites every child URI through `/stream/live/{id}/proxy/{signed-token}`. Tokens are HMAC-signed with a per-install `live_proxy_secret` stored in settings, so callers cannot turn the endpoint into an arbitrary unsigned HTTP proxy.
- Proxy child manifests are recursively rewritten. Binary HLS assets (TS/fMP4 segments, keys, init maps) stream through ViperTV with configured User-Agent/Referer and Range forwarding.
- Browser route: `/watch/live/{id}` uses bundled hls.js and the same stable manifest endpoint.
- Main `/iptv/channels.m3u`, `/iptv/xmltv.xml`, `/guide`, `/channels`, and sidebar include manual live channels. XMLTV emits the channel identity but does not invent programme schedule data; the internal guide displays a truthful continuous `Live Stream` block because no external EPG has been supplied yet.
- Channel-number collision checks span generated ViperTV channels, imported Pluto channels and other manual live streams.
- Validation used a local two-level HLS fixture with variant playlist, TS segments and an encryption-key URI; root and nested manifests rewrote correctly, signed tokens decoded only when valid, M3U/XMLTV/Guide/Watch exposed the manual channel, and proxied segment bytes were returned successfully.


## v1.1.29 Pluto Kodi HLS fix
- Do not redirect Kodi from a `.ts` URL to Pluto HLS. IPTV Simple repeatedly reopened the ViperTV URL instead of settling on the redirected playlist.
- The generated ViperTV M3U now advertises `/stream/pluto/<id>.m3u8`.
- On GET ViperTV creates an isolated Pluto boot/stitcher session, fetches the master playlist server-side, absolutizes child URIs against the final CDN URL, and returns the playlist directly.
- This path has no FFmpeg process and independent channel opens use independent Pluto sessions.
- `/stream/pluto/<id>.ts` remains as compatibility and returns the same HLS master directly (no redirect).

## v1.1.28 Pluto TV source

Pluto is intentionally modeled as a **live external station source**, not as local/Plex media and not as a normal `channels` row. Persistent tables are `pluto_channels` and `pluto_epg`; both live in the normal `/data/vipertv.db` and therefore participate in existing backups. `pluto_channels.imported=1` determines which discovered channels are published. `display_number` is ViperTV's stable lineup number and is assigned with `pluto_number_offset` while avoiding current ViperTV-channel numbers.

The integration talks directly to Pluto's current APIs: `boot.pluto.tv/v4/start`, `service-channels.../v2/guide/channels`, `/categories`, `/timelines`, and the boot-provided `/v2/stitch/hls/channel/{id}/master.m3u8` stitcher. A per-install `pluto_client_id` is generated once and persisted in settings. Boot/JWT state is process-memory only and is refreshed as necessary. Region defaults to `ca`; `PLUTO_REGION_IPS` supplies regional X-Forwarded-For hints and `VIPERTV_PLUTO_X_FORWARDED_FOR` can override them.

Key routes: `/pluto`, `/stream/pluto/{id}.m3u8` (current Kodi/IPTV path), `/stream/pluto/{id}.ts` (legacy no-redirect compatibility), `/watch/pluto/{id}`, `/preview/hls/pluto/...`, `/api/pluto/status`, `/api/pluto/streams`. Main `/iptv/channels.m3u`, `/iptv/xmltv.xml`, `/guide`, and `/channels` now include imported Pluto channels. `periodic_pluto_sync_loop()` refreshes lineup+48h guide on the configurable interval (24h default). Live playback uses one `PLUTO_STREAMS` producer per active Pluto station plus inexpensive per-client remuxers, mirroring the normal shared-channel strategy.

Do not convert Pluto entries into normal ViperTV playout channels: Pluto controls its own live schedule, ad breaks and programme transitions.

## v1.1.26 EPG colour coding

`channel_media()` now attaches non-playback metadata (`library_name`, `media_type`) to item dictionaries. `guide_media_class()` maps YouTube libraries to `youtube`, episodic/show items to `tv`, and movies/unknown standalone video to `movie`. `/guide` emits `epg-youtube`, `epg-tv`, and `epg-movie` classes. Keep these fields metadata-only; they must not alter stream selection or playout ordering.

## v1.1.25 stream-stability hotfix

The v1.1.21/1.1.22 one-producer-per-channel architecture is retained, but the transport layer is hardened. `_shared_channel_producer()` must never advance `current_idx` or persisted schedule cursor merely because FFmpeg exits early; early EOF/error retries the same item with a resumed offset. Each source process is assigned `-output_ts_offset` on one monotonic station timeline and emits `initial_discontinuity` at its boundary.

Do not restore the old QueueFull behaviour that removed the oldest byte chunk. Dropping arbitrary bytes corrupts MPEG-TS/PES. v1.1.25 drains/disconnects only the lagging subscriber while the station keeps running for everyone else. External `/stream/...ts` clients are passed through `_clean_client_ts_stream()`, a cheap `-c copy` FFmpeg remux reading the internal shared station. Browser HLS also reads the internal shared station. Thus multiple viewers do not create multiple Plex/local source transcodes.

Browser HLS segment numbers use epoch numbering, `temp_file`, list size 30 and delete threshold 60. The browser no longer POSTs `/preview/.../restart` automatically for ordinary HLS errors; reattaching to the manifest lets `_start_browser_hls()` restart the backend only if the segmenter is actually dead.

Validation for v1.1.25 included two simultaneous external MPEG-TS clients plus one HLS client on one synthetic channel, with all three attached to a single station producer; both TS captures probed as H.264/AAC, HLS segments returned successfully, no segment 404/503 occurred in the clean run, and `/api/streams/shared` reported 3 viewers with zero slow disconnects/retries. A forced `SIGKILL` of a source FFmpeg incremented `source_retries` while `program_advances` stayed unchanged, proving transport failure no longer jumps to the next programme. A short two-item channel was also run through multiple natural programme boundaries with concurrent viewers.

v1.1.18 adds a live AJAX TheTVDB enrichment progress dashboard with current item, percent, counters, elapsed time and ETA. The `/api/tvdb/status` endpoint remains the source of truth.

## v1.1.22 built-in browser preview

- User-facing player: `GET /watch/channel/{channel_number}`.
- Browser stream: `GET/HEAD /preview/channel/{channel_number}.mp4`.
- `_browser_preview_ffmpeg_command()` emits a finite current-program fragmented MP4.
- Local preview transcodes to 720p H.264/AAC; Plex preview asks Plex for H.264/AAC and remuxes.
- The player reloads the preview URL on `ended`, which re-evaluates wall-clock playout and starts the next current program.
- Existing `/stream/channel/{number}.ts`, M3U, XMLTV and Kodi behavior are intentionally unchanged.
- Validation: Python compile passed; watch page returned expected markup; preview endpoint was probed with ffprobe and detected H.264 1280x720 + AAC.

Current proven backend baseline remains the v1.0.2 stream/database core. v1.1.6 extends the v1.1 ErsatzTV-style UI with automatic YouTube/You Tube, Music Videos, and Game Shows library classification plus cached totals for TV Shows, Movies, YouTube, Music Videos, and Game Shows in the Media sidebar; playback, Plex sync, schedules and persistence remain unchanged.

## UI architecture

`app/main.py::page_shell()` now renders the permanent ErsatzTV Legacy-inspired sidebar and top bar. Active sidebar entries are selected client-side from the current path.

New read-oriented UI helpers/routes:
- Local: `/media/local`, `/media/libraries`
- Catalog: `/media/tv`, `/media/movies`, `/media/youtube`, `/media/music-videos`, `/media/game-shows`
- Channels: `/channels`
- Lists: `/lists/collections`, `/lists/smart`, `/lists/multi`, `/lists/filler`
- Scheduling: `/scheduling/schedules`, `/scheduling/playouts`, `/scheduling/blocks`
- System: `/system/streaming`

Legacy functional endpoints remain in place: `/plex`, `/studio`, `/studio/channel/{id}`, `/guide`, `/sources`, `/maintenance`, channel builder/edit endpoints, IPTV/XMLTV and stream routes.

## Persistence

Do not change the durable model: live SQLite under `/data/vipertv.db`, primary snapshots under `/data/backups`, secondary snapshots under `/backup2`. The container remains disposable.

## Validation performed

- Python compile passed.
- Fresh database startup passed.
- HTTP 200 smoke tests passed for dashboard, all new sidebar pages, Plex, Guide, Backup and channel builder.
- Sidebar was confirmed present on every tested administration page.
- Health endpoint reports version 1.1.8.
- YouTube/You Tube classification smoke-tested for both local and Plex libraries; YouTube libraries are absent from TV/Movies and present under `/media/youtube`.
- Music Videos classification smoke-tested for both local and Plex libraries; Music Videos libraries are absent from TV/Movies and present under `/media/music-videos`.

Next likely work: continue refining individual forms/pages to mirror ErsatzTV workflows even more closely (modal add/edit flows, richer media cards/posters, schedule item editor, playout detail page) without destabilizing the v1.0.2 stream core.

- Game Shows classification smoke-tested for local/Plex naming rules; Game Shows libraries are excluded from TV/Movies and available under `/media/game-shows`.


## v1.1.6
Media sidebar shows cached TV-show and movie totals. Counts exclude YouTube/You Tube, Music Videos and Game Shows title-classified libraries.


## v1.1.6
Media sidebar now shows cached counts for all five catalog categories. YouTube and Music Videos count media items; Game Shows counts distinct shows.


## v1.1.8 channel cloning

- `/channels/{id}/clone` is the user-facing clone wizard.
- `_copy_channel_configuration()` is the canonical channel-copy helper.
- It copies media selections, channel collections, filler, external selections, schedules/items and channel presentation/transcode settings.
- It deliberately does not copy `playout_state`, giving every clone independent runtime progression.
- Stable shuffle already includes `channel_id` in its hash seed; schedule shuffle uses the cloned schedule id, so copies naturally diverge.


## v1.1.11 additions
- Channels page: select-all, per-row checkboxes, Delete Selected, Reset All Channels.
- POST `/channels/delete-selected` and `/channels/reset-all`.
- `_delete_channel_ids` centralizes cleanup of playout state, cross-channel schedule references and channel rows.
- Channel builder edit mode includes an Already Selected summary table.


## v1.1.12 additions — AI Channel Builder
- Sidebar route: `/channels/ai`.
- Preview POST: `/channels/ai/preview`.
- Create POST: `/channels/ai/create`.
- `interpret_ai_channel_prompt()` is the canonical local natural-language interpreter.
- The interpreter reads only ViperTV's own show/library metadata and never calls an external AI service.
- It understands show titles, networks, exact years/ranges/decades, source hints, special media categories, name/number and playback ordering.
- `create_channel_from_ai_plan()` writes ordinary `channels` and `channel_selections` rows, preserving compatibility with the existing channel engine.
- Duplicate title matches prefer Plex over local by default to avoid duplicate programming; explicit `Plex` or `local` wording overrides this.
- Genre terms are currently informational only because genre is not yet part of the show metadata schema.


## v1.1.16 additions

- Fixed Plex original-network ingestion. `Network` is a Plex child element, not a scalar includeFields attribute.
- Section-level TV sync requests optional Network metadata and falls back to `/library/metadata/<ratingKey>` for shows that omit it.
- After upgrade, run Plex Sync All once to backfill existing cached shows.


## v1.1.17 additions — TheTVDB metadata provider

- `/system/metadata` is the metadata-provider UI.
- TheTVDB credentials and bearer-token cache are stored in the existing `settings` table.
- `tvdb_show_metadata` caches provider IDs, `originalNetwork`, year, genres, series status, match method and errors per ViperTV show identity.
- `enrich_tvdb_metadata(force=False)` is the canonical bulk enrichment function. It uses Plex `Guid` TVDB IDs first and exact title/year search only as fallback.
- `auto_channel_show_catalog()` now applies metadata precedence: Manual override → TheTVDB → Plex/local.
- v1.1.17 deliberately removes Plex `studio` as a network fallback. A one-time migration clears cached Plex station values created by the old studio fallback, but manual overrides and TVDB data are untouched.
- The scheduled Plex sync performs incremental TVDB enrichment afterward when TVDB credentials are configured.
- TheTVDB attribution is surfaced in the metadata UI/channel builder.

Validation: Python compile, fresh DB startup, metadata-provider page, Channel Builder/Plex page HTTP smoke tests, TVDB response parser, provider-ID extraction, metadata precedence, mocked bulk enrichment, and one-time polluted-Plex-station migration all passed.



## v1.1.21 concurrent streaming core
- One source FFmpeg/Plex transcode per active channel.
- All MPEG-TS viewers subscribe to the same producer.
- Browser HLS subscribes internally and only performs HLS segmentation (`-c copy`).
- This specifically fixes Watch + Kodi / multiple Kodi clients competing for the old i5-3570 / Intel HD 2500 and Plex transcoder.
- Diagnostics: GET `/api/streams/shared`.


## v1.1.22 Plex direct-Part source
- Shared Plex station producers now resolve `/library/metadata/<id>?includeMedia=1` and use the returned `Media/Part key` as the primary source.
- `_plex_direct_part_source()` caches the resolved media Part and supplies Plex auth headers.
- `_profiled_plex_part_command()` applies the ViperTV channel profile to that direct Plex source.
- `_shared_channel_producer()` reports `source_mode=plex-direct-part`; if no Part can be resolved it falls back to the older universal-transcoder HLS URL and records `source_warning`.
- `/api/streams/shared` now exposes source mode/item, warning, last return code, last item bytes and recent error text.
- Validation: Python compile passed; mocked Plex Media/Part resolution passed; authenticated HTTP media input was transcoded/remuxed by FFmpeg to H.264/AAC MPEG-TS successfully.


### v1.1.25 live latency
The current baseline keeps the v1.1.23 shared-producer stability model but tunes downstream playback for LAN low latency. Do not reintroduce arbitrary queue-byte dropping; slow viewers must still be disconnected cleanly. Kodi uses a copy/remux sanitizer with a 128 KiB / 250 ms probe and immediate TS flushing. Browser HLS targets 1-second segments and ~2 seconds startup media.


### v1.1.25 continuation note
System → Guide was replaced with a conventional horizontally scrolling EPG grid. `/guide` accepts `hours` (1-168, UI presets 6/12/24/168) and `offset` (-168..168 hours). Channel labels and the time header are sticky, programme blocks are calculated from `channel_media()` + `locate_at()`, and Watch links use stable visible channel numbers.


## v1.1.28 Pluto playback
Pluto Kodi/IPTV playback is now direct HLS by HTTP 302 from `/stream/pluto/{id}.ts`; every GET creates an isolated Pluto boot/stitcher session. Do not regress this to a single shared Pluto boot identity. Browser Watch remains server-assisted but its upstream producer also uses an isolated session.


## v1.1.36 Retro TV 403 fix
The TVTango importer no longer sends the ViperTV application User-Agent. It sends normal browser navigation headers and retries www/mail/bare TVTango hostnames on 403/429/503/network failures. Manual import remains the deterministic fallback.

## v1.1.36 Retro TV parser fix
Jina Reader fallback now requests HTML and parses the original TVTango table structure so station rows and colspan-based 30/60 minute programme durations survive. Pluto v1.1.35 short-token proxy remains unchanged.


## v1.1.37 Retro TV automatic-source fallback
- Keep the working Pluto short-token recursive HLS proxy unchanged.
- Retro historical lookup order is now: direct TVTango HTML -> default/unauthenticated Jina Reader Markdown -> TVmaze daily schedule JSON.
- Do not re-enable Jina `X-Respond-With: html`; the user's server received HTTP 401 from that mode.
- `_retro_parse_tvtango_markdown()` handles image/network labels, rich cell text and line-wrapped Reader output.
- `_retro_fetch_tvmaze()` requires no API key and filters by network/date/country, using primetime rows and clock-slot runtimes. It is a last resort because TVmaze does not provide rerun-inclusive TV Guide listings.
- Reader results are optionally enriched with matching TVmaze premiere rows to restore historical airtime and one-hour/multi-slot durations when Markdown conversion loses HTML colspan.
- Tested failure chain: TVTango 403 + Reader 401 -> TVmaze success for mocked 1994-09-22 NBC, producing 20:00 Mad About You, 20:30 Friends, 21:00 Seinfeld, 21:30 Madman of the People, 22:00-23:00 ER.
