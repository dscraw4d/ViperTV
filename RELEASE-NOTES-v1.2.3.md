# ViperTV v1.2.3 — Search Progress

ViperTV Search now gives visible feedback while a search is running.

## New

- In-page search progress bar.
- Current stage: preparing catalog, searching media, ranking results, complete.
- Actual items checked / total item count once the catalog is loaded.
- Live matches-found counter.
- Automatic redirect to the finished results.
- Background search jobs so the search page can render immediately instead of appearing frozen.

## Compatibility

No database schema changes are required. Existing channels, media indexes, Collections, Smart Collections, Playlists, schedules, Plex/Jellyfin/Emby configuration and metadata remain intact. The recovery-safe drag-and-drop package does not include Compose files, `.env`, databases, backups or media folders.
