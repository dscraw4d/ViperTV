VIPERTV v1.2.8 — INSTALL / UPDATE NOTES
Created by Darren "The Viper" Crawford

This update contains program/documentation files only. It does NOT contain or replace your database, media, backups, Plex token, .env, private paths, or API keys.

WHAT v1.2.x ADDS
- Block Scheduling with reusable fixed-duration Blocks.
- Day-of-week Block Templates and per-channel Block Playouts.
- Reusable Decos for watermark policy, Block filler, dead-air fallback and graphics.
- Full commercial/filler roles: Pre-roll, Mid-roll, Post-roll, Tail and Fallback.
- Filler modes: Count, Duration and Pad, with exact-boundary trimming.
- Mid-roll commercial breaks with configurable break count and chapter-aware placement when chapter metadata is available.
- Graphics & Branding with image station bugs and dynamic text overlays.
- Channel graphics scopes: All, Primary only and Filler only.
- Graphics on Classic items, Block items/Decos, and Sequential schedules.
- Sequential YAML Scheduling with content sources, sequences, resets and playout instructions.
- Content sources include searches, Collections, Smart/Multi Collections, Playlists, shows, images and reusable Marathons.
- Saved Marathons can group by show/season/artist/album, shuffle groups, and play one/all items per group.
- Advanced Filler sources are reusable across Classic, Block and Sequential schedules, including saved Marathons.
- Fallback filler can loop/trim exactly to a hard schedule boundary.
- Blocks and Block Templates can be cloned.
- Sequential instructions include count/all/duration/padding/waits/sequences, graphics controls and watermark controls.
- Classic Schedule items now have a Commercials / Filler & Graphics editor.
- Classic, Block and Sequential assignments are mutually exclusive per channel.
- Guide/XMLTV support for grouped split programmes such as mid-roll breaks.
- Smart Global Search with mixed-media Playlists and deep technical metadata.
- Persistent SQLite/FTS5 Search Index so repeated searches do not rebuild the whole catalog.
- Search progress, index status, and a manual Rebuild Search Index control.

HOW TO INSTALL
1. Stop ViperTV in OpenMediaVault / Docker / Compose.
2. Back up your ViperTV data folder/database as normal.
3. Drag the CONTENTS of this update ZIP over the existing ViperTV program folder and allow matching files to be replaced.
4. Rebuild the ViperTV Docker/Compose project. A simple container restart is not enough because the application and the new PyYAML dependency are installed at image build time.
5. Start ViperTV.
6. Confirm the sidebar and /healthz show v1.2.8.
7. Open Scheduling -> Marathons, Blocks / Templates, Sequential, Lists -> Filler, and System -> Graphics & Branding.

NO DATABASE RESET IS REQUIRED.
The v1.2.x schema migrations are additive and preserve existing channels, Classic Schedules, Collections, Playlists, Plex/Jellyfin/Emby setup, People metadata, Pluto, Retro TV, backups and media indexes.

The proven shared-channel producer, Plex direct-Part source handling, Pluto recursive HLS proxy and Retro TV engines are preserved.

See docs/SCHEDULER-COMPLETION.md, docs/ADVANCED-SCHEDULING.md and docs/SCHEDULING.md.

NEW IN v1.2.8
--------------
- Scheduling -> Deco Templates
- Scheduling -> Playout Templates
- Scheduling -> Scripted
- Authenticated external scheduler API under /api/v1/scripted/*
- FastAPI interactive API documentation under /docs

