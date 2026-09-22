# ViperTV v1.3.0 — Direct Media Paths + FFmpeg Profiles

ViperTV 1.3.0 closes three remaining media/transcoding gaps:

- Jellyfin stream-from-disk/path replacements.
- Emby stream-from-disk/path replacements.
- Named reusable full FFmpeg transcoding profiles.

Jellyfin and Emby path replacements are server-specific and validate the translated container file before playback. Direct-disk playback is preferred only when the file exists; otherwise ViperTV automatically falls back to the media server's HTTP stream.

Reusable FFmpeg profiles can be assigned globally or per channel and cover hardware selection, H.264/HEVC/copy video modes, AAC/AC-3/copy audio modes, resolution, video/audio bitrate, frame rate, preset, pixel format, sample rate, audio channels, max-rate and buffer size.

The existing hardware-acceleration fallback remains authoritative. Filtered programming such as graphics or burned subtitles cannot use video stream-copy; ViperTV safely encodes instead.

Database migration is additive. Recovery-safe update packages exclude Compose files, `.env`, databases, backups, credentials and media.
