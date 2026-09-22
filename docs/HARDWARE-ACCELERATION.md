# ViperTV Hardware Acceleration

ViperTV v1.2.5 adds a unified **System → Hardware Acceleration** dashboard.

## Profiles

- **Use Global Default** — per-channel choice that follows the system-wide profile.
- **Auto Detect** — chooses a usable hardware encoder when possible, otherwise software.
- **Software (libx264)** — CPU encoding and the compatibility fallback.
- **VAAPI** — Linux hardware encoding for Intel and AMD GPUs exposed through `/dev/dri`.
- **Intel Quick Sync (QSV)** — alternate Intel hardware encoding path.
- **NVIDIA NVENC** — NVIDIA hardware encoding when NVIDIA device nodes and driver libraries are visible in the container.
- **Direct / Copy** — no video transcode when the source and presentation path permit it.

## OMV / Docker

ViperTV does not rewrite Compose files. Intel and AMD normally require the host to expose `/dev/dri` to the container. NVIDIA requires the NVIDIA Container Toolkit/runtime to be configured on the Docker host and the NVIDIA GPU to be exposed to the ViperTV container.

The supplied Dockerfile retains legacy Intel `i965` VAAPI support and attempts to install newer Intel media and Mesa VAAPI drivers when the Debian base image offers those packages.

## Safe fallback

When automatic software fallback is enabled, a missing hardware prerequisite resolves to software before FFmpeg launches. If a hardware encoder passes detection but still exits during initialization, the shared station producer retries the **same programme** in software rather than advancing the schedule.

## Graphics

Advanced image/text graphics are deliberately rendered through the software-filter path for reliability across GPU vendors. Ordinary video transcoding, Plex direct-Part transcoding, songs and image programming can use the selected hardware profile.

## Diagnostics

The Hardware page includes one-click Software/VAAPI/QSV/NVENC tests, device visibility, FFmpeg encoder readiness, VAAPI output, active stream profile/fallback information, and a JSON status endpoint at `/api/hardware/status`.
