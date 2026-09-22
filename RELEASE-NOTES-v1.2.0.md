# ViperTV v1.2.0 Release Notes

Created by Darren “The Viper” Crawford.

ViperTV v1.2.0 is a major scheduling and presentation release built on the proven v1.1.46 Classic Schedule/Playout baseline.

## New

- **Block Scheduling** with reusable fixed-duration Blocks, day-of-week Templates, Decos and per-channel Block Playouts.
- **Commercial / Filler system** with Pre-roll, Mid-roll, Post-roll, Tail and Fallback roles.
- Filler **Count**, **Duration** and **Pad** modes with exact-boundary trimming.
- Configurable multi-break mid-roll insertion for long programmes.
- **Graphics & Branding** with reusable image overlays and dynamic-text overlays.
- Channel graphic scopes: All content, Primary only, or Filler only.
- Graphics attachment for Classic items, Block items/Decos and Sequential schedules.
- **Sequential YAML Scheduling** with reusable content sources, sequences, reset instructions and looping playout instructions.
- Sequential search/Collection/Smart Collection/Multi Collection/Playlist/show/Marathon sources.
- Sequential count/all/duration/pad/wait/sequence controls plus graphics and watermark controls.
- Classic Schedule Items now include a **Commercials / Filler & Graphics** editor.
- EPG/XMLTV understands grouped duration for split programmes such as mid-roll commercial breaks.
- Editing/reordering management for Block items plus edit workflows for Filler presets, Graphics and Decos.

## Upgrade / compatibility

- Database changes are additive. **Do not delete `vipertv.db`.**
- Existing Classic Schedules, Legacy Time Blocks, Collections, Playlists, channels, metadata, Plex/Jellyfin/Emby settings, Pluto and Retro TV configuration are preserved.
- Classic, Block and Sequential reusable playout modes are mutually exclusive per channel; assigning one automatically detaches the other two.
- The shared channel producer, direct Plex Part source path, slow-viewer disconnect behavior, Pluto recursive HLS proxy and Retro TV engine are intentionally preserved.
- Plex universal-transcoder fallback also preserves split-segment offsets and advanced branding.
- `PyYAML` is a new Python dependency. Rebuild the Docker image after copying the update; a container restart alone is not sufficient.

## Mid-roll note

ViperTV v1.2.0 places multiple mid-roll breaks at even intervals through a programme. The current media index does not store chapter/ad-break markers, so chapter-aware break placement is not yet available.

## Install

1. Stop ViperTV.
2. Keep/backup the existing data folder and `vipertv.db`.
3. Drag the contents of `ViperTV-v1.2.0-DRAG-DROP-UPDATE.zip` over the existing ViperTV program folder and replace matching files.
4. Rebuild the Docker/Compose project.
5. Start ViperTV and confirm `/healthz` and the sidebar report `1.2.0`.
6. Explore **Scheduling → Blocks / Templates**, **Scheduling → Sequential**, **Lists → Filler**, and **System → Graphics & Branding**.

See `docs/ADVANCED-SCHEDULING.md` for the complete workflow.
