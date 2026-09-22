# Images as Scheduled Media and Streaming Modes

ViperTV v1.2.6 makes local still images first-class timed programming and adds selectable delivery modes for generated channels.

## Images as scheduled media

Open **Media → Images** to manage indexed local images.

Supported local image types are JPG/JPEG, PNG, WebP, BMP and GIF. Images are discovered when their Local library is scanned. ViperTV keeps a stable media record for each indexed image so exact Playlist/Collection selections survive later scans.

### Display duration

The installation-wide default is **10 seconds**. On **Media → Images** you can:

- change the default duration used by newly indexed images;
- optionally apply a new default to every currently indexed image;
- set a different duration for any individual image.

Changing an image duration changes only ViperTV metadata. The source image file is not modified.

### Where images can be scheduled

Local images can be used directly in:

- Classic Schedule items;
- Block Schedule items;
- mixed-media Playlists;
- Manual/Smart/Multi Collections;
- Sequential schedules.

Sequential example:

```yaml
content:
  - key: STATION_ID
    image: "ViperTV Station ID"

sequence:
  - key: HOURLY_ID
    items:
      - content: STATION_ID
```

Exact image choices are exposed directly in the Classic/Block source picker. For extremely large photo libraries, the direct picker is intentionally capped to keep the page responsive; every indexed image remains available through Search, Playlists and Collections.

### Playback behavior

ViperTV turns a scheduled image into a normal H.264/AAC television segment for the selected duration. The image is scaled to fit the channel resolution while preserving its aspect ratio; unused space is letterboxed/pillarboxed. Silent audio is generated so IPTV clients receive a normal A/V transport stream. The configured channel hardware profile may be used when supported, with the normal ViperTV software fallback protections.

## Multiple streaming modes

Streaming mode is configured per generated channel in **Channel Studio** and summarized under **System → Streaming Profiles**. It is independent of the channel's encoder/hardware profile.

### MPEG-TS — Sanitized

Recommended for Kodi and conventional IPTV clients.

ViperTV keeps one shared station producer for the channel, then gives each viewer a lightweight stream-copy/remux sanitizer. This gives a joining client clean MPEG-TS tables/timestamps without creating another source transcode.

M3U URL suffix: `.ts`

### MPEG-TS Legacy — Direct shared feed

Lowest-overhead transport-stream mode. The client attaches directly to the shared station producer.

This removes the per-viewer sanitizer, but some clients are less tolerant of joining a transport stream in the middle of a programme.

M3U URL suffix: `.ts`

### HLS Segmenter — Compatibility

ViperTV creates compatibility-oriented HLS from the existing shared station feed using stream copy/remux only. It targets roughly four-second segments and a larger rolling playlist.

This does **not** launch another Plex/local source transcode.

M3U URL suffix: `.m3u8`

### HLS Direct — Low latency

Low-latency HLS from the same shared station producer, targeting roughly one-second segments and a shorter rolling playlist.

This is useful for clients that prefer HLS but where faster channel startup is more important than conservative segment sizing.

M3U URL suffix: `.m3u8`

## Shared producer rule

All four modes preserve ViperTV's established shared-channel architecture: one expensive source producer/transcode per active generated channel. Delivery-mode remuxing/segmentation happens downstream from that producer.

Do not change the multiple-streaming-mode implementation into one source transcode per viewer.

## Upgrade safety

The v1.2.6 database changes are additive. Existing channels retain their previous `mpegts` or `hls` values. No media files are changed.

Recovery-safe update ZIPs intentionally exclude Compose files, `.env`, databases, backups and media directories.
