# ViperTV v1.5.0 — Administration, Diagnostics & Setup

ViperTV v1.5.0 focuses on day-to-day operation and safer public deployment rather than changing the proven shared-streaming core.

## Highlights
- First-run Setup Wizard
- System Health and source connectivity checks
- Live Stream Diagnostics and per-station restart
- Media Integrity scanner
- Duplicate Detector
- Metadata Repair Queue
- Configuration import/export with pre-import snapshot
- Named database snapshots
- Admin / Editor / Viewer accounts and OIDC default roles
- SYSOP Audit Log
- Recovery-safe Update Manager
- About / System Info

## Upgrade safety
The v1.5.0 database migration is additive. Existing v1.4.0 channels/settings remain intact. The recovery-safe drag-and-drop ZIP contains no Compose YAML, `.env`, database, backups or media.

## Update Manager deployment note
OMV/Docker images are normally immutable. ViperTV therefore does not expose the Docker socket or attempt to rebuild its own container. It can check/validate/stage packages automatically; normal OMV users still perform **Build → Up** after copying the recovery-safe update into the project directory.
