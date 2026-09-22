# ViperTV v1.3.0 — Jellyfin/Emby Direct Paths + Reusable FFmpeg Profiles

## Jellyfin / Emby Direct Media Paths

ViperTV can continue using Jellyfin or Emby for library discovery and metadata while reading the actual media file directly from a path already mounted inside the ViperTV container.

Open **Sources → Direct Media Paths**. Each rule maps a path prefix reported by one Jellyfin/Emby server to a path visible inside ViperTV.

Example:

- Jellyfin reports: `D:\Media\TV\MASH\S02E13.mkv`
- Remote prefix: `D:\Media\TV`
- ViperTV container prefix: `/mnt/share2`
- Direct file: `/mnt/share2/MASH/S02E13.mkv`

A mapping is used only when the translated target is an existing file. If it is missing, ViperTV automatically falls back to that server's `/Videos/{id}/stream` HTTP endpoint. ViperTV never changes Jellyfin/Emby paths and never changes Docker/OMV mounts.

Rules are server-specific, prioritized, boundary-aware, and accept Windows or Unix path separators. **Recheck paths** updates cached direct-path coverage after a library sync or storage change.

## Reusable FFmpeg Profiles

Open **System → FFmpeg Profiles**. A profile is a named complete output recipe that can be used globally or assigned to individual generated channels.

A profile can define:

- hardware path: inherit/global/auto/software/VAAPI/QSV/NVENC/direct
- video mode: H.264, HEVC/H.265, or stream copy when filters allow
- audio mode: AAC, AC-3, or stream copy
- resolution
- video bitrate
- maximum bitrate and rate-control buffer
- frame rate
- encoder preset
- pixel format
- audio bitrate
- sample rate
- channel count

Per-channel assignment takes priority over the global reusable FFmpeg profile. If neither exists, the channel's original v1.2.x resolution/bitrate/FPS/hardware settings remain active.

Hardware availability and software fallback are still managed under **System → Hardware Acceleration**. An FFmpeg profile does not bypass the safe fallback system.

Graphics and burned subtitles require video filtering. If a profile asks for video stream-copy while filters are active, ViperTV encodes that programme instead of issuing an invalid FFmpeg copy/filter combination.

## Update safety

v1.3.0 is an additive database migration. It does not replace the ViperTV database, Compose YAML, `.env`, backups, media, Docker mounts, Plex/Jellyfin/Emby credentials, or private paths.
