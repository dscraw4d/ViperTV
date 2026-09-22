# ViperTV v1.5.0 — Administration, Diagnostics & Setup

## Setup Wizard
Open **System → Setup Wizard** (or `/setup`). The wizard walks through timezone, durable storage, media sources, hardware acceleration, metadata/search, and the first channel. Existing installations are not forcibly redirected into the wizard.

## System Health
**System → System Health** reports SQLite integrity, database and disk size, active channel producers, search-index status, FFmpeg/FFprobe versions, configured media servers and detected hardware. **Probe Sources** performs short connectivity checks against configured Plex/Jellyfin/Emby servers.

## Stream Diagnostics
**System → Stream Diagnostics** shows active shared station producers, viewer count, source mode/current item, effective encoder, hardware fallbacks, sanitized FFmpeg command and recent error text. A station producer can be restarted without restarting the entire ViperTV container.

## Media Integrity and Duplicates
The Media Integrity scan runs in a background thread and checks indexed local paths, zero-byte files, missing duration metadata, and cached Plex/Jellyfin/Emby direct paths. The Duplicate Detector compares local, Plex and Jellyfin/Emby items using movie/title and show-season-episode identity.

## Metadata Repair Queue
The queue finds incomplete title/show/season/episode/year/duration metadata. Retry actions run the appropriate local scan, Plex sync or Jellyfin/Emby sync when a source-library reference is available.

## Configuration Export / Import
Configuration export intentionally excludes media indexes and secret-bearing settings such as passwords, JWT secrets, Plex tokens and API keys. Import replaces only supported configuration tables and automatically creates a full database snapshot first.

## Snapshots
Named snapshots are full SQLite point-in-time copies stored under the configured backup directory. They can be downloaded or restored from the UI. ViperTV creates additional automatic snapshots before configuration imports and source-overlay updates.

## Users and Roles
Local accounts support `admin`, `editor`, and `viewer` roles. Admin has full access. Editor can manage normal programming but cannot change security/users/update configuration or perform database restore operations. Viewer is read-only. Existing v1.4.0 administrator credentials remain valid. Unknown OIDC users receive the configured OIDC default role.

## Audit Log
The SYSOP Audit Log records login events and management mutations with user, role, HTTP method, path, result and remote address.

## Update Manager
The updater rejects packages containing Compose YAML, `.env`, databases, data/backups directories or path traversal. On ordinary immutable Docker/OMV installs it safely validates and stages updates; copy the staged recovery ZIP over the host project and perform **Build → Up**. ViperTV does not require or request the Docker socket.

For advanced deployments only, mounting the project source tree into the container and setting `VIPERTV_SOURCE_ROOT` enables source-overlay mode. ViperTV creates a database snapshot and a rollback ZIP before overlaying allowed application/documentation files. A Docker rebuild/restart is still required afterward.
