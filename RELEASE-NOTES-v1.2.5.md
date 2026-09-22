# ViperTV v1.2.5 — Hardware Acceleration Management

ViperTV v1.2.5 expands the existing Intel VAAPI controls into a central hardware-acceleration system for Intel, AMD and NVIDIA GPUs.

## New

- System → Hardware Acceleration dashboard
- Intel/AMD DRM device detection
- VAAPI and Intel QSV readiness detection
- NVIDIA NVENC readiness detection
- Global Auto/Software/VAAPI/QSV/NVENC/Direct profile
- Per-channel hardware override or Use Global Default
- Preferred VAAPI/QSV render-device selection
- One-click real FFmpeg encoder tests
- `/api/hardware/status` diagnostics
- Active stream effective-profile and fallback reporting
- Safe runtime retry in software after hardware initialization failure
- Hardware profile support for songs/images and advanced scheduling wrappers

## Upgrade safety

The database is preserved and no destructive migration is performed. The recovery-safe update intentionally excludes Compose YAML, `.env`, databases, backups and media paths. Keep the working OMV Compose configuration unchanged and rebuild the image after applying the update because the Dockerfile has optional additional VAAPI driver packages.

## NVIDIA note

NVENC requires the Docker host to have the NVIDIA Container Toolkit/runtime configured and to expose NVIDIA devices/driver libraries to the container. ViperTV detects readiness but does not alter the host or Compose file automatically.
