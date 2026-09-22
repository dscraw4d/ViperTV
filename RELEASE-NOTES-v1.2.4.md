# ViperTV v1.2.4 — Persistent Indexed Search

ViperTV Search now builds a persistent SQLite search catalog once instead of reconstructing all media, People and technical metadata for every query. SQLite FTS5 is used when available, with weighted title/show/person fields and aliases for years, decades, codecs, HDR, resolution, languages and media types.

The first index build may take a while on a large library, but it is retained in `vipertv.db` across container restarts. Local scans and Plex/Jellyfin/Emby/metadata refreshes queue a background index refresh; searches can continue using the previous committed index while that refresh runs.

Search now shows Indexed Search status and offers a manual Rebuild Search Index button. The v1.2.3 progress page remains in place and will show the one-time index build when necessary. Smart Collections keep the same query syntax and benefit from the materialized index.

This release performs an additive database migration. It does not require a database wipe, Compose-file replacement or storage-path change. The recovery-safe update package intentionally excludes Compose YAML, `.env`, databases, backups and media directories.
