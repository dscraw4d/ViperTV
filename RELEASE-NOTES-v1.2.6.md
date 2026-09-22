# ViperTV v1.2.6 — Scheduled Images + Multiple Streaming Modes

ViperTV v1.2.6 adds two major television-programming capabilities while preserving the v1.2.5 hardware-acceleration and shared-streaming architecture.

## Images are now first-class scheduled media

Local JPG/JPEG, PNG, WebP, BMP and GIF files indexed by a Local library can be programmed as timed channel content.

**Media → Images** provides:

- a global default still-image duration (10 seconds by default);
- an optional apply-to-existing action;
- a duration override for each individual indexed image.

Images can be used directly in Classic Schedules and Blocks, inside mixed Playlists and Collections, and from Sequential YAML with `image: "Title"`.

At playback ViperTV renders the image at the channel resolution while preserving aspect ratio and generates silent audio, producing a normal IPTV-friendly A/V segment. Image timing is metadata only; ViperTV never edits the original picture.

## Four generated-channel streaming modes

Every generated channel can choose its delivery mode in Channel Studio:

- **MPEG-TS — Sanitized:** recommended IPTV/Kodi mode; lightweight per-viewer stream-copy/remux sanitation.
- **MPEG-TS Legacy — Direct shared feed:** minimum overhead; viewer attaches directly to the shared station producer.
- **HLS Segmenter — Compatibility:** compatibility-oriented HLS with roughly 4-second target segments.
- **HLS Direct — Low latency:** low-latency HLS with roughly 1-second target segments.

The main M3U automatically uses `.ts` for MPEG-TS modes and `.m3u8` for HLS modes.

Both HLS modes are downstream copy/remux segmenters. They subscribe to the same shared station producer used by MPEG-TS viewers and **do not create a second source transcode**.

## Upgrade / database safety

- Existing `mpegts` and `hls` channel values remain valid.
- New settings are additive and use the existing database.
- No database reset is required.
- The recovery-safe drag-and-drop update contains no Compose files, `.env`, databases, backups or media directories.

## Validation performed

- Python compile/import.
- Fresh database initialization.
- Existing database/channel mode preservation.
- Local image indexing and stable image media records.
- Default and per-image duration behavior.
- Exact Classic/Block image source expansion.
- Sequential `image:` content resolution.
- Timed still-image FFmpeg playback with video + silent audio.
- MPEG-TS Sanitized output.
- MPEG-TS Legacy output.
- HLS Segmenter manifest and segment playback.
- HLS Direct manifest and segment playback.
- M3U URL selection for all four modes.
- Recovery-safe overlay verification.
